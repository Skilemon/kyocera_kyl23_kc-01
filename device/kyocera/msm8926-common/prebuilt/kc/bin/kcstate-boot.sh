#!/system/bin/sh
#
# kcstate-boot.sh -- run the health report on a plain timer instead of waiting
# for sys.boot_completed.
#
# fix13 hung the report off "on property:sys.boot_completed=1".  On this port
# boot_completed only shows up after ~170 s, while the WiFi teardown crash
# lands at ~168 s, so the report never ran once.  A timer always gets there.
#
# fix26 ran five of these up front; each pass is a snapshot, so five early
# passes all described a phone nobody had touched yet.
#
# fix31 makes the timer repeat instead.  The last two dumps both turned out to
# hold a single snapshot taken 60 s into the boot -- every question we cared
# about (the WiFi off/on cycle, the shutter press) happened minutes later, so
# there was nothing in the dump to read.  Now a snapshot lands every 150 s for
# the first fifteen minutes, which is exactly the window the user is poking at
# the phone in, and kcstate.sh keeps the file under 400 KB so the newest
# snapshots always survive.
#
sleep 45
/vendor/bin/kcstate.sh

n=0
while [ "$n" -lt 6 ]; do
    sleep 150
    /vendor/bin/kcstate.sh
    n=$((n + 1))
done
exit 0
