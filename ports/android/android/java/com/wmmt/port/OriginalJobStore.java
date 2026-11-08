package com.wmmt.port;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.channels.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.*;
import java.security.*;
import java.util.*;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/** Independent self-produced conversion lane, NOT a converted-ZIP importer.
 * Every entry point requires the foreground caller to hold the existing
 * DataCoordinator.ProcessLock, and keep it through native shutdown. The old
 * ProcessLock API has no validation token; this is an explicit caller obligation.
 *
 * Only begin/loadJob mint Job capabilities from app-private owner records. Only
 * the APK's signed, controlled convert worker may generate outputs/completion:
 * it MUST authenticate the entire APK-pinned readset and Python full snapshot,
 * execute only packaged code, validate the format closure, then CREATE_NEW and
 * fsync completion.tsv. Service JSON is notification only, never authority.
 * A later private HMAC registers that controlled job's output against tampering;
 * it is NOT a pre-signed gold baseline and never extends old DMF1 ownership.
 *
 * Noncooperating/root writers are out of scope, as in ResourceStore. Component
 * nofollow and before/after identity checks detect observed substitutions; Java
 * Path APIs do not offer an atomic whole-chain openat guarantee on every Android
 * filesystem. No old input, save, legacy transaction or unknown directory is
 * deleted, adopted, modified, or recovered by this class. Partial roots remain.
 */
public final class OriginalJobStore {
    public interface Cancel { boolean cancelled(); }
    public interface Progress { void update(String stage,long current,long total); }
    public static final class Job {
        public final String id, nonce, profileSha256;
        public final Path root;
        private Job(String i,String n,Path r,String h) { id=i; nonce=n; root=r; profileSha256=h; }
    }
    public static final class Ready {
        public final Path dataDirectory;
        public final String installId;
        public final List<String> warnings;
        private Ready(Path p,String id,List<String> w) { dataDirectory=p; installId=id; warnings=Collections.unmodifiableList(new ArrayList<String>(w)); }
    }
    /** Package-private deterministic failure hooks; production always uses DEFAULT. */
    interface Hooks {
        default void at(String stage,Path path) throws IOException { }
        default long usable(Path path) throws IOException { return path.toFile().getUsableSpace(); }
        default void force(FileChannel file) throws IOException { file.force(true); }
        default void sync(Path path) throws IOException {
            try(FileChannel channel=FileChannel.open(path,StandardOpenOption.READ)) { channel.force(true); }
            catch(UnsupportedOperationException e) { throw new IOException("Directory fsync unavailable",e); }
        }
    }
    private static final Hooks DEFAULT=new Hooks() { };
    private static final LinkOption[] NOFOLLOW={LinkOption.NOFOLLOW_LINKS};
    private static final String UUID_RE="[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
    private static final int COMPLETION_LIMIT=2*1024*1024;
    private static final int LEGACY_SELECTION_LIMIT=1024, LEGACY_MANIFEST_LIMIT=8*1024*1024;
    private static final long RESERVE=64L*1024*1024;
    private final Path external,noBackup,jobs,state,installations,choice,oldState,published;
    private final OriginalProfile profile;
    private final Hooks hooks;
    private final SecureRandom random=new SecureRandom();

    public OriginalJobStore(Path externalRoot,Path noBackupRoot,OriginalProfile p) { this(externalRoot,noBackupRoot,p,DEFAULT); }
    OriginalJobStore(Path externalRoot,Path noBackupRoot,OriginalProfile p,Hooks h) {
        external=Objects.requireNonNull(externalRoot).toAbsolutePath().normalize();
        noBackup=Objects.requireNonNull(noBackupRoot).toAbsolutePath().normalize();
        profile=Objects.requireNonNull(p); hooks=Objects.requireNonNull(h);
        if(external.equals(noBackup) || external.startsWith(noBackup) || noBackup.startsWith(external))
            throw new IllegalArgumentException("Private and external roots must be disjoint");
        jobs=noBackup.resolve("re3dxplus-original-jobs"); state=noBackup.resolve("original-convert-v1");
        installations=state.resolve("installations"); choice=noBackup.resolve("resource-choice-v2");
        oldState=noBackup.resolve("game-data-state"); published=external.resolve("re3dxplus-original");
    }
    private static IOException bad(String s) { return new IOException(s); }
    private static boolean exists(Path p) { return Files.exists(p,NOFOLLOW); }
    private static void check(Cancel c) throws InterruptedIOException {
        if(Thread.currentThread().isInterrupted() || c!=null && c.cancelled()) throw new InterruptedIOException("Original conversion cancelled; previous selection and all files preserved");
    }
    private static void safeChain(Path p) throws IOException {
        Path q=p.getRoot();
        for(Path part:p) { q=q.resolve(part); if(Files.isSymbolicLink(q)) throw bad("Symlink in storage path"); }
    }
    private static void directory(Path p,boolean create,boolean privateMode) throws IOException {
        safeChain(p);
        if(!exists(p) && create) {
            directory(p.getParent(),true,privateMode);
            createDirectory(p,privateMode);
        }
        safeChain(p);
        if(!Files.isDirectory(p,NOFOLLOW)) throw bad("Missing or unsafe storage directory");
    }
    private static void createDirectory(Path p,boolean privateMode) throws IOException {
        safeChain(p.getParent());
        if(privateMode) {
            try { Files.createDirectory(p,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------"))); return; }
            catch(UnsupportedOperationException e) { /* Android/app-private filesystem may expose no POSIX view. */ }
        }
        Files.createDirectory(p);
    }
    private static FileChannel newFile(Path p,boolean privateMode) throws IOException {
        safeChain(p); Set<OpenOption> options=new HashSet<OpenOption>(Arrays.asList(StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS));
        if(privateMode) {
            try { return FileChannel.open(p,options,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------"))); }
            catch(UnsupportedOperationException e) { /* Fall back only when permissions are unsupported, not on I/O failure. */ }
        }
        return FileChannel.open(p,options);
    }
    private static void writeNew(Path p,byte[] bytes,boolean privateMode) throws IOException {
        try(FileChannel out=newFile(p,privateMode)) { ByteBuffer b=ByteBuffer.wrap(bytes); while(b.hasRemaining()) out.write(b); out.force(true); }
    }
    private void sync(Path p) throws IOException { safeChain(p); hooks.sync(p); }
    private void stage(String s,Path path,Cancel c,Progress progress,long n,long total) throws IOException {
        check(c); hooks.at(s,path); if(progress!=null) progress.update(s,n,total); check(c);
    }
    private void room(Path p,long bytes) throws IOException {
        long reserve=Math.max(RESERVE,bytes/20),free=hooks.usable(p);
        if(bytes<0 || bytes>Long.MAX_VALUE-reserve || free<bytes+reserve) throw bad("Insufficient space; previous resources retained");
    }
    private void preflight() throws IOException {
        directory(external,false,false); directory(noBackup,false,true);
        ResourceStore.requireClearFinished(noBackup);
        safeChain(oldState);
        if(exists(oldState)) {
            directory(oldState,false,true);
            if(exists(oldState.resolve("pending"))) throw bad("Legacy pending update requires its exact original import source; new lane is blocked");
            for(String name:new String[]{"overlay.journal","old.manifest","new.manifest"})
                if(exists(oldState.resolve(name))) throw bad("Unbound legacy update state; preserved for recovery");
            try(DirectoryStream<Path> ds=Files.newDirectoryStream(oldState,"txn-*")) {
                if(ds.iterator().hasNext()) throw bad("Unbound legacy transaction; preserved for recovery");
            }
        }
        // Only central selection and legacy recovery gates are universal.
        // Inactive original job/installation/external roots must not shadow a
        // newer prepared selection. Validate each lane root when it is used.
        safeChain(choice); if(exists(choice)) directory(choice,false,true);
    }
    private static BasicFileAttributes attrs(Path p) throws IOException {
        safeChain(p); return Files.readAttributes(p,BasicFileAttributes.class,NOFOLLOW);
    }
    private static boolean same(BasicFileAttributes a,BasicFileAttributes b) {
        return a.isRegularFile()==b.isRegularFile() && a.isDirectory()==b.isDirectory() &&
                Objects.equals(a.fileKey(),b.fileKey()) && a.size()==b.size() && a.lastModifiedTime().equals(b.lastModifiedTime());
    }
    private static byte[] small(Path p,int max) throws IOException {
        BasicFileAttributes before=attrs(p);
        if(!before.isRegularFile() || before.size()<1 || before.size()>max) throw bad("Missing or oversized private record");
        byte[] bytes;
        try(InputStream in=Files.newInputStream(p,LinkOption.NOFOLLOW_LINKS)) { bytes=OriginalProfile.bounded(in,max); }
        if(bytes.length!=before.size() || !same(before,attrs(p))) throw bad("Private record changed while reading");
        return bytes;
    }
    private static byte[] ascii(String s) { return s.getBytes(StandardCharsets.US_ASCII); }
    private static byte[] utf8(String s) { return s.getBytes(StandardCharsets.UTF_8); }
    private static String digest(byte[] b) { return OriginalProfile.hex(OriginalProfile.sha().digest(b)); }
    private static void uuid(String id) throws IOException { if(id==null || !id.matches(UUID_RE)) throw bad("Invalid job/install UUID"); }
    private String owner(Job j) {
        return "WMMT-ORIGINAL-JOB-1\njob\t"+j.id+"\nnonce\t"+j.nonce+"\nprofile\t"+j.profileSha256+"\nEND\n";
    }
    private Job checkedJob(Job j) throws IOException {
        if(j==null) throw bad("Missing process-minted Job"); uuid(j.id); OriginalProfile.hashSyntax(j.nonce);
        if(!profile.sha256.equals(j.profileSha256) || !jobs.resolve(j.id).equals(j.root)) throw bad("Job belongs to another store/profile");
        directory(j.root,false,true);
        if(!Arrays.equals(small(j.root.resolve("owner.tsv"),1024),ascii(owner(j)))) throw bad("Job owner changed");
        return j;
    }
    public Job begin(Cancel cancel,Progress progress) throws IOException {
        check(cancel); preflight(); stage("begin",jobs,cancel,progress,0,1);
        directory(jobs,true,true); room(noBackup,RESERVE);
        String id=UUID.randomUUID().toString(); Path root=jobs.resolve(id);
        createDirectory(root,true); byte[] nonce=new byte[32]; random.nextBytes(nonce);
        Job job=new Job(id,OriginalProfile.hex(nonce),root,profile.sha256);
        writeNew(root.resolve("owner.tsv"),ascii(owner(job)),true);
        createDirectory(root.resolve("outputs"),true); createDirectory(root.resolve("snapshots"),true);
        sync(root); sync(jobs); sync(noBackup); check(cancel);
        return job;
    }
    /** Recover only a UUID under this store's private owner root. No external path/receipt input. */
    public Job loadJob(UUID id) throws IOException {
        check(null); preflight(); if(id==null) throw bad("Missing job UUID");
        Path root=jobs.resolve(id.toString()); directory(root,false,true);
        String[] f=OriginalProfile.lines(small(root.resolve("owner.tsv"),1024));
        if(f.length!=5 || !f[0].equals("WMMT-ORIGINAL-JOB-1") || !f[4].equals("END")) throw bad("Invalid job owner");
        String jobId=OriginalProfile.header(f[1],"job"),nonce=OriginalProfile.header(f[2],"nonce"),hash=OriginalProfile.header(f[3],"profile");
        if(!id.toString().equals(jobId)) throw bad("Owner UUID mismatch");
        return checkedJob(new Job(jobId,nonce,root,hash));
    }
    private String jobJson(Job j,String kind) {
        return "{\"schema\":\"wmmt-original-job-v1\",\"job_id\":\""+j.id+"\",\"nonce\":\""+j.nonce+
                "\",\"profile_sha256\":\""+profile.sha256+"\",\"readset_sha256\":\""+profile.readsetSha256+
                "\",\"recipe_sha256\":\""+profile.recipeSha256+"\",\"source_kind\":\""+kind+
                "\",\"source_path\":\""+(kind.equals("zip")?"incoming.zip":"incoming")+"\",\"profile_id\":\""+profile.profileId+"\"}\n";
    }
    /** Broker has created incoming.zip or incoming; this seals only the fixed job
     * envelope. Source hashes/readonly snapshot/format validation belong to the
     * controlled worker and MUST finish before it creates completion.tsv. */
    public void sealSource(Job job,String kind) throws IOException {
        check(null); preflight(); checkedJob(job);
        if(!"zip".equals(kind) && !"tree".equals(kind)) throw bad("Source kind must be zip or tree");
        Path source=job.root.resolve(kind.equals("zip")?"incoming.zip":"incoming");
        BasicFileAttributes sourceAttrs=attrs(source);
        if(kind.equals("zip")?(!sourceAttrs.isRegularFile() || sourceAttrs.size()<1):!sourceAttrs.isDirectory()) throw bad("Missing or unsafe broker source");
        directory(job.root.resolve("outputs"),false,true); directory(job.root.resolve("snapshots"),false,true);
        if(exists(job.root.resolve("job.json")) || exists(job.root.resolve("completion.tsv"))) throw bad("Job already sealed or has premature completion");
        byte[] data=utf8(jobJson(job,kind));
        Path temp=job.root.resolve("job-"+UUID.randomUUID()+".tmp"); writeNew(temp,data,true); sync(job.root);
        checkedJob(job); if(exists(job.root.resolve("job.json"))) throw bad("Job envelope appeared during sealing");
        // Both operands are checked absolute direct children of the minted root.
        moveAtomic(temp,job.root.resolve("job.json"),false);
        sync(job.root);
    }
    private String sealedKind(Job j) throws IOException {
        byte[] record=small(j.root.resolve("job.json"),1024*1024);
        for(String kind:new String[]{"zip","tree"}) if(Arrays.equals(record,utf8(jobJson(j,kind)))) return kind;
        throw bad("Job envelope does not match minted owner/profile");
    }
    private static void moveAtomic(Path source,Path target,boolean replace) throws IOException {
        if(!source.isAbsolute() || !target.isAbsolute() || !source.normalize().equals(source) || !target.normalize().equals(target) ||
                !source.getParent().equals(target.getParent()) || source.equals(target)) throw bad("Unsafe atomic move target");
        safeChain(source); safeChain(target);
        if(!Files.isRegularFile(source,NOFOLLOW)) throw bad("Atomic source is not a regular file");
        if(!replace && exists(target)) throw bad("Refusing to overwrite unknown record");
        if(replace) Files.move(source,target,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
        else Files.move(source,target,StandardCopyOption.ATOMIC_MOVE);
    }
    private static final class Entry {
        final String path,hash; final long length;
        Entry(String p,long n,String h) { path=p; length=n; hash=h; }
    }
    private static final class Completion {
        final String jobId,nonce,output,digest; final byte[] bytes;
        final SortedMap<String,Entry> files;
        final long total;
        Completion(String id,String n,String out,byte[] b,SortedMap<String,Entry> f,long t) {
            jobId=id; nonce=n; output=out; bytes=b; digest=digest(b); files=f; total=t;
        }
    }
    private Completion completion(byte[] bytes,Job job) throws IOException {
        String[] lines=OriginalProfile.lines(bytes);
        if(lines.length!=OriginalProfile.OUTPUT_COUNT+7 || !lines[0].equals("WMMT-ORIGINAL-COMPLETION-1") || !lines[lines.length-1].equals("END")) throw bad("Incomplete completion");
        String id=OriginalProfile.header(lines[1],"job"),nonce=OriginalProfile.header(lines[2],"nonce"),hash=OriginalProfile.header(lines[3],"profile");
        uuid(id); OriginalProfile.hashSyntax(nonce);
        if(!hash.equals(profile.sha256) || !OriginalProfile.header(lines[4],"readset").equals(profile.readsetSha256)) throw bad("Completion profile/readset mismatch");
        if(job!=null && (!job.id.equals(id) || !job.nonce.equals(nonce))) throw bad("Completion owner/nonce mismatch");
        String output=OriginalProfile.header(lines[5],"output");
        if(!output.matches("original-convert-[0-9a-f]{32}")) throw bad("Invalid controlled output name");
        SortedMap<String,Entry> files=new TreeMap<String,Entry>(); String previous=null; long total=0;
        for(int i=6;i<lines.length-1;i++) {
            String[] f=lines[i].split("\t",-1);
            if(f.length!=4 || !f[0].equals("file")) throw bad("Invalid completion row");
            OriginalProfile.path(f[1],true);
            OriginalProfile.Output spec=profile.outputs.get(f[1]);
            if(spec==null || previous!=null && previous.compareTo(f[1])>=0) throw bad("Unexpected, duplicate, or unsorted completion file");
            long length=OriginalProfile.number(f[2],spec.maxLength); OriginalProfile.hashSyntax(f[3]);
            if(spec.exactSha256!=null && !spec.exactSha256.equals(f[3])) throw bad("Pinned output SHA mismatch");
            if(length>profile.maxOutputBytes-total) throw bad("Completion size limit");
            total+=length; files.put(f[1],new Entry(f[1],length,f[3])); previous=f[1];
        }
        if(!files.keySet().equals(profile.outputs.keySet())) throw bad("Completion roster mismatch");
        return new Completion(id,nonce,output,bytes,files,total);
    }
    private Path member(Path root,String path) throws IOException {
        OriginalProfile.path(path,true); Path p=root.resolve(path).normalize();
        if(!p.startsWith(root) || p.equals(root)) throw bad("Output path escaped root"); safeChain(p); return p;
    }
    /** Exact tree closure, including directories: unknown empty directories are
     * rejected as well as extra files; traversal never follows symlinks. */
    private void tree(Path root,Completion c,Cancel cancel) throws IOException {
        directory(root,false,false); Set<String> dirs=new HashSet<String>(); dirs.add("");
        for(String name:c.files.keySet()) { int i=name.indexOf('/'); while(i>=0) { dirs.add(name.substring(0,i)); i=name.indexOf('/',i+1); } }
        Set<String> seen=new HashSet<String>(); Set<Object> inodes=new HashSet<Object>();
        Files.walkFileTree(root,new SimpleFileVisitor<Path>() {
            @Override public FileVisitResult preVisitDirectory(Path d,BasicFileAttributes a) throws IOException {
                check(cancel); safeChain(d); String path=root.relativize(d).toString().replace(File.separatorChar,'/');
                if(!a.isDirectory() || a.isSymbolicLink() || !dirs.contains(path)) throw bad("Unexpected output directory");
                return FileVisitResult.CONTINUE;
            }
            @Override public FileVisitResult visitFile(Path f,BasicFileAttributes a) throws IOException {
                check(cancel); safeChain(f); String path=root.relativize(f).toString().replace(File.separatorChar,'/'); Entry e=c.files.get(path);
                if(!a.isRegularFile() || a.isSymbolicLink() || e==null || a.size()!=e.length || !seen.add(path) || a.fileKey()!=null && !inodes.add(a.fileKey())) throw bad("Unexpected, aliased, or damaged output file");
                return FileVisitResult.CONTINUE;
            }
        });
        if(!seen.equals(c.files.keySet())) throw bad("Output tree missing files");
    }
    private String streamFile(Path path,Entry e,FileChannel target,Cancel cancel,Progress progress,String phase) throws IOException {
        BasicFileAttributes before=attrs(path);
        if(!before.isRegularFile() || before.size()!=e.length) throw bad("Missing or wrong-sized output");
        MessageDigest d=OriginalProfile.sha(); long count=0; byte[] buf=new byte[65536];
        stage(phase+":before-open",path,cancel,progress,0,e.length);
        if(!same(before,attrs(path))) throw bad("Output changed before open");
        try(InputStream in=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS)) {
            while(true) {
                check(cancel); int n=in.read(buf); if(n<0) break; if(n==0) continue;
                if(n>e.length-count) throw bad("Output grew while reading"); d.update(buf,0,n);
                if(target!=null) { ByteBuffer b=ByteBuffer.wrap(buf,0,n); while(b.hasRemaining()) target.write(b); }
                count+=n; if(progress!=null) progress.update(phase,count,e.length); check(cancel);
            }
        }
        if(count!=e.length || !same(before,attrs(path))) throw bad("Output changed while reading");
        String actual=OriginalProfile.hex(d.digest()); if(!actual.equals(e.hash)) throw bad("Output content hash mismatch"); return actual;
    }
    private void verify(Path root,Completion c,Cancel cancel,Progress progress,String phase) throws IOException {
        tree(root,c,cancel); int count=0;
        for(Entry e:c.files.values()) { streamFile(member(root,e.path),e,null,cancel,progress,phase); stage(phase+":files",root,cancel,progress,++count,c.files.size()); }
        tree(root,c,cancel);
    }
    private void syncTree(Path root,Cancel cancel) throws IOException {
        List<Path> dirs=new ArrayList<Path>();
        Files.walkFileTree(root,new SimpleFileVisitor<Path>() {
            @Override public FileVisitResult preVisitDirectory(Path d,BasicFileAttributes a) throws IOException { check(cancel); safeChain(d); dirs.add(d); return FileVisitResult.CONTINUE; }
            @Override public FileVisitResult visitFile(Path f,BasicFileAttributes a) throws IOException { if(!a.isRegularFile() || a.isSymbolicLink()) throw bad("Unsafe published tree"); return FileVisitResult.CONTINUE; }
        });
        Collections.reverse(dirs); for(Path d:dirs) { check(cancel); sync(d); }
    }
    private byte[] key(boolean create) throws IOException {
        Path key=state.resolve("hmac.key");
        if(!exists(key)) {
            if(!create) throw bad("Missing original-lane HMAC key; no fallback");
            directory(state,true,true); byte[] fresh=new byte[32]; random.nextBytes(fresh);
            writeNew(key,fresh,true); sync(state); sync(noBackup);
        }
        byte[] value=small(key,32); if(value.length!=32) throw bad("Invalid HMAC key; not overwritten");
        boolean allZero=true; for(byte b:value) if(b!=0) allZero=false;
        if(allZero) throw bad("Invalid all-zero HMAC key; not overwritten"); return value;
    }
    private static String mac(byte[] key,byte[] body) throws IOException {
        try { Mac m=Mac.getInstance("HmacSHA256"); m.init(new SecretKeySpec(key,"HmacSHA256")); return OriginalProfile.hex(m.doFinal(body)); }
        catch(GeneralSecurityException e) { throw new IOException("HMAC unavailable",e); }
    }
    private static byte[] authenticated(String body,byte[] key) throws IOException { return utf8(body+"hmac\t"+mac(key,utf8(body))+"\nEND\n"); }
    private static String[] authenticate(byte[] bytes,byte[] key) throws IOException {
        String[] f=OriginalProfile.lines(bytes);
        if(f.length<3 || !f[f.length-1].equals("END")) throw bad("Invalid authenticated record");
        String expected=OriginalProfile.header(f[f.length-2],"hmac"); OriginalProfile.hashSyntax(expected);
        StringBuilder body=new StringBuilder(); for(int i=0;i<f.length-2;i++) body.append(f[i]).append('\n');
        if(!MessageDigest.isEqual(ascii(expected),ascii(mac(key,utf8(body.toString()))))) throw bad("Original-lane HMAC mismatch; files preserved, no fallback");
        return Arrays.copyOf(f,f.length-2);
    }
    /** Two old Store selector authorities are private app state, not external
     * resource ownership. Their presence and exact byte identities form an epoch
     * barrier: a successful old import must not be shadowed if this process dies
     * before markPreparedSelection can update the separate central pointer. */
    private String legacyEpoch() throws IOException {
        Path oldImport=noBackup.resolve("resource-import-v1"); safeChain(oldImport);
        if(exists(oldImport)) directory(oldImport,false,true);
        Path oldSelection=oldImport.resolve("selection"),active=oldState.resolve("active.manifest");
        String selectionDigest=exists(oldSelection)?digest(small(oldSelection,LEGACY_SELECTION_LIMIT)):"-";
        String activeDigest=exists(active)?digest(small(active,LEGACY_MANIFEST_LIMIT)):"-";
        return digest(ascii("WMMT-ORIGINAL-LEGACY-EPOCH-1\nimportSelection\t"+selectionDigest+"\nactiveManifest\t"+activeDigest+"\n"));
    }
    private static final class Selection {
        final String kind,id,profile,digest,legacyEpoch; final byte[] bytes;
        Selection(String k,String i,String p,String d,String e,byte[] b) { kind=k; id=i; profile=p; digest=d; legacyEpoch=e; bytes=b; }
    }
    private Selection selection(byte[] key) throws IOException {
        Path file=choice.resolve("selection"); if(!exists(file)) return null;
        byte[] bytes=small(file,2048); String[] f=authenticate(bytes,key);
        if(f.length!=6 || !f[0].equals("WMMT-RESOURCE-CHOICE-2")) throw bad("Unknown central choice");
        String kind=OriginalProfile.header(f[1],"kind"),id=OriginalProfile.header(f[2],"installation"),p=OriginalProfile.header(f[3],"profile"),d=OriginalProfile.header(f[4],"completion"),epoch=OriginalProfile.header(f[5],"legacyEpoch");
        if(kind.equals("original")) { uuid(id); OriginalProfile.hashSyntax(p); OriginalProfile.hashSyntax(d); OriginalProfile.hashSyntax(epoch); }
        else if(!kind.equals("prepared") || !id.equals("-") || !p.equals("-") || !d.equals("-") || !epoch.equals("-")) throw bad("Unknown central choice kind");
        return new Selection(kind,id,p,d,epoch,bytes);
    }
    private interface CommitCheck { void run() throws IOException; }
    private boolean commitChoice(byte[] data,Selection previous,Cancel cancel,Progress progress,CommitCheck guard) throws IOException {
        directory(choice,true,true); Path target=choice.resolve("selection"),temp=choice.resolve("selection-"+UUID.randomUUID()+".tmp");
        writeNew(temp,data,true); sync(choice); sync(noBackup);
        stage("selection:before-commit",target,cancel,progress,0,1); preflight();
        if(guard!=null) guard.run(); check(cancel);
        if(previous==null?exists(target):!Arrays.equals(previous.bytes,small(target,2048))) throw bad("Central selection changed; no overwrite");
        // Final operation that can fail: both operands are fixed checked children.
        moveAtomic(temp,target,true);
        // No callbacks/cancellation/ordinary failed result after this point.
        try { sync(choice); return true; } catch(IOException | RuntimeException e) { return false; }
    }
    private void registrationClosure(Path registration) throws IOException {
        directory(registration,false,true); Set<String> names=new HashSet<String>();
        try(DirectoryStream<Path> ds=Files.newDirectoryStream(registration)) {
            for(Path p:ds) {
                String name=p.getFileName().toString();
                if((!name.equals("completion.tsv") && !name.equals("installation.tsv")) || !attrs(p).isRegularFile() || !names.add(name))
                    throw bad("Unknown or unsafe private installation record");
            }
        }
        if(names.size()!=2) throw bad("Incomplete private installation records");
    }
    private String installationBody(String id,Job j,String sourceKind,String jobDigest,Completion c,String epoch) {
        return "WMMT-ORIGINAL-INSTALLATION-1\ninstallation\t"+id+"\nprofile\t"+profile.sha256+
                "\nprofileId\t"+profile.profileId+"\nreadset\t"+profile.readsetSha256+"\nrecipe\t"+profile.recipeSha256+
                "\nsourceBytes\t"+profile.sourceBytes+"\njob\t"+j.id+"\nnonce\t"+j.nonce+
                "\nsourceKind\t"+sourceKind+"\njobSha256\t"+jobDigest+"\ncompletion\t"+c.digest+"\nlegacyEpoch\t"+epoch+"\n";
    }
    public Ready publish(Job job,Cancel cancel,Progress progress) throws IOException {
        check(cancel); preflight(); checkedJob(job); String sourceKind=sealedKind(job); String epoch=legacyEpoch();
        byte[] jobRecord=small(job.root.resolve("job.json"),1024*1024);
        Completion c=completion(small(job.root.resolve("completion.tsv"),COMPLETION_LIMIT),job);
        Path outputs=job.root.resolve("outputs"); directory(outputs,false,true); Path source=outputs.resolve(c.output);
        stage("publish:verify",source,cancel,progress,0,c.files.size()); verify(source,c,cancel,progress,"verify-private");
        byte[] k=key(!exists(choice.resolve("selection"))); Selection previous=selection(k);
        directory(published,true,false); room(published,c.total);
        String installId=UUID.randomUUID().toString(); Path install=published.resolve(installId),data=install.resolve("data");
        createDirectory(install,false); createDirectory(data,false); sync(published); sync(external);
        int count=0;
        for(Entry e:c.files.values()) {
            check(cancel); Path target=member(data,e.path); directory(target.getParent(),true,false); room(target.getParent(),e.length);
            stage("copy:before-file",target,cancel,progress,count,c.files.size());
            // Exclusive create, no truncation, no overwrite, no rollback cleanup.
            try(FileChannel out=newFile(target,false)) { streamFile(member(source,e.path),e,out,cancel,progress,"copy-output"); hooks.force(out); }
            stage("copy:files",data,cancel,progress,++count,c.files.size());
        }
        verify(data,c,cancel,progress,"verify-published"); syncTree(data,cancel); sync(install); sync(published);
        checkedJob(job);
        if(!Arrays.equals(jobRecord,small(job.root.resolve("job.json"),1024*1024)) || !Arrays.equals(c.bytes,small(job.root.resolve("completion.tsv"),COMPLETION_LIMIT))) throw bad("Private completion/job changed during publish");
        directory(installations,true,true); Path registration=installations.resolve(installId); createDirectory(registration,true);
        writeNew(registration.resolve("completion.tsv"),c.bytes,true);
        writeNew(registration.resolve("installation.tsv"),authenticated(installationBody(installId,job,sourceKind,digest(jobRecord),c,epoch),k),true);
        sync(registration); sync(installations); sync(state); sync(noBackup);
        stage("publish:registered",registration,cancel,progress,1,1);
        // Recheck closure/content after injectable callbacks and before selection.
        verify(data,c,cancel,progress,"verify-final");
        String body="WMMT-RESOURCE-CHOICE-2\nkind\toriginal\ninstallation\t"+installId+"\nprofile\t"+profile.sha256+"\ncompletion\t"+c.digest+"\nlegacyEpoch\t"+epoch+"\n";
        boolean durable=commitChoice(authenticated(body,k),previous,cancel,progress,new CommitCheck() {
            @Override public void run() throws IOException {
            // A callback immediately before commit cannot smuggle a changed tree
            // or private record past the earlier verification pass.
            checkedJob(job); registrationClosure(registration);
            if(!epoch.equals(legacyEpoch())) throw bad("Prepared selection changed during original publication; previous choice retained");
            if(!Arrays.equals(jobRecord,small(job.root.resolve("job.json"),1024*1024)) ||
                    !Arrays.equals(c.bytes,small(job.root.resolve("completion.tsv"),COMPLETION_LIMIT)) ||
                    !Arrays.equals(c.bytes,small(registration.resolve("completion.tsv"),COMPLETION_LIMIT)) ||
                    !Arrays.equals(authenticated(installationBody(installId,job,sourceKind,digest(jobRecord),c,epoch),k),small(registration.resolve("installation.tsv"),4096)))
                throw bad("Registered job/completion changed before selection");
            verify(data,c,cancel,null,"verify-commit");
            if(!epoch.equals(legacyEpoch())) throw bad("Prepared selection changed before original commit");
            }
        });
        List<String> warnings=new ArrayList<String>();
        if(!durable) warnings.add("Resources selected, but final directory sync failed; next launch will reverify");
        return new Ready(data,installId,warnings);
    }
    /** Missing/prepared central choice delegates to unchanged ResourceStore.
     * A corrupt original choice never falls back to another tree or old selection. */
    public Ready resolve(Cancel cancel,Progress progress) throws IOException {
        check(cancel); preflight();
        if(!exists(choice.resolve("selection"))) return null;
        byte[] k=key(false); Selection s=selection(k);
        if(s.kind.equals("prepared")) return null;
        // Validate the app-private epoch BEFORE requiring an obsolete original
        // profile/registration/tree: a committed old import wins even if this
        // process crashed before it could mark the separate choice prepared.
        if(!s.legacyEpoch.equals(legacyEpoch())) {
            if(!Arrays.equals(s.bytes,small(choice.resolve("selection"),2048))) throw bad("Selection changed during epoch verification");
            check(cancel); return null;
        }
        if(!s.profile.equals(profile.sha256)) {
            if(OriginalProfilePin.requiresReconversion(s.profile)) throw new IOException(OriginalProfilePin.UPGRADE_HINT);
            throw bad("Selected original profile differs from this APK; no fallback");
        }
        Path registration=installations.resolve(s.id); registrationClosure(registration);
        String[] f=authenticate(small(registration.resolve("installation.tsv"),4096),k);
        if(f.length!=13 || !f[0].equals("WMMT-ORIGINAL-INSTALLATION-1") ||
                !OriginalProfile.header(f[1],"installation").equals(s.id) || !OriginalProfile.header(f[2],"profile").equals(profile.sha256) ||
                !OriginalProfile.header(f[3],"profileId").equals(profile.profileId) || !OriginalProfile.header(f[4],"readset").equals(profile.readsetSha256) ||
                !OriginalProfile.header(f[5],"recipe").equals(profile.recipeSha256) || !OriginalProfile.header(f[6],"sourceBytes").equals(Long.toString(profile.sourceBytes)) ||
                !OriginalProfile.header(f[12],"legacyEpoch").equals(s.legacyEpoch)) throw bad("Private installation/profile/epoch mismatch");
        String jobId=OriginalProfile.header(f[7],"job"),nonce=OriginalProfile.header(f[8],"nonce"),sourceKind=OriginalProfile.header(f[9],"sourceKind"),jobDigest=OriginalProfile.header(f[10],"jobSha256"),completionDigest=OriginalProfile.header(f[11],"completion");
        uuid(jobId); OriginalProfile.hashSyntax(nonce); OriginalProfile.hashSyntax(jobDigest); OriginalProfile.hashSyntax(completionDigest);
        if(!sourceKind.equals("zip") && !sourceKind.equals("tree")) throw bad("Invalid registered source kind");
        Completion c=completion(small(registration.resolve("completion.tsv"),COMPLETION_LIMIT),null);
        if(!c.digest.equals(s.digest) || !c.digest.equals(completionDigest) || !c.jobId.equals(jobId) || !c.nonce.equals(nonce) ||
                !digest(utf8(jobJson(new Job(jobId,nonce,jobs.resolve(jobId),profile.sha256),sourceKind))).equals(jobDigest)) throw bad("Registered completion/input identity mismatch");
        Path data=published.resolve(s.id).resolve("data"); verify(data,c,cancel,progress,"resolve-original");
        if(!Arrays.equals(s.bytes,small(choice.resolve("selection"),2048))) throw bad("Selection changed during verification");
        check(cancel); return new Ready(data,s.id,Collections.<String>emptyList());
    }
    /** Call ONLY after old ResourceStore import has succeeded under the same lock.
     * No old Store state is written. There is no cancellation after atomic commit. */
    public void markPreparedSelection() throws IOException {
        check(null); preflight(); byte[] k=key(!exists(choice.resolve("selection"))); Selection previous=selection(k);
        String body="WMMT-RESOURCE-CHOICE-2\nkind\tprepared\ninstallation\t-\nprofile\t-\ncompletion\t-\nlegacyEpoch\t-\n";
        commitChoice(authenticated(body,k),previous,null,null,null);
    }
}
