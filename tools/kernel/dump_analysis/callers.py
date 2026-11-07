import struct, sys
D = open(sys.argv[1] if len(sys.argv) > 1 else 'sbl1.img', 'rb').read()
B = 0xf800c000


def callers(target):
    """Thumb BL / B.W 调用点（修正 S 位：S=1 时 h1 在 0xF800-0xFFFF）"""
    r = []
    for o in range(0x50, len(D) - 4, 2):
        h1 = struct.unpack_from('<H', D, o)[0]
        if (h1 >> 11) != 0x1E:      # 11110 S imm10
            continue
        h2 = struct.unpack_from('<H', D, o + 2)[0]
        kind = h2 & 0xD000
        if kind not in (0x9000, 0xD000):   # B.W / BL
            continue
        S = (h1 >> 10) & 1
        i10 = h1 & 0x3FF
        J1 = (h2 >> 13) & 1
        J2 = (h2 >> 11) & 1
        I1 = 1 - (J1 ^ S)
        I2 = 1 - (J2 ^ S)
        imm = (S << 24) | (I1 << 23) | (I2 << 22) | (i10 << 12) | ((h2 & 0x7FF) << 1)
        if imm & (1 << 24):
            imm -= 1 << 25
        if (B + o + 4) + imm == target:
            r.append(('%08x' % (B + o), 'bl' if kind == 0xD000 else 'b.w'))
    return r


if __name__ == '__main__':
    import sys
    for a in sys.argv[1:]:
        t = int(a, 16)
        print("%08x <- %s" % (t, callers(t)))
