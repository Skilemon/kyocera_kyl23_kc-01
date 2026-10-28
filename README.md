# KC-01/KYL23 移植项目 — 当前状态与使用指南

> 更新：2026-10-28

## 已完成的工作

### 1. 设备全量备份（最重要！）
`D:\KC-01\backup\kc01_backup\` — 41 个分区镜像，共 1.86GB。
包含 boot/recovery/system/modem/persist 等所有分区。
**请把整个 backup 目录复制到另一块磁盘或网盘保存，这是唯一救命稻草。**

系统信息存档：`getprop.txt`、`mounts.txt`、`kernel_version.txt`。

### 2. 移植源码就绪（`D:\KC-01\porting\`）
- `kernel_moto_msm8226/` — 移植用内核
  - 基底：LineageOS thea 内核（Linux 3.4.113，Nougat 就绪，含全部 4.4→7.1 兼容补丁）
  - 已嫁接京瓷设备驱动：
    - 触摸：`atmel_mxt_kc.c` + `kc_ts.c`（含 Makefile/Kconfig 集成）
    - 传感器：全套 YAS 驱动（加速度/磁力/方向/融合）+ SFH7776 光距
    - 电池：京瓷 qpnp-bms + oem/oem-nouim 电池曲线（无 SIM 时自动切换）
    - 板级 DTS：msm8926-720p-mtp（京磁板：NT35590 面板、BMA250、AT24 EEPROM、IDTP90xx）
  - 新增 `kc01_defconfig`（titan 基底 + 京瓷驱动开关）
  - 新增 `CONFIG_MSM_KC01_DTB` 只编译本机 DTB
- `device_kyocera_kc01/` — 设备树（BoardConfig / fstab / init.rc / TWRP/LOS 产品 mk）
  - 分区表、boot.img 参数（base 0、ramdisk_offset 0x01000000、tags 0x100、page 2048、dtb 5MB）
  - 均按真机实测数据填写
- `device_motorola_thea` / `device_motorola_msm8226-common` — 参考母本（bring-up 阶段对照用）
- `.github/workflows/twrp.yml` — GitHub Actions 自动编译 TWRP

### 3. 关键实测参数（来自本机 boot.img 头部解析）
```
kernel_size:  0x0058a350 (KC-01 boot) / recovery 类似
page_size:    2048
base:         0x00000000
kernel_offset 0x00008000  ramdisk_offset 0x01000000
second_offset 0x00f00000  tags_offset   0x00000100
dtb:          appended separately, 5MB (BOARD_KERNEL_SEPARATED_DT)
cmdline:      console=ttyHSL0,115200,n8 ... androidboot.hardware=qcom
```

## 下一步：用 GitHub Actions 编译 TWRP

1. 在 GitHub 建一个 **私有** 仓库（免费额度 2000 分钟/月，够用）
2. 把 `porting/` 下的内容推上去，结构：
   ```
   repo根/
   ├── .github/workflows/twrp.yml
   ├── device/kyocera/kc01/     ← device_kyocera_kc01 内容
   └── kernel/kyocera/kc01/     ← kernel_moto_msm8226 内容
   ```
3. Actions 页面手动触发 `Build TWRP for KC-01/KYL23`
4. 约 3–5 小时后下载 `twrp-kc01` artifact 里的 recovery.img
5. 刷入方法（本机已 root，无需解锁 bootloader）：
   ```
   adb push recovery.img /data/media/0/
   adb shell
   su
   dd if=/data/media/0/recovery.img of=/dev/block/platform/msm_sdcc.1/by-name/recovery
   ```

### 刷入前必读
- **先确认备份完整**（backup 目录 41 个文件 1.86GB 已在电脑上）
- 第一次进 TWRP 如果卡 logo：说明内核/DTB 参数有问题，回滚方式是
  `dd` 写回备份里的 `recovery.img` 原厂镜像即可
- TWRP 能进 = 内核+显示+触摸+存储四关全过，之后 LineageOS 主体编译水到渠成

## 风险与回退
- 高通设备有 9008 (EDL) 救砖模式，且我们持有全部分区镜像，理论上砖了也能救
- persist/modem 分区此次不会触碰（TWRP 不写它们）
