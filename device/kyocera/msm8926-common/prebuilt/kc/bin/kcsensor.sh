#!/system/bin/sh
# ---------------------------------------------------------------------------
# Give the sensors HAL ownership of the sensor driver's attributes.
#
# /vendor/lib/hw/sensors.default.so does not go through any abstraction: it
# writes /sys/class/input/inputN/enable_als_sensor and .../enable_ps_sensor
# directly.  It runs inside system_server, i.e. as uid 1000 (AID_SYSTEM), while
# sfh7776.c publishes those attributes as 0660 root:root and /dev/psals_sensor
# as 0600 root:root.  So every write the HAL ever made came back EACCES, and
# one cause produced both symptoms:
#
#   * activate() failed, so the light sensor never sampled.  fix80's dump has
#     mLightSensorEnabled=true (the framework did ask) sitting next to
#     /sys/class/input/input6/enable_als_sensor == 0 (the driver never heard),
#     and als_poll_delay still at the driver's default, i.e. the HAL could not
#     write the delay either.
#   * the two readInitialValue() calls and setCrossTalkVal() in the HAL
#     constructor failed and retried: nuSensorService starting (03.893) to
#     "thread starting" (28.428) is 24.5 s of every boot.
#
# Stock did exactly this in /init.rc plus /init.kc.sensor.sh, and both
# scripts list precisely these nodes (chown system:input: enable_als_sensor,
# enable_ps_sensor, ps_crosstalk, and enable+delay+wake for the accelerometer,
# magnetometer and virtual sensors).  Our ramdisk is CM's msm8926 one and has
# neither file, so nothing in this port ever handed the nodes over.
#
# 1000:1004 rather than system:input because this ROM ships no /etc/passwd or
# /etc/group, and toybox chown resolves names through them.
#
# Run from "on post-fs-data" in kyl23-extra.rc: the input devices exist from
# driver probe (kernel time), and post-fs-data is still well before zygote, so
# the HAL sees the right owner on its very first write.
# ---------------------------------------------------------------------------
PATH=/sbin:/system/bin:/system/xbin:/vendor/bin
export PATH

SYS=1000        # AID_SYSTEM, the uid sensors.default.so runs as
INP=1004        # AID_INPUT
n=0
als=no
ps=no
psals=no

own() {
    [ -e "$1" ] || return 0
    chown "$2:$3" "$1" 2>/dev/null && n=$((n + 1))
}

for d in /sys/class/input/input*; do
    case "$(cat "$d/name" 2>/dev/null)" in
        light)
            own "$d/enable_als_sensor" $SYS $INP
            own "$d/als_poll_delay"    $SYS $INP
            als=yes
            ;;
        proximity)
            own "$d/enable_ps_sensor" $SYS $INP
            own "$d/ps_crosstalk"     $SYS $INP
            ps=yes
            ;;
        accelerometer)
            own "$d/enable"       $SYS $INP
            own "$d/delay"        $SYS $INP
            own "$d/wake"         $SYS $INP
            own "$d/mtp_recovery" $SYS $INP
            ;;
        geomagnetic|orientation|rotation_vector|linear_acceleration|gravity)
            own "$d/enable" $SYS $INP
            own "$d/delay"  $SYS $INP
            own "$d/wake"   $SYS $INP
            ;;
    esac
done

# The HAL's ioctl channel to the driver (crosstalk calibration).
if [ -e /dev/psals_sensor ]; then
    chown $SYS:$SYS /dev/psals_sensor 2>/dev/null && psals=yes
fi

# One line, so the report can quote it without another file to fetch.
echo "kcsensor: nodes=$n als=$als ps=$ps psals=$psals" > /dev/kmsg 2>/dev/null
exit 0
