import com.wmmt.port.*;
import java.io.*;import java.nio.file.*;import java.nio.charset.StandardCharsets;import java.util.*;import java.util.zip.*;

/** Run with java.io.tmpdir set to a new external test directory; no Android runtime. */
public final class DataBaselinesHostTest {
    static final DataManifest.Limits LIMITS=new DataManifest.Limits(100,100000,100000,2*1024*1024);
    static int passed;
    static void ok(boolean value,String message) { if(!value) throw new AssertionError(message); }
    static byte[] zip(String[] names,byte[][] payloads,boolean stored)throws Exception {
        ByteArrayOutputStream out=new ByteArrayOutputStream();
        try(ZipOutputStream z=new ZipOutputStream(out)) {
            for(int i=0;i<names.length;i++) { ZipEntry e=new ZipEntry(names[i]); e.setTime(0);
                if(stored) { CRC32 crc=new CRC32();crc.update(payloads[i]);e.setMethod(ZipEntry.STORED);e.setSize(payloads[i].length);e.setCompressedSize(payloads[i].length);e.setCrc(crc.getValue()); }
                z.putNextEntry(e);z.write(payloads[i]);z.closeEntry(); }
        }
        return out.toByteArray();
    }
    static DataManifest manifest(String content,String id,boolean empty)throws Exception {
        final byte[] bytes=zip(empty?new String[0]:new String[]{"cars/stock.wpk"},empty?new byte[0][]:new byte[][]{content.getBytes("UTF-8")},false);
        return DataManifest.fromZip(()->new ByteArrayInputStream(bytes),LIMITS,"legacy-baseline",id);
    }
    static byte[] encode(DataManifest m)throws Exception { Path d=Files.createTempDirectory("baseline-manifest-test-");Path p=d.resolve("baseline.dmf");m.writeAtomic(p,null,LIMITS);return Files.readAllBytes(p); }
    static String name(DataManifest m){return m.zipSha256+".dmf";}
    static byte[] catalog(DataManifest m)throws Exception{return zip(new String[]{name(m)},new byte[][]{encode(m)},false);}
    static int u16(byte[] b,int p){return (b[p]&255)|((b[p+1]&255)<<8);}
    static int at(byte[] b,int signature){for(int i=0;i<=b.length-4;i++)if(((b[i]&255)|((b[i+1]&255)<<8)|((b[i+2]&255)<<16)|(b[i+3]<<24))==signature)return i;return -1;}
    static void reject(String label,byte[] b)throws Exception { try{DataBaselines.read(new ByteArrayInputStream(b),LIMITS);throw new AssertionError("Accepted "+label);}catch(IOException expected){passed++;System.out.println("PASS reject "+label+": "+expected.getMessage());} }
    static final class Tracking extends ByteArrayInputStream {boolean closed;Tracking(byte[] b){super(b);}public void close(){closed=true;}}
    static byte[] replace(byte[] b,String from,String to){byte[] a=from.getBytes(StandardCharsets.US_ASCII),c=to.getBytes(StandardCharsets.US_ASCII);ok(a.length==c.length,"replace length");byte[] result=b.clone();outer:for(int i=0;i<=result.length-a.length;i++){for(int j=0;j<a.length;j++)if(result[i+j]!=a[j])continue outer;System.arraycopy(c,0,result,i,c.length);i+=a.length-1;}return result;}
    public static void main(String[] args)throws Exception {
        DataManifest m=manifest("old-wheel","re3dxplus-data-v1",false),m2=manifest("another-wheel","re3dxplus-data-v1",false);byte[] dmf=encode(m),good=catalog(m);
        Tracking input=new Tracking(good);DataBaselines parsed=DataBaselines.read(input,LIMITS);ok(!input.closed&&parsed.size()==1&&parsed.find(m.zipSha256).files().size()==1,"valid/nonclosing");ok(parsed.find(String.join("",Collections.nCopies(64,"0")))==null,"unknown hash");passed++;
        ok(DataBaselines.read(new ByteArrayInputStream(zip(new String[]{name(m)},new byte[][]{dmf},true)),LIMITS).size()==1,"stored ZIP");passed++;
        ok(DataBaselines.read(new ByteArrayInputStream(zip(new String[]{name(m),name(m2)},new byte[][]{dmf,encode(m2)},false)),LIMITS).size()==2,"two baselines");passed++;
        try{parsed.find("UPPERCASE");throw new AssertionError("bad lookup accepted");}catch(IOException expected){passed++;}
        reject("empty input",new byte[0]);reject("empty ZIP",zip(new String[0],new byte[0][],false));
        reject("truncated EOCD",Arrays.copyOf(good,good.length-1));reject("missing central directory",Arrays.copyOf(good,at(good,0x02014b50)));
        reject("trailing junk",Arrays.copyOf(good,good.length+1));
        reject("directory",zip(new String[]{"folder/"},new byte[][]{new byte[0]},false));
        reject("unknown entry",zip(new String[]{"notes.txt"},new byte[][]{dmf},false));
        reject("uppercase SHA",zip(new String[]{name(m).toUpperCase(Locale.ROOT)},new byte[][]{dmf},false));
        reject("nested leaf",zip(new String[]{"nested/"+name(m)},new byte[][]{dmf},false));
        reject("duplicate names",replace(zip(new String[]{name(m),name(m2)},new byte[][]{dmf,encode(m2)},true),name(m2),name(m)));
        reject("manifest SHA mismatch",zip(new String[]{name(m2)},new byte[][]{dmf},false));
        reject("wrong canonical ID",catalog(manifest("old-wheel","foreign-identity",false)));
        reject("empty manifest inventory",catalog(manifest("none","re3dxplus-data-v1",true)));
        byte[] badDmf=dmf.clone();badDmf[badDmf.length-1]^=1;reject("DMF checksum",zip(new String[]{name(m)},new byte[][]{badDmf},false));
        byte[] crc=zip(new String[]{name(m)},new byte[][]{dmf},true);int payload=30+u16(crc,26)+u16(crc,28);crc[payload]^=1;reject("payload CRC",crc);
        byte[] local=good.clone();local[30]^=1;reject("local/central name mismatch",local);
        byte[] descriptor=good.clone();int dp=at(descriptor,0x08074b50);ok(dp>=0,"fixture descriptor");descriptor[dp+4]^=1;reject("descriptor CRC mismatch",descriptor);
        reject("compressed byte limit",new byte[DataBaselines.MAX_CATALOG_BYTES+1]);
        reject("per-DMF byte limit",zip(new String[]{name(m)},new byte[][]{new byte[DataBaselines.MAX_MANIFEST_BYTES+1]},false));
        String[] names=new String[17];byte[][] contents=new byte[17][];for(int i=0;i<17;i++){names[i]=String.format(Locale.ROOT,"%064x.dmf",i);contents[i]=dmf;}
        reject("17 baselines",zip(names,contents,false));
        names=Arrays.copyOf(names,9);contents=new byte[9][];for(int i=0;i<9;i++)contents[i]=new byte[DataBaselines.MAX_MANIFEST_BYTES];reject("aggregate uncompressed byte limit",zip(names,contents,false));
        try{DataBaselines.read(new ByteArrayInputStream(good),new DataManifest.Limits(100,100000,100000,64));throw new AssertionError("caller manifest limit ignored");}catch(IOException expected){passed++;}
        Tracking badInput=new Tracking(new byte[]{1});try{DataBaselines.read(badInput,LIMITS);}catch(IOException expected){}ok(!badInput.closed,"failure closed caller stream");passed++;
        System.out.println("DataBaselines host tests passed: "+passed);
    }
}
