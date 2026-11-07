# -*- coding: utf-8 -*-
"""可靠的 newc(cpio) 读写：字段全部小写十六进制，namesize 与名称长度严格一致。"""
import struct

def parse(data):
    i = 0; ents = []
    while True:
        if data[i:i+6] != b'070701':
            raise ValueError(f"bad magic at {i}")
        f = [int(data[i+6+j*8:i+6+(j+1)*8], 16) for j in range(13)]
        ns = f[11]; name = data[i+110:i+110+ns-1]
        assert len(name) + 1 == ns, (name, ns)
        pad = (4 - ((110 + ns) % 4)) % 4
        size = f[6]
        blob = data[i+110+ns+pad : i+110+ns+pad+size]
        i += 110 + ns + pad + size + ((4 - size % 4) % 4)
        ents.append(dict(f=f, name=name, data=blob))
        if name == b'TRAILER!!!':
            return ents, i

def build(ents):
    out = bytearray()
    for e in ents:
        f = e['f'][:]; name = e['name']; data = e['data']
        f[11] = len(name) + 1
        f[6] = len(data)
        out += b'070701' + b''.join(b'%08x' % (x & 0xffffffff) for x in f)
        out += name + b'\0' + b'\0' * ((4 - ((110 + len(name) + 1) % 4)) % 4)
        out += data + b'\0' * ((4 - len(data) % 4) % 4)
    return bytes(out)

def add(ents, name, data, mode=0o100644, ino=None):
    """在 TRAILER 前插入一个新条目"""
    body = [e for e in ents if e['name'] != b'TRAILER!!!']
    tr = [e for e in ents if e['name'] == b'TRAILER!!!'][0]
    if ino is None:
        ino = max(e['f'][0] for e in ents) + 1
    f = [ino, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(name) + 1, 0]
    return body + [dict(f=f, name=name, data=data)] + [tr]
