#!/usr/bin/env python3
"""在现有 twrp-kyl23-wp.img 的基础上增量重打包：

  * 加 /sbin/kc_wp.ko、/sbin/wp_fix.sh
  * init.rc 里把 "write .../mmc_protect/clear" 换成 exec wp_fix.sh

kernel / dtb / cmdline 原样保留，只重打 ramdisk，输出仍 pad 到 16 MiB。
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

SRC = os.path.join(IMG_DIR, 'twrp-kyl23-wp.img')
OUT = os.path.join(IMG_DIR, 'twrp-kyl23-wp2.img')
KO = os.environ.get('KC_KO', os.path.join(
    HERE, '..', '..', 'device', 'kyocera', 'msm8926-common',
    'prebuilt', 'kc_wp.ko'))
SH = os.path.join(HERE, '..', 'flash', 'wp_fix.sh')
SIZE = 16777216

OLD_CLEAR = (b'    # aboot re-arms the eMMC write protect on every boot, at the card level\n'
             b'    # (WP groups), so only CMD29 can lift it.  mmc_protect.ko does that for\n'
             b'    # the two partitions TWRP has to write.\n'
             b'    wait /dev/block/mmcblk0p12 10\n'
             b'    write /sys/kernel/mmc_protect/clear mmcblk0p12\n'
             b'    write /sys/kernel/mmc_protect/clear mmcblk0p11\n')

NEW_CLEAR = (b'    wait /dev/block/mmcblk0p12 10\n'
             b'    # aboot re-arms the card-level write protect on every boot; '
             b'only CMD29 lifts it.\n'
             b'    # mmc_protect.ko passes start_sect<<9 (a byte address) but '
             b'this eMMC is >2GB\n'
             b'    # and addresses WP groups in sectors, so its CMD29 lands 512x '
             b'too far.\n'
             b'    # kc_wp.ko sweeps the whole partition in both units and '
             b're-checks.\n'
             b'    exec /sbin/sh /sbin/wp_fix.sh\n')


def main():
    d = open(SRC, 'rb').read()
    p = M.split_boot(d)
    print('src: kernel=%d ramdisk=%d dtb=%d page=%d'
          % (len(p['kernel']), len(p['ramdisk']), len(p['dtb']), p['page']))

    raw = gzip.decompress(p['ramdisk'])
    ents, end = M.cpio_parse(raw)
    print('cpio: %d entries, %d bytes used of %d'
          % (len(ents), end, len(raw)))

    names = {e['name'] for e in ents}

    # --- init.rc -------------------------------------------------------
    rc = [e for e in ents if e['name'] == b'init.rc']
    if not rc:
        raise SystemExit('init.rc not found')
    txt = rc[0]['data']
    if OLD_CLEAR not in txt:
        raise SystemExit('init.rc: 找不到原来的 write clear 段，拒绝瞎改')
    txt = txt.replace(OLD_CLEAR, NEW_CLEAR)
    if b'insmod /sbin/kc_wp.ko' not in txt:
        anchor = b'    insmod /sbin/mmc_protect.ko\n'
        if anchor not in txt:
            raise SystemExit('init.rc: 找不到 insmod mmc_protect.ko')
        txt = txt.replace(anchor, anchor + b'    insmod /sbin/kc_wp.ko\n', 1)
    rc[0]['data'] = txt
    rc[0]['f'][6] = len(txt)
    print('init.rc: %d -> %d bytes' % (len(rc[0]['data']), len(txt)))

    # --- 新文件 ---------------------------------------------------------
    ko = open(KO, 'rb').read()
    sh = open(SH, 'rb').read()
    ino = 0xED000000
    for name, blob in ((b'sbin/kc_wp.ko', ko), (b'sbin/wp_fix.sh', sh)):
        if name in names:
            raise SystemExit('ramdisk 里已经有 %s' % name.decode())
        ents.insert(len(ents) - 1,          # 保持 TRAILER!!! 在最后
                    M.cpio_make(name, 0o100755, blob, ino=ino))
        ino += 1
        print('+ /%s (%d bytes)' % (name.decode(), len(blob)))

    # --- 重新打包 -------------------------------------------------------
    new_raw = M.cpio_build(ents)
    print('new cpio: %d bytes' % len(new_raw))
    new_gz = gzip.compress(new_raw, 6, mtime=0)
    print('new ramdisk.gz: %d bytes (was %d)' % (len(new_gz), len(p['ramdisk'])))

    img = M.make_boot(p['kernel'], new_gz, p['dtb'], p['cmdline'])
    if len(img) > SIZE:
        raise SystemExit('image %d bytes > %d' % (len(img), SIZE))
    img += b'\0' * (SIZE - len(img))
    open(OUT, 'wb').write(img)

    print('out: %s  %d bytes  md5=%s' % (OUT, len(img),
                                          hashlib.md5(img).hexdigest()))


if __name__ == '__main__':
    main()
