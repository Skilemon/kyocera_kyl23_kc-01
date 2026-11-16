#!/system/bin/sh
#
# kcadsp -- ask for the ADSP early, then leave ONE SMALL REPORT that says what
#           happened.  Two copies, on purpose:
#
#             /data/local/tmp/kcaudio.txt   (pull over adb: a few tens of KB)
#             /dev/kmsg                     (first 120 lines, so a dump of the
#                                            20 MB "log" partition carries it)
#
#           Runs as the kcadsp oneshot service at class_start core.  It can also
#           be run by hand on a live device, no flashing needed:
#
#               adb push kc_audio.sh /data/local/tmp/
#               adb shell su -c 'sh /data/local/tmp/kc_audio.sh'
#               adb shell cat /data/local/tmp/kcaudio.txt
#
# Why not just read the log partition:
#
#   /dev/block/bootdevice/by-name/log is a 20 MB v2.0.0 "DBGC" store with three
#   reused slots.  The writer drops lines (a 640 s session leaves ~1100 of tens
#   of thousands) and "Linux version" is one of the droppable ones, so absence
#   of a build string there proves nothing.  That is why the report is pushed
#   into kmsg with its own KCRPT tag: it does not depend on which lines the
#   store happened to keep.
#
#   The report starts with the kernel that is actually running, so no
#   conclusion can be built on a build that is not there.

R1=/data/local/tmp/kcaudio.txt
R2=/cache/kcaudio.txt
T=$R1.tmp
D=/sys/bus/msm_subsys/devices
B=/sys/kernel/boot_adsp/boot
K=/dev/kmsg
LOGDEV=/dev/block/bootdevice/by-name/log
[ -e "$LOGDEV" ] || LOGDEV=/dev/block/platform/msm_sdcc.1/by-name/log

up() { cut -d' ' -f1 /proc/uptime 2>/dev/null; }
sec() { echo; echo "===== $* ====="; }
kmsg() { printf '<6>KCADSP %s\n' "$*" >>$K 2>/dev/null; }
st_of() { [ -n "$1" ] && cat "$1/state" 2>/dev/null; }

# ---- body ------------------------------------------------------------------
{
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

    # ---- did anything actually go through a PCM? ---------------------------
    # Run this while a sound is playing and the difference is obvious:
    # state RUNNING + a non-zero hw_ptr means the DSP is being fed.
    sec pcm
    for p in /proc/asound/card*/pcm*p/sub*/status; do
        [ -r "$p" ] || continue
        echo "$p"
        sed 's/^/    /' "$p" 2>/dev/null | head -n 8
    done
    echo "-- datapath --"
    dmesg 2>/dev/null | grep -Ei 'msm_pcm|msm-dai|afe_|adm_|asm_|dapm|slimbus|SLIM' | tail -n 30

    sec audioflinger
    dumpsys media.audio_flinger 2>/dev/null |
        grep -Ei 'output thread|input thread|standby|sample rate|format|channel|card|hal' |
        head -n 25

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
} >"$T" 2>&1

# ---- summary first, so a truncated copy is still useful --------------------
A=""
for d in $D/subsys*; do
    [ -d "$d" ] || continue
    [ "$(cat $d/name 2>/dev/null)" = adsp ] && A=$d
done
lrec=$(od -An -tu4 -j 8 -N 4 "$LOGDEV" 2>/dev/null | tr -d ' ')
{
    echo "=== SUMMARY ==="
    echo "version: $(cat /proc/version)"
    echo "uptime:  $(up)  android: $(getprop ro.build.version.release 2>/dev/null) $(getprop ro.build.type 2>/dev/null)"
    echo "adsp:    state=$(st_of "$A") dev=${A:-MISSING} asks=$tries"
    echo "card:    $(cat /proc/asound/cards 2>/dev/null | tr '\n' '|')"
    echo "audio:   audioserver start/exit = $(dmesg 2>/dev/null | grep -c "Starting service 'audioserver'") / $(dmesg 2>/dev/null | grep -c "audioserver') exited")"
    echo "logstore: magic=$(dd if="$LOGDEV" bs=1 count=7 2>/dev/null) records=${lrec:-?}"
    cat "$T"
} >"$R1" 2>/dev/null

rm -f "$T"

if [ -d /cache ]; then
    cp -f "$R1" "$R2" 2>/dev/null && chmod 0644 "$R2" 2>/dev/null
fi
chmod 0644 "$R1" 2>/dev/null

# ---- mirror into kmsg: first 120 lines, that is all a 20 MB dump needs -----
n=0
while IFS= read -r l; do
    n=$((n+1))
    [ $n -gt 120 ] && { kmsg "KCRPT| ... report truncated, full copy in $R1"; break; }
    case "$l" in
        "====="*) kmsg "KCRPT| $l" ;;
        *)        kmsg "KCRPT| $(printf '%s' "$l" | cut -c1-190)" ;;
    esac
done <"$R1"

kmsg "report $(wc -l <"$R1" 2>/dev/null) lines: $R1 (also in kmsg as KCRPT)"

exit 0
