#!/sbin/sh
# 手动兜底：怀疑写保护没解时补一刀。
#
# 正常情况下不需要跑这个 —— kc_wp.ko 的 `parts` 默认值就是
# "mmcblk0p12 mmcblk0p11 mmcblk0p19"（recovery / boot / system），insmod 后
# 4 秒它自己在 delayed work 里清完，不依赖 init.rc。
#
# aboot 每次上电都会用 CMD28 把 boot / recovery / system 三片区域按 WP group
# 置上保护，保护位是易失的、只在卡上，换内核不影响。写的时候不会报错，
# 数据被丢弃 —— 表现为 dd / package_extract_file 返回成功、回读没变。
#
# 分区号取自 docs/DEVICE_NOTES.md：
#   mmcblk0p11 = boot    (16 MiB)
#   mmcblk0p12 = recovery(16 MiB)
#   mmcblk0p19 = system  (1404 MiB)
#
# init 阶段没有 /tmp（TWRP 起来后会重挂），日志一律走 kernel log，
# `dmesg | grep kc_wp_fix` 就能看到结果。

log() { echo "kc_wp_fix: $*" > /dev/kmsg 2>/dev/null; }

if [ ! -d /sys/kernel/kc_wp ]; then
    log "sysfs missing (kc_wp.ko not loaded), give up"
    exit 0
fi

for p in mmcblk0p12 mmcblk0p11 mmcblk0p19; do
    n=0
    while [ ! -e /dev/block/$p ] && [ $n -lt 10 ]; do
        sleep 1
        n=$((n + 1))
    done
    if [ ! -e /dev/block/$p ]; then
        log "$p missing, skip"
        continue
    fi
    log "autofix $p ..."
    printf 'autofix %s' "$p" > /sys/kernel/kc_wp/run
    sleep 1
done

log "all done"
