package com.wmmt.port;

import android.app.Activity;
import android.app.ActivityManager;
import android.app.AlertDialog;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.Message;
import android.os.Messenger;
import android.os.Process;
import android.os.RemoteException;
import android.os.SystemClock;
import java.io.File;
import java.io.IOException;
import java.lang.ref.WeakReference;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.util.Arrays;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/** Main-process UI orchestration only. No Ready factory, ResourceStore, game launch,
 * report-path publication authority, old-resource/save cleanup, or process killing.
 * Host MUST be a static weak-Activity adapter; its gate uses only process/app state.
 */
public final class OriginalConversionController {
    public interface Work { void run() throws Exception; }
    public interface Host {
        Activity activity();
        boolean canBegin();
        OriginalProfile profile() throws IOException;
        void withInstallLock(Work work) throws Exception;
        void setBusy(boolean busy);
        void status(String text);
        void completed(boolean committed,String message);
        default boolean isAlive() { Activity a=activity();return a!=null&&!a.isFinishing()&&!a.isDestroyed(); }
    }
    public static final int REQUEST_ZIP=1351, REQUEST_TREE=1352;
    public static final long MIN_AVAILABLE_MEMORY=2L*1024*1024*1024;
    private static final long DISK_RESERVE=128L*1024*1024, CONNECT_TIMEOUT_MS=20_000L;
    private static final String STATE_PREFIX="original-convert.ui.";
    private static final String UUID_RE="[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
    private static OriginalConversionController singleton;
    enum Phase { IDLE,RESTORING,PICKER,COPYING,SEALED,CONNECTING,RUNNING,CANCELLING,PUBLISHING,COMMIT_UNKNOWN,FINISHING }

    private final Context app;
    private final Path noBackup;
    private final Handler main=new Handler(Looper.getMainLooper());
    private final ExecutorService io=Executors.newSingleThreadExecutor();
    private WeakReference<Host> host=new WeakReference<Host>(null);
    private volatile Phase phase=Phase.IDLE;
    private volatile OriginalProfile profile;
    private volatile OriginalJobStore store;
    private volatile OriginalJobStore.Job job;
    private volatile OriginalSourceBroker.Control sourceControl;
    private final AtomicBoolean cancelled=new AtomicBoolean();
    private volatile boolean committed;
    private volatile boolean detachedDuringCopy;
    private volatile String copyServiceError;
    private int pickerKind,workerPid;
    private boolean pickerLaunched,restoreStarted,recoveryBind,ackOnly,terminalHandled,publishScheduled;
    private boolean bound,binding,preparingService,ackExpected,finishScheduled;
    private long connectionGeneration,lastUiProgress;
    private Messenger service;
    private String outcomeMessage;
    private boolean outcomeCommitted,outcomePending,deferredFinish,deferredAck;
    private Bundle savedPicker;
    private PendingResult earlyPicker;
    // Worker-owned marker bytes: a hint, never a Store Job capability or output authority.
    private byte[] markerBytes;
    private final Messenger replies=new Messenger(new Handler(Looper.getMainLooper()) {
        @Override public void handleMessage(Message message) { workerReply(message); }
    });
    private static final class PendingResult {
        final int request,result;final Intent data;
        PendingResult(int q,int r,Intent d){request=q;result=r;data=d;}
    }
    private final ServiceConnection connection=new ServiceConnection() {
        @Override public void onServiceConnected(ComponentName name,IBinder binder) {
            if(!bound||finishScheduled||deferredFinish||phase==Phase.FINISHING)return;
            if(!name.getPackageName().equals(app.getPackageName())||!name.getClassName().equals(OriginalConversionService.class.getName())||!binder.isBinderAlive()) {
                connectionLost("转换服务身份或连接无效");return;
            }
            if(!isBusy()) { unbind();return; }
            service=new Messenger(binder);binding=false;
            if(phase!=Phase.COPYING) startWorker();
        }
        @Override public void onServiceDisconnected(ComponentName name) { connectionLost("转换进程已断开；未确认提交的任务仅保留partial"); }
        @Override public void onBindingDied(ComponentName name) { connectionLost("转换服务binding已失效；不会重跑旧job"); }
        @Override public void onNullBinding(ComponentName name) { connectionLost("转换服务没有可用Messenger"); }
    };

    private OriginalConversionController(Context context) throws IOException {
        app=context.getApplicationContext();noBackup=app.getNoBackupFilesDir().getCanonicalFile().toPath();
    }
    /** Call on main before prepared-resource checks. Retain Host strongly in Activity;
     * Host itself must hold Activity only weakly. The process singleton holds app state only.
     */
    public static OriginalConversionController obtain(Host host,Bundle saved) throws IOException {
        requireMain();
        if(host==null||!host.isAlive()) throw new IOException("No live original-conversion UI host");
        if(singleton==null) singleton=new OriginalConversionController(host.activity());
        singleton.attach(host,saved);return singleton;
    }
    public void attach(Host next,Bundle saved) {
        requireMain();if(next==null||!next.isAlive())return;
        Host previous=host.get();
        if(previous!=null&&previous!=next&&cancelCopyOnDetach(phase)) {
            detachedDuringCopy=true;cancelled.set(true);OriginalSourceBroker.Control c=sourceControl;if(c!=null)c.cancel();
        }
        host=new WeakReference<Host>(next);
        if(outcomePending) { deliverOutcome();return; }
        if(deferredFinish) { deferredFinish=false;scheduleFinish(outcomeCommitted,outcomeMessage,deferredAck);return; }
        if(isBusy()) {
            next.setBusy(true);next.status(statusForPhase());
            if(reconnectPhase(phase)&&service==null&&!binding&&job!=null) connect(true);
            if(phase==Phase.PUBLISHING&&!publishScheduled) publish();
            return;
        }
        if(restoreStarted) { next.setBusy(false);next.completed(false,"");return; }
        if(!next.canBegin()) { next.status("当前游戏或其它资源操作未结束，暂不恢复原版转换");return; }
        try { profile=next.profile(); }
        catch(IOException e) { next.setBusy(false);next.status("APK原版转换profile不可用："+message(e));next.completed(false,"原版profile不可用；只重新检查既有资源，不采用partial");return; }
        restoreStarted=true;phase=Phase.RESTORING;savedPicker=saved==null?null:new Bundle(saved);
        next.setBusy(true);next.status("检查原版转换状态…");
        final Host gate=next;
        io.execute(() -> restore(gate));
    }
    public boolean isBusy() { return phase!=Phase.IDLE; }
    public void saveState(Bundle out) {
        requireMain();out.putString(STATE_PREFIX+"phase",phase.name());out.putInt(STATE_PREFIX+"pickerKind",pickerKind);
        out.putBoolean(STATE_PREFIX+"pickerLaunched",pickerLaunched);
        OriginalJobStore.Job active=job;if(active!=null)out.putString(STATE_PREFIX+"jobId",active.id);
    }
    /** Prefer the identity-aware overload: an old Activity must not detach a newer host. */
    public void detach(Host expectedHost) { requireMain();if(host.get()==expectedHost)detach(); }
    /** Rotation does not cancel foreground conversion. A source-copy URI is never resumed. */
    public void detach() {
        requireMain();
        if(cancelCopyOnDetach(phase)) { detachedDuringCopy=true;cancelled.set(true);OriginalSourceBroker.Control c=sourceControl;if(c!=null)c.cancel(); }
        host.clear();
    }
    public void showStartDialog() {
        requireMain();Host h=liveHost();if(h==null)return;
        if(isBusy()) { h.status(statusForPhase());return; }
        if(!h.canBegin()) { h.status("请先结束游戏或其它资源操作，再开始原版转换");return; }
        try {
            OriginalProfile p=h.profile();admission(p);profile=p;
            String text="仅转换您有合法使用权的原版街机资源；不会运行原版main/ELF。\n\n"+
                "当前仅支持已钉住的main："+OriginalProfile.MAIN_LENGTH+" bytes / SHA256 "+OriginalProfile.MAIN_SHA256.substring(0,16)+"…\n"+
                "最低需2 GiB可用RAM，且设备不处于low-RAM/low-memory状态；完整Tokyo任务实测中间态约1.30 GiB，256 MiB启动门槛不足。\n"+
                "私有分区预留至少 "+gib(requiredSpace(p.sourceBytes,p.maxOutputBytes))+" GiB（来源×2 + 输出上限×2 +128 MiB，包含worker输出和发布副本；仅分区即时估算，实际ZIP可能更大）。\n"+
                "原版ZIP压缩文件最多8 GiB（来源只读复制，不解压执行）。\n手机整包可能耗时1–3小时，默认服务期限4小时。选定来源后可以返回桌面，允许通知即可查看转换进度。\n\n"+
                "仅生成新私有job；主进程验证并提交成功后才改变选择。旧资源/存档不作清理。请选择原版ZIP或目录。";
            new AlertDialog.Builder(h.activity()).setTitle("原版街机资源一键转换")
                .setMessage(text).setPositiveButton("我有使用权：选ZIP",(d,w)->choose(REQUEST_ZIP))
                .setNeutralButton("我有使用权：选目录",(d,w)->choose(REQUEST_TREE)).setNegativeButton("取消",null).show();
        } catch(Exception e) { h.status("暂不能开始原版转换："+message(e)+"；旧可用资源保留"); }
    }
    private void choose(int kind) {
        Host h=liveHost();if(h==null)return;
        if(isBusy()||!h.canBegin()) { h.status("当前资源操作状态已改变，请重新检查");return; }
        try { profile=h.profile();admission(profile); }
        catch(Exception e) { h.status("预检失败："+message(e)+"；旧资源/存档保留");return; }
        cancelled.set(false);committed=false;detachedDuringCopy=false;terminalHandled=false;publishScheduled=false;finishScheduled=false;ackOnly=false;ackExpected=false;
        pickerKind=kind;pickerLaunched=false;job=null;store=null;workerPid=0;phase=Phase.PICKER;
        h.setBusy(true);h.status("准备只读来源选择…");final Host gate=h;
        io.execute(() -> {
            try { gate.withInstallLock(() -> writeMarker(Phase.PICKER)); }
            catch(Exception e) { completeLocal(gate,false,"无法记录来源选择状态："+message(e));return; }
            main.post(() -> {
                Host current=liveHost();if(current==null||phase!=Phase.PICKER)return;
                Intent intent=new Intent(kind==REQUEST_ZIP?Intent.ACTION_OPEN_DOCUMENT:Intent.ACTION_OPEN_DOCUMENT_TREE);
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                if(kind==REQUEST_ZIP) { intent.addCategory(Intent.CATEGORY_OPENABLE);intent.setType("*/*");intent.putExtra(Intent.EXTRA_MIME_TYPES,new String[]{"application/zip","application/octet-stream","application/x-zip-compressed"}); }
                try { pickerLaunched=true;current.activity().startActivityForResult(intent,kind); }
                catch(RuntimeException e) { scheduleFinish(false,"无法打开来源选择器："+message(e),false); }
            });
        });
    }
    public boolean onActivityResult(int request,int result,Intent data) {
        requireMain();if(request!=REQUEST_ZIP&&request!=REQUEST_TREE)return false;
        if(phase==Phase.RESTORING) { earlyPicker=new PendingResult(request,result,data);return true; }
        if(phase!=Phase.PICKER||request!=pickerKind) return true; // stale original picker, never old request134
        pickerLaunched=false;
        if(result!=Activity.RESULT_OK||data==null||data.getData()==null) { scheduleFinish(false,"已取消来源选择；旧资源和存档保留",false);return true; }
        Uri uri=data.getData();
        if(!"content".equals(uri.getScheme())) { scheduleFinish(false,"来源必须是系统SAF的只读content URI",false);return true; }
        copy(uri,pickerKind);return true;
    }
    private void copy(Uri uri,int kind) {
        Host h=liveHost();if(h==null)return;phase=Phase.COPYING;h.setBusy(true);h.status("复制并验证原版来源到新私有job…");
        OriginalProfile p=profile;OriginalSourceBroker.Control control=new OriginalSourceBroker.Control();sourceControl=control;
        copyServiceError=null;
        // Start while the file picker returns to the launcher. Android may reject a new
        // foreground service if the user goes home during the source copy.
        connect(false);
        final Host gate=h;
        io.execute(() -> {
            try {
                gate.withInstallLock(() -> {
                    checkCancelled();admission(p);OriginalJobStore target=newStore(p);store=target;
                    OriginalJobStore.Job fresh=target.begin(cancelled::get,(s,n,t)->progress(s,n,t));job=fresh;
                    writeMarker(Phase.COPYING);checkCancelled();
                    if(kind==REQUEST_ZIP) OriginalSourceBroker.copyZip(app,uri,fresh.root,p,control,(s,n,t)->progress(s,n,t));
                    else OriginalSourceBroker.copyTree(app,uri,fresh.root,p,control,(s,n,t)->progress(s,n,t));
                    checkCancelled();target.sealSource(fresh,kind==REQUEST_ZIP?"zip":"tree");
                    writeMarker(Phase.SEALED);
                });
                sourceControl=null;
                main.post(() -> {
                    phase=Phase.SEALED;
                    if(cancelled.get()) {
                        scheduleFinish(false,copyServiceError!=null?copyServiceError:"来源复制后已取消；未启动转换，partial保留",false);return;
                    }
                    startWorker();
                });
            } catch(Exception e) {
                sourceControl=null;
                String failure=copyServiceError;
                if(failure==null) failure=cancelled.get()||detachedDuringCopy?"来源复制已取消/因界面重建停止；partial保留，请重新选择":"来源准备失败："+message(e);
                completeLocal(gate,false,failure+"；旧资源和存档保留");
            }
        });
    }
    public void cancel() {
        requireMain();
        if(committed) { status("资源选择已经提交；取消不会回滚，请重新检查可用资源");return; }
        if(!isBusy())return;
        cancelled.set(true);OriginalSourceBroker.Control control=sourceControl;if(control!=null)control.cancel();
        if(phase==Phase.PICKER) { scheduleFinish(false,"已取消来源选择；返回的过期选择结果将被忽略",false);return; }
        if(phase==Phase.COPYING) { status("正在关闭本次来源句柄并取消复制；不读取旧URI重试");return; }
        if(phase==Phase.PUBLISHING) { status("正在取消发布；若原子提交已完成，将保留已提交资源并重新检查");return; }
        phase=Phase.CANCELLING;status("正在等待转换进程合作取消/60秒self-watchdog…");
        try { if(service!=null)sendJob(OriginalConversionService.MSG_CANCEL); }
        catch(RemoteException e) { connectionLost("取消时转换连接已断开；partial保留"); }
    }
    private void connect(boolean recover) {
        if((recover&&job==null)||service!=null||binding)return;
        Host h=liveHost();if(h==null){phase=ackOnly?Phase.COMMIT_UNKNOWN:Phase.SEALED;return;}
        recoveryBind=recover;ackExpected=false;binding=true;
        if(recover) {
            phase=ackOnly?Phase.COMMIT_UNKNOWN:Phase.CONNECTING;
            h.setBusy(true);h.status("重连已存在的转换任务（不会重跑）…");
        }
        Intent intent=new Intent(app,OriginalConversionService.class).setAction(OriginalConversionService.ACTION_PREPARE);
        final long generation=++connectionGeneration;
        try {
            if(!recover) {
                app.startForegroundService(intent);
                preparingService=true;
            }
            bound=app.bindService(intent,connection,recover?0:Context.BIND_AUTO_CREATE);
            if(!bound) { binding=false;connectionLost(recover?"原转换服务已不存在；不会重新运行，partial保留":"无法绑定转换服务");return; }
            main.postDelayed(() -> { if(generation==connectionGeneration&&binding) connectionLost("转换服务连接超时；不自动重跑或采用partial"); },CONNECT_TIMEOUT_MS);
        } catch(RuntimeException e) { binding=false;connectionLost("转换服务启动/绑定失败："+message(e)); }
    }
    private void startWorker() {
        if(service==null || job==null)return;
        if(!ackOnly) phase=cancelled.get()?Phase.CANCELLING:Phase.RUNNING;
        try {
            Bundle data=new Bundle();data.putString(OriginalConversionService.KEY_JOB_ID,job.id);
            data.putString(OriginalConversionService.KEY_JOB_DIR,job.root.toString());
            // A reconnect deadline is deliberately invalid for a new worker.
            data.putLong(OriginalConversionService.KEY_DEADLINE,startDeadline(recoveryBind,SystemClock.elapsedRealtime()));
            send(OriginalConversionService.MSG_START,data);
            preparingService=false;
            if(cancelled.get()) sendJob(OriginalConversionService.MSG_CANCEL);
        } catch(Exception e) { connectionLost("无法发送转换任务："+message(e)); }
    }
    private void send(int what,Bundle data) throws RemoteException {
        Messenger target=service;if(target==null)throw new RemoteException("No conversion Messenger");
        Message m=Message.obtain(null,what);m.setData(data);m.replyTo=replies;target.send(m);
    }
    private void sendJob(int what) throws RemoteException {
        OriginalJobStore.Job active=job;if(active==null)return;
        Bundle data=new Bundle();data.putString(OriginalConversionService.KEY_JOB_ID,active.id);if(workerPid>0)data.putInt(OriginalConversionService.KEY_PID,workerPid);send(what,data);
    }
    private void workerReply(Message message) {
        requireMain();OriginalJobStore.Job active=job;if(active==null||!isBusy()||ackExpected)return;
        try {
            Bundle data=message.getData();data.setClassLoader(OriginalConversionController.class.getClassLoader());
            String id=data.getString(OriginalConversionService.KEY_JOB_ID);int pid=data.getInt(OriginalConversionService.KEY_PID,0);
            if(!validReply(active.id,id,workerPid,pid,message.what,message.sendingUid,Process.myUid(),Process.myPid()))return;
            if(service==null||message.replyTo==null||!service.getBinder().equals(message.replyTo.getBinder()))return;
            workerPid=pid;binding=false;
            if(message.what==OriginalConversionService.MSG_PROGRESS) {
                if(ackOnly) { cancelled.set(true);sendJob(OriginalConversionService.MSG_CANCEL);status("上次提交结果不确定；停止不一致worker后重新校验");return; }
                if(phase!=Phase.PUBLISHING) phase=cancelled.get()?Phase.CANCELLING:Phase.RUNNING;
                progress(data.getString(OriginalConversionService.KEY_STAGE,"convert"),data.getLong(OriginalConversionService.KEY_DONE,0),data.getLong(OriginalConversionService.KEY_TOTAL,0));return;
            }
            if(terminalHandled) {
                if(message.what==OriginalConversionService.MSG_FAILED&&phase==Phase.PUBLISHING&&publishScheduled) {
                    if(!committed)cancelled.set(true);
                    status(committed?"资源已提交；worker后续停止，不会回滚":"worker在发布期间停止；等待事务确认，不能声称已回滚");
                }
                return;
            }
            terminalHandled=true;
            if(ackOnly) { scheduleFinish(false,"上次发布过程被中断，提交结果未知；可能已提交，请重新检查（不会重发或回滚）",true);return; }
            if(message.what==OriginalConversionService.MSG_FAILED) {
                String code=data.getString(OriginalConversionService.KEY_ERROR_CODE,"ENGINE_FAILED");
                scheduleFinish(false,"转换未提交："+bounded(code,120)+" / "+bounded(data.getString(OriginalConversionService.KEY_ERROR_MESSAGE,"worker stopped"),1200)+"；partial保留",true);
            } else {
                // reportPath/reportJson deliberately not read: only Store's fixed private completion is authority.
                if(cancelled.get())scheduleFinish(false,"已取消，转换candidate不发布；partial保留",true);
                else { phase=Phase.PUBLISHING;publish(); }
            }
        } catch(Exception e) { connectionLost("转换协议无效："+message(e)); }
    }
    private void publish() {
        if(publishScheduled||job==null)return;
        Host h=liveHost();if(h==null) { phase=Phase.PUBLISHING;return; }
        publishScheduled=true;phase=Phase.PUBLISHING;h.setBusy(true);h.status("主进程独立验证完整输出并提交选择…");
        final Host gate=h;final OriginalJobStore target=store;final OriginalJobStore.Job active=job;
        io.execute(() -> {
            final String[] warnings={""};
            String note="原版资源已提交，请重新检查可用资源；不会自动开始游戏";
            try {
                gate.withInstallLock(() -> {
                    checkCancelled();writeMarker(Phase.PUBLISHING);
                    OriginalJobStore.Ready ready=target.publish(active,cancelled::get,(s,n,t)->progress(s,n,t));
                    committed=true; // Before any further callback/marker I/O/cancellation: never misreport rollback.
                    if(!ready.warnings.isEmpty())warnings[0]="；"+bounded(ready.warnings.toString(),1800);
                    // Keep PUBLISHING marker until ACK has been sent: main-process death
                    // must not orphan a terminal worker or cause an automatic republish.
                });
            } catch(Exception e) {
                if(committed)note="资源选择已提交，后续状态同步异常："+message(e)+"；请重新检查，不会回滚";
                else note=(cancelled.get()?"发布已取消，未确认提交":"发布校验失败："+message(e))+"；partial保留，旧资源/存档不清理";
            }
            final String text=note+warnings[0];
            main.post(() -> scheduleFinish(committed,text,true));
        });
    }
    private void connectionLost(String reason) {
        requireMain();service=null;binding=false;++connectionGeneration;
        if(ackExpected){unbind();return;}
        if(phase==Phase.COPYING) {
            copyServiceError=reason;
            cancelled.set(true);
            OriginalSourceBroker.Control control=sourceControl;
            if(control!=null) control.cancel();
            unbind();status(reason);return;
        }
        if(!isBusy()||job==null){unbind();return;}
        if(committed&&phase!=Phase.PUBLISHING) {
            unbind();scheduleFinish(true,"资源选择已经提交，worker连接已结束；请重新检查可用资源，不会回滚",false);return;
        }
        if(phase==Phase.PUBLISHING&&publishScheduled) {
            if(!committed)cancelled.set(true);
            status(committed?"资源已经提交，worker连接已结束；重新检查可用资源":reason+"；正在等待发布事务确认，不能声称已回滚");
            unbind();return;
        }
        cancelled.set(true);unbind();
        scheduleFinish(false,ackOnly?"上次提交结果未知且服务已结束；请重新核验（不会重发/回滚）":reason,false);
    }
    private void scheduleFinish(boolean success,String text,boolean ack) {
        requireMain();if(finishScheduled)return;
        Host h=liveHost();
        if(h==null) { outcomeMessage=text;outcomeCommitted=success;deferredAck=ack;deferredFinish=true;phase=Phase.FINISHING;return; }
        h.setBusy(true);finishScheduled=true;phase=Phase.FINISHING;final Host gate=h;
        String acknowledged=text;
        if(ack&&service!=null&&job!=null) {
            try { ackExpected=true;sendJob(OriginalConversionService.MSG_RESULT_ACK); }
            catch(RemoteException e) { acknowledged+="；worker ACK连接已结束"; }
        }
        final String afterAck=acknowledged;
        io.execute(() -> {
            String note=afterAck;
            try { gate.withInstallLock(this::clearMarker); }
            catch(Exception e) { note += "；私有UI记录未清理，后续需核验："+message(e); }
            final String end=note;
            main.post(() -> finish(committedOutcome(success,committed),end,false));
        });
    }
    private void completeLocal(Host gate,boolean success,String text) {
        String note=text;
        try { gate.withInstallLock(this::clearMarker); }
        catch(Exception e) { note+="；UI状态记录保留："+message(e); }
        final String end=note;main.post(() -> finish(committedOutcome(success,committed),end,false));
    }
    private void finish(boolean success,String text,boolean ack) {
        requireMain();
        if(ack&&service!=null&&job!=null) {
            try { ackExpected=true;sendJob(OriginalConversionService.MSG_RESULT_ACK); }
            catch(RemoteException e) { text+="；worker ACK连接已结束"; }
        }
        unbind();phase=Phase.IDLE;sourceControl=null;pickerKind=0;pickerLaunched=false;job=null;store=null;publishScheduled=false;finishScheduled=false;
        outcomeCommitted=success;outcomeMessage=text;outcomePending=true;deliverOutcome();
    }
    private void deliverOutcome() {
        Host h=liveHost();if(h==null)return;
        outcomePending=false;h.setBusy(false);h.status(outcomeMessage==null?"":outcomeMessage);h.completed(outcomeCommitted,outcomeMessage==null?"":outcomeMessage);
    }
    private void unbind() {
        ++connectionGeneration;service=null;binding=false;
        if(preparingService) {
            preparingService=false;
            app.stopService(new Intent(app,OriginalConversionService.class));
        }
        if(bound){bound=false;try{app.unbindService(connection);}catch(IllegalArgumentException ignored){}}
    }
    private void restore(Host gate) {
        try {
            final Marker[] found=new Marker[1];
            gate.withInstallLock(() -> {
                Marker m=readMarker();found[0]=m;
                if(m!=null&&!m.profile.equals(profile.sha256))throw new IOException("UI记录与APK profile不匹配；不采用旧job");
                if(m!=null&&m.job!=null) { store=newStore(profile);job=store.loadJob(UUID.fromString(m.job)); }
            });
            Marker m=found[0];
            main.post(() -> {
                if(m==null){phase=Phase.IDLE;Host h=liveHost();if(h!=null){h.setBusy(false);h.completed(false,"");}return;}
                pickerKind=m.kind;
                if(m.phase==Phase.PICKER && savedPicker!=null && savedPicker.getInt(STATE_PREFIX+"pickerKind",0)==m.kind && savedPicker.getBoolean(STATE_PREFIX+"pickerLaunched",false)) {
                    phase=Phase.PICKER;pickerLaunched=true;status("等待本次原版来源选择结果…");
                    PendingResult early=earlyPicker;earlyPicker=null;if(early!=null)onActivityResult(early.request,early.result,early.data);return;
                }
                if(m.phase==Phase.COPYING||m.phase==Phase.PICKER) {
                    scheduleFinish(false,"上次来源选择/复制已中断；只保留partial，请重新选择，不会自动读取过期URI",false);return;
                }
                ackOnly=recoveryNeedsNoRepublish(m.phase);
                if(m.phase==Phase.CANCELLING)cancelled.set(true);
                phase=ackOnly?Phase.COMMIT_UNKNOWN:Phase.SEALED;
                connect(true);
            });
        } catch(Exception e) {
            main.post(() -> {phase=Phase.IDLE;status("原版任务恢复失败，记录/partial保留："+message(e));Host h=liveHost();if(h!=null){h.setBusy(false);h.completed(false,"原版任务恢复失败，需检查记录；未采用未知输出："+message(e));}});
        }
    }
    private OriginalJobStore newStore(OriginalProfile p) throws IOException {
        File external=app.getExternalFilesDir(null);if(external==null)throw new IOException("应用外置分区不可用");
        return new OriginalJobStore(external.getCanonicalFile().toPath(),noBackup,p);
    }
    private void admission(OriginalProfile p) throws IOException {
        ActivityManager manager=(ActivityManager)app.getSystemService(Context.ACTIVITY_SERVICE);
        if(manager==null)throw new IOException("无法读取内存状态");
        ActivityManager.MemoryInfo info=new ActivityManager.MemoryInfo();manager.getMemoryInfo(info);
        if(manager.isLowRamDevice()||info.lowMemory||info.availMem<MIN_AVAILABLE_MEMORY)throw new IOException("完整任务至少需要2 GiB可用RAM且不能是low-RAM/low-memory");
        long required=requiredSpace(p.sourceBytes,p.maxOutputBytes),available=noBackup.toFile().getUsableSpace();
        if(available<required)throw new IOException("私有分区空间不足：需 "+gib(required)+" GiB，可用 "+gib(available)+" GiB");
    }
    static long requiredSpace(long sourceBytes,long outputBytes) throws IOException {
        if(sourceBytes<0||outputBytes<0)throw new IOException("Invalid profile byte budget");
        try{return Math.addExact(Math.addExact(Math.multiplyExact(sourceBytes,2L),Math.multiplyExact(outputBytes,2L)),DISK_RESERVE);}
        catch(ArithmeticException e){throw new IOException("Profile byte budget overflow",e);}
    }
    static boolean committedOutcome(boolean success,boolean didCommit){return success||didCommit;}
    static boolean cancelCopyOnDetach(Phase p){return p==Phase.COPYING;}
    static boolean reconnectPhase(Phase p){return p==Phase.RUNNING||p==Phase.SEALED||p==Phase.CONNECTING||p==Phase.CANCELLING;}
    static boolean recoveryNeedsNoRepublish(Phase p){return p==Phase.PUBLISHING||p==Phase.COMMIT_UNKNOWN;}
    static long startDeadline(boolean reconnect,long now) { return reconnect?0L:now+OriginalConversionService.DEFAULT_DURATION_MS; }
    static boolean validReply(String expected,String actual,int knownPid,int pid,int what,int senderUid,int ownUid,int uiPid) {
        return expected!=null&&expected.equals(actual)&&pid>1&&pid!=uiPid&&(knownPid==0||knownPid==pid)&&senderUid==ownUid&&
            (what==OriginalConversionService.MSG_PROGRESS||what==OriginalConversionService.MSG_FINISHED||what==OriginalConversionService.MSG_FAILED);
    }
    private static String gib(long bytes){return String.format(Locale.ROOT,"%.2f",bytes/(1024.0*1024*1024));}
    private void checkCancelled() throws IOException {if(cancelled.get()||Thread.currentThread().isInterrupted())throw new IOException("Cancelled");}
    private void progress(String stage,long done,long total) {
        long now=SystemClock.elapsedRealtime();synchronized(this){if(now-lastUiProgress<250L)return;lastUiProgress=now;}
        final String text=bounded(stage==null?"convert":stage,160)+"  "+Math.max(0,done)+(total>0?" / "+total:"");
        Phase reported=phase;
        main.post(() -> {
            if(phase==Phase.IDLE||phase==Phase.FINISHING)return;
            Host h=liveHost();if(h!=null)h.status(text);
            if(phase!=reported||service==null||(phase!=Phase.COPYING&&phase!=Phase.PUBLISHING))return;
            Bundle data=new Bundle();
            if(phase==Phase.PUBLISHING && job!=null) data.putString(OriginalConversionService.KEY_JOB_ID,job.id);
            data.putString(OriginalConversionService.KEY_STAGE,stage);
            data.putLong(OriginalConversionService.KEY_DONE,done);
            data.putLong(OriginalConversionService.KEY_TOTAL,total);
            try { send(OriginalConversionService.MSG_HOST_PROGRESS,data); }
            catch(RemoteException e) { connectionLost("转换通知连接已断开"); }
        });
    }
    private Host liveHost(){Host h=host.get();return h!=null&&h.isAlive()?h:null;}
    private void status(String text){main.post(()->{Host h=liveHost();if(h!=null)h.status(text);});}
    private String statusForPhase(){return phase==Phase.COPYING?"正在准备来源；界面重建将取消这次复制":phase==Phase.PUBLISHING?"主进程正在独立验证/发布，尚不能开始游戏":phase==Phase.CANCELLING?"正在等待取消终端结果":phase==Phase.PICKER?"等待原版来源选择…":"原版转换任务进行中/等待重连…";}
    private static String bounded(String text,int max){if(text==null)return "";String s=text.replace('\0',' ').replace('\r',' ').replace('\n',' ');return s.length()<=max?s:s.substring(0,max);}
    private static String message(Throwable e){return bounded(e.getMessage()==null?e.toString():e.getMessage(),1400);}
    private static void requireMain(){if(Looper.myLooper()!=Looper.getMainLooper())throw new IllegalStateException("Controller lifecycle/UI methods require main thread");}

    private static final class Marker {
        final Phase phase;final int kind;final String job,profile;
        Marker(Phase p,int k,String j,String h){phase=p;kind=k;job=j;profile=h;}
    }
    private Path uiRoot(boolean create) throws IOException {
        Path root=noBackup.resolve("original-convert-ui-v1");
        if(!root.toFile().getCanonicalFile().toPath().equals(root)||Files.isSymbolicLink(root))throw new IOException("Unsafe original UI state root");
        if(!Files.exists(root,LinkOption.NOFOLLOW_LINKS)&&create)Files.createDirectory(root);
        if(Files.exists(root,LinkOption.NOFOLLOW_LINKS)&&!Files.isDirectory(root,LinkOption.NOFOLLOW_LINKS))throw new IOException("Original UI state root is not a directory");
        return root;
    }
    private byte[] small(Path file) throws IOException {
        if(Files.isSymbolicLink(file)||!Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS)||Files.size(file)>4096)throw new IOException("Invalid private UI marker");
        try(FileChannel channel=FileChannel.open(file,StandardOpenOption.READ,LinkOption.NOFOLLOW_LINKS)) {
            ByteBuffer b=ByteBuffer.allocate(4097);while(b.hasRemaining()&&channel.read(b)>=0){}if(b.position()>4096)throw new IOException("UI marker too large");return Arrays.copyOf(b.array(),b.position());
        }
    }
    private Marker readMarker() throws IOException {
        Path file=uiRoot(false).resolve("state.tsv");
        if(!Files.exists(file,LinkOption.NOFOLLOW_LINKS)){markerBytes=null;return null;}
        byte[] bytes=small(file);Marker parsed=decodeMarker(bytes,app.getPackageName());markerBytes=bytes;return parsed;
    }
    private static Marker decodeMarker(byte[] bytes,String packageName) throws IOException {
        if(bytes==null||bytes.length>4096)throw new IOException("UI marker size");
        String text;
        try{text=StandardCharsets.UTF_8.newDecoder().onMalformedInput(java.nio.charset.CodingErrorAction.REPORT).onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();}
        catch(java.nio.charset.CharacterCodingException e){throw new IOException("UI marker UTF-8",e);}
        String[] f=text.split("\n",-1);
        if(f.length!=8||!f[0].equals("WMMT-ORIGINAL-UI-1")||!f[1].equals("package\t"+packageName)||!f[6].equals("END")||!f[7].isEmpty())throw new IOException("Unknown UI marker; not overwritten");
        try {
            if(!f[2].startsWith("phase\t")||!f[3].startsWith("kind\t")||!f[4].startsWith("job\t")||!f[5].startsWith("profile\t"))throw new IOException("Invalid UI marker fields");
            Phase p=Phase.valueOf(f[2].substring(6));int kind=Integer.parseInt(f[3].substring(5));String j=f[4].substring(4),hash=f[5].substring(8);
            if(!(p==Phase.PICKER||p==Phase.COPYING||p==Phase.SEALED||p==Phase.RUNNING||p==Phase.CANCELLING||p==Phase.PUBLISHING||p==Phase.COMMIT_UNKNOWN)||
                    (kind!=REQUEST_ZIP&&kind!=REQUEST_TREE)||!f[3].substring(5).equals(Integer.toString(kind))||(!j.equals("-")&&!j.matches(UUID_RE))||!hash.matches("[0-9a-f]{64}")||
                    (p==Phase.PICKER?!j.equals("-"):j.equals("-")))throw new IOException("Invalid UI marker state");
            return new Marker(p,kind,j.equals("-")?null:j,hash);
        }catch(IllegalArgumentException e){throw new IOException("Invalid UI marker enum/number",e);}
    }
    private void writeMarker(Phase state) throws IOException {
        Path root=uiRoot(true),target=root.resolve("state.tsv");
        if(Files.exists(target,LinkOption.NOFOLLOW_LINKS)) {
            byte[] before=small(target);if(markerBytes==null||!Arrays.equals(before,markerBytes))throw new IOException("UI marker changed; not overwritten");
        } else if(markerBytes!=null)throw new IOException("UI marker unexpectedly disappeared");
        OriginalJobStore.Job active=job;
        String value="WMMT-ORIGINAL-UI-1\npackage\t"+app.getPackageName()+"\nphase\t"+state.name()+"\nkind\t"+pickerKind+"\njob\t"+(active==null?"-":active.id)+"\nprofile\t"+profile.sha256+"\nEND\n";
        byte[] bytes=value.getBytes(StandardCharsets.UTF_8);Path temp=root.resolve("state-"+UUID.randomUUID()+".tmp");
        try(FileChannel channel=FileChannel.open(temp,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS)) {
            ByteBuffer b=ByteBuffer.wrap(bytes);while(b.hasRemaining())channel.write(b);channel.force(true);
        }
        Files.move(temp,target,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);sync(root);sync(noBackup);markerBytes=bytes;
    }
    private void clearMarker() throws IOException {
        Path root=uiRoot(false),file=root.resolve("state.tsv");
        if(!Files.exists(file,LinkOption.NOFOLLOW_LINKS)){markerBytes=null;return;}
        byte[] current=small(file);
        if(markerBytes==null||!Arrays.equals(current,markerBytes))throw new IOException("Private UI marker changed; not deleted");
        if(!file.getParent().equals(root)||!file.toFile().getCanonicalFile().toPath().equals(file))throw new IOException("Unsafe UI marker deletion target");
        Files.delete(file);sync(root);markerBytes=null;
    }
    private static void sync(Path dir) throws IOException {try(FileChannel channel=FileChannel.open(dir,StandardOpenOption.READ)){channel.force(true);}}
}
