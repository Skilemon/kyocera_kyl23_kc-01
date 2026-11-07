#!/usr/bin/env python3
"""wp4 -> wp5：换 kc_wp.ko（自带开机自动清除）、换 wp_fix.sh、init.rc 去掉 exec。

aboot 每次上电都会重新置位写保护，所以必须开机自清。但 init.rc 的 exec 路线
不可靠：/dev 节点出现时机不定、/tmp 会被 TWRP 重挂（日志随之消失）。
改成模块 insmod 后延时 4s 自己在 workqueue 里清，日志只进 dmesg。
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

SRC = os.path.join(IMG_DIR, 'twrp-kyl23-wp4.img')
OUT = os.path.join(IMG_DIR, 'twrp-kyl23-wp5.img')
KO = os.environ.get('KC_KO', os.path.join(
    HERE, '..', '..', 'device', 'kyocera', 'msm8926-common',
    'prebuilt', 'kc_wp.ko'))
SH = os.path.join(HERE, '..', 'flash', 'wp_fix.sh')
SIZE = 16777216

OLD = (b'    wait /dev/block/mmcblk0p12 10\n'
       b'    # aboot re-arms the card-level write protect on every boot; '
       b'only CMD29 lifts it.\n'
       b'    # mmc_protect.ko passes start_sect<<9 (a byte address) but '
       b'this eMMC is >2GB\n'
       b'    # and addresses WP groups in sectors, so its CMD29 lands 512x '
       b'too far.\n'
       b'    # kc_wp.ko sweeps the whole partition in both units and '
       b're-checks.\n'
       b'    exec /sbin/sh /sbin/wp_fix.sh\n')

NEW = (b'    # aboot re-arms the card-level write protect on every boot, so\n'
       b'    # something has to lift it (CMD29) after the eMMC is up.\n'
       b'    # kc_wp.ko does that itself: a delayed work 4s after insmod,\n'
       b'    # retried until /dev/block/mmcblk0p12 exists.  Do not exec a\n'
       b'    # script here: /dev nodes are late and TWRP remounts /tmp, which\n'
       b'    # ate the log we relied on.\n')


def main():
    d = open(SRC, 'rb').read()
    p = M.split_boot(d)
    ents, _ = M.cpio_parse(gzip.decompress(p['ramdisk']))
    print('src: %d entries, ramdisk.gz=%d' % (len(ents), len(p['ramdisk'])))

    # init.rc: 去掉 wait + exec
    i = [k for k, e in enumerate(ents) if e['name'] == b'init.rc'][0]
    txt = ents[i]['data']
    if OLD not in txt:
        raise SystemExit('init.rc: 找不到旧的 wait/exec 段')
    txt = txt.replace(OLD, NEW, 1)
    ents[i] = M.cpio_make(b'init.rc', 0o100750, txt, ino=0xED000010)
    print('init.rc: %d bytes, exec 已移除' % len(txt))

    # kc_wp.ko / wp_fix.sh 覆盖
    for name, src, ino in ((b'sbin/kc_wp.ko', KO, 0xED000001),
                           (b'sbin/wp_fix.sh', SH, 0xED000002)):
        k = [j for j, e in enumerate(ents) if e['name'] == name][0]
        old = ents[k]['data']
        new = open(src, 'rb').read()
        print('%s: %d -> %d' % (name.decode(), len(old), len(new)))
        ents[k] = M.cpio_make(name, 0o100755, new, ino=ino)

    gz = gzip.compress(M.cpio_build(ents), 6, mtime=0)
    img = M.make_boot(p['kernel'], gz, p['dtb'], p['cmdline'])
    if len(img) > SIZE:
        raise SystemExit('image %d > %d' % (len(img), SIZE))
    img += b'\0' * (SIZE - len(img))
    open(OUT, 'wb').write(img)
    print('out: %s %d bytes md5=%s' % (OUT, len(img),
                                       hashlib.md5(img).hexdigest()))


if __name__ == '__main__':
    main()
