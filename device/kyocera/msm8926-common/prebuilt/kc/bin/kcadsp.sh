#!/system/bin/sh
#
# kcadsp -- watch the ADSP come up and leave the evidence where a dump can see
# it.  It does NOT drive the load any more; the kernel does (patch
# kernel-patches/0003-adsp-loader-boot-from-kernel.patch, adsp-loader.c):
# trying to race init and audioserver from here was the mistake of fix24..fix66.
#
# Why the kernel owns it now:
#
#   * Every userspace hook available on this port runs late.  /firmware is
#     mounted at 4.7 s, post-fs-data burns another 1.2 s (e2fsck, kcboot,
#     kcfix, ...), so "on early-boot" fires at 5.99 s - 150 ms before init
#     starts audioserver and before the ASoC card has probed.  There is no
#     userspace stage early enough.
#   * adsp_loader_do() -> subsystem_get("adsp") -> pil_boot() -> 
#     request_firmware() needs a live ueventd and a mounted /firmware, but it
#     does not need Android: a workqueue retry from the loader driver covers
#     the whole window and prints every attempt, so one dump says whether the
#     blob is missing, whether the authentication was refused, or whether it
#     simply had not been tried yet.
#
# What this script is for now:
#
#   1. record the ADSP subsystem state over the first 20 s (by NAME - the
#      fix66 version polled subsys0, which is the *modem*, so it reported
#      "ONLINE after 1s" while the ADSP had never been touched at all);
#   2. copy the interesting part of dmesg to the kernel log, so the log
#      partition dump carries it (the /cache copy is unreadable: the dump tool
#      only keeps the first 20 MB of a 120 MB filesystem);
#   3. stay out of the load path, so the kernel log shows exactly one driver
#      behind every attempt.
#
# /dev/kmsg writes are the risk this script has to live with: a printf to
# /dev/kmsg can block on the console.  Everything below is emitted from one
# background child after the observation window, at most 24 short lines, so a
# block costs a sleeping child and never init.

L=/cache/kcadsp.log
D=/sys/bus/msm_subsys/devices
B=/sys/kernel/boot_adsp/boot

say() {
    echo "$*" >> $L 2>/dev/null
}

adsp_dev() {
    for d in $D/subsys*; do
        [ -d "$d" ] || continue
        if [ "$(cat $d/name 2>/dev/null)" = "adsp" ]; then
            echo "$d"
            return 0
        fi
    done
    return 1
}

: > $L 2>/dev/null
say "=== kcadsp observe $(date) uptime $(cat /proc/uptime 2>/dev/null)"

for d in $D/subsys*; do
    [ -d "$d" ] || continue
    say "$(basename $d) name=$(cat $d/name 2>/dev/null) state=$(cat $d/state 2>/dev/null) level=$(cat $d/restart_level 2>/dev/null) fw=$(cat $d/firmware_name 2>/dev/null)"
done

if [ -d /sys/kernel/boot_adsp ]; then
    say "boot_adsp present: $(ls /sys/kernel/boot_adsp 2>/dev/null | tr '\n' ' ')"
else
    say "boot_adsp MISSING"
fi
say "boot attr: $(ls -l $B 2>/dev/null)"

for d in /firmware/image /firmware /system/etc/firmware /vendor/firmware; do
    n=$(ls "$d" 2>/dev/null | grep -ci '^adsp')
    [ "$n" = "0" ] || say "fw $d: $n adsp* files [$(ls "$d" 2>/dev/null | grep -i '^adsp' | tr '\n' ' ')]"
done

A=$(adsp_dev)
say "adsp subsystem: ${A:-<none>} state=$(cat $A/state 2>/dev/null)"

i=0
while [ $i -lt 20 ]; do
    st=$(cat $A/state 2>/dev/null)
    case "$st" in
        ONLINE)
            say "adsp ONLINE at uptime $(cat /proc/uptime 2>/dev/null) (poll $i)"
            break
            ;;
    esac
    sleep 1
    i=$((i + 1))
done

st=$(cat $A/state 2>/dev/null)
say "adsp final state=${st:-<none>} after ${i}s"

say "cards: $(cat /proc/asound/cards 2>/dev/null | tr '\n' '|')"
say "slimbus: $(ls /sys/bus/slimbus/devices 2>/dev/null | tr '\n' ' ')"
say "loader: $(dmesg 2>/dev/null | grep -c 'adsp-loader:') adsp-loader lines"

# ---- why does audioserver quit? -------------------------------------------
# It exits with status 0 about a second after every start, and the reason is
# only in logcat: ALOG goes to logd, never to the kernel log, and the log
# partition dump therefore never carried it.  KCLED already dumps logcat to
# /cache/lc.txt, but /cache does not survive the dump, so copy the audio part
# into the kernel log while we are here.
log_src=/cache/lc.txt
if [ ! -s "$log_src" ]; then
    log_src=/cache/kcadsp-lc.txt
    logcat -d -v brief -t 4000 > $log_src 2>/dev/null
fi
say "logcat $log_src: $(grep -ic audio "$log_src" 2>/dev/null) audio lines"

# ---- one bounded report into the kernel log -------------------------------
{
    printf '<6>KCADSP adsp=%s state=%s uptime=%s\n' \
        "${A:-none}" "${st:-none}" "$(cat /proc/uptime 2>/dev/null | cut -d' ' -f1)" >>/dev/kmsg 2>/dev/null
    for d in $D/subsys*; do
        [ -d "$d" ] || continue
        printf '<6>KCADSP %s name=%s state=%s\n' "$(basename $d)" \
            "$(cat $d/name 2>/dev/null)" "$(cat $d/state 2>/dev/null)" >>/dev/kmsg 2>/dev/null
    done
    dmesg 2>/dev/null | grep -E 'adsp-loader:|pil-|pil_|APR|apr' | tail -n 12 |
        while IFS= read -r l; do
            printf '<6>KCADSP | %s\n' "$l" >>/dev/kmsg 2>/dev/null
        done
    grep -i -E 'audio|AudioFlinger|AudioPolicy|HAL|tapan' "$log_src" 2>/dev/null | tail -n 20 |
        while IFS= read -r l; do
            printf '<6>KCLOG %s\n' "$l" >>/dev/kmsg 2>/dev/null
        done
} &

exit 0
