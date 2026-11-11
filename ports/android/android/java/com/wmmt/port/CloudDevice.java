package com.wmmt.port;

import java.io.FileOutputStream;
import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;

/** Installation-scoped identity stored separately from game saves and resources. */
final class CloudDevice {
    static final String CLOUD_ORIGIN = "https://niceapi.net";
    // Room matches use a separate UDP server.
    static final String ONLINE_VS_DOMAIN = "";

    private final String secret;
    final String id;

    private CloudDevice(byte[] key) {
        secret = hex(key);
        try {
            id = hex(MessageDigest.getInstance("SHA-256")
                    .digest(secret.getBytes(StandardCharsets.US_ASCII))).substring(0, 32);
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    String authorization() { return "CinderDevice " + secret; }

    static synchronized CloudDevice load(Path directory) throws IOException {
        Path identity = directory.resolve("cinder-device-v1");
        if (!Files.exists(identity, LinkOption.NOFOLLOW_LINKS)) {
            byte[] key = new byte[32];
            new SecureRandom().nextBytes(key);
            Path staged = Files.createTempFile(directory, ".cinder-device-", ".tmp");
            try {
                try (FileOutputStream out = new FileOutputStream(staged.toFile())) {
                    out.write(key);
                    out.getFD().sync();
                }
                Files.move(staged, identity, StandardCopyOption.ATOMIC_MOVE);
            } finally {
                Files.deleteIfExists(staged);
            }
        }
        if (!Files.isRegularFile(identity, LinkOption.NOFOLLOW_LINKS) || Files.size(identity) != 32)
            throw new IOException("Invalid Cinder device identity");
        byte[] key = Files.readAllBytes(identity);
        if (key.length != 32) throw new IOException("Invalid Cinder device identity");
        return new CloudDevice(key);
    }

    static boolean validDomain(String host) {
        if (host == null || host.length() > 253 || !host.contains(".")) return false;
        String[] labels = host.split("\\.", -1);
        if (!labels[labels.length - 1].matches("[A-Za-z][A-Za-z0-9-]*")) return false;
        for (String label : labels)
            if (!label.matches("[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")) return false;
        return true;
    }

    static String httpsOrigin(String address) {
        URI uri = URI.create(address);
        if (!"https".equals(uri.getScheme()) || !validDomain(uri.getHost()) ||
                uri.getRawUserInfo() != null || uri.getRawQuery() != null || uri.getRawFragment() != null ||
                !("".equals(uri.getRawPath()) || "/".equals(uri.getRawPath())) ||
                uri.getPort() == 0 || uri.getPort() > 65535) throw new IllegalArgumentException("Invalid cloud origin");
        return "https://" + uri.getRawAuthority();
    }

    private static String hex(byte[] bytes) {
        StringBuilder out = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) {
            out.append(Character.forDigit((b >>> 4) & 15, 16));
            out.append(Character.forDigit(b & 15, 16));
        }
        return out.toString();
    }
}
