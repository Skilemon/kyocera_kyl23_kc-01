import struct
import sys

IMG = sys.argv[1] if len(sys.argv) > 1 else "aboot.img"
data = open(IMG, "rb").read()

# interesting strings and their file offsets (from `strings -t x`)
STRINGS = {
    "up_key_on": 0x5b038,
    "booting recovery": 0x5a5d0,
    "boot-recovery": None,
    "is_fastboot": 0x5b038,
}

CANDIDATES = [0x10200000, 0x8F600000, 0x0, 0x1027C000, 0x8F640000]

print("file size", hex(len(data)))
for base in CANDIDATES:
    hits = 0
    for name, off in STRINGS.items():
        if off is None:
            continue
        va = base + off
        needle = struct.pack("<I", va)
        n = data.count(needle)
        if n:
            hits += 1
            locs = []
            i = -1
            while True:
                i = data.find(needle, i + 1)
                if i < 0:
                    break
                locs.append(hex(i))
            print("  base %08x  %-18s va %08x  refs %d  @ %s"
                  % (base, name, va, n, ",".join(locs[:4])))
    print("base %08x -> %d/%d strings referenced" %
          (base, hits, len([v for v in STRINGS.values() if v])))
