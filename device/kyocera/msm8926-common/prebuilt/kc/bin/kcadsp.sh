#!/system/bin/sh
#
# kcadsp -- bring the ADSP up.  This is the keystone of everything else.
#
# The ADSP (LPASS/QDSP6) never loads on this port.  Consequences, all observed
# in the dumps:
#
#   * audioserver reaches audio_hw_primary: adev_open: enter and then blocks
#     forever.  The ASoC card (msm8226-asoc-tapan) is still deferred because it
#     waits for APR, and APR lives in the ADSP.  media.audio_policy therefore
#     never gets published, system_server sits in
#         ServiceManager: Waiting for service media.audio_policy...
#     for about 150 seconds, and that is the whole reason boot takes minutes.
#   * no sound at all (no card, no codec, no calibration).
#   * SLIMBUS is NGSLIM: the bus is driven by a framer inside the ADSP, so the
#     codec can never enumerate.
#
# fix24 assumed the loader driver had failed to probe because the DT property
# qcom,adsp-state has length 0.  That was wrong: /sys/kernel/boot_adsp exists,
# so the driver did probe and did create its sysfs node.  What never happened
# is anybody writing to it.
#
# fix25/26 asked for the boot and then hung: both scripts mirrored their output
# to /dev/kmsg, and a write to /dev/kmsg blocks once the kernel ring buffer is
# full - which on this phone it always is.  So they died on their own first log
# line and never reached the interesting part.  Nothing here writes to /dev/kmsg.
#
# Two ways in are tried:
#   1. /sys/kernel/boot_adsp/boot   -> adsp_loader_do() -> pil_boot("adsp")
#   2. /dev/subsys_adsp              -> subsystem_get("adsp") -> pil_boot("adsp")
# Both are started in a child: a pil_boot that fails can sit in the firmware
# loader for a long time and must not stall init.

L=/cache/kcadsp.log
D=/sys/bus/msm_subsys/devices
E=/cache/kcadsp.err

say() {
    echo "$*" >> $L 2>/dev/null
}

: > $E 2>/dev/null
say "" 
say "=== kcadsp run $(date) uptime $(cat /proc/uptime 2>/dev/null)"

for d in $D/subsys*; do
    [ -d "$d" ] || continue
    say "$(basename $d) name=$(cat $d/name 2>/dev/null) state=$(cat $d/state 2>/dev/null) level=$(cat $d/restart_level 2>/dev/null) fw=$(cat $d/firmware_name 2>/dev/null)"
done

# ---- what the loader driver built ----------------------------------------
if [ -d /sys/kernel/boot_adsp ]; then
    say "boot_adsp present: $(ls /sys/kernel/boot_adsp 2>/dev/null | tr '\n' ' ')"
else
    say "boot_adsp MISSING"
fi
B=/sys/kernel/boot_adsp/boot
[ -e "$B" ] && say "boot attr: exists mode=$(ls -ld $B 2>/dev/null | cut -c1-10)"

# ---- what the device tree says --------------------------------------------
P=/proc/device-tree/soc/qcom,msm-adsp-loader
if [ -d "$P" ]; then
    say "dt adsp-loader present: $(ls $P 2>/dev/null | tr '\n' ' ')"
    for f in "$P"/*; do
        say "  dt $(basename $f) size=$(wc -c < "$f" 2>/dev/null)"
    done
else
    say "dt adsp-loader node MISSING"
fi

# ---- try to boot it -------------------------------------------------------
try_boot() {
    [ -e "$B" ] || return 1
    ( echo 1 > "$B" ) 2>>$E &
    bg=$!
    i=0
    while [ $i -lt 12 ]; do
        sleep 1
        st=$(cat $D/subsys0/state 2>/dev/null)
        case "$st" in
            ONLINE) say "adsp ONLINE after ${i}s (echo 1 > boot)"; return 0 ;;
        esac
        i=$((i + 1))
    done
    say "adsp still $(cat $D/subsys0/state 2>/dev/null) after 12s, err=[$(cat $E 2>/dev/null | tr '\n' ' ')]"
    return 1
}

if try_boot; then
    :
else
    # second route: opening the subsystem device runs pil_boot() itself
    if [ -e /dev/subsys_adsp ]; then
        ( exec 3</dev/subsys_adsp ) 2>>$E &
        bg=$!
        i=0
        while [ $i -lt 8 ]; do
            sleep 1
            st=$(cat $D/subsys0/state 2>/dev/null)
            case "$st" in
                ONLINE) say "adsp ONLINE after ${i}s (subsys_adsp)"; break ;;
            esac
            i=$((i + 1))
        done
        kill $bg 2>/dev/null
        say "after subsys_adsp: state=$(cat $D/subsys0/state 2>/dev/null) err=[$(cat $E 2>/dev/null | tr '\n' ' ')]"
    fi
fi

say "final adsp state=$(cat $D/subsys0/state 2>/dev/null)"
say "cards: $(cat /proc/asound/cards 2>/dev/null | tr '\n' '|')"
say "slimbus: $(ls /sys/bus/slimbus/devices 2>/dev/null | tr '\n' ' ')"
say "--- dmesg (adsp/pil/apr/slim/tapan/sound)"
dmesg 2>/dev/null | grep -i -E "adsp|pil_|pil-|apr|slimbus|slim|tapan|sound|asoc|q6" | tail -n 60 | while IFS= read -r l; do say "  $l"; done
say "done"
exit 0
