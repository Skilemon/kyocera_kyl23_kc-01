import capstone, struct, sys

B = 0xf800c000
D = open(sys.argv[1] if len(sys.argv) > 1 else 'sbl1.img', 'rb').read()
MD = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
MD.detail = True


def cstr(fo, maxlen=80):
    if not (0 <= fo < len(D)):
        return None
    e = D.find(b'\0', fo, fo + maxlen)
    if e < 0:
        return None
    s = D[fo:e]
    if len(s) < 2:
        return None
    try:
        t = s.decode('ascii')
    except Exception:
        return None
    return t if all(32 <= c < 127 for c in t) else None


def decode(start_va, end_va, maxskip=40):
    """线性扫描，解码失败跳 2 字节，输出带注释"""
    off = start_va - B
    end = end_va - B
    skipped = 0
    out = []
    while off < end:
        got = None
        for ins in MD.disasm(D[off:off + 4], B + off):
            got = ins
            break
        if got is None:
            out.append(('%08x' % (B + off), '.byte', '%02x' % D[off], ''))
            off += 2
            skipped += 1
            if skipped > maxskip:
                out.append(('', '', 'too many skips, stop', ''))
                break
            continue
        skipped = 0
        extra = ''
        try:
            if got.mnemonic in ('ldr', 'ldrb', 'ldrh', 'ldr.w') and len(got.operands) == 2:
                o1 = got.operands[1]
                if o1.type == capstone.arm.ARM_OP_MEM and o1.mem.base == capstone.arm.ARM_REG_PC:
                    tgt = ((got.address + 4) & ~3) + o1.mem.disp
                    fo = tgt - B
                    if 0 <= fo < len(D) - 3:
                        v = struct.unpack_from('<I', D, fo)[0]
                        extra = '  ; [%#x]=%08x' % (fo, v)
                        if B <= v < B + len(D):
                            s = cstr(v - B)
                            extra += ' %r' % (s,) if s else ' (ptr)'
        except Exception:
            pass
        out.append(('%08x' % got.address, got.mnemonic, got.op_str, extra))
        off += got.size
    for a, m, o, e in out:
        print('%-10s %-9s %-26s%s' % (a, m, o, e))


if __name__ == '__main__':
    s = int(sys.argv[1], 16)
    t = int(sys.argv[2], 16)
    decode(s, t)
