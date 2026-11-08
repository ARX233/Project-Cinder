package com.wmmt.port;

import android.content.ContentResolver;
import android.content.Context;
import android.content.res.AssetFileDescriptor;
import android.database.Cursor;
import android.net.Uri;
import android.os.CancellationSignal;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsContract;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;

import java.io.Closeable;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFilePermission;
import java.nio.file.attribute.PosixFilePermissions;
import java.nio.file.attribute.UserPrincipal;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.text.Normalizer;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.SortedMap;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Read-only SAF input, not publication authority. Caller holds the Store ProcessLock
 * and supplies a Store.begin-minted job. Never writes job.json, seals, extracts,
 * publishes, authenticates a receipt, deletes partials, or changes a user document.
 *
 * Invoke on a background thread. Control offers best-effort source close and
 * CancellationSignal cancellation; a plain Cancel only polls between calls. A
 * provider/kernel which ignores cancellation or close can still block: this API
 * promises neither a hard deadline nor vendor-provider validation.
 */
public final class OriginalSourceBroker {
    private OriginalSourceBroker() { }

    /** Compressed archive limit, deliberately NOT the 2 GiB per-source-file limit. */
    public static final long MAX_ZIP_BYTES = 8L * 1024 * 1024 * 1024;
    public static final long FREE_SPACE_RESERVE = 64L * 1024 * 1024;
    public static final long MAX_SOURCE_BYTES = 2L * 1024 * 1024 * 1024;
    public static final long MAX_TOTAL_BYTES = 32L * 1024 * 1024 * 1024;
    public static final int MAX_CHILDREN = 16384;
    public static final int MAX_NAMESPACE = 65536;
    public static final int MAX_DEPTH = 64;
    public static final int MAX_WRAPPER_DEPTH = 8;
    public static final int MAX_WRAPPER_DIRECTORIES = 256;
    private static final int BUFFER_BYTES = 128 * 1024;
    private static final long MAIN_LENGTH = 24855892L;
    private static final String MAIN_SHA256 =
            "2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6";
    private static final LinkOption[] NOFOLLOW = { LinkOption.NOFOLLOW_LINKS };
    private static final Set<PosixFilePermission> DIR_MODE = PosixFilePermissions.fromString("rwx------");
    private static final Set<PosixFilePermission> FILE_MODE = PosixFilePermissions.fromString("rw-------");

    public interface Cancel { boolean cancelled(); }
    public interface Progress { void update(String stage, long current, long total); }

    public enum Code {
        CANCELLED, INVALID_JOB, INVALID_PROFILE, INVALID_METADATA, NO_ROOT,
        AMBIGUOUS_ROOT, SOURCE_MISSING, SIZE_MISMATCH, HASH_MISMATCH, LIMIT, SPACE
    }
    public static final class Failure extends IOException {
        private static final long serialVersionUID = 1L;
        public final Code code;
        Failure(Code code, String message) { super(message); this.code = code; }
    }

    /** One operation at a time; cancellation is permanent and never closes outputs. */
    public static final class Control implements Cancel {
        private final AtomicBoolean cancelled = new AtomicBoolean();
        private Operation active;
        @Override public boolean cancelled() { return cancelled.get(); }
        /** Returns promptly: potentially blocking provider close runs on a daemon. */
        public void cancel() {
            if (!cancelled.compareAndSet(false, true)) return;
            final List<Owned> snapshot;
            synchronized (this) {
                snapshot = active == null ? Collections.emptyList() : active.snapshot();
            }
            for (Owned resource : snapshot) {
                // At most a signal + cursor/source are live in the SAF adapter.
                // One uncooperative signal/close must not delay another owned FD close.
                // Each close is identity-bound and idempotent, never a raw FD number.
                Thread closer = new Thread(resource::closeQuietly, "OriginalSourceBroker-cancel");
                closer.setDaemon(true);
                closer.start();
            }
        }
        private synchronized void begin(Operation op) throws IOException {
            if (active != null) throw new IOException("Control is already in use");
            active = op;
        }
        private synchronized void end(Operation op) { if (active == op) active = null; }
    }

    public static final class CopiedFile {
        public final String path;
        public final long length;
        public final String sha256;
        /** fstat observation only; a nonregular provider stream is not a regular snapshot. */
        public final String sourceFdKind;
        CopiedFile(String path, long length, String sha256, String kind) {
            this.path = path; this.length = length; this.sha256 = sha256; this.sourceFdKind = kind;
        }
    }
    /** Immutable staging/provisional progress receipt; NEVER trusted publish authority. */
    public static final class Receipt {
        public final List<CopiedFile> files;
        public final long bytes;
        /** Always redacted; no document ID or user filesystem path is retained. */
        public final String rootUri;
        private Receipt(List<CopiedFile> files, long bytes) {
            this.files = Collections.unmodifiableList(new ArrayList<>(files));
            this.bytes = bytes;
            this.rootUri = "content://[redacted]";
        }
    }

    /**
     * Copies an opaque, at-most-8-GiB compressed archive to incoming.zip only.
     * No ZIP metadata is parsed here. UI MUST show MAX_ZIP_BYTES before selection.
     * PythonArchiveSource must subsequently verify all metadata/selected hashes.
     */
    public static Receipt copyZip(Context context, Uri uri, Path jobRoot,
                                  OriginalProfile profile, Cancel cancel, Progress progress)
            throws IOException {
        backgroundOnly();
        requireContent(uri);
        plan(profile); // Validate the audited profile even though ZIP bytes stay opaque here.
        JobArea area = JobArea.open(context.getNoBackupFilesDir().toPath(), jobRoot, profile.sha256);
        return copyZip(new SafProvider(context.getContentResolver(), uri, false), area,
                cancel, progress, SYSTEM_SPACE);
    }

    /** Copies only the immutable APK-audited profile sources, with main first. */
    public static Receipt copyTree(Context context, Uri tree, Path jobRoot,
                                   OriginalProfile profile, Cancel cancel, Progress progress)
            throws IOException {
        backgroundOnly();
        requireContent(tree);
        if (!DocumentsContract.isTreeUri(tree)) throw new IOException("A SAF tree URI is required");
        Plan plan = plan(profile);
        JobArea area = JobArea.open(context.getNoBackupFilesDir().toPath(), jobRoot, profile.sha256);
        return copyTree(new SafProvider(context.getContentResolver(), tree, true), area,
                plan, cancel, progress, SYSTEM_SPACE);
    }

    private static void backgroundOnly() throws IOException {
        if (Looper.myLooper() == Looper.getMainLooper())
            throw new IOException("SAF broker must run on a background thread");
    }
    private static void requireContent(Uri uri) throws IOException {
        if (uri == null || !"content".equals(uri.getScheme()))
            throw new IOException("Only read-only content URIs are accepted");
    }
    private static Failure fail(Code code, String message) { return new Failure(code, message); }

    // Package-private pure boundaries allow an external host harness, without a
    // fake Android runtime or exposing an alternate public production entrypoint.
    static final class Expected {
        final String path; final long length; final String sha256;
        Expected(String path, long length, String sha256) {
            this.path = path; this.length = length; this.sha256 = sha256;
        }
    }
    static final class Plan {
        final List<Expected> files; final long bytes;
        Plan(List<Expected> sources) throws IOException {
            if (sources == null || sources.isEmpty() || sources.size() > MAX_NAMESPACE)
                throw fail(Code.INVALID_PROFILE, "Invalid source inventory");
            List<Expected> ordered = new ArrayList<>(sources);
            Map<String, String> caseless = new HashMap<>();
            Set<String> exact = new HashSet<>();
            long total = 0;
            for (Expected source : ordered) {
                if (source == null || source.length < 0 || source.length > MAX_SOURCE_BYTES
                        || !hex64(source.sha256)) throw fail(Code.INVALID_PROFILE, "Invalid source entry");
                validateRelative(source.path);
                if (!source.path.equals("main") && !source.path.startsWith("data/"))
                    throw fail(Code.INVALID_PROFILE, "Source must be main or below data");
                if (!exact.add(source.path)) throw fail(Code.INVALID_PROFILE, "Duplicate source path");
                String old = caseless.putIfAbsent(fold(source.path), source.path);
                if (old != null) throw fail(Code.INVALID_PROFILE, "Caseless source path alias");
                total = Math.addExact(total, source.length);
                if (total > MAX_TOTAL_BYTES) throw fail(Code.INVALID_PROFILE, "Source total exceeds 32 GiB");
            }
            if (!exact.contains("main")) throw fail(Code.INVALID_PROFILE, "Missing audited main");
            Map<String, String> allPrefixes = new HashMap<>(caseless);
            for (String path : exact) {
                int slash = path.indexOf('/');
                while (slash >= 0) {
                    String prefix = path.substring(0, slash), folded = fold(prefix);
                    if (caseless.containsKey(folded))
                        throw fail(Code.INVALID_PROFILE, "Source file/directory conflict");
                    String previous = allPrefixes.putIfAbsent(folded, prefix);
                    if (previous != null && !previous.equals(prefix))
                        throw fail(Code.INVALID_PROFILE, "Caseless source directory alias");
                    if (allPrefixes.size() > MAX_NAMESPACE)
                        throw fail(Code.INVALID_PROFILE, "Source paths exceed namespace budget");
                    slash = path.indexOf('/', slash + 1);
                }
            }
            // TreeMap order alone is insufficient: main is explicitly FIRST.
            ordered.sort(Comparator.comparing((Expected s) -> !s.path.equals("main"))
                    .thenComparing(s -> s.path));
            this.files = Collections.unmodifiableList(ordered); this.bytes = total;
        }
    }
    static Plan plan(OriginalProfile profile) throws IOException {
        if (profile == null || !hex64(profile.sha256) || profile.sources == null)
            throw fail(Code.INVALID_PROFILE, "Missing immutable profile");
        SortedMap<String, OriginalProfile.Source> sources = profile.sources;
        if (sources.size() > MAX_NAMESPACE)
            throw fail(Code.INVALID_PROFILE, "Source inventory exceeds namespace budget");
        List<Expected> entries = new ArrayList<>();
        for (Map.Entry<String, OriginalProfile.Source> entry : sources.entrySet()) {
            OriginalProfile.Source s = entry.getValue();
            if (s == null || entry.getKey() == null || !entry.getKey().equals(s.path))
                throw fail(Code.INVALID_PROFILE, "Source map key differs from path");
            entries.add(new Expected(s.path, s.length, s.sha256));
        }
        Plan result = new Plan(entries);
        Expected main = result.files.get(0);
        if (main.length != MAIN_LENGTH || !MAIN_SHA256.equals(main.sha256))
            throw fail(Code.INVALID_PROFILE, "Not the audited Android 1.35 main");
        if (profile.sourceBytes != result.bytes)
            throw fail(Code.INVALID_PROFILE, "Profile source byte total mismatch");
        return result;
    }
    private static boolean hex64(String value) { return value != null && value.matches("[0-9a-f]{64}"); }

    static void validateRelative(String path) throws IOException {
        if (path == null || path.isEmpty() || path.startsWith("/") || path.endsWith("/"))
            throw fail(Code.INVALID_METADATA, "Invalid relative source path");
        String[] segments = path.split("/", -1);
        if (segments.length > MAX_DEPTH) throw fail(Code.LIMIT, "Source path exceeds depth 64");
        for (String segment : segments) validateName(segment);
    }
    static void validateName(String name) throws IOException {
        if (name == null || name.isEmpty() || name.length() > 1024
                || !Normalizer.isNormalized(name, Normalizer.Form.NFC)
                || name.equals(".") || name.equals("..") || name.endsWith(".") || name.endsWith(" "))
            throw fail(Code.INVALID_METADATA, "Unsafe or non-NFC document name");
        for (int i = 0; i < name.length();) {
            int cp = name.codePointAt(i);
            int type = Character.getType(cp);
            if (cp == '/' || cp == '\\' || cp == ':' || Character.isISOControl(cp)
                    || type == Character.FORMAT || type == Character.SURROGATE
                    || type == Character.LINE_SEPARATOR || type == Character.PARAGRAPH_SEPARATOR)
                throw fail(Code.INVALID_METADATA, "Unsafe document name character");
            i += Character.charCount(cp);
        }
    }
    // Bounded conservative key, NOT a complete Unicode CaseFold implementation.
    // Stabilization covers multi-round expansions such as ẞ -> ß -> ss;
    // additional aliases may be rejected. Never uses the default locale.
    static String fold(String name) throws IOException {
        String current = Normalizer.normalize(name, Normalizer.Form.NFC);
        for (int round = 0; round < 4; round++) {
            String next = Normalizer.normalize(
                    current.toUpperCase(Locale.ROOT).toLowerCase(Locale.ROOT), Normalizer.Form.NFC);
            if (next.equals(current)) return current;
            current = next;
        }
        throw fail(Code.INVALID_METADATA, "Caseless name did not stabilize within four rounds");
    }

    static final class Document {
        final String id, name; final boolean directory, virtual; final Long size;
        Document(String id, String name, boolean directory, boolean virtual, Long size) {
            this.id = id; this.name = name; this.directory = directory; this.virtual = virtual; this.size = size;
        }
    }
    interface Provider {
        Document root(Operation operation) throws IOException;
        List<Document> children(Document directory, Operation operation) throws IOException;
        ReadHandle open(Document document, Operation operation) throws IOException;
    }
    static class ReadHandle implements Closeable {
        private InputStream input;
        final String fdKind;
        private Closeable descriptor;
        private boolean closed;
        ReadHandle(InputStream input, String kind) { this.input = input; this.fdKind = kind; }
        ReadHandle(Closeable descriptor, String kind) { this.descriptor = descriptor; this.fdKind = kind; }
        synchronized void attach(InputStream stream) throws IOException {
            if (closed) { stream.close(); throw fail(Code.CANCELLED, "Source closed during open"); }
            input = stream;
        }
        synchronized InputStream input() throws IOException {
            if (closed || input == null) throw fail(Code.CANCELLED, "Source handle closed");
            return input;
        }
        @Override public void close() throws IOException {
            final InputStream stream; final Closeable fd;
            synchronized (this) {
                if (closed) return;
                closed = true; stream = input; fd = descriptor;
            }
            IOException error = null;
            // Close the descriptor first: do not wait for InputStream's monitor
            // while its read may be blocked. Neither handle belongs to the caller.
            if (fd != null) try { fd.close(); } catch (IOException e) { error = e; }
            if (stream != null) try { stream.close(); } catch (IOException e) {
                if (error == null) error = e; else error.addSuppressed(e);
            }
            if (error != null) throw error;
        }
    }
    private static final class Owned implements Closeable {
        final Closeable resource; final AtomicBoolean closed = new AtomicBoolean();
        Owned(Closeable resource) { this.resource = resource; }
        @Override public void close() throws IOException {
            if (closed.compareAndSet(false, true)) resource.close();
        }
        void closeQuietly() { try { close(); } catch (IOException | RuntimeException ignored) { } }
    }
    static final class Operation implements Closeable {
        final Cancel cancel;
        final Map<Closeable, Owned> owned = new IdentityHashMap<>();
        Operation(Cancel cancel) throws IOException {
            this.cancel = cancel == null ? () -> false : cancel;
            if (this.cancel instanceof Control) ((Control) this.cancel).begin(this);
            try { check(); } catch (IOException e) { close(); throw e; }
        }
        void check() throws IOException {
            if (cancel.cancelled()) throw fail(Code.CANCELLED, "Source copy cancelled; partial remains private");
        }
        Owned track(Closeable source) throws IOException {
            Owned result;
            synchronized (this) { result = owned.computeIfAbsent(source, Owned::new); }
            if (cancel.cancelled()) { result.closeQuietly(); check(); }
            return result;
        }
        void release(Closeable source) throws IOException {
            Owned value;
            synchronized (this) { value = owned.remove(source); }
            if (value != null) value.close();
        }
        void forget(Closeable source) { synchronized (this) { owned.remove(source); } }
        synchronized List<Owned> snapshot() { return new ArrayList<>(owned.values()); }
        @Override public void close() {
            for (Owned resource : snapshot()) resource.closeQuietly();
            synchronized (this) { owned.clear(); }
            if (cancel instanceof Control) ((Control) cancel).end(this);
        }
    }

    static final class Listing {
        final Map<String, Document> exact;
        Listing(List<Document> rows) throws IOException {
            if (rows == null || rows.size() > MAX_CHILDREN)
                throw fail(Code.LIMIT, "Directory exceeds 16384 rows");
            Map<String, Document> names = new LinkedHashMap<>();
            Set<String> keys = new HashSet<>(), ids = new HashSet<>();
            for (Document row : rows) {
                if (row == null || row.id == null || row.id.isEmpty() || row.id.length() > 4096
                        || (row.size != null && row.size < 0))
                    throw fail(Code.INVALID_METADATA, "Malformed document metadata");
                validateName(row.name); // Even unused unknown payload names must be safe.
                if (names.putIfAbsent(row.name, row) != null || !keys.add(fold(row.name)))
                    throw fail(Code.INVALID_METADATA, "Duplicate exact/caseless document name");
                if (!ids.add(row.id)) throw fail(Code.INVALID_METADATA, "Document-ID path alias");
            }
            exact = Collections.unmodifiableMap(names);
        }
    }
    private static final class Namespace {
        final Provider provider; final Operation operation;
        final Map<String, Listing> cache = new HashMap<>();
        final Map<String, String> idPaths = new HashMap<>();
        int rows;
        Namespace(Provider provider, Operation operation, Document root) throws IOException {
            this.provider = provider; this.operation = operation;
            if (root == null || root.id == null || root.id.isEmpty() || root.id.length() > 4096
                    || !root.directory || root.virtual)
                throw fail(Code.INVALID_METADATA, "Tree root is not an ordinary directory");
            validateName(root.name);
            if (root.size != null && root.size < 0)
                throw fail(Code.INVALID_METADATA, "Negative root metadata size");
            idPaths.put(root.id, "");
        }
        Listing list(Document dir, String path, int depth) throws IOException {
            operation.check();
            if (depth > MAX_DEPTH) throw fail(Code.LIMIT, "Directory depth exceeds 64");
            Listing existing = cache.get(dir.id);
            if (existing != null) return existing;
            Listing result = new Listing(provider.children(dir, operation));
            if (rows > MAX_NAMESPACE - result.exact.size())
                throw fail(Code.LIMIT, "Namespace exceeds 65536 rows");
            rows += result.exact.size();
            for (Document child : result.exact.values()) {
                String childPath = path + "/" + child.name;
                String previous = idPaths.putIfAbsent(child.id, childPath);
                if (previous != null && !previous.equals(childPath))
                    throw fail(Code.INVALID_METADATA, "Directory cycle or cross-path document-ID alias");
            }
            cache.put(dir.id, result);
            return result;
        }
    }
    private static final class Located {
        final Document document; final String path; final int depth;
        Located(Document document, String path, int depth) {
            this.document = document; this.path = path; this.depth = depth;
        }
    }
    private static boolean candidate(Listing listing) {
        Document main = listing.exact.get("main"), data = listing.exact.get("data");
        return main != null && !main.directory && !main.virtual
                && data != null && data.directory && !data.virtual;
    }
    private static Located locateRoot(Namespace namespace, Document root) throws IOException {
        Located selected = new Located(root, "", 0);
        Listing direct = namespace.list(root, "", 0);
        if (candidate(direct)) return selected;
        Deque<Located> queue = new ArrayDeque<>();
        queue.add(selected);
        Located found = null;
        int queried = 1;
        while (!queue.isEmpty()) {
            Located current = queue.removeFirst();
            Listing list = namespace.list(current.document, current.path, current.depth);
            if (current.depth != 0 && candidate(list)) {
                if (found != null) throw fail(Code.AMBIGUOUS_ROOT, "Multiple main+data roots; choose a narrower tree");
                found = current;
                continue; // Never enumerate payload descendants of an accepted root.
            }
            for (Document child : list.exact.values()) {
                if (!child.directory || child.virtual) continue;
                if (current.depth >= MAX_WRAPPER_DEPTH || ++queried > MAX_WRAPPER_DIRECTORIES)
                    throw fail(Code.LIMIT, "Wrapper search exceeds depth 8 or 256 directories; choose a narrower tree");
                queue.addLast(new Located(child, current.path + "/" + child.name, current.depth + 1));
            }
        }
        if (found == null) throw fail(Code.NO_ROOT, "No ordinary exact-case main+data root; no payload read");
        return found;
    }
    private static Document resolve(Namespace namespace, Located root, Expected expected) throws IOException {
        Document current = root.document;
        String currentPath = root.path;
        int depth = root.depth;
        String[] segments = expected.path.split("/");
        for (int i = 0; i < segments.length; i++) {
            Document child = namespace.list(current, currentPath, depth).exact.get(segments[i]);
            if (child == null) throw fail(Code.SOURCE_MISSING, "Missing exact-case audited source: " + expected.path);
            if (child.virtual) throw fail(Code.INVALID_METADATA, "Virtual audited source is not accepted");
            boolean intermediate = i < segments.length - 1;
            if (child.directory != intermediate)
                throw fail(Code.INVALID_METADATA, "Audited source file/directory substitution");
            if (!intermediate) {
                if (child.size != null && child.size != expected.length)
                    throw fail(Code.SIZE_MISMATCH, "Known source size differs from profile: " + expected.path);
                return child;
            }
            current = child; currentPath += "/" + child.name; depth++;
        }
        throw fail(Code.SOURCE_MISSING, "Empty source path");
    }

    interface Space { long available(Path root) throws IOException; }
    private static final Space SYSTEM_SPACE = root -> root.toFile().getUsableSpace();
    private static void requireSpace(Space space, Path root, long bytes) throws IOException {
        if (bytes < 0 || bytes > Long.MAX_VALUE - FREE_SPACE_RESERVE
                || space.available(root) < bytes + FREE_SPACE_RESERVE)
            throw fail(Code.SPACE, "Insufficient private-job space (64 MiB reserve required)");
    }
    static Receipt copyTree(Provider provider, JobArea area, Plan plan, Cancel cancel,
                            Progress progress, Space space) throws IOException {
        try (Operation op = new Operation(cancel)) {
            area.verify();
            report(progress, "validate-tree", 0, plan.bytes);
            Document root = provider.root(op);
            Namespace namespace = new Namespace(provider, op, root);
            Located selected = locateRoot(namespace, root);
            // Metadata only, all required files resolved before any source body is opened.
            List<Document> documents = new ArrayList<>();
            for (Expected expected : plan.files) documents.add(resolve(namespace, selected, expected));
            op.check(); area.verify(); requireSpace(space, area.root, plan.bytes);
            Path incoming = area.freshIncoming();
            List<CopiedFile> copied = new ArrayList<>();
            long done = 0;
            for (int i = 0; i < plan.files.size(); i++) {
                Expected expected = plan.files.get(i);
                op.check(); area.verify(); requireSpace(space, area.root, expected.length);
                Path target = area.target(incoming, expected.path);
                try (FileChannel output = area.newFile(target)) {
                    ReadHandle source = provider.open(documents.get(i), op);
                    if (source == null) throw new IOException("Provider returned no source descriptor");
                    op.track(source);
                    try {
                        CopiedFile result = transfer(source, output, expected.path, expected.length,
                                expected.sha256, op, progress, done, plan.bytes, space, area.root);
                        op.check(); area.verify(); output.force(true);
                        // CREATE_NEW established 0600 (non-executable). The later
                        // VerifiedSnapshot worker, not this provisional broker, owns 0400 sealing.
                        copied.add(result); done += result.length;
                    } finally { op.release(source); }
                }
            }
            op.check(); area.verify(); report(progress, "staged-provisional", done, plan.bytes);
            op.check(); area.verify();
            return new Receipt(copied, done);
        }
    }
    static Receipt copyZip(Provider provider, JobArea area, Cancel cancel,
                           Progress progress, Space space) throws IOException {
        try (Operation op = new Operation(cancel)) {
            area.verify();
            report(progress, "archive-limit-8GiB", 0, MAX_ZIP_BYTES);
            op.check();
            requireSpace(space, area.root, 0);
            Path target = area.root.resolve("incoming.zip");
            try (FileChannel output = area.newFile(target)) {
                Document document = provider.root(op);
                if (document == null || document.directory || document.virtual)
                    throw fail(Code.INVALID_METADATA, "ZIP URI must be an ordinary readable document");
                if (document.size != null && (document.size < 0 || document.size > MAX_ZIP_BYTES))
                    throw fail(Code.LIMIT, "Compressed archive exceeds 8 GiB");
                if (document.size != null) requireSpace(space, area.root, document.size);
                ReadHandle source = provider.open(document, op);
                if (source == null) throw new IOException("Provider returned no source descriptor");
                op.track(source);
                try {
                    CopiedFile result = transfer(source, output, "incoming.zip", MAX_ZIP_BYTES,
                            null, op, progress, 0, MAX_ZIP_BYTES, space, area.root);
                    op.check(); area.verify(); output.force(true);
                    // Provisional 0600; later snapshot sealing is deliberately separate.
                    report(progress, "staged-provisional", result.length, result.length);
                    op.check(); area.verify();
                    return new Receipt(Collections.singletonList(result), result.length);
                } finally { op.release(source); }
            }
        }
    }
    static CopiedFile transfer(ReadHandle source, FileChannel output, String name, long limit,
                               String expectedSha, Operation op, Progress progress, long completed,
                               long total, Space space, Path jobRoot) throws IOException {
        MessageDigest digest = sha256();
        byte[] buffer = new byte[BUFFER_BYTES];
        long count = 0;
        int zeros = 0;
        InputStream input = source.input();
        report(progress, expectedSha == null ? "copy-zip" : name.equals("main") ? "copy-main" : "copy-source",
                completed, total);
        while (true) {
            op.check();
            // The extra byte detects overruns without ever writing the overrun.
            int requested = (int) Math.min(buffer.length, limit - count + 1);
            int n;
            try { n = input.read(buffer, 0, requested); }
            catch (IOException e) { op.check(); throw e; }
            op.check();
            if (n == -1) break;
            if (n < -1 || n > requested) throw new IOException("Provider returned an invalid stream byte count");
            if (n == 0) {
                if (++zeros > 16) throw new IOException("Provider stream repeatedly returned zero bytes");
                continue;
            }
            zeros = 0;
            if (n > limit - count)
                throw fail(expectedSha == null ? Code.LIMIT : Code.SIZE_MISMATCH,
                        expectedSha == null ? "Compressed archive exceeds 8 GiB" : "Source exceeds profile length");
            requireSpace(space, jobRoot, n);
            ByteBuffer bytes = ByteBuffer.wrap(buffer, 0, n);
            while (bytes.hasRemaining()) { op.check(); output.write(bytes); }
            digest.update(buffer, 0, n); count += n;
            report(progress, expectedSha == null ? "copy-zip" : name.equals("main") ? "copy-main" : "copy-source",
                    completed + count, total);
        }
        if (expectedSha != null && count != limit)
            throw fail(Code.SIZE_MISMATCH, "Source shorter than profile length");
        String hash = hex(digest.digest());
        if (expectedSha != null && !hash.equals(expectedSha))
            throw fail(Code.HASH_MISMATCH, "Source SHA-256 differs from audited profile");
        return new CopiedFile(name, count, hash, source.fdKind);
    }
    private static MessageDigest sha256() {
        try { return MessageDigest.getInstance("SHA-256"); }
        catch (NoSuchAlgorithmException impossible) { throw new AssertionError(impossible); }
    }
    private static String hex(byte[] bytes) {
        char[] text = new char[bytes.length * 2];
        char[] digits = "0123456789abcdef".toCharArray();
        for (int i = 0; i < bytes.length; i++) {
            text[i * 2] = digits[(bytes[i] >>> 4) & 15]; text[i * 2 + 1] = digits[bytes[i] & 15];
        }
        return new String(text);
    }
    private static void report(Progress progress, String stage, long current, long total) {
        if (progress != null) progress.update(stage, current, total);
    }

    static final class JobArea {
        final Path root, jobs, noBackup, owner;
        final Object rootKey, jobsKey, ownerKey;
        final UserPrincipal principal;
        final byte[] ownerBytes;
        private JobArea(Path noBackup, Path jobs, Path root, String profileSha) throws IOException {
            this.noBackup = noBackup; this.jobs = jobs; this.root = root; this.owner = root.resolve("owner.tsv");
            principal = Files.getOwner(noBackup, NOFOLLOW);
            checkDirectory(jobs, principal); checkDirectory(root, principal);
            rootKey = key(root); jobsKey = key(jobs);
            BasicFileAttributes attrs = Files.readAttributes(owner, BasicFileAttributes.class, NOFOLLOW);
            if (!attrs.isRegularFile() || attrs.size() > 1024 || !Files.getOwner(owner, NOFOLLOW).equals(principal)
                    || !Files.getPosixFilePermissions(owner, NOFOLLOW).equals(FILE_MODE))
                throw fail(Code.INVALID_JOB, "Missing regular private owner record");
            ownerKey = attrs.fileKey();
            if (rootKey == null || jobsKey == null || ownerKey == null)
                throw fail(Code.INVALID_JOB, "Stable job identity unavailable");
            ownerBytes = readOwner(owner);
            String text = new String(ownerBytes, StandardCharsets.US_ASCII);
            String prefix = "WMMT-ORIGINAL-JOB-1\njob\t" + root.getFileName() + "\nnonce\t";
            String suffix = "\nprofile\t" + profileSha + "\nEND\n";
            if (!text.startsWith(prefix) || !text.endsWith(suffix)
                    || !hex64(text.substring(prefix.length(), text.length() - suffix.length())))
                throw fail(Code.INVALID_JOB, "Owner record is not bound to this job/profile");
            verify();
        }
        static JobArea open(Path trustedNoBackup, Path jobRoot, String profileSha) throws IOException {
            if (trustedNoBackup == null || jobRoot == null || !hex64(profileSha)
                    || !jobRoot.isAbsolute() || !jobRoot.equals(jobRoot.normalize()))
                throw fail(Code.INVALID_JOB, "Job path must be exact absolute canonical path");
            Path noBackup = trustedNoBackup.toRealPath();
            Path jobs = noBackup.resolve("re3dxplus-original-jobs");
            String id = jobRoot.getFileName() == null ? "" : jobRoot.getFileName().toString();
            try {
                if (!UUID.fromString(id).toString().equals(id))
                    throw fail(Code.INVALID_JOB, "Job ID is not a canonical UUID");
            } catch (IllegalArgumentException e) { throw fail(Code.INVALID_JOB, "Job ID is not a canonical UUID"); }
            if (!jobRoot.equals(jobs.resolve(id)) || !jobRoot.equals(jobRoot.toRealPath()))
                throw fail(Code.INVALID_JOB, "Job is outside canonical noBackup job namespace");
            return new JobArea(noBackup, jobs, jobRoot, profileSha);
        }
        void verify() throws IOException {
            if (!root.equals(root.toRealPath()) || !jobs.equals(jobs.toRealPath())
                    || !Files.getOwner(noBackup, NOFOLLOW).equals(principal)
                    || !rootKey.equals(key(root)) || !jobsKey.equals(key(jobs)))
                throw fail(Code.INVALID_JOB, "Job directory identity changed");
            checkDirectory(jobs, principal); checkDirectory(root, principal);
            BasicFileAttributes attrs = Files.readAttributes(owner, BasicFileAttributes.class, NOFOLLOW);
            if (!attrs.isRegularFile() || !ownerKey.equals(attrs.fileKey()) || attrs.size() != ownerBytes.length
                    || !Files.getOwner(owner, NOFOLLOW).equals(principal)
                    || !Files.getPosixFilePermissions(owner, NOFOLLOW).equals(FILE_MODE)
                    || !Arrays.equals(ownerBytes, readOwner(owner)))
                throw fail(Code.INVALID_JOB, "Job owner record changed");
        }
        Path freshIncoming() throws IOException {
            verify();
            Path incoming = root.resolve("incoming");
            Files.createDirectory(incoming, PosixFilePermissions.asFileAttribute(DIR_MODE));
            checkDirectory(incoming, principal);
            return incoming;
        }
        Path target(Path incoming, String relative) throws IOException {
            verify(); validateRelative(relative);
            if (!incoming.equals(root.resolve("incoming"))) throw fail(Code.INVALID_JOB, "Wrong staging root");
            checkDirectory(incoming, principal);
            Path current = incoming;
            String[] segments = relative.split("/");
            for (int i = 0; i < segments.length - 1; i++) {
                current = current.resolve(segments[i]);
                if (!Files.exists(current, NOFOLLOW))
                    Files.createDirectory(current, PosixFilePermissions.asFileAttribute(DIR_MODE));
                checkDirectory(current, principal);
            }
            return current.resolve(segments[segments.length - 1]);
        }
        FileChannel newFile(Path target) throws IOException {
            verify();
            Path normalized = target.toAbsolutePath().normalize();
            if (!normalized.equals(target) || !target.startsWith(root) || target.equals(root))
                throw fail(Code.INVALID_JOB, "Target escaped job");
            Path parent = target.getParent();
            while (!parent.equals(root)) {
                checkDirectory(parent, principal);
                parent = parent.getParent();
            }
            return FileChannel.open(target,
                    new HashSet<>(Arrays.asList(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE,
                            LinkOption.NOFOLLOW_LINKS)), PosixFilePermissions.asFileAttribute(FILE_MODE));
        }
        private static byte[] readOwner(Path path) throws IOException {
            try (FileChannel channel = FileChannel.open(path, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
                ByteBuffer buffer = ByteBuffer.allocate(1025);
                while (buffer.hasRemaining() && channel.read(buffer) != -1) { }
                if (buffer.position() > 1024) throw fail(Code.INVALID_JOB, "Owner record too large");
                return Arrays.copyOf(buffer.array(), buffer.position());
            }
        }
        private static Object key(Path path) throws IOException {
            return Files.readAttributes(path, BasicFileAttributes.class, NOFOLLOW).fileKey();
        }
        private static void checkDirectory(Path path, UserPrincipal owner) throws IOException {
            BasicFileAttributes attrs = Files.readAttributes(path, BasicFileAttributes.class, NOFOLLOW);
            if (!attrs.isDirectory() || !Files.getOwner(path, NOFOLLOW).equals(owner)
                    || !Files.getPosixFilePermissions(path, NOFOLLOW).equals(DIR_MODE))
                throw fail(Code.INVALID_JOB, "Job directory must be private, owned, and no-follow");
        }
    }

    private static final class SafProvider implements Provider {
        private static final String[] COLUMNS = {
            DocumentsContract.Document.COLUMN_DOCUMENT_ID,
            DocumentsContract.Document.COLUMN_DISPLAY_NAME,
            DocumentsContract.Document.COLUMN_MIME_TYPE,
            DocumentsContract.Document.COLUMN_FLAGS,
            DocumentsContract.Document.COLUMN_SIZE
        };
        final ContentResolver resolver; final Uri selected; final boolean tree;
        SafProvider(ContentResolver resolver, Uri selected, boolean tree) {
            this.resolver = resolver; this.selected = selected; this.tree = tree;
        }
        private Cursor query(Uri uri, Operation operation) throws IOException {
            operation.check();
            CancellationSignal signal = new CancellationSignal();
            Closeable signalOwner = signal::cancel;
            operation.track(signalOwner);
            try {
                Cursor cursor = resolver.query(uri, COLUMNS, null, null, null, signal);
                if (cursor == null) throw new IOException("Provider returned no metadata cursor");
                operation.track(cursor);
                operation.check();
                return cursor;
            } finally { operation.forget(signalOwner); }
        }
        @Override public Document root(Operation operation) throws IOException {
            if (!tree) return new Document("opaque-zip", "incoming.zip", false, false, null);
            String id = DocumentsContract.getTreeDocumentId(selected);
            Uri uri = DocumentsContract.buildDocumentUriUsingTree(selected, id);
            Cursor cursor = query(uri, operation);
            try {
                if (!cursor.moveToNext()) throw fail(Code.INVALID_METADATA, "Missing tree-root document");
                Document root = row(cursor);
                if (!id.equals(root.id) || cursor.moveToNext())
                    throw fail(Code.INVALID_METADATA, "Ambiguous tree-root metadata");
                return root;
            } finally { operation.release(cursor); }
        }
        @Override public List<Document> children(Document directory, Operation operation) throws IOException {
            Uri uri = DocumentsContract.buildChildDocumentsUriUsingTree(selected, directory.id);
            Cursor cursor = query(uri, operation);
            try {
                List<Document> result = new ArrayList<>();
                while (cursor.moveToNext()) {
                    operation.check();
                    if (result.size() >= MAX_CHILDREN) throw fail(Code.LIMIT, "Directory exceeds 16384 rows");
                    result.add(row(cursor));
                }
                return result;
            } finally { operation.release(cursor); }
        }
        private static Document row(Cursor cursor) throws IOException {
            int id = cursor.getColumnIndexOrThrow(COLUMNS[0]);
            int name = cursor.getColumnIndexOrThrow(COLUMNS[1]);
            int mime = cursor.getColumnIndexOrThrow(COLUMNS[2]);
            int flags = cursor.getColumnIndexOrThrow(COLUMNS[3]);
            int size = cursor.getColumnIndexOrThrow(COLUMNS[4]);
            if (cursor.getType(id) != Cursor.FIELD_TYPE_STRING
                    || cursor.getType(name) != Cursor.FIELD_TYPE_STRING
                    || cursor.getType(mime) != Cursor.FIELD_TYPE_STRING
                    || cursor.getType(flags) != Cursor.FIELD_TYPE_INTEGER)
                throw fail(Code.INVALID_METADATA, "Incomplete SAF row");
            Long length = null;
            if (!cursor.isNull(size)) {
                if (cursor.getType(size) != Cursor.FIELD_TYPE_INTEGER)
                    throw fail(Code.INVALID_METADATA, "Nonnumeric SAF size");
                long value = cursor.getLong(size);
                if (value >= 0) length = value; // Negative/unknown provider sizes stay unknown.
            }
            String type = cursor.getString(mime);
            if (type == null || type.isEmpty()) throw fail(Code.INVALID_METADATA, "Missing MIME type");
            long flagValue = cursor.getLong(flags);
            if (flagValue < 0 || flagValue > Integer.MAX_VALUE)
                throw fail(Code.INVALID_METADATA, "Invalid SAF flags");
            int bits = (int) flagValue;
            return new Document(cursor.getString(id), cursor.getString(name),
                    DocumentsContract.Document.MIME_TYPE_DIR.equals(type),
                    (bits & DocumentsContract.Document.FLAG_VIRTUAL_DOCUMENT) != 0, length);
        }
        @Override public ReadHandle open(Document document, Operation operation) throws IOException {
            operation.check();
            Uri uri = tree ? DocumentsContract.buildDocumentUriUsingTree(selected, document.id) : selected;
            CancellationSignal signal = new CancellationSignal();
            Closeable signalOwner = signal::cancel;
            operation.track(signalOwner);
            AssetFileDescriptor afd = null;
            ReadHandle handle = null;
            try {
                afd = resolver.openAssetFileDescriptor(uri, "r", signal);
                if (afd == null) throw new IOException("Provider returned no read-only descriptor");
                String kind = "unknown";
                try {
                    ParcelFileDescriptor pfd = afd.getParcelFileDescriptor();
                    StructStat stat = Os.fstat(pfd.getFileDescriptor());
                    kind = OsConstants.S_ISREG(stat.st_mode) ? "regular-observed" : "nonregular-stream";
                } catch (ErrnoException | RuntimeException ignored) { /* Do not pretend pipe==regular. */ }
                handle = new ReadHandle((Closeable) afd, kind);
                operation.track(handle);
                operation.check();
                if (!tree && afd.getLength() > MAX_ZIP_BYTES)
                    throw fail(Code.LIMIT, "Compressed archive descriptor length exceeds 8 GiB");
                if (tree && document.size != null && afd.getLength() >= 0
                        && afd.getLength() != document.size)
                    throw fail(Code.SIZE_MISMATCH, "Descriptor length differs from document metadata");
                handle.attach(afd.createInputStream());
                operation.check();
                return handle;
            } catch (IOException | RuntimeException e) {
                if (handle != null) operation.release(handle);
                else if (afd != null) afd.close();
                operation.check();
                throw e;
            } finally { operation.forget(signalOwner); }
        }
    }
}
