package com.wmmt.port;

import android.content.Context;
import android.content.pm.PackageManager;
import android.content.res.AssetManager;
import android.content.res.ColorStateList;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.graphics.drawable.StateListDrawable;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.lang.ref.WeakReference;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Launcher-only presentation. No resource capability, source path or game state lives here. */
final class LauncherWallpaperView extends FrameLayout {
  static final String WALLPAPER_ASSET = "original-convert/launcher-wallpaper.jpg";
  static final int MAX_ENCODED_BYTES = 16 * 1024 * 1024;
  static final long MAX_SOURCE_PIXELS = 128L * 1024 * 1024;
  static final long MAX_DECODED_PIXELS = 4L * 1024 * 1024;
  static final int MAX_DECODED_EDGE = 4096;

  final Button selectButton, launchButton, cancelButton, clearButton;
  // Retained non-null action controls for MainActivity's existing enable/disable contract.
  // They are never part of a front-of-car five-button bar or accessibility traversal.
  final Button originalActionButton, recheckActionButton;
  final TextView statusText;
  private final ImageView wallpaper;
  private final FrameLayout controls, statusDock;
  private final LinearLayout statusContent, wordmark;
  private final TextView wallpaperWarning;
  private final Handler main = new Handler(Looper.getMainLooper());
  private ExecutorService loader;
  private Bitmap wallpaperBitmap;
  private boolean loadScheduled, busy;
  private volatile boolean released;
  private int safeLeft, safeTop, safeRight, safeBottom;

  LauncherWallpaperView(Context context) {
    super(context);
    setBackgroundColor(0xff0b1017);
    setClipChildren(false);
    wallpaper = new ImageView(context);
    wallpaper.setScaleType(ImageView.ScaleType.CENTER_CROP);
    wallpaper.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
    addView(wallpaper, new FrameLayout.LayoutParams(-1, -1));

    // Edge-only shading keeps the supplied photograph and car unobscured.
    addEdgeShade(context, true);
    addEdgeShade(context, false);
    controls = new FrameLayout(context);
    addView(controls, new FrameLayout.LayoutParams(-1, -1));

    selectButton = button(context, "选择资源", false);
    selectButton.setContentDescription("选择资源，打开原版转换、运行资源导入或重新检查菜单");
    launchButton = button(context, "启动游戏", true);
    launchButton.setContentDescription("启动游戏，资源完整校验通过后可用");
    launchButton.setEnabled(false);
    controls.addView(selectButton, corner(Gravity.TOP | Gravity.LEFT));
    controls.addView(launchButton, corner(Gravity.TOP | Gravity.RIGHT));

    wordmark = new LinearLayout(context);
    wordmark.setOrientation(LinearLayout.VERTICAL);
    wordmark.setGravity(Gravity.CENTER);
    wordmark.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
    TextView title = new TextView(context);
    title.setText("PROJECT CINDER");
    title.setTextColor(0xfff2f1ee);
    title.setTextSize(17);
    title.setLetterSpacing(0.22f);
    title.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
    title.setShadowLayer(dp(5), 0, dp(1), 0xaa000000);
    wordmark.addView(title, new LinearLayout.LayoutParams(-2, -2));
    TextView version = new TextView(context);
    try {
      version.setText(context.getPackageManager().getPackageInfo(context.getPackageName(), 0).versionName);
    } catch (PackageManager.NameNotFoundException ignored) { }
    version.setTextColor(0xffdfa575);
    version.setTextSize(11);
    version.setLetterSpacing(0.24f);
    LinearLayout.LayoutParams versionParams = new LinearLayout.LayoutParams(-2, -2);
    versionParams.topMargin = dp(5);
    wordmark.addView(version, versionParams);
    FrameLayout.LayoutParams brand = new FrameLayout.LayoutParams(-2, -2, Gravity.TOP | Gravity.CENTER_HORIZONTAL);
    brand.topMargin = dp(25);
    controls.addView(wordmark, brand);

    statusDock = new FrameLayout(context);
    statusDock.setBackground(round(0xc010151d, 0x2dffffff, 13));
    FrameLayout.LayoutParams dock = new FrameLayout.LayoutParams(-1, dp(76), Gravity.BOTTOM);
    dock.setMargins(dp(24), 0, dp(24), dp(18));
    controls.addView(statusDock, dock);
    statusContent = new LinearLayout(context);
    statusContent.setOrientation(LinearLayout.VERTICAL);
    FrameLayout.LayoutParams content = new FrameLayout.LayoutParams(-1, -1);
    content.setMargins(dp(16), dp(10), dp(16), dp(10));
    statusDock.addView(statusContent, content);
    wallpaperWarning = new TextView(context);
    wallpaperWarning.setTextColor(0xffffbc86);
    wallpaperWarning.setTextSize(12);
    wallpaperWarning.setText("壁纸不可用，已使用深色背景；资源检查和启动规则不受影响。");
    wallpaperWarning.setVisibility(View.GONE);
    wallpaperWarning.setPadding(0, 0, 0, dp(4));
    statusContent.addView(wallpaperWarning, new LinearLayout.LayoutParams(-1, -2));
    statusText = new TextView(context);
    statusText.setTextColor(0xffe1e5e8);
    statusText.setTextSize(13);
    statusText.setLineSpacing(dp(2), 1.0f);
    statusText.setTextIsSelectable(true);
    statusText.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
    statusText.setText("正在检查已安装资源，存档不会被清除…");
    ScrollView statusScroll = new ScrollView(context);
    statusScroll.setFillViewport(true);
    statusScroll.setVerticalScrollBarEnabled(true);
    statusScroll.addView(statusText, new FrameLayout.LayoutParams(-1, -2));
    statusContent.addView(statusScroll, new LinearLayout.LayoutParams(-1, 0, 1));
    cancelButton = button(context, "取消操作", false);
    cancelButton.setTextSize(12);
    cancelButton.setContentDescription("安全取消当前资源操作，等待文件提供方返回");
    FrameLayout.LayoutParams cancel = new FrameLayout.LayoutParams(dp(104), dp(48), Gravity.RIGHT | Gravity.CENTER_VERTICAL);
    cancel.rightMargin = dp(12);
    statusDock.addView(cancelButton, cancel);
    cancelButton.setVisibility(View.GONE);

    clearButton = button(context, "清除资源包", false);
    clearButton.setTextSize(12);
    clearButton.setContentDescription("清除已导入的游戏资源包，保留存档");
    statusDock.addView(clearButton, new FrameLayout.LayoutParams(cancel));
    updateBusyPresentation(false);

    originalActionButton = button(context, "原版 ZIP / 目录", false);
    recheckActionButton = button(context, "重新检查资源", false);
    originalActionButton.setVisibility(View.GONE);
    recheckActionButton.setVisibility(View.GONE);
    controls.addView(originalActionButton, new FrameLayout.LayoutParams(1, 1));
    controls.addView(recheckActionButton, new FrameLayout.LayoutParams(1, 1));
    setOnApplyWindowInsetsListener((view, insets) -> applySafeInsets(insets));
  }

  private void addEdgeShade(Context context, boolean top) {
    View shade = new View(context);
    shade.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
    GradientDrawable gradient = new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,
        top ? new int[]{0x7a080d14, 0x00080d14} : new int[]{0x00080d14, 0x8a080d14});
    shade.setBackground(gradient);
    addView(shade, new FrameLayout.LayoutParams(-1, dp(top ? 142 : 122), top ? Gravity.TOP : Gravity.BOTTOM));
  }

  private WindowInsets applySafeInsets(WindowInsets insets) {
    safeLeft = insets.getSystemWindowInsetLeft(); safeTop = insets.getSystemWindowInsetTop();
    safeRight = insets.getSystemWindowInsetRight(); safeBottom = insets.getSystemWindowInsetBottom();
    if (insets.getDisplayCutout() != null) {
      safeLeft = Math.max(safeLeft, insets.getDisplayCutout().getSafeInsetLeft());
      safeTop = Math.max(safeTop, insets.getDisplayCutout().getSafeInsetTop());
      safeRight = Math.max(safeRight, insets.getDisplayCutout().getSafeInsetRight());
      safeBottom = Math.max(safeBottom, insets.getDisplayCutout().getSafeInsetBottom());
    }
    FrameLayout.LayoutParams p = (FrameLayout.LayoutParams) controls.getLayoutParams();
    p.setMargins(safeLeft, safeTop, safeRight, safeBottom);
    controls.setLayoutParams(p);
    layoutOverlays(getWidth(), getHeight());
    return insets;
  }

  @Override protected void onAttachedToWindow() {
    super.onAttachedToWindow();
    requestApplyInsets();
  }

  @Override protected void onSizeChanged(int width, int height, int oldWidth, int oldHeight) {
    super.onSizeChanged(width, height, oldWidth, oldHeight);
    layoutOverlays(width, height);
    if (released || loadScheduled || width <= 0 || height <= 0) return;
    loadScheduled = true;
    final int targetWidth = Math.min(width, 2560), targetHeight = Math.min(height, 1440);
    final AssetManager assets = getContext().getApplicationContext().getAssets();
    final WeakReference<LauncherWallpaperView> target = new WeakReference<LauncherWallpaperView>(this);
    final Handler delivery = main;
    loader = Executors.newSingleThreadExecutor(task -> new Thread(task, "cinder-wallpaper-decode"));
    loader.execute(() -> {
      Bitmap decoded = null;
      try { decoded = decode(assets, targetWidth, targetHeight); }
      catch (IOException | RuntimeException | OutOfMemoryError unavailable) { /* bounded fallback below */ }
      final Bitmap result = decoded;
      delivery.post(() -> {
        LauncherWallpaperView current = target.get();
        if (current == null || current.released) {
          // Never displayed; it is safe to reclaim this result immediately.
          if (result != null) result.recycle();
        } else current.acceptWallpaper(result);
      });
    });
  }

  private static Bitmap decode(AssetManager assets, int targetWidth, int targetHeight) throws IOException {
    byte[] encoded;
    try (InputStream input = assets.open(WALLPAPER_ASSET, AssetManager.ACCESS_STREAMING);
         ByteArrayOutputStream bytes = new ByteArrayOutputStream(65536)) {
      byte[] buffer = new byte[16384]; int count, total = 0;
      while ((count = input.read(buffer)) != -1) {
        if (Thread.currentThread().isInterrupted()) throw new IOException("Wallpaper decode cancelled");
        if (count > MAX_ENCODED_BYTES - total) throw new IOException("Wallpaper encoded-byte budget");
        bytes.write(buffer, 0, count); total += count;
      }
      encoded = bytes.toByteArray();
    }
    BitmapFactory.Options bounds = new BitmapFactory.Options(); bounds.inJustDecodeBounds = true;
    BitmapFactory.decodeByteArray(encoded, 0, encoded.length, bounds);
    int width = bounds.outWidth, height = bounds.outHeight;
    if (width <= 0 || height <= 0 || width > 32768 || height > 32768 || (long) width * height > MAX_SOURCE_PIXELS)
      throw new IOException("Wallpaper source-dimension budget");
    int sample = sampleSizeFor(width, height, targetWidth, targetHeight);
    if (Thread.currentThread().isInterrupted()) throw new IOException("Wallpaper decode cancelled");
    BitmapFactory.Options options = new BitmapFactory.Options();
    options.inSampleSize = sample; options.inScaled = false; options.inPreferredConfig = Bitmap.Config.ARGB_8888;
    Bitmap result = BitmapFactory.decodeByteArray(encoded, 0, encoded.length, options);
    if (result == null) throw new IOException("Wallpaper could not be decoded");
    if ((long) result.getWidth() * result.getHeight() > MAX_DECODED_PIXELS ||
        result.getWidth() > MAX_DECODED_EDGE || result.getHeight() > MAX_DECODED_EDGE) {
      result.recycle(); throw new IOException("Wallpaper decoded-byte budget");
    }
    return result;
  }

  static int sampleSizeFor(int width, int height, int targetWidth, int targetHeight) {
    if (width <= 0 || height <= 0 || targetWidth <= 0 || targetHeight <= 0 ||
        width > 32768 || height > 32768 || (long) width * height > MAX_SOURCE_PIXELS)
      throw new IllegalArgumentException("Wallpaper dimension budget");
    int sample = 1;
    // Use rounded-up decoded dimensions so the preallocation bound is conservative.
    while (((long) width + sample - 1) / sample * (((long) height + sample - 1) / sample) > MAX_DECODED_PIXELS ||
        (width + sample - 1) / sample > MAX_DECODED_EDGE || (height + sample - 1) / sample > MAX_DECODED_EDGE ||
        (width / (sample * 2) >= targetWidth && height / (sample * 2) >= targetHeight)) sample *= 2;
    return sample;
  }

  private void acceptWallpaper(Bitmap result) {
    if (loader != null) { loader.shutdown(); loader = null; }
    if (result == null) {
      wallpaperWarning.setVisibility(View.VISIBLE);
      layoutOverlays(getWidth(), getHeight());
      return;
    }
    wallpaperBitmap = result;
    wallpaper.setImageBitmap(result);
    wallpaperWarning.setVisibility(View.GONE);
  }

  private void layoutOverlays(int width, int height) {
    if (width <= 0 || height <= 0) return;
    int availableWidth = width - safeLeft - safeRight;
    FrameLayout.LayoutParams brand = (FrameLayout.LayoutParams) wordmark.getLayoutParams();
    brand.topMargin = availableWidth < dp(620) ? dp(88) : dp(25);
    wordmark.setLayoutParams(brand);
    FrameLayout.LayoutParams dock = (FrameLayout.LayoutParams) statusDock.getLayoutParams();
    int desired = dp(wallpaperWarning.getVisibility() == View.VISIBLE ? 102 : 76);
    dock.height = Math.min(desired, Math.max(dp(54), (height - safeTop - safeBottom) / 4));
    statusDock.setLayoutParams(dock);
  }

  void updateBusyPresentation(boolean value) {
    busy = value;
    if (released) return;
    cancelButton.setVisibility(busy ? View.VISIBLE : View.GONE);
    clearButton.setVisibility(busy ? View.GONE : View.VISIBLE);
    FrameLayout.LayoutParams content = (FrameLayout.LayoutParams) statusContent.getLayoutParams();
    content.rightMargin = dp(128);
    statusContent.setLayoutParams(content);
  }

  @Override protected void onDetachedFromWindow() {
    super.onDetachedFromWindow();
    release();
  }

  /** Call only after detaching. Never recycle a bitmap still referenced by RenderThread. */
  void release() {
    if (released) return;
    released = true;
    if (loader != null) { loader.shutdownNow(); loader = null; }
    wallpaper.setImageDrawable(null);
    // Removing both strong references lets Android safely retire the displayed bitmap
    // after rendering references are gone; immediate Bitmap.recycle would race the GPU.
    wallpaperBitmap = null;
  }

  private FrameLayout.LayoutParams corner(int gravity) {
    FrameLayout.LayoutParams p = new FrameLayout.LayoutParams(dp(136), dp(52), gravity);
    p.setMargins(dp(24), dp(22), dp(24), 0); return p;
  }

  private Button button(Context context, String label, boolean accent) {
    Button button = new Button(context);
    button.setText(label); button.setAllCaps(false); button.setTextSize(15);
    button.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
    button.setMinHeight(0); button.setMinimumHeight(0); button.setMinWidth(0); button.setMinimumWidth(0);
    button.setPadding(dp(12), 0, dp(12), 0);
    button.setTextColor(new ColorStateList(new int[][]{new int[]{-android.R.attr.state_enabled}, new int[]{}},
        new int[]{0x778f999f, Color.WHITE}));
    StateListDrawable states = new StateListDrawable();
    states.addState(new int[]{-android.R.attr.state_enabled}, round(0x9910141a, 0x3356626d, 12));
    states.addState(new int[]{android.R.attr.state_pressed}, round(accent ? 0xeea84925 : 0xe92a2521, 0xfff3b173, 12));
    states.addState(new int[]{}, round(accent ? 0xd8bc512b : 0xb8171d24, accent ? 0xcff39a5c : 0x72dba575, 12));
    button.setBackground(new RippleDrawable(ColorStateList.valueOf(0x28ffffff), states, round(Color.WHITE, Color.TRANSPARENT, 12)));
    button.setElevation(dp(3));
    return button;
  }

  private GradientDrawable round(int fill, int stroke, int radius) {
    GradientDrawable drawable = new GradientDrawable(); drawable.setColor(fill);
    drawable.setCornerRadius(dp(radius)); drawable.setStroke(dp(1), stroke); return drawable;
  }

  private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
}
