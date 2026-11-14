#!/system/bin/sh
#
# kchalt.sh -- turn "reboot" into something that actually reboots.
#
# Measured on this phone: the framework is done with its half of a reboot in
# four seconds and then nothing happens for as long as you are willing to
# wait.  From kc_shut.log, the last round:
#
#       shutdown requested: '1'  at uptime 266.78
#       still alive at           uptime 269.90
#       (nothing more -- the process was killed by the shutdown itself)
#
# so userspace let go at ~270 s and the machine never came back: the console
# stayed on the reboot animation for eight minutes and had to be held down.
#
# What is left at that point runs in the kernel, and the kernel is waiting for
# a modem that is stuck in its own reset loop (SMSM_RESET every 42 s, "Watchdog
# detects stalled initialization").  The stop handshake has nothing to talk to,
# and we cannot replace the kernel from the system partition.
#
# What we can do is take the same shortcut a long power-press takes: sysrq 'b'
# calls emergency_restart(), which goes straight to the board's restart hook
# and skips the whole device_shutdown() walk -- no subsystem stop, no modem
# handshake, no waiting.  'o' does the same for power off.
#
# Triggered from init on the property the framework sets when the user picks
# Reboot, so it costs the framework nothing: we wait for sys.powerctl (the
# property the framework writes when it has finished) and only then pull the
# lever.  A sync() first, because this path does not unmount anything.
#
L=/cache/kc_shut.log

say() {
    echo "$*" >> $L 2>/dev/null
    echo "KCHALT $*" > /dev/kmsg 2>/dev/null
}

say "armed, requested='$(getprop sys.shutdown.requested)' uptime $(cut -d' ' -f1 /proc/uptime 2>/dev/null)"

if [ ! -w /proc/sysrq-trigger ]; then
    say "no /proc/sysrq-trigger -- cannot shorten this shutdown"
    exit 0
fi

# 20 s at 0.1 s.  sys.powerctl normally appears 3-4 s after the request.
i=0
while [ "$i" -lt 200 ]; do
    p=$(getprop sys.powerctl 2>/dev/null)
    case "$p" in
        reboot*|shutdown*|poweroff*)
            say "powerctl='$p' uptime $(cut -d' ' -f1 /proc/uptime 2>/dev/null) -> forcing"
            sync
            sleep 0.3
            sync
            case "$p" in
                reboot*) echo b > /proc/sysrq-trigger 2>/dev/null ;;
                *)       echo o > /proc/sysrq-trigger 2>/dev/null ;;
            esac
            # emergency_restart() does not return; if we are still here the
            # write was rejected.  Say so, and give the normal path a chance.
            say "sysrq-trigger returned -- falling back to init"
            exit 1
            ;;
    esac
    i=$((i + 1))
    sleep 0.1
done

say "sys.powerctl never appeared in 20 s -- leaving this to init"
exit 0
