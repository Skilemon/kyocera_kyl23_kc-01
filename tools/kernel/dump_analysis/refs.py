import struct, sys, capstone
D = open(sys.argv[1] if len(sys.argv) > 1 else 'sbl1.img','rb').read()
B = 0xf800c000
MD = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB); MD.detail=True

def refs(va):
    out=[]
    # literal pool scan: 4-byte little endian == va
    for o in range(0x50, len(D)-4, 2):
        if struct.unpack_from('<I',D,o)[0]==va:
            out.append(o)
    return out

def dec(off, back=0, fwd=60):
    a = B+off
    for ins in MD.disasm(D[off:off+fwd], a):
        print('%08x  %-8s %s' % (ins.address, ins.mnemonic, ins.op_str))
        if ins.address+ins.size >= a+fwd: break

if __name__=='__main__':
    for s in sys.argv[1:]:
        va=int(s,16)
        for o in refs(va):
            print('pool @%08x (va %08x) -> string %r' % (o, B+o, D[va-B:va-B+40].split(b'\0')[0]))
            dec(o-16, fwd=60)
            print('---')
