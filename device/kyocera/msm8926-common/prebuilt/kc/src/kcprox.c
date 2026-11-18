/*
 * kcprox -- pocket mode for this device, at the input layer.
 *
 * The problem it solves, and why it has to live down here:
 *
 *   The proximity sensor itself works.  fix82's dump has en=1 on
 *   enable_ps_sensor, "SFH7776 Proximity Sensor: last 10 events", and the value
 *   the driver reports with nothing in front of the phone is 4 -- its own level
 *   table in drivers/sensors/sfh7776.c is
 *
 *       level 0: hi=0xffff lo=20    (something there: high raw counts)
 *       ...
 *       level 4: hi=13     lo=0     (nothing there)
 *
 *   What does not work is the framework end, and that is a code path, not a
 *   node.  PowerManagerService.runWithProximityCheck() is only reachable from
 *   PowerManager.wakeUpWithProximityCheck(), and the only caller of that in
 *   services.jar is PhoneWindowManager.wakeUp(..., withProximityCheck), with
 *
 *       event.getKeyCode() == KeyEvent.KEYCODE_WAKEUP
 *
 *   i.e. the CM "proximity_on_wake" setting can never veto a *power key* press:
 *   wakeUpFromPowerKey() calls the 3-argument wakeUp(), which passes false.
 *   Nothing is broken; the feature simply does not apply to this key on 14.1.
 *
 *   Patching that means patching services.jar's dex, and this ROM is built
 *   "boot image only": /system/framework/*.jar are 299-byte stubs and every
 *   framework class lives precompiled in boot.art/boot-*.oat.  Touching
 *   services.jar's dex invalidates those images, and with the jars empty there
 *   is nothing left to fall back to.  So the framework stays as it is and the
 *   decision is made here instead.
 *
 * What it does:
 *
 *   While the screen is ON nothing is touched at all -- the power key keeps its
 *   own long-press menu, and covering the sensor changes nothing.
 *
 *   When the screen goes off, this process grabs the power key's evdev node
 *   (qpnp_pon, a device of its own on this board: gpio-keys carries the volume
 *   keys) and enables the proximity driver.  From then on a power key press is
 *   a question this process answers:
 *
 *       covered  -> the press is swallowed, the screen stays dark
 *       clear    -> KEY_POWER is injected through uinput, the framework wakes
 *                   exactly as it would have
 *
 *   Grabbing is what makes this possible: EVIOCGRAB stops evdev from delivering
 *   the device's events to anybody else, so the framework never sees the press
 *   that was swallowed.  The grab is owned by one file descriptor, so if this
 *   process dies the kernel releases it and the power key works normally again.
 *
 * Failure modes, deliberately chosen:
 *
 *   * value 4 is "nothing in front" and only 0..2 counts as covered (<=
 *     KCPROX_NEAR_MAX).  If the level table were ever inverted, nothing would
 *     ever look covered and the feature would quietly do nothing -- it could
 *     not lock the phone.
 *   * after KCPROX_MAX_SWALLOW presses in a row the next one is always let
 *     through, so a stuck sensor can never make the power key unusable.
 *   * if uinput cannot be set up, the fallback is /system/bin/input; if that
 *     fails too, the grab is released and this process stops intervening.
 *   * a 500 ms poll timeout means the screen state is re-read four times a
 *     second; there is no blocking call in the loop that can hang.
 *
 * Build: see build.sh in this directory.  Static, because there is no reason to
 * depend on bionic's symbol set for a single-file daemon (the HAL libraries in
 * this tree are a different story -- they are loaded *into* bionic).
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <dirent.h>
#include <time.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/ioctl.h>
#include <sys/poll.h>
#include <linux/input.h>
#include <linux/uinput.h>

#define KCPROX_NEAR_MAX     2       /* 0..2 = covered, 3..4 = nothing there */
#define KCPROX_MAX_SWALLOW  3       /* escape hatch: the 4th press always wakes */
#define KCPROX_FRESH_MS     10000   /* a prox value older than this is ignored */
#define KCPROX_LOG          "/data/local/tmp/kcprox.log"

static int logfd = -1;
static volatile sig_atomic_t stop;

static void logline(const char *fmt, ...)
{
    char buf[240];
    va_list ap;
    int n;
    struct timespec ts;

    if (logfd < 0)
        return;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    n = snprintf(buf, sizeof buf, "[%lu.%03lu] ",
                 (unsigned long)ts.tv_sec, (unsigned long)(ts.tv_nsec / 1000000));
    va_start(ap, fmt);
    n += vsnprintf(buf + n, sizeof buf - n, fmt, ap);
    va_end(ap);
    if (n > (int)sizeof buf - 2)
        n = sizeof buf - 2;
    buf[n++] = '\n';
    write(logfd, buf, n);
}

static void on_signal(int sig)
{
    (void)sig;
    stop = 1;
}

/* ------------------------------------------------------------------ */
/* sysfs helpers                                                       */
/* ------------------------------------------------------------------ */

static int read_int_file(const char *path, int *out)
{
    char b[64];
    int f, r;

    f = open(path, O_RDONLY);
    if (f < 0)
        return -1;
    r = read(f, b, sizeof b - 1);
    close(f);
    if (r <= 0)
        return -1;
    b[r] = 0;
    *out = atoi(b);
    return 0;
}

static int write_int_file(const char *path, int v)
{
    char b[16];
    int f, n, r;

    n = snprintf(b, sizeof b, "%d", v);
    f = open(path, O_WRONLY);
    if (f < 0)
        return -1;
    r = write(f, b, n);
    close(f);
    return (r == n) ? 0 : -1;
}

/*
 * inputN -> "proximity", "qpnp_pon", ... and then that same inputN's event
 * node.  By name, because the numbers move: the sensors HAL registers five
 * devices and their order is not guaranteed across boots.
 */
static int find_event_node(const char *want, char *out, size_t outsz)
{
    DIR *d, *dd;
    struct dirent *e, *ee;
    char path[256], name[128], dirp[256];
    int f, r, found = -1;

    d = opendir("/sys/class/input");
    if (!d)
        return -1;
    while ((e = readdir(d)) != NULL) {
        if (strncmp(e->d_name, "input", 5) != 0)
            continue;
        snprintf(path, sizeof path, "/sys/class/input/%s/name", e->d_name);
        f = open(path, O_RDONLY);
        if (f < 0)
            continue;
        r = read(f, name, sizeof name - 1);
        close(f);
        if (r <= 0)
            continue;
        name[r] = 0;
        if (strchr(name, '\n'))
            *strchr(name, '\n') = 0;
        if (strcmp(name, want) != 0)
            continue;
        snprintf(dirp, sizeof dirp, "/sys/class/input/%s", e->d_name);
        dd = opendir(dirp);
        if (!dd)
            continue;
        while ((ee = readdir(dd)) != NULL) {
            if (strncmp(ee->d_name, "event", 5) != 0)
                continue;
            snprintf(out, outsz, "/dev/input/%s", ee->d_name);
            found = 0;
            break;
        }
        closedir(dd);
        if (found == 0)
            break;
    }
    closedir(d);
    return found;
}

static int find_input_sysfs(const char *want, char *out, size_t outsz)
{
    DIR *d;
    struct dirent *e;
    char path[256], name[128];
    int f, r, found = -1;

    d = opendir("/sys/class/input");
    if (!d)
        return -1;
    while ((e = readdir(d)) != NULL) {
        if (strncmp(e->d_name, "input", 5) != 0)
            continue;
        snprintf(path, sizeof path, "/sys/class/input/%s/name", e->d_name);
        f = open(path, O_RDONLY);
        if (f < 0)
            continue;
        r = read(f, name, sizeof name - 1);
        close(f);
        if (r <= 0)
            continue;
        name[r] = 0;
        if (strchr(name, '\n'))
            *strchr(name, '\n') = 0;
        if (strcmp(name, want) == 0) {
            snprintf(out, outsz, "/sys/class/input/%s", e->d_name);
            found = 0;
            break;
        }
    }
    closedir(d);
    return found;
}

/*
 * The panel's backlight is the cheapest honest "is the screen on" test on this
 * port: the lights HAL writes 0 to lcd-backlight for Display.STATE_OFF, and the
 * value is not otherwise touched while the screen is off.
 */
static int screen_is_on(void)
{
    int v;
    if (read_int_file("/sys/class/leds/lcd-backlight/brightness", &v) == 0)
        return v > 0;
    return -1;
}

/* ------------------------------------------------------------------ */
/* key injection                                                       */
/* ------------------------------------------------------------------ */

/* Discard whatever the power key node queued while the screen was on.
 *
 * evdev keeps one queue per open fd, and this process holds the key node open
 * from start to exit while only reading it inside the grab window.  So the
 * press that put the screen to sleep -- and every other key pressed during that
 * screen-on period -- is still sitting in the buffer when the grab lands.  The
 * first poll after arming would read it as a fresh press: with the sensor
 * clear, that reinjects KEY_POWER and the panel comes straight back on.
 *
 * fix83's log has exactly that, twice: "screen off -> armed" and
 * "power: ... -> wake" in the same millisecond, once swallowing the press and
 * once undoing the sleep.  Drain after grabbing, before anyone can look.
 */
static void drain_events(int fd)
{
    struct input_event ev[64];
    while (read(fd, ev, sizeof ev) > 0)
        ;
}

static int ufd = -1;

static int uinput_setup(void)
{
    struct uinput_user_dev udev;
    int f;

    f = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
    if (f < 0 && errno == ENOENT) {
        /* devtmpfs is off on this kernel and 7.1's ueventd.rc has no rule for
         * it, so the node may simply be missing. */
        if (mknod("/dev/uinput", S_IFCHR | 0600, makedev(10, 223)) == 0)
            f = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
    }
    if (f < 0)
        return -1;

    ioctl(f, UI_SET_EVBIT, EV_KEY);
    ioctl(f, UI_SET_KEYBIT, KEY_POWER);
    ioctl(f, UI_SET_KEYBIT, KEY_VOLUMEUP);
    ioctl(f, UI_SET_KEYBIT, KEY_VOLUMEDOWN);

    memset(&udev, 0, sizeof udev);
    snprintf(udev.name, sizeof udev.name, "kcprox-vkeys");
    udev.id.bustype = BUS_VIRTUAL;
    udev.id.vendor = 0x0001;
    udev.id.product = 0x0001;
    udev.id.version = 1;
    if (write(f, &udev, sizeof udev) != (ssize_t)sizeof udev) {
        close(f);
        return -1;
    }
    if (ioctl(f, UI_DEV_CREATE) < 0) {
        close(f);
        return -1;
    }
    ufd = f;
    return 0;
}

static void emit(int code, int value)
{
    struct input_event ev;

    if (ufd < 0)
        return;
    memset(&ev, 0, sizeof ev);
    ev.type = EV_KEY;
    ev.code = code;
    ev.value = value;
    write(ufd, &ev, sizeof ev);
    memset(&ev, 0, sizeof ev);
    ev.type = EV_SYN;
    ev.code = SYN_REPORT;
    write(ufd, &ev, sizeof ev);
}

/*
 * Either uinput or the shell tool.  uinput is instant; /system/bin/input starts
 * a whole app_process (~300 ms) and is only here so that a missing uinput node
 * degrades the feature instead of deadlocking the power key.
 */
static int inject_power(int use_uinput)
{
    if (use_uinput) {
        emit(KEY_POWER, 1);
        emit(KEY_POWER, 0);
        return 0;
    }
    return system("/system/bin/input keyevent 26 </dev/null >/dev/null 2>&1");
}

/* ------------------------------------------------------------------ */
/* main                                                                */
/* ------------------------------------------------------------------ */

int main(int argc, char **argv)
{
    char proxev[64] = "", keysys[64] = "", keyev[64] = "", proxsys[64] = "";
    char proxfile[128], logpath[128];
    int dry = (argc > 1 && strcmp(argv[1], "--dry") == 0);
    int kfd = -1, pfd = -1;
    int grabbed = 0, prox_on = 0;
    int screen = -1, near = 0, swallowed = 0, have_prox = 0, use_uinput = 0;
    int seen_on = 0, armed = 0;
    long long prox_age_ms = 0;
    struct timespec now, prox_ts;
    struct pollfd pfdset[2];

    snprintf(logpath, sizeof logpath, "%s", KCPROX_LOG);
    logfd = open(logpath, O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (logfd >= 0) {
        struct stat st;
        if (fstat(logfd, &st) == 0 && st.st_size > 65536) {
            close(logfd);
            logfd = open(logpath, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        }
    }

    signal(SIGTERM, on_signal);
    signal(SIGINT, on_signal);

    /* The sensors HAL registers its devices from system_server; at boot_completed
     * they are always there, but wait rather than guess. */
    for (int i = 0; i < 120; i++) {
        if (find_event_node("proximity", proxev, sizeof proxev) == 0 &&
            find_input_sysfs("proximity", proxsys, sizeof proxsys) == 0)
            break;
        usleep(500000);
    }
    if (find_event_node("qpnp_pon", keyev, sizeof keyev) != 0) {
        /* Fall back to whatever publishes KEY_POWER. */
        if (find_event_node("gpio-keys", keyev, sizeof keyev) != 0) {
            logline("no power key node, exiting");
            return 1;
        }
    }
    find_input_sysfs("qpnp_pon", keysys, sizeof keysys);
    if (proxev[0] == 0 || proxsys[0] == 0) {
        logline("no proximity node, exiting (proxev='%s' proxsys='%s')", proxev, proxsys);
        return 1;
    }
    snprintf(proxfile, sizeof proxfile, "%s/enable_ps_sensor", proxsys);

    if (uinput_setup() == 0)
        use_uinput = 1;

    pfd = open(proxev, O_RDONLY | O_NONBLOCK);
    kfd = open(keyev, O_RDONLY | O_NONBLOCK);
    if (pfd < 0 || kfd < 0) {
        logline("open failed: prox=%d(%s) key=%d(%s)", pfd, proxev, kfd, keyev);
        return 1;
    }

    logline("start dry=%d key=%s prox=%s proxctl=%s uinput=%d",
            dry, keyev, proxev, proxfile, use_uinput);

    clock_gettime(CLOCK_MONOTONIC, &prox_ts);
    /* Give the lights HAL a moment: this process starts at boot_completed and
     * lcd-backlight is only meaningful once the first brightness write landed.
     * Until the screen has been seen on at least once, nothing is armed -- an
     * unknown screen state must never turn the power key into a no-op. */
    sleep(2);
    screen = screen_is_on();

    while (!stop) {
        int timeout = 250;
        int n;

        if (screen < 0)
            screen = screen_is_on();
        if (screen > 0)
            seen_on = 1;

        /* Screen off <-> on is the only state change that matters. */
        if (screen > 0 && (grabbed || prox_on)) {
            if (grabbed) {
                ioctl(kfd, EVIOCGRAB, 0);
                grabbed = 0;
            }
            if (prox_on) {
                write_int_file(proxfile, 0);
                prox_on = 0;
            }
            logline("screen on  -> released (swallowed=%d)", swallowed);
            swallowed = 0;
            armed = 0;
        } else if (screen == 0 && seen_on && (!grabbed || !prox_on)) {
            if (!prox_on) {
                if (write_int_file(proxfile, 1) == 0)
                    prox_on = 1;
                else
                    logline("cannot enable %s: %s", proxfile, strerror(errno));
            }
            if (!grabbed) {
                if (ioctl(kfd, EVIOCGRAB, 1) == 0) {
                    grabbed = 1;
                    drain_events(kfd);
                } else {
                    logline("EVIOCGRAB failed: %s", strerror(errno));
                }
            }
            swallowed = 0;
            if (!armed) {
                armed = 1;
                logline("screen off -> armed (near=%d, grabbed=%d)", near, grabbed);
            }
        }

        pfdset[0].fd = pfd;
        pfdset[0].events = POLLIN;
        pfdset[1].fd = grabbed ? kfd : -1;
        pfdset[1].events = POLLIN;

        n = poll(pfdset, 2, timeout);
        clock_gettime(CLOCK_MONOTONIC, &now);

        if (n < 0 && errno != EINTR) {
            logline("poll: %s", strerror(errno));
            break;
        }
        if (n <= 0) {
            int s = screen_is_on();
            if (s >= 0)
                screen = s;
            continue;
        }

        if (pfdset[0].revents & POLLIN) {
            struct input_event ev[8];
            int r = read(pfd, ev, sizeof ev);
            int cnt = r > 0 ? r / (int)sizeof(struct input_event) : 0;
            for (int i = 0; i < cnt; i++) {
                if (ev[i].type != EV_ABS || ev[i].code != ABS_DISTANCE)
                    continue;
                if (ev[i].value < 0)     /* the driver's -1 dummy value */
                    continue;
                /* One line per transition, not per sample.  The HAL enables the
                 * sensor at its own poll rate and the driver reports levels
                 * 0..4, so a hand held near the earpiece flips covered/clear
                 * several times a second; logging each of those turned a
                 * 90-second test into 40 lines of noise with the four that
                 * mattered buried in it. */
                {
                    int was = have_prox ? near : -1;
                    near = (ev[i].value <= KCPROX_NEAR_MAX);
                    have_prox = 1;
                    prox_ts = now;
                    if (near != was)
                        logline("prox: %s (%d)",
                                near ? "covered" : "clear", ev[i].value);
                }
            }
        }

        if ((pfdset[1].revents & POLLIN) && grabbed) {
            struct input_event ev[16];
            int r = read(kfd, ev, sizeof ev);
            int cnt = r > 0 ? r / (int)sizeof(struct input_event) : 0;
            for (int i = 0; i < cnt; i++) {
                if (ev[i].type != EV_KEY || ev[i].value != 1)
                    continue;           /* only presses decide anything */
                if (ev[i].code != KEY_POWER) {
                    /* Something else on this node (a combo key): pass it on. */
                    if (use_uinput) {
                        emit(ev[i].code, 1);
                        emit(ev[i].code, 0);
                    }
                    continue;
                }
                prox_age_ms = (now.tv_sec - prox_ts.tv_sec) * 1000LL +
                              (now.tv_nsec - prox_ts.tv_nsec) / 1000000LL;
                if (near && have_prox && prox_age_ms < KCPROX_FRESH_MS &&
                    swallowed < KCPROX_MAX_SWALLOW) {
                    if (dry) {
                        /* --dry still grabs and still reads, it just refuses to
                         * drop anything: the power key behaves exactly as it
                         * would without this program, and the log records what
                         * the decision would have been.  That is the only way
                         * to test the rule without risking the key. */
                        logline("power: covered (age=%lldms) -> would swallow",
                                prox_age_ms);
                    } else {
                        swallowed++;
                        logline("power: covered (age=%lldms) -> swallowed %d/%d",
                                prox_age_ms, swallowed, KCPROX_MAX_SWALLOW);
                        continue;
                    }
                }
                /* If the screen came on while this press was in flight, the
                 * framework has already handled it; injecting now would put it
                 * straight back to sleep. */
                {
                    int s2 = screen_is_on();
                    if (s2 > 0) {
                        logline("power: screen already on -> not injecting");
                        continue;
                    }
                    if (s2 == 0)
                        screen = 0;
                }
                if (inject_power(use_uinput) != 0) {
                    /* Without injection the grab would eat the power key.  */
                    logline("power: inject failed -> releasing grab");
                    ioctl(kfd, EVIOCGRAB, 0);
                    grabbed = 0;
                    continue;
                }
                logline("power: %s -> wake (age=%lldms, swallowed so far %d)",
                        near ? "covered but limit reached" : "clear",
                        prox_age_ms, swallowed);
                swallowed = 0;
            }
        }
    }

    if (grabbed)
        ioctl(kfd, EVIOCGRAB, 0);
    if (prox_on)
        write_int_file(proxfile, 0);
    if (ufd >= 0) {
        ioctl(ufd, UI_DEV_DESTROY);
        close(ufd);
    }
    close(pfd);
    close(kfd);
    logline("stop");
    return 0;
}
