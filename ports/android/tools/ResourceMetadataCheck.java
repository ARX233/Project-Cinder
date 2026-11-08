import com.wmmt.port.ResourceMetadata;
import java.io.*;
/** Host build check only; never part of the application DEX. */
public final class ResourceMetadataCheck {
  public static void main(String[] args) throws Exception {
    if (args.length != 1) throw new IOException("Specify the signed sidecar metadata input");
    try (InputStream in = new FileInputStream(args[0])) {
      ResourceMetadata m = ResourceMetadata.read(in);
      if (m.files().size() != 41) throw new IOException("Expected all 41 approved sidecar metadata entries");
      System.out.println("sidecar metadata OK entries=41; no payload included");
    }
  }
}
