#!/system/bin/sh
#
# kcadsp -- boot the ADSP, and leave the evidence where a dump can see it.
#
# Why it still writes /sys/kernel/boot_adsp/boot itself:
#
#   fix67 moved the trigger into the kernel (kernel-patches/0003) and made this
#   script a pure observer.  The dump from that build proves the idea failed in
#   practice for a boring reason: the kernel it needs was never flashed.  All
#   three boots in 21_log.img are "#23 Mon Nov 16 13:40:03", none is "#24", and
#   the newest one has no pil_boot() at all -- nothing ever called
#   subsystem_get("adsp").  audioserver then exits every 5 s, 32 times.
#
#   So the userspace trigger has to stay until a dump shows a kernel newer than
#   the one that shipped the retry.  The kernel path (first attempt 5 s, then
#   every 1 s, 60 tries) and this one are safe together: subsystem_get() is
#   refcounted and adsp_loader_do() returns early once priv->pil_h is set.
#
# Timing, measured: the load itself takes ~0.5 s (pil "loading from" 5.516 ->
# "Q6 Is Up" 6.020) and audioserver starts at 6.06 s.  The rc now asks at
# post-fs-data (4.70 s).  This script runs later, at class_start core, and is
# the retry for when that first ask lost or was refused.
#
# Everything goes to /dev/kmsg from the foreground: init SIGKILLs the process
# group of a oneshot service as soon as the script exits, so the background
# child the fix67 version used for its report was dead before it could write a
# single line -- which is why that dump has no KCADSP line in it.

L=/cache/kcadsp.log
D=/sys/bus/msm_subsys/devices
B=/sys/kernel/boot_adsp/boot
K=/dev/kmsg

# The kernel that has the in-driver retry.  Printed on every boot so the next
# dump answers "did the boot partition actually get written?" without guessing:
# if "kernel=" here is older than this string, the flash did not take and
# nothing else in the log means what it looks like.
EXPECT="#25"

say() { echo "$*" >> $L 2>/dev/null; }
kmsg() { printf '<6>KCADSP %s\n' "$*" >> $K 2>/dev/null; }
up() { cut -d' ' -f1 /proc/uptime 2>/dev/null; }

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

A=$(adsp_dev)
st=$(cat $A/state 2>/dev/null)

kmsg "start up=$(up) state=${st:-none} kernel=$(sed -n 's/.*\(#[0-9][0-9]*\) SMP.*/\1/p' /proc/version 2>/dev/null) expect=$EXPECT"
kmsg "dev=${A:-none} fw_adsp=$(ls /firmware/image 2>/dev/null | grep -ic '^adsp') bootattr=$([ -e $B ] && echo yes || echo no)"
say "=== kcadsp $(date) up=$(up) state=${st:-none}"

# ---- ask for the boot, repeatedly -----------------------------------------
# The write blocks in request_firmware() for as long as the load takes, so the
# state read that follows it is already the post-load one.
tries=0
i=0
while [ $i -lt 10 ]; do
    st=$(cat $A/state 2>/dev/null)
    [ "$st" = "ONLINE" ] && break

    if [ ! -e $B ]; then
        kmsg "no $B, cannot boot the ADSP"
        break
    fi

    tries=$((tries + 1))
    echo 1 > $B 2>/dev/null
    rc=$?
    st=$(cat $A/state 2>/dev/null)
    kmsg "boot #$tries rc=$rc state=${st:-none} up=$(up)"
    say "boot #$tries rc=$rc state=${st:-none} up=$(up)"

    [ "$st" = "ONLINE" ] && break
    sleep 2
    i=$((i + 1))
done

st=$(cat $A/state 2>/dev/null)
kmsg "final state=${st:-none} tries=$tries up=$(up)"

# ---- what the kernel and the DSP had to say -------------------------------
for d in $D/subsys*; do
    [ -d "$d" ] || continue
    kmsg "$(basename $d) $(cat $d/name 2>/dev/null) $(cat $d/state 2>/dev/null)"
done

dmesg 2>/dev/null | grep -E 'adsp-loader:|pil-q6v5-lpass|apr_tal|Q6 Is Up' |
    tail -n 12 | while IFS= read -r l; do kmsg "| $l"; done

# audioserver dies or survives on this: keep the length bounded, it is one line
kmsg "cards=$(cat /proc/asound/cards 2>/dev/null | tr '\n' '|')"
kmsg "slim=$(ls /sys/bus/slimbus/devices 2>/dev/null | tr '\n' ',')"
kmsg "audioserver_exits=$(dmesg 2>/dev/null | grep -c "audioserver') exited")"

exit 0
