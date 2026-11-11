package com.wmmt.port;

import java.io.*;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.security.*;
import java.util.*;

/** Independent import/selection state. Caller MUST hold the existing ProcessLock for
 * every operation and through native shutdown. Noncooperating writers are out of scope.
 * Ordinary repair never changes legacy trees; only an already-registered pending
 * transaction may be resumed by DataCoordinator after exact-source authentication.
 * Save trees are never touched, and import leftovers are never adopted. */
public final class ResourceStore {
    static final long SOURCE_LIMIT=2L*1024*1024*1024;
    private static final long MAIN_LIMIT=50L*1024*1024*1024, EXTRA_LIMIT=1024L*1024*1024;
    private static final long RESERVE=64L*1024*1024;
    private static final String ID="re3dxplus-data-v1", MARKER=".re3dxplus-install-v1", SELECTION="selection";
    private static final String UUID_PATTERN="[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
    private static final String CLEAR_PENDING="resource-clear.pending";
    private static final String COMPANION_SELECTION="companion-selection";
    private final Path external,noBackup,state,oldState,legacy,imported,companions;
    private final DataManifest.Limits limits;
    private final DataBaselines baselines;
    private final ResourceMetadata metadata;
    public interface Cancel { boolean cancelled(); }
    public interface Progress { void update(String stage,long current,long total); }
    public static final class Ready {
        public final Path dataDirectory, optionalDirectory, cardDirectory;
        public final List<String> warnings;
        /** Only individually verified canonical names. Backfire and front halo each require both files. */
        public final Map<String,Path> optionalFiles;
        private Ready(Path d,Path o,Path c,List<String> w,Map<String,Path> files) { dataDirectory=d; optionalDirectory=o; cardDirectory=c; warnings=Collections.unmodifiableList(new ArrayList<String>(w)); optionalFiles=Collections.unmodifiableMap(new TreeMap<String,Path>(files)); }
    }
    public ResourceStore(Path externalRoot,Path noBackupRoot,DataManifest.Limits limits,DataBaselines baselines,ResourceMetadata metadata) {
        external=Objects.requireNonNull(externalRoot).toAbsolutePath().normalize(); noBackup=Objects.requireNonNull(noBackupRoot).toAbsolutePath().normalize();
        this.limits=Objects.requireNonNull(limits); this.baselines=Objects.requireNonNull(baselines); this.metadata=Objects.requireNonNull(metadata).withFixedEffects();
        state=noBackup.resolve("resource-import-v1"); oldState=noBackup.resolve("game-data-state");
        legacy=external.resolve("re3dxplus-data"); imported=external.resolve("re3dxplus-imported");
        companions=external.resolve("re3dxplus-addons");
    }
    static void check(Cancel c) throws IOException { if(Thread.currentThread().isInterrupted() || (c!=null&&c.cancelled())) throw new InterruptedIOException("已取消；若旧更新尚未完成，请使用同一原始来源重试恢复"); }
    static MessageDigest sha() { try { return MessageDigest.getInstance("SHA-256"); } catch(NoSuchAlgorithmException e) { throw new AssertionError(e); } }
    static String hex(byte[] b) { char[] h="0123456789abcdef".toCharArray(),s=new char[b.length*2]; for(int i=0;i<b.length;i++) { s[2*i]=h[(b[i]&255)>>>4]; s[2*i+1]=h[b[i]&15]; } return new String(s); }
    private static boolean exists(Path p) { return Files.exists(p,LinkOption.NOFOLLOW_LINKS); }
    private static void safeChain(Path path) throws IOException {
        Path q=path.getRoot(); for(Path part:path) { q=q.resolve(part); if(Files.isSymbolicLink(q)) throw new IOException("资源路径包含符号链接，已停止"); }
    }
    private static void directory(Path p,boolean create) throws IOException {
        safeChain(p); if(create&&!exists(p)) { Path parent=p.getParent(); if(parent!=null) directory(parent,true); Files.createDirectory(p); }
        if(!Files.isDirectory(p,LinkOption.NOFOLLOW_LINKS)) throw new IOException("资源目录不存在或不安全");
    }
    private void preflight(boolean allowPending) throws IOException {
        directory(external,false); directory(noBackup,false); safeChain(state); safeChain(oldState);
        requireClearFinished(noBackup);
        if(exists(oldState)) {
            directory(oldState,false);
            boolean pending=exists(oldState.resolve("pending"));
            if(pending&&!allowPending) throw new IOException("旧资源更新尚未完成，请导入原先的主资源 ZIP 恢复，或清除资源包后重新导入；无需回装旧应用");
            if(!pending) {
                for(String name:new String[]{"overlay.journal","old.manifest","new.manifest"})
                    if(exists(oldState.resolve(name))) throw new IOException("发现未归属的旧更新事务，请先检查恢复；旧资源与事务文件已保留");
                try(DirectoryStream<Path> transactions=Files.newDirectoryStream(oldState,"txn-*")) {
                    if(transactions.iterator().hasNext()) throw new IOException("发现未归属的旧更新事务目录，请先检查恢复；旧资源与事务目录已保留");
                }
            }
        }
        if(exists(state)) directory(state,false);
    }
    static void requireClearFinished(Path noBackup) throws IOException {
        if (exists(noBackup.resolve(CLEAR_PENDING)))
            throw new IOException("上次清除资源包尚未完成，请再次点击“清除资源包”。");
    }
    /** Caller holds the install lock and has stopped all resource jobs. Only
     * these owned resource namespaces are removed, including abandoned imports. */
    public static void clearInstalledResources(Path external, Path noBackup) throws IOException {
        directory(external, false);
        directory(noBackup, false);
        List<Path> roots = new ArrayList<>();
        for (String name : new String[]{"re3dxplus-imported", "re3dxplus-addons", "re3dxplus-data", "re3dxplus-original", "wmmt-sidecars"})
            roots.add(external.resolve(name));
        for (String name : new String[]{"re3dxplus-original-jobs", "original-convert-ui-v1",
                "original-convert-v1", "resource-import-v1", "resource-choice-v2", "game-data-state",
                "ghost-ui-v1", "builtin-ghosts-v1"})
            roots.add(noBackup.resolve(name));
        for (Path root : roots) {
            safeChain(root);
            if (exists(root)) directory(root, false);
        }
        Path pending = noBackup.resolve(CLEAR_PENDING);
        if (!exists(pending)) Files.createFile(pending);
        else if (!Files.isRegularFile(pending, LinkOption.NOFOLLOW_LINKS))
            throw new IOException("资源清除记录路径不安全。");
        sync(noBackup);
        for (Path root : roots) {
            if (Files.notExists(root, LinkOption.NOFOLLOW_LINKS)) continue;
            // The default walk does not follow links. Remove a link itself, never its target.
            Files.walkFileTree(root, new SimpleFileVisitor<Path>() {
                @Override public FileVisitResult preVisitDirectory(Path dir, BasicFileAttributes attrs) throws IOException {
                    safeChain(dir);
                    return FileVisitResult.CONTINUE;
                }
                @Override public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) throws IOException {
                    safeChain(file.getParent());
                    Files.delete(file);
                    return FileVisitResult.CONTINUE;
                }
                @Override public FileVisitResult postVisitDirectory(Path dir, IOException error) throws IOException {
                    if (error != null) throw error;
                    safeChain(dir);
                    Files.delete(dir);
                    return FileVisitResult.CONTINUE;
                }
            });
        }
        sync(external);
        sync(noBackup);
        Files.delete(pending);
        sync(noBackup);
    }
    private static Path child(Path root,String name) throws IOException {
        SafeResourceZip.path(name,false); Path p=root.resolve(name); safeChain(p); return p;
    }
    private static byte[] small(Path p,int max) throws IOException {
        safeChain(p); if(!Files.isRegularFile(p,LinkOption.NOFOLLOW_LINKS)||Files.size(p)>max) throw new IOException("资源选择记录或完成标记损坏，请重新导入");
        try(InputStream in=Files.newInputStream(p,LinkOption.NOFOLLOW_LINKS)) {
            ByteArrayOutputStream out=new ByteArrayOutputStream(); byte[] b=new byte[1024]; int n;
            while((n=in.read(b))!=-1) { if(n==0) continue; if(n>max-out.size()) throw new IOException("资源状态记录超限"); out.write(b,0,n); } return out.toByteArray();
        }
    }
    private static String text(Path p,int max) throws IOException {
        byte[] b=small(p,max); for(byte x:b) if((x&255)>127) throw new IOException("资源状态记录格式损坏"); return new String(b,StandardCharsets.US_ASCII);
    }
    private DataManifest baseline(String hash) throws IOException {
        if(!hash.matches("[0-9a-f]{64}")) throw new IOException("资源选择记录损坏，请重新导入");
        DataManifest m=baselines.find(hash);
        if(m==null || !ID.equals(m.canonicalId) || !hash.equals(m.zipSha256) || m.files().isEmpty()) throw new IOException("资源版本不受支持，请导入受支持的转换包");
        return m;
    }
    private static boolean sameFiles(DataManifest a,DataManifest b) {
        if(!a.canonicalId.equals(b.canonicalId)||!a.zipSha256.equals(b.zipSha256)||!a.files().keySet().equals(b.files().keySet())) return false;
        for(DataManifest.Entry e:a.files().values()) { DataManifest.Entry x=b.files().get(e.path); if(e.length!=x.length||!e.sha256.equals(x.sha256)) return false; } return true;
    }
    private static boolean sameInstallation(DataManifest a,DataManifest b) {
        return a!=null&&b!=null&&a.resourceDirectory.equals(b.resourceDirectory)&&sameFiles(a,b);
    }
    private static final class Pending {
        final String record; final DataManifest next;
        Pending(String record,DataManifest next) { this.record=record; this.next=next; }
    }
    private DataManifest privateManifest(Path file,String expected,Cancel cancel,Progress progress) throws IOException {
        safeChain(file);
        if(!Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS)||Files.size(file)>limits.maxManifestBytes) throw new IOException("旧更新事务快照缺失或不安全，状态已保留");
        if(expected!=null&&!hashFile(file,Files.size(file),cancel,progress,"verify-old-state").equals(expected)) throw new IOException("旧更新事务快照已改变，状态已保留");
        check(cancel); DataManifest value=DataManifest.read(file,limits);
        if(!sameFiles(value,baseline(value.zipSha256))) throw new IOException("旧更新事务快照不符合受支持目录，状态已保留");
        return value;
    }
    /** Read-only DOV1 binding check, matching DataOverlay's existing journal contract. */
    private void verifyOverlayJournal(Path root,DataManifest old,DataManifest next) throws IOException {
        Path journal=oldState.resolve("overlay.journal"); if(!exists(journal)) return;
        if(!exists(root)) throw new IOException("旧更新日志对应的资源目录缺失，状态已保留");
        ByteArrayOutputStream bytes=new ByteArrayOutputStream(); DataOutputStream out=new DataOutputStream(bytes);
        out.writeUTF(root.toString()); out.writeUTF(old==null?next.zipSha256:old.zipSha256); out.writeUTF(next.zipSha256);
        for(DataManifest manifest:new DataManifest[]{old,next}) {
            out.writeInt(manifest==null?0:manifest.files().size());
            if(manifest!=null) for(DataManifest.Entry entry:manifest.files().values()) { out.writeUTF(entry.path); out.writeLong(entry.length); out.writeUTF(entry.sha256); }
        }
        out.flush(); byte[] expected=sha().digest(bytes.toByteArray());
        try(DataInputStream in=new DataInputStream(new ByteArrayInputStream(small(journal,128)))) {
            if(in.readInt()!=0x444f5631) throw new IOException("旧覆盖日志格式损坏，状态已保留");
            byte[] actual=new byte[32]; in.readFully(actual); String nonce=in.readUTF();
            if(!nonce.matches("[0-9a-f]{32}")||in.read()!=-1||!MessageDigest.isEqual(actual,expected)) throw new IOException("旧覆盖日志与登记事务不匹配，状态已保留");
        }
    }
    /** Read-only admission, before any legacy mutation, including init-root creation. */
    private Pending readPending(Cancel cancel,Progress progress) throws IOException {
        if(!exists(oldState.resolve("pending"))) return null;
        String record=text(oldState.resolve("pending"),256); String[] fields=record.split("\n",-1);
        if(fields.length!=4 || !fields[1].matches("[0-9a-f]{32}") || !fields[3].matches("[0-9a-f]{64}") ||
                (!fields[0].equals("init")&&!fields[0].equals("update-marked")&&!fields[0].equals("update-unmarked")) ||
                (fields[0].equals("init")?!fields[2].equals("-"):!fields[2].matches("[0-9a-f]{64}"))) throw new IOException("旧更新事务记录损坏或不受支持，不能绕过；原状态已保留");
        Path transaction=child(oldState,"txn-"+fields[1]); directory(transaction,false);
        for(String unbound:new String[]{"old.manifest","new.manifest"}) if(exists(oldState.resolve(unbound))) throw new IOException("旧更新同时存在未归属快照，请先检查；全部状态已保留");
        try(DirectoryStream<Path> transactions=Files.newDirectoryStream(oldState,"txn-*")) {
            for(Path other:transactions) if(!other.equals(transaction)) throw new IOException("旧更新同时存在未归属事务目录，请先检查；全部状态已保留");
        }
        try(DirectoryStream<Path> snapshots=Files.newDirectoryStream(transaction)) {
            for(Path file:snapshots) { String name=file.getFileName().toString();
                if(!name.equals("new.manifest") && !(name.equals("old.manifest")&&!fields[0].equals("init"))) throw new IOException("旧事务目录包含未归属文件，请先检查；全部文件已保留");
            }
        }
        DataManifest next=privateManifest(transaction.resolve("new.manifest"),fields[3],cancel,progress);
        if(!next.resourceDirectory.matches("[0-9a-f]{64}-"+UUID_PATTERN)) throw new IOException("旧更新事务目录不安全，状态已保留");
        DataManifest old=fields[0].equals("init")?null:privateManifest(transaction.resolve("old.manifest"),fields[2],cancel,progress);
        if(old!=null&&!old.resourceDirectory.equals(next.resourceDirectory)) throw new IOException("旧更新事务目录不一致，状态已保留");
        directory(legacy,false); Path root=child(legacy,next.resourceDirectory);
        if(exists(root)) directory(root,false); else if(old!=null) throw new IOException("旧更新事务资源目录缺失，状态已保留");
        DataManifest active=exists(oldState.resolve("active.manifest"))?privateManifest(oldState.resolve("active.manifest"),null,cancel,progress):null;
        boolean done=sameInstallation(active,next);
        if(!done && (old==null?active!=null:!sameInstallation(active,old))) throw new IOException("旧更新事务与当前登记不一致，状态已保留");
        verifyOverlayJournal(root,old,next);
        Path marker=root.resolve(MARKER); String published=ID+":"+next.zipSha256;
        if(fields[0].equals("update-marked")) {
            String value=text(marker,256),previous=ID+":"+old.zipSha256,updating=ID+":in-progress:"+old.zipSha256+":"+next.zipSha256;
            if(done?(!value.equals(updating)&&!value.equals(published)):(!value.equals(previous)&&!value.equals(updating))) throw new IOException("旧更新完成标记已改变，状态已保留");
        } else if(old!=null&&exists(marker)) throw new IOException("旧更新事务出现未登记标记，状态已保留");
        else if(old==null&&exists(marker)&&(!done||!text(marker,256).equals(published))) throw new IOException("旧初始化事务标记不一致，状态已保留");
        return new Pending(record,next);
    }
    private void recoverPending(Pending expected,Path archive,Cancel cancel,Progress progress) throws IOException {
        Pending current=readPending(cancel,progress);
        if(current==null||!current.record.equals(expected.record)||!sameInstallation(current.next,expected.next)) throw new IOException("旧更新事务在验证期间发生变化，请重试；原选择未切换");
        String exact=hashFile(archive,Files.size(archive),cancel,progress,"verify-recovery-source");
        if(!exact.equals(current.next.zipSha256)) throw new IOException("所选 ZIP 与旧更新所需的原始主资源 ZIP 不匹配。请选原始主资源 ZIP，或清除资源包后重新导入。");
        long recoveryBytes=0; for(DataManifest.Entry entry:current.next.files().values()) {
            if(entry.length>mainLimit()-recoveryBytes) throw new IOException("旧事务资源大小超过安全上限"); recoveryBytes+=entry.length;
        }
        // Reserve the full registered next set conservatively before the first legacy write.
        room(legacy,recoveryBytes); check(cancel);
        final boolean[] committed={false};
        DataManifest.ZipSource stable=()->{
            safeChain(archive); final InputStream raw=Files.newInputStream(archive,LinkOption.NOFOLLOW_LINKS);
            return new FilterInputStream(raw) {
                @Override public int read() throws IOException { if(!committed[0]) check(cancel); return in.read(); }
                @Override public int read(byte[] b,int off,int length) throws IOException { if(!committed[0]) check(cancel); return in.read(b,off,length); }
            };
        };
        try {
            Path restored=DataCoordinator.withBaselines(legacy,oldState,limits,baselines).prepare(stable,stage->{
                if(stage.equals("after-pending-delete")) committed[0]=true;
                if(!committed[0]) { check(cancel); if(progress!=null) progress.update("recover-old:"+stage,0,-1); check(cancel); }
            });
            if(!restored.equals(legacy.resolve(current.next.resourceDirectory))||exists(oldState.resolve("pending"))) throw new IOException("旧更新恢复尚未完成，请使用同一原始来源重试");
            check(cancel); verifyMain(restored,baseline(current.next.zipSha256),cancel,progress);
        } catch(InterruptedIOException interrupted) { throw interrupted; }
        catch(IOException failure) { check(cancel); throw new IOException("旧资源更新恢复未完成；请保留同一原始来源并重试，登记状态未被绕过",failure); }
    }
    private static final class Selection { final String kind,name,hash; Selection(String k,String n,String h) { kind=k;name=n;hash=h; } }
    private Selection readSelection() throws IOException {
        String t=text(state.resolve(SELECTION),512); String[] f=t.split("\n",-1);
        if(f.length!=6 || !f[0].equals("WMMT-RESOURCE-SELECTION-1") || !f[5].isEmpty() || (!f[1].equals("legacy")&&!f[1].equals("imported")) ||
                !f[3].matches("[0-9a-f]{64}") || !f[4].matches("[0-9a-f]{64}")) throw new IOException("资源选择记录损坏，请重新导入");
        String prefix=f[0]+"\n"+f[1]+"\n"+f[2]+"\n"+f[3]+"\n";
        if(!hex(sha().digest(prefix.getBytes(StandardCharsets.US_ASCII))).equals(f[4])) throw new IOException("资源选择记录校验失败，请重新导入");
        if(f[1].equals("imported")?!f[2].matches(UUID_PATTERN):!f[2].matches("[0-9a-f]{64}-"+UUID_PATTERN)) throw new IOException("资源选择目录无效，请重新导入");
        return new Selection(f[1],f[2],f[3]);
    }
    private static String hashFile(Path path,long length,Cancel cancel,Progress progress,String stage) throws IOException {
        safeChain(path); if(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)||Files.size(path)!=length) throw new IOException("资源缺失或大小不正确，请重新导入完整资源包");
        MessageDigest d=sha(); long count=0; byte[] b=new byte[65536];
        try(InputStream in=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS)) {
            int n; while(true) { check(cancel); n=in.read(b); if(n<0) break; if(n==0) continue; if(n>length-count) throw new IOException("资源在校验期间发生变化"); count+=n; d.update(b,0,n); if(progress!=null) progress.update(stage,count,length); }
        }
        if(count!=length) throw new IOException("资源不完整，请重新导入"); return hex(d.digest());
    }
    private void verifyMain(Path root,DataManifest m,Cancel cancel,Progress progress) throws IOException {
        directory(root,false); int i=0;
        for(DataManifest.Entry e:m.files().values()) { check(cancel); if(!hashFile(child(root,e.path),e.length,cancel,progress,"verify-main").equals(e.sha256)) throw new IOException("主资源校验失败，请重新导入完整资源包"); if(progress!=null) progress.update("verify-files",++i,m.files().size()); }
    }
    public Ready resolve(Cancel cancel,Progress progress) throws IOException {
        check(cancel); preflight(false);
        if(exists(state.resolve(SELECTION))) {
            Selection s=readSelection(); Path base=s.kind.equals("legacy")?legacy:imported; directory(base,false); Path root=child(base,s.name);
            verifyMain(root,baseline(s.hash),cancel,progress); return ready(root,s.kind.equals("legacy"),cancel,progress);
        }
        Path active=oldState.resolve("active.manifest");
        if(exists(active)) {
            safeChain(active); if(!Files.isRegularFile(active,LinkOption.NOFOLLOW_LINKS)) throw new IOException("旧资源登记损坏，请重新导入");
            DataManifest m=DataManifest.read(active,limits),b=baseline(m.zipSha256);
            if(!sameFiles(m,b) || !m.resourceDirectory.matches("[0-9a-f]{64}-"+UUID_PATTERN)) throw new IOException("旧资源登记不符合受支持目录，请重新导入");
            directory(legacy,false); Path root=child(legacy,m.resourceDirectory); verifyMain(root,b,cancel,progress); return ready(root,true,cancel,progress);
        }
        if(!exists(legacy)) throw new IOException("尚未选择游戏资源，请导入已转换的资源 ZIP 或使用原版转换");
        directory(legacy,false); List<Path> roots=new ArrayList<Path>(); List<DataManifest> manifests=new ArrayList<DataManifest>(); List<String> markers=new ArrayList<String>();
        try(DirectoryStream<Path> list=Files.newDirectoryStream(legacy)) {
            for(Path root:list) {
                check(cancel); String name=root.getFileName().toString();
                if(!name.matches("[0-9a-f]{64}-"+UUID_PATTERN) || Files.isSymbolicLink(root) || !Files.isDirectory(root,LinkOption.NOFOLLOW_LINKS)) continue;
                Path marker=root.resolve(MARKER); if(!exists(marker) || Files.isSymbolicLink(marker) || !Files.isRegularFile(marker,LinkOption.NOFOLLOW_LINKS) || Files.size(marker)>256) continue;
                String value; try { value=text(marker,256); } catch(IOException invalidMarker) { continue; }
                if(!value.matches(ID+":[0-9a-f]{64}")) continue;
                DataManifest b=baselines.find(value.substring(ID.length()+1)); if(b==null) continue;
                roots.add(root); manifests.add(b); markers.add(value);
                if(roots.size()>1) throw new IOException("发现多个受支持的旧资源目录，请明确导入要使用的资源；现有文件均已保留");
            }
        }
        // Count BEFORE verification: a damaged recognized sibling does not establish uniqueness.
        if(roots.size()>1) throw new IOException("发现多个受支持的旧资源目录，请明确导入要使用的资源；现有文件均已保留");
        if(roots.isEmpty()) throw new IOException("未找到完整且受支持的旧资源，请导入已转换的资源 ZIP 或使用原版转换");
        Path root=roots.get(0); DataManifest b=baseline(manifests.get(0).zipSha256); verifyMain(root,b,cancel,progress);
        if(!text(root.resolve(MARKER),256).equals(markers.get(0))) throw new IOException("旧资源标记在校验期间发生变化");
        return ready(root,true,cancel,progress);
    }
    private boolean group(Path root,List<String> paths,boolean stripCard,Cancel cancel,Progress progress) throws IOException {
        check(cancel);
        try {
            directory(root,false);
            for(String path:paths) {
                check(cancel); ResourceMetadata.Entry e=metadata.find(path); if(e==null) return false;
                String relative=stripCard?path.substring("card-resources/".length()):path;
                if(!hashFile(child(root,relative),e.length,cancel,progress,"verify-optional").equals(e.sha256)) return false;
            }
            return true;
        } catch(InterruptedIOException e) { throw e; } catch(IOException e) { check(cancel); return false; }
    }
    private static final class Sidecars {
        final Map<String,Path> files=new TreeMap<>();
        Path card;
        void fill(Sidecars other) {
            other.files.forEach(files::putIfAbsent);
            if(card==null) card=other.card;
        }
    }

    public Ready resolveOriginal(OriginalJobStore.Ready original,Cancel cancel,Progress progress) throws IOException {
        Path data=original.dataDirectory;
        Sidecars sidecars=readSidecars(data.getParent(),false,cancel,progress);
        fillCompanion(sidecars,cancel,progress);
        // A previously selected prepared pack remains registered when the
        // original converter is selected. Reuse only its independently pinned sidecars.
        if(!hasCompleteSidecars(sidecars)) {
            try {
                if(exists(state.resolve(SELECTION))) {
                    Selection prior=readSelection();
                    Path root=child(prior.kind.equals("legacy")?legacy:imported,prior.name);
                    sidecars.fill(readSidecars(root,prior.kind.equals("legacy"),cancel,progress));
                } else sidecars.fill(readSidecars(legacy,true,cancel,progress));
            } catch(InterruptedIOException cancelled) { throw cancelled; }
            catch(IOException unavailable) { check(cancel); }
        }
        return assembled(data,sidecars);
    }

    private Path companionRoot() throws IOException {
        if(!exists(state.resolve(COMPANION_SELECTION))) return null;
        String name=text(state.resolve(COMPANION_SELECTION),64);
        if(!name.matches(UUID_PATTERN)) throw new IOException("附加资源登记损坏");
        return child(companions,name);
    }

    private static boolean hasCompleteSidecars(Sidecars sidecars) {
        return sidecars.card!=null && ResourceMetadata.OPTIONAL_PATHS.subList(0,4).stream().allMatch(sidecars.files::containsKey)
                && ResourceMetadata.CONVERTED_PATHS.stream().allMatch(sidecars.files::containsKey)
                && ResourceMetadata.FRONT_HALO_PATHS.stream().allMatch(sidecars.files::containsKey)
                && sidecars.files.containsKey(ResourceMetadata.TEN_BGM_PATH)
                && sidecars.files.containsKey(ResourceMetadata.CROWN_SCENES_PATH);
    }

    private void fillCompanion(Sidecars sidecars,Cancel cancel,Progress progress) throws IOException {
        if(hasCompleteSidecars(sidecars)) return;
        try {
            Path root=companionRoot();
            if(root!=null) sidecars.fill(readSidecars(root,false,cancel,progress));
        } catch(InterruptedIOException cancelled) { throw cancelled; }
        catch(IOException unavailable) { check(cancel); }
    }

    private static Ready assembled(Path data,Sidecars sidecars) {
        List<String> warnings=new ArrayList<>();
        Map<String,Path> files=sidecars.files;
        if(!files.containsKey("story-cutin.bin")) warnings.add("缺少剧情演出资源");
        if(!files.containsKey("card-pages.bin")) warnings.add("缺少完整卡片页面资源");
        if(!files.containsKey("backfire.wpk")) warnings.add("缺少完整的回火特效资源");
        if(sidecars.card==null) warnings.add("缺少扩展表盘与音乐");
        if(!warnings.isEmpty()) warnings.add("可通过「导入已转换的资源 ZIP」补齐附加资源，无需重转主资源。");
        for(String name:ResourceMetadata.CONVERTED_PATHS) {
            if(files.containsKey(name) || (name.equals(ResourceMetadata.FINISH_MENU_PATH) && files.containsKey("card-pages.bin"))) continue;
            warnings.add("缺少转换附加资源 " + name);
        }
        if(!files.containsKey(ResourceMetadata.TEN_BGM_PATH)) warnings.add("缺少十人斩原版音乐");
        if(!files.containsKey(ResourceMetadata.CROWN_SCENES_PATH)) warnings.add("缺少原版皇冠与驾驶风格画面素材");
        Path optional=files.get("story-cutin.bin");
        if(optional!=null) {
            optional=optional.getParent();
            for(String name:ResourceMetadata.OPTIONAL_PATHS.subList(0,4))
                if(!optional.resolve(name).equals(files.get(name))) { optional=null; break; }
        }
        return new Ready(data,optional,sidecars.card,warnings,files);
    }

    private Ready ready(Path root,boolean old,Cancel cancel,Progress progress) throws IOException {
        Sidecars sidecars=readSidecars(root,old,cancel,progress);
        fillCompanion(sidecars,cancel,progress);
        return assembled(root,sidecars);
    }
    private Sidecars readSidecars(Path root,boolean old,Cancel cancel,Progress progress) throws IOException {
        Sidecars sidecars=new Sidecars();
        Map<String,Path> optionalFiles=sidecars.files;
        Path side=old?external.resolve("wmmt-sidecars"):root;
        for(String name:ResourceMetadata.OPTIONAL_PATHS.subList(0,2)) {
            if(group(side,Collections.singletonList(name),false,cancel,progress)) optionalFiles.put(name,side.resolve(name));
        }
        Path backfire=side;
        if(old) {
            backfire=null;
            try {
                String version=text(side.resolve("backfire-current"),64);
                if(version.matches("[0-9a-f]{64}")) backfire=child(side,"backfire-"+version);
            } catch(IOException invalidPointer) { check(cancel); }
        }
        List<String> pair=ResourceMetadata.OPTIONAL_PATHS.subList(2,4);
        if(backfire!=null&&group(backfire,pair,false,cancel,progress)) for(String name:pair) optionalFiles.put(name,backfire.resolve(name));
        if(metadata.find(ResourceMetadata.GHOST_UI_PATH)!=null && group(side,Collections.singletonList(ResourceMetadata.GHOST_UI_PATH),false,cancel,progress))
            optionalFiles.put(ResourceMetadata.GHOST_UI_PATH,side.resolve(ResourceMetadata.GHOST_UI_PATH));
        if(group(side,ResourceMetadata.FRONT_HALO_PATHS,false,cancel,progress))
            for(String name:ResourceMetadata.FRONT_HALO_PATHS) optionalFiles.put(name,side.resolve(name));
        for(String name:ResourceMetadata.CONVERTED_PATHS)
            if(group(side,Collections.singletonList(name),false,cancel,progress)) optionalFiles.put(name,side.resolve(name));
        String tenBgm=ResourceMetadata.TEN_BGM_PATH;
        if(group(side,Collections.singletonList(tenBgm),false,cancel,progress)) optionalFiles.put(tenBgm,side.resolve(tenBgm));
        String crownScenes=ResourceMetadata.CROWN_SCENES_PATH;
        if(group(side,Collections.singletonList(crownScenes),false,cancel,progress))
            optionalFiles.put(crownScenes,side.resolve(crownScenes));
        if(old) {
            Path cards=side.resolve("card-resources-v1"); List<Path> valid=new ArrayList<Path>();
            try {
                directory(cards,false);
                try(DirectoryStream<Path> ds=Files.newDirectoryStream(cards)) {
                    for(Path p:ds) { check(cancel); if(p.getFileName().toString().startsWith("ready-") && group(p,ResourceMetadata.CARD_PATHS,true,cancel,progress)) { valid.add(p); if(valid.size()==2) break; } }
                }
            } catch(InterruptedIOException e) { throw e; } catch(IOException e) { check(cancel); }
            if(valid.size()==1) sidecars.card=valid.get(0);
        } else {
            Path c=root.resolve("card-resources"); if(group(c,ResourceMetadata.CARD_PATHS,true,cancel,progress)) sidecars.card=c;
        }
        return sidecars;
    }
    /** A capability minted only after a bounded digest check. No public path constructor. */
    public static final class VerifiedOptional {
        private final String name; private final Path path;
        private VerifiedOptional(String n,Path p) { name=n; path=p; }
        public Path verifiedPath(String requested) { return name.equals(requested)?path:null; }
    }
    public interface GhostSource { InputStream open() throws IOException; }
    /** Caller holds ProcessLock through native shutdown, like all Store operations.
     * Source is the exact APK asset chosen by MainActivity, never an imported path.
     * Missing/corrupt optional data returns no capability; main readiness is unchanged.
     * Abandoned staging trees are retained and never adopted or scanned. */
    public VerifiedOptional preparePackagedGhost(GhostSource source,Cancel cancel,Progress progress) throws IOException {
        return preparePackagedOptional(ResourceMetadata.GHOST_UI_PATH,"ghost-ui-v1",source,cancel,progress);
    }
    public VerifiedOptional preparePackagedBuiltinGhosts(GhostSource source,Cancel cancel,Progress progress) throws IOException {
        return preparePackagedOptional(ResourceMetadata.BUILTIN_GHOSTS_PATH,"builtin-ghosts-v1",source,cancel,progress);
    }
    private VerifiedOptional preparePackagedOptional(String name,String privateNamespace,GhostSource source,Cancel cancel,Progress progress) throws IOException {
        check(cancel);
        ResourceMetadata.Entry spec=metadata.find(name);
        if(spec==null || source==null) return new VerifiedOptional(name,null);
        try {
            directory(noBackup,false);
            Path base=child(noBackup,privateNamespace); directory(base,true);
            Path owned=child(base,spec.sha256); directory(owned,true);
            Path published=child(owned,name);
            if(exists(published)) {
                if(hashFile(published,spec.length,cancel,progress,"verify-optional").equals(spec.sha256)) return new VerifiedOptional(name,published);
                return new VerifiedOptional(name,null);
            }
            room(owned,spec.length);
            Path staging=child(owned,"payload-"+UUID.randomUUID().toString()+".tmp");
            Files.createFile(staging);
            MessageDigest digest=sha(); long count=0; byte[] buffer=new byte[65536];
            try(InputStream input=source.open(); FileOutputStream output=new FileOutputStream(staging.toFile())) {
                if(input==null) throw new IOException("Packaged optional asset unavailable");
                int n;
                while(true) {
                    check(cancel); n=input.read(buffer); if(n<0) break;
                    if(n==0) { int one=input.read(); if(one<0) break; buffer[0]=(byte)one; n=1; }
                    if(n>spec.length-count) throw new IOException("Packaged optional byte limit");
                    output.write(buffer,0,n); digest.update(buffer,0,n); count+=n;
                    if(progress!=null) progress.update("verify-optional",count,spec.length);
                }
                if(count!=spec.length || !hex(digest.digest()).equals(spec.sha256)) throw new IOException("Packaged optional digest mismatch");
                output.getFD().sync();
            }
            check(cancel); sync(owned); sync(base); sync(noBackup);
            Files.move(staging,published,StandardCopyOption.ATOMIC_MOVE);
            sync(owned); sync(base);
            if(!hashFile(published,spec.length,cancel,progress,"verify-optional").equals(spec.sha256)) throw new IOException("Packaged optional changed after publication");
            check(cancel); return new VerifiedOptional(name,published);
        } catch(InterruptedIOException interrupted) { throw interrupted; }
        catch(IOException optionalUnavailable) { check(cancel); return new VerifiedOptional(name,null); }
    }
    private static void sync(Path p) throws IOException { try(FileChannel c=FileChannel.open(p,StandardOpenOption.READ)) { c.force(true); } catch(UnsupportedOperationException e) { throw new IOException("文件系统不支持可靠同步，未切换资源",e); } }
    private static void room(Path p,long bytes) throws IOException {
        long free=p.toFile().getUsableSpace(),reserve=Math.max(RESERVE,bytes/20);
        if(bytes<0 || bytes>Long.MAX_VALUE-reserve || free<bytes+reserve) throw new IOException("存储空间不足，请预留资源大小及至少 64 MiB 安全余量");
    }
    private long mainLimit() { return Math.min(MAIN_LIMIT,limits.maxTotalBytes); }
    private long sourceLimit() { return Math.min(SOURCE_LIMIT,(long)limits.maxArchiveBytes); }
    private void copySource(InputStream input,Path file,Cancel cancel,Progress progress) throws IOException {
        long count=0; byte[] b=new byte[65536];
        try(FileOutputStream out=new FileOutputStream(file.toFile())) {
            int n; while(true) { check(cancel); n=input.read(b); if(n<0) break;
                if(n==0) { int one=input.read(); if(one<0) break; b[0]=(byte)one; n=1; }
                if(n>sourceLimit()-count) throw new IOException("导入文件超过 2 GiB 或配置的安全大小上限");
                room(file.getParent(),n); count+=n; out.write(b,0,n); if(progress!=null) progress.update("copy-source",count,-1);
            }
            out.getFD().sync();
        }
    }
    private static boolean rawArcade(Collection<SafeResourceZip.Member> files) {
        for(SafeResourceZip.Member m:files) { String n=m.name.toLowerCase(Locale.ROOT); if(n.equals("main") || n.endsWith("/main") || (n.startsWith("data/car/")||n.contains("/data/car/"))&&n.endsWith(".igb")) return true; } return false;
    }
    private long extraTotal() throws IOException {
        long total=0; for(ResourceMetadata.Entry e:metadata.files().values()) { if(e.length>EXTRA_LIMIT-total) throw new IOException("APK 附加资源校验目录大小超限"); total+=e.length; } return total;
    }
    private int zipEntries() { return (int)Math.min(16384L,(long)limits.maxEntries+8192); }
    private String extract(SafeResourceZip zip,SafeResourceZip.Member member,Path target,Cancel cancel,Progress progress) throws IOException {
        directory(target.getParent(),true); safeChain(target); Files.createFile(target);
        try(FileOutputStream out=new FileOutputStream(target.toFile())) {
            String digest=zip.consume(member,out,cancel,progress,"extract");
            out.getFD().sync();
            return digest;
        }
    }
    private DataManifest importMain(SafeResourceZip zip,Path root,Cancel cancel,Progress progress) throws IOException {
        if(rawArcade(zip.members.values())) throw new IOException("原版需要转换，本版不直接运行；请选择转换后的资源包");
        SortedMap<String,SafeResourceZip.Member> main=new TreeMap<String,SafeResourceZip.Member>(); List<SafeResourceZip.Member> extras=new ArrayList<SafeResourceZip.Member>();
        long total=0,extraBytes=0;
        for(SafeResourceZip.Member m:zip.members.values()) {
            check(cancel); if(m.directory) { zip.consume(m,null,cancel,progress,"verify-zip"); continue; }
            if(ResourceMetadata.companionPath(m.name) ||
                    (m.name.equals(ResourceMetadata.GHOST_UI_PATH)&&metadata.find(m.name)!=null)) { if(m.length>EXTRA_LIMIT-extraBytes) throw new IOException("附加资源解压大小超过安全上限"); extraBytes+=m.length; extras.add(m); continue; }
            if(m.length>mainLimit()-total) throw new IOException("主资源解压大小超过安全上限"); total+=m.length; main.put(m.name,m);
        }
        List<DataManifest> candidates=new ArrayList<DataManifest>();
        for(DataManifest b:baselines.inventories()) {
            if(!b.files().keySet().equals(main.keySet())) continue; boolean match=true;
            for(DataManifest.Entry e:b.files().values()) if(main.get(e.path).length!=e.length) { match=false; break; }
            if(match) candidates.add(b);
        }
        if(candidates.isEmpty()) throw new IOException("资源文件缺失、大小不符或包含未知文件；请导入完整转换包");
        room(root,total+extraTotal());
        for(SafeResourceZip.Member m:main.values()) {
            check(cancel); Path target=child(root,m.name); directory(target.getParent(),true); Files.createFile(target); String digest;
            try(FileOutputStream out=new FileOutputStream(target.toFile())) { digest=zip.consume(m,out,cancel,progress,"extract-main"); out.getFD().sync(); }
            final String hash=digest; candidates.removeIf(b->!b.files().get(m.name).sha256.equals(hash));
            if(candidates.isEmpty()) throw new IOException("主资源内容被修改或不受支持；原有资源未切换");
        }
        // Content-identical packaged inventories use the smallest canonical SHA deterministically.
        Collections.sort(candidates,(a,b)->a.zipSha256.compareTo(b.zipSha256)); DataManifest chosen=baseline(candidates.get(0).zipSha256);
        for(SafeResourceZip.Member m:extras) optionalExtract(zip,m,m.name,root,cancel,progress);
        verifyMain(root,chosen,cancel,progress); return chosen;
    }
    private void optionalExtract(SafeResourceZip zip,SafeResourceZip.Member m,String canonical,Path root,Cancel cancel,Progress progress) throws IOException {
        ResourceMetadata.Entry spec=metadata.find(canonical);
        // Untrusted optional manifests never extend ownership or the signed whitelist.
        if(spec==null || spec.length!=m.length) { zip.consume(m,null,cancel,progress,"verify-optional"); return; }
        extract(zip,m,child(root,canonical),cancel,progress);
        // A mismatched optional payload remains confined to the new root and is never Ready.
    }
    private void syncTree(Path root,Cancel cancel) throws IOException {
        // Only this call's newly-created, bounded resource tree is traversed.
        List<Path> dirs=new ArrayList<Path>(); try(java.util.stream.Stream<Path> paths=Files.walk(root)) {
            Iterator<Path> it=paths.iterator(); while(it.hasNext()) { check(cancel); Path p=it.next(); safeChain(p); if(Files.isDirectory(p,LinkOption.NOFOLLOW_LINKS)) dirs.add(p); }
        }
        Collections.sort(dirs,(a,b)->Integer.compare(b.getNameCount(),a.getNameCount())); for(Path p:dirs) { check(cancel); sync(p); }
    }
    private boolean publish(String name,String hash,Cancel cancel,Progress progress) throws IOException {
        directory(state,true); Path target=state.resolve(SELECTION); if(exists(target)&&!Files.isRegularFile(target,LinkOption.NOFOLLOW_LINKS)) throw new IOException("资源选择记录路径不安全，未切换资源");
        String prefix="WMMT-RESOURCE-SELECTION-1\nimported\n"+name+"\n"+hash+"\n";
        byte[] data=(prefix+hex(sha().digest(prefix.getBytes(StandardCharsets.US_ASCII)))+"\n").getBytes(StandardCharsets.US_ASCII);
        Path temp=state.resolve("selection-"+UUID.randomUUID()+".tmp"); Files.createFile(temp);
        try(FileOutputStream out=new FileOutputStream(temp.toFile())) { out.write(data); out.getFD().sync(); }
        sync(state); sync(noBackup); check(cancel); if(progress!=null) progress.update("publish",0,1); check(cancel);
        // Last commit point; no cancellation or failure result after the atomic switch.
        Files.move(temp,target,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
        // If the postcommit durability barrier fails, report committed success with a warning,
        // never a misleading failed-import result after the old selection has been replaced.
        try { sync(state); return true; } catch(IOException | RuntimeException durabilityFailure) { return false; }
    }
    private boolean isCompanion(SafeResourceZip zip) {
        return zip.members.values().stream().anyMatch(m->!m.directory) &&
                zip.members.values().stream().allMatch(m->m.directory || ResourceMetadata.companionPath(m.name));
    }

    private void importCompanion(SafeResourceZip zip,Path staging,Cancel cancel,Progress progress) throws IOException {
        List<String> required=new ArrayList<>(ResourceMetadata.OPTIONAL_PATHS.subList(0,4));
        required.addAll(ResourceMetadata.CARD_PATHS);
        required.addAll(ResourceMetadata.CONVERTED_PATHS);
        required.addAll(ResourceMetadata.FRONT_HALO_PATHS);
        for(String name:required) {
            SafeResourceZip.Member m=zip.members.get(name);
            if(m==null || m.directory) throw new IOException("附加资源包缺少 " + name);
        }
        long bytes=extraTotal();
        room(staging,bytes);
        for(SafeResourceZip.Member m:zip.members.values()) {
            check(cancel);
            if(m.directory) { zip.consume(m,null,cancel,progress,"verify-zip"); continue; }
            ResourceMetadata.Entry entry=metadata.find(m.name);
            if(entry==null || entry.length!=m.length) throw new IOException("附加资源大小不符 " + m.name);
            Path file=child(staging,m.name);
            if(!entry.sha256.equals(extract(zip,m,file,cancel,progress)))
                throw new IOException("附加资源内容不符 " + m.name);
        }
        syncTree(staging,cancel);
        Path old=null;
        try { old=companionRoot(); } catch(IOException invalid) { check(cancel); }
        directory(companions,true);
        String name=UUID.randomUUID().toString();
        Path target=companions.resolve(name);
        Files.move(staging,target,StandardCopyOption.ATOMIC_MOVE);
        Path pointer=null;
        boolean committed=false;
        try {
            sync(companions);
            sync(external);
            directory(state,true);
            pointer=Files.createTempFile(state,"companion-",".tmp");
            try(FileOutputStream out=new FileOutputStream(pointer.toFile())) {
                out.write(name.getBytes(StandardCharsets.US_ASCII));
                out.getFD().sync();
            }
            check(cancel);
            Files.move(pointer,state.resolve(COMPANION_SELECTION),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
            committed=true;
        } finally {
            if(!committed) try {
                if(pointer!=null) Files.deleteIfExists(pointer);
                deleteOwnedTree(target);
            } catch(IOException ignored) { /* Original selection is still intact. */ }
        }
        try {
            sync(state);
            if(old!=null) deleteOwnedTree(old);
        } catch(IOException ignored) { /* The selection was already committed. */ }
    }

    private static void deleteOwnedTree(Path root) throws IOException {
        safeChain(root);
        if(!exists(root)) return;
        Files.walkFileTree(root,new SimpleFileVisitor<Path>() {
            @Override public FileVisitResult visitFile(Path file,BasicFileAttributes attrs) throws IOException {
                Files.delete(file);
                return FileVisitResult.CONTINUE;
            }
            @Override public FileVisitResult postVisitDirectory(Path dir,IOException error) throws IOException {
                if(error!=null) throw error;
                Files.delete(dir);
                return FileVisitResult.CONTINUE;
            }
        });
    }

    public Ready importArchive(InputStream input,Cancel cancel,Progress progress) throws IOException {
        return importArchive(input,cancel,progress,false);
    }

    /** A null result in this overload means a companion was registered, with no main selection change. */
    public Ready importArchive(InputStream input,Cancel cancel,Progress progress,boolean allowCompanion) throws IOException {
        if(input==null) throw new IOException("未选择导入文件"); check(cancel); preflight(true);
        Pending pending=readPending(cancel,progress); directory(imported,true); room(imported,RESERVE);
        String name=UUID.randomUUID().toString(); Path root=imported.resolve(name); Files.createDirectory(root); sync(imported); sync(external);
        // All cache files and failed/abandoned outputs stay within this unique owned root.
        Path cache=root.resolve(".source.zip"); Files.createFile(cache); copySource(input,cache,cancel,progress);
        DataManifest chosen;
        boolean companion=false;
        try(SafeResourceZip zip=new SafeResourceZip(cache,zipEntries(),mainLimit()+EXTRA_LIMIT,cancel)) {
            companion=allowCompanion && isCompanion(zip);
            if(companion) {
                Path staging=Files.createTempDirectory(root,"addons-");
                importCompanion(zip,staging,cancel,progress);
                return null;
            }
            chosen=importMain(zip,root,cancel,progress);
        } finally {
            if(companion) try { deleteOwnedTree(root); }
            catch(IOException ignored) { /* A temporary tree can be removed by clear resources. */ }
        }
        Ready result=ready(root,false,cancel,progress); syncTree(root,cancel); sync(imported); check(cancel);
        // Existing registered recovery is a separate controlled transaction, never a repair
        // shortcut. No legacy byte is modified until ALL imported payloads have been checked.
        if(pending!=null) recoverPending(pending,cache,cancel,progress);
        check(cancel); preflight(false);
        if(!publish(name,chosen.zipSha256,cancel,progress)) {
            List<String> warnings=new ArrayList<String>(result.warnings); warnings.add("资源已切换，但选择记录的最终目录同步失败；下次启动将重新校验，请勿立即断电");
            return new Ready(result.dataDirectory,result.optionalDirectory,result.cardDirectory,warnings,result.optionalFiles);
        }
        return result;
    }
}
