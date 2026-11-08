package com.wmmt.port;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.zip.*;

/** Finite, APK-authenticated legacy inventories. This parser does not establish
 * provenance: only the caller's signed APK asset is a trust source. Installed
 * files and their completion markers must never be used to create this catalog.
 * Reading leaves the caller-owned input stream open. */
public final class DataBaselines implements DataCoordinator.Baselines {
    public static final int MAX_BASELINES = 16;
    public static final int MAX_MANIFEST_BYTES = 2 * 1024 * 1024;
    public static final int MAX_CATALOG_BYTES = 16 * 1024 * 1024;
    private static final String ID = "re3dxplus-data-v1";
    private final Map<String, DataManifest> manifests;

    private DataBaselines(Map<String, DataManifest> entries) {
        manifests = Collections.unmodifiableMap(new TreeMap<String, DataManifest>(entries));
    }
    /** A miss is not permission to infer a baseline from installed bytes. */
    @Override public DataManifest find(String zipSha256) throws IOException {
        if (zipSha256 == null || !zipSha256.matches("[0-9a-f]{64}")) throw bad("Invalid baseline SHA-256");
        return manifests.get(zipSha256);
    }
    public int size() { return manifests.size(); }
    /** Immutable inventories authenticated by this APK; never inferred from player files. */
    public Collection<DataManifest> inventories() { return manifests.values(); }
    private static IOException bad(String message) { return new IOException(message); }
    private static int u16(byte[] b, int p) { return (b[p] & 255) | ((b[p + 1] & 255) << 8); }
    private static long u32(byte[] b, int p) { return (u16(b, p) & 65535L) | ((long) u16(b, p + 2) << 16); }
    private static byte[] bounded(InputStream in, int max) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream(); byte[] buffer = new byte[8192]; int n;
        while ((n = in.read(buffer)) != -1) {
            if (n == 0) { int one = in.read(); if (one < 0) break;
                if (out.size() == max) throw bad("Baseline catalog byte limit"); out.write(one); continue; }
            if (n > max - out.size()) throw bad("Baseline catalog byte limit");
            out.write(buffer, 0, n);
        }
        return out.toByteArray();
    }
    private static final class Member {
        final String name; final int flags, method, offset; final long crc, compressed, length;
        Member(String n, int f, int m, int o, long c, long z, long l) { name=n; flags=f; method=m; offset=o; crc=c; compressed=z; length=l; }
    }
    /** Bind the complete ordinary ZIP central directory to the complete local stream.
     * ZipInputStream alone accepts missing central directories and trailing junk. */
    private static Map<String, Member> index(byte[] b) throws IOException {
        int end = -1;
        for (int i=b.length-22; i>=Math.max(0,b.length-65557); i--)
            if (u32(b,i)==0x06054b50L && (long)i+22+u16(b,i+20)==b.length) { end=i; break; }
        if (end<0 || u16(b,end+4)!=0 || u16(b,end+6)!=0 || u16(b,end+8)!=u16(b,end+10)) throw bad("Invalid or truncated baseline ZIP");
        int count=u16(b,end+10); long central=u32(b,end+16), bytes=u32(b,end+12);
        if (count<1 || count>MAX_BASELINES || central+bytes!=end || central>end) throw bad("Empty, oversized or unsupported baseline ZIP");
        Map<String,Member> members=new LinkedHashMap<String,Member>(); long total=0; int at=(int)central;
        for(int i=0;i<count;i++) {
            if(at>end-46 || u32(b,at)!=0x02014b50L) throw bad("Invalid baseline ZIP directory");
            int flags=u16(b,at+8), method=u16(b,at+10), n=u16(b,at+28), extra=u16(b,at+30), comment=u16(b,at+32);
            long crc=u32(b,at+16), compressed=u32(b,at+20), length=u32(b,at+24), offset=u32(b,at+42);
            if((long)at+46+n+extra+comment>end || n!=68 || u16(b,at+34)!=0 || offset>=central || compressed==0xffffffffL || length>MAX_MANIFEST_BYTES ||
                    (flags & ~0x0808)!=0 || (method!=ZipEntry.STORED && method!=ZipEntry.DEFLATED)) throw bad("Unsupported baseline ZIP member");
            String name=new String(b,at+46,n,StandardCharsets.US_ASCII);
            if(!name.matches("[0-9a-f]{64}\\.dmf") || members.containsKey(name)) throw bad("Unknown or duplicate baseline ZIP entry");
            if(length>MAX_CATALOG_BYTES-total) throw bad("Baseline catalog uncompressed limit"); total+=length;
            members.put(name,new Member(name,flags,method,(int)offset,crc,compressed,length)); at+=46+n+extra+comment;
        }
        if(at!=end) throw bad("Unrecognized baseline ZIP directory data");
        List<Member> ordered=new ArrayList<Member>(members.values());
        Collections.sort(ordered,new Comparator<Member>() { public int compare(Member a,Member c) { return Integer.compare(a.offset,c.offset); } });
        long next=0;
        for(Member m:ordered) {
            int p=m.offset;
            if(p!=next || p>(int)central-30 || u32(b,p)!=0x04034b50L || u16(b,p+6)!=m.flags || u16(b,p+8)!=m.method) throw bad("Invalid baseline ZIP local header");
            int n=u16(b,p+26), extra=u16(b,p+28);
            if(n!=68 || (long)p+30+n+extra>central || !m.name.equals(new String(b,p+30,n,StandardCharsets.US_ASCII))) throw bad("Baseline ZIP member name mismatch");
            long localCrc=u32(b,p+14), localCompressed=u32(b,p+18), localLength=u32(b,p+22); boolean descriptor=(m.flags&8)!=0;
            if(descriptor ? ((localCrc!=0&&localCrc!=m.crc)||(localCompressed!=0&&localCompressed!=m.compressed)||(localLength!=0&&localLength!=m.length)) :
                    (localCrc!=m.crc || localCompressed!=m.compressed || localLength!=m.length)) throw bad("Baseline ZIP header values mismatch");
            next=(long)p+30+n+extra+m.compressed; if(next>central) throw bad("Truncated baseline ZIP member");
            if(descriptor) {
                int d=(int)next; if(d>central-12) throw bad("Truncated baseline ZIP descriptor");
                if(u32(b,d)==0x08074b50L) { d+=4; if(d>central-12) throw bad("Truncated baseline ZIP descriptor"); }
                if(u32(b,d)!=m.crc || u32(b,d+4)!=m.compressed || u32(b,d+8)!=m.length) throw bad("Baseline ZIP descriptor mismatch");
                next=d+12L;
            }
        }
        if(next!=central) throw bad("Unrecognized baseline ZIP local data"); return members;
    }
    public static DataBaselines read(InputStream catalog, DataManifest.Limits limits) throws IOException {
        if(catalog==null || limits==null) throw bad("Missing baseline catalog or limits");
        byte[] bytes=bounded(catalog,MAX_CATALOG_BYTES); Map<String,Member> expected=index(bytes);
        Map<String,DataManifest> result=new TreeMap<String,DataManifest>(); long total=0;
        try(ZipInputStream zip=new ZipInputStream(new ByteArrayInputStream(bytes),StandardCharsets.UTF_8)) {
            ZipEntry entry;
            while((entry=zip.getNextEntry())!=null) {
                String name=entry.getName(); Member member=expected.get(name);
                if(entry.isDirectory() || member==null || result.containsKey(name.substring(0,64))) throw bad("Unknown or duplicate baseline ZIP entry");
                byte[] dmf=bounded(zip,Math.min(MAX_MANIFEST_BYTES,limits.maxManifestBytes)); zip.closeEntry();
                if(dmf.length!=member.length || entry.getSize()!=member.length || entry.getCrc()!=member.crc || entry.getCompressedSize()!=member.compressed) throw bad("Baseline ZIP member integrity mismatch");
                if(dmf.length>MAX_CATALOG_BYTES-total) throw bad("Baseline catalog uncompressed limit"); total+=dmf.length;
                DataManifest manifest=DataManifest.read(new ByteArrayInputStream(dmf),limits); String hash=name.substring(0,64);
                if(!ID.equals(manifest.canonicalId) || manifest.files().isEmpty() || !hash.equals(manifest.zipSha256)) throw bad("Baseline manifest identity mismatch");
                result.put(hash,manifest);
            }
        } catch(IllegalArgumentException ex) { throw new IOException("Invalid baseline ZIP",ex); }
        if(result.size()!=expected.size()) throw bad("Missing baseline ZIP members"); return new DataBaselines(result);
    }
}
