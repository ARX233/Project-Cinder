#!/usr/bin/env python3
"""Host Java and extracted MainActivity upgrade wiring; no APK/device build.

All output is isolated on the external work volume. Synthetic fixtures are not
substitutes for the separately recorded real 1.29 -> current resource regression.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'android/java/com/wmmt/port'


def extract(source, name):
    match = re.search(r'private File ' + name + r'\([^;{}]*\) throws Exception\s*\{', source)
    if not match:
        raise AssertionError('Missing actual MainActivity method: ' + name)
    at, depth, state = match.end()-1, 0, 'code'
    while at < len(source):
        ch, nxt = source[at], source[at+1:at+2]
        if state == 'code':
            if ch == '/' and nxt == '*': state = 'block'; at += 1
            elif ch == '/' and nxt == '/': state = 'line'; at += 1
            elif ch in ('"', "'"): state = ch
            elif ch == '{': depth += 1
            elif ch == '}':
                depth -= 1
                if not depth: return source[match.start():at+1]
        elif state == 'block' and ch == '*' and nxt == '/': state = 'code'; at += 1
        elif state == 'line' and ch == '\n': state = 'code'
        elif state in ('"', "'"):
            if ch == '\\': at += 1
            elif ch == state: state = 'code'
        at += 1
    raise AssertionError('Unclosed actual MainActivity method')


HARNESS = r'''
import com.wmmt.port.*;
import java.io.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.zip.*;
public class MainActivityDataUpgradeHostTest {
 static final String ID="re3dxplus-data-v1", ASSET="re3dxplus-data.zip", BASELINES_ASSET="data-baselines.zip";
 static final DataManifest.Limits LIMITS=new DataManifest.Limits(100,1000000,1000000,1000000);
 static void ok(boolean v){if(!v)throw new AssertionError();}
 interface Task{void run()throws Exception;}
 static void fails(Task t)throws Exception{try{t.run();throw new AssertionError("expected refusal");}catch(IOException expected){}}
 static byte[] bytes(String s)throws Exception{return s.getBytes("UTF-8");}
 static String hash(byte[] data)throws Exception{StringBuilder h=new StringBuilder();for(byte b:MessageDigest.getInstance("SHA-256").digest(data))h.append(String.format("%02x",b&255));return h.toString();}
 static byte[] zip(String value)throws Exception{ByteArrayOutputStream b=new ByteArrayOutputStream();try(ZipOutputStream z=new ZipOutputStream(b)){z.putNextEntry(new ZipEntry("cars/test.wpk"));z.write(bytes(value));z.closeEntry();z.putNextEntry(new ZipEntry("sound/unchanged.wav"));z.write(bytes("stable"));z.closeEntry();}return b.toByteArray();}
 static DataManifest.ZipSource source(byte[] b){return ()->new ByteArrayInputStream(b);}
 static byte[] catalog(Path t,byte[] old)throws Exception{DataManifest m=DataManifest.fromZip(source(old),LIMITS,"legacy-baseline",ID);Path p=t.resolve("baseline.dmf");m.writeAtomic(p,null,LIMITS);ByteArrayOutputStream b=new ByteArrayOutputStream();try(ZipOutputStream z=new ZipOutputStream(b)){z.putNextEntry(new ZipEntry(m.zipSha256+".dmf"));z.write(Files.readAllBytes(p));z.closeEntry();}return b.toByteArray();}
 static class Assets{
  final Map<String,byte[]> entries=new HashMap<String,byte[]>();int catalogOpens;
  String[] list(String dir){return entries.keySet().toArray(new String[0]);}
  InputStream open(String name)throws IOException{if(name.equals(BASELINES_ASSET))catalogOpens++;byte[] data=entries.get(name);if(data==null)throw new FileNotFoundException("Missing packaged asset: "+name);return new ByteArrayInputStream(data);}
 }
 static class HostActivity{
  final Path root;final Assets assets=new Assets();final List<String> progress=new ArrayList<String>();
  HostActivity(Path r)throws Exception{root=r;Files.createDirectories(root.resolve("files"));Files.createDirectories(root.resolve("nobackup"));Files.createDirectories(root.resolve("external/wmmt"));}
  Assets getAssets(){return assets;}
  File getFilesDir(){return root.resolve("files").toFile();}
  File getNoBackupFilesDir(){return root.resolve("nobackup").toFile();}
  void installProgress(String s){progress.add(s);}
  __ACTUAL_PREPARE_DATA__
  Path run()throws Exception{try(DataCoordinator.ProcessLock lock=DataCoordinator.acquire(root.resolve("files/game-data-install.lock"))){ok(lock.valid());return prepareData(root.resolve("external").toFile(),root.resolve("external/wmmt").toFile()).toPath();}}
 }
 static Path legacy(HostActivity a,byte[] old)throws Exception{
  Path r=a.root.resolve("external/re3dxplus-data/"+hash(old)+"-"+UUID.randomUUID());Files.createDirectories(r);
  try(ZipInputStream z=new ZipInputStream(new ByteArrayInputStream(old))){ZipEntry e;while((e=z.getNextEntry())!=null){Path p=r.resolve(e.getName());Files.createDirectories(p.getParent());try(OutputStream out=Files.newOutputStream(p,StandardOpenOption.CREATE_NEW)){byte[] b=new byte[256];int n;while((n=z.read(b))!=-1)out.write(b,0,n);}z.closeEntry();}}
  Files.write(r.resolve(".re3dxplus-install-v1"),bytes(ID+":"+hash(old)));return r;
 }
 static HostActivity env()throws Exception{return new HostActivity(Files.createTempDirectory("main-data-upgrade-"));}
 public static void main(String[] args)throws Exception{
  byte[] old=zip("old"),next=zip("next");ok(!hash(old).equals(hash(next)));
  HostActivity a=env();Path r=legacy(a,old);a.assets.entries.put(ASSET,next);a.assets.entries.put(BASELINES_ASSET,catalog(a.root,old));
  Path save=a.root.resolve("external/wmmt/garage1");Files.write(save,bytes("KEEP-SAVE"));Files.write(r.resolve("unowned-note"),bytes("KEEP-UNKNOWN"));
  ok(!Files.exists(a.root.resolve("nobackup/game-data-state/active.manifest")));
  ok(a.run().equals(r));ok(Arrays.equals(Files.readAllBytes(r.resolve("cars/test.wpk")),bytes("next")));
  ok(Arrays.equals(Files.readAllBytes(save),bytes("KEEP-SAVE")));ok(Arrays.equals(Files.readAllBytes(r.resolve("unowned-note")),bytes("KEEP-UNKNOWN")));
  ok(a.assets.catalogOpens==1);ok(a.progress.stream().anyMatch(s->s.startsWith("Verifying existing")));
  DataManifest active=DataManifest.read(a.root.resolve("nobackup/game-data-state/active.manifest"),LIMITS);ok(active.zipSha256.equals(hash(next)));
  // Current registered resources do not need or read the historical catalog.
  a.assets.entries.remove(BASELINES_ASSET);a.assets.catalogOpens=0;ok(a.run().equals(r));ok(a.assets.catalogOpens==0);
  HostActivity missing=env();Path mr=legacy(missing,old);missing.assets.entries.put(ASSET,next);fails(()->missing.run());
  ok(Arrays.equals(Files.readAllBytes(mr.resolve("cars/test.wpk")),bytes("old")));ok(!Files.exists(missing.root.resolve("nobackup/game-data-state/active.manifest")));
  HostActivity corrupt=env();Path cr=legacy(corrupt,old);corrupt.assets.entries.put(ASSET,next);corrupt.assets.entries.put(BASELINES_ASSET,new byte[]{1,2,3});fails(()->corrupt.run());ok(Arrays.equals(Files.readAllBytes(cr.resolve("cars/test.wpk")),bytes("old")));
  // Pending recovery also has priority over a missing/unrelated legacy catalog.
  HostActivity pending=env();Path base=pending.root.resolve("external/re3dxplus-data"),state=pending.root.resolve("nobackup/game-data-state");DataCoordinator c=new DataCoordinator(base,state,LIMITS);Path pr=c.prepare(source(old),null);
  fails(()->c.prepare(source(next),stage->{if(stage.equals("after-pending"))throw new IOException("interrupt");}));
  pending.assets.entries.put(ASSET,next);ok(pending.run().equals(pr));ok(pending.assets.catalogOpens==0);ok(!Files.exists(state.resolve("pending")));
  HostActivity badActive=env();Path br=legacy(badActive,old);badActive.assets.entries.put(ASSET,next);badActive.assets.entries.put(BASELINES_ASSET,catalog(badActive.root,old));Path bs=badActive.root.resolve("nobackup/game-data-state");Files.createDirectories(bs);Files.write(bs.resolve("active.manifest"),new byte[]{0});fails(()->badActive.run());ok(badActive.assets.catalogOpens==0);ok(Arrays.equals(Files.readAllBytes(br.resolve("cars/test.wpk")),bytes("old")));
  System.out.println("Actual MainActivity.prepareData host wiring PASS: distinct-ZIP legacy, catalog failure, active and pending priority, save protection");
 }
}
'''


class DataUpgradeHostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = Path(tempfile.mkdtemp(prefix='data-upgrade-host-', dir='/Volumes/CodexWork'))
        print('Host validation output: ' + str(cls.output), flush=True)
        for name in ('classes', 'tmp', 'home', 'cache'):
            (cls.output/name).mkdir()
        cls.jdk = Path(os.environ.get('JAVA_HOME', '/Library/Java/JavaVirtualMachines/jdk-25.jdk/Contents/Home'))
        cls.env = dict(os.environ)
        for key in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS', 'JDK_JAVAC_OPTIONS', 'CLASSPATH'):
            cls.env.pop(key, None)
        cls.env.update(HOME=str(cls.output/'home'), TMPDIR=str(cls.output/'tmp'), TMP=str(cls.output/'tmp'), TEMP=str(cls.output/'tmp'), XDG_CACHE_HOME=str(cls.output/'cache'), PYTHONDONTWRITEBYTECODE='1')
        activity = (PACKAGE/'MainActivity.java').read_text()
        harness = cls.output/'MainActivityDataUpgradeHostTest.java'
        harness.write_text(HARNESS.replace('__ACTUAL_PREPARE_DATA__', extract(activity, 'prepareData')))
        files = [PACKAGE/n for n in ('DataManifest.java', 'DataOverlay.java', 'DataCoordinator.java', 'DataBaselines.java')]
        files += [ROOT/'android/tests/com/wmmt/port/DataManifestTest.java']
        files += [ROOT/'tests'/n for n in ('DataOverlayHostTest.java', 'DataCoordinatorHostTest.java', 'DataBaselinesHostTest.java', 'DataLegacyUpgradeHostTest.java')]
        files += [harness]
        cmd = [str(cls.jdk/'bin/javac'), '-J-Djava.io.tmpdir='+str(cls.output/'tmp'), '--release', '8', '-d', str(cls.output/'classes'), *map(str, files)]
        p = subprocess.run(cmd, env=cls.env, cwd=cls.output, text=True, capture_output=True, timeout=90)
        (cls.output/'compile.log').write_text(p.stdout+p.stderr)
        if p.returncode:
            raise AssertionError(p.stdout+p.stderr)

    def run_java(self, name):
        # The original coordinator suite performs many real directory fsyncs on
        # external storage. Its 46th fixture was still progressing at 120s; do
        # not turn that storage latency into a false functional regression.
        try:
            p = subprocess.run([str(self.jdk/'bin/java'), '-Djava.io.tmpdir='+str(self.output/'tmp'), '-cp', str(self.output/'classes'), name], env=self.env, cwd=self.output, text=True, capture_output=True, timeout=int(os.environ.get('WMMT_HOST_TEST_TIMEOUT_SECONDS', '600')))
        except subprocess.TimeoutExpired as exc:
            data = (exc.stdout or b'') + (exc.stderr or b'')
            (self.output/(name+'.timeout.log')).write_bytes(data if isinstance(data, bytes) else data.encode())
            raise
        (self.output/(name+'.log')).write_text(p.stdout+p.stderr)
        self.assertEqual(p.returncode, 0, p.stdout+p.stderr)

    def test_manifest(self): self.run_java('com.wmmt.port.DataManifestTest')
    def test_overlay(self): self.run_java('DataOverlayHostTest')
    def test_existing_coordinator(self): self.run_java('DataCoordinatorHostTest')
    def test_catalog(self): self.run_java('DataBaselinesHostTest')
    def test_legacy_bootstrap(self): self.run_java('DataLegacyUpgradeHostTest')
    # Retained legacy installer regression, not the 1.34 launcher/SAF wiring.
    # Actual 1.34 lifecycle methods are exercised by test_resource_import_activity.py.
    def test_retained_legacy_activity_helper(self): self.run_java('MainActivityDataUpgradeHostTest')

    def test_package_wiring(self):
        source = (ROOT/'build_android.sh').read_text()
        self.assertIn('${GAME_DATA_BASELINES_ZIP:?', source)
        self.assertIn('android/java/com/wmmt/port/DataBaselines.java', source)
        self.assertIn('DataBaselineCompiler --check "$GAME_DATA_BASELINES_ZIP"', source)
        self.assertIn('assets/data-baselines.zip assets/sidecars-index-v1.tsv', source)
        self.assertNotIn('cp "$GAME_DATA_ZIP"', source)
        self.assertNotIn('cp "$CARD_RESOURCES"', source)
        self.assertNotIn('elif [ -f data/story-cutin.bin ]', source)
        self.assertIn('tools/verify_resource_free_apk.py "$APK_OUT" --expected-baselines', source)
        for name in ('ResourceStore.java', 'ResourceMetadata.java', 'SafeResourceZip.java'):
            self.assertIn('android/java/com/wmmt/port/' + name, source)
        self.assertLess(source.index('"$BT/d8"'), source.index('"$OUT/baseline-check" tools/DataBaselineCompiler.java'))


if __name__ == '__main__':
    unittest.main()
