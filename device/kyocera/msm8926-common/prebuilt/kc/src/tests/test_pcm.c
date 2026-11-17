/*
 * test_pcm.c -- host-side proof that the built library does the right things,
 * without a phone and without a sound card.
 *
 * pcm.c is compiled into this file with its syscalls renamed to __wrap_*, and
 * those wrappers implement just enough of the 3.4 ALSA kernel to be honest:
 *
 *   - HW_PARAMS refines period size / count the way the kernel does and writes
 *     the result back;
 *   - SW_PARAMS applies the *real* checks from sound/core/pcm_native.c
 *     (silence_size >= boundary, silence_size > silence_threshold,
 *     silence_threshold > buffer_size, avail_min == 0 -> EINVAL), which is the
 *     wall every pcm_open hit on the device;
 *   - WRITEI_FRAMES refuses to run in SETUP state, exactly like
 *     snd_pcm_lib_write1() (-EBADFD), so a missing PREPARE cannot pass unnoticed;
 *   - it starts the stream when appl_ptr - hw_ptr reaches start_threshold.
 *
 * The two configs are the real bytes: 36 bytes as the vendor HAL passes them
 * (pcm_config_deep_buffer), and 40 bytes as a 7.1 caller would.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdarg.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <sys/mman.h>

#include <linux/ioctl.h>
#include <sound/asound.h>

/* ---- fake kernel ------------------------------------------------------- */

static struct {
    unsigned int state;
    unsigned int period_size, periods, rate, channels, format;
    unsigned int buffer_size;
    unsigned int boundary;
    unsigned int hw_ptr, appl_ptr;
    int prepares, starts, writes, drops;
    /* last sw_params, for inspection */
    unsigned int avail_min, start_threshold, stop_threshold;
    unsigned int silence_threshold, silence_size;
    int sw_calls, sw_fail;
} K;

static void kreset(void)
{
    memset(&K, 0, sizeof(K));
    K.state = SNDRV_PCM_STATE_OPEN;
    K.boundary = 0x7fffffff;
}

/* the on-wire arrays are indexed from the first mask/interval param */
static void set_int(struct snd_pcm_hw_params *p, int n, unsigned int v)
{
    struct snd_interval *i = &p->intervals[n - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL];
    i->min = v;
    i->max = v;
    i->integer = 1;
}

static unsigned int get_int(struct snd_pcm_hw_params *p, int n)
{
    return (unsigned int)p->intervals[n - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL].min;
}

int __wrap_open(const char *path, int flags, ...)
{
    (void)flags;
    if (strncmp(path, "/dev/snd/pcmC", 13))
        return -1;
    K.state = SNDRV_PCM_STATE_OPEN;
    return 3;
}
int __wrap_close(int fd) { (void)fd; return 0; }
int __wrap_fcntl(int fd, int cmd, ...) { (void)fd; (void)cmd; return 0; }
void *__wrap_mmap(void *a, size_t l, int p, int f, int fd, long o)
{
    (void)a; (void)l; (void)p; (void)f; (void)fd; (void)o;
    return MAP_FAILED;
}
int __wrap_munmap(void *a, size_t l) { (void)a; (void)l; return 0; }
int __wrap_poll(struct pollfd *f, unsigned long n, int t)
{
    (void)f; (void)n; (void)t; return 1;
}

int __wrap_ioctl(int fd, unsigned long req, ...)
{
    va_list ap;
    void *arg;
    (void)fd;
    va_start(ap, req);
    arg = va_arg(ap, void *);
    va_end(ap);
    
    switch (req) {
    case SNDRV_PCM_IOCTL_INFO:
        memset(arg, 0, sizeof(struct snd_pcm_info));
        return 0;

    case SNDRV_PCM_IOCTL_HW_PARAMS: {
        struct snd_pcm_hw_params *p = arg;
        /* the kernel's refine step: clamp to what the hardware does */
        K.period_size = get_int(p, SNDRV_PCM_HW_PARAM_PERIOD_SIZE);
        K.periods     = get_int(p, SNDRV_PCM_HW_PARAM_PERIODS);
        K.rate        = get_int(p, SNDRV_PCM_HW_PARAM_RATE);
        K.channels    = get_int(p, SNDRV_PCM_HW_PARAM_CHANNELS);
        K.format      = (unsigned)__builtin_ctz(p->masks[SNDRV_PCM_HW_PARAM_FORMAT -
                                 SNDRV_PCM_HW_PARAM_FIRST_MASK].bits[0]);
        K.buffer_size = K.period_size * K.periods;
        set_int(p, SNDRV_PCM_HW_PARAM_PERIOD_SIZE, K.period_size);
        set_int(p, SNDRV_PCM_HW_PARAM_PERIODS, K.periods);
        set_int(p, SNDRV_PCM_HW_PARAM_BUFFER_SIZE, K.buffer_size);
        set_int(p, SNDRV_PCM_HW_PARAM_RATE, K.rate);
        set_int(p, SNDRV_PCM_HW_PARAM_CHANNELS, K.channels);
        K.state = SNDRV_PCM_STATE_SETUP;
        return 0;
    }

    case SNDRV_PCM_IOCTL_SW_PARAMS: {
        struct snd_pcm_sw_params *p = arg;
        K.sw_calls++;
        K.avail_min = p->avail_min;
        K.start_threshold = p->start_threshold;
        K.stop_threshold = p->stop_threshold;
        K.silence_threshold = p->silence_threshold;
        K.silence_size = p->silence_size;
        /* sound/core/pcm_native.c, snd_pcm_sw_params() */
        if (p->avail_min == 0) { K.sw_fail = 1; errno = EINVAL; return -1; }
        if (p->silence_size >= K.boundary) {
            if (p->silence_threshold != 0) { K.sw_fail = 1; errno = EINVAL; return -1; }
        } else {
            if (p->silence_size > p->silence_threshold) { K.sw_fail = 1; errno = EINVAL; return -1; }
            if (p->silence_threshold > K.buffer_size) { K.sw_fail = 1; errno = EINVAL; return -1; }
        }
        return 0;
    }

    case SNDRV_PCM_IOCTL_PREPARE:
        if (K.state != SNDRV_PCM_STATE_SETUP) { errno = EBADFD; return -1; }
        K.prepares++;
        K.hw_ptr = K.appl_ptr = 0;
        K.state = SNDRV_PCM_STATE_PREPARED;
        return 0;

    case SNDRV_PCM_IOCTL_START:
        if (K.state != SNDRV_PCM_STATE_PREPARED) { errno = EBADFD; return -1; }
        K.starts++;
        K.state = SNDRV_PCM_STATE_RUNNING;
        return 0;

    case SNDRV_PCM_IOCTL_DROP:
        K.drops++;
        K.state = SNDRV_PCM_STATE_SETUP;
        return 0;

    case SNDRV_PCM_IOCTL_WRITEI_FRAMES: {
        struct snd_xferi *x = arg;
        snd_pcm_uframes_t frames = x->frames;
        /* snd_pcm_lib_write1(): SETUP and XRUN are refused */
        if (K.state != SNDRV_PCM_STATE_PREPARED &&
            K.state != SNDRV_PCM_STATE_RUNNING &&
            K.state != SNDRV_PCM_STATE_PAUSED) { errno = EBADFD; return -1; }
        if (frames > K.buffer_size) frames = K.buffer_size;
        K.writes++;
        K.appl_ptr += frames;       /* the DAC has not started yet, so
                                     * hw_ptr stays where it was */
        x->result = frames;
        if (K.state == SNDRV_PCM_STATE_PREPARED &&
            (K.appl_ptr - K.hw_ptr) >= K.start_threshold)
            K.state = SNDRV_PCM_STATE_RUNNING;
        return 0;
    }

    case SNDRV_PCM_IOCTL_STATUS: {
        struct snd_pcm_status *s = arg;
        memset(s, 0, sizeof(*s));
        s->state = K.state;
        s->avail = K.buffer_size;
        return 0;
    }

    default:
        errno = ENOTTY;
        return -1;
    }
}

/* ---- the library, with its syscalls pointed at the wrappers ------------- */
#define open   __wrap_open
#define close  __wrap_close
#define fcntl  __wrap_fcntl
#define mmap   __wrap_mmap
#define munmap __wrap_munmap
#define poll   __wrap_poll
#define ioctl  __wrap_ioctl
#include "../tinyalsa/pcm.c"

/* ---- tests ------------------------------------------------------------- */

static int fails;

static void check(const char *what, long got, long want)
{
    if (got == want) {
        printf("  ok    %-46s %ld\n", what, got);
    } else {
        printf("  FAIL  %-46s got %ld want %ld\n", what, got, want);
        fails++;
    }
}

int main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    /* the exact bytes of pcm_config_deep_buffer, 36 of them */
    struct __attribute__((packed)) {
        unsigned int channels, rate, period_size, period_count;
        unsigned int format, start_threshold, stop_threshold;
        unsigned int silence_threshold, avail_min;
    } kk = { 2, 48000, 960, 4, PCM_FORMAT_S16_LE, 240, 0x7fffffff, 0, 240 };

    printf("sizeof(struct pcm_config) = %zu (must be 36)\n", sizeof(struct pcm_config));
    check("sizeof(struct pcm_config)", (long)sizeof(struct pcm_config), 36);
    check("sizeof(kitkat config)", (long)sizeof(kk), 36);

    printf("\n-- playback, 36-byte config, non-mmap --\n");
    kreset();
    struct pcm *p = pcm_open(0, 0, PCM_OUT, (struct pcm_config *)&kk);
    check("pcm_open returned a handle", p != NULL, 1);
    check("pcm_is_ready", pcm_is_ready(p), 1);
    if (!pcm_is_ready(p)) {
        printf("  error: %s\n", pcm_get_error(p));
        return 1;
    }
    check("sw_params accepted", K.sw_fail, 0);
    check("avail_min seen by kernel", K.avail_min, 240);
    check("silence_size forced to 0", K.silence_size, 0);
    check("silence_threshold", K.silence_threshold, 0);
    check("start_threshold", K.start_threshold, 240);
    check("rate", K.rate, 48000);
    check("channels", K.channels, 2);
    check("period_size", K.period_size, 960);
    check("periods", K.periods, 4);
    check("buffer_size", K.buffer_size, 3840);
    check("format is S16_LE", K.format, SNDRV_PCM_FORMAT_S16_LE);

    static short buf[960 * 2];
    check("first pcm_write", pcm_write(p, buf, sizeof(buf)), 0);
    check("PREPARE was issued", K.prepares, 1);
    check("stream is RUNNING", K.state, SNDRV_PCM_STATE_RUNNING);
    check("second pcm_write", pcm_write(p, buf, sizeof(buf)), 0);
    check("prepared only once", K.prepares, 1);
    pcm_close(p);

    printf("\n-- playback, 40-byte config (7.1 caller) --\n");
    kreset();
    struct __attribute__((packed)) {
        unsigned int channels, rate, period_size, period_count;
        unsigned int format, start_threshold, stop_threshold;
        unsigned int silence_threshold, silence_size, avail_min;
    } n71 = { 2, 48000, 960, 4, PCM_FORMAT_S16_LE, 0, 0, 0, 0, 240 };
    struct pcm *q = pcm_open(0, 0, PCM_OUT, (struct pcm_config *)&n71);
    check("pcm_open returned a handle", q != NULL, 1);
    check("pcm_is_ready", pcm_is_ready(q), 1);
    check("sw_params accepted", K.sw_fail, 0);
    /* offset 32 of a 40-byte struct is silence_size == 0, so upstream's own
     * fallback takes over: 1 for the rw path, period_size for mmap. */
    check("avail_min fell back (rw path -> 1)", K.avail_min, 1);
    check("start_threshold defaulted to p*c/2", K.start_threshold, 1920);
    check("first pcm_write", pcm_write(q, buf, sizeof(buf)), 0);
    check("still PREPARED below start_threshold", K.state, SNDRV_PCM_STATE_PREPARED);
    check("second pcm_write", pcm_write(q, buf, sizeof(buf)), 0);
    check("RUNNING once threshold is reached", K.state, SNDRV_PCM_STATE_RUNNING);
    pcm_close(q);

    printf("\n-- the config that used to fail: silence_size 240 --\n");
    /* what a 40-byte-aware library saw in the 36-byte struct: offset 32
     * (avail_min, 240) read as silence_size, with threshold 0 */
    kreset();
    K.boundary = 0x7fffffff;
    struct snd_pcm_sw_params bad;
    memset(&bad, 0, sizeof(bad));
    bad.avail_min = 240;
    bad.silence_threshold = 0;
    bad.silence_size = 240;
    if (__wrap_ioctl(3, SNDRV_PCM_IOCTL_SW_PARAMS, &bad) < 0)
        printf("  ok    kernel rejects silence_size 240 > threshold 0  (EINVAL)\n");
    else { printf("  FAIL  the fake kernel accepted the broken params\n"); fails++; }

    printf("\n%s (%d failures)\n", fails ? "FAILED" : "all checks passed", fails);
    return fails ? 1 : 0;
}
