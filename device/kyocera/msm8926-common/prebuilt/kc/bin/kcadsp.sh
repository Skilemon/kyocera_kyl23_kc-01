#!/system/bin/sh
#
# kcadsp -- ask for the ADSP early, then leave ONE SMALL FILE that says what
#           happened.  Runs as the kcadsp oneshot service at class_start core,
#           and can also be run by hand on a live device:
#
#               adb push kc_audio.sh /data/local/tmp/
#               adb shell su -c 'sh /data/local/tmp/kc_audio.sh'
#               adb shell cat /data/local/tmp/kcaudio.txt
#
# Why a file and not the log partition:
#
#   /dev/block/bootdevice/by-name/log is a 20 MB v2.0.0 "DBGC" store with three
#   fixed slots.  A slot is rewritten whole, the writer keeps only a subset of
#   the kernel lines (a 640 s session leaves ~1100 of them, out of tens of
#   thousands), and a slot only appears in a dump once it has been completed --
#   so the session the device is running right now is usually not in it at all.
#   "Linux version" is one of the lines that can be dropped.  Verdict: absence
#   from that partition proves nothing and must never be used to judge the build
#   that is running.
#
#   This file is a few tens of KB, so it survives a slow link, can be read on
#   screen, or photographed.  It starts with the kernel that is actually
#   running, so no conclusion can be built on a build that is not there.

R1=/data/local/tmp/kcaudio.txt
R2=/cache/kcaudio.txt
D=/sys/bus/msm_subsys/devices
B=/sys/kernel/boot_adsp/boot
K=/dev/kmsg
LOGDEV=/dev/block/bootdevice/by-name/log
[ -e "$LOGDEV" ] || LOGDEV=/dev/block/platform/msm_sdcc.1/by-name/log

up() { cut -d' ' -f1 /proc/uptime 2>/dev/null; }
sec() { echo; echo "===== $* ====="; }
kmsg() { printf '<6>KCADSP %s\n' "$*" >>$K 2>/dev/null; }
st_of() { [ -n "$1" ] && cat "$1/state" 2>/dev/null; }

{
    echo "kcadsp report  uptime=$(up)"
    echo "version: $(cat /proc/version)"
    echo "cmdline: $(cat /proc/cmdline)"

    sec subsys
    for d in $D/subsys*; do
        [ -d "$d" ] || continue
        echo "$(basename $d) name=$(cat $d/name 2>/dev/null) state=$(cat $d/state 2>/dev/null)"
    done

    # ---- ask for the boot --------------------------------------------------
    A=""
    for d in $D/subsys*; do
        [ -d "$d" ] || continue
        [ "$(cat $d/name 2>/dev/null)" = adsp ] && A=$d
    done
    sec boot
    echo "dev=${A:-MISSING} sysfs_boot=$([ -e $B ] && echo yes || echo no)"
    echo "fw adsp files: $(ls /firmware/image 2>/dev/null | grep -ic '^adsp')"
    echo "fw sample: $(ls /firmware/image 2>/dev/null | grep -i '^adsp' | tr '\n' ' ')"
    i=0
    tries=0
    while [ $i -lt 10 ]; do
        st=$(st_of "$A")
        [ "$st" = ONLINE ] && break
        [ -e $B ] || { echo "no $B -- cannot ask"; break; }
        tries=$((tries+1))
        echo 1 >$B 2>/dev/null
        rc=$?
        echo "ask #$tries rc=$rc state=$(st_of "$A") up=$(up)"
        sleep 2
        i=$((i+1))
    done
    echo "final: state=$(st_of "$A") asks=$tries up=$(up)"

    # ---- kernel side -------------------------------------------------------
    sec kernel
    dmesg 2>/dev/null | grep -E 'adsp-loader:' | tail -n 25
    echo "-- pil --"
    dmesg 2>/dev/null | grep -E 'pil-q6v5-lpass|pil_pronto|subsystem_restart|subsys' | tail -n 15
    echo "-- apr --"
    dmesg 2>/dev/null | grep -E 'apr_tal|APR:|apr_|Q6 Is Up|adsp not up' | tail -n 20
    echo "-- audio --"
    dmesg 2>/dev/null | grep -Ei 'audioserver|AudioFlinger|tapan|asoc|slimbus|sound\.' | tail -n 25

    # ---- audio stack -------------------------------------------------------
    sec audio
    echo "cards: $(cat /proc/asound/cards 2>/dev/null | tr '\n' '|')"
    echo "pcm:   $(cat /proc/asound/pcm 2>/dev/null | head -n 8 | tr '\n' '|')"
    echo "slim:  $(ls /sys/bus/slimbus/devices 2>/dev/null | tr '\n' ',')"
    echo "audioserver start/exit: $(dmesg 2>/dev/null | grep -c "Starting service 'audioserver'") / $(dmesg 2>/dev/null | grep -c "audioserver') exited")"
    dmesg 2>/dev/null | grep -E 'audioserver' | tail -n 10

    sec logcat_audio
    logcat -d -v brief -t 500 2>/dev/null |
        grep -Ei 'audioflinger|audiopolicy|audio_hw|audiohal|tapan|adm_|asm_|afe_' |
        tail -n 40

    # KCLED keeps a logcat copy under /cache; cheap to peek, bounded on purpose
    for f in /cache/lc.txt /cache/kcadsp.log; do
        [ -r "$f" ] || continue
        echo "-- $f ($(wc -c <"$f" 2>/dev/null) bytes) --"
        tail -n 40 "$f" 2>/dev/null | cut -c1-200
    done

    # ---- is the log store even tracking this boot? -------------------------
    sec logstore
    if [ -r "$LOGDEV" ]; then
        echo "header magic: $(dd if=$LOGDEV bs=1 count=7 2>/dev/null)"
        echo "record count: $(od -An -tu4 -j 8 -N 4 $LOGDEV 2>/dev/null | tr -d ' ')"
    else
        echo "log device not readable"
    fi
} >"$R1" 2>&1

# a second copy where recovery/DL tooling usually looks first
if [ -d /cache ]; then
    cp -f "$R1" "$R2" 2>/dev/null && chmod 0644 "$R2" 2>/dev/null
fi
chmod 0644 "$R1" 2>/dev/null

kmsg "report $(wc -l <"$R1" 2>/dev/null) lines: $R1"
kmsg "version=$(cat /proc/version | cut -c1-42) adsp=$(st_of "$A") cards=$(cat /proc/asound/cards 2>/dev/null | tr '\n' ' ')"

exit 0
