#!/sbin/sh
# eMMC 写保护清理，由 init.rc 在 class_start default 之后 exec 一次。
#
# aboot 每次上电都会用 CMD28 把 boot / recovery / system 三片区域按 WP group
# 置上保护，保护位是易失的、只在卡上，换内核不影响。写的时候不会报错，
# 数据被丢弃 —— 表现为 dd / package_extract_file 返回成功、回读没变。
#
# kc_wp.ko 的 delayed work 只会清它自己写死的那一组（rodata 里的
# "mmcblk0p12 mmcblk0p11"），system 不在里面。刷 lineage 的 system.img
# 时 1.4 GB 会被整段丢弃，重启还是原厂系统，所以这里必须补上 p19。
#
# 分区号取自 docs/DEVICE_NOTES.md：
#   mmcblk0p11 = boot    (16 MiB)
#   mmcblk0p12 = recovery(16 MiB)
#   mmcblk0p19 = system  (1404 MiB)
#
# init 阶段没有 /tmp（TWRP 起来后会重挂），日志一律走 kernel log，
# 进 TWRP 后 `dmesg | grep kc_wp_fix` 就能看到结果。

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
