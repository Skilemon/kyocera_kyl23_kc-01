#!/system/bin/sh
#
# kcssr.sh -- stop a wcnss crash from taking the whole phone down.
#
# On a bad boot (dump 21_log.img, first boot record):
#
#   [ 24.226] Fatal error on the wcnss.  wconn_util_command_buff.c:576:Assertion 0 failed
#   [ 29.648] VOS BUG in hdd_wlan_re_init / kernel BUG at wlan_hdd_early_suspend.c:2344!
#   [ 34.239] apps_wcnss_reset_req interrupt detected!  restart_level = RELATED
#   [ 34.239] Kernel panic - not syncing:
#                 Subsystems have crashed 2 times in less than 40 seconds!
#
# The first crash is the firmware overrunning its own command buffer.  The
# second is not a second firmware fault: prima's watchdog notices the dead chip,
# calls hdd_wlan_re_init() before the subsystem is back, hits a BUG_ON, and then
# issues a reset of its own.  Two crashes inside forty seconds and the
# subsystem-restart governor panics the kernel.
#
# INDEPENDENT means "restart this subsystem and nothing else": wifi drops out
# for the session instead of the phone rebooting.  The attribute is
#   /sys/bus/msm_subsys/devices/subsysN/restart_level
#
# fix23 set it and the readback still said RELATED.  fix24/25/26 blamed the
# driver.  They were wrong: the shell line was
#       echo independent > .../restart_level 2>/tmp/kcssr.err
# and this device has no /tmp, so the second redirection failed, the whole
# command aborted before echo ever ran, and $? was 1 with an empty errno file.
# The write had never been attempted at all.  stderr now goes to /cache, which
# fix25 made world writable for exactly this kind of thing.

K=/dev/kmsg
L=/cache/kcssr.log
D=/sys/bus/msm_subsys/devices

say() {
    echo "$*" >> $L 2>/dev/null
}

put() {
    # $1 dir -- try the two spellings the driver has used, report which worked
    for s in independent INDEPENDENT; do
        echo "$s" > "$1/restart_level" 2>>/cache/kcssr.err
        rc=$?
        err=$(cat /cache/kcssr.err 2>/dev/null | tr '\n' ' ')
        now=$(cat "$1/restart_level" 2>/dev/null)
        say "  write '$s' rc=$rc err='$err' now='$now'"
        case "$now" in
            INDEPENDENT|independent) return 0 ;;
        esac
    done
    return 1
}

attempt() {
    found=0
    hit=0
    known=0

    for d in "$D"/subsys*; do
        [ -d "$d" ] || continue
        found=$((found + 1))
        fn=$(cat "$d/firmware_name" 2>/dev/null)
        cur=$(cat "$d/restart_level" 2>/dev/null)
        [ -n "$fn" ] && known=$((known + 1))

        case "$fn" in
            *wcnss*|*WCNSS*)
                hit=1
                if put "$d"; then
                    say "$(basename $d) fw=$fn was=$cur ok"
                    echo "KCSSR $(basename $d) fw=$fn was=$cur ok" > $K 2>/dev/null
                    return 0
                fi
                say "$(basename $d) fw=$fn was=$cur write failed"
                ;;
            *)
                [ "$1" = "all" ] &&
                    say "$(basename $d) fw=${fn:-?} level=${cur:-?}"
                ;;
        esac
    done

    if [ "$found" -eq 0 ]; then
        say "no $D/subsys* yet"
        return 1
    fi

    # No firmware_name attribute anywhere: we cannot tell which entry is the
    # wifi chip, so make every subsystem independent.  A modem or dsp crash
    # restarting on its own is survivable; the kernel panicking is not.
    if [ "$known" -eq 0 ]; then
        n=0
        for d in "$D"/subsys*; do
            [ -d "$d" ] || continue
            say "put $(basename $d) from $(cat $d/restart_level 2>/dev/null)"
            put "$d" && n=$((n + 1))
        done
        say "no firmware_name, set $n/$found to INDEPENDENT"
        echo "KCSSR no-fwname set $n/$found" > $K 2>/dev/null
        [ "$n" -gt 0 ] && return 0
        return 1
    fi

    [ "$hit" -eq 0 ] && say "no wcnss entry among $found"
    return 1
}

: > $L 2>/dev/null
: > /cache/kcssr.err 2>/dev/null
say "kcssr $(date)"

if attempt all; then
    say "done early"
    exit 0
fi

i=0
while [ $i -lt 12 ]; do
    sleep 3
    i=$((i + 1))
    if attempt quiet; then
        say "settled after $((i * 3))s"
        exit 0
    fi
done

say "gave up after 36s"
exit 0
