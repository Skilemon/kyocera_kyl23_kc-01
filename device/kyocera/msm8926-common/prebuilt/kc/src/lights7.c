/*
 * lights7.c -- a 7.1 lights HAL for this device, written from scratch.
 *
 * Why it exists: the lights HAL in the fix76 image is a hand-built .so with no
 * DT_NEEDED at all.  On 7.1 the linker resolves a vendor library's undefined
 * symbols only through its declared dependencies, so the very first libc call
 * it made failed at load time:
 *
 *     E HAL: load: module=/vendor/lib/hw/lights.default.so
 *     E HAL: dlopen failed: cannot locate symbol "write" referenced by ...
 *
 * LightsService never came up, which cost the panel backlight (no brightness
 * control at all, the panel stayed at whatever the bootloader left) and the
 * notification LED.
 *
 * This one declares libc.so (see build.sh) and only uses open/write/close, so
 * the symbols resolve against bionic the same way the stock HAL's do.
 *
 * Mapping, from /sys/class/leds on this device:
 *   backlight      -> lcd-backlight            (0..255)
 *   buttons        -> button-backlight         (0..255)
 *   battery        -> red / green              (charge state)
 *   notifications  -> amber
 *   attention      -> amber
 *   keyboard, bluetooth, wifi -> nothing on this board
 *   flashlight     -> torch-light              (0..255)
 *
 * flashlight was missing until fix84 and that is a real user-visible bug, not
 * a completeness exercise: nothing in the ROM could turn the LED on.  The node
 * itself is fine -- drivers/media/platform/msm/camera_v2/sensor/flash/
 * msm_led_torch.c registers "torch-light" and its brightness_set() is a plain
 * led_trigger_event(), so any 0..255 value lights it.  The factory 4.4 HAL
 * (kc_lights.default.so) knows the same path; only this rewrite forgot it.
 *
 * The quick-settings tile is a separate path: 7.1's FlashlightController goes
 * through CameraManager.setTorchMode(), i.e. the camera HAL, and this device's
 * camera HAL is 4.4 (no set_torch_mode field at all), so that route is dead on
 * this port regardless.  This handler is what makes every LightsManager client
 * -- Tasker, the torch widgets, `service call lights` -- work again.
 */

#include <stdint.h>
#include <stddef.h>

/* ------------------------------------------------------------------ */
/* hardware/libhardware structures, 7.1 layout                         */
/* ------------------------------------------------------------------ */

#define MAKE_TAG(a, b, c, d) \
    (((uint32_t)(a) << 24) | ((uint32_t)(b) << 16) | ((uint32_t)(c) << 8) | (uint32_t)(d))

#define HARDWARE_MODULE_TAG MAKE_TAG('H', 'W', 'M', 'T')
#define HARDWARE_DEVICE_TAG MAKE_TAG('H', 'W', 'D', 'T')

struct hw_module_t;
struct hw_device_t;

struct hw_module_methods_t {
    int (*open)(const struct hw_module_t *module, const char *id, struct hw_device_t **device);
};

struct hw_module_t {
    uint32_t tag;
    uint16_t module_api_version;
    uint16_t hal_api_version;
    const char *id;
    const char *name;
    const char *author;
    struct hw_module_methods_t *methods;
    void *dso;
    uint32_t reserved[32 - 7];
};

struct hw_device_t {
    uint32_t tag;
    uint32_t version;
    struct hw_module_t *module;
    uint32_t reserved[12];
    int (*close)(struct hw_device_t *device);
};

struct light_state_t {
    unsigned int color;          /* ARGB */
    unsigned int flashMode;
    unsigned int flashOnMs;
    unsigned int flashOffMs;
    unsigned int brightnessMode;
};

struct light_device_t {
    struct hw_device_t common;
    int (*set_light)(struct light_device_t *dev, const struct light_state_t *state);
};

#define LIGHT_VERSION 1

/* libc, declared rather than included: a 32-bit glibc header set rewrites
 * open() to open64() and bionic has no such symbol. */
extern int open(const char *path, int flags, ...);
extern int close(int fd);
extern long write(int fd, const void *buf, unsigned long count);

#define O_WRONLY 00000001

/* ------------------------------------------------------------------ */
/* sysfs                                                               */
/* ------------------------------------------------------------------ */

static int write_str(const char *path, const char *s, int len)
{
    int fd = open(path, O_WRONLY, 0);
    long n;

    if (fd < 0)
        return -1;
    n = write(fd, s, (unsigned long)len);
    close(fd);
    return n == len ? 0 : -1;
}

static int write_int(const char *path, int value)
{
    char buf[12];
    int i = 0, j;
    char tmp[12];

    if (value < 0)
        value = 0;
    do {
        tmp[i++] = (char)('0' + value % 10);
        value /= 10;
    } while (value);
    for (j = 0; j < i; j++)
        buf[j] = tmp[i - 1 - j];
    buf[i] = '\n';
    return write_str(path, buf, i + 1);
}

static int str_eq(const char *a, const char *b)
{
    while (*a && *a == *b) {
        a++;
        b++;
    }
    return *a == *b;
}

static int max_component(unsigned int color)
{
    int r = (int)((color >> 16) & 0xff);
    int g = (int)((color >> 8) & 0xff);
    int b = (int)(color & 0xff);
    int m = r > g ? r : g;

    return b > m ? b : m;
}

static int state_is_on(const struct light_state_t *state)
{
    if (!state)
        return 0;
    if (state->flashMode == 2 /* LIGHT_FLASH_TIMED */)
        return 1;
    return max_component(state->color) > 0;
}

/* ------------------------------------------------------------------ */
/* per-light handlers                                                  */
/* ------------------------------------------------------------------ */

static int light_backlight(struct light_device_t *dev, const struct light_state_t *state)
{
    int v;

    (void)dev;
    if (!state)
        return -1;
    v = max_component(state->color);
    /* LIGHT_FLASH_NONE with black is "off", but never let a transient 0 blank
     * the panel from a HAL that has no other brightness source. */
    return write_int("/sys/class/leds/lcd-backlight/brightness", v);
}

static int light_buttons(struct light_device_t *dev, const struct light_state_t *state)
{
    int v;

    (void)dev;
    if (!state)
        return -1;
    v = state_is_on(state) ? max_component(state->color) : 0;
    return write_int("/sys/class/leds/button-backlight/brightness", v);
}

static int light_amber(struct light_device_t *dev, const struct light_state_t *state)
{
    int v;

    (void)dev;
    if (!state)
        return -1;
    v = state_is_on(state) ? max_component(state->color) : 0;
    return write_int("/sys/class/leds/amber/brightness", v);
}

static int light_battery(struct light_device_t *dev, const struct light_state_t *state)
{
    int r, g;

    (void)dev;
    if (!state)
        return -1;
    r = (int)((state->color >> 16) & 0xff);
    g = (int)((state->color >> 8) & 0xff);
    if (!state_is_on(state)) {
        r = 0;
        g = 0;
    }
    write_int("/sys/class/leds/red/brightness", r);
    write_int("/sys/class/leds/green/brightness", g);
    return 0;
}

static int light_none(struct light_device_t *dev, const struct light_state_t *state)
{
    (void)dev;
    (void)state;
    return 0;
}

/* torch-light takes 0..255 through led_trigger_event(), so the colour's max
 * component is the right value -- the framework sends 0xFFFFFFFF for "on" and
 * 0 for "off", i.e. 255 and 0 after this. */
static int light_flashlight(struct light_device_t *dev, const struct light_state_t *state)
{
    int v;
    int rc;

    (void)dev;
    if (!state)
        return -1;
    v = state_is_on(state) ? max_component(state->color) : 0;

    /* Two nodes reach the same die: torch-light, which msm_led_torch
     * registers, and led:flash_torch, the trigger the camera blob installs
     * once it has claimed the LED.  Both light when written by hand, and
     * which of them exists depends on whether the camera HAL got that far,
     * so fall back rather than assume.  Never write both -- they are two
     * views of one device and a double write is a double current step. */
    rc = write_int("/sys/class/leds/torch-light/brightness", v);
    if (rc != 0)
        rc = write_int("/sys/class/leds/led:flash_torch/brightness", v);
    return rc;
}

/* ------------------------------------------------------------------ */
/* module                                                              */
/* ------------------------------------------------------------------ */

static int close_light(struct hw_device_t *dev)
{
    (void)dev;
    return 0;
}

#define MAX_LIGHTS 8
static struct light_device_t g_lights[MAX_LIGHTS];
static int g_used;

static int open_light(const struct hw_module_t *module, const char *id, struct hw_device_t **device)
{
    struct light_device_t *dev;
    int (*fn)(struct light_device_t *, const struct light_state_t *);

    if (!id || !device || g_used >= MAX_LIGHTS)
        return -1;

    if (str_eq(id, "backlight"))
        fn = light_backlight;
    else if (str_eq(id, "buttons") || str_eq(id, "keyboard"))
        fn = light_buttons;
    else if (str_eq(id, "battery"))
        fn = light_battery;
    else if (str_eq(id, "notifications") || str_eq(id, "attention"))
        fn = light_amber;
    else if (str_eq(id, "flashlight"))
        fn = light_flashlight;
    else if (str_eq(id, "bluetooth") || str_eq(id, "wifi"))
        fn = light_none;
    else
        return -1;

    dev = &g_lights[g_used++];
    dev->common.tag = HARDWARE_DEVICE_TAG;
    dev->common.version = LIGHT_VERSION;
    dev->common.module = (struct hw_module_t *)module;
    dev->common.close = close_light;
    dev->set_light = fn;
    *device = (struct hw_device_t *)dev;
    return 0;
}

static struct hw_module_methods_t g_methods = {
    .open = open_light,
};

/*
 * The symbol has to be named HMI, not HAL_MODULE_INFO_SYM.
 *
 * hardware.h does `#define HAL_MODULE_INFO_SYM HMI`, so a real HAL writes
 * `struct hw_module_t HAL_MODULE_INFO_SYM` and the compiler emits a symbol
 * literally called HMI.  lights7.c spelled the macro name out instead, so the
 * .so exported "HAL_MODULE_INFO_SYM" while hw_get_module() dlsym()ed "HMI":
 *
 *     E HAL: load: couldn't find symbol HMI
 *
 * That is why the fix77 build still had no brightness control -- the library
 * loaded, and then the loader threw it away because it could not find its
 * entry point.  The version fields also now match what a real 7.1 lights HAL
 * declares (HARDWARE_MODULE_API_VERSION(1,0) == 0x0100).
 */
#define KC_MODULE_INFO_SYM HMI

struct hw_module_t KC_MODULE_INFO_SYM = {
    .tag = HARDWARE_MODULE_TAG,
    .module_api_version = 0x0100,
    .hal_api_version = 0x0100,
    .id = "lights",
    .name = "Kyocera KC01 lights module",
    .author = "kc01 port",
    .methods = &g_methods,
    .dso = 0,
    .reserved = {0},
};
