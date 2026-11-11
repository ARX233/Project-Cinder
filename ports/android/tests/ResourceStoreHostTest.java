import com.wmmt.port.*;
import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.zip.*;

/** Run with a JDK only; every generated file stays under /Volumes/CodexWork. */
public final class ResourceStoreHostTest {
    static final Path WORK=Paths.get("/Volumes/CodexWork");
    static final DataManifest.Limits LIMITS=new DataManifest.Limits(10000,50L*1024*1024*1024,Integer.MAX_VALUE,2*1024*1024);
    static int assertions;
    static final String ID="re3dxplus-data-v1", MARKER=".re3dxplus-install-v1";
    interface Action { void run() throws Exception; }
    static void ok(boolean value,String what) { assertions++; if(!value) throw new AssertionError(what); }
    static IOException fails(Action a,String what) throws Exception {
        try { a.run(); } catch(IOException e) { assertions++; return e; } throw new AssertionError("Unexpected success: "+what);
    }
    static byte[] bytes(String s) { return s.getBytes(StandardCharsets.UTF_8); }
    static String sha(byte[] data) throws Exception { StringBuilder s=new StringBuilder(); for(byte b:MessageDigest.getInstance("SHA-256").digest(data)) s.append(String.format(Locale.ROOT,"%02x",b&255)); return s.toString(); }
    static byte[] zip(Map<String,byte[]> files,String comment) throws Exception {
        ByteArrayOutputStream out=new ByteArrayOutputStream();
        try(ZipOutputStream zip=new ZipOutputStream(out)) {
            zip.setComment(comment); for(Map.Entry<String,byte[]> e:files.entrySet()) { ZipEntry z=new ZipEntry(e.getKey()); z.setTime(0); zip.putNextEntry(z); zip.write(e.getValue()); zip.closeEntry(); }
        } return out.toByteArray();
    }
    static Map<String,byte[]> mainFiles() {
        Map<String,byte[]> map=new TreeMap<String,byte[]>(); map.put("critical.rsm",bytes("rsm-complete")); map.put("root.bin",bytes("root-data"));
        for(int i=0;i<1796;i++) map.put(String.format(Locale.ROOT,"part-%04d.bin",i),bytes("verified-main-"+i)); return map;
    }
    static Map<String,byte[]> sideFiles() {
        Map<String,byte[]> map=new TreeMap<String,byte[]>();
        for(String p:ResourceMetadata.OPTIONAL_PATHS.subList(0,4)) map.put(p,bytes("signed-"+p));
        for(String p:ResourceMetadata.CARD_PATHS) map.put(p,bytes("signed-"+p)); return map;
    }
    static ResourceMetadata metadata(Map<String,byte[]> extras) throws Exception {
        StringBuilder s=new StringBuilder("WMMT-SIDECARS-1\n"); for(Map.Entry<String,byte[]> e:extras.entrySet()) s.append(e.getKey()).append('\t').append(e.getValue().length).append('\t').append(sha(e.getValue())).append('\n');
        return ResourceMetadata.read(new ByteArrayInputStream(bytes(s.toString())));
    }
    static Path temp(String name) throws Exception { return Files.createTempDirectory(WORK,"resource-test-"+name+"-").toRealPath(); }
    static DataManifest manifest(byte[] archive,String dirname) throws Exception { return DataManifest.fromZip(()->new ByteArrayInputStream(archive),LIMITS,dirname,ID); }
    static DataBaselines catalog(Path work,DataManifest... manifests) throws Exception {
        Map<String,byte[]> files=new TreeMap<String,byte[]>();
        for(DataManifest m:manifests) { Path p=work.resolve(m.zipSha256+".dmf"); if(!Files.exists(p)) m.writeAtomic(p,null,LIMITS); files.put(m.zipSha256+".dmf",Files.readAllBytes(p)); }
        return DataBaselines.read(new ByteArrayInputStream(zip(files,"signed-catalog")),LIMITS);
    }
    static final class Env {
        final Path work,ext,noBackup; final ResourceStore store;
        Env(String name,DataBaselines b,ResourceMetadata m) throws Exception { work=temp(name); ext=Files.createDirectory(work.resolve("external")); noBackup=Files.createDirectory(work.resolve("noBackup")); store=new ResourceStore(ext,noBackup,LIMITS,b,m); }
        Path selection() { return noBackup.resolve("resource-import-v1/selection"); }
    }
    static void materialize(Path root,Map<String,byte[]> files) throws Exception {
        Files.createDirectories(root); for(Map.Entry<String,byte[]> e:files.entrySet()) { Path p=root.resolve(e.getKey()); Files.createDirectories(p.getParent()); Files.write(p,e.getValue()); }
    }
    static Path oldRoot(Env e,DataManifest m,Map<String,byte[]> files,boolean marker) throws Exception {
        Path root=e.ext.resolve("re3dxplus-data").resolve(m.zipSha256+"-"+UUID.randomUUID()); materialize(root,files);
        if(marker) Files.write(root.resolve(MARKER),bytes(ID+":"+m.zipSha256)); return root;
    }
    static String fileSha(Path path) throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256"); byte[] buffer=new byte[65536];
        try(InputStream in=Files.newInputStream(path)) { int n; while((n=in.read(buffer))!=-1) if(n>0) digest.update(buffer,0,n); }
        StringBuilder out=new StringBuilder(); for(byte b:digest.digest()) out.append(String.format(Locale.ROOT,"%02x",b&255)); return out.toString();
    }
    static Map<String,String> snapshot(Path root) throws Exception {
        Map<String,String> map=new TreeMap<String,String>(); if(!Files.exists(root,LinkOption.NOFOLLOW_LINKS)) return map;
        try(java.util.stream.Stream<Path> stream=Files.walk(root)) {
            for(Iterator<Path> it=stream.iterator();it.hasNext();) { Path p=it.next(); String n=root.relativize(p).toString();
                map.put(n,Files.isSymbolicLink(p)?"L:"+Files.readSymbolicLink(p):Files.isDirectory(p,LinkOption.NOFOLLOW_LINKS)?"D":fileSha(p)); }
        } return map;
    }
    static void unchanged(Path path,Map<String,String> before,String what) throws Exception { ok(snapshot(path).equals(before),what); }
    static byte[] replaceHeader(byte[] data,int centralField,int localField,int mask) {
        byte[] b=data.clone(); for(int i=0;i<b.length-46;i++) {
            int sig=(b[i]&255)|((b[i+1]&255)<<8)|((b[i+2]&255)<<16)|((b[i+3]&255)<<24);
            if(sig==0x02014b50) { b[i+centralField]|=(byte)mask; break; }
        }
        if(localField>=0) b[localField]|=(byte)mask; return b;
    }
    static int firstCentral(byte[] b) { for(int i=0;i<b.length-46;i++) if(b[i]==0x50&&b[i+1]==0x4b&&b[i+2]==1&&b[i+3]==2) return i; throw new AssertionError(); }
    static void put32(byte[] b,int p,long value) { for(int i=0;i<4;i++) b[p+i]=(byte)(value>>>(8*i)); }
    static long get32(byte[] b,int p) { return (b[p]&255L)|((b[p+1]&255L)<<8)|((b[p+2]&255L)<<16)|((b[p+3]&255L)<<24); }
    static byte[] apkSigningBlock(byte[] original) {
        int end=original.length-22; while(end>=0 && get32(original,end)!=0x06054b50L) end--; int central=(int)get32(original,end+16);
        byte[] block=new byte[44]; put32(block,0,36); put32(block,8,4); put32(block,16,0x7109871aL); put32(block,20,36);
        System.arraycopy(bytes("APK Sig Block 42"),0,block,28,16); byte[] out=new byte[original.length+block.length];
        System.arraycopy(original,0,out,0,central); System.arraycopy(block,0,out,central,block.length); System.arraycopy(original,central,out,central+block.length,original.length-central);
        put32(out,end+block.length+16,central+block.length); return out;
    }
    static byte[] withLocalExtra(byte[] original,byte[] extra) {
        int end=original.length-22; while(get32(original,end)!=0x06054b50L) end--; int central=(int)get32(original,end+16);
        int n=(original[26]&255)|((original[27]&255)<<8),oldExtra=(original[28]&255)|((original[29]&255)<<8),at=30+n+oldExtra;
        byte[] out=new byte[original.length+extra.length]; System.arraycopy(original,0,out,0,at); System.arraycopy(extra,0,out,at,extra.length); System.arraycopy(original,at,out,at+extra.length,original.length-at);
        int length=oldExtra+extra.length; out[28]=(byte)length;out[29]=(byte)(length>>>8); int p=central+extra.length;
        while(get32(out,p)==0x02014b50L) { long offset=get32(out,p+42); if(offset>0) put32(out,p+42,offset+extra.length); p+=46+(out[p+28]&255)+((out[p+29]&255)<<8)+(out[p+30]&255)+((out[p+31]&255)<<8)+(out[p+32]&255)+((out[p+33]&255)<<8); }
        put32(out,end+extra.length+16,central+extra.length); return out;
    }
    static ResourceStore.Ready importIt(Env e,byte[] b) throws Exception { return e.store.importArchive(new ByteArrayInputStream(b),null,null); }
    public static void main(String[] args) throws Exception {
        if(args.length>0&&args[0].equals("real")) { realArchives(args); return; }
        if(args.length>0&&args[0].equals("real-pending")) { realPending(args); return; }
        if(args.length>0&&args[0].equals("pending")) { pendingRecoveryTests(); System.out.println("ResourceStore pending recovery tests passed: "+assertions+" assertions"); return; }
        if(args.length>0&&args[0].equals("parser-heap")) { parserHeapTests(args); return; }
        if(args.length==2&&args[0].equals("front-halo")) { frontHaloTests(Paths.get(args[1])); return; }
        Path fixtures=temp("fixtures"); Map<String,byte[]> main=mainFiles(),sides=sideFiles(); ResourceMetadata meta=metadata(sides);
        byte[] original=zip(main,"canonical-a"),repacked=zip(main,"different-container-byte-identity");
        Map<String,byte[]> changed=new TreeMap<String,byte[]>(main); changed.put("root.bin",bytes("root-next")); byte[] next=zip(changed,"canonical-next");
        DataManifest a=manifest(original,"packaged-a"),b=manifest(next,"packaged-b"); DataBaselines baselines=catalog(fixtures,a,b);
        ok(main.size()==1798&&sides.size()==41,"complete production-shaped fixture counts");
        Env empty=new Env("empty",baselines,meta); fails(()->empty.store.resolve(null,null),"no data");
        Env imported=new Env("imported",baselines,meta); ResourceStore.Ready ready=importIt(imported,repacked);
        ok(ready.dataDirectory.getParent().equals(imported.ext.resolve("re3dxplus-imported")),"new imported root");
        ok(ready.optionalDirectory==null&&ready.cardDirectory==null&&ready.optionalFiles.isEmpty(),"optional absent is not main failure");
        ok(imported.store.resolve(null,null).dataDirectory.equals(ready.dataDirectory),"selection retained");
        String selection=new String(Files.readAllBytes(imported.selection()),StandardCharsets.US_ASCII); ok(selection.contains(a.zipSha256)&&!selection.contains(sha(repacked)),"canonical baseline, not container SHA");
        Map<String,byte[]> full=new TreeMap<String,byte[]>(main); full.putAll(sides); full.put("empty-directory/",new byte[0]);
        ResourceStore.Ready fullReady=importIt(imported,zip(full,"full-prepared"));
        ok(fullReady.optionalDirectory.equals(fullReady.dataDirectory)&&fullReady.optionalFiles.size()==4&&fullReady.cardDirectory.equals(fullReady.dataDirectory.resolve("card-resources")),"prepared full main+41 extras");
        ok(Files.exists(ready.dataDirectory.resolve("critical.rsm")),"replacement preserves previous imported root");
        ok(imported.store.resolve(null,null).optionalFiles.size()==4,"sidecar resolve verifies signed copies");
        try { fullReady.optionalFiles.put("other",fullReady.dataDirectory); throw new AssertionError("mutable optional map"); } catch(UnsupportedOperationException expected) { assertions++; }
        try { fullReady.warnings.clear(); throw new AssertionError("mutable warnings"); } catch(UnsupportedOperationException expected) { assertions++; }
        // Damaged selected roots fail closed rather than rediscovering intact older roots.
        byte[] selectedRecord=Files.readAllBytes(imported.selection()); Files.write(fullReady.dataDirectory.resolve("critical.rsm"),new byte[]{1});
        fails(()->imported.store.resolve(null,null),"selected main missing/wrong size"); ok(Arrays.equals(selectedRecord,Files.readAllBytes(imported.selection())),"failed resolve does not change selection");
        ResourceStore.Ready repaired=importIt(imported,original); ok(!repaired.dataDirectory.equals(fullReady.dataDirectory),"explicit repair uses fresh root");
        Files.write(imported.selection(),bytes("broken-selection")); fails(()->imported.store.resolve(null,null),"bad selection is not absent");
        importIt(imported,original); ok(imported.store.resolve(null,null)!=null,"explicit repair can replace corrupt regular selection");
        // Main set is exact, including mandatory .rsm, but compression/container identity is not.
        for(String scenario:new String[]{"missing-rsm","wrong-size","modified","unknown","raw-main","raw-car","raw-prefix-main","raw-prefix-car"}) {
            Map<String,byte[]> bad=new TreeMap<String,byte[]>(main);
            if(scenario.equals("missing-rsm")) bad.remove("critical.rsm");
            if(scenario.equals("wrong-size")) bad.put("critical.rsm",new byte[]{1});
            if(scenario.equals("modified")) bad.put("root.bin",bytes("ROOT-DATA"));
            if(scenario.equals("unknown")) bad.put("player-save.bin",new byte[]{1});
            if(scenario.equals("raw-main")) bad.put("main",new byte[]{1});
            if(scenario.equals("raw-car")) bad.put("data/car/raw.igb",new byte[]{1});
            if(scenario.equals("raw-prefix-main")) bad.put("user/archive/game/main",new byte[]{1});
            if(scenario.equals("raw-prefix-car")) bad.put("user/archive/data/car/raw.igb",new byte[]{1});
            byte[] prior=Files.readAllBytes(imported.selection()),archive=zip(bad,scenario);
            IOException failure=fails(()->importIt(imported,archive),scenario); ok(Arrays.equals(prior,Files.readAllBytes(imported.selection())),scenario+" keeps selection");
            if(scenario.startsWith("raw")) ok(failure.getMessage().contains("原版需要转换"),"explicit original arcade conversion error");
        }
        // Old active inventory must be catalog-exact; no marker required for an active binding.
        Env old=new Env("oldactive",baselines,meta); Path oldData=oldRoot(old,a,main,false); Files.createDirectories(old.noBackup.resolve("game-data-state"));
        a.rebindDirectory(oldData.getFileName().toString()).writeAtomic(old.noBackup.resolve("game-data-state/active.manifest"),null,LIMITS);
        materialize(old.ext.resolve("wmmt"),Collections.singletonMap("player-save.bin",bytes("private-save-sentinel")));
        materialize(old.ext.resolve("re3dxplus-data/unknown-sibling"),Collections.singletonMap("personal",bytes("keep-unknown")));
        Map<String,String> oldBefore=snapshot(old.ext),oldStateBefore=snapshot(old.noBackup.resolve("game-data-state"));
        ok(old.store.resolve(null,null).dataDirectory.equals(oldData),"old active reused");
        unchanged(old.ext,oldBefore,"resolve preserves entire old and save tree"); unchanged(old.noBackup.resolve("game-data-state"),oldStateBefore,"old private state unmodified");
        importIt(old,original); unchanged(old.ext.resolve("re3dxplus-data"),snapshotCopyPrefix(oldBefore,"re3dxplus-data"),"explicit import leaves legacy tree unchanged");
        unchanged(old.ext.resolve("wmmt"),snapshotCopyPrefix(oldBefore,"wmmt"),"explicit import leaves save unchanged"); unchanged(old.noBackup.resolve("game-data-state"),oldStateBefore,"import does not overwrite old active");
        Env badActive=new Env("bad-active",baselines,meta); Path candidate=oldRoot(badActive,a,main,true); Files.createDirectories(badActive.noBackup.resolve("game-data-state")); Files.write(badActive.noBackup.resolve("game-data-state/active.manifest"),bytes("bad"));
        fails(()->badActive.store.resolve(null,null),"bad active cannot fall back to valid marker"); ok(Files.exists(candidate),"bad active candidate preserved");
        Env foreignActive=new Env("foreign-active",baselines,meta); Path foreign=oldRoot(foreignActive,a,main,true); Map<String,byte[]> foreignFiles=new TreeMap<String,byte[]>(main); foreignFiles.remove("critical.rsm");
        DataManifest wrong=manifest(zip(foreignFiles,"foreign"),foreign.getFileName().toString()); Files.createDirectories(foreignActive.noBackup.resolve("game-data-state")); wrong.writeAtomic(foreignActive.noBackup.resolve("game-data-state/active.manifest"),null,LIMITS);
        fails(()->foreignActive.store.resolve(null,null),"unsupported active cannot fall back");
        Env direct=new Env("legacy",baselines,meta); Path legacy=oldRoot(direct,a,main,true); materialize(direct.ext.resolve("re3dxplus-data/unknown"),Collections.singletonMap("save",new byte[]{1}));
        ok(direct.store.resolve(null,null).dataDirectory.equals(legacy),"unique recognized completed legacy reused");
        Path second=oldRoot(direct,b,changed,true); Files.write(second.resolve("root.bin"),new byte[]{0}); fails(()->direct.store.resolve(null,null),"count candidates before verification");
        Env inProgress=new Env("in-progress",baselines,meta); Path interrupted=oldRoot(inProgress,a,main,false); Files.write(interrupted.resolve(MARKER),bytes(ID+":in-progress:"+a.zipSha256+":"+b.zipSha256)); fails(()->inProgress.store.resolve(null,null),"in-progress marker never ready");
        // Strict old pending takes precedence even over an otherwise valid new selection.
        Env pending=new Env("pending",baselines,meta); importIt(pending,original); Files.createDirectories(pending.noBackup.resolve("game-data-state")); Files.write(pending.noBackup.resolve("game-data-state/pending"),bytes("unfinished"));
        Map<String,String> beforePending=snapshot(pending.work); IOException pe=fails(()->pending.store.resolve(null,null),"pending resolve blocks"); ok(pe.getMessage().contains("无需回装"),"pending actionable in-place recovery error"); fails(()->importIt(pending,original),"pending import blocks"); unchanged(pending.work,beforePending,"pending no state changed");
        // Orphan legacy transactions are never silently bypassed, with or without active.
        for(boolean active:new boolean[]{false,true}) for(String artifact:new String[]{"overlay.journal","old.manifest","new.manifest","txn-orphan"}) {
            Env orphan=new Env("orphan",baselines,meta); Path data=oldRoot(orphan,a,main,true),state=orphan.noBackup.resolve("game-data-state"); Files.createDirectories(state);
            if(active) a.rebindDirectory(data.getFileName().toString()).writeAtomic(state.resolve("active.manifest"),null,LIMITS);
            if(artifact.startsWith("txn-")) Files.createDirectory(state.resolve(artifact)); else Files.write(state.resolve(artifact),bytes("unowned-transaction"));
            Map<String,String> before=snapshot(orphan.work); IOException error=fails(()->orphan.store.resolve(null,null),"orphan resolve active="+active);
            ok(error.getMessage().contains("未归属"),"explicit orphan error"); fails(()->importIt(orphan,original),"orphan import blocked active="+active); unchanged(orphan.work,before,"orphan preserved without any mutation");
        }
        // Cancellation applies inside SAF copy, extraction, verification, optional hashing, publication.
        for(String stage:new String[]{"copy-source","extract-main","verify-main","verify-optional","publish"}) {
            byte[] before=Files.readAllBytes(imported.selection()); final boolean[] cancel={false}; byte[] source=zip(full,"cancel-"+stage);
            fails(()->imported.store.importArchive(new ByteArrayInputStream(source),()->cancel[0],(s,c,t)->{if(s.equals(stage))cancel[0]=true;}),"cancel "+stage);
            ok(Arrays.equals(before,Files.readAllBytes(imported.selection())),"cancel keeps old selection "+stage);
            ok(imported.store.resolve(null,null)!=null,"cancel old ready still available "+stage);
        }
        byte[] beforeFault=Files.readAllBytes(imported.selection()); InputStream fault=new InputStream() { int count; public int read() throws IOException { if(++count==100) throw new IOException("simulated read failure"); return count<200?0:-1; } };
        fails(()->imported.store.importArchive(fault,null,null),"SAF read fault"); ok(Arrays.equals(beforeFault,Files.readAllBytes(imported.selection())),"read fault no switch");
        try { imported.store.importArchive(new ByteArrayInputStream(original),null,(s,c,t)->{if(s.equals("publish")) throw new IllegalStateException("simulated interruption");}); throw new AssertionError("fault not hit"); } catch(IllegalStateException expected) { assertions++; }
        ok(Arrays.equals(beforeFault,Files.readAllBytes(imported.selection())),"precommit process fault no switch");
        Method room=ResourceStore.class.getDeclaredMethod("room",Path.class,long.class); room.setAccessible(true);
        try { room.invoke(null,imported.ext,Long.MAX_VALUE); throw new AssertionError("space precheck accepted overflow"); } catch(InvocationTargetException e) { ok(e.getCause() instanceof IOException,"space exhaustion check"); }
        Env leftovers=new Env("leftovers",baselines,meta); materialize(leftovers.ext.resolve("re3dxplus-imported").resolve(UUID.randomUUID().toString()),main); fails(()->leftovers.store.resolve(null,null),"unpublished complete import never auto adopted");
        Map<String,String> leftBefore=snapshot(leftovers.ext); fails(()->leftovers.store.importArchive(new ByteArrayInputStream(original),()->true,null),"cancel before creation"); unchanged(leftovers.ext,leftBefore,"unowned staging not cleaned");
        // Optional sidecars are independent; imported roots never fall back to legacy sidecars.
        Env optional=new Env("optional",baselines,meta); Map<String,byte[]> partial=new TreeMap<String,byte[]>(main); partial.put("story-cutin.bin",sides.get("story-cutin.bin")); partial.put("backfire.wpk",sides.get("backfire.wpk"));
        ResourceStore.Ready part=importIt(optional,zip(partial,"partial")); ok(part.optionalFiles.size()==1&&part.optionalFiles.containsKey("story-cutin.bin"),"individual cutin usable and incomplete backfire disabled");
        materialize(optional.ext.resolve("wmmt-sidecars"),sides); ok(optional.store.resolve(null,null).optionalFiles.size()==1,"no imported fallback");
        Env legacySide=new Env("legacy-side",baselines,meta); oldRoot(legacySide,a,main,true); Path side=legacySide.ext.resolve("wmmt-sidecars");
        materialize(side,new TreeMap<String,byte[]>(sides)); String version=sha(bytes("pair-version")); Path back=side.resolve("backfire-"+version);
        materialize(back,new TreeMap<String,byte[]>(){{put("backfire.wpk",sides.get("backfire.wpk"));put("backfire.bfx",sides.get("backfire.bfx"));}}); Files.write(side.resolve("backfire-current"),bytes(version));
        Map<String,byte[]> cardFiles=new TreeMap<String,byte[]>(); for(String p:ResourceMetadata.CARD_PATHS) cardFiles.put(p.substring(15),sides.get(p));
        Path firstCard=side.resolve("card-resources-v1/ready-one"); materialize(firstCard,cardFiles);
        ResourceStore.Ready ls=legacySide.store.resolve(null,null); ok(ls.optionalFiles.size()==4&&ls.optionalFiles.get("backfire.wpk").getParent().equals(back)&&ls.optionalDirectory==null&&ls.cardDirectory.equals(firstCard),"old split backfire pointer and complete cards reused");
        materialize(side.resolve("card-resources-v1/ready-two"),cardFiles); ok(legacySide.store.resolve(null,null).cardDirectory==null,"multiple valid card copies not guessed");
        Files.write(back.resolve("backfire.bfx"),bytes("corrupt")); ok(legacySide.store.resolve(null,null).optionalFiles.size()==2,"one corrupt backfire disables entire pair");
        // Reject APK bytes even when a provider presents the file as a ZIP.
        Map<String,byte[]> apk=new TreeMap<>();
        apk.put("AndroidManifest.xml",new byte[]{1,2});
        apk.put("classes.dex",new byte[]{9,8});
        apk.put("assets/re3dxplus-data.zip",repacked);
        Env strictZip=new Env("zip-only",baselines,meta);
        ResourceStore.Ready selected=importIt(strictZip,original);
        byte[] beforeApk=Files.readAllBytes(strictZip.selection());
        byte[] unsignedApk=zip(apk,"renamed-to-zip");
        for(byte[] source:new byte[][]{unsignedApk,apkSigningBlock(unsignedApk)}) {
            IOException rejected=fails(()->importIt(strictZip,source),"APK content rejected");
            ok(rejected.getMessage().contains("不能导入 APK"),"APK rejection explains ZIP-only import");
        }
        apk.remove("AndroidManifest.xml");
        fails(()->importIt(strictZip,zip(apk,"nested-without-manifest")),"nested APK wrapper rejected");
        ok(Arrays.equals(beforeApk,Files.readAllBytes(strictZip.selection()))&&
            strictZip.store.resolve(null,null).dataDirectory.equals(selected.dataDirectory),"rejected APKs leave selection usable");
        fails(()->importIt(strictZip,apkSigningBlock(original)),"plain resources cannot imitate APK signing gap");
        fails(()->importIt(strictZip,withLocalExtra(original,new byte[4])),"plain local zero TLV rejected");
        for(int id:new int[]{1,0x7075,0x9901,0x000f,0x0017,0x5455}) {
            byte[] extra={(byte)id,(byte)(id>>>8),0,0};
            fails(()->importIt(strictZip,withLocalExtra(original,extra)),"forbidden/duplicate extra id");
        }
        Map<String,byte[]> unicode=new TreeMap<String,byte[]>(main); unicode.put("caf\u00e9.bin",new byte[]{1}); unicode.put("cafe\u0301.bin",new byte[]{1});
        ok(fails(()->importIt(strictZip,zip(unicode,"nfc")),"NFC aliases").getMessage().contains("ZIP"),"NFC aliases rejected during ZIP structural validation");
        // Bad structures rejected without changing an existing valid selection.
        List<byte[]> badZip=new ArrayList<byte[]>(); badZip.add(Arrays.copyOf(original,original.length-30)); badZip.add(Arrays.copyOf(original,original.length+1));
        badZip.add(replaceHeader(original,8,6,1)); // encrypted flag
        byte[] symlink=original.clone(); int central=firstCentral(symlink); symlink[central+5]=3; put32(symlink,central+38,0120777L<<16); badZip.add(symlink);
        byte[] crc=original.clone(); int cp=firstCentral(crc); crc[cp+16]^=1; badZip.add(crc);
        for(String name:new String[]{"../escape","/absolute","C:/drive","data/../escape","a\\b","ROOT.BIN","root.bin/child"}) { Map<String,byte[]> mal=new TreeMap<String,byte[]>(main); mal.put(name,new byte[]{1}); badZip.add(zip(mal,"unsafe")); }
        Map<String,byte[]> fileDir=new LinkedHashMap<String,byte[]>(); fileDir.put("conflict/child",new byte[]{1}); fileDir.put("conflict",new byte[]{1}); badZip.add(zip(fileDir,"file-dir-conflict"));
        byte[] bomb=original.clone(); put32(bomb,firstCentral(bomb)+24,0xfffffffeL); badZip.add(bomb);
        byte[] beforeBad=Files.readAllBytes(strictZip.selection()); for(byte[] z:badZip) { fails(()->importIt(strictZip,z),"hostile ZIP"); ok(Arrays.equals(beforeBad,Files.readAllBytes(strictZip.selection())),"hostile ZIP no switch"); }
        // NOFOLLOW at every path segment for main, state, selected roots and sidecars.
        Env links=new Env("links",baselines,meta); Path linkRoot=oldRoot(links,a,main,true); Path retained=links.work.resolve("retained-rsm"); Files.move(linkRoot.resolve("critical.rsm"),retained); Files.createSymbolicLink(linkRoot.resolve("critical.rsm"),retained);
        fails(()->links.store.resolve(null,null),"legacy main symlink");
        Env stateLink=new Env("selection-link",baselines,meta); importIt(stateLink,original); Path originalSelection=stateLink.work.resolve("selection-retained"); Files.move(stateLink.selection(),originalSelection); Files.createSymbolicLink(stateLink.selection(),originalSelection);
        fails(()->stateLink.store.resolve(null,null),"selection symlink"); fails(()->importIt(stateLink,original),"repair must not replace symlink selection");
        // Metadata: canonical sorted unique whitelist, stream ownership and hard bounds.
        final boolean[] closed={false}; InputStream metaStream=new ByteArrayInputStream(bytes("WMMT-SIDECARS-1\n")) { public void close(){closed[0]=true;} }; ResourceMetadata.read(metaStream); ok(!closed[0],"metadata caller stream remains open");
        for(String bad:new String[]{"", "WMMT-SIDECARS-1\r\n", "WMMT-SIDECARS-1\n../save\t1\t"+sha(new byte[]{1})+"\n", "WMMT-SIDECARS-1\nstory-cutin.bin\t01\t"+sha(new byte[]{1})+"\n", "WMMT-SIDECARS-1\nstory-cutin.bin\t1\t"+sha(new byte[]{1}).toUpperCase(Locale.ROOT)+"\n"}) fails(()->ResourceMetadata.read(new ByteArrayInputStream(bytes(bad))),"bad metadata");
        fails(()->ResourceMetadata.read(new ByteArrayInputStream(new byte[65537])),"metadata bounds");
        String dup="WMMT-SIDECARS-1\nstory-cutin.bin\t1\t"+sha(new byte[]{1})+"\nstory-cutin.bin\t1\t"+sha(new byte[]{1})+"\n"; fails(()->ResourceMetadata.read(new ByteArrayInputStream(bytes(dup))),"metadata duplicate");
        pendingRecoveryTests();
        clearResourceTests(baselines,meta,original);
        System.out.println("ResourceStore host tests passed: "+assertions+" assertions; all artifacts retained under "+WORK);
    }

    private static void frontHaloTests(Path sidecarDirectory) throws Exception {
        Path fixtures=temp("front-halo-fixtures");
        Map<String,byte[]> main=mainFiles();
        DataManifest baseline=manifest(zip(main,"front-halo-main"),"approved-main");
        DataBaselines baselines=catalog(fixtures,baseline);
        Env imported=new Env("front-halo",baselines,metadata(sideFiles()));
        Map<String,byte[]> files=new TreeMap<String,byte[]>(main);
        files.put("front_halo.wpk",Files.readAllBytes(sidecarDirectory.resolve("front_halo.wpk")));
        ResourceStore.Ready partial=importIt(imported,zip(files,"missing-locators"));
        ok(partial.optionalFiles.isEmpty(),"partial front halo pair is unavailable");
        files.put("front_halo.bin",Files.readAllBytes(sidecarDirectory.resolve("front_halo.bin")));
        ResourceStore.Ready complete=importIt(imported,zip(files,"complete-front-halo"));
        ok(complete.optionalFiles.keySet().equals(new TreeSet<>(Arrays.asList("front_halo.bin","front_halo.wpk"))),
                "verified front halo pair is exposed");
        ok(imported.store.resolve(null,null).optionalFiles.equals(complete.optionalFiles),"ready re-verifies the pair");
        byte[] altered=files.get("front_halo.bin"); altered[altered.length-1]^=1;
        ResourceStore.Ready corrupted=importIt(imported,zip(files,"changed-locators"));
        ok(corrupted.optionalFiles.isEmpty(),"same-size altered locator payload disables the pair");
        ok(imported.store.resolve(null,null).optionalFiles.isEmpty(),"changed payload stays unavailable on reopen");
        System.out.println("ResourceStore front halo tests passed: "+assertions+" assertions");
    }
    static void clearResourceTests(DataBaselines baselines, ResourceMetadata meta, byte[] archive) throws Exception {
        Env env=new Env("clear",baselines,meta);
        ResourceStore.Ready installed=importIt(env,archive);
        Path saves=env.ext.resolve("wmmt");
        materialize(saves,Collections.singletonMap("garage-and-pb.bin",bytes("save")));
        String[] records={"ta-ranking-v1","ghost-crown-v1","cloud-ghost-outbox-v1","unrelated"};
        for (String dir : records)
            materialize(env.noBackup.resolve(dir),Collections.singletonMap("record",bytes(dir)));
        Map<String,String> saveBefore=snapshot(saves), privateBefore=snapshot(env.noBackup);
        privateBefore.keySet().removeIf(name->name.equals("resource-import-v1") || name.startsWith("resource-import-v1/"));
        for (String dir : new String[]{"re3dxplus-data","re3dxplus-original","wmmt-sidecars"})
            materialize(env.ext.resolve(dir),Collections.singletonMap("nested/resource",bytes(dir)));
        for (String dir : new String[]{"re3dxplus-original-jobs","original-convert-ui-v1","original-convert-v1",
                "resource-choice-v2","game-data-state","ghost-ui-v1","builtin-ghosts-v1"})
            materialize(env.noBackup.resolve(dir),Collections.singletonMap("partial/resource",bytes(dir)));
        Files.createSymbolicLink(installed.dataDirectory.resolve("save-link"),saves);

        Path pending=env.noBackup.resolve("resource-clear.pending");
        Files.createFile(pending);
        ok(fails(()->env.store.resolve(null,null),"interrupted clear blocks resolve").getMessage().contains("清除资源包"),
                "interrupted clear reports retry");
        fails(()->importIt(env,archive),"interrupted clear blocks imports");
        ResourceStore.clearInstalledResources(env.ext,env.noBackup);
        unchanged(saves,saveBefore,"clear preserves save bytes even when resources contain a link to saves");
        unchanged(env.noBackup,privateBefore,"clear preserves rankings, crowns and other non-resource private data");
        ok(snapshot(env.ext).size()==3,"clear removes every external resource root");
        fails(()->env.store.resolve(null,null),"cleared resources cannot be reused");
        ResourceStore.clearInstalledResources(env.ext,env.noBackup);
        ok(importIt(env,archive)!=null,"resource ZIP reimport works after clear and retry");
        Map<String,String> before=snapshot(env.work);
        Path unsafe=env.ext.resolve("re3dxplus-original");
        Files.createSymbolicLink(unsafe,saves);
        fails(()->ResourceStore.clearInstalledResources(env.ext,env.noBackup),"linked resource root rejected");
        Files.delete(unsafe);
        unchanged(env.work,before,"linked root fails before deleting anything");
    }
    /** Reflection only crosses package visibility; constructor Errors are rethrown, never swallowed. */
    static int openZipMetadata(Path file,ResourceStore.Cancel cancel) throws Exception {
        Class<?> type=Class.forName("com.wmmt.port.SafeResourceZip");
        Constructor<?> constructor=type.getDeclaredConstructor(Path.class,int.class,long.class,ResourceStore.Cancel.class); constructor.setAccessible(true);
        Object reader;
        try { reader=constructor.newInstance(file,16384,50L*1024*1024*1024,cancel); }
        catch(InvocationTargetException failed) {
            Throwable cause=failed.getCause(); if(cause instanceof Exception) throw (Exception)cause; if(cause instanceof Error) throw (Error)cause; throw new AssertionError(cause);
        }
        try(Closeable ignored=(Closeable)reader) { Field members=type.getDeclaredField("members"); members.setAccessible(true); return ((Map<?,?>)members.get(reader)).size(); }
    }
    static Path storedMetadataFixture(Path work,String file,int count,java.util.function.IntFunction<String> names) throws Exception {
        Path target=work.resolve(file);
        try(ZipOutputStream out=new ZipOutputStream(Files.newOutputStream(target,StandardOpenOption.CREATE_NEW))) {
            for(int i=0;i<count;i++) { ZipEntry entry=new ZipEntry(names.apply(i)); entry.setMethod(ZipEntry.STORED); entry.setSize(0); entry.setCompressedSize(0); entry.setCrc(0); out.putNextEntry(entry); out.closeEntry(); }
        }
        return target;
    }
    /** parser-heap <independent deep fixture> <real APK> <real prepared ZIP>, with -Xmx32m.
     * Opens headers/central metadata only: no ResourceStore calls and no payload decoding. */
    static void parserHeapTests(String[] args) throws Exception {
        if(args.length!=4) throw new IllegalArgumentException("parser-heap deepFixture realAPK realPreparedZIP");
        long start=System.nanoTime(); System.out.println("PARSER_ONLY max_heap="+Runtime.getRuntime().maxMemory());
        ok(Runtime.getRuntime().maxMemory()<=32L*1024*1024,"run parser-only regression with -Xmx32m");
        Path deep=Paths.get(args[1]),work=temp("parser-heap"); ok(Files.size(deep)==197302,"original independent 197302-byte fixture unchanged");
        IOException depth=fails(()->openZipMetadata(deep,null),"deep stored empty entries rejected without OOM"); ok(depth.getMessage().contains("64"),"controlled depth-budget IOException");
        StringBuilder component=new StringBuilder(); for(int i=0;i<126;i++) component.append('a'); final String longPart=component.toString();
        Path chars=storedMetadataFixture(work,"shallow-unique-prefixes.zip",64,index->{
            StringBuilder name=new StringBuilder(String.format(Locale.ROOT,"root%03d/",index)); for(int i=0;i<30;i++) name.append(longPart).append('/'); return name.append("file").toString();
        });
        IOException aggregate=fails(()->openZipMetadata(chars,null),"shallow unique prefixes exceed aggregate path budget"); ok(aggregate.getMessage().contains("字符总量"),"controlled aggregate-character IOException, not depth rejection");
        Path nodes=storedMetadataFixture(work,"many-unique-prefix-nodes.zip",11000,index->String.format(Locale.ROOT,"r%05d/a/b/c/file",index));
        IOException nodeLimit=fails(()->openZipMetadata(nodes,null),"short names exceed aggregate index-node budget"); ok(nodeLimit.getMessage().contains("节点总量"),"controlled aggregate-node IOException");
        Path shared=storedMetadataFixture(work,"shared-prefixes.zip",100,index->{StringBuilder name=new StringBuilder("shared/");for(int i=0;i<30;i++)name.append(longPart).append('/');return name.append(String.format(Locale.ROOT,"file%03d",index)).toString();});
        ok(openZipMetadata(shared,null)==100,"shared directory prefixes are charged only on unique insertion per index");
        final int[] checks={0}; IOException cancelled=fails(()->openZipMetadata(chars,()->++checks[0]>=3),"inner prefix traversal cancellation"); ok(cancelled instanceof InterruptedIOException,"inner prefix traversal observes cancellation");
        fails(()->openZipMetadata(Paths.get(args[2]),null),"real old APK metadata rejected");
        ok(openZipMetadata(Paths.get(args[3]),null)==1839,"real 1798-main plus41-sidecar prepared metadata still accepted");
        System.out.println("PARSER_HEAP_PASS assertions="+assertions+" elapsed_s="+(System.nanoTime()-start)/1e9+" deep_bytes="+Files.size(deep)+" shallow_bytes="+Files.size(chars)+" node_bytes="+Files.size(nodes)+" fixture="+work);
    }
    static Path pendingRoot(Env env) throws Exception {
        String[] record=new String(Files.readAllBytes(env.noBackup.resolve("game-data-state/pending")),StandardCharsets.US_ASCII).split("\n",-1);
        DataManifest next=DataManifest.read(env.noBackup.resolve("game-data-state/txn-"+record[1]+"/new.manifest"),LIMITS);
        return env.ext.resolve("re3dxplus-data").resolve(next.resourceDirectory);
    }
    static void pendingRecoveryTests() throws Exception {
        Map<String,byte[]> oldFiles=new TreeMap<String,byte[]>(),newFiles=new TreeMap<String,byte[]>();
        oldFiles.put("critical.rsm",bytes("old-rsm")); oldFiles.put("data/keep.bin",bytes("old-keep")); oldFiles.put("old-only.bin",bytes("old-owned"));
        newFiles.put("critical.rsm",bytes("new-rsm")); newFiles.put("data/keep.bin",bytes("new-keep")); newFiles.put("new-only.bin",bytes("new-owned"));
        byte[] oldZip=zip(oldFiles,"pending-old"),newZip=zip(newFiles,"pending-exact"); DataManifest old=manifest(oldZip,"old"),next=manifest(newZip,"next");
        DataBaselines history=catalog(temp("pending-catalog"),old,next); ResourceMetadata meta=metadata(sideFiles());
        // Init and update cover pre-overlay, mid-resource and post-manifest-commit recovery.
        for(boolean initial:new boolean[]{true,false}) for(String stage:new String[]{"after-pending","overlay:after-replace","after-commit","before-marker-publish"}) {
            Env env=new Env("pending-exact",history,meta); ResourceStore.Ready prior=importIt(env,oldZip); byte[] selectionBefore=Files.readAllBytes(env.selection());
            DataCoordinator coordinator=new DataCoordinator(env.ext.resolve("re3dxplus-data"),env.noBackup.resolve("game-data-state"),LIMITS);
            if(!initial) coordinator.prepare(()->new ByteArrayInputStream(oldZip),null);
            fails(()->coordinator.prepare(()->new ByteArrayInputStream(newZip),s->{if(s.equals(stage))throw new IOException("registered interruption");}),"create pending "+initial+stage);
            Path root=pendingRoot(env); materialize(env.ext.resolve("wmmt"),Collections.singletonMap("save",bytes("keep-save"))); materialize(env.ext.resolve("re3dxplus-data/unknown-sibling"),Collections.singletonMap("personal",bytes("keep-unknown")));
            if(Files.isDirectory(root)) Files.write(root.resolve("personal"),bytes("root-user-file"));
            Map<String,String> saveBefore=snapshot(env.ext.resolve("wmmt")),unknownBefore=snapshot(env.ext.resolve("re3dxplus-data/unknown-sibling"));
            fails(()->env.store.resolve(null,null),"pending blocks even existing imported selection");
            ResourceStore.Ready repaired=importIt(env,newZip);
            ok(!Files.exists(env.noBackup.resolve("game-data-state/pending")),"exact ZIP completes registered pending");
            DataManifest active=DataManifest.read(env.noBackup.resolve("game-data-state/active.manifest"),LIMITS); ok(active.zipSha256.equals(next.zipSha256),"registered active advances only through coordinator");
            for(DataManifest.Entry e:next.files().values()) ok(fileSha(root.resolve(e.path)).equals(e.sha256),"restored registered main hash");
            ok(repaired.dataDirectory.equals(env.store.resolve(null,null).dataDirectory)&&!repaired.dataDirectory.equals(root),"explicit validated import published after recovery");
            ok(!Arrays.equals(selectionBefore,Files.readAllBytes(env.selection()))&&Files.exists(prior.dataDirectory.resolve("critical.rsm")),"previous import preserved and explicit source selected");
            unchanged(env.ext.resolve("wmmt"),saveBefore,"recovery preserves save"); unchanged(env.ext.resolve("re3dxplus-data/unknown-sibling"),unknownBefore,"recovery preserves unknown siblings");
            if(Files.exists(root.resolve("personal"))) ok(new String(Files.readAllBytes(root.resolve("personal")),StandardCharsets.UTF_8).equals("root-user-file"),"registered root unknown user file retained");
        }
        Env wrong=new Env("pending-reject",history,meta); importIt(wrong,oldZip); DataCoordinator wc=new DataCoordinator(wrong.ext.resolve("re3dxplus-data"),wrong.noBackup.resolve("game-data-state"),LIMITS); wc.prepare(()->new ByteArrayInputStream(oldZip),null);
        fails(()->wc.prepare(()->new ByteArrayInputStream(newZip),s->{if(s.equals("after-pending"))throw new IOException("interrupt");}),"wrong-source pending setup");
        materialize(wrong.ext.resolve("wmmt"),Collections.singletonMap("save",bytes("save"))); Path oldState=wrong.noBackup.resolve("game-data-state"); byte[] beforeSelection=Files.readAllBytes(wrong.selection());
        Map<String,String> beforeLegacy=snapshot(wrong.ext.resolve("re3dxplus-data")),beforePrivate=snapshot(oldState),beforeSave=snapshot(wrong.ext.resolve("wmmt"));
        Map<String,byte[]> prepared=new TreeMap<String,byte[]>(newFiles); prepared.putAll(sideFiles());
        byte[] rezip=zip(newFiles,"recompressed-same-files"),preparedZip=zip(prepared,"prepared-with-sidecars");
        Map<String,byte[]> unknown=new TreeMap<String,byte[]>(newFiles); unknown.put("unknown.bin",new byte[]{1});
        for(byte[] source:new byte[][]{oldZip,rezip,preparedZip,zip(unknown,"unknown")}) {
            fails(()->importIt(wrong,source),"wrong or repacked pending source rejected"); unchanged(wrong.ext.resolve("re3dxplus-data"),beforeLegacy,"wrong source no old resource mutation"); unchanged(oldState,beforePrivate,"wrong source no old transaction mutation"); ok(Arrays.equals(beforeSelection,Files.readAllBytes(wrong.selection())),"wrong source no selection mutation");
        }
        Map<String,byte[]> wrapped=new TreeMap<>();
        wrapped.put("AndroidManifest.xml",bytes("old-apk"));
        wrapped.put("assets/re3dxplus-data.zip",newZip);
        fails(()->importIt(wrong,zip(wrapped,"apk-with-exact-main")),"APK rejected even with exact pending recovery ZIP");
        unchanged(oldState,beforePrivate,"APK rejection retains pending snapshots");
        ok(Arrays.equals(beforeSelection,Files.readAllBytes(wrong.selection())),"APK rejection leaves selection intact");
        final boolean[] cancelled={false};
        IOException cancellation=fails(()->wrong.store.importArchive(new ByteArrayInputStream(newZip),()->cancelled[0],(s,c,t)->{if(s.equals("recover-old:overlay:after-replace"))cancelled[0]=true;}),"cancel controlled mid-recovery");
        ok(cancellation instanceof InterruptedIOException&&!cancellation.getMessage().contains("保持不变"),"recovery cancellation does not falsely promise unchanged resources");
        ok(Files.exists(oldState.resolve("pending"))&&Arrays.equals(beforeSelection,Files.readAllBytes(wrong.selection())),"cancel retains registered pending and old selection"); unchanged(wrong.ext.resolve("wmmt"),beforeSave,"cancelled recovery preserves save");
        ResourceStore.Ready retried=importIt(wrong,newZip); ok(!Files.exists(oldState.resolve("pending"))&&wrong.store.resolve(null,null).dataDirectory.equals(retried.dataDirectory),"same exact ZIP retries recovery after cancellation");
        // An exact original main ZIP is also sufficient; full APK installation is unnecessary.
        Env direct=new Env("pending-direct-main",history,meta); DataCoordinator dc=new DataCoordinator(direct.ext.resolve("re3dxplus-data"),direct.noBackup.resolve("game-data-state"),LIMITS);
        fails(()->dc.prepare(()->new ByteArrayInputStream(newZip),s->{if(s.equals("after-pending"))throw new IOException("interrupt");}),"direct pending setup");
        ok(importIt(direct,newZip)!=null&&!Files.exists(direct.noBackup.resolve("game-data-state/pending")),"exact original main ZIP restores init pending");
        // A damaged snapshot or mismatched active never reaches coordinator init-root creation.
        Env journal=new Env("pending-bad-journal",history,meta); DataCoordinator jc=new DataCoordinator(journal.ext.resolve("re3dxplus-data"),journal.noBackup.resolve("game-data-state"),LIMITS); jc.prepare(()->new ByteArrayInputStream(oldZip),null);
        fails(()->jc.prepare(()->new ByteArrayInputStream(newZip),s->{if(s.equals("after-pending"))throw new IOException("interrupt");}),"bad journal setup"); Files.write(journal.noBackup.resolve("game-data-state/overlay.journal"),bytes("foreign-journal")); Map<String,String> beforeBadJournal=snapshot(journal.work); fails(()->importIt(journal,newZip),"foreign overlay rejected before marker invalidation"); unchanged(journal.work,beforeBadJournal,"foreign overlay no old marker/data/state changes");
        Env damaged=new Env("pending-damaged-snapshot",history,meta); DataCoordinator sc=new DataCoordinator(damaged.ext.resolve("re3dxplus-data"),damaged.noBackup.resolve("game-data-state"),LIMITS);
        fails(()->sc.prepare(()->new ByteArrayInputStream(newZip),s->{if(s.equals("after-pending"))throw new IOException("interrupt");}),"damaged snapshot setup"); String[] record=new String(Files.readAllBytes(damaged.noBackup.resolve("game-data-state/pending")),StandardCharsets.US_ASCII).split("\n",-1); Files.write(damaged.noBackup.resolve("game-data-state/txn-"+record[1]+"/new.manifest"),bytes("changed-snapshot")); Map<String,String> damagedBefore=snapshot(damaged.work); fails(()->importIt(damaged,newZip),"damaged new snapshot rejected"); unchanged(damaged.work,damagedBefore,"damaged snapshot no old tree or private mutations");
        Env bad=new Env("pending-invalid",history,meta); DataCoordinator bc=new DataCoordinator(bad.ext.resolve("re3dxplus-data"),bad.noBackup.resolve("game-data-state"),LIMITS);
        fails(()->bc.prepare(()->new ByteArrayInputStream(newZip),s->{if(s.equals("after-pending"))throw new IOException("interrupt");}),"invalid pending setup");
        Path bound=pendingRoot(bad); Files.write(bad.noBackup.resolve("game-data-state/active.manifest"),bytes("bad-active")); Map<String,String> invalidBefore=snapshot(bad.work); fails(()->importIt(bad,newZip),"invalid registered active rejected before recovery"); unchanged(bad.work,invalidBefore,"invalid pending causes no mutation or init directory creation"); ok(!Files.exists(bound),"invalid init target never created");
    }
    /** real-pending <APK> <catalog> <metadata> <verified original main ZIP cache>. */
    static void realPending(String[] args) throws Exception {
        if(args.length!=5) throw new IllegalArgumentException("real-pending APK catalog metadata original-main-ZIP");
        long start=System.nanoTime(); DataBaselines history; ResourceMetadata meta; Path apk=Paths.get(args[1]),main=Paths.get(args[4]);
        try(InputStream in=Files.newInputStream(Paths.get(args[2]))) { history=DataBaselines.read(in,LIMITS); }
        try(InputStream in=Files.newInputStream(Paths.get(args[3]))) { meta=ResourceMetadata.read(in); }
        Env env=new Env("real-pending",history,meta); System.out.println("REAL_PENDING_FIXTURE "+env.work);
        DataCoordinator coordinator=new DataCoordinator(env.ext.resolve("re3dxplus-data"),env.noBackup.resolve("game-data-state"),LIMITS);
        fails(()->coordinator.prepare(()->Files.newInputStream(main),s->{if(s.equals("after-pending"))throw new IOException("simulated old APK interruption");}),"real registered init interruption");
        Path legacy=pendingRoot(env); Files.createDirectories(legacy); Files.write(legacy.resolve("personal"),bytes("unknown-root-file"));
        materialize(env.ext.resolve("wmmt"),Collections.singletonMap("save",bytes("save-unchanged"))); materialize(env.ext.resolve("re3dxplus-data/unknown-sibling"),Collections.singletonMap("personal",bytes("unknown-sibling")));
        Map<String,String> beforeSave=snapshot(env.ext.resolve("wmmt")),beforeUnknown=snapshot(env.ext.resolve("re3dxplus-data/unknown-sibling"));
        System.out.println("REAL_PENDING_REGISTERED elapsed_s="+(System.nanoTime()-start)/1e9); fails(()->env.store.resolve(null,null),"real pending resolve blocked");
        long[] last={0}; ResourceStore.Progress progress=(stage,current,total)->{long now=System.nanoTime(); if(now-last[0]>5_000_000_000L || stage.equals("publish")) {last[0]=now;System.out.println("REAL_PENDING_PROGRESS elapsed_s="+(now-start)/1e9+" stage="+stage+" current="+current+" total="+total);}};
        fails(()->{try(InputStream in=Files.newInputStream(apk)) { env.store.importArchive(in,null,progress); }},"real legacy APK refused");
        long began=System.nanoTime(); ResourceStore.Ready selected; try(InputStream in=Files.newInputStream(main)) { selected=env.store.importArchive(in,null,progress); }
        System.out.println("REAL_PENDING_IMPORT_RECOVER_OK duration_s="+(System.nanoTime()-began)/1e9+" imported="+selected.dataDirectory+" registered="+legacy);
        ok(!Files.exists(env.noBackup.resolve("game-data-state/pending")),"real pending removed by coordinator confirmation");
        DataManifest active=DataManifest.read(env.noBackup.resolve("game-data-state/active.manifest"),LIMITS); ok(history.find(active.zipSha256)!=null&&active.files().size()==1798,"real recovery active is supported catalog inventory");
        for(DataManifest.Entry entry:active.files().values()) ok(Files.size(legacy.resolve(entry.path))==entry.length&&fileSha(legacy.resolve(entry.path)).equals(entry.sha256),"real registered recovery full SHA");
        ok(!selected.dataDirectory.equals(legacy)&&selected.optionalFiles.isEmpty()&&selected.cardDirectory==null,"real explicit main ZIP source selected after recovery");
        ok(env.store.resolve(null,progress).dataDirectory.equals(selected.dataDirectory),"real post-recovery independent resolve");
        unchanged(env.ext.resolve("wmmt"),beforeSave,"real recovery save preserved"); unchanged(env.ext.resolve("re3dxplus-data/unknown-sibling"),beforeUnknown,"real recovery unknown sibling preserved"); ok(new String(Files.readAllBytes(legacy.resolve("personal")),StandardCharsets.UTF_8).equals("unknown-root-file"),"real recovery unknown root file preserved");
        System.out.println("REAL_PENDING_ACCEPTANCE_PASS assertions="+assertions+" elapsed_s="+(System.nanoTime()-start)/1e9+" fixture="+env.work);
    }
    /** Optional full static acceptance: real <APK> <prepared ZIP> <catalog> <metadata>. */
    static void realArchives(String[] args) throws Exception {
        if(args.length!=5) throw new IllegalArgumentException("real APK preparedZIP catalog metadata");
        long started=System.nanoTime(); Path apkPath=Paths.get(args[1]),preparedPath=Paths.get(args[2]); DataBaselines history; ResourceMetadata meta;
        try(InputStream in=Files.newInputStream(Paths.get(args[3]))) { history=DataBaselines.read(in,LIMITS); }
        try(InputStream in=Files.newInputStream(Paths.get(args[4]))) { meta=ResourceMetadata.read(in); }
        Env env=new Env("real-repair",history,meta); System.out.println("REAL_FIXTURE "+env.work);
        DataManifest baseline; String nestedHash;
        try(ZipFile apk=new ZipFile(apkPath.toFile())) {
            ZipEntry nested=apk.getEntry("assets/re3dxplus-data.zip"); MessageDigest digest=MessageDigest.getInstance("SHA-256"); byte[] buffer=new byte[65536];
            try(InputStream in=apk.getInputStream(nested)) { int n; while((n=in.read(buffer))!=-1) if(n>0) digest.update(buffer,0,n); }
            StringBuilder hash=new StringBuilder(); for(byte b:digest.digest()) hash.append(String.format(Locale.ROOT,"%02x",b&255)); nestedHash=hash.toString(); baseline=history.find(nestedHash);
            ok(baseline!=null&&baseline.files().size()==1798,"real APK known complete baseline");
            String missing=null; for(String name:baseline.files().keySet()) if(name.equals("wheels/rsm_high.wpk") || name.endsWith(".rsm")) { missing=name; break; } ok(missing!=null,"real rsm fixture exists");
            Path legacy=env.ext.resolve("re3dxplus-data").resolve(nestedHash+"-"+UUID.randomUUID()); Files.createDirectories(legacy);
            int count=0; long decoded=0;
            try(ZipInputStream zip=new ZipInputStream(apk.getInputStream(nested))) {
                ZipEntry entry; while((entry=zip.getNextEntry())!=null) {
                    if(entry.isDirectory()) { zip.closeEntry(); continue; } DataManifest.Entry spec=baseline.files().get(entry.getName()); ok(spec!=null,"real nested entry in signed catalog");
                    if(!entry.getName().equals(missing)) { Path dest=legacy.resolve(entry.getName()); Files.createDirectories(dest.getParent()); long copied=Files.copy(zip,dest); ok(copied==spec.length,"real legacy exact length"); }
                    else while(zip.read(buffer)!=-1) { /* consume omitted rsm fixture */ }
                    decoded+=spec.length; count++; zip.closeEntry();
                }
            }
            ok(count==1798&&decoded==2281599278L,"real complete source count and decoded bytes"); Files.write(legacy.resolve(MARKER),bytes(ID+":"+nestedHash));
            materialize(env.ext.resolve("wmmt"),Collections.singletonMap("player-save.bin",bytes("save-unchanged-sentinel")));
            materialize(env.ext.resolve("re3dxplus-data/unrecognized"),Collections.singletonMap("personal",bytes("unknown-unchanged-sentinel")));
            System.out.println("LEGACY_MISSING_RSM_READY elapsed_s="+(System.nanoTime()-started)/1e9+" main_bytes="+decoded+" missing="+missing);
            fails(()->env.store.resolve(null,null),"real unregistered missing-rsm legacy rejected");
            Files.createDirectories(env.noBackup.resolve("game-data-state")); baseline.rebindDirectory(legacy.getFileName().toString()).writeAtomic(env.noBackup.resolve("game-data-state/active.manifest"),null,LIMITS);
            fails(()->env.store.resolve(null,null),"real registered missing-rsm legacy rejected");
            Map<String,String> beforeLegacy=snapshot(env.ext.resolve("re3dxplus-data")),beforeSave=snapshot(env.ext.resolve("wmmt")),beforePrivate=snapshot(env.noBackup.resolve("game-data-state"));
            long[] last={0}; ResourceStore.Progress progress=(stage,current,total)->{long now=System.nanoTime(); if(now-last[0]>5_000_000_000L || stage.equals("publish")) {last[0]=now;System.out.println("PROGRESS elapsed_s="+(now-started)/1e9+" stage="+stage+" current="+current+" total="+total);}};
            long began=System.nanoTime(); ResourceStore.Ready repaired;
            fails(()->{try(InputStream in=Files.newInputStream(apkPath)) { env.store.importArchive(in,null,progress); }},"real old APK refused without selection");
            ok(!Files.exists(env.selection()),"real old APK rejection did not select resources");
            try(InputStream in=Files.newInputStream(preparedPath)) { repaired=env.store.importArchive(in,null,progress); }
            System.out.println("REAL_ZIP_REPAIR_OK duration_s="+(System.nanoTime()-began)/1e9+" root="+repaired.dataDirectory);
            ok(!repaired.dataDirectory.equals(legacy)&&Files.isRegularFile(repaired.dataDirectory.resolve(missing)),"real missing rsm repaired into NEW root");
            ok(repaired.optionalFiles.size()==4&&repaired.cardDirectory!=null&&repaired.warnings.stream().noneMatch(w->w.startsWith("缺少完整卡片")),"real signed sidecar all4 plus37 enabled");
            began=System.nanoTime(); ResourceStore.Ready resolved=env.store.resolve(null,progress); ok(resolved.dataDirectory.equals(repaired.dataDirectory)&&resolved.optionalFiles.size()==4&&resolved.cardDirectory!=null,"real ZIP independent resolve full hash");
            System.out.println("REAL_ZIP_REPAIR_RESOLVE_OK duration_s="+(System.nanoTime()-began)/1e9);
            unchanged(env.ext.resolve("re3dxplus-data"),beforeLegacy,"real legacy and unknown tree byte-identical after repair"); unchanged(env.ext.resolve("wmmt"),beforeSave,"real save unchanged"); unchanged(env.noBackup.resolve("game-data-state"),beforePrivate,"real old active unchanged");
            byte[] oldSelection=Files.readAllBytes(env.selection()); began=System.nanoTime(); ResourceStore.Ready plain;
            try(InputStream in=Files.newInputStream(preparedPath)) { plain=env.store.importArchive(in,null,progress); }
            System.out.println("REAL_PREPARED_IMPORT_OK duration_s="+(System.nanoTime()-began)/1e9+" root="+plain.dataDirectory);
            ok(!plain.dataDirectory.equals(repaired.dataDirectory)&&plain.optionalFiles.size()==4&&plain.cardDirectory!=null&&plain.warnings.stream().noneMatch(w->w.startsWith("缺少完整卡片")),"real prepared main and41 sidecars");
            ok(!Arrays.equals(oldSelection,Files.readAllBytes(env.selection()))&&Files.isRegularFile(repaired.dataDirectory.resolve(missing)),"real previous import root retained");
            began=System.nanoTime(); ok(env.store.resolve(null,progress).dataDirectory.equals(plain.dataDirectory),"real prepared independent resolve full hash"); System.out.println("REAL_PREPARED_RESOLVE_OK duration_s="+(System.nanoTime()-began)/1e9);
            unchanged(env.ext.resolve("re3dxplus-data"),beforeLegacy,"real plain import does not change legacy"); unchanged(env.ext.resolve("wmmt"),beforeSave,"real plain import does not change save"); unchanged(env.noBackup.resolve("game-data-state"),beforePrivate,"real plain import does not change old active");
            System.out.println("REAL_ACCEPTANCE_PASS assertions="+assertions+" elapsed_s="+(System.nanoTime()-started)/1e9+" fixture="+env.work+" canonical="+nestedHash);
        }
    }
    static Map<String,String> snapshotCopyPrefix(Map<String,String> map,String prefix) {
        Map<String,String> result=new TreeMap<String,String>(); for(Map.Entry<String,String> e:map.entrySet()) if(e.getKey().equals(prefix)||e.getKey().startsWith(prefix+"/")) result.put(e.getKey().equals(prefix)?"":e.getKey().substring(prefix.length()+1),e.getValue()); return result;
    }
}
