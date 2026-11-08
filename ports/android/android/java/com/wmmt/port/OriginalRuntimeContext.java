package com.wmmt.port;

import android.app.Application;
import android.content.Context;
import android.content.ContextWrapper;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/** Routes trusted Chaquopy runtime storage, NOT a same-UID permission sandbox.
 * AndroidPlatform17.2 casts getApplicationContext() to Application, so the facade
 * is necessary: a plain ContextWrapper would silently return the real Application.
 */
public final class OriginalRuntimeContext extends ContextWrapper {
    private final File root;
    private final Application facade;
    private final Map<String, SharedPreferences> preferences = new HashMap<String, SharedPreferences>();

    public OriginalRuntimeContext(Context real) throws IOException {
        super(real.getApplicationContext());
        File noBackup = real.getNoBackupFilesDir().getCanonicalFile();
        File rawParent = new File(noBackup, "re3dxplus-original-runtime");
        File parent = rawParent.getCanonicalFile();
        if (!parent.equals(rawParent) || !noBackup.equals(parent.getParentFile()))
            throw new IOException("Unsafe original runtime parent");
        File rawRoot = new File(parent, "chaquopy17-py313");
        root = rawRoot.getCanonicalFile();
        if (!root.equals(rawRoot) || !parent.equals(root.getParentFile()))
            throw new IOException("Unsafe original runtime root");
        directory(root);
        facade = new RuntimeApplication(this);
    }
    private static File directory(File f) {
        Path p = f.toPath();
        if (Files.isSymbolicLink(p)) throw new IllegalStateException("Runtime directory is a symlink");
        if (!f.isDirectory() && !f.mkdirs() && !f.isDirectory())
            throw new IllegalStateException("Cannot create owned runtime directory: " + f);
        if (!Files.isDirectory(p, LinkOption.NOFOLLOW_LINKS))
            throw new IllegalStateException("Invalid runtime directory: " + f);
        return f;
    }
    private File child(String name) {
        try {
            File raw = new File(root, name);
            File f = raw.getCanonicalFile();
            if (!f.equals(raw) || !f.toPath().startsWith(root.toPath()))
                throw new IllegalArgumentException("Owned runtime path escape/symlink");
            return f;
        } catch (IOException e) { throw new IllegalStateException(e); }
    }
    private File file(String name) {
        if (name == null || name.isEmpty() || name.indexOf('/') >= 0 || name.indexOf('\\') >= 0 || name.equals(".") || name.equals(".."))
            throw new IllegalArgumentException("Invalid runtime filename");
        getFilesDir();
        return child("files/" + name);
    }
    public File getOwnedRoot() { return root; }
    @Override public Context getApplicationContext() { return facade; }
    @Override public File getFilesDir() { return directory(child("files")); }
    @Override public File getCacheDir() { return directory(child("cache")); }
    @Override public File getNoBackupFilesDir() { return directory(child("no-backup")); }
    @Override public File getCodeCacheDir() { return directory(child("code-cache")); }
    @Override public File getDataDir() { return root; }
    @Override public File getDir(String name, int mode) {
        if (name == null || !name.matches("[A-Za-z0-9_.-]+")) throw new IllegalArgumentException("Invalid runtime directory name");
        return directory(child("app_" + name));
    }
    @Override public ApplicationInfo getApplicationInfo() {
        ApplicationInfo info = new ApplicationInfo(super.getApplicationInfo());
        info.dataDir = root.toString();
        info.deviceProtectedDataDir = root.toString();
        // Preserve real signed assets/sourceDir and nativeLibraryDir.
        return info;
    }
    @Override public File getFileStreamPath(String name) { return file(name); }
    @Override public FileInputStream openFileInput(String name) throws FileNotFoundException { return new FileInputStream(file(name)); }
    @Override public FileOutputStream openFileOutput(String name, int mode) throws FileNotFoundException {
        if ((mode & ~(MODE_PRIVATE | MODE_APPEND)) != 0) throw new IllegalArgumentException("Private runtime files only");
        return new FileOutputStream(file(name), (mode & MODE_APPEND) != 0);
    }
    @Override public String[] fileList() { String[] names = getFilesDir().list(); return names == null ? new String[0] : names; }
    @Override public boolean deleteFile(String name) { return file(name).delete(); }
    @Override public synchronized SharedPreferences getSharedPreferences(String name, int mode) {
        // Asset hashes are hints only. Recheck/extract on every fresh conversion process.
        if (!preferences.containsKey(name)) preferences.put(name, new MemoryPreferences());
        return preferences.get(name);
    }
    @Override public synchronized boolean deleteSharedPreferences(String name) { return preferences.remove(name) != null; }
    @Override public boolean moveSharedPreferencesFrom(Context c, String name) { throw new UnsupportedOperationException("No global preferences migration"); }
    private static final class RuntimeApplication extends Application {
        RuntimeApplication(Context base) { attachBaseContext(base); }
        @Override public Context getApplicationContext() { return this; }
    }
    private static final class MemoryPreferences implements SharedPreferences {
        private final Map<String,Object> values = new HashMap<String,Object>();
        @Override public synchronized Map<String,?> getAll() { return new HashMap<String,Object>(values); }
        @Override public synchronized String getString(String k, String d) { return values.containsKey(k) ? (String)values.get(k) : d; }
        @SuppressWarnings("unchecked") @Override public synchronized Set<String> getStringSet(String k, Set<String> d) { return values.containsKey(k) ? new HashSet<String>((Set<String>)values.get(k)) : d; }
        @Override public synchronized int getInt(String k,int d) { return values.containsKey(k)?(Integer)values.get(k):d; }
        @Override public synchronized long getLong(String k,long d) { return values.containsKey(k)?(Long)values.get(k):d; }
        @Override public synchronized float getFloat(String k,float d) { return values.containsKey(k)?(Float)values.get(k):d; }
        @Override public synchronized boolean getBoolean(String k,boolean d) { return values.containsKey(k)?(Boolean)values.get(k):d; }
        @Override public synchronized boolean contains(String k) { return values.containsKey(k); }
        @Override public Editor edit() { return new MemoryEditor(); }
        @Override public void registerOnSharedPreferenceChangeListener(OnSharedPreferenceChangeListener l) { }
        @Override public void unregisterOnSharedPreferenceChangeListener(OnSharedPreferenceChangeListener l) { }
        private final class MemoryEditor implements Editor {
            private final Map<String,Object> updates = new HashMap<String,Object>(); private boolean clear;
            public Editor putString(String k,String v) { updates.put(k,v);return this; }
            public Editor putStringSet(String k,Set<String> v) { updates.put(k,v==null?null:new HashSet<String>(v));return this; }
            public Editor putInt(String k,int v) { updates.put(k,v);return this; }
            public Editor putLong(String k,long v) { updates.put(k,v);return this; }
            public Editor putFloat(String k,float v) { updates.put(k,v);return this; }
            public Editor putBoolean(String k,boolean v) { updates.put(k,v);return this; }
            public Editor remove(String k) { updates.put(k,null);return this; }
            public Editor clear() { clear=true;return this; }
            public boolean commit() { synchronized(MemoryPreferences.this) {
                if(clear) values.clear();
                for(Map.Entry<String,Object> e:updates.entrySet()) { if(e.getValue()==null) values.remove(e.getKey());else values.put(e.getKey(),e.getValue()); }
            } return true; }
            public void apply() { commit(); }
        }
    }
}
