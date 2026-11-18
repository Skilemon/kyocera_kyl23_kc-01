#!/system/bin/sh
#
# kcadsp -- the one thing that runs as root on this device without adb.
#
# It does three jobs, in this order, and none of them needs a terminal, a
# mounted /data from a host, or USB:
#
#   1. bring USB up itself (the framework never manages it on this port, and
#      the gadget refuses to enable until iSerial is written -- see below);
#   2. leave a small report where any file manager can read it;
#   3. stop.  It used to also sample once a second for twenty minutes and take
#      AudioFlinger snapshots when playback started; that was for the sound
#      work and it is gone as of fix80 (see the note at the end of the file).
#
# Where the report goes -- one file, and only one:
#
#   /data/local/tmp/kcaudio.txt   0644, root-owned
#   /dev/kmsg                     as KCRPT, so a dump of the 20 MB log
#                                 partition carries it too
#
# It used to be written to /data/media/0 as well (and a copy in /cache).  That
# put a second identical file in the zip handed over after every run and made
# it ambiguous which one was current, so the media and cache copies are gone
# as of fix77.  /data/local/tmp is a tmpfs: nothing to clean up, and it is
# gone on reboot, which is the point -- one run, one file.
#
# Why the log partition alone is not enough: it is a v2.0.0 "DBGC" store with
# three reused slots that drops lines (a 640 s session leaves ~1100 of tens of
# thousands), and "Linux version" is droppable.  Absence there proves nothing.
# The KCRPT lines do not care which lines the store kept, but a *fresh* dump of
# it only contains the session before last, so the file is the primary channel.
#
# USB, and the reason "the phone does nothing at all when plugged in":
#
#   The gadget is never enabled.  Not "enabled with the wrong functions" --
#   enable stays 0, so the D+ pull-up is off and the host sees nothing, not even
#   an unknown device.  android.c:2724 explains it:
#
#       if (strcmp(serial_string,"0123456789ABCDEF")) {
#               ... android_enable(dev); dev->enabled = true;
#       } else {
#               android_connect_flag = 1;          <- enable_store(1) is a no-op
#       }
#
#   serial_string is "0123456789ABCDEF" (android.c:3031) until somebody writes
#   iSerial, and nothing in *our* ramdisk does.  The factory ramdisk started
#   /vendor/bin/usb_init from init.rc:676 for exactly that; we replaced init.rc
#   with 7.1's, which has no such service, and init.kyocera.usb.rc (which the
#   binary needs, it is what applies the composition) went with it.
#
#   So: write iSerial first, then enable.  Any non-default string works; the
#   eMMC CID gives one that is stable across flashes and unique per device.
#   After that the three compositions below are the ones the stock rc had, and
#   the property path (init.qcom.rc stanzas) works again too.

R1=/data/local/tmp/kcaudio.txt
T=/data/local/tmp/.kcaudio.$$.tmp
U=/dev/.kcusb.$$.tmp
UB=/dev/.kcusb.body
D=/sys/bus/msm_subsys/devices
B=/sys/kernel/boot_adsp/boot
AUST=/sys/class/android_usb/android0
K=/dev/kmsg
PIDF=/data/local/tmp/kcaudio.pid
LC=/data/local/tmp/kclogcat.txt
LOGDEV=/dev/block/bootdevice/by-name/log
[ -e "$LOGDEV" ] || LOGDEV=/dev/block/platform/msm_sdcc.1/by-name/log

up()   { cut -d' ' -f1 /proc/uptime 2>/dev/null; }
sec()  { echo; echo "===== $* ====="; }
kmsg() { printf '<6>KCADSP %s\n' "$*" >>$K 2>/dev/null; }

# Text helpers, in pure shell, because this ROM has no awk at all:
#
#   /vendor/bin/kcadsp.sh: awk: not found
#
# That is what fix82's sensors section and half of its display block printed --
# nothing.  toybox here carries sed/grep/tr/cut but no awk applet, and toybox
# sed has no "/pat/,+Np" range either (fix81 hit "bad pattern"), so the two
# helpers below are a while-read loop each.  They take a *file*: dumps are
# written to /data/local/tmp once and read as many times as needed, since every
# dumpsys call costs a second or two.
grab_from() {   # file startpat endpat maxlines
    _f=$1; _s=$2; _e=$3; _m=$4; _p=0; _n=0
    while IFS= read -r _l; do
        if [ "$_p" = 0 ]; then
            case "$_l" in *"$_s"*) _p=1 ;; *) continue ;; esac
        fi
        printf '%s\n' "$_l" | cut -c1-190
        _n=$((_n+1))
        case "$_l" in *"$_e"*) break ;; esac
        [ "$_n" -ge "$_m" ] && break
    done <"$_f"
}
grab_after() {  # file pat nlines
    _f=$1; _s=$2; _m=$3; _p=0; _n=0
    while IFS= read -r _l; do
        if [ "$_p" = 0 ]; then
            case "$_l" in *"$_s"*) _p=1 ;; *) continue ;; esac
        fi
        printf '%s\n' "$_l" | cut -c1-190
        _n=$((_n+1))
        [ "$_n" -ge "$_m" ] && break
    done <"$_f"
}
# Same idea, but stops at the next sensor ring.  A ring is a header line
# ("  NAME Sensor: last N events") followed by indented sample lines, and the
# next ring's header is indented by the same amount -- so "indented" is not a
# usable stop condition, "the line is another ring header" is.  Without the
# stop, "the newest sample" is the first line of the *next* sensor.
grab_ring() {   # file pat maxlines
    _f=$1; _s=$2; _m=$3; _p=0; _n=0
    while IFS= read -r _l; do
        case "$_l" in *"$_s"*) _p=1; continue ;; esac
        [ "$_p" = 1 ] || continue
        case "$_l" in
            ""|*"Sensor: last"*) break ;;
        esac
        printf '%s\n' "$_l" | cut -c1-190
        _n=$((_n+1))
        [ "$_n" -ge "$_m" ] && break
    done <"$_f"
}
st_of(){ [ -n "$1" ] && cat "$1/state" 2>/dev/null; }
adspdev() {
    for d in $D/subsys*; do
        [ -d "$d" ] || continue
        [ "$(cat $d/name 2>/dev/null)" = adsp ] && { echo "$d"; return; }
    done
}
usbsnap() {
    printf 'enable=%s state=%s func=%s vid=%s pid=%s' \
        "$(cat $AUST/enable 2>/dev/null)" "$(cat $AUST/state 2>/dev/null)" \
        "$(cat $AUST/functions 2>/dev/null)" "$(cat $AUST/idVendor 2>/dev/null)" \
        "$(cat $AUST/idProduct 2>/dev/null)"
}

# one instance only: the rc starts this from class core and again at
# boot_completed, and two samplers fighting over the file help nobody.
if [ -r "$PIDF" ] && kill -0 "$(cat $PIDF 2>/dev/null)" 2>/dev/null; then
    exit 0
fi
echo $$ >"$PIDF" 2>/dev/null

USB0=$(usbsnap)

# ---- 1. the ADSP ----------------------------------------------------------
# The rc already wrote boot_adsp from post-fs-data at ~4.7 s, which is what
# actually gets the ADSP up before audioserver.  This loop is the fallback for
# a kernel/rc mismatch, and it is what records "asked N times, rc=..".
A=$(adspdev)
asks=0
i=0
while [ $i -lt 10 ]; do
    [ "$(st_of "$A")" = ONLINE ] && break
    [ -e "$B" ] || break
    asks=$((asks+1))
    echo 1 >"$B" 2>/dev/null
    sleep 2
    i=$((i+1))
done

# ---- 2. wait for the framework -------------------------------------------
# USB must not be touched before system_server has read its own property, or
# UsbDeviceManager overwrites whatever we set two seconds later.
i=0
while [ $i -lt 30 ]; do
    [ "$(getprop sys.boot_completed 2>/dev/null)" = 1 ] && break
    sleep 2
    i=$((i+1))
done

# ---- 3. USB --------------------------------------------------------------
# The serial first.  Without it nothing below can work, and the failure is
# completely silent: enable_store(1) returns success, the pull-up never comes
# on, and the host has nothing to enumerate.
kcusb_serial() {
    s=$(getprop ro.serialno 2>/dev/null)
    case "$s" in
        ""|0123456789ABCDEF) ;;
        *) echo "$s"; return ;;
    esac
    c=$(cat /sys/block/mmcblk0/device/cid 2>/dev/null | tr -cd '0-9a-f')
    if [ ${#c} -ge 12 ]; then
        echo "KC$(printf '%s' "$c" | cut -c1-14)"
        return
    fi
    echo "KYL23KC00000001"
}
SER=$(kcusb_serial)
echo "$SER" >"$AUST/iSerial" 2>"$U"
SER_RB=$(cat "$AUST/iSerial" 2>/dev/null)
echo 0482 >"$AUST/idVendor" 2>/dev/null
echo 0a27 >"$AUST/idProduct" 2>/dev/null
# Both properties, or the framework puts "mtp" back two seconds later.
setprop persist.sys.usb.config mtp,adb 2>/dev/null

usbtry() {
    f=$1
    echo 0 >"$AUST/enable" 2>/dev/null
    echo "$2" >"$AUST/idVendor" 2>/dev/null
    echo "$3" >"$AUST/idProduct" 2>/dev/null
    if ! echo "$f" >"$AUST/functions" 2>"$U"; then
        echo "  functions=$f FAILED: $(tr '\n' ' ' <"$U" 2>/dev/null)"
        return 1
    fi
    echo 1 >"$AUST/enable" 2>/dev/null
    sleep 3
    echo "  after 3s: $(usbsnap) adbdev=$([ -e /dev/android_adb ] && echo yes || echo no) svc.adbd=$(getprop init.svc.adbd 2>/dev/null)"
    case "$(cat "$AUST/state" 2>/dev/null)" in
        CONFIGURED|CONNECTED) return 0 ;;
    esac
    return 1
}

# Last resort, and the order the kernel actually wants: enable_store(1) sets
# android_connect_flag when the serial is still the default, and *then* a
# serial_store() call does the android_enable() it skipped (android.c:2888).
usbviaen() {
    f=$1
    echo "$f" >"$AUST/functions" 2>/dev/null
    echo 1 >"$AUST/enable" 2>/dev/null
    echo "$SER" >"$AUST/iSerial" 2>/dev/null
    sleep 3
    echo "  via iSerial($f): $(usbsnap) svc.adbd=$(getprop init.svc.adbd 2>/dev/null)"
    case "$(cat "$AUST/state" 2>/dev/null)" in
        CONFIGURED|CONNECTED) return 0 ;;
    esac
    return 1
}

{
    sec usb
    echo "initial: $USB0"
    echo "serial:  ro.serialno='$(getprop ro.serialno 2>/dev/null)' wrote='$SER' readback='$SER_RB'"
    echo "props:   sys.usb.config=$(getprop sys.usb.config 2>/dev/null) sys.usb.state=$(getprop sys.usb.state 2>/dev/null) persist=$(getprop persist.sys.usb.config 2>/dev/null) configfs=$(getprop sys.usb.configfs 2>/dev/null)"
    echo "nodes:   $(ls /dev/android_adb* 2>/dev/null | tr '\n' ' ')"
    echo "udc:     $(ls /sys/class/udc 2>/dev/null | tr '\n' ' ')"
    if [ ! -d "$AUST" ]; then
        echo "no $AUST -- the gadget never registered, this is a kernel problem"
    elif [ "$(cat "$AUST/state" 2>/dev/null)" = CONFIGURED ]; then
        echo "already CONFIGURED, leaving it alone"
    else
        echo "-- bring-up --"
        setprop sys.usb.config mtp,adb 2>/dev/null
        sleep 2
        echo "  prop path: $(usbsnap)"
        case "$(cat "$AUST/state" 2>/dev/null)" in
            CONFIGURED|CONNECTED) ;;
            *) usbtry "mtp,adb" 0482 0a27 ||
               usbtry "adb" 18d1 4ee7 ||
               usbtry "mtp" 0482 0a28 ||
               usbviaen "mtp,adb" ||
               usbviaen "mtp" ;;
        esac
        echo "after:   $(usbsnap)"
        echo "enable now $(cat "$AUST/enable" 2>/dev/null) (1 = pull-up on, host will see it when the cable is in)"
    fi
    if [ -e /dev/android_adb ]; then
        case "$(getprop init.svc.adbd 2>/dev/null)" in
            running) ;;
            *) setprop ctl.start adbd 2>/dev/null; sleep 1
               echo "adbd start -> $(getprop init.svc.adbd 2>/dev/null)" ;;
        esac
    fi
    # The 25-line dmesg tail that used to be here was for the bring-up that
    # established the enabled/pid/UDC dance above; it has said the same thing
    # every boot since fix30, and the five lines above are the summary of it.
} >"$UB" 2>&1

# ---- 4. the report -------------------------------------------------------
# Short on purpose.  fix80 removed everything that only existed while the audio
# and key-backlight questions were open: the boot-stall sampler (the 25 s was
# the ADSP boot blocking audioserver, and that is fixed), the 21-line PCM status
# table, the 110-line audio policy dump, the whole AudioFlinger deep snapshot
# machinery and the sensor probe that read /dev/input/event6 by hand.
#
# What is left answers two questions that are still open:
#
#   auto-brightness   The framework side is settled: fix80's dump has
#                     mUseSoftwareAutoBrightnessConfig=true, the 11-point
#                     spline, mLightSensorEnabled=true and
#                     mLightSensorEnableTime != 0 -- AutomaticBrightnessController
#                     really did ask.  What was still 0 is the driver's
#                     enable_als_sensor, i.e. the HAL never wrote it (it runs as
#                     uid 1000 and the node was 0660 root:root).  So this report
#                     prints the owner of that node, the driver's counter, and
#                     the lux the framework ended up with: enabled + owner
#                     system + a moving mAmbientLux is the whole chain.
#
#   proximity        Not the same story as the light sensor.  fix82's dump
#                     proves the *sensor* works: en=1, "SFH7776 Proximity
#                     Sensor: last 10 events", and the value the driver reports
#                     with nothing in front of the phone is 4 (its own level 4 =
#                     "nothing there", 0..2 = covered).  What does not work is
#                     the framework end, and that is a code path, not a node:
#                     PowerManagerService.runWithProximityCheck() is only ever
#                     reached from PowerManager.wakeUpWithProximityCheck(), and
#                     the only caller in services.jar is
#                     PhoneWindowManager.wakeUp(..., withProximityCheck) with
#                     `event.getKeyCode() == KEYCODE_WAKEUP`.  The power key goes
#                     through wakeUpFromPowerKey() -> wakeUp(3 args) -> plain
#                     wakeUp().  So on this ROM the setting cannot veto a power
#                     key press at all; nothing is wrong with the sensor.
#                     fix83 put kcprox in front of the framework to do the veto
#                     the framework never did, and fix83's dump shows it working:
#                     armed on screen-off, covered at 0..2, presses swallowed,
#                     release + press waking normally, the fourth press forced
#                     through.  The per-sample "prox: newest=" line and the
#                     kcprox block below are what proves it, so the raw evdev
#                     trace this section used to ask for is gone.
#
# The display state is sampled every 15 s for five minutes, because the state
# that matters only exists while the sensor is being covered, and the report says
# so between samples, since that is where the user is looking.
A=$(adspdev)
# The two input nodes by name, not by number: what the HAL was actually asked
# for is the difference between "the framework never enabled it" and "the
# driver was told to sample and stayed silent".
LI=$(for d in /sys/class/input/input*; do [ "$(cat $d/name 2>/dev/null)" = light ] && echo "$d"; done | head -n1)
PX=$(for d in /sys/class/input/input*; do [ "$(cat $d/name 2>/dev/null)" = proximity ] && echo "$d"; done | head -n1)
# Event nodes by name, for the one-line "nodes:" summary and for -i below.
# The power key is not on gpio-keys on this device -- EventHub logs 'qpnp_pon'
# as a separate device (event1) and 'gpio-keys' (event11) carries the volume
# keys -- which is why kcprox grabs qpnp_pon and why the report names both.
evnode() {
    for d in /sys/class/input/input*; do
        [ "$(cat $d/name 2>/dev/null)" = "$1" ] || continue
        for e in $d/event*; do
            [ -e "$e" ] && { echo "/dev/input/$(basename $e)"; return; }
        done
    done
}
EVP=$(evnode proximity)
EVK=$(evnode qpnp_pon)
EVG=$(evnode gpio-keys)

dispblock() {
    echo "-- t+$1 s (up=$(up)) --"
    timeout 10 dumpsys power 2>/dev/null |
        grep -E 'mWakefulness=|mScreenBrightnessSetting=|mScreenBrightnessModeSetting=' |
        head -n 3
    # Only the ABC fields that decide whether the closed loop is running.  This
    # used to print 46 lines of the block plus four more dumpsys calls (window
    # policy, window, display extras, sensorservice) per sample -- five calls
    # every 15 s for five minutes, on a phone with two cores.  Auto-brightness
    # has been confirmed working since fix82, so what is left is a regression
    # sentinel: config on, sensor enabled, lux moving.
    _ds=/data/local/tmp/.kcdisp.$$
    timeout 10 dumpsys display >"$_ds" 2>/dev/null
    grep -E 'mUseSoftwareAutoBrightnessConfig=|mScreenAutoBrightness=|mAmbientLux=|mAmbientLuxValid=|mLightSensorEnabled=|mBrighteningLuxThreshold=|mDarkeningLuxThreshold=|mRecentLightSamples=' \
        "$_ds" 2>/dev/null | head -n 9 | cut -c1-150
    rm -f "$_ds"
    echo "setting: mode=$(settings get system screen_brightness_mode 2>/dev/null) bright=$(settings get system screen_brightness 2>/dev/null)"
    echo "leds:    lcd=$(cat /sys/class/leds/lcd-backlight/brightness 2>/dev/null) button=$(cat /sys/class/leds/button-backlight/brightness 2>/dev/null)"
    echo "input:   light=$LI en=$(cat "$LI/enable_als_sensor" 2>/dev/null) | prox=$PX en=$(cat "$PX/enable_ps_sensor" 2>/dev/null)"
    # One sensor dump, two numbers: what the framework last knew.  The rings
    # themselves are printed once, in the sensors section; per sample only the
    # newest entry, because a timeline is the point here.
    _ss=/data/local/tmp/.kcss.$$
    timeout 8 dumpsys sensorservice >"$_ss" 2>/dev/null
    echo "kcprox:  svc=$(getprop init.svc.kcprox 2>/dev/null) last=[$(tail -n 1 /data/local/tmp/kcprox.log 2>/dev/null | cut -c1-120)]"
    # Sample lines only: the ring block runs into the next section, so the last
    # line of grab_ring is not necessarily a sample.  fix83's report printed
    # "prox: newest=SFH7776 Light Sensor (handle=..., connections=1)" -- a
    # heading, not a distance -- because tail -n 1 landed on the boundary.
    echo "prox:    newest=$(grab_ring "$_ss" 'Proximity Sensor: last' 12 | grep -E '[0-9]+ \(ts=' | tail -n 1 | sed 's/, wall=[^)]*//; s/^[[:space:]]*//; s/[[:space:]]*$//' | tr -s ' \t' ' ')"
    echo "lux:     newest=$(grab_ring "$_ss" 'Light Sensor: last' 8 | grep -E '[0-9]+ \(ts=' | tail -n 1 | sed 's/, wall=[^)]*//; s/^[[:space:]]*//; s/[[:space:]]*$//' | tr -s ' \t' ' ')"
    rm -f "$_ss"
}

{
    sec subsys
    for d in $D/subsys*; do
        [ -d "$d" ] || continue
        echo "$(basename $d) name=$(cat $d/name 2>/dev/null) state=$(cat $d/state 2>/dev/null)"
    done

    sec boot
    echo "dev=${A:-MISSING} sysfs_boot=$([ -e $B ] && echo yes || echo no)"
    echo "final: state=$(st_of "$A") asks=$asks up=$(up)"

    cat "$UB"
    rm -f "$UB"

    sec audio
    echo "cards:   $(cat /proc/asound/cards 2>/dev/null | tr '\n' '|')"
    echo "audio:   start/exit = $(dmesg 2>/dev/null | grep -c "Starting service 'audioserver'") / $(dmesg 2>/dev/null | grep -c "audioserver') exited")"
    # One line, not a table: this is only here to notice a *regression*.
    busy=$(grep -s '^state' /proc/asound/card*/pcm*p/sub*/status 2>/dev/null |
        grep -v 'closed$' |
        sed 's#^/proc/asound/##; s#/status:state[[:space:]]*:[[:space:]]*#=#' |
        tr '\n' ' ')
    echo "busy:    ${busy:-none}"
    tlfile=
    for f in /system/lib/libtinyalsa.so /lib/libtinyalsa.so; do
        [ -r "$f" ] && tlfile=$f && break
    done
    echo "tinyalsa: $(wc -c <"$tlfile" 2>/dev/null) bytes $(grep -a -m1 -o 'kc-tinyalsa7[^,;]\{0,60\}' "$tlfile" 2>/dev/null)"

    sec sensors
    # Handles, types and the order the HAL reports them in.  The display dump
    # only names the sensor ABC was handed, not the handle SensorService gave
    # it, and handle == the number the HAL's activate() switches on.
    #
    # This whole section printed *nothing* in the fix82 dump: it was written
    # with awk, and /system/bin has no awk applet in this ROM.  Same for the
    # "Sensors by connection" block below and for half of the display block.
    _ss=/data/local/tmp/.kcss2.$$
    timeout 15 dumpsys sensorservice >"$_ss" 2>/dev/null
    grab_after "$_ss" "Sensor List" 12 | cut -c1-170
    # Who holds the proximity sensor right now.  "Sensors by connection" is the
    # 4.4-era heading; 14.1's dumpsys has "Active sensors:" and "Previous
    # Registrations:" instead, which is why fix83's holders block came out
    # empty.  What matters is the connection count: 0 active connections while
    # proximity_on_wake=1 is the framework agreeing it never asked for it.
    echo "-- holders --"
    grab_after "$_ss" "Active sensors:" 8
    # The full proximity ring, not one line of it.  fix82 printed only the
    # oldest entry of "last N events" (4.00) and that single number cannot
    # distinguish "far, as it should be" from "stuck".  The sequence 4..4,0..0,4
    # is the proof that the driver reports both states.
    echo "-- prox ring --"
    grep -m1 'Proximity Sensor: last' "$_ss" 2>/dev/null | sed 's/^[[:space:]]*//'
    grab_ring "$_ss" "Proximity Sensor: last" 14
    echo "-- light ring --"
    grep -m1 'Light Sensor: last' "$_ss" 2>/dev/null | sed 's/^[[:space:]]*//'
    grab_ring "$_ss" "Light Sensor: last" 8
    rm -f "$_ss"
    # What the node advertises, from /proc rather than `getevent -i`: this
    # toybox build prints its usage for -i (and for -lt) when handed a device
    # path, which is why fix83's caps line was blank.  Bit 0x10 is ABS_DISTANCE.
    echo "caps:    $(grep -A6 'Name="proximity"' /proc/bus/input/devices 2>/dev/null | grep -m1 'B: ABS=' | tr -s ' ' ' ')"
    echo "nodes:   key=$EVK prox=$EVP"
    echo "psdrv:   $(dmesg 2>/dev/null | grep 'ABS_DISTANCE' | tail -n 6 | sed 's/^.*\] //' | tr '\n' '|')"
    echo "kcsensor: $(dmesg 2>/dev/null | grep -m1 'kcsensor:')"
    # What the pocket-mode daemon decided, and when.  This is the only record
    # of a swallowed power key: nothing reaches logcat when a press is dropped,
    # because the whole point is that the framework never sees it.
    echo "-- kcprox --"
    echo "  svc=$(getprop init.svc.kcprox 2>/dev/null) log=/data/local/tmp/kcprox.log"
    tail -n 20 /data/local/tmp/kcprox.log 2>/dev/null | cut -c1-170

    sec display
    dispblock 0
    echo
    echo "load:    $(grep -c 'find symbol HMI' "$LC" 2>/dev/null) x 'couldn't find symbol HMI' (must be 0)"

    # GPS.  The symptom being chased is "satellites are visible but there is no
    # position", and that shape has exactly three explanations worth telling
    # apart, in this order:
    #
    #   1. the engine never started      -> no /dev/gss, or locClientOpen failed
    #   2. the engine runs, no ephemeris  -> SV list has CN0 but no fix; needs
    #      12.5 min of clean sky, or XTRA, and this gps.conf has every
    #      XTRA_SERVER line commented out
    #   3. the engine has a fix and the framework drops it -> rare, and the
    #      only reason to look at dumpsys location
    #
    # The logcat lines below are the engine's own words: locClientOpen's
    # "Service instance id is -1" means the QMI LOC client did not attach to an
    # instance, and every position fix shows up as a LOC_EVENT_POSITION_REPORT
    # or a GnssLocationProvider locationReceived.  Nothing here is sampled --
    # one snapshot per report, and the report can be re-run after a GPS session
    # by hand (the pidfile is removed at exit).
    sec gps
    echo "dev:     $([ -e /dev/gss ] && echo yes || echo NO) $(stat -c '%U:%G %a' /dev/gss 2>/dev/null)"
    echo "conf:    $(ls -l /system/etc/gps.conf /vendor/etc/gps.conf 2>/dev/null | wc -l) file(s), xtra_servers=$(grep -c '^XTRA_SERVER' /system/etc/gps.conf 2>/dev/null) supl=[$(grep '^SUPL_HOST' /system/etc/gps.conf 2>/dev/null)]"
    echo "state:   $(ls /data/misc/gpsone_d/ 2>/dev/null | tr '\n' ' ')"
    echo "mode:    $(settings get secure location_mode 2>/dev/null) providers=[$(settings get secure location_providers_allowed 2>/dev/null)]"
    _dl=/data/local/tmp/.kcloc.$$
    timeout 12 dumpsys location >"$_dl" 2>/dev/null
    grab_from "$_dl" "Location Manager State" "Passive" 24
    echo "  -- fixes --"
    grep -E "last location=|Last Known|gps:|gnss:" "$_dl" 2>/dev/null | head -n 6 | cut -c1-170
    rm -f "$_dl"
    echo "  -- engine log (last 18) --"
    grep -a -E "LocSvc|GnssLocationProvider|locClient" "$LC" 2>/dev/null | tail -n 18 | cut -c1-170

    # Camera and the torch.  7.1's CameraService refuses to load this device's
    # HAL, and the reason is one line in logcat that is very easy to miss:
    #
    #   E HAL: load: module=/vendor/lib/hw/camera.msm8226.so
    #   E HAL: dlopen failed: /system/vendor/lib/libmmcamera_faceproc.so:
    #          has text relocations
    #
    # bionic has rejected DF_TEXTREL libraries since 5.0, and every camera
    # function -- preview, shutter, flash, and setTorchMode for the flashlight
    # tile -- sits behind that dlopen.  Only one library in the whole blob set
    # has the flag (libmmcamera_faceproc.so), and camera.msm8226.so imports no
    # symbol that is unique to it, so fix84 builds the HAL without that DT_NEEDED
    # entry.  These four lines say whether it took.
    sec camera
    echo "hal:     $(ls -l /vendor/lib/hw/camera.msm8226.so 2>/dev/null | sed 's/^.* \([0-9]*\) /\1 /') md5=$(md5sum /vendor/lib/hw/camera.msm8226.so 2>/dev/null | cut -c1-32)"
    echo "torch:   $(cat /sys/class/leds/torch-light/brightness 2>/dev/null) (node $([ -e /sys/class/leds/torch-light ] && echo present || echo MISSING))"
    echo "lights:  $(grep -ac flashlight /vendor/lib/hw/lights.default.so 2>/dev/null) x 'flashlight' in the HAL (must be >= 1)"
    echo "  -- camera log (last 8) --"
    grep -a -E "Could not load camera HAL|has text relocations|camera.msm8226|CameraService" "$LC" 2>/dev/null | tail -n 8 | cut -c1-170
} >"$T" 2>&1

writereport() {
    lrec=$(od -An -tu4 -j 8 -N 4 "$LOGDEV" 2>/dev/null | tr -d ' ')
    {
        echo "=== SUMMARY ==="
        echo "version: $(cat /proc/version)"
        echo "uptime:  $(up)  android: $(getprop ro.build.version.release 2>/dev/null) $(getprop ro.build.type 2>/dev/null)"
        echo "adsp:    state=$(st_of "$A") dev=${A:-MISSING} asks=$asks"
        echo "usb0:    $USB0"
        echo "usb:     $(usbsnap) adbdev=$([ -e /dev/android_adb ] && echo yes || echo no) svc.adbd=$(getprop init.svc.adbd 2>/dev/null)"
        echo "serial:  '$(cat $AUST/iSerial 2>/dev/null)' (ro.serialno='$(getprop ro.serialno 2>/dev/null)')"
        echo "card:    $(cat /proc/asound/cards 2>/dev/null | tr '\n' '|')"
        echo "audio:   start/exit = $(dmesg 2>/dev/null | grep -c "Starting service 'audioserver'") / $(dmesg 2>/dev/null | grep -c "audioserver') exited")"
        echo "logstore: magic=$(dd if="$LOGDEV" bs=1 count=7 2>/dev/null) records=${lrec:-?}"
        # adsprpcd is the factory KitKat daemon started by init.qcom.rc:271.  It
        # exits 255 within half a second, twice, and then stops being restarted.
        # Two candidates, and this line tells them apart: the device node it
        # opens (/dev/adsprpc-smd, a misc device, and this kernel is built with
        # devtmpfs off so ueventd has to create it) or something inside the
        # daemon itself.
        echo "adsprpc: svc=$(getprop init.svc.adsprpcd 2>/dev/null) nodes=$(ls /dev/adsprpc* 2>/dev/null | tr '\n' ' ') last=[$(dmesg 2>/dev/null | grep "Service 'adsprpcd'" | tail -1 | sed 's/^.*\] //')]"
        cat "$T"
        if [ -s "${R1}.ev" ]; then
            sec events
            tail -n 200 "${R1}.ev"
        fi
    } >"$R1" 2>/dev/null
    chmod 0644 "$R1" 2>/dev/null
}

writereport

# ---- 5. mirror into kmsg -------------------------------------------------
# 40 lines, not 120: the DBGC store drops lines, and 40 short lines survive a
# lot better than 120.  The whole file is on internal storage anyway.
n=0
while IFS= read -r l; do
    n=$((n+1))
    [ $n -gt 40 ] && { kmsg "KCRPT| ... $n+ lines, full copy at $R1"; break; }
    kmsg "KCRPT| $(printf '%s' "$l" | cut -c1-180)"
done <"$R1"

# ---- 6. the sensor timeline ----------------------------------------------
# The report above is written within a minute of boot_completed.  It used to
# sample every 15 s for twenty samples (five minutes) because the interesting
# state only existed while somebody was covering a sensor, and fix80's dump was
# pulled 70 s into the test.  Both sensor questions are settled now:
# auto-brightness works (fix82) and the proximity veto works (fix83), so what
# is left is four samples over one minute -- enough to see a regression, not
# enough to cost five dumpsys calls every 15 s for five minutes.
#
# The report can be re-run by hand at any time: the pidfile is removed on exit,
# which is what makes "open a GPS app, wait a minute, run kcadsp.sh again"
# work for the gps section above.
#
# This used to also record the raw evdev stream of the power key and the
# proximity sensor for the same five minutes, as a second reader on the same
# nodes.  It never produced a single event: toybox's getevent prints its usage
# and exits when given an explicit device path together with -lt, and the only
# thing that ended up in /data/local/tmp/kc_input.log was that usage text.  The
# question it was meant to answer -- what distance is reported while covered --
# is answered by the per-sample "prox: newest=" line below, straight from the
# driver's own ring buffer.  Removed in fix84.
{
    sec "sensor timeline"
    echo "  每 15 秒采样一次，共 4 次（到开机后约 1 分钟）。"
    echo "  亮度与距离都已在上几轮确认过，这里只留一段回归哨兵："
    echo "  打开「自适应亮度」并遮一下光感，应能看到 mAmbientLux 变化、"
    echo "  mScreenAutoBrightness 跟随；盖住听筒时 prox: newest 应落到 0..2。"
    echo "  GPS 请另外测：进任意地图/GPSTest 等到搜到卫星后保持 1 分钟，"
    echo "  再执行一次 sh /vendor/bin/kcadsp.sh，报告里的 gps 段会记下引擎状态。"
} >>"$R1" 2>/dev/null
i=1
while [ $i -le 4 ]; do
    sleep 15
    dispblock "$((i*15))" >>"$R1" 2>/dev/null
    i=$((i+1))
done
{
    sec "timeline done"
    echo "  采样结束。文件可以取了。"
} >>"$R1" 2>/dev/null
chmod 0644 "$R1" 2>/dev/null

# ---- 7. done -------------------------------------------------------------
# What used to be here was a 1200-iteration sampler (1 s, then 2 s) that watched
# the PCM nodes and took an AudioFlinger snapshot the moment one went busy.
# That is how fix74 -> fix78 were diagnosed, and it is also how the report would
# be flooded now: every state change went to /dev/kmsg and to the .ev file,
# 40 KB of it per boot with nothing to look at.  Sound works, so it is gone; the
# version to restore, if it is ever needed again, is in the fix79 commit.

kmsg "report done up=$(up), file $R1"
rm -f "$T" "$U" "$PIDF" 2>/dev/null
exit 0
