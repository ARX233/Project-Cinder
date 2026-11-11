package com.wmmt.port;

import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;
import android.media.MediaCodec;
import android.media.MediaExtractor;
import android.media.MediaFormat;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.channels.FileChannel;

/** Decodes the first pass ahead of playback, then loops PCM in a single AudioTrack.
 * The seek at the seam is only a file offset. The audio device keeps its queued frames. */
final class ArcadeBgm {
    interface Listener {
        void ready(ArcadeBgm player);
        void failed(ArcadeBgm player, Exception error);
    }

    private static final int PCM_LIMIT = 96 * 1024 * 1024;
    private static final long STALL_NS = 10_000_000_000L;

    private static final int[] MAXI_3_FRAMES = {
        5443201, 5329008, 4440840, 4144784, 4366826, 6291189, 4366826, 4639562,
        5347511, 5625064, 2886546, 8618401, 8659637, 12226346, 10658014
    };
    private static final int[] MAXI_3_DX_PLUS_FRAMES = {
        10710800, 7105343, 11218899, 9474921
    };

    private final File source, cacheDir;
    private final String tenCue;
    private final Listener listener;
    private final Thread worker;
    private volatile boolean closed, playing;
    private volatile float volume = 1;
    private volatile Fade fade;

    private static final class Fade {
        final boolean in;
        final long duration;
        Fade(boolean in, int millis) {
            this.in = in;
            duration = millis * 1_000_000L;
        }
    }

    ArcadeBgm(File source, File cacheDir, Listener listener) {
        this(source, cacheDir, null, listener);
    }

    ArcadeBgm(File source, File cacheDir, String tenCue, Listener listener) {
        this.source = source;
        this.cacheDir = cacheDir;
        this.tenCue = tenCue;
        this.listener = listener;
        worker = new Thread(this::run, "cinder-bgm");
        worker.setDaemon(true);
    }

    static boolean supports(String name) {
        return originalFrames(name) != 0 || name.matches("wm[2r]_[0-9][0-9]");
    }

    static boolean isTenCue(String name) {
        return name != null && name.matches("ten_[a-e][1-9]");
    }

    /** Length of the arcade PCM data chunk in stereo frames at 44.1 kHz. */
    private static int originalFrames(String name) {
        if (name.matches("wm3_(0[1-9]|1[0-5])"))
            return MAXI_3_FRAMES[Integer.parseInt(name.substring(4)) - 1];
        if (name.matches("wm3DX_P_race_0[1-4]"))
            return MAXI_3_DX_PLUS_FRAMES[name.charAt(name.length() - 1) - '1'];
        switch (name) {
            case "wm3DX_P_sys_01_ent": return 12470843;
            case "wm3DX_P_sys_02_sel": return 8955686;
            case "sys_04": return 2368448;
            case "wm3DX_race_01_mainD": return 9970435;
            default: return 0;
        }
    }

    static long playableFrames(String name, int rate, long durationUs, int encoderDelay) {
        long mediaFrames = durationUs > 0 && durationUs <= 900_000_000L ?
                (durationUs * rate + 500_000) / 1_000_000 : 0;
        int original = originalFrames(name);
        if (rate == 44100 && original > 0 && Math.abs(mediaFrames - original) <= rate / 5)
            return original;
        // MPEG4Extractor reports mdhd duration and the edit list's starting frame.
        // The codec drops that start; this also drops any final partial AAC access unit.
        return encoderDelay > 0 && mediaFrames > encoderDelay ? mediaFrames - encoderDelay : 0;
    }

    void start() { worker.start(); }

    synchronized void fade(boolean in, int millis) {
        fade = new Fade(in, millis);
        notifyAll();
    }

    synchronized void playback(boolean play, float gain) {
        if (closed) return;
        playing = play;
        volume = gain;
        notifyAll();
    }

    synchronized void close() {
        closed = true;
        playing = false;
        notifyAll();
    }

    private synchronized void idle(boolean buffered) throws InterruptedException {
        if (!closed) {
            if (buffered && !playing) wait();
            else wait(buffered ? 12 : 3);
        }
    }

    private void run() {
        File cache = null;
        try {
            if (tenCue != null) {
                try (RandomAccessFile bank = new RandomAccessFile(source, "r")) {
                    TenCue cue = TenCue.read(bank.getChannel(), tenCue);
                    output(bank.getChannel(), null, cue.offset, cue.length, cue.rate, 2);
                }
                return;
            }
            cache = File.createTempFile("cinder-bgm-", ".pcm", cacheDir);
            try (RandomAccessFile pcm = new RandomAccessFile(cache, "rw");
                 Decoder decoder = new Decoder(source)) {
                // On Android an open file remains accessible after unlink.
                // A crash or replacement then leaves no decoded soundtrack in cache.
                cache.delete();
                output(pcm.getChannel(), decoder, 0, 0, decoder.rate, decoder.channels);
            }
        } catch (Exception error) {
            if (!closed) listener.failed(this, error);
        } finally {
            if (cache != null) cache.delete();
        }
    }

    private static void readFully(FileChannel channel, ByteBuffer bytes, long offset) throws IOException {
        while (bytes.hasRemaining()) {
            int read = channel.read(bytes, offset);
            if (read <= 0) throw new IOException("Incomplete BGM stream");
            offset += read;
        }
    }

    private static final class TenCue {
        final long offset;
        final int length, rate;

        TenCue(long offset, int length, int rate) {
            this.offset = offset;
            this.length = length;
            this.rate = rate;
        }

        static TenCue read(FileChannel bank, String requested) throws IOException {
            int tracks = 38;
            ByteBuffer index = ByteBuffer.allocate(8 + tracks * 16).order(ByteOrder.LITTLE_ENDIAN);
            readFully(bank, index, 0);
            index.flip();
            if (index.getInt() != 0x31425457 || index.getInt() != tracks)
                throw new IOException("Invalid 10-rival BGM index");
            long offset = index.limit(), size = bank.size();
            TenCue found = null;
            byte[] name = new byte[6];
            for (int i = 0; i < tracks; ++i) {
                index.get(name);
                int pad = index.getShort(), rate = index.getInt(), length = index.getInt();
                if (pad != 0 || (rate != 28000 && rate != 44100)
                        || length <= 0 || length % 4 != 0 || length > size - offset)
                    throw new IOException("Invalid 10-rival BGM range");
                if (requested.equals(new String(name, StandardCharsets.US_ASCII)))
                    found = new TenCue(offset, length, rate);
                offset += length;
            }
            if (found == null || offset != size) throw new IOException("10-rival BGM cue unavailable");
            return found;
        }
    }

    private void output(FileChannel pcm, Decoder decoder, long sourceOffset, long sourceLength, int rate,
                        int channels) throws IOException, InterruptedException {
        int frameBytes = channels * 2;
        int second = rate * frameBytes;
        int mask = channels == 1 ? AudioFormat.CHANNEL_OUT_MONO : AudioFormat.CHANNEL_OUT_STEREO;
        int minimum = AudioTrack.getMinBufferSize(rate, mask, AudioFormat.ENCODING_PCM_16BIT);
        if (minimum <= 0) throw new IOException("Unsupported BGM output format");
        int bufferBytes = Math.max(minimum, second / 4);
        bufferBytes = (bufferBytes + frameBytes - 1) / frameBytes * frameBytes;
        int ahead = Math.max(bufferBytes, second);
        AudioTrack track = new AudioTrack.Builder()
                .setAudioAttributes(new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_GAME)
                        .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                .setAudioFormat(new AudioFormat.Builder().setChannelMask(mask)
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT).setSampleRate(rate).build())
                .setTransferMode(AudioTrack.MODE_STREAM)
                .setBufferSizeInBytes(bufferBytes)
                .build();
        try {
            if (track.getState() != AudioTrack.STATE_INITIALIZED) throw new IOException("BGM output unavailable");
            ByteBuffer block = ByteBuffer.allocateDirect(16 * 1024);
            block.limit(0);
            long cursor = 0;
            long stall = System.nanoTime() + STALL_NS;
            boolean ready = false, started = false;
            float applied = -1;
            Fade activeFade = null;
            long fadeTime = 0, fadeTick = 0;
            while (!closed) {
                boolean progress = false;
                if (decoder != null && !decoder.done && decoder.written - cursor < ahead) {
                    progress = decoder.pump(pcm);
                    if (progress) stall = System.nanoTime() + STALL_NS;
                    else if (System.nanoTime() >= stall) throw new IOException("BGM decoder stalled");
                } else stall = System.nanoTime() + STALL_NS;
                long written = decoder == null ? sourceLength : decoder.written;
                boolean complete = decoder == null || decoder.done;
                boolean priming = !ready && (written >= bufferBytes || complete);
                if (priming && written < frameBytes) throw new IOException("Empty BGM stream");
                boolean wantPlay = ready && playing && !closed;
                long now = System.nanoTime();
                Fade currentFade = fade;
                if (currentFade != activeFade) {
                    activeFade = currentFade;
                    fadeTime = 0;
                } else if (started && wantPlay && activeFade != null) {
                    fadeTime += now - fadeTick;
                }
                fadeTick = now;
                float gain = volume;
                if (activeFade != null) {
                    float part = Math.min(1, (float) fadeTime / activeFade.duration);
                    if (part == 1 && !activeFade.in) break;
                    gain *= activeFade.in ? part : 1 - part;
                }
                if (started != wantPlay) {
                    if (wantPlay) {
                        track.setVolume(gain);
                        applied = gain;
                        track.play();
                    } else track.pause();
                    started = wantPlay;
                }
                if (started || priming) {
                    if (gain != applied) {
                        track.setVolume(gain);
                        applied = gain;
                    }
                    if (!block.hasRemaining()) {
                        if (complete && cursor == written) cursor = 0;
                        int size = (int) Math.min(block.capacity(), written - cursor);
                        if (size > 0) {
                            block.clear();
                            block.limit(size);
                            readFully(pcm, block, sourceOffset + cursor);
                            cursor += size;
                            block.flip();
                        }
                    }
                    if (block.hasRemaining()) {
                        int requested = block.remaining();
                        int bytes = track.write(block, requested, AudioTrack.WRITE_NON_BLOCKING);
                        if (bytes < 0 || bytes % frameBytes != 0) throw new IOException("BGM output write failed");
                        progress |= bytes > 0;
                        // A short write is the platform's portable signal that the
                        // stopped stream has been primed to its actual capacity.
                        if (priming && bytes < requested) {
                            ready = true;
                            listener.ready(this);
                        }
                    }
                }
                if (!progress) idle(ready && (complete || written - cursor >= ahead));
            }
        } finally {
            track.release();
        }
    }

    private static final class Decoder implements AutoCloseable {
        private final MediaExtractor extractor = new MediaExtractor();
        private MediaCodec codec;
        private final MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
        private boolean sentEnd, done;
        private int rate, channels;
        private long written, limit;

        Decoder(File source) throws IOException {
            try {
                extractor.setDataSource(source.getAbsolutePath());
                for (int i = 0; i < extractor.getTrackCount(); i++) {
                    MediaFormat format = extractor.getTrackFormat(i);
                    String mime = format.getString(MediaFormat.KEY_MIME);
                    if (!"audio/mp4a-latm".equals(mime)) continue;
                    rate = format.getInteger(MediaFormat.KEY_SAMPLE_RATE);
                    channels = format.getInteger(MediaFormat.KEY_CHANNEL_COUNT);
                    if (rate < 8000 || rate > 48000 || (channels != 1 && channels != 2))
                        throw new IOException("Unsupported BGM source format");
                    extractor.selectTrack(i);
                    String name = source.getName();
                    long frames = playableFrames(name.substring(0, name.length() - 4), rate,
                            format.containsKey(MediaFormat.KEY_DURATION) ? format.getLong(MediaFormat.KEY_DURATION) : 0,
                            format.containsKey(MediaFormat.KEY_ENCODER_DELAY) ?
                                    format.getInteger(MediaFormat.KEY_ENCODER_DELAY) : 0);
                    limit = frames > 0 ? frames * channels * 2L : Long.MAX_VALUE;
                    if (limit != Long.MAX_VALUE && limit > PCM_LIMIT)
                        throw new IOException("BGM exceeds the decoded size limit");
                    // Retain the container's encoder-delay and encoder-padding metadata.
                    // Android's codec buffer path applies these before returning PCM.
                    format.setInteger(MediaFormat.KEY_PCM_ENCODING, AudioFormat.ENCODING_PCM_16BIT);
                    codec = MediaCodec.createDecoderByType(mime);
                    codec.configure(format, null, null, 0);
                    codec.start();
                    return;
                }
                throw new IOException("AAC BGM track missing");
            } catch (IOException | RuntimeException error) {
                close();
                throw error;
            }
        }

        boolean pump(FileChannel pcm) throws IOException {
            boolean progress = false;
            if (!sentEnd) {
                int index = codec.dequeueInputBuffer(0);
                if (index >= 0) {
                    ByteBuffer input = codec.getInputBuffer(index);
                    if (input == null) throw new IOException("AAC decoder input unavailable");
                    input.clear();
                    int size = extractor.readSampleData(input, 0);
                    sentEnd = size < 0;
                    codec.queueInputBuffer(index, 0, sentEnd ? 0 : size,
                            sentEnd ? 0 : extractor.getSampleTime(),
                            sentEnd ? MediaCodec.BUFFER_FLAG_END_OF_STREAM : 0);
                    if (!sentEnd) extractor.advance();
                    progress = true;
                }
            }
            int index = codec.dequeueOutputBuffer(info, 0);
            if (index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                MediaFormat format = codec.getOutputFormat();
                if (format.getInteger(MediaFormat.KEY_SAMPLE_RATE) != rate ||
                        format.getInteger(MediaFormat.KEY_CHANNEL_COUNT) != channels ||
                        (format.containsKey(MediaFormat.KEY_PCM_ENCODING) &&
                         format.getInteger(MediaFormat.KEY_PCM_ENCODING) != AudioFormat.ENCODING_PCM_16BIT))
                    throw new IOException("Unsupported decoded BGM format");
                return true;
            }
            if (index < 0) return progress;
            if (info.size > 0 && (info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0) {
                ByteBuffer samples = codec.getOutputBuffer(index);
                int bytesToKeep = (int) Math.min(info.size, limit - written);
                if (samples == null || info.size % (channels * 2) != 0 || bytesToKeep > PCM_LIMIT - written)
                    throw new IOException("Invalid decoded BGM buffer");
                samples.position(info.offset);
                samples.limit(info.offset + bytesToKeep);
                while (samples.hasRemaining()) {
                    int bytes = pcm.write(samples, written);
                    if (bytes <= 0) throw new IOException("Could not cache decoded BGM");
                    written += bytes;
                }
            }
            codec.releaseOutputBuffer(index, false);
            done = written == limit || (info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0;
            if (done) releaseCodec();
            return true;
        }

        private void releaseCodec() {
            MediaCodec active = codec;
            codec = null;
            if (active != null) active.release();
        }

        @Override public void close() {
            try { releaseCodec(); }
            finally { extractor.release(); }
        }
    }
}
