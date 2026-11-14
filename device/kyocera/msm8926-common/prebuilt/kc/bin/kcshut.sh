#!/system/bin/sh
#
# kcshut -- what happens between "Rebooting, reason: null" and the phone
# actually going down.  Since fix29 this is a recorder only: kchalt.sh is the
# one that pulls the lever (see kchalt.sh and the shutdown trigger in
# kyl23-extra.rc).
#
# The framework half of a shutdown is quick:
#
#   18:41:29.778 ShutdownThread: Notifying thread to start shutdown
#   18:41:33.893 ShutdownThread: Rebooting, reason: null
#
# Four seconds of userspace and then silence, yet the phone sat on the reboot
# animation for eight minutes.  The last log ended with this process being
# killed by the shutdown itself -- so the wait is below userspace, in the
# kernel's subsystem stop, which has nothing healthy to talk to: this modem is
# in a permanent reset loop (SMSM_RESET every 42 s).
#
# fix28 tried to power the modem subsystem down first and wrote to
# /sys/.../subsys1/power, which is a directory on this kernel ("can't create
# ... Is a directory"), so it never did anything.  That attempt is gone; what
# is kept is the timeline, because the next dump has to be able to tell whether
# a shutdown was slow before or after userspace let go.

L=/cache/kc_shut.log
D=/sys/bus/msm_subsys/devices

say() {
    echo "$*" >> $L 2>/dev/null
    echo "KCSHUT $*" > /dev/kmsg 2>/dev/null
}

: > $L 2>/dev/null
say "kcshut watching, uptime $(cut -d' ' -f1 /proc/uptime 2>/dev/null)"

while true; do
    v=$(getprop sys.shutdown.requested 2>/dev/null)
    if [ -n "$v" ]; then
        say "shutdown requested: '$v' at $(date) uptime $(cut -d' ' -f1 /proc/uptime 2>/dev/null)"
        say "modem=$(cat $D/subsys1/state 2>/dev/null) adsp=$(cat $D/subsys0/state 2>/dev/null)"
        # Record when the framework hands over.  From that point kchalt.sh is
        # responsible for the reboot; if this line is the last one in the file
        # next time, userspace never got that far.
        j=0
        while [ "$j" -lt 120 ]; do
            p=$(getprop sys.powerctl 2>/dev/null)
            if [ -n "$p" ]; then
                say "powerctl='$p' uptime $(cut -d' ' -f1 /proc/uptime 2>/dev/null)"
                break
            fi
            j=$((j + 1))
            sleep 0.25
        done
        sleep 600
        say "STILL ALIVE 600 s after the request -- the kernel never took over"
        break
    fi
    sleep 3
done
exit 0
