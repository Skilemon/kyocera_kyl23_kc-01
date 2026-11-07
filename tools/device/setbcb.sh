#!/system/bin/sh
# Write a BCB command into the misc partition.
#
# Pulled aboot.img apart and counted code references to each string: only
# these two command names are ever read from misc:
#   boot-recovery
#   update-radio
#
# "reboot-bootloader" is NOT a BCB command.  It belongs to the fastboot
# command table, and that table is not linked into this aboot at all -
# writing it here leaves 17 bytes of noise and nothing else happens.
#
# usage: setbcb.sh boot-recovery
#        setbcb.sh --clear
#        setbcb.sh --show

MISC=/dev/block/mmcblk0p26
CMD="$1"

if [ -z "$CMD" ] || [ "$CMD" = "--show" ]; then
    echo "current misc[0:64]:"
    dd if=$MISC bs=1 count=64 2>/dev/null
    echo
    exit 0
fi

if [ "$CMD" = "--clear" ]; then
    echo "zeroing misc[0:32]"
    dd if=/dev/zero of=$MISC bs=1 count=32 2>/dev/null
    sync
    echo "read back:"
    dd if=$MISC bs=1 count=64 2>/dev/null
    echo
    exit 0
fi

echo "writing '$CMD' to $MISC"
printf '%s' "$CMD" | dd of=$MISC bs=1 conv=notrunc 2>/dev/null
sync

echo "read back:"
dd if=$MISC bs=1 count=64 2>/dev/null
echo
