import capstone, struct, sys
D=open(sys.argv[1] if len(sys.argv)>1 else 'aboot.img','rb').read()
B=0x10200000; OFF0=0x28
MD=capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB); MD.detail=True
def f2v(o): return B+o-OFF0
def v2f(v): return v-B+OFF0
def cstr(v):
    o=v2f(v)
    if not (0<=o<len(D)): return None
    e=D.find(b'\0',o,o+80)
    if e<0: return None
    try: t=D[o:e].decode('ascii')
    except: return None
    return t if all(32<=c<127 for c in t) else None
def dis(v, n=60):
    o=v2f(v)
    c=0
    for ins in MD.disasm(D[o:o+n*4], v):
        extra=''
        try:
            if ins.mnemonic.startswith('ldr') and len(ins.operands)==2 and ins.operands[1].type==capstone.arm.ARM_OP_MEM and ins.operands[1].mem.base==capstone.arm.ARM_REG_PC:
                t=((ins.address+4)&~3)+ins.operands[1].mem.disp
                fo=v2f(t)
                if 0<=fo<len(D)-3:
                    val=struct.unpack_from('<I',D,fo)[0]
                    s=cstr(val)
                    extra='  ; =%08x %r'%(val,s) if s else '  ; =%08x'%val
        except Exception: pass
        print('%08x  %-8s %-26s%s'%(ins.address,ins.mnemonic,ins.op_str,extra))
        c+=1
        if c>=n: break
if __name__=='__main__':
    dis(int(sys.argv[1],16), int(sys.argv[2]) if len(sys.argv)>2 else 60)
