/*
 * tinyalsa7.c -- one libtinyalsa for both sides of this port.
 *
 * The problem this replaces
 * -------------------------
 * /system/lib/libtinyalsa.so existed in two builds and only one of them could
 * ever be installed:
 *
 *   13580 bytes, Android 4.4 (KitKat)  -- the build audio.primary.msm8226.so
 *       was compiled against.  Its struct pcm_config is 36 bytes:
 *       channels, rate, period_size, period_count, format, start_threshold,
 *       stop_threshold, silence_threshold, avail_min.
 *   26420 bytes, Android 7.1           -- what the rest of this ROM wants.
 *       Same first eight fields, then silence_size and avail_min, 40 bytes.
 *
 * Install the 7.1 build and every pcm_open() from the KitKat HAL dies: the
 * library reads silence_size at offset 32, which in the 36-byte struct is
 * avail_min (240 for deep-buffer), and silence_threshold at 28, which is 0.
 * snd_pcm_sw_params() rejects silence_size > silence_threshold with EINVAL, so
 * the HAL logs "cannot set sw params: Invalid argument" and returns.  Install
 * the KitKat build and every 7.1 caller (the AOSP USB and r_submix HALs) reads
 * the wrong avail_min.  Section 34 of docs/DEVICE_NOTES.md.
 *
 * What this does instead
 * ----------------------
 * A 7.1-ABI library -- the full 7.1 symbol set, so nothing that links against
 * libtinyalsa has to change -- that reads the config by field and never past
 * offset 32.  silence filling is switched off unconditionally (threshold 0,
 * size 0): it is an underrun nicety the Android HALs do not use, and it is the
 * exact field pair whose meaning moved between the two structs.  avail_min is
 * taken from offset 32 when it looks like one (the KitKat layout), otherwise
 * from period_size (the 7.1 layout puts silence_size there, usually 0).
 *
 * Result: one library, no downgrade, both ABIs.
 *
 * Build: see build.sh in this directory.  No libc headers beyond the kernel
 * UAPI: the .so keeps libc symbols undefined and declares DT_NEEDED libc.so, so
 * bionic resolves them at load time exactly as it does for the stock library.
 */

#include <stddef.h>
#include <stdint.h>
#include <stdarg.h>
#include <time.h>
#include <linux/ioctl.h>

/*
 * No glibc headers for the system calls, on purpose.  A modern 32-bit glibc
 * rewrites open() to open64(), mmap() to mmap64() and ioctl() to
 * __ioctl_time64(); bionic has none of those names, so the .so would not even
 * load on the phone.  Declared here with the plain bionic names, and the two
 * or three constants this file needs are spelled out.
 */
extern int open(const char *path, int flags, ...);
extern int close(int fd);
extern int ioctl(int fd, unsigned long request, ...);
extern void *mmap(void *addr, size_t length, int prot, int flags, int fd, long offset);
extern int munmap(void *addr, size_t length);
extern void *calloc(size_t n, size_t size);
extern void free(void *p);
struct pollfd {
    int fd;
    short events;
    short revents;
};
extern int poll(struct pollfd *fds, unsigned long nfds, int timeout);

#ifndef O_RDWR
#define O_RDWR      00000002
#endif
#ifndef O_NONBLOCK
#define O_NONBLOCK  00004000
#endif
#ifndef PROT_READ
#define PROT_READ   0x1
#endif
#ifndef PROT_WRITE
#define PROT_WRITE  0x2
#endif
#ifndef MAP_SHARED
#define MAP_SHARED  0x01
#endif
#ifndef MAP_FAILED
#define MAP_FAILED  ((void *)-1)
#endif
#define MAP_FILE    0
#define POLLIN      0x001
#define POLLOUT     0x004

/* The 3.4 kernel's own UAPI header.  Pulled in with -I on the kernel tree so
 * the ioctl numbers and struct layouts are the ones this device's ALSA stack
 * actually implements -- not a modern distro's idea of them. */
#include <sound/asound.h>

#define TL_EXPORT __attribute__((visibility("default")))

/* Bumped when the behaviour changes; the boot report greps for this string so
 * a dump always says which build of the library produced it. */
TL_EXPORT const char kc_tinyalsa_version[] =
    "kc-tinyalsa7/fix77: 7.1 symbol set, reads both 36- and 40-byte pcm_config";


/* ------------------------------------------------------------------ */
/* flags and formats, from 7.1's tinyalsa.h                            */
/* ------------------------------------------------------------------ */

#define PCM_OUT        0x00000000
#define PCM_IN         0x10000000
#define PCM_MMAP       0x00000001
#define PCM_NOIRQ      0x00000002
#define PCM_NOREPORT   0x00000004
#define PCM_MONOTONIC  0x00000008

enum pcm_format {
    PCM_FORMAT_INVALID = -1,
    PCM_FORMAT_S16_LE = 0,
    PCM_FORMAT_S32_LE,
    PCM_FORMAT_S8,
    PCM_FORMAT_S24_LE,
    PCM_FORMAT_S24_3LE,
    PCM_FORMAT_MAX,
};

/* 40 bytes, as 7.1 declares it.  Callers compiled against the 36-byte version
 * pass a shorter object; see config_read(). */
struct pcm_config {
    unsigned int channels;
    unsigned int rate;
    unsigned int period_size;
    unsigned int period_count;
    unsigned int format;
    unsigned int start_threshold;
    unsigned int stop_threshold;
    unsigned int silence_threshold;
    unsigned int silence_size;
    unsigned int avail_min;
};

struct pcm {
    int fd;
    unsigned int flags;
    unsigned int card;
    unsigned int device;
    unsigned int buffer_size;      /* frames */
    unsigned int period_size;      /* frames */
    unsigned int channels;
    unsigned int frame_size;       /* bytes per frame */
    struct pcm_config config;
    char error[128];
    int prepared;
    unsigned int state;
    /* mmap */
    void *mmap_buffer;
    unsigned int mmap_frames;      /* frames in the mapping == buffer_size */
    unsigned int mmap_offset;      /* frames handed out by pcm_mmap_begin */
    struct snd_pcm_sync_ptr *sync_ptr;
    /* capture without irq */
    unsigned int xfer_align;
};

struct mixer;
struct mixer_ctl {
    struct mixer *mixer;
    struct snd_ctl_elem_info *info;
    char *name;
    unsigned int count;
    unsigned int type;
};

struct mixer {
    int fd;
    struct snd_ctl_elem_info *info;
    struct mixer_ctl *ctl;
    unsigned int count;
    char name[32];
};

/* ------------------------------------------------------------------ */
/* small helpers -- no errno, no stdio                                 */
/* ------------------------------------------------------------------ */

static void tl_memcpy(void *d, const void *s, size_t n)
{
    unsigned char *dd = d;
    const unsigned char *ss = s;
    while (n--)
        *dd++ = *ss++;
}

static void tl_memset(void *d, int c, size_t n)
{
    unsigned char *dd = d;
    while (n--)
        *dd++ = (unsigned char)c;
}

static size_t tl_strlen(const char *s)
{
    const char *p = s;
    while (*p)
        p++;
    return (size_t)(p - s);
}

static int tl_strcmp(const char *a, const char *b)
{
    while (*a && *a == *b) { a++; b++; }
    return (unsigned char)*a - (unsigned char)*b;
}

static int tl_strncmp(const char *a, const char *b, size_t n)
{
    while (n && *a && *a == *b) { a++; b++; n--; }
    if (!n)
        return 0;
    return (unsigned char)*a - (unsigned char)*b;
}

static void tl_strcpy(char *d, const char *s)
{
    while ((*d++ = *s++))
        ;
}

/* integer to decimal, for the device node name */
static char *tl_utoa(unsigned int v, char *end)
{
    char tmp[12];
    int i = 0;
    do {
        tmp[i++] = (char)('0' + v % 10);
        v /= 10;
    } while (v);
    while (i)
        *end++ = tmp[--i];
    *end = 0;
    return end;
}

static void set_error(struct pcm *pcm, const char *msg)
{
    if (!pcm)
        return;
    tl_strcpy(pcm->error, msg);
}

/* ------------------------------------------------------------------ */
/* hw_params helpers                                                   */
/* ------------------------------------------------------------------ */

static void param_init(struct snd_pcm_hw_params *p)
{
    tl_memset(p, 0, sizeof(*p));
}

static void param_set_mask(struct snd_pcm_hw_params *p, unsigned int var, unsigned int val)
{
    if (val >= 8 * sizeof(p->masks[0].bits))
        return;
    p->masks[var].bits[val >> 5] |= (1U << (val & 31));
    p->rmask |= (1U << var);
}

static void param_set_min(struct snd_pcm_hw_params *p, unsigned int var, unsigned int val)
{
    p->intervals[var].min = val;
    p->rmask |= (1U << var);
}

static void param_set_max(struct snd_pcm_hw_params *p, unsigned int var, unsigned int val)
{
    p->intervals[var].max = val;
    p->rmask |= (1U << var);
}

static void param_set_int(struct snd_pcm_hw_params *p, unsigned int var, unsigned int val)
{
    p->intervals[var].min = val;
    p->intervals[var].max = val;
    p->rmask |= (1U << var);
}

static unsigned int param_get_int(struct snd_pcm_hw_params *p, unsigned int var)
{
    return p->intervals[var].max;
}

TL_EXPORT unsigned int pcm_format_to_bits(unsigned int format)
{
    switch (format) {
    case PCM_FORMAT_S16_LE:  return 16;
    case PCM_FORMAT_S24_LE:
    case PCM_FORMAT_S32_LE:  return 32;
    case PCM_FORMAT_S24_3LE: return 24;
    case PCM_FORMAT_S8:      return 8;
    default:                 return 0;
    }
}

static unsigned int format_to_alsa(unsigned int format)
{
    switch (format) {
    case PCM_FORMAT_S16_LE:  return SNDRV_PCM_FORMAT_S16_LE;
    case PCM_FORMAT_S32_LE:  return SNDRV_PCM_FORMAT_S32_LE;
    case PCM_FORMAT_S8:      return SNDRV_PCM_FORMAT_S8;
    case PCM_FORMAT_S24_LE:  return SNDRV_PCM_FORMAT_S24_LE;
    case PCM_FORMAT_S24_3LE: return SNDRV_PCM_FORMAT_S24_3LE;
    default:                 return SNDRV_PCM_FORMAT_S16_LE;
    }
}

/* ------------------------------------------------------------------ */
/* the one place the two struct pcm_config layouts meet                */
/* ------------------------------------------------------------------ */

/*
 * Reads a caller's config without ever touching byte 36.  Offsets 0..31 are
 * identical in both layouts (channels, rate, period_size, period_count,
 * format, start_threshold, stop_threshold, silence_threshold); only offset 32
 * differs, avail_min vs silence_size.
 *
 * An avail_min has to be a frame count no larger than the ring, and every QCOM
 * config in this HAL uses either period_size or 0.  A silence_size is either 0
 * or a multiple of period_size, and is 0 in the one build that sets it here.
 * So: take offset 32 as avail_min when it is in range; otherwise use
 * period_size, which is what the caller meant in both ABIs.
 */
static void config_read(struct pcm_config *dst, const void *src)
{
    const unsigned int *s = (const unsigned int *)src;
    unsigned int ring;

    dst->channels = s[0];
    dst->rate = s[1];
    dst->period_size = s[2];
    dst->period_count = s[3];
    dst->format = s[4];
    dst->start_threshold = s[5];
    dst->stop_threshold = s[6];
    dst->silence_threshold = s[7];

    ring = dst->period_size * dst->period_count;
    dst->avail_min = s[8];
    if (dst->avail_min == 0 || dst->avail_min > ring)
        dst->avail_min = dst->period_size;

    /* Never forwarded to the kernel.  See the file header. */
    dst->silence_threshold = 0;
    dst->silence_size = 0;
}

/* ------------------------------------------------------------------ */
/* pcm                                                                 */
/* ------------------------------------------------------------------ */

static int pcm_sync_ptr(struct pcm *pcm, int flags)
{
    struct snd_pcm_sync_ptr *sp = pcm->sync_ptr;

    if (!sp) {
        set_error(pcm, "no sync_ptr buffer");
        return -1;
    }
    sp->flags = (unsigned int)flags;
    if (ioctl(pcm->fd, SNDRV_PCM_IOCTL_SYNC_PTR, sp) < 0) {
        set_error(pcm, "SNDRV_PCM_IOCTL_SYNC_PTR failed");
        return -1;
    }
    return 0;
}

TL_EXPORT const char *pcm_get_error(struct pcm *pcm)
{
    return pcm ? pcm->error : "invalid pcm";
}

TL_EXPORT unsigned int pcm_get_buffer_size(struct pcm *pcm)
{
    return pcm ? pcm->buffer_size : 0;
}

TL_EXPORT unsigned int pcm_get_poll_fd(struct pcm *pcm)
{
    return pcm ? (unsigned int)pcm->fd : (unsigned int)-1;
}

TL_EXPORT unsigned int pcm_frames_to_bytes(struct pcm *pcm, unsigned int frames)
{
    if (!pcm)
        return 0;
    return frames * pcm->frame_size;
}

TL_EXPORT unsigned int pcm_bytes_to_frames(struct pcm *pcm, unsigned int bytes)
{
    if (!pcm || !pcm->frame_size)
        return 0;
    return bytes / pcm->frame_size;
}

TL_EXPORT int pcm_is_ready(struct pcm *pcm)
{
    return pcm != NULL && pcm->fd >= 0;
}

TL_EXPORT int pcm_get_htimestamp(struct pcm *pcm, unsigned int *avail, struct timespec *tstamp)
{
    unsigned int hw_ptr, app_ptr, frames;

    if (!pcm || !avail || !tstamp)
        return -1;
    if (!pcm->sync_ptr)
        return -1;
    if (pcm_sync_ptr(pcm, SNDRV_PCM_SYNC_PTR_HWSYNC) < 0)
        return -1;

    hw_ptr = pcm->sync_ptr->s.status.hw_ptr;
    app_ptr = pcm->sync_ptr->c.control.appl_ptr;
    if (pcm->flags & PCM_IN) {
        frames = hw_ptr - app_ptr;
        if (frames > pcm->buffer_size)
            frames = pcm->buffer_size;
    } else {
        frames = pcm->buffer_size + hw_ptr - app_ptr;
        frames %= pcm->buffer_size;
    }
    *avail = frames;
    *tstamp = pcm->sync_ptr->s.status.tstamp;
    return 0;
}

TL_EXPORT int pcm_state(struct pcm *pcm)
{
    unsigned int state;

    if (!pcm)
        return -1;
    if (pcm->sync_ptr) {
        if (pcm_sync_ptr(pcm, 0) < 0)
            return -1;
        state = pcm->sync_ptr->s.status.state;
    } else {
        struct snd_pcm_status st;
        tl_memset(&st, 0, sizeof(st));
        if (ioctl(pcm->fd, SNDRV_PCM_IOCTL_STATUS, &st) < 0)
            return -1;
        state = st.state;
    }
    pcm->state = state;
    return (int)state;
}

static int pcm_sw_params(struct pcm *pcm)
{
    struct snd_pcm_sw_params sp;

    tl_memset(&sp, 0, sizeof(sp));
    sp.tstamp_mode = SNDRV_PCM_TSTAMP_ENABLE;
    sp.period_step = 1;
    sp.avail_min = pcm->config.avail_min ? pcm->config.avail_min : pcm->period_size;
    sp.start_threshold = pcm->config.start_threshold;
    sp.stop_threshold = pcm->config.stop_threshold;
    sp.silence_threshold = 0;
    sp.silence_size = 0;
    if (ioctl(pcm->fd, SNDRV_PCM_IOCTL_SW_PARAMS, &sp) < 0) {
        set_error(pcm, "cannot set sw params");
        return -1;
    }
    return 0;
}

static int pcm_hw_params(struct pcm *pcm)
{
    struct snd_pcm_hw_params params;
    unsigned int fmt = format_to_alsa(pcm->config.format);

    param_init(&params);
    param_set_mask(&params, SNDRV_PCM_HW_PARAM_FORMAT, fmt);
    param_set_mask(&params, SNDRV_PCM_HW_PARAM_SUBFORMAT, SNDRV_PCM_SUBFORMAT_STD);
    param_set_mask(&params, SNDRV_PCM_HW_PARAM_ACCESS,
                   (pcm->flags & PCM_MMAP) ? SNDRV_PCM_ACCESS_MMAP_INTERLEAVED
                                           : SNDRV_PCM_ACCESS_RW_INTERLEAVED);
    param_set_min(&params, SNDRV_PCM_HW_PARAM_PERIOD_SIZE, pcm->config.period_size);
    param_set_int(&params, SNDRV_PCM_HW_PARAM_PERIODS, pcm->config.period_count);
    param_set_int(&params, SNDRV_PCM_HW_PARAM_RATE, pcm->config.rate);
    param_set_int(&params, SNDRV_PCM_HW_PARAM_CHANNELS, pcm->config.channels);

    if (ioctl(pcm->fd, SNDRV_PCM_IOCTL_HW_PARAMS, &params) < 0) {
        set_error(pcm, "cannot set hw params");
        return -1;
    }

    pcm->buffer_size = param_get_int(&params, SNDRV_PCM_HW_PARAM_BUFFER_SIZE);
    pcm->period_size = param_get_int(&params, SNDRV_PCM_HW_PARAM_PERIOD_SIZE);
    pcm->channels = pcm->config.channels;
    if (!pcm->buffer_size || !pcm->period_size) {
        set_error(pcm, "hw params came back empty");
        return -1;
    }
    return 0;
}

TL_EXPORT struct pcm *pcm_open(unsigned int card, unsigned int device,
                               unsigned int flags, struct pcm_config *config)
{
    struct pcm *pcm;
    char fn[64];
    char *p;
    unsigned int bits;

    if (!config)
        return NULL;

    pcm = (struct pcm *)calloc(1, sizeof(*pcm));
    if (!pcm)
        return NULL;

    pcm->flags = flags;
    pcm->card = card;
    pcm->device = device;
    pcm->fd = -1;

    config_read(&pcm->config, config);

    if (!pcm->config.period_size || !pcm->config.period_count) {
        set_error(pcm, "period_size/period_count not set");
        goto fail;
    }
    if (!pcm->config.rate || !pcm->config.channels) {
        set_error(pcm, "rate/channels not set");
        goto fail;
    }

    bits = pcm_format_to_bits(pcm->config.format);
    if (!bits) {
        set_error(pcm, "unsupported format");
        goto fail;
    }
    pcm->frame_size = (bits / 8) * pcm->config.channels;

    tl_strcpy(fn, "/dev/snd/pcmC");
    p = tl_utoa(card, fn + tl_strlen(fn));
    *p++ = 'D';
    p = tl_utoa(device, p);
    *p++ = (flags & PCM_IN) ? 'c' : 'p';
    *p = 0;

    pcm->fd = open(fn, O_RDWR | ((flags & PCM_NOIRQ) ? O_NONBLOCK : 0), 0);
    if (pcm->fd < 0) {
        set_error(pcm, "cannot open device node");
        goto fail;
    }

    if (pcm_hw_params(pcm) < 0)
        goto fail;

    if (flags & PCM_MMAP) {
        unsigned int bytes = pcm->buffer_size * pcm->frame_size;
        pcm->mmap_buffer = mmap(NULL, bytes, PROT_READ | PROT_WRITE,
                                MAP_FILE | MAP_SHARED, pcm->fd, 0);
        if (pcm->mmap_buffer == MAP_FAILED) {
            pcm->mmap_buffer = NULL;
            set_error(pcm, "cannot mmap the ring");
            goto fail;
        }
        pcm->mmap_frames = pcm->buffer_size;
    }

    if (!(flags & PCM_NOIRQ)) {
        pcm->sync_ptr = (struct snd_pcm_sync_ptr *)calloc(1, sizeof(*pcm->sync_ptr));
        if (!pcm->sync_ptr) {
            set_error(pcm, "no memory for sync_ptr");
            goto fail;
        }
        if (pcm_sync_ptr(pcm, 0) < 0)
            goto fail;
    }

    if (pcm_sw_params(pcm) < 0)
        goto fail;

    pcm->prepared = 0;
    pcm->state = SNDRV_PCM_STATE_OPEN;
    return pcm;

fail:
    if (pcm->mmap_buffer)
        munmap(pcm->mmap_buffer, pcm->buffer_size * pcm->frame_size);
    if (pcm->sync_ptr)
        free(pcm->sync_ptr);
    if (pcm->fd >= 0)
        close(pcm->fd);
    /*
     * NULL, not a half-built object.  Both eras test the result with
     * pcm_is_ready(), and in both it is nothing but "pcm != NULL" -- the
     * KitKat HAL's copy is an inline in its own pcm.h.  Returning a non-NULL
     * object with fd == -1 would therefore read as success there, and the next
     * pcm_write would go into a dead descriptor.
     */
    free(pcm);
    return NULL;
}

TL_EXPORT int pcm_close(struct pcm *pcm)
{
    if (!pcm)
        return 0;
    if (pcm->mmap_buffer)
        munmap(pcm->mmap_buffer, pcm->buffer_size * pcm->frame_size);
    if (pcm->sync_ptr)
        free(pcm->sync_ptr);
    if (pcm->fd >= 0)
        close(pcm->fd);
    free(pcm);
    return 0;
}

TL_EXPORT int pcm_prepare(struct pcm *pcm)
{
    if (!pcm || pcm->fd < 0)
        return -1;
    if (ioctl(pcm->fd, SNDRV_PCM_IOCTL_PREPARE, 0) < 0) {
        set_error(pcm, "cannot prepare");
        return -1;
    }
    pcm->prepared = 1;
    pcm->state = SNDRV_PCM_STATE_PREPARED;
    pcm->mmap_offset = 0;
    return 0;
}

TL_EXPORT int pcm_start(struct pcm *pcm)
{
    if (!pcm || pcm->fd < 0)
        return -1;
    if (ioctl(pcm->fd, SNDRV_PCM_IOCTL_START, 0) < 0) {
        set_error(pcm, "cannot start");
        return -1;
    }
    pcm->state = SNDRV_PCM_STATE_RUNNING;
    return 0;
}

TL_EXPORT int pcm_stop(struct pcm *pcm)
{
    if (!pcm || pcm->fd < 0)
        return -1;
    if (ioctl(pcm->fd, SNDRV_PCM_IOCTL_DROP, 0) < 0) {
        set_error(pcm, "cannot stop");
        return -1;
    }
    pcm->state = SNDRV_PCM_STATE_SETUP;
    pcm->prepared = 0;
    return 0;
}

TL_EXPORT int pcm_ioctl(struct pcm *pcm, int request, ...)
{
    va_list ap;
    void *arg;

    if (!pcm || pcm->fd < 0)
        return -1;
    va_start(ap, request);
    arg = va_arg(ap, void *);
    va_end(ap);
    return ioctl(pcm->fd, request, arg);
}

TL_EXPORT int pcm_wait(struct pcm *pcm, int timeout)
{
    struct pollfd pfd;
    int ret;

    if (!pcm || pcm->fd < 0)
        return -1;
    pfd.fd = pcm->fd;
    pfd.events = (pcm->flags & PCM_IN) ? POLLIN : POLLOUT;
    pfd.revents = 0;
    ret = poll(&pfd, 1, timeout);
    if (ret < 0) {
        set_error(pcm, "poll failed");
        return -1;
    }
    if (ret == 0) {
        set_error(pcm, "poll timed out");
        return -1;
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/* pcm transfer: the non-mmap path                                     */
/* ------------------------------------------------------------------ */

static int pcm_write_nommap(struct pcm *pcm, const void *data, unsigned int count)
{
    struct snd_xferi xfer;
    unsigned int frames = count / pcm->frame_size;
    const unsigned char *p = (const unsigned char *)data;

    while (frames) {
        xfer.buf = (void *)p;
        xfer.frames = frames;
        xfer.result = 0;
        if (ioctl(pcm->fd, SNDRV_PCM_IOCTL_WRITEI_FRAMES, &xfer) < 0) {
            set_error(pcm, "SNDRV_PCM_IOCTL_WRITEI_FRAMES failed");
            return -1;
        }
        if (!xfer.result) {
            set_error(pcm, "write transferred no frames");
            return -1;
        }
        frames -= (unsigned int)xfer.result;
        p += xfer.result * pcm->frame_size;
    }
    return 0;
}

static int pcm_read_nommap(struct pcm *pcm, void *data, unsigned int count)
{
    struct snd_xferi xfer;
    unsigned int frames = count / pcm->frame_size;
    unsigned char *p = (unsigned char *)data;

    while (frames) {
        xfer.buf = p;
        xfer.frames = frames;
        xfer.result = 0;
        if (ioctl(pcm->fd, SNDRV_PCM_IOCTL_READI_FRAMES, &xfer) < 0) {
            set_error(pcm, "SNDRV_PCM_IOCTL_READI_FRAMES failed");
            return -1;
        }
        if (!xfer.result) {
            set_error(pcm, "read transferred no frames");
            return -1;
        }
        frames -= (unsigned int)xfer.result;
        p += xfer.result * pcm->frame_size;
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/* pcm transfer: mmap                                                  */
/* ------------------------------------------------------------------ */

static unsigned int pcm_avail_count(struct pcm *pcm)
{
    unsigned int hw, app, avail;

    if (!pcm || pcm->fd < 0 || !pcm->sync_ptr || !pcm->buffer_size)
        return 0;
    if (pcm_sync_ptr(pcm, SNDRV_PCM_SYNC_PTR_HWSYNC) < 0)
        return 0;
    hw = pcm->sync_ptr->s.status.hw_ptr;
    app = pcm->sync_ptr->c.control.appl_ptr;
    if (pcm->flags & PCM_IN) {
        avail = hw - app;
        if (avail > pcm->buffer_size)
            avail = pcm->buffer_size;
    } else {
        avail = pcm->buffer_size + hw - app;
        avail %= pcm->buffer_size;
    }
    return avail;
}

TL_EXPORT int pcm_avail_update(struct pcm *pcm)
{
    return (int)pcm_avail_count(pcm);
}

TL_EXPORT int pcm_mmap_avail(struct pcm *pcm)
{
    return (int)pcm_avail_count(pcm);
}

TL_EXPORT int pcm_set_avail_min(struct pcm *pcm, int avail_min)
{
    if (!pcm || pcm->fd < 0 || (unsigned int)avail_min > pcm->buffer_size)
        return -1;
    pcm->config.avail_min = (unsigned int)avail_min;
    return pcm_sw_params(pcm);
}

TL_EXPORT int pcm_mmap_begin(struct pcm *pcm, void **areas, unsigned int *frames)
{
    unsigned int avail, offset, cont;

    if (!pcm || !pcm->mmap_buffer || !areas || !frames)
        return -1;
    avail = pcm_avail_count(pcm);
    offset = pcm->mmap_offset % pcm->buffer_size;
    cont = pcm->buffer_size - offset;
    if (avail > cont)
        avail = cont;
    *areas = (char *)pcm->mmap_buffer + (size_t)offset * pcm->frame_size;
    *frames = avail;
    return 0;
}

TL_EXPORT int pcm_mmap_commit(struct pcm *pcm, unsigned int offset, unsigned int frames)
{
    if (!pcm || !pcm->sync_ptr)
        return -1;
    (void)offset;
    pcm->sync_ptr->c.control.appl_ptr += frames;
    pcm->sync_ptr->c.control.appl_ptr %= pcm->buffer_size;
    pcm->mmap_offset = (pcm->mmap_offset + frames) % pcm->buffer_size;
    if (pcm_sync_ptr(pcm, 0) < 0)
        return -1;
    return (int)frames;
}

TL_EXPORT int pcm_mmap_transfer(struct pcm *pcm, void *buf, unsigned int frames, int is_read)
{
    unsigned int total = frames;

    while (frames) {
        void *area = NULL;
        unsigned int chunk = 0;
        unsigned int bytes;

        if (pcm_mmap_begin(pcm, &area, &chunk) < 0)
            return -1;
        if (!chunk) {
            if (pcm->state == SNDRV_PCM_STATE_RUNNING) {
                /* ring full (playback) or empty (capture): wait for the IRQ */
                pcm_wait(pcm, -1);
                continue;
            }
            set_error(pcm, "no frames available");
            return -1;
        }
        if (chunk > frames)
            chunk = frames;
        bytes = chunk * pcm->frame_size;
        if (is_read)
            tl_memcpy(buf, area, bytes);
        else
            tl_memcpy(area, buf, bytes);
        if (pcm_mmap_commit(pcm, 0, chunk) < 0)
            return -1;

        buf = (char *)buf + bytes;
        frames -= chunk;
    }
    return (int)total;
}

TL_EXPORT int pcm_mmap_write(struct pcm *pcm, const void *data, unsigned int count)
{
    if (!pcm)
        return -1;
    if (!(pcm->flags & PCM_MMAP))
        return pcm_write_nommap(pcm, data, count);
    return pcm_mmap_transfer(pcm, (void *)data, count / pcm->frame_size, 0);
}

TL_EXPORT int pcm_mmap_read(struct pcm *pcm, void *data, unsigned int count)
{
    if (!pcm)
        return -1;
    if (!(pcm->flags & PCM_MMAP))
        return pcm_read_nommap(pcm, data, count);
    return pcm_mmap_transfer(pcm, data, count / pcm->frame_size, 1);
}

TL_EXPORT int pcm_write(struct pcm *pcm, const void *data, unsigned int count)
{
    if (!pcm || pcm->fd < 0 || !pcm->frame_size)
        return -1;
    if (pcm->flags & PCM_MMAP)
        return pcm_mmap_transfer(pcm, (void *)data, count / pcm->frame_size, 0);
    return pcm_write_nommap(pcm, data, count);
}

TL_EXPORT int pcm_read(struct pcm *pcm, void *data, unsigned int count)
{
    if (!pcm || pcm->fd < 0 || !pcm->frame_size)
        return -1;
    if (pcm->flags & PCM_MMAP)
        return pcm_mmap_transfer(pcm, data, count / pcm->frame_size, 1);
    return pcm_read_nommap(pcm, data, count);
}

/* ------------------------------------------------------------------ */
/* pcm_params -- 7.1's introspection API                               */
/* ------------------------------------------------------------------ */

struct pcm_params {
    unsigned int card;
    unsigned int device;
    unsigned int flags;
    struct snd_pcm_hw_params params;
};

TL_EXPORT struct pcm_params *pcm_params_get(unsigned int card, unsigned int device, unsigned int flags)
{
    struct pcm_params *p;
    struct snd_pcm_hw_params hw;
    char fn[64];
    char *q;
    int fd;

    tl_strcpy(fn, "/dev/snd/pcmC");
    q = tl_utoa(card, fn + tl_strlen(fn));
    *q++ = 'D';
    q = tl_utoa(device, q);
    *q++ = (flags & PCM_IN) ? 'c' : 'p';
    *q = 0;

    fd = open(fn, O_RDWR | O_NONBLOCK, 0);
    if (fd < 0)
        return NULL;

    param_init(&hw);
    if (ioctl(fd, SNDRV_PCM_IOCTL_HW_REFINE, &hw) < 0) {
        close(fd);
        return NULL;
    }
    close(fd);

    p = (struct pcm_params *)calloc(1, sizeof(*p));
    if (!p)
        return NULL;
    p->card = card;
    p->device = device;
    p->flags = flags;
    p->params = hw;
    return p;
}

TL_EXPORT void pcm_params_free(struct pcm_params *p)
{
    if (p)
        free(p);
}

TL_EXPORT unsigned int pcm_params_get_min(struct pcm_params *p, unsigned int param)
{
    if (!p || param > SNDRV_PCM_HW_PARAM_LAST_INTERVAL)
        return 0;
    return (unsigned int)p->params.intervals[param].min;
}

TL_EXPORT unsigned int pcm_params_get_max(struct pcm_params *p, unsigned int param)
{
    if (!p || param > SNDRV_PCM_HW_PARAM_LAST_INTERVAL)
        return 0;
    return (unsigned int)p->params.intervals[param].max;
}

TL_EXPORT int pcm_params_set_min(struct pcm_params *p, unsigned int param, unsigned int val)
{
    if (!p || param > SNDRV_PCM_HW_PARAM_LAST_INTERVAL)
        return -1;
    p->params.intervals[param].min = val;
    return 0;
}

TL_EXPORT int pcm_params_set_max(struct pcm_params *p, unsigned int param, unsigned int val)
{
    if (!p || param > SNDRV_PCM_HW_PARAM_LAST_INTERVAL)
        return -1;
    p->params.intervals[param].max = val;
    return 0;
}

/* struct pcm_mask in 7.1 is exactly snd_mask: 8 words of 32 bits. */
TL_EXPORT const void *pcm_params_get_mask(struct pcm_params *p, unsigned int param)
{
    if (!p || param > SNDRV_PCM_HW_PARAM_LAST_MASK)
        return NULL;
    return &p->params.masks[param];
}

TL_EXPORT int pcm_params_format_test(struct pcm_params *p, unsigned int format)
{
    unsigned int alsa;

    if (!p)
        return 0;
    alsa = format_to_alsa(format);
    if (alsa >= 8 * sizeof(p->params.masks[0].bits))
        return 0;
    return (p->params.masks[SNDRV_PCM_HW_PARAM_FORMAT].bits[alsa >> 5] & (1U << (alsa & 31))) != 0;
}

TL_EXPORT const char *pcm_params_to_string(struct pcm_params *p, char *buf, unsigned int len)
{
    unsigned int lo, hi, n;
    char tmp[16];
    char *q;

    if (!buf || !len)
        return buf;
    buf[0] = 0;
    if (!p)
        return buf;

    lo = (unsigned int)p->params.intervals[SNDRV_PCM_HW_PARAM_RATE].min;
    hi = (unsigned int)p->params.intervals[SNDRV_PCM_HW_PARAM_RATE].max;

    tl_utoa(lo, tmp);
    n = (unsigned int)tl_strlen(tmp);
    if (n + 13 > len)
        return buf;
    tl_memcpy(buf, tmp, n);
    q = buf + n;
    *q++ = '-';
    tl_utoa(hi, q);
    return buf;
}

/* ------------------------------------------------------------------ */
/* mixer                                                               */
/* ------------------------------------------------------------------ */

TL_EXPORT struct mixer *mixer_open(unsigned int card)
{
    struct mixer *m;
    struct snd_ctl_card_info info;
    struct snd_ctl_elem_list list;
    char fn[64];
    char *q;
    unsigned int i;

    m = (struct mixer *)calloc(1, sizeof(*m));
    if (!m)
        return NULL;
    m->fd = -1;

    tl_strcpy(fn, "/dev/snd/controlC");
    q = tl_utoa(card, fn + tl_strlen(fn));
    *q = 0;

    m->fd = open(fn, O_RDWR | O_NONBLOCK, 0);
    if (m->fd < 0)
        goto fail;

    tl_memset(&info, 0, sizeof(info));
    if (ioctl(m->fd, SNDRV_CTL_IOCTL_CARD_INFO, &info) < 0)
        goto fail;
    tl_memcpy(m->name, info.id, sizeof(m->name) - 1);
    m->name[sizeof(m->name) - 1] = 0;

    tl_memset(&list, 0, sizeof(list));
    if (ioctl(m->fd, SNDRV_CTL_IOCTL_ELEM_LIST, &list) < 0)
        goto fail;
    m->count = list.count;
    if (!m->count)
        return m;

    m->info = (struct snd_ctl_elem_info *)calloc(m->count, sizeof(*m->info));
    m->ctl = (struct mixer_ctl *)calloc(m->count, sizeof(*m->ctl));
    if (!m->info || !m->ctl)
        goto fail;

    list.space = m->count;
    list.used = 0;
    list.pids = (struct snd_ctl_elem_id *)calloc(m->count, sizeof(*list.pids));
    if (!list.pids)
        goto fail;
    if (ioctl(m->fd, SNDRV_CTL_IOCTL_ELEM_LIST, &list) < 0) {
        free(list.pids);
        goto fail;
    }

    for (i = 0; i < m->count; i++) {
        m->info[i].id = list.pids[i];
        if (ioctl(m->fd, SNDRV_CTL_IOCTL_ELEM_INFO, &m->info[i]) < 0) {
            free(list.pids);
            goto fail;
        }
        m->ctl[i].mixer = m;
        m->ctl[i].info = &m->info[i];
        m->ctl[i].name = m->info[i].id.name;
        m->ctl[i].count = m->info[i].count;
        m->ctl[i].type = m->info[i].type;
    }
    free(list.pids);
    return m;

fail:
    if (m->info)
        free(m->info);
    if (m->ctl)
        free(m->ctl);
    if (m->fd >= 0)
        close(m->fd);
    free(m);
    return NULL;
}

TL_EXPORT int mixer_close(struct mixer *m)
{
    unsigned int i;

    if (!m)
        return 0;
    /* Every ctl->name points inside m->info[i].id.name; nothing separate to
     * free, but keep the loop so a future allocation per ctl cannot leak. */
    for (i = 0; i < m->count; i++)
        m->ctl[i].name = NULL;
    if (m->ctl)
        free(m->ctl);
    if (m->info)
        free(m->info);
    if (m->fd >= 0)
        close(m->fd);
    free(m);
    return 0;
}

TL_EXPORT const char *mixer_get_name(struct mixer *m)
{
    return m ? m->name : NULL;
}

TL_EXPORT unsigned int mixer_get_num_ctls(struct mixer *m)
{
    return m ? m->count : 0;
}

TL_EXPORT struct mixer_ctl *mixer_get_ctl(struct mixer *m, unsigned int id)
{
    if (!m || id >= m->count)
        return NULL;
    return &m->ctl[id];
}

TL_EXPORT struct mixer_ctl *mixer_get_ctl_by_name(struct mixer *m, const char *name)
{
    unsigned int i;

    if (!m || !name)
        return NULL;
    for (i = 0; i < m->count; i++) {
        if (!tl_strcmp((const char *)m->info[i].id.name, name))
            return &m->ctl[i];
    }
    return NULL;
}

TL_EXPORT const char *mixer_ctl_get_name(struct mixer_ctl *ctl)
{
    return ctl ? (const char *)ctl->info->id.name : NULL;
}

TL_EXPORT unsigned int mixer_ctl_get_num_values(struct mixer_ctl *ctl)
{
    return ctl ? ctl->info->count : 0;
}

TL_EXPORT unsigned int mixer_ctl_get_num_enums(struct mixer_ctl *ctl)
{
    if (!ctl || ctl->info->type != SNDRV_CTL_ELEM_TYPE_ENUMERATED)
        return 0;
    return ctl->info->value.enumerated.items;
}

TL_EXPORT unsigned int mixer_ctl_get_type(struct mixer_ctl *ctl)
{
    return ctl ? ctl->info->type : 0;
}

TL_EXPORT const char *mixer_ctl_get_type_string(struct mixer_ctl *ctl)
{
    if (!ctl)
        return "UNKNOWN";
    switch (ctl->info->type) {
    case SNDRV_CTL_ELEM_TYPE_BOOLEAN:    return "BOOL";
    case SNDRV_CTL_ELEM_TYPE_INTEGER:    return "INT";
    case SNDRV_CTL_ELEM_TYPE_ENUMERATED: return "ENUM";
    case SNDRV_CTL_ELEM_TYPE_BYTES:      return "BYTES";
    case SNDRV_CTL_ELEM_TYPE_IEC958:     return "IEC958";
    default:                             return "UNKNOWN";
    }
}

TL_EXPORT int mixer_ctl_update(struct mixer_ctl *ctl)
{
    if (!ctl || !ctl->mixer)
        return -1;
    if (ioctl(ctl->mixer->fd, SNDRV_CTL_IOCTL_ELEM_INFO, ctl->info) < 0)
        return -1;
    ctl->count = ctl->info->count;
    ctl->type = ctl->info->type;
    return 0;
}

TL_EXPORT int mixer_ctl_get_range_min(struct mixer_ctl *ctl)
{
    if (!ctl || ctl->info->type != SNDRV_CTL_ELEM_TYPE_INTEGER)
        return 0;
    return (int)ctl->info->value.integer.min;
}

TL_EXPORT int mixer_ctl_get_range_max(struct mixer_ctl *ctl)
{
    if (!ctl || ctl->info->type != SNDRV_CTL_ELEM_TYPE_INTEGER)
        return 0;
    return (int)ctl->info->value.integer.max;
}

TL_EXPORT int mixer_ctl_get_value(struct mixer_ctl *ctl, unsigned int id)
{
    struct snd_ctl_elem_value ev;

    if (!ctl || !ctl->mixer)
        return -1;
    if (ctl->info->type != SNDRV_CTL_ELEM_TYPE_BOOLEAN &&
        ctl->info->type != SNDRV_CTL_ELEM_TYPE_INTEGER &&
        ctl->info->type != SNDRV_CTL_ELEM_TYPE_ENUMERATED)
        return -1;
    if (id >= ctl->info->count)
        return -1;

    tl_memset(&ev, 0, sizeof(ev));
    ev.id = ctl->info->id;
    if (ioctl(ctl->mixer->fd, SNDRV_CTL_IOCTL_ELEM_READ, &ev) < 0)
        return -1;

    switch (ctl->info->type) {
    case SNDRV_CTL_ELEM_TYPE_BOOLEAN:
    case SNDRV_CTL_ELEM_TYPE_INTEGER:
        return (int)ev.value.integer.value[id];
    case SNDRV_CTL_ELEM_TYPE_ENUMERATED:
        return (int)ev.value.enumerated.item[id];
    default:
        return -1;
    }
}

TL_EXPORT int mixer_ctl_set_value(struct mixer_ctl *ctl, unsigned int id, int value)
{
    struct snd_ctl_elem_value ev;

    if (!ctl || !ctl->mixer)
        return -1;
    if (ctl->info->type != SNDRV_CTL_ELEM_TYPE_BOOLEAN &&
        ctl->info->type != SNDRV_CTL_ELEM_TYPE_INTEGER &&
        ctl->info->type != SNDRV_CTL_ELEM_TYPE_ENUMERATED)
        return -1;
    if (id >= ctl->info->count)
        return -1;

    tl_memset(&ev, 0, sizeof(ev));
    ev.id = ctl->info->id;
    switch (ctl->info->type) {
    case SNDRV_CTL_ELEM_TYPE_BOOLEAN:
        ev.value.integer.value[id] = !!value;
        break;
    case SNDRV_CTL_ELEM_TYPE_INTEGER:
        if (value < ctl->info->value.integer.min)
            value = (int)ctl->info->value.integer.min;
        if (value > ctl->info->value.integer.max)
            value = (int)ctl->info->value.integer.max;
        ev.value.integer.value[id] = value;
        break;
    case SNDRV_CTL_ELEM_TYPE_ENUMERATED:
        if ((unsigned int)value >= ctl->info->value.enumerated.items)
            return -1;
        ev.value.enumerated.item[id] = (unsigned int)value;
        break;
    default:
        return -1;
    }
    return ioctl(ctl->mixer->fd, SNDRV_CTL_IOCTL_ELEM_WRITE, &ev) < 0 ? -1 : 0;
}

TL_EXPORT int mixer_ctl_get_array(struct mixer_ctl *ctl, void *array, size_t count)
{
    struct snd_ctl_elem_value ev;
    size_t n;

    if (!ctl || !ctl->mixer || !array || !count)
        return -1;
    tl_memset(&ev, 0, sizeof(ev));
    ev.id = ctl->info->id;
    if (ioctl(ctl->mixer->fd, SNDRV_CTL_IOCTL_ELEM_READ, &ev) < 0)
        return -1;

    switch (ctl->info->type) {
    case SNDRV_CTL_ELEM_TYPE_BOOLEAN:
    case SNDRV_CTL_ELEM_TYPE_INTEGER: {
        long *dst = (long *)array;
        n = ctl->info->count;
        if (count < n)
            return -1;
        for (size_t i = 0; i < n; i++)
            dst[i] = ev.value.integer.value[i];
        return (int)n;
    }
    case SNDRV_CTL_ELEM_TYPE_BYTES: {
        unsigned char *dst = (unsigned char *)array;
        n = ctl->info->count;
        if (count < n)
            return -1;
        tl_memcpy(dst, ev.value.bytes.data, n);
        return (int)n;
    }
    case SNDRV_CTL_ELEM_TYPE_IEC958: {
        if (count < sizeof(ev.value.iec958))
            return -1;
        tl_memcpy(array, &ev.value.iec958, sizeof(ev.value.iec958));
        return (int)sizeof(ev.value.iec958);
    }
    default:
        return -1;
    }
}

TL_EXPORT int mixer_ctl_set_array(struct mixer_ctl *ctl, const void *array, size_t count)
{
    struct snd_ctl_elem_value ev;
    size_t n;

    if (!ctl || !ctl->mixer || !array || !count)
        return -1;
    tl_memset(&ev, 0, sizeof(ev));
    ev.id = ctl->info->id;

    switch (ctl->info->type) {
    case SNDRV_CTL_ELEM_TYPE_BOOLEAN:
    case SNDRV_CTL_ELEM_TYPE_INTEGER: {
        const long *src = (const long *)array;
        n = ctl->info->count;
        if (count < n)
            return -1;
        for (size_t i = 0; i < n; i++)
            ev.value.integer.value[i] = src[i];
        break;
    }
    case SNDRV_CTL_ELEM_TYPE_BYTES: {
        n = ctl->info->count;
        if (count < n)
            return -1;
        tl_memcpy(ev.value.bytes.data, array, n);
        break;
    }
    default:
        return -1;
    }
    return ioctl(ctl->mixer->fd, SNDRV_CTL_IOCTL_ELEM_WRITE, &ev) < 0 ? -1 : 0;
}

TL_EXPORT int mixer_ctl_get_percent(struct mixer_ctl *ctl, unsigned int id)
{
    int min, max, val;

    if (!ctl || ctl->info->type != SNDRV_CTL_ELEM_TYPE_INTEGER)
        return -1;
    min = (int)ctl->info->value.integer.min;
    max = (int)ctl->info->value.integer.max;
    val = mixer_ctl_get_value(ctl, id);
    if (val < 0 || max == min)
        return -1;
    return (val - min) * 100 / (max - min);
}

TL_EXPORT int mixer_ctl_set_percent(struct mixer_ctl *ctl, unsigned int id, int percent)
{
    int min, max, val;

    if (!ctl || ctl->info->type != SNDRV_CTL_ELEM_TYPE_INTEGER)
        return -1;
    min = (int)ctl->info->value.integer.min;
    max = (int)ctl->info->value.integer.max;
    if (percent < 0)
        percent = 0;
    if (percent > 100)
        percent = 100;
    val = min + (max - min) * percent / 100;
    return mixer_ctl_set_value(ctl, id, val);
}

TL_EXPORT const char *mixer_ctl_get_enum_string(struct mixer_ctl *ctl, unsigned int id)
{
    if (!ctl || ctl->info->type != SNDRV_CTL_ELEM_TYPE_ENUMERATED)
        return NULL;
    if (id >= ctl->info->value.enumerated.items)
        return NULL;

    ctl->info->value.enumerated.item = id;
    if (ioctl(ctl->mixer->fd, SNDRV_CTL_IOCTL_ELEM_INFO, ctl->info) < 0)
        return NULL;
    return ctl->info->value.enumerated.name;
}

TL_EXPORT int mixer_ctl_set_enum_by_string(struct mixer_ctl *ctl, const char *string)
{
    unsigned int i, items;

    if (!ctl || !string || ctl->info->type != SNDRV_CTL_ELEM_TYPE_ENUMERATED)
        return -1;

    items = ctl->info->value.enumerated.items;
    for (i = 0; i < items; i++) {
        const char *name = mixer_ctl_get_enum_string(ctl, i);
        if (name && !tl_strcmp(name, string))
            return mixer_ctl_set_value(ctl, 0, (int)i);
    }
    return -1;
}

/* ------------------------------------------------------------------ */
/* leftovers the 7.1 symbol set expects                                */
/* ------------------------------------------------------------------ */

