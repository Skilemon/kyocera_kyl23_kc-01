#!/system/bin/sh
#
# kcledguard.sh -- hold the button backlight at 0 across the boot animation,
# and write down every value that somebody else tried to set.
#
# Why: with fix74/75 the keys flash twice in the second or two before the boot
# animation.  The first guess (section 36.4) was a DT collision -- a gpio-leds
# node on GPIO 34 fighting the camera's CAM_AF_PWDM -- and that guess is wrong.
# The boot image's own DTB has no gpio-leds node at all: qcom,leds@a100 is
# "okay" and the button backlight is PMIC MPP2 (qcom,led_mpp_2,
# linux,name="button-backlight", default-state off), exactly like the factory
# build.  So the flashing comes from software writing brightness, not from the
# camera driving a shared line, and there are only three writers in this ROM:
# kcbtnled (our daemon, level 255 for 5 s at start), the framework's lights HAL
# (dead: lights.default.so fails to load, see section 37), and the kernel's
# default-state.
#
# This cannot say *who* wrote, so it records when: a timestamped line per
# transition, at 20 ms resolution through the boot window, in three places
# (/data/local/tmp survives to the next boot; /cache is dumped; kmsg is the
# one that survives a crash).  The next dump then says whether the flash is
# kcbtnled's 5 s light, two short writes from somewhere else, or the panel
# backlight rather than the keys.
#
# It also holds the node at 0 the whole time, so the flash is not visible in
# the meantime.  Cost: for the first four minutes touching the keys does not
# light them; after that this exits and kcbtnled owns the node again.
#
B=/sys/class/leds/button-backlight/brightness
L1=/data/local/tmp/kc_led.log
L2=/cache/kc_led.log

say() {
    for f in $L1 $L2; do echo "$*" >> $f 2>/dev/null; done
    echo "KLEDGUARD $*" > /dev/kmsg 2>/dev/null
}

now() { cut -d' ' -f1 /proc/uptime 2>/dev/null; }

# /system is mounted by now but the LED class device appears when qpnp probes,
# which is ~1 s into the kernel boot -- long before init gets here.  Still, wait
# rather than give up: "no node at this instant" is not "no node".
i=0
while [ ! -e "$B" ] && [ "$i" -lt 600 ]; do
    sleep 0.05
    i=$((i + 1))
done
[ -e "$B" ] || { say "no $B after 30 s"; exit 0; }

echo 0 >"$B" 2>/dev/null
prev=$(cat "$B" 2>/dev/null)
say "start t=$(now) v=$prev"

# 45 s at 20 ms (the boot animation window), then 200 ms until four minutes.
# Two loops rather than one with a variable sleep: this shell has no
# sub-second arithmetic worth trusting.
#
# fix77: kcbtnled no longer starts in class core (that was the flash -- the
# fix76 dump caught v=5 at 7.89 s with pidof kcbtnled = 494), so this no longer
# has to fight it for the whole boot.  Instead it yields the moment the
# framework is up: after boot_completed the keys belong to kcbtnled, and
# holding the node at 0 past that would just look like broken key backlight.
n=0
i=0
while [ "$i" -lt 2250 ]; do
    v=$(cat "$B" 2>/dev/null)
    if [ -n "$v" ] && [ "$v" != "0" ]; then
        n=$((n + 1))
        [ "$n" -le 20 ] && [ "$v" != "$prev" ] && say "caught v=$v t=$(now) cam=$(pidof qcamerasvr 2>/dev/null) btn=$(pidof kcbtnled 2>/dev/null)"
        echo 0 >"$B" 2>/dev/null
        prev=0
    fi
    i=$((i + 1))
    if [ $((i % 50)) -eq 0 ] && [ "$(getprop sys.boot_completed 2>/dev/null)" = 1 ]; then
        # kcbtnled starts on this same property and fades the keys up for its
        # 5 s timeout as part of its own start-up.  Hold six more seconds so
        # that light is not visible either, then hand the node over.
        say "boot_completed t=$(now), holding 6 s for kcbtnled start"
        j=0
        while [ "$j" -lt 300 ]; do
            v=$(cat "$B" 2>/dev/null)
            if [ -n "$v" ] && [ "$v" != "0" ]; then
                n=$((n + 1))
                [ "$n" -le 20 ] && say "caught v=$v t=$(now) (post-boot)"
                echo 0 >"$B" 2>/dev/null
            fi
            j=$((j + 1))
            sleep 0.02
        done
        say "releasing t=$(now) corrected=$n"
        exit 0
    fi
    sleep 0.02
done

i=0
while [ "$i" -lt 585 ]; do
    v=$(cat "$B" 2>/dev/null)
    if [ -n "$v" ] && [ "$v" != "0" ]; then
        n=$((n + 1))
        [ "$n" -le 20 ] && say "caught v=$v t=$(now) (slow phase)"
        echo 0 >"$B" 2>/dev/null
    fi
    i=$((i + 1))
    sleep 0.2
done

say "done t=$(now) corrected=$n v=$(cat "$B" 2>/dev/null)"
