#!/sbin/sh
# ---------------------------------------------------------------------------
# wipe_data.sh — 格式化 userdata (mmcblk0p20) / 清 cache
#
# 在哪跑：TWRP 终端，或系统内 root shell。不要在 DL 模式跑。
# 用法：
#   sh /data/local/tmp/wipe_data.sh            # 只清 data
#   sh /data/local/tmp/wipe_data.sh --cache    # 顺手清 cache
#   sh /data/local/tmp/wipe_data.sh --dry-run  # 只检查，不写
#
# 为什么不用 dd 写零：data 有 5 GB，走不了这个通道。
# 为什么不用 DL 模式：DL 通道只有 read/write，没有 ERASE；写零 5 GB 不现实。
# 所以清 data 只能在 TWRP / root 下做，本脚本就是这个动作。
#
# 文件系统特性：
#   本机 twrp-kyl23.img 里的 mke2fs 是 e2fsprogs 1.42.9，ramdisk 的 /etc/mke2fs.conf
#   把 ext4 默认特性钉成 has_journal,extent,huge_file,flex_bg,uninit_bg,dir_nlink,
#   extra_isize —— 没有 64bit / metadata_csum，3.4.0 内核全支持，直接用就行。
#   换成带 e2fsprogs >=1.43 的 TWRP 时，metadata_csum（>=1.43）和 64bit（>=1.44）
#   会变成默认，格式化"成功"但内核挂不上，表现为无限重启且没有报错指向文件系统。
#   所以下面按版本分三级显式关特性，最后一定 mount 验证一次。
# ---------------------------------------------------------------------------

set -u

DATA_DEV=""
CACHE_DEV=""
DRY=0
DO_CACHE=0

for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --cache)   DO_CACHE=1 ;;
    -h|--help) sed -n '2,20p' "$0" 2>/dev/null; exit 0 ;;
  esac
done

say() { echo "$*"; }
die() { echo "✗ $*"; exit 1; }

# --- 找块设备：优先 by-name，退回固定节点号
find_dev() {
  name="$1"; node="$2"
  for p in /dev/block/bootdevice/by-name/$name \
           /dev/block/platform/msm_sdcc.1/by-name/$name \
           /dev/block/by-name/$name; do
    [ -e "$p" ] && { echo "$p"; return 0; }
  done
  [ -e "$node" ] && { echo "$node"; return 0; }
  return 1
}

DATA_DEV=$(find_dev userdata /dev/block/mmcblk0p20) || die "找不到 userdata 分区"
CACHE_DEV=$(find_dev cache /dev/block/mmcblk0p21) || CACHE_DEV=""

say "data  : $DATA_DEV"
[ -n "$CACHE_DEV" ] && say "cache : $CACHE_DEV"
say "大小  : $(blockdev --getsize64 "$DATA_DEV" 2>/dev/null || echo '?') 字节"

# --- 写保护自检（data 本来就没有保护，这里只是确认没被别的东西挡住）
if [ -e /sys/kernel/mmc_protect/state ]; then
  say "写保护: $(cat /sys/kernel/mmc_protect/state 2>/dev/null | head -1)"
fi

# --- 卸载
say ""
say "── 卸载 ──"
for m in /data /sdcard /mnt/sdcard /data/media /cache; do
  if mountpoint -q "$m" 2>/dev/null || grep -q " $m " /proc/mounts 2>/dev/null; then
    umount -l "$m" 2>/dev/null && say "  umount $m" || say "  umount $m 失败（继续）"
  fi
done
umount -l "$DATA_DEV" 2>/dev/null

if [ "$DRY" = "1" ]; then
  say ""
  say "[dry-run] 当前文件系统："
  blkid "$DATA_DEV" 2>/dev/null || say "  (blkid 无输出，可能未格式化)"
  say "[dry-run] 到此为止，没有写任何东西。"
  exit 0
fi

# --- 选格式化工具
MK=""
MKE2FS_OPTS=""
if command -v mke2fs >/dev/null 2>&1; then
  MK="mke2fs"
  ver=$(mke2fs -V 2>&1 | head -1)
  say ""
  say "── 格式化 ──"
  say "  $ver"

  # 3.4 内核不认识的特性一律关掉。分多轮试，因为特性名在不同 e2fsprogs
  # 版本里存在与否不一样（TWRP 自带的是 1.42.9，认 64bit 但没有 metadata_csum）。
  if mke2fs -n -t ext4 -O ^64bit,^metadata_csum,^metadata_csum_seed,^orphan_file \
        -b 4096 -m 0 -L data "$DATA_DEV" >/dev/null 2>&1; then
    MKE2FS_OPTS="-O ^64bit,^metadata_csum,^metadata_csum_seed,^orphan_file"
    say "  已关闭 64bit / metadata_csum / orphan_file"
  elif mke2fs -n -t ext4 -O ^64bit,^metadata_csum -b 4096 -m 0 -L data "$DATA_DEV" >/dev/null 2>&1; then
    MKE2FS_OPTS="-O ^64bit,^metadata_csum"
    say "  已关闭 64bit / metadata_csum"
  elif mke2fs -n -t ext4 -O ^64bit -b 4096 -m 0 -L data "$DATA_DEV" >/dev/null 2>&1; then
    MKE2FS_OPTS="-O ^64bit"
    say "  已显式关闭 64bit（这个版本的 mke2fs 不认 metadata_csum，本来也没有）"
  else
    MKE2FS_OPTS=""
    say "  ! 无法指定特性，用 mke2fs 默认值（下面会 mount 验证，失败就换 make_ext4fs）"
  fi
fi

format_ext4() {
  dev="$1"; label="$2"
  if [ -n "$MK" ]; then
    # shellcheck disable=SC2086
    mke2fs -t ext4 $MKE2FS_OPTS -b 4096 -m 0 -L "$label" "$dev" 2>&1 | tail -5 && return 0
  fi
  if command -v make_ext4fs >/dev/null 2>&1; then
    say "  改用 make_ext4fs"
    sz=$(blockdev --getsize64 "$dev" 2>/dev/null)
    make_ext4fs -s -l "${sz:-5093M}" -a "$label" -L "$label" "$dev" 2>&1 | tail -3
    return 0
  fi
  return 1
}

format_ext4 "$DATA_DEV" data || die "格式化失败"

# --- 挂载验证：这一步不能省，格式化的"成功"不算数
say ""
say "── 挂载验证 ──"
mkdir -p /data
if mount -t ext4 -o rw "$DATA_DEV" /data 2>/dev/null; then
  say "  ✓ 3.4 内核能挂上，文件系统兼容"
  chown 0:0 /data 2>/dev/null
  chmod 0771 /data 2>/dev/null
  df -h /data 2>/dev/null | tail -2
  umount /data 2>/dev/null
else
  say "  ✗ 挂不上！内核不认这个文件系统。"
  say "    别重启，先跑：e2fsck -f -y $DATA_DEV"
  say "    还是不行就用 make_ext4fs 重来，或者从备份写回 userdata.img。"
  exit 8
fi

# --- cache 可选
if [ "$DO_CACHE" = "1" ] && [ -n "$CACHE_DEV" ]; then
  say ""
  say "── cache ──"
  format_ext4 "$CACHE_DEV" cache && say "  ✓ cache 已重建"
fi

say ""
say "完成。可以重启：reboot"
say "首次开机会重建 /data 下的目录，需要 3–10 分钟（屏幕停 logo 是正常现象）。"
