#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mkhybrid.py - splice the TWRP payload into the stock KitKat recovery ramdisk.

Why this exists
---------------
The stock boot chain on the KC-01 / KYL23 will not run TWRP's own Android 7.1
ramdisk.  The kernel is a Kyocera 3.4.0 build and its init cannot create the
7.1 property area (``/dev/__properties__`` became a per-context directory with
a ``properties_serial`` file only in 7.0).  Result:

    init: Failed to initialize property area
    Kernel panic - not syncing: Attempted to kill init! exitcode=0x00000100

So we keep the stock 4.4.4 init/unueventd/healthd/adbd/sepolicy -- a set that is
known to boot on this hardware -- and graft TWRP's ``/sbin`` payload on top.
The stock ``init.rc`` already contains ``service recovery /sbin/recovery``, so
init execs TWRP for us.

Hard rules learned the hard way (each one cost a round of bricking)
------------------------------------------------------------------
1.  The kernel refuses to mount /system in any process except init:

        no permission mount /system/... by non-init process in selinux_mount
        pid=165 pname=recovery realpath=/system dev_name=/dev/block/mmcblk0p19

    That check sits *before* avc_has_perm(), so androidboot.selinux=permissive
    does not disarm it.  We let init mount /system in "on boot" instead.

2.  TWRP's busybox is dynamically linked against /sbin/linker, and 52 shared
    libraries also live in /sbin.  The stock ramdisk ships /sbin as 0750
    (root-only), so a shell-user process cannot even traverse it and adbd
    answers "exec '/system/bin/sh' failed: Permission denied (13)".
    Therefore the whole /sbin subtree is forced to 0755/0777.

3.  The stock adbd hardcodes /system/bin/sh, which does not exist in recovery.
    We add it as a symlink so ``adb shell`` works without root.

4.  The QCDT blob must be the stock one (40 board=8 entries pointing at 8
    distinct DTBs).  A de-duplicated table pointing every entry at one DTB
    makes aboot hand the kernel a device tree for the wrong SoC: the logo shows
    up and the device reboots after ~3s.

5.  The ramdisk has to be gzip, not LZMA -- this 3.4 kernel has no CONFIG_RD_LZMA.
"""

import argparse
import gzip
import hashlib
import os
import re
import stat
import struct
import sys

PAGE = 2048
CPIO_MAGIC = b'070701'
TRAILER = b'TRAILER!!!'

# Boot header values, read straight out of the stock recovery.img:
#
#   magic ANDROID!  page_size 2048
#   kernel   5808608 @ 0x00008000
#   ramdisk  1224393 @ 0x01000000
#   second         0 @ 0x00f00000
#   tags             @ 0x00000100
#
# They are mirrored in BoardConfigCommon.mk; if one of them were wrong the
# kernel would not decompress at all, so they are not worth re-deriving.
KERNEL_ADDR = 0x00008000
RAMDISK_ADDR = 0x01000000
SECOND_ADDR = 0x00F00000
TAGS_ADDR = 0x00000100

# The stock command line.  androidboot.selinux=permissive is appended below.
STOCK_CMDLINE = (
    b'console=ttyHSL0,115200,n8 no_console_suspend=1 '
    b'androidboot.console=ttyHSL0 androidboot.hardware=qcom '
    b'user_debug=31 msm_rtb.filter=0x37'
)

# Files that must stay stock: they form the 4.4.4 init ecosystem.
KEEP_STOCK = {
    b'init', b'init.rc', b'default.prop', b'sepolicy', b'file_contexts',
    b'property_contexts', b'seapp_contexts', b'ueventd.rc', b'ueventd.qcom.rc',
    b'fstab.qcom',
    b'sbin/ueventd', b'sbin/watchdogd', b'sbin/adbd', b'sbin/healthd',
}

# TWRP entries that must never win over the stock ones.
SKIP_TWRP = KEEP_STOCK | {
    b'file_contexts.bin', b'init.environ.rc', b'init.usb.rc',
    b'sbin/recovery',          # handled explicitly
    b'etc/recovery.fstab',     # handled explicitly
    b'ramdisk-files.txt', b'ramdisk-files.sha256sum',   # build bookkeeping
    b'proc', b'sys', b'dev', b'tmp',
}

# The stock init.rc does `import /init.recovery.${ro.hardware}.rc`.  Neither the
# stock ramdisk nor a fresh TWRP build necessarily ships that file, and a missing
# import target only produces a warning -- but an empty placeholder keeps the
# ramdisk identical to the build that was validated on hardware.
PLACEHOLDER_RC = (
    b'init.recovery.qcom.rc',
    b'init.recovery.logd.rc',
    b'init.recovery.ldconfig.rc',
    b'init.recovery.mksh.rc',
    b'init.recovery.vold_decrypt.rc',
)

# --------------------------------------------------------------------------
# newc (cpio) helpers
# --------------------------------------------------------------------------


def cpio_parse(data):
    """Parse a newc archive, return (entries, end_offset)."""
    i = 0
    ents = []
    while True:
        if data[i:i + 6] != CPIO_MAGIC:
            raise ValueError("bad cpio magic at offset %d" % i)
        f = [int(data[i + 6 + j * 8:i + 6 + (j + 1) * 8], 16) for j in range(13)]
        namesize = f[11]
        name = data[i + 110:i + 110 + namesize - 1]
        hdr_pad = (4 - ((110 + namesize) % 4)) % 4
        size = f[6]
        blob = data[i + 110 + namesize + hdr_pad:i + 110 + namesize + hdr_pad + size]
        i += 110 + namesize + hdr_pad + size + ((4 - size % 4) % 4)
        ents.append({'f': f, 'name': name, 'data': blob})
        if name == TRAILER:
            return ents, i


def cpio_make(name, mode, data=b'', uid=0, gid=0, mtime=0, ino=0, nlink=1,
              rdev=(0, 0)):
    """Build one newc entry dict."""
    f = [ino & 0xffffffff, mode, uid, gid, nlink, mtime, len(data),
         rdev[0], rdev[1], 0, 0, len(name) + 1, 0]
    return {'f': f, 'name': name, 'data': data}


def cpio_build(entries):
    out = bytearray()
    for e in entries:
        f = e['f'][:]
        name = e['name']
        data = e['data']
        f[11] = len(name) + 1
        f[6] = len(data)
        out += CPIO_MAGIC + b''.join(b'%08x' % (x & 0xffffffff) for x in f)
        out += name + b'\0' + b'\0' * ((4 - ((110 + len(name) + 1) % 4)) % 4)
        out += data + b'\0' * ((4 - len(data) % 4) % 4)
    return bytes(out)


# --------------------------------------------------------------------------
# boot image helpers
# --------------------------------------------------------------------------


def split_boot(data):
    """Split an Android boot/recovery image into its parts (used for self-check)."""
    if data[:8] != b'ANDROID!':
        raise ValueError("not an Android boot image")
    ksz, kaddr, rsz, raddr, ssz, saddr, tags, page, dtsz = struct.unpack(
        '<9I', data[8:44])
    if page not in (2048, 4096, 8192, 16384):
        raise ValueError("implausible page size %d" % page)
    ro = page + ((ksz + page - 1) // page * page)
    do = ro + ((rsz + page - 1) // page * page)
    return {
        'ksz': ksz, 'kaddr': kaddr, 'rsz': rsz, 'raddr': raddr,
        'ssz': ssz, 'saddr': saddr, 'tags': tags, 'page': page, 'dtsz': dtsz,
        'ro': ro, 'do': do,
        'kernel': data[page:page + ksz],
        'ramdisk': data[ro:ro + rsz],
        'dtb': data[do:do + dtsz],
        'cmdline': data[64:64 + 512].split(b'\0')[0],
    }


def pad_to(b, page):
    return b + b'\0' * ((page - len(b) % page) % page)


def make_boot(kernel, ramdisk_gz, dtb, cmdline, page=PAGE):
    hdr = bytearray(1632)
    struct.pack_into('<8s', hdr, 0, b'ANDROID!')
    struct.pack_into('<9I', hdr, 8,
                     len(kernel), KERNEL_ADDR,
                     len(ramdisk_gz), RAMDISK_ADDR,
                     0, SECOND_ADDR,
                     TAGS_ADDR, page, len(dtb))
    struct.pack_into('<512s', hdr, 64, cmdline)
    sha = hashlib.sha1(
        kernel + ramdisk_gz + struct.pack('<3I', 0, len(kernel), len(ramdisk_gz))
    ).hexdigest()
    struct.pack_into('<32s', hdr, 576, sha.encode())
    return (pad_to(bytes(hdr), page) + pad_to(kernel, page) +
            pad_to(ramdisk_gz, page) + pad_to(dtb, page))


# --------------------------------------------------------------------------
# TWRP root directory -> cpio entries
# --------------------------------------------------------------------------


def scan_root(root):
    """Walk a recovery root directory into cpio entries (parents before kids).

    Permission bits are taken from the files on disk.  A blanket 0755 would turn
    every png and ttf into an executable, which is harmless but noisy and hides
    a genuinely wrong mode when one shows up.
    """
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise SystemExit("twrp root is not a directory: %s" % root)

    ents = []
    ino = 300000
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        filenames.sort()
        rel_dir = os.path.relpath(dirpath, root)

        # a symlink to a directory shows up in dirnames; do not recurse into it
        real_dirs = []
        for name in dirnames:
            full = os.path.join(dirpath, name)
            rel = os.path.normpath(os.path.join(rel_dir, name)).replace(os.sep, '/').encode()
            st = os.lstat(full)
            if stat.S_ISLNK(st.st_mode):
                ents.append(cpio_make(rel, 0o120777, os.readlink(full).encode(),
                                      ino=ino))
            else:
                # a directory has to stay traversable
                ents.append(cpio_make(rel, 0o040000 | stat.S_IMODE(st.st_mode) | 0o111,
                                      b'', ino=ino))
                real_dirs.append(name)
            ino += 1

        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.normpath(os.path.join(rel_dir, name)).replace(os.sep, '/').encode()
            st = os.lstat(full)
            if stat.S_ISLNK(st.st_mode):
                ents.append(cpio_make(rel, 0o120777, os.readlink(full).encode(),
                                      ino=ino))
            elif stat.S_ISREG(st.st_mode):
                with open(full, 'rb') as fh:
                    blob = fh.read()
                mode = stat.S_IMODE(st.st_mode)
                # anything in sbin/ is meant to be run
                if rel.startswith(b'sbin/'):
                    mode |= 0o111
                if not mode & 0o444:
                    mode |= 0o644
                ents.append(cpio_make(rel, 0o100000 | mode, blob, ino=ino))
            else:
                continue
            ino += 1

        dirnames[:] = real_dirs
    return ents


# --------------------------------------------------------------------------
# theme overlay / language pruning
#
# The omni-7.1 manifest ships 19 languages in twres/languages and no CJK font.
# Simplified Chinese lives in the upstream "extra-languages" tree, which is not
# pulled in by the minimal manifest, so it is carried in this repo and laid over
# twres/ here.  Carrying every language costs ~960 KB of the 16 MiB slot for
# nothing, so the run also prunes the rest.
# --------------------------------------------------------------------------

TWRES = b'twres/'
LANG_DIR = b'twres/languages/'
FONT_DIR = b'twres/fonts/'


def apply_twres_overlay(entries, overlay):
    """Lay ``overlay/**`` on top of ``<root>/twres``, replacing same-named files."""
    overlay = os.path.abspath(overlay)
    if not os.path.isdir(overlay):
        raise SystemExit("twres overlay is not a directory: %s" % overlay)

    merged = {}
    for e in entries:
        merged[e['name']] = e

    added = 0
    for dirpath, dirnames, filenames in os.walk(overlay):
        dirnames.sort()
        rel_dir = os.path.relpath(dirpath, overlay)
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.normpath(os.path.join(rel_dir, name)).replace(os.sep, '/')
            dst = TWRES + rel.encode()
            parent = dst.rsplit(b'/', 1)[0]
            if parent and parent not in merged:
                merged[parent] = cpio_make(parent, 0o040755, b'')
            with open(full, 'rb') as fh:
                merged[dst] = cpio_make(dst, 0o100644, fh.read())
            added += 1
    return list(merged.values()), added


def prune_languages(entries, keep):
    """Drop every twres/languages/*.xml whose id is not in ``keep``."""
    out = []
    for e in entries:
        n = e['name']
        if n.startswith(LANG_DIR) and n.endswith(b'.xml'):
            if n[len(LANG_DIR):-4] not in keep:
                continue
        out.append(e)
    return out


def check_language_fonts(entries, keep):
    """A language whose fontoverride points at a missing ttf renders tofu."""
    by_name = {e['name']: e for e in entries}
    missing = []
    for lang in sorted(keep):
        src = by_name.get(LANG_DIR + lang + b'.xml')
        if not src:
            missing.append((lang, b'<language xml>'))
            continue
        for fn in re.findall(rb'filename="([^"]+\.ttf)"', src['data']):
            if FONT_DIR + fn not in by_name:
                missing.append((lang, fn))
    return missing


def check_all_font_refs(entries):
    """Every ``filename="x.ttf"`` under twres/ must resolve to a real file."""
    have = {e['name'] for e in entries if e['name'].startswith(FONT_DIR)}
    miss = []
    pat = re.compile(rb'filename="([^"]+\.ttf)"')
    for e in entries:
        if not (e['name'].startswith(TWRES) and e['name'].endswith(b'.xml')):
            continue
        for fn in pat.findall(e['data']):
            if FONT_DIR + fn not in have:
                miss.append((e['name'], fn))
    return miss


def single_font(entries, target=b'DroidSansFallback.ttf'):
    """Point every twres font reference at one face and drop the other files.

    DroidSansFallback covers full ASCII (95/95) and 20,902 of the 20,992 CJK
    ideographs, so keeping a separate Latin face and a monospace face only
    costs 233 KB of ramdisk.  The catch is layout, not glyphs: latin advance
    widths run ~12% wider and line height grows ~11.7% at the same font size,
    and ``fixed`` is no longer monospaced.  See docs/DEVICE_NOTES.md 13.8.
    """
    keep = FONT_DIR + target
    if keep not in {e['name'] for e in entries}:
        raise SystemExit("single-font: %s is not in the ramdisk" % target.decode())

    pat = re.compile(rb'filename="([^"]+\.ttf)"')
    changed = [0]

    def sub(m):
        if m.group(1) != target:
            changed[0] += 1
            return b'filename="' + target + b'"'
        return m.group(0)

    out, dropped = [], []
    for e in entries:
        n = e['name']
        if n.startswith(FONT_DIR) and n != keep:
            dropped.append(n)
            continue
        if n.startswith(TWRES) and n.endswith(b'.xml'):
            e['data'] = pat.sub(sub, e['data'])
        out.append(e)
    return out, changed[0], dropped


# --------------------------------------------------------------------------
# patches
# --------------------------------------------------------------------------

MOUNT_DEV = b'/dev/block/platform/msm_sdcc.1/by-name/system'
CACHE_DEV = b'/dev/block/platform/msm_sdcc.1/by-name/cache'

# Injected by --boot-trace.  init 4.4 does not honour quotes when it splits a
# service's argv, so the redirection cannot live here; boottrace.sh does it.
TRACE_RC = b"""
# --- boot trace (mkhybrid --boot-trace) -------------------------------
# Snapshot init's progress into /cache, which is eMMC and therefore survives
# the watchdog reset that a hung recovery triggers.
service boottrace_1 /sbin/sh /sbin/boottrace.sh 1
    oneshot
    disabled

service boottrace_2 /sbin/sh /sbin/boottrace.sh 2
    oneshot
    disabled
"""

TRACE_SH = b"""#!/sbin/sh
# Written by mkhybrid --boot-trace.  Arg 1 is the stage number.
# Everything here has to survive a hard reset, so it goes to /cache.
# Each boot gets its own run number so the trail from a hung boot is not
# overwritten by the boot you use to go in and read it.
D=/cache/recovery
S=$1

say() {
    echo "boottrace: $1" > /dev/kmsg 2>/dev/null
}

if ! grep -q ' /cache ' /proc/mounts 2>/dev/null; then
    # init mounts cache just before stage 1.  Retry once by hand, in case it
    # was the mount itself that failed - that is exactly what we are hunting.
    mount -t ext4 -o rw,barrier=1 \\
        /dev/block/platform/msm_sdcc.1/by-name/cache /cache 2>/dev/null
fi

if grep -q ' /cache ' /proc/mounts 2>/dev/null; then
    O=$D
    mkdir -p "$O" 2>/dev/null
    # The stock adbd drops to uid 2000 and cannot be talked out of it, while
    # /cache is 0770 system:cache, so adb cannot even traverse into it and the
    # trace would be unreadable through the only shell that works.  Relax the
    # modes; this is a debug build, "chmod 0770 /cache" puts it back.
    chmod 0755 /cache 2>/dev/null
    chmod 0755 "$O" 2>/dev/null
else
    # No cache at all: /tmp is tmpfs and group shell can read it, but a reset
    # loses it.  Better than nothing if cache is what blew up.
    O=/tmp
    say "/cache not mounted, stage $S goes to /tmp only"
fi

if [ "$S" = "1" ]; then
    R=$(cat "$O/run" 2>/dev/null)
    R=$(( ${R:-0} + 1 ))
    echo "$R" > "$O/run"
    G=$(( R - 10 ))
    if [ "$G" -gt 0 ] 2>/dev/null; then
        rm -f "$O/run${G}_stage1.txt" "$O/run${G}_stage2.txt" 2>/dev/null
    fi
else
    R=$(cat "$O/run" 2>/dev/null)
    R=${R:-0}
fi

T="$O/run${R}_stage${S}.txt"

{
    echo "== boot $R stage $S"
    echo "== uptime $(cat /proc/uptime 2>/dev/null)"
    echo "== cmdline $(cat /proc/cmdline 2>/dev/null)"
    echo "== modes"
    ls -ld /cache /cache/recovery /tmp 2>&1
    echo "== mounts"
    cat /proc/mounts 2>/dev/null
    echo "== dmesg"
    dmesg 2>/dev/null
} > "$T" 2>&1

chmod 0644 "$T" 2>/dev/null
sync
"""


# TWRP drives the USB gadget through sys.usb.config: Enable_MTP writes "none",
# rewrites idVendor/idProduct, then writes "mtp,adb" and expects init to rebuild
# the gadget.  TWRP's own init.recovery.usb.rc carries those handlers, but this
# image runs the stock 4.4 init.rc, which has none of them - so the property
# changed and nothing happened, leaving functions=adb: adb worked, the host
# never saw an MTP device.  Only the property triggers matter here; the stock
# init already sets up the adb-only gadget in its "on init" block.
USB_RC = b"""
# --- USB config switching (mkhybrid) ----------------------------------
# f_mtp is in the kernel and ueventd already maps /dev/mtp_usb, so all that is
# missing is somebody reacting to sys.usb.config.
on property:sys.usb.config=none
    stop adbd
    write /sys/class/android_usb/android0/enable 0
    write /sys/class/android_usb/android0/bDeviceClass 0
    setprop sys.usb.state ${sys.usb.config}

on property:sys.usb.config=adb
    stop adbd
    write /sys/class/android_usb/android0/enable 0
    write /sys/class/android_usb/android0/functions ${sys.usb.config}
    write /sys/class/android_usb/android0/enable 1
    start adbd
    setprop sys.usb.state ${sys.usb.config}

on property:sys.usb.config=mtp,adb
    stop adbd
    write /sys/class/android_usb/android0/enable 0
    write /sys/class/android_usb/android0/functions ${sys.usb.config}
    write /sys/class/android_usb/android0/enable 1
    start adbd
    setprop sys.usb.state ${sys.usb.config}

on property:sys.usb.config=mass_storage,adb
    stop adbd
    write /sys/class/android_usb/android0/enable 0
    write /sys/class/android_usb/android0/functions ${sys.usb.config}
    write /sys/class/android_usb/android0/enable 1
    start adbd
    setprop sys.usb.state ${sys.usb.config}
"""


def patch_init_rc(data, trace=False, modules=(), wp_clear=(),
                  wp_script=None):
    """Point LD_LIBRARY_PATH at /sbin, let init mount /system, load modules."""
    out = data
    note = []

    old_ld = b'export LD_LIBRARY_PATH /vendor/lib:/system/lib'
    if old_ld in out:
        out = out.replace(old_ld, b'export LD_LIBRARY_PATH /sbin')
        note.append("LD_LIBRARY_PATH -> /sbin")

    if b'mount ext4 ' + MOUNT_DEV not in out:
        anchor = b'    class_start default'
        if anchor not in out:
            raise SystemExit("init.rc: cannot find 'class_start default'")
        block = b''
        if trace:
            # cache has to be up before anything can be written to it, and it
            # is the mount most likely to stall on this eMMC.
            block += b'    mount ext4 ' + CACHE_DEV + b' /cache\n'
            block += b'    start boottrace_1\n'
        block += b'    mount ext4 ' + MOUNT_DEV + b' /system rw\n'
        # /system/bin/sh is now the 4.4 mksh, which cannot start under
        # LD_LIBRARY_PATH=/sbin.  Put the busybox one back on top of it so
        # scripts with a #!/system/bin/sh shebang still run.
        block += (b'    exec /sbin/busybox mount --bind /sbin/sh '
                  b'/system/bin/sh\n')
        if trace:
            block += b'    start boottrace_2\n'
        out = out.replace(anchor, block + anchor)
        note.append("mount /system before class_start")

    if trace and b'service boottrace_1' not in out:
        out = out.rstrip(b'\n') + b'\n' + TRACE_RC
        note.append("dump dmesg to /cache at 2 stages")

    if b'sys.usb.config=mtp,adb' not in out:
        out = out.rstrip(b'\n') + b'\n' + USB_RC
        note.append("sys.usb.config handlers")

    if modules:
        # 模块只做两件事：注册 /sys/kernel/mmc_protect 和一张分区->bdev 的查找表。
        # 它不在 init 阶段碰块设备（clear 是写 sysfs 时才 lookup_bdev），所以
        # 放在 "on init" 里最早的一批操作之后就行，不必等 ueventd 建好节点。
        # insmod 失败只会让 init 往 kernel log 打一行，不会卡住 recovery。
        lines = b''.join(b'    insmod /sbin/' + m + b'\n' for m in modules)
        anchor = (b'    write /sys/class/android_usb/android0/iSerial '
                  b'${ro.serialno}')
        if anchor in out:
            out = out.replace(anchor, anchor + b'\n' + lines, 1)
            where = "on init"
        else:
            # stock init.rc 变了，退回独立段：同名 trigger 会被合并执行，
            # 仍然早于 on boot 的 class_start。
            out = out.rstrip(b'\n') + b'\n\non init\n' + lines
            where = "new on init block"
        note.append("%s: insmod %s" % (where, ", ".join(m.decode() for m in modules)))

    if wp_clear:
        # eMMC write protect is armed by aboot at every boot, at the card level
        # (WP groups), so it survives a kernel change; only CMD29 lifts it and
        # mmc_protect.ko is what issues it.  devtmpfs is off in this kernel, so
        # /dev/block/* only appears once ueventd has run: wait for the node and
        # do the clearing after class_start.
        anchor = b'    class_start default'
        if anchor not in out:
            raise SystemExit("init.rc: cannot find 'class_start default'")
        block = b'    wait /dev/block/' + wp_clear[0] + b' 10\n'
        if wp_script:
            block += b'    exec /sbin/sh /sbin/' + wp_script + b'\n'
        else:
            for part in wp_clear:
                block += (b'    write /sys/kernel/mmc_protect/clear '
                          + part + b'\n')
        out = out.replace(anchor, anchor + b'\n' + block, 1)
        note.append(("clear eMMC WP via /sbin/" + wp_script.decode())
                    if wp_script else
                    ("clear eMMC WP for " +
                     ", ".join(p.decode() for p in wp_clear)))

    return out, note


def patch_default_prop(data):
    out = data
    for a, b in ((b'ro.secure=1', b'ro.secure=0'),
                 (b'ro.debuggable=0', b'ro.debuggable=1'),
                 (b'ro.adb.secure=1', b'ro.adb.secure=0')):
        out = out.replace(a, b)
    return out


SHELL_OLD = b'/system/bin/sh\x00'
SHELL_NEW = b'/sbin/sh' + b'\x00' * (len(SHELL_OLD) - len(b'/sbin/sh'))


def patch_adbd(data):
    """Point adbd's hard-coded shell at the busybox one in /sbin.

    The stock adbd is statically linked and therefore immune to the
    LD_LIBRARY_PATH=/sbin export, but the shell it execs is not: /system/bin/sh
    is the 4.4 mksh, which resolves libc.so through that variable and lands on
    7.1's.  Every `adb shell <cmd>` dies with

        cannot locate symbol "android_get_application_target_sdk_version"

    The replacement is byte-for-byte the same length, so no offset moves.
    """
    n = data.count(SHELL_OLD)
    if not n:
        return data, 0
    return data.replace(SHELL_OLD, SHELL_NEW), n


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(
        description="Splice the TWRP payload into the stock recovery ramdisk")
    ap.add_argument('--kernel', required=True,
                    help='stock kernel (raw zImage)')
    ap.add_argument('--ramdisk', required=True,
                    help='stock recovery ramdisk (gzip cpio, prebuilt/stock/ramdisk.gz)')
    ap.add_argument('--dt', required=True,
                    help='QCDT blob (prebuilt/stock/dtb-kyl23.img)')
    ap.add_argument('--twrp-root', required=True,
                    help='TWRP recovery root directory (out/.../recovery/root)')
    ap.add_argument('--out', required=True, help='output image')
    ap.add_argument('--size', type=int, default=16777216,
                    help='pad the image to this size (default: 16 MiB)')
    ap.add_argument('--gzip-level', type=int, default=6,
                    help='ramdisk gzip level; 6 reproduces the stock stream')
    ap.add_argument('--twres-overlay',
                    help='directory laid over <twrp-root>/twres '
                         '(e.g. prebuilt/twres for zh_CN + its CJK font)')
    ap.add_argument('--languages',
                    help='comma separated language ids to keep in twres/languages '
                         '(default: keep whatever the build produced)')
    ap.add_argument('--single-font', action='store_true',
                    help='keep only twres/fonts/DroidSansFallback.ttf and repoint '
                         'every font reference at it; drops RobotoCondensed and '
                         'DroidSansMono (saves ~162 KB compressed, but latin '
                         'runs ~12% wider and "fixed" stops being monospaced)')
    ap.add_argument('--wp-clear', action='append', default=[],
                    metavar='PART', help='eMMC partition name to unprotect '
                    '(e.g. mmcblk0p12); needs --module mmc_protect.ko')
    ap.add_argument('--wp-script', metavar='SH',
                    help='shell script dropped at /sbin/ and exec\'d from init '
                         'instead of the per-partition write; must take over '
                         'the whole eMMC WP clearing step')
    ap.add_argument('--module', action='append', default=[],
                    metavar='KO',
                    help='kernel module to drop in /sbin and insmod from init '
                         '(repeatable; e.g. prebuilt/mmc_protect.ko)')
    ap.add_argument('--boot-trace', action='store_true',
                    help='dump dmesg into /cache before and after mounting '
                         '/system, so a watchdog reset still leaves a trail')
    args = ap.parse_args()

    kernel = open(args.kernel, 'rb').read()
    stock_rd = open(args.ramdisk, 'rb').read()
    dtb = open(args.dt, 'rb').read()
    print("kernel=%d  stock ramdisk=%d  dt=%d" % (len(kernel), len(stock_rd), len(dtb)))

    if stock_rd[:2] != b'\x1f\x8b':
        raise SystemExit("stock ramdisk is not gzip; refusing to guess")
    if len(dtb) < 16 or dtb[:4] != b'QCDT':
        raise SystemExit("blob is not a QCDT table")

    dt_count = struct.unpack('<I', dtb[8:12])[0]
    if dt_count == 0:
        raise SystemExit("QCDT table is empty")

    st_ents, _ = cpio_parse(gzip.decompress(stock_rd))
    tw_ents = scan_root(args.twrp_root)

    if args.twres_overlay:
        tw_ents, added = apply_twres_overlay(tw_ents, args.twres_overlay)
        print("  twres    : %d file(s) overlaid from %s"
              % (added, args.twres_overlay))

    if args.languages:
        keep = {l.strip().encode() for l in args.languages.split(',') if l.strip()}
        before = len(tw_ents)
        tw_ents = prune_languages(tw_ents, keep)
        missing = check_language_fonts(tw_ents, keep)
        if missing:
            raise SystemExit(
                "language(s) unusable: " + ", ".join(
                    "%s -> %s" % (l.decode(), f.decode()) for l, f in missing))
        print("  languages: kept %s, dropped %d file(s)"
              % (",".join(sorted(k.decode() for k in keep)), before - len(tw_ents)))

    if args.single_font:
        tw_ents, n_ref, gone = single_font(tw_ents)
        print("  font     : %d reference(s) -> DroidSansFallback.ttf, dropped %s"
              % (n_ref, ", ".join(g.decode() for g in gone) or "nothing"))
        bad = check_all_font_refs(tw_ents)
        if bad:
            raise SystemExit(
                "single-font left dangling reference(s): " + ", ".join(
                    "%s -> %s" % (x.decode(), y.decode()) for x, y in bad))

    mod_names = []

    wp_parts = [p.encode() for p in args.wp_clear]

    wp_script_name = None
    if args.wp_script:
        blob = open(args.wp_script, 'rb').read()
        name = os.path.basename(args.wp_script).encode()
        if b'sbin/' + name in {e['name'] for e in tw_ents}:
            raise SystemExit("twrp-root already ships sbin/%s" % name.decode())
        tw_ents.append(cpio_make(b'sbin/' + name, 0o100755, blob,
                                 ino=0xED000001))
        wp_script_name = name
        print("  wp-script: /sbin/%s (%d bytes)" % (name.decode(), len(blob)))
    for path in args.module:
        blob = open(path, 'rb').read()
        if blob[:4] != b'\x7fELF':
            raise SystemExit("%s is not an ELF module" % path)
        name = os.path.basename(path).encode()
        if b'sbin/' + name in {e['name'] for e in tw_ents}:
            raise SystemExit("twrp-root already ships sbin/%s" % name.decode())
        tw_ents.append(cpio_make(b'sbin/' + name, 0o100644, blob,
                                 ino=0xEC000000 + len(mod_names)))
        mod_names.append(name)
        print("  module   : /sbin/%s (%d bytes)" % (name.decode(), len(blob)))

    tw = {e['name']: e for e in tw_ents}
    print("entries: stock=%d twrp=%d" % (len(st_ents), len(tw_ents)))

    for need in (b'sbin/recovery', b'etc/recovery.fstab'):
        if need not in tw:
            raise SystemExit("TWRP root is missing %s" % need.decode())

    cmdline = STOCK_CMDLINE
    if b'androidboot.selinux' not in cmdline:
        cmdline += b' androidboot.selinux=permissive'

    # ---- merge: stock is the base -------------------------------------
    out = []
    names = set()
    for e in st_ents:
        n = e['name']
        if n == TRAILER:
            continue

        if n == b'init.rc':
            data, note = patch_init_rc(e['data'], trace=args.boot_trace,
                                       modules=mod_names,
                                       wp_clear=wp_parts,
                                       wp_script=wp_script_name)
            print("  init.rc  : %s" % (", ".join(note) or "unchanged"))
            out.append(cpio_make(n, e['f'][1], data, e['f'][2], e['f'][3],
                                 e['f'][5], e['f'][0]))
            names.add(n)
            continue

        if n == b'default.prop':
            out.append(cpio_make(n, e['f'][1], patch_default_prop(e['data']),
                                 e['f'][2], e['f'][3], e['f'][5], e['f'][0]))
            names.add(n)
            continue

        if n in (b'sbin/recovery', b'etc/recovery.fstab'):
            t = tw[n]
            out.append(cpio_make(n, t['f'][1], t['data'], t['f'][2], t['f'][3],
                                 t['f'][5], t['f'][0]))
            names.add(n)
            continue

        out.append(e)
        names.add(n)

    # ---- merge: append the TWRP payload -------------------------------
    added = 0
    for e in tw_ents:
        n = e['name']
        if n == TRAILER or n in SKIP_TWRP or n in names:
            continue
        out.append(e)
        names.add(n)
        added += 1

    # ---- adb shell needs /system/bin/sh -> /sbin/sh -------------------
    sh = b'system/bin/sh'
    if sh not in names:
        out.append(cpio_make(b'system', 0o040755, b''))
        out.append(cpio_make(b'system/bin', 0o040755, b''))
        out.append(cpio_make(sh, 0o120777, b'/sbin/sh'))
        names.update({b'system', b'system/bin', sh})
        print("  + /system/bin/sh -> /sbin/sh")

    # ---- keep the ramdisk byte-comparable with the validated build ----
    gaps = [n for n in PLACEHOLDER_RC if n not in names]
    for n in gaps:
        out.append(cpio_make(n, 0o100644, b''))
        names.add(n)
    if gaps:
        print("  + placeholder rc: %s" % ", ".join(g.decode() for g in gaps))

    # ---- adbd has to exec /sbin/sh once /system is mounted -------------
    for e in out:
        if e['name'] == b'sbin/adbd':
            data, cnt = patch_adbd(e['data'])
            if cnt:
                e['data'] = data
                print("  adbd     : %d hard-coded shell path(s) -> /sbin/sh"
                      % cnt)
            else:
                print("  adbd     : WARNING no /system/bin/sh to rewrite")

    # ---- boot trace helper --------------------------------------------
    if args.boot_trace:
        if b'sbin/boottrace.sh' in names:
            raise SystemExit("twrp-root already carries sbin/boottrace.sh")
        out.append(cpio_make(b'sbin/boottrace.sh', 0o100755, TRACE_SH))
        names.add(b'sbin/boottrace.sh')
        print("  + /sbin/boottrace.sh (stage dumps land in /cache/recovery)")

    # ---- rule 2: the whole /sbin subtree must be world readable/exec --
    fixed = {'dir': 0, 'file': 0, 'link': 0}
    for e in out:
        n = e['name']
        if not (n == b'sbin' or n.startswith(b'sbin/')):
            continue
        kind = e['f'][1] & 0o170000
        if kind == 0o040000:
            e['f'][1] = 0o040755
            fixed['dir'] += 1
        elif kind == 0o100000:
            e['f'][1] = 0o100755
            fixed['file'] += 1
        elif kind == 0o120000:
            e['f'][1] = 0o120777
            fixed['link'] += 1
    print("  /sbin    : %d dirs, %d files, %d links set to 0755/0777"
          % (fixed['dir'], fixed['file'], fixed['link']))

    tr = [e for e in st_ents if e['name'] == TRAILER][0]
    out.append(cpio_make(TRAILER, tr['f'][1], b'', tr['f'][2], tr['f'][3],
                         tr['f'][5], tr['f'][0]))

    cpio = cpio_build(out)
    gz = gzip.compress(cpio, args.gzip_level, mtime=0)
    print("ramdisk: cpio=%d gzip=%d (%d entries)" % (len(cpio), len(gz), len(out)))

    img = make_boot(kernel, gz, dtb, cmdline, PAGE)
    body = len(img)
    if body > args.size:
        raise SystemExit("image body %d exceeds partition %d" % (body, args.size))
    img += b'\0' * (args.size - body)
    with open(args.out, 'wb') as fh:
        fh.write(img)

    # ---- self-check ---------------------------------------------------
    chk = split_boot(img)
    assert chk['ramdisk'][:2] == b'\x1f\x8b', "ramdisk lost its gzip header"
    back, _ = cpio_parse(gzip.decompress(chk['ramdisk']))
    m2 = {e['name']: e for e in back}
    m = m2
    assert m[b'sbin/busybox']['f'][1] & 0o001, "busybox not world-executable"
    assert m[b'sbin']['f'][1] & 0o001, "/sbin not world-traversable"
    assert m[b'sbin/recovery']['data'][:4] == b'\x7fELF', "recovery is not ELF"
    assert chk['dtb'] == dtb, "QCDT blob moved"
    for m in mod_names:
        assert b'sbin/' + m in m2, "module /sbin/%s missing from ramdisk" % m

    print("body   : %d bytes, image %d bytes" % (body, len(img)))
    print("md5    : %s" % hashlib.md5(img).hexdigest())
    print("dt     : %d bytes, count=%d" % (len(dtb), dt_count))
    print("cmdline: %s" % cmdline.decode('utf-8', 'replace'))
    print("OK -> %s" % args.out)


if __name__ == '__main__':
    main()
