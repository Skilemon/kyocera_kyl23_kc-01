#!/system/bin/sh
# kyl23: create the /dev nodes the stock ueventd.rc does not have.
#
# This kernel has CONFIG_DEVTMPFS=n, so every device node comes from a static
# entry in the ramdisk's ueventd.rc.  That file is the stock 4.4 one and is
# missing two nodes that Android 7.1 needs:
#
#   /dev/fuse   char 10:229  -- FUSE is built into the kernel, so it never
#                               sends a uevent; without the node vold hangs in
#                               "Waiting for FUSE to spin up" and /sdcard is a
#                               dead directory.
#   /dev/kmsg   char 1:11    -- needed by dmesg and by every diagnostic probe.
#
# Runs from init on post-fs-data, before vold starts.

mknod /dev/fuse c 10 229 2>/dev/null
chmod 0666 /dev/fuse 2>/dev/null
chown system:system /dev/fuse 2>/dev/null

mknod /dev/kmsg c 1 11 2>/dev/null
chmod 0600 /dev/kmsg 2>/dev/null

# report what we ended up with (kcboot creates the node itself if this failed)
/vendor/bin/kcboot note "devs fuse=$(ls -l /dev/fuse 2>/dev/null | wc -l) kmsg=$(ls -l /dev/kmsg 2>/dev/null | wc -l)"

exit 0
