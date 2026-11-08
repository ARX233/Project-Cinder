/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L
#include "oc_media.h"
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/audio_fifo.h>
#include <libavutil/channel_layout.h>
#include <libavutil/opt.h>
#include <libavutil/samplefmt.h>
#include <libswresample/swresample.h>
#include <libswscale/swscale.h>

typedef struct Job Job;
typedef struct {
    Job *job; int fd, writable; int64_t pos, size, high;
} IO;
typedef struct {
    IO io; AVIOContext *pb; AVFormatContext *fmt; AVCodecContext *dec;
    AVPacket *pkt; AVFrame *frame; int stream, sent_eof;
} Input;
struct Job {
    oc_media_limits l; oc_media_result *r; oc_media_cancel cancel; void *opaque;
    int failure; int64_t start_us;
    Input video, audio; IO out; AVIOContext *out_pb; AVFormatContext *mux;
    AVCodecContext *ve, *ae; AVStream *vs, *as;
    struct SwsContext *sws; SwrContext *swr; AVAudioFifo *fifo;
    AVFrame *vf; int audio_eof, swr_eof;
    int64_t audio_pts, audio_limit, video_pts;
    int audio_in_rate; enum AVSampleFormat audio_in_fmt; AVChannelLayout audio_in_layout;
};
static int64_t now_us(void) {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000000 + ts.tv_nsec / 1000;
}
static int fail(Job *j, int status, int av, const char *where) {
    if (!j->failure) {
        j->failure = status; j->r->status = status; j->r->av_error = av;
        char text[96] = ""; if (av < 0) av_strerror(av, text, sizeof text);
        snprintf(j->r->message, sizeof j->r->message, "%s%s%s", where, *text ? ": " : "", text);
    }
    return av < 0 ? av : AVERROR(EINVAL);
}
static int interrupted(void *p) {
    Job *j = p;
    if (j->failure) return 1;
    if (j->cancel && j->cancel(j->opaque)) {
        fail(j, OC_MEDIA_CANCELLED, AVERROR_EXIT, "cancelled"); return 1;
    }
    if ((uint64_t)(now_us() - j->start_us) / 1000 > j->l.max_wall_ms) {
        fail(j, OC_MEDIA_BUDGET, AVERROR_EXIT, "wall-time budget"); return 1;
    }
    return 0;
}
static int read_cb(void *p, uint8_t *buf, int n) {
    IO *io = p; if (interrupted(io->job)) return AVERROR_EXIT;
    if (io->pos >= io->size) return AVERROR_EOF;
    if (n > io->size - io->pos) n = (int)(io->size - io->pos);
    ssize_t r; do { r = pread(io->fd, buf, (size_t)n, io->pos); } while (r < 0 && errno == EINTR && !interrupted(io->job));
    if (r < 0) return fail(io->job, OC_MEDIA_IO, AVERROR(errno), "read source");
    if (!r) return fail(io->job, OC_MEDIA_IO, AVERROR(EIO), "source shrank during conversion");
    io->pos += r; io->job->r->input_bytes_read += r; return (int)r;
}
static int write_cb(void *p, const uint8_t *buf, int n) {
    IO *io = p; Job *j = io->job; if (interrupted(j)) return AVERROR_EXIT;
    if (n < 0 || io->pos < 0 || (uint64_t)io->pos > j->l.max_output_bytes ||
        (uint64_t)n > j->l.max_output_bytes - (uint64_t)io->pos)
        return fail(j, OC_MEDIA_BUDGET, AVERROR(ENOSPC), "output-byte budget");
    int done = 0;
    while (done < n) {
        if (interrupted(j)) return AVERROR_EXIT;
        ssize_t r = pwrite(io->fd, buf + done, (size_t)(n - done), io->pos);
        if (r < 0 && errno == EINTR) continue;
        if (r <= 0) return fail(j, OC_MEDIA_IO, AVERROR(r ? errno : EIO), "write output");
        done += (int)r; io->pos += r;
        if (io->pos > io->high) io->high = io->pos;
        j->r->output_bytes = io->high;
    }
    return done;
}
static int64_t seek_cb(void *p, int64_t off, int whence) {
    IO *io = p; if (interrupted(io->job)) return AVERROR_EXIT;
    if (whence == AVSEEK_SIZE) return io->writable ? io->high : io->size;
    whence &= ~AVSEEK_FORCE;
    int64_t base = whence == SEEK_SET ? 0 : whence == SEEK_CUR ? io->pos : whence == SEEK_END ? (io->writable ? io->high : io->size) : -1;
    if (base < 0 || off < -base || (off > 0 && base > INT64_MAX - off)) return AVERROR(EINVAL);
    int64_t pos = base + off;
    uint64_t max = io->writable ? io->job->l.max_output_bytes : (uint64_t)io->size;
    if ((uint64_t)pos > max) return AVERROR(EINVAL);
    return io->pos = pos;
}
static int regular_fd(Job *j, int fd, int output, struct stat *st) {
    if (fd < 0 || fstat(fd, st) || !S_ISREG(st->st_mode) || st->st_size < 0)
        return fail(j, OC_MEDIA_INVALID, AVERROR(EINVAL), "FD must be a seekable regular file");
    int fl = fcntl(fd, F_GETFL);
    if (fl < 0 || (output ? ((fl & O_ACCMODE) == O_RDONLY || (fl & O_APPEND)) : (fl & O_ACCMODE) == O_WRONLY))
        return fail(j, OC_MEDIA_INVALID, AVERROR(EINVAL), "FD access flags");
    if (output && (st->st_size != 0 || st->st_nlink != 1))
        return fail(j, OC_MEDIA_INVALID, AVERROR(EINVAL), "output must be new empty unaliased job partial");
    if (!output && (!st->st_size || (uint64_t)st->st_size > j->l.max_input_bytes))
        return fail(j, OC_MEDIA_BUDGET, AVERROR(EFBIG), "input-byte budget");
    return 0;
}
static int open_input(Job *j, Input *in, int fd, int video) {
    struct stat st; int r = regular_fd(j, fd, 0, &st); if (r < 0) return r;
    uint8_t magic[12]; if (pread(fd, magic, sizeof magic, 0) != sizeof magic)
        return fail(j, OC_MEDIA_INVALID, AVERROR_INVALIDDATA, "short source header");
    if (video ? memcmp(magic, "BIK", 3) != 0 : (memcmp(magic, "RIFF", 4) || memcmp(magic + 8, "WAVE", 4)))
        return fail(j, OC_MEDIA_INVALID, AVERROR_INVALIDDATA, "expected original Bink1 / RIFF WAVE bytes");
    in->io = (IO){ .job=j, .fd=fd, .size=st.st_size };
    uint8_t *b = av_malloc(32768); if (!b) return AVERROR(ENOMEM);
    in->pb = avio_alloc_context(b, 32768, 0, &in->io, read_cb, NULL, seek_cb);
    if (!in->pb) { av_free(b); return AVERROR(ENOMEM); }
    in->fmt = avformat_alloc_context(); if (!in->fmt) return AVERROR(ENOMEM);
    in->fmt->pb = in->pb; in->fmt->flags |= AVFMT_FLAG_CUSTOM_IO;
    in->fmt->interrupt_callback = (AVIOInterruptCB){interrupted, j};
    in->fmt->probesize = 1024 * 1024; in->fmt->max_analyze_duration = 1000000;
    in->fmt->max_probe_packets = 64; in->fmt->max_streams = 2;
    in->fmt->max_index_size = 4 * 1024 * 1024;
    r = avformat_open_input(&in->fmt, NULL, av_find_input_format(video ? "bink" : "wav"), NULL); if (r < 0) return r;
    r = avformat_find_stream_info(in->fmt, NULL); if (r < 0) return r;
    in->stream = av_find_best_stream(in->fmt, video ? AVMEDIA_TYPE_VIDEO : AVMEDIA_TYPE_AUDIO, -1, -1, NULL, 0);
    if (in->stream < 0) return in->stream;
    AVCodecParameters *par = in->fmt->streams[in->stream]->codecpar;
    if (video) {
        if (par->codec_id != AV_CODEC_ID_BINKVIDEO || par->width < 1 || par->height < 1 ||
            par->width > (int)j->l.max_width || par->height > (int)j->l.max_height)
            return fail(j, OC_MEDIA_BUDGET, AVERROR_INVALIDDATA, "Bink codec/resolution budget");
    } else {
        /* Original resource WAVs are PCM. Restrict before decoder allocation. */
        if ((par->codec_id != AV_CODEC_ID_PCM_S16LE && par->codec_id != AV_CODEC_ID_PCM_U8 &&
             par->codec_id != AV_CODEC_ID_PCM_S24LE && par->codec_id != AV_CODEC_ID_PCM_S32LE &&
             par->codec_id != AV_CODEC_ID_PCM_F32LE) || par->sample_rate < 8000 || par->sample_rate > 96000 ||
             par->ch_layout.nb_channels < 1 || par->ch_layout.nb_channels > 2)
            return fail(j, OC_MEDIA_INVALID, AVERROR_INVALIDDATA, "only mono/stereo 8-96kHz PCM WAV supported");
    }
    if (in->fmt->duration == AV_NOPTS_VALUE || in->fmt->duration <= 0)
        return fail(j, OC_MEDIA_INVALID, AVERROR_INVALIDDATA, "source must declare a finite positive duration");
    if (in->fmt->duration > (int64_t)j->l.max_duration_ms * 1000)
        return fail(j, OC_MEDIA_BUDGET, AVERROR_INVALIDDATA, "source duration budget");
    const AVCodec *dec = avcodec_find_decoder(par->codec_id); if (!dec) return AVERROR_DECODER_NOT_FOUND;
    in->dec = avcodec_alloc_context3(dec); if (!in->dec) return AVERROR(ENOMEM);
    r = avcodec_parameters_to_context(in->dec, par); if (r < 0) return r;
    in->dec->thread_count = 1;
    in->dec->max_pixels = (int64_t)j->l.max_width * j->l.max_height;
    r = avcodec_open2(in->dec, dec, NULL); if (r < 0) return r;
    in->pkt = av_packet_alloc(); in->frame = av_frame_alloc();
    return in->pkt && in->frame ? 0 : AVERROR(ENOMEM);
}
/* One frame at a time; no complete movie/audio buffer. */
static int next_frame(Job *j, Input *in) {
    for (;;) {
        if (interrupted(j)) return AVERROR_EXIT;
        int r = avcodec_receive_frame(in->dec, in->frame);
        if (r != AVERROR(EAGAIN)) return r;
        if (in->sent_eof) return AVERROR_EOF;
        do {
            av_packet_unref(in->pkt); r = av_read_frame(in->fmt, in->pkt);
        } while (r >= 0 && in->pkt->stream_index != in->stream && !interrupted(j));
        if (r == AVERROR_EOF) { in->sent_eof = 1; r = avcodec_send_packet(in->dec, NULL); }
        else if (r >= 0) r = avcodec_send_packet(in->dec, in->pkt);
        av_packet_unref(in->pkt); if (r < 0) return r;
    }
}
static int encoded(Job *j, AVCodecContext *enc, AVStream *st, AVFrame *f) {
    if (interrupted(j)) return AVERROR_EXIT;
    int r = avcodec_send_frame(enc, f); if (r < 0) return r;
    AVPacket *pkt = av_packet_alloc(); if (!pkt) return AVERROR(ENOMEM);
    while ((r = avcodec_receive_packet(enc, pkt)) >= 0) {
        if (interrupted(j)) { r = AVERROR_EXIT; break; }
        av_packet_rescale_ts(pkt, enc->time_base, st->time_base); pkt->stream_index = st->index;
        r = av_interleaved_write_frame(j->mux, pkt); av_packet_unref(pkt);
        if (r < 0) break;
    }
    av_packet_free(&pkt);
    return r == AVERROR(EAGAIN) || r == AVERROR_EOF ? 0 : r;
}
/* Verify actual encoder SPS, not merely requested AVCodecContext fields. The
   upstream OpenH264 adapter may warn about profile enum translation; fail closed
   if a future encoder ever produces a different Android compatibility envelope. */
static int baseline_sps(const uint8_t *p, int n) {
    for (int i = 0; i + 7 < n; ++i) {
        int skip = !p[i] && !p[i+1] && p[i+2] == 1 ? 3 :
                   !p[i] && !p[i+1] && !p[i+2] && p[i+3] == 1 ? 4 : 0;
        if (skip && i + skip + 3 < n && (p[i+skip] & 31) == 7)
            return p[i+skip+1] == 66 && (p[i+skip+2] & 0xc0) == 0xc0 && p[i+skip+3] <= 30;
    }
    return 0;
}
static int setup_mux(Job *j, int video, int output_fd) {
    int r = avformat_alloc_output_context2(&j->mux, NULL, video ? "mp4" : "ipod", NULL); if (r < 0) return r;
    j->out = (IO){.job=j, .fd=output_fd, .writable=1};
    uint8_t *b = av_malloc(32768); if (!b) return AVERROR(ENOMEM);
    j->out_pb = avio_alloc_context(b, 32768, 1, &j->out, NULL, write_cb, seek_cb);
    if (!j->out_pb) { av_free(b); return AVERROR(ENOMEM); }
    j->mux->pb = j->out_pb; j->mux->flags |= AVFMT_FLAG_CUSTOM_IO;
    j->mux->interrupt_callback = (AVIOInterruptCB){interrupted, j};
    if (video) {
        const AVCodec *c = avcodec_find_encoder_by_name("libopenh264"); if (!c) return AVERROR_ENCODER_NOT_FOUND;
        j->ve = avcodec_alloc_context3(c); if (!j->ve) return AVERROR(ENOMEM);
        AVCodecContext *e = j->ve;
        e->width = j->video.dec->width; e->height = j->video.dec->height;
        if (e->width % 2 || e->height % 2 || e->width > 640 || e->height > 480)
            return fail(j, OC_MEDIA_INVALID, AVERROR(EINVAL), "Android baseline envelope: even dimensions <=640x480");
        AVRational fps = av_guess_frame_rate(j->video.fmt, j->video.fmt->streams[j->video.stream], NULL);
        if (fps.num < 1 || fps.den < 1 || av_q2d(fps) > 30.001)
            return fail(j, OC_MEDIA_INVALID, AVERROR(EINVAL), "Android baseline envelope: 0<fps<=30");
        e->framerate = fps; e->time_base = av_inv_q(fps); e->pix_fmt = AV_PIX_FMT_YUV420P;
        e->profile = AV_PROFILE_H264_CONSTRAINED_BASELINE; e->level = 30;
        e->bit_rate = 1800000; e->rc_max_rate = 2000000; e->rc_buffer_size = 2000000;
        e->gop_size = 60; e->max_b_frames = 0; e->thread_count = 1;
        e->flags |= AV_CODEC_FLAG_GLOBAL_HEADER;
        AVDictionary *opts = NULL; av_dict_set(&opts, "rc_mode", "bitrate", 0);
        av_dict_set(&opts, "allow_skip_frames", "0", 0); av_dict_set(&opts, "coder", "cavlc", 0);
        r = avcodec_open2(e, c, &opts); av_dict_free(&opts); if (r < 0) return r;
        if (!baseline_sps(e->extradata, e->extradata_size))
            return fail(j, OC_MEDIA_CODEC, AVERROR_INVALIDDATA, "encoder SPS is not ConstrainedBaseline <=Level3");
        j->vs = avformat_new_stream(j->mux, NULL); if (!j->vs) return AVERROR(ENOMEM);
        j->vs->time_base = e->time_base; j->vs->avg_frame_rate = fps;
        r = avcodec_parameters_from_context(j->vs->codecpar, e); if (r < 0) return r;
        j->r->width = e->width; j->r->height = e->height;
        j->vf = av_frame_alloc(); if (!j->vf) return AVERROR(ENOMEM);
        j->vf->format = e->pix_fmt; j->vf->width = e->width; j->vf->height = e->height;
        r = av_frame_get_buffer(j->vf, 32); if (r < 0) return r;
    }
    const AVCodec *aac = avcodec_find_encoder_by_name("aac"); if (!aac) return AVERROR_ENCODER_NOT_FOUND;
    j->ae = avcodec_alloc_context3(aac); if (!j->ae) return AVERROR(ENOMEM);
    j->ae->sample_rate = 44100; j->ae->sample_fmt = AV_SAMPLE_FMT_FLTP;
    j->ae->bit_rate = 128000; j->ae->profile = AV_PROFILE_AAC_LOW;
    j->ae->time_base = (AVRational){1, 44100}; j->ae->thread_count = 1;
    av_channel_layout_default(&j->ae->ch_layout, 2); j->ae->flags |= AV_CODEC_FLAG_GLOBAL_HEADER;
    r = avcodec_open2(j->ae, aac, NULL); if (r < 0) return r;
    j->as = avformat_new_stream(j->mux, NULL); if (!j->as) return AVERROR(ENOMEM);
    j->as->time_base = j->ae->time_base;
    r = avcodec_parameters_from_context(j->as->codecpar, j->ae); if (r < 0) return r;
    j->r->sample_rate = 44100; j->r->channels = 2;
    j->fifo = av_audio_fifo_alloc(AV_SAMPLE_FMT_FLTP, 2, 16384); if (!j->fifo) return AVERROR(ENOMEM);
    return avformat_write_header(j->mux, NULL);
}
static int append_audio(Job *j, AVFrame *f) {
    if (!j->swr) {
        int r = swr_alloc_set_opts2(&j->swr, &j->ae->ch_layout, j->ae->sample_fmt, 44100,
                                   &f->ch_layout, f->format, f->sample_rate, 0, NULL);
        if (r < 0 || (r = swr_init(j->swr)) < 0) return r;
        j->audio_in_rate = f->sample_rate; j->audio_in_fmt = f->format;
        av_channel_layout_copy(&j->audio_in_layout, &f->ch_layout);
    }
    if (f && (f->sample_rate != j->audio_in_rate || f->format != j->audio_in_fmt ||
              av_channel_layout_compare(&f->ch_layout, &j->audio_in_layout)))
        return AVERROR_INVALIDDATA;
    int needed = swr_get_out_samples(j->swr, f ? f->nb_samples : 0);
    if (needed < 0 || needed > 262144 || av_audio_fifo_size(j->fifo) > 262144)
        return fail(j, OC_MEDIA_BUDGET, AVERROR(ENOMEM), "audio-frame buffer budget");
    uint8_t **data = NULL; int r = av_samples_alloc_array_and_samples(&data, NULL, 2, needed > 0 ? needed : 1, AV_SAMPLE_FMT_FLTP, 0);
    if (r < 0) return r;
    r = swr_convert(j->swr, data, needed, f ? (const uint8_t **)f->extended_data : NULL, f ? f->nb_samples : 0);
    if (r > 0) {
        int n = r; r = av_audio_fifo_write(j->fifo, (void **)data, n);
        if (r == n) r = n; else r = AVERROR(ENOMEM);
    }
    av_freep(&data[0]); av_freep(&data); return r;
}
static int audio_until(Job *j, int64_t target, int finish) {
    if (target > j->audio_limit) target = j->audio_limit;
    while (j->audio_pts < target) {
        if (interrupted(j)) return AVERROR_EXIT;
        int remain = (int)FFMIN((int64_t)j->ae->frame_size, target - j->audio_pts);
        if (!finish && remain < j->ae->frame_size) break;
        while (av_audio_fifo_size(j->fifo) < remain && !j->audio_eof) {
            int r = next_frame(j, &j->audio);
            if (r == AVERROR_EOF) j->audio_eof = 1;
            else if (r < 0) return r;
            else {
                r = append_audio(j, j->audio.frame); av_frame_unref(j->audio.frame);
                if (r < 0) return r;
            }
        }
        if (j->audio_eof && !j->swr_eof && j->swr) {
            int r = append_audio(j, NULL); if (r < 0) return r; if (!r) j->swr_eof = 1;
        }
        int available = av_audio_fifo_size(j->fifo);
        if (!available) break;
        if (available < remain) { if (!j->audio_eof) continue; remain = available; }
        AVFrame *f = av_frame_alloc(); if (!f) return AVERROR(ENOMEM);
        f->format = j->ae->sample_fmt; f->sample_rate = 44100; f->nb_samples = remain;
        av_channel_layout_copy(&f->ch_layout, &j->ae->ch_layout);
        int r = av_frame_get_buffer(f, 0);
        if (r >= 0 && av_audio_fifo_read(j->fifo, (void **)f->extended_data, remain) != remain) r = AVERROR(EIO);
        f->pts = j->audio_pts;
        if (r >= 0) r = encoded(j, j->ae, j->as, f);
        av_frame_free(&f); if (r < 0) return r;
        j->audio_pts += remain; j->r->audio_samples = j->audio_pts;
    }
    return 0;
}
static void close_input(Input *in) {
    avcodec_free_context(&in->dec); avformat_close_input(&in->fmt);
    if (in->pb) { av_freep(&in->pb->buffer); avio_context_free(&in->pb); }
    av_packet_free(&in->pkt); av_frame_free(&in->frame);
}
static void cleanup(Job *j) {
    close_input(&j->video); close_input(&j->audio);
    avcodec_free_context(&j->ve); avcodec_free_context(&j->ae);
    sws_freeContext(j->sws); swr_free(&j->swr); av_audio_fifo_free(j->fifo);
    av_channel_layout_uninit(&j->audio_in_layout); av_frame_free(&j->vf);
    avformat_free_context(j->mux);
    if (j->out_pb) { av_freep(&j->out_pb->buffer); avio_context_free(&j->out_pb); }
}
const char *oc_media_build_info(void) { return "oc_media ABI1; FFmpeg " AV_STRINGIFY(LIBAVCODEC_VERSION_MAJOR) "; OpenH264 2.6.0; LGPL-2.1-or-later + BSD-2-Clause; no x264/GPL/network/programs"; }
int oc_media_convert_fd(int mode, int source_fd, int audio_fd, int output_fd,
                        const oc_media_limits *limits, oc_media_cancel cancel,
                        void *opaque, oc_media_result *result) {
    if (!result || !limits || result->size != sizeof *result || result->abi != OC_MEDIA_ABI) return OC_MEDIA_INVALID;
    memset(result, 0, sizeof *result); result->abi = OC_MEDIA_ABI; result->size = sizeof *result;
    Job j = {.r=result, .cancel=cancel, .opaque=opaque, .start_us=now_us()};
    if (limits->abi != OC_MEDIA_ABI || limits->size != sizeof *limits ||
        !limits->max_input_bytes || limits->max_input_bytes > INT64_MAX ||
        !limits->max_output_bytes || limits->max_output_bytes > INT64_MAX ||
        !limits->max_duration_ms || limits->max_duration_ms > 3600000 ||
        !limits->max_video_frames || !limits->max_wall_ms || limits->max_wall_ms > 86400000 ||
        !limits->max_width || limits->max_width > 4096 || !limits->max_height || limits->max_height > 4096 ||
        limits->preview_duration_ms > limits->max_duration_ms ||
        (mode != OC_MEDIA_WAV_AAC && mode != OC_MEDIA_BINK_AVC_AAC)) {
        fail(&j, OC_MEDIA_INVALID, 0, "invalid ABI / limits / mode"); return j.failure;
    }
    j.l = *limits; int video = mode == OC_MEDIA_BINK_AVC_AAC;
    int r = 0; struct stat out_st, src_st, aud_st;
    if (interrupted(&j)) { r = AVERROR_EXIT; goto done; }
    r = regular_fd(&j, output_fd, 1, &out_st); if (r < 0) goto done;
    r = regular_fd(&j, source_fd, 0, &src_st); if (r < 0) goto done;
    if (out_st.st_dev == src_st.st_dev && out_st.st_ino == src_st.st_ino) { r = AVERROR(EINVAL); goto done; }
    if (video) {
        r = regular_fd(&j, audio_fd, 0, &aud_st); if (r < 0) goto done;
        if (out_st.st_dev == aud_st.st_dev && out_st.st_ino == aud_st.st_ino) { r = AVERROR(EINVAL); goto done; }
        r = open_input(&j, &j.video, source_fd, 1); if (r < 0) goto done;
    }
    r = open_input(&j, &j.audio, video ? audio_fd : source_fd, 0); if (r < 0) goto done;
    int64_t duration = (int64_t)j.l.max_duration_ms * 1000;
    if (j.audio.fmt->duration > 0 && j.audio.fmt->duration < duration) duration = j.audio.fmt->duration;
    if (video && j.video.fmt->duration > 0 && j.video.fmt->duration < duration) duration = j.video.fmt->duration;
    if (j.l.preview_duration_ms && (int64_t)j.l.preview_duration_ms * 1000 < duration) duration = (int64_t)j.l.preview_duration_ms * 1000;
    j.audio_limit = av_rescale(duration, 44100, 1000000);
    r = setup_mux(&j, video, output_fd); if (r < 0) goto done;
    if (video) {
        for (;;) {
            int64_t t = av_rescale_q(j.video_pts, j.ve->time_base, AV_TIME_BASE_Q);
            if (t >= duration) break;
            if (j.r->video_frames >= j.l.max_video_frames) { r = fail(&j, OC_MEDIA_BUDGET, 0, "video-frame budget"); goto done; }
            r = next_frame(&j, &j.video);
            if (r == AVERROR_EOF) {
                int64_t frame_us = av_rescale_q(1, j.ve->time_base, AV_TIME_BASE_Q);
                r = t + frame_us < duration ? AVERROR_INVALIDDATA : 0;
                if (r < 0) goto done;
                break;
            }
            if (r < 0) goto done;
            AVFrame *f = j.video.frame;
            if (f->width != j.ve->width || f->height != j.ve->height) { r = AVERROR_INVALIDDATA; goto done; }
            r = av_frame_make_writable(j.vf); if (r < 0) goto done;
            j.sws = sws_getCachedContext(j.sws, f->width, f->height, f->format, j.ve->width, j.ve->height, j.ve->pix_fmt, SWS_BILINEAR, NULL, NULL, NULL);
            if (!j.sws) { r = AVERROR(ENOMEM); goto done; }
            r = sws_scale(j.sws, (const uint8_t *const *)f->data, f->linesize, 0, f->height, j.vf->data, j.vf->linesize);
            av_frame_unref(f); if (r != j.ve->height) { r = AVERROR_INVALIDDATA; goto done; }
            j.vf->pts = j.video_pts++;
            r = encoded(&j, j.ve, j.vs, j.vf); if (r < 0) goto done;
            j.r->video_frames++;
            int64_t audio_target = av_rescale_q(j.video_pts, j.ve->time_base, j.ae->time_base);
            r = audio_until(&j, audio_target, 0); if (r < 0) goto done;
        }
        j.audio_limit = FFMIN(j.audio_limit, av_rescale_q(j.video_pts, j.ve->time_base, j.ae->time_base));
        r = encoded(&j, j.ve, j.vs, NULL); if (r < 0) goto done;
    }
    r = audio_until(&j, j.audio_limit, 1); if (r < 0) goto done;
    if (!j.r->audio_samples || j.audio_pts + 64 < j.audio_limit || (video && !j.r->video_frames)) {
        r = fail(&j, OC_MEDIA_CODEC, AVERROR_INVALIDDATA, "decoded stream ended before declared duration"); goto done;
    }
    r = encoded(&j, j.ae, j.as, NULL); if (r < 0) goto done;
    r = av_write_trailer(j.mux); if (r < 0) goto done;
    avio_flush(j.out_pb); if (j.out_pb->error < 0) { r = j.out_pb->error; goto done; }
    if (interrupted(&j)) { r = AVERROR_EXIT; goto done; }
    if (fsync(output_fd)) { r = fail(&j, OC_MEDIA_IO, AVERROR(errno), "fsync output"); goto done; }
    snprintf(result->message, sizeof result->message, "%s", j.l.preview_duration_ms ? "converted preview; blink overlay not implemented" : video ? "converted AVC/AAC; blink overlay not implemented" : "converted AAC-LC M4A");
done:
    if (r < 0 && !j.failure) fail(&j, OC_MEDIA_CODEC, r, "conversion");
    cleanup(&j); return result->status;
}
