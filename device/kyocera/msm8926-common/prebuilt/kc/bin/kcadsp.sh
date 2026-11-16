#!/system/bin/sh
#
# kcadsp -- the one thing that runs as root on this device without adb.
#
# It does three jobs, in this order, and none of them needs a terminal, a
# mounted /data from a host, or USB:
#
#   1. bring USB up itself (the framework never manages it on this port);
#   2. leave a small report where any file manager can read it;
#   3. keep sampling for ten minutes so a sound played *later* is recorded.
#
# Where the report goes -- all three, because only one of them may be reachable:
#
#   /data/media/0/kcaudio.txt     internal storage, 0644: file manager, MTP,
#                                 recovery, anything can read it
#   /data/local/tmp/kcaudio.txt   0644, the old path, still fine
#   /dev/kmsg                     as KCRPT, so a dump of the 20 MB log
#                                 partition carries it too
#
# Why the log partition alone is not enough: it is a v2.0.0 "DBGC" store with
# three reused slots that drops lines (a 640 s session leaves ~1100 of tens of
# thousands), and "Linux version" is droppable.  Absence there proves nothing.
# The KCRPT lines do not care which lines the store kept, but a *fresh* dump of
# it only contains the session before last, so the file is the primary channel.
#
# USB: this kernel's android gadget has f_adb (/dev/android_adb) and f_mtp, and
# the adbd in the ramdisk knows both /dev/android_adb and /dev/usb-ffs/adb/ep0,
# so adb is reachable -- but only if somebody sets "functions".  init.qcom.rc
# has stanzas for every value the framework can write, and the framework writes
# "mtp" (persist.sys.usb.config in default.prop).  If that stanza ever fails --
# or the value in /data is something with no stanza at all, e.g. "none" -- the
# gadget stays disabled and the phone looks like it is charging from a wall
# charger.  So: try mtp,adb, then adb, then mtp, and record what each one did.

R1=/data/media/0/kcaudio.txt
[ -d /data/media/0 ] || R1=/data/local/tmp/kcaudio.txt
R2=/data/local/tmp/kcaudio.txt
R3=/cache/kcaudio.txt
T=/data/local/tmp/.kcaudio.$$.tmp
U=/dev/.kcusb.$$.tmp
UB=/dev/.kcusb.body
D=/sys/bus/msm_subsys/devices
B=/sys/kernel/boot_adsp/boot
AUST=/sys/class/android_usb/android0
K=/dev/kmsg
PIDF=/data/local/tmp/kcaudio.pid
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

{
    sec usb
    echo "initial: $USB0"
    echo "props:   sys.usb.config=$(getprop sys.usb.config 2>/dev/null) sys.usb.state=$(getprop sys.usb.state 2>/dev/null) persist=$(getprop persist.sys.usb.config 2>/dev/null) configfs=$(getprop sys.usb.configfs 2>/dev/null)"
    echo "nodes:   $(ls /dev/android_adb* 2>/dev/null | tr '\n' ' ')"
    echo "udc:     $(ls /sys/class/udc 2>/dev/null | tr '\n' ' ')"
    if [ ! -d "$AUST" ]; then
        echo "no $AUST -- the gadget never registered, this is a kernel problem"
    elif [ "$(cat "$AUST/state" 2>/dev/null)" = CONFIGURED ]; then
        echo "already CONFIGURED, leaving it alone"
    else
        echo "-- bring-up --"
        usbtry "mtp,adb" 0482 0a27 || usbtry "adb" 18d1 4ee7 || usbtry "mtp" 0482 0a28
        echo "after:   $(usbsnap)"
    fi
    if [ -e /dev/android_adb ]; then
        case "$(getprop init.svc.adbd 2>/dev/null)" in
            running) ;;
            *) setprop ctl.start adbd 2>/dev/null; sleep 1
               echo "adbd start -> $(getprop init.svc.adbd 2>/dev/null)" ;;
        esac
    fi
    echo "-- dmesg usb --"
    dmesg 2>/dev/null | grep -Ei 'android_usb|msm_otg|msm_hsusb|udc|usb_bam|android_work' | tail -n 25
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

    sec pcm
    for p in /proc/asound/card*/pcm*p/sub*/status; do
        [ -r "$p" ] || continue
        echo "$p"
        sed 's/^/    /' "$p" 2>/dev/null | head -n 8
    done
    echo "-- datapath --"
    dmesg 2>/dev/null | grep -Ei 'msm_pcm|msm-dai|afe_|adm_|asm_|dapm' | tail -n 20

    sec logcat_audio
    logcat -d -v brief -t 400 2>/dev/null |
        grep -Ei 'audioflinger|audiopolicy|audio_hw|audiohal|tapan|adm_|asm_|afe_|usb' |
        tail -n 40
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
        echo "card:    $(cat /proc/asound/cards 2>/dev/null | tr '\n' '|')"
        echo "audio:   start/exit = $(dmesg 2>/dev/null | grep -c "Starting service 'audioserver'") / $(dmesg 2>/dev/null | grep -c "audioserver') exited")"
        echo "logstore: magic=$(dd if="$LOGDEV" bs=1 count=7 2>/dev/null) records=${lrec:-?}"
        cat "$T"
        if [ -s "${R1}.ev" ]; then
            sec events
            tail -n 200 "${R1}.ev"
        fi
    } >"$R1" 2>/dev/null
    chmod 0644 "$R1" 2>/dev/null
    chown media_rw media_rw "$R1" 2>/dev/null
    cp -f "$R1" "$R2" 2>/dev/null && chmod 0644 "$R2" 2>/dev/null
    [ -d /cache ] && cp -f "$R1" "$R3" 2>/dev/null && chmod 0644 "$R3" 2>/dev/null
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

# ---- 6. sample for thirty minutes ------------------------------------------
# Something has to be running at the moment a sound is played, or the PCM
# status is always "closed".  Thirty minutes, because the useful test is
# "boot it, play something, reboot" and nobody does that in two minutes.  Every change is appended to the report and sent
# to kmsg as KCEVT, so a dump taken after a reboot still shows the shape.
snap() {
    s=none
    for d in $D/subsys*; do
        [ -d "$d" ] || continue
        [ "$(cat $d/name 2>/dev/null)" = adsp ] && s=$(cat "$d/state" 2>/dev/null)
    done
    p=
    for f in /proc/asound/card*/pcm*p/sub*/status; do
        [ -r "$f" ] || continue
        x=$(sed -n 's/^state[[:space:]]*:[[:space:]]*//p' "$f" 2>/dev/null | head -1)
        [ -n "$x" ] && [ "$x" != closed ] &&
            p="$p $(printf '%s' "$f" | sed 's#/proc/asound/##; s#/status$##')=$x"
    done
    echo "adsp=$s usb=$(cat "$AUST/state" 2>/dev/null) adbd=$(getprop init.svc.adbd 2>/dev/null) audio=$(pidof audioserver 2>/dev/null | cut -d' ' -f1) pcm=${p:-none}"
}

kmsg "sampling start, 30 min window, changes go out as KCEVT"
prev=$(snap)
i=0
while [ $i -lt 900 ]; do
    sleep 2
    i=$((i+1))
    cur=$(snap)
    [ "$cur" = "$prev" ] && continue
    prev=$cur
    printf '<6>KCEVT t=%s %s\n' "$(up)" "$cur" >>$K 2>/dev/null
    printf '%s | %s\n' "$(up)" "$cur" >>"${R1}.ev" 2>/dev/null
    echo "$(up) | $cur" >>"$R1" 2>/dev/null
done

# one last snapshot, so the file ends with where things settled
snap | sed "s/^/final@$(up) /" >>"$R1" 2>/dev/null
kmsg "sampling done up=$(up), report at $R1"
rm -f "$T" "$U" "$PIDF" 2>/dev/null
exit 0
