#!/system/bin/sh
#
# kcbtinit.sh -- give the WCNSS Bluetooth core the address it does not have.
#
# Started by init on property:bluetooth.hciattach=true, i.e. at the moment the
# vendor library powers the controller up, and before it opens /dev/smd3.
# Whatever this prints goes to /cache/kcbt.log, next to kcbt.sh's output.
#
# Why it exists:
#
#   Everything about this phone's Bluetooth works -- enabling, discovery,
#   pairing, OPP, toggle, reboot -- except that it calls itself
#   00:00:00:00:5A:AD.  That is not a misread.  The core is a second CPU inside
#   the WCNSS with its own NV, and nothing in 7.1 ever fills that NV in:
#
#       W bt_btif: BTIF init BDA was c4:21:c8:f2:9f:3a
#       W bt_btif: Controller BDA is 00:00:00:00:5a:ad
#
#   The host knows the right address (it is in /persist/.bt_nv.bin, NV447 --
#   a boot that never opened the transport says "Read the Vendor BD addr from
#   '/persist/.bt_nv.bin'" and reports C4:21:C8:F2:9F:3A), it just has no code
#   that pushes it across.
#
#   The 4.4 ROM did have that code, and it is still on the stock image:
#
#       /system/bin/btnvtool        reads / writes NV447 in /persist/.bt_nv.bin
#       /system/bin/hci_qcomm_init  reads NV447, sends the "NV VS set" commands
#                                   over /dev/smd3 that program the core
#
#   hci_qcomm_init takes its port from ro.qualcomm.bt.hci_transport (set to
#   "smd" in post-fs-data; unset would mean /dev/ttyHS0) and prints, with -e,
#   the BTS_* variables the old init.qcom.bt.sh used to eval.
#
# What it does not do: run init.qcom.bt.sh.  That script also sets a page of
# ro.qualcomm.bluetooth.* profile flags through config_bt(), which would change
# which profiles 7.1 exposes, and none of that has anything to do with an
# address.  Only the one step is taken.
#
export PATH=/sbin:/system/bin:/system/xbin

LOG=/cache/kcbt.log
say() { echo "KCBTINIT $*" >> "$LOG" 2>/dev/null; }

say "== start uptime=$(cut -d' ' -f1 /proc/uptime 2>/dev/null)"
say "hci_transport='$(getprop ro.qualcomm.bt.hci_transport)' soc='$(getprop qcom.bluetooth.soc)'"
say "nv: $(ls -l /persist/.bt_nv.bin 2>&1)"

# The vendor library waits five seconds for bluetooth.status before it opens the
# port regardless.  Four seconds for this keeps us strictly inside that window:
# if the tool hangs on a dead channel it is killed and its descriptor is closed
# before the stack goes looking for the same port.
out=$(timeout 4 /system/bin/hci_qcomm_init -e 2>&1)
rc=$?
say "hci_qcomm_init rc=$rc"
printf '%s\n' "$out" | while IFS= read -r l; do say "  $l"; done

if [ "$rc" = "0" ]; then
    eval "$out" 2>/dev/null
    say "programmed address=$BTS_ADDRESS device=$BTS_DEVICE type=$BTS_TYPE"
else
    say "not programmed (rc=$rc); the core keeps whatever address it has"
fi

# Success or not, stop the stack from sitting out the five seconds: on failure
# the core is exactly as it was before this ran, which is the state every build
# up to fix52 shipped with.
setprop bluetooth.status on
say "== done"
exit 0
