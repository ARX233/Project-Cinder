package com.wmmt.port;

import java.io.ByteArrayOutputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.channels.FileChannel;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Optional authenticated replay sharing. A downloaded recording never confers a crown. */
final class GhostCloud {
    static final int RECORDS = 16;
    private static final int DEFENSE_RECORDS = 8;
    private static final int MAX_PROFILE = 248 + 28 + 4 * 512 + 48 * 8192;
    private static final int MAX_PENDING = 32;
    private static final Pattern SHA = Pattern.compile("[a-f0-9]{64}");
    private static final Pattern ID = Pattern.compile("[a-f0-9]{32}");
    private static final Pattern FILE = Pattern.compile("([0-7])-([a-f0-9]{64})(?:-([a-f0-9]{32}))?\\.ghost");
    private static final Pattern BATTLE = Pattern.compile("([a-f0-9]{32})-([a-f0-9]{32})\\.battle");
    private static final int BATTLE_BYTES = 34;
    private static final int TIMING_BYTES = 236;
    private static final SecureRandom RANDOM = new SecureRandom();
    private final String base;
    private final CloudDevice device;
    private volatile int registration; // 0 unknown, 1 approved, -1 awaiting approval
    private final Path root;
    private final ScheduledExecutorService worker = Executors.newSingleThreadScheduledExecutor(r -> {
        Thread t = new Thread(r, "cinder-ghost-cloud");
        t.setDaemon(true);
        return t;
    });
    private byte[] reply, defenseReply, timingReply;
    private boolean fetching, defenseFetching, draining, timingFetching, timingSending;
    private int timingAck;

    GhostCloud(String address, CloudDevice device, Path queueRoot) {
        this.base = CloudDevice.httpsOrigin(address);
        this.device = device;
        root = queueRoot.resolve(digest((base + "\n" + device.id).getBytes(StandardCharsets.UTF_8)));
        worker.scheduleWithFixedDelay(() -> {
            if (!approved()) checkRegistration();
            if (approved()) scheduleUpload();
        }, 0, 30, TimeUnit.SECONDS);
    }

    boolean approved() { return registration == 1; }
    int registrationStatus() { return registration; }

    synchronized void refreshRegistration(Runnable callback) {
        if (worker.isShutdown()) return;
        worker.execute(() -> {
            checkRegistration();
            callback.run();
        });
    }

    private void checkRegistration() {
        try {
            JSONObject state = json(exchange("/v1/device", null, 256, null));
            if (device.id.equals(state.getString("device_id")) && state.getBoolean("approved"))
                registration = 1;
        } catch (IOException | JSONException ignored) { /* 403 is handled by exchange. */ }
    }

    synchronized void close() { worker.shutdownNow(); }

    synchronized boolean timingSubmit(byte[] record) {
        if (worker.isShutdown() || timingSending || record == null || record.length != TIMING_BYTES) return false;
        timingSending = true;
        timingAck = 0;
        worker.execute(() -> {
            int result = -1;
            try {
                JSONObject ack = json(exchange("/v1/ta/community", record, 1024, null));
                if (digest(record).equals(ack.getString("sha256")) && !ack.getBoolean("verified")) result = 1;
            } catch (IOException | JSONException ignored) { /* the native outbox retains the record */ }
            finally { synchronized (this) { timingAck = result; timingSending = false; } }
        });
        return true;
    }

    synchronized int timingPollAck() {
        int result = timingAck;
        timingAck = 0;
        return result;
    }

    synchronized boolean timingRefresh(String rules, String physics, int course, int traffic) {
        if (worker.isShutdown() || timingFetching || !SHA.matcher(rules).matches() || !SHA.matcher(physics).matches() ||
                course < 0 || course > 14 || traffic < 0 || traffic > 1) return false;
        timingFetching = true;
        timingReply = null;
        worker.execute(() -> {
            byte[] result = new byte[0];
            try {
                result = exchange("/v1/ta/community?rules_sha256=" + rules + "&physics_sha256=" + physics +
                        "&course_id=" + course + "&traffic=" + traffic, null, 8 + 10 * TIMING_BYTES, null);
            } catch (IOException ignored) { /* an empty reply falls back to the local board */ }
            finally { synchronized (this) { timingReply = result; timingFetching = false; } }
        });
        return true;
    }

    synchronized byte[] timingPollBoard() {
        byte[] result = timingReply;
        timingReply = null;
        return result;
    }

    boolean refresh(String physics) { return fetch(physics, null, null); }

    boolean search(String physics, String name) {
        if (name == null || name.isEmpty() || name.length() > 5) return false;
        return fetch(physics, name, null);
    }

    boolean searchId(String physics, String id) {
        return id != null && ID.matcher(id).matches() && fetch(physics, null, id);
    }

    private synchronized boolean fetch(String physics, String name, String id) {
        if (worker.isShutdown() || fetching || !SHA.matcher(physics).matches()) return false;
        reply = null;
        fetching = true;
        scheduleUpload();
        worker.execute(() -> {
            byte[] result = new byte[0];
            try { result = download(physics, name, id); }
            catch (IOException | JSONException ignored) { /* empty reply signals error */ }
            finally {
                synchronized (this) {
                    reply = result;
                    fetching = false;
                }
            }
        });
        return true;
    }

    synchronized byte[] poll() {
        byte[] data = reply;
        reply = null;
        return data;
    }

    synchronized boolean enqueue(int area, byte[] recording, String cardId) {
        if (area < 0 || area > 7 || recording == null || recording.length < 276 ||
                recording.length > MAX_PROFILE || (cardId != null && !ID.matcher(cardId).matches()))
            return false;
        String leaf = area + "-" + digest(recording) + (cardId == null ? "" : "-" + cardId) + ".ghost";
        return queue(leaf, "*.ghost", recording);
    }

    synchronized boolean report(byte[] id, boolean won, int rawModel, int hp, int gap, String name) {
        if (id == null || id.length != 16 || rawModel < 0 || rawModel >= 247 ||
                hp < 1 || hp > 2000 || name == null || name.isEmpty() || name.length() > 5)
            return false;
        byte[] nonce = new byte[16];
        RANDOM.nextBytes(nonce);
        ByteBuffer body = ByteBuffer.allocate(BATTLE_BYTES).order(ByteOrder.LITTLE_ENDIAN);
        body.put(nonce).put((byte) (won ? 1 : 0)).put((byte) rawModel).putShort((short) hp).putInt(gap);
        body.put(name.getBytes(StandardCharsets.UTF_16LE));
        return queue(hex(id) + "-" + hex(nonce) + ".battle", "*.battle", body.array());
    }

    synchronized boolean defenseRefresh(String cardId) {
        if (worker.isShutdown() || defenseFetching || !ID.matcher(cardId).matches()) return false;
        defenseReply = null;
        defenseFetching = true;
        scheduleUpload();
        worker.execute(() -> {
            byte[] result = new byte[0];
            try { result = defense(cardId); }
            catch (IOException | JSONException ignored) { /* empty reply signals error */ }
            finally {
                synchronized (this) {
                    defenseReply = result;
                    defenseFetching = false;
                }
            }
        });
        return true;
    }

    synchronized byte[] defensePoll() {
        byte[] data = defenseReply;
        defenseReply = null;
        return data;
    }

    private boolean queue(String leaf, String glob, byte[] payload) {
        if (worker.isShutdown()) return false;
        Path staging = null;
        try {
            Files.createDirectories(root);
            if (!Files.isDirectory(root, LinkOption.NOFOLLOW_LINKS)) return false;
            Path target = root.resolve(leaf);
            if (!Files.isRegularFile(target, LinkOption.NOFOLLOW_LINKS)) {
                int pending = 0;
                try (DirectoryStream<Path> entries = Files.newDirectoryStream(root, glob)) {
                    for (Path ignored : entries) if (++pending >= MAX_PENDING) return false;
                }
                staging = Files.createTempFile(root, ".pending-", ".part");
                try (FileOutputStream out = new FileOutputStream(staging.toFile())) {
                    out.write(payload);
                    out.getFD().sync();
                }
                Files.move(staging, target, StandardCopyOption.ATOMIC_MOVE);
                staging = null;
                try (FileChannel dir = FileChannel.open(root, StandardOpenOption.READ)) { dir.force(true); }
            }
            scheduleUpload();
            return true;
        } catch (IOException | RuntimeException failure) {
            return false;
        } finally {
            if (staging != null) try { Files.deleteIfExists(staging); } catch (IOException ignored) { }
        }
    }

    private synchronized void scheduleUpload() {
        if (draining || worker.isShutdown() || !approved()) return;
        draining = true;
        worker.execute(() -> {
            try {
                long deadline = System.nanoTime() + 8_000_000_000L;
                try { drainBattles(Math.min(deadline, System.nanoTime() + 4_000_000_000L)); }
                catch (IOException | JSONException ignored) { /* retry independently of replay uploads */ }
                try { drainReplays(deadline); }
                catch (IOException | JSONException ignored) { /* retry on next refresh or enqueue */ }
            } finally { synchronized (this) { draining = false; } }
        });
    }

    private void drainReplays(long deadline) throws IOException, JSONException {
        if (!Files.isDirectory(root, LinkOption.NOFOLLOW_LINKS)) return;
        try (DirectoryStream<Path> entries = Files.newDirectoryStream(root, "*.ghost")) {
            for (Path item : entries) {
                if (System.nanoTime() >= deadline) return;
                String leaf = item.getFileName().toString();
                Matcher file = FILE.matcher(leaf);
                if (!file.matches() || !Files.isRegularFile(item, LinkOption.NOFOLLOW_LINKS)) continue;
                byte[] body;
                try (InputStream source = Files.newInputStream(item)) { body = bounded(source, MAX_PROFILE); }
                String expected = file.group(2);
                if (!digest(body).equals(expected)) continue;
                JSONObject ack;
                try { ack = json(exchange("/v1/ghosts?area=" + file.group(1), body, 4096, file.group(3))); }
                catch (Rejected failure) {
                    if (failure.status == 400 || failure.status == 413 ||
                            failure.status == 415 || failure.status == 422) continue;
                    throw failure;
                }
                if (!expected.equals(ack.getString("sha256")) ||
                        !ID.matcher(ack.getString("id")).matches() ||
                        ack.getInt("area") != leaf.charAt(0) - '0') throw new IOException("Invalid replay acknowledgement");
                Files.deleteIfExists(item);
            }
        }
    }

    private void drainBattles(long deadline) throws IOException, JSONException {
        if (!Files.isDirectory(root, LinkOption.NOFOLLOW_LINKS)) return;
        try (DirectoryStream<Path> entries = Files.newDirectoryStream(root, "*.battle")) {
            for (Path item : entries) {
                if (System.nanoTime() >= deadline) return;
                Matcher file = BATTLE.matcher(item.getFileName().toString());
                if (!file.matches() || !Files.isRegularFile(item, LinkOption.NOFOLLOW_LINKS)) continue;
                byte[] body;
                try (InputStream source = Files.newInputStream(item)) { body = bounded(source, BATTLE_BYTES); }
                if (body.length != BATTLE_BYTES || !file.group(2).equals(hex(java.util.Arrays.copyOf(body, 16))))
                    continue;
                String id = file.group(1);
                try {
                    JSONObject ack = json(exchange("/v1/ghosts/" + id + "/battles", body, 4096, null));
                    if (!id.equals(ack.getString("id")) || ack.getBoolean("verified"))
                        throw new IOException("Invalid battle acknowledgement");
                    Files.deleteIfExists(item);
                } catch (Rejected failure) {
                    if (failure.status == 400 || failure.status == 404 || failure.status == 409 || failure.status == 413)
                        Files.deleteIfExists(item);
                    else throw failure;
                }
            }
        }
    }

    private byte[] defense(String cardId) throws IOException, JSONException {
        JSONObject snapshot = json(exchange("/v1/ghosts/defense?card_id=" + cardId, null, 4096, null));
        int battles = snapshot.getInt("battles"), wins = snapshot.getInt("wins");
        JSONArray recent = snapshot.getJSONArray("recent");
        if (battles < 0 || wins < 0 || wins > battles || recent.length() != Math.min(battles, DEFENSE_RECORDS) ||
                snapshot.getBoolean("verified"))
            throw new IOException("Invalid defense totals");
        ByteBuffer result = ByteBuffer.allocate(9 + 27 * recent.length()).order(ByteOrder.LITTLE_ENDIAN);
        result.putInt(wins).putInt(battles).put((byte) recent.length());
        for (int i = 0; i < recent.length(); i++) {
            JSONObject row = recent.getJSONObject(i);
            long time = row.getLong("created_ms") / 1000L;
            int won = row.getInt("won"), model = row.getInt("raw_model"), hp = row.getInt("hp");
            String name = row.getString("name");
            int area = row.getInt("area"), gap = row.getInt("gap");
            if (area < 0 || area > 7 || (gap != Integer.MIN_VALUE && (gap < -1000000 || gap > 1000000)) ||
                    time <= 0 || time > 253402300799L || (won != 0 && won != 1) || model < 0 ||
                    model >= 247 || hp < 1 || hp > 2000 || name.isEmpty() || name.length() > 5)
                throw new IOException("Invalid defense row");
            result.putLong(time).put((byte) won).put((byte) model).putShort((short) hp);
            for (int j = 0; j < 5; j++) result.putChar(j < name.length() ? name.charAt(j) : 0);
            result.put((byte) area).putInt(gap);
        }
        return result.array();
    }

    private byte[] download(String physics, String name, String ghostId) throws IOException, JSONException {
        String basePath = "/v1/ghosts?physics_sha256=" + physics + "&limit=" + RECORDS;
        String filter = name != null ? "&name_hex=" + hex(name.getBytes(StandardCharsets.UTF_8)) :
                ghostId != null ? "&id=" + ghostId : "&others=1";
        JSONObject list;
        try { list = json(exchange(basePath + filter, null, 32768, null)); }
        catch (Rejected failure) {
            if (failure.status != 400 || name != null || ghostId != null) throw failure;
            list = json(exchange(basePath, null, 32768, null)); // servers without discovery filters
        }
        JSONArray ghosts = list.getJSONArray("ghosts");
        if (ghosts.length() > RECORDS) throw new IOException("Cloud replay count exceeds budget");
        ByteArrayOutputStream rows = new ByteArrayOutputStream();
        int count = 0;
        long deadline = System.nanoTime() + 12_000_000_000L;
        for (int i = 0; i < ghosts.length() && System.nanoTime() < deadline; i++) {
            JSONObject item = ghosts.getJSONObject(i);
            String id = item.getString("id"), sha = item.getString("sha256");
            int area = item.getInt("area"), bytes = item.getInt("bytes");
            if (!ID.matcher(id).matches() || (ghostId != null && !ghostId.equals(id)) ||
                    (name != null && !item.getString("display_name").contains(name)) || !SHA.matcher(sha).matches() ||
                    !physics.equals(item.getString("physics_sha256")) || area < 0 || area > 7 ||
                    bytes < 276 || bytes > MAX_PROFILE) continue;
            byte[] data;
            try { data = exchange("/v1/ghosts/" + id, null, bytes, null); }
            catch (IOException failure) { continue; }
            if (data.length != bytes || !digest(data).equals(sha)) continue;
            rows.write(area);
            for (int n = 0; n < id.length(); n += 2)
                rows.write(Integer.parseInt(id.substring(n, n + 2), 16));
            for (int n = 0; n < 4; n++) rows.write(bytes >>> (8 * n));
            rows.write(data, 0, bytes);
            count++;
        }
        ByteArrayOutputStream result = new ByteArrayOutputStream(1 + rows.size());
        result.write(count);
        rows.writeTo(result);
        return result.toByteArray();
    }

    private static final class Rejected extends IOException {
        final int status;
        Rejected(int status) {
            super("Cloud request rejected");
            this.status = status;
        }
    }

    private byte[] exchange(String path, byte[] body, int max, String cardId) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) new URL(base + path).openConnection();
        connection.setInstanceFollowRedirects(false);
        connection.setConnectTimeout(3500);
        connection.setReadTimeout(4000);
        connection.setRequestProperty("Authorization", device.authorization());
        connection.setRequestProperty("Accept-Encoding", "identity");
        if (cardId != null) connection.setRequestProperty("X-Cinder-Card-ID", cardId);
        try {
            if (body != null) {
                connection.setRequestMethod("POST");
                connection.setRequestProperty("Content-Type", "application/octet-stream");
                connection.setFixedLengthStreamingMode(body.length);
                connection.setDoOutput(true);
                try (OutputStream out = connection.getOutputStream()) { out.write(body); }
            }
            int status = connection.getResponseCode();
            if (status == 401 || status == 403) registration = -1;
            if (status != 200 && (body == null || status != 201)) throw new Rejected(status);
            if (connection.getContentLengthLong() > max) throw new IOException("Cloud payload exceeds budget");
            try (InputStream source = connection.getInputStream()) { return bounded(source, max); }
        } finally {
            connection.disconnect();
        }
    }

    private static byte[] bounded(InputStream source, int max) throws IOException {
        ByteArrayOutputStream data = new ByteArrayOutputStream(Math.min(max, 8192));
        byte[] block = new byte[8192];
        int n;
        while ((n = source.read(block)) != -1) {
            if (n > max - data.size()) throw new IOException("Cloud payload exceeds budget");
            data.write(block, 0, n);
        }
        return data.toByteArray();
    }

    private static JSONObject json(byte[] payload) throws JSONException {
        return new JSONObject(new String(payload, StandardCharsets.UTF_8));
    }

    private static String hex(byte[] data) {
        StringBuilder value = new StringBuilder(data.length * 2);
        for (byte b : data) {
            value.append(Character.forDigit((b >>> 4) & 15, 16));
            value.append(Character.forDigit(b & 15, 16));
        }
        return value.toString();
    }

    private static String digest(byte[] data) {
        try { return hex(MessageDigest.getInstance("SHA-256").digest(data)); }
        catch (NoSuchAlgorithmException impossible) { throw new AssertionError(impossible); }
    }
}
