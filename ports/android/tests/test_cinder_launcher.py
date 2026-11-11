#!/usr/bin/env python3
"""Cinder launcher source contracts and actual pure-Java sampling arithmetic.

No Android View, bitmap decode, Activity, Binder, native game, or original material
is executed. The separate real-SDK compile checks Android API usage. Source pins
below protect the 1.35 resource/start/restoration bodies during the visual change.
All generated classes and logs go to a fresh external APFS directory.
"""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_resource_import_activity import method, marked_block, closing_brace

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'android/java/com/wmmt/port/MainActivity.java'
WALLPAPER = MAIN.with_name('LauncherWallpaperView.java')
DIALOG = MAIN.with_name('LauncherDialog.java')
PRESERVED_METHODS = {'startGame': 'b7b135af4186f8bce5458a26ff5a059ece6b18ab2784fc24958baa205424df75', 'onActivityResult': '0d8ef3f4ecf99d796a1955f33a66e36dd56c1660e521ece1c39af4a32e5d2d28', 'startQueuedImport': 'ca0fca2238bfe634d1f35031828ff16727baf38f2e5d4e6371f7f6881780cbef', 'onSaveInstanceState': '0032065adceb15859663c8513f23c89f391ee2a765a0a021c4642541e03bf02c', 'prepareResources': 'fffd0a8120f3ce0184ee0475c70ea1c9a98af067b50003a9311caa02369b4afd', 'cancelResourceOperation': '92556a52160892536d23d4e0f38a77281b0850fb703701f520b4aa13a13526b5', 'closeResourceInput': '20cfd2b3a162e3f1c8699885a3ef47b24597bba733225a2db202b6b552875ebf', 'resourcePath': '3200e596d6f95e9a3c159f2c68670c9069b9de5c7b7bf2a6c74f77c8fbfb5d7d', 'installError': '4ccc225743b2f0b4742e8f6da6044ac47175e62fa5aa0ec4bba5dac8fc2662fd'}
PRESERVED_BLOCKS = {'private static final class OriginalHost': '8e7cf573264cf0b7781d957258758bbf0e35458567f6eb6feeae47149d4863ba', 'private static final class ResolvedResources': '870a04d95fe48946c43fe83c712a0cb792244cc2964da56f7567d6d3fc9ba2b7'}

class CinderLauncherContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = MAIN.read_text(encoding='utf-8')
        cls.wallpaper = WALLPAPER.read_text(encoding='utf-8')
        cls.dialog = DIALOG.read_text(encoding='utf-8')

    def test_existing_resource_and_start_methods_are_unchanged(self):
        for name, expected in PRESERVED_METHODS.items():
            with self.subTest(method=name):
                self.assertEqual(hashlib.sha256(method(self.main, name).encode()).hexdigest(), expected)
        for marker, expected in PRESERVED_BLOCKS.items():
            with self.subTest(block=marker):
                self.assertEqual(hashlib.sha256(marked_block(self.main, marker).encode()).hexdigest(), expected)

    def test_launcher_action_wiring_is_explicit(self):
        body = method(self.main, 'onCreate')
        for text in ['dataPanel = launcherWallpaper;', 'progress = launcherWallpaper.statusText;',
                     'beginButton = launcherWallpaper.launchButton;', 'importButton = launcherWallpaper.selectButton;',
                     'originalButton = launcherWallpaper.originalActionButton;', 'checkButton = launcherWallpaper.recheckActionButton;',
                     'clearButton = launcherWallpaper.clearButton;', 'clearButton.setOnClickListener(v -> confirmResourceClear());',
                     'cancelButton = launcherWallpaper.cancelButton;', 'showResourceSelection()',
                     'beginButton.setOnClickListener(v -> startGame())']:
            self.assertIn(text, body)
        self.assertNotIn('resourceButton(actions', body)
        self.assertNotIn('chooseResourceArchive()', body)
        self.assertNotIn('"导入资源 ZIP"', self.wallpaper)
        self.assertIn('private FrameLayout dataPanel;', self.main)
        self.assertIn('originalController = OriginalConversionController.obtain(originalHost, b)', body)

    def test_notice_requires_acknowledgement_and_follows_launcher_visits(self):
        create = method(self.main, 'onCreate')
        show = method(self.main, 'showLauncherNotice')
        self.assertIn('noticeButton.setOnClickListener(v -> showLauncherNotice())', create)
        self.assertLess(self.wallpaper.index('launchActions.addView(noticeButton'),
                        self.wallpaper.index('launchActions.addView(launchButton'))
        for text in ['"倒狗必死"', 'boldTitle()', 'setCancelable(false)', 'setCanceledOnTouchOutside(false)',
                     '"我已阅读"', 'URLSpan', '"niceapi.net"', '"点此跳转赞助网页"',
                     'new URLSpan("https://afdian.com/a/ProjectCinder")',
                     'if (launcherNotice != null) return;', 'if (!launcherVisible()) return;']:
            self.assertIn(text, show)
        self.assertIn('Typeface.BOLD', self.dialog)
        self.assertIn('setLinkTextColor(LINK)', self.dialog)
        self.assertIn('LinkMovementMethod.getInstance()', self.dialog)
        self.assertIn('launcherNoticePending = true', self.main)
        self.assertIn('launcherNoticePending) showLauncherNotice()', method(self.main, 'onResume'))
        self.assertIn('Intent.CATEGORY_LAUNCHER', method(self.main, 'onNewIntent'))
        stop = method(self.main, 'onStop')
        for text in ['launcherNotice == null', '!awaitingResourcePicker', '!originalController.isPickingSource()']:
            self.assertIn(text, stop)

    def test_dialog_actions_revalidate_current_gate(self):
        gate = method(self.main, 'resourceSelectionAllowed')
        for text in ['!destroyed', 'currentActivity==this', '!isFinishing()', '!resourceBusy',
                     '!awaitingResourcePicker', '!started', 'nativeDataDir==null', '!originalController.isBusy()']:
            self.assertIn(text, gate)
        menu = method(self.main, 'showResourceSelection')
        self.assertGreaterEqual(menu.count('if (!resourceSelectionAllowed()) return;'), 2)
        for text in ['原版 ZIP / 目录一键转换', '导入已转换的资源 ZIP', '重新检查资源',
                     'requestOriginalConversion()', 'chooseResourceArchive()', 'requestResourceRecheck()',
                     'originalController.resumeLast()']:
            self.assertIn(text, menu)
        self.assertIn('originalController.showStartDialog()', method(self.main, 'requestOriginalConversion'))
        self.assertIn('resourceSelectionAllowed()', method(self.main, 'requestResourceRecheck'))
        picker = method(self.main, 'chooseResourceArchive')
        self.assertEqual(picker.count('if (!resourceSelectionAllowed()) return;'), 2)
        self.assertLess(picker.index('awaitingResourcePicker = true;'), picker.index('startActivityForResult'))
        self.assertIn('Intent.ACTION_OPEN_DOCUMENT', picker)

    def test_registration_uses_independent_launcher_button(self):
        self.assertIn('registrationButton.setOnClickListener(v -> showGhostCloudSettings())',
                      method(self.main, 'onCreate'))
        self.assertLess(self.wallpaper.index('resourceActions.addView(selectButton'),
                        self.wallpaper.index('resourceActions.addView(registrationButton'))
        self.assertNotIn('showGhostCloudSettings()', method(self.main, 'showResourceSelection'))
        registration = method(self.main, 'showGhostCloudSettings')
        self.assertNotIn('resourceSelectionAllowed()', registration)
        for text in ['if (!launcherVisible()) return;', 'clipboard.setPrimaryClip',
                     'cloud.refreshRegistration', 'dialog.isShowing()']:
            self.assertIn(text, registration)

    def test_dialog_body_scrolls_independently_of_header_and_actions(self):
        self.assertIn('new ScrollView(getContext())', self.dialog)
        self.assertIn('panel.addView(scroll, new LinearLayout.LayoutParams(-1, -2, 1f))', self.dialog)
        self.assertIn('panel.addView(heading, titleLayout)', self.dialog)
        self.assertIn('panel.addView(actions, actionLayout)', self.dialog)
        self.assertIn('shape(SURFACE, 28)', self.dialog)
        self.assertNotIn('AlertDialog.Builder', self.main)

    def test_controls_never_enable_launch_from_wallpaper_or_dialog(self):
        controls = method(self.main, 'resourceControls')
        self.assertIn('beginButton.setEnabled(installReady && !resourceClearing && !resourceBusy', controls)
        self.assertIn('!controllerBusy', controls)
        self.assertIn('importButton.setEnabled(selectable)', controls)
        self.assertIn('checkButton.setEnabled(selectable)', controls)
        self.assertIn('clearButton.setEnabled(selectable)', controls)
        self.assertIn('updateBusyPresentation(resourceBusy || controllerBusy)', controls)
        self.assertIn('launchButton.setEnabled(false)', self.wallpaper)
        self.assertNotIn('setEnabled(true)', self.wallpaper)
        self.assertNotIn('nativeStart', self.wallpaper)
        self.assertNotIn('installReady', self.wallpaper)

    def test_clear_requires_confirmation_and_excludes_other_operations(self):
        confirm = method(self.main, 'confirmResourceClear')
        clear = method(self.main, 'clearResources')
        self.assertIn('primary("清除资源包", this::clearResources)', confirm)
        self.assertIn('if (!resourceSelectionAllowed()) return;', clear)
        self.assertLess(clear.index('resourceClearing = true;'), clear.index('new Thread('))
        self.assertLess(clear.index('lockInstallProcess(app);'), clear.index('ResourceStore.clearInstalledResources('))
        self.assertIn('installReady = false;', clear)
        self.assertIn('!resourceClearing', method(self.main, 'resourceSelectionAllowed'))
        self.assertIn('resourceClearing ||', method(self.main, 'startGame'))
        self.assertIn('resourceClearing ||', method(self.main, 'prepareResources'))
        self.assertIn('clearButton.setVisibility(busy ? View.GONE : View.VISIBLE)', self.wallpaper)

    def test_wallpaper_uses_only_bounded_fixed_apk_asset(self):
        self.assertIn('"original-convert/launcher-wallpaper.jpg"', self.wallpaper)
        self.assertIn('ImageView.ScaleType.CENTER_CROP', self.wallpaper)
        self.assertIn('assets.open(WALLPAPER_ASSET', self.wallpaper)
        self.assertIn('MAX_ENCODED_BYTES - total', self.wallpaper)
        self.assertIn('inJustDecodeBounds = true', self.wallpaper)
        self.assertIn('options.inSampleSize = sample', self.wallpaper)
        self.assertIn('MAX_DECODED_PIXELS', self.wallpaper)
        self.assertIn('MAX_DECODED_EDGE', self.wallpaper)
        self.assertIn('catch (IOException | RuntimeException | OutOfMemoryError', self.wallpaper)
        for prohibited in ['FileInputStream', 'ContentResolver', 'Uri.parse', 'getExternalFilesDir', 'sourcePath', 'System.loadLibrary']:
            self.assertNotIn(prohibited, self.wallpaper)

    def test_photo_stays_visible_and_fallback_is_accessible(self):
        for text in ['"PROJECT CINDER"', 'getPackageInfo(context.getPackageName(), 0).versionName', '"选择资源"', '"启动游戏"',
                     'wallpaperWarning.setVisibility(View.VISIBLE)', 'setVerticalScrollBarEnabled(true)',
                     'setTextIsSelectable(true)', 'getDisplayCutout()', 'setContentDescription',
                     'originalActionButton.setVisibility(View.GONE)', 'recheckActionButton.setVisibility(View.GONE)']:
            self.assertIn(text, self.wallpaper)
        self.assertIn('setBackgroundColor(0xff0b1017)', self.wallpaper)
        self.assertIn('new WeakReference<LauncherWallpaperView>(this)', self.wallpaper)
        self.assertIn('getApplicationContext().getAssets()', self.wallpaper)
        self.assertIn('newSingleThreadExecutor', self.wallpaper)
        self.assertIn('wallpaper.setImageDrawable(null)', self.wallpaper)
        self.assertIn('wallpaperBitmap = null', self.wallpaper)
        self.assertIn('loader.shutdownNow()', self.wallpaper)
        destroy = method(self.main, 'onDestroy')
        self.assertLess(destroy.index('root.removeView(dataPanel)'), destroy.index('launcherWallpaper.release()'))
        self.assertIn('root.removeView(dataPanel)', method(self.main, 'startGame'))

    def test_actual_sampling_math_is_bounded_on_host_java(self):
        start = self.wallpaper.index('  static int sampleSizeFor(')
        end = closing_brace(self.wallpaper, self.wallpaper.index('{', start)) + 1
        sample = self.wallpaper[start:end]
        java = '''public final class CinderSampleBudget {
static final long MAX_SOURCE_PIXELS=128L*1024*1024,MAX_DECODED_PIXELS=4L*1024*1024;
static final int MAX_DECODED_EDGE=4096;
''' + sample + '''
static int assertions;
static void ok(boolean value){assertions++;if(!value)throw new AssertionError();}
public static void main(String[] args){
  ok(sampleSizeFor(2560,1440,1920,1080)==1);
  ok(sampleSizeFor(2560,1440,1280,720)==2);
  ok(sampleSizeFor(2560,1440,640,360)==4);
  int[][] sources={{1,1},{2560,1440},{4097,1025},{32768,4096},{16384,8192},{10000,10000}};
  for(int[] s:sources)for(int width:new int[]{1,128,640,1080,2560})for(int height:new int[]{1,128,360,720,1440}){
    int n=sampleSizeFor(s[0],s[1],width,height);long w=((long)s[0]+n-1)/n,h=((long)s[1]+n-1)/n;
    ok(n>0&&(n&(n-1))==0);ok(w<=4096&&h<=4096&&w*h<=MAX_DECODED_PIXELS);
  }
  for(int[] invalid:new int[][]{{0,1440,640,360},{2560,-1,640,360},{2560,1440,0,360},{32769,1,1,1},{16384,16384,1,1}}){
    try{sampleSizeFor(invalid[0],invalid[1],invalid[2],invalid[3]);throw new AssertionError("accepted invalid dimensions");}
    catch(IllegalArgumentException expected){assertions++;}
  }
  System.out.println("Actual Cinder sampling math PASS: "+assertions+" assertions");
}}
'''
        parent = Path(os.environ.get('CINDER_LAUNCHER_TEST_ROOT', '/Volumes/CodexWork'))
        parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix='cinder-sampling-', dir=parent))
        (work/'CinderSampleBudget.java').write_text(java, encoding='utf-8')
        jdk = Path(os.environ.get('JAVA_HOME', '/Library/Java/JavaVirtualMachines/jdk-25.jdk/Contents/Home'))
        for command in [[str(jdk/'bin/javac'), '--release','8','-d',str(work),str(work/'CinderSampleBudget.java')],
                        [str(jdk/'bin/java'),'-cp',str(work),'CinderSampleBudget']]:
            result = subprocess.run(command, capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            if command[0].endswith('/java'):
                self.assertIn('PASS: 308 assertions', result.stdout)

if __name__ == '__main__':
    unittest.main(verbosity=2)
