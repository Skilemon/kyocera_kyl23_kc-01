#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mkqcdt.py - build the QCDT blob for Kyocera KC-01 / miraie KYL23 (MSM8926).

Why this exists
---------------
The stock recovery.img carries a QCDT table whose entries are **24 bytes /
6 words**, ordered as::

    board_id  variant_id  soc_rev  offset  size  msm_id

aboot matches a device against that table with the triple
``(msm_id, board_id, soc_rev)``.  If the ``msm_id`` field is missing - which
is exactly what happens when a tool emits the older 20-byte / 5-word layout -
every lookup misses, aboot gives up, and the phone sits on the boot logo
forever.  That failure mode is silent and looks identical to a broken kernel,
so this script writes the six-field layout explicitly and refuses to emit
anything else.

It is also a drop-in replacement for ``dtbToolCM``: the Android build system
invokes ``$(DTBTOOL) -o <out> -s <pagesize> -c <config> [flags] <dtb>...`` and
this script accepts that same command line.

Usage
-----
    mkqcdt.py -o dt.img -s 2048 -c msm8926-kyocera_defconfig arch/arm/boot/msm8926-*.dtb

    # inspect an existing blob
    mkqcdt.py --dump dt.img
"""

import argparse
import os
import struct
import sys

DT_MAGIC = b"\xd0\x0d\xfe\xed"
QCDT_MAGIC = b"QCDT"
ENTRY_SIZE = 24          # 6 words - NOT 20
FIRST_DTB_OFFSET = 0x1800  # same start as the stock image
HEADER_FIELD4 = 145      # stock value (0x91, the first entry's msm_id)


# --------------------------------------------------------------------------
# minimal FDT reader - we only need the root node's qcom,msm-id
# --------------------------------------------------------------------------
def fdt_root_props(blob):
    if len(blob) < 40 or blob[:4] != DT_MAGIC:
        return {}
    (totalsize, off_struct, off_strings, _off_rsv,
     _ver, _lastc, _bcp, _sizestr, _sisestruct) = struct.unpack_from(">9I", blob, 4)

    end = min(len(blob), totalsize) if totalsize else len(blob)
    p = off_struct
    depth = 0
    props = {}

    while p + 4 <= end:
        tok = struct.unpack_from(">I", blob, p)[0]
        p += 4
        if tok == 1:                                    # FDT_BEGIN_NODE
            n = blob.index(b"\x00", p)
            p = (n + 1 + 3) & ~3
            depth += 1
        elif tok == 2:                                  # FDT_END_NODE
            depth -= 1
        elif tok == 3:                                  # FDT_PROP
            length, nameoff = struct.unpack_from(">II", blob, p)
            p += 8
            n = blob.index(b"\x00", off_strings + nameoff)
            name = blob[off_strings + nameoff:n].decode("latin-1")
            val = blob[p:p + length]
            p = (p + length + 3) & ~3
            if depth == 1:
                props[name] = val
        elif tok == 4:                                  # FDT_NOP
            continue
        elif tok == 9:                                  # FDT_END
            break
        else:
            break
    return props


def fdt_msm_ids(blob):
    """Return the msm-id list of a DTB (pairs of msm_id, soc_rev)."""
    raw = fdt_root_props(blob).get("qcom,msm-id", b"")
    return [struct.unpack_from(">I", raw, i)[0] for i in range(0, len(raw) - 3, 4)]


def fdt_board_id(blob):
    raw = fdt_root_props(blob).get("qcom,board-id", b"")
    vals = [struct.unpack_from(">I", raw, i)[0] for i in range(0, len(raw) - 3, 4)]
    return vals[0] if vals else None


# --------------------------------------------------------------------------
def load_keys(path):
    """Parse qcdt-keys.txt -> [(board, variant, soc_rev, msm_id), ...]."""
    keys = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 4:
                raise SystemExit("bad line in %s: %r" % (path, line))
            keys.append((int(parts[0], 0), int(parts[1], 0),
                         int(parts[2], 0), int(parts[3], 0)))
    if not keys:
        raise SystemExit("no keys parsed from %s" % path)
    return keys


def build(keys, dtbs, page_size=2048):
    """Emit a QCDT blob covering every key, sharing the supplied DTB images."""
    # pick a DTB per key: prefer one whose qcom,msm-id contains the key's msm_id
    fallback = dtbs[0]
    mapping = []
    for board, variant, soc_rev, msm_id in keys:
        chosen = fallback
        for blob in dtbs:
            if msm_id in fdt_msm_ids(blob):
                chosen = blob
                break
        mapping.append(chosen)

    # dedupe payloads by identity, place them 2048-aligned
    order, offsets = [], {}
    body = bytearray()
    cur = FIRST_DTB_OFFSET
    for blob in mapping:
        key = id(blob)
        if key not in offsets:
            offsets[key] = cur
            pad = (page_size - (len(blob) % page_size)) % page_size
            body += blob + b"\x00" * pad
            cur += len(blob) + pad
            order.append(blob)

    header = bytearray(QCDT_MAGIC) + struct.pack("<3I", 2, len(keys), HEADER_FIELD4)
    table = bytearray(ENTRY_SIZE * len(keys))
    for i, ((board, variant, soc_rev, msm_id), blob) in enumerate(zip(keys, mapping)):
        struct.pack_into("<6I", table, i * ENTRY_SIZE,
                         board, variant, soc_rev, offsets[id(blob)], len(blob), msm_id)

    out = bytearray(header + table)
    if len(out) > FIRST_DTB_OFFSET:
        raise SystemExit(
            "table needs %d bytes but the first DTB sits at 0x%x; "
            "raise FIRST_DTB_OFFSET" % (len(out), FIRST_DTB_OFFSET))
    out += b"\x00" * (FIRST_DTB_OFFSET - len(out))
    out += body
    return bytes(out), len(order)


def dump(path):
    data = open(path, "rb").read()
    if data[:4] != QCDT_MAGIC:
        raise SystemExit("%s is not a QCDT blob" % path)
    ver, count, field4 = struct.unpack_from("<3I", data, 4)
    print("%s: ver=%d entries=%d field4=%d total=%d bytes"
          % (path, ver, count, field4, len(data)))
    print("%-4s %-8s %-9s %-10s %-9s %-8s %s"
          % ("idx", "board", "variant", "soc_rev", "offset", "size", "msm_id"))
    for i in range(count):
        w = struct.unpack_from("<6I", data, 16 + i * ENTRY_SIZE)
        ok = data[w[3]:w[3] + 4] == DT_MAGIC if w[3] + 4 <= len(data) else False
        print("%-4d %-8d %-9d 0x%-8x 0x%-7x %-8d %-7d %s"
              % (i, w[0], w[1], w[2], w[3], w[4], w[5], "" if ok else "<-- BAD"))


def selftest():
    """Sanity-check the layout without needing a real kernel build."""
    keys_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "qcdt-keys.txt")
    keys = load_keys(keys_path)
    fake = DT_MAGIC + b"\x00" * 4092
    blob, unique = build(keys, [fake])

    ver, count, field4 = struct.unpack_from("<3I", blob, 4)
    assert blob[:4] == QCDT_MAGIC, "bad magic"
    assert ver == 2, "unexpected version %d" % ver
    assert count == len(keys), "entry count mismatch"
    assert field4 == HEADER_FIELD4, "header word 4 changed"
    assert len(blob) >= FIRST_DTB_OFFSET, "payload overlaps the table"

    for i, expect in enumerate(keys):
        w = struct.unpack_from("<6I", blob, 16 + i * ENTRY_SIZE)
        assert (w[0], w[1], w[2], w[5]) == expect, "entry %d key mismatch" % i
        assert w[5] != 0, ("entry %d has msm_id 0 - aboot would never match it"
                           % i)

    print("mkqcdt selftest OK: %d keys, %d unique dtb, %d bytes, %d-byte entries"
          % (count, unique, len(blob), ENTRY_SIZE))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("-o", "--output")
    ap.add_argument("-s", "--page-size", type=int, default=2048)
    ap.add_argument("-c", "--config")
    # dtbToolCM takes "-p <dir>" pointing at the built scripts/dtc.  We do
    # not shell out to dtc, so just swallow it instead of letting its value
    # fall through into the positional list and be mistaken for a DTB.
    ap.add_argument("-p", "--dtc-path", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--keys", default=None,
                    help="defaults to qcdt-keys.txt next to this script")
    ap.add_argument("--force-v2", action="store_true",
                    help="accepted for dtbToolCM compatibility, ignored")
    ap.add_argument("-d", "--debug", action="store_true")
    ap.add_argument("--dump", metavar="BLOB")
    ap.add_argument("dtbs", nargs="*",
                    help=".dtb files, or directories that are searched "
                         "recursively for *.dtb")
    args, unknown = ap.parse_known_args(argv)

    if args.selftest:
        return selftest()

    if args.dump:
        dump(args.dump)
        return 0

    if not args.output:
        ap.error("-o/--output is required")
    if not args.dtbs:
        ap.error("no .dtb files given")

    keys_path = args.keys or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "qcdt-keys.txt")
    keys = load_keys(keys_path)

    dtbs = []
    for p in args.dtbs:
        if os.path.isdir(p):
            # dtbToolCM-style: the caller hands us the kernel's arch/arm/boot
            # directory and expects every .dtb below it to be considered.
            found = []
            for root, _dirs, names in os.walk(p):
                for n in sorted(names):
                    if n.endswith(".dtb"):
                        found.append(os.path.join(root, n))
            if not found:
                print("mkqcdt: no .dtb under %s" % p, file=sys.stderr)
            for f in found:
                blob = open(f, "rb").read()
                if blob[:4] == DT_MAGIC:
                    dtbs.append(blob)
                else:
                    print("mkqcdt: %s is not an FDT" % f, file=sys.stderr)
            continue
        if not os.path.exists(p):
            print("mkqcdt: missing %s" % p, file=sys.stderr)
            continue
        blob = open(p, "rb").read()
        if blob[:4] != DT_MAGIC:
            print("mkqcdt: %s is not an FDT" % p, file=sys.stderr)
            continue
        dtbs.append(blob)
    if not dtbs:
        raise SystemExit("mkqcdt: no usable .dtb inputs")

    blob, unique = build(keys, dtbs, args.page_size)
    with open(args.output, "wb") as fh:
        fh.write(blob)

    print("mkqcdt: %s  %d bytes  %d keys  %d unique DTB(s)  %.2f MB"
          % (args.output, len(blob), len(keys), unique, len(blob) / 1048576.0))
    if unknown:
        print("mkqcdt: ignored options: %s" % " ".join(unknown))
    return 0


if __name__ == "__main__":
    sys.exit(main())
