from pathlib import Path
import tempfile, subprocess
root=Path(tempfile.mkdtemp(prefix="wmmt-bgm-test-"))
project=Path(__file__).resolve().parents[1]
p=(project / 'android/java/com/wmmt/port/MainActivity.java').read_text()
a=p.index('  void setBgmGameplayPaused('); b=p.index('  void fail(',a)
lifecycle=p[p.index('  @Override protected void onPause()'):p.index('  @Override public void onTrimMemory(')]
# The current no-log Activity has no old diagnostics handler or consent dialog.
assert 'logHandler' not in lifecycle and 'logHealthCheck' not in lifecycle and 'consentDialog' not in lifecycle
methods=p[a:b].replace('Executors.newSingleThreadExecutor()', 'new FakeExecutor()')
(root / 'android/util').mkdir(parents=True,exist_ok=True)
(root / 'android/util/Log.java').write_text('package android.util; public class Log { public static int w(String a,String b){return 0;} public static int w(String a,String b,Throwable c){return 0;} }')
t='''import java.io.*; import java.util.*; import java.util.concurrent.*;
class Activity { protected void onPause(){} protected void onResume(){} protected void onDestroy(){} protected void onStop(){} protected void onNewIntent(Intent i){} }
class Intent { static final String ACTION_MAIN="main", CATEGORY_LAUNCHER="launcher"; String getAction(){return null;} boolean hasCategory(String name){return false;} }
class Sensors { void unregisterListener(Object o){} void registerListener(Object o,Object g,int rate){} }
class Displays { void unregisterDisplayListener(Object o){} void registerDisplayListener(Object o,Object h){} }
class OriginalController { void detach(Object o){} boolean isPickingSource(){return false;} }
class Panel { void removeView(Object o){} void release(){} }
class SensorManager { static final int SENSOR_DELAY_GAME=1; }
class Movie { void pause(){} void start(){} void stopPlayback(){} }
class Handler { Runnable removed; void removeCallbacks(Runnable r){removed=r;} }
class AlertDialog { boolean dismissed; void dismiss(){dismissed=true;} }
class CardResources { static File music(File f,String n) { return f; } }
class ArcadeBgm {
 interface Listener { void ready(ArcadeBgm p); void failed(ArcadeBgm p,Exception e); }
 static boolean enabled; static boolean supports(String name){return enabled;}
 static boolean isTenCue(String name){return name!=null&&name.matches("ten_[a-e][1-9]");}
 Listener listener; boolean closed,playing,started,fadeIn; float volume; int fadeMs;
 ArcadeBgm(File file,File cache,String cue,Listener l){listener=l;}
 void fade(boolean in,int ms){fadeIn=in;fadeMs=ms;}
 void start(){started=true;} void close(){closed=true;playing=false;}
 void playback(boolean play,float gain){if(closed)throw new AssertionError("closed PCM");playing=play;volume=gain;}
 void ready(){listener.ready(this);} void fail(){listener.failed(this,new IOException("fake PCM error"));}
}
class MediaPlayer {
 interface Error { boolean call(MediaPlayer p,int w,int e); } interface Prepared { void call(MediaPlayer p); }
 static ArrayList<MediaPlayer> all=new ArrayList<>(); Error error; Prepared prepared; boolean released,playing,preparing; float volume;
 MediaPlayer(){all.add(this);} void setOnErrorListener(Error e){error=e;} void setOnPreparedListener(Prepared p){prepared=p;}
 void setDataSource(String p){} void setLooping(boolean b){} void prepare(){} void prepareAsync(){preparing=true;} void setVolume(float a,float b){if(preparing)throw new AssertionError("volume during prepare");volume=a;} void start(){if(released||preparing)throw new AssertionError("invalid start"); playing=true;} boolean isPlaying(){return playing;} void pause() {if(preparing)throw new AssertionError("invalid pause");playing=false;} void firePrepared(){preparing=false;prepared.call(this);} void release(){if(released)throw new RuntimeException("double release");released=true;playing=false;}
}
class FakeExecutor extends AbstractExecutorService { ArrayList<Runnable> q=new ArrayList<>(); boolean closed; public void execute(Runnable r){q.add(r);} public void shutdown(){closed=true;} public java.util.List<Runnable> shutdownNow(){closed=true;return q;} public boolean isShutdown(){return closed;} public boolean isTerminated(){return closed;} public boolean awaitTermination(long n,TimeUnit u){return true;} void run(){q.remove(0).run();} }
public class AsyncStateTest extends Activity {
 volatile boolean started=true,destroyed=false; boolean resumed=true,bgmPreparing; volatile boolean bgmGameplayPaused; long bgmPauseRevision; volatile long bgmGeneration; ExecutorService bgmExecutor; MediaPlayer bgm; ArcadeBgm arcadeBgm,pendingArcadeBgm,fadingArcadeBgm; String requestedBgm; float bgmVolume=1; File cardResources,dataDir; static File nativeTenBgmFile; int failures; ArrayList<Runnable> ui=new ArrayList<>();
 static AsyncStateTest currentActivity; final Handler logHandler=new Handler(); final Runnable logHealthCheck=()->{}; AlertDialog consentDialog;
 AlertDialog launcherNotice; boolean launcherNoticePending,awaitingResourcePicker; void showLauncherNotice(){}
 Displays displays; OriginalController originalController; Object originalHost; Panel root,dataPanel,launcherWallpaper;
 Sensors sensors; Object gravity; Movie movie; long movieToken; void finishMovie(Movie m,long t,boolean notify,boolean start){} void nativePause(boolean p){} void hideBars(){} void refreshSurfaceRate(){} void cancelResourceOperation(){}
 File getCacheDir(){return dataDir;} boolean isFinishing(){return false;} void nativeBgmFailure(AsyncStateTest a,int g){failures++;} void runOnUiThread(Runnable r){ui.add(r);} void drain(){while(!ui.isEmpty())ui.remove(0).run();} void worker(){((FakeExecutor)bgmExecutor).run();}
'''+lifecycle+methods+'''
 static void check(boolean b){if(!b)throw new AssertionError();}
 public static void main(String[] x)throws Exception {
  AsyncStateTest a=new AsyncStateTest(); currentActivity=a; a.cardResources=File.createTempFile("music",".m4a",new File(x[0])); a.dataDir=new File(x[0],"fixture"); a.dataDir.mkdirs();
  a.playBgm("wm2_01");a.drain(); a.playBgm("wmr_01");a.drain(); a.worker();check(a.ui.isEmpty());a.worker();a.drain();MediaPlayer old=a.bgm;check(a.bgmPreparing);
  a.onPause();a.onResume();check(a.bgmPreparing&&!old.playing);a.onPause();a.setBgmVolume(.25f);a.drain();old.firePrepared();check(!old.playing&&old.volume==.25f);a.onResume();check(old.playing);
  a.playBgm("wm2_01");a.drain();check(old.released);a.worker();a.drain();MediaPlayer current=a.bgm;old.error.call(old,1,1);old.prepared.call(old);check(a.bgm==current&&a.failures==0);
  a.playBgm(null);a.drain();check(current.released);current.error.call(current,1,1);check(a.failures==0);
  a.playBgm("wm2_01");a.drain();a.worker();a.drain();MediaPlayer error=a.bgm;error.error.call(error,1,1);check(error.released&&a.failures==1&&a.bgm==null);
  a.playBgm("wm2_01");a.drain();a.worker();a.playBgm(null);a.drain();check(a.bgm==null&&a.failures==1);
  File dir=new File(a.dataDir,"sound/bgm");dir.mkdirs();new File(dir,"legacy.m4a").createNewFile();
  a.playBgm("wm2_01");a.drain();a.worker();a.playBgm("legacy");a.drain();MediaPlayer legacy=a.bgm;check(legacy!=null&&legacy.playing&&!a.bgmPreparing&&a.failures==1);
  a.playBgm("wm2_01");a.drain();a.worker();a.drain();MediaPlayer dead=a.bgm;a.onDestroy();dead.error.call(dead,1,1);dead.prepared.call(dead);check(dead.released&&a.failures==1);
  // A replacement Activity becomes current before the old instance is destroyed.
   AsyncStateTest previous=new AsyncStateTest(); currentActivity=previous; previous.cardResources=a.cardResources; previous.dataDir=a.dataDir; previous.consentDialog=new AlertDialog();
   previous.playBgm("wm2_01");previous.drain();previous.worker();previous.drain();MediaPlayer stale=previous.bgm;check(previous.bgmPreparing);
   AsyncStateTest replacement=new AsyncStateTest();currentActivity=replacement;replacement.cardResources=a.cardResources;replacement.dataDir=a.dataDir;
   replacement.playBgm("wmr_01");replacement.drain();replacement.worker();replacement.drain();MediaPlayer fresh=replacement.bgm;check(replacement.bgmPreparing);
   previous.onDestroy();check(currentActivity==replacement&&stale.released);
   stale.error.call(stale,1,1);stale.prepared.call(stale);check(previous.bgm==null&&previous.failures==0&&replacement.bgm==fresh&&replacement.bgmPreparing&&replacement.failures==0&&!fresh.playing);
   fresh.firePrepared();check(fresh.playing&&!fresh.released);replacement.onDestroy();check(currentActivity==null&&fresh.released);
   // PCM playback swaps only after the replacement has actually primed.
   ArcadeBgm.enabled=true;currentActivity=a=new AsyncStateTest();
   a.dataDir=new File(x[0],"fixture");
   File pcmDir=new File(a.dataDir,"sound/bgm");new File(pcmDir,"other.m4a").createNewFile();
   a.playBgm("legacy");a.drain();ArcadeBgm first=a.pendingArcadeBgm;
   check(first.started&&!first.playing&&a.arcadeBgm==null);
   first.ready();a.drain();check(a.arcadeBgm==first&&first.playing);
   a.playBgm("other");a.drain();ArcadeBgm next=a.pendingArcadeBgm;
   check(first.playing&&!first.closed&&!next.playing);
   a.playBgm("legacy");a.drain();ArcadeBgm latest=a.pendingArcadeBgm;
   next.ready();next.fail();a.drain();check(next.closed&&first.playing&&a.pendingArcadeBgm==latest);
   a.setBgmGameplayPaused(true);a.setBgmVolume(.4f);latest.ready();a.drain();
   check(first.closed&&a.arcadeBgm==latest&&!latest.playing&&latest.volume==.4f);
   a.setBgmGameplayPaused(false);a.drain();check(latest.playing);
   a.onPause();check(!latest.playing&&!latest.closed);a.onResume();check(latest.playing);
   latest.fail();a.drain();check(a.arcadeBgm==null&&a.bgm!=null&&a.bgm.playing);
   a.playBgm("other");a.drain();ArcadeBgm cancelled=a.pendingArcadeBgm;
   a.playBgm(null);a.drain();cancelled.ready();a.drain();
   check(cancelled.closed&&a.arcadeBgm==null&&a.bgm==null);
   a.playRaceBgm("ten_d1","legacy",0);a.drain();ArcadeBgm fallback=a.pendingArcadeBgm;
   fallback.ready();a.drain();
   a.playRaceBgm("ten_d2","legacy",2000);a.drain();check(a.arcadeBgm==fallback&&a.pendingArcadeBgm==null);
   nativeTenBgmFile=File.createTempFile("ten-bgm",".bin",a.dataDir);
   a.playRaceBgm("ten_d1","legacy",0);a.drain();ArcadeBgm ten=a.pendingArcadeBgm;
   ten.ready();a.drain();check(fallback.closed&&a.arcadeBgm==ten);
   a.playRaceBgm("ten_d2","legacy",2000);a.drain();ArcadeBgm nextTen=a.pendingArcadeBgm;
   check(ten.playing&&nextTen!=null&&!nextTen.playing);
   nextTen.ready();a.drain();
   check(ten.playing&&nextTen.playing&&a.fadingArcadeBgm==ten&&a.arcadeBgm==nextTen);
   check(ten.fadeMs==2000&&!ten.fadeIn&&nextTen.fadeMs==2000&&nextTen.fadeIn);
   a.onPause();check(!ten.playing&&!nextTen.playing);a.onResume();check(ten.playing&&nextTen.playing);
   a.onDestroy();
   check(ten.closed&&nextTen.closed);
   System.out.println("fake executor/player state tests passed");
 }
}
'''
(root / 'AsyncStateTest.java').write_text(t)
(root / 'classes').mkdir()
subprocess.run(['javac','-d',str(root / 'classes'),str(root / 'android/util/Log.java'),str(root / 'AsyncStateTest.java')],check=True)
subprocess.run(['java','-cp',str(root / 'classes'),'AsyncStateTest',str(root)],check=True)
print('Temporary test artifacts:', root)
