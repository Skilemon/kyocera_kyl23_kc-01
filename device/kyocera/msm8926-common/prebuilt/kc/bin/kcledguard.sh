#!/system/bin/sh
#
# kcledguard.sh -- hold the button backlight at 0 while the camera probes.
#
# The double blink just before the boot animation is a DT collision, not a
# userspace race:
#
#   msm8926-qrd-skug.dtsi   gpio-leds { keypad-backlight { gpios = <&msmgpio 34 0> } }
#   msm8226-camera-sensor-qrd.dtsi
#                           qcom,camera@6c { gpios = <... 34>; qcom,gpio-af-pwdm = <4>; }
#                           qcom,gpio-req-tbl-label = ... "CAM_AF_PWDM"
#
# Both claim GPIO 34.  The camera's power sequence drives it whenever
# qcamerasvr brings a sensor up or down, and the LED -- which is wired to that
# same line in this DT -- follows: two sensors, two blinks.  The factory build
# does not do this because its button backlight is PMIC MPP2
# (qcom,led_mpp_2 under qcom,leds@a100, linux,name = "button-backlight",
# default-state off) and the qrd gpio-leds node does not exist there.
#
# Putting the DT back the factory way means rebuilding the boot image, so until
# that happens this holds the node at 0 through the window in which the camera
# probes.  It also writes down every value it had to correct, which is what
# proves or disproves the paragraph above: after fix75 a dump either has
# KLEDGUARD lines (camera was driving the line) or none (something else is).
#
# What this costs: for the first two minutes, touching the keys will not light
# them.  After that the service exits and kcbtnled owns the node again.
#
B=/sys/class/leds/button-backlight/brightness
L=/cache/kc_led.log

say() {
    echo "$*" >> $L 2>/dev/null
    echo "KLEDGUARD $*" > /dev/kmsg 2>/dev/null
}

[ -e "$B" ] || { say "no $B -- nothing to guard"; exit 0; }

say "start uptime $(cut -d' ' -f1 /proc/uptime 2>/dev/null) v=$(cat $B 2>/dev/null)"

# 120 s at 100 ms.  The camera is up by 6.2 s and its retries are done well
# before a minute; the rest of the window is margin for a slow boot.
i=0
n=0
while [ "$i" -lt 1200 ]; do
    v=$(cat $B 2>/dev/null)
    if [ -n "$v" ] && [ "$v" != "0" ]; then
        n=$((n + 1))
        # Only the first few, so a stuck line cannot fill the kernel ring.
        [ "$n" -le 8 ] && say "caught v=$v at $(cut -d' ' -f1 /proc/uptime 2>/dev/null) cam=$(pidof qcamerasvr 2>/dev/null) mm=$(pidof mm-qcamera-daemon 2>/dev/null)"
        echo 0 > $B 2>/dev/null
    fi
    i=$((i + 1))
    sleep 0.1
done

say "done uptime $(cut -d' ' -f1 /proc/uptime 2>/dev/null) corrected=$n v=$(cat $B 2>/dev/null)"
