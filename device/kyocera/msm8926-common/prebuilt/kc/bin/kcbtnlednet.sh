#!/system/bin/sh
#
# kcbtnlednet.sh -- the safety net for kcledguard.
#
# kcbtnled only starts on sys.kcbtnled.late, which kcledguard sets at the end
# of its two-minute hold.  If that script dies (it is a shell loop writing to
# sysfs, so it can), nothing would ever set the property and the keys would
# never light again -- a worse bug than the flash it was fixing.  This starts
# at boot, waits past the guard's window, and sets the property anyway.
#
# Setting it twice is harmless: init's "start" on a running service is a no-op.
sleep 200
setprop sys.kcbtnled.late 1
