package com.wmmt.port;

import android.app.Application;
import android.content.Context;
import android.os.Looper;
import android.os.Process;
import android.system.Os;
import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.util.List;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/** Trusted signed-APK conversion entry only. Never loads the game/native MainActivity.
 * Same UID remains fully privileged: this is lifecycle/storage separation, not a sandbox.
 */
public final class OriginalRuntime {
    public static final String EXPECTED_PYTHON = "3.13.16";
    public static final String EXPECTED_NUMPY = "1.26.2";
    public static final String EXPECTED_PILLOW = "11.0.0";
    private static boolean attempted, ready;
    private static OriginalRuntimeContext owned;
    private OriginalRuntime() { }

    public static final class BootstrapException extends Exception {
        private static final long serialVersionUID = 1L;
        public BootstrapException(String message, Throwable cause) { super(message, cause); }
    }
    public static final class EntryPointException extends Exception {
        private static final long serialVersionUID = 1L;
        public EntryPointException(String message) { super(message); }
        public EntryPointException(String message, Throwable cause) { super(message, cause); }
    }
    public static boolean isConversionProcess(Context context) {
        return (context.getPackageName() + ":convert").equals(Application.getProcessName());
    }
    public static void requireConversionProcess(Context context) {
        if (!isConversionProcess(context)) throw new IllegalStateException("Original runtime requires the exact :convert process");
    }
    public static String getNativeLibraryDir(Context context) throws IOException {
        String dir = context.getApplicationContext().getApplicationInfo().nativeLibraryDir;
        if (dir == null || dir.isEmpty()) throw new IOException("APK nativeLibraryDir is unavailable");
        return new File(dir).getCanonicalPath();
    }
    /** Called only by a worker, at most once per converter process; no retry after failure. */
    public static synchronized void start(Context context) throws BootstrapException, EntryPointException {
        requireConversionProcess(context);
        if (Looper.myLooper() == Looper.getMainLooper())
            throw new BootstrapException("Do not bootstrap Python on the service main thread", null);
        if (ready) {
            if (!Python.isStarted()) throw new BootstrapException("Unexpected lost Python runtime", null);
            return;
        }
        if (attempted) throw new BootstrapException("Runtime bootstrap already attempted; a fresh conversion process is required", null);
        attempted = true;
        try {
            if (Python.isStarted()) throw new IllegalStateException("Python was started outside OriginalRuntime");
            requireSignedAssetEntry(context);
            owned = new OriginalRuntimeContext(context);
            File tmp = new File(owned.getCacheDir(), "chaquopy/tmp");
            if (!tmp.isDirectory() && !tmp.mkdirs()) throw new IOException("Cannot create owned Python tmp directory");
            Os.setenv("HOME", owned.getFilesDir().toString(), true);
            Os.setenv("TMPDIR", tmp.toString(), true);
            // Chaquopy's asset loader only accepts paths inside its virtual asset tree.
            // A global cache prefix redirects even bytecode reads outside that tree.
            Os.unsetenv("PYTHONPYCACHEPREFIX");
            Os.setenv("PYTHONDONTWRITEBYTECODE", "1", true);
            Os.setenv("OPENBLAS_NUM_THREADS", "1", true);
            Os.setenv("OMP_NUM_THREADS", "1", true);
            Python.start(new AndroidPlatform(owned));
            Python py = Python.getInstance();
            py.getModule("os").callAttr("chdir", owned.getFilesDir().toString());
            // Only Chaquopy's verified signed-asset extraction/virtual-finder tree is admitted.
            // Neither jobDir nor sourceRoot is ever inserted into sys.path or used as cwd.
            String assets = new File(owned.getFilesDir(), "chaquopy").getCanonicalPath() + File.separator;
            List<PyObject> paths = py.getModule("sys").get("path").asList();
            for (int i = paths.size() - 1; i >= 0; i--) {
                PyObject value = paths.get(i);
                String path = value == null ? "" : value.toJava(String.class);
                if (path.isEmpty() || !new File(path).isAbsolute() ||
                        !new File(path).getCanonicalPath().startsWith(assets)) paths.remove(i);
            }
            if (paths.isEmpty()) throw new IOException("Chaquopy signed asset search path is unavailable");
            ready = true;
        } catch (EntryPointException e) { throw e; }
        catch (Exception | LinkageError e) { throw new BootstrapException("Original conversion runtime bootstrap failed; no retry in this process", e); }
    }
    private static void requireSignedAssetEntry(Context context) throws IOException, EntryPointException {
        boolean pkg = false, engine = false;
        try (InputStream in = context.getAssets().open("chaquopy/app.imy"); ZipInputStream zip = new ZipInputStream(in)) {
            ZipEntry entry;
            while ((entry = zip.getNextEntry()) != null) {
                String n = entry.getName();
                pkg |= n.equals("original_convert/__init__.py") || n.equals("original_convert/__init__.pyc");
                engine |= n.equals("original_convert/engine.py") || n.equals("original_convert/engine.pyc");
                if (pkg && engine) break;
            }
        }
        if (!pkg || !engine) throw new EntryPointException("Signed APK lacks original_convert.engine; converter is not installed (no synthetic fallback)");
    }
    private static void requireAppSpec(Python py, String module, String relative) throws EntryPointException, IOException {
        PyObject spec;
        try { spec = py.getModule("importlib.util").callAttr("find_spec", module); }
        catch (Exception e) { throw new EntryPointException("Cannot locate signed entry: " + module, e); }
        if (spec == null || spec.get("origin") == null) throw new EntryPointException("Missing signed module spec: " + module);
        String origin = spec.get("origin").toJava(String.class);
        String app = new File(owned.getFilesDir(), "chaquopy/AssetFinder/app").getCanonicalPath() + File.separator;
        String expected = app + relative;
        if (!(origin.equals(expected + ".py") || origin.equals(expected + ".pyc")))
            throw new EntryPointException("Refusing entry outside signed Chaquopy app assets: " + module + " origin=" + origin);
    }
    /** Parent Python owns schema/runtime/numeric gates and writes only the private job tree.
     * Return means transport completion only: main must authenticate the report before ACK/publish.
     */
    public static String runJob(Context context, String canonicalJobDir, Object progress) throws Exception {
        start(context);
        Python py = Python.getInstance();
        requireAppSpec(py, "original_convert", "original_convert/__init__");
        py.getModule("original_convert");
        requireAppSpec(py, "original_convert.engine", "original_convert/engine");
        PyObject engine = py.getModule("original_convert.engine");
        PyObject entry = engine.get("run_job");
        if (entry == null || !py.getBuiltins().callAttr("callable", entry).toBoolean())
            throw new EntryPointException("Signed original_convert.engine has no callable run_job");
        PyObject result = entry.call(canonicalJobDir, progress);
        if (result == null) throw new EntryPointException("original_convert.engine.run_job returned None, not a JSON report string");
        return result.toJava(String.class);
    }
    /** Exact self PID/process guard. Never accepts another PID and never kills the UI process. */
    public static void exitSelf(Context context, int expectedSelfPid) {
        requireConversionProcess(context);
        int actual = Process.myPid();
        if (actual != expectedSelfPid || actual <= 0) throw new IllegalStateException("Refusing unexpected converter PID");
        Process.killProcess(actual);
    }
}
