#!/usr/bin/env python3
"""Host lifecycle harness extracted from actual MainActivity resource UI methods.

No Android device, APK, original ELF, native game or ResourceStore parser runs.
Real onActivityResult/startQueuedImport/onSaveInstanceState/resourceControls and
both worker UI completion bodies are compiled into Java view/provider stubs.
Only the worker-I/O launch is replaced with an operation recorder; its actual
production guard/state-reset prefix is retained. Actual startGame/resourcePath
run against a boolean JNI recorder, including failure/retry/reattach cache tests.
Actual closeResourceInput runs against memory-only InputStream close fault stubs.
Current onCreate/OriginalHost/ResolvedResources and Controller interfaces are extracted.
Controller scheduling/UI/provider/JNI are minimal host fakes; actual OriginalHost.completed
performs startup dispatch. No Binder/FGS/Android execution is claimed.
Every generated source/class/log stays in a new APFS directory.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ACTIVITY = Path(os.environ.get('RESOURCE_IMPORT_ACTIVITY_SOURCE', ROOT / 'android/java/com/wmmt/port/MainActivity.java'))
CONTROLLER = Path(os.environ.get('RESOURCE_IMPORT_CONTROLLER_SOURCE', ACTIVITY.with_name('OriginalConversionController.java')))


def closing_brace(source, opening):
    depth, state, at = 0, 'code', opening
    while at < len(source):
        ch, nxt = source[at], source[at+1:at+2]
        if state == 'code':
            if ch == '/' and nxt == '*':
                state = 'block'; at += 1
            elif ch == '/' and nxt == '/':
                state = 'line'; at += 1
            elif ch in ('"', "'"):
                state = ch
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return at
        elif state == 'block' and ch == '*' and nxt == '/':
            state = 'code'; at += 1
        elif state == 'line' and ch == '\n':
            state = 'code'
        elif state in ('"', "'"):
            if ch == '\\':
                at += 1
            elif ch == state:
                state = 'code'
        at += 1
    raise AssertionError('unclosed actual Java block')


def method(source, name):
    match = re.search(r'(?:@Override\s+)?(?:private|protected|public)\s+(?:static\s+)?[\w.<>\[\]]+\s+' +
                      re.escape(name) + r'\([^;{}]*\)(?:\s+throws\s+[\w., ]+)?\s*\{', source)
    if match is None:
        raise AssertionError('missing production Activity method: ' + name)
    opening = source.index('{', match.start())
    return source[match.start():closing_brace(source, opening)+1]


def marked_block(source, marker):
    start = source.index(marker)
    opening = source.index('{', start)
    return source[start:closing_brace(source, opening)+1]


def if_else_block(source, marker):
    start = source.index(marker)
    opening = source.index('{', start)
    end = closing_brace(source, opening)
    following = end + 1
    while source[following].isspace():
        following += 1
    if not source.startswith('else', following):
        raise AssertionError('expected actual onCreate native/Controller else branch')
    other_open = source.index('{', following)
    return source[start:closing_brace(source, other_open)+1]


JAVA = r'''
import java.util.*;
import java.io.*;
import java.nio.file.*;
public final class ResourceImportActivityHostTest {
  static int assertions;
  static void ok(boolean value,String what) { assertions++;if(!value)throw new AssertionError(what); }
  static final class Uri {
    final String value; Uri(String v){value=v;}
    public String toString(){return value;}
  }
  static final class Intent { final Uri value;Intent(Uri u){value=u;}Uri getData(){return value;} }
  static final class Bundle {
    final Map<String,Object> values=new HashMap<>();
    void putBoolean(String k,boolean v){values.put(k,v);}
    boolean getBoolean(String k,boolean fallback){return values.containsKey(k)?(Boolean)values.get(k):fallback;}
    void putParcelable(String k,Uri v){values.put(k,v);}
    Uri getParcelable(String k){return (Uri)values.get(k);}
  }
  // Namespace-shaped log stub keeps the actual helper body unmodified.
  static final class android {
    static final class util {
      static final class Log {
        static int warnings;static String lastTag,lastMessage;
        static int w(String tag,String message){warnings++;lastTag=tag;lastMessage=message;return 0;}
        static int w(String tag,String message,Throwable error){return w(tag,message);}
      }
    }
    static final class os {
      static final class Process { static int myUid(){return 1234;} }
    }
    static final class system {
      static final class ErrnoException extends Exception { }
      static final class OsConstants {
        static final int O_RDONLY=0,O_NONBLOCK=1,O_NOFOLLOW=2,O_CLOEXEC=4;
        static boolean S_ISDIR(int mode){return (mode&0170000)==0040000;}
      }
      static final class StructStat {
        final int st_mode,st_uid;
        StructStat(int mode,int uid){st_mode=mode;st_uid=uid;}
      }
      static final class Os {
        static final Map<FileDescriptor,String> openDirs=new HashMap<>();
        static final Map<String,Integer> permissions=new HashMap<>();
        static int uid=os.Process.myUid(),chmodCalls;
        static FileDescriptor open(String path,int flags,int mode) throws ErrnoException {
          if(flags!=(OsConstants.O_NONBLOCK|OsConstants.O_NOFOLLOW|OsConstants.O_CLOEXEC)||
              !Files.isDirectory(Paths.get(path),LinkOption.NOFOLLOW_LINKS))throw new ErrnoException();
          FileDescriptor fd=new FileDescriptor();openDirs.put(fd,path);return fd;
        }
        static StructStat lstat(String path) throws ErrnoException {
          if(!Files.isDirectory(Paths.get(path),LinkOption.NOFOLLOW_LINKS))throw new ErrnoException();
          return new StructStat(0040000|permissions.getOrDefault(path,0771),uid);
        }
        static StructStat fstat(FileDescriptor fd) throws ErrnoException {
          String path=openDirs.get(fd);if(path==null)throw new ErrnoException();
          return new StructStat(0040000|permissions.getOrDefault(path,0771),uid);
        }
        static void fchmod(FileDescriptor fd,int mode) throws ErrnoException {
          String path=openDirs.get(fd);if(path==null)throw new ErrnoException();
          permissions.put(path,mode);chmodCalls++;
        }
        static void close(FileDescriptor fd) throws ErrnoException {
          if(openDirs.remove(fd)==null)throw new ErrnoException();
        }
      }
    }
  }
  static final class TextView { String text="";void setText(CharSequence t){text=t.toString();} }
  static final class Button { boolean enabled;void setEnabled(boolean e){enabled=e;} }
  static final class Surface { boolean valid=true;boolean isValid(){return valid;} }
  static final class Holder { Surface surface=new Surface();Surface getSurface(){return surface;} }
  static final class SurfaceView { final Holder holder=new Holder();Holder getHolder(){return holder;} }
  static class FrameLayout { int removals;void removeView(Object panel){removals++;} }
  // Cinder presentation is a host-only record: no Android View/bitmap code runs.
  static final class LauncherWallpaperView extends FrameLayout {
    boolean busy;
    final Button selectButton=new Button(),launchButton=new Button(),cancelButton=new Button();
    final Button originalActionButton=new Button(),recheckActionButton=new Button();
    final TextView statusText=new TextView();
    void updateBusyPresentation(boolean value){busy=value;}
    void release(){}
  }
  static class Context {
    static final int MODE_PRIVATE=0;
    File getDir(String store,int mode){
      Path root=Paths.get(System.getProperty("java.io.tmpdir"),"private-records");
      try { Files.createDirectories(root); }
      catch(IOException error){throw new UncheckedIOException(error);}
      File leaf=root.resolve("app_"+store).toFile();
      if(!Files.exists(leaf.toPath(),LinkOption.NOFOLLOW_LINKS)&&!leaf.mkdir())
        throw new IllegalStateException("Unable to create host record directory");
      return leaf;
    }
  }
  static final Context APP_CONTEXT=new Context();
  static class Activity extends Context {
    boolean isFinishing(){return false;}
    boolean isDestroyed(){return false;}
  }
  static final class OriginalProfile { }
  static final class OriginalJobStore {
    static final class Ready {
      final Path dataDirectory;final List<String> warnings;
      private Ready(Path path,List<String> notes){dataDirectory=path;warnings=Collections.unmodifiableList(new ArrayList<String>(notes));}
    }
    static Ready verifiedFixture(){return new Ready(Paths.get("/SYNTHETIC-NOT-OPENED/verified-original"),Arrays.asList("fixture capability warning"));}
  }
  // Fixture only: no Controller, Binder or Android implementation is executed.
  // Obtain reserves busy and queues recovery; drain models a later UI-loop callback.
  static final class OriginalConversionController {
    __ACTUAL_CONTROLLER_INTERFACES__
    final Host host;boolean busy=true,recoveryPending=true;int saveCalls,cancelCalls;
    final List<Integer> delegated=new ArrayList<Integer>();int consumedResults;
    static int obtains;static boolean failObtain;
    OriginalConversionController(Host h){host=h;}
    static OriginalConversionController obtain(Host h,Bundle b)throws IOException{
      obtains++;if(failObtain)throw new IOException("synthetic controller admission failure");
      OriginalConversionController c=new OriginalConversionController(h);h.setBusy(true);h.status("fixture: awaiting controller recovery callback");return c;
    }
    boolean isBusy(){return busy;}
    void drainRecovery(){deliverRecovery(false,"");}
    void deliverRecovery(boolean committed,String message){
      if(!recoveryPending)return;recoveryPending=false;busy=false;host.setBusy(false);host.completed(committed,message);
    }
    boolean onActivityResult(int request,int result,Intent data){
      delegated.add(request);if(request!=1351&&request!=1352)return false;consumedResults++;return true;
    }
    void saveState(Bundle out){saveCalls++;out.putBoolean("controller-fixture-busy",busy);}
    void cancel(){cancelCalls++;}
  }
  // Boundary declarations only: null capabilities never manufacture verification.
  static final class ResourceMetadata {
    static final String GHOST_UI_PATH="ghost-ui.bin", BUILTIN_GHOSTS_PATH="builtin-ghosts.bin";
  }
  static final class ResourceStore {
    static final class VerifiedOptional { Path verifiedPath(String name){return null;} }
    static final class Ready {
      final Path dataDirectory;
      final Path cardDirectory;
      final Map<String,Path> optionalFiles;
      final List<String> warnings=Collections.emptyList();
      Ready(){this("/SYNTHETIC-NOT-OPENED/verified-main",null,Collections.emptyMap());}
      Ready(String data,String card,Map<String,Path> files){dataDirectory=Paths.get(data);cardDirectory=card==null?null:Paths.get(card);optionalFiles=files;}
    }
  }
  static class BaseActivity extends Activity {
    static final int RESULT_OK=-1,RESULT_CANCELED=0;
    boolean finishing;int baseSaveCalls,baseResultCalls;
    boolean isFinishing(){return finishing;}
    boolean isDestroyed(){return this instanceof MainActivity&&((MainActivity)this).destroyed;}
    Context getApplicationContext(){return APP_CONTEXT;}
    File getExternalFilesDir(String ignored){return new File("/SYNTHETIC-NOT-OPENED/app-external");}
    protected void onActivityResult(int request,int result,Intent data){baseResultCalls++;}
    protected void onSaveInstanceState(Bundle state){baseSaveCalls++;}
  }
  static final class MainActivity extends BaseActivity {
    static MainActivity currentActivity;
    static String nativeDataDir;
    static File nativeCardResources;
    static String[] nativeOptionalFiles;
    static boolean resourceClearing;
    static final Object INSTALL_LOCK=new Object();
    static final int REQUEST_RESOURCE_IMPORT=134;
    volatile boolean resourceBusy,resourceCancelled,started,destroyed;
    boolean installReady,awaitingResourcePicker;
    Uri pendingResourceImport;
    ResolvedResources preparedResources;
    OriginalConversionController originalController;OriginalHost originalHost;
    Button originalButton=new Button();String pendingOriginalNotice;
    static Context lastLockContext;static int lockCalls,profileCalls;
    private static void lockInstallProcess(Context app)throws IOException{lastLockContext=app;lockCalls++;}
    private static OriginalProfile originalProfile(Context app)throws IOException{profileCalls++;return new OriginalProfile();}
    __ACTUAL_ORIGINAL_HOST__
    __ACTUAL_RESOLVED_RESOURCES__
    long lastResourceProgress;
    String dataDir,saveDir;
    volatile String resourceNotice;
    File cardResources;
    final Button beginButton=new Button(),importButton=new Button(),checkButton=new Button(),cancelButton=new Button(),clearButton=new Button();
    final TextView progress=new TextView();
    final List<Uri> operations=new ArrayList<>();
    final FrameLayout root=new FrameLayout();
    final SurfaceView game=new SurfaceView();
    final FrameLayout dataPanel=new FrameLayout();
    final LauncherWallpaperView launcherWallpaper=new LauncherWallpaperView();
    int surfaceWidth,surfaceHeight,nativeCalls,surfaceCalls,pauseCalls,cancelCalls;
    boolean resumed,nextNativeResult=true,lastPause;
    String passedData,passedSave,passedCard,cacheAtNativeCall,passedTaStore,passedCrownStore;
    String[] passedOptional;
    MainActivity(){currentActivity=this;}
    int refreshCalls; void refreshSurfaceRate(){refreshCalls++;} // Display-rate boundary, not refresh-policy proof.
    static boolean nativeStart(MainActivity owner,String data,String save,String card,String cutin,String pages,String wpk,String bfx,String ghost,String builtin,String haloWpk,String haloAnchors,String taStore,String crownStore){
      owner.passedTaStore=taStore;owner.passedCrownStore=crownStore;
      owner.nativeCalls++;owner.passedData=data;owner.passedSave=save;owner.passedCard=card;
      owner.passedOptional=new String[]{cutin,pages,wpk,bfx,ghost,builtin,haloWpk,haloAnchors};owner.cacheAtNativeCall=nativeDataDir;
      return owner.nextNativeResult;
    }
    static void nativeSurface(Surface surface,int width,int height){currentActivity.surfaceCalls++;}
    static void nativePause(boolean paused){currentActivity.pauseCalls++;currentActivity.lastPause=paused;}
    // Provider operations are not executed here; queue behavior records cancellation.
    private void cancelResourceOperation(){cancelCalls++;resourceCancelled=true;}
    __METHODS__
    // Exact production guard and state reset, replacing only actual Thread/I/O.
    __PREPARE_PREFIX__
      operations.add(source);
    }
    void recreateResourceUi(Bundle b){recreateResourceUiWithLoop(b,true);}
    void recreateResourceUiDeferred(Bundle b){recreateResourceUiWithLoop(b,false);}
    void recreateResourceUiWithLoop(Bundle b,boolean drainUiLoop){
      currentActivity=this;
      __RESTORE_BUNDLE__
      // Actual current onCreate native/else branch. Startup legacy dispatch is ONLY actual OriginalHost.completed.
      __CREATE_RESOURCE_BRANCH__
      // Explicit fixture event-loop drain, not an old-onCreate substitute.
      if(drainUiLoop&&originalController!=null)originalController.drainRecovery();
    }
    void completeSuccess(ResourceStore.Ready rawReady,String savePath){
      ResolvedResources ready=new ResolvedResources(rawReady);
      __SUCCESS_CALLBACK__
    }
    void completeFailure(Exception ex){
      __FAILURE_CALLBACK__
    }
  }
  static MainActivity fresh(){MainActivity.nativeDataDir=null;MainActivity.nativeCardResources=null;MainActivity.nativeOptionalFiles=null;return new MainActivity();}
  static Uri uri(String id){return new Uri("content://synthetic-provider/"+id);}
  static ResourceStore.Ready ready(){return new ResourceStore.Ready();}
  static Bundle pickerState(){Bundle b=new Bundle();b.putBoolean("resource-picker-pending",true);return b;}
  static MainActivity eligible(){
    MainActivity a=fresh();a.installReady=true;a.dataDir="/SYNTHETIC-NOT-OPENED/main-first";
    a.saveDir="/SYNTHETIC-NOT-OPENED/save-only";a.cardResources=new File("/SYNTHETIC-NOT-OPENED/card-first");
    Map<String,Path> extras=new TreeMap<>();
    for(String name:new String[]{"story-cutin.bin","card-pages.bin","backfire.wpk","backfire.bfx","front_halo.wpk","front_halo.bin"})
      extras.put(name,Paths.get("/SYNTHETIC-NOT-OPENED/approved-optional",name));
    a.preparedResources=new MainActivity.ResolvedResources(new ResourceStore.Ready(a.dataDir,a.cardResources.getAbsolutePath(),extras));
    a.surfaceWidth=1280;a.surfaceHeight=720;a.resourceControls();return a;
  }
  static void startupChecks() throws IOException {
    for(String condition:new String[]{"unready","busy","awaiting","started","destroyed","not-current","finishing"}){
      MainActivity blocked=eligible();
      if(condition.equals("unready"))blocked.installReady=false;
      if(condition.equals("busy"))blocked.resourceBusy=true;
      if(condition.equals("awaiting"))blocked.awaitingResourcePicker=true;
      if(condition.equals("started"))blocked.started=true;
      if(condition.equals("destroyed"))blocked.destroyed=true;
      if(condition.equals("not-current"))new MainActivity();
      if(condition.equals("finishing"))blocked.finishing=true;
      blocked.startGame();
      ok(blocked.nativeCalls==0&&blocked.root.removals==0&&MainActivity.nativeDataDir==null,"actual Begin fail-closed guard: "+condition);
    }
    MainActivity a=eligible();MainActivity.ResolvedResources verified=a.preparedResources;String selected=a.dataDir;
    a.nextNativeResult=false;a.startGame();
    ok(a.nativeCalls==1&&!a.started&&a.installReady&&a.beginButton.enabled,"boolean false leaves verified Begin retryable");
    ok(MainActivity.nativeDataDir==null&&MainActivity.nativeCardResources==null&&MainActivity.nativeOptionalFiles==null,"failed JNI start must not freeze any native resource cache");
    ok(a.root.removals==0&&a.surfaceCalls==0&&a.pauseCalls==0,"failed JNI start keeps panel and sends no surface/pause");
    ok(a.preparedResources==verified&&a.dataDir.equals(selected)&&a.operations.isEmpty(),"failed JNI start retains prepared paths without importing");
    a.nextNativeResult=true;a.startGame();
    ok(a.nativeCalls==2&&a.started&&a.root.removals==1,"retry accepts true and hides panel once");
    ok(a.cacheAtNativeCall==null&&MainActivity.nativeDataDir.equals(selected),"first cache published only AFTER successful boolean call");
    ok(MainActivity.nativeCardResources==a.cardResources&&MainActivity.nativeOptionalFiles.length==8,"all first verified resource paths frozen together");
    ok(Arrays.equals(a.passedOptional,MainActivity.nativeOptionalFiles),"first JNI call consumes exact Ready optionalFiles map");
    ok(a.passedOptional[6].endsWith("/front_halo.wpk")&&a.passedOptional[7].endsWith("/front_halo.bin"),"front halo pair reaches JNI in order");
    ok(a.surfaceCalls==1&&a.pauseCalls==1&&a.lastPause,"valid surface and paused lifecycle forwarded after success");
    ok(a.passedSave.equals("/SYNTHETIC-NOT-OPENED/save-only")&&!a.passedSave.equals(a.passedData),"native receives distinct save path");
    ok(a.getDir("ta-ranking-v1",Context.MODE_PRIVATE).getCanonicalPath().equals(a.passedTaStore)&&
       a.getDir("ghost-crown-v1",Context.MODE_PRIVATE).getCanonicalPath().equals(a.passedCrownStore),
       "TA and Ghost crown use separate private paths");
    ok(android.system.Os.permissions.get(a.passedTaStore)==0700&&
       android.system.Os.permissions.get(a.passedCrownStore)==0700&&android.system.Os.chmodCalls==2,
       "Android 0771 directories are narrowed once and admitted on both startups");
    ok(android.system.Os.openDirs.isEmpty(),"record directory descriptors close after startup");
    android.system.Os.uid++;
    ok(a.privateRecordDirectory("foreign")==null&&android.system.Os.chmodCalls==2&&
       android.system.Os.openDirs.isEmpty(),"foreign directory rejected without changing it");
    android.system.Os.uid--;
    File link=a.getDir("link",Context.MODE_PRIVATE);
    Files.delete(link.toPath());
    Files.createSymbolicLink(link.toPath(),Paths.get(a.passedCrownStore));
    ok(a.privateRecordDirectory("link")==null&&android.system.Os.chmodCalls==2,"symlink rejected");
    a.startGame();ok(a.nativeCalls==2&&a.root.removals==1,"second Begin click does not create another native game");
    String frozen=MainActivity.nativeDataDir;File frozenCard=MainActivity.nativeCardResources;String[] frozenOptional=MainActivity.nativeOptionalFiles;
    MainActivity replacement=new MainActivity();replacement.installReady=true;replacement.dataDir="/UNVERIFIED-BAIT/main";
    replacement.cardResources=new File("/UNVERIFIED-BAIT/card");replacement.preparedResources=new MainActivity.ResolvedResources(ready());replacement.saveDir=a.saveDir;
    replacement.nextNativeResult=false;replacement.startGame();
    ok(!replacement.started&&replacement.root.removals==0&&MainActivity.nativeDataDir.equals(frozen),"failed reattach keeps existing cache and visible panel");
    ok(replacement.passedData.equals(frozen)&&replacement.passedCard.equals(frozenCard.getAbsolutePath())&&Arrays.equals(replacement.passedOptional,frozenOptional),"reattach never switches to new Activity bait paths");
    replacement.nextNativeResult=true;replacement.startGame();
    ok(replacement.started&&replacement.dataDir.equals(frozen)&&replacement.cardResources==frozenCard,"reattach success selects first process paths");
    ok(MainActivity.nativeOptionalFiles==frozenOptional&&MainActivity.nativeCardResources==frozenCard&&replacement.root.removals==1,"reattach does not replace frozen path objects");
    MainActivity absent=eligible();absent.cardResources=null;absent.preparedResources=new MainActivity.ResolvedResources(ready());absent.startGame();
    ok(absent.passedCard==null&&Arrays.equals(absent.passedOptional,new String[8]),"unavailable optional files stay null without filesystem guessing");
    System.out.println("Actual extracted boolean startGame failure/retry/reattach checks PASS");
  }
  static final class CloseSource extends InputStream {
    final int fault;int closes;CloseSource(int f){fault=f;}
    public int read(){return -1;}
    public void close() throws IOException {
      closes++;
      if(fault==1)throw new IOException("synthetic provider close IOException");
      if(fault==2)throw new IllegalStateException("synthetic provider close RuntimeException");
    }
  }
  static void closeInputChecks(){
    int before=assertions;
    for(boolean committed:new boolean[]{false,true}){
      MainActivity a=fresh();String prior="prior notice";a.resourceNotice=prior;
      android.util.Log.warnings=0;
      a.closeResourceInput(null,committed);
      ok(a.resourceNotice==prior&&android.util.Log.warnings==0,"null input is harmless for committed="+committed);
      InputStream noop=new InputStream(){public int read(){return -1;}};
      a.closeResourceInput(noop,committed);
      ok(a.resourceNotice==prior&&android.util.Log.warnings==0,"default no-op close preserves notice for committed="+committed);
      CloseSource success=new CloseSource(0);a.closeResourceInput(success,committed);
      ok(success.closes==1&&a.resourceNotice==prior&&android.util.Log.warnings==0,"successful close runs once without warning for committed="+committed);
      ok(a.operations.isEmpty()&&a.nativeCalls==0,"closing never retries imports or starts native");
    }
    for(int fault:new int[]{1,2}){
      MainActivity committed=fresh();committed.resourceBusy=true;
      CloseSource afterCommit=new CloseSource(fault);android.util.Log.warnings=0;
      committed.closeResourceInput(afterCommit,true);
      ok(afterCommit.closes==1,"postcommit close attempted once fault="+fault);
      ok(committed.resourceNotice!=null&&committed.resourceNotice.contains("已登记")&&committed.resourceNotice.contains("不要因此重复导入"),"postcommit close becomes registration warning fault="+fault);
      ok(android.util.Log.warnings==0&&!committed.resourceCancelled,"postcommit warning does not masquerade as cancellation/failure");
      String notice=committed.resourceNotice;committed.completeSuccess(ready(),"/SYNTHETIC-NOT-OPENED/save-only");
      ok(committed.installReady&&committed.beginButton.enabled&&committed.progress.text.contains(notice),"actual success callback keeps Ready and appends close warning fault="+fault);
      ok(committed.operations.isEmpty()&&committed.nativeCalls==0,"postcommit close never causes duplicate import or automatic native start");
      MainActivity failed=fresh();CloseSource beforeCommit=new CloseSource(fault);android.util.Log.warnings=0;
      IOException original=new IOException("original unsuccessful import");Throwable observed=null;
      try {try {throw original;} finally {failed.closeResourceInput(beforeCommit,false);}}
      catch(Throwable ex){observed=ex;}
      ok(observed==original&&beforeCommit.closes==1,"failed-import close must not mask original exception identity fault="+fault);
      ok(failed.resourceNotice==null&&android.util.Log.warnings==1&&"WMMT".equals(android.util.Log.lastTag),"precommit close logs only, never claims registration fault="+fault);
      ok(failed.operations.isEmpty()&&failed.nativeCalls==0,"precommit close does not import/start");
    }
    System.out.println("Actual extracted closeResourceInput PASS: "+(assertions-before)+" assertions");
  }

  static void originalIntegrationChecks()throws Exception{
    int before=assertions;
    MainActivity deferred=fresh();deferred.recreateResourceUiDeferred(null);
    ok(deferred.originalController!=null&&deferred.originalController.isBusy()&&deferred.resourceBusy,"actual obtain reserves asynchronous startup before legacy scan");
    ok(deferred.operations.isEmpty()&&!deferred.installReady&&deferred.preparedResources==null,"no legacy resolve or Ready before controller completion");
    deferred.installReady=true;deferred.resourceControls();
    ok(!deferred.beginButton.enabled&&!deferred.importButton.enabled&&!deferred.checkButton.enabled,"controller resourceBusy disables prepared controls");
    deferred.resourceBusy=false;deferred.startGame();
    ok(deferred.nativeCalls==0&&MainActivity.nativeDataDir==null,"actual startGame independently checks originalController.isBusy");
    deferred.resourceBusy=true;deferred.installReady=false;
    deferred.originalController.deliverRecovery(false,"");
    ok(deferred.operations.size()==1&&deferred.operations.get(0)==null&&deferred.resourceBusy,"actual completed(false,empty) starts one legacy resolve");
    deferred.originalController.drainRecovery();
    ok(deferred.operations.size()==1,"draining the consumed recovery event cannot cause a duplicate initial scan");
    ok(!deferred.installReady&&deferred.preparedResources==null&&deferred.nativeCalls==0,"false/empty recovery callback never manufactures signed readiness");
    for(boolean committed:new boolean[]{false,true}){
      MainActivity flags=fresh();flags.recreateResourceUiDeferred(null);flags.originalController.deliverRecovery(committed,"notification-only");
      ok(flags.operations.size()==1&&flags.operations.get(0)==null&&!flags.installReady&&flags.preparedResources==null,"committed boolean only requests real verification, not Ready: "+committed);
      ok("notification-only".equals(flags.resourceNotice)&&flags.pendingOriginalNotice==null&&flags.nativeCalls==0,"actual prepare prefix carries original notice and never autostarts: "+committed);
    }
    MainActivity queued=fresh();Uri pending=uri("original-completed-queue");Bundle saved=new Bundle();saved.putParcelable("resource-import-uri",pending);
    queued.recreateResourceUiDeferred(saved);queued.originalController.deliverRecovery(false,"");
    ok(queued.operations.size()==1&&queued.operations.get(0)==pending&&queued.pendingResourceImport==null,"actual completed(false,empty) prefers one saved queued import over resolve");
    queued.originalController.drainRecovery();ok(queued.operations.size()==1,"saved queued source is not dispatched twice");
    MainActivity picker=fresh();picker.recreateResourceUiDeferred(pickerState());OriginalConversionController controller=picker.originalController;
    picker.onActivityResult(1351,-1,new Intent(uri("original-zip")));picker.onActivityResult(1352,-1,new Intent(uri("original-tree")));
    ok(controller.consumedResults==2&&controller.delegated.equals(Arrays.asList(1351,1352)),"actual result method delegates original request1351/1352");
    ok(picker.awaitingResourcePicker&&picker.pendingResourceImport==null&&picker.operations.isEmpty()&&picker.cancelCalls==0,"original picker results cannot enter legacy request134 or cancel its source");
    controller.deliverRecovery(false,"");
    ok(picker.operations.isEmpty()&&picker.awaitingResourcePicker&&!picker.beginButton.enabled,"actual Host.completed preserves pending prepared picker instead of scanning");
    Uri legacy=uri("legacy-after-original");picker.onActivityResult(134,-1,new Intent(legacy));
    ok(controller.consumedResults==2&&controller.delegated.get(2)==134,"legacy result is consulted but not consumed by original controller fixture");
    ok(picker.operations.size()==1&&picker.operations.get(0)==legacy&&!picker.awaitingResourcePicker,"legacy134 still imports exactly once after original delegation");
    MainActivity saving=fresh();saving.recreateResourceUiDeferred(pickerState());Uri queuedSave=uri("dual-save");saving.pendingResourceImport=queuedSave;
    Bundle both=new Bundle();saving.onSaveInstanceState(both);
    ok(saving.originalController.saveCalls==1&&both.getBoolean("controller-fixture-busy",false),"actual onSaveInstanceState delegates original state");
    ok(both.getBoolean("resource-picker-pending",false)&&both.getParcelable("resource-import-uri")==queuedSave&&saving.baseSaveCalls==1,"original save delegation preserves both legacy picker fields and super");
    MainActivity adapter=fresh();adapter.preparedResources=new MainActivity.ResolvedResources(OriginalJobStore.verifiedFixture());
    ok(adapter.preparedResources.cardDirectory==null&&adapter.preparedResources.optionalFiles.isEmpty(),"actual Original Ready adapter never guesses card/optional fallback paths");
    ok(adapter.preparedResources.warnings.size()==2&&adapter.preparedResources.warnings.get(0).equals("fixture capability warning"),"actual Original Ready adapter preserves verified warnings and adds no-fallback notice");
    ok(adapter.resourcePath("story-cutin.bin")==null&&adapter.resourcePath("backfire.wpk")==null,"Original capability absent optional paths remain null");
    try{adapter.preparedResources.optionalFiles.put("bait",Paths.get("/SYNTHETIC-NOT-OPENED/bait"));throw new AssertionError("mutable original optional map");}catch(UnsupportedOperationException expected){ok(true,"actual Original optional map is immutable");}
    try{adapter.preparedResources.warnings.add("bait");throw new AssertionError("mutable original warnings");}catch(UnsupportedOperationException expected){ok(true,"actual Original warnings are immutable");}
    MainActivity weak=fresh();weak.recreateResourceUiDeferred(null);final int[] ran={0};weak.originalHost.withInstallLock(()->ran[0]++);
    ok(ran[0]==1&&MainActivity.lastLockContext==APP_CONTEXT&&!(MainActivity.lastLockContext instanceof Activity),"actual weak Host gate passes application context, not Activity");
    ok(weak.originalHost.activity()==weak,"actual weak Host activity reference remains available while owned");
    for(java.lang.reflect.Field f:MainActivity.OriginalHost.class.getDeclaredFields())ok(f.getType()!=MainActivity.class,"actual Host has no strong MainActivity field: "+f.getName());
    MainActivity stale=weak;int count=stale.operations.size();new MainActivity();stale.originalHost.completed(true,"stale");
    ok(stale.operations.size()==count&&stale.resourceBusy&&!stale.installReady,"actual weak Host.live rejects non-current completion without fabricating Ready");
    MainActivity blocked=fresh();blocked.recreateResourceUiDeferred(null);blocked.started=true;blocked.originalHost.completed(false,"");
    ok(blocked.operations.isEmpty(),"actual Host.completed refuses resolve while native has started");
    System.out.println("Actual extracted OriginalHost/ResolvedResources integration PASS: "+(assertions-before)+" assertions");
  }
  public static void main(String[] ignored)throws Exception{
    if(ignored.length==1&&ignored[0].equals("close-only")){closeInputChecks();return;}
    if(ignored.length==1&&ignored[0].equals("original-integration")){originalIntegrationChecks();return;}
    MainActivity duringClear=eligible();
    MainActivity.resourceClearing=true;
    duringClear.resourceControls();
    duringClear.startGame();
    duringClear.prepareResources(null);
    duringClear.onActivityResult(134,-1,new Intent(uri("stale-during-clear")));
    ok(!duringClear.beginButton.enabled&&!duringClear.importButton.enabled&&!duringClear.clearButton.enabled,
       "clearing blocks all conflicting launcher actions");
    ok(duringClear.nativeCalls==0&&duringClear.operations.isEmpty()&&duringClear.pendingResourceImport==null,
       "clearing blocks native start, recheck and stale import results");
    MainActivity.resourceClearing=false;
    MainActivity a=fresh();a.recreateResourceUi(pickerState());
    ok(a.operations.isEmpty(),"recreation awaiting picker must not steal result with resolve");
    ok(a.awaitingResourcePicker&&!a.beginButton.enabled&&!a.importButton.enabled&&!a.checkButton.enabled,"picker control gate");
    Uri one=uri("one");a.onActivityResult(134,-1,new Intent(one));
    ok(a.operations.size()==1&&a.operations.get(0)==one&&a.resourceBusy&&!a.awaitingResourcePicker,"result accepted once after recreation");
    ok(a.pendingResourceImport==null&&!a.startQueuedImport(),"consumed URI is not dispatched twice");
    a.completeSuccess(ready(),"/SYNTHETIC-NOT-OPENED/save-only");
    ok(a.installReady&&a.beginButton.enabled&&a.nativeCalls==0,"verify completion never auto-starts native");
    ok(a.saveDir.equals("/SYNTHETIC-NOT-OPENED/save-only")&&!a.saveDir.equals(a.dataDir),"save and data UI paths remain distinct");

    MainActivity noResources=fresh();
    noResources.pendingOriginalNotice="转换未提交：ENGINE_FAILED / converter bootstrap";
    noResources.prepareResources(null);
    noResources.completeFailure(new IOException("尚未选择游戏资源"));
    ok(noResources.progress.text.contains("尚未选择游戏资源")&&noResources.progress.text.contains("ENGINE_FAILED"),
       "resource check preserves original conversion failure detail when no old resources exist");

    for(boolean workerFails:new boolean[]{false,true}){
      MainActivity b=fresh();b.recreateResourceUi(null);
      ok(b.operations.size()==1&&b.operations.get(0)==null&&b.resourceBusy,"initial resolve started");
      Uri selected=uri(workerFails?"after-failure":"after-success");
      b.onActivityResult(134,-1,new Intent(selected));
      ok(b.operations.size()==1&&b.pendingResourceImport==selected&&b.resourceCancelled,"busy result queues and cancels old check");
      if(workerFails)b.completeFailure(new Exception("cancelled old check"));else b.completeSuccess(ready(),"ignored-old-save");
      ok(b.operations.size()==2&&b.operations.get(1)==selected&&b.pendingResourceImport==null,"both completion paths dispatch pending URI once");
      ok(b.resourceBusy&&!b.resourceCancelled&&!b.installReady&&b.preparedResources==null,"new import resets stale cancellation/readiness");
      ok(!b.startQueuedImport()&&b.operations.size()==2,"busy duplicate dispatch suppressed");
      b.completeSuccess(ready(),"/SYNTHETIC-NOT-OPENED/save-only");
      ok(b.installReady&&b.nativeCalls==0,"import completion only enables explicit Begin");
    }
    MainActivity c=fresh();c.recreateResourceUi(pickerState());c.onActivityResult(134,0,null);
    ok(!c.awaitingResourcePicker&&c.operations.size()==1&&c.operations.get(0)==null,"cancel after recreation without ready starts resolve");
    MainActivity d=fresh();d.installReady=true;d.awaitingResourcePicker=true;d.resourceControls();d.onActivityResult(134,0,null);
    ok(d.installReady&&d.operations.isEmpty()&&d.beginButton.enabled,"cancel with ready retains prior readiness without importing");
    MainActivity nullResult=fresh();nullResult.awaitingResourcePicker=true;nullResult.onActivityResult(134,-1,new Intent(null));
    ok(nullResult.operations.size()==1&&nullResult.operations.get(0)==null,"OK with missing URI follows cancelled-picker path");

    MainActivity old=fresh();old.recreateResourceUi(null);Uri queued=uri("saved-queue");old.onActivityResult(134,-1,new Intent(queued));
    Bundle saved=new Bundle();old.onSaveInstanceState(saved);
    ok(saved.getParcelable("resource-import-uri")==queued&&!saved.getBoolean("resource-picker-pending",true)&&old.baseSaveCalls==1,"pending URI saved with picker flag");
    old.destroyed=true;MainActivity replacement=new MainActivity();replacement.recreateResourceUi(saved);
    ok(replacement.operations.size()==1&&replacement.operations.get(0)==queued,"saved queued URI imports without unrequested resolve");
    old.completeSuccess(ready(),"stale");old.completeFailure(new Exception("stale"));old.onActivityResult(134,-1,new Intent(uri("stale-result")));
    ok(replacement.operations.size()==1&&replacement.resourceBusy&&!replacement.installReady,"old callbacks do not mutate new Activity");
    ok(old.preparedResources==null,"old success callback not published after destroy");
    MainActivity waiting=fresh();waiting.awaitingResourcePicker=true;Bundle waitingSaved=new Bundle();waiting.onSaveInstanceState(waitingSaved);
    MainActivity waitingNew=new MainActivity();waitingNew.recreateResourceUi(waitingSaved);
    ok(waitingNew.awaitingResourcePicker&&waitingNew.operations.isEmpty(),"awaiting flag survives independently of queued URI");

    for(String condition:new String[]{"busy","destroyed","started","native","not-current","finishing"}){
      MainActivity guarded=fresh();Uri selected=uri(condition);guarded.pendingResourceImport=selected;
      if(condition.equals("busy"))guarded.resourceBusy=true;
      if(condition.equals("destroyed"))guarded.destroyed=true;
      if(condition.equals("started"))guarded.started=true;
      if(condition.equals("native"))MainActivity.nativeDataDir="already-running";
      if(condition.equals("not-current"))new MainActivity();
      if(condition.equals("finishing"))guarded.finishing=true;
      ok(!guarded.startQueuedImport()&&guarded.pendingResourceImport==selected&&guarded.operations.isEmpty(),"queue guard preserves pending URI: "+condition);
    }
    MainActivity unknown=fresh();unknown.awaitingResourcePicker=true;unknown.onActivityResult(999,-1,new Intent(uri("other-request")));
    ok(unknown.awaitingResourcePicker&&unknown.operations.isEmpty(),"unrelated Activity result ignored");
    ok(unknown.baseResultCalls==1,"super result handler preserved");
    startupChecks();
    System.out.println("Actual extracted resource Activity lifecycle PASS: "+assertions+" assertions");
  }
}
'''


class ResourceImportActivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ACTIVITY.read_text(encoding='utf-8')
        cls.controller_source = CONTROLLER.read_text(encoding='utf-8')
        cls.work = Path(tempfile.mkdtemp(prefix='resource-import-activity-', dir=os.environ.get('RESOURCE_IMPORT_ACTIVITY_WORK_ROOT') or os.environ.get('TMPDIR') or tempfile.gettempdir()))
        for name in ('classes', 'tmp', 'home', 'cache'):
            (cls.work / name).mkdir()
        print('Actual Activity host harness: ' + str(cls.work), flush=True)
        cls.jdk = Path(os.environ.get('JAVA_HOME', '/Library/Java/JavaVirtualMachines/jdk-25.jdk/Contents/Home'))
        cls.env = dict(os.environ)
        for key in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS', 'JDK_JAVAC_OPTIONS', 'CLASSPATH'):
            cls.env.pop(key, None)
        cls.env.update(HOME=str(cls.work/'home'), TMPDIR=str(cls.work/'tmp'), TMP=str(cls.work/'tmp'),
                       TEMP=str(cls.work/'tmp'), XDG_CACHE_HOME=str(cls.work/'cache'), PYTHONDONTWRITEBYTECODE='1')
        cls.worker = method(cls.source, 'prepareResources')
        callbacks = []
        marker = 'runOnUiThread(() -> {'
        at = 0
        while True:
            at = cls.worker.find(marker, at)
            if at < 0:
                break
            opening = cls.worker.index('{', at)
            end = closing_brace(cls.worker, opening)
            callbacks.append(cls.worker[opening+1:end])
            at = end + 1
        if len(callbacks) != 2:
            raise AssertionError('expected actual worker success and failure UI callbacks')
        on_create = method(cls.source, 'onCreate')
        replacement = {
            '__METHODS__': '\n'.join(method(cls.source, name) for name in
                ('onActivityResult', 'startQueuedImport', 'onSaveInstanceState', 'resourceControls', 'resourceSelectionAllowed', 'installError', 'resourcePath', 'startGame', 'closeResourceInput', 'privateRecordDirectory')),
            '__PREPARE_PREFIX__': cls.worker[:cls.worker.index('    new Thread(')],
            '__RESTORE_BUNDLE__': marked_block(on_create, 'if (b != null) {'),
            '__CREATE_RESOURCE_BRANCH__': if_else_block(on_create, 'if (nativeDataDir != null)'),
            '__ACTUAL_ORIGINAL_HOST__': marked_block(cls.source, 'private static final class OriginalHost'),
            '__ACTUAL_RESOLVED_RESOURCES__': marked_block(cls.source, 'private static final class ResolvedResources'),
            '__ACTUAL_CONTROLLER_INTERFACES__': '\n'.join(marked_block(cls.controller_source, 'public interface ' + name) for name in ('Work', 'Host')),
            '__SUCCESS_CALLBACK__': callbacks[0], '__FAILURE_CALLBACK__': callbacks[1],
        }
        harness = JAVA
        for token, value in replacement.items():
            harness = harness.replace(token, value)
        java = cls.work/'ResourceImportActivityHostTest.java'
        java.write_text(harness, encoding='utf-8')
        (cls.work/'production-source-sha256.txt').write_text(hashlib.sha256(cls.source.encode()).hexdigest()+'\n')
        command = [str(cls.jdk/'bin/javac'), '-J-Djava.io.tmpdir='+str(cls.work/'tmp'),
                   '--release', '8', '-encoding', 'UTF-8', '-d', str(cls.work/'classes'), str(java)]
        result = subprocess.run(command, cwd=cls.work, env=cls.env, capture_output=True, text=True, timeout=60)
        (cls.work/'compile.log').write_text(result.stdout+result.stderr)
        if result.returncode:
            raise AssertionError(result.stdout+result.stderr)
        cls.callbacks = callbacks
        cls.original_host_source = marked_block(cls.source, 'private static final class OriginalHost')
        cls.original_complete = method(cls.original_host_source, 'completed')
        cls.generated_harness = harness
        cls.work.joinpath('controller-interface-source-sha256.txt').write_text(hashlib.sha256(cls.controller_source.encode()).hexdigest()+'\n')

    def test_actual_lifecycle_methods(self):
        result = subprocess.run([str(self.jdk/'bin/java'), '-Djava.io.tmpdir='+str(self.work/'tmp'),
                                 '-cp', str(self.work/'classes'), 'ResourceImportActivityHostTest'],
                                cwd=self.work, env=self.env, capture_output=True, text=True, timeout=30)
        (self.work/'lifecycle.log').write_text(result.stdout+result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('lifecycle PASS', result.stdout)

    def test_actual_close_input_faults(self):
        result = subprocess.run([str(self.jdk/'bin/java'), '-Djava.io.tmpdir='+str(self.work/'tmp'),
                                 '-cp', str(self.work/'classes'), 'ResourceImportActivityHostTest', 'close-only'],
                                cwd=self.work, env=self.env, capture_output=True, text=True, timeout=30)
        (self.work/'close-input.log').write_text(result.stdout+result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('closeResourceInput PASS: 24 assertions', result.stdout)
        close_at = self.worker.index('closeResourceInput(opened, imported != null);')
        self.assertLess(close_at, self.worker.index('if (resourceSource == opened) resourceSource = null;'))
        self.assertLess(close_at, self.worker.index('if (resourceOpenSignal == signal) resourceOpenSignal = null;'))
        self.assertIn('if (resourceNotice != null) text.append(', self.callbacks[0])

    def test_real_worker_hooks_precede_ready_or_error_publication(self):
        self.assertEqual(self.worker.count('if (startQueuedImport()) return;'), 2)
        for callback in self.callbacks:
            self.assertLess(callback.index('resourceBusy = false;'), callback.index('if (startQueuedImport()) return;'))
        self.assertLess(self.callbacks[0].index('if (startQueuedImport()) return;'),
                        self.callbacks[0].index('preparedResources = ready;'))
        self.assertLess(self.callbacks[1].index('if (startQueuedImport()) return;'),
                        self.callbacks[1].index('installError('))
        self.assertIn('resourceCancelled || destroyed || currentActivity != this', self.worker)
        self.assertNotIn('nativeStart(', self.worker)

    def test_boolean_start_publishes_cache_after_acceptance(self):
        begin = method(self.source, 'startGame')
        self.assertIn('static native boolean nativeStart(', self.source)
        self.assertLess(begin.index('if (!nativeStart('), begin.index('nativeDataDir = selectedData'))
        self.assertLess(begin.index('nativeDataDir = selectedData'), begin.index('started = true;'))
        self.assertLess(begin.index('started = true;'), begin.index('root.removeView(dataPanel);'))
        failed = marked_block(begin, 'if (!nativeStart(')
        self.assertIn('installError(', failed)
        self.assertIn('return;', failed)
        self.assertNotIn('started = true', failed)
        self.assertNotIn('nativeDataDir =', failed)

    def test_provider_cancellation_uses_captured_handles_off_ui(self):
        cancel = method(self.source, 'cancelResourceOperation')
        self.assertIn('resourceCancelled = true;', cancel)
        self.assertIn('final android.os.CancellationSignal signal = resourceOpenSignal;', cancel)
        self.assertIn('final java.io.Closeable source = resourceSource;', cancel)
        thread = marked_block(cancel, 'new Thread(() -> {')
        self.assertIn('signal.cancel()', thread)
        self.assertIn('source.close()', thread)
        self.assertNotIn('resourceSource.close()', thread)
        self.assertNotIn('resourceOpenSignal.cancel()', thread)
        self.assertIn('cancelResourceOperation();', method(self.source, 'onActivityResult'))
        self.assertIn('cancelResourceOperation();', method(self.source, 'onDestroy'))
        self.assertIn('openFileDescriptor(source, "r", signal)', self.worker)
        self.assertIn('new android.os.ParcelFileDescriptor.AutoCloseInputStream(descriptor)', self.worker)
        self.assertIn('if (resourceSource == opened) resourceSource = null;', self.worker)
        self.assertIn('if (resourceOpenSignal == signal) resourceOpenSignal = null;', self.worker)
        choose = method(self.source, 'chooseResourceArchive')
        self.assertEqual(choose.count('if (!resourceSelectionAllowed()) return;'), 2)
        self.assertIn('awaitingResourcePicker = true;', choose)
        self.assertIn('awaitingResourcePicker = false;', choose)

    def test_start_gate_and_no_automatic_initial_start(self):
        begin = method(self.source, 'startGame')
        for guard in ('!installReady', 'resourceBusy', 'awaitingResourcePicker', 'started', 'destroyed',
                      'currentActivity != this', 'isFinishing()'):
            self.assertIn(guard, begin.split('synchronized (INSTALL_LOCK)')[0])
        create = method(self.source, 'onCreate')
        self.assertIn('if (nativeDataDir != null)', create)
        self.assertIn('OriginalConversionController.obtain(originalHost, b)', create)
        startup = if_else_block(create, 'if (nativeDataDir != null)')
        controller_else = startup[startup.index('} else {')+len('} else {'):]
        self.assertNotIn('prepareResources(', controller_else)
        self.assertNotIn('startQueuedImport(', controller_else)
        self.assertLess(self.original_complete.index('a.awaitingResourcePicker'), self.original_complete.index('a.startQueuedImport()'))
        self.assertLess(self.original_complete.index('a.startQueuedImport()'), self.original_complete.index('a.prepareResources(null)'))


    def test_actual_original_host_completed_and_ready_adapter(self):
        result = subprocess.run([str(self.jdk/'bin/java'), '-Djava.io.tmpdir='+str(self.work/'tmp'),
                                 '-cp', str(self.work/'classes'), 'ResourceImportActivityHostTest', 'original-integration'],
                                cwd=self.work, env=self.env, capture_output=True, text=True, timeout=30)
        (self.work/'original-integration.log').write_text(result.stdout+result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('OriginalHost/ResolvedResources integration PASS', result.stdout)

    def test_actual_completed_bool_is_notification_not_ready_factory(self):
        complete = self.original_complete
        self.assertNotIn('new ResolvedResources', complete)
        self.assertNotIn('installReady=true', complete.replace(' ', ''))
        self.assertNotIn('nativeStart(', complete)
        self.assertIn('a.pendingOriginalNotice=', complete)
        adapter = marked_block(self.source, 'private static final class ResolvedResources')
        self.assertIn('ResolvedResources(ResourceStore.Ready ready)', adapter)
        self.assertIn('ResolvedResources(OriginalJobStore.Ready ready)', adapter)
        self.assertNotIn('ResolvedResources(boolean', adapter)
        self.assertIn('optionalFiles=java.util.Collections.emptyMap()', adapter.replace(' ', ''))
        self.assertIn('new ResolvedResources(imported)', self.worker)
        self.assertIn('originalStore.resolve(', self.worker)
        pinned = method(self.source, 'originalProfile')
        self.assertIn('getAssets().open(OriginalProfilePin.ASSET)', pinned)
        self.assertIn('OriginalProfile.read(input,OriginalProfilePin.SHA256)', pinned)
        self.assertIn('return originalProfile(app)', self.original_host_source)

    def test_actual_controller_delegation_and_weak_application_gate(self):
        activity_result = method(self.source, 'onActivityResult')
        self.assertLess(activity_result.index('originalController.onActivityResult(request,result,data)'), activity_result.index('request != REQUEST_RESOURCE_IMPORT'))
        self.assertIn('originalController.saveState(state)', method(self.source, 'onSaveInstanceState'))
        self.assertIn('originalController.detach(originalHost)', method(self.source, 'onDestroy'))
        begin = method(self.source, 'startGame')
        self.assertIn('originalController.isBusy()', begin.split('synchronized (INSTALL_LOCK)')[0])
        self.assertIn('WeakReference<MainActivity>', self.original_host_source)
        self.assertIn('private final Context app', self.original_host_source)
        self.assertIn('lockInstallProcess(app); work.run();', self.original_host_source)
        self.assertNotIn('System.loadLibrary', self.generated_harness)
        self.assertNotIn('new Thread(', self.generated_harness)


if __name__ == '__main__':
    unittest.main(verbosity=2)
