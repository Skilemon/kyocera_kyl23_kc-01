#!/usr/bin/env python3
"""wp5 -> wp6：把原厂 mmc_protect.ko 彻底移除（insmod 行 + ramdisk 里的文件）。

它在 sd 卡上地址算错（start_sect<<9 当字节地址，本卡 >2GB 按扇区），
CMD29 全部 OUT_OF_RANGE，clear 却报"成功"；留着我反而误导手动排查。
kc_wp.ko 已经把清除和诊断全包了。
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

SRC = os.path.join(IMG_DIR, 'twrp-kyl23-wp5.img')
OUT = os.path.join(IMG_DIR, 'twrp-kyl23-wp6.img')
SIZE = 16777216
LINE = b'    insmod /sbin/mmc_protect.ko\n'


def main():
    d = open(SRC, 'rb').read()
    p = M.split_boot(d)
    ents, _ = M.cpio_parse(gzip.decompress(p['ramdisk']))
    print('src: %d entries, ramdisk.gz=%d' % (len(ents), len(p['ramdisk'])))

    i = [k for k, e in enumerate(ents) if e['name'] == b'init.rc'][0]
    txt = ents[i]['data']
    if LINE not in txt:
        raise SystemExit('init.rc 里没有 mmc_protect 的 insmod 行')
    txt = txt.replace(LINE, b'', 1)
    ents[i] = M.cpio_make(b'init.rc', 0o100750, txt, ino=0xED000010)
    print('init.rc: 去掉 insmod mmc_protect.ko，剩 %d bytes' % len(txt))

    drop = [k for k, e in enumerate(ents) if e['name'] == b'sbin/mmc_protect.ko']
    for k in drop:
        print('drop sbin/mmc_protect.ko (%d bytes)' % len(ents[k]['data']))
    ents = [e for k, e in enumerate(ents) if k not in drop]

    gz = gzip.compress(M.cpio_build(ents), 6, mtime=0)
    print('ramdisk.gz: %d -> %d' % (len(p['ramdisk']), len(gz)))
    img = M.make_boot(p['kernel'], gz, p['dtb'], p['cmdline'])
    if len(img) > SIZE:
        raise SystemExit('image %d > %d' % (len(img), SIZE))
    img += b'\0' * (SIZE - len(img))
    open(OUT, 'wb').write(img)
    print('out: %s %d bytes md5=%s' % (OUT, len(img),
                                       hashlib.md5(img).hexdigest()))


if __name__ == '__main__':
    main()
