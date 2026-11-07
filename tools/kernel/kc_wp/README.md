# kc_wp.ko — 解除 eMMC 卡级写保护

TWRP 要写 recovery 分区，必须先解掉卡上的写保护，而这件事用户态做不了：
`aboot` 每次上电用 **CMD28** 把 WP group 置成临时保护，只有 **CMD29** 能解，
CMD29 是 mmc 核心命令，必须在内核里发。这就是这个模块存在的全部理由。

## 与内核的关系

必须用**设备上实际运行的那棵内核源码树**编译，`vermagic` 要逐字一致：

```
vermagic=3.4.0 SMP preempt mod_unload modversions ARMv7
```

本项目的内核 release 固定为 `3.4.0`，靠三件事保证：

- `CONFIG_LOCALVERSION=""`
- `CONFIG_LOCALVERSION_AUTO=n`
- 源码树里不能有 `.scmversion` 文件（否则会多出 `-g<sha>` 或 `+`）

源码树 = 京瓷 GPL 3.4.0 + `kernel-patches/0001-kyocera-3.4.0-build-with-gcc13-and-drop-kc-insmod-hook.patch`。
原厂内核里的 `selinux_kernel_setup_load_info` 会拒绝 init 加载任何非 wlan 模块，
补丁已把它改成 `return 0`。

## 编译

```sh
make -C <kernel-src> M=$PWD ARCH=arm CROSS_COMPILE=arm-linux-gnueabi- modules
```

`arm-linux-gnueabi-` 用哪个版本都行，只要 gcc 能编 3.4 的代码。产物 `kc_wp.ko`
直接放进 `device/kyocera/msm8926-common/prebuilt/`，CI 会用 `--module` 注入到
`/sbin/` 并在 `init.rc` 的 `on init` 段 `insmod`。

## 加载与参数

```sh
insmod /sbin/kc_wp.ko
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `parts` | `mmcblk0p12 mmcblk0p11` | 开机要清的分区，空格分隔 |
| `autofix` | `1` | `0` = 关掉自动清除，只留手动命令 |
| `delay` | `4000` | insmod 后等多少毫秒再动手 |
| `retry` | `15` | 设备节点没就绪时重试次数，每次间隔 500ms |

自动清除跑在模块自己的 delayed work 里，**不依赖 `init.rc` 的 `exec`**：
`/dev/block/*` 由 ueventd 在 `class_start` 之后才建，时序不定；而 `exec` 那条路
还会把日志写进 `/tmp`，TWRP 启动时会把 `/tmp` 重挂成新的 tmpfs，日志直接消失。
现在所有输出只走 `dmesg`，重启后还能在 `last_kmsg` 里查到。

## 手动命令

```sh
echo info > /sys/kernel/kc_wp/run                  # EXT_CSD: USER_WP / WR_REL_SET / SECURE_WP
echo "autofix mmcblk0p12" > /sys/kernel/kc_wp/run  # 清一个分区并复查
echo "31 0x2f800" > /sys/kernel/kc_wp/run          # 原始 CMD31，只读
```

分区名可以给裸名字（模块内部补 `/dev/block/` 前缀），也可以给绝对路径。
**必须用 `printf`/`echo` 且不能带尾随换行以外的杂质**——早期版本把 `\n`
拼进路径导致 `lookup_bdev` 一直 `-ENOENT`。

## 为什么不用原厂的 mmc_protect.ko

它把 `start_sect << 9`（字节地址）当 CMD29 的参数。JEDEC 规定容量超过 2 GB 的
卡改用**扇区**寻址，于是每条命令都落在 512 倍远的地方；实测
`CMD31 arg=0x05f00000` 返回 `-110 / OUT_OF_RANGE`，可它的 `clear` 仍然打印成功。
`kc_wp.ko` 改成从 `bd_part->start_sect` 取扇区号，按 512 扇区（256KB）步长扫完
整个分区——比任何 eMMC 的 WP group 都小，保证每个组的起点都被踩到。

## 三个踩过的坑

1. **`lookup_bdev()` 不打开设备。** 它只做 `bd_acquire()`，返回的 `bdev` 上
   `bd_part`、`bd_contains` 全是 `NULL`。要分区信息必须
   `blkdev_get_by_path(path, FMODE_READ, NULL)`，用完 `blkdev_put()`。
2. **分区盘没有 `driverfs_dev`。** `mmcblk0pN` 的 gendisk 由 `add_partition()`
   建立，`block/partition-generic.c` 不设这个字段；只有整盘 `mmcblk0` 才是
   `driverfs_dev = &card->dev`。要 `container_of` 出 `mmc_card`，得沿
   `bd_contains` 上溯一层。
3. **CMD29 的地址单位随容量变。** ≤2GB 用字节，>2GB 用扇区。这台是 4GB+，
   所以按字节算的命令全部越界，而且卡对越界命令的返回和“成功”长得一样。
