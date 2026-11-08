package com.wmmt.port;
import java.io.*;
import java.nio.charset.StandardCharsets;
/** Pure parser regression; no Android, install, network, resource or GPU claim. */
public final class ArcadeUiV5MetadataTest {
  static int checks;
  static final String SHA="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
  static ByteArrayInputStream in(String s) { return new ByteArrayInputStream(s.getBytes(StandardCharsets.UTF_8)); }
  static ResourceMetadata base() throws IOException { return ResourceMetadata.read(in("WMMT-SIDECARS-1\n")); }
  static String ui(String magic) { return magic+"\nghost-ui.bin\t4077459\t"+SHA+"\n"; }
  static void yes(boolean v) { if(!v) throw new AssertionError(); checks++; }
  interface Action { void run() throws IOException; }
  static void bad(Action f) throws IOException { try { f.run(); } catch(IOException expected) { checks++; return; } throw new AssertionError("accepted invalid approval"); }
  public static void main(String[] args) throws Exception {
    ResourceMetadata v5=base().withArcadeUiV5(in(ui("WMMT-ARCADE-UI-5")));
    yes(v5.files().size()==1 && v5.find("ghost-ui.bin").length==4077459 && v5.find("ghost-ui.bin").sha256.equals(SHA));
    ResourceMetadata old=base().withGhost(in(ui("WMMT-GHOST-UI-1")));
    yes(old.files().size()==1 && old.find("ghost-ui.bin")!=null);
    yes(ResourceMetadata.OPTIONAL_PATHS.size()==6 && ResourceMetadata.OPTIONAL_PATHS.contains("ghost-ui.bin"));
    bad(()->base().withGhost(in(ui("WMMT-ARCADE-UI-5"))));
    bad(()->base().withArcadeUiV5(in(ui("WMMT-GHOST-UI-1"))));
    bad(()->v5.withGhost(in(ui("WMMT-GHOST-UI-1"))));
    bad(()->old.withArcadeUiV5(in(ui("WMMT-ARCADE-UI-5"))));
    bad(()->base().withArcadeUiV5(in(ui("WMMT-ARCADE-UI-4"))));
    bad(()->base().withArcadeUiV5(in(ui("WMMT-ARCADE-UI-5").replace("ghost-ui.bin","builtin-ghosts.bin"))));
    bad(()->base().withArcadeUiV5(in(ui("WMMT-ARCADE-UI-5").replace("4077459","0"))));
    bad(()->base().withArcadeUiV5(in(ui("WMMT-ARCADE-UI-5").replace("4077459","15"))));
    bad(()->base().withArcadeUiV5(in(ui("WMMT-ARCADE-UI-5").replace("4077459","268435457"))));
    bad(()->base().withArcadeUiV5(in(ui("WMMT-ARCADE-UI-5").replace("4077459","9999999999"))));
    bad(()->base().withArcadeUiV5(in(ui("WMMT-ARCADE-UI-5").replace("4077459","04077459"))));
    bad(()->base().withArcadeUiV5(in(ui("WMMT-ARCADE-UI-5")+"\n")));
    bad(()->base().withArcadeUiV5(in(ui("WMMT-ARCADE-UI-5").replace("\n","\r\n"))));
    bad(()->base().withArcadeUiV5(new ByteArrayInputStream(new byte[]{(byte)0xc3,(byte)0x28})));
    bad(()->base().withArcadeUiV5(in(new String(new char[513]).replace('\0','a'))));
    bad(()->base().withArcadeUiV5(null));
    String bank="WMMT-BUILTIN-GHOSTS-1\nbuiltin-ghosts.bin\t54528259\t"+SHA+"\n";
    yes(v5.withBuiltinGhosts(in(bank)).files().size()==2);
    bad(()->base().withBuiltinGhosts(in(ui("WMMT-ARCADE-UI-5"))));
    System.out.println("PASS "+checks+" explicit v5/legacy separation and same-six-namespace checks; not Android/GPU evidence");
  }
}
