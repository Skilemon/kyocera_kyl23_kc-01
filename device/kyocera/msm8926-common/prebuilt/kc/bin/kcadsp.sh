#!/system/bin/sh
#
# kcadsp -- the one thing that runs as root on this device without adb.
#
# It does four jobs, in this order, and none of them needs a terminal, a
# mounted /data from a host, or USB:
#
#   1. bring USB up itself (the framework never manages it on this port, and
#      the gadget refuses to enable until iSerial is written -- see below);
#   2. leave a small report where any file manager can read it;
#   3. keep sampling once a second, so a sound played *later* is recorded at
#      the transition, not two seconds after it;
#   4. when playback finally starts, take one deep snapshot of AudioFlinger
#      while the stream is live -- that is the only moment it is true.
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
    echo "-- dmesg usb --"
    dmesg 2>/dev/null | grep -Ei 'android_usb|msm_otg|msm_hsusb|udc|usb_bam|android_work|enable_store' | tail -n 25
} >"$UB" 2>&1

# ---- 4. the report -------------------------------------------------------
A=$(adspdev)
{
    sec subsys
    for d in $D/subsys*; do
        [ -d "$d" ] || continue
        echo "$(basename $d) name=$(cat $d/name 2>/dev/null) state=$(cat $d/state 2>/dev/null)"
    done

    sec boot
    echo "dev=${A:-MISSING} sysfs_boot=$([ -e $B ] && echo yes || echo no)"
    echo "fw adsp files: $(ls /firmware/image 2>/dev/null | grep -ic '^adsp')"
    echo "final: state=$(st_of "$A") asks=$asks up=$(up)"

    cat "$UB"
    rm -f "$UB"

    sec kernel
    dmesg 2>/dev/null | grep -E 'adsp-loader:' | tail -n 20
    echo "-- pil --"
    dmesg 2>/dev/null | grep -E 'pil-q6v5-lpass|pil_pronto|subsystem_restart' | tail -n 12
    echo "-- apr --"
    dmesg 2>/dev/null | grep -E 'apr_tal|APR:|Q6 Is Up|adsp not up' | tail -n 15
    echo "-- audio --"
    dmesg 2>/dev/null | grep -Ei 'audioserver|tapan|asoc|slimbus|sound\.' | tail -n 20

    sec audio
    echo "cards: $(cat /proc/asound/cards 2>/dev/null | tr '\n' '|')"
    echo "pcm:   $(cat /proc/asound/pcm 2>/dev/null | head -n 10 | tr '\n' '|')"
    echo "slim:  $(ls /sys/bus/slimbus/devices 2>/dev/null | tr '\n' ',')"
    echo "audioserver start/exit: $(dmesg 2>/dev/null | grep -c "Starting service 'audioserver'") / $(dmesg 2>/dev/null | grep -c "audioserver') exited")"
    # The audio HAL in /vendor/lib/hw is the KitKat prebuilt (byte-identical to
    # the stock one), and it passes a 36-byte struct pcm_config.  libtinyalsa
    # 13580 bytes is the KitKat build that expects those 36 bytes; 26420 bytes
    # is the 7.1 build, which reads avail_min at offset 36 and silence_size at
    # 32 -- i.e. past the end of the caller's struct -- and every pcm_open()
    # then dies in SNDRV_PCM_IOCTL_SW_PARAMS with EINVAL.
    tlfile=
    for f in /system/lib/libtinyalsa.so /lib/libtinyalsa.so; do
        [ -r "$f" ] && tlfile=$f && break
    done
    echo "tinyalsa: ${tlfile:-missing} $(wc -c <"$tlfile" 2>/dev/null) bytes"
    echo "          $(grep -m1 -ao 'kc-tinyalsa7[^\"]*' "$tlfile" 2>/dev/null || echo 'no kc-tinyalsa7 tag -- still the stock 7.1 or KitKat build')"

    sec sensors
    # fix76's dump retired the 36-vs-68-byte sensor_t theory: SensorService
    # printed all eight sensors with the right names, vendors and handles, so
    # the HAL's array is stepped correctly.  What it also printed was
    #
    #     Recent Sensor events:            <- nothing, ever
    #     Active sensors: SFH7776 Proximity Sensor (connections=1)
    #
    # and the sysfs enable nodes were still 0.  So the framework asked for the
    # proximity sensor and the HAL either never wrote enable, or wrote it and
    # got nothing back.  This section now settles that by hand: write the node
    # itself, read the event device, write it back.
    echo "hal:    $(wc -c </vendor/lib/hw/sensors.default.so 2>/dev/null) bytes"
    for d in /sys/class/input/input*; do
        [ -r "$d/name" ] || continue
        n=$(cat "$d/name" 2>/dev/null)
        case "$n" in
            light|proximity)
                echo "$d name=$n"
                for a in enable_als_sensor als_poll_delay als_ratio enable_ps_sensor ps_crosstalk drvstr; do
                    [ -r "$d/$a" ] && echo "    $a=$(cat "$d/$a" 2>/dev/null)"
                done
                ;;
            *) echo "$d name=$n" ;;
        esac
    done

    # Direct proof, one sensor at a time: does the driver emit an event when
    # the enable node is written by hand?  If yes the kernel and the part are
    # fine and the fault is above (HAL or SensorService); if no, it is below
    # and no amount of HAL surgery will help.
    sensprobe() {
        id=$1      # input6
        node=$2    # enable_als_sensor
        d=/sys/class/input/$id
        ev=
        for e in "$d"/event*; do [ -e "$e" ] && ev=/dev/input/$(basename "$e"); done
        [ -e "$d/$node" ] || { echo "  $id: no $node"; return; }
        was=$(cat "$d/$node" 2>/dev/null)
        echo "  $id $node: before=$was event=${ev:-none}"
        echo 1 >"$d/$node" 2>/dev/null
        sleep 1
        echo "  $id $node: after=$(cat "$d/$node" 2>/dev/null)"
        if [ -n "$ev" ] && [ -r "$ev" ]; then
            echo "  $id events (16-byte input_event, raw):"
            timeout 2 dd if="$ev" bs=16 count=3 2>/dev/null | od -An -tu4 -w16 | head -n 4
        fi
        # put back whatever was there: if the framework had already enabled it
        # for the phone app, forcing 0 would quietly take proximity away.
        echo "${was:-0}" >"$d/$node" 2>/dev/null
    }
    echo "-- direct probe --"
    sensprobe input6 enable_als_sensor
    sensprobe input7 enable_ps_sensor

    echo "-- sensorservice --"
    timeout 8 dumpsys sensorservice 2>/dev/null | head -n 60

    sec mic
    echo "capture: $(ls /proc/asound/card*/pcm*c/sub*/status 2>/dev/null | tr '\n' ' ')"
    echo "-- audio policy (full, first 110 lines) --"
    # fix76 grepped this for "input" and got three lines, because 7.1 dumps the
    # whole AudioPolicyConfig as XML and the interesting part -- which input
    # profile was parsed, with which masks -- is not on a line containing the
    # word "input".  Dump it whole; it is the only place the parsed profile is
    # visible without a debugger.
    timeout 10 dumpsys media.audio_policy 2>/dev/null | head -n 110
    echo "-- input devices as APM sees them --"
    timeout 5 dumpsys media.audio_policy 2>/dev/null | grep -Ei 'unreachable|input|Input' | head -n 30
    echo "-- record attempts --"
    grep -Ei 'AudioRecord|open_input|start_input|getInputForAttr|cannot open input|AUDIO_DEVICE_IN' "$LC" 2>/dev/null | tail -n 12

    sec led
    echo "leds:   $(ls /sys/class/leds 2>/dev/null | tr '\n' ' ')"
    echo "button: $(cat /sys/class/leds/button-backlight/brightness 2>/dev/null) of $(cat /sys/class/leds/button-backlight/max_brightness 2>/dev/null)"
    echo "lcd:    $(cat /sys/class/leds/lcd-backlight/brightness 2>/dev/null)"
    echo "-- kcledguard --"
    sed 's/^/    /' /data/local/tmp/kc_led.log 2>/dev/null | head -n 20

    sec pcm
    for p in /proc/asound/card*/pcm*p/sub*/status; do
        [ -r "$p" ] || continue
        echo "$p"
        sed 's/^/    /' "$p" 2>/dev/null | head -n 8
    done
    echo "-- datapath --"
    dmesg 2>/dev/null | grep -Ei 'msm_pcm|msm-dai|afe_|adm_|asm_|dapm' | tail -n 20

    sec logcat_audio
    # kclogcat (a service in kyl23-extra.rc) has been writing every buffer to
    # disk since boot_completed, so this is the *live* stream, not the tail of
    # a buffer that has already wrapped.  Fall back to logcat -d if it is not
    # there -- that is the fix72 behaviour, and it only ever showed the boot.
    if [ -s "$LC" ]; then
        echo "from $LC ($(wc -l <"$LC" 2>/dev/null) lines)"
        grep -Ei 'audioflinger|audiopolicy|audio_hw|audiohal|tapan|adm_|asm_|afe_|MediaPlayer|AudioTrack|NuPlayer|OMX' "$LC" 2>/dev/null | tail -n 80
    else
        logcat -d -v brief -t 400 2>/dev/null |
            grep -Ei 'audioflinger|audiopolicy|audio_hw|audiohal|tapan|adm_|asm_|afe_|usb' |
            tail -n 40
    fi
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

# ---- 6. sample once a second, and go deep when playback starts -------------
# The fix72 run sampled every 2 s and recorded this for a 20-second playback:
#
#     136.37 | ... pcm= card0/pcm0p/sub0=OPEN
#     139.75 | ... pcm=none
#
# i.e. the output was opened, sat in "open", and closed again 3.4 s later.  It
# never reached PREPARED or RUNNING, so nothing was ever handed to the PCM ring
# -- but a 2 s sampler can only say "we did not see it", not "it never
# happened", and it cannot say why.  So: 1 s, and the moment a node goes busy,
# one snapshot of AudioFlinger taken *while the stream is live*, which is the
# only time its per-track state means anything.
#
# The PCM state names come straight from ALSA: open -> setup -> prepared ->
# running -> draining -> closed.  A music track that is actually playing sits
# in RUNNING; one that failed to start is stuck in open/prepared or goes
# straight back to closed.
snap() {
    s=$(cat "$A/state" 2>/dev/null)
    p=$(grep -s '^state' /proc/asound/card*/pcm*p/sub*/status 2>/dev/null |
        grep -v 'closed$' |
        sed 's#^/proc/asound/##; s#/status:state[[:space:]]*:[[:space:]]*#=#; s#^state[[:space:]]*:[[:space:]]*#?=#' |
        tr '\n' ' ')
    echo "adsp=$s usb=$(cat "$AUST/state" 2>/dev/null) adbd=$(getprop init.svc.adbd 2>/dev/null) audio=$(pidof audioserver 2>/dev/null | cut -d' ' -f1) pcm=${p:-none}"
}

# Deep snapshot.  Everything here is read while the stream exists, so the
# track list, the output's sample rate and the HAL's own counters line up.
audiosnap() {
    {
        sec "audio_snapshot t=$(up) why=$1"
        echo "-- cards --"
        cat /proc/asound/cards 2>/dev/null
        echo "-- hw_params (busy nodes) --"
        for f in /proc/asound/card*/pcm*p/sub*/hw_params; do
            [ -r "$f" ] || continue
            grep -q '^closed' "$f" 2>/dev/null && continue
            echo "$f:"; sed 's/^/    /' "$f" 2>/dev/null
        done
        echo "-- foreground --"
        dumpsys activity activities 2>/dev/null | grep -m3 -E 'mResumedActivity|mFocusedActivity'
        echo "-- stream volume / mode --"
        # A silent phone with a healthy PCM path is usually this: STREAM_MUSIC
        # at 0, or a headset/jack state that routed the mix elsewhere.
        dumpsys audio 2>&1 | grep -E 'STREAM_MUSIC|Muted|Current|Mode:|Ringing|Devices' | head -n 24
        echo "-- jack --"
        echo "h2w=$(cat /sys/class/switch/h2w/state 2>/dev/null) name=$(cat /sys/class/switch/h2w/name 2>/dev/null)"
        echo "-- AudioFlinger --"
        dumpsys media.audio_flinger 2>&1 | head -n 220
        echo "-- logcat (audio, last 120) --"
        logcat -d -v brief -t 400 2>/dev/null |
            grep -Ei 'audioflinger|audiopolicy|audio_hw|audiohal|tapan|adm_|asm_|afe_|MediaPlayer|AudioTrack|AwesomePlayer|NuPlayer|OMX|codec' |
            tail -n 120
        echo "-- dmesg tail --"
        dmesg 2>/dev/null | tail -n 60
    } >>"$R1" 2>&1
    chmod 0644 "$R1" 2>/dev/null
    kmsg "KCSNAP t=$(up) pcm=$(snap | sed 's/.*pcm=//') full copy at $R1"
}

kmsg "sampling start, 1 s, 10 min fast then 2 s for 20 min"
prev=$(snap)
lastbusy=0
esnaps=0
i=0
while [ $i -lt 1200 ]; do
    if [ $i -lt 600 ]; then sleep 1; else sleep 2; fi
    i=$((i+1))
    cur=$(snap)
    changed=0
    [ "$cur" != "$prev" ] && changed=1
    busy=0
    case "$cur" in *pcm=none*) ;; *) busy=1 ;; esac
    if [ $changed -eq 1 ]; then
        prev=$cur
        printf '<6>KCEVT t=%s %s\n' "$(up)" "$cur" >>$K 2>/dev/null
        printf '%s | %s\n' "$(up)" "$cur" >>"${R1}.ev" 2>/dev/null
        echo "$(up) | $cur" >>"$R1" 2>/dev/null
    elif [ $busy -eq 0 ]; then
        continue
    fi
    # Two moments are worth a deep snapshot: the first second of an episode
    # (something opened) and any later change while it is still busy (open ->
    # prepared -> running, which is what "playing" looks like).  Four per
    # episode, so a five-minute album does not turn the report into a dump.
    if [ $busy -eq 1 ] && [ $lastbusy -eq 0 ]; then
        esnaps=1
        audiosnap "episode start"
    elif [ $busy -eq 1 ] && [ $changed -eq 1 ] && [ $esnaps -lt 4 ]; then
        esnaps=$((esnaps+1))
        audiosnap "state change #$esnaps"
    fi
    [ $busy -eq 0 ] && esnaps=0
    lastbusy=$busy
done

# one last snapshot, so the file ends with where things settled
snap | sed "s/^/final@$(up) /" >>"$R1" 2>/dev/null
kmsg "sampling done up=$(up), report at $R1"
rm -f "$T" "$U" "$PIDF" 2>/dev/null
exit 0
