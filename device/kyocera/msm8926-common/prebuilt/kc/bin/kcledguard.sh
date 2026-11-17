#!/system/bin/sh
#
# kcledguard.sh -- keep the button backlight dark for the whole boot window,
# then hand the node to kcbtnled.
#
# History, because this file has been wrong twice:
#
#   fix75  blamed a DT collision (gpio-leds on GPIO 34 vs the camera's
#          CAM_AF_PWDM).  Wrong: the boot image's own DTB has no gpio-leds node
#          at all -- qcom,leds@a100 is "okay" and the button backlight is PMIC
#          MPP2 (qcom,led_mpp_2, default-state off), same as the factory build.
#
#   fix76  the dump caught "v=5 t=7.89 cam= btn=494": pidof kcbtnled was 494,
#          so kcbtnled was the writer, and it was starting in class core --
#          i.e. right on top of the boot animation.
#
#   fix77  moved kcbtnled to boot_completed, which only moved the flash: the
#          user now sees it "two blinks just after the boot animation ends".
#          The guard also released six seconds after boot_completed, and its
#          log stopped after the first catch, so kcbtnled had the node to
#          itself from about 60 s -- exactly when the flash shows up.
#
# fix78 stops trying to out-run it.  The guard owns the node for the first two
# minutes of uptime and nothing else may touch it.  Only then does it set
# sys.kcbtnled.late, which is what starts kcbtnled (see kyl23-extra.rc).  So
# there is no window in which two writers alternate, and no window in which
# kcbtnled is started but this is not holding the node.
#
# kcbtnled's own log says its start does not light anything -- the light comes
# from its key handler, "set 255 (key)" on input code 330 -- so starting it
# after the guard lets go is invisible.  kcbtnlednet.sh is the safety net: if
# this script dies, kcbtnled still gets started, just later.
#
B=/sys/class/leds/button-backlight/brightness
L1=/data/local/tmp/kc_led.log
L2=/cache/kc_led.log
HOLD=120

say() {
    for f in $L1 $L2; do echo "$*" >> $f 2>/dev/null; done
    echo "KLEDGUARD $*" > /dev/kmsg 2>/dev/null
}

now() { cut -d' ' -f1 /proc/uptime 2>/dev/null; }

# Heartbeat, file only so /dev/kmsg stays readable: fix78's log ended at the
# first "caught" with no phase-1 completion and no exit line, i.e. the script
# stopped existing and nothing said why.  A line every five seconds turns
# "the log just stops" into a timestamp.
beat() {
    for f in $L1 $L2; do echo "beat $*" >> $f 2>/dev/null; done
}

# Whatever happens, say why we stopped.  A silent exit is what made fix77's
# log useless: two lines, then nothing, with no way to tell whether the loop
# ended, the script was killed, or the writes started failing.
finish() {
    say "exit at t=$(now) reason=$1 corrected=$n"
    setprop sys.kcbtnled.late 1
    exit 0
}

n=0
prev=""

# /system is mounted by now but the LED class device appears when qpnp probes,
# ~1 s into the kernel boot.  Wait rather than give up: "no node yet" is not
# "no node".
i=0
while [ ! -e "$B" ] && [ "$i" -lt 600 ]; do
    sleep 0.05
    i=$((i + 1))
done
[ -e "$B" ] || { say "no $B after 30 s"; setprop sys.kcbtnled.late 1; exit 0; }

trap 'finish signal' INT TERM HUP

echo 0 >"$B" 2>/dev/null
prev=$(cat "$B" 2>/dev/null)
say "start t=$(now) v=$prev hold=${HOLD}s"

# Phase 1: 20 ms for the first 60 s -- that is the boot animation window and
# the few seconds after it, where the two blinks were seen.
i=0
while [ "$i" -lt 3000 ]; do
    v=$(cat "$B" 2>/dev/null)
    if [ -n "$v" ] && [ "$v" != "0" ]; then
        n=$((n + 1))
        [ "$n" -le 30 ] && [ "$v" != "$prev" ] && \
            say "caught v=$v t=$(now) cam=$(pidof qcamerasvr 2>/dev/null) btn=$(pidof kcbtnled 2>/dev/null)"
        echo 0 >"$B" 2>/dev/null
        prev=0
    fi
    i=$((i + 1))
    [ $((i % 250)) -eq 0 ] && beat "t=$(now) phase1 v=$(cat "$B" 2>/dev/null) n=$n"
    sleep 0.02
done
say "t=$(now) fast phase done, corrected=$n"

# Phase 2: 50 ms until HOLD seconds of uptime.  Nothing should write here; if
# something does, it is the framework (the lights HAL) rather than kcbtnled,
# and pidof button tells us which.
j=0
while :; do
    u=$(now | cut -d. -f1)
    [ -z "$u" ] && break
    [ "$u" -ge "$HOLD" ] && break
    v=$(cat "$B" 2>/dev/null)
    if [ -n "$v" ] && [ "$v" != "0" ]; then
        n=$((n + 1))
        [ "$n" -le 30 ] && say "caught v=$v t=$(now) (slow phase) btn=$(pidof kcbtnled 2>/dev/null)"
        echo 0 >"$B" 2>/dev/null
    fi
    j=$((j + 1))
    [ $((j % 100)) -eq 0 ] && beat "t=$(now) phase2 v=$(cat "$B" 2>/dev/null) n=$n"
    sleep 0.05
done

finish hold-${HOLD}s-complete
