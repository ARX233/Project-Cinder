package com.wmmt.port;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.charset.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.zip.*;

/** Inventory for trusted, signed APK ZIP assets, not a general-purpose ZIP verifier.
 * ZIP external attributes are ignored: consumers must create regular files only, safely
 * resolving every path without following links. Directories are not owned by this index.
 * All read/write operations and related resource changes require the same external lock.
 * File sync and atomic rename do not sync the parent directory; crash durability requires
 * a platform-specific directory fsync, which this class does not provide. */
public final class DataManifest {
    public static final String RESERVED_MARKER = ".wmmt-data-manifest";
    private static final int MAGIC = 0x444d4631, VERSION = 1, END = 0x454e4421;
    private static final int MAX_STRING = 65535;
    public interface ZipSource { InputStream open() throws IOException; }
    public static final class Limits {
        public final int maxEntries, maxArchiveBytes, maxManifestBytes;
        public final long maxTotalBytes;
        public Limits(int entries, long total, int archive, int manifest) {
            if (entries < 0 || total < 0 || archive < 22 || manifest < 64) throw new IllegalArgumentException();
            maxEntries=entries; maxTotalBytes=total; maxArchiveBytes=archive; maxManifestBytes=manifest;
        }
    }
    public static final class Entry {
        public final String path, sha256; public final long length;
        private Entry(String p, long n, String h) { path=p; length=n; sha256=h; }
    }
    public final String zipSha256, resourceDirectory, canonicalId;
    private final SortedMap<String,Entry> files;
    private DataManifest(String z, String dir, String id, SortedMap<String,Entry> f) {
        zipSha256=z; resourceDirectory=dir; canonicalId=id;
        files=Collections.unmodifiableSortedMap(new TreeMap<String,Entry>(f));
    }
    public SortedMap<String,Entry> files() { return files; }
    /** Rebind a trusted inventory to one checked installation name; file ownership
     * and the archive identity are unchanged. This does not verify disk contents. */
    public DataManifest rebindDirectory(String directory) throws IOException {
        identity(directory,canonicalId);
        return new DataManifest(zipSha256,directory,canonicalId,files);
    }
    public Entry find(String relativePath) throws IOException { path(relativePath, false); return files.get(relativePath); }
    private static IOException bad(String message) { return new IOException(message); }
    private static MessageDigest sha() { try { return MessageDigest.getInstance("SHA-256"); } catch (NoSuchAlgorithmException e) { throw new AssertionError(e); } }
    private static String hex(byte[] b) { char[] out=new char[b.length*2]; char[] h="0123456789abcdef".toCharArray(); for(int i=0;i<b.length;i++) { out[i*2]=h[(b[i]&255)>>>4]; out[i*2+1]=h[b[i]&15]; } return new String(out); }
    private static void text(String s) throws IOException {
        if(s==null || s.isEmpty() || s.getBytes(StandardCharsets.UTF_8).length>MAX_STRING) throw bad("invalid text length");
        for(int i=0;i<s.length();i++) { char c=s.charAt(i); if(Character.isISOControl(c) || Character.isSurrogate(c)) throw bad("invalid text character"); }
    }
    private static void path(String s, boolean directory) throws IOException {
        text(s); if(s.startsWith("/") || s.indexOf('\\')>=0 || s.indexOf(':')>=0) throw bad("unsafe path");
        String x=directory && s.endsWith("/") ? s.substring(0,s.length()-1) : s;
        if(x.isEmpty() || (!directory && s.endsWith("/"))) throw bad("empty path");
        for(String part:x.split("/",-1)) if(part.isEmpty() || part.equals(".") || part.equals("..") || part.equalsIgnoreCase(RESERVED_MARKER) || part.equalsIgnoreCase(".re3dxplus-install-v1") || part.equalsIgnoreCase("mods") || part.equalsIgnoreCase("wmmt") || part.startsWith(".overlay-")) throw bad("unsafe path component");
    }
    private static void identity(String dir,String id) throws IOException { path(dir,false); if(dir.indexOf('/')>=0) throw bad("directory must be one component"); text(id); }
    private static byte[] bounded(InputStream in,int max) throws IOException {
        ByteArrayOutputStream out=new ByteArrayOutputStream(); byte[] buf=new byte[8192]; int n;
        while((n=in.read(buf))!=-1) { if(n==0) continue; if(n>max-out.size()) throw bad("byte limit"); out.write(buf,0,n); } return out.toByteArray();
    }
    private static int u16(byte[] b,int p) { return (b[p]&255)|((b[p+1]&255)<<8); }
    private static long u32(byte[] b,int p) { return (u16(b,p)&65535L)|((long)u16(b,p+2)<<16); }
    private static final class CheckedStream extends FilterInputStream {
        final MessageDigest digest=sha(); final long limit; long count;
        CheckedStream(InputStream input,long limit) { super(input); this.limit=limit; }
        @Override public int read() throws IOException { byte[] one=new byte[1]; int n=read(one,0,1); return n<0?-1:one[0]&255; }
        @Override public int read(byte[] b,int off,int len) throws IOException {
            int n=in.read(b,off,len); if(n>0) { if(n>limit-count) throw bad("archive byte limit"); count+=n; digest.update(b,off,n); } return n;
        }
    }
    /** The source is streamed twice and both byte counts and SHA-256 hashes must match.
     * Only the last 65557 bytes are buffered to verify the ZIP end record. Empty
     * directories are accepted but never owned. ZIP64 and multi-disk are rejected.
     * This is not a validator for hostile ZIP structure or external file attributes. */
    public static DataManifest fromZip(ZipSource source, Limits limits, String directory, String canonicalId) throws IOException {
        identity(directory,canonicalId);
        byte[] tail=new byte[65557], buf=new byte[8192], firstHash; long firstLength;
        int used=0, cursor=0;
        try(InputStream raw=source.open()) {
            if(raw==null) throw bad("null ZIP stream"); CheckedStream in=new CheckedStream(raw,limits.maxArchiveBytes); int n;
            while((n=in.read(buf))!=-1) { if(n==0) continue; for(int j=0;j<n;j++) { tail[cursor]=buf[j]; cursor=(cursor+1)%tail.length; if(used<tail.length) used++; } }
            firstLength=in.count; firstHash=in.digest.digest();
        }
        byte[] suffix=new byte[used]; int start=(cursor-used+tail.length)%tail.length;
        for(int i=0;i<used;i++) suffix[i]=tail[(start+i)%tail.length];
        int end=-1;
        for(int i=used-22;i>=0;i--) if(u32(suffix,i)==0x06054b50L && i+22+u16(suffix,i+20)==used) { end=i; break; }
        if(end<0 || u16(suffix,end+4)!=0 || u16(suffix,end+6)!=0 || u16(suffix,end+8)!=u16(suffix,end+10) || u16(suffix,end+10)==65535 || u32(suffix,end+12)==0xffffffffL || u32(suffix,end+16)==0xffffffffL || u32(suffix,end+12)+u32(suffix,end+16)!=firstLength-used+end) throw bad("invalid or unsupported ZIP end");
        int declared=u16(suffix,end+10), count=0; long total=0; Set<String> paths=new HashSet<String>(); SortedMap<String,Entry> files=new TreeMap<String,Entry>();
        InputStream raw=source.open(); if(raw==null) throw bad("null ZIP stream");
        CheckedStream checked=new CheckedStream(raw,limits.maxArchiveBytes);
        try(ZipInputStream zip=new ZipInputStream(checked,StandardCharsets.UTF_8)) {
            ZipEntry entry;
            while((entry=zip.getNextEntry())!=null) {
                if(++count>limits.maxEntries || count>declared) throw bad("entry limit or count mismatch");
                boolean dir=entry.isDirectory(); String name=entry.getName(); path(name,dir);
                String key=dir?name.substring(0,name.length()-1):name; if(!paths.add(key)) throw bad("duplicate entry");
                MessageDigest hash=sha(); long length=0; int n;
                while((n=zip.read(buf))!=-1) { if(n==0) continue; if(n>limits.maxTotalBytes-total) throw bad("uncompressed limit"); total+=n; length+=n; hash.update(buf,0,n); }
                zip.closeEntry(); if(dir && length!=0) throw bad("directory has content");
                if(!dir) files.put(name,new Entry(name,length,hex(hash.digest())));
            }
            while(checked.read(buf)!=-1) { /* consume central directory and trailing data */ }
            if(checked.count!=firstLength || !MessageDigest.isEqual(firstHash,checked.digest.digest())) throw bad("ZIP changed between reads");
        } catch(IllegalArgumentException ex) { throw new IOException("invalid ZIP",ex); }
        if(count!=declared) throw bad("missing ZIP entries");
        checkParents(files);
        return new DataManifest(hex(firstHash),directory,canonicalId,files);
    }
    private static void checkParents(SortedMap<String,Entry> files) throws IOException {
        for(String file:files.keySet()) { int p=file.indexOf('/'); while(p>=0) { if(files.containsKey(file.substring(0,p))) throw bad("file used as directory"); p=file.indexOf('/',p+1); } }
    }
    private static void put(DataOutputStream o,String s) throws IOException { byte[] b=s.getBytes(StandardCharsets.UTF_8); o.writeInt(b.length); o.write(b); }
    private static String get(DataInputStream in) throws IOException {
        int n=in.readInt(); if(n<1 || n>MAX_STRING) throw bad("invalid string length"); byte[] b=new byte[n]; in.readFully(b);
        try { String s=StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(b)).toString(); text(s); return s; }
        catch(CharacterCodingException e) { throw new IOException("invalid UTF-8",e); }
    }
    private static void hash(String s) throws IOException { if(s==null || !s.matches("[0-9a-f]{64}")) throw bad("invalid SHA-256"); }
    private byte[] encode() throws IOException {
        ByteArrayOutputStream bytes=new ByteArrayOutputStream(); DataOutputStream out=new DataOutputStream(bytes);
        out.writeInt(MAGIC); out.writeInt(VERSION); put(out,zipSha256); put(out,resourceDirectory); put(out,canonicalId); out.writeInt(files.size());
        for(Entry e:files.values()) { put(out,e.path); out.writeLong(e.length); put(out,e.sha256); }
        out.writeInt(END); out.flush(); byte[] body=bytes.toByteArray(); out.write(sha().digest(body)); out.flush(); return bytes.toByteArray();
    }
    /** Strictly read a complete canonical private manifest, under the external lock. */
    public static DataManifest read(Path file, Limits limits) throws IOException {
        try(InputStream in=Files.newInputStream(file,LinkOption.NOFOLLOW_LINKS)) { return read(in,limits); }
    }
    /** Read a bounded complete inventory, e.g. from a signed APK catalog entry.
     * The caller owns the stream. The checksum detects damage, not authenticity. */
    public static DataManifest read(InputStream input, Limits limits) throws IOException {
        if(input==null) throw bad("null manifest stream");
        byte[] bytes=bounded(input,limits.maxManifestBytes);
        if(bytes.length<40) throw bad("incomplete manifest"); byte[] body=Arrays.copyOf(bytes,bytes.length-32);
        if(!MessageDigest.isEqual(sha().digest(body),Arrays.copyOfRange(bytes,bytes.length-32,bytes.length))) throw bad("manifest checksum");
        DataInputStream in=new DataInputStream(new ByteArrayInputStream(body)); if(in.readInt()!=MAGIC || in.readInt()!=VERSION) throw bad("unknown manifest version");
        String zip=get(in),dir=get(in),id=get(in); hash(zip); identity(dir,id); int count=in.readInt(); if(count<0 || count>limits.maxEntries) throw bad("entry limit");
        SortedMap<String,Entry> files=new TreeMap<String,Entry>(); long total=0; String previous=null;
        for(int i=0;i<count;i++) { String name=get(in); path(name,false); long n=in.readLong(); String h=get(in); hash(h);
            if(n<0 || n>limits.maxTotalBytes-total || (previous!=null && previous.compareTo(name)>=0)) throw bad("invalid entry");
            total+=n; files.put(name,new Entry(name,n,h)); previous=name;
        }
        if(in.readInt()!=END || in.read()!=-1) throw bad("manifest incomplete or trailing data"); checkParents(files);
        return new DataManifest(zip,dir,id,files);
    }
    /** Caller holds the external lock. Expected null means destination must be absent;
     * non-null means it must exactly equal the previous canonical manifest. No unknown
     * file is replaced. Atomic rename support is required; failures retain the old file. */
    public void writeAtomic(Path destination, DataManifest expected, Limits limits) throws IOException {
        Path target=destination.toAbsolutePath(); Path parent=target.getParent(); byte[] next=encode(); if(next.length>limits.maxManifestBytes) throw bad("manifest limit");
        if(Files.exists(target,LinkOption.NOFOLLOW_LINKS)) {
            if(expected==null || Files.isSymbolicLink(target) || !Files.isRegularFile(target,LinkOption.NOFOLLOW_LINKS)) throw bad("unknown destination");
            byte[] old; try(InputStream in=Files.newInputStream(target,LinkOption.NOFOLLOW_LINKS)) { old=bounded(in,limits.maxManifestBytes); }
            if(!Arrays.equals(old,expected.encode())) throw bad("destination changed or unknown");
        } else if(expected!=null) throw bad("expected manifest missing");
        Path temp=Files.createTempFile(parent,".data-manifest-", ".tmp");
        try {
            try(FileOutputStream out=new FileOutputStream(temp.toFile())) { out.write(next); out.getFD().sync(); }
            Files.move(temp,target,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
        } finally { Files.deleteIfExists(temp); }
    }
}
