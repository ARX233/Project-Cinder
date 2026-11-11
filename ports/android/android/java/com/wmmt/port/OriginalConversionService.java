package com.wmmt.port;

import android.app.ActivityManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.Message;
import android.os.Messenger;
import android.os.PowerManager;
import android.os.Process;
import android.os.RemoteException;
import android.os.SystemClock;
import android.util.Log;
import org.json.JSONObject;
import org.json.JSONTokener;
import java.io.File;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/** Non-exported :convert foreground service. Owns a private job ONLY: never publishes
 * resources, changes selection, opens saves, imports MainActivity or loads game main.
 * FINISHED means an engine report exists; only main authenticates it and then ACKs.
 * Same UID is not a sandbox. Cancellation is cooperative, with a self-only watchdog.
 */
public final class OriginalConversionService extends Service {
    public static final int MSG_START=1, MSG_CANCEL=2, MSG_RESULT_ACK=3, MSG_HOST_PROGRESS=4;
    public static final int MSG_PROGRESS=101, MSG_FINISHED=102, MSG_FAILED=103;
    public static final String KEY_JOB_ID="jobId", KEY_JOB_DIR="jobDir";
    public static final String KEY_DEADLINE="deadlineElapsedRealtime";
    public static final String KEY_STAGE="stage", KEY_DONE="done", KEY_TOTAL="total", KEY_PID="pid";
    public static final String KEY_REPORT_JSON="reportJson", KEY_REPORT_PATH="reportPath";
    public static final String KEY_ERROR_CODE="errorCode", KEY_ERROR_MESSAGE="errorMessage";
    public static final String ACTION_PREPARE="com.wmmt.port.original.PREPARE";
    public static final String ACTION_CANCEL="com.wmmt.port.original.CANCEL";
    public static final long DEFAULT_DURATION_MS=4L*60*60*1000;
    public static final long MAX_DURATION_MS=6L*60*60*1000;
    public static final long CANCEL_GRACE_MS=60_000L;
    public static final long MIN_AVAILABLE_MEMORY=256L*1024*1024;
    private static final long MAX_JOB_JSON=1024L*1024, MAX_REPORT_BYTES=2L*1024*1024;
    private static final int INLINE_REPORT_BYTES=48*1024, RUNNING=1, WAIT_ACK=2;
    private static final String TAG="OriginalConversion", CHANNEL="wmmt_original_conversion_v1";
    private static final int NOTIFICATION_ID=13501;

    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final Messenger incoming = new Messenger(new Handler(Looper.getMainLooper()) {
        @Override public void handleMessage(Message message) { receive(message); }
    });
    private volatile Job job;
    private int selfPid;
    private boolean foreground, clientBound;
    private PowerManager.WakeLock wakeLock;
    private String startupError;

    private static final class Job {
        final String id; final File dir; final long deadline;
        final AtomicBoolean cancelled=new AtomicBoolean();
        volatile int state=RUNNING;
        volatile String cancelCode;
        volatile String stage="accepted";
        volatile long done,total,lastProgressAt;
        Messenger client;
        Bundle terminal;
        int terminalWhat;
        boolean cancelWatchdogArmed;
        Job(String id,File dir,long deadline,Messenger client) { this.id=id;this.dir=dir;this.deadline=deadline;this.client=client; }
    }

    @Override public void onCreate() {
        super.onCreate(); selfPid=Process.myPid();
        try {
            OriginalRuntime.requireConversionProcess(this);
            ServiceInfo info=getPackageManager().getServiceInfo(new ComponentName(this,OriginalConversionService.class),0);
            if(info.exported || !(getPackageName()+":convert").equals(info.processName))
                throw new IllegalStateException("Manifest must declare a non-exported exact :convert service");
            NotificationManager manager=(NotificationManager)getSystemService(Context.NOTIFICATION_SERVICE);
            if(manager==null) throw new IllegalStateException("Notification service unavailable");
            manager.createNotificationChannel(new NotificationChannel(CHANNEL,"原版资源转换",NotificationManager.IMPORTANCE_LOW));
            // Android13 notification permission denial is NOT a storage fallback condition.
            // FGS is still requested; any platform FGS failure is reported and refuses work.
            startForeground(NOTIFICATION_ID,notification(null,"正在准备原版资源",0,0));
            foreground=true;
            PowerManager power=getSystemService(PowerManager.class);
            if(power==null) throw new IllegalStateException("转换无法取得设备电源服务");
            wakeLock=power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"ProjectCinder:original-conversion");
            wakeLock.acquire(MAX_DURATION_MS);
        } catch(Exception | LinkageError e) {
            startupError=bounded(e.toString(),1800); Log.e(TAG,"Foreground converter admission failed",e);
        }
        main.postDelayed(() -> {
            if(job==null && !clientBound) retireSelf();
        },30_000L);
    }
    @Override public IBinder onBind(Intent intent) { clientBound=true;return incoming.getBinder(); }
    @Override public boolean onUnbind(Intent intent) {
        clientBound=false;
        if(job==null) retireSelf();
        return true;
    }
    @Override public int onStartCommand(Intent intent,int flags,int startId) {
        if(intent!=null && ACTION_CANCEL.equals(intent.getAction())) {
            Job active=job;
            if(active!=null && active.id.equals(intent.getStringExtra(KEY_JOB_ID))) requestCancel(active,"CANCELLED");
        }
        return START_NOT_STICKY;
    }
    private void receive(Message message) {
        // Non-exported manifest plus UID admission; same-UID callers remain mutually trusted.
        if(message.sendingUid!=Process.myUid()) { Log.w(TAG,"Rejected foreign UID message"); return; }
        Bundle data=message.getData(); data.setClassLoader(OriginalConversionService.class.getClassLoader());
        try {
            if(message.what==MSG_START) { startRequest(data,message.replyTo); return; }
            String id=data.getString(KEY_JOB_ID);
            Job active=job;
            if(message.what==MSG_HOST_PROGRESS) {
                if((active==null && id==null) ||
                        (active!=null && active.id.equals(id) && active.state==WAIT_ACK && active.terminalWhat==MSG_FINISHED)) {
                    long done=data.getLong(KEY_DONE), total=data.getLong(KEY_TOTAL);
                    String label=active==null?stageLabel(data.getString(KEY_STAGE)):"正在校验并登记资源";
                    updateNotification(active,progressText(label,done,total),done,total);
                }
                return;
            }
            if(active==null || !active.id.equals(id)) { sendFailure(message.replyTo,id,"UNKNOWN_JOB","No matching accepted job"); return; }
            if(data.containsKey(KEY_PID) && data.getInt(KEY_PID)!=selfPid) { sendFailure(message.replyTo,id,"STALE_PID","Converter PID does not match"); return; }
            if(message.replyTo!=null) active.client=message.replyTo;
            if(message.what==MSG_CANCEL) {
                if(active.state==WAIT_ACK) resendTerminal(active); else requestCancel(active,"CANCELLED");
            } else if(message.what==MSG_RESULT_ACK) {
                if(active.state!=WAIT_ACK) { sendFailure(message.replyTo,id,"NOT_TERMINAL","Cannot ACK a running job"); return; }
                // Main has independently checked/discarded the result. No publish/Ready here.
                retireSelf();
            } else sendFailure(message.replyTo,id,"BAD_REQUEST","Unknown message code");
        } catch(Exception e) { sendFailure(message.replyTo,null,"BAD_REQUEST",e.toString()); }
    }
    private void startRequest(Bundle data,Messenger reply) {
        String id=null;
        try {
            if(reply==null) throw new IOException("START requires replyTo Messenger");
            for(String key:data.keySet()) if(!key.equals(KEY_JOB_ID)&&!key.equals(KEY_JOB_DIR)&&!key.equals(KEY_DEADLINE))
                throw new IOException("Unknown START key (no sourceRoot/URI execution): "+key);
            id=data.getString(KEY_JOB_ID);
            String raw=data.getString(KEY_JOB_DIR);
            File dir=validatePrivateJob(getNoBackupFilesDir(),id,raw);
            Job active=job;
            if(active!=null) {
                if(!active.id.equals(id)||!active.dir.equals(dir)) { sendFailure(reply,id,"BUSY","This process already owns another job");return; }
                active.client=reply;
                if(active.state==WAIT_ACK) resendTerminal(active); else progress(active,active.stage,active.done,active.total,true);
                return; // Reconnect, never a second Python/job invocation.
            }
            long now=SystemClock.elapsedRealtime();
            long deadline=data.containsKey(KEY_DEADLINE)?data.getLong(KEY_DEADLINE):now+DEFAULT_DURATION_MS;
            if(deadline<=now || deadline-now>MAX_DURATION_MS) throw new IOException("Deadline must be in (now, now+6h], using elapsedRealtime milliseconds");
            final Job accepted=new Job(id,dir,deadline,reply); job=accepted;
            if(startupError!=null || !foreground) {
                fail(accepted,"FOREGROUND_UNAVAILABLE",startupError==null?"Foreground service did not start":startupError);
                main.postDelayed(this::retireSelf,250L); return;
            }
            try { memoryAdmission(); }
            catch(IOException e) { fail(accepted,"LOW_RAM",e.getMessage());return; }
            progress(accepted,"runtime-preflight",0,0,true);
            main.postDelayed(() -> {
                if(accepted.state==RUNNING) requestCancel(accepted,"DEADLINE_EXCEEDED");
            },Math.max(1L,deadline-SystemClock.elapsedRealtime()));
            worker.execute(() -> run(accepted));
        } catch(Exception e) { sendFailure(reply,id,"UNSAFE_OR_INCOMPLETE_JOB",e.getMessage()); }
    }
    /** Pure path/sentinel admission, also host-testable. Main writes job.json last by atomic rename.
     * Python owns full JSON schema/source inventory validation. No source URI/root is accepted.
     */
    static File validatePrivateJob(File noBackup,String id,String raw) throws IOException {
        if(id==null || !id.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}") || !UUID.fromString(id).toString().equals(id))
            throw new IOException("jobId must be a canonical lowercase UUID");
        if(raw==null || !new File(raw).isAbsolute()) throw new IOException("A canonical private job directory is required");
        File base=noBackup.getCanonicalFile();
        File rawRoot=new File(base,"re3dxplus-original-jobs"), root=rawRoot.getCanonicalFile();
        File expected=new File(root,id);
        if(!root.equals(rawRoot)||!root.getParentFile().equals(base)||!new File(raw).getCanonicalPath().equals(raw)||!expected.getPath().equals(raw))
            throw new IOException("Job path is not the exact canonical noBackup job UUID directory");
        if(Files.isSymbolicLink(root.toPath())||Files.isSymbolicLink(expected.toPath())||
                !Files.isDirectory(root.toPath(),LinkOption.NOFOLLOW_LINKS)||!Files.isDirectory(expected.toPath(),LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Private job root/directory is missing or a symlink");
        Path sentinel=expected.toPath().resolve("job.json");
        if(Files.isSymbolicLink(sentinel)||!Files.isRegularFile(sentinel,LinkOption.NOFOLLOW_LINKS)||Files.size(sentinel)<=0||Files.size(sentinel)>MAX_JOB_JSON)
            throw new IOException("job.json must be a nonempty regular nofollow direct child, at most 1MiB");
        return expected;
    }
    private void memoryAdmission() throws IOException {
        ActivityManager manager=(ActivityManager)getSystemService(Context.ACTIVITY_SERVICE);
        if(manager==null) throw new IOException("Cannot inspect available memory; conversion refused");
        ActivityManager.MemoryInfo memory=new ActivityManager.MemoryInfo(); manager.getMemoryInfo(memory);
        if(manager.isLowRamDevice()||memory.lowMemory||memory.availMem<MIN_AVAILABLE_MEMORY)
            throw new IOException("Low-RAM/low-memory device state; need at least 256MiB available before runtime bootstrap");
    }
    static int conversionWorkerBudget(int cores,int ceiling,long available,long threshold,int thermalStatus) {
        // Reserve 256 MiB above Android's low-memory threshold. Each worker
        // has a 256 MiB allowance, matching the native AO heap ceiling.
        long workerBytes = 256L * 1024 * 1024;
        long memoryWorkers = (available - threshold) / workerBytes - 1;
        int limit = (int)Math.max(1, Math.min(Math.min(cores, ceiling), memoryWorkers));
        if (thermalStatus >= PowerManager.THERMAL_STATUS_CRITICAL) return 1;
        if (thermalStatus >= PowerManager.THERMAL_STATUS_SEVERE) return Math.min(limit, 2);
        if (thermalStatus >= PowerManager.THERMAL_STATUS_MODERATE || limit < 6) return Math.min(limit, 4);
        if (thermalStatus >= PowerManager.THERMAL_STATUS_LIGHT || limit < 8) return 6;
        return 8;
    }

    private int conversionWorkerCount(int ceiling) {
        int cores = Runtime.getRuntime().availableProcessors();
        if (cores < 2) return 1;
        ActivityManager manager = (ActivityManager)getSystemService(Context.ACTIVITY_SERVICE);
        if (manager == null || manager.isLowRamDevice()) return 1;
        ActivityManager.MemoryInfo memory = new ActivityManager.MemoryInfo();
        manager.getMemoryInfo(memory);
        if (memory.lowMemory) return 1;

        int thermalStatus = PowerManager.THERMAL_STATUS_NONE;
        if (Build.VERSION.SDK_INT >= 29) {
            PowerManager power = getSystemService(PowerManager.class);
            if (power != null) thermalStatus = power.getCurrentThermalStatus();
        }
        return conversionWorkerBudget(cores,ceiling,memory.availMem,memory.threshold,thermalStatus);
    }

    private void run(Job active) {
        try {
            JavaProgressObject callback=new JavaProgressObject(this,active);
            if(callback.isCancelled()) throw new IOException("Cancelled before runtime bootstrap");
            memoryAdmission();
            String json;
            Path lockPath=active.dir.toPath().resolve("converter.lock");
            try(FileChannel file=FileChannel.open(lockPath,StandardOpenOption.CREATE,
                    StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS);
                    FileLock lock=file.tryLock()) {
                if(lock==null) throw new IOException("上次转换仍在结束，请稍后继续");
                json=OriginalRuntime.runJob(this,active.dir.getPath(),callback);
            }
            if(callback.isCancelled()) throw new IOException("Cancelled before report handoff");
            byte[] bytes=json.getBytes(StandardCharsets.UTF_8);
            if(bytes.length==0 || bytes.length>MAX_REPORT_BYTES) throw new IOException("Engine report must be nonempty and at most 2MiB");
            JSONTokener tokener=new JSONTokener(json);
            if(!(tokener.nextValue() instanceof JSONObject)||tokener.nextClean()!=0) throw new IOException("Engine did not return one JSON report object");
            validatePrivateJob(getNoBackupFilesDir(),active.id,active.dir.getPath());
            // Unique CREATE_NEW receipt, fsynced before FINISHED. Crash partial files are not Ready.
            File report=new File(active.dir,"java-report-"+selfPid+"-"+UUID.randomUUID()+".json");
            if(!report.getCanonicalFile().getParentFile().equals(active.dir)) throw new IOException("Unsafe report path");
            try(FileChannel channel=FileChannel.open(report.toPath(),StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS)) {
                ByteBuffer buffer=ByteBuffer.wrap(bytes);while(buffer.hasRemaining())channel.write(buffer);channel.force(true);
            }
            Bundle result=base(active.id);result.putString(KEY_REPORT_PATH,report.getCanonicalPath());
            if(bytes.length<=INLINE_REPORT_BYTES) result.putString(KEY_REPORT_JSON,json);
            main.post(() -> {
                if(active.state!=RUNNING) return;
                if(active.cancelled.get()) fail(active,cancelCode(active),"Cancelled; candidate not accepted or published");
                else terminal(active,MSG_FINISHED,result,"转换已完成，等待主进程校验");
            });
        } catch(Throwable e) {
            Log.e(TAG,"Original conversion worker stopped at "+active.stage+" "+active.done+"/"+active.total,e);
            final String code=active.cancelled.get()?cancelCode(active):
                    (e instanceof OriginalRuntime.EntryPointException?"ENGINE_ENTRY_MISSING":
                    e instanceof OriginalRuntime.BootstrapException?"RUNTIME_BOOTSTRAP_FAILED":"ENGINE_FAILED");
            final String error=bounded(e.toString(),1800);
            main.post(() -> fail(active,code,error));
        }
    }
    /** Public methods are the signed Python engine's sole progress/cancel/native-dir bridge. */
    public static final class JavaProgressObject {
        private final OriginalConversionService owner; private final Job job;
        private JavaProgressObject(OriginalConversionService owner,Job job) { this.owner=owner;this.job=job; }
        public void onProgress(String stage,long done,long total) { owner.progress(job,stage,done,total,false); }
        public boolean isCancelled() {
            if(SystemClock.elapsedRealtime()>=job.deadline && markCancelled(job,"DEADLINE_EXCEEDED"))
                owner.main.post(() -> owner.requestCancel(job,"DEADLINE_EXCEEDED"));
            return job.cancelled.get();
        }
        public int aoWorkerCount() { return owner.conversionWorkerCount(8); }
        public int mediaWorkerCount() { return owner.conversionWorkerCount(4); }
        public long aoWallBudgetMillis() {
            return Math.max(1L, job.deadline - SystemClock.elapsedRealtime());
        }
        public String getNativeLibraryDir() throws IOException { return OriginalRuntime.getNativeLibraryDir(owner); }
    }
    private static synchronized boolean markCancelled(Job active,String reason) {
        if(active.cancelled.get()) return false;
        active.cancelCode=reason; active.cancelled.set(true);return true;
    }
    private static String cancelCode(Job active) { return active.cancelCode==null?"CANCELLED":active.cancelCode; }
    private void requestCancel(Job active,String reason) {
        if(job!=active||active.state!=RUNNING) return;
        markCancelled(active,reason);
        progress(active,"cancelling-"+cancelCode(active),active.done,active.total,true);
        if(!active.cancelWatchdogArmed) {
            active.cancelWatchdogArmed=true;
            main.postDelayed(() -> {
                if(job==active&&active.state==RUNNING&&active.cancelled.get())
                    forceRetire(active,cancelCode(active)+"_FORCE_EXIT","Cooperative cancellation grace expired; only the converter PID is terminated");
            },CANCEL_GRACE_MS);
        }
    }
    private void progress(Job active,String stage,long done,long total,boolean force) {
        if(job!=active||active.state!=RUNNING) return;
        long now=SystemClock.elapsedRealtime();
        synchronized(active) {
            active.stage=bounded(stage==null?"convert":stage,160); active.done=Math.max(0,done);active.total=Math.max(0,total);
            if(!force&&now-active.lastProgressAt<200L) return;
            active.lastProgressAt=now;
        }
        main.post(() -> {
            if(job!=active||active.state!=RUNNING) return;
            Bundle data=base(active.id);data.putString(KEY_STAGE,active.stage);data.putLong(KEY_DONE,active.done);data.putLong(KEY_TOTAL,active.total);
            send(active.client,MSG_PROGRESS,data);
            updateNotification(active,progressText(stageLabel(active.stage),active.done,active.total),active.done,active.total);
        });
    }
    private void fail(Job active,String code,String error) {
        if(job!=active||active.state!=RUNNING) return;
        Bundle result=base(active.id);result.putString(KEY_ERROR_CODE,code);result.putString(KEY_ERROR_MESSAGE,bounded(error,1800));
        terminal(active,MSG_FAILED,result,"转换已停止，旧资源和存档未由本服务改动");
    }
    private void terminal(Job active,int what,Bundle result,String text) {
        active.state=WAIT_ACK;active.terminalWhat=what;active.terminal=new Bundle(result);
        if(what==MSG_FAILED) releaseWakeLock();
        send(active.client,what,result); updateNotification(active,text,0,0);
        // No ordinary auto-exit after FINISHED: main must verify then ACK. Reconnect resends.
    }
    private void resendTerminal(Job active) { if(active.terminal!=null) send(active.client,active.terminalWhat,new Bundle(active.terminal)); }
    private void sendFailure(Messenger target,String id,String code,String message) {
        Bundle data=base(id);data.putString(KEY_ERROR_CODE,code);data.putString(KEY_ERROR_MESSAGE,bounded(message,1800));send(target,MSG_FAILED,data);
    }
    private Bundle base(String id) { Bundle data=new Bundle();if(id!=null)data.putString(KEY_JOB_ID,id);data.putInt(KEY_PID,selfPid);return data; }
    private void send(Messenger target,int what,Bundle data) {
        if(target==null) return;
        Message message=Message.obtain(null,what);message.setData(data);message.replyTo=incoming;
        try { target.send(message); } catch(RemoteException e) { Log.w(TAG,"Client disconnected; retained terminal report awaits reconnect/ACK"); }
    }
    private Notification notification(Job active,String text,long done,long total) {
        Intent cancel=new Intent(this,OriginalConversionService.class).setAction(ACTION_CANCEL);
        if(active!=null) cancel.putExtra(KEY_JOB_ID,active.id);
        PendingIntent pending=PendingIntent.getService(this,NOTIFICATION_ID,cancel,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        Intent launch=new Intent(this,MainActivity.class).setAction(Intent.ACTION_MAIN)
                .addCategory(Intent.CATEGORY_LAUNCHER).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent open=PendingIntent.getActivity(this,NOTIFICATION_ID,launch,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder builder=new Notification.Builder(this,CHANNEL)
                .setSmallIcon(android.R.drawable.stat_sys_download).setContentTitle("原版资源转换")
                .setContentText(bounded(text,180)).setContentIntent(open)
                .setCategory(Notification.CATEGORY_PROGRESS).setOnlyAlertOnce(true).setOngoing(true);
        if(active!=null&&active.state==RUNNING) {
            builder.addAction(new Notification.Action.Builder(android.R.drawable.ic_menu_close_clear_cancel,"取消",pending).build());
        }
        if(active==null || active.state==RUNNING || total>0) {
            int amount=total<=0?0:(int)Math.max(0,Math.min(1000,1000.0*(double)done/(double)total));
            builder.setProgress(1000,amount,total<=0);
        }
        return builder.build();
    }
    private static String progressText(String label,long done,long total) {
        return total>0?label+" · "+Math.max(0,done)+"/"+total:label;
    }
    private static String stageLabel(String stage) {
        if(stage==null) return "正在准备原版资源";
        if(stage.startsWith("cancelling-")) return "正在取消转换";
        switch(stage) {
            case "copy-zip": return "正在复制原版 ZIP";
            case "copy-main": case "copy-source": case "snapshot-original": return "正在验证原版文件";
            case "convert-cars": case "convert-wheels": return "正在转换车辆和轮毂";
            case "plan-maps-file": case "snapshot-map-file": case "convert-map-model":
            case "convert-map-phase": case "write-map-file": return "正在转换赛道";
            case "convert-extras": return "正在转换车贴和附加资源";
            case "pack_hud": case "pack_meters": case "pack_navi": case "read-full-menu-anims":
            case "render-full-menu-sprites": return "正在转换菜单和仪表";
            case "convert-media": return "正在转换音视频";
            case "bake-ambient-occlusion": return "正在烘焙车辆阴影";
            case "verify-original-output": case "reverify-original-input": return "正在核对转换结果";
            case "pack-mileage-aura": return "正在转换里程光焰";
            case "pack-finish-menu": return "正在转换终点距离提示";
            case "pack-ten-bgm": return "正在转换十人斩音乐";
            case "pack-crown-scenes": return "正在转换皇冠与驾驶风格画面";
            case "pack-ghost-wheel": return "正在转换分身轮毂";
            case "pack-ghost-match": return "正在转换分身对战入场素材";
            case "pack-mileage-menu": return "正在转换里程结算画面";
            case "write-original-completion": return "正在写入转换完成凭据";
            default: return "正在转换原版资源";
        }
    }
    private void updateNotification(Job active,String text,long done,long total) {
        if(!foreground) return;
        try { NotificationManager manager=(NotificationManager)getSystemService(Context.NOTIFICATION_SERVICE);if(manager!=null)manager.notify(NOTIFICATION_ID,notification(active,text,done,total)); }
        catch(RuntimeException e) { Log.w(TAG,"Notification update failed; no storage fallback",e); }
    }
    private static String bounded(String text,int max) {
        if(text==null) return "";
        String clean=text.replace('\0',' ').replace('\r',' ').replace('\n',' ');
        return clean.length()<=max?clean:clean.substring(0,max);
    }
    private void forceRetire(Job active,String code,String reason) {
        if(active!=null&&active.state==RUNNING) fail(active,code,reason);
        main.postDelayed(this::retireSelf,250L); // Exceptional OS/deadline/cancel expiry, never a successful ACK.
    }
    /** Android35 dataSync OS budget timeout: stop immediately, then report the interruption.
     * This is an exceptional interruption; main must discard unfinished candidate state.
     */
    @Override public void onTimeout(int startId,int foregroundServiceType) {
        foreground=false;
        stopSelf(); // Meet Android's shutdown deadline before messaging the client.
        Job active=job;
        if(active!=null) {
            Log.w(TAG,"Android foreground-service timeout at "+active.stage+" "+active.done+"/"+active.total);
            markCancelled(active,"OS_FGS_TIMEOUT");
            if(active.state==RUNNING) fail(active,"OS_FGS_TIMEOUT","Android 后台转换已超时。可以导入已转换的资源 ZIP。");
            else {
                Bundle timeout=base(active.id);
                timeout.putString(KEY_ERROR_CODE,"OS_FGS_TIMEOUT");
                timeout.putString(KEY_ERROR_MESSAGE,"Android foreground-service budget expired while waiting for main ACK");
                active.terminalWhat=MSG_FAILED;active.terminal=timeout;
                send(active.client,MSG_FAILED,new Bundle(timeout));
            }
        }
        retireSelf();
    }
    @Override public void onTimeout(int startId) { onTimeout(startId,0); }
    @Override public void onLowMemory() { super.onLowMemory();Job active=job;if(active!=null)requestCancel(active,"LOW_MEMORY"); }
    @Override public void onTrimMemory(int level) { super.onTrimMemory(level);if(level==TRIM_MEMORY_RUNNING_CRITICAL){Job active=job;if(active!=null)requestCancel(active,"LOW_MEMORY");} }
    private void retireSelf() {
        if(!OriginalRuntime.isConversionProcess(this)) { Log.e(TAG,"Refused retirement outside exact :convert");return; }
        try { stopForeground(STOP_FOREGROUND_REMOVE); } catch(RuntimeException ignored) { }
        foreground=false;stopSelf();releaseWakeLock();
        OriginalRuntime.exitSelf(this,selfPid);
    }
    private void releaseWakeLock() {
        if(wakeLock!=null && wakeLock.isHeld()) wakeLock.release();
        wakeLock=null;
    }
    @Override public void onDestroy() {
        Job active=job;if(active!=null&&active.state==RUNNING)markCancelled(active,"SERVICE_DESTROYED");
        releaseWakeLock();
        worker.shutdown();
        if(active!=null&&active.state==RUNNING)main.postDelayed(() -> forceRetire(active,"SERVICE_DESTROYED","Service destroyed before worker completion"),CANCEL_GRACE_MS);
        super.onDestroy();
    }
}
