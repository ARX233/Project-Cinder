package com.wmmt.port;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.Context;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.hardware.display.DisplayManager;
import android.view.Display;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.media.MediaPlayer;
import android.os.Build;
import android.os.Bundle;
import android.view.MotionEvent;
import android.view.Surface;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.VideoView;
import android.widget.TextView;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.IOException;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/* The Android side of the port, as main.m is the iOS one: the game draws on a SurfaceView
 * from its own thread (src/main_android.c), the attract movies play in a VideoView over it,
 * the BGM through the audio queue; touches, the gravity for
 * steering by tilt and the lifecycle go down to the native side. */
public class MainActivity extends Activity implements SurfaceHolder.Callback, SensorEventListener, DisplayManager.DisplayListener {
  static { System.loadLibrary("wmmt"); }

  static native boolean nativeStart(MainActivity a, String dataDir, String saveDir, String sidecarDir,
      String cutin, String cardPages, String backfireWpk, String backfireBfx, String ghostUi, String builtinGhosts,
      String frontHaloWpk, String frontHaloAnchors, String taStoreDir, String ghostCrownDir);
  static native void nativeSurface(Surface s, int w, int h);
  static native void nativeTouch(int id, int phase, float x, float y);
  static native void nativePause(boolean p);
  static native void nativeTilt(float radians);
  static native boolean nativeWantsTilt();
  static native void nativeMovieDone(MainActivity owner, long token, boolean pressStart);
  static native void nativePressStart();
  static native void nativeMemoryWarning();
  static native void nativeBgmFailure(MainActivity owner, int group);
  static native void nativeRefreshRate(MainActivity owner, float hz);
  static native int nativeFrameRateLimit();

  private static volatile MainActivity currentActivity;
  private boolean installReady;
  private String saveDir;
  private static volatile GhostCloud ghostCloud;
  private static CloudDevice cloudDevice;
  private static volatile String resolvedVsAddress;
  private static long vsResolveAt;
  private static boolean vsResolving;
  private FrameLayout root;
  private SurfaceView game;
  private VideoView movie;
  private long movieToken; /* UI thread: identity of the attached view (or pending failure). */
  private volatile long movieRequest; /* newest native request, published before posting. */
  private MediaPlayer bgm; /* fallback for an unavailable PCM path */
  private ArcadeBgm arcadeBgm, pendingArcadeBgm;
  private float bgmVolume = 1.0f; /* legacy Android player default */
  private String dataDir;
  private File cardResources;
  private DisplayManager displays;
  private SensorManager sensors;
  private Sensor gravity;
  private TextView progress;
  private volatile boolean started, destroyed;
  private boolean resumed, bgmPreparing;
  /* Fail closed until this Activity receives the game thread's first snapshot. */
  private volatile boolean bgmGameplayPaused = true;
  private long bgmPauseRevision; /* guarded by this */
  private volatile long bgmGeneration;
  private ExecutorService bgmExecutor;
  private int surfaceWidth, surfaceHeight;
  private static final Object INSTALL_LOCK = new Object();
  /* Held until process exit: another cooperating process must not install while native runs. */
  private static DataCoordinator.ProcessLock processInstallLock;
  private static String nativeDataDir;
  private static File nativeCardResources;
  private static String[] nativeOptionalFiles;
  private static boolean resourceClearing; // Main thread, shared across Activity recreation.
  private static final int REQUEST_RESOURCE_IMPORT = 134;
  private static final int REQUEST_CONVERSION_NOTIFICATIONS = 135;
  private FrameLayout dataPanel;
  private LauncherWallpaperView launcherWallpaper;
  private Button beginButton, importButton, checkButton, cancelButton, clearButton;
  private volatile boolean resourceBusy, resourceCancelled;
  private volatile android.os.CancellationSignal resourceOpenSignal;
  private volatile java.io.Closeable resourceSource;
  private boolean awaitingResourcePicker;
  private Uri pendingResourceImport;
  private volatile String resourceNotice;
  private ResolvedResources preparedResources;
  private OriginalConversionController originalController;
  private OriginalHost originalHost;
  private Button originalButton;
  private String pendingOriginalNotice;

  private static final class OriginalHost implements OriginalConversionController.Host {
    private final java.lang.ref.WeakReference<MainActivity> owner;
    private final Context app;
    OriginalHost(MainActivity activity) { owner=new java.lang.ref.WeakReference<MainActivity>(activity); app=activity.getApplicationContext(); }
    public Activity activity() { return owner.get(); }
    private MainActivity live() {
      MainActivity a=owner.get();
      return a!=null && !a.destroyed && !a.isFinishing() && currentActivity==a ? a : null;
    }
    public boolean canBegin() {
      MainActivity a=live();
      return a!=null && !a.started && nativeDataDir==null && !resourceClearing && !a.resourceBusy && !a.awaitingResourcePicker;
    }
    public OriginalProfile profile() throws IOException { return originalProfile(app); }
    public void withInstallLock(OriginalConversionController.Work work) throws Exception {
      synchronized (INSTALL_LOCK) { lockInstallProcess(app); work.run(); }
    }
    public void setBusy(boolean busy) {
      MainActivity a=live(); if(a==null) return;
      a.resourceBusy=busy; if(busy) a.resourceCancelled=false; a.resourceControls();
    }
    public void status(String text) { MainActivity a=live(); if(a!=null && a.progress!=null) a.progress.setText(text); }
    public void completed(boolean committed,String text) {
      MainActivity a=live(); if(a==null || a.started || nativeDataDir!=null) return;
      a.resourceBusy=false; a.resourceCancelled=false;
      a.pendingOriginalNotice=text==null || text.isEmpty()?null:text;
      if(a.awaitingResourcePicker) { a.progress.setText("正在等待原有资源文件选择结果…"); a.resourceControls(); }
      else if(!a.startQueuedImport()) a.prepareResources(null);
    }
  }

  /* No arbitrary-path Ready constructor: both adapters require a capability
   * minted by one of the independent, fully verified resource stores. */
  private static final class ResolvedResources {
    final java.nio.file.Path dataDirectory, cardDirectory;
    final java.util.List<String> warnings;
    final java.util.Map<String,java.nio.file.Path> optionalFiles;
    ResolvedResources(ResourceStore.Ready ready) {
      dataDirectory=ready.dataDirectory; cardDirectory=ready.cardDirectory;
      optionalFiles=ready.optionalFiles;
      java.util.List<String> messages=new java.util.ArrayList<String>(ready.warnings);
      if (!java.nio.file.Files.isRegularFile(dataDirectory.resolve("sound/rx7_rev1.wav"), java.nio.file.LinkOption.NOFOLLOW_LINKS))
        messages.add("所选资源缺少 RX-7／RX-8 原版高转蜂鸣音效。可通过“原版 ZIP / 目录一键转换”补齐。");
      warnings=java.util.Collections.unmodifiableList(messages);
    }
    ResolvedResources(OriginalJobStore.Ready ready) {
      dataDirectory=ready.dataDirectory; cardDirectory=null;
      java.util.List<String> messages=new java.util.ArrayList<String>(ready.warnings);
      messages.add("已使用原版本地转换资源；额外卡片/附加演出不从未校验文件回退。");
      warnings=java.util.Collections.unmodifiableList(messages);
      optionalFiles=java.util.Collections.emptyMap();
    }
    ResolvedResources(ResolvedResources base, ResourceStore.VerifiedOptional uiCapability,
        ResourceStore.VerifiedOptional datasetCapability) {
      dataDirectory=base.dataDirectory; cardDirectory=base.cardDirectory; warnings=base.warnings;
      java.util.Map<String,java.nio.file.Path> files=new java.util.TreeMap<String,java.nio.file.Path>(base.optionalFiles);
      // Neither new bank inherits imported/external or revoked cache paths.
      files.remove(ResourceMetadata.GHOST_UI_PATH);
      files.remove(ResourceMetadata.BUILTIN_GHOSTS_PATH);
      java.nio.file.Path ghost=uiCapability==null?null:uiCapability.verifiedPath(ResourceMetadata.GHOST_UI_PATH);
      java.nio.file.Path dataset=datasetCapability==null?null:datasetCapability.verifiedPath(ResourceMetadata.BUILTIN_GHOSTS_PATH);
      if(ghost!=null) files.put(ResourceMetadata.GHOST_UI_PATH,ghost);
      if(dataset!=null) files.put(ResourceMetadata.BUILTIN_GHOSTS_PATH,dataset);
      optionalFiles=java.util.Collections.unmodifiableMap(files);
    }
  }

  // Merge only a Store-minted capability into either original or legacy readiness.
  private ResolvedResources withGhosts(ResolvedResources base, ResourceStore.VerifiedOptional uiCapability,
      ResourceStore.VerifiedOptional datasetCapability) {
    return new ResolvedResources(base, uiCapability, datasetCapability);
  }

  private static OriginalProfile originalProfile(Context app) throws IOException {
    try (InputStream input=app.getAssets().open(OriginalProfilePin.ASSET)) {
      return OriginalProfile.read(input,OriginalProfilePin.SHA256);
    }
  }
  private long lastResourceProgress;

  private String resourcePath(String name) {
    java.nio.file.Path p = preparedResources == null ? null : preparedResources.optionalFiles.get(name);
    return p == null ? null : p.toFile().getAbsolutePath();
  }

  private static void lockInstallProcess(Context app) throws IOException {
    if (processInstallLock != null && processInstallLock.valid()) return;
    processInstallLock = DataCoordinator.acquire(new File(app.getFilesDir(), "game-data-install.lock").toPath());
  }
  private void lockInstallProcess() throws IOException { lockInstallProcess(getApplicationContext()); }
  private static final String ASSET = "re3dxplus-data.zip";
  private static final String BASELINES_ASSET = "data-baselines.zip";
  private static final String MARKER = ".re3dxplus-install-v1";
  private static final String CUTIN_ASSET = "story-cutin.bin";
  private static final long CUTIN_LIMIT = 256L * 1024 * 1024;

  @Override protected void onCreate(Bundle b) {
    super.onCreate(b);
    if (ghostCloud == null) loadGhostCloud();
    onlineVsAddress();
    currentActivity = this;
    if (b != null) {
      awaitingResourcePicker = b.getBoolean("resource-picker-pending", false);
      pendingResourceImport = b.getParcelable("resource-import-uri");
    }
    getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON | WindowManager.LayoutParams.FLAG_FULLSCREEN);
    if (android.os.Build.VERSION.SDK_INT >= 28)
      getWindow().getAttributes().layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
    root = new FrameLayout(this);
    game = new SurfaceView(this);
    game.getHolder().addCallback(this);
    game.setOnTouchListener((v, e) -> { touch(e); return true; });
    root.addView(game);
    setContentView(root);
    hideBars();
    launcherWallpaper = new LauncherWallpaperView(this);
    dataPanel = launcherWallpaper;
    progress = launcherWallpaper.statusText;
    beginButton = launcherWallpaper.launchButton;
    importButton = launcherWallpaper.selectButton;
    originalButton = launcherWallpaper.originalActionButton;
    checkButton = launcherWallpaper.recheckActionButton;
    cancelButton = launcherWallpaper.cancelButton;
    clearButton = launcherWallpaper.clearButton;
    beginButton.setOnClickListener(v -> startGame());
    importButton.setOnClickListener(v -> showResourceSelection());
    originalButton.setOnClickListener(v -> requestOriginalConversion());
    checkButton.setOnClickListener(v -> requestResourceRecheck());
    clearButton.setOnClickListener(v -> confirmResourceClear());
    cancelButton.setOnClickListener(v -> {
      if(originalController!=null && originalController.isBusy()) {
        originalController.cancel(); cancelButton.setEnabled(false); return;
      }
      cancelResourceOperation();
      cancelButton.setEnabled(false);
      progress.setText("正在安全取消，等待文件提供方返回。未提交的新选择不会启用；如正在恢复旧版事务，可用同一来源继续完成。存档保留，不会自动启动游戏。");
    });
    resourceControls();
    root.addView(dataPanel, new FrameLayout.LayoutParams(-1, -1));
    displays = (DisplayManager) getSystemService(DISPLAY_SERVICE);
    sensors = (SensorManager) getSystemService(SENSOR_SERVICE);
    gravity = sensors == null ? null : sensors.getDefaultSensor(Sensor.TYPE_GRAVITY);
    if (nativeDataDir != null) {
      dataDir = nativeDataDir;
      cardResources = nativeCardResources;
      File ext = getExternalFilesDir(null);
      if (ext == null) { installError("External app storage is unavailable."); return; }
      saveDir = new File(ext, "wmmt").getAbsolutePath();
      installReady = true;
      startGame(); // Reattach only; never import while this process's native game is running.
    } else {
      originalHost = new OriginalHost(this);
      try { originalController = OriginalConversionController.obtain(originalHost, b); }
      catch (IOException failure) { installError("转换任务控制状态暂不可用："+failure.getMessage()+"。未改动资源选择，请关闭后重试。"); }
      // Controller.completed owns initial resolve after private-marker recovery.
      // Never race a second legacy scan against restored foreground conversion.
    }
  }

  /* Each new record store uses its own trusted internal directory.
   * Legacy garage/PB/saveDir stay where they already are. */
  private String privateRecordDirectory(String store) {
    try {
      File requested = getDir(store, Context.MODE_PRIVATE);
      java.nio.file.Path leaf = requested.toPath();
      if (java.nio.file.Files.isSymbolicLink(leaf) ||
          !java.nio.file.Files.isDirectory(leaf, java.nio.file.LinkOption.NOFOLLOW_LINKS))
        throw new IOException("Record store is not a no-follow directory");
      /* Resolve Android's trusted /data/user/0 alias before native component-wise
       * O_NOFOLLOW traversal; never allow a caller-selected/uploaded directory. */
      File canonical = requested.getCanonicalFile();
      java.nio.file.Path path = canonical.toPath();
      if (java.nio.file.Files.isSymbolicLink(path) ||
          !java.nio.file.Files.isDirectory(path, java.nio.file.LinkOption.NOFOLLOW_LINKS))
        throw new IOException("Canonical record store is not a directory");
      java.io.FileDescriptor fd = android.system.Os.open(canonical.getPath(),
          android.system.OsConstants.O_RDONLY | android.system.OsConstants.O_NONBLOCK |
          android.system.OsConstants.O_NOFOLLOW | android.system.OsConstants.O_CLOEXEC, 0);
      try {
        android.system.StructStat identity = android.system.Os.fstat(fd);
        if (!android.system.OsConstants.S_ISDIR(identity.st_mode) ||
            identity.st_uid != android.os.Process.myUid())
          throw new IOException("Record store ownership is unsafe");
        // Android getDir can create the app-owned directory with mode 0771.
        if ((identity.st_mode & 0022) != 0) android.system.Os.fchmod(fd, 0700);
        if ((android.system.Os.fstat(fd).st_mode & 0022) != 0)
          throw new IOException("Record store permissions are unsafe");
        return canonical.getPath();
      } finally {
        android.system.Os.close(fd);
      }
    } catch (IOException | android.system.ErrnoException | RuntimeException storageFailure) {
      android.util.Log.w("WMMT", "Private record storage unavailable for " + store, storageFailure);
      return null;
    }
  }

  private void startGame() {
    if (!installReady || resourceClearing || resourceBusy || awaitingResourcePicker || started || destroyed || currentActivity != this || isFinishing() || (originalController!=null && originalController.isBusy())) return;
    synchronized (INSTALL_LOCK) {
      boolean first = nativeDataDir == null;
      String selectedData = first ? dataDir : nativeDataDir;
      File selectedCard = first ? cardResources : nativeCardResources;
      String[] optional = first ? new String[]{resourcePath("story-cutin.bin"), resourcePath("card-pages.bin"),
          resourcePath("backfire.wpk"), resourcePath("backfire.bfx"), resourcePath("ghost-ui.bin"), resourcePath("builtin-ghosts.bin"),
          resourcePath("front_halo.wpk"), resourcePath("front_halo.bin")} : nativeOptionalFiles;
      if (optional == null) optional = new String[8];
      if (!nativeStart(this, selectedData, saveDir, selectedCard == null ? null : selectedCard.getAbsolutePath(),
          optional[0], optional[1], optional[2], optional[3], optional[4], optional[5], optional[6], optional[7],
          privateRecordDirectory("ta-ranking-v1"), privateRecordDirectory("ghost-crown-v1"))) {
        installError("运行线程暂未能启动。资源已保留，可重新点击开始游戏。");
        return;
      }
      if (first) { nativeDataDir = selectedData; nativeCardResources = selectedCard; nativeOptionalFiles = optional; }
      dataDir = nativeDataDir; cardResources = nativeCardResources;
      started = true;
    }
    root.removeView(dataPanel);
    Surface surface = game.getHolder().getSurface();
    if (surfaceWidth > 0 && surfaceHeight > 0 && surface != null && surface.isValid())
      nativeSurface(surface, surfaceWidth, surfaceHeight);
    refreshSurfaceRate();
    nativePause(!resumed);
  }

  private void cancelResourceOperation() {
    resourceCancelled = true;
    final android.os.CancellationSignal signal = resourceOpenSignal;
    final java.io.Closeable source = resourceSource;
    // A document provider can block in open/read/close; do not block the UI on it.
    if (signal != null || source != null) new Thread(() -> {
      if (signal != null) try { signal.cancel(); } catch (RuntimeException ignored) {}
      if (source != null) try { source.close(); } catch (IOException ignored) {}
    }, "resource-provider-cancel").start();
  }

  private void closeResourceInput(InputStream input, boolean committed) {
    if (input == null) return;
    try { input.close(); }
    catch (IOException | RuntimeException closeError) {
      if (committed) resourceNotice = "资源已登记，但文件提供方关闭报告异常；可重新检查资源，不要因此重复导入。";
      else android.util.Log.w("WMMT", "Document provider close failed after an unsuccessful import");
    }
  }

  private Button resourceButton(LinearLayout row, String label, Runnable action) {
    Button button = new Button(this);
    button.setText(label);
    button.setOnClickListener(v -> action.run());
    row.addView(button, new LinearLayout.LayoutParams(0, -2, 1));
    return button;
  }

  private void resourceControls() {
    if (beginButton == null) return;
    boolean controllerBusy = originalController!=null && originalController.isBusy();
    boolean selectable = resourceSelectionAllowed();
    if(originalButton!=null) originalButton.setEnabled(selectable && originalController!=null);
    beginButton.setEnabled(installReady && !resourceClearing && !resourceBusy && !awaitingResourcePicker && !started && !controllerBusy && !destroyed && currentActivity==this && !isFinishing());
    importButton.setEnabled(selectable);
    checkButton.setEnabled(selectable);
    if (clearButton != null) clearButton.setEnabled(selectable);
    cancelButton.setEnabled((resourceBusy || controllerBusy) && !resourceCancelled);
    if(launcherWallpaper!=null) launcherWallpaper.updateBusyPresentation(resourceBusy || controllerBusy);
  }

  private boolean resourceSelectionAllowed() {
    return !destroyed && currentActivity==this && !isFinishing() && !resourceClearing && !resourceBusy &&
        !awaitingResourcePicker && !started && nativeDataDir==null &&
        (originalController==null || !originalController.isBusy());
  }

  private void showResourceSelection() {
    if (!resourceSelectionAllowed()) return;
    new AlertDialog.Builder(this).setTitle("选择资源")
        .setItems(new String[]{"原版 ZIP / 目录一键转换", "导入已转换的资源 ZIP", "重新检查资源", "联网设备登记"}, (dialog, which) -> {
          // A dialog may stay open while restored work changes state. Recheck at action time.
          if (!resourceSelectionAllowed()) return;
          if (which==0) requestOriginalConversion();
          else if (which==1) chooseResourceArchive();
          else if (which==2) requestResourceRecheck();
          else if (which==3) showGhostCloudSettings();
        }).setNegativeButton("取消", null).show();
  }

  private void loadGhostCloud() {
    try {
      if (cloudDevice == null) cloudDevice = CloudDevice.load(getNoBackupFilesDir().toPath());
      if (!CloudDevice.CLOUD_ORIGIN.isEmpty())
        ghostCloud = new GhostCloud(CloudDevice.CLOUD_ORIGIN, cloudDevice,
            getNoBackupFilesDir().toPath().resolve("cloud-ghost-outbox-v1"));
    } catch (IOException | IllegalArgumentException unavailable) {
      ghostCloud = null;
    }
  }

  private void showGhostCloudSettings() {
    CloudDevice identity = cloudDevice;
    if (identity == null) {
      new AlertDialog.Builder(this).setTitle("联网设备登记")
          .setMessage("暂时无法读取此安装的设备 ID。").setPositiveButton("关闭", null).show();
      return;
    }
    GhostCloud cloud = ghostCloud;
    int status = cloud == null ? 0 : cloud.registrationStatus();
    String note = cloud == null ? "登记服务尚未配置。" :
        status == 1 ? "此设备已放行。" : status == -1 ? "此设备尚未获准联网。" : "尚未验证登记状态。";
    AlertDialog.Builder dialog = new AlertDialog.Builder(this).setTitle("联网设备登记")
        .setMessage("设备 ID\n" + identity.id + "\n\n" + note +
            "\n将 ID 提交到登记网站，获准后即可同步联网化身和计时榜。")
        .setNegativeButton("关闭", null)
        .setPositiveButton("复制设备 ID", (d, which) -> {
          android.content.ClipboardManager clipboard =
              (android.content.ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
          if (clipboard != null) clipboard.setPrimaryClip(android.content.ClipData.newPlainText("Cinder 设备 ID", identity.id));
        });
    if (cloud != null) dialog.setNeutralButton("检查登记", (d, which) ->
        cloud.refreshRegistration(() -> runOnUiThread(() -> {
          if (resourceSelectionAllowed()) showGhostCloudSettings();
        })));
    dialog.show();
  }

  String onlineVsAddress() {
    if (!CloudDevice.validDomain(CloudDevice.ONLINE_VS_DOMAIN)) return null;
    synchronized (MainActivity.class) {
      long now = android.os.SystemClock.elapsedRealtime();
      if (!vsResolving && now >= vsResolveAt) {
        vsResolving = true;
        Thread resolver = new Thread(() -> {
          String address = null;
          try {
            for (java.net.InetAddress candidate : java.net.InetAddress.getAllByName(CloudDevice.ONLINE_VS_DOMAIN)) {
              if (candidate instanceof java.net.Inet4Address) {
                address = candidate.getHostAddress();
                break;
              }
            }
          } catch (IOException | SecurityException ignored) {
          } finally {
            synchronized (MainActivity.class) {
              resolvedVsAddress = address;
              vsResolveAt = android.os.SystemClock.elapsedRealtime() + (address == null ? 5000 : 60000);
              vsResolving = false;
            }
          }
        }, "cinder-vs-resolver");
        resolver.start();
      }
      return resolvedVsAddress;
    }
  }

  private static GhostCloud approvedGhostCloud() {
    GhostCloud cloud = ghostCloud;
    return cloud != null && cloud.approved() ? cloud : null;
  }

  boolean ghostCloudConfigured() { return approvedGhostCloud() != null; }
  boolean ghostCloudRefresh(String physics) {
    GhostCloud cloud = approvedGhostCloud();
    return cloud != null && cloud.refresh(physics);
  }
  boolean ghostCloudSearch(String physics, String name) {
    GhostCloud cloud = approvedGhostCloud();
    return cloud != null && cloud.search(physics, name);
  }
  boolean ghostCloudSearchId(String physics, String id) {
    GhostCloud cloud = approvedGhostCloud();
    return cloud != null && cloud.searchId(physics, id);
  }
  byte[] ghostCloudPoll() {
    GhostCloud cloud = approvedGhostCloud();
    return cloud != null ? cloud.poll() : null;
  }
  boolean ghostCloudEnqueue(int area, byte[] profile, String cardId) {
    GhostCloud cloud = approvedGhostCloud();
    return cloud != null && cloud.enqueue(area, profile, cardId);
  }
  boolean ghostCloudReport(byte[] id, boolean won, int rawModel, int hp, int gap, String name) {
    GhostCloud cloud = approvedGhostCloud();
    return cloud != null && cloud.report(id, won, rawModel, hp, gap, name);
  }
  boolean ghostCloudDefenseRefresh(String cardId) {
    GhostCloud cloud = approvedGhostCloud();
    return cloud != null && cloud.defenseRefresh(cardId);
  }
  byte[] ghostCloudDefensePoll() {
    GhostCloud cloud = approvedGhostCloud();
    return cloud != null ? cloud.defensePoll() : null;
  }
  boolean timingCloudSubmit(byte[] record) {
    GhostCloud cloud = approvedGhostCloud();
    return cloud != null && cloud.timingSubmit(record);
  }
  int timingCloudPollAck() {
    GhostCloud cloud = approvedGhostCloud();
    return cloud != null ? cloud.timingPollAck() : -1;
  }
  boolean timingCloudRefresh(String rules, String physics, int course, int traffic) {
    GhostCloud cloud = approvedGhostCloud();
    return cloud != null && cloud.timingRefresh(rules, physics, course, traffic);
  }
  byte[] timingCloudPollBoard() {
    GhostCloud cloud = approvedGhostCloud();
    return cloud != null ? cloud.timingPollBoard() : null;
  }

  private void requestOriginalConversion() {
    if (!resourceSelectionAllowed()) return;
    if (originalController == null) {
      progress.setText("原版转换入口尚未准备好；可以重新检查既有资源，未启用未知输出。");
      return;
    }
    if (Build.VERSION.SDK_INT >= 33 &&
        checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
      android.content.SharedPreferences prefs = getPreferences(Context.MODE_PRIVATE);
      if (!prefs.getBoolean("asked-conversion-notifications", false)) {
        prefs.edit().putBoolean("asked-conversion-notifications", true).apply();
        requestPermissions(new String[]{android.Manifest.permission.POST_NOTIFICATIONS}, REQUEST_CONVERSION_NOTIFICATIONS);
        return;
      }
    }
    originalController.showStartDialog();
  }

  @Override public void onRequestPermissionsResult(int request, String[] permissions, int[] grantResults) {
    super.onRequestPermissionsResult(request, permissions, grantResults);
    if (request == REQUEST_CONVERSION_NOTIFICATIONS && originalController != null && resourceSelectionAllowed()) {
      originalController.showStartDialog();
    }
  }

  private void requestResourceRecheck() {
    if (resourceSelectionAllowed()) prepareResources(null);
  }

  private void confirmResourceClear() {
    if (!resourceSelectionAllowed()) return;
    new AlertDialog.Builder(this).setTitle("清除资源包")
        .setMessage("清除应用内游戏资源目录及导入、转换暂存。车库存档、计时成绩和化身记录会保留。之后需要重新导入资源才能开始游戏。")
        .setNegativeButton("取消", null)
        .setPositiveButton("清除资源包", (dialog, which) -> clearResources())
        .show();
  }

  private void clearResources() {
    if (!resourceSelectionAllowed()) return;
    resourceClearing = true;
    installReady = false;
    preparedResources = null;
    dataDir = null;
    cardResources = null;
    progress.setText("正在清除游戏资源，保留存档…");
    resourceControls();
    Context app = getApplicationContext();
    new Thread(() -> {
      String result;
      try {
        synchronized (INSTALL_LOCK) {
          lockInstallProcess(app);
          File external = app.getExternalFilesDir(null), privateRoot = app.getNoBackupFilesDir();
          if (external == null || privateRoot == null) throw new IOException("应用存储当前不可用");
          ResourceStore.clearInstalledResources(external.getCanonicalFile().toPath(), privateRoot.getCanonicalFile().toPath());
        }
        result = "资源包已清除，存档已保留。请导入资源包或转换原版资源。";
      } catch (Exception failure) {
        result = "未能完成资源清除。存档已保留，可再次点击“清除资源包”重试。\n" + failure.getMessage();
      }
      final String message = result;
      runOnUiThread(() -> {
        resourceClearing = false;
        MainActivity activity = currentActivity;
        if (activity == null || activity.destroyed || activity.isFinishing()) return;
        activity.progress.setText(message);
        activity.resourceControls();
      });
    }, "resource-clear-worker").start();
  }

  private void chooseResourceArchive() {
    if (!resourceSelectionAllowed()) return;
    new AlertDialog.Builder(this).setTitle("本地导入 / 安全修复")
        .setMessage("请选择已转换的游戏资源 ZIP。原版街机 ZIP 或目录请使用“原版 ZIP / 目录一键转换”。存档会保留。")
        .setNegativeButton("取消", null)
        .setPositiveButton("选择文件", (dialog, which) -> {
          if (!resourceSelectionAllowed()) return;
          awaitingResourcePicker = true;
          resourceControls();
          Intent pick = new Intent(Intent.ACTION_OPEN_DOCUMENT);
          pick.addCategory(Intent.CATEGORY_OPENABLE);
          pick.setType("*/*");
          pick.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"application/zip", "application/x-zip-compressed", "application/octet-stream"});
          pick.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
          try { startActivityForResult(pick, REQUEST_RESOURCE_IMPORT); }
          catch (android.content.ActivityNotFoundException ex) {
            awaitingResourcePicker = false;
            installError("系统文件选择器不可用，请先启用设备的文件管理/文档服务。");
          }
        }).show();
  }

  @Override protected void onActivityResult(int request, int result, Intent data) {
    super.onActivityResult(request, result, data);
    if(originalController!=null && originalController.onActivityResult(request,result,data)) return;
    if (request != REQUEST_RESOURCE_IMPORT || resourceClearing || destroyed || started || currentActivity != this) return;
    awaitingResourcePicker = false;
    if (result != RESULT_OK || data == null || data.getData() == null) {
      if (!installReady && !resourceBusy) prepareResources(null);
      else {
        progress.setText("未选择文件，原有资源与存档未改变。可重新检查或再次导入。");
        resourceControls();
      }
      return;
    }
    pendingResourceImport = data.getData();
    if (resourceBusy) {
      cancelResourceOperation(); // Queue, do not drop a result delivered during recreation's check.
      progress.setText("已收到所选文件，正在安全停止当前检查，随后开始导入…");
      resourceControls();
    } else startQueuedImport();
  }

  private boolean startQueuedImport() {
    if (pendingResourceImport == null || resourceClearing || resourceBusy || destroyed || started || nativeDataDir != null || currentActivity != this || isFinishing()) return false;
    Uri source = pendingResourceImport;
    pendingResourceImport = null;
    prepareResources(source);
    return true;
  }

  @Override protected void onSaveInstanceState(Bundle state) {
    if(originalController!=null) originalController.saveState(state);
    state.putBoolean("resource-picker-pending", awaitingResourcePicker);
    if (pendingResourceImport != null) state.putParcelable("resource-import-uri", pendingResourceImport);
    super.onSaveInstanceState(state);
  }

  private String resourceStage(String stage) {
    if (stage.startsWith("recover-old:")) return "正在恢复旧版已登记更新，仅处理受控资源";
    switch (stage) {
      case "verify-old-state": return "正在只读检查旧更新记录";
      case "verify-recovery-source": return "正在核对旧更新所需的精确资源来源";
      case "copy-source": return "正在复制所选文件到独立暂存目录";
      case "extract-main": return "正在校验并展开主资源";
      case "verify-main": return "正在核对主资源完整性";
      case "verify-files": return "正在核对资源文件清单";
      case "verify-optional": return "正在核对可选演出、音效与表盘";
      case "extract": return "正在展开所选资源";
      case "verify-zip": return "正在校验压缩包结构与CRC";
      case "publish": return "正在登记已校验的新资源";
      default: return "正在准备资源";
    }
  }

  private void prepareResources(Uri source) {
    if (resourceClearing || resourceBusy || started || nativeDataDir != null || destroyed) return;
    resourceBusy = true; resourceCancelled = false; installReady = false; preparedResources = null;
    resourceNotice = pendingOriginalNotice; pendingOriginalNotice = null;
    lastResourceProgress = 0;
    progress.setText(source == null ? "正在校验已安装资源…" : "正在读取所选文件，现有资源和存档保留…");
    resourceControls();
    new Thread(() -> {
      final long resourceStartedNanos = System.nanoTime();
      try {
        File ext = getExternalFilesDir(null), privateRoot = getNoBackupFilesDir();
        if (ext == null || privateRoot == null) throw new IOException("应用存储当前不可用");
        ext = ext.getCanonicalFile();
        File save = new File(ext, "wmmt");
        final ResolvedResources ready;
        ResolvedResources baseReady;
        synchronized (INSTALL_LOCK) {
          lockInstallProcess();
          if (java.nio.file.Files.isSymbolicLink(save.toPath())) throw new IOException("存档路径不安全，已保留原数据");
          if (!save.isDirectory() && !save.mkdirs()) throw new IOException("无法访问存档目录");
          ResourceStore.Cancel cancel = () -> resourceCancelled || destroyed || currentActivity != this;
          DataManifest.Limits limits = new DataManifest.Limits(200000, 50L * 1024 * 1024 * 1024,
              Integer.MAX_VALUE, 64 * 1024 * 1024);
          DataBaselines baselines;
          ResourceMetadata metadata;
          try (InputStream in = getAssets().open(BASELINES_ASSET)) { baselines = DataBaselines.read(in, limits); }
          try (InputStream in = getAssets().open("sidecars-index-v1.tsv")) { metadata = ResourceMetadata.read(in); }
          // Independent optional metadata: malformed or absent bank never invalidates main.
          try {
            boolean uiV6=false, uiV5=false, uiLegacy=false;
            String[] packagedAssets=getAssets().list("");
            if(packagedAssets!=null) for(String asset:packagedAssets) {
              if(asset.equals("arcade-ui-v6-index.tsv")) uiV6=true;
              if(asset.equals("arcade-ui-v5-index.tsv")) uiV5=true;
              if(asset.equals("ghost-ui-index-v1.tsv")) uiLegacy=true;
            }
            // Exactly one signed generation may authorize this same native key.
            // Malformed v6 never falls back to v5 or a legacy approval.
            if(uiV6 && !uiV5 && !uiLegacy) {
              try(InputStream in=getAssets().open("arcade-ui-v6-index.tsv")) { metadata=metadata.withArcadeUiV6(in); }
            } else if(uiV5 && !uiV6 && !uiLegacy) {
              try(InputStream in=getAssets().open("arcade-ui-v5-index.tsv")) { metadata=metadata.withArcadeUiV5(in); }
            } else if(uiLegacy && !uiV6 && !uiV5) {
              try(InputStream in=getAssets().open("ghost-ui-index-v1.tsv")) { metadata=metadata.withGhost(in); }
            }
          } catch(IOException missingOrInvalidUiMetadata) { /* optional capability absent; main unchanged */ }
          try (InputStream in=getAssets().open("builtin-ghosts-index-v1.tsv")) { metadata=metadata.withBuiltinGhosts(in); }
          catch(IOException missingOrInvalidDatasetMetadata) { /* capability absent; authentic main readiness unchanged */ }
          ResourceStore store = new ResourceStore(ext.toPath(), privateRoot.getCanonicalFile().toPath(), limits, baselines, metadata);
          ResourceStore.Progress report = (stage, current, total) -> {
            long now = android.os.SystemClock.elapsedRealtime();
            if (now - lastResourceProgress < 200 && !stage.equals("publish")) return;
            lastResourceProgress = now;
            String detail = total > 0 ? " (" + current + "/" + total + ")" : "";
            long seconds = (System.nanoTime() - resourceStartedNanos) / 1000000000L;
            installProgress(resourceStage(stage) + detail + "，已用时 " + seconds + " 秒\n存档与未知文件保留；校验完成前不会启动游戏。旧版完整更新恢复可能需要较长时间。");
          };
          OriginalJobStore originalStore = new OriginalJobStore(ext.toPath(), privateRoot.getCanonicalFile().toPath(), originalProfile(getApplicationContext()));
          if (source == null) {
            OriginalJobStore.Ready original = originalStore.resolve(() -> cancel.cancelled(), (stage,current,total) -> report.update(stage,current,total));
            baseReady = original == null ? new ResolvedResources(store.resolve(cancel, report)) : new ResolvedResources(original);
          } else {
            android.os.CancellationSignal signal = new android.os.CancellationSignal();
            resourceOpenSignal = signal;
            InputStream opened = null;
            ResourceStore.Ready imported = null;
            try {
              if (cancel.cancelled()) signal.cancel();
              android.os.ParcelFileDescriptor descriptor = getContentResolver().openFileDescriptor(source, "r", signal);
              if (descriptor == null) throw new IOException("无法打开所选文件");
              opened = new android.os.ParcelFileDescriptor.AutoCloseInputStream(descriptor);
              resourceSource = opened;
              imported = store.importArchive(opened, cancel, report);
            } finally {
              // A provider close error after the atomic selection switch is a warning,
              // never a false claim that the committed import failed or was rolled back.
              closeResourceInput(opened, imported != null);
              if (resourceSource == opened) resourceSource = null;
              if (resourceOpenSignal == signal) resourceOpenSignal = null;
            }
            if (imported == null) throw new IOException("导入没有返回已校验资源");
            // Old Store committed its own selector already. If this extra marker
            // fails, the authenticated legacy-epoch barrier still delegates to it;
            // never misreport a committed old import as rolled back.
            if (java.nio.file.Files.exists(privateRoot.toPath().resolve("resource-choice-v2/selection"), java.nio.file.LinkOption.NOFOLLOW_LINKS)) {
              try { originalStore.markPreparedSelection(); }
              catch (IOException markerError) { resourceNotice = "已校验并登记所选资源；附加选择标记未同步，重新检查将按旧资源选择记录核验。"; }
            }
            baseReady = new ResolvedResources(imported);
          }
          ResourceStore.VerifiedOptional uiCapability = store.preparePackagedGhost(() -> getAssets().open("ghost-ui.bin"), cancel, report);
          ResourceStore.VerifiedOptional datasetCapability = store.preparePackagedBuiltinGhosts(() -> getAssets().open("builtin-ghosts.bin"), cancel, report);
          ready = withGhosts(baseReady, uiCapability, datasetCapability);
        }
        final String savePath = save.getAbsolutePath();
        runOnUiThread(() -> {
          if (destroyed || currentActivity != this || isFinishing()) return;
          resourceBusy = false;
          if (startQueuedImport()) return;
          if (resourceCancelled) {
            installReady = false;
            progress.setText("操作已停止，未启动游戏。若资源已完成登记，重新检查后可复用；旧资源与存档保留。");
          } else {
            preparedResources = ready;
            dataDir = ready.dataDirectory.toFile().getAbsolutePath();
            cardResources = ready.cardDirectory == null ? null : ready.cardDirectory.toFile();
            saveDir = savePath;
            installReady = true;
            StringBuilder text = new StringBuilder("主资源已校验，可以开始游戏。\n");
            for (String warning : ready.warnings) text.append("\n提示：").append(warning);
            if (resourceNotice != null) text.append("\n提示：").append(resourceNotice);
            text.append("\n\n若需要更新或补齐资源，请打开“选择资源”。");
            progress.setText(text);
          }
          resourceControls();
        });
      } catch (Exception ex) {
        runOnUiThread(() -> {
          if (destroyed || currentActivity != this || isFinishing()) return;
          resourceBusy = false; installReady = false;
          if (startQueuedImport()) return;
          String detail = resourceCancelled ? "操作已取消。" : "资源尚未就绪：" + String.valueOf(ex.getMessage());
          if (resourceNotice != null) detail += "\n提示：" + resourceNotice;
          installError(detail);
        });
      }
    }, "resource-import-worker").start();
  }

  private void installError(String message) {
    progress.setText(message + "\n存档保留。可从“选择资源”重新检查或导入。");
    resourceControls();
  }

  private void installProgress(String text) {
    runOnUiThread(() -> { if (!destroyed && !isFinishing()) progress.setText(text); });
  }

  /* Separate from the large ZIP version and from save files. Rehash both copies on every
   * launch; a same-directory temporary plus rename leaves the old version intact on failure. */
  private byte[] cutinDigest(InputStream in) throws Exception {
    MessageDigest sha = MessageDigest.getInstance("SHA-256");
    byte[] buf = new byte[65536]; long total = 0; int n;
    while ((n = in.read(buf)) != -1) {
      total += n;
      if (total > CUTIN_LIMIT) throw new IOException("Cut-in asset exceeds limit");
      sha.update(buf, 0, n);
    }
    if (total == 0) throw new IOException("Empty cut-in asset");
    return sha.digest();
  }

  private void prepareCutin(File ext) throws Exception {
    String[] assets = getAssets().list("");
    if (assets == null) throw new IOException("Cannot list APK assets");
    boolean present = false;
    for (String name : assets) if (CUTIN_ASSET.equals(name)) present = true;
    if (!present) return;
    byte[] expected;
    try (InputStream in = getAssets().open(CUTIN_ASSET)) { expected = cutinDigest(in); }
    File dir = new File(ext, "wmmt-sidecars");
    if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("Cannot create cut-in directory");
    if (!dir.getCanonicalFile().equals(new File(ext.getCanonicalFile(), "wmmt-sidecars")))
      throw new IOException("Unsafe cut-in directory");
    File dest = new File(dir, CUTIN_ASSET);
    if (!dest.getCanonicalFile().equals(new File(dir.getCanonicalFile(), CUTIN_ASSET)))
      throw new IOException("Unsafe cut-in file");
    if (dest.isFile()) {
      try (InputStream in = new FileInputStream(dest)) {
        if (MessageDigest.isEqual(expected, cutinDigest(in))) return;
      } catch (IOException ignored) { /* replace a damaged copy */ }
    }
    File temp = File.createTempFile(".story-cutin-", ".tmp", dir);
    try {
      byte[] buffer = new byte[65536]; long total = 0;
      MessageDigest sha = MessageDigest.getInstance("SHA-256");
      try (InputStream in = getAssets().open(CUTIN_ASSET); FileOutputStream out = new FileOutputStream(temp)) {
        int n; while ((n = in.read(buffer)) != -1) {
          total += n;
          if (total > CUTIN_LIMIT) throw new IOException("Cut-in asset exceeds limit");
          sha.update(buffer, 0, n); out.write(buffer, 0, n);
        }
        out.getFD().sync();
      }
      if (!MessageDigest.isEqual(expected, sha.digest())) throw new IOException("Cut-in asset changed during copy");
      try (InputStream in = new FileInputStream(temp)) {
        if (!MessageDigest.isEqual(expected, cutinDigest(in))) throw new IOException("Cut-in copy verification failed");
      }
      if (!temp.renameTo(dest)) throw new IOException("Cannot publish cut-in asset");
    } finally { if (temp.exists() && !temp.delete()) android.util.Log.w("WMMT", "Cannot remove cut-in temporary file"); }
  }

  /* The card resource bank is independent of the game archive and save data. */
  private void prepareCardPages(File ext) throws Exception {
    final String asset = "card-pages.bin";
    String[] assets = getAssets().list("");
    if (assets == null) throw new IOException("Cannot list APK assets");
    boolean present = false;
    for (String name : assets) if (asset.equals(name)) present = true;
    if (!present) return;
    byte[] expected;
    try (InputStream in = getAssets().open(asset)) { expected = cutinDigest(in); }
    File dir = new File(ext, "wmmt-sidecars");
    if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("Cannot create sidecar directory");
    if (!dir.getCanonicalFile().equals(new File(ext.getCanonicalFile(), "wmmt-sidecars")))
      throw new IOException("Unsafe sidecar directory");
    File dest = new File(dir, asset);
    if (!dest.getCanonicalFile().equals(new File(dir.getCanonicalFile(), asset)))
      throw new IOException("Unsafe card pages file");
    if (dest.isFile()) {
      try (InputStream in = new FileInputStream(dest)) {
        if (MessageDigest.isEqual(expected, cutinDigest(in))) return;
      } catch (IOException ignored) { /* retry using the packaged source */ }
    }
    File temp = File.createTempFile(".card-pages-", ".tmp", dir);
    try {
      byte[] buffer = new byte[65536]; long total = 0;
      MessageDigest sha = MessageDigest.getInstance("SHA-256");
      try (InputStream in = getAssets().open(asset); FileOutputStream out = new FileOutputStream(temp)) {
        int n; while ((n = in.read(buffer)) != -1) {
          total += n;
          if (total > CUTIN_LIMIT) throw new IOException("Card pages exceed limit");
          sha.update(buffer, 0, n); out.write(buffer, 0, n);
        }
        out.getFD().sync();
      }
      if (!MessageDigest.isEqual(expected, sha.digest())) throw new IOException("Card pages changed during copy");
      try (InputStream in = new FileInputStream(temp)) {
        if (!MessageDigest.isEqual(expected, cutinDigest(in))) throw new IOException("Card pages copy verification failed");
      }
      if (!temp.renameTo(dest)) throw new IOException("Cannot publish card pages");
    } finally { if (temp.exists() && !temp.delete()) android.util.Log.w("WMMT", "Cannot remove card pages temporary file"); }
  }

  /* Publish an immutable, verified pair directory before atomically replacing its pointer.
   * The pointer is exactly 64 lowercase hex bytes: SHA-256(WPK digest || BFX digest).
   * Native must read the pointer once and validate it before constructing either path. Old
   * versions are retained for concurrent readers. This is not a power-loss transaction. */
  private void prepareBackfire(File ext) throws Exception {
    final String[] names = { "backfire.wpk", "backfire.bfx" };
    String[] assets = getAssets().list("");
    if (assets == null) throw new IOException("Cannot list APK assets");
    boolean[] present = new boolean[2];
    for (String asset : assets)
      for (int i = 0; i < names.length; i++) if (names[i].equals(asset)) present[i] = true;
    if (!present[0] && !present[1]) return;
    if (!present[0] || !present[1]) throw new IOException("Incomplete packaged backfire pair");

    byte[][] expected = new byte[2][];
    for (int i = 0; i < names.length; i++)
      try (InputStream in = getAssets().open(names[i])) { expected[i] = cutinDigest(in); }
    File dir = new File(ext, "wmmt-sidecars");
    if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("Cannot create sidecar directory");
    if (!dir.getCanonicalFile().equals(new File(ext.getCanonicalFile(), "wmmt-sidecars")))
      throw new IOException("Unsafe backfire directory");
    MessageDigest pairHash = MessageDigest.getInstance("SHA-256");
    pairHash.update(expected[0]); pairHash.update(expected[1]);
    StringBuilder hex = new StringBuilder();
    for (byte b : pairHash.digest()) hex.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
    String version = hex.toString();
    File dest = new File(dir, "backfire-" + version);
    if (!dest.getCanonicalFile().equals(new File(dir.getCanonicalFile(), dest.getName())))
      throw new IOException("Unsafe backfire version directory");
    File stage = null, pointerTemp = null;
    try {
      if (!dest.exists()) {
        File candidate = new File(dir, ".backfire-stage-" + UUID.randomUUID());
        if (!candidate.mkdir()) throw new IOException("Cannot create backfire staging directory");
        stage = candidate;
        for (int i = 0; i < names.length; i++) {
          File file = new File(stage, names[i]);
          MessageDigest sha = MessageDigest.getInstance("SHA-256");
          byte[] buffer = new byte[65536]; long total = 0;
          try (InputStream in = getAssets().open(names[i]); FileOutputStream out = new FileOutputStream(file)) {
            int n; while ((n = in.read(buffer)) != -1) {
              total += n;
              if (total > CUTIN_LIMIT) throw new IOException("Backfire asset exceeds limit: " + names[i]);
              sha.update(buffer, 0, n); out.write(buffer, 0, n);
            }
            out.getFD().sync();
          }
          if (!MessageDigest.isEqual(expected[i], sha.digest()))
            throw new IOException("Backfire asset changed during copy: " + names[i]);
        }
        verifyBackfirePair(stage, names, expected);
        if (!stage.renameTo(dest) && !dest.isDirectory())
          throw new IOException("Cannot publish backfire directory");
      }
      verifyBackfirePair(dest, names, expected);
      File pointer = new File(dir, "backfire-current");
      if (!pointer.getCanonicalFile().equals(new File(dir.getCanonicalFile(), "backfire-current")))
        throw new IOException("Unsafe backfire pointer");
      pointerTemp = File.createTempFile(".backfire-current-", ".tmp", dir);
      try (FileOutputStream out = new FileOutputStream(pointerTemp)) {
        out.write(version.getBytes("US-ASCII")); out.getFD().sync();
      }
      if (!pointerTemp.renameTo(pointer)) throw new IOException("Cannot publish backfire pointer");
    } finally {
      if (pointerTemp != null && pointerTemp.exists() && !pointerTemp.delete())
        android.util.Log.w("WMMT", "Cannot remove backfire pointer temporary file");
      if (stage != null && stage.exists()) {
        for (String name : names) {
          File file = new File(stage, name);
          if (file.exists() && !file.delete()) android.util.Log.w("WMMT", "Cannot remove backfire staging file");
        }
        if (!stage.delete()) android.util.Log.w("WMMT", "Cannot remove backfire staging directory");
      }
    }
  }

  private void verifyBackfirePair(File dir, String[] names, byte[][] expected) throws Exception {
    if (!dir.isDirectory()) throw new IOException("Backfire version is not a directory");
    for (int i = 0; i < names.length; i++) {
      File file = new File(dir, names[i]);
      if (!file.getCanonicalFile().equals(new File(dir.getCanonicalFile(), names[i])) || !file.isFile())
        throw new IOException("Unsafe or missing backfire file: " + names[i]);
      try (InputStream in = new FileInputStream(file)) {
        if (!MessageDigest.isEqual(expected[i], cutinDigest(in)))
          throw new IOException("Backfire verification failed: " + names[i]);
      }
    }
  }

  /* The private lock remains held for the lifetime of this process, including native use.
   * Other writers such as root/ADB must not mutate data concurrently. */
  private File prepareData(File ext, File legacy) throws Exception {
    String[] assets = getAssets().list("");
    if (assets == null) throw new IOException("Cannot list APK assets");
    boolean present = false;
    for (String name : assets) if (ASSET.equals(name)) present = true;
    File stateRoot = getNoBackupFilesDir();
    if (stateRoot == null) throw new IOException("Private update storage is unavailable");
    /* No released version uses this earlier draft path. Never silently discard it. */
    if (new File(getFilesDir(), "game-data-state").exists())
      throw new IOException("Unrecognized existing update state; preserve it and contact support");
    if (!present) {
      if (new File(stateRoot, "game-data-state/pending").exists())
        throw new IOException("Interrupted data update requires its packaged ZIP to repair");
      return legacy;
    }
    installProgress("Checking packaged game data…");
    DataManifest.Limits limits = new DataManifest.Limits(200000, 50L * 1024 * 1024 * 1024,
        Integer.MAX_VALUE, 64 * 1024 * 1024);
    File canonicalExt = ext.getCanonicalFile();
    File privateDir = stateRoot.getCanonicalFile();
    // Existing active/pending state is authoritative without needing a legacy
    // catalog. Load only the fixed signed-APK asset when discovery asks for it.
    DataCoordinator.Baselines history = new DataCoordinator.Baselines() {
      private DataBaselines catalog;
      @Override public DataManifest find(String zipSha256) throws IOException {
        if (catalog == null) {
          try (InputStream in = getAssets().open(BASELINES_ASSET)) {
            catalog = DataBaselines.read(in, limits);
          }
        }
        return catalog.find(zipSha256);
      }
    };
    DataCoordinator coordinator = DataCoordinator.withBaselines(new File(canonicalExt, "re3dxplus-data").toPath(),
        new File(privateDir, "game-data-state").toPath(), limits, history);
    return coordinator.prepare(() -> getAssets().open(ASSET), stage -> {
      if (stage.equals("before-legacy-verify"))
        installProgress("Verifying existing game resources; saves are kept…");
      else if (stage.equals("after-legacy-publish") || stage.equals("after-pending"))
        installProgress("Updating game resources in place; saves are kept…");
      else if (stage.equals("before-confirm"))
        installProgress("Confirming updated game resources…");
    }).toFile();
  }

  private void hideBars() {
    getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_FULLSCREEN
        | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
        | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN);
  }

  @Override public void onWindowFocusChanged(boolean f) {
    super.onWindowFocusChanged(f);
    if (f) { hideBars(); refreshSurfaceRate(); }
  }

  private void touch(MotionEvent e) {
    if (!started || currentActivity != this) return;
    int a = e.getActionMasked();
    if (a == MotionEvent.ACTION_MOVE) {
      for (int i = 0; i < e.getPointerCount(); ++i) nativeTouch(e.getPointerId(i), 1, e.getX(i), e.getY(i));
      return;
    }
    int phase = a == MotionEvent.ACTION_DOWN || a == MotionEvent.ACTION_POINTER_DOWN ? 0
        : a == MotionEvent.ACTION_UP || a == MotionEvent.ACTION_POINTER_UP ? 2 : a == MotionEvent.ACTION_CANCEL ? 3 : -1;
    if (phase < 0) return;
    if (phase == 3) {
      /* Preserve each cancelled pointer's identity and coordinates for the native bridge. */
      for (int i = 0; i < e.getPointerCount(); ++i) {
        nativeTouch(e.getPointerId(i), phase, e.getX(i), e.getY(i));
      }
      return;
    }
    int i = e.getActionIndex();
    nativeTouch(e.getPointerId(i), phase, e.getX(i), e.getY(i));
  }

  /* Prefer an advertised matching mode, then an even multiple (60 on 120 Hz),
   * then a faster mode the native pacer can cap, or the fastest slower mode. */
  static float chooseRefreshRate(float[] rates, int limit) {
    float below = 0, above = Float.POSITIVE_INFINITY, multiple = Float.POSITIVE_INFINITY;
    for (float hz : rates) {
      if (!(hz >= 30 && hz <= 120.001f)) continue;
      if (limit == 0 || hz < limit - 0.5f) {
        below = Math.max(below, hz);
      } else {
        above = Math.min(above, hz);
        if (Math.abs(hz - Math.round(hz / limit) * limit) <= 0.5f) multiple = Math.min(multiple, hz);
      }
    }
    if (multiple != Float.POSITIVE_INFINITY) return multiple;
    if (above != Float.POSITIVE_INFINITY) return above;
    return below > 0 ? below : 60;
  }

  public void frameRateLimitChanged() { runOnUiThread(this::refreshSurfaceRate); }

  private void refreshSurfaceRate() {
    if (game == null || currentActivity != this || destroyed) return;
    Surface surface = game.getHolder().getSurface();
    Display display = game.getDisplay();
    float target = 60;
    int modeId = 0;
    try {
      if (display != null && android.os.Build.VERSION.SDK_INT >= 23) {
        Display.Mode current = display.getMode();
        Display.Mode[] modes = display.getSupportedModes();
        float[] rates = new float[modes.length];
        for (int i = 0; i < modes.length; ++i)
          if (modes[i].getPhysicalWidth() == current.getPhysicalWidth() &&
              modes[i].getPhysicalHeight() == current.getPhysicalHeight()) rates[i] = modes[i].getRefreshRate();
        target = chooseRefreshRate(rates, started ? nativeFrameRateLimit() : 0);
        for (int i = 0; i < modes.length; ++i)
          if (rates[i] == target) { modeId = modes[i].getModeId(); break; }
      }
      WindowManager.LayoutParams attrs = getWindow().getAttributes();
      if (attrs.preferredDisplayModeId != modeId || attrs.preferredRefreshRate != target) {
        attrs.preferredDisplayModeId = modeId;
        attrs.preferredRefreshRate = target;
        getWindow().setAttributes(attrs);
      }
      if (android.os.Build.VERSION.SDK_INT >= 30 && surface != null && surface.isValid())
        surface.setFrameRate(target, Surface.FRAME_RATE_COMPATIBILITY_DEFAULT);
    } catch (RuntimeException rejected) {
      target = 60; // Optional display APIs must not prevent starting/resuming.
      try {
        WindowManager.LayoutParams attrs = getWindow().getAttributes();
        attrs.preferredDisplayModeId = 0;
        attrs.preferredRefreshRate = 60;
        getWindow().setAttributes(attrs);
        if (android.os.Build.VERSION.SDK_INT >= 30 && surface != null && surface.isValid())
          surface.setFrameRate(60, Surface.FRAME_RATE_COMPATIBILITY_DEFAULT);
      } catch (RuntimeException ignored) { }
    }
    // Before nativeStart there is no owner yet; startGame republishes the hint.
    if (started) nativeRefreshRate(this, target);
  }

  @Override public void onDisplayAdded(int id) { }
  @Override public void onDisplayRemoved(int id) { }
  @Override public void onDisplayChanged(int id) { refreshSurfaceRate(); }

  @Override public void surfaceCreated(SurfaceHolder h) {}
  @Override public void surfaceChanged(SurfaceHolder h, int fmt, int w, int ht) {
    surfaceWidth = w; surfaceHeight = ht;
    Surface surface = h.getSurface();
    refreshSurfaceRate();
    if (started && currentActivity == this) nativeSurface(surface, w, ht);
  }
  @Override public void surfaceDestroyed(SurfaceHolder h) {
    surfaceWidth = surfaceHeight = 0;
    if (started && currentActivity == this) nativeSurface(null, 0, 0);
  }

  @Override protected void onPause() {
    super.onPause();
    resumed = false;
    if (displays != null) displays.unregisterDisplayListener(this);
    if (started && currentActivity == this) nativePause(true);
    if (sensors != null) sensors.unregisterListener(this);
    updateBgmPlayback();
    finishMovie(movie, movieToken, true, false);
  }

  @Override protected void onResume() {
    super.onResume();
    hideBars();
    resumed = true;
    if (displays != null) displays.registerDisplayListener(this, null);
    refreshSurfaceRate();
    if (started && currentActivity == this) nativePause(false);
    if (gravity != null && sensors != null) sensors.registerListener(this, gravity, SensorManager.SENSOR_DELAY_GAME);
    updateBgmPlayback();
  }

  @Override protected void onDestroy() {
    if(originalController!=null) originalController.detach(originalHost);
    cancelResourceOperation();
    finishMovie(movie, movieToken, true, false);
    destroyed = true;
    if (currentActivity == this) currentActivity = null;
    ++bgmGeneration;
    if (bgmExecutor != null) { bgmExecutor.shutdownNow(); bgmExecutor = null; }
    closePendingBgm();
    closeCurrentBgm();
    if (root != null && dataPanel != null) root.removeView(dataPanel);
    if (launcherWallpaper != null) { launcherWallpaper.release(); launcherWallpaper = null; }
    super.onDestroy();
  }

  @Override public void onTrimMemory(int level) {
    super.onTrimMemory(level);
    if (started && currentActivity == this && level >= TRIM_MEMORY_RUNNING_LOW) nativeMemoryWarning();
  }

  /* the phone turned like a wheel (main.m's tilt): gravity's angle in the screen's plane from
   * its down, clockwise positive; nothing when it lies flat. In landscape the screen's right is
   * the sensor's -y (rotation 90) or +y (270) and its down the sensor's +x or -x. */
  @Override public void onSensorChanged(SensorEvent e) {
    if (!started || currentActivity != this || !nativeWantsTilt()) return;
    float gx = e.values[0], gy = e.values[1];
    int rot = getWindowManager().getDefaultDisplay().getRotation();
    float right = rot == Surface.ROTATION_270 ? gy : -gy, down = rot == Surface.ROTATION_270 ? -gx : gx;
    float g2 = right * right + down * down;
    nativeTilt(g2 < 0.04f * 96.2f ? 0.0f : (float) Math.atan2(-right, down));
  }
  @Override public void onAccuracyChanged(Sensor s, int a) {}

  /* ---- called by the game's thread ---- */

  /* One UI-thread exit: invalidate first, stop decoding, then detach the actual overlay.
   * A replaced view's saved completion/error/touch listener cannot affect its successor. */
  private void finishMovie(VideoView expected, long token, boolean notify, boolean pressStart) {
    if (token == 0 || movieToken != token || movie != expected) return;
    movie = null;
    movieToken = 0;
    if (expected != null) {
      expected.setOnCompletionListener(null);
      /* Consume even a late VideoView-internal error: null would enable its default dialog. */
      expected.setOnErrorListener((mp, what, extra) -> true);
      expected.setOnTouchListener(null);
      try { expected.stopPlayback(); }
      catch (RuntimeException stopFailure) {
        /* stop() may reject a failed MediaPlayer state; suspend still releases that player. */
        try { expected.suspend(); } catch (RuntimeException ignored) { }
      }
      finally { if (root != null) root.removeView(expected); }
    }
    if (notify && token == movieRequest) nativeMovieDone(this, token, pressStart);
  }

  @Override public void onBackPressed() {
    if (movieToken != 0) {
      finishMovie(movie, movieToken, true, false);
      return;
    }
    super.onBackPressed();
  }

  /* the attract movie (data dir's intro.mp4 etc.), or none for null */
  void showMovie(final String name, final long token) {
    movieRequest = token;
    runOnUiThread(() -> {
      if (token != movieRequest) return; /* obsolete queued show/hide */
      finishMovie(movie, movieToken, false, false);
      if (name == null) return;
      movieToken = token;
      if (destroyed || currentActivity != this || isFinishing() || !resumed) {
        finishMovie(null, token, true, false);
        return;
      }
      File f = new File(dataDir, name);
      if (!f.exists()) {
        finishMovie(null, token, true, false);
        return;
      }
      final VideoView video = new VideoView(this);
      movie = video;
      video.setZOrderMediaOverlay(true);
      video.setOnCompletionListener(mp -> finishMovie(video, token, true, false));
      video.setOnErrorListener((mp, what, extra) -> { finishMovie(video, token, true, false); return true; });
      /* a tap on the movie is the arcade's "press the gas"; done+start is one native event */
      video.setOnTouchListener((v, e) -> {
        if (e.getActionMasked() == MotionEvent.ACTION_DOWN) finishMovie(video, token, true, true);
        return true;
      });
      FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT,
          FrameLayout.LayoutParams.MATCH_PARENT, android.view.Gravity.CENTER);
      /* the intro's picture is letterboxed in its 4:3 (640x326 at y 76): on a wider screen it
       * goes the screen's width, its black bands off the top and bottom; playdemo and tutorial
       * fill their 4:3 and stay so */
      int w = root.getWidth(), h = root.getHeight();
      if (name.equals("intro.mp4") && w * 3 > h * 4) {
        lp.width = w;
        lp.height = w * 3 / 4;
      }
      try {
        video.setVideoPath(f.getAbsolutePath());
        if (movie != video || movieToken != token) return;
        root.addView(video, lp);
        video.start();
      } catch (RuntimeException failure) {
        finishMovie(video, token, true, false);
      }
    });
  }

  /* Publish pause immediately, even if a track-start task is already queued.
   * Release is ordered on the UI queue after any preceding track replacement. */
  void setBgmGameplayPaused(final boolean paused) {
    final long revision;
    synchronized (this) {
      if (destroyed || currentActivity != this) return;
      revision = ++bgmPauseRevision;
      if (paused) bgmGameplayPaused = true;
    }
    runOnUiThread(() -> {
      synchronized (this) {
        if (destroyed || currentActivity != this || isFinishing()) return;
        if (!paused && revision == bgmPauseRevision) bgmGameplayPaused = false;
        updateBgmPlayback();
      }
    });
  }

  private synchronized void updateBgmPlayback() {
    if (destroyed || currentActivity != this) return;
    boolean play = resumed && !bgmGameplayPaused;
    if (arcadeBgm != null) arcadeBgm.playback(play, bgmVolume);
    if (bgm == null || bgmPreparing) return;
    if (play) {
      if (!bgm.isPlaying()) bgm.start();
    } else if (bgm.isPlaying()) bgm.pause();
  }

  /* The Activity owns playback requests; the PCM worker applies them to AudioTrack. */
  void setBgmVolume(final float volume) {
    if (Float.isNaN(volume) || Float.isInfinite(volume) || volume < 0 || volume > 1) return;
    runOnUiThread(() -> {
      if (destroyed || isFinishing()) return;
      bgmVolume = volume;
      if (arcadeBgm != null) arcadeBgm.playback(resumed && !bgmGameplayPaused, volume);
      if (bgm != null && !bgmPreparing) bgm.setVolume(volume, volume);
    });
  }

  private void closePendingBgm() {
    if (pendingArcadeBgm != null) { pendingArcadeBgm.close(); pendingArcadeBgm = null; }
  }

  private void closeCurrentBgm() {
    if (arcadeBgm != null) { arcadeBgm.close(); arcadeBgm = null; }
    if (bgm != null) { bgm.release(); bgm = null; }
    bgmPreparing = false;
  }

  void playBgm(final String name) {
    runOnUiThread(() -> {
      if (destroyed || currentActivity != this || isFinishing()) return;
      final long generation = ++bgmGeneration;
      closePendingBgm();
      if (name == null || arcadeBgm == null) closeCurrentBgm();
      if (name == null) return;
      final int group = name.matches("wm2_[0-9][0-9]") ? 1 : name.matches("wmr_[0-9][0-9]") ? 2 : 0;
      if (group != 0) {
        if (started) queueExtraBgm(name, group, generation);
        return;
      }
      File file = new File(dataDir, "sound/bgm/" + name + ".m4a");
      if (!file.isFile()) {
        closeCurrentBgm();
        android.util.Log.w("WMMT", "BGM unavailable: " + name);
        return;
      }
      prepareBgm(file, name, 0, generation);
    });
  }

  private void prepareBgm(File file, String name, int group, long generation) {
    if (!ArcadeBgm.supports(name)) {
      closeCurrentBgm();
      prepareLegacyBgm(file, name, group, generation);
      return;
    }
    pendingArcadeBgm = new ArcadeBgm(file, getCacheDir(), new ArcadeBgm.Listener() {
      @Override public void ready(ArcadeBgm player) {
        runOnUiThread(() -> {
          if (pendingArcadeBgm != player || !currentBgmRequest(generation)) return;
          pendingArcadeBgm = null;
          closeCurrentBgm();
          arcadeBgm = player;
          updateBgmPlayback();
        });
      }

      @Override public void failed(ArcadeBgm player, Exception error) {
        runOnUiThread(() -> {
          if (pendingArcadeBgm != player && arcadeBgm != player) return;
          if (pendingArcadeBgm == player) pendingArcadeBgm = null;
          if (arcadeBgm == player) arcadeBgm = null;
          if (!currentBgmRequest(generation)) return;
          android.util.Log.w("WMMT", "PCM BGM playback failed: " + name, error);
          closeCurrentBgm();
          prepareLegacyBgm(file, name, group, generation);
        });
      }
    });
    pendingArcadeBgm.start();
  }

  /* The worker verifies immutable optional resources. Playback state and
   * generation checks stay on the Activity's UI thread. */
  private boolean currentBgmRequest(long generation) {
    return started && !destroyed && currentActivity == this && !isFinishing() && generation == bgmGeneration;
  }

  private void queueExtraBgm(final String name, final int group, final long generation) {
    final File resources = cardResources;
    try {
      if (bgmExecutor == null) bgmExecutor = Executors.newSingleThreadExecutor();
      bgmExecutor.execute(() -> {
        if (destroyed || !started || generation != bgmGeneration) return;
        File verified = null;
        try { verified = CardResources.music(resources, name); }
        catch (Exception ex) { android.util.Log.w("WMMT", "BGM verification failed: " + name, ex); }
        if (destroyed || !started || generation != bgmGeneration) return;
        final File file = verified;
        runOnUiThread(() -> {
          if (!currentBgmRequest(generation)) return;
          if (file == null || !file.isFile()) {
            closeCurrentBgm();
            android.util.Log.w("WMMT", "BGM unavailable: " + name);
            nativeBgmFailure(this, group);
            return;
          }
          prepareBgm(file, name, group, generation);
        });
      });
    } catch (RuntimeException ex) {
      android.util.Log.w("WMMT", "BGM verification scheduling failed: " + name, ex);
      if (currentBgmRequest(generation)) {
        closeCurrentBgm();
        nativeBgmFailure(this, group);
      }
    }
  }

  private void legacyBgmFailed(MediaPlayer player, String name, int group, long generation) {
    if (bgm != player || !currentBgmRequest(generation)) return;
    bgm = null;
    bgmPreparing = false;
    player.release();
    android.util.Log.w("WMMT", "BGM playback failed: " + name);
    if (group != 0) nativeBgmFailure(this, group);
  }

  private void prepareLegacyBgm(File file, String name, int group, long generation) {
    MediaPlayer player = null;
    try {
      player = new MediaPlayer();
      final MediaPlayer pending = player;
      bgm = pending;
      bgmPreparing = true;
      pending.setOnErrorListener((mp, what, extra) -> {
        legacyBgmFailed(mp, name, group, generation);
        return true;
      });
      pending.setOnPreparedListener(mp -> {
        if (bgm != mp || !currentBgmRequest(generation)) return;
        try {
          bgmPreparing = false;
          mp.setVolume(bgmVolume, bgmVolume);
          updateBgmPlayback();
        } catch (Exception ex) {
          android.util.Log.w("WMMT", "BGM start failed: " + name, ex);
          legacyBgmFailed(mp, name, group, generation);
        }
      });
      pending.setDataSource(file.getAbsolutePath());
      pending.setLooping(true);
      if (group == 0) {
        pending.prepare();
        bgmPreparing = false;
        pending.setVolume(bgmVolume, bgmVolume);
        updateBgmPlayback();
      } else pending.prepareAsync();
    } catch (Exception ex) {
      android.util.Log.w("WMMT", "BGM preparation failed: " + name, ex);
      if (player != null) legacyBgmFailed(player, name, group, generation);
      else if (group != 0 && currentBgmRequest(generation)) nativeBgmFailure(this, group);
    }
  }

  void fail(final String msg) {
    runOnUiThread(() -> new android.app.AlertDialog.Builder(this).setTitle("WMMT3DX").setMessage(msg)
        .setPositiveButton("OK", null).show());
  }
}
