#!/sbin/sh
# 手动清写保护（兜底/调试用）。
#
# 正常情况下不需要跑这个：kc_wp.ko 在 insmod 后 4 秒会自己在 workqueue 里
# 把 mmcblk0p12 / mmcblk0p11 的写保护清掉，整个过程只走 dmesg，不碰 /tmp
# （TWRP 起来后会重挂 /tmp，init 阶段写的日志会被盖掉，这也是为什么之前
#  /tmp/wp_fix.log 一直"找不到"）。

for p in mmcblk0p12 mmcblk0p11; do
    [ -e /dev/block/$p ] || { echo "--- $p 不存在，跳过"; continue; }
    echo "--- autofix $p"
    printf 'autofix %s' "$p" > /sys/kernel/kc_wp/run
done

echo "--- dmesg ---"
dmesg | grep kc_wp | tail -40
