import com.wmmt.port.DataBaselines;
import com.wmmt.port.DataManifest;
import java.io.*;
import java.nio.file.*;
import java.security.*;
import java.util.Locale;

/** Host build helper only; never included in the application DEX. */
public final class DataBaselineCompiler {
    private static final DataManifest.Limits LIMITS = new DataManifest.Limits(
        200000, 50L * 1024 * 1024 * 1024, Integer.MAX_VALUE, DataBaselines.MAX_MANIFEST_BYTES);
    private static String hash(Path p) throws IOException {
        try {
            MessageDigest digest=MessageDigest.getInstance("SHA-256"); byte[] buffer=new byte[65536];
            try(InputStream in=Files.newInputStream(p)) { int n; while((n=in.read(buffer))!=-1) if(n>0) digest.update(buffer,0,n); }
            StringBuilder out=new StringBuilder(); for(byte b:digest.digest()) out.append(String.format(Locale.ROOT,"%02x",b&255)); return out.toString();
        } catch(NoSuchAlgorithmException impossible) { throw new AssertionError(impossible); }
    }
    public static void main(String[] args) throws Exception {
        if(args.length==2 && args[0].equals("--check")) {
            Path catalog=Paths.get(args[1]); DataBaselines parsed;
            try(InputStream in=Files.newInputStream(catalog)) { parsed=DataBaselines.read(in,LIMITS); }
            if(parsed.size()<1) throw new IOException("Empty baseline catalog");
            System.out.println("catalog OK entries="+parsed.size()); return;
        }
        if(args.length!=4 || !args[0].equals("--compile") || !args[1].matches("[0-9a-f]{64}"))
            throw new IllegalArgumentException("Usage: DataBaselineCompiler --compile EXPECTED_SHA256 ZIP OUTPUT_DMF | --check CATALOG");
        final Path source=Paths.get(args[2]); Path output=Paths.get(args[3]); String expected=args[1];
        if(!Files.isRegularFile(source,LinkOption.NOFOLLOW_LINKS)) throw new IOException("Baseline ZIP must be a regular file");
        if(Files.exists(output,LinkOption.NOFOLLOW_LINKS)) throw new IOException("Refusing to replace output DMF");
        if(!hash(source).equals(expected)) throw new IOException("Baseline ZIP differs from explicit reviewed SHA-256");
        DataManifest manifest=DataManifest.fromZip(new DataManifest.ZipSource() {
            public InputStream open() throws IOException { return Files.newInputStream(source); }
        },LIMITS,"legacy-baseline","re3dxplus-data-v1");
        if(!manifest.zipSha256.equals(expected) || manifest.files().isEmpty()) throw new IOException("Empty or changed baseline ZIP");
        manifest.writeAtomic(output,null,LIMITS);
        System.out.println("manifest OK sha256="+manifest.zipSha256+" entries="+manifest.files().size()+" bytes="+Files.size(output));
    }
}
