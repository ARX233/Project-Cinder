package com.wmmt.port;
import java.io.*;
import java.nio.channels.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.*;
import java.util.*;
/** Caller holds a process-wide lock through native shutdown. Root/ADB and other
 * non-cooperating writers must not mutate data. Directory fsync is not guaranteed. */
public final class DataCoordinator {
 private static final String ID="re3dxplus-data-v1", MARKER=".re3dxplus-install-v1";
 private final Path base,state; private final DataManifest.Limits limits; private final DirectorySync sync; private final Baselines baselines;
 public interface Fault { void at(String stage) throws IOException; }
 /** Only inventories authenticated by the signed package may be supplied here.
  * A completion marker is a lookup key, never proof of resource ownership. */
 public interface Baselines { DataManifest find(String zipSha256) throws IOException; }
 private static final Set<String> HELD_LOCKS=new HashSet<>();
 public static final class ProcessLock implements Closeable {
  private final RandomAccessFile file; private final FileLock lock; private final String path;
  private ProcessLock(RandomAccessFile f,FileLock l,String p){file=f;lock=l;path=p;}
  public boolean valid(){return lock.isValid();}
  public void close() throws IOException {synchronized(HELD_LOCKS){try{lock.release();}finally{try{file.close();}finally{HELD_LOCKS.remove(path);}}}}
 }
 public static ProcessLock acquire(Path lockPath)throws IOException {
  String path=lockPath.toFile().getCanonicalPath();synchronized(HELD_LOCKS){
   if(HELD_LOCKS.contains(path))throw new IOException("Another process is using game data");
   RandomAccessFile f=new RandomAccessFile(path,"rw");
   try{FileLock l=f.getChannel().tryLock();if(l==null)throw new IOException("Another process is using game data");HELD_LOCKS.add(path);return new ProcessLock(f,l,path);}
   catch(OverlappingFileLockException e){f.close();throw new IOException("Another process is using game data",e);}
   catch(IOException | RuntimeException e){f.close();throw e;}
  }
 }
 public interface DirectorySync { void sync(Path path) throws IOException; }
 public DataCoordinator(Path b,Path s,DataManifest.Limits l){this(b,s,l,DataCoordinator::nativeSyncDir,null);}
 public DataCoordinator(Path b,Path s,DataManifest.Limits l,DirectorySync d){this(b,s,l,d,null);}
 public DataCoordinator(Path b,Path s,DataManifest.Limits l,DirectorySync d,Baselines history){base=b.toAbsolutePath().normalize();state=s.toAbsolutePath().normalize();limits=l;sync=Objects.requireNonNull(d);baselines=history;}
 public static DataCoordinator withBaselines(Path b,Path s,DataManifest.Limits l,Baselines history){return new DataCoordinator(b,s,l,DataCoordinator::nativeSyncDir,Objects.requireNonNull(history));}
 private Path p(String s){return state.resolve(s);} private static boolean exists(Path p){return Files.exists(p,LinkOption.NOFOLLOW_LINKS);}
 private static void hit(Fault f,String s)throws IOException{if(f!=null)f.at(s);}
 private static void nativeSyncDir(Path p)throws IOException{try(FileChannel c=FileChannel.open(p,StandardOpenOption.READ)){c.force(true);}catch(UnsupportedOperationException | SecurityException e){throw new IOException("Cannot sync directory: "+p,e);}}
 private void syncDir(Path p)throws IOException{sync.sync(p);}
 private static String hash(InputStream in)throws IOException{try{MessageDigest d=MessageDigest.getInstance("SHA-256");byte[] b=new byte[65536];int n;while((n=in.read(b))!=-1)if(n>0)d.update(b,0,n);StringBuilder s=new StringBuilder();for(byte x:d.digest())s.append(String.format(Locale.ROOT,"%02x",x&255));return s.toString();}catch(NoSuchAlgorithmException e){throw new AssertionError(e);}}
 private DataManifest read(Path p)throws IOException{DataManifest m=DataManifest.read(p,limits);if(!ID.equals(m.canonicalId))throw new IOException("Unknown manifest identity");return m;}
 private Path root(DataManifest m)throws IOException{Path r=base.resolve(m.resourceDirectory).normalize();if(!base.equals(r.getParent())||Files.isSymbolicLink(r))throw new IOException("Unsafe data directory");return r;}
 private static Map<String,DataOverlay.Entry> map(DataManifest m){Map<String,DataOverlay.Entry> r=new TreeMap<>();if(m!=null)for(DataManifest.Entry e:m.files().values())r.put(e.path,new DataOverlay.Entry(e.length,e.sha256));return r;}
 private static String text(Path p)throws IOException{if(Files.isSymbolicLink(p)||!Files.isRegularFile(p,LinkOption.NOFOLLOW_LINKS)||Files.size(p)>256)throw new IOException("Invalid journal/marker");return new String(Files.readAllBytes(p),StandardCharsets.US_ASCII);}
 private static void atomicText(Path p,String s)throws IOException{Path t=Files.createTempFile(p.getParent(),".coordinator-",".tmp");try{try(FileOutputStream o=new FileOutputStream(t.toFile())){o.write(s.getBytes(StandardCharsets.US_ASCII));o.getFD().sync();}Files.move(t,p,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);}finally{Files.deleteIfExists(t);}}
 private static String fileHash(Path p)throws IOException{try(InputStream in=Files.newInputStream(p,LinkOption.NOFOLLOW_LINKS)){return hash(in);}}
 /** Best effort after readiness is durable. Never recurse or touch unbound paths. */
 private void cleanup(Path tx,String oldHash,String newHash,Fault fault){
  try{
   hit(fault,"cleanup-before-check");
   if(Files.isSymbolicLink(tx)||!Files.isDirectory(tx,LinkOption.NOFOLLOW_LINKS))return;
   try(DirectoryStream<Path> files=Files.newDirectoryStream(tx)){
    for(Path file:files){String name=file.getFileName().toString();String expected=name.equals("new.manifest")?newHash:name.equals("old.manifest")&&!oldHash.equals("-")?oldHash:null;
     if(expected==null||Files.isSymbolicLink(file)||!Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS)||Files.size(file)>limits.maxManifestBytes||!fileHash(file).equals(expected))return;
    }
   }
   for(String name:new String[]{"old.manifest","new.manifest"}){
    if(name.equals("old.manifest")&&oldHash.equals("-"))continue;
    Path file=tx.resolve(name);if(!exists(file))continue;
    hit(fault,"cleanup-before-delete");String expected=name.equals("old.manifest")?oldHash:newHash;
    if(Files.isSymbolicLink(file)||!Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS)||Files.size(file)>limits.maxManifestBytes||!fileHash(file).equals(expected))return;
    Files.delete(file);hit(fault,"cleanup-after-delete");
   }
   syncDir(tx);hit(fault,"cleanup-before-rmdir");Files.delete(tx);syncDir(state);hit(fault,"cleanup-after-rmdir");
  }catch(IOException|RuntimeException ignored){/* Durable installation stays ready; leave leftovers untouched. */}
 }
 private static boolean sameManifest(DataManifest a,DataManifest b){if(a==null||b==null||!a.zipSha256.equals(b.zipSha256)||!a.resourceDirectory.equals(b.resourceDirectory)||!a.canonicalId.equals(b.canonicalId)||!a.files().keySet().equals(b.files().keySet()))return false;for(String path:a.files().keySet()){DataManifest.Entry x=a.files().get(path),y=b.files().get(path);if(x.length!=y.length||!x.sha256.equals(y.sha256))return false;}return true;}
 private void pending(String mode,DataManifest old,DataManifest next)throws IOException{
  syncDir(base.getParent());syncDir(state.getParent());
  if(exists(p("pending")))throw new IOException("Pending transaction");
  if(exists(p("old.manifest"))||exists(p("new.manifest")))throw new IOException("Unowned legacy snapshot; preserved for manual review");
  String id=UUID.randomUUID().toString().replace("-","");Path tx=p("txn-"+id);Files.createDirectory(tx);syncDir(state);
  String oldHash="-";if(old!=null){old.writeAtomic(tx.resolve("old.manifest"),null,limits);oldHash=fileHash(tx.resolve("old.manifest"));}
  next.writeAtomic(tx.resolve("new.manifest"),null,limits);String newHash=fileHash(tx.resolve("new.manifest"));
  syncDir(tx);atomicText(p("pending"),mode+"\n"+id+"\n"+oldHash+"\n"+newHash);syncDir(state);
 }
 private static void verify(Path root,DataManifest m)throws IOException{if(Files.isSymbolicLink(root)||!Files.isDirectory(root,LinkOption.NOFOLLOW_LINKS))throw new IOException("Unsafe directory");for(DataManifest.Entry e:m.files().values()){Path q=root;for(String part:e.path.split("/")){q=q.resolve(part);if(Files.isSymbolicLink(q))throw new IOException("Unsafe path: "+e.path);}if(!Files.isRegularFile(q,LinkOption.NOFOLLOW_LINKS)||Files.size(q)!=e.length)throw new IOException("Missing or modified: "+e.path);try(InputStream in=Files.newInputStream(q,LinkOption.NOFOLLOW_LINKS)){if(!hash(in).equals(e.sha256))throw new IOException("Modified: "+e.path);}}}
 private Path resume(DataManifest.ZipSource src,Fault f)throws IOException{
  String[] journal=text(p("pending")).split("\n",-1);
  if(journal.length!=4||!journal[1].matches("[0-9a-f]{32}")||!journal[3].matches("[0-9a-f]{64}"))throw new IOException("Invalid or unsupported pending transaction; manual repair required");
  String mode=journal[0];if(!mode.equals("init")&&!mode.equals("update-marked")&&!mode.equals("update-unmarked"))throw new IOException("Invalid pending mode");
  boolean marked=mode.equals("update-marked");
  if(mode.equals("init")?!journal[2].equals("-"):!journal[2].matches("[0-9a-f]{64}"))throw new IOException("Invalid pending snapshot identity");
  Path tx=p("txn-"+journal[1]);if(Files.isSymbolicLink(tx)||!Files.isDirectory(tx,LinkOption.NOFOLLOW_LINKS))throw new IOException("Missing or unsafe transaction directory");
  Path np=tx.resolve("new.manifest"),op=tx.resolve("old.manifest");
  if(!fileHash(np).equals(journal[3])||(!mode.equals("init")&&!fileHash(op).equals(journal[2])))throw new IOException("Transaction snapshots changed");
  DataManifest next=read(np),old=mode.equals("init")?null:read(op);
  if(old!=null&&!old.resourceDirectory.equals(next.resourceDirectory))throw new IOException("Transaction directory mismatch");
  Path root=root(next);if(old==null&&!exists(root))Files.createDirectory(root);
  if(Files.isSymbolicLink(root)||!Files.isDirectory(root,LinkOption.NOFOLLOW_LINKS))throw new IOException("Unsafe transaction root");
  DataManifest active=exists(p("active.manifest"))?read(p("active.manifest")):null;
  boolean done=sameManifest(active,next);
  if(!done && (old==null?active!=null:!sameManifest(active,old)))throw new IOException("Active transaction mismatch");
  syncDir(base);syncDir(state);
  Path marker=root.resolve(MARKER);
  String previous=old==null?null:ID+":"+old.zipSha256;
  String progress=old==null?null:ID+":in-progress:"+old.zipSha256+":"+next.zipSha256;
  String published=ID+":"+next.zipSha256;
  if(marked){
   if(!exists(marker))throw new IOException("Registered marker missing; cannot safely update");
   String current=text(marker);
   if(!done){
    if(!current.equals(previous)&&!current.equals(progress))throw new IOException("Registered marker changed; cannot safely update");
    if(current.equals(previous)){hit(f,"before-marker-invalidate");atomicText(marker,progress);hit(f,"after-marker-invalidate");}
    // This durability barrier precedes every resource modification, including recovery.
    syncDir(root);hit(f,"after-marker-invalidate-sync");
   }else if(!current.equals(progress)&&!current.equals(published))throw new IOException("Committed transaction marker changed");
  }else if(old!=null&&exists(marker))throw new IOException("Unexpected marker appeared; cannot safely update");
  else if(old==null&&exists(marker)&&(!done||!text(marker).equals(published)))throw new IOException("Unexpected marker in new installation");
  if(!done){
   DataOverlay.Result applied=DataOverlay.apply(root,state,map(old),map(next),src::open,old==null?next.zipSha256:old.zipSha256,next.zipSha256,(stage,path)->hit(f,"overlay:"+stage));
   if(!applied.directoriesSynced)throw new IOException("Cannot sync data directories; retry repair");
   hit(f,"before-commit");next.writeAtomic(p("active.manifest"),active,limits);hit(f,"after-commit");
  }
  syncDir(state);hit(f,"before-confirm");
  DataOverlay.Result confirmed=DataOverlay.confirm(root,state,map(old),map(next),old==null?next.zipSha256:old.zipSha256,next.zipSha256);
  if(!confirmed.directoriesSynced)throw new IOException("Cannot sync confirmation; retry repair");
  syncDir(state);hit(f,"after-confirm");
  if(marked){
   String current=text(marker);
   if(!current.equals(progress)&&!current.equals(published))throw new IOException("Transaction marker changed before publication");
   if(current.equals(progress)){hit(f,"before-marker-publish");atomicText(marker,published);hit(f,"after-marker-publish");}
   syncDir(root);hit(f,"after-marker-publish-sync");
  }else if(old!=null&&exists(marker))throw new IOException("Unexpected marker appeared during update");
  else if(old==null){
   if(exists(marker)){if(!text(marker).equals(published))throw new IOException("Unexpected marker in new installation");}
   else {hit(f,"before-marker-publish");atomicText(marker,published);hit(f,"after-marker-publish");}
   syncDir(root);hit(f,"after-marker-publish-sync");
  }
  Files.delete(p("pending"));syncDir(state);
  try{hit(f,"after-pending-delete");cleanup(tx,journal[2],journal[3],f);}catch(IOException|RuntimeException ignored){/* Cleanup never revokes readiness. */}
  return root;
 }
 private Path prepareActive(DataManifest.ZipSource src,Fault f,String zip,DataManifest active)throws IOException{
  Path root=root(active);
  if(!Files.isDirectory(root,LinkOption.NOFOLLOW_LINKS))throw new IOException("Registered data missing");
  if(active.zipSha256.equals(zip))return root;
  DataManifest next=DataManifest.fromZip(src,limits,active.resourceDirectory,ID);
  if(next.files().isEmpty()||!next.zipSha256.equals(zip))throw new IOException("Empty or changed ZIP");
  Path marker=root.resolve(MARKER);boolean marked=exists(marker);
  if(marked&&!text(marker).equals(ID+":"+active.zipSha256))throw new IOException("Registered marker changed; cannot safely update");
  pending(marked?"update-marked":"update-unmarked",active,next);hit(f,"after-pending");return resume(src,f);
 }
 private void requireCleanBootstrap()throws IOException{
  for(String name:new String[]{"overlay.journal","old.manifest","new.manifest"})
   if(exists(p(name)))throw new IOException("Unbound update state; existing files preserved for review");
  try(DirectoryStream<Path> dirs=Files.newDirectoryStream(state,"txn-*")){
   if(dirs.iterator().hasNext())throw new IOException("Unbound update transaction; existing files preserved for review");
  }
 }
 private static final class Candidate{
  final Path path;final String marker;final DataManifest baseline;
  Candidate(Path p,String m,DataManifest b){path=p;marker=m;baseline=b;}
 }
 public Path prepare(DataManifest.ZipSource src,Fault f)throws IOException{
  Files.createDirectories(base);Files.createDirectories(state);
  if(Files.isSymbolicLink(base)||Files.isSymbolicLink(state))throw new IOException("Unsafe storage");
  // A registered or interrupted update is never replaced by legacy discovery.
  if(exists(p("pending")))resume(src,f);
  String zip;try(InputStream in=src.open()){zip=hash(in);}
  DataManifest active=exists(p("active.manifest"))?read(p("active.manifest")):null;
  if(active!=null)return prepareActive(src,f,zip,active);
  requireCleanBootstrap();
  List<Candidate> matches=new ArrayList<>();boolean unknown=false,sawInterrupted=false;
  try(DirectoryStream<Path> ds=Files.newDirectoryStream(base)){
   for(Path d:ds){
    unknown=true;String name=d.getFileName().toString();
    if(!name.matches("[0-9a-f]{64}-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")||Files.isSymbolicLink(d)||!Files.isDirectory(d,LinkOption.NOFOLLOW_LINKS)||!exists(d.resolve(MARKER)))continue;
    String marked=text(d.resolve(MARKER));
    if(marked.startsWith(ID+":in-progress:")){sawInterrupted=true;continue;} // Never adopt a partial root.
    if(!marked.startsWith(ID+":"))continue;
    String prior=marked.substring(ID.length()+1);
    if(!prior.matches("[0-9a-f]{64}"))continue;
    if(prior.equals(zip)){matches.add(new Candidate(d,marked,null));continue;}
    DataManifest baseline=baselines==null?null:baselines.find(prior);
    if(baseline==null)continue; // Unknown siblings remain unowned and untouched.
    if(!prior.equals(baseline.zipSha256)||!ID.equals(baseline.canonicalId)||baseline.files().isEmpty())throw new IOException("Invalid packaged historical baseline");
    matches.add(new Candidate(d,marked,baseline.rebindDirectory(name)));
   }
  }
  // Count before verifying: a damaged recognized root cannot make another root
  // appear uniquely authoritative. No timestamps or directory order select it.
  if(matches.size()>1)throw new IOException("Multiple recognized installations; existing data preserved");
  if(matches.size()==1){
   Candidate selected=matches.get(0);Path r=selected.path;
   DataManifest m=selected.baseline==null?DataManifest.fromZip(src,limits,r.getFileName().toString(),ID):selected.baseline;
   if(m.files().isEmpty()||(selected.baseline==null&&!m.zipSha256.equals(zip)))throw new IOException("Empty or changed ZIP");
   hit(f,"before-legacy-verify");verify(r,m);hit(f,"after-legacy-verify");
   if(!root(m).equals(r)||!text(r.resolve(MARKER)).equals(selected.marker))throw new IOException("Installation changed during baseline verification");
   syncDir(base);syncDir(state.getParent());hit(f,"before-legacy-publish");
   if(!text(r.resolve(MARKER)).equals(selected.marker))throw new IOException("Installation marker changed before registration");
   m.writeAtomic(p("active.manifest"),null,limits);syncDir(state);hit(f,"after-legacy-publish");
   // Publish the durable old inventory first, then reuse the existing updater.
   return prepareActive(src,f,zip,m);
  }
  if(sawInterrupted)throw new IOException("Interrupted installation has no registered transaction; preserve data for review");
  if(unknown)throw new IOException("Existing data lacks a supported verified baseline; existing files preserved");
  String name=zip+"-"+UUID.randomUUID();DataManifest next=DataManifest.fromZip(src,limits,name,ID);
  if(next.files().isEmpty()||!next.zipSha256.equals(zip))throw new IOException("Empty or changed ZIP");
  pending("init",null,next);hit(f,"after-pending");return resume(src,f);
 }
}
