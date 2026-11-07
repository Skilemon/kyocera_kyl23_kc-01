#!/usr/bin/env python3
"""把 wp2 里的 /sbin/kc_wp.ko 换成修正版，输出 wp3。

只重打 ramdisk：kernel / dtb / cmdline 原样，末尾补零到 16 MiB。
"""
import gzip
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'image'))
import mkhybrid as M

# 参与重打包的原厂镜像和中间产物不进仓库，用 KC_IMG_DIR 指向存放它们的目录。
IMG_DIR = os.environ.get('KC_IMG_DIR', os.path.join(HERE, '..', '..', 'images'))

SRC = os.path.join(IMG_DIR, 'twrp-kyl23-wp2.img')
OUT = os.path.join(IMG_DIR, 'twrp-kyl23-wp3.img')
KO = os.environ.get('KC_KO', os.path.join(
    HERE, '..', '..', 'device', 'kyocera', 'msm8926-common',
    'prebuilt', 'kc_wp.ko'))
SH = os.path.join(HERE, '..', 'flash', 'wp_fix.sh')
SIZE = 16777216


def main():
    d = open(SRC, 'rb').read()
    p = M.split_boot(d)
    raw = gzip.decompress(p['ramdisk'])
    ents, end = M.cpio_parse(raw)
    print('src: cpio %d entries, %d/%d bytes' % (len(ents), end, len(raw)))

    idx = [i for i, e in enumerate(ents) if e['name'] == b'sbin/kc_wp.ko']
    if not idx:
        raise SystemExit('wp2 里没有 sbin/kc_wp.ko')

    for name, src, ino in ((b'sbin/kc_wp.ko', KO, 0xED000001),
                           (b'sbin/wp_fix.sh', SH, 0xED000002)):
        i = [k for k, e in enumerate(ents) if e['name'] == name][0]
        old = ents[i]['data']
        new = open(src, 'rb').read()
        print('%s: %d -> %d bytes' % (name.decode(), len(old), len(new)))
        ents[i] = M.cpio_make(name, 0o100755, new, ino=ino)

    new_raw = M.cpio_build(ents)
    new_gz = gzip.compress(new_raw, 6, mtime=0)
    print('ramdisk.gz: %d -> %d bytes' % (len(p['ramdisk']), len(new_gz)))

    img = M.make_boot(p['kernel'], new_gz, p['dtb'], p['cmdline'])
    if len(img) > SIZE:
        raise SystemExit('image %d > %d' % (len(img), SIZE))
    img += b'\0' * (SIZE - len(img))
    open(OUT, 'wb').write(img)
    print('out: %s  %d bytes  md5=%s'
          % (OUT, len(img), hashlib.md5(img).hexdigest()))


if __name__ == '__main__':
    main()
