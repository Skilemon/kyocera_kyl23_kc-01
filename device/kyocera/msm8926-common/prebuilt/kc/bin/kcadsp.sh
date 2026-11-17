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
#   proximity on wake Same node, same cause (enable_ps_sensor).  Once the HAL
#                     can write it, PWM's "Not waking up. Proximity sensor is
#                     blocked." becomes possible again.
#
# Both are sampled once a minute for three minutes, because the state that
# matters only exists while the sensor is being covered, and the report says so
# between samples, since that is where the user is looking.
A=$(adspdev)
# The two input nodes by name, not by number: what the HAL was actually asked
# for is the difference between "the framework never enabled it" and "the
# driver was told to sample and stayed silent".
LI=$(for d in /sys/class/input/input*; do [ "$(cat $d/name 2>/dev/null)" = light ] && echo "$d"; done | head -n1)
PX=$(for d in /sys/class/input/input*; do [ "$(cat $d/name 2>/dev/null)" = proximity ] && echo "$d"; done | head -n1)

dispblock() {
    echo "-- t+$1 s (up=$(up)) --"
    timeout 10 dumpsys power 2>/dev/null |
        grep -E 'mWakefulness=|mScreenBrightnessSetting=|mScreenBrightnessModeSetting=|mScreenBrightnessOverrideFromWindowManager=|mTemporaryScreenBrightnessSettingOverride=' |
        head -n 6
    timeout 10 dumpsys display 2>/dev/null |
        grep -E 'mUseSoftwareAutoBrightnessConfig=|mProximitySensor=|mProximitySensorEnabled=|mScreenBrightness=|mScreenAutoBrightnessSpline=|mLightSensor=|mLightSensorEnabled=|mLightSensorEnableTime=|mAmbientLux=|mScreenAutoBrightness=|mLastObservedLux=|mDozing=|mAmbientLightRingBuffer=' |
        cut -c1-240 | head -n 14
    timeout 10 dumpsys window policy 2>/dev/null |
        grep -iE 'mProximityWake|mProximitySensor|mProximityTimeOut|mAwake=|mScreenOnEarly=' |
        head -n 8
    echo "setting: mode=$(settings get system screen_brightness_mode 2>/dev/null) prox=$(settings get system proximity_on_wake 2>/dev/null) bright=$(settings get system screen_brightness 2>/dev/null)"
    echo "leds:    lcd=$(cat /sys/class/leds/lcd-backlight/brightness 2>/dev/null) button=$(cat /sys/class/leds/button-backlight/brightness 2>/dev/null)"
    echo "input:   light=$LI en=$(cat "$LI/enable_als_sensor" 2>/dev/null) poll=$(cat "$LI/als_poll_delay" 2>/dev/null) | prox=$PX en=$(cat "$PX/enable_ps_sensor" 2>/dev/null)"
    # Owner is the whole point: the HAL writes these as uid 1000, and 0660
    # root:root is what made every write EACCES before fix81.
    echo "perm:    $(stat -c '%U:%G %a' "$LI/enable_als_sensor" 2>/dev/null) $(stat -c '%U:%G %a' "$PX/enable_ps_sensor" 2>/dev/null) $(stat -c '%U:%G %a' /dev/psals_sensor 2>/dev/null)"
    echo "sensor:  $(timeout 6 dumpsys sensorservice 2>/dev/null |
        grep -E 'Light Sensor: last|Proximity Sensor: last' -A1 |
        tr -s ' \n' ' ' | cut -c1-240)"
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
    timeout 10 dumpsys sensorservice 2>/dev/null | sed -n '/Sensor List/,+10p' | cut -c1-170
    echo "kcsensor: $(dmesg 2>/dev/null | grep -m1 'kcsensor:')"

    sec display
    dispblock 0
    echo
    echo "load:    $(grep -c 'find symbol HMI' "$LC" 2>/dev/null) x 'couldn't find symbol HMI' (must be 0)"
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
# The report above is written within a minute of boot_completed.  The test --
# open Settings, turn adaptive brightness on, cover the sensor -- happens after
# that, and fix80's dump was pulled only 70 s into it, so the file ended up with
# two samples and the interesting minute was missing.  Six samples 30 s apart
# cover the first three minutes with a before and an after of the same action;
# the file can be pulled as soon as the seventh header appears.
{
    sec "sensor timeline"
    echo "  每 30 秒采样一次，共 6 次（到开机后约 3 分钟）。"
    echo "  现在去 设置 -> 显示 打开「自适应亮度」，然后遮住屏幕上方听筒左边的"
    echo "  光感约 2 秒，再用手盖住听筒约 3 秒。每次采样都会记在这里。"
} >>"$R1" 2>/dev/null
i=1
while [ $i -le 6 ]; do
    sleep 30
    dispblock "$((i*30))" >>"$R1" 2>/dev/null
    i=$((i+1))
done
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
