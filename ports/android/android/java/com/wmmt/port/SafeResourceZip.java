package com.wmmt.port;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.charset.*;
import java.nio.file.*;
import java.text.Normalizer;
import java.util.*;
import java.util.zip.*;

/** Hostile ordinary ZIP reader: binds every central member to a nonoverlapping local
 * member, rejects special files/encryption/ambiguous paths, and checks decoded CRCs.
 * ZIP64, split archives and APKs are deliberately unsupported.
 * Length/CRC and catalog SHA are checked, but ZipFile does not expose exact inflater
 * EOF/unused-compressed-byte accounting; this is not a canonical DEFLATE proof. */
final class SafeResourceZip implements Closeable {
    static final class Member {
        final String name; final boolean directory; final long length, compressed, crc, offset;
        final int flags, method; final byte[] rawName;
        Member(String n,boolean d,long l,long c,long r,long o,int f,int m,byte[] raw) {
            name=n; directory=d; length=l; compressed=c; crc=r; offset=o; flags=f; method=m; rawName=raw;
        }
    }
    final SortedMap<String,Member> members=new TreeMap<String,Member>();
    private ZipFile zip;
    private static final int MAX_PATH_COMPONENTS=64, MAX_PATH_CHARS=4*1024*1024, MAX_PATH_NODES=65536;
    private static IOException bad() { return new IOException("ZIP 损坏、结构不完整或包含不安全条目"); }
    /** Bound retained names and all index records before insertion, not decoded bytes.
     * Original names/encoded name bytes are also charged, conservatively, so Unicode
     * and multiple index sets cannot silently multiply the accepted character budget. */
    private static final class PathBudget {
        int chars,nodes;
        void reserve(int count,int records) throws IOException {
            if(count>MAX_PATH_CHARS-chars) throw new IOException("ZIP 路径索引字符总量超过安全上限");
            if(records>MAX_PATH_NODES-nodes) throw new IOException("ZIP 路径索引节点总量超过安全上限");
            chars+=count; nodes+=records;
        }
        void add(Set<String> set,String value) throws IOException {
            if(set.contains(value)) return;
            reserve(value.length(),1); set.add(value);
        }
    }
    static void path(String name,boolean directory) throws IOException {
        if(name==null || name.isEmpty() || name.length()>4096 || name.startsWith("/") || name.indexOf('\\')>=0 || name.indexOf(':')>=0) throw bad();
        String value=directory && name.endsWith("/")?name.substring(0,name.length()-1):name;
        if(value.isEmpty() || (!directory && name.endsWith("/"))) throw bad();
        for(int i=0;i<value.length();i++) if(Character.isISOControl(value.charAt(i)) || Character.isSurrogate(value.charAt(i))) throw bad();
        int start=0,components=0;
        for(int i=0;i<=value.length();i++) if(i==value.length() || value.charAt(i)=='/') {
            if(++components>MAX_PATH_COMPONENTS) throw new IOException("ZIP 路径层级超过 64 项安全上限");
            int n=i-start; if(n==0 || (n==1&&value.charAt(start)=='.') || (n==2&&value.charAt(start)=='.'&&value.charAt(start+1)=='.')) throw bad();
            start=i+1;
        }
    }
    private static int u16(byte[] b,int p) { return (b[p]&255)|((b[p+1]&255)<<8); }
    private static long u32(byte[] b,int p) { return (u16(b,p)&65535L)|((long)u16(b,p+2)<<16); }
    private static byte[] at(RandomAccessFile f,long p,int n) throws IOException {
        if(p<0 || n<0 || p>f.length()-n) throw bad(); byte[] b=new byte[n]; f.seek(p); f.readFully(b); return b;
    }
    private static void extra(byte[] data) throws IOException {
        Set<Integer> seen=new HashSet<Integer>(); int p=0;
        while(p<data.length) {
            if(p>data.length-4) throw bad(); int id=u16(data,p),length=u16(data,p+2); p+=4;
            if(length>data.length-p || id==1 || id==0x7075 || id==0x9901 || id==0x000f || id==0x0017) throw bad();
            if(id==0 || !seen.add(id)) throw bad();
            p+=length;
        }
    }
    SafeResourceZip(Path file,int maxEntries,long maxDecoded,ResourceStore.Cancel cancel) throws IOException {
        try(RandomAccessFile f=new RandomAccessFile(file.toFile(),"r")) {
            long size=f.length(); if(size<22 || size>ResourceStore.SOURCE_LIMIT) throw bad();
            byte[] tail=at(f,Math.max(0,size-65557),(int)Math.min(size,65557)); int end=-1;
            for(int i=tail.length-22;i>=0;i--) if(u32(tail,i)==0x06054b50L && i+22+u16(tail,i+20)==tail.length) { end=i; break; }
            if(end<0 || u16(tail,end+4)!=0 || u16(tail,end+6)!=0 || u16(tail,end+8)!=u16(tail,end+10)) throw bad();
            int count=u16(tail,end+10); long central=u32(tail,end+16),centralBytes=u32(tail,end+12),endOffset=size-tail.length+end;
            if(count==65535 || count>maxEntries || central==0xffffffffL || centralBytes>16L*1024*1024 || central+centralBytes!=endOffset) throw bad();
            long p=central,total=0; Set<String> explicit=new HashSet<String>(),files=new HashSet<String>(),dirs=new HashSet<String>(); PathBudget paths=new PathBudget();
            for(int i=0;i<count;i++) {
                ResourceStore.check(cancel); byte[] h=at(f,p,46); if(u32(h,0)!=0x02014b50L) throw bad();
                int flags=u16(h,8),method=u16(h,10),n=u16(h,28),extra=u16(h,30),comment=u16(h,32),made=u16(h,4)>>>8;
                long crc=u32(h,16),compressed=u32(h,20),length=u32(h,24),offset=u32(h,42),attrs=u32(h,38); int unix=(int)(attrs>>>16),type=unix&0170000;
                if(p+46L+n+extra+comment>endOffset || u16(h,34)!=0 || (flags&~0x080e)!=0 || (method!=0&&method!=8) ||
                        compressed==0xffffffffL || length==0xffffffffL || offset>=central || n==0 ||
                        (made==3 && type!=0 && type!=0100000 && type!=0040000) || (attrs&8)!=0) throw bad();
                byte[] raw=at(f,p+46,n); extra(at(f,p+46+n,extra)); String name;
                try { name=((flags&0x800)!=0?StandardCharsets.UTF_8:Charset.forName("Cp437")).newDecoder().onMalformedInput(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(raw)).toString(); }
                catch(CharacterCodingException e) { throw bad(); }
                boolean directory=name.endsWith("/"); path(name,directory);
                if((made==3 && type==0040000 && !directory) || (made==3 && type==0100000 && directory) || ((attrs&16)!=0&&!directory) || (directory&&length!=0)) throw bad();
                String key=Normalizer.normalize(Normalizer.normalize(directory?name.substring(0,name.length()-1):name,Normalizer.Form.NFC).toUpperCase(Locale.ROOT).toLowerCase(Locale.ROOT),Normalizer.Form.NFC);
                if(key.equals("androidmanifest.xml") || key.equals("assets/re3dxplus-data.zip"))
                    throw new IOException("仅支持资源 ZIP，不能导入 APK");
                if(explicit.contains(key) || (directory?files.contains(key):files.contains(key)||dirs.contains(key))) throw bad();
                paths.reserve(name.length()+raw.length,1); // Retained Member name/bytes/node.
                paths.add(explicit,key); paths.add(directory?dirs:files,key);
                int slash=key.indexOf('/'); while(slash>=0) {
                    ResourceStore.check(cancel); String parent=key.substring(0,slash); if(files.contains(parent)) throw bad();
                    paths.add(dirs,parent); slash=key.indexOf('/',slash+1);
                }
                if(length>maxDecoded-total || (length>1024*1024 && length/10000>compressed)) throw new IOException("ZIP 解压大小超限，请选择转换后的资源包"); total+=length;
                if(members.put(name,new Member(name,directory,length,compressed,crc,offset,flags,method,raw))!=null) throw bad();
                p+=46L+n+extra+comment;
            }
            if(p!=endOffset) throw bad();
            List<Member> ordered=new ArrayList<Member>(members.values()); Collections.sort(ordered,(a,b)->Long.compare(a.offset,b.offset)); long next=0;
            for(Member m:ordered) {
                ResourceStore.check(cancel); if(m.offset!=next) throw bad(); byte[] h=at(f,m.offset,30);
                if(u32(h,0)!=0x04034b50L || u16(h,6)!=m.flags || u16(h,8)!=m.method) throw bad();
                int n=u16(h,26),extra=u16(h,28); if(!Arrays.equals(m.rawName,at(f,m.offset+30,n))) throw bad();
                extra(at(f,m.offset+30+n,extra));
                long localCrc=u32(h,14),localCompressed=u32(h,18),localLength=u32(h,22); boolean descriptor=(m.flags&8)!=0;
                if(descriptor?((localCrc!=0&&localCrc!=m.crc)||(localCompressed!=0&&localCompressed!=m.compressed)||(localLength!=0&&localLength!=m.length)):
                        localCrc!=m.crc||localCompressed!=m.compressed||localLength!=m.length) throw bad();
                next=m.offset+30L+n+extra+m.compressed; if(next>central) throw bad();
                if(descriptor) { byte[] d=at(f,next,12); if(u32(d,0)==0x08074b50L) { next+=4; d=at(f,next,12); }
                    if(u32(d,0)!=m.crc || u32(d,4)!=m.compressed || u32(d,8)!=m.length) throw bad(); next+=12; }
                if(next>central) throw bad();
            }
            if(next!=central) throw bad();
        } catch(IllegalArgumentException e) { throw bad(); }
        try { zip=new ZipFile(file.toFile(),Charset.forName("Cp437")); }
        catch(IllegalArgumentException e) { throw bad(); }
        if(zip.size()!=members.size()) { zip.close(); throw bad(); }
    }
    /** Check the decoded length and CRC for each consumed resource member. */
    String consume(Member member,OutputStream output,ResourceStore.Cancel cancel,ResourceStore.Progress progress,String stage) throws IOException {
        ZipEntry entry=zip.getEntry(member.name); if(entry==null || entry.getSize()!=member.length || entry.getCompressedSize()!=member.compressed || entry.getCrc()!=member.crc) throw bad();
        java.security.MessageDigest digest=ResourceStore.sha(); CRC32 crc=new CRC32(); long count=0; byte[] b=new byte[65536];
        try(InputStream in=zip.getInputStream(entry)) {
            int n; while(true) { ResourceStore.check(cancel); n=in.read(b); if(n<0) break; if(n==0) continue;
                if(n>member.length-count) throw bad(); count+=n; crc.update(b,0,n); digest.update(b,0,n); if(output!=null) output.write(b,0,n);
                if(progress!=null) progress.update(stage,count,member.length);
            }
        }
        if(count!=member.length || crc.getValue()!=member.crc) throw bad(); return ResourceStore.hex(digest.digest());
    }
    public void close() throws IOException { if(zip!=null) zip.close(); }
}
