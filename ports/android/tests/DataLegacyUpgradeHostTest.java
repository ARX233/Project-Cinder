import com.wmmt.port.DataCoordinator;
import com.wmmt.port.DataManifest;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.attribute.FileTime;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Collections;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.HashSet;
import java.util.TreeMap;
import java.util.UUID;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import java.util.zip.ZipOutputStream;

/**
 * Synthetic host regression for the legacy-catalog bootstrap. No APK, player save,
 * real release inventory, or original resource is read or written by this test.
 * Distinct generated ZIPs prove the control flow, NOT a shipped 1.29->1.32 chain.
 *
 * Run with an explicit external fixture directory, or set java.io.tmpdir to one:
 *   java -cp <classes> DataLegacyUpgradeHostTest <external-temp-directory>
 * No fixture cleanup is attempted; preserved trees help diagnose a failure.
 */
public final class DataLegacyUpgradeHostTest {
    private static final String ID = "re3dxplus-data-v1";
    private static final String MARKER = ".re3dxplus-install-v1";
    private static final String CHANGED = "pack/changed.bin";
    private static final String SAME = "pack/same.bin";
    private static final String OLD_ONLY = "old-only.bin";
    private static final String ADDED = "fresh/new.bin";
    private static final DataManifest.Limits LIMITS =
            new DataManifest.Limits(100, 100000, 100000, 100000);
    private static Path tempBase;
    private static byte[] oldZip, newZip, thirdZip, unsupportedZip;
    private static String oldHash, newHash, thirdHash, unsupportedHash;
    private static DataManifest oldInventory, newInventory;
    private static int checks;

    private interface IO { void run() throws Exception; }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
        checks++;
    }

    private static IOException rejected(IO task) throws Exception {
        try {
            task.run();
            throw new AssertionError("Expected IOException");
        } catch (IOException expected) {
            checks++;
            return expected;
        }
    }

    private static byte[] bytes(String value) {
        return value.getBytes(StandardCharsets.UTF_8);
    }

    private static String value(Path path) throws IOException {
        return new String(Files.readAllBytes(path), StandardCharsets.UTF_8);
    }

    private static String sha(byte[] bytes) throws Exception {
        StringBuilder text = new StringBuilder();
        for (byte b : MessageDigest.getInstance("SHA-256").digest(bytes))
            text.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
        return text.toString();
    }

    private static DataManifest.ZipSource source(byte[] zip) {
        return () -> new ByteArrayInputStream(zip);
    }

    private static byte[] zip(String version) throws Exception {
        Map<String, String> files = new LinkedHashMap<>();
        files.put(CHANGED, version);
        files.put(SAME, "same immutable bytes");
        if (version.equals("old")) files.put(OLD_ONLY, "old");
        else files.put(ADDED, "new-only-" + version);
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (ZipOutputStream out = new ZipOutputStream(bytes)) {
            for (Map.Entry<String, String> file : files.entrySet()) {
                ZipEntry entry = new ZipEntry(file.getKey());
                entry.setTime(1500000000000L);
                out.putNextEntry(entry);
                out.write(bytes(file.getValue()));
                out.closeEntry();
            }
        }
        return bytes.toByteArray();
    }

    private static DataManifest inventory(byte[] zip, String id) throws Exception {
        return DataManifest.fromZip(source(zip), LIMITS, "catalog-placeholder", id);
    }

    private static Path temp(String name) throws IOException {
        return Files.createTempDirectory(tempBase, "legacy-" + name + "-").toRealPath();
    }

    private static String completion(String hash) { return ID + ":" + hash; }

    private static String interrupted(String oldHash, String newHash) {
        return ID + ":in-progress:" + oldHash + ":" + newHash;
    }

    /** Create a 1.29-style tree directly, deliberately NEVER calling prepare(oldZip). */
    private static Path legacy(Path fixture, byte[] zip, Set<String> omitted,
                               String markerText) throws Exception {
        Path root = Files.createDirectories(fixture.resolve("data").resolve(
                sha(zip) + "-" + UUID.randomUUID()));
        try (ZipInputStream input = new ZipInputStream(new ByteArrayInputStream(zip))) {
            ZipEntry entry;
            while ((entry = input.getNextEntry()) != null) {
                boolean skip = false;
                for (String omit : omitted) {
                    if (entry.getName().equals(omit) || entry.getName().startsWith(omit + "/"))
                        skip = true;
                }
                if (skip) continue;
                Path target = root.resolve(entry.getName());
                Files.createDirectories(target.getParent());
                Files.copy(input, target);
            }
        }
        if (markerText != null) Files.write(root.resolve(MARKER), bytes(markerText));
        Files.write(root.resolve("personal.bin"), bytes("unknown resource-root file"));
        Files.createDirectories(fixture.resolve("wmmt"));
        Files.write(fixture.resolve("wmmt/garage1"), bytes("PLAYER GARAGE SENTINEL"));
        Files.write(fixture.resolve("wmmt/records1"), bytes("PLAYER RECORDS SENTINEL"));
        Files.write(fixture.resolve("wmmt/slot"), bytes("1\n"));
        return root;
    }

    private static Path legacy(Path fixture) throws Exception {
        return legacy(fixture, oldZip, Collections.emptySet(), completion(oldHash));
    }

    private static DataCoordinator.Baselines catalog() {
        return hash -> hash.equals(oldHash) ? oldInventory : null;
    }

    private static DataCoordinator coordinator(Path fixture, DataCoordinator.Baselines history) {
        // Keep the Coordinator's directory sync mockable. DataOverlay's real host
        // directory-sync implementation is still exercised by successful updates.
        return new DataCoordinator(fixture.resolve("data"), fixture.resolve("state"),
                LIMITS, path -> {}, history);
    }

    private static Path active(Path fixture) { return fixture.resolve("state/active.manifest"); }

    /** File bytes, names, and entry types; never follows a symbolic link. */
    private static Map<String, String> snapshot(Path root) throws Exception {
        Map<String, String> tree = new TreeMap<>();
        try (java.util.stream.Stream<Path> stream = Files.walk(root)) {
            Iterator<Path> paths = stream.iterator();
            while (paths.hasNext()) {
                Path path = paths.next();
                String relative = root.relativize(path).toString();
                if (Files.isSymbolicLink(path))
                    tree.put(relative, "link:" + Files.readSymbolicLink(path));
                else if (Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS))
                    tree.put(relative, "directory");
                else tree.put(relative, "file:" + sha(Files.readAllBytes(path)));
            }
        }
        return tree;
    }

    private static void assertRejectedBeforePublish(Path fixture,
            DataCoordinator.Baselines history) throws Exception {
        Map<String, String> beforeData = snapshot(fixture.resolve("data"));
        Map<String, String> beforeSave = snapshot(fixture.resolve("wmmt"));
        rejected(() -> coordinator(fixture, history).prepare(source(newZip), null));
        check(!Files.exists(active(fixture), LinkOption.NOFOLLOW_LINKS),
                "Rejected bootstrap published active baseline");
        check(!Files.exists(fixture.resolve("state/pending"), LinkOption.NOFOLLOW_LINKS),
                "Rejected bootstrap started a transaction");
        check(snapshot(fixture.resolve("data")).equals(beforeData),
                "Rejected bootstrap changed resource or unknown tree");
        check(snapshot(fixture.resolve("wmmt")).equals(beforeSave),
                "Rejected bootstrap changed save tree");
    }

    private static void verifyReady(Path fixture, Path root, byte[] expectedZip) throws Exception {
        DataManifest expected = inventory(expectedZip, ID);
        DataManifest actual = DataManifest.read(active(fixture), LIMITS);
        check(actual.zipSha256.equals(expected.zipSha256), "Wrong active ZIP");
        check(actual.resourceDirectory.equals(root.getFileName().toString()), "Changed root binding");
        check(actual.canonicalId.equals(ID), "Changed canonical ID");
        check(actual.files().keySet().equals(expected.files().keySet()), "Wrong manifest paths");
        for (DataManifest.Entry file : expected.files().values()) {
            Path path = root.resolve(file.path);
            check(Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS), "Missing new resource");
            check(Files.size(path) == file.length && sha(Files.readAllBytes(path)).equals(file.sha256),
                    "Wrong new bytes: " + file.path);
        }
        check(value(root.resolve(MARKER)).equals(completion(expected.zipSha256)),
                "Completion marker not published");
        check(!Files.exists(fixture.resolve("state/pending")), "Pending survived ready");
        check(!Files.exists(fixture.resolve("state/overlay.journal")), "Overlay journal survived ready");
        check(value(fixture.resolve("wmmt/garage1")).equals("PLAYER GARAGE SENTINEL"), "Save changed");
        check(value(fixture.resolve("wmmt/records1")).equals("PLAYER RECORDS SENTINEL"), "Records changed");
        check(value(root.resolve("personal.bin")).equals("unknown resource-root file"), "Unknown changed");
    }

    private static void directWithInertSiblings() throws Exception {
        for (boolean olderChosenRoot : new boolean[] {true, false}) {
            Path fixture = temp("direct-cross-zip");
            Path chosen = legacy(fixture);
            Path unsupported = legacy(fixture, unsupportedZip, Collections.emptySet(),
                    completion(unsupportedHash));
            Path markerless = legacy(fixture, thirdZip, Collections.emptySet(), null);
            Path inProgress = legacy(fixture, oldZip, Collections.emptySet(),
                    interrupted(oldHash, newHash));
            Path arbitrary = Files.createDirectory(fixture.resolve("data/user-folder"));
            Files.write(arbitrary.resolve("private.txt"), bytes("arbitrary unknown"));
            long early = 1400000000000L, late = 1700000000000L;
            Files.setLastModifiedTime(chosen, FileTime.fromMillis(olderChosenRoot ? early : late));
            Files.setLastModifiedTime(unsupported, FileTime.fromMillis(olderChosenRoot ? late : early));
            Map<String, String> unknownBefore = snapshot(unsupported);
            Map<String, String> markerlessBefore = snapshot(markerless);
            Map<String, String> progressBefore = snapshot(inProgress);
            Map<String, String> arbitraryBefore = snapshot(arbitrary);
            Map<String, String> saveBefore = snapshot(fixture.resolve("wmmt"));
            check(!Files.exists(active(fixture)), "Fixture accidentally has active manifest");
            check(coordinator(fixture, catalog()).prepare(source(newZip), null).equals(chosen),
                    "Direct legacy bootstrap chose another resource root");
            verifyReady(fixture, chosen, newZip);
            check(!Files.exists(chosen.resolve(OLD_ONLY)), "Unmodified old-only resource not retired");
            check(snapshot(unsupported).equals(unknownBefore), "Unsupported sibling changed");
            check(snapshot(markerless).equals(markerlessBefore), "Markerless sibling changed");
            check(snapshot(inProgress).equals(progressBefore), "In-progress sibling changed");
            check(snapshot(arbitrary).equals(arbitraryBefore), "Arbitrary sibling changed");
            check(snapshot(fixture.resolve("wmmt")).equals(saveBefore), "Save path or bytes changed");
        }
        System.out.println("PASS distinct-ZIP/no-active catalog bootstrap; inert siblings/save/unknown preserved; mtime irrelevant");
    }

    private static void recognizedAmbiguity() throws Exception {
        for (int kind = 0; kind < 3; kind++) {
            for (boolean damagedFirst : new boolean[] {true, false}) {
                Path fixture = temp("multiple-recognized");
                byte[] secondZip = kind == 1 ? thirdZip : kind == 2 ? newZip : oldZip;
                String secondHash = sha(secondZip);
                Set<String> missing = Collections.singleton(CHANGED);
                if (damagedFirst) legacy(fixture, secondZip, missing, completion(secondHash));
                legacy(fixture);
                if (!damagedFirst) legacy(fixture, secondZip, missing, completion(secondHash));
                DataManifest thirdInventory = inventory(thirdZip, ID);
                DataCoordinator.Baselines history = hash -> hash.equals(oldHash) ? oldInventory
                        : hash.equals(thirdHash) ? thirdInventory : null;
                Map<String, String> before = snapshot(fixture.resolve("data"));
                IOException error = rejected(() -> coordinator(fixture, history).prepare(source(newZip), null));
                check(error.getMessage().contains("Multiple recognized"),
                        "Damaged recognized root was filtered or verified before counting");
                check(!Files.exists(active(fixture)), "Ambiguous roots registered");
                check(snapshot(fixture.resolve("data")).equals(before), "Ambiguity changed a root");
            }
        }
        System.out.println("PASS multiple recognized roots counted before verification, including damaged current root and reversed insertion order");
    }

    private static void resourceRejections() throws Exception {
        for (String missing : new String[] {CHANGED, SAME, OLD_ONLY}) {
            Path fixture = temp("missing-resource");
            legacy(fixture, oldZip, Collections.singleton(missing), completion(oldHash));
            assertRejectedBeforePublish(fixture, catalog());
        }
        for (String modified : new String[] {CHANGED, SAME, OLD_ONLY}) {
            Path fixture = temp("modified-resource");
            Path root = legacy(fixture);
            Files.write(root.resolve(modified), bytes("USER MODIFICATION"));
            assertRejectedBeforePublish(fixture, catalog());
        }
        Path mixedFixture = temp("lost-state-mixed");
        Path mixedRoot = legacy(mixedFixture);
        Files.write(mixedRoot.resolve(CHANGED), bytes("new")); // Valid new bytes + other old bytes.
        assertRejectedBeforePublish(mixedFixture, catalog());

        Path leafFixture = temp("symlink-leaf");
        Path leafRoot = legacy(leafFixture, oldZip, Collections.singleton(CHANGED), completion(oldHash));
        Path outside = Files.write(leafFixture.resolve("outside.bin"), bytes("old"));
        Files.createSymbolicLink(leafRoot.resolve(CHANGED), outside);
        assertRejectedBeforePublish(leafFixture, catalog());
        check(value(outside).equals("old"), "Symlink target changed");

        Path parentFixture = temp("symlink-parent");
        Path parentRoot = legacy(parentFixture, oldZip, Collections.singleton("pack"), completion(oldHash));
        Path outsideDir = Files.createDirectory(parentFixture.resolve("outside-pack"));
        Files.write(outsideDir.resolve("changed.bin"), bytes("old"));
        Files.write(outsideDir.resolve("same.bin"), bytes("same immutable bytes"));
        Files.createSymbolicLink(parentRoot.resolve("pack"), outsideDir);
        Map<String, String> outsideBefore = snapshot(outsideDir);
        assertRejectedBeforePublish(parentFixture, catalog());
        check(snapshot(outsideDir).equals(outsideBefore), "Symlink parent target changed");

        Path markerFixture = temp("symlink-marker");
        Path markerRoot = legacy(markerFixture, oldZip, Collections.emptySet(), null);
        Path markerTarget = Files.write(markerFixture.resolve("outside-marker"), bytes(completion(oldHash)));
        Files.createSymbolicLink(markerRoot.resolve(MARKER), markerTarget);
        assertRejectedBeforePublish(markerFixture, catalog());

        Path rootFixture = temp("symlink-root");
        Path outsideFixture = temp("symlink-root-target");
        Path outsideRoot = legacy(outsideFixture);
        Files.createDirectories(rootFixture.resolve("data"));
        Files.createDirectories(rootFixture.resolve("wmmt"));
        Files.write(rootFixture.resolve("wmmt/garage1"), bytes("PLAYER GARAGE SENTINEL"));
        Files.createSymbolicLink(rootFixture.resolve("data").resolve(
                oldHash + "-" + UUID.randomUUID()), outsideRoot);
        Map<String, String> outsideRootBefore = snapshot(outsideRoot);
        assertRejectedBeforePublish(rootFixture, catalog());
        check(snapshot(outsideRoot).equals(outsideRootBefore), "Symlink root target changed");
        System.out.println("PASS missing/modified/mixed old-new resources and leaf/parent/marker/root symlinks reject before adoption");
    }

    private static void privateStateRejectionsAndResume() throws Exception {
        for (String name : new String[] {"active.manifest", "pending", "old.manifest", "new.manifest", "overlay.journal", "txn-unowned"}) {
            Path fixture = temp("bad-private-state");
            legacy(fixture);
            Files.createDirectories(fixture.resolve("state"));
            Path unknown = fixture.resolve("state").resolve(name);
            if (name.startsWith("txn-")) {
                Files.createDirectory(unknown);
                Files.write(unknown.resolve("new.manifest"), bytes("unowned snapshot"));
            } else Files.write(unknown, bytes("invalid or unbound state"));
            Map<String, String> stateBefore = snapshot(fixture.resolve("state"));
            Map<String, String> dataBefore = snapshot(fixture.resolve("data"));
            int[] lookups = {0};
            DataCoordinator.Baselines history = hash -> {lookups[0]++; return oldInventory;};
            rejected(() -> coordinator(fixture, history).prepare(source(newZip), null));
            check(lookups[0] == 0, "Bad registered/journal state fell back to catalog");
            check(snapshot(fixture.resolve("state")).equals(stateBefore), "Bad private state changed");
            check(snapshot(fixture.resolve("data")).equals(dataBefore), "Bad state changed resources");
        }
        Path fixture = temp("valid-pending-resume");
        Path root = legacy(fixture);
        boolean[] fired = {false};
        rejected(() -> coordinator(fixture, catalog()).prepare(source(newZip), stage -> {
            if (stage.equals("overlay:after-replace")) {fired[0] = true; throw new IOException("interrupt update");}
        }));
        check(fired[0] && Files.exists(fixture.resolve("state/pending")), "Pending fixture not created");
        DataCoordinator.Baselines unavailableHistory = hash -> {throw new IOException("catalog must not be consulted while resuming");};
        check(coordinator(fixture, unavailableHistory).prepare(source(newZip), null).equals(root),
                "Valid pending recovery fell back to legacy discovery");
        verifyReady(fixture, root, newZip);
        System.out.println("PASS bad active/pending/orphan state preserved without fallback; valid pending resumes before catalog");
    }

    private static void noEligibleDoesNotInitialize() throws Exception {
        for (int kind = 0; kind < 3; kind++) {
            Path fixture = temp("no-eligible");
            if (kind == 0) legacy(fixture, unsupportedZip, Collections.emptySet(), completion(unsupportedHash));
            else if (kind == 1) legacy(fixture, oldZip, Collections.emptySet(), null);
            else legacy(fixture, oldZip, Collections.emptySet(), interrupted(oldHash, newHash));
            assertRejectedBeforePublish(fixture, catalog());
        }
        System.out.println("PASS unsupported-only/markerless-only/in-progress-only bases are not treated as fresh installations");
    }

    private static void put(DataOutputStream out, String value) throws IOException {
        byte[] data = bytes(value);
        out.writeInt(data.length);
        out.write(data);
    }

    /** Deliberately invalid catalog inventory fixture: valid DMF1, correct ZIP, zero files. */
    private static DataManifest emptyCatalog(String zipHash) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        DataOutputStream out = new DataOutputStream(bytes);
        out.writeInt(0x444d4631); // Existing DMF1 test fixture, not a new production format.
        out.writeInt(1);
        put(out, zipHash);
        put(out, "catalog-placeholder");
        put(out, ID);
        out.writeInt(0);
        out.writeInt(0x454e4421);
        out.flush();
        byte[] body = bytes.toByteArray();
        out.write(MessageDigest.getInstance("SHA-256").digest(body));
        out.flush();
        return DataManifest.read(new ByteArrayInputStream(bytes.toByteArray()), LIMITS);
    }

    private static void wrongCatalogRejected() throws Exception {
        DataManifest[] wrong = {
            inventory(unsupportedZip, ID),
            inventory(oldZip, "wrong-canonical-id"),
            emptyCatalog(oldHash)
        };
        for (DataManifest invalid : wrong) {
            Path fixture = temp("wrong-catalog");
            legacy(fixture);
            assertRejectedBeforePublish(fixture, hash -> hash.equals(oldHash) ? invalid : null);
        }
        Path fixture = temp("catalog-read-error");
        legacy(fixture);
        assertRejectedBeforePublish(fixture, hash -> {
            if (hash.equals(oldHash)) throw new IOException("recognized catalog asset damaged");
            return null;
        });
        System.out.println("PASS wrong catalog ZIP/ID/empty inventory and recognized-asset read failure cannot register baseline");
    }

    private static void adoptionAndOverlayFaults() throws Exception {
        String[] stages = {
            "before-legacy-verify", "after-legacy-verify", "before-legacy-publish", "after-legacy-publish",
            "after-pending", "after-marker-invalidate", "after-marker-invalidate-sync",
            "overlay:after-journal-rename", "overlay:after-replace", "before-commit", "after-commit",
            "before-confirm", "after-confirm", "before-marker-publish", "after-marker-publish"
        };
        for (String stop : stages) {
            Path fixture = temp("fault");
            Path root = legacy(fixture);
            Map<String, String> saveBefore = snapshot(fixture.resolve("wmmt"));
            boolean[] fired = {false};
            rejected(() -> coordinator(fixture, catalog()).prepare(source(newZip), stage -> {
                if (stage.equals(stop)) {fired[0] = true; throw new IOException("fault at " + stop);}
            }));
            check(fired[0], "Fault hook not reached: " + stop);
            if (stop.equals("before-legacy-verify") || stop.equals("after-legacy-verify") || stop.equals("before-legacy-publish")) {
                check(!Files.exists(active(fixture)), "Baseline published before requested boundary");
                check(value(root.resolve(CHANGED)).equals("old"), "Resource changed before baseline");
            }
            if (stop.equals("after-legacy-publish")) {
                check(DataManifest.read(active(fixture), LIMITS).zipSha256.equals(oldHash), "Old baseline not committed first");
                check(value(root.resolve(CHANGED)).equals("old"), "Resource changed before original overlay");
            }
            check(coordinator(fixture, catalog()).prepare(source(newZip), null).equals(root),
                    "Fault recovery changed root: " + stop);
            verifyReady(fixture, root, newZip);
            check(snapshot(fixture.resolve("wmmt")).equals(saveBefore), "Fault recovery changed save tree");
        }
        System.out.println("PASS " + stages.length + " fault-and-retry boundaries (four adoption hooks plus original journal/overlay/commit/publication)");
    }

    private static void markerChangesAndBaselineSyncFailure() throws Exception {
        for (String stage : new String[] {"after-legacy-verify", "before-legacy-publish"}) {
            Path fixture = temp("marker-change");
            Path root = legacy(fixture);
            rejected(() -> coordinator(fixture, catalog()).prepare(source(newZip), at -> {
                if (at.equals(stage)) Files.write(root.resolve(MARKER), bytes("changed marker"));
            }));
            check(!Files.exists(active(fixture)) && !Files.exists(fixture.resolve("state/pending")),
                    "Changed marker was registered");
            check(value(root.resolve(CHANGED)).equals("old"), "Changed marker allowed resource writes");
            check(value(root.resolve(MARKER)).equals("changed marker"), "Changed marker was overwritten");
        }
        Path fixture = temp("baseline-sync-failure");
        Path root = legacy(fixture);
        Path state = fixture.resolve("state").toAbsolutePath();
        boolean[] failed = {false};
        DataCoordinator noStateSync = new DataCoordinator(fixture.resolve("data"), state, LIMITS,
                path -> {if (path.equals(state)) {failed[0] = true; throw new IOException("state sync failed");}}, catalog());
        rejected(() -> noStateSync.prepare(source(newZip), null));
        check(failed[0], "State fsync failure not exercised");
        check(value(root.resolve(CHANGED)).equals("old") && !Files.exists(state.resolve("pending")),
                "Resource modified before old-baseline durability barrier");
        check(DataManifest.read(active(fixture), LIMITS).zipSha256.equals(oldHash),
                "Old manifest publication was not atomic");
        check(coordinator(fixture, catalog()).prepare(source(newZip), null).equals(root),
                "Baseline-sync retry could not use active path");
        verifyReady(fixture, root, newZip);
        System.out.println("PASS marker changes block adoption; baseline directory-sync failure prevents resource writes and retries safely");
    }

    private static void copyResourceTree(Path source, Path destination) throws Exception {
        try (java.util.stream.Stream<Path> stream = Files.walk(source)) {
            Iterator<Path> paths = stream.iterator();
            while (paths.hasNext()) {
                Path from = paths.next();
                Path to = destination.resolve(source.relativize(from));
                if (Files.isSymbolicLink(from)) Files.createSymbolicLink(to, Files.readSymbolicLink(from));
                else if (Files.isDirectory(from, LinkOption.NOFOLLOW_LINKS)) Files.createDirectories(to);
                else Files.copy(from, to);
            }
        }
    }

    private static void nextVersionAfterRegistryLoss() throws Exception {
        Path first = temp("series-first");
        Path root = legacy(first);
        coordinator(first, catalog()).prepare(source(newZip), null);
        verifyReady(first, root, newZip);
        check(root.getFileName().toString().startsWith(oldHash + "-"), "Updater renamed initial resource root");

        // Copy ONLY the resource/save trees into a new fixture, not private state.
        // This simulates registry loss without deleting or moving any source tree.
        Path lost = temp("series-registry-lost");
        Path reboundRoot = lost.resolve("data").resolve(root.getFileName());
        Files.createDirectories(reboundRoot.getParent());
        copyResourceTree(root, reboundRoot);
        copyResourceTree(first.resolve("wmmt"), lost.resolve("wmmt"));
        Map<String, String> savesBefore = snapshot(lost.resolve("wmmt"));
        check(!Files.exists(active(lost)), "Lost-state fixture copied private state");
        check(value(reboundRoot.resolve(MARKER)).equals(completion(newHash)) && !oldHash.equals(newHash),
                "Fixture lacks old folder prefix/new marker distinction");
        DataCoordinator.Baselines history = hash -> hash.equals(newHash) ? newInventory : null;
        check(coordinator(lost, history).prepare(source(thirdZip), null).equals(reboundRoot),
                "Next missing-state upgrade incorrectly required prefix == marker SHA");
        verifyReady(lost, reboundRoot, thirdZip);
        check(snapshot(lost.resolve("wmmt")).equals(savesBefore), "Next-version adoption changed saves");
        System.out.println("PASS subsequent distinct-ZIP upgrade after registry loss with original folder hash != marker hash");
    }

    private static final class TrackedInput extends ByteArrayInputStream {
        boolean closed;
        TrackedInput(byte[] bytes) { super(bytes); }
        @Override public void close() { closed = true; }
    }

    private static void manifestApiChecks() throws Exception {
        Path fixture = temp("manifest-api");
        Path path = fixture.resolve("inventory");
        oldInventory.writeAtomic(path, null, LIMITS);
        byte[] encoded = Files.readAllBytes(path);
        TrackedInput input = new TrackedInput(encoded);
        DataManifest read = DataManifest.read(input, LIMITS);
        check(!input.closed, "read(InputStream) closed caller-owned stream");
        DataManifest rebound = read.rebindDirectory("bound-root");
        check(rebound.zipSha256.equals(oldHash) && rebound.canonicalId.equals(ID)
                && rebound.resourceDirectory.equals("bound-root"), "Rebind changed trusted identity");
        for (DataManifest.Entry file : oldInventory.files().values()) {
            DataManifest.Entry actual = rebound.files().get(file.path);
            check(actual != null && actual.length == file.length && actual.sha256.equals(file.sha256),
                    "Rebind changed file ownership");
        }
        for (String unsafe : new String[] {"../escape", "/absolute", "a/b", "wmmt", "mods", ".overlay-test"})
            rejected(() -> read.rebindDirectory(unsafe));
        rejected(() -> DataManifest.read(new ByteArrayInputStream(Arrays.copyOf(encoded, encoded.length - 1)), LIMITS));
        System.out.println("PASS stream parser/rebind preserve trusted file identity and reject unsafe/truncated input");
    }

    public static void main(String[] args) throws Exception {
        if (args.length > 1) throw new IllegalArgumentException("Supply at most one fixture directory");
        tempBase = Paths.get(args.length == 1 ? args[0] : System.getProperty("java.io.tmpdir"))
                .toAbsolutePath().normalize().toRealPath();
        if (!Files.isDirectory(tempBase, LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Fixture directory unavailable");
        oldZip = zip("old");
        newZip = zip("new");
        thirdZip = zip("third");
        unsupportedZip = zip("unlisted");
        oldHash = sha(oldZip);
        newHash = sha(newZip);
        thirdHash = sha(thirdZip);
        unsupportedHash = sha(unsupportedZip);
        check(!oldHash.equals(newHash) && !newHash.equals(thirdHash) && !oldHash.equals(thirdHash),
                "Cross-version fixtures must have different archive SHA-256 identities");
        oldInventory = inventory(oldZip, ID);
        newInventory = inventory(newZip, ID);
        manifestApiChecks();
        directWithInertSiblings();
        recognizedAmbiguity();
        resourceRejections();
        privateStateRejectionsAndResume();
        noEligibleDoesNotInitialize();
        wrongCatalogRejected();
        adoptionAndOverlayFaults();
        markerChangesAndBaselineSyncFailure();
        nextVersionAfterRegistryLoss();
        System.out.println("DataLegacyUpgradeHostTest passed: " + checks + " checks.");
        System.out.println("SYNTHETIC ONLY: not shipped 1.29->1.32 APK/provider/build wiring evidence.");
    }
}
