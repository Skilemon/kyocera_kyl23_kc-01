# 写保护解锁模块

`mmc_protect_fix2.ko` 是原厂 `/system/lib/modules/mmc_protect.ko` 的修补版，
用于清除 boot / recovery **/ system** 分区的 eMMC 硬件写保护。用法见 [../../docs/FLASHING.md](../../docs/FLASHING.md)。

> **system 也要清。** aboot 每次上电按 WP group 把 boot / recovery / system 三片区域
> 一起置上保护，写进去不报错、数据被丢弃。kc_wp.ko 自带的 delayed work 只清
> `mmcblk0p12` / `mmcblk0p11`（表写死在模块 rodata 里），**不含 `mmcblk0p19`**。
> 所以 TWRP 由 `init.rc` 在 `class_start default` 之后 exec `/sbin/wp_fix.sh`，
> 对 p12 / p11 / p19 各发一次 CMD29。少了这一步，刷 `system.img` 会「报成功、
> 回读没变」，重启还是原厂系统。

> **TWRP 镜像里已经内置了它**：同一个文件以 `mmc_protect.ko` 的名字放在
> `device/kyocera/msm8926-common/prebuilt/`，构建时由 `mkhybrid.py --module`
> 装进 `/sbin` 并在 `init.rc` 的 `on init` 里自动 `insmod`。进 TWRP 后
> 直接 `printf <分区> > /sys/kernel/mmc_protect/clear` 即可，不用再推文件。
> 这里这份是给**系统内**（Android 已启动）用的，那边得走 `insmod_as_wlan`。

## 原厂模块的两个问题

1. **加载失败**：模块的 `__versions` 段里 7 个 mmc 符号（`mmc_wait_for_cmd`、
   `mmc_wait_for_req`、`__mmc_claim_host` 等）的 CRC 与本机内核的 `__kcrctab` 不符，
   `insmod` 报 `Unknown symbol (err -22)`。本仓库的版本从 vmlinux 里解析出真实 CRC
   并逐条写回，现在可以正常加载。
2. **地址单位错误**：它把 `hd_struct->start_sect`（512 字节扇区）直接作为 CMD29 的
   字节地址发送，差 512 倍，结果清到了卡片最前面而不是目标分区。本版本把该值左移 9 位。

改动仅涉及 `__versions` 的 7 个 CRC 和一条 `lsl` 指令（4 字节），其余原样。

## 加载

原厂内核对模块加载有额外校验（`selinux_kernel_setup_load_info`），普通 `insmod`
会被拒绝，需要用系统自带的包装器：

```bash
su -c '/system/xbin/insmod_as_wlan /data/local/tmp/mmc_protect_fix2.ko'
```

## 接口

| 路径 | 作用 |
|---|---|
| `/sys/kernel/mmc_protect/clear` | 写入分区名（如 `mmcblk0p12`），对该分区发 CMD29 |
| `/sys/kernel/mmc_protect/status` | 打印 WP 位图，`1` 表示该组被保护 |

## 注意

- 分区名写错会让内核 oops（模块没有检查 `lookup_bdev` 的错误指针返回），
  写入前务必确认节点存在。
- 写保护位是易失的，重启后由 bootloader 重新设置，需重新加载并清除。
