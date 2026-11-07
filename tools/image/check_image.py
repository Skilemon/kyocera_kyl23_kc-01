#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_image.py - refuse to ship a recovery.img that cannot boot.

Run this on every build output before flashing.  It catches the failure
modes that this project has actually hit, in order of how much time they
cost when missed:

  1. QCDT entries whose msm_id field is zero      -> hangs on the boot logo
  2. QCDT entries too small (20 bytes, not 24)    -> same
  3. image larger than the 16 MiB recovery slot   -> dd truncates silently
  4. missing / implausible ramdisk                -> TWRP never starts
  5. dt_size that does not match the payload      -> aboot reads garbage
  6. init.rc that lost the /system mount or the sys.usb.config handlers
  7. more than one font face in twres/fonts  (--max-fonts, see DEVICE_NOTES 13)
  8. an init.rc that insmods a module the ramdisk does not carry
     (--require-module to demand one is present)

Exit code is non-zero on any failure, so CI stops before uploading.
"""

import argparse
import gzip
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ANDROID_MAGIC = b"ANDROID!"
DT_MAGIC = b"\xd0\x0d\xfe\xed"
QCDT_MAGIC = b"QCDT"
ENTRY_SIZE = 24

# the device only matches these; anything else means the table is bogus
VALID_MSM_IDS = {145, 158, 159, 198, 199, 200, 205, 219, 220, 221, 222, 223, 224}


def parse_header(data):
    if data[:8] != ANDROID_MAGIC:
        raise SystemExit("not an Android boot image (magic %r)" % data[:8])
    (kernel_size, kernel_addr, ramdisk_size, ramdisk_addr,
     second_size, second_addr, tags_addr, page_size) = struct.unpack_from("<8I", data, 8)
    dt_size, _unused = struct.unpack_from("<2I", data, 0x28)
    return dict(kernel_size=kernel_size, kernel_addr=kernel_addr,
                ramdisk_size=ramdisk_size, ramdisk_addr=ramdisk_addr,
                second_size=second_size, second_addr=second_addr,
                tags_addr=tags_addr, page_size=page_size, dt_size=dt_size)


def align(n, p):
    return (n + p - 1) // p * p


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--max-size", type=int, default=16777216)
    ap.add_argument("--min-ramdisk", type=int, default=1024 * 1024)
    ap.add_argument("--max-fonts", type=int, default=0,
                    help="fail if twres/fonts holds more than N .ttf files (0 = no check)")
    ap.add_argument("--require-module", action="append", default=[],
                    metavar="KO",
                    help="fail unless /sbin/KO is present and init.rc insmods it")
    args = ap.parse_args(argv)

    data = open(args.image, "rb").read()
    h = parse_header(data)
    ps = h["page_size"]
    problems = []

    print("image      : %s (%d bytes)" % (args.image, len(data)))
    print("page_size  : %d" % ps)
    print("kernel     : %d bytes @ 0x%08x" % (h["kernel_size"], h["kernel_addr"]))
    print("ramdisk    : %d bytes @ 0x%08x" % (h["ramdisk_size"], h["ramdisk_addr"]))
    print("dt_size    : %d bytes" % h["dt_size"])

    # ---- size budget -----------------------------------------------------
    if len(data) > args.max_size:
        problems.append("image is %d bytes, partition holds %d"
                        % (len(data), args.max_size))

    # ---- ramdisk ---------------------------------------------------------
    if h["ramdisk_size"] < args.min_ramdisk:
        problems.append("ramdisk is only %d bytes - TWRP binaries are missing?"
                        % h["ramdisk_size"])
    rd_off = ps + align(h["kernel_size"], ps)
    rd_magic = data[rd_off:rd_off + 4]
    if rd_magic not in (b"\x1f\x8b\x08\x00", b"\x04\x22\x4d\x18", b"\x5d\x00\x00\x80"):
        problems.append("ramdisk at 0x%x does not look compressed (%s)"
                        % (rd_off, rd_magic.hex()))

    # ---- init.rc ---------------------------------------------------------
    # Both lines below are things mkhybrid injects because the stock init.rc
    # cannot do them itself.  Losing either one is silent on the device: no
    # /system mount (Kyocera only lets init mount it) or no MTP on the host
    # while the UI still says it is enabled.
    fonts = None
    if rd_magic == b"\x1f\x8b\x08\x00":
        try:
            import mkhybrid
            ents, _ = mkhybrid.cpio_parse(gzip.decompress(
                data[rd_off:rd_off + h["ramdisk_size"]]))
            fonts = sorted(e["name"].decode() for e in ents
                           if e["name"].startswith(b"twres/fonts/")
                           and e["name"].lower().endswith(b".ttf"))
            rc = {e["name"]: e["data"] for e in ents}.get(b"init.rc", b"")
            if b"by-name/system /system rw" not in rc:
                problems.append("init.rc does not mount /system from init")
            if b"sys.usb.config=mtp,adb" not in rc:
                problems.append("init.rc has no sys.usb.config handlers - MTP "
                                "will show as enabled but never reach the host")
            # Any module init.rc mentions has to be in the ramdisk, otherwise
            # init prints "cannot insmod" and carries on - the failure only
            # surfaces later as "dd says ok but nothing changed".
            present = {e["name"] for e in ents}
            for m in args.require_module:
                name = b"sbin/" + m.encode()
                if name not in present:
                    problems.append("ramdisk has no %s" % name.decode())
                if b"insmod /" + name not in rc:
                    problems.append("init.rc does not insmod %s" % name.decode())
            for line in rc.splitlines():
                line = line.strip()
                if line.startswith(b"insmod /sbin/"):
                    target = line.split()[1].lstrip(b"/")
                    if target not in present:
                        problems.append(
                            "init.rc insmods /%s but the ramdisk does not "
                            "carry it" % target.decode())
        except Exception as exc:                      # noqa: BLE001
            problems.append("cannot read init.rc out of the ramdisk: %s" % exc)

    # ---- fonts -----------------------------------------------------------
    # Two latin faces plus the CJK one is 233 KB of ramdisk for nothing; the
    # single-font build points every reference at DroidSansFallback.ttf and
    # deletes the rest.  A second face reappearing means the build step lost
    # its --single-font flag.
    if fonts:
        print("fonts      : %d" % len(fonts))
        for f in fonts:
            print("             %s" % f)
        if args.max_fonts and len(fonts) > args.max_fonts:
            problems.append(
                "ramdisk carries %d font faces (%s) - expected at most %d; "
                "mkhybrid.py needs --single-font"
                % (len(fonts), ", ".join(os.path.basename(f) for f in fonts),
                   args.max_fonts))

    # ---- device tree -----------------------------------------------------
    dt_off = ps + align(h["kernel_size"], ps) + align(h["ramdisk_size"], ps) \
        + align(h["second_size"], ps)
    print("dt_off     : 0x%x" % dt_off)

    if h["dt_size"] == 0:
        problems.append("no device tree appended (BOARD_KERNEL_SEPARATED_DT is on)")
    else:
        dt = data[dt_off:dt_off + h["dt_size"]]
        if dt[:4] != QCDT_MAGIC:
            problems.append("DT blob does not start with QCDT (%r)" % dt[:4])
        else:
            ver, count, word4 = struct.unpack_from("<3I", dt, 4)
            print("QCDT       : ver=%d entries=%d word4=%d" % (ver, count, word4))
            if count == 0:
                problems.append("QCDT has zero entries")
            if 16 + count * ENTRY_SIZE > len(dt):
                problems.append("QCDT table overruns the blob")

            zero_msm = 0
            bad_off = 0
            for i in range(count):
                w = struct.unpack_from("<6I", dt, 16 + i * ENTRY_SIZE)
                if w[5] == 0:
                    zero_msm += 1
                if not (w[3] + 4 <= len(dt) and dt[w[3]:w[3] + 4] == DT_MAGIC):
                    bad_off += 1
            if zero_msm:
                problems.append(
                    "%d/%d QCDT entries have msm_id=0 - aboot will not match "
                    "any of them and the device will hang on the boot logo "
                    "(entries must be 24 bytes / 6 words)" % (zero_msm, count))
            if bad_off:
                problems.append("%d/%d QCDT entries point at non-FDT data"
                                % (bad_off, count))

            if dt_off + h["dt_size"] > len(data):
                problems.append("dt_size runs past the end of the file")
            slack = len(data) - (dt_off + h["dt_size"])
            print("dt payload : %d bytes, %d bytes slack to end of image"
                  % (h["dt_size"], slack))

    # ---- verdict ---------------------------------------------------------
    if problems:
        print("\nFAILED:")
        for p in problems:
            print("  - %s" % p)
        return 1
    print("\nOK - image looks flashable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
