#!/sbin/sh
# =============================================================================
#  eMMC 写保护 清理 + 验证 + 刷入     （kc_wp.ko 第 2 版）
#
#  注：kc_wp.ko 现在会在 insmod 后 4 秒自己清一遍（日志只进 dmesg），
#  这个脚本用于"手动补一刀 + 写入验证 + 刷镜像"，也可以用来验证自动清除
#  到底有没有生效（看 dmesg 里 boot: 那几行）。
#
#  本版修的是"autofix 拼路径"这一处：把裸名字 "mmcblk0p12" 直接交给
#  blkdev_get_by_path() 等于相对路径，kern_path 必然 -ENOENT(-2)，
#  所以日志里是 blkdev_get_by_path(mmcbk0p12) -> -2。现在模块内部统一
#  补成 /dev/block/%s，调用方给裸名字就行。
#
#  上一版修的是"拿不到卡"这一步：
#    mmcblk0p12 是分区盘，它的 gendisk 由 add_partition() 建立，
#    block/partition-generic.c 根本不设 driverfs_dev（alloc_disk_node 把它
#    初始化成 NULL），只有整盘 mmcblk0 才 driverfs_dev = &card->dev。
#    上一版直接 container_of(disk->driverfs_dev) 拿到 NULL → 报
#    "no gendisk/driverfs_dev"；兜底路径 /dev/block/mmcblk0 在不存在的节点上
#    lookup_bdev 返回 -2。现在沿 bd_contains 上溯一层再取 card。
#
#  用法：
#    adb push kc_wp.ko twrp-kyl23-wp6.img wpcheck.sh /sdcard/
#    adb shell sh /sdcard/wpcheck.sh
# =============================================================================

IMG=${IMG:-/sdcard/twrp-kyl23-wp6.img}
[ -f "$IMG" ] || IMG=/sdcard/twrp-kyl23-wp5.img
KO=${KO:-/sdcard/kc_wp.ko}
DEV=/dev/block/mmcblk0p12
BOOT=/dev/block/mmcblk0p11
MAGIC=4b4357504f4b3031

say() { echo; echo "===== $* ====="; }

say "0 环境"
echo "kernel: $(uname -r)"
ls -l $DEV $BOOT 2>&1
echo "ramdisk 自带模块: $(ls -l /sbin/kc_wp.ko 2>&1)"
echo "原厂模块: $(ls /sbin/mmc_protect.ko 2>&1 | tail -1)  (wp6 起已移除)"

say "1 换成新版 kc_wp.ko"
if [ ! -f "$KO" ]; then
    echo "!! 找不到 $KO，先 adb push 上去"
    exit 1
fi
if [ -d /sys/kernel/kc_wp ]; then
    echo "内存里已有一个旧版模块，先卸载"
    rmmod kc_wp 2>/dev/null || /sbin/rmmod kc_wp 2>/dev/null
    sleep 1
    if [ -d /sys/kernel/kc_wp ]; then
        echo "!! rmmod 没成功（模块还被引用）。"
        echo "   reboot recovery 之后把新版 push 成 /sdcard/kc_wp.ko 再来。"
        exit 1
    fi
    echo "旧模块已卸载"
fi
insmod "$KO" 2>&1 || insmod /sbin/kc_wp.ko 2>&1
if [ ! -d /sys/kernel/kc_wp ]; then
    echo "!! insmod 失败，看 dmesg："
    dmesg | tail -15
    exit 1
fi
echo "新模块已加载"
dmesg | tail -6

say "2 清理 p12 / p11"
for p in mmcblk0p12 mmcblk0p11; do
    if [ -e /dev/block/$p ]; then
        echo "--- autofix $p"
        printf 'autofix %s' "$p" > /sys/kernel/kc_wp/run
        sleep 1
    else
        echo "--- $p 不存在，跳过"
    fi
done
echo "--- dmesg ---"
dmesg | grep kc_wp | tail -40

say "3 写入验证（8 字节魔数，绕过页缓存）"
echo "写前前 8 字节:"
dd if=$DEV bs=8 count=1 2>/dev/null | hexdump -v -e '8/1 "%02x"'; echo
printf 'KCWPOK01' | dd of=$DEV bs=1 count=8 conv=notrunc 2>/dev/null
sync
echo 3 > /proc/sys/vm/drop_caches
sync
got=$(dd if=$DEV bs=8 count=1 2>/dev/null | hexdump -v -e '8/1 "%02x"')
echo "读回:        $got"
echo "期望:        $MAGIC"

if [ "$got" != "$MAGIC" ]; then
    say "FAIL 魔数没写进去（写入被丢弃），保护还在"
    echo "--- EXT_CSD ---"
    printf 'info' > /sys/kernel/kc_wp/run
    sleep 1
    dmesg | grep kc_wp | tail -50
    echo
    echo "把上面 autofix 的 基线 / 复查 两行、以及 EXT_CSD 发回来。"
    echo "（p11 没动，recovery 还是现在这个能进的版本）"
    exit 2
fi

say "PASS 写保护已解除，开始刷入"
if [ ! -f "$IMG" ]; then
    echo "!! 找不到 $IMG，跳过刷写。写保护已解除，手动 dd 即可。"
    exit 0
fi
echo "镜像 md5: $(md5sum "$IMG" | cut -d' ' -f1)"
dd if="$IMG" of=$DEV bs=16384 2>/dev/null
sync
echo 3 > /proc/sys/vm/drop_caches
sync
echo "回读 md5: $(dd if=$DEV bs=16384 count=1024 2>/dev/null | md5sum | cut -d' ' -f1)"

say "完成"
echo "两个 md5 相同 → 刷入成功，reboot recovery 即可。"
echo "之后每次开机 init.rc 都会自动跑 wp_fix.sh，日志在 /tmp/wp_fix.log。"
