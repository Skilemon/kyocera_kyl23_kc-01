#!/usr/bin/env python3
"""Edit single-value resources inside resources.arsc without recompiling.

Why this exists
---------------
`apktool b` renumbers the `^attr-private` entries of package android: all 203
names survive, but the ids are reassigned in alphabetical order instead of the
order the original aapt used.  Every prebuilt apk in the image that was
compiled against the *old* ids would then resolve an attribute to the wrong
resource -- silently, and only at runtime.  See docs/DEVICE_NOTES.md 41.2.

So framework-res is never recompiled here.  A bool is a 4-byte field inside an
existing Res_value.  An empty `<integer-array>` is a ResTable_map_entry with
count 0; its items are appended at the end of the type chunk, which moves
nothing except the three size fields above it.

Usage
-----
    arsc_patch.py --apk framework-res.apk --arsc out.arsc \\
        --dump 0x12:0x25 \\
        --bool 0x12:0x25=true \\
        --int-array 0x07:0x2e=5,20,60,150

TYPEID:ENTRYINDEX is the resource id split in half: 0x01120025 -> 0x12:0x25.
Feed the result to `apkresign.py patch --arsc out.arsc`.
"""

import argparse
import struct
import zipfile

RES_TABLE_TYPE = 0x0002
RES_STRING_POOL_TYPE = 0x0001
RES_TABLE_PACKAGE_TYPE = 0x0200
RES_TABLE_TYPE_TYPE = 0x0201
RES_TABLE_TYPE_SPEC_TYPE = 0x0202

FLAG_COMPLEX = 0x0001
NO_ENTRY = 0xFFFFFFFF
TYPE_INT_DEC = 0x10
TYPE_INT_BOOLEAN = 0x12


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def p32(b, o, v):
    struct.pack_into("<I", b, o, v)


def chunks(b, start, end):
    o = start
    while o + 8 <= end:
        typ = u16(b, o)
        size = u32(b, o + 4)
        if size < 8 or o + size > end:
            raise ValueError("bad chunk at %#x: type=%#x size=%d" % (o, typ, size))
        yield o, typ
        o += size


class Arsc:
    """Read-only view with two write operations.  Rebuild it after a write."""

    def __init__(self, data):
        self.b = bytearray(data)
        if u16(self.b, 0) != RES_TABLE_TYPE:
            raise ValueError("not a resources.arsc")
        self.size = u32(self.b, 4)
        if self.size != len(self.b):
            raise ValueError("header size %d != file %d" % (self.size, len(self.b)))

        self.pkg = None
        for o, typ in chunks(self.b, u16(self.b, 2), self.size):
            if typ == RES_TABLE_PACKAGE_TYPE:
                self.pkg = (o, u16(self.b, o + 2), u32(self.b, o + 4))
                break
        if self.pkg is None:
            raise ValueError("no package chunk")
        po = self.pkg[0]
        self.pkg_name = bytes(self.b[po + 12:po + 12 + 256]).decode(
            "utf-16-le").split("\0")[0]
        self.pkg_id = u32(self.b, po + 8)
        self.type_names = self.strings(po + u32(self.b, po + 268))
        self.keys = self.strings(po + u32(self.b, po + 276))

        self.chunks = {}      # typeId -> (offset, headerSize, size) default config
        self.counts = {}      # typeId -> entryCount (from the type chunk)
        for o, typ in chunks(self.b, po + self.pkg[1], po + self.pkg[2]):
            if typ == RES_TABLE_TYPE_TYPE:
                tid = self.b[o + 8]
                hsz = u16(self.b, o + 2)
                # ResTable_config starts at o+20 (u32 size at o+20, then the
                # fields).  Everything after the size word must be zero for the
                # default configuration.
                if bytes(self.b[o + 24:o + hsz]).strip(b"\0"):
                    continue      # some overlay configuration, not the default
                if tid in self.chunks:
                    continue      # keep the first default config we saw
                self.chunks[tid] = (o, hsz, u32(self.b, o + 4))
                self.counts[tid] = u32(self.b, o + 12)

    def strings(self, o):
        if u16(self.b, o) != RES_STRING_POOL_TYPE:
            raise ValueError("expected a string pool at %#x, found %#x"
                             % (o, u16(self.b, o)))
        hsz, count, flags = u16(self.b, o + 2), u32(self.b, o + 8), u32(self.b, o + 16)
        base = o + u32(self.b, o + 20)
        utf8 = bool(flags & 0x100)
        out = []
        for i in range(count):
            p = base + u32(self.b, o + hsz + 4 * i)
            if utf8:
                p += 2 if self.b[p] & 0x80 else 1
                n = self.b[p]
                if n & 0x80:
                    n = ((n & 0x7F) << 8) | self.b[p + 1]
                    p += 2
                else:
                    p += 1
                out.append(bytes(self.b[p:p + n]).decode("utf-8", "replace"))
            else:
                n = u16(self.b, p)
                p += 2
                if n & 0x8000:
                    n = ((n & 0x7FFF) << 16) | u16(self.b, p)
                    p += 2
                out.append(bytes(self.b[p:p + 2 * n]).decode("utf-16-le", "replace"))
        return out

    def chunk(self, tid):
        if tid not in self.chunks:
            raise KeyError("type id %#x: no default-config chunk" % tid)
        return self.chunks[tid]

    def entry(self, tid, idx):
        o, hsz, _ = self.chunk(tid)
        if idx >= self.counts[tid]:
            raise IndexError("entry %#x >= count %d" % (idx, self.counts[tid]))
        rel = u32(self.b, o + hsz + 4 * idx)
        if rel == NO_ENTRY:
            raise KeyError("entry %#x is absent" % idx)
        return o + u32(self.b, o + 16) + rel

    def describe(self, tid, idx):
        e = self.entry(tid, idx)
        esz, flags, key = u16(self.b, e), u16(self.b, e + 2), u32(self.b, e + 4)
        d = {"id": "0x%08x" % ((self.pkg_id << 24) | (tid << 16) | idx),
             "type": self.type_names[tid - 1],
             "name": self.keys[key], "entrySize": esz}
        if flags & FLAG_COMPLEX:
            cnt = u32(self.b, e + 12)
            d["items"] = cnt
            d["values"] = [u32(self.b, e + 16 + 12 * i + 8) for i in range(cnt)]
        else:
            d["dataType"] = "0x%02x" % self.b[e + 11]
            d["value"] = u32(self.b, e + 12)
        return d

    def set_scalar(self, tid, idx, dtype, value):
        e = self.entry(tid, idx)
        if u16(self.b, e + 2) & FLAG_COMPLEX:
            raise ValueError("entry is a map, not a scalar")
        self.b[e + 11] = dtype
        p32(self.b, e + 12, value & 0xFFFFFFFF)

    def set_int_array(self, tid, idx, values):
        """Relocate a map entry to the end of its type chunk with items filled in.

        A bag is not a separate blob: the entry offset points at the entry
        *and* its inline ResTable_map items.  There is no room after the
        original 16-byte header, so the whole entry (header + items) is copied
        to the end of the chunk and the offset table is repointed.  The old
        entry is left as dead space, which nothing reads.
        """
        o, hsz, size = self.chunk(tid)
        start = u32(self.b, o + 16)
        e = self.entry(tid, idx)
        flags = u16(self.b, e + 2)
        if not flags & FLAG_COMPLEX:
            raise ValueError("entry is not a map; cannot hold items")
        if u32(self.b, e + 12) != 0:
            raise ValueError("entry already has %d items" % u32(self.b, e + 12))

        key = u32(self.b, e + 4)
        parent = u32(self.b, e + 8)
        blob = bytearray(struct.pack("<HHIII", u16(self.b, e), flags, key,
                                     parent, len(values)))
        for i, v in enumerate(values):
            # ResTable_map: u32 name, then Res_value{size,res0,dataType,data}
            blob += struct.pack("<IHBBI", 0x01000000 | (i + 1), 8, 0,
                                TYPE_INT_DEC, v & 0xFFFFFFFF)

        p32(self.b, o + hsz + 4 * idx, size - start)     # entries offset
        self.b[o + size:o + size] = blob
        grow = len(blob)
        p32(self.b, o + 4, size + grow)
        p32(self.b, self.pkg[0] + 4, self.pkg[2] + grow)
        p32(self.b, 4, self.size + grow)
        # keep the in-memory view consistent for a second call
        self.chunks[tid] = (o, hsz, size + grow)
        self.pkg = (self.pkg[0], self.pkg[1], self.pkg[2] + grow)
        self.size += grow
        return grow


def loc(s):
    tid, idx = s.split(":")
    return int(tid, 0), int(idx, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apk", required=True)
    ap.add_argument("--arsc", required=True)
    ap.add_argument("--dump", action="append", default=[])
    ap.add_argument("--bool", action="append", default=[],
                    help="TYPE:ENTRY=true|false")
    ap.add_argument("--int", action="append", default=[],
                    help="TYPE:ENTRY=value, a scalar android:integer")
    ap.add_argument("--int-array", action="append", default=[],
                    help="TYPE:ENTRY=v1,v2,...")
    a = ap.parse_args()

    arsc = Arsc(zipfile.ZipFile(a.apk).read("resources.arsc"))
    print("package %s id %#x, %d type chunks"
          % (arsc.pkg_name, arsc.pkg_id, len(arsc.chunks)))

    for s in a.dump:
        print("  %-12s %s" % (s, arsc.describe(*loc(s))))

    for s in a.bool:
        where, val = s.split("=", 1)
        tid, idx = loc(where)
        on = val.strip().lower() in ("1", "true", "yes", "on")
        before = arsc.describe(tid, idx)
        arsc.set_scalar(tid, idx, TYPE_INT_BOOLEAN, 0xFFFFFFFF if on else 0)
        print("  bool %s %s: %d -> %d" % (before["id"], before["name"],
                                          before["value"], 1 if on else 0))
        arsc = Arsc(bytes(arsc.b))

    for s in a.int:
        where, val = s.split("=", 1)
        tid, idx = loc(where)
        value = int(val, 0)
        before = arsc.describe(tid, idx)
        arsc.set_scalar(tid, idx, TYPE_INT_DEC, value)
        print("  int  %s %s: %d -> %d"
              % (before["id"], before["name"], before["value"], value))
        arsc = Arsc(bytes(arsc.b))

    for s in a.int_array:
        where, vals = s.split("=", 1)
        tid, idx = loc(where)
        values = [int(v, 0) for v in vals.split(",")]
        before = arsc.describe(tid, idx)
        grow = arsc.set_int_array(tid, idx, values)
        print("  array %s %s: %d items -> %d items (+%d bytes)"
              % (before["id"], before["name"], before["items"],
                 len(values), grow))
        # the insertion moved every chunk behind it; re-index before the next op
        arsc = Arsc(bytes(arsc.b))

    open(a.arsc, "wb").write(bytes(arsc.b))
    print("wrote %s (%d bytes)" % (a.arsc, len(arsc.b)))


if __name__ == "__main__":
    main()
