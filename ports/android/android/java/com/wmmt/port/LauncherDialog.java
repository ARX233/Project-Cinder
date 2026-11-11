package com.wmmt.port;

import android.app.Activity;
import android.app.Dialog;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Insets;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.os.Build;
import android.text.Spanned;
import android.text.method.LinkMovementMethod;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.view.WindowMetrics;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.util.function.IntConsumer;

/** Material 3 styling for the launcher's native dialogs. */
final class LauncherDialog extends Dialog {
  private static final int SURFACE = 0xff20262e;
  private static final int ITEM = 0xff2b333d;
  private static final int ON_SURFACE = 0xffeef1f6;
  private static final int BODY = 0xffcdd4de;
  private static final int PRIMARY = 0xffffc29c;
  private static final int ON_PRIMARY = 0xff3d1b08;
  private static final int LINK = 0xffadcfff;

  private final Activity owner;
  private final LinearLayout content, actions;
  private final TextView heading;
  private TextView message;
  private int maxHeight;

  LauncherDialog(Activity owner, String title) {
    super(owner, android.R.style.Theme_Material_Dialog_NoActionBar);
    this.owner = owner;
    setOwnerActivity(owner);
    requestWindowFeature(Window.FEATURE_NO_TITLE);
    setTitle(title);
    setCanceledOnTouchOutside(true);

    LinearLayout panel = new LinearLayout(getContext()) {
      @Override protected void onMeasure(int width, int height) {
        if (maxHeight > 0 && (MeasureSpec.getMode(height) == MeasureSpec.UNSPECIFIED ||
            MeasureSpec.getSize(height) > maxHeight)) {
          height = MeasureSpec.makeMeasureSpec(maxHeight, MeasureSpec.AT_MOST);
        }
        super.onMeasure(width, height);
      }
    };
    panel.setOrientation(LinearLayout.VERTICAL);
    panel.setPadding(dp(24), dp(20), dp(24), dp(12));
    panel.setBackground(shape(SURFACE, 28));

    heading = new TextView(getContext());
    heading.setText(title);
    heading.setTextSize(24);
    heading.setTextColor(ON_SURFACE);
    heading.setAccessibilityHeading(true);
    LinearLayout.LayoutParams titleLayout = new LinearLayout.LayoutParams(-1, -2);
    titleLayout.bottomMargin = dp(12);
    panel.addView(heading, titleLayout);

    ScrollView scroll = new ScrollView(getContext());
    scroll.setOverScrollMode(View.OVER_SCROLL_IF_CONTENT_SCROLLS);
    scroll.setVerticalScrollBarEnabled(true);
    content = new LinearLayout(getContext());
    content.setOrientation(LinearLayout.VERTICAL);
    scroll.addView(content);
    panel.addView(scroll, new LinearLayout.LayoutParams(-1, -2, 1f));

    actions = new LinearLayout(getContext()) {
      @Override protected void onMeasure(int width, int height) {
        int count = getChildCount();
        if (count > 0 && MeasureSpec.getMode(width) != MeasureSpec.UNSPECIFIED) {
          int maxButtonWidth = Math.max(1, (MeasureSpec.getSize(width) - dp(8) * (count - 1)) / count);
          for (int i = 0; i < count; ++i) {
            Button button = (Button)getChildAt(i);
            if (button.getMaxWidth() != maxButtonWidth) button.setMaxWidth(maxButtonWidth);
          }
        }
        super.onMeasure(width, height);
      }
    };
    actions.setGravity(Gravity.END | Gravity.CENTER_VERTICAL);
    LinearLayout.LayoutParams actionLayout = new LinearLayout.LayoutParams(-1, -2);
    actionLayout.topMargin = dp(12);
    panel.addView(actions, actionLayout);
    setContentView(panel);
  }

  @Override protected void onStart() {
    super.onStart();
    Window window = getWindow();
    View parentDecor = owner.getWindow().getDecorView();
    int width = parentDecor.getWidth(), height = parentDecor.getHeight();
    if (Build.VERSION.SDK_INT >= 30) {
      WindowMetrics metrics = owner.getWindowManager().getCurrentWindowMetrics();
      Insets cutout = metrics.getWindowInsets().getInsetsIgnoringVisibility(WindowInsets.Type.displayCutout());
      width = metrics.getBounds().width() - 2 * Math.max(cutout.left, cutout.right);
      height = metrics.getBounds().height() - 2 * Math.max(cutout.top, cutout.bottom);
    }
    if (width <= 0) width = getContext().getResources().getDisplayMetrics().widthPixels;
    if (height <= 0) height = getContext().getResources().getDisplayMetrics().heightPixels;
    maxHeight = Math.max(1, height - dp(32));
    window.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
    window.addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND | WindowManager.LayoutParams.FLAG_FULLSCREEN);
    window.setDimAmount(0.62f);
    window.setGravity(Gravity.CENTER);
    window.setLayout(Math.max(1, Math.min(dp(560), width - dp(48))), -2);
    window.getDecorView().setSystemUiVisibility(parentDecor.getSystemUiVisibility());
  }

  LauncherDialog boldTitle() {
    heading.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
    return this;
  }

  LauncherDialog message(CharSequence text) {
    if (message == null) {
      message = new TextView(getContext());
      message.setTextSize(16);
      message.setTextColor(BODY);
      message.setLinkTextColor(LINK);
      message.setLineSpacing(dp(4), 1.0f);
      content.addView(message, new LinearLayout.LayoutParams(-1, -2));
    }
    message.setText(text);
    if (text instanceof Spanned) message.setMovementMethod(LinkMovementMethod.getInstance());
    return this;
  }

  LauncherDialog choices(String[] labels, IntConsumer select) {
    for (int i = 0; i < labels.length; ++i) {
      final int choice = i;
      Button row = button(labels[i], ITEM, ON_SURFACE, 14);
      row.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
      row.setTextSize(16);
      LinearLayout.LayoutParams item = new LinearLayout.LayoutParams(-1, -2);
      if (i > 0) item.topMargin = dp(6);
      content.addView(row, item);
      row.setOnClickListener(v -> { dismiss(); select.accept(choice); });
    }
    return this;
  }

  LauncherDialog action(String label, Runnable callback) {
    bindDismiss(addAction(label, false), callback);
    return this;
  }

  LauncherDialog primary(String label, Runnable callback) {
    bindDismiss(addAction(label, true), callback);
    return this;
  }

  Button addAction(String label, boolean filled) {
    Button button = button(label, filled ? PRIMARY : Color.TRANSPARENT, filled ? ON_PRIMARY : PRIMARY, 24);
    LinearLayout.LayoutParams layout = new LinearLayout.LayoutParams(-2, -2);
    if (actions.getChildCount() > 0) layout.setMarginStart(dp(8));
    actions.addView(button, layout);
    return button;
  }

  private void bindDismiss(Button button, Runnable callback) {
    button.setOnClickListener(v -> {
      dismiss();
      if (callback != null) callback.run();
    });
  }

  private Button button(String label, int fill, int ink, int radius) {
    Button button = new Button(getContext());
    button.setAllCaps(false);
    button.setText(label);
    button.setTextSize(14);
    button.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
    button.setTextColor(new ColorStateList(new int[][]{{-android.R.attr.state_enabled}, {}},
        new int[]{0xff8f98a4, ink}));
    button.setMinHeight(dp(48));
    button.setMinimumHeight(dp(48));
    button.setMinWidth(0);
    button.setMinimumWidth(0);
    button.setPadding(dp(14), dp(4), dp(14), dp(4));
    button.setStateListAnimator(null);
    button.setBackground(new RippleDrawable(ColorStateList.valueOf((ink & 0x00ffffff) | 0x33000000),
        shape(fill, radius), shape(Color.WHITE, radius)));
    return button;
  }

  private GradientDrawable shape(int color, int radius) {
    GradientDrawable drawable = new GradientDrawable();
    drawable.setColor(color);
    drawable.setCornerRadius(dp(radius));
    return drawable;
  }

  private int dp(int value) {
    return Math.round(value * getContext().getResources().getDisplayMetrics().density);
  }
}
