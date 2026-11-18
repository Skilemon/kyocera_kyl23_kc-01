# 设备实测笔记

本文件只记录**在真机上验证过**的数据。推测和待验证项单独列在最后，不要混用。

---

## 1. QCDT（设备树表）

这是整个移植里最容易踩、也最致命的地方。

### 表项结构：24 字节 / 6 个字

```
word 0  board_id      8 = MTP
word 1  variant_id    0 / 2 / 5
word 2  soc_rev       0x0 / 0x20000 / 0x10001
word 3  offset        相对 DT 段起点的字节偏移
word 4  size          DTB 字节数
word 5  msm_id        145(0x91)=MSM8226  200(0xC8)=MSM8926  224(0xE0)=MSM8926v2
```

头部：`QCDT` + `version=2` + `num_entries` + 第四个字（原厂写 `145`，即首条的 msm_id）。
原厂 recovery 的头部是 `51 43 44 54 | 02 00 00 00 | b8 00 00 00 | 91 00 00 00`，184 条。

### 关键：`msm_id` 必须在第 6 个字

aboot 用 `(msm_id, board_id, soc_rev)` 三元组匹配。如果工具只写 5 个字（20 字节表），
第 6 个字就是 0，**任何设备都匹配不上**，aboot 找不到可用 DT，屏幕停在 bootloader 的 logo。

这个失败是静默的：内核根本没被加载，dmesg 里什么都不会有，现象和「内核坏了」完全一样。

`device/kyocera/msm8926-common/mkqcdt.py` 专门处理这件事，`tools/image/check_image.py` 会在构建末尾拦住它。

### DTB 内容

原厂 184 条表项背后只有 32 个唯一 DTB。区分同一 board 下 8226 / 8926 的是
**DTB 内部的 `qcom,msm-id` 属性**，它是一组 `(msm_id, soc_rev)` 对：

- 8226 系列：`145, 158, 159, 198, 205, 220, 221, 222, 223`
- 8926 系列：`200, 224`

所以只留 `board_id=8` 的条目、把所有 DTB 统一成一个 8926 MTP 的 DTB 是可行的——
本机实测可以进 recovery。

---

## 2. boot.img 头部（原厂实测）

```
magic          ANDROID!
page_size      2048
kernel_size    5808608 (recovery) / 5808976 (boot)
kernel_addr    0x00008000
ramdisk_size   1224393 (recovery) / 614931 (boot)
ramdisk_addr   0x01000000
second_addr    0x00f00000
tags_addr      0x00000100
dt_size        5179392
cmdline        console=ttyHSL0,115200,n8 no_console_suspend=1
               androidboot.console=ttyHSL0 androidboot.hardware=qcom
               user_debug=31 msm_rtb.filter=0x37
```

`BOARD_KERNEL_BASE := 0x00000000` + `--ramdisk_offset 0x01000000
--second_offset 0x00f00000 --tags_offset 0x00000100` 与之对应。

### 空间预算（16 MiB 分区）

当前 CI 产物（`twrp-kyl23.img`，含中文界面）实测：

| 组成 | 原厂 recovery | 本仓库产物 |
|---|---|---|
| header | 2048 | 2048 |
| kernel | 5,808,608 | 5,808,608 |
| ramdisk（gzip） | 1,224,393 | 8,448,291 |
| DT（QCDT） | 5,179,392 | 1,290,240 |
| 合计 | 12,214,435 | **15,552,512** |
| 分区余量 | 4,562,781 | **1,224,704** |

原厂 DT 有 5.18 MB，是因为整张 QCDT 塞了 8 份完整 DTB。当前用的
`prebuilt/stock/dtb-kyl23.img` 里 **40 条表项一条不少**，但 8 份 DTB 换成了精简版
（每份 159,744 B，即 `prebuilt/dtb/msm8926-mtp.dtb` 那个大小），所以降到 1.29 MB。
表项一条都不能删——塌成 1 条就会卡 logo 3 秒重启（见 7.4）。

中文界面占掉约 3.7 MB 未压缩（字体）+ 45 KB（`zh_CN.xml`），同时删掉 18 个用不上的
语言省回约 860 KB。剩下 1.22 MB 余量，够一次小改动，但**不够再加一套 CJK 字体**。

### 为什么用京瓷源码自编译的内核

> 2026-11 起 `prebuilt/kernel` 已经是从京瓷 GPL 源码编出来的 zImage（见 12.9
> 和 `kernel-patches/README.md`）。下面这段是当初"为什么默认用原厂内核"的
> 记录，对 **dtb 那一半仍然成立**：QCDT 表依旧是原厂那份，不能重新生成。

`prebuilt/kernel` 和 `prebuilt/dtb/msm8926-mtp.dtb` 都是从原厂 `recovery.img` 里原样取出的：

| 文件 | 大小 | 来源 | MD5 |
|---|---|---|---|
| `prebuilt/kernel` | 5,808,608 | `recovery.img` 偏移 2048 | `40aada0058c8b0aadd00f5a5bc75166a` |
| `prebuilt/dtb/msm8926-mtp.dtb` | 159,744 | QCDT 第 81 条（`msm=200 board=8 rev=0x10001`） | `b93f265cda2b9291086322a6e330ca10` |

这一对是**唯一在真机上验证过能启动**的组合：用它写回 recovery 分区后能正常进入原厂
recovery，随后把 DT 换成精简版也仍然能进。TWRP 换掉的是 ramdisk，内核和 DT 保持不变，
变量最少。

DTB 内部属性（读出来核对过）：

```
qcom,msm-id   = 200 0, 224 0, 200 0x10001, 224 0x10001     # 8926 与 8926v2，两档 soc_rev
qcom,board-id = 8 0                                        # MTP
model         = "Qualcomm MSM 8926 MTP"                    # 与 dmesg 的 Machine: 行一致
```

从源码编内核（留给 ROM 阶段）只能用 LineageOS 的 msm8226 4.4.113 内核加
`kernel-overlay/`，手工跑；CI 不再提供开关，因为 TWRP 的构建树里
`build/core/tasks/kernel.mk` 压根没被 `main.mk` include。**这条路还没有在任何真机上
验证过**，尤其是 overlay 里的 `msm8926-720p-mtp.dts` 只是 QC 通用模板（没有京瓷的
触摸屏、面板、传感器节点），编出来的 DTB 大概率能点亮但屏幕和触摸不工作。要投入这条路，
第一步应该是把原厂 DTB 反编译成 `dts` 作为基线，而不是从通用模板开始。

---

## 2.1 两个代号共用一套 prebuilt

`device/kyocera/kyl23` 和 `device/kyocera/kc01` 只是同一块 msm8926 板的两个产品代号：

| | kyl23 | kc01 |
|---|---|---|
| 原厂版本 | 2016，`201.1.0a20` | 2015，`102.0.1e20` |
| `PRODUCT_DEVICE` | `kyl23` | `kc01` |
| `TW_DEVICE_VERSION` | `kyl23-unofficial` | `kc01-unofficial` |
| 内核 / ramdisk / QCDT | `msm8926-common/prebuilt/` | 同一份 |

所以 CI 里 `device=all` 跑出来的是两个只有 build 属性不同的镜像：`mka recoveryimage`
各编一遍，`mkhybrid.py` 用同一份原厂 ramdisk 组装两次。这样做的代价只有 runner 时间。

真要区分硬件，就在设备树里放自己的 prebuilt，并把 `BoardConfigCommon.mk` 里的
`TARGET_PREBUILT_KERNEL` 指过去（或让设备自己的 `BoardConfig.mk` 覆盖它），
`dt` 同理。判断依据是原厂 `recovery.img` 头部：`kernel_size` / `ramdisk_size` /
`dt_size` 只要有一个不同，就不是同一套二进制，必须分开。

---

## 3. eMMC 写保护

**boot 和 recovery 分区在运行时有硬件写保护，`cache` 和 `data` 没有。**

表现：

- `dd` 报告 `1797+0 records out` 且 `sync` 成功，但读回来还是旧数据
- `blockdev --getro` 返回 0，看起来可写
- CSD 里 `WP_GRP_ENABLE=1`、`WP_GRP_SIZE=15`（16 × 512 KB = 8 MB 一组）

清除方法：给 MMC 发 **CMD29 (CLR_WRITE_PROT)**。原厂在
`/system/lib/modules/mmc_protect.ko` 里实现了这个模块（`/sys/kernel/mmc_protect/clear`，
写入分区名如 `mmcblk0p12`），但原厂模块有两个问题：

1. 它用 `CONFIG_MODVERSIONS` 的 CRC 表，内核版本不匹配时 `insmod` 直接失败
   （`Unknown symbol (err -22)`）
2. 它把 `start_sect`（512 字节扇区）直接当字节地址发给 CMD29，地址差了 512 倍

修好之后 3 轮循环即可清掉整个 16 MiB 分区，具体流程见 [FLASHING.md](FLASHING.md)。

注意：**写保护位是易失的**，每次上电由 bootloader 重新设置。所以「解锁 → 写入」必须
在同一个上电周期内完成，中间重启就白做。

---

## 4. 分区

节点号来自 `cat /proc/partitions`，名称来自 `ls /dev/block/platform/msm_sdcc.1/by-name/`。
注意 `/dev/block/bootdevice/by-name/` 在这台机器上**不存在**（老式布局），别照抄新机型的路径。

| 名称 | 节点 | 大小 | 用途 |
|---|---|---|---|
| modem | mmcblk0p1 | 64 MiB | 基带 |
| boot | **mmcblk0p9** | 16 MiB | 内核（有写保护） |
| tz | mmcblk0p10 | 1 MiB | TrustZone |
| tzbak | mmcblk0p11 | 1 MiB | TrustZone 备份（**不是 boot**） |
| recovery | mmcblk0p12 | 16 MiB | recovery（有写保护） |
| system | mmcblk0p19 | 1,404 MiB | 系统 |
| bootwork | mmcblk0p24 | 4 MiB | boot 的工作槽 |
| userdata | mmcblk0p20 | 5,093 MiB | 数据 |
| cache | mmcblk0p21 | 458 MiB | 缓存（无保护） |
| log | mmcblk0p22 | 20 MiB | **Kyocera ram console，最近一次启动的完整 dmesg** |
| logwork | mmcblk0p23 | 20 MiB | 上一条的备份槽 |
| misc | mmcblk0p26 | 6 MiB | BCB |
| DDR | mmcblk0p27 | 1 MiB | 太小，装不下内存转储 |
| persist | mmcblk0p28 | 8 MiB | 单机校准 |
| carrier | mmcblk0p32 | 8 MiB | 运营商配置 |
| sysprop | mmcblk0p37 | 8 MiB | 系统属性分区 |

> **2026-11 订正：boot 是 mmcblk0p9，之前写的 mmcblk0p11 是错的。**
>
> 依据是设备上 `ls -l /dev/block/platform/msm_sdcc.1/by-name/` 与
> `cat /proc/partitions` 实测：`boot -> mmcblk0p9`（16384 KB = 16 MiB），
> `tzbak -> mmcblk0p11`（1024 KB = 1 MiB）。kc_wp 模块按 `p11` 清保护时，
> 内核读到的是 `start_sect=192512 nr_sects=2048`，1 MiB 根本装不下一个
> boot.img（内核 5.7 MB + ramdisk 8.3 MB），等于一直在清 tzbak，
> 真正的 boot 从未被解锁 —— 刷进去的内核被卡静默丢弃，重启照旧走原厂内核。
>
> 教训：**清写保护要传分区名，不要传 `mmcblk0pN`。** 现在的 kc_wp 用
> by-name 解析，名字对就不会错。

**拿到崩溃现场的正确方式是 `log` 分区，不是 pstore。** 这台机器的内核没编
`CONFIG_PSTORE`（`/sys/fs/pstore` 根本不存在，`mount` 也挂不上），也没开
`CONFIG_IKCONFIG_PROC`（`/proc/config.gz` 不存在）。但 `log` 分区里有京瓷的
ram console：`dmesg | grep KCJLOG` 会看到 `KCJLOG: found log partition, partno=22`，
一次启动约 466 KB，环形缓冲保留最近 4 次。

```bash
adb shell "su -c 'dd if=/dev/block/mmcblk0p22 of=/data/local/tmp/log.bin bs=1M'"
adb pull /data/local/tmp/log.bin
```

注意 Android 5.1 的 `/sdcard` 由 FUSE 托管，**root shell 写不进去**，必须落到
`/data/local/tmp/`。

完整 41 个分区的镜像已备份（1.86 GB），**这是唯一的救命稻草，务必多存几份**。
`recovery.img` 建议单独再存一份——它是唯一能把设备拉回原厂 recovery 的文件。

---

## 5. SoC 信息

```
hw_platform    MTP
revision       1.1
model          Qualcomm MSM 8926 MTP
dmesg          Machine: Qualcomm MSM 8226 (Flattened Device Tree)
               model: Qualcomm MSM 8926 MTP
kernel         Linux 3.4.0 (build@KYOCERA) gcc 4.7
```

`/proc/device-tree` 不存在（`CONFIG_PROC_DEVICETREE` 未开），要看 DT 只能从
`/sys/devices/soc0/` 或 dmesg 里取。

---

## 6. 待验证

这些事情**还没有实测数据**，写在这里是为了避免把它们当成已知事实：

- [ ] KC-01 与 KYL23 的面板型号、触摸控制器是否相同（overlay 里目前只有一份 `msm8926-720p-mtp.dts`，按 KYL23 配置）
- [ ] KC-01 的分区表是否与 KYL23 完全一致
- [ ] `/carrier`、`/sysprop` 的文件系统类型（fstab 里暂按 ext4 写）
- [ ] TWRP 的加密支持是否需要（原厂 userdata 使用 `encryptable=/persist/udf`）
- [ ] 9008 (EDL) 模式能否进入、能否绕过写保护（**未验证，不要当作救砖手段**）
- [ ] KC-01 的 build fingerprint（当前用的是 102.0.1e20 推断值）

---

## 7. 内核层面的四个硬限制

这一节记录的都是**真机上撞出来的**，不是推测。改动这个仓库里任何与 ramdisk、
DT 或启动镜像相关的东西之前，先读一遍。

### 7.1 只有 init 进程能挂载 `/system`

内核的 `selinux_mount()` 里有一段京瓷自己加的判断：

```
no permission in selinux_mount pid=165 pname=recovery realpath=/system dev_name=/dev/block/mmcblk0p19
```

配套的字符串在内核镜像里可以直接找到：

```
"no permission mount /system/... by non-init process in %s pid=%d pname=%s realpath=%s dev_name=%s"
"/dev/block/platform/msm_sdcc.1/by-name/system"
```

关键点：**这个判断在 `avc_has_perm()` 之前就 `return -EPERM`**，所以
`androidboot.selinux=permissive`（`/sys/fs/selinux/enforce` 读到 `0`）对它无效。
现象是 TWRP 的 Mount 页勾不上 System，且界面不报错、只有震动。

绕过方式：让初始化进程自己挂。`tools/image/mkhybrid.py` 会在原厂 `init.rc` 的
`on boot` 段、`class_start default` 之前插入：

```
mount ext4 /dev/block/platform/msm_sdcc.1/by-name/system /system rw
```

TWRP 启动后读 `/proc/mounts` 看到已挂载就直接用。

**副作用：TWRP 里卸载 `/system` 一定失败**，日志里会留两条

```
卸载 ' /system ' 失败 (Operation not permitted)
```

一条来自 `Process_Fstab()` 末尾的 `UnMount_Main_Partitions()`（启动时），一条来自
进入 Mount 页时再刷一次分区表。`TWPartition::UnMount()` 走的 `umount()` 同样被
上面那段判断挡住（`enforce=0` 也一样），所以这两条消不掉，**但它们本身无害**：
`UnMount()` 失败只是返回 false，启动流程继续走。

真正会因此失败的是**需要先卸载再格式化**的操作，因为
`Wipe_EXT4()` / `Wipe_F2FS()` 的第一句就是 `if (!UnMount(true)) return false;`：

| 操作 | 结果 |
|---|---|
| 备份 / 恢复 System（`*.img`，走 `Raw_Read_Write` 直接写块设备） | 正常 |
| 恢复 System（tar 格式，要先 `Wipe()` 再解包） | **失败** |
| 清除 → 高级清除 → System | **失败**（提示 `Unable to wipe System`） |
| 刷 ZIP、备份 / 恢复 data、格式化 data | 正常（只拦 `/system`） |

绕过办法：Settings 里勾上 **`使用 rm -rf 命令代替格式化`**（`use_rmrf_chk`，
对应 `tw_rm_rf`）。`Wipe_RMRF()` 不卸载分区，只 `removeDir()`，源码里那句注释
写得很明白——*"This is the only wipe that leaves the partition mounted"*。
勾上之后"清除 System"和恢复 tar 备份都能跑通；随后 `ReMount_RW()` 因为
`Is_File_System_Writable()` 已经为真会直接返回，不会再碰 `umount`。

反过来，**不要**用格式化（`make_ext4fs`）去清 System：即使卸载能成功，格式化后
TWRP 要重新挂载才能用，而挂载同样被拦，会留下一个空分区挂不回去。

彻底解除要 patch 内核（在 `selinux_mount` 里定位那个 `return -EPERM` 改成原地
`nop`），属于改二进制，风险高一个量级，尚未做。

### 7.2 属性区在 4.4 和 7.0 之间断代

`/dev/__properties__` 在 Android 4.4 是**单个文件**，从 7.0 起变成按 SELinux
上下文拆分的目录，还要一个 `properties_serial`。所以 7.1 的 init 在这台 4.4.4
的机器上必然失败：

```
SELinux: Context u:object_r:properties_serial:s0 is not valid (left unmapped).
init: Failed to initialize property area
Kernel panic - not syncing: Attempted to kill init! exitcode=0x00000100
```

这不是缺文件能补的，只能**保留原厂 4.4.4 的 init 体系**（init / ueventd /
healthd / adbd / sepolicy / init.rc / default.prop），把 TWRP 当载荷挂上去。
这就是 `mkhybrid.py` 的全部理由。

### 7.3 ramdisk 必须是 gzip

内核 `Linux version 3.4.0 (build@KYOCERA) ... Tue Sep 13 17:33:24 JST 2016`，
**没有编 `CONFIG_RD_LZMA`**。用 LZMA 打包的 ramdisk 会让内核拿到空 rootfs，
表现是亮 logo 几秒后复位。原厂 ramdisk 的 gzip 流用 `gzip -6` 可以逐字节复现。

### 7.4 QCDT 表项 24 字节，`msm_id` 在第一位

```
偏移 0   4      8        12      16      20
     msm_id board  variant  soc_rev offset  size
```

`msm_id` **不是最后一个字段**。按 `(board, variant, soc_rev, offset, size, msm_id)`
去读会让每个字段整体错位一格，做出来的表看起来完全合理、永远匹配不上。

本机的键是 `(200, 8, 0, 0x10001)`：

| 来源 | 值 |
|---|---|
| `/sys/devices/soc0/soc_id` | 200（MSM8926；145 是 MSM8226） |
| `hw_platform` | MTP → board = 8 |
| `revision` | 1.1 → soc_rev = 0x10001 |
| variant | 0 |

对应 DTB 偏移 `0xec800`。原厂表里 board=8 有 40 条，指向 **8 份不同的 DTB**，
必须原样保留，不能合并。

验证方法（不刷机）：

```bash
adb shell "su -c 'cat /sys/devices/soc0/soc_id /sys/devices/soc0/revision /sys/devices/soc0/hw_platform'"
```

---

## 7.5 `/system` 下的 4.4 程序在 TWRP 里跑不起来

现象：

```
CANNOT LINK EXECUTABLE: could not load library "libc.so" needed by "/system/bin/sh";
caused by cannot locate symbol "android_get_application_target_sdk_version"
referenced by "libc.so"...
```

原因不是丢文件，是**库搜索路径被劫持**。`init.rc` 里有一句

```
export LD_LIBRARY_PATH /sbin
```

这是必需的：TWRP 的 `recovery` 和 `busybox` 都是动态链接，`readelf -d` 里
**没有 RPATH/RUNPATH**，只靠这个变量找 `/sbin` 下的 52 个 `.so`。去掉它就等于
不让 TWRP 启动。

副作用是：所有从 init 继承环境的进程都带着这个变量，包括原厂 4.4 的
`/system/bin/sh`。它的 interpreter 是 4.4 的 `/system/bin/linker`，但 linker 按
`LD_LIBRARY_PATH` **先**找到 `/sbin/libc.so`——那是 7.1 的。

两边对不上，证据在符号表里：

```
libc.so   android_get_application_target_sdk_version   UND     <- 需要别人提供
linker    __dl__Z42android_get_application_target_sdk_versionv  <- 7.1 才有
```

这个符号是 Android 7.0 引入的，由 linker 导出给 libc 用。4.4 的 linker 里根本
没有它，所以 7.1 的 libc 一加载就失败。

**没有两边都照顾的写法**。`/system/lib` 放前面 TWRP 起不来，`/sbin` 放前面 4.4 的
程序起不来——两边要的是同一个 `libc.so`，内容不兼容。

最要命的是 `adb shell`：adbd 处理非交互命令时走的是 `/system/bin/sh -c <命令>`，
所以预挂载 `/system` 之后**任何 `adb shell <cmd>` 都会失败**，而排障只有这一只手。
`mkhybrid.py` 用两处改动堵掉：

1. **改 adbd 里的字符串**。原厂 adbd 是静态链接（本身不受变量影响），但它 exec 的
   路径写死成 `/system/bin/sh`。镜像里把两处都换成 `/sbin/sh`——**逐字节等长替换**
   （14 + NUL → 8 + 7 个 NUL），文件大小和所有偏移都不变，ELF 头与段表原样。
2. **挂载后 bind mount**。`mount ext4 ... /system` 之后紧接一句
   `exec /sbin/busybox mount --bind /sbin/sh /system/bin/sh`，让带
   `#!/system/bin/sh` shebang 的脚本也能跑。`exec` 是 4.4 init 的内置关键字
   （在 stock `init` 二进制里能查到），失败也只是打一行错，不中断启动。

剩下的限制：**`/system/bin` 下的其它 4.4 程序仍然跑不起来**（`ls`、`cat`、`toolbox`
这些）。确实要用，就把变量摘掉：

```sh
unset LD_LIBRARY_PATH
/system/bin/ls
```

或者只对一条命令生效：

```sh
env -u LD_LIBRARY_PATH /system/bin/某个程序
```

注意 `unset` 之后**当前 shell 里的 busybox 仍可用**（applet 是同进程内分发，不
exec），但再 exec `/sbin` 下的东西就会反方向失败。要切回来重新
`export LD_LIBRARY_PATH=/sbin`。

TWRP 自身的功能（备份、恢复、刷 ZIP、文件管理）都是 C++ 直接做的，不经过 shell，
完全不受影响。

---

## 8. 启动跟踪：`mkhybrid.py --boot-trace`

现象：用硬件按键进 recovery，内核起来了（屏幕熄），然后卡住，约 30 秒后被
**硬件看门狗**复位，日志里留下一条 `PET: KERNEL / HW WATCH DOG`，时间戳是
1970（RTC 没被设置过——只有 recovery 不会同步时间）。

麻烦在于**拿不到卡在哪**。log 分区（`mmcblk0p22`）是内核 ram console，顺序写：
recovery 卡死之后紧接着启动的那次系统会把它覆盖掉。等你能 `adb pull` 的时候，
里面已经是系统的 dmesg 了。

`--boot-trace` 解决这个：把启动分成两个快照点写进 `/cache`（eMMC，没有写保护，
硬复位不丢），位置在 `init.rc` 的 `on boot` 段：

```
mount ext4 .../by-name/cache /cache
start boottrace_1                  <- 快照 1：挂 /system 之前
mount ext4 .../by-name/system /system rw
start boottrace_2                  <- 快照 2：挂 /system 之后
class_start default
```

每个快照是一份完整的 `dmesg` 加 `/proc/mounts`、`/proc/uptime`、`/proc/cmdline`。
文件名带**启动序号**，所以卡死那次的现场不会被你之后进去读它时覆盖：

```
/cache/recovery/run1_stage1.txt      <- 第 1 次启动，挂 system 之前
/cache/recovery/run1_stage2.txt      <- 第 1 次启动，挂 system 之后
/cache/recovery/run<N>_stage*.txt    <- 第 N 次；保留最近 10 组
```

怎么读：

| 情况 | 结论 |
|---|---|
| 只有 `stage1`，没有 `stage2` | 卡在 `mount /system`（多半是 eMMC 超时，见 9） |
| `stage1` `stage2` 都有，但 TWRP 没起来 | 卡在 TWRP 二进制内部，不在 init |
| 两个都没有，`/cache/run` 也没更新 | `/cache` 就没挂上，或者 init 根本没走到 `on boot` |
| 两个都没有，dmesg 里有 `boottrace: /cache not mounted` | cache 分区整个挂不上，快照只落在 `/tmp` |

`oneshot` + `disabled` 保证每个快照只跑一次，`start` 是异步的，所以即使
`mount /system` 长期阻塞，快照 1 的子进程仍会写完。

代价：镜像 body 从 15,552,512 涨到 15,554,560（1.9 KB，脚本本体），余量不受影响。
这个开关**不进默认构建**，只在排查时手动加。

### 8.1 为什么 `adb shell ls /cache` 会 Permission denied

`/cache` 是 ext4 分区，根 inode 是 **`0770 system:cache`**，而原厂 adbd 编译时关了
`ALLOW_ADBD_ROOT`，`adb shell` 固定 uid 2000（shell），**不是** system 也不在 cache
组——连目录都穿不进去，`ls` 报的就是这个，跟链接器、跟 SELinux 都无关。

| 读法 | 权限 | 前提起 |
|---|---|---|
| TWRP → Advanced → Terminal | root | 已经进得去 TWRP |
| `adb shell` / `adb pull` | uid 2000 | `/cache` 得是 0755 |

所以 `boottrace.sh` 自己把 `chmod 0755 /cache` 和 `chmod 0755 /cache/recovery` 都做了
（脚本以 root 跑），快照文件也 `chmod 0644`。**这个改动落在 cache 分区的 inode 上，
重启不恢复**，调试完用 TWRP Terminal 执行 `chmod 0770 /cache`，或者在 TWRP 里格式化
一次 cache 就回原样。

副作用可以忽略：`/cache` 属主仍是 system:cache，系统自己读写 cache 用的是属主权限。

进了 TWRP 之后最省事的读法（不依赖 chmod 是否生效）：

```bash
adb shell "cat /cache/recovery/run*_stage*.txt" | head -80
# 或者直接用 TWRP 的终端，root，永远能读
```

---

## 9. MTP：缺的是 init 里的响应，不是内核

现象：TWRP 界面显示「MTP 已启用」，但插上电脑只出现 adb 设备，设备管理器里连未知
设备都没有。ADB 一切正常。

### 9.1 链路

TWRP 不直接写 USB sysfs，它走属性：

```c
property_set("sys.usb.config", "none");
write_file("/sys/class/android_usb/android0/idVendor",  "18D1");
write_file("/sys/class/android_usb/android0/idProduct", "4EE2");
property_set("sys.usb.config", "mtp,adb");
```

真正把 `functions` 改成 `mtp,adb` 的是 **init 里 `on property:sys.usb.config=mtp,adb`
那一段**——它在 TWRP 自己的 `init.recovery.usb.rc` 里。这套镜像用的是**原厂 4.4 的
init.rc**，里面没有任何 `sys.usb.config` 的触发段，于是属性变了、没人响应，
`functions` 一直是开机时写死的 `adb`。电脑看到的就只有 adb。

而且 `Enable_MTP()` 只看 `fork()` 成不成功，孩子进程 `open("/dev/mtp_usb")` 失败是
在子进程里打的，日志里看不到，所以界面照样报「MTP 已启用」。

### 9.2 内核这一侧是齐的

不用猜，三项都对得上：

| 证据 | 内容 |
|---|---|
| 解压内核（gzip @ 0x3FB7）后 `strings` | `drivers/usb/gadget/f_mtp.c`、`mtp_bind_config`、`mtp_function`、`f_mtp` |
| `ueventd.rc` | `/dev/mtp_usb   0660  root  mtp` |
| `file_contexts` | `/dev/mtp_usb  u:object_r:mtp_device:s0` |

也就是 4.4 时代的 legacy `f_mtp`（用户态走 `/dev/mtp_usb` 字符设备），**不是** 7.1 的
functionfs 那一套。TWRP 的 `mtp_MtpServer.cpp` 正好也是开 `/dev/mtp_usb`
（`USB_MTP_DEVICE` 默认值），对得上，所以不需要 configfs、不需要挂 functionfs。

### 9.3 修法

`mkhybrid` 在 `init.rc` 末尾追加四条属性触发段（`none` / `adb` / `mtp,adb` /
`mass_storage,adb`），内容取自 TWRP 的 `init.recovery.usb.rc`，改了两处：

- `none` 段加 `stop adbd`。AOSP 4.4 的 `init.usb.rc` 就是这么写的：切 gadget 配置
  必须重启 adbd，否则它握着旧的 `/dev/android_adb` fd，重新枚举之后 adb 就断了。
- `adb` 段把 `enable ${service.adb.root}` 改成 `enable 1`——`service.adb.root`
  大多时候没设，展开成空串，`write` 会失败。

顺序是 `enable 0` → `functions` → `enable 1` → `start adbd`，跟 AOSP 一致。
`functions` 写失败（比如内核没编 f_mtp）时 gadget 停在原配置，`enable 1` 之后
adb 照常回来——**最坏情况只是回到修复前，不会把 adb 弄丢**。

### 9.4 验证

进 TWRP 后：

```bash
adb shell "getprop sys.usb.config"                                   # mtp,adb
adb shell "cat /sys/class/android_usb/android0/functions"            # mtp,adb
adb shell "ls -l /dev/mtp_usb"                                       # 存在即 f_mtp 已绑定
```

Windows 侧应出现一个 `18D1:4EE2` 的设备。Win10/11 自带 MTP 驱动，正常情况下不需要
装任何东西——但「自带」指的是一次干净匹配；如果这台电脑以前在这个 VID 下装过别的
设备，Windows 会走一条完全不同的路径，见 9.5。

如果三行都对但电脑还是没反应，那就是 TWRP 的 MTP 子进程在 `functions` 生效之前
就 `open("/dev/mtp_usb")` 失败了（它只等 800 ms）。在 TWRP 里把 MTP 关掉再打开
一次即可，不用重启。

### 9.5 Windows 说「设备设置未从以前的 OS 安装迁移」

典型事件日志：

```
由于设备部分匹配或不明确，USB\VID_18D1&PID_4EE2&MI_00\7&2a8e7aca&0&0000 的
设备设置未从以前的 OS 安装迁移。
最后一个设备实例 ID： USB\VID_18D1&PID_D001&MI_00\7&269d47bb&6&0000
类 GUID： {4d36e972-e325-11ce-bfc1-08002be10318}
迁移排名： 0xF000FFFFFFFF0023
Present： false
状态： 0xC0000719
```

这是**设备侧的 MTP 已经通了**之后才会出现的现象——`4EE2` 这个 PID 是 TWRP 的
`Enable_MTP()` 亲自写进 `idProduct` 的，能看到它就说明 `functions` 也确实切过去了。
问题全在 Windows 这一侧。逐行读：

| 字段 | 含义 |
|---|---|
| `VID_18D1&PID_4EE2&MI_00` | 新设备：Google 的 MTP+ADB 复合设备，接口 0 |
| `最后一个设备实例 ID ... PID_D001` | 旧设备：本镜像 `on init` 里写死的 adb-only 配置（`D001`） |
| `类 GUID {4d36e972-...}` | **Network adapters**（网络适配器）安装类 |
| `0xC0000719` | 设备设置迁移失败 |
| `Present: false` | 记录里那台设备当时不在线，是历史条目 |

也就是说：这台电脑的 USB 设备历史库（`HKLM\SYSTEM\CurrentControlSet\Enum\USB\VID_18D1&PID_D001*`）
里，有一条把 `VID_18D1` 的接口 0 绑到了**网卡**类的记录——那是某次 `functions` 里带
`rndis` 时留下的（早期探针镜像就试过）。现在 PID 从 `D001` 变成 `4EE2`，Windows 认为
「同一台设备换了型号」（部分匹配），试图把网卡那套设置继承过来；类对不上，迁移失败，
于是一个 MTP 设备顶着黄色感叹号躺着，驱动装不上。

`&0` 与 `&6` 这两个尾号不同，就是 Windows 认定「换了设备」的直接证据。

#### 修法：把旧记录删掉，让它重新枚举

顺序从轻到重，做一步插拔一次，能认出来就停：

1. **设备管理器 → 查看 → 显示隐藏的设备**，在「网络适配器」和「其他设备」里找所有
   `18D1` 相关项，逐个右键卸载，卸载对话框里**勾上「删除此设备的驱动程序软件」**。
2. 还不行就用 [USBDeview](https://www.nirsoft.net/utils/usb_devices_view.html)，按
   VendorID `18D1` 过滤，把 `D001` / `4EE2` 的条目全删（含 Service 列显示
   `RNDIS`、`usb8023` 的），再插线。
3. 命令行等价操作（管理员 PowerShell）：

   ```powershell
   pnputil /enum-devices /connected | Select-String -Context 3 "VID_18D1"
   pnputil /remove-device "USB\VID_18D1&PID_4EE2&MI_00\<实例ID>"
   ```

清干净之后重新插线，Windows 会按**兼容 ID** `USB\Class_06&SubClass_01&Prot_01`
匹配内置的 `wpdmtp.inf`，直接出现「便携设备 → 内部存储」。

#### 还是装不上，就看兼容 ID

设备管理器 → 该设备 → 属性 → 详细信息 → 属性选「兼容 ID」。结果只有三种：

| 兼容 ID | 说明 | 下一步 |
|---|---|---|
| `USB\Class_06&SubClass_01&Prot_01` | f_mtp 绑对了，是纯 Windows 侧问题 | 手动指定驱动：更新驱动 → 浏览计算机 → 从列表选 → **便携设备 → MTP 设备** |
| `USB\Class_FF&SubClass_42&Prot_01` | 只有 adb，`functions` 没切成 `mtp,adb` | 回到设备侧：`adb shell cat /sys/class/android_usb/android0/functions` |
| 只有 `USB\VID_18D1&PID_4EE2`，没有 `&MI_` | 复合设备没起来（单功能），gadget 没建出接口 1 | 设备侧 `adb shell cat /sys/class/android_usb/android0/state`，看是不是 `CONFIGURED` |

`f_mtp` 的接口描述符是 Still Image（`06/01/01`），这正是 Windows 认 MTP 的依据；
`adb` 的是 Vendor Specific（`FF/42/01`）。看到 `06/01/01` 就说明 `f_mtp` 已经绑上，
剩下全是主机侧的事。

#### 为什么不能靠改 PID 绕过去

`4EE2` 硬编码在 TWRP 的 `recovery` 二进制里（`Enable_MTP()` 用 `write_file` 写死），
镜像侧改不了；而且 `18D1:4EE2` 是 Google 给 MTP+ADB 的正式 PID，Windows 有现成匹配
规则。真正错的是那台电脑的历史记录，不是这个 PID——换个 PID 只会在另一台机器上重新
踩一遍「这个 PID 没匹配规则」的坑。

---

## 10. aboot 里的 fastboot 是死代码，BCB 只能进 recovery

现象：物理键进不了 recovery；`adb reboot bootloader` 只是「第一屏后再次重启」。

从 41 个分区的完整备份里挖出 `aboot.img`（2 MiB，APPSBL），它是个高通 MBN：

```
0x00  image_id = 5
0x0c  image_dest_ptr = 0x10200000     <- 加载基址
0x10  image_size = 0x7d92c
0x14  code_size  = 0x7c02c
0x28  ARM 代码起始（b 0x1020004c）
```

所以 `VA = 0x10200000 + file_offset - 0x28`。有了这个换算，就能判断某个字符串到底有没有
代码引用：ARM 里字符串地址基本都从 literal pool 用 `ldr rX, [pc, #imm]` 取，pool 里存的是
4 字节绝对地址，在文件里搜这个 word 就能数出引用次数。

### 10.1 第一轮的做法：数每个字符串被引用了几次

ARM 里字符串地址基本都从字面量池用 `ldr rX, [pc, #imm]` 取，池里存的是 4 字节绝对
地址。在文件里搜这个 word，就能数出某个字符串被「直接」引用了几次。第一轮的结果：

| 字符串 | 文件偏移 | 第一轮计数 |
|---|---|---|
| `boot-recovery` | `0x5b238` | 2 |
| `update-radio` | `0x5b298` | 2 |
| `OKAY` / `failed-update` | `0x5b268` | 2 |
| `reboot-bootloader` | `0x5ae84` | 0 |
| `flash:` / `erase:` / `oem unlock` / `oem device-info` | `0x5ae60` | 0 |
| `product` / `kernel` / `serialno` / `MSM8226` | `0x5af00` | 0 |
| `Could not do normal boot. Reverting to fastboot mode.` | `0x5afff` | 0 |
| `up_key_on=%d down_key_on=%d is_fastboot_key=%d` | `0x5b038` | 0 |

`bootonce-bootloader` 这个字符串在整份 aboot 里**根本不存在**——这一点后来没有翻案。

当时直接据此说「零引用 = 死代码 = 功能被裁」。**这个推论过强，见 10.2。**

### 10.2 第一轮的判据错在哪

一开始的判据是「某个字符串在文件里找不到 4 字节绝对地址引用 = 那段代码没链接进来」。
这个判据**不成立**，有两个漏检：

1. ARM 的条件执行指令（`ldreq` / `streq`）cond 位不是 `0xE`，按 `0xE51F0000` 掩码匹配
   会全部漏掉——而 lk 里到处是条件执行。
2. 字符串可能通过指针数组间接引用，不一定被 `ldr` 直接加载。

修正后重扫（掩码改成 `0x0F1F0000`，忽略 cond 位），命中 578 处 pc 相对加载、230 个
唯一字符串。**结论不变，但证据换了**：不再看字符串，直接看那个决定启动目标的关键变量。

### 10.3 决定性证据：`boot_into_recovery` 的全部访问点

从 BCB 解析函数（`0x10211c28`）里读到它把 `1` 写进 `0x102b0200`，这就是
`boot_into_recovery`。aboot 加载 recovery 分区还是 boot 分区，只取决于这一个变量。
于是把文件里所有指向该地址的字面量池、以及所有加载这些池的 `ldr`（含条件执行）全部
列出来——一共 8 处，无一遗漏：

| 指令地址 | 条件 | 作用 |
|---|---|---|
| `0x1020fc2c` | AL | 构造 cmdline，读它决定是否追加 recovery 参数 |
| `0x10210498` | AL | boot image 加载路径 |
| `0x102110dc` | AL | 在 `boot` / `recovery` 两个分区名之间二选一 |
| `0x10211988` | **EQ** | BCB magic 等于 `0x77665502` 时置 1 |
| `0x10211cd8` | AL | BCB 命令 `boot-recovery` 时置 1 |
| `0x10211dfc` | AL | BCB 的 `update-radio` 分支 |
| `0x10211f50` | **EQ** | recovery 分区内那份 BCB 的解析 |
| `0x10212088` | AL | misc 里 `ffbm-` 工厂模式 cookie 命中时置 1 |

五个写入点，触发源分别是 BCB magic、`boot-recovery`、`update-radio`、`ffbm-` cookie。
**没有一处来自按键检测。** 如果物理键能进 recovery，它必须先写这个变量；没有第五种
写法，就没有这条路径。

同一函数的字面量池也完整展开了（`0x10211e68` 起）：只有 `boot-recovery`、`update-radio`
两个命令名，其余是 `RADIO`、`OKAY`、`failed-update` 这些 status 值。

### 10.4 顺带排除的其他方向

| 检查项 | 结果 |
|---|---|
| `abootbak.img` 是不是另一版 aboot | **不是**。与 `aboot.img` 只有 9,915 字节不同，全部落在 `0x7d954` 之后的签名区，代码段逐字节相同 |
| `sbl1.img` 里的 `PWR KEY` | 是 PET 事件枚举值（和 `UNKNOWN` / `KERNEL` / `HW WATCH DOG` 并列），不是按键检测 |
| `sbl1.img` 里的 `recovery` | 分区名列表（`rpmbak, abootbak, tzbak, fotabk, ... bootwork, modem, rpm, aboot, recovery, tz`） |
| `persist` / `ssd` / `rom` / `sysprop` | 无 `fastboot` / `recovery` / `unlock` / 按键相关字符串 |
| 原厂 `boot.img` 的 cmdline | `console=ttyHSL0 ... androidboot.hardware=qcom user_debug=31 msm_rtb.filter=0x37`，没有 `androidboot.mode` |

还有一条 Kyocera 定制的线索：aboot 会往 cmdline 追加 ` kcdroidboot.mode=f-ksg`
（`0x1020ff70`）。这是厂商自己加的模式串，但同样没有按键入口——它属于 cmdline 拼接，
不是启动目标判定。

### 10.5 实测确认

misc 原本是全零，写进 `reboot-bootloader` 后回读正确：

```powershell
adb shell su -c "sh /data/local/tmp/setbcb.sh --show"
#   current misc[0:64]:            <- 全零
adb shell su -c "sh /data/local/tmp/setbcb.sh reboot-bootloader"
#   read back: reboot-bootloader
adb reboot
#   -> 正常进入系统，没有 fastboot
```

这和二进制分析完全一致。**BCB 进 fastboot 这条路不存在**，不是命令名写错了。

反过来，用同一个脚本写 `boot-recovery`：

```powershell
adb shell su -c "sh /data/local/tmp/setbcb.sh boot-recovery"
#   read back: boot-recovery
adb reboot
#   -> 直接进入 TWRP，完全不经过系统
```

**成立。** 这是 aboot 里唯一一条被真正实现的 BCB 分支，也是这台机器上唯一一个
「不依赖 adb、不依赖 Android、不依赖任何按键」的入口。

### 10.6 结论

| 通道 | 状态 |
|---|---|
| `adb reboot recovery` / misc 写 `boot-recovery` | **可用**，aboot 认，代码活的 |
| `adb reboot bootloader` | 无效：写的是 `bootonce-bootloader`，aboot 里没这个字符串 |
| misc 写 `reboot-bootloader` | 无效：不是 BCB 命令，无代码引用 |
| 物理按键进 fastboot | 无效：fastboot 命令表整块未链接 |
| 物理按键进 recovery | 无效：按键分支被裁，只剩 normal boot |
| EDL（`05C6:9008`） | 唯一硬件级入口，需短接 |

**misc 写 `boot-recovery` 是系统完全起不来时唯一的软件兜底**，因为它不依赖 adb、不依赖
Android、不依赖 recovery 分区以外的任何东西。前提是系统还能起来一次，把命令写进去。

### 10.7 收尾：把 misc 清干净

`reboot-bootloader` 留在 misc 里虽然无害（没人读），但会和下次实验的观察互相干扰。
清成全零：

```powershell
adb shell su -c "dd if=/dev/zero of=/dev/block/mmcblk0p26 bs=1 count=32"
adb shell su -c "sync"
adb shell su -c "sh /data/local/tmp/setbcb.sh --show"
```

写完 `boot-recovery`、从 TWRP 回到系统之后，**第一时间再跑一次 `--show`**，确认 command
字段已经被 recovery 清掉：

```powershell
adb shell su -c "sh /data/local/tmp/setbcb.sh --show"
```

如果还残留着 `boot-recovery`，说明 TWRP 没清（或者那次 recovery 是卡死退出的），必须手
动 `dd if=/dev/zero` 抹掉——否则每次开机都会再进一次 recovery，而且进不去系统就没法再抹。

### 10.8 这条兜底的真实边界

它有前提：**写入动作本身需要一个能跑 `su` 的环境**。所以它在下面这些场景里无效：

- 系统已经起不来，adb 也没有
- 停在 TWRP 里但 TWRP 卡死

真正能救的场景是「系统还能开机，但已经明显不对劲」，比如反复重启、进桌面就崩。这时候
赶在彻底挂掉之前写一次 `boot-recovery`，重启就落在 TWRP 里，可以从那里刷 boot、刷
system，或者 `rm -rf /data`。

想在更早的时候留一手，可以在系统里放一个快捷方式，需要时一键写：

```sh
su -c 'printf boot-recovery | dd of=/dev/block/mmcblk0p26 bs=1 conv=notrunc'
```

反过来说，**这台机器没有「系统全挂还能进 recovery」的物理通道**，这是 aboot 决定的，
和镜像无关。真正的保险只有全分区备份。

## 11. sbl1 里的京瓷下载模式：SDDL，全部由 SD 卡触发

从全分区备份里解出 `sbl1.img`（1 MiB，MBN `image_id=0x844BDCD1`，加载基址
`0xF800C000`，代码从 `0x50` 起，`VA = base + file_offset`）。它和 `sbl1bak.img`
逐字节相同。

sbl1 是**第一个**执行的阶段，早于 aboot，所以它里面的"下载"跟按键、跟 `misc`、
跟 adb 都没有关系——它只看两样东西：**SD 卡上的文件**，和**一块 16 字节的持久化命令槽**。

### 11.1 SDDL：能用的那条

```
sbl1 启动 → ... → Tz Execution → SDDL()
```

`SDDL` = SD Download。你自己的 `bootwork` 分区（存 SBL1 日志）里两次启动都是这样收尾的：

```
B -    875289 - Tz Execution, Start
D -    164151 - Tz Execution, Delta
B -   1049505 - SDDL Start
```

**它每次开机都会走到**，普通零售机也一样，不需要任何按键或 USB。真正决定做不做事的是
下一步：找不找得到一份合法的下载清单。

门槛有两条，命中任意一条就继续（都返回 `-1` 才退出）：

| 来源 | 内容 | 命中后 |
|---|---|---|
| 持久化命令槽（item 5，16 字节） | 以 `SDDL_ON_NONCRC` 开头 | 读完立即清零（一次性） |
| `/mmc1/SDCRCON`（SD 卡根目录） | 正好 8 字节 `SDLCRCON` | 读完立即 `remove()`，返回 1 |
| `/mmc1/SDCRCOFF` | 正好 8 字节 `SDLCRCOF` | 读完立即 `remove()`，返回 0 |

两个控制文件都是**读写即删**，所以想看效果每次都得重新放。

清单文件是 `/mmc1/set.bin`：

```
+0x00  16 字节  ASCII "KCSDDL_set MAGIC"
+0x10  64 字节 × N 条记录（N ≤ 1024，即最多 64 KiB）
```

单条记录（64 字节，多字节字段都是**大端**）：

| 偏移 | 长度 | 含义 |
|---|---|---|
| `+0x00` | 1 | 类型：`0`=结束、`0xFF`=中止、`5/6/7/8`=实际操作、`1..4`=落空 |
| `+0x01` | ≤`0x20` | 文件名，拼成 `/mmc1/<name>` |
| `+0x20` | 4 | 参数 A |
| `+0x24` | 4 | 参数 B |
| `+0x28` | 4 | 参数 C |
| `+0x2c` | 1 | 子类型（`7`/`8` 跳过文件名拼接） |
| `+0x30` | 4 | 参数 D |
| `+0x34` | 4 | 参数 E |
| `+0x38` | 2 | 参数 F |

类型分派是 `tbb [pc, ip]` 跳表（`0xF8031B18`），四个参数按
`(path, B, A, C, flag)` 传给 `0xF8031044`。这四个字段到底是"目标地址 / 长度 / 偏移"
中的哪几个，需要一份真实 `set.bin` 才能定；**在弄清之前不要往卡里放 `set.bin`**——
它写的是裸 flash 地址，写错就是砖。

### 11.2 RAM dump 到 SD / USB：另一条独立通道

同一份 sbl1 里还有 `boot_sd_ramdump.c`，把上一阶段的崩溃现场写到 SD 或从 USB 吐出来：

```
/dump/work/rawdump.bin
/dump/work/errfile.txt
```

开关是 item `0x11` 的 1 个字节：bit0 = 走 USB，bit1 = 走 SD。日志串是
`SD_DUMP, START / not SD / disable / exSD_chk / exSD_start / USB / USB(SD give) / END reset`。

还有一处 Lauterbach 脚本生成器（`0x19C78`），会往卡里写 `.cmm`：

```
if OS.FILE(<bin>)
(
  d.load.binary <bin> 0x<addr> /noclear
)
```

### 11.3 编译进去但没接上启动流程的

下面这些代码完整存在，但**整份镜像里没有任何分支或数据指针指向它们的入口**（BL/B.W
全类型扫描 + 绝对指针扫描都是 0）：

| 机制 | 文件 / 内容 | 结果 |
|---|---|---|
| `DEVKEYDL` | `/mmc1/NOTPUSH` 内容 `DEVKEYDL` → 返回 2 | 置下载 cookie `E47B337D CE14091A` 后复位 |
| | `/mmc1/CHKCODE` 内容 `DEVKEYDL` → 返回 1 | 同上（还要两个 USB 状态位为 1） |
| | `/mmc1/CHKCDDEL` 内容 `KEYDLDEL` → 返回 3 | 同上，并删除该文件 |
| IMEM 下载标记 | `0xFE805FE0` = `322A4F99 / C67E4350 / 77777777` | 写完直接复位 |
| Sahara 入口 | `Enter boot Sahara` → `boot_dload()` | 进 9008 |
| | `boot_flash_trans_sdcc_factory` | 绕过写保护的传输层 |

`sbl1` 日志里从来没有出现过 `Enter boot Sahara`，这也对得上：**这条路在本版固件里被关掉了**。
所以网上那些"往 misc 写某个命令进 9008"的说法，在这台机器上都不成立——sbl1 里唯一活着的
下载入口就是 SDDL。

### 11.4 安全的第一轮测试

只放控制文件，不碰 `set.bin`：

```bash
# FAT32 卡，根目录建一个 8 字节文件，不要带回车
printf 'SDLCRCON' > /mnt/sd/SDCRCON
```

插卡开机，进系统后读 SBL1 日志：

```bash
su -c "dd if=/dev/block/platform/msm_sdcc.1/by-name/bootwork of=/sdcard/bw.bin bs=1M"
# 拉回电脑后
strings -a bw.bin | grep -a "SDDL"
```

判读：

- 只有 `SDDL Start` → 和平时一样，卡上没找到 `set.bin`，正常退出。
- `SDDL Start` 后面多了 `SDDL End` → 它确实进去翻过卡，SDDL 这条链路是活的。
- 卡上的 `SDCRCON` 开机后消失 → sbl1 读到并删了它，控制文件生效。

`SDCRCON` 是安全的：它只会让 SDDL 多走一段"找 set.bin"的流程，找不到就返回。

## 12. SBL1 下载模式：能回滚到什么程度，写保护算哪一层

### 12.1 两条入口，都停在 aboot 之前

| 入口 | 触发 | 命令 | 谁在执行 |
|---|---|---|---|
| USB 厂商命令 | 插线 + 进下载模式，`0482:xxxx` 枚举 | `0xA3` 读 / `0xA1` 写 | sbl1 里的 Sahara 命令循环 |
| SD 卡 `set.bin` | 卡根目录放控制文件 + 清单 | 无（自己读卡） | sbl1 里的 `SDDL()` |

`serial_probe.py` / `serial_dump.py` / `serial_write.py` / `serial_restore.py` 走的是第一条。
两条都跑在 **aboot 之前**，这一点决定了下面所有结论。

### 12.2 写保护谁置、谁清

- **aboot 置。** `aboot.img` 里有整套 WP 代码和日志串：`Write Protect set for the region,
  only partial space was erased`、`Power on protection is disabled, cannot be set`、
  `Card status timed out after sending write protect command`。
- **sbl1 不置。** `Start write protect set`（`0xf8030ab4`）整份镜像里 **没有任何 BL/B.W 调用点**，
  是死代码。
- **sbl1 里的 SDDL 还会主动清一次。** `SDDL` 主函数（`0xf8031918`）的顺序是：

  ```
  log "SDDL Start"  →  bl 0xf8030b00  →  open /mmc1  →  fopen /mmc1/set.bin
  ```

  `0xf8030b00` 就是 `Start write protect clr / End write protect clr` 那个包装
  （`0xf804027c`）所调用的同一个函数；它最后是 `dev->vtable[3](dev, 1, 1)`，
  和「置保护」那条 `dev->vtable[3](dev, 1, 0)`（`0xf8030bd4`）只差最后一个参数。

**所以：DL 模式下 boot / recovery / system 都是可写的，不需要先清保护。**
写保护位是易失的，每次上电由 aboot 重新置上；DL 模式根本没走到 aboot。

一个前提：**要冷启动进 DL**（拔电池 → 装电池 → 开机）。写保护位扛得住 SoC 复位，
扛不住断电；如果是热复位进来的，aboot 上一轮置的保护可能还在。
SDDL 那条之所以自己再清一次，防的就是这种情况。

反过来，进入 Android 或 TWRP 之后，保护已经在了 —— 这是 §3 和 FLASHING.md 里那套
`mmc_protect_fix2.ko` 流程存在的原因。

### 12.3 回滚能力：到哪一步为止

| 场景 | DL 模式能不能救 |
|---|---|
| 刷了坏 system，开机卡 logo | **能**，写回 `system` 即可 |
| 刷了坏 boot / recovery | **能**，写回对应分区 |
| GPT 主表被清（本机真实发生过） | **能**，写回条目区，已实测 |
| 两个 GPT 都坏了 | 能，但要手工算 LBA 写回，需要先从备份里取 |
| sbl1 / aboot 被写坏 | **理论能，实际上别指望**：sbl1 坏了根本起不到 DL 模式 |
| eMMC 物理损坏 | 不能 |

已实测：`0xA1` 写 GPT 条目区 → 回读逐字节一致 → 正常开机。
整分区第一次尝试就卡在包的尺寸上（`END_OF_IMAGE`），原因是脚本自己的单包长度错了，
不是通道不行 —— 见 §12.7。

同族对照：KYF37 在同一套 `0xA3`/`0xA1` 协议下写过 1.6 GB 的 system 和 boot，
SHA-256 回读全部通过，随后正常开机。协议本身扛得住大分区。

### 12.4 用 `tools/device/serial_restore.py` 刷回

```bash
python serial_restore.py --list                      # 看分区
python serial_restore.py COM13 --part recovery --wp-test          # 先测这一片能不能写
python serial_restore.py COM13 --image dump/19_system.img --part system --verify
python serial_restore.py COM13 --image dump/12_recovery.img --part recovery --verify
```

先跑 `--wp-test` 的理由：它只做「读一扇区 → 原样写回 → 再读」，数据不变，
但能把「写保护没清」和「包大小不对」两件事分开（错误码 0x55 vs 0x54，见 §12.7）。

要点：

- 单包默认 `0x1000`（4096 B）—— 这是固件里的硬上限，不是试出来的，见 §12.7。
  再大的包设备会回 `0x04 + 0x54`，而且**残包会留在它的收包缓冲里**，
  后面连 512 B 也写不进去（这就是“拆块之后反而更糟”的原因）。
- 镜像 < 64 MB 时默认逐块回读比对；大分区用 `--verify` 在结尾校验
  （>128 MB 默认抽 32 处、每处 64 KB，要全量就加 `--verify-full`，
  但 1.4 GB 全量回读在 1024 B/包的读通道上要跑很久）。
- 每写一块往 `<image>.wstate` 记断点，掉线后加 `--resume` 续写。
- `sbl1`/`aboot`/`tz`/`rpm`/`modem`/`persist`/`misc` 这类默认拒写，要写必须 `--allow-critical`。
  判据只有一条：**写坏了还能不能重新进本通道**。sbl1/aboot/tz 写坏就连 DL 都进不去，
  所以拦；`boot`/`recovery`/`system` 写坏只是开不了机，冷启动照样能重进 DL 写回来，
  所以**不拦、不需要 `--allow-critical`**，只在写之前打一行提示。
- LBA 0/1 默认拒写，要写必须 `--gpt`。
- `system` **不在**拒写名单里，刷系统只需要 `--part system`，不用加 `--allow-critical`。
- 镜像可以是 raw，也可以是 Android sparse（ROM 包里那种）；脚本会自动展开成 raw，
  用完删掉临时文件。zip 不行，得先把 `system.img` 取出来。
- 完整流程（备份 → 写 system → 清 data → 验收）见 [FLASH_SYSTEM.md](FLASH_SYSTEM.md)；
  一条命令版是 `tools/device/flash_system.py --image system.img --backup --wipe-data`。

### 12.4.1 「只刷 system」什么时候成立

`system` 里是文件系统，`boot` 里是内核 + ramdisk（含 `init`）。两者必须同代：

| 情况 | 要刷什么 |
|---|---|
| 恢复同一版本的系统备份 | 只刷 `system` |
| 换同版本 ROM，内核没动 | 只刷 `system` |
| 换 Android 大版本（4.4 → 5.1/7.1） | `system` + `boot`（两个都一样，直接写） |

跨版本只刷 `system`、留着 4.4 的 `boot`，表现是卡第一屏或起来就崩 —— ramdisk 里的
`init` 和 `system` 里的 `init` 不是同一代，属性区、`init.rc` 语法都对不上（见 §7.2）。

另外跨版本首次开机基本都要清 `/data`（`TWRP → Wipe → Data`，或
`rm -rf /data/*`），旧布局会让 `vold` 起不来。清之前先把 `/data` 里要留的东西拷出来。

### 12.5 `set.bin` 格式（修正版）

之前记的「16 字节 magic + 记录从 0x10 开始」是错的。按 `0xf8031918` 的实际读取顺序：

```
+0x00  64 字节  文件头，前 16 字节必须是 ASCII "KCSDDL_set MAGIC"，其余忽略
+0x40  64 字节 × N 条记录（N ≤ 1024，即整份清单 ≤ 64 KiB + 64）
```

单条记录（64 B，多字节字段**大端**）：

| 偏移 | 长度 | 含义 |
|---|---|---|
| `+0x00` | 1 | 记录状态：`0`=清单结束、`0xFF`=立即中止、其它=继续 |
| `+0x01` | ≤0x20 | 文件名，拼成 `/mmc1/<name>`；子类型 7/8 不看这个字段 |
| `+0x20` | 4 | 参数 A — **起始 LBA**（512 B 扇区号） |
| `+0x24` | 4 | 参数 B — **字节长度** |
| `+0x28` | 4 | 参数 C — **CRC16**（仅 gate=1 时校验，见下） |
| `+0x2c` | 1 | 子类型，见下表 |
| `+0x30` | 4 | 参数 D |
| `+0x34` | 4 | 参数 E |
| `+0x38` | 2 | 参数 F |

A/B/C 的语义是从写函数 `0xf8031044` 反推出来的，不是猜的：

- 它把 B 拆成 `B>>16` 个 64 KiB 块 + `B&0xFFFF` 的尾巴；
- 每块读 64 KiB 到缓冲区，然后 `write(dev, A + i*0x80, buf, 0x80)` —— 每次前进 0x80 = 128 个
  512 B 页 = 64 KiB，所以 **A 的单位就是 LBA**；
- 尾巴不足 64 KiB 会用 `0xFF` 补齐后照样写一整块（所以 B 别写成分区边界外的值，
  否则会把下一个分区的开头抹成 0xFF）；
- 校验分支会把回读的块做 CRC16、取反、字节交换，再和 **C 的低 16 位**比，所以 C 的高 16 位必须是 0。

子类型走 `tbb [pc, ip]`（表在 `0xf8031b14`）：

| 子类型 | 跳转 | 行为 |
|---|---|---|
| 0 | `0x1b22` | 读文件 → 写 A 起的 B 字节（带 CRC 校验） |
| 1–4 | `0x1bf6` | 空操作 |
| 5 | `0x1b4c` | 只读文件算 CRC16 与 C 比对，不写 |
| 6 | `0x1b62` | 写（另一变体，走 `0xf8031524` / `0xf8031218`，参数 D 参与） |
| 7 | `0x1bac` | 先 `0xf8031d68(A,E)` 再 `0xf8030d98(A,E)` 分块擦除 |
| 8 | `0x1bce` | 只擦除：`0xf8030d98(A,E)`，按 `0x2000` 一块 |

D/E/F 三个字段还没定死，所以**目前不要拿它写 boot / recovery**。

先用 `cache` 做落点校准（`cache` 无保护、可随意覆盖、也在备份里）：

1. 造一个 64 KiB 的测试镜像，内容是有规律的 4 字节序号；
2. 清单里写一条：文件名、A = cache 的起始 LBA、B = 65536、子类型 0；
3. 卡里同时放 `SDCRCON`（8 字节，无换行）；
4. 开机进系统，读 `mmcblk0p21` 头 64 KiB，和测试文件逐字节比。

对上了，说明 A 就是 LBA、B 是字节数，可以往 `recovery` 试；对不上就停下来，
别拿它碰关键分区。

### 12.6 TWRP 必须自己清保护

> **2026-11 更正：写保护不在内核里，换内核去不掉。** 自编译内核上线后实测
> `dd` 写 `mmcblk0p12` 仍然报成功、回读还是 `ANDROID!`。原因是保护做在
> **eMMC 卡级 WP group** 上，由 aboot 每次上电用 CMD28 置上，与内核无关；
> `mmc_protect.ko` 的 `clear` 是拿分区名换 LBA 后发 CMD29 解除，模块的导入符号
> （`mmc_wait_for_cmd` / `__mmc_claim_host` / `lookup_bdev`）和
> `write_protect_group_size` 都印证这一点。所以模块还得留，只是现在能加载了 ——
> 自编译内核删掉了 `selinux_kernel_setup_load_info` 那道闸。
>
> 现在的做法：模块进 `/sbin`，`init.rc` 在 `class_start default` 之后
> `wait /dev/block/mmcblk0p12` 再 `write .../clear`，p12（recovery）和
> p11（boot）各清一次。见下面 12.6.1。

TWRP 跑在 aboot 之后，每次上电保护都被重新置上，所以：

- TWRP 里**恢复 boot / recovery**、或刷带 `boot.img` 的 ROM 包 → `dd` 报成功、回读没变，
  **静默失败**。这是这套机器最容易踩的坑。
- 内核是原厂 `recovery.img` 那份（与 `kcbak/recovery.img` 的内核逐字节相同）。
  它和系统内核是两次不同的构建（2015-08-18 / 2016-09-13），`vermagic` 一致
  （`3.4.0 SMP preempt mod_unload modversions ARMv7`），CRC 也一致 —— 见下。

**当时的镜像自己加载模块**。`mkhybrid.py --module` 把仓库里的
`prebuilt/mmc_protect.ko`（就是当年 `tools/flash/` 下那份 `mmc_protect_fix2.ko`
改名的，两个文件都已经删了，见 12.6.2）
放进 `/sbin`，并在 stock `init.rc` 的 `on init` 段末尾插一行：

```
    insmod /sbin/mmc_protect.ko
```

于是进 TWRP 时 `/sys/kernel/mmc_protect/` 已经在了，只剩清保护这一件事：

```bash
printf mmcblk0p12 > /sys/kernel/mmc_protect/clear      # 注意是 printf，不是 echo
dmesg | grep -c Loop                                   # 应为 6（3 轮，每轮 start+done）
```

`insmod` 失败不会卡住 recovery（init 只往 kernel log 打一行，`service recovery`
照常启动），失败时用 `dmesg | grep -i mmc_protect` 看原因。

#### 12.6.1 自编译内核上的加载方式

模块本身不用改：`__versions` 的 29 项 CRC 与我们重编内核的 `Module.symvers`
**逐项相同**（CRC 是 genksyms 对类型串做的哈希，源码一样结果就一样），
`struct module` 大小也一致（`.gnu.linkonce.this_module` 都是 `0x168`）。
唯一要动的是 `vermagic`：模块写死 `3.4.0 SMP preempt mod_unload modversions ARMv7`，
所以内核编译时把 `CONFIG_LOCALVERSION` 置空、`CONFIG_LOCALVERSION_AUTO` 关掉、
`scripts/setlocalversion` 的 `+` 用空的 `.scmversion` 去掉，`uname -r` 就是 `3.4.0`，
与模块逐字节对上。

`init.rc` 片段（`on boot` 段）：

```
    insmod /sbin/mmc_protect.ko
    class_start default

    wait /dev/block/mmcblk0p12 10
    write /sys/kernel/mmc_protect/clear mmcblk0p12
    write /sys/kernel/mmc_protect/clear mmcblk0p11
```

`wait` 是因为 devtmpfs 没开（`CONFIG_DEVTMPFS` 未设），`/dev/block/*` 由 ueventd
创建，`class_start` 之后才齐。清完 `dmesg | grep -i mmc_protect` 应无 `no permission`。

#### CRC 为什么能对上

模块的 `__versions` 是按**系统内核**（2015-08-18）的 `__kcrctab` 修的，
而 TWRP 跑的是 **recovery 内核**（2016-09-13），两个镜像差 15,514,980 / 15,515,492 字节。
直接搜模块记录的若干个 CRC 值，两边都能命中，且 recovery 那份整体后移 `0x310`
（它多导出了一些符号）：

| 符号 | CRC | 系统内核 | recovery 内核 |
|---|---|---|---|
| `module_layout` | `0x456faa00` | `0xbcf270` | `0xbcf580` |
| `mmc_wait_for_cmd` | `0x154ff28d` | `0xbcf228` | `0xbcf538` |
| `printk` | `0x27e1a049` | `0xbcfb0c` | `0xbcfe1c` |
| `lookup_bdev` | `0x117f7471` | `0xbcefc0` | `0xbcf2d0` |
| `kfree` | `0x037a0cba` | `0xbcec64` | `0xbcef74` |
| `snprintf` | `0xb81960ca` | `0xbd07d4` | `0xbd0ae4` |

两次构建的 config 相同，所以 CRC 表内容一致，模块在 TWRP 里不会因为
`disagrees about version of symbol` 被拒。若将来换了 recovery 内核，
重跑这段搜索即可判断要不要按新内核重修。

验证方法只有一条：写完立刻 `dd` 回读、比 md5，别信命令的退出码。

### 12.6.2 `kc_wp.ko`：模块自清（现行方案）

前面两节讲的 `mmc_protect.ko` 路线最终没走通，根因不是权限也不是 CRC，是**地址单位**。

**症状**：`printf mmcblk0p12 > /sys/kernel/mmc_protect/clear` 返回成功，
`dmesg` 里 `grep -c Loop` 也是 6，但 `dd` 回读还是原样。

**定位**：直接用 CMD31（`SEND_WRITE_PROT_TYPE`）问卡，一次就露馅：

```
CMD31 arg=0x05f00000  ->  ret=-110  R1=0x80000900
```

`R1` 的 bit31 是 `OUT_OF_RANGE`，`-110` 是 `-ETIMEDOUT`。参数本身越界了。
对照 JEDEC 标准：**卡容量 > 2 GB 时，CMD28/CMD29/CMD31 的地址单位是扇区**，
而不是字节。原厂模块用 `bd_part->start_sect << 9` 换算成字节地址发出去，
在这张 8 GB 卡上必然越界；它又没检查 `R1` 的 bit31，于是"发出去就当成功"。

顺带确认了保护类型：`CMD31` 返回 `0x5555…`，每 2 位一组全是 `01` = **临时保护**，
可以被 CMD29 解掉；出现 `10`（上电）/ `11`（永久）才是真的没救。

**所以自己写了一个** `tools/kernel/kc_wp/`，要点：

- 分区偏移取 `bd_part->start_sect`（扇区），**不换算字节**，直接当 CMD29 参数
- `autofix` 两种口径都扫一遍：A 组按扇区、B 组按字节（`step = 512` 扇区全扫），
  各打印首条 `ret / R1`，结束时打一行「起始 WP 组类型 %u -> %u」
- 开机自清：`insmod` 后起一个 delayed work，4 秒后动手；`/dev/block/*` 还没建出来
  就每 500 ms 重试，最多 15 次，默认清 `mmcblk0p12`（recovery）和 `mmcblk0p11`（boot）

**两个内核 API 陷阱**（都是这次踩出来的）：

| 坑 | 表现 | 解法 |
|---|---|---|
| `lookup_bdev()` 只 `bd_acquire()`，不打开设备 | `bd_part` / `bd_contains` 都是 NULL，拿不到分区信息 | 改用 `blkdev_get_by_path(path, FMODE_READ, NULL)`，用完 `blkdev_put` |
| 分区盘 gendisk 的 `driverfs_dev` 是 NULL | `add_partition()` 不给分区盘设，直接 `container_of` 会崩 | 用 `bd_contains` 上溯到整盘，再从整盘的 `driverfs_dev` 拿 `mmc_card` |

还有一条：`blkdev_get_by_path("mmcblk0p12")` 返回 `-2`（`-ENOENT`），因为它按
**相对路径**解析。模块里统一补成 `/dev/block/<name>`。

**为什么不用 `init.rc` 里 `exec` 脚本**：三条都撞过 —— `/dev/block/*` 由 ueventd 在
`class_start default` 之后才建、TWRP 启动会重挂 `/tmp`（`/tmp/wp_fix.log` 直接消失）、
脚本里的 `write` 在 init 阶段不可靠。改成模块内 delayed work 之后日志只走
`dmesg` / `last_kmsg`，不再有文件依赖。

**真机结果**（`wpcheck.sh`）：`基线 55…` → `复查 40…`，写 8 字节魔数 `KCWPOK01`
回读逐字节一致，16 MiB 镜像 `dd` 后双 md5 相同。CI 产出的镜像里 `kc_wp.ko`
是**唯一**的模块，`mmc_protect.ko` 的 `insmod` 行和文件都已删除。

**仓库里的 `prebuilt/kc_wp.ko` 是 strip 过的**：原始产物带 DWARF 调试段，里面记着
构建机上的绝对源码路径（目录结构、用户名都会被写进去），不适合放进公开仓库。
`arm-linux-gnueabi-strip --strip-debug` 只摘掉 14 个 `.debug_*` 段，`.text` 逐字节
不变（`fc6dc43e4bc5b1539bd79e3ca5f6a853`），`__versions` 和 `vermagic` 都保留，
体积 154,008 → 16,264 B（md5 `a79f5570…`）。

> 因此：**真机上验证过的 wp6 用的是未 strip 的原件**，用现在的 `prebuilt/kc_wp.ko`
> 重新构建，镜像 md5 会和 `f4ec23f8` 不同——差异只在这个模块的调试段，代码没动。
> 注意 x86 的 `strip` 不认 ARM ELF，会报 `Unable to recognise the format`，
> 得装 `binutils-arm-linux-gnueabi`。

### 12.7 `0xA1`/`0xA3` 的真实上限与错误码（2024 实测修正）

早先 `serial_restore.py` 把单包定成 `0x3e00`（15872 B），依据是“对端实测上限”，
那个 15872 其实来自另一台机的工具，不是这台固件的检查值。实际刷 recovery 时：

```
开始写入（单包 15872B）…
    ↳ 拆块：15872B → 7680B + 8192B
    ↳ 拆块：7680B → 3584B + 4096B
    ↳ 拆块：3584B → 1536B + 2048B
    ↳ 拆块：1536B → 512B + 1024B
RuntimeError: LBA 194560 写入失败：END_OF_IMAGE（设备拒绝该长度）
```

反汇编 sbl1 后，三件事都清楚了：

**一、上限是 4096，写和读各有一处 `cmp #0x1000`。**

```
0xA1 写处理 @0xf802029c：
    ldr  r5, [r4, #0xc]     ; n = 包的 word[3]
    ...
0xf80202f0  cmp.w r5, #0x1000
0xf80202f4  bls   #0xf8020300   ; ≤ 4096 才往下走，去 `bl 0xf802647c` 写盘
0xf80202f6  movs  r0, #0x54     ; 否则回错误码 0x54
0xf80202f8  bl    #0xf8020440

0xA3 读处理 @0xf80201fc：
0xf802022e  cmp.w r0, #0x1000   ; count > 4096 → 同样 0x54
```

再往上还有一层：收包缓冲 `0x1200`（4608），`0xf8021118` 里 `mov.w r2, #0x1200`
就是它的长度。所以 **4096 数据 + 16 字节头 = 4112** 刚好塞得下，
再大连这一层都过不去（错误码 `0x08`）。15872 是它的 3.4 倍。

**二、`END_OF_IMAGE` 从来不是“镜像结束”，是“这条命令被拒”。**

所有错误都走同一个回执函数 `0xf8020440`：

```
[r4+0]  = 4        ; cmd = 0x04
[r4+4]  = 0x10     ; len = 16
[r4+0xc]= code     ; 真正的错误码在这里
```

| 码 | 含义 | 出处 |
|---|---|---|
| `0x05` | 头部两个长度字段与实际收到的字节数不符 | 写/读处理函数开头 |
| `0x08` | 请求超过 4608 收包缓冲，设备根本没接收 | `0xf8020d60` |
| `0x54` | 长度非法（0 或 > 4096） | `0xf80202f0` / `0xf802022e` |
| `0x55` | 底层 eMMC 读/写失败（写保护、坏块、超范围） | 写盘返回值透传，`0xf802030a` |

以前脚本只看到 `cmd == 0x04` 就报“设备拒绝该长度”，把 `0x55`（写保护）
和 `0x54`（长度）混成一句话，判断不了到底是哪一种。现在把 word[3] 解出来。

**三、被拒之后不能就地拆块重试。**

长度类拒绝时，设备只读了 8 字节头就回错误，**后面的数据原封不动留在收包缓冲里**。
这时再发小包，新包头前面顶着几千字节的镜像数据，会被当成垃圾解析 ——
所以日志里“拆到 512 B 还是失败”不是 512 也超限，是链路已经脏了。
现在的做法：长度类拒绝一律不重试、不拆块，重新握手（`0x0C`）+ 读一次 GPT 头
确认链路干净才继续；确认不了就报 `LinkDead`，让人拔电池重进 DL。

反过来，`0x55` 是写盘那一层返回的，数据已经收完，链路是干净的，
可以重新握手后重试、必要时对半拆（保护是按区分组的，跨组写会整条失败）。

**怎么用这套信息判断故障**（`--part <分区> --wp-test` 一条命令）：

| `--wp-test` 结果 | 结论 |
|---|---|
| `✓ 能写` | 通道、写保护、长度都没问题，直接刷 |
| `✗ 0x55` | 写保护还在（多半是热复位进的 DL，不是拔电池冷启动），或落在保护区 |
| `✗ 0x54` | 脚本的包长算法不对（改 `--chunk`，别超 4096） |
| 连读都失败 | 链路本身坏了，重新插拔 |

### 12.9 内核改成自编译（京瓷 3.4.0 源码）

原厂 recovery zImage 里那层 `selinux_kernel_setup_load_info` 钩子拒绝一切
非 wlan 的 insmod（见 12.6 顶部），绕不开也不该绕：直接换成自己编的内核，
钩子和写保护一起消失。完整由来和补丁解释在 `kernel-patches/README.md`，
这里只留结论。

| | 原厂 | 现在 |
|---|---|---|
| `prebuilt/kernel` | 5,808,608 B，`40aada0058c8b0aadd00f5a5bc75166a` | 5,730,752 B，`3d87f8d8c7a3153be3064c2560fa3a98` |
| 版本 | 3.4.0（CAF `LNX.LA.3.5.1-06610-8x26.0`） | 同左，京瓷 GPL 源码 |
| insmod 钩子 | 拒 `pname=init` | `return 0`（`mov r0,#0; bx lr`） |
| mmc 写保护 | 由 `mmc_protect.ko` 提供 | 不加载即无 |
| 镜像需要模块 | 是（`--module`） | 否 |

**为什么不是 3.4.113**：面板（`mdss_dsi_nt35590_720p_video`）、触摸
（`atmel_mxt_kc@4a`）、传感器、音频的 dts 节点和驱动全在京瓷这棵树里。
LineageOS 的 3.4.113 只留作后续补丁源，不当基线。

**固件级风险**：这份 zImage 是用 gcc 13.3 + `-std=gnu89` 编的，原厂是
gcc 4.8 era。`.config` 与 `defconfig` 一致（`CONFIG_SECURITY_SELINUX_KC`
仍为 `y`，函数保留为空实现），dt 沿用 `prebuilt/stock/dtb-kyl23.img` ——
内核版本没变，binding 一致，不需要重新生成 QCDT 表。

**验收顺序**（别一次到位）：

1. 刷"只换内核、ramdisk 不动"的镜像，确认能进 TWRP、触摸可用、`dmesg` 无
   `Kernel panic` / `Unable to mount root`；
2. 在 TWRP 里 `dd if=/dev/zero of=/dev/block/mmcblk0p12 count=1` 之后回读
   确认被改（或者直接刷一次 boot.img），验证写保护真的没了；
3. 再改 ramdisk（去掉 `insmod` 那行）出正式版。

## 13. TWRP 的字体：中文到底多花了多少体积

### 13.1 是两套，但按语言切换，不并行

`twres/languages/zh_CN.xml` 第 7–11 行有一组 `fontoverride`：

```xml
<!-- Font overrides - only change these if your language requires special characters -->
<resource name="font_l" type="fontoverride" filename="DroidSansFallback.ttf" scale="100" />
<resource name="font_m" type="fontoverride" filename="DroidSansFallback.ttf" scale="100" />
<resource name="font_s" type="fontoverride" filename="DroidSansFallback.ttf" scale="100" />
<resource name="fixed"  type="fontoverride" filename="DroidSansFallback.ttf" scale="100" />
```

`ui.xml` 里的默认是：

```xml
<font name="font_l" filename="RobotoCondensed-Regular.ttf" size="54"/>
<font name="font_m" filename="RobotoCondensed-Regular.ttf" size="42"/>
<font name="font_s" filename="RobotoCondensed-Regular.ttf" size="36"/>
<font name="fixed"  filename="DroidSansMono.ttf" size="30"/>
<font name="keylabel" filename="RobotoCondensed-Regular.ttf" size="64"/>
```

所以行为是：

| 当前语言 | `font_l/m/s` | `fixed` |
|---|---|---|
| English | RobotoCondensed | DroidSansMono |
| 简体中文 | DroidSansFallback | DroidSansFallback |

同一时刻只渲染一套。但两套都得打包进 ramdisk，因为语言是运行时切换的，
主题引擎不能在切换时去别处找字体——**这就是体积增加的全部原因**。

三处细节：

- `keylabel` / `keylabel-small` / `keylabel-longpress` **没有** override，
  中文界面下键盘标签仍是 RobotoCondensed。键盘只有字母数字，无所谓。
- 中文界面下**西文和数字也用 DroidSansFallback 渲染**，字宽比 Condensed 大约 10–15%，
  1080×1920 的布局可能出现文字挤在一起或提前换行。这是 `fontoverride` 的固有代价，
  不是配置错了。
- `fixed` 也被换成非等宽字体，终端/日志里字符对不齐。

### 13.2 体积账

| 文件 | 未压缩 | gzip -9 后 |
|---|---|---|
| `DroidSansFallback.ttf` | 3,725,920 | 1,781,907（47.8%） |
| `DroidSansMono.ttf` | 108,128 | 70,597 |
| `RobotoCondensed-Regular.ttf` | 125,332 | 66,028 |
| **合计** | **3,959,380** | **1,918,532** |

ramdisk 未压缩 18,263,948 B，压缩后 8,449,879 B。中文字体一项占压缩后体积的 21%。

镜像实际占用（`twrp-kyl23.img`）：

```
header 2 KiB + kernel 5,808,608 + gap 1,568 + ramdisk gzip 8,449,879 + dt 1,290,240
= 15,552,343 → 页对齐 15,552,512 B
recovery 分区 16,777,216 B，余量 1,224,704 B（1.17 MiB）
```

文件是 16 MiB 是因为 `mkhybrid.py` 补零补到分区大小，不是内容顶满。
**再往 ramdisk 里塞东西，压缩后超过 1.17 MiB 才会真的放不下。**

### 13.3 要省体积就 subset，别删字体

删 `DroidSansFallback.ttf` 中文就全变方块，没有意义。真正有效的是裁字形集：

`zh_CN.xml` 里界面文案用到的汉字去重只有 **495 个**。但 TWRP 还要显示**文件名**，
备份名一旦是中文，缺字就是方块。所以按用途分三档：

| 裁剪策略 | 字数 | 字体大小 |
|---|---|---|
| 只留界面用字 | 495 | 约 150–250 KB |
| 界面用字 + GB2312 一级 | 3,755 | 约 1.2 MB |
| 不动（当前） | 20,992（4E00–9FFF） | 3.55 MB |

```bash
pip install fonttools
pyftsubset DroidSansFallback.ttf \
  --unicodes=U+4E00-9FFF,U+3000-303F,U+FF00-FFEF \
  --output-file=DroidSansFallback.subset.ttf
```

`U+3000-303F` 是中文标点，`U+FF00-FFEF` 是全角字符，这两个区间必须带上，
否则中文界面里的「，。」和全角括号全变方块。

改完替换 `twres/fonts/` 里的文件、重新 `mkhybrid.py` 打包，
`check_bootimg.py` 看一眼总大小没超 16 MiB 再刷。

### 13.4 能不能只用一套字体？能，但省的不是那 233 KB

先说结论：**`DroidSansFallback.ttf` 本身就是一套中英文通吃的字体**，不需要再配英文字体。

实测它的 cmap 覆盖：

| 区段 | 覆盖 |
|---|---|
| ASCII 可打印 0x20–0x7E | 95/95 |
| Latin-1 补充 0xA0–0xFF | 46/96 |
| CJK 基本区 4E00–9FFF | 20,902/20,992 |
| 通用标点 2000–206F | 29/112 |
| 中文标点 3000–303F | 35/64 |
| 全角 FF00–FFEF | 164/240 |

而 `RobotoCondensed-Regular` 的 CJK 覆盖是 0/20992，`DroidSansMono` 也是 0。
换句话说：**中文字体是超集，英文字体是子集。**

所以「删掉英文字体、只留中文那套」在字符层面完全可行，界面里的 5 个特殊字符
（`°` `—` `“` `”` `…`）中文字体全都有，Roboto 也全都有。

**但省下来的只有 233,460 B（gzip 后 136,625 B）**——`RobotoCondensed` + `DroidSansMono`
本来就只有 233 KB。真正的大头是 3.55 MB 的中文字体本身。

### 13.5 真正有效的做法：裁字形集

以 `DroidSansFallback.ttf`（34,461 个 cmap 项）为源，按用途裁：

| 档位 | 字数 | 字体大小 | gzip | ramdisk 省 |
|---|---|---|---|---|
| `ui`（只留界面用字） | 1,102 | 112,304 | 64,805 | 1.74 MB |
| **`gb2312`（一二级）** | **7,370** | **1,065,628** | **573,381** | **1.23 MB** |
| `gbk`（全集） | 22,228 | 3,014,760 | 1,571,988 | 0.24 MB |
| 不裁（现状） | 34,461 | 3,725,920 | 1,781,907 | — |

`gb2312` 是甜点：现代汉语 99.9% 的用字都在 GB2312 的 6,763 个汉字里，
1.07 MB 换 1.23 MB 的 ramdisk 空间，性价比最高。

`gbk` 档几乎没意义——GBK 有 21,791 字，裁完还有 2.94 MB，只省 0.24 MB。

`ui` 档要慎用：1102 个字符只够渲染界面文案，**TWRP 还要显示文件名**，
备份名一旦是中文且不在这个集合里，就是方块。做备份管理的机器不建议。

### 13.6 一个容易误解的点：分区固定 16 MiB

`recovery` 分区就是 16 MiB，镜像再小也不会释放物理空间。所以这项优化的收益是
**ramdisk 到 dt 之间的空档变大**，也就是「以后往 ramdisk 里加东西还能加多少」：

```
现在的布局：  ramdisk gzip 8,449,879 B ─┐
                                        └─ 空档 0 B ── dt 1,290,240 B ── 补零到 16 MiB

裁到 gb2312： ramdisk gzip 7,216,225 B ─┐
                                        └─ 空档 1,233,654 B ── dt ── 补零
```

做法上刻意**不动 dt 的绝对位置**：新 ramdisk 变短的部分用零补齐，
这样除了 header 里 offset 16 的 `ramdisk_size` 字段，镜像其余字节与原文件完全一致。
重新打包时如果让 dt 跟着前移，aboot 能否正确找到 QCDT 就成了新的未知数——
这台机器的镜像本来就不符合标准页对齐（ramdisk 末尾直接接 dt，中间没有 padding），
不值得为 1.2 MB 去赌。

### 13.7 工具

```bash
pip install fonttools
python tools/image/slim_fonts.py twrp-kyl23.img -o twrp-kyl23-slim.img            # 默认 gb2312
python tools/image/slim_fonts.py twrp-kyl23.img -o slim.img --level ui
python tools/image/slim_fonts.py twrp-kyl23.img --single-font -o single.img       # 只留一套字体
python tools/image/slim_fonts.py twrp-kyl23.img --report                          # 只看数字
```

脚本做的事：

1. 扫 gzip 魔数定位 ramdisk（不依赖 header 的页对齐推算，这份镜像偏了 1,568 B）；
2. `cpioutil` 解析 cpio（3,277 个条目，无硬链接、无设备节点，可以安全重建）；
3. 只替换 `DroidSansFallback.ttf` 一个条目，**文件名不动**，所以 `zh_CN.xml` 的
   `fontoverride` 一行都不用改；
4. 重新 gzip、按原布局组装，dt 位置不变；
5. 自检：header/kernel 段未动、dt 及以后未动、总长一致、回读字体一致；
   带 `--single-font` 时再加两项——cpio 解析完整、所有 `.ttf` 引用都能对应到实际文件。

已实测产出 `twrp-kyl23-slim.img`（16,777,216 B，与原来同大小），
四项自检全过，495 个界面汉字与 5 个特殊字符零缺失。

**风险**：裁剪后的字体去掉了 hinting（`--no-hinting`）和 OpenType 布局表。
TWRP 用 FreeType 渲染大字号（36–64 px），hinting 影响很小；但这是推断，没在真机上验证过。
第一次刷之前把原镜像留着，起不来就刷回去——`recovery` 分区本身没有写保护问题
（DL 模式可直接写，TWRP 里要 insmod 清保护）。

### 13.8 单字体方案：只留 DroidSansFallback（已产出，自检含 dt 位置）

13.4 说过 `DroidSansFallback` 已经是中英文通吃的超集。那就直接落地：
**删掉另两套，让所有字体资源都指回这一套。**

#### 改了什么

字体名在 ramdisk 里只出现在 XML 的 `filename=` 属性里，`sbin/recovery`
和 `libminuitwrp.so` 都没有硬编码字体名（`strings` 里只有一个 `.ttf` 字面量），
所以改 XML 就够了。

| 文件 | 处数 | 改法 |
|---|---|---|
| `twres/ui.xml` | 7 | `font_l` `font_m` `font_s` `fixed` `keylabel` `keylabel-small` `keylabel-longpress` 全部指到 `DroidSansFallback.ttf` |
| `twres/languages/en.xml` | 4 | 4 条 `fontoverride` 同上 |
| `twres/splash.xml` | 1 | 开机画面那行 `font_l` |
| `twres/languages/zh_CN.xml` | 4 | **不动**，本来就指向它 |

合计 16 处引用，全部收敛到一个文件名。然后删两个字体条目：

```
twres/fonts/RobotoCondensed-Regular.ttf   125,332 B
twres/fonts/DroidSansMono.ttf             108,128 B
```

顺序不能反：先改引用、再删文件。反了会短暂出现悬空引用，虽然 `C.build`
只在内存里操作，但自检会误报。

#### 体积账

| | 原镜像 | 单字体 |
|---|---|---|
| ramdisk 解压 | 18,263,948 | 18,030,140 |
| ramdisk 压缩 | 8,449,879 | 8,287,307 |
| cpio 条目 | 3,277 | 3,275 |
| dt 起点 | 14,262,272 | **14,100,480**（前移 161,792） |

只有 **162 KB**（压缩后）。这是「只用一套字体」这件事的真实收益上限——
两个英文字体本来就只有 233 KB。想让 ramdisk 更松，只能裁字形集（13.5）。

#### 真正的代价在排版，不在体积

用 fontTools 量了三个字体的度量（`hmtx` 前进宽度 / `head.unitsPerEm`）：

| 字体 | upm | `A` 宽 | `0` 宽 | ascender |
|---|---|---|---|---|
| RobotoCondensed | 2048 | 0.576 em | 0.494 em | 0.928 |
| DroidSansMono | 2048 | 0.600 em | 0.600 em | 0.928 |
| **DroidSansFallback** | 256 | 0.609 em | 0.551 em | **1.043** |

拉平到 70 个常用拉丁字符比，**中位宽度是 RobotoCondensed 的 1.12 倍**，
最大的是 `|`（2.26 倍）、`r`（1.31 倍）、`I`（1.36 倍）、`,`（1.27 倍）。
`font_l` 用 size=54 时，行高从 63.3 px 变成 **70.7 px（+11.7%）**，
基线因为 ascender 从 0.928 涨到 1.043 会整体下移。

会有三个可见后果：

1. **英文界面文字变宽约 12%**，长一点的条目可能提前换行，1080×1920 的列表会看着更挤。
2. **`keylabel` 那三个（64/46/32 px）是键盘标签**，现在用的是比例字体，
   标签比原来宽，键盘格子可能挤。
3. **`fixed` 不再是等宽字体**。实测这 70 个字符在 DroidSansFallback 里有 38 种宽度
   （等宽字体应为 1 种），TWRP 的终端/日志里字符会对不齐。

前两条是观感问题，第三条是功能性退化——但 TWRP 的日志界面不是日常操作路径，
真要读日志可以 `adb pull /tmp/recovery.log`。

#### 已经产出的镜像

`twrp-kyl23-single.img`，16,777,216 B（与原镜像同大小），MD5
`89e76a24c2f88afe18226003f58445d6`（原镜像 `28ac980434d59be225f34a25291b1917`）。自检：

```
header/kernel 段未动 : ✓   只差 header offset 16..18 的 ramdisk_size
dt 整块搬到 14,100,480 : ✓  页对齐 ✓
dt 之后全是零填充    : ✓
总长与原来一致       : ✓
回读字体一致         : ✓
cpio 解析完整        : ✓   3,275 条目
字体引用都有对应文件 : ✓   16 处引用 → 只剩 DroidSansFallback.ttf
英文字体已删除       : ✓
```

再跑一遍 `tools/image/check_image.py --max-fonts 1`：`QCDT ver=2 entries=40`、字体 1 个、`OK`。

**云端产物（推荐刷这一份）。** 当前这版是 run `42269729025` / commit `5a50759e`，
在单字体之上又塞进了 `mmc_protect.ko` 并自动 `insmod`：

| 文件 | MD5 | ramdisk | dt 起点 | 余量 |
|---|---|---|---|---|
| `twrp-kyl23.img` | `deeb5dca36c231c098cd85374417d722` | 8,379,580 | 14,192,640 | 1,294,336 |
| `twrp-kc01.img` | `195ea89a1e911584d23570ff72a8e428` | 8,379,594 | 14,192,640 | 1,294,336 |

上一版（只做了单字体、没有模块）是 run `42260554158` / `1c3c43e7`：
`edbf3e52…` / `551977fd…`，ramdisk 8,313,236 / 8,313,250，dt 起点 14,127,104。
两者 kernel 段与 dt 段逐字节相同，差别只有 ramdisk 里多出的
`sbin/mmc_protect.ko`（143,066 B，与 `prebuilt/mmc_protect.ko` 一致）和
`init.rc` 末尾那一行 `insmod`；busybox 的 build-id 每次构建都不同，属正常。

两者 kernel 段逐字节相同，与原厂 `kcbak/recovery.img` 的 kernel 段也相同
（sha256 `8d8453f4…`）；ramdisk 内只有 `sbin/busybox`、`sbin/recovery`、`sbin/twrp`
三处因构建和设备名不同，其余条目（含全部 twres、mke2fs 1.42.9、mke2fs.conf 钉死的
安全特性）与本地产物逐字节一致，权限位有零星差别（`init.recovery.*.rc` 644 vs 750），
都不影响 init 读取。

上面那份本地产物（`89e76a24…`）和它内容等价，只是由原厂 TWRP 载荷直接改的；
两者选其一即可，没必要都留着。

**踩过的坑（第一版产出是刷不起来的镜像）。** 最初的 `slim_fonts.py` 写的是
「dt 绝对位置不动，ramdisk 变短的部分用零补齐」，自检还专门断言了
「dt 及以后未动 ✓」——这条断言把错误当成了正确。aboot 不记绝对偏移，它按 header 算：

```
dt = page_align(kernel_size) + page_align(ramdisk_size) + page_align(second_size) + page
```

ramdisk 从 8,449,879 缩到 8,287,307，dt 就必须从 14,262,272 前移到 14,100,480。
旧产物照抄了旧偏移，于是 aboot 去 14,100,480 读到的是**一片零**
（`check_image.py` 里就报了 `DT blob does not start with QCDT`），
表现是开机卡住而不是报错。现在 `assemble()` 会把 dt 搬到位，自检也改成
验三条：整块内容一致、位置等于页对齐值、其后全零。

#### 命令

两条路径，做的事完全一样：

```bash
# A. 改已有的镜像
python tools/image/slim_fonts.py twrp-kyl23.img --single-font --level full -o twrp-kyl23-single.img

# B. 从源码构建时就只打一套（README 的构建命令已带这个参数）
python tools/image/mkhybrid.py ... --twres-overlay "$D/twres" --languages en,zh_CN --single-font ...
```

两者对同一份输入产出的 cpio **逐字节相同**（sha256 `1c667ca698850b3f…`，18,030,140 B），
因为它们做的是同一件事：正则改 `filename="*.ttf"`、删多余字体条目、校验无悬空引用。
`mkhybrid.py` 的 `--single-font` 还能顺手挡掉一种错误——overlay 里的语言文件若引用了
被删的字体，构建会直接 `SystemExit`，而不是刷完看到方块才发现。

`--single-font` 只做两件事：改写 XML 引用、删两个字体条目。字形一个没动，
所以不存在 13.7 里「去 hinting 导致渲染异常」那类风险。剩下的风险纯属排版观感，
刷坏了也能立刻刷回原镜像（`recovery` 分区在 DL 模式直接可写）。

#### 回退

```bash
python serial_restore.py COM13 --image twrp-kyl23.img --part recovery --verify
```

或者 TWRP 里 `insmod mmc_protect_fix2.ko` 后 `dd` 回去（见 12.6）。

## 14. Wi-Fi：删掉已保存网络的，是当初为了兼容 4.4 打的那个补丁

这一节记的是这台设备最后一个长期未解的 bug，以及它为什么绕了那么多圈。
结论在前：**根因是 `/system/framework/wifi-service.jar` 里一处手工补丁，
而它补的是一个已经不存在的问题。**

### 14.1 现象

| 步骤 | 结果 |
|---|---|
| 开机 | 不自动连，但设置里能看到保存过的热点 |
| 手动连一次 | 成功，能上网 |
| 关 Wi-Fi → 开 | 显示"无法连接到 Wi-Fi"，热点仍在列表里、仍标着"已保存" |
| 再关 → 再开 | 热点从"已保存"里消失，要求输入密码 |
| 重启 | 同样要求密码 |

关键点：**手动连接永远是成功的**。凡是"新建网络"的路径都正常，出问题的
只有"重新加载已保存网络"这条路径。

### 14.2 先排除掉的几个方向

这些都是当时看起来最像、实际都不是的：

- **`networkHistory.txt` 的 configKey 校验**。`loadConfiguredNetworks()` 里
  `WifiNetworkHistory.readNetworkHistory()` 会因为 configKey 对不上而丢弃配置，
  日志是 `Ignoring network ...`。实测 `grep -c "Ignoring network"` = 0，这条排除。
- **`nid=-1616136200`**。这个负数在日志里很扎眼，但它只是 `"K2"WPA_PSK` 的
  Java `hashCode()`，来自 `readIpAndProxyConfigurations()` 的
  `configuration found for missing network, nid=`，是无害的。
- **captive portal 把网络判定为"无互联网"然后禁用**。7.1 的
  `NETWORK_SELECTION_DISABLE_THRESHOLD[DISABLED_NO_INTERNET] = 1`，
  `TIMEOUT = Integer.MAX_VALUE`，一次探测失败就永久禁用，而探针
  `connectivitycheck.gstatic.com` 在国内不可能通——所以这条**确实存在**，
  但它解释的是"连上了却显示无法访问网络"，不是"配置被删掉"。
  `kcfix.sh` 把 `captive_portal_mode` 设成 `IGNORE` 就是为这个。
- **`wpa_supplicant.conf` 的权限/属主**。曾经被脚本改成 root 所有导致 supplicant
  读不了，但修好之后现象不变。

### 14.3 决定性证据：让 supplicant 自己说话

fix45 在 `p2p_supplicant` 服务的命令行末尾加了 `-d`。这是整件事的转折点——
之前所有日志都来自 framework，而 framework 只能说"我认为失败"，
说不出"失败在哪一步"。

以下是关掉再打开 Wi-Fi 那一刻，supplicant 自己的记录：

```
16:41:06.795  Priority group 1
16:41:06.795     id=0 ssid='K2'              <- 配置里 K2 还在
16:41:06.903  wlan0: command 'LIST_NETWORKS'
16:41:06.919  wlan0: command 'LIST_NETWORKS' <- 它又读了一遍
16:41:06.928  wlan0: command 'REMOVE_NETWORK 0' <- framework 把它删了
16:41:12.086  CTRL_IFACE: Could not find network id=0
16:41:12.087  wlan0: command 'SAVE_CONFIG'   <- 把空配置写回文件
```

**framework 在每次重新加载网络时，把自己保存的那个网络删掉了。**
之后的 `SET_NETWORK 0 ...` 全部回答 `FAIL`（`id=0` 已经不存在），
`saveNetwork()` 返回 false，下一次开关就把空配置写进文件——这就是密码提示。

### 14.4 根因：两行互相矛盾的代码

`WifiConfigStore.loadNetworks()` 是分页读的：

```java
int last_id = -1;
boolean done = false;
while (!done) {
    String listStr = mWifiNative.listNetworks(last_id);
    ...
    done = (lines.length == 1);     // 本页只有表头 = 读完了
}
```

`WifiNative.listNetworks(int last_id)` 本该把 `last_id` 发出去：

```java
return doStringCommand("LIST_NETWORKS LAST_ID=" + last_id);
```

但这台设备镜像里的那份 jar，这个方法体是：

```
const-string/jumbo v0, LIST_NETWORKS
invoke-direct v1, v0, WifiNative->doStringCommand(String)
```

**参数被忽略，每次都发裸 `LIST_NETWORKS`。** 于是"第二页"就是第一页：

1. 第一轮读到 `id=0 K2`，塞进 map；
2. 第二轮又读到同一个 `id=0 K2`，`configs.put(configKey, config)` 返回
   上一轮的值 → 判定"重复网络" → `mWifiNative.removeNetwork(0)`；
3. 第三轮读到空列表 → `done = true`，循环结束，但网络已经没了。

`removeNetwork()` 那行本来是为 WPS 场景写的（"用户手动连过之后又用 WPS
连了一次，supplicant 会新建一个 network"），注释写得没错，只是这里被
自己的分页逻辑喂了个"重复"。

### 14.5 这个补丁是干什么的，为什么早该撤

`git log` 里 fix43 的注释已经把话说完了：

> Everything above this line was written to keep a 4.4 wpa_supplicant blob alive
> under a 7.1 framework: kcwpad talked to it, kcwd repaired its config file,
> **the framework's jar was patched so LIST_NETWORKS would be understood**.
> ... So: no daemon, no file repair, **no jar patch**.

4.4 的 supplicant（v2.1-devel）的命令表用 `strcmp` 比裸字符串 `LIST_NETWORKS`，
收到 `LIST_NETWORKS LAST_ID=-1` 会回 `UNKNOWN COMMAND`。所以在用 4.4 blob 的
那些版本里，这个补丁是**必要的**。

fix43 把 `/system/bin/wpa_supplicant` 换成 cm-14.1 自己构建的 v2.6-devel 之后，
前提消失了，但**补丁没撤**。于是"兼容 4.4 的补丁"反过来破坏了 7.1 的分页，
而且症状比原来更难查——它不报错，它删数据。

### 14.6 修法：什么都不用改

7.1 的 supplicant 分页是正确的（`ctrl_iface.c`）：

```c
if (cmd != NULL && os_strncmp(cmd, "LAST_ID=", 8) == 0) {
    int last_id = atoi(cmd + 8);
    if (last_id != -1) {
        while (ssid != NULL && ssid->id <= last_id)
            ssid = ssid->next;
    }
}
```

`LAST_ID=-1` 返回全部；`LAST_ID=<最后一个 id>` 返回只剩表头的一行；
`lines.length == 1` → `done = true`。**原版 jar 和 7.1 supplicant 是自洽的。**

所以最终这一版做的是：

- `/system/framework/wifi-service.jar` **换回构建系统产出的那一份**，
  与 `out/target/product/kyl23/system/framework/wifi-service.jar` 一字不差
  （458,803 B，md5 `073f7af8d9a7fb449d7438787e29505e`）；
- `/system/bin/wpa_supplicant` 用 cm-14.1 的 v2.6-devel（fix43 起就是这样）；
- **没有任何东西**去写 `wpa_supplicant.conf`、`networkHistory.txt`，
  也没有任何东西往 supplicant 里预置网络。

### 14.7 顺带清掉的东西

4.4 supplicant 时代留下的一整套东西，前提消失后全是负担：

| 文件 | 作用 | 现状 |
|---|---|---|
| `/vendor/bin/wpa_supplicant` | 4.4 blob，871 KB | 删 |
| `/vendor/bin/kcwpa` | 4.4 supplicant 的启动包装 | 删 |
| `/vendor/lib/kcssl/` | 专供 4.4 supplicant 的 OpenSSL 1.0（1.2 MB） | 删 |
| `/vendor/bin/kcwifi2.sh` `kcwifi3.sh` `kcwifiwd.sh` | 直接改 conf 文件"修"网络 | 删 |
| `/vendor/bin/kcwpad` | 直接改 conf 文件 + 禁用蓝牙包 | 删 |
| `/system/bin/wpaq` `/system/etc/kcprobe.sh` | 问 daemon"为什么 FAIL"的探针 | 删（它已回答完了） |

`kcwifi` 留着——它是加载 prima 驱动的那个东西，删了 Wi-Fi 根本起不来。

### 14.8 如果以后又怀疑 Wi-Fi

按这个顺序，两分钟能定位：

1. `getprop | grep wpa`、`dumpsys wifi | grep -E "SET_NETWORK|LIST_NETWORKS"`
   —— 看 framework 认为自己在发什么；
2. `logcat -s wpa_supplicant` —— 加了 `-d` 的 supplicant 会把收到的每条命令
   和它的回答都打出来，`Could not find network id=` 和 `Failed to set network
   variable` 是两个完全不同的方向；
3. `cat /data/misc/wifi/wpa_supplicant.conf` —— `network={...}` 块在不在、
   `id_str` 里的 configKey 是什么。

**不要先怀疑 jar。** 这一轮的教训是：镜像里的每一个手工补丁都要能说出
"它当时在解决什么问题、那个问题现在还在不在"，说不出来就该删。

## 15. 蓝牙：五层，从"包被禁用"到"两条 SMD 通道"

这一节记的是蓝牙从"开关打不开"到"能被别的设备搜到"的完整路径。
结论在前：**一共五层，前四层各自都能单独让开关失效，最后一层才是无线电本身。**

### 15.1 五轮现象

| 轮次 | 现象 | 真正卡住的那一层 |
|---|---|---|
| fix48 | 开关点了没反应 | 4.4 的 HAL blob 在 linker 里就死了，7.1 的 HAL 从没被加载过 |
| fix49 | 同上 | 包被 `pm disable` 过，`bindService()` 直接失败，进程都没起 |
| fix50 | 同上 | `pm` 在本机开机阶段要近 60 s 才可用，修得太晚 |
| fix51 | 弹"蓝牙共享屡次停止运行" | `timer_create(CLOCK_BOOTTIME_ALARM)` 返回 EINVAL，`alarm.c:157` 断言自杀 |
| fix52 | 开关能停住，但 `enable timeout` | HCI 后端选错：`got 2, expected 1` |
| — | **能开、能被搜到** | SMD 两条通道后面确实有活的控制器 |

### 15.2 前三层，一句话一层

**第一层，HAL 加载。** `/vendor/lib/hw/bluetooth.default.so` 是 4.4 的 blob，
它引用 `_ZN7android10AudioTrack5writeEPKvj`（6.0 之前的二参数形式），
而这套 ROM 的 libmedia 只导出三参数形式，`dlopen` 直接失败：

```
E HAL: dlopen failed: cannot locate symbol
       "_ZN7android10AudioTrack5writeEPKvj" ...
E BluetoothServiceJni: No Bluetooth Library found
```

7.1 自己的 `bluetooth.default.so`（1,448,792 B）一直在 `/lib/hw` 里躺着，
只是 7.1 先找 `/vendor/lib/hw`，同名文件被 4.4 blob 占了位置。fix48 把两边
都换成 7.1 那份，JNI 也回到构建产出的原版。

**第二层，包被禁用。** fix32 的 `kcwpad` 在 Wi-Fi 出问题时执行过
`pm disable com.android.bluetooth`，这个状态写在
`/data/system/users/0/package-restrictions.xml`（`enabled="3"
enabledCaller="shell:0"`），**不在任何 system 镜像里**，所以后面每一版都受影响。
被禁用的包不是"打不开的适配器"，是整个包从解析里消失：

```
E BluetoothManagerService: Fail to bind to:
       Intent { act=android.bluetooth.IBluetooth }
```

修法是改文件而不是让 PackageManager 改主意：post-fs-data 早于 zygote，
那时的改动对整个开机有效，不需要 `pm`、不需要 binder。这就是
`/system/etc/kcbt.sh pre`，`boot_completed` 那次只做兜底与取证。

**第三层，clock 9。** 3.4 内核没开 alarm clock（`CONFIG_RTC_CLASS`），
`CLOCK_BOOTTIME_ALARM` 不存在，`timer_create()` 对 clock 9 返回 EINVAL，
`system/bt/osi/./src/alarm.c:157` 的 `assert("false")` 直接 SIGABRT：

```
E bt_osi_alarm: timer_create_internal unable to create timer with clock 9
F libc: alarm_new_internal: assertion "false" failed
F libc: Fatal signal 6 (SIGABRT) in tid ... (stack_manager)
```

1.3 s 一次，8 次，就是 UI 上的"屡次停止运行"。修法是 HAL 里两个字节：
`timer_create_internal()` 把 clock_id 放在 r4 里直接传给 `timer_create()`，
vaddr `0x10145c`（文件偏移 `0xfd45c`）

```
04 46   mov  r4, r0     ->     07 24   movs r4, #7
```

此后所有定时器建在 `CLOCK_BOOTTIME` 上。代价只有一个：不能靠定时器把设备
从 suspend 里叫醒——这套 port 本来也不 suspend。全库 22 处 `clock_gettime`
只用 7/1/0，数字 9 整个文件只出现在这一处。

### 15.3 第四层：`got 2, expected 1` 不是 HAL 的 bug

```
I bt_hci_h4 : hal_open
I bt_vendor : bt-vendor : BT_VND_OP_USERIAL_OPEN
E bt_hci_h4 : hal_open opened the wrong number of ports: got 2, expected 1.
```

这行字看着像 HAL 坏了，其实是**协议栈的两半对这个手机的传输方式判断不一致**：

- `/vendor/lib` 里的 Qualcomm 库按设计打开两条描述符：
  `fd[0]=/dev/smd3`（命令）、`fd[1]=/dev/smd2`（ACL/事件），返回 2。
  内核 `arch/arm/mach-msm/smd_tty.c` 里这两个节点注册为
  `{2,"APPS_RIVA_BT_ACL"}`、`{3,"APPS_RIVA_BT_CMD"}`，同属 `SMD_APPS_WCNSS`。
- `bluetooth.default.so` 里有两个 HCI 后端，`get_soc_type()` 读
  `qcom.bluetooth.soc` 决定用哪个：ROME/CHEROKEE/AR3K/**DEFAULT** 走
  `hci_hal_h4`（单描述符 UART），其余走 `hci_hal_mct`（2 或 4 描述符）。
  属性没设 → DEFAULT → H4 → H4 按构造拒绝两个 fd。

所以 fix52 只加一行 `setprop qcom.bluetooth.soc smd`。属性在 post-fs-data 设，
两半都读同一个键。

顺带记一笔容易搞反的地方：库内枚举是 `1=smd 2=ath3k 3=rome 4=cherokee`，
`smd` 不在 H4 那一串里，所以选定的是 **MCT**，不是 H4。实测日志证实了这一点
（见下）。`libbt-vendor.so` 自身只认 `rome/cherokee/ath3k`，遇到 `smd` 会打
`qcom.bluetooth.soc not set, so using default` 并返回 0——和它未设属性时的行为
一模一样，所以 vendor 侧行为没变，改动只影响 HAL 挑哪个后端。

### 15.4 通道对端是活的：fix52 那一次开机的日志顺序

```
I bt_vendor: qcom.bluetooth.soc set to smd
I bt_vendor: BD Address: 3a:9f:f2:c8:21:c4
I bt_vendor: Hw_config: First Time BT on after boot. Starting hciattach daemon
I bt_hci_mct: hal_open
I bt_vendor: Done intiailizing UART
I bt_hci_mct: hal_open got uart fds: CMD=73, EVT=73, ACL_OUT=74, ACL_IN=74
I bt_vendor: Bluetooth FW and transport layer are initialized
D BluetoothAdapterState: 10-> 14   BLE_TURNING_ON
D BluetoothAdapterState: 14-> 15   BLE_ON
D BluetoothAdapterState: 15-> 11   TURNING_ON
D BluetoothAdapterState: 11-> 12   ON
D BluetoothAdapterProperties: ScanMode = 20 / Scan Mode:21  (可连接 + 可被发现)
D BluetoothAdapterProperties: Name is: KYL23
```

`CMD=73, EVT=73` 是同一个 fd——SMD 的命令通道同时承载命令与事件，这正是 H4
做不到的事。控制器回了命令、回了 LE 特性，堆栈才可能走到 12；
`Scan Mode:21` 就是"别的设备能搜到"这一件事在日志里的样子。

同一次开机 36 s 后是关机（`ShutdownThread: Disabling Bluetooth...`），
状态 12→13→15→16 干净走完，没有崩溃。

### 15.5 还剩一处不一致：控制器上报的地址

```
W bt_btif: BTIF init BDA was c4:21:c8:f2:9f:3a
W bt_btif: Controller BDA is 00:00:00:00:5a:ad
D BluetoothAdapterProperties: Address is:00:00:00:00:5A:AD
```

堆栈最终采用**控制器上报的那个**。两个值都值得怀疑：

- `c4:21:c8:f2:9f:3a` 和这台机器的 Wi-Fi MAC `c4:21:c8:f3:fe:ca` 同段
  （`c4:21:c8` 是京瓷的 OUI），看起来像真实分配到的地址；
- `00:00:00:00:5a:ad` 前四字节全零，像是 NVM 里没写地址时的默认值。

同一时刻还有两条命令异常：

```
E bt_hci  : read_command_complete_header: return status - 0x1
E bt_btif : bta_dm_ctrl_features_rd_cmpl_cback Ctrl BLE feature read failed: status :255
D %s VS event found treat it as valid 0x%x: get_waiting_command
```

`status 255`/`0x1` 不是 HCI 规范里的错误码，更像是等待中的命令被一条
vendor-specific 事件"顶包"了（CAF 的 `hci_layer` 对 VS 事件有"当作有效"的
分支）。所以现在还分不清是控制器真的没地址，还是 `Read_BD_ADDR` 的回包串了。

**判据很便宜：看对方手机搜到这台设备时显示的地址。**
如果是 `00:00:00:00:5A:AD`，就是控制器侧的问题（要写 NVM 或发 VS 写地址命令，
两者都还没验证过这条路）；如果显示 `C4:21:C8:F2:9F:3A`，就只是日志里的读回失败，
不影响任何功能。

### 15.6 下次再怀疑蓝牙，按这个顺序

1. `/cache/kcbt.log`：第一行就是 `KCBT soc prop -> 'smd'`，然后是 `smd nodes`。
   属性不是 smd、或者包状态要重写，这里会直接说。
2. 日志里认后端名：`bt_hci_h4: hal_open` = 属性没生效；`bt_hci_mct: hal_open` = 选对了。
3. `got uart fds:` 后面是不是两个描述符；不是的话通道没开。
4. 状态机有没有到 12，`Scan Mode` 是不是 21 或 23。
5. 以上都过、但对方搜不到，才轮到无线电与地址（15.5）。

代码位置：`kyl23-extra.rc` 的 post-fs-data 段（`setprop qcom.bluetooth.soc smd`
与 `exec -- /system/etc/kcbt.sh pre`）、`boot_completed` 段（`kcbt.sh post`），
脚本本体 `device/kyocera/msm8926-common/prebuilt/kc/kcbt.sh` → `/system/etc/kcbt.sh`
（`lineage-common.mk` 里用 `PRODUCT_COPY_FILES` 装，权限由 rc 里的 `chmod 0755` 给）。

## 16. 蓝牙的地址：控制器自己不知道，主机知道

fix52 之后蓝牙是能用的——开、搜、配对、传文件、关开、重启都过了。剩下的唯一问题
在另一台手机上看得到：**它把这台设备显示成 `00:00:00:00:5A:AD`**。

### 16.1 这不是读错，是真地址

堆栈自己就报过这两个值对不上：

```
W bt_btif: BTIF init BDA was c4:21:c8:f2:9f:3a
W bt_btif: Controller BDA is 00:00:00:00:5a:ad
D BluetoothAdapterProperties: Address is:00:00:00:00:5A:AD
```

一开始还怀疑是 `Read_BD_ADDR` 的回包被 vendor event 顶包了（同一时刻确实有
`read_command_complete_header: return status - 0x1` 和
`Ctrl BLE feature read failed: status :255`）。**对端看到的也是这个地址**，
这条怀疑就排除了：inquiry response 里的 BD_ADDR 是控制器填的，两边一致，
说明控制器确实以 `00:00:00:00:5A:AD` 在发。

### 16.2 主机其实有正确的那一个

同一次开机更早的一次启动打过这么一行（那次没走到打开传输，直接用了 NV）：

```
W bt_btif: Read the Vendor BD addr from '/persist/.bt_nv.bin'
D BluetoothAdapterProperties: Address is:C4:21:C8:F2:9F:3A
```

`/persist/.bt_nv.bin` 就是这颗芯片的 BT NV 在主机侧的那份拷贝（NV447 = BD_ADDR），
里面的地址和 Wi-Fi MAC `c4:21:c8:f3:fe:ca` 同段（`c4:21:c8` 是京瓷的 OUI）。

所以缺的不是数据，是**把数据推给控制器的那一步**。7.1 的堆栈只做
`HCI_Read_BD_ADDR` 然后采用结果（CAF 的逻辑：控制器说了算），它没有任何代码
去写芯片的 NV。

### 16.3 那一步在 4.4 的镜像里，一直都在

原厂 system.img 里有三样东西：

| 文件 | 作用 |
|---|---|
| `/system/bin/btnvtool` | 读写 `/persist/.bt_nv.bin` 的 NV447；`-O` 表示"没有就生成一个稳定的" |
| `/system/bin/hci_qcomm_init` | 读 NV447，然后往 `/dev/smd3` 发一串 "NV VS set" 命令，**这才是真正写芯片的那一步** |
| `/system/etc/init.qcom.bt.sh` | 把上面两个串起来的胶水 |

而且 7.1 的 vendor 库**仍然在做同一个握手**，只是没人应答：

```
W bt_vendor: Hw_config: First Time BT on after boot.Starting hciattach daemon BTStatus=
```

它 `setprop bluetooth.hciattach true`，然后最多等五秒 `bluetooth.status`。
fix52 日志里 `BT_VND_OP_POWER_CTRL On`（07:19:00.820）到 `hal_open`
（07:19:05.828）之间正好空五秒——那就是等超时了。

`hci_qcomm_init` 选端口看 `ro.qualcomm.bt.hci_transport`，这个属性本 ROM 里
**没有人设**，未设时它用 `/dev/ttyHS0`（这台机器没有这个 UART）。不过实测
`-e` 模式并不打开这个口，见 §16.5 第 1 条。

### 16.4 fix53 做了什么

1. 把原厂那两个二进制搬回 `/system/bin`（`btnvtool` 9,540 B、
   `hci_qcomm_init` 129,008 B，一字未改）。它们依赖的 `libbtnv.so`、
   `libqmi*.so`、`libqcci_legacy.so`、`libstdc++.so` 本来就在镜像里。
2. `/system/etc/kcbtinit.sh`：只跑 `hci_qcomm_init -e`，把输出记进
   `/cache/kcbt.log`，然后把 `bluetooth.status` 置 `on`。
   **没有**跑原厂 `init.qcom.bt.sh`——它的 `config_bt()` 会顺手设一页
   `ro.qualcomm.bluetooth.*` 的 profile 开关，那会改变 7.1 暴露哪些 profile，
   而写地址用不到这些。
3. `kyl23-extra.rc`：
   - post-fs-data 里 `setprop ro.qualcomm.bt.hci_transport smd`；
   - `service kcbtinit`（user bluetooth，group bluetooth net_bt_stack）+
     `on property:bluetooth.hciattach=true` → `start kcbtinit`。
4. `kcbt.sh` 每次开机把 NV 文件与 `btnvtool -p` 的内容记进日志；
   只有在 `/persist` 确实是挂载点、且 `.bt_nv.bin` 不存在时，才按原厂做法
   `btnvtool -O` 生成一个（已有地址绝不覆盖）。

时间窗是硬约束：vendor 库最多等五秒，所以 `kcbtinit.sh` 用
`timeout 4` 兜住 `hci_qcomm_init`——真卡住就把它杀掉、描述符随进程关闭，
不会和随后打开同一个端口的堆栈抢。

### 16.5 实测：fix53 回传的那一次启动

`grep KCBTINIT /cache/kcbt.log`，实际拿到的是：

```
KCBTINIT == start uptime=99.33
KCBTINIT hci_transport='smd' soc='smd'
KCBTINIT nv: -rw------- 1 bluetooth bluetooth 17 ... /persist/.bt_nv.bin
KCBTINIT hci_qcomm_init rc=0
KCBTINIT   BTS_DEVICE=/dev/ttyHS0;
KCBTINIT   BTS_ADDRESS=c4:21:c8:f2:9f:3a;
KCBTINIT   ro.qualcomm.bt.hci_transport: smd
KCBTINIT programmed address=c4:21:c8:f2:9f:3a device=/dev/ttyHS0 type=qualcomm
```

两处与当初的预期不同，都记在这里，免得下次再当异常查：

1. **`BTS_DEVICE` 是 `/dev/ttyHS0`，不是 `/dev/smd3`。** 上面 §16.3 推断
   "属性设成 smd 就走 smd 口"，这条只对了一半：`hci_qcomm_init -e` 先在
   modem 侧找 `MODEM_NV_BD_ADDR`，找到就直接用 QMI 把地址交给蓝牙核，
   `/dev/ttyHS0` 只是它在 `-b` 手动模式下才会用的回落口。既然 `rc=0` 且
   地址写进去了，说明这一次走的是 QMI 那条路，那个不存在的 UART 根本没被打开。
   这也解释了为什么 `ro.qualcomm.bt.hci_transport=smd` 设不设都能通。
2. **两条无害告警。** `Failed to open the /sys/devices/platform/wcnss_wlan.0/
   smd_channel_ready` 是诊断通道节点不在（4.4 的 sysfs 布局），
   `Diag_LSM_Init ... error = 13` 是同一个原因的下游结果。两条都在写地址
   之前发生，之后 `rc` 仍是 0，与结果无关。

主日志那边验证通过，三条都对上：

```
W bt_btif : BTIF init BDA was 00:00:00:00:5a:ad
W bt_btif : Controller BDA is c4:21:c8:f2:9f:3a
D BluetoothAdapterProperties: Address is:C4:21:C8:F2:9F:3A
```

第一条仍是 `00:00:00:00:5a:ad`，那是开关按下之前从 NV 读到的旧值（`HCI_Read_
BD_ADDR` 在写地址之前发生）；第二条才是写完之后的答案，也是从这之后
`Address is:` 才变成真地址。**判据看第二、三条，第一条留着不算问题。**

失败时的判读方式：

- `rc=143`（timeout 杀掉）→ 四秒不够，或通道没就绪，把窗口调大再试；
- `rc` 非零且输出里有 QMI 报错 → 走的是 modem NV 那条路失败，需要 `-b` 显式给地址。

### 16.6 这一层的边界

地址是写进**芯片 NV** 的，正常一次就够，之后每次开机都还在。若某次刷回原厂
4.4 或清 `/persist`，NV 文件没了，`btnvtool -O` 会生成一个新的（原厂行为），
那时地址会变，已配对设备需要重新配。

## 17. rild 少了设备路径：一个真实的缺陷，但不是基带未知的原因

> **事后订正（fix54 实测）**：这一节最初是把「基带版本未知」归因到下面这个空格上
> 的，那个结论是错的。fix54 把 `rild.libargs` 修好之后，日志里 `RIL_Init argc`
> 确实从 4 变成 5，但 `BASEBAND_VERSION` 依旧在 14 ms 后失败，
> `gsm.version.baseband` 依旧为空。真正的原因记在 §18。
>
> 这个空格本身是一个独立存在的缺陷（见 17.4），修它是对的，只是它不解释这个症状。
> 保留这一节是因为 17.2 里那组时间线（14 ms 失败 vs 30 秒超时）仍然是判断
> 「请求有没有出进程」的有效方法。

### 17.1 症状与属性链

设置 → 关于手机 → 基带版本，显示"未知"。这一格读的是
`TelephonyManager.getBasebandVersion()`，实现就是一行：

```java
return SystemProperties.get(TelephonyProperties.PROPERTY_BASEBAND_VERSION);
```

也就是 `gsm.version.baseband`。而这个属性的**唯一写入方是电话栈自己**：收到
`EVENT_GET_BASEBAND_VERSION_DONE` 且没有异常时，才把 RIL 的返回值写进去；
请求失败就 `break`，属性保持不存在。

抓到的属性表里确实没有它，而同一批的 `gsm.version.ril-impl` 在：

```
[gsm.version.ril-impl]: [Qualcomm RIL 1.0]
（没有 gsm.version.baseband）
```

### 17.2 请求确实发出去了，而且被拒了

```
D RILJ    : [3657]> BASEBAND_VERSION [SUB0]
D RilRequest: [3657]< BASEBAND_VERSION error: ... CommandException: GENERIC_FAILURE
```

两条相隔 **14 毫秒**，八次开机八次如此。关键在于 14 ms 这个数字：qcril 里处理
这个请求的函数 `qcril_qmi_nas_dms_request_baseband_version()`，反汇编出来是

```
mov r0, #4                 ; qcril_qmi_client_get_user_handle(DMS)
mov r1, #81                ; QMI 消息号
movw r2, #30000            ; 30 秒超时
bl  qmi_client_send_msg_sync
```

**它带的超时是 30 秒**。所以 14 ms 失败不可能是 modem 超时——请求根本没出进程。
而同一时刻 NAS/UIM/SMS/WDS 都初始化正常、注册状态有值，说明 QMI 链路本身是通的。

### 17.3 对照原厂，差的是一个参数

原厂 4.4 的 `build.prop`：

```
rild.libpath=/vendor/lib/libril-qc-qmi-1.so
rild.libargs=-d /dev/smd0
```

我们的 7.1 镜像里：

```
rild.libpath=/vendor/lib/libril-qc-qmi-1.so
rild.libargs=-d
/dev/smd0
```

**`/dev/smd0` 掉到了下一行，成了一个没有 `=` 的孤立行。** 日志对得上：

| | rild 传给 qcril 的参数个数 |
|---|---|
| 原厂 4.4 | `RIL_Init argc = 5` |
| 本移植 | `RIL_Init argc = 4` |

差的那一个就是设备路径。

### 17.4 为什么这个值会丢：`PRODUCT_PROPERTY_OVERRIDES` 装不下带空格的值

`lineage-common.mk` 里原来写的是：

```make
PRODUCT_PROPERTY_OVERRIDES += \
    rild.libpath=/vendor/lib/libril-qc-qmi-1.so \
    rild.libargs=-d /dev/smd0 \
    ro.telephony.default_network=8
```

这个变量是**按空格分词的 `key=value` 列表**，一个带空格的值在里面无法表达：
`rild.libargs=-d` 成了一个词，`/dev/smd0` 成了另一个词，两个都被原样写进
build.prop，后者因为不含 `=` 被 init 忽略。

**加反斜杠转义没有用**——`\ ` 是 shell 的规则，make 是在展开之后按空格切的：

```make
rild.libargs=-d\ /dev/smd0     # 仍然被切成两个词
```

### 17.5 修法

把带空格的值从 makefile 挪进 `system.prop`（`BoardConfigCommon.mk:245` 把
`TARGET_SYSTEM_PROP` 指向它，内容是**按文件原样**并进 build.prop，不经过分词）：

```
rild.libpath=/vendor/lib/libril-qc-qmi-1.so
rild.libargs=-d /dev/smd0
```

`lineage-common.mk` 的 telephony 段随之清空，只留注释。注意顺序：build.prop 里
`TARGET_SYSTEM_PROP` 先写、`PRODUCT_PROPERTY_OVERRIDES` 后写，后者会覆盖前者，
所以 makefile 那边**必须真的删掉**，否则补好的值又被盖回 `-d`。

### 17.6 实测结果：两条对上，一条没对

fix54 刷入后从 dump 里读到：

| 检查项 | 结果 |
|---|---|
| `RIL_Init argc = 5` | 通过，4 → 5，参数确实补回来了 |
| `baseband=` 不再是空 | 没通过，仍然是空 |
| RILJ 里不再有 `BASEBAND_VERSION error` | 没通过，仍然 14 ms 失败 |

也就是说：这个空格是一个真实存在、也确实被修好的缺陷，但它不解释基带版本这个
症状。因果链在别处，见 §18。

值应当是 `MPSS.DI.2.0.1.c9-00059-M8926DAAAANAZM-1`——这是 modem 分区里固件自带的
版本串：

```
$ strings modem.img | grep MPSS | head -1
/local/mnt/workspace/CRMBuilds/MPSS.DI.2.0.1.c9-00059-M8926DAAAANAZM-1_20140912_030333/...
```

如果 `baseband=` 有了值但内容和这串不一致，说明 qcril 走的是自己那条路（返回的
是 `QMI_DMS_GET_DEVICE_REV_ID` 的结果），更应该以它为准。

## 18. 基带版本：一条命令被 modem 拒，另一条根本没发出去

> 这一节的第一版把原因写成「qcril 比固件新，问了一条 modem 不认的命令」，
> 并且据此打了个改命令号的补丁（fix55）。补丁刷进去之后毫无变化，复查
> 反汇编才发现问题在**响应缓冲长度校验**上，而不是命令号。下面 18.3 之后
> 是按实际机制重写的，18.4/18.5 保留的是那一版为什么失败——它本身是一个
> 有用的教训：`0x51` 和 `0x23` 看着是同一个服务的两条命令，实际连门都进不去。

### 18.1 一个被忽略的对照组

这次 dump 里最有价值的一条，不是失败的那条，而是**成功**的那条：

```
[3657]> BASEBAND_VERSION [SUB0]
[3658]> RIL_REQUEST_DEVICE_IDENTITY [SUB0]
[3658]< RIL_REQUEST_DEVICE_IDENTITY {356408061218140, 00, 809A04BA, 35640806121814}
[3657]< BASEBAND_VERSION error: CommandException: GENERIC_FAILURE
```

两条请求前后脚发出，`DEVICE_IDENTITY` 成功回来，`BASEBAND_VERSION` 失败。而
`*#06#` 显示的 MEID 就是 `DEVICE_IDENTITY` 里的那个值——这就解释了为什么 MEID
看得见、基带版本看不见。

### 18.2 两条命令都走 DMS，但编号不同

反汇编两个处理函数，请求发往同一个服务：

```
qcril_qmi_nas_dms_request_device_identity       msg_id = 0x25   -> 成功
qcril_qmi_nas_dms_request_baseband_version      msg_id = 0x51   -> 失败
```

`qcril_qmi_nas_dms_request_baseband_version` 的关键几条指令：

```
1ab3d8: mov  r0, #4              ; qcril_qmi_client_get_user_handle(DMS)
1ab3f4: mov.w r1, #81            ; msg_id = 0x51
1ab3f8: mov  r2, #0              ; 无请求参数
1ab3fc: mov  r3, #0
        [sp+4] = 44              ; 响应缓冲 44 字节
        [sp+8] = 30000           ; 30 秒超时
1ab400: blx qmi_client_send_msg_sync
```

按 QMI DMS 消息表：

| 编号 | 命令 | 含义 |
|---|---|---|
| 0x23 | `GET_REV_ID` | 取设备修订号，老设备上就是基带版本串 |
| 0x25 | `GET_DEVICE_SERIAL_NUMBERS` | IMEI / ESN / MEID，这条通了 |
| 0x51 | `GET_SW_VERSION` | 取软件版本，较新的命令 |

**同一个 DMS 服务、同一个 client handle、同一条 QMI 通道，0x25 通、0x51 不通。**
所以不是链路问题、不是权限问题、不是 radio 处于 off（`DEVICE_IDENTITY` 和它同一
批发出）。是这一条命令 modem 不认。

### 18.3 为什么 qcril 会去问一条 modem 不认的命令

对比两边的年份：

```
modem 固件   MPSS.DI.2.0.1.c9-00059-M8926DAAAANAZM-1   2014-09-12
qcril 库     含 QMI_NAS_GET_AREA_SETTING 等 2015+ 特性
```

qcril 比 modem 固件新，它选了新命令 `GET_SW_VERSION`，而这颗 2014 年的 modem
只认老的 `GET_REV_ID`。modem 立即回一个服务错误（不是超时，14 ms 就回来了），
qcril 转成 `GENERIC_FAILURE`，电话栈只在成功时才写 `gsm.version.baseband`，
于是 Settings 显示「未知」。

**这不是移植引入的。** `vendor/.../vendor/lib/libril-qc-qmi-1.so` 和原厂
`system.img` 里那份 md5 完全一致（`cbdf5c2dc7025b59f24abe1f5c9d5e40`），也就是说
原厂 4.4 用的就是这份 qcril 配这颗 modem，原厂状态下这一项大概率同样是未知。

### 18.4 fix55 的改法：把命令号改回老的

`libril-qc-qmi-1.so` 的第一个 LOAD 段 `Offset == VirtAddr == 0`，所以虚拟地址就是
文件偏移。`0x1ab3f4` 处原本是：

```
4f f0 51 01     mov.w r1, #81     ; 0x51  GET_SW_VERSION
```

改成：

```
4f f0 23 01     mov.w r1, #35     ; 0x23  GET_REV_ID
```

**整库只改这一个字节**（`0x51` → `0x23`），`cmp -l` 确认差异为 1 处。改完反汇编
验证：

```
1ab3f4: f04f 0123   mov.w r1, #35  @ 0x23
1ab3f8: f04f 0200   mov.w r2, #0
1ab400: blx 4cf7c   qmi_client_send_msg_sync@plt
```

同文件里另有两处 `4ff05101`，都不碰：`0x2294cc` 是 `qcril_hook_unsol_response`
的 hook id（后面紧跟 `movt r1, #8`，拼成 `0x80051`），`0x23f37e` 是 `snprintf`
的参数。只有 `0x1ab3f4` 是 `qmi_client_send_msg_sync` 的 msg_id。

### 18.5 为什么这个改法是安全的（最坏也只是不生效）

qcril 给这条请求的响应缓冲是 **44 字节**（`memset(sp+72, 0, 44)`，栈帧
`sub sp, #120`，buffer 正好占满尾部，**无法加大**），读字符串的位置是
`buffer+8`、长度 33：

```
1ab53c: add  r3, sp, #72
1ab53e: add.w r3, r3, #8      ; 字符串在 buffer+8
1ab544: mov.w r3, #33         ; 长度 33
```

`qmi_client_send_msg_sync` 在解码前会校验 `resp_c_struct_len` 是否够放下该消息的
C 结构：

- `GET_REV_ID` 结构不超过 44 字节 → 照常解码，字符串落在 `buffer+8`，成功；
- 超过 44 字节 → 直接返回参数错误，**不会越界写**，qcril 走错误分支返回
  `GENERIC_FAILURE`，行为与 fix54 完全相同。

所以这个补丁的失败模式是「白改」，不是「崩掉」。回滚方式是把 fix54 再刷一遍。

### 18.6 下次开机看什么

`/vendor/bin/kcstate.sh` 的 `modem / baseband` → `version` 一节，三行就能定案：

```
baseband=...           有值 => 通了；仍为空 => 这条命令也不认，退回 §18.7
argc5=1                应为 1，确认 rild 参数还是完整的
（下面若干行）          若失败，这里会出现 qcril 的 DMS/baseband 错误
```

如果 `baseband=` 有值但字符串开头缺字符，说明两个结构的字符串偏移不同（一个在
`+4`、一个在 `+8`），那就是 idl 布局差异，不是命令号问题——此时退回显示层兜底。

### 18.7 备选：显示层兜底

如果改命令号也不通，就不要再往闭源二进制里加补丁了。直接让显示拿到真实值：

```
# modem 分区挂在 /firmware，版本串在 image/modem.b* 里
v=$(grep -ao 'MPSS\.DI\.[0-9A-Za-z._-]*' /firmware/image/modem.b* | head -1)
setprop gsm.version.baseband "$v"
```

也可以在 `system.prop` 里直接写死
`gsm.version.baseband=MPSS.DI.2.0.1.c9-00059-M8926DAAAANAZM-1`（这个串来自
modem 分区，见 §17.6 末尾）。`gsm.version.baseband` 不是 `ro.*`，电话栈只在请求
成功时才覆盖它，所以请求一直失败的前提下，写进去的值不会被抹掉。

顺带记一下这颗 modem 的 `/firmware/VERINFO/VER_INFO.TXT` 只有 23 字节：

```
M8926AAAAANLYD1015015.2
```

那是 Kyocera 的构建号，不是基带版本，别拿它当值用。

## 19. QMI 的发前校验：响应缓冲长度必须**精确相等**

### 19.1 判据在 `libqmi_cci.so` 里，不在 qcril 里

`qmi_client_send_msg_sync` 转发到内部实现后，第一件事是问 IDL 表这条消息的
C 结构有多大，然后拿调用方传进来的长度去比：

```
2478: bl  qmi_idl_get_message_c_struct_len(service, RESPONSE=0, msg_id, &need)
2486: ldr r1, [sp, #104]     ; 调用方传的 resp_c_struct_len
2484: ldr r3, [sp, #40]      ; 表里说的 need
2486: cmp r1, r3
2488: bne 25a8               ; ← 不相等就走
25a8: mov r7, #-1            ; 直接 return -1，请求根本不发
```

**是 `bne`，不是 `blo`。** 传大了也不行、传小了也不行，必须一分不差。
请求侧同理，但有一条例外：`req_len == 0` 时整段校验被跳过（`cmp sl,#0; beq`），
于是空请求会被当成"这条消息没有请求体"直接编码出去。

这条 `bne` 解释了全部现象：11 ms 失败、logcat 里一条错误都没有（失败发生在本进程，
连 QMUX 都没走到）、改 msg id 毫无反应。

### 19.2 那张 IDL 表在哪，怎么自己解

不需要外部规范文档，`libqmiservices.so` 里带的就是完整定义：

- `dms_get_service_object_internal_v01` 用 `ldr r0,[pc,#4]; add r0,pc` 返回
  service object，落在 `.data` 的 `0x150b8`；
- object `+0x24` 指向 type table object；
- object `+0x10` 存着 req/resp 各自的**消息条数**（低半字 resp、高半字 req，都是 56）；
- object `+0x18` / `+0x1c` 是 resp / req 的**消息表指针**（`0x91fe` / `0x937a`）；
- 消息表每条 **6 字节**：`{uint16 msg_id; uint16 packed; uint16 extra}`，
  `packed` 高 4 位选类型组、低 12 位是组内序号；
- 类型描述 `+0x0c` 是 `{uint32 size; uint32 type_ptr}` 数组，**`size` 就是
  `sizeof()` 那个 C 结构**。

按这个走一遍，三个已知量全部对上 qcril 代码里的立即数，说明这份解析是对的。

### 19.3 三条命令的实际尺寸

| 命令 | 名称 | req 结构 | resp 结构 | qcril 实际传 | 结果 |
|---|---|---|---|---|---|
| `0x25` | GET_DEVICE_SERIAL_NUMBERS | 空 | **368** | resp 368 ✓ | 成功（`*#06#` 的 MEID） |
| `0x51` | GET_SW_VERSION | **12** | 44 | req **0** ✗ / resp 44 ✓ | 发出去了，modem 拒 |
| `0x23` | GET_DEVICE_REV_ID | 空 | **540** | resp **44** ✗ | 本地 `return -1` |

`368` 和 `44` 与 `qcril_qmi_nas_dms_request_device_identity` /
`..._baseband_version` 里的 `mov.w r2,#368` / `#44` 完全一致——这是这条解析链
可信的理由。

### 19.4 两条路各堵在哪

**`0x51`**：长度对得上，所以它**真的发到了 modem**。请求侧没有问题——IDL 给
这条命令的请求结构就是 **1 字节的空结构**，`qcril` 传 `NULL + 0` 是合法形态，
`req_len == 0` 时那段校验本来就被跳过。堵住的是**响应侧两道独立的闸**：

| | 表里说的 | 这颗 modem 要回的 |
|---|---|---|
| 响应 c-struct | 44 字节（版本串在 `+8`，容量 36 = 35 字符 + NUL） | 47 字符 |
| 响应编码上限（消息表第三半字） | 42 字节 | TLV 头 + 数组头 + 1 + 1 + 47 ≈ 53～55 |

版本串本身 47 字符：`MPSS.DI.2.0.1.c9-00059-M8926DAAAANAZM-1.66647.1`。两条都
超，所以 modem 的回复进不了 `libqmi_cci` 给的那块中转缓冲，解码失败，
`qcril` 只能回 `GENERIC_FAILURE`。

**`0x23`**：`540 ≠ 44`，`bne` 直接跳到 `return -1`。这就是 fix55 一个字节补丁
完全没有动静的原因——**它连发送都没走到**。

而 540 字节在这条路上放不下：函数开头 `sub sp, #120`，响应缓冲在 `sp+72`，
44 字节正好铺到 `sp+115`，`sp+116` 是 stack canary。**缓冲加不大**。真要让
`0x23` 跑起来，得把缓冲指针改成指向一块 540 字节的全局区，动三条指令外加
找 BSS 空间——为了显示一个字符串，风险与收益不成比例。

### 19.5 fix56 做的三件事

1. **撤销 `0x23` 补丁**。`/vendor/lib/libril-qc-qmi-1.so` 的 md5 回到原厂的
   `cbdf5c2dc7025b59f24abe1f5c9d5e40`，`0x1ab3f4` 处恢复成 `4ff05101`（`0x51`）。
   留着它只会在下次读代码时误导人。
2. **显示兜底（已撤回）**。fix56 曾在 `system.prop` 里写过
   `gsm.version.baseband=MPSS.DI.2.0.1.c9-00059-M8926DAAAANAZM-1.66647.1`，
   值取自 modem 分区 `0x26ea1f8` 处的版本头，紧挨着构建时间
   `20160810_175730`——说明这颗 modem 被 OTA 更新过，2014 那个串只是编译
   路径的一部分（在 `CRMBuilds/.../b/modem_proc/...` 里出现过上千次），
   不是版本号。
   刷入后设置里确实显示了这行字，但 logcat 证明 `BASEBAND_VERSION` 仍然
   每次失败（10–19 ms，`GENERIC_FAILURE`），也就是说**那只是把显示修好了，
   问题一个没动**。这个值已经删掉：一个看起来正确、实际来自手写属性的字段，
   比"未知"更容易骗过下一次排查。
3. **打开 qcril 的消息日志（没成）**。当时在 `kyl23-extra.rc` 的
   `on post-fs-data` 里加了 `setprop persist.radio.adb_log_on 1`，实测每次
   开机读回都是 0：那个 section 跑在 `load_persist_props_action` **之前**，
   init 随后从 `/data/property` 载入旧值 0 把它盖掉。这行已经删了。
   能用的是系统起来之后 `setprop persist.radio.adb_log_on 1`——它写的是同一个
   `/data/property` 文件，下次开机留得住。

### 19.6 实测：兜底那次开机看到了什么

fix56 刷入后回传的 dump：

```
baseband=MPSS.DI.2.0.1.c9-00059-M8926DAAAANAZM-1.66647.1   兜底生效
adb_log=0                                                  开关从来没起来过
argc5=1                                                     rild 参数仍然完整
-- BASEBAND_VERSION --   [3657] error: GENERIC_FAILURE, 10–19 ms
```

跨多次开机都是同一结果（`01-01 11:43:14.615`、`01-02 06:28:59.567` …），
没有一次成功；`subsys1 modem state=ONLINE`，log.img 里也没有 modem crash。
也就是说那行字**只可能来自 `system.prop`**，RIL 侧一点没变。

`adb_log=0` 说明 QMI 的 hex 根本没收，所以"看错误码"这一步没法做——这也是
19.5 第 3 条要撤回的原因。要看就得先 `setprop persist.radio.adb_log_on 1`、
重启，再取一次 `version` 段。

### 19.7 结论：这条线到此为止

- RIL/IDL 是 **2015-08** 编的，modem 是 **2016-08** 的，中间这颗 modem 被
  单独 OTA 过，版本串从 30 多字符长到 47 字符，越过了 IDL 的两个上限。
  出厂 `build.prop` 里没有 `gsm.version.baseband`，说明出厂时这个请求是能
  成功的——不是移植弄坏的，也不是库被换过（四个 QMI 库的 md5 与原厂镜像
  逐一相同）。
- 真治本要同时改四处：消息表编码上限 42→64（位置已知，一条 `strh`）、
  IDL 里版本串 `max` 36→48（在未公开的打包 blob 里找那个字节，盲改）、
  `qcril` 那 44 字节栈缓冲挪到全局（`sp+72..115` 紧挨 canary，原地扩不了）、
  上报长度常量 33→48。收益是**显示 modem 里同一个字符串**——和手动写进
  `system.prop` 的内容一字不差。风险与收益不成比例，不做。
- 因此 `gsm.version.baseband` **不设**，设置里显示"未知"。这是真实状态。
  如果哪天要确认这颗 modem 的版本，直接读 modem 分区 `0x26ea1f8`，或者看
  `/vendor/bin/kcstate.sh` 的 `modem` 段。
- 若以后 modem 再被 OTA、或换了主板，需要重新确认这个偏移还有效。

## 20. USB：组合配置写在了一个没人安装的文件里

### 20.1 现象

插上电脑后设备管理器**毫无反应**，手机只在充电，通知栏也不出现"USB 用途"。
换线、换口、换电脑都一样，而且不是某个版本才有的——移植以来的每一版都这样。

### 20.2 根因

7.1 的框架会把 `persist.sys.usb.config` 写进 `sys.usb.config`：调试关着写 `mtp`，
打开写 `mtp,adb`。`system/core/rootdir/init.usb.rc` 只应答 `none`、`adb`、
`accessory`、`audio_source` 几种，**没有 `mtp`**——这本来就该由设备自己补。

我们确实写了一份，但在 `device/kyocera/kc01/rootdir/init.kc01.usb.rc`，而它从来没被
装进系统：

- `init.rc` 只 `import /init.${ro.hardware}.rc`，`ro.hardware` 是 `qcom`，
  所以真正生效的板级 init 是 `msm8926-common/rootdir/init.qcom.rc`；
- `lineage-common.mk` 只 copy 了那一个 rc，`kc01/rootdir/` 下的文件一个都没进 ramdisk；
- `kc01/device.mk` 的注释自己就写着"rootdir 下的 stock init 文件是给完整 ROM 参考的，
  不复制进镜像"。

于是一个 `on property:sys.usb.config=mtp` 都没有。gadget 停在 `enable 0`，D+ 不上拉，
电脑端什么也看不到，Android 侧也没有 connected 事件——自然没有 USB 通知，
用户也就没有"传输文件"可选。**死循环**。

对照原厂：4.4 的 `boot.img` ramdisk 里有 `init.kyocera.usb.rc`，把 mtp /
mtp,adb / mass_storage / diag 各种组合写得整整齐齐，PID 是 0a27 / 0a28 / 0a23。
我们的那份只学了 `mtp,adb`，还把它映射成 `adb`（因为当时以为内核没有 MTP——
其实 `CONFIG_USB_G_ANDROID=y` 把 `f_mtp.c` 一起编进去了）。

### 20.3 修法

1. 把组合搬进 `msm8926-common/rootdir/init.qcom.rc`：`mtp`、`mtp,adb`、`ptp`、
   `ptp,adb`、`mass_storage`，PID 用原厂的 0a28 / 0a27 / 0a23，`functions` 照实写
   `${sys.usb.config}`，不再折成 adb；
2. `BoardConfigCommon.mk` 加 `ADDITIONAL_DEFAULT_PROPERTIES += persist.sys.usb.config=mtp`。
   这不是"默认开 adb"——adb 仍然只在打开 USB 调试后才出现，只是让开机有个明确的
   组合，`init.usb.rc` 的 `on boot && property:persist.sys.usb.config=*` 才会触发；
3. 删掉 `kc01/rootdir/init.kc01.usb.rc`，`init.kc01.rc` 里那行 `import` 换成注释，
   免得下次又有人以为它生效；
4. `kcstate.sh` 加 `usb` 段：`persist/config/state` 三个属性、`enable`/`functions`、
   以及 dmesg 里 gadget 的行。以后再遇到，一次 dump 就能定位。

### 20.4 已知遗留

`persist.*` 属性一旦在 `/data/property` 里存在，build.prop 里的默认值就不再起作用。
设备上可能残留旧值（`none` 或 `adb`）：

- `adb`：`init.usb.rc` 有分支，照样能枚举，只是设备名是 18d1:D002；
- `none`：仍然只充电。需要在系统起来后执行一次
  `setprop persist.sys.usb.config mtp`，它会写回 `/data/property`，下次开机生效。

要干净验证，可以 `wipe /data` 后刷机，也可以先手动改这一条属性。

## 21. prebuilt/kernel 停在 11-07：CI 出的整包开不了机

### 21.1 现象

`boot-fix57.img` 是从 CI 产物里原样取出的 boot（内核就是仓库的
`prebuilt/kernel`），刷进去**黑屏**，没有开机动画，adb 也起不来。整包里那份
boot 是同一个二进制，所以整包刷同样起不来——它此前从没被真正刷过。

### 21.2 判据：两个内核不是同一批

| | `prebuilt/kernel` | `boot-diag23.img` 里的 |
|---|---|---|
| 编译时间 | 2026-11-07 17:14 **#6** | 2026-11-12 14:03 **#20** |
| 编译目录 | `/workspace/src/kernel` | `/workspace/source/kernel` |
| md5 | `3d87f8d8…` | `eb39a954…` |
| 设备树 | `bc64efe7…` | `bc64efe7…`（逐字节相同） |

设备树、gcc 版本、页大小、cmdline 基串都一致，只有内核体不同。把两份 zImage
里各自的 gzip 段解出来做 `strings` 差集，只在 #20 里存在的串正好对应 11-07 之后
内核树改过的几批东西：

| 改动 | 时间 | 只在 #20 里的串 |
|---|---|---|
| `security/selinux/` 整体换核，24 个文件 +1435/−386 | 11-10 22:59 | `Android master kernel running Android M policy in compatibility mode`、`avtab: entry has extended permissions`、`permissive=%u` |
| `net/wireless/nl80211.c` 空指针防护 | 11-11 前 | `nl80211: vendor cmd without rdev/dev` |
| `drivers/gpu/ion/ion.c` 1 GiB 钳位 + 打印 | 11-11 12:51 | `IONBIG`、`IONA`、`IONFAIL` |
| `drivers/video/msm/mdss/*` pipe 类型回退 + 打印 | 11-11 17:12 | `OSCFB pset: fell back to pipe type` |
| `drivers/uio/msm_sharedmem.c` 按 reg-names 命名 | 11-12 01:15 | `uio %s registered` |
| `arch/arm/mm/fault.c` 用户态崩溃现场 | 11-12 | `USRFLT` 十余条 |

反方向，#6 里有、#20 里没有的是 Kyocera 定制 SELinux 的那几条：
`no permission in … realpath=… dev_name=…`、`no permission mount /system/... by
non-init process`。

两个 ramdisk 的差异只有 `kcrec`、`adb_keys`、USB 那几个 stanza 和构建指纹，
`sepolicy`、`file_contexts.bin`、`fstab.qcom`、`ueventd.*` 逐字节相同，都不影响启动。

### 21.3 为什么是黑屏而不是重启

init 在 first stage 就要把 ramdisk 里的 `sepolicy` 交给内核。7.1 这份策略是
policy version 30，带 extended permissions；#6 的 avtab 是换核之前的老代码，
认不了这些规则，`policydb_read` 直接失败。init 停在这一步，`adbd` 没起来，
屏幕当然是黑的，也不会进开机动画——和"卡 logo 后重启"是两回事，后者是
surfaceflinger 或 wlan 在跑。

### 21.4 处理

用当前内核树重编，`#22`，2026-11-16 00:15：

```bash
cd kernel && make -j32 ARCH=arm CROSS_COMPILE=arm-linux-gnueabi- zImage
```

同时做了两件事：

1. **去掉 11-11/11-12 加的诊断**：`USRFLT`（fault.c 整段恢复）、`OSCFB` 两处
   （`mdss_mdp_pipe.c` 整段恢复，`mdss_mdp_overlay.c` 只留 pipe 回退）、
   `IONBIG`/`IONA`/`IONFAIL`（只留 1 GiB 钳位，`IONFAIL` 回到原来的 `pr_debug`）。
   功能性改动全部保留：SELinux 换核、nl80211 防护、ion 钳位、mdss 回退、
   msm_sharedmem 命名。
2. **Makefile 加 `-fgnu89-inline`**。gcc 13 默认 `-std=gnu11`，`extern inline`
   变成"本单元导出定义"、普通 `inline` 变成"别处必须有定义"，老代码两头都会
   炸：`arch/arm/include/asm/ftrace.h` 的 `extern inline return_address()` 让每个
   .o 都带一份，链接报 *multiple definition*；`drivers/gpu/msm/kgsl_iommu.c` 的
   `inline kgsl_iommu_sync_lock()` 没人导出，链接报 *undefined reference*。
   加这一个 flag 就够，不必改源码。

vermagic 与 #20 完全一致（`3.4.0 SMP preempt mod_unload modversions ARMv7`），
导出符号没变，所以 `pronto_wlan.ko`、`kc_wp.ko` 不用重编。

### 21.5 教训

CI 不编内核，只搬 `prebuilt/kernel`。这个二进制一旦落后，**整包就是坏的，而且
CI 自己检查不出来**——workflow 里那道断言只验 `Linux version 3.4`，任何一版
3.4 内核都能过。以后换 `prebuilt` 前后，比对一下内核体里的特征串
（`IONBIG`、`OSCFB`、`compatibility mode` 这几条最灵敏）。

## 22. SurfaceFlinger 秒退的根因：Adreno 用相对路径 dlopen 自己的 GL 库

### 22.1 现象

刷完 system 后停在首屏（开机 logo），充电灯亮，`init` 每 4 秒重启一次
`surfaceflinger`，日志里是 `exited with status 0`，看起来像"正常退出"，很容易
被当成没崩。真正的证据只有 logcat 里有：

```
I SurfaceFlinger: SurfaceFlinger's main thread ready to run. Initializing graphics H/W...
D libEGL  : loaded /vendor/lib/egl/libEGL_adreno.so
D libEGL  : loaded /vendor/lib/egl/libGLESv1_CM_adreno.so
D libEGL  : loaded /vendor/lib/egl/libGLESv2_adreno.so
W Adreno-GSL: <os_lib_map:1303>: os_lib_map error: dlopen failed:
              library "egl/libGLESv2_adreno.so" not found
E Adreno-EGL: <egliLoadLibrary:631>: OpenGLES20 lib failed to load
E Adreno-EGL: <eglFetchClientAPIFunctions:3463>: NO OGL 2 functions
E Adreno-EGL: <eglCreateClientContextApiFunctions:2230>: Unable to fetch GL functions
W Adreno-EGL: <qeglDrvAPI_eglCreateContext:2507>: EGL_BAD_ALLOC
F SurfaceFlinger: EGLContext creation failed
F libc    : Fatal signal 6 (SIGABRT), code -6 in tid 4879 (surfaceflinger)
```

`init` 之所以报 `status 0`，是因为 `LOG_FATAL` 之后 SF 在 abort 之前自己退了
一次，信号 6 是后面 debuggerd 补的，别被这行糊弄。

### 22.2 为什么

`libEGL_adreno.so` 里写死了两个**相对**库名：

```
143088  egl/libGLESv1_CM_adreno.so
143292  egl/libGLESv2_adreno.so
```

dlopen 遇到相对路径是按进程 cwd 解析的，SF 的 cwd 是 `/`，于是去找
`/egl/libGLESv2_adreno.so`——永远不存在。库其实好好地躺在
`/vendor/lib/egl/` 下。

老的那份移植包能开机，是因为有人把 `libEGL_adreno.so` 里这两处字符串**就地改短**
了 4 个字节（`egl/` 前缀删掉、后面补 NUL），改成裸名 `libGLESv2_adreno.so`，
走的是默认搜索路径。文件大小一个字节都没变，157,836 B，所以谁也没注意。

### 22.3 这次为什么丢了

CI 从 AOSP 重新编/拷贝 `libEGL_adreno.so`，那两处字符串回到带前缀的原样。
fix56 之前的包是手工换过的二进制，fix57 之后直接取 CI 产物，补丁就没了。

判据：fix56 的 `/vendor/lib/egl/libEGL_adreno.so` mtime 是 2026-11-12 11:39
（手工换过），md5 `5049999e…`；CI 的是 `d69d77bf…`，两者只差这 49 个字节。
把 CI 那份按同样方式改短之后，md5 与 fix56 那份**逐字节相同**，等于把当年的
补丁精确复现出来。

### 22.4 处理

`system-fix60.img` 起，`/vendor/lib/egl/libEGL_adreno.so` 用改短过的那份
（`5049999e…`），属主 root、0644、SELinux `u:object_r:system_file:s0` 不变。
`libGLESv1_CM_adreno.so` 里还有一处同样的 `egl/libGLESv2_adreno.so`，那是创建
GLES1 上下文时才走的，不影响开机，暂不动。

`/vendor/bin/kc_bootanim.sh` 早就用 `cd` 绕过了同一个坑（开机动画能显示、
SF 起不来，两边症状不一样），所以这处一直没被发现。

### 22.5 教训

1. `exited with status 0` 不等于没崩。init 对 SF 这类 `oneshot` 服务的这条措辞
   会掩盖 SIGABRT，必须看 logcat 里的 `F/` 行。
2. 图形栈除错优先看 `Adreno-GSL` 和 `Adreno-EGL` 的 tag——EGL 自己会说清楚
   哪个库没找到，比反汇编 `libsurfaceflinger.so` 快一百倍。
3. 老包里手工改过的二进制要在文档里留指纹（这里就是 mtime + md5 + 改了哪 49
   字节），否则下次从 CI 重新出包必然复发。

## 23. 能开机之后：开机动画、蓝牙、WiFi

第 22 节修好 SurfaceFlinger 之后，系统终于走到开机动画这一步，然后卡在那里。
这一节记的是从"SF 正常"到"能进桌面"之间的三个问题，以及它们共同的成因：
**原厂 4.4 的 HAL 把 7.1 编的同名 HAL 挡住了。**

### 23.1 卡在开机动画：desc.txt 缺两个数

logcat 里只有两行：

```
I libEGL  : loaded /vendor/lib/egl/libEGL_adreno.so
I Adreno-EGL: <qeglDrvAPI_eglInitialize:410>: EGL 1.4 QUALCOMM
F libc    : Fatal signal 8 (SIGFPE), code -6, fault addr 0x381 in tid 1057 (BootAnimation)
F libc    : failed to resend signal during crash: Operation not permitted
```

`code -6` 是 `SI_TKILL`，不是硬件除零陷阱的 `code 1`（`FPE_INTDIV`），说明信号是
`raise(8)` 主动发的。`/system/bin/bootanimation` 反汇编里正好有这一段：

```
000083e4 <__aeabi_idiv0@@Base>:
    83e4:  push  {r1, lr}
    83e8:  mov   r0, #8
    83ec:  bl    364c <raise@plt>
```

libgcc 的整数除零辅助函数。`debuggerd` 没能留下 tombstone（`/cache/kc_tombstone_*`
都是 0 字节，进程已经消失），所以只能从二进制反推。

除数是 `/system/media/bootanimation.zip` 里的 `desc.txt`：

| | 原厂（能开机） | CI 产物 |
|---|---|---|
| 大小 | 23,894 B | 236,262 B |
| 第一行 | `540 960 1` | `  60` |
| 帧图 | `part1/01.jpg` 540×960 | 480 个 **1×1** PNG |

`BootAnimation` 用 `sscanf(line, "%d %d %d") == 3` 判断第一行，`"  60"` 只给得出
一个数，这行被丢弃，`Animation::fps` 保持构造时的 0，`movie()` 里做帧间隔的 64 位
取模就撞上 `__aeabi_idiv0`。

**为什么这一崩就永远停在首屏**：`bootanimation` 正常结束时才调
`SurfaceFlinger::bootFinished()`，那一步才置 `mBootAnimationComplete`，
`ActivityManagerService` 才会 `startHomeActivity()`。它崩了，AMS 就一直等，
屏幕停在 bootloader 的 static splash 上，而 `kcbtnled` 照样在跑——所以充电灯亮着，
人以为系统还在启动。

修法：把原厂那份 `bootanimation.zip` 放回 `prebuilt/media/`，workflow 在 sync 之后
覆盖 `vendor/lineage/prebuilt/bootanimation/bootanimation.zip`，并当场校验 desc.txt
第一行是三个数。

### 23.2 蓝牙打不开：加载到了 4.4 的 HAL

```
E HAL     : load: module=/vendor/lib/hw/bluetooth.default.so
E HAL     : dlopen failed: cannot locate symbol
            "_ZN7android10AudioTrack5writeEPKvj" referenced by
            "/system/vendor/lib/hw/bluetooth.default.so"...
E BluetoothServiceJni: No Bluetooth Library found
```

`AudioTrack::write(void const*, unsigned int)` 是 4.4 的签名；7.1 是
`write(void const*, size_t, bool)`，符号带 `b` 后缀。两个文件同时在镜像里：

| 路径 | 大小 | 来源 | 引用的符号 |
|---|---|---|---|
| `/system/lib/hw/bluetooth.default.so` | 1,448,792 | `system/bt` 编的 | `…5writeEPKvjb` |
| `/vendor/lib/hw/bluetooth.default.so` | 1,212,144 | 原厂 4.4 blob | `…5writeEPKvj` |

`hw_get_module()` 先走 `/vendor/lib/hw`，所以永远是错的那一个。原本靠
`libkccabi.so` 的 `LD_PRELOAD` 把这个符号补回全局作用域——它确实导出了
`_ZN7android10AudioTrack5writeEPKvj`（内部转调 7.1 的 `…jb`）——但 `LD_PRELOAD`
只对 init 直接 exec 的服务（`audioserver`、`mediaserver`）稳，对 zygote fork 出来的
`com.android.bluetooth` 不可靠，于是 dlopen 时符号仍然缺失。

修法：在 `lineage-common.mk` 里 `filter-out` 掉 vendor mk 对这三个 HAL 的拷贝，
让 `hw_get_module()` 回退到 `/system/lib/hw`：

```make
PRODUCT_COPY_FILES := $(filter-out \
    vendor/.../hw/bluetooth.default.so:% \
    vendor/.../hw/hwcomposer.msm8226.so:% \
    vendor/.../hw/gralloc.msm8226.so:%, \
    $(PRODUCT_COPY_FILES))
```

`hwcomposer` / `gralloc` 是同一个病：原厂那对（103 KB / 18 KB）和 7.1 那对
（141 KB / 26 KB）不能混用，第 22 节之前手工覆盖过它们，CI 出包时又会盖回去。

`camera.msm8226.so`、`audio.primary.msm8226.so`、`lights.default.so` 这些在 7.1 树里
没有对应实现，继续用原厂 blob，不动。

### 23.3 WiFi 打不开：finit_module 在 3.4 上不存在

```
D WifiHW  : finit_module for "/vendor/lib/modules/pronto/pronto_wlan.ko" failed:
            Function not implemented
E WifiStateMachine: Failed to load driver
E WifiController: WifiControllerWifi turn on failed
```

`finit_module` 是 3.8 才加的系统调用（ARM 上 `__NR_finit_module` = 379，而 3.4 的
编号表到 376 为止），3.4 内核回 `ENOSYS`。

`libkccabi.so` 里确实有一个 `finit_module`：

```
00000418 <finit_module>:
 418:  mov  r0, #0
 41c:  bx   lr
```

但框架根本不走这个符号。`libhardware_legacy.so` 的动态符号表里只有
`syscall@LIBC`，没有 `finit_module`；`wifi.c` 的 `insmod()` 是

```c
ret = syscall(__NR_finit_module, fd, args, 0);
```

`syscall()` 是个转发器，`LD_PRELOAD` 覆盖不到，所以 shim 从来没被用过。
`kcwifi` 提前 `insmod` 能让内核里有 `wlan`，但框架仍会自己再 `finit_module` 一次，
失败即 `Failed to load driver`，随后把刚加载的模块卸掉。

三条路，按代价排：

1. **给 3.4 内核补 `finit_module`**（syscall 379）。读 fd、`load_module()`，
   同名模块已加载时返回 0 而不是 `-EEXIST`，这样 `kcwifi` 的前置加载和框架的
   加载都算成功。改动集中在 `kernel/module.c` + `arch/arm/kernel/calls.S`，
   需要重编内核、重刷 boot。
2. **改 `libhardware_legacy.so`**，把 `syscall(__NR_finit_module, …)` 换成先查
   `/proc/modules`。这是 AOSP 源码，得在 workflow 里打补丁再编，改动面更大。
3. **让 `kcwifi` 成为唯一加载者**：关掉框架的加载路径。7.1 的 `wifi.c` 没有留开关，
   实际做不到。

现状：已按第一条走，见第 24 节（fix64 内核）。

### 23.4 教训

`/vendor/lib/hw` 优先于 `/system/lib/hw` 这件事，在这个移植里踩了三次：
hwcomposer/gralloc（第 22 节，手工覆盖）、bluetooth（本节）。
`vendor/kyocera/msm8926-common/msm8926-common-vendor.mk` 是
`tools/blobs/extract.py` 生成的，不能手改一行——要动就在 `lineage-common.mk` 里
`filter-out`，这样下次重新抽 blob 也不会被冲掉。

判断某个 HAL 该用哪一份，看它引用的 libmedia / libgui 符号有没有 `b` 后缀、
看它 NEEDED 里是 `libchrome.so`（7.1 的 Fluoride）还是 `libbt-hci.so`（4.4 的
bluedroid）。大小差一个数量级的，基本都是版本不同而不是裁剪。

### 23.5 fix62 的"蓝牙共享已停止运行"：HAL 换对了，补丁丢了

fix61 那一版加载的是原厂 4.4 的 HAL，死在 `AudioTrack::write` 的符号上（23.2）。
fix62 把 `/vendor/lib/hw/bluetooth.default.so` 换成 7.1 编的那份（1,448,792 B），
符号问题确实没了，但一开蓝牙就弹"蓝牙共享已停止运行"——症状换了，仍然不能用。

拿 fix56（蓝牙能开的那一版）逐字节比同一个文件，两份的差别只有 **2 字节**，
在文件偏移 `0xfd45c`：

```
fix56 : 07 24   movs r4, #7      ; CLOCK_BOOTTIME
fix62 : 04 46   mov  r4, r0      ; 编译器原样：沿用调用者给的 clockid（9）
```

`vaddr 0x10145c` 正是 15.2 里那个 `timer_create_internal()` 的入口。也就是说
15.2 的修法从 fix52 起一直是**对手工拼出来的镜像打字节补丁**——它从来没写进源码。
而 fix57 之后每一版都是从 CI 产物直接转的镜像：fix58–fix60 手工覆盖的是显示栈，
fix61 用的是原厂 HAL（连 `timer_create()` 都没走到），直到 fix62 才第一次把 7.1
编的 HAL 放回那个位置，于是 `mov r4, r0` 又回来了：clock 9 依旧不存在，
`timer_create()` 回 EINVAL，`lazy_initialize()` 退栈，第一次 `alarm_set()` 断言，
SIGABRT。UI 上就是"蓝牙共享已停止运行"。

所以不是这一版把蓝牙修坏了，是**这个补丁一直只活在某一版镜像的两个字节里**。

修法：把它写进源码。`patches/0002-bt-alarm-drop-clock-nine.patch` 把

```c
#if defined(KERNEL_MISSING_CLOCK_BOOTTIME_ALARM) && (KERNEL_MISSING_CLOCK_BOOTTIME_ALARM == TRUE)
static const clockid_t CLOCK_ID_ALARM = CLOCK_BOOTTIME;
#else
static const clockid_t CLOCK_ID_ALARM = CLOCK_BOOTTIME_ALARM;
#endif
```

改成无条件 `CLOCK_BOOTTIME`。上游其实为这种内核留了
`KERNEL_MISSING_CLOCK_BOOTTIME_ALARM` 这个开关，只是 14.1 的构建里没有任何地方
设它，所以那份代码永远走 `#else`。改完之后 CI 直出的 HAL 自带这个行为，不必再
每版手工改字节。

同时 fix63 镜像里两份 `bluetooth.default.so`（`/lib/hw` 和 `/vendor/lib/hw`）已经
按 fix56 改好，md5 `4ee10c46…`，可以立刻刷。

## 24. WiFi 的第二件事：把 finit_module 补进 3.4 内核

23.3 列的第三条路（"等内核改动排期"）就是现在这一条：给 3.4 加 syscall 379。

### 24.1 为什么必须在内核里补

框架那一侧的调用改不了。7.1 的 `libhardware_legacy.so` 里只有

```c
ret = syscall(__NR_finit_module, fd, args, 0);
```

`syscall()` 是个转发器：它把编号塞进 r7 直接 `svc 0`，不查任何符号表。所以
`libkccabi.so` 里那个 `finit_module`（`mov r0, #0; bx lr`）从来没被调用过——
它能骗过的只有 `dlsym()`，骗不过 `svc`。内核没有 379 号入口，
`cmp scno, #NR_syscalls` 就把这次调用变成 `-ENOSYS`，logcat 里是
`Function not implemented`。

`NR_syscalls` 是 `calls.S` 里数出来的（每条 `CALL()` 加一），所以补入口要同时改
三处：编号表、调用表、实现。编号用 379 而不是"下一个空位"，是因为 bionic 的
`__NR_finit_module` 写死 379；378 是 3.5 的 `kcmp`，这棵树没有，放 `sys_ni_syscall`
占位，免得以后有人把 378 当成 finit_module。

### 24.2 实现要点

上游 3.8 是让 loader 自己 `mmap` 文件；这棵树的 `load_module()` 签名是
`(void __user *umod, unsigned long len, const char __user *uargs)`，内部
`copy_and_check()` 先 `copy_from_user()` 一整份到 vmalloc。所以这里反过来做：
先把文件读进内核缓冲，抬 `KERNEL_DS`，再调 `sys_init_module()`——和当年
`insmod(8)` 拿着 mmap 出来的指针调 `init_module(2)` 完全等价。

两个刻意的偏离：

- **`flags` 必须是 0。** `MODULE_INIT_IGNORE_VERMAGIC` 会让 vermagic 不匹配的模块
  也装进来；这套移植重编内核的前提就是 vermagic 要和原厂 `mmc_protect.ko`、
  `kc_wp.ko` 对得上（见 kernel-patches/README），这个口子不能开。
- **`-EEXIST` 当成功。** `kcwifi` 开机先 insmod 一次把 wlan0 拉起来，框架随后
  再加载同一个文件。同名模块已经在那里，正是调用方想要的状态；照上游返回
  `-EEXIST`，`WifiStateMachine` 会认为加载失败并把接口拆掉。

### 24.3 验证（不用刷机就能确认一半）

`sys_call_table[379]` 必须等于 `sys_finit_module`：

```
c0105a44 T sys_call_table
c01d6198 T sys_finit_module
377 0xc023af60  sys_process_vm_writev
378 0xc01a834c  sys_ni_syscall
379 0xc01d6198  sys_finit_module      <- 对上了
```

`strings vmlinux | grep "3.4.0 SMP preempt"` 仍是
`3.4.0 SMP preempt mod_unload modversions ARMv7`，和原厂预编译模块的 vermagic
逐字相同，`pronto_wlan.ko`、`kc_wp.ko` 都不需要重编。

镜像：`prebuilt/kernel` 换成这一版（5,734,352 B，md5 `521ea557…`），
`boot-fix64.img` 由 `boot-fix58.img` 的 ramdisk + QCDT + cmdline 原样重封，
只换 kernel 和头里的 SHA1（8,431,616 B）。

### 24.4 刷完该看到什么

驱动加载这一步应该从

```
D WifiHW  : finit_module for ".../pronto_wlan.ko" failed: Function not implemented
E WifiStateMachine: Failed to load driver
```

变成没有这两行：`wifi_load_driver()` 拿到 0，`wlan.driver.status` 置 `ok`，
接着是 supplicant 起来、扫描出列表。如果还有别的失败，那至少是**下一层**的
问题（firmware、MAC、supplicant 控制口），不再是 syscall 缺失。

## 25. audioserver 每五秒崩一次：libkccabi 的 list_* 参数顺序反了

刷上能开机、WiFi 和蓝牙都正常的版本之后，手机开机就烫、整机卡。这一次
不是显示也不是无线，是音频。

### 25.1 现场

`cache` 里的 logcat，同一次开机：

```
10:12:46.830 F/libc (  493): Fatal signal 11 (SIGSEGV), code 1, fault addr 0x0 in tid 1021 (AudioOut_D)
10:12:48.193 F/libc ( 3397): Fatal signal 11 ... tid 3410 (AudioOut_D)
10:12:52.381 F/libc ( 3473): Fatal signal 11 ... tid 3486 (AudioOut_D)
10:12:57.213 F/libc ( 3607): Fatal signal 11 ... tid 3623 (AudioOut_D)
   ... 每五秒一次，pid 一路往上加
```

pid 一直变大，说明每次都是新起的 audioserver，崩了被 init 拉回来，再崩。
后果是连锁的：

```
E/ActivityManager: ANR in com.android.settings
E/ActivityManager:   Reason: Input dispatching timed out (... Wait queue head age: 12643.5ms.)
E/ActivityManager: Load: 15.87 / 5.03 / 1.77
E/ActivityManager:   87% 518/sh: 5.5% user + 81% kernel
E/ActivityManager:   86% 423/sh: 5% user + 81% kernel
W/AudioService: Long monitor contention ... setStreamVolumeIndex ... for 34.292s
```

四核机器 load 15.87、两个核被吃满、AudioService 的锁一持有就是 34 秒——
点什么都慢，电池跟着掉。烫是 CPU 跑出来的，不是电池或充电。

### 25.2 崩在哪

诊断内核（#20）留下的 `USRFLT` 记录把地址钉死了：

```
USRFLT pc b6430380 in libkccabi.so off=00000380
```

`libkccabi.so` 的 `list_add_tail` 只有 5 条指令（0x378 起），0x380 是其中
第三条：

```
0378: ldr  r3, [r0, #4]     ; r3 = head->prev
037c: stm  r1, {r0, r3}     ; item->next = head; item->prev = head->prev
0380: str  r1, [r3]         ; head->prev->next = item   <-- fault addr 0x0
0384: str  r1, [r0, #4]     ; head->prev = item
```

`r3` 是 0。按这个顺序，`r3` 来自 `head->prev`，而 `head` 是 r1。调用点
（`audio.primary.msm8226.so` 0x4470）是：

```
4438: bl   calloc              ; r0 = calloc(1, 12) -> r6，一个全新的 listnode + 4 字节数据
4464: add  r0, r4, #248        ; r0 = ctx + 0xf8
4468: mov  r1, r6              ; r1 = calloc 出来的
4470: bl   list_add_tail
```

r0 是 ctx 里那个长命的链表头，r1 是刚 calloc 出来的项。`calloc` 的
`prev` 当然是 0——**如果实现把 r1 当 head 来读，就必然空指针**。

### 25.3 为什么反了

4.4 和 7.1 的这个 API 同名、同结构体，参数顺序相反：

```c
/* android-4.4.4_r1 libcutils/list.c —— 头在前 */
void list_add_tail(struct listnode *head, struct listnode *item)
{
    item->next = head;
    item->prev = head->prev;
    head->prev->next = item;
    head->prev = item;
}

/* android-7.1 cutils/list.h —— 变成 inline，而且项在前 */
static inline void list_add_tail(struct listnode *node, struct listnode *head)
```

4.4 的 blob 编译时看到的是前者，所以 r0 = 头、r1 = 项；libkccabi 是照着
7.1 的原型写的（r0 = 项、r1 = 头），寄存器全反。`list_add_head` 一样反。
`list_init` 和 `list_remove` 只有一项参数，没这个问题。

这也是为什么它只崩音频：`audio.primary.msm8226.so` 是镜像里唯一还引用
`list_add_tail` 的 4.4 blob（另一个引用者是 libkccabi 自己）。

### 25.4 修法

参数的角色在库内部交换，两个函数各自还是 20 字节，原地改，文件大小、符号
表、其他函数一律不动：

```
list_add_tail(head=r0, item=r1)
0378: ldr  r3, [r0, #4]     ; r3 = head->prev
037c: stm  r1, {r0, r3}     ; item->next = head; item->prev = head->prev
0380: str  r1, [r3]         ; head->prev->next = item
0384: str  r1, [r0, #4]     ; head->prev = item

list_add_head(head=r0, item=r1)
038c: ldr  r3, [r0]         ; head->next
0390: str  r3, [r1]         ; item->next = head->next
0394: str  r0, [r1, #4]     ; item->prev = head
0398: str  r1, [r3, #4]     ; head->next->prev = item
039c: str  r1, [r0]         ; head->next = item
```

`tools/blobs/fix_kccabi_list.py` 做这件事，幂等，`--check` 只检查不写。
`libkccabi.so`（现在 preload 的那个，5972 B，改后 md5 `d639f118…`）和
`libkcabi.so`（早期的同名库，5680 B，今天没人加载，一并改掉免得以后踩）。

### 25.5 刷完该看到什么

`Fatal signal 11 ... (AudioOut_D)` 应该一条都没有，audioserver 的 pid
稳定不变，`Load:` 回到个位数。

**声音仍然要另说**：同一次开机里还有

```
subsys0 name=adsp state=OFFLINE
init: Service 'adsprpcd' (pid 550) exited with status 255
APR: Wrong parameters      (每五秒一次，跟着 audioserver 的重启周期)
```

ADSP 没起来，音频 DSP 用不了，HAL 出不了声。崩是因为链表被踩坏，不出声是
因为 DSP 不在——两件事。把崩止住，系统先恢复可用；ADSP 的 PIL 加载是下一个
独立问题。

## 26. 声音（一）：卡在 AP R 之前的那一步，和它背后的时序

25 节把 audioserver 五秒一崩止住了。声音还是不出，这一节把"为什么不出"拆开。

### 26.1 崩在哪一步，先钉死

`audio.primary.msm8226.so` 的 `start_output_stream()` 反汇编（`0x8f84`）：

```
8fdc: ldr  r5, [r4, #184]      ; out->devices
8ffc: bl   __android_log_print ; "start_output_stream: enter: usecase(%d: %s) devices(%#x)"
900c: bl   platform_get_pcm_device_id
9028: bl   calloc              ; 32 字节的 listnode
905c: mov  r1, r5              ; r1 = 刚 calloc 出来的
9060: add  r0, r6, #184        ; r0 = adev 里那个长命的链表头
9064: bl   list_add_tail       ; <-- 就是这里
9074: bl   select_devices
90c8: bl   pcm_open
```

`list_add_tail` **在 `pcm_open` 之前**。所以 25 节那个空指针一崩，HAL 根本走
不到打开 PCM、更走不到和 ADSP 说话那一步；日志里 "start_output_stream: enter"
之后紧跟着就是 SIGSEGV，位置完全对得上。先把 25 节的补丁刷上去，这一层才会
露出下一层。

### 26.2 下一层：ASM 会话拿到的 APR 句柄是 NULL

同一批日志里，每次 audioserver 起来都有且只有一条：

```
<3>#3[    9.484429] APR: Wrong parameters
```

来源是 `arch/arm/mach-msm/qdsp6v2/apr.c:271`：

```c
int apr_send_pkt(void *handle, uint32_t *buf)
{
	if (!handle || !buf) {
		pr_err("APR: Wrong parameters\n");
		return -EINVAL;
	}
```

`handle` 是 `q6asm.c` 里的 `ac->apr`，也就是 `apr_register("ADSP", "ASM", …)`
的返回值。它不是"ADSP 没起来"（那种情况是下一句 `Still dsp is not Up`），而是
注册函数已经返回了 NULL、调用方没检查就往下发。没有 ASM 会话，就没有
`q6asm_open_write`，也就没有 PCM 数据通路——出声的前提是先让这次注册成功。

### 26.3 时序：ADSP 比 audioserver 晚

原厂是这么干的（`init.qcom.rc`，`on early-boot`，一行）：

```
write /sys/kernel/boot_adsp/boot 1
```

这一版移植一直只靠 `kcadsp` 服务去写同一个节点，而那个服务是 `post-fs-data`
里 `start kcadsp` 拉起来的，落到时间轴上：

```
4.29s  fs_mgr 挂上 /firmware（modem 分区，ADSP 镜像在这里）
5.40s  audioserver 起
5.99s  kcadsp 起
6.4s   adsp ONLINE        <- kcadsp 自己记的 "adsp ONLINE after 2s"
8.9s   声卡 msm8226tapansnd 注册完成
```

也就是音频子系统先睁眼、DSP 后上线。`apr_register()` 对 `APR_DEST_QDSP6` 只在
`q6 state == DOWN` 时等 1 秒（`apr_wait_for_device_up`），等不到就返回 NULL，
之后那次 `apr_send_pkt` 就是上面那条错误。audioserver 每五秒重来一次，但每次
都在同一个窗口里撞上同一堵墙。

修法照抄原厂：在 `kyl23-extra.rc` 里加

```
on early-boot
    write /sys/kernel/boot_adsp/boot 1
```

`early-boot` 在 `mount_all` 之后、`class_start main` 之前，`/firmware` 已经挂好，
比 audioserver 早一整个阶段。`kcadsp` 保留，作为"这一拍 PIL 还没准备好"时的
重试。

### 26.4 下一次 dump 要看什么

> **已被 27 节推翻。** 26.3 的 `early-boot` 修法在真机上无效，26.2 关于
> `apr_register()` 等 1 秒的描述也是错的。结论以 27 节为准。

`kcadsp.sh` 加了四行证据，写进 `/cache/kcadsp.log`：

```
fw /firmware/image: N adsp* files [...]     <- 镜像到底在不在 modem 分区
dev adsprpc: ...
pil-state:   N loading from                 <- PIL 有没有真的搬镜像
pil-after / apr-open / cards+4s
```

如果 `fw` 那行是 0 个文件，问题就在 modem 分区而不是内核；如果 `loading from`
一直是 0 而 state 却是 ONLINE，那就是 subsystem 状态和 PIL 对不上，得回头看
`adsp-loader` 的 `subsystem_get()` 返回值。

## 27. 声音（二）：26 节的结论是错的，触发点搬进内核

26 节给出的修法是"照抄原厂，在 `early-boot` 写一次 `/sys/kernel/boot_adsp/boot`"。
fix66 就这么做了，设备刷完、dump 交上来，**没有用**。这一节把不对的地方逐条更正。

### 27.1 先说这一版成立的结论

25 节的 `list_add_tail` 补丁确实生效了：整份日志里 `Fatal signal 11` 和
`USRFLT pc b6430380` 一条都没有，`audioserver` 不再是每五秒 SIGSEGV 一次，而是
**自己退出**（`exited with status 0`）。所以链表那一层现在是通的，别再改它。

### 27.2 但 audioserver 仍然每五秒退出一次，一直退到 217 秒

```
#0[   61.849] init: Service 'audioserver' (pid 493) exited with status 0
#0[   61.851] init: Starting service 'audioserver'...
#1[   62.339] APR: Wrong parameters
#1[   62.339] adm_get_params: Failed to Get Params on port 16385
#0[   62.436] msm_audio_ion_import: DMA Buf name=audio_acdb_client
#3[   63.171] init: Service 'audioserver' (pid 3397) exited with status 0
```

同样的四行，33 次，间隔 5 秒，一直到日志末尾。**这就否掉了"时序差几百毫秒"的
说法**：如果 ADSP 在 8.9 s 就上了线，60 s 之后重启的 audioserver 不可能还撞同一
堵墙。它一次都没成功，说明 ADSP 到 217 s 仍然是 DOWN。

### 27.3 26.2 那段的更正：`apr_register()` 对 QDSP6 不等 1 秒

26 节写"`apr_register()` 对 `APR_DEST_QDSP6` 只在 `q6 state == DOWN` 时等 1 秒"。
看 `apr_v2.c:57`：

```c
if (dest_id == APR_DEST_QDSP6) {
        if (apr_get_q6_state() != APR_SUBSYS_LOADED) {
                pr_err("%s: adsp not up\n", __func__);
                return NULL;
        }
```

等 1 秒（`apr_wait_for_device_up`）的是 MODEM 那条分支，QDSP6 是**立刻返回 NULL**。
而 `adsp_loader_do()` 和 lpass 的 `SUBSYS_AFTER_POWERUP` 通知都会把 q6 置
`LOADED`。所以 "APR 报错" 的充分条件是 "ADSP 没加载"，没有别的可能。

另外 `adm_get_params()`（`q6adm.c:375`）不检查 `this_adm.apr` 就往下发，所以每次
audioserver 起来都会先撞出一条 `APR: Wrong parameters` —— 它是**症状**，不是病因，
别拿它当线索。

### 27.4 `early-boot` 到底落在哪一拍

这份日志把时间轴钉死了：

```
4.688s  fs_mgr 挂 /firmware（vfat modem 分区，adsp.mdt/adsp.b0* 在这里）
4.7-5.9s post-fs-data：sysinit、kcbt.sh、kcfuse.sh、kcboot、kcfix、两次 rm
5.946s  exec 5 退出（kcfix 结束）
5.996s  kcssr / kcadsp 起  <- 这是 class core，即 boot 阶段，early-boot 紧挨其前
6.137s  adsprpcd 起
6.142s  audioserver 起
```

也就是说 `early-boot` 落在 5.99 s，和 audioserver 之间只有 **150 ms**，而
`pil_boot()` 要等 `request_firmware()` 把镜像从用户态搬进来、再做认证，本身就要
好几秒。**用户态没有哪个阶段来得及**，这是结构性的，不是调参数能解决的。

顺带一提：`write` 是同步的，`pil_boot()` 会在 `request_firmware()` 里待到超时
（默认 60 s），一旦真的慢起来，`early-boot` 之后的所有服务都得跟着等。fix67 把这条
写操作从 rc 里删掉了。

### 27.5 之前那些"证据"为什么不可信

两件事叠在一起，让 26 节得出了错误结论：

1. **`kcadsp.sh` 按序号轮询，没校验名字。** 它读的是 `subsys0/state`，而
   `subsysN` 的编号取决于 PIL 各 desc 的注册顺序。日志里
   `pil-q6v5-lpass` 在 0.967 s、`pil_pronto` 0.971 s、`pil_venus` 0.974 s 依次
   probe，"subsys0 就是 adsp" 从来没有被验证过。于是脚本 1 秒就报
   `adsp ONLINE after 1s`，而 `echo 1 > /sys/kernel/boot_adsp/boot` 是丢在子
   shell 里跑的，成没成功根本没人看。
2. **`/cache` 的日志 dump 不出来。** 这次 dump 的 `20_cache.img.part` 只有
   21 MB（`20,000,192` 字节），而 `/cache` 是 480 MB 的 ext4（块 4096、
   `117248` 块）。更糟的是根目录数据块在 `100631` 块 = 412 MB 处，连目录都读不
   到 —— `debugfs` 直接报 `Can't read a block bitmap`。所以 `/cache/kcadsp.log`
   和 `/cache/lc.txt` 无论如何都取不到。

还有一条要记住：`21_log.img` 是裸分区，里面叠着三次开机的内核日志（`#23`、
`#20`、`#22`），每次只剩两千多行时间戳 —— 有明显丢行。**"日志里没看到"不能当成
"没发生"**，只能当成"没有证据"。这也是 fix67 要提高日志重复率、并把关键信息往
内核日志里搬的原因。

### 27.6 fix67 的两件事

内核（`0003-adsp-loader-boot-from-kernel.patch`）：`adsp-loader` 驱动里挂一个
delayed work，6 s 起、每 2 s 一次、最多 20 次，调 `subsystem_get("adsp")`，每次
打一行带返回码的日志。ADSP 一起来就停。这样"没人触发"和"触发失败"在 dump 里一眼
可分，而且不再依赖任何用户态阶段。

用户态（`kcadsp.sh`）：从"驱动加载"改成"观察 + 取证"。

* 按 `name == adsp` 找子系统，不再用 `subsys0`；
* 观察 20 s，记录 ONLINE 的时刻；
* 把 `dmesg` 里 `adsp-loader:` / `pil-` / `APR` 的行，以及 `/cache/lc.txt`
  （KCLED 抓的 logcat）里 `audio|AudioFlinger|AudioPolicy|HAL|tapan` 的最后 20 行，
  以 `<6>KCADSP` / `<6>KCLOG` 前缀写进 `/dev/kmsg` —— 只有内核日志会进
  `21_log.img`，logcat 里的真正原因（audioserver 为什么 exit 0）以前从来没被带
  出来过；
* 全部输出放在一个后台子 shell 里，最多 32 行：`/dev/kmsg` 的写有可能卡在 console
  上，卡住的是一个要退出的子进程，不是 init。

### 27.7 下一次 dump 看三样

```
grep -a "adsp-loader:" 21_log.img        # 试了几次、每次返回码多少
grep -a "KCADSP"       21_log.img        # 最后状态、卡在哪个子系统
grep -a "KCLOG"        21_log.img        # audioserver 退出前 AudioFlinger 说了什么
```

`rc` 的含义：`-2`（`ENOENT`）= 固件没找到，去查 `/firmware/image` 里的
`adsp.mdt`；`-5`/`-13`/`-22` = 拿到了但被拒（认证/参数），那就是 PIL + TZ 那一层；
如果 20 次全失败而 `state` 一直是 `OFFLINE`，下一步是把 `pil_boot()` 里的
`request_firmware_direct()` 返回值也打出来。

## 28. 声音（三）：ADSP 一起来，音频栈就是好的

> **本节 28.1 与 28.6 已被 29 节推翻，保留原文只作记录。** 那两句"boot 分区没写进去"
> 建立在"低偏移 = 最新"的假设上，而这个日志分区是整块复用的三槽 DBGC 环，还会丢行，
> 物理顺序和时间顺序无关；设备实际跑的就是 `#24`。真正成立的只有下面这句：
> **只要 ADSP 在 audioserver 之前起来，音频栈就完全正常**（s1 那段 160 s）。

### 28.1 三次开机，没有一次是 #24（结论已撤回）

`21_log.img` 里三个 `Linux version`，当时按"环形缓冲回卷后低偏移是最新的"排的序 ——
这个假设是错的，见 29 节。表格本身（每段的 uptime、`pil_boot`、audioserver 退出次数）
是从分区里逐行数出来的，仍然有效：

| 段 | 内核 | 构建机 | 最长 uptime | pil_boot | audioserver 退出 | adsprpcd |
|---|---|---|---|---|---|---|
| s0 | `#23 Mon Nov 16 13:40:03` | `root@8ded1cdd5b47` | 509 s | **无** | **32 次** | 255 |
| s1 | `#23 Mon Nov 16 13:40:03` | `root@8ded1cdd5b47` | 160 s | **有** | **0 次** | 常驻 |
| s2 | `#22 Mon Nov 16 00:15:43` | `root@ad17b0cbe76d` | 639 s | 无 | 30 次 | 255 |

`boot-fix67.img` 里确实是 `#24 … 18:26:20`（解 gzip 验过），设备上跑着的也是 `#24`。
~~所以 boot 分区没写进去~~ —— **这句撤回**：这个分区里根本没有当前这次开机的记录，
"没看到"不等于"没发生"，见 29 节。真正的事实只有一条：这三段里没有 `0003` 的
`adsp-loader:` 行，所以那三段（#22/#23）确实一个都没跑到内核重试。

> 这台机器的 boot/recovery 有 eMMC 卡级写保护（`docs/FLASHING.md`），`dd` 会报成功但
> 数据全丢；`kc_wp.ko` 只在本机 Android 启动后清，所以在 TWRP/电脑侧写完必须回头确认。

### 28.2 s1：唯一一次 ADSP 起来过，音频就全好了

```
#2[ 5.516550] pil-q6v5-lpass fe200000.qcom,lpass: adsp: loading from 0x0dc00000 to 0x0f000000
#2[ 5.938020] pil-q6v5-lpass fe200000.qcom,lpass: adsp: Brought out of reset
#0[ 6.014453] adsp-loader qcom,msm-adsp-loader.41: adsp_loader_do: Q6/ADSP image is loaded
#0[ 6.020727] apr_tal:Q6 Is Up
#1[ 6.062816] init: Starting service 'audioserver'...
#0[ 6.702727] msm8226-asoc-tapan sound.42: msm8226_setup_hs_jack: Failed to request tapan us-euro gpio -22
#0[ 7.407217] APR: Wrong parameters            <- 只有这一条
```

这一整段 160 s 里 audioserver **一次都没退出**（s0 是 32 次），`adsprpcd` 没再 255 退出，
`APR: Wrong parameters` 只有 7.407 那一条——那是声卡初始化时
`msm_routing_get_dolby_dap_param_to_get_control` 在 `port_id` 还没设时的一次查询，不是
致命错误。**这是第一个声音链条完整的开机。**

### 28.3 结论：全部问题就是"约 0.5 s 的窗口"

- 触发（`echo 1 > /sys/kernel/boot_adsp/boot`）到 `Q6 Is Up` 是 **0.504 s**
  （5.516 → 6.020）；
- audioserver 在 **6.06 s** 起来（`class_start main`）；
- 所以触发的死线是 **~5.5 s**。s1 那次 `kcadsp` 在 5.394 s 起，刚好赶上；
- s0（fix67）没有任何人写，ADSP 永远是 DOWN，audioserver 每次起来都在
  `adm_get_params` 上撞 `this_adm.apr == NULL`，退出、重启、再撞，5 s 一轮到日志末尾。

这也解释了 26 节那次"ADSP 8.9 s 才上线"却仍然崩到底：那次的触发是 5.99 s 的
`early-boot`，加载完已经 6.5 s 之后了。**ADSP 晚上线 = 永久坏，不是"慢一点"**：
`q6afe`/`q6adm` 的 APR 句柄在声卡 probe 那一拍注册，拿到 NULL 就一直 NULL。

### 28.4 fix67 那份 dump 为什么一条 `KCADSP` 都没有

脚本把整段报告放在一个后台子 shell 里（`{ ... } &` 然后 `exit 0`）。oneshot 服务退出
时 init 会把整个进程组杀掉，子 shell 还没来得及写第一行就没了。这一版改成**前台顺序
执行、写完再退**，总共十几行，都是同步 `write()`。

### 28.5 fix68 做了什么

1. **`on post-fs-data` 写一次 `boot_adsp`**（4.70 s，`/firmware` 在 4.688 s 挂好）。
   这是最早能工作的钩子，留 1.3 s 余量而不是负的。写入是同步的，init 会在
   `request_firmware()` 里等 ~0.5 s——正好，init 被挡住，audioserver 就起得晚，
   ADSP 就起得早。
2. **`kcadsp.sh` 自己重试**：每 2 s 写一次，最多 10 次；每次把
   `boot #n rc=… state=… up=…` 写进 `/dev/kmsg`，最后再补 `final state`、
   各子系统状态、`dmesg` 里 `adsp-loader|pil-q6v5-lpass|apr_tal|Q6 Is Up` 的最后 12 行、
   声卡、slimbus、audioserver 退出次数。
3. **内核 retry 提前**（`0003`）：第一次 5 s（原来 6 s），间隔 1 s（原来 2 s），
   60 次（原来 20 次）；DT 的 `adsp-state` 不是 DOWN 时打一行说明，免得"驱动以为
   已经加载"被当成成功。内核 `#25`。
4. **脚本每次开机报内核号**：`KCADSP start up=… state=… kernel=#25 expect=#25`。
   下次 dump 第一眼看这一行——如果 `kernel=` 不是 `#25`，说明 boot 又没刷进去，
   后面所有现象都别按 fix68 的前提解释。

### 28.6 刷完先确认这两行（第二行已作废，见 29 节）

```
adb shell cat /proc/version            # 必须是 #25 SMP PREEMPT ... 19:12:22
grep -a "KCADSP start" 21_log.img      # 作废：日志分区不含当前这次开机
```

boot 没写进去的判据只能是 `/proc/version` 和 `/data/local/tmp/kcaudio.txt` 的第一行，
**不能再用日志分区**。如果确实是旧内核，按 `docs/FLASHING.md` 清写保护再写，
**中间不要重启**。清的时候给**名字**，不要给 `pN`：

```bash
echo "autofix boot" > /sys/kernel/kc_wp/run     # boot 是 mmcblk0p9；p11 是 tzbak（见 §6 的订正）
```

本份日志里 kc_wp 解析出来的就是 `.../by-name/boot`，`start_sect=157696`、复查
`0054555555555555`、起始 WP 组 `0 -> 0`——也就是说 Android 这边保护已经是干净的，
问题只可能出在**刷机那一步没有落到 boot 分区**（或者在保护还没清的那一侧写）。
写之前 `cat /proc/version`，写完立刻再 `cat` 一次并要求看到 `#25`，是最省事的判据。

### 28.7 顺手修掉一个一直存在的隐患：脚本清的是 tzbak，不是 boot

§6 早就订正过 `boot = mmcblk0p9`、`mmcblk0p11` 是 1 MiB 的 tzbak，但
`tools/flash/wp_fix.sh`、`tools/flash/wpcheck.sh` 和 `docs/FLASHING.md` 里还留着
`mmcblk0p11`。也就是说：**一旦走这两条脚本清保护，被清掉的是 tzbak，boot 仍然带保护，
随后写进去的内核会被静默丢弃**——症状和这次 dump 一模一样。

`kc_wp.ko` 自己是按 by-name 解析的（日志里就是 `.../by-name/boot`、
`start_sect=157696`），所以问题只在这几个外壳脚本。现在三个地方都改成按名字
（`recovery boot system`），`wpcheck.sh` 的 `$BOOT` 改成 `mmcblk0p9` 并注明原因。

> 以后任何"刷了没生效"的排查，第一件事都是对 partition 名字而不是编号。

## 29. 日志分区到底是什么：一个会丢行的三槽 DBGC 环，不能用来判断"刷没刷进去"

28 节说"三次开机没有一次是 #24，所以 boot 分区没写进去"。**这个结论是错的，撤回。**
错在把"`21_log.img` 里没有"当成了"设备上没发生"，而那份分区连当前这一次开机都没装进去。
下面是把 20 MiB 按结构拆开之后的实情。

### 29.1 结构

```
0000  "v2.0.0\0"  u32=3(记录数)  01 01 01 01
0010  "UNKNOWN"                   <- 复位原因字段
0020  "PWR KEY"
00b0  "MPSS.DI.2.0.1.c9-00059-M8926DAAAANAZM-1.66647.1"
0110  记录1 描述符：len=140720, ...
03d0  记录2 描述符：len=110611
0530  记录3 描述符：len=127461
0800  "DBGC" + len + len + 会话文本      <- 记录1
655c00 "DBGC" ...                        <- 记录2
980600 "DBGC" ...                        <- 记录3
```

三个槽的 `len` 与描述符逐字节对得上，会话文本各自带着自己的
`Linux version 3.4.0 (root@...)`：#23 / #23 / #22。分区里 `#24`、`18:26`
出现 **0 次**，这一点没错；错的是从这里推出去的那一步。

### 29.2 三件事让"物理顺序 = 时间顺序"不成立

1. **槽是整块复用的。** 槽 3（`0x980600` 起）里叠着三次会话的尾巴：256 s、
   606 s、639 s 各一次 `Restarting system`。整个分区有 **6 次重启边界**，却只有
   **3 条 `Linux version`**。所以"偏移小 = 新"、"偏移大 = 新"都不成立。
2. **写入者会丢行。** 整个 20 MiB 只留下 6616 条带时间戳的行，一次 640 s 的开机
   正常会有几万行。`Linux version` 这一行本身也会被丢掉——这就是"没有 #24"
   最可能的解释，而不是"没刷进去"。
3. **中间不是文本。** 记录之间那几 MB 是二进制噪声（可打印率 0.32，zlib/gzip 都
   解不开），不是"被截断的会话"。我之前把它当成会话，是误读。

结论：这个分区**只能用来做旁证**（"某次开机里 APR 长什么样"），不能用来判定
"当前跑的是哪版内核"。要判定，只能问正在跑的系统本身。

### 29.3 `/cache` 也不要再要了

`/cache` 是 480 MB 的 ext4，串口 251 KB/s 意味着整分区要半小时；而上一次那份
"前 21 MB" 连根目录数据块（块 100631 = 412 MB 处）都不包含，`debugfs` 直接拒绝。
以后任何"把 cache 给我"的要求都是错的，改为让设备自己吐一个小文件。

### 29.4 现在的取证通道：一个几十 KB 的文本

`/vendor/bin/kcadsp.sh` 改成把整份报告写进

```
/data/local/tmp/kcaudio.txt      （同时复制一份 /cache/kcaudio.txt）
```

内容包括：`/proc/version`、`/proc/cmdline`、所有 `msm_subsys` 的 name/state、
最多 10 次 `boot_adsp` 写入的 rc、`adsp-loader:` / `pil-` / `apr` / `audio` 的
dmesg 尾部、`/proc/asound/cards`、slimbus、audioserver 启动/退出次数、logcat 里
audio 相关 40 行、`/cache/lc.txt` 尾部 40 行，以及日志分区的头部（`v2.0.0` 与
记录数，用来判断这个环有没有在跟着本次开机走）。

**同一个脚本可以手动跑**，不需要刷机——这一条最重要，因为现在的设备上是 #24，
而 #24 里就有 `0003` 的内核重试，它到底跑没跑、返回码多少，`dmesg` 里就有：

```
adb push kc_audio.sh /data/local/tmp/
adb shell su -c 'sh /data/local/tmp/kc_audio.sh'
adb shell cat /data/local/tmp/kcaudio.txt
```

没有 adb 就把它拷进设备用终端跑，或者直接看 `/data/local/tmp/kcaudio.txt` 前 40 行
（`version:` 那行就是真正在跑的内核）。

### 29.5 判定顺序（以后固定这么走）

1. `version:` 行 —— 设备实际内核，一切结论的前提；
2. `final: state=… asks=…` —— 写了几次、最后 ONLINE 没有；
3. `-- pil --` / `-- apr --` —— 加载到哪一步、`Q6 Is Up` 有没有；
4. `cards:` —— 声卡在不在（`msm8226-tapan-snd-card`）；
5. `audioserver start/exit` —— 次数是否还在涨。

前两项就能把"没触发 / 触发被拒 / 起来了但音频栈没接上"三种情况分开，不用再猜。

### 29.6 两条交付通道，选一条就行

报告现在同时写两个地方，哪条通走哪条：

| 通道 | 取什么 | 大小 / 耗时 |
|---|---|---|
| adb | `adb pull /data/local/tmp/kcaudio.txt` | 约 10–30 KB，秒级 |
| 串口 + DL 模式 | `dd` 读 `by-name/log` 整个分区 | 20 MB，251 KB/s 约 83 s |

第二条之所以可行，是因为报告会**逐行以 `<6>KCADSP KCRPT| ` 写进 `/dev/kmsg`**（前 120 行，
单行截到 190 字符）。这样它落在内核日志里，和 DBGC 槽"保留哪些行"无关——那个环会丢行，
但我们自己的行是在 dump 前刚刚写进去的。3.4 的 ring 是 128 KB，120 行约 20 KB，占 15%，
不会把别的刷掉。

**`/cache` 永远不要再传**：480 MB / 251 KB/s 是半小时，而且前 20 MB 连根目录数据块
（412 MB 处）都不含，`debugfs` 打不开。

判读只看第一段 `=== SUMMARY ===`：

```
version: Linux version 3.4.0 (...) #25 SMP PREEMPT ...   <- 实际在跑的内核
adsp:    state=ONLINE dev=... asks=2                     <- 问了几次、最后什么状态
card:    0 [msm8226-tapan-snd-card] ...                  <- 声卡在不在
audio:   audioserver start/exit = 1 / 0                  <- 还在不在崩
logstore: magic=v2.0.0 records=N                         <- 环有没有在跟着本次开机走
```

`records` 比上一次大，说明环在跟着走；不变就说明这个环根本不记当前开机，那以后只走 adb。

## 30. 声音（四）：链路通了，#25 是第一次 ADSP 早于 audioserver 的开机

fix70 的 dump 同时给了 `kcaudio.txt` 和 `21_log.img`。前者是本次开机，后者又一次证实
"这个分区只装上一场"。

### 30.1 本次开机的时间线（来自 kcaudio.txt，可信）

```
5.234  adsp-loader: userspace requested boot (cmd=1)      <- rc 的 post-fs-data 写入
5.316  pil-q6v5-lpass: adsp: loading from 0x0dc00000      <- 开始搬镜像
5.682  pil-q6v5-lpass: adsp: Brought out of reset
5.737  adsp: Power/Clock ready interrupt received
5.760  apr_tal:Q6 Is Up                                   <- ADSP 上线
5.760  adsp-loader: userspace boot done, rc=0
6.146  asoc: tapan_rx1 <-> msm-dai-q6-dev.16384 mapping ok <- 走 ADSP 的 DAI 起来了
6.173  input: msm8226-tapan-snd-card Headset Jack
6.219  adsp-loader: ADSP came up on attempt 1             <- 内核那一路也跑到了，发现已上线
6.989  init: Starting service 'audioserver'
59 s   audioserver start/exit = 1 / 0
```

ADSP 比 audioserver 早 **1.23 s**，而之前每一次都是晚（或者根本没起）。声卡
`card0 [msm8226tapansnd]` 在，`slimbus: sb-1 tapan-slim-ifd tapan-slim-pgd` 三个设备
都绑上了，`/proc/asound/pcm` 里 MultiMedia1/2、CS-Voice、VoIP、LPA、SLIMBUS_0 全都在。
**音频链路这一层已经不需要再改了。**

三层触发里，真正起作用的是 `on post-fs-data` 那一行（5.234 的 cmd=1）；内核那一路在
6.219 只是确认。所以 0003 的 retry 可以留着当保险，但别指望它救场——它比 audioserver
只早 0.77 s，靠的是 post-fs-data 已经把 ADSP 拉起来了。

### 30.2 日志分区：这次更清楚了，它装的是"上一场"

`21_log.img` 的三个槽：#23 / #23 / **#24**（`root@be411d766fb9`，uptime 到 780 s 才重启）。
本次 #25 的 `KCRPT` 行一条都没有——因为**这个环在会话结束时才落盘**，dump 到的永远是
上一场。所以要它包含本次，必须再重启一次再 dump。

上一份 dump 的第三槽是 #22，这一份变成 #24，两次都落后一场，规律一致。

⚠️ 也正因为会丢行：那场 #24 里 `Q6 Is Up` 计数为 0，但同一场 7.89 s 就有
`tapan-slim tapan-slim-pgd: Looking up qcom,cdc-micbias4-cfilt-sel`，说明 codec/slimbus
是通的，ADSP 大概率也起着，只是那行被丢了。**计数 0 只能说明"没抓到"，不能说明"没发生"**
——这条教训在 29 节写过一次，这里再记一次。

### 30.3 剩下三条报错的性质

| 报错 | 结论 |
|---|---|
| `sound-9302.43: probe failed with error -16` | DT 里有两个 `msm8226-asoc-tapan` 节点（`sound.42` 与 `sound-9302.43`）。第二个抢 `tapan mclk gpio 440` 失败（第一个已占），于是 probe 返回 EBUSY。**card0 是 `sound.42`，正常工作**，这条只影响那个多余的节点，属噪声。 |
| `msm8226_setup_hs_jack: Failed to request tapan us-euro gpio -22` | 老问题：驱动把 `gpio_get_value` 风格的负返回值往 `u32` 里塞，`-22`=`EINVAL` 其实是 DT 没有 `qcom,us-euro-gpios`。影响的是 EU/JP 耳机类型判定那一路，插孔本身（Headset Jack / Button Jack 两个 input）已注册。 |
| `APR: Wrong parameters` @8.461，全场一条 | 声卡初始化时 mixer 在 `port_id` 未设的情况下查 dolby dap 参数，之前每次都有，不致命。 |

### 30.4 还缺的证据：没人放过音

整份 dmesg 在 6.989 之后没有任何 `msm_pcm` / `afe` / `adm` / `asm` 活动，logcat 里也没有
audio 相关行，说明这台设备**还没有真正播过一次声音**。`audioserver 1/0` 只证明 HAL 活得
好，不证明能出声。

所以 kcadsp.sh 又加了一段（不改内核，手动就能跑）：`sec pcm` 会把每个
`/proc/asound/card*/pcm*/sub*/status` 打出来，`-- datapath --` 抓 30 行
`msm_pcm|msm-dai|afe_|adm_|asm_|dapm`，`sec audioflinger` 抓
`dumpsys media.audio_flinger` 里的 output thread。

判据：

* 放音时 `state: RUNNING`、`hw_ptr` 在动 → PCM 层通了；
* 停在 `SETUP`/`PREPARED` 不动 → 卡在 DAI/AFE，看 `-- datapath --` 里最后一条 route；
* `state: RUNNING` 但没声音 → 模拟域（codec 上电、spk/ear 通路、`msm8226_setup_hs_jack`）。

## 31. 没有 root、没有 USB 的时候怎么取证

用户的原话：脚本执行不了（没有 root），机器接到电脑上没有任何反应（没有新设备、没有 adb、
没有 MTP），但 recovery 和 DL 模式能连。这一节回答两件事：USB 到底缺什么，以及在没有
root、没有 adb 的情况下日志怎么出来。

### 31.1 先把"脚本跑不了"这件事摆正

`/vendor/bin/kcadsp.sh` 从来不需要用户执行。它是 init 的 service：

```
service kcadsp /vendor/bin/kcadsp.sh
    class core
    user root
```

init 以 **root** 起它，跟 `su` 没有关系。fix70 那份 dump 里的 `kcaudio.txt` 就是它自己
生成的——取证一直在工作，缺的只是**把文件拿出来**的通道。所以这一版改的不是"怎么执行"，
是"写到哪"。

三个地方同时写：

| 路径 | 谁能读 | 怎么拿 |
|---|---|---|
| `/data/media/0/kcaudio.txt` | 0644，任何 App / 文件管理器 | 内部存储里直接拷，MTP 通了也能拷 |
| `/data/local/tmp/kcaudio.txt` | 0644 | recovery 挂 /data 后 `adb pull` |
| `/dev/kmsg`（`KCRPT` 行） | 内核日志 | dump 20 MB 的 log 分区 |

另外 `/cache/kcaudio.txt` 留一份（recovery 里 `cat /cache/kcaudio.txt` 也行）。

### 31.2 USB 缺的不是驱动，是"没人去设 functions"（**结论作废，见 32**）

> 这一节把"属性值没有对应 stanza"当成原因，fix72 的 dump 证明不是：属性值和
> stanza 都正常跑完了，`functions=mtp`、`vid/pid=0482:0a28` 都对，只有 `enable`
> 一直是 0。真正的原因在 §32，是 `iSerial` 没写、`enable_store(1)` 被内核补丁
> 静默吞掉。下面这张链路表仍然是对的，错的是最后一行的归因。

把这条链路逐段核对过，**每一段都是完整的**：

| 段 | 状态 | 证据 |
|---|---|---|
| gadget 控制器 | 在 | `msm_hsusb`、`ci13xxx_start hw_ep_max = 32`、`android_usb ready` |
| adb function | 在 | `f_adb.c` 被 `android.c` 直接 `#include`，`adb_function_init` 在 vmlinux 里，节点 `/dev/android_adb` |
| mtp function | 在 | `mtp_function_init`、`mtp_function_bind`、`ptp_function_init` 都在 vmlinux 里 |
| adbd | 两种模式都认 | ramdisk 的 `/sbin/adbd` 里同时有 `/dev/android_adb` 和 `/dev/usb-ffs/adb/ep0` 两个字符串 |
| init 的 stanza | 齐 | `init.qcom.rc` 里有 `mtp` / `mtp,adb` / `ptp` / `ptp,adb` / `mass_storage` 五组，VID/PID 是原厂的 0482:0a28 / 0a27 / 0a23 |
| 属性 | **这里断的** | `default.prop` 里 `persist.sys.usb.config=mtp`，而 `/data/property` 里存的是上一次的开机值 |

`init.usb.rc` 里唯一的入口是

```
on boot && property:persist.sys.usb.config=*
    setprop sys.usb.config ${persist.sys.usb.config}
```

也就是：**开机时 `sys.usb.config` 的值完全由 `/data/property/persist.sys.usb.config` 决
定**。它的值只要落在没有 stanza 的那几个上（`none`、`charging`、`rndis`、空），gadget
就会一直被 `on init` 写的那次 `enable 0` 关着——枚举都没有，电脑那边自然"没有任何动静"，
连"未知设备"都不会出现。recovery 能连，是因为 recovery 用的是原厂 recovery 内核 + 自己
的 init，压根不读这个属性。

`21_log.img` 里那一场 #23 是唯一有 USB 记录的开机，它是好的（5.558 `USB_STATE=CONNECTED`
→ 5.662 `high-speed config #1` → 5.720 `CONFIGURED`），说明**硬件、gadget、host 全都
正常**，坏的只是"这一场的属性值"。

所以 fix72 不再依赖属性：脚本在 `sys.boot_completed=1` 之后直接写 sysfs，按
`mtp,adb` → `adb` → `mtp` 顺序试，每次记录

```
  functions=mtp,adb FAILED: <内核给出的原因>
  after 3s: enable=1 state=DISCONNECTED func=mtp,adb vid=0482 pid=0a27 adbdev=yes svc.adbd=running
```

* `functions=... FAILED` → function 注册失败，看内核那句话；
* 三次之后 `state` 还是 `DISCONNECTED`、`adbdev=no` → gadget 没被 host 枚举（线只充电、
  host 口是 hub 上的充电口、或者 VBUS 没检测到）；
* `state=CONFIGURED` 而电脑仍看不到 → host 侧驱动/授权问题，这时 `adbdev=yes` 且
  `svc.adbd=running`，设备上应该弹出"允许 USB 调试"。

`state` 只有 `CONFIGURED` / `CONNECTED` / `DISCONNECTED` 三种，写进报告的 `usb:` 行。

### 31.3 现在能抓住"放音那一刻"

以前报告是开机时拍一张，`pcm` 段永远是 `closed`。现在脚本写完之后**继续采样 30 分钟**，
每 2 秒比对一次：`adsp` 状态、`usb` 状态、`adbd`、audioserver 的 pid、以及每个
`pcm*/sub*/status` 的 `state`。**只在变化时**记一行：

```
<6>KCEVT t=71.42 adsp=ONLINE usb=CONFIGURED adbd=running audio=1832 pcm= card0/pcm0p/sub0=RUNNING
```

同时追加到报告的 `===== events =====` 段。所以正确用法是：

1. 开机，等 2 分钟（USB 的三次尝试和报告都在这之前完成）；
2. 插上 USB，看电脑有没有反应（这本身就验证了 31.2 的三条判据）；
3. **放一段声音**；
4. 重启；
5. 拿文件（三条通道任选）。

重启是因为 `log` 分区只保存**已经结束**的会话；`/data/media/0/kcaudio.txt` 不需要重启，
它每 2 秒就在更新。

### 31.4 不要再做的事

* 不要 `su`、不要 adb shell 里跑脚本——没有 root 也照样有报告，跑脚本反而会因为没有
  root 失败；
* 不要传 `/cache`：480 MB / 251 KB/s；
* 不要指望 log 分区里的"当前场"：它要等这一场结束才落盘，dump 到的永远是上一场。

## 32. USB 真正的原因：`iSerial` 没人写，`enable` 是个空操作

fix72 的 dump 里 USB 那一段是这样的：

```
usb0:    enable=0 state=DISCONNECTED func= vid=0482 pid=0a28
props:   sys.usb.config=mtp sys.usb.state=mtp persist=none configfs=0
nodes:   /dev/android_adb    udc: msm_hsusb
-- bring-up --
  after 3s: enable=0 state=DISCONNECTED func=mtp,adb vid=0482 pid=0a27 adbdev=yes svc.adbd=stopped
  after 3s: enable=0 state=DISCONNECTED func=adb vid=18d1 pid=4ee7 adbdev=yes svc.adbd=stopped
  after 3s: enable=0 state=DISCONNECTED func=mtp vid=0482 pid=0a28 adbdev=yes svc.adbd=stopped
```

`functions` 写进去了，`vid/pid` 跟着变了，`sys.usb.state=mtp` 说明 init 的
`on property:sys.usb.config=mtp` 整段跑完了 —— 而 `enable` 三次都是 0。整场 dump 里
`enable_store` 只有四次输出，全部是 `android_usb: already disabled`，也就是**写 0 的
那几次**；我们写 1 的那三次连一行都没有。

原因在内核源码里，Kyocera 自己加的：

```c
/* drivers/usb/gadget/android.c:2724, enable_store() */
sscanf(buff, "%d", &enabled);
if (enabled && !dev->enabled) {
        ...
if (strcmp(serial_string,"0123456789ABCDEF")) {   /* 串号不是默认值才真开 */
        err = android_enable(dev);
        if (err < 0) { ... }
        dev->enabled = true;
} else {
        android_connect_flag = 1;                 /* 否则只是举个旗子 */
}
```

`serial_string` 在 `android_bind_config()`（3031 行）里被初始化成
`"0123456789ABCDEF"`，之后只有**写 `iSerial` 这一个入口**能改它
（`serial_store()`，2883 行）。写 1 而串号还是默认值时，`enable_store` 返回成功、
不改任何硬件状态：D+ 上拉不打开，host 端连"未知设备"都不会出现 —— 这正是
"接上电脑没有任何动静"。

那么原厂是谁写 `iSerial`？原厂 ramdisk：

```
# /workspace/device_dump/fw/boot.img 的 init.rc:676
service usb_init /system/vendor/bin/usb_init
    class core
    user root
    group system
```

`/vendor/bin/usb_init` 就在我们的 system 镜像里（`strings` 里有
`/sys/class/android_usb/android0/iSerial`、`ro.serialno`、`persist.sys.usb.config`、
`charge_only,adb` 那一套），同目录还有 `init.kyocera.usb.rc`（0482:0a22…0a2b 全套
composition）。**我们的 ramdisk 里两样都没有**：init.rc 换成了 7.1 的（24 个文件里
`grep -r usb_init` 只在 `sbin/adbd` 里命中一个无关字符串），`init.kyocera.usb.rc`
也没带过来。所以 USB 不是"属性值不对"，是从换掉 init.rc 那天起就没工作过；§31.2 的
归因作废，§31.1/31.3/31.4 的取证办法仍然有效。

**fix73 的修法**（只改 system，不用重刷 boot）：`kcadsp.sh` 在
`boot_completed` 之后，先写 `iSerial`，再走四条路：

| 顺序 | 动作 | 说明 |
|---|---|---|
| 0 | `iSerial = KC<eMMC CID 前 14 位>` | 清掉内核补丁的守卫；`ro.serialno` 为空，CID 唯一且跨刷机稳定 |
| 1 | `setprop persist.sys.usb.config mtp,adb` + `setprop sys.usb.config mtp,adb` | 走 init 的 stanza，顺带把框架的覆盖挡住 |
| 2 | 直接写 `functions`/`idVendor`/`idProduct`/`enable`，mtp,adb → adb → mtp | 每次等 3 秒看 `state` |
| 3 | `enable 1` 之后再写一次 `iSerial` | `serial_store()` 里那段 `android_connect_flag` 分支会把刚才跳过的 `android_enable()` 补上 |

判据只有两条：

* `enable=1`（有没有插线都成立，插线前就该是 1）；
* 插上线之后 `state=CONNECTED`/`CONFIGURED`，`dmesg` 里出现
  `msm_hsusb ... CONFIGURED`，电脑上多出 0482:0a27（MTP+ADB）。

报告第一段新增 `serial:` 行（写进去的值和读回来的值），USB 段的 `-- bring-up --`
会打印 `prop path:` 这一步的结果，所以下次 dump 能一眼看出是"串号没写进去"还是
"stanza 没跑"。

## 33. 声音（五）：放了 20 秒，PCM 只开了 3.4 秒，一次都没进 RUNNING

这次的操作是"开机等 2 分钟 → 打开音乐软件放 20 秒 → 暂停"，报告（写于 74.89 s，
之后靠采样追加）里的全部证据就是两行：

```
136.37 | adsp=ONLINE usb=DISCONNECTED adbd=running audio=515 pcm= card0/pcm0p/sub0=OPEN
139.75 | adsp=ONLINE usb=DISCONNECTED adbd=running audio=515 pcm=none
```

ALSA 的状态机是 `closed → open → setup → prepared → running → draining → closed`。
抓到的是 `open`（子流开出来了，参数还没设、更没 start），3.4 秒后回到 `closed`。
**中间没有 `RUNNING`**，也就是说数据从来没有进过 PCM 环形缓冲；再往前一步，
`pcm0p` 对应的就是 `MultiMedia1`，正常放歌时它会长时间停在 `RUNNING`。

同时 `logcat_audio` 段只有 8 行，全是开机那一刻的 `adev_set_parameters:
screen_state` —— 因为 `logcat -d -t 400` 是在 74 s 拍的，放音发生在 136 s，仪器
早就收了。

所以这一轮能确定的只有："输出被打开过，然后关掉了"，**不能**确定是播放器没送数据、
是 codec 起不来、还是 HAL 的 `start` 失败。2 秒采样 + 一次性 logcat 不足以回答，
fix73 换三件仪器：

1. **1 秒采样**（前 10 分钟），状态机每一次跃迁都进 `KCEVT`；
2. **放音瞬间的深照**：进入 busy 的第一秒、以及 busy 期间每次状态变化，各拍一次
   `dumpsys media.audio_flinger`（220 行）+ 忙着的 `hw_params` + 前台 Activity +
   `dumpsys audio` 里的 STREAM_MUSIC 音量与耳机口 `h2w` 状态 + 最近的 audio/media
   logcat。这一段只有流还活着的时候才有意义；一个"PCM 正常但没声"的常见原因就是
   STREAM_MUSIC 被摁到 0，或者插着耳机把混音送去了别处，这两条都得当场看；
3. **连续 logcat 落盘**：新服务 `kclogcat`
   （`-b main,system,crash,radio -v threadtime -f /data/local/tmp/kclogcat.txt -r 4096 -n 2`），
   从 `boot_completed` 一直写到关机，recovery 挂 /data 后 `adb pull` 即可。
   放音时的播放器/AudioFlinger/OMX/NuPlayer 全部在里面。

顺带一个关于日志分区的结论：这次 `21_log.img` 第 3 槽是 #24 那一场（780 s），
60 s 之后有 3147 行，几乎全是 `KCLED beat/key/ino/dbwatch` 和我们自己的
`audit_lost` 限流行 —— 内核环被 LED 调试打印打满了，音频相关的行进不去。
所以声音这条线不要再指望 log 分区，看 `/data/local/tmp` 下的文件。

下一次的操作顺序（和这次一样，只是多拿两个文件）：

1. 刷 fix73 的 system（boot 不用动，`boot-fix72` 与 fix70 逐字节相同，内核 #25）；
2. 开机等 2 分钟，**插上电脑看有没有反应**（这一步同时验证 §32）；
3. 打开音乐软件放 20 秒，暂停；
4. 重启进 recovery，挂 /data，`adb pull /data/local/tmp/kcaudio.txt` 和
   `adb pull /data/local/tmp/kclogcat.txt`。

## 34. 声音（六）：找到了。`libtinyalsa` 和音频 HAL 的 ABI 不是一代东西

fix73 的 dump 先证明 §32 是对的：

```
usb:     enable=1 state=CONFIGURED func=mtp,adb vid=0482 pid=0a27 adbdev=yes svc.adbd=running
serial:  '5bb64bcc' (ro.serialno='5bb64bcc')
```

`iSerial` 一写进去，`prop path` 一步就把 `state` 推到 `CONFIGURED`，电脑上 MTP 和 ADB 同时出现。
USB 这条线结束。

声音这边，这次终于抓到了放音那一刻的 logcat（`kclogcat` 连续落盘生效），而且它不是
"没进 RUNNING"这种间接证据，是 HAL 自己喊出来的：

```
V/audio_hw_primary: enable_audio_route: apply mixer path: deep-buffer-playback
V/audio_hw_primary: start_output_stream: Opening PCM device card_id(0) device_id(0)
E/audio_hw_primary: start_output_stream: cannot set sw params: Invalid argument
V/audio_hw_primary: stop_output_stream: enter: usecase(0: deep-buffer-playback)
```

整份 logcat 里这一组出现 **1445 次**。也就是说 `pcm_open()` 从来没成功过一次，
播放器每试一次就被打回来一次；`pcm=...=OPEN` 那 4 秒就是"文件开出来了、参数没设成、
立刻被关掉"，和 §33 里看到的 `OPEN → closed` 完全对上。**声音链路一层都没问题，
是 HAL 打不开 PCM。**

### 34.1 为什么 `SW_PARAMS` 会 EINVAL

`cannot set sw params` 这句不是 HAL 打的，是 `libtinyalsa` 的 `oops()` 存进
`pcm->error`，HAL 再用 `ALOGE("%s: %s", __func__, pcm_get_error(pcm))` 打出来，
所以 tag 是 `audio_hw_primary`。也就是说失败点就在 `pcm_open()` 里那句：

```c
if (ioctl(pcm->fd, SNDRV_PCM_IOCTL_SW_PARAMS, &sparams))   /* pcm.c:972 */
        oops(pcm, errno, "cannot set sw params");
```

内核侧（`sound/core/pcm_native.c`，3.4）能返回 `-EINVAL` 的只有三条，其中一条是：

```c
if (params->silence_size >= runtime->boundary) { if (params->silence_threshold != 0) return -EINVAL; }
else { if (params->silence_size > params->silence_threshold) return -EINVAL; ... }
```

要触发它，只能是 `silence_size > 0` 而 `silence_threshold == 0`。而 HAL 的
`pcm_config_deep_buffer` 里这两个字段都是 0。于是问题只能出在**字段错位**上。

错位是真的，而且可以逐字节验证。我们的音频 HAL 是**原厂 KitKat 的预编译库**：

```
md5(/vendor/lib/hw/audio.primary.msm8226.so) == md5(原厂 system.img:/lib/hw/audio.primary.msm8226.so)
    4946f586287223153760b4fe5dc57779   （118644 字节，同一个文件）
导出符号 pcm_config_deep_buffer 的 size = 36 字节
数据 = {channels 2, rate 48000, period_size 960, period_count 4, S16_LE,
        start_threshold 240, stop_threshold INT_MAX, silence_threshold 0, avail_min 240}
```

36 字节 = 9 个字段，也就是 KitKat 的 `struct pcm_config`（**没有** `silence_size`）。
而 `/lib/libtinyalsa.so` 是 7.1 编的（26420 字节），它的结构体是 10 个字段、40 字节：

| 偏移 | KitKat（HAL 写的） | 7.1（libtinyalsa 读的） |
|---|---|---|
| 0..16 | channels/rate/period_size/period_count/format | 同 |
| 20/24/28 | start_threshold/stop_threshold/silence_threshold | 同 |
| **32** | **avail_min = 240** | **silence_size = 240** ← |
| **36** | 越界（下一个全局变量的值 20324） | **avail_min = 20324** ← |

反汇编两头都对得上：7.1 的 `pcm_open` 里 `ldr.w r0,[r9,#36]` 取 `avail_min`、
`ldr r0,[r9,#32]` 取 `silence_size`；KitKat 的 `pcm_open` 里取 `avail_min` 用的是 `[r5,#32]`。

于是内核看到的请求是 `silence_size=240, silence_threshold=0` → **EINVAL**，一次都过不去。
即使侥幸过去，`avail_min=20324 > buffer_size=3840` 也会让 `pcm_write` 永远等不到空间。

一句话：**system 里换了 7.1 的 libtinyalsa，而音频 HAL 一直是原厂 KitKat 的预编译库，
两者的 `struct pcm_config` 差一个字段。** 这不是驱动问题，也不是 ADSP 问题；从换掉
system 那天起，这个 ROM 就不可能放出声音。

### 34.2 fix74：把 libtinyalsa 换回原厂那一版

只换一个文件：`/lib/libtinyalsa.so` ← 原厂 `system.img:/lib/libtinyalsa.so`
（13580 字节，md5 `503bb93ba2288146bf94b342f3f59ada`）。理由是这一版就是那批 HAL 的
编译伙伴，字段语义、`xfer_align`、`pcm_prepare` 的有无全都对得上。

替换前先核过依赖，这个 ROM 里只有四个东西碰 `pcm_*`/`mixer_*`，且**全是原厂预编译**：

| 文件 | 需要的 tinyalsa 符号 | 原厂 lib 是否都有 |
|---|---|---|
| `/vendor/lib/hw/audio.primary.msm8226.so` | 21 个（`pcm_open/close/write/read/start/stop/mmap_*/get_htimestamp/...`） | 有（只差 `__aeabi_uidiv`，那是 libc 里的编译器助手） |
| `/vendor/lib/hw/audio.usb.default.so` | `pcm_open/close/get_error/is_ready/mmap_write` | 有 |
| `/vendor/lib/hw/audio_policy.msm8226.so`、`audio.a2dp.default.so` | 不用 pcm | — |
| `/vendor/bin/audio_diag`、`/vendor/lib/libaudioUsbAlert.so` | 也全是原厂 | — |

7.1 那一版多出来的导出（`pcm_prepare`、`pcm_params_*`、`pcm_get_poll_fd`、`pcm_mmap_avail`）
在这个 ROM 里没有任何**非原厂**调用者，所以换掉不会连锁。反过来说，如果哪天真要接
7.1 编的 HAL，就得把它连同 ABI 一起换，不能只换一半。

`kcadsp.sh` 的报告里加了一行金丝雀：

```
tinyalsa: 13580 bytes (matches this HAL, 26420 = 7.1 ABI, breaks every pcm_open)
```

13580 说明这次的库进去了；再看到 26420 就是刷错了镜像。

### 34.3 下一步怎么判

刷 fix74 的 system（boot 照旧不动），开机放 20 秒，然后看 `kcaudio.txt.ev`：

* 出现 `pcm=card0/pcm0p/sub0=RUNNING` → HAL 起来了，接下来只看喇叭有没有声；
* 若 `RUNNING` 但没声，问题就落到 mixer/codec 这一段（`deep-buffer-playback` 的
  `SLIM_0_RX`、`RX1/2/3 MIX`、`SPK` 增益），那时候再抓 `dumpsys media.audio_flinger`
  里的 thread 和 `AudioMixer` 就够了 —— 报告里已经在放音瞬间拍了一份。

## 35. 声音（七）：fix74 实测出声，链路全通

刷 fix74 后，同样的操作（开机等 2 分钟 → 放 20 秒），`kcaudio.txt.ev` 里出现了
三段时间不短的 `RUNNING`：

```
 84.07 | adsp=ONLINE usb=CONFIGURED adbd=running audio=510 pcm=card0/pcm0p/sub0=RUNNING
 89.35 | ... pcm=none
123.97 | ... pcm=card0/pcm0p/sub0=RUNNING
151.15 | ... pcm=none
160.80 | ... pcm=card0/pcm0p/sub0=RUNNING
167.01 | ... pcm=none
```

放音瞬间拍到的 `hw_params` 就是 §34 推算的那组参数，一个不差：

```
access: RW_INTERLEAVED   format: S16_LE   channels: 2
rate: 48000 (48000/1)    period_size: 960   buffer_size: 3840
```

也就是 KitKat HAL 的 `pcm_config_deep_buffer`（960×4）终于被内核接受了 —— 7.1 那个库
读出来的 `silence_size=240` 已经不存在。其他可以对照的：

* `grep -c 'cannot set sw params'` = **0**（fix73 那一轮是 1445）；
* `start_output_stream: exit` 正常返回，`out_standby` 正常收尾；
* `Normal mixer raw underrun counters: partial=0 empty=0` —— 一次欠载都没有，
  说明送数节奏是健康的，不是"能开但喂不上"；
* 音源设备 `devices(0x2)` = speaker，前台是 `com.cyanogenmod.eleven`。

§33/§34 那条链到此闭合：ADSP 起来（§30）→ HAL 能开 PCM（§34）→ 出声（本节）。

### 35.1 报告里那行金丝雀写错了路径

fix75 起改成先试 `/system/lib/libtinyalsa.so` 再试 `/lib/libtinyalsa.so`：

```
/vendor/bin/kcadsp.sh[279]: can't open /lib/libtinyalsa.so: No such file or directory
tinyalsa:  bytes (13580 = ...)
```

设备上 system 挂在 `/system`，脚本里少了这个前缀。只是报告文本，不影响任何行为。

### 35.2 顺带解释：这次 `usb:` 行是 `func=adb` 而不是 `mtp,adb`

不是回退。logcat 里两次设置都在：

```
09:04:26.479  UsbDeviceManager: Setting USB config to adb
09:05:03.899  UsbDeviceManager: Setting USB config to mtp,adb
```

报告写在 63.9 s（约 09:04:5x），正好落在两句之间，框架还没把 MTP 加回去；
`kcadsp.sh` 看到 `state=CONFIGURED` 就"leaving it alone"，不再插手。
再过半分钟 `sys.usb.config` 自己会变成 `mtp,adb`。两条路（我们写 / 框架写）都通，
先到先得，不冲突。

## 36. 三件"小问题"的账，和按键背光的真正来历

### 36.1 `audio.r_submix` 加载失败：又是跨代 ABI，这次方向反过来

```
E HAL: load: module=/vendor/lib/hw/audio.r_submix.default.so
E HAL: dlopen failed: cannot locate symbol "_ZN7android8MonoPipeC1Ejjb"
       referenced by "/system/vendor/lib/hw/audio.r_submix.default.so"
E AudioFlinger: couldn't load audio hw module audio.r_submix (Invalid argument)
E AudioFlinger: loadHwModule() error -22 loading module r_submix
W APM_AudioPolicyManager: could not open HW module r_submix
```

`_ZN7android8MonoPipeC1Ejjb` 是 `android::MonoPipe::MonoPipe(unsigned int, unsigned int, bool)`
——**KitKat 的构造函数**。我们镜像里：

| 文件 | 大小 | md5 | 结论 |
|---|---|---|---|
| `/vendor/lib/hw/audio.r_submix.default.so` | 17708 | `cfd4caaa…` | 与原厂逐字节相同，**KitKat** |
| `/lib/libnbaio.so` | 38488 | `f181a1e5…` | **7.1**（原厂是 25708 / `95c66023…`） |

7.1 的 libnbaio 只导出 `_ZN7android8MonoPipeC1EjRKNS_12NBAIO_FormatEb`
（`MonoPipe(size_t, const NBAIO_Format&, bool)`），成员布局也换成了 `NBAIO_Format`，
所以不是"缺一个符号"这么简单——KitKat 的 HAL 与 7.1 的 `MonoPipe` 不是同一个类。

与 §34 那次（KitKat HAL + 7.1 libtinyalsa）是同一类错误，只是那次坏在**声音主通路**，
这次坏在**只在投屏/内录时才用得到的旁路**。libnbaio 不能换回原厂：7.1 的
`libaudioflinger.so` 依赖 7.1 的 `MonoPipe`/`MonoPipeReader` ABI，换了 AudioFlinger 直接崩。
要保留 r_submix 就得有一个 7.1 编的 r_submix HAL（AOSP 里它是
`hardware/libhardware/modules/audio_remote_submix/audio_hw.cpp`，纯软件、与高通无关），
这需要一整套 bionic/libc++ 头，收益是"录屏内录和 Wi-Fi Display 能出声"——这台机器两样都没有。

fix75 的处理：**把模块声明从 `/etc/audio_policy.conf` 里删掉**，`global_configuration`
的 `attached_input_devices` 里也去掉 `AUDIO_DEVICE_IN_REMOTE_SUBMIX`。没有声明就不会有
加载尝试，四行报错消失。HAL 文件仍留在镜像里（`/vendor/lib/hw/audio.r_submix.default.so`），
将来真要用，换的是那个文件，不是这行配置。

### 36.2 `adsprpcd` 退 255：先给它一副眼睛，再谈原因

`/system/bin/adsprpcd` 是软链，指向原厂 `/vendor/bin/adsprpcd`；服务由 7.1 ramdisk 的
`init.qcom.rc:271` 定义。dump 里每次开机都是同一副样子：

```
6.060  init: Service adsprpcd does not have a SELinux domain defined.
6.061  init: Starting service 'adsprpcd'...
6.438  init: Service 'adsprpcd' (pid 550) exited with status 255
11.07  init: Service adsprpcd does not have a SELinux domain defined.
11.07  init: Starting service 'adsprpcd'...
```

起来、0.4 秒后退 255、5 秒后再试一次、然后彻底放弃。255 是 `exit(-1)`，也就是
daemon 自己的 `main()` 走到了失败分支，不是被信号打死，也不是 SELinux 拒（当前是
permissive，所有 `avc: denied` 都带 `permissive=1`）。

两个候选，目前的数据分不开：

* `/dev/adsprpc-smd` 不存在。内核 `CONFIG_DEVTMPFS=n`，misc 设备注册时不会自己
  建节点，得靠 ueventd 按 `ueventd.qcom.rc:91` 的 `dev` 段补上；如果注册发生在
  ueventd coldboot 之后、或者驱动根本没 probe，节点就是空的。
* daemon 内部失败（比如它要的 `libadsprpc.so` 里某个 ioctl 返回错误）。

所以 fix75 在报告摘要里加了一行，把这两者分开：

```
adsprpc: svc=stopped nodes=/dev/adsprpc-smd last=[Service 'adsprpcd' (pid 550) exited with status 255]
```

`nodes=` 为空 → 是节点问题，补 ueventd 规则；`nodes=` 有值但照样 255 → 是 daemon 内部，
再往下就得给它 `strace`（`/vendor/bin/adsprpcd` 是原厂 KitKat 二进制，跑在这个 7.1 的
`libc` 上，本身也可能是跨代问题，跟 §34/36.1 同一族）。

### 36.3 `does not have a SELinux domain defined`：不是 kchalt 一个，是二十五个

抓一份完整的开机日志，这条 ERROR 的服务名单是：

```
adsprpcd bootanim exec2/13(kcbt.sh) exec3(kcfuse.sh) exec4(kcboot) irsc_util
kcadsp kcbtnled kcdiag kchalt kcshut kcssr kcstate kctail kcwifi
mpdecision netmgrd qcamerasvr qmuxd qseecomd rfs_access rmt_storage
time_daemon uimd
```

连 7.1 ramdisk 自带的 `bootanim`、`mpdecision`、`netmgrd`、`qmuxd` 都在里面。原因不是
某个 rc 写漏了 `seclabel`，而是 **ramdisk 里的 `sepolicy` 是 7.1 AOSP 的，里面没有这些
原厂服务的域**（它们来自 KitKat 的 `init.qcom.rc`）。init 在 `seclabel` 为空时打一行
ERROR，然后用**继承来的 init 域**执行——所以这些服务其实都在跑，`bootanim` 能画、
`qmuxd` 能起、`kchalt` 能重启，全是照常的。当前 SELinux 是 permissive，没有实际后果，
只有日志噪音。

fix75 给 10 个自己的服务补了显式域，值和当前实际行为完全一致：

```
service kcadsp /vendor/bin/kcadsp.sh
    seclabel u:r:init:s0
    ...
```

涉及 `kcadsp kcbtnled kcdiag kcdiag2 kchalt kcshut kcssr kcstate kctail kcwifi`。
剩下那十几个在 ramdisk 的 rc 里，要改得重打 boot 镜像，留到改 DT（§36.4）那一轮一起做——
它们的噪音不影响任何功能，不值得单独刷一次机。

### 36.4 按键背光闪两下：GPIO 34 同时是"按键灯"和"相机对焦电源"

这是本轮唯一真正的发现。原厂 DT 和我们的 DT 在这一处**根本不是同一个硬件接法**：

原厂 `boot.img` 的 DTB（`/tmp/d6.dts`，5284 行）：

```
qcom,leds@a100 {
    compatible = "qcom,leds-qpnp";
    label = "mpp";
    status = "okay";
    qcom,led_mpp_2 {
        linux,name = "button-backlight";
        qcom,default-state = "off";
        qcom,max-current = <0x28>;
        qcom,current-setting = <0x05>;
        qcom,id = <0x06>;
        qcom,mode = "manual";
        ...
```

也就是说：**按键背光是 PMIC 的 MPP2**，默认关。

我们的 `msm8926-qrd-skug.dtsi`（78–83 行）却是：

```
gpio-leds {
    keypad-backlight {
        gpios = <&msmgpio 34 0>;
        label = "button-backlight";
        linux,default-trigger = "none";
    };
};
```

同时又在 `&spmi_bus` 里把原厂那个 `qcom,leds@a100` 写成了 `status = "disable"`。
**这是从 qrd 参考设计搬过来的 gpio-leds 节点，把这台机器的按键灯改到了 GPIO 34 上。**

而 GPIO 34 在 `msm8226-camera-sensor-qrd.dtsi:281` 里属于 ov12830：

```
gpios = <&msmgpio 26 0>, <&msmgpio 37 0>, <&msmgpio 36 0>,
        <&msmgpio 22 0>, <&msmgpio 34 0>;
qcom,gpio-reset   = <1>;
qcom,gpio-standby = <2>;
qcom,gpio-vdig    = <3>;
qcom,gpio-af-pwdm = <4>;          /* ← 第 5 个，就是 GPIO 34 */
qcom,gpio-req-tbl-label = "CAMIF_MCLK", "CAM_RESET1", "CAM_STANDBY",
                          "CAM_VDIG", "CAM_AF_PWDM";
```

相机每次给 sensor 上电/下电，`CAM_AF_PWDM` 就把 34 拉高/拉低一次，按键灯跟着亮/灭。
**两个 sensor，两次，就是"闪两下"**，时间点在 `qcamerasvr` 启动（6.06–6.16 s）之后、
开机动画首帧前后——和观察完全对得上。

原厂不会有这个现象：它的按键灯在 PMIC 上，GPIO 34 只归相机。

根治有两条路，都要动 boot 镜像（DT 在 boot 里）：

| 方案 | 改动 | 代价 |
|---|---|---|
| 恢复原厂接法 | 删 `gpio-leds` 节点，`qcom,leds@a100` 改回 `okay` | 要验证 MPP2 在本机确实接灯；按键灯从此走 PMIC（原厂行为） |
| 保住 GPIO 34 | 删掉 `camera@6c` 里的 `CAM_AF_PWDM` 那一项并同步 `req-tbl` | 相机对焦永远没有电（相机本来完全不能用） |

两条都要重打 boot（QCDT 1,290,240 字节，含多个 DTB，顺序和 id 不能错），所以 fix75 先不做。

fix75 做的是**压制 + 取证**：新服务 `kcledguard`（`class core`，比 `qcamerasvr` 早）在
开机前 120 秒里每 100 ms 读一次 `brightness`，不是 0 就写回 0，并把每一笔改动连同时间、
`qcamerasvr`/`mm-qcamera-daemon` 的 pid 一起写进 `KLEDGUARD`：

```
KLEDGUARD start uptime 6.4 v=0
KLEDGUARD caught v=1 at 6.9 cam=1234 mm=
KLEDGUARD caught v=1 at 7.3 cam=1234 mm=
KLEDGUARD done uptime 126.4 corrected=2 v=0
```

flash 不闪了；如果日志里出现 `caught`，36.4 这段就得到证实，下一轮直接按"方案一"改 DT；
如果一行都没有，说明闪的不是这个节点，那就再查（比如 LK 阶段遗留电平或 `wled`）。
代价：开机两分钟内按触摸键不会点亮按键灯，两分钟后服务退出，`kcbtnled` 照旧接管。

## 37. fix75 验收：r_submix 干净了，adsprpcd 自己好了，麦克风查到了断点

### 37.1 已解决的两件

**r_submix**：整份 logcat 里 `r_submix` 出现 **0 次**（fix74 是每次开机四行
`couldn't load audio hw module` / `error -22`）。删声明这条路是对的。

**adsprpcd**：这一轮它是**活的**，报告里写着：

```
adsprpc: svc=running nodes=/dev/adsprpc-smd  last=[]
```

它照样打 `apps_std fopen failed: ./oemconfig.so`、`rfsa/adsp/voiceproc_tx.so`
之类的 E 行（那是 ADSP 侧没有 factory 测试库，不是失败），但进程一直在跑。
所以"退 255"这条暂时不用再抓日志了；等哪天又挂，`last=[...]` 会第一时间说出来。

### 37.2 §36.4 撤回：DT 是原厂的，根本没有 gpio-leds

把 boot 镜像里的 QCDT 拆开看（8 个 DTB，board-id `08 00` 与 `08 02` 两族），
**每一个** 都是 `qcom,leds@a100 { status = "okay" }`，按键背光是 PMIC MPP2
（`qcom,led_mpp_2`, `linux,name="button-backlight"`, `default-state="off"`），
`grep gpio-leds` 全部为 0 命中。

也就是说 boot 里的 DT 一直是原厂那份（我们换的是 zImage，DTB 原样保留），
`msm8926-qrd-skug.dtsi` 里那个 GPIO 34 的 gpio-leds 节点**从未进过这台机器**。
§36.4 把源码树里的一套 DT 当成了设备上的 DT，结论作废。

所以"闪两下"是**软件写 brightness**，这个 ROM 里只有两个写者：`kcbtnled`
（启动时 level=255、timeout=5000，即开机点灯 5 秒）和框架的 lights HAL
（下一节说，它是坏的）。至于是不是它俩，fix76 让 `kcledguard` 用 20 ms 的
时间分辨率把每一次跳变记下来，下一份 dump 直接看时间点。

### 37.3 麦克风：不是录音参数，是 APM 开机时连输入流都打不开

`kclogcat` 里第一次录音尝试（09:42:00，44100/mono/PCM16）：

```
E AudioRecord: Could not get audio input for session 33, record source 1 ...
E AudioRecord-JNI: Error creating AudioRecord instance: initialization check failed with status -22.
E APM::AudioPolicyEngine: getDeviceForInputSource() no default device defined
W APM_AudioPolicyManager: getInputForAttr() could not find device for source 1
```

但真正的原因在开机第 3 秒就写下来了：

```
V audio_hw_primary: adev_open_input_stream: enter
W APM_AudioPolicyManager: Cannot open input stream for device 80000004 on hw module primary
W APM_AudioPolicyManager: Input device 80000004 unreachable     (BUILTIN_MIC)
W APM_AudioPolicyManager: Input device 80000080 unreachable     (BACK_MIC)
W APM_AudioPolicyManager: Input device 80000040 unreachable     (VOICE_CALL)
```

7.1 的 APM 在 `initialize()` 里对**每个输入 profile 打开一次输入流**，成功才把
该设备标记为 attached（`AudioPolicyManager.cpp`，`openInput(... AUDIO_SOURCE_MIC ...)`
那一段）；失败就打 `Cannot open input stream`，随后 `Input device ... unreachable`
把它从表里删掉。于是 Engine 没有任何输入设备，任何 `AudioRecord` 都拿不到 device，
回归 -22。也就是说：**不是录音参数不对，是这台机器的输入通路在 APM 眼里根本不存在。**

HAL 只打了 `enter`，没有 `exit`、没有 `ALOGE`。对照 KitKat 的 QCOM HAL 源码，这正是
`check_input_parameters()` 的分支：

```c
ALOGV("%s: enter", __func__);
*stream_in = NULL;
if (check_input_parameters(config->sample_rate, config->format, channel_count) != 0)
        return -EINVAL;                      /* 静默返回，什么也不打 */
```

它只接受 `PCM_16_BIT`、1/2/6 声道、8k/11.025k/12k/16k/22.05k/24k/32k/44.1k/48k。
APM 传进去的是 profile 的"默认配置"，而 `/etc/audio_policy.conf` 的输入段是原厂的
原文（`channel_masks ...MONO|STEREO|FRONT_BACK|5POINT1`，`formats` 里还有
AMR/QCELP/EVRC 一串）。4.4 的 APM 取默认配置的方式和 7.1 不同，7.1 取到的
组合落在这三类之外，HAL 就静默 EINVAL 了。

下一份 dump 里 fix76 新增了 `===== mic =====` 段：`dumpsys media.audio_policy`
里与 input 相关的行、以及 logcat 里所有 `AudioRecord/open_input/getInputForAttr`，
那时就能看到 APM 究竟把哪一组参数递给了 HAL。**在此之前不动 `audio_policy.conf`**：
它是原厂原文，4.4 上能用，盲改只会把已经能用的输出也带歪。

### 37.4 光线/距离传感器：内核侧是全好的，断在 HAL 与框架之间

内核日志（`21_log.img`，每一场开机都一样）：

```
1.315 [ALS_PS]sfh7776_probe regulator min_uV = 2800000 ...
1.324 input: light as /devices/virtual/input/input6
1.325 input: proximity as /devices/virtual/input/input7
6.101 KCBOOT misc=[... psals_sensor ...]
```

驱动 probe 成功、两个 input 设备注册成功、sysfs 属性组建在
`/sys/class/input/input6|7/`（`enable_als_sensor`、`als_poll_delay`、`als_ratio`、
`enable_ps_sensor`、`ps_crosstalk`）。所以 DT、i2c、供电、中断都没问题。

问题在 userspace：`/vendor/lib/hw/sensors.default.so` 是**原厂 KitKat 的预编译**
（38192 字节，与原厂 system.img 逐字节相同）。而 7.1 的 `SensorService` 按
**68 字节**一步走 `sensor_t` 数组，KitKat 的 `sensor_t` 只有 **36 字节**
（`name/vendor/version/handle/type/maxRange/resolution/power/minDelay` 九项）。
5.0 起加进来的 `fifoReservedEventCount/fifoMaxEventCount/stringType/
requiredPermission/maxDelay/flags/reserved[2]` 在原厂那份里不存在。

这和 §34（KitKat HAL + 7.1 libtinyalsa）、§36.1（KitKat HAL + 7.1 libnbaio）是
同一族错误，只是这次坏在传感器。另一个旁证：`SensorService` 的构造函数从
18.21 s 卡到 41.20 s（23 秒），才吐出 "thread starting"。

修法只有两条：写一个 7.1 的 sensors HAL（把这台机器的 input 事件翻译成
`sensor_t`/`sensors_event_t`），或者写一个 shim 去 dlopen 原厂那支、把 36 字节
的结构体按 68 字节重新排布后转发。两条都要先确认一件事：`dumpsys sensorservice`
现在到底列出了几个传感器、名字是不是乱码。fix76 的报告里加了 `===== sensors =====`
段（HAL 字节数、input6/7 的名字与属性、`dumpsys sensorservice` 前 30 行），
下一份 dump 就能定案，然后按定案写 HAL。

### 37.5 顺带发现：`lights.default.so` 自己就没加载成功

```
E HAL: load: module=/vendor/lib/hw/lights.default.so
E HAL: dlopen failed: cannot locate symbol "write" referenced by "/system/vendor/lib/hw/lights.default.so"
```

这支 6356 字节的模块是"KYL23 sysfs lights"（早期手写的那支），`readelf -d` 显示
它**没有 DT_NEEDED**：`write/open/close/strcmp` 全是未定义，却没有任何依赖库声明，
所以 bionic 找不到 `write`。后果是 `LightsService` 起不来 —— 屏幕亮度调节、
通知灯都归它管。于是"自动亮度不工作"其实是两个独立故障叠在一起：光线传感器没数据
（37.4），亮度这条路本身也断着。修它要重编这支 .so（链接时补上 libc.so），
和 37.4 的 HAL 一起做。

### 37.6 SELinux 域告警：我们自己的 10 个已消，剩下 15 个在 ramdisk

fix75 给 `kcadsp kcbtnled kcdiag kcdiag2 kchalt kcshut kcssr kcstate kctail kcwifi`
补了 `seclabel u:r:init:s0`，这十个不再报。剩下的 `adsprpcd bootanim irsc_util
mpdecision netmgrd qcamerasvr qmuxd qseecomd rfs_access rmt_storage time_daemon uimd`
定义在 **ramdisk 的 init.qcom.rc / init.rc** 里，改它们要重打 boot 镜像
（QCDT + ramdisk，1.4 MB cpio.gz）。当前是 permissive，init 用继承域照样把它们跑起来，
所以只是日志噪音。这一轮不动 boot：为了几行日志去冒一次刷 boot 的风险不划算，
等 37.4/37.5 那批 userspace 的活干完，若还需要动 boot（比如换 DT），一起做。

### 37.7 fix76 改了什么

* `kcledguard` 由 `class core` 改成 `post-fs-data` 里显式 `start`（class core 在
  4.3 s 之后，闪已经过去了），前 45 s 每 20 ms 采一次，之后 200 ms 到四分钟，
  **每一次跳变**记一行到 `/data/local/tmp/kc_led.log` + `/cache/kc_led.log` +
  `KLEDGUARD`（kmsg），并把非 0 写回 0；
* `kcadsp` 报告新增三段：`sensors`（HAL 字节数、input6/7 名字与属性、
  `dumpsys sensorservice` 前 30 行）、`mic`（`dumpsys media.audio_policy` 的
  input 行、logcat 里的录音尝试、capture 节点）、`led`（`/sys/class/leds` 全表、
  按键与屏幕亮度、guard 日志）；
* 上一轮那行金丝雀的路径已修（`/system/lib/libtinyalsa.so` 优先），这份 dump 里
  已经打出 `tinyalsa: 13580 bytes`。

## 38. fix76 验收，以及把跨代的那一层库换成自己写的

### 38.1 声音是真的通了，USB 也稳

fix76 的 `kcaudio.txt.ev` 只有七行，但七行全是要的：

```
105.18 | adsp=ONLINE usb=CONFIGURED adbd=running audio=524 pcm=card0/pcm0p/sub0=RUNNING
114.40 | ... pcm=none
131.13 | ... pcm=card0/pcm0p/sub0=SETUP
135.19 | ... pcm=none
142.00 | ... pcm=card0/pcm0p/sub0=RUNNING
151.58 | ... pcm=none
192.34 | ... pcm=card0/pcm0p/sub0=RUNNING
```

三段独立播放，每段都进了 `RUNNING`，两次自然收尾回 `none`（用户暂停），第三段还在放。
`hw_params` = 48000/S16_LE/2ch/period 960/buffer 3840，`cannot set sw params`
在整个 dump 里 0 次 —— §34 那个 36/40 字节 `pcm_config` 的账结清了。

USB 这一段也干净：`serial: '5bb64bcc' (ro.serialno='5bb64bcc')`、`usb: enable=1
state=CONFIGURED func=adb`、`svc.adbd=running`，脚本走的是"already CONFIGURED,
leaving it alone"分支，一次都没重配。

### 38.2 撤回 §37.4：KitKat 的 `sensor_t` 也是 68 字节

§37.4 说 KitKat 的 `struct sensor_t` 是 36 字节、7.1 按 68 字节步进会读错，并拿
"列表里有 8 个传感器"当反证。这个推断是错的，dump 直接推翻了它：

```
HAL: Yamaha Sensors module (Yamaha Corporation), version 0000000000
Total 8 h/w sensors, 8 running:
0x00000001) BMA250/250E Acceleration Sensor | Bosch Sensortec | ...
0x00000002) MS-3R (YAS532) Magnetic Sensor | Yamaha Corporation | ...
0x00000005) SFH7776 Light Sensor | OSRAM Opt Semiconductors | ...
0x00000008) SFH7776 Proximity Sensor | OSRAM Opt Semiconductors | ...
```

八个名字、厂商、handle、type 全对。原因很简单，是我数漏了字段：

```c
/* hardware/libhardware/include/hardware/sensors.h, KitKat */
struct sensor_t {
    const char* name;      /* +0  */
    ...
    int32_t minDelay;      /* +32 */
    void* reserved[8];     /* +36 .. +68 */
};
```

`sizeof(sensor_t)` 在 4.4 就是 **68**，7.1 只是把 `reserved[8]` 换成了具名字段，
大小没变。所以传感器 HAL 的 ABI 是对的，`sensors.default.so`（38192 字节，与原厂
逐字节相同）可以留着，不需要重写。

那问题就剩下 dump 里的另外两行：

```
Recent Sensor events:                                        <- 一直是空
Active sensors: SFH7776 Proximity Sensor (connections=1)
```

SensorService 认为距离传感器有一个连接，但一个事件都没收到，而 sysfs 里
`enable_als_sensor=0`、`enable_ps_sensor=0` —— 框架要了，HAL 没写下去，或者写了
没生效。这次不再猜：`kcadsp` 在抓报告时**自己写一次 enable 节点**，读 2 秒
`/dev/input/eventN`，再写回 0（见 38.7）。事件出来 = 驱动和器件都好，问题在 HAL 以上；
不出来 = 在 HAL 以下，换 HAL 也没用。

另外记一笔：`nuSensorService starting...` 到 `nuSensorService thread starting...`
用了 22.9 秒（10:29:33.494 → 10:29:56.363），期间 system_server 一直在
`Waiting for service sensorservice`。这是开机慢的一大块，等传感器的事定位了一起看。

### 38.3 麦克风：7.1 的 APM 在开机时就把三个输入设备判死了

fix76 的 logcat 只有四行相关，但这四行已经把因果写全了：

```
V audio_hw_primary: adev_open_input_stream: enter      <- 两次，同一毫秒
V audio_hw_primary: adev_open_input_stream: enter
W APM_AudioPolicyManager: Cannot open input stream for device 80000004 on hw module primary
W APM_AudioPolicyManager: Input device 80000004 unreachable
W APM_AudioPolicyManager: Input device 80000080 unreachable
W APM_AudioPolicyManager: Input device 80000040 unreachable
```

`80000004` BUILTIN_MIC、`80000080` BACK_MIC、`80000040` VOICE_CALL，正好是
`attached_input_devices` 里那三个。7.1 的 `AudioPolicyManager` 在 `initialize()`
阶段会为**每个 always-present 输入设备**建一个 input descriptor 并调
`openInput()`，失败就把它从可用集合里永久删掉 —— 所以开机 0.5 秒内，
这一整台手机的输入设备就全没了，之后任何 `AudioRecord` 都是 `-22`，与 App 无关。

HAL 侧是静默拒绝：`check_input_parameters()` 只接受 PCM16、1~2 声道、标准采样率，
不满足就 `return -EINVAL`，一行日志都不打。而 `audio_policy.conf` 的 input profile
当时是原厂原文：

```
sampling_rates 8000|11025|12000|16000|22050|24000|32000|44100|48000
channel_masks AUDIO_CHANNEL_IN_MONO|AUDIO_CHANNEL_IN_STEREO|AUDIO_CHANNEL_IN_FRONT_BACK|AUDIO_CHANNEL_IN_5POINT1
formats AUDIO_FORMAT_PCM_16_BIT|AMR_NB|AMR_WB|QCELP|EVRC|EVRCB|EVRCNW
```

7.1 的 APM 不是"挑一个 HAL 能接受的"，它按 profile 组 config。压缩格式和
5.1/front-back 这两组对一个 capture stream 本来就没意义（它们是给 voice_call
用的），留着只会让 APM 组出一个 HAL 不收的 config。fix77 把这一段收窄到
`PCM_16_BIT` + `MONO|STEREO` + 六个标准率，设备列表保留 BUILTIN_MIC / BACK_MIC /
VOICE_CALL / WIRED_HEADSET / BT_SCO。

这一条是**有依据的修正**，但还没被实测证实。所以 `kcadsp` 的 mic 段改成把
`dumpsys media.audio_policy` **整段前 110 行**打出来（7.1 会把解析后的
AudioPolicyConfig 序列化成 XML，input profile 在那里是可见的），而不是像 fix76
那样 grep "input" —— 那样只能捞到三行标题。

### 38.4 把 libtinyalsa 换成自己写的一份（这是这一轮的主菜）

问题回到 §34：这台机器上 `libtinyalsa.so` 只有两个选择，选哪个都要另一边死。

| | 字节 | `pcm_config` | 谁受不了 |
|---|---|---|---|
| KitKat 版 | 13580 | 36 字节，末字段 `avail_min` | 7.1 的 usb / r_submix HAL |
| 7.1 版 | 26420 | 40 字节，`silence_size` + `avail_min` | 厂商 audio HAL（每个 `pcm_open` 都 EINVAL） |

前八個字段两边完全一样，只有 offset 32 的含义变了。而 `silence_threshold` /
`silence_size` 这两个字段**只影响 underrun 时补零**，Android 的 HAL 一个都不用；
偏偏内核 `sound/core/pcm_native.c:541` 就是拿它们互相比较：

```c
if (params->silence_size >= runtime->boundary) {
        if (params->silence_threshold != 0) return -EINVAL;
} else {
        if (params->silence_size > params->silence_threshold) return -EINVAL;
        ...
}
```

7.1 的库把 offset 32 当 `silence_size` 读，在 36 字节结构里那个位置是
`avail_min`（deep-buffer 是 240），而 `silence_threshold`（offset 28）是 0，
于是 `240 > 0`，EINVAL。fix74 之前那 1445 次 `cannot set sw params` 就是这么来的。

所以 fix77 的 `prebuilt/kc/src/tinyalsa7.c` 是一份**从零写的、7.1 符号集完整**的
实现：

* 导出符号与 7.1 原版逐一对齐（57 个函数，7.1 那份 62 个里差的 5 个是 libgcc 的
  `__aeabi_*` 除法辅助，bionic 自带）；
* `pcm_config` **按字段读，永远不碰第 36 字节**：offset 0..31 两边一致，offset 32
  在合理范围（>0 且 <= period_size*period_count）时当 `avail_min` 用，否则退回
  `period_size`；
* `silence_threshold` / `silence_size` **写死 0**，不下发内核 —— 这一对就是唯一
  会随 ABI 变含义的字段，关掉它，36 和 40 字节就都一样了；
* `pcm_open` 失败返回 **NULL**（不是半成品对象）：两个时代的 `pcm_is_ready()` 都
  只是 `pcm != NULL`，KitKat HAL 那份还是头文件里的 inline，返回非 NULL 会被当成
  成功，下一次 `pcm_write` 就写进一个 `fd = -1` 的句柄；
* `hw_params` 流程照抄 7.1 原版（直接 `SNDRV_PCM_IOCTL_HW_PARAMS`，不预先
  `HW_REFINE`），因为这条路径是 fix74 实测通过的，不引入新变量。

编译方式也是这一轮的一部分，写在 `prebuilt/kc/src/build.sh` 里。关键点是
`-nostdlib` + `-l:libc.so`：

```
$ arm-linux-gnueabi-gcc -shared -fPIC -O2 -fno-stack-protector -nostdlib \
      -I$KERNEL/include -I$KERNEL/arch/arm/include \
      -o libtinyalsa.so tinyalsa7.c \
      -Wl,-soname,libtinyalsa.so -L stub -l:libc.so -lgcc
$ readelf -d libtinyalsa.so | grep NEEDED
 0x00000001 (NEEDED)  Shared library: [libc.so]
```

如果按常规方式链 glibc，出来的 `.so` 会带 `DT_NEEDED libc.so.6` 和
`open64` / `mmap64` / `__ioctl_time64` 三个 bionic 根本没有的符号，加载即
`cannot locate symbol` —— §37.5 那个手搓的 lights HAL 就是这么死的。所以这里
所有 libc 调用都自己声明（`open` / `ioctl` / `mmap` / `poll` / `calloc`），
让它们保持 undefined，由 bionic 在加载时解析；`stub/libc.so` 只是给链接器一个
符号来源，一行代码都不进镜像。

`asound.h` 用的是 `/workspace/source/kernel` 里**这台机器真正跑的那棵 3.4 树**，
不是主机的 ALSA 头 —— ioctl 号和 `snd_pcm_hw_params` 的掩码数组大小必须与设备一致。

本地验证（x86 编译同一份源码跑单元测试，`/tmp/t7test`）：

```
36B: ch=2 rate=48000 per=960 cnt=4 fmt=0 start=240 stop=2147483647 sil_th=0 sil_sz=0 avail=240
40B: sil_th=0 sil_sz=0 avail=960
open on a host with no /dev/snd: p=(nil) ready=-1 err=-
zero period: p=(nil) ready=-1 err=-
```

36 字节那份跑出来的 `avail_min` 是 240（正是 `pcm_config_deep_buffer` 里的值），
`silence_*` 归零；失败路径返回 NULL 而不是野对象。

### 38.5 lights HAL：按 7.1 重写，并且这次能加载

fix76 的 `/vendor/lib/hw/lights.default.so` 是 6356 字节、`readelf -d` 里
**没有 DT_NEEDED**，第一条 libc 调用就死了：

```
E HAL: dlopen failed: cannot locate symbol "write" referenced by
       "/system/vendor/lib/hw/lights.default.so"
```

LightsService 起不来，屏幕亮度完全交给 bootloader 留下的值，通知灯也不亮。

`prebuilt/kc/src/lights7.c` 是重写的一份，结构体按 7.1 的
`hw_module_t` / `hw_device_t` / `light_device_t`（128 / 64 / 76 字节）摆，
导出 `HAL_MODULE_INFO_SYM`，只调 `open` / `write` / `close`，并且**声明了
`DT_NEEDED libc.so`**（同上，`-nostdlib -l:libc.so`）。映射：

| light id | sysfs |
|---|---|
| `backlight` | `lcd-backlight/brightness` |
| `buttons` / `keyboard` | `button-backlight/brightness` |
| `battery` | `red/brightness` + `green/brightness` |
| `notifications` / `attention` | `amber/brightness` |
| `bluetooth` / `wifi` | 这块板子没有，返回 0 |

`set_light` 取 ARGB 里最大的颜色分量当亮度（0..255），`flashMode == 2`（TIMED）
视为点亮。屏幕亮度这条尤其要看实测：它同时是"lights HAL 活了没有"的判据 ——
亮度滑条能拖、`/sys/class/leds/lcd-backlight/brightness` 跟着变，就是成了。

### 38.6 开机动画前闪两下：是 kcbtnled 自己点的

fix76 的 `kc_led.log` 只有两行，但够了：

```
start t=6.70 v=0
caught v=5 t=7.89 cam= btn=494
```

`btn=494` 是那一刻 `pidof kcbtnled` 的返回值 —— **写者就是它**。`v=5` 是它
0→255 淡入的第一步，`cam=` 为空说明相机进程根本没在跑。§36.4 那个"GPIO 34 与
相机 `CAM_AF_PWDM` 冲突"的猜测早在 fix75 就撤回了（boot 里的 DTB 没有 gpio-leds
节点，按键背光是 PMIC MPP2，`default-state` 就是 off）。

所以修法不是跟它抢节点，而是**别在开机动画期间启动它**：fix77 把 `kcbtnled`
从 `class core` 拿掉，改成 `on property:sys.boot_completed=1` 起。同时
`kcledguard` 增加一个让位条件：第一阶段每 50 次采样（约 1 秒）看一眼
`sys.boot_completed`，为 1 就记一行 `releasing at boot_completed` 退出，
把节点交还给 kcbtnled —— 否则它会继续压 0 到四分钟，表现为"按键背光坏了"。

### 38.7 报告通道：只留 `/data/local/tmp`

`kcadsp` 以前同时写 `/data/media/0/kcaudio.txt`（0644，方便文件管理器/MTP 读）
和 `/cache/kcaudio.txt`。实际效果是每次交上来的 zip 里有两份一模一样的
`kcaudio.txt`，还要问哪份是这次的。fix77 起**只写 `/data/local/tmp/kcaudio.txt`**，
另外照旧往 `/dev/kmsg` 打 40 行 `KCRPT`（log 分区那份 dump 能带出来）。
`/data/local/tmp` 是 tmpfs，重启即清，一次运行一个文件。

`kcadsp` 这一轮新增/改动的段：

* `sensors`：新增 `-- direct probe --`，对 `input6/enable_als_sensor` 和
  `input7/enable_ps_sensor` 各做一次"写 1 → 等 1 秒 → 读 `/dev/input/eventN`
  3 个 `input_event`（16 字节，`od -tu4`）→ 写回 0"；`dumpsys sensorservice`
  从 30 行加到 60 行；
* `mic`：`dumpsys media.audio_policy` 打**整段前 110 行**（看解析后的 profile），
  再补一遍 grep 版；
* `audio`：`tinyalsa` 那行改成打印路径 + 字节数 + `grep -a` 出来的
  `kc-tinyalsa7/fix77 ...` 标记串 —— 一份 dump 就能确认跑的是哪份库；
* `led`：不变。

### 38.8 fix77 到底改了什么

镜像 `system-fix77.img.zip`（只刷 system，boot 仍是 fix72 那个与 fix70 逐字节
相同的 #25 内核）：

| 路径 | 从 | 到 |
|---|---|---|
| `/lib/libtinyalsa.so` | 13580，KitKat 版 | 21032，`kc-tinyalsa7/fix77` |
| `/vendor/lib/hw/lights.default.so` | 6356，无 DT_NEEDED | 6388，7.1 结构 + libc.so |
| `/etc/audio_policy.conf` | 原厂 input profile | 收窄到 PCM16/MONO/STEREO |
| `/vendor/bin/kcadsp.sh` | fix76 | 38.7 那几段 |
| `/vendor/bin/kcledguard.sh` | fix76 | boot_completed 让位 |
| `/etc/init/kyl23-extra.rc` | fix76 | kcbtnled 延后到 boot_completed |

**没有动的**：`audio.primary.msm8226.so`（厂商 KitKat 二进制，含 ACDB/DSP/tapan
初始化，没有源码）、`sensors.default.so`（§38.2，ABI 本来就是对的）、boot 镜像。

关于"audio HAL 也统一到 7.1"这件事，得说清楚边界：`audio.primary` 不是"一代库"，
它是**厂商闭源 HAL**，7.1 没有对应物。能统一的、也是唯一真正造成故障的，是它
脚下那一层库（`libtinyalsa`）以及与 7.1 框架的接口层（`audio_policy.conf`、
`lights`/`sensors` HAL）。这两层现在都是 7.1 的了。真要重写 `audio.primary`，
等价于从零实现一个 msm8226+tapan 的 audio HAL（mixer 路由、ACDB、voice call、
compress offload），那是另一个量级的工程，而且是拿"已经出声"去换"血统纯正" ——
不建议在传感器和相机还没收尾的时候做。

### 38.9 这一轮要看的

1. `===== led =====`：`lcd` 是不是能被亮度滑条改动（lights HAL 活了没有），
   `-- kcledguard --` 里有没有 `releasing at boot_completed`，开机动画前还应
   完全没有 `caught`；
2. `===== sensors =====` 的 `-- direct probe --`：写 1 之后
   `after=` 是不是 1、有没有事件行。有事件 = HAL 的问题；没事件 = 驱动/器件的问题；
3. `===== mic =====` 的 `dumpsys media.audio_policy` 前 110 行：input profile
   解析成了什么样，以及开机后还有没有 `unreachable`；
4. `tinyalsa:` 那行是不是 `kc-tinyalsa7/fix77`，以及播放时 `pcm=` 能不能进
   `RUNNING`（声音不能因为换库退回去，这是这一轮最大的风险）。

## 39. fix77 全崩，以及四个各不相同的真因

fix77 的四项改动四条全错：没声音、亮度条无效、动画后仍闪两下、麦克风还是不行。
这一轮把每一条都追到根，其中三条是"我写的东西错了"，一条是"根本没问题"。

### 39.1 没声音：自研 libtinyalsa 的两处硬伤

fix76 有声音、fix77 没声音，中间只换了 `libtinyalsa`，所以是我写的那份 1412 行
实现的问题。dump 里 HAL 的行为把范围收得很窄：

```
V audio_hw_primary: start_output_stream: Opening PCM device card_id(0) device_id(0)
V audio_hw_primary: start_output_stream: exit          <- 10 ms 后正常退出，没有报错
```

`pcm_open` 成功（否则 HAL 会打 `E audio_hw_primary`，整个 dump 里一行 E 都没有），
AudioTrack 放了 8 秒，`out_standby` 正常收尾，就是没声。也就是"写进去的数据没人要"。
两处原因，都在我那份实现里：

**(1) avail 公式在环空的时候返回 0。** 我写的是

```c
avail = (pcm->buffer_size + hw - app) % pcm->buffer_size;   /* 错 */
```

第一次写时 `hw == app == 0`，于是 `3840 % 3840 == 0`。`pcm_mmap_transfer` 拿到
`chunk == 0`，状态又不是 RUNNING，直接 `set_error("no frames available")` 返回 -1。
上游的写法是 `buffer_size - (app - hw)`，环空时返回满环 3840。差别就是"第一个字节
能不能写进去"，而第一个字节进不去，后面全都进不去。

**(2) 没有 PREPARE。** fix74 那版我判断"7.1 把 prepare 交给 HAL"，就把
`pcm_write` 里的隐式 prepare 删了。但把这个 HAL 导入的符号列出来看：

```
pcm_open pcm_is_ready pcm_get_error pcm_close pcm_write pcm_read
pcm_start pcm_stop pcm_mmap_write pcm_mmap_read pcm_ioctl pcm_get_htimestamp
```

**没有 `pcm_prepare`** —— 它从来不会自己准备。而内核 `snd_pcm_lib_write1()`
（`sound/core/pcm_lib.c`）在 SETUP 状态下直接 `-EBADFD`。反汇编原厂那份
13580 字节的库，prepared 检查就在 `pcm_write` 和 `pcm_start` 里：

```
<pcm_write>::  movw r1, #16704   @ 0x4140  (SNDRV_PCM_IOCTL_PREPARE)
<pcm_start>::  movw r1, #16704   @ 0x4140  (PREPARE)
<pcm_start>::  movw r1, #16706   @ 0x4142  (START)
```

它是有意这么做的，我却按"7.1 的风格"把它去掉了。两条叠加：即使 avail 算对，
写入也会因为 SETUP 状态失败。

### 39.2 正解：上游 7.1 源码 + `-DIGNORE_SILENCE_SIZE`

不再手写。`pcm.c` / `mixer.c` 用 CyanogenMod `android_external_tinyalsa` 的
cm-14.1 原文（就是 7.1 那一代的原版），只加两样东西：

1. `-DIGNORE_SILENCE_SIZE` —— 这是**上游自带的开关**，作用是删掉
   `struct pcm_config` 的 `silence_size` 字段：

   ```c
   unsigned int start_threshold, stop_threshold, silence_threshold;
   #ifndef IGNORE_SILENCE_SIZE
       unsigned int silence_size;
   #endif
       unsigned int avail_min;
   ```

   编译出来 `sizeof(struct pcm_config) == 36`，与本机厂商 HAL 那份 KitKat 结构
   逐字节相同，`avail_min` 落在 offset 32。§34 那个 36/40 的对撞，上游早就留了
   这个开关，我却在手搓实现里去"猜"字段。

   传 40 字节结构的调用者（7.1 的 usb HAL）offset 32 是 `silence_size`（0），
   上游自己会退化成 `period_size`（mmap）或 1（rw），不会 EINVAL。**一份库同时
   满足两种布局，不需要判断、不需要猜测。**

2. 一个 `bionic_compat.h`，只解决三件宿主 gcc 与 bionic 的差异：
   `errno` 要映射到 `__errno()`（glibc 的 `__errno_location` 在 bionic 上不存在）、
   `stderr`/`fprintf` 变空操作（bionic 没有可链接的 `stderr` 对象，而且错误文本
   本来就写进 `pcm->error`）。另外 Ubuntu 的 gcc-arm-linux-gnueabi 默认
   `_TIME_BITS=64`/`_FILE_OFFSET_BITS=64`，会把 `open`/`mmap`/`ioctl` 变成
   `open64`/`mmap64`/`__ioctl_time64`，所以 build.sh 里显式
   `-D_TIME_BITS=32 -D_FILE_OFFSET_BITS=32 -D_FORTIFY_SOURCE=0`。

结果：26272 字节（原厂 7.1 是 26420），`NEEDED` 只有 `libc.so`，未定义符号全部
是 bionic 有的名字：

```
__aeabi_idiv __aeabi_uidiv __aeabi_uidivmod calloc close __errno fcntl free ioctl
memcpy memset mmap munmap open poll snprintf strcmp strdup strerror strlen sysconf
vsnprintf write
```

导出 57 个 `pcm_*`/`mixer_*`，与原厂 7.1 的 62 个相比只少 5 个 `__aeabi_*`
（libgcc 的除零辅助，bionic 自带，我们也不再静态链它们）。

另外给 `oops()` 加了一行：**任何内部失败同时写 `/dev/kmsg` 的 `KCTL` 行**。
理由就是这个 HAL 不看 `pcm_mmap_write` 的返回值 —— 库坏掉时全系统一声不响，
fix77 就是这么过去的。报告里新增 `-- pcm errors logged by the library --` 段。

### 39.3 用一个假的 3.4 内核把它测了

不能只靠"读代码觉得对"。`prebuilt/kc/src/tests/test_pcm.c` 把 `pcm.c` 编进来，
把 `open/ioctl/mmap/poll/fcntl` 换成假的，假内核按 `sound/core/pcm_native.c` 的
真实规则办事：SETUP 状态下写返回 `-EBADFD`；`silence_size >= boundary` 或
`silence_size > silence_threshold` 或 `avail_min == 0` 一律 `-EINVAL`。

```
sizeof(struct pcm_config) = 36 (must be 36)
-- playback, 36-byte config, non-mmap --
  ok  sw_params accepted            0      ok  avail_min seen by kernel      240
  ok  silence_size forced to 0      0      ok  start_threshold               240
  ok  rate 48000   channels 2   period_size 960   periods 4   buffer_size 3840
  ok  first pcm_write               0      ok  PREPARE was issued            1
  ok  stream is RUNNING             3      ok  prepared only once            1
-- playback, 40-byte config (7.1 caller) --
  ok  avail_min fell back (rw path -> 1)   ok  start_threshold defaulted to p*c/2 1920
  ok  still PREPARED below start_threshold ok  RUNNING once threshold is reached 3
-- the config that used to fail: silence_size 240 --
  ok  kernel rejects silence_size 240 > threshold 0  (EINVAL)
all checks passed (0 failures)
```

最后那条是反向对照：拿 §34 里那份"把 avail_min 当 silence_size"的参数喂给假内核，
它必须报 EINVAL —— 说明这个假内核确实会拒绝当初那个 bug，前面那些 ok 才有意义。

### 39.4 亮度：`HMI`，不是 `HAL_MODULE_INFO_SYM`

fix77 的 `lights.default.so`（6372 字节，`NEEDED libc.so`，符号齐全）仍然没工作，
logcat 里只有一行：

```
E HAL: load: couldn't find symbol HMI
```

`hardware.h` 里是 `#define HAL_MODULE_INFO_SYM HMI`，真 HAL 写
`struct hw_module_t HAL_MODULE_INFO_SYM`，编译器产出的符号名就是 `HMI`。
我在 `lights7.c` 里把宏名当成符号名写了出来，于是 `.so` 导出的是
`HAL_MODULE_INFO_SYM`，而 `hw_get_module()` 找的是 `HMI`：库加载成功，然后被
**丢掉**，LightsService 拿不到设备，亮度条自然一动不动。

顺手把版本字段改成真 HAL 的样子（`HARDWARE_MODULE_API_VERSION(1,0) == 0x0100`）。
现在 `readelf --dyn-syms` 里是 `9: 00002018 128 OBJECT GLOBAL DEFAULT 12 HMI`。

报告里加了三行判据，一条 dump 就能定论：

```
lcd:     <brightness> of <max>          <- 拖亮度条这个数必须变
load:    0 x 'couldn't find symbol HMI' <- 必须是 0
setting: screen_brightness=... mode=... button=...
```

`mode=1` 才是自动亮度；如果它是 0，"光线传感器没用"其实是"自动亮度没开"。

### 39.5 按键背光：三次都错在时间点上

- fix75 说是 DT 冲突 → 撤回（DT 是原厂的，按键背光是 PMIC MPP2）。
- fix76 抓到 `caught v=5 t=7.89 cam= btn=494` → 是 kcbtnled，于是 fix77 把它从
  `class core` 挪到 `boot_completed`。
- fix77 的 dump：`caught v=5 t=53.35 cam= btn=4222`，`boot_completed` 在 52 s，
  也就是**动画结束之后**。用户看到的"闪两下"正好在这个位置。同一份 dump 里
  kcbtnled 自己的日志（`kclog.txt`）写得很清楚：

  ```
  [52] kcbtnled fix24 start: level=255 timeout=5000 enabled=1
  [62] key: dev=0 code=330 led=0 en=1
  [62] set 255 (key): 0 -> 255
  ```

  它的**启动本身不点灯**（52 秒没有任何 `set`），点灯来自 62 秒那次 input
  `code=330`（触摸屏 BTN_TOOL_FINGER）—— 开机动画一结束，触摸屏上报一次，
  kcbtnled 就按设计把按键点亮 5 秒。两次，就是这类事件来了两次。

  而 fix77 的守卫在 53.35 抓到一次之后就没再记录了，`boot_completed` 那段的
  让步逻辑没留下任何行 —— 它在那之后就不再守着节点，62 秒那次自然看得见。

fix78 不再抢时间差：**守卫独占节点 120 秒**（0-60 s 每 20 ms，60-120 s 每 50 ms），
期间任何人写非 0 都压回 0 并记一行；到点后 `setprop sys.kcbtnled.late 1` 才启动
kcbtnled。因为它的启动不点灯，交接是不可见的。另外：

- 守卫加了 `trap` 和 `finish`，**任何退出路径都会留一行原因**（fix77 那种
  "两行之后没了"不能再发生）；
- 新增 `kcbtnlednet.sh`：class core 起，`sleep 200` 后无条件
  `setprop sys.kcbtnled.late 1`。守卫万一死了，按键背光只是晚两分钟，不会永久失效。

`sh` 干跑（`/tmp/g78`，假 sysfs、HOLD=4 s，中途写 5 和 255）：

```
start t=... v=0 hold=4s
caught v=5   t=... cam= btn=
caught v=255 t=... cam= btn=
t=... fast phase done, corrected=2
exit at t=... reason=hold-4s-complete corrected=2
final value: 0
```

### 39.6 麦克风：APM 那一层已经通了

fix77 把 input profile 收窄到 PCM16/MONO|STEREO 之后，7.1 的 APM 开机不再把输入
设备判死。fix77 的 dump：

```
V audio_hw_primary: adev_open_input_stream: enter
V audio_hw_primary: adev_open_input_stream: exit      <- fix76 里永远等不到这一行
- Available input devices:
  Device 1: AUDIO_DEVICE_IN_BUILTIN_MIC  PCM_16_BIT  8000..48000  0x000c,0x0010
  Device 2: AUDIO_DEVICE_IN_BACK_MIC     ...
  Device 3: AUDIO_DEVICE_IN_TELEPHONY_RX ...
```

三个都在、profile 正确、`unreachable` 一条都没有。剩下的断点就是采集流的
`pcm_open` —— 和放音同一个库、同一类错误（§39.1 的 avail 公式和 PREPARE 一样
会把 `pcm_read` 打死）。换库之后这条应该一起好，但需要实测：

- 用录音机 App 录一段，能听到自己的声音；
- 播完 `kcaudio.txt` 里 `-- record attempts --` 应该出现 `start_input_stream`，
  `-- pcm errors --` 里不应有 `KCTL`。

### 39.7 传感器：其实一直是好的，坏的是亮度

fix77 的 `-- direct probe --` 是这一轮最干净的一条证据：

```
input6 enable_als_sensor: before=0 event=/dev/input/event6
input6 enable_als_sensor: after=1
input6 events (16-byte input_event, raw):
   61  950969  2621443  96          <- EV_ABS ABS_MISC = 96 lux
   61  950975        0      0       <- EV_SYN
input7 enable_ps_sensor: after=1  (无事件，见下)
```

`od -tu4` 那两行拆开是 `type=3(EV_ABS) code=0x28(ABS_MISC) value=96`，也就是**手动
写 enable 之后驱动和器件立刻给数据**。再看 `dumpsys sensorservice`：

```
Recent Sensor events:
SFH7776 Light Sensor: last 2 events
	 1 (ts=59.200837) 98.00       <- 就是上面那次 probe
	 2 (ts=61.950975) 96.00
SFH7776 Proximity Sensor: last 1 events
	 1 (ts=62.221997) 4.00
```

这些事件**已经穿过了 HAL 和 SensorService**，说明 `sensors.default.so`（原厂
38192 字节）→ HAL → 框架整条链路是通的。八个传感器名字/厂商/handle 全对，
`Active sensors: 0` 只是当时没有客户端在要（我们自己写完又写回了）。

所以"光线传感器不能用"最可能的真相是：**自动亮度靠 LightsService 调屏幕亮度，
而 lights HAL 是死的（§39.4）**，传感器有数据、屏幕不动。距离传感器同理 ——
它只在通话时关屏，而关屏/亮屏也要走 lights。修好 `HMI` 之后两者应该同时恢复。

距离那次没有事件，是因为 PS 是 on-change：手不在上方时它只在状态变化时上报，
而 probe 只等了 1 秒。不是故障。

为了不再靠猜，报告里加了两样：

- `-- direct probe --` 保留（写 enable → 读 1 秒 event → **写回原值**，不是无条件写 0，
  否则会把电话 App 正在用的 PS 关掉）；
- 采样循环每 30 秒打一行 `sen:`（`dumpsys sensorservice` 里 light/prox 的
  last events 和 active 数），这样**用户在测试 App 里看传感器的同时**，报告里就有
  一条时间线，能直接看出"事件有没有到框架"。

### 39.8 fix78 改了什么

镜像 `system-fix78.img.zip`（只刷 system，boot 仍是 fix72 那版 #25 内核）：

| 路径 | 从 | 到 |
|---|---|---|
| `/lib/libtinyalsa.so` | 21032，自研（avail 公式错、无 PREPARE） | 26272，上游 7.1 + `IGNORE_SILENCE_SIZE` |
| `/vendor/lib/hw/lights.default.so` | 6372，导出 `HAL_MODULE_INFO_SYM` | 6372，导出 `HMI` |
| `/vendor/bin/kcledguard.sh` | fix77，45 s + 6 s 让步 | 独占 120 s，退出必留原因 |
| `/vendor/bin/kcbtnlednet.sh` | 无 | 新增，200 s 后无条件放行 kcbtnled |
| `/etc/init/kyl23-extra.rc` | fix77 | kcbtnled 改由 `sys.kcbtnled.late` 启动 |
| `/vendor/bin/kcadsp.sh` | fix77 | `KCTL` 段、`sen:` 周期采样、亮度/HMI/设置三项判据 |

源码：`prebuilt/kc/src/tinyalsa/`（pcm.c、mixer.c、include/tinyalsa/asoundlib.h、
bionic_compat.h）、`lights7.c`、`tests/test_pcm.c`，`build.sh` 一键重编。
手写的 `tinyalsa7.c` 已删除 —— 一份"看起来对"的实现输给了一份被几亿台设备跑过的
实现，这轮就认这一点。

### 39.9 这一轮要看的

1. **声音**：放音时 `pcm=` 能进 `RUNNING`；`tinyalsa:` 行显示
   `kc-tinyalsa7/fix78: upstream 7.1 pcm.c+mixer.c, IGNORE_SILENCE_SIZE`；
   `-- pcm errors --` 里应为空。
2. **亮度**：拖亮度条，`lcd:` 那个数要变；`load: 0 x 'couldn't find symbol HMI'`。
3. **自动亮度**：`setting:` 行里 `mode=` 是不是 1。
4. **按键背光**：开机动画前后都不该闪；`kc_led.log` 里应有
   `start ... hold=120s`、若干 `caught` 带 `btn=<pidof kcbtnled>`（如果 120 s 内
   还有的话）、以及 `exit at ... reason=hold-120s-complete`。
5. **麦克风**：录一段音；`-- record attempts --` 出现 `start_input_stream`。
6. **传感器**：`sen:` 那些行里有没有新的 light/prox 事件。

## 40. 自动亮度和距离感应：两个 bool、两条曲线，都在资源里

fix78 的验收结果：**麦克风正常了，声音正常了，亮度条也能调**。§39.4 的判断成立 ——
lights HAL 一旦导出 `HMI`，亮度、关屏、按键背光就都活了。

剩下两件是新的，而且都不是驱动问题：

- 设置 → 显示 里没有"自适应亮度"这一项；
- 距离传感器"似乎没生效"。

这两件是同一个性质：**功能开关在资源里是关的**。这台机器之前没有任何设备 overlay
（`device/kyocera/msm8926-common/overlay/` 这个目录根本不存在），所以所有
`config_*` 都停在 AOSP 默认值上，而 AOSP 默认值是"别的设备在自己的 overlay 里打开"。

### 40.1 自动亮度：一个 bool 加两条曲线

`config_automatic_brightness_available` 这一个 bool 同时控制两个地方：

| 位置 | false 时 |
|---|---|
| `DisplaySettings.isAutomaticBrightnessAvailable()` | 直接把 preference `removePreference` 掉，设置里就没有这一项 |
| `DisplayPowerController` 构造函数 | `mUseSoftwareAutoBrightnessConfig = false`，不建 `AutomaticBrightnessController`，连光感都不注册 |

所以"开关不在"和"就算在也没用"是同一个原因。fix78 的 dump 里 `setting: mode=0`
也印证了这一点（`Settings.System.SCREEN_BRIGHTNESS_MODE` 是手动）。

### 40.2 但只把 bool 打开会开不了机

`createAutoBrightnessSpline()` 是这样的：

```java
final int n = brightness.length;
y[0] = normalizeAbsoluteBrightness(brightness[0]);   // 空数组 -> AIOOBE
for (int i = 1; i < n; i++) { x[i] = lux[i - 1]; ... }
```

这台机器的 `config_autoBrightnessLevels` 和 `...LcdBacklightValues` 都是**空数组**。
bool 一打开，`brightness[0]` 就是 `ArrayIndexOutOfBoundsException`，而这个异常在
`DisplayPowerController` 的构造路径上 —— 打穿的是 system_server，也就是开机循环。
**bool 和两个数组必须一起改。**

数组本身还有两个坑：

- `x[0]` 恒为 0（`Spline` 的第一个控制点是 0），所以 `lux[0]` 不能是 0，否则
  `Spline.createSpline()` 因为 x 不严格递增抛 `IllegalArgumentException`，被 catch
  成 `"Could not create auto-brightness spline"`，功能**静默失效**，看起来就像没修；
- 背光数组必须比 lux 数组**多一个**（多出来那个是"比第一个阈值还暗"）。

fix79 用的曲线（写进 `overlay/.../core/res/res/values/config.xml`，也写进了镜像）：

```
lux:      5  20  60  150  400  1000 2500 6000 10000 20000
backlig: 12  25  45   70   95   120  150  185   220   245  255
```

### 40.3 距离感应：bool 在另一个 apk 里

`config_proximityCheckOnWake` 不在 framework-res，在
`/framework/org.cyanogenmod.platform-res.apk`（包名 `cyanogenmod.platform`，
运行时包 id `0x3f`）。dump 里那一行就是它：

```
ConstraintsHelper: construct key=proximity_on_wake available=false
```

`available=false` 的后果是两件事：CM 的设置界面根本不生成这个开关；
`PhoneWindowManager` 也不会注册 PS 监听（"口袋里别点亮屏幕"变成死代码）。

而**传感器本身是好的**，dump 里 `dumpsys sensorservice` 写得很清楚：

```
0x00000008) SFH7776 Proximity Sensor | OSRAM | type: android.sensor.proximity(8) | wakeUp
SFH7776 Proximity Sensor: last 3 events
   1 (ts=62.924165000) 4.00
   2 (ts=63.121939000) 3.00
   3 (ts=63.222930000) 4.00
Previous Registrations:
   22:52:14 activated handle=0x00000008 ... package=com.android.systemui.classifier.FalsingManager
```

有事件、数值合理（3~4 cm，手不在上方）、SystemUI 的 FalsingManager 一直在用它。
所以"距离传感器没生效"从头到尾是**功能开关**，不是硬件也不是 HAL。

fix79 把 `config_proximityCheckOnWake` 和 `...EnabledByDefault` 都打开了 ——
后者是行为改变（默认就在口袋里挡亮屏），只因为上面这段证据说明 PS 读数正常才敢开。
想关掉：设置 → 显示 → 防止误触，不用重刷。

### 40.4 改这两个 apk 的前提：platform key

framework-res 和 CM 平台资源都是用 AOSP **platform key** 签的：

```
sha256 Fingerprint=C8:A2:E9:BC:CF:59:7C:2F:B6:DC:66:BE:E2:93:FC:13:
                  F2:FC:47:EC:77:BC:6B:2B:0D:52:C1:1F:51:19:2A:B8
```

私钥在 `platform_build/android-7.1.2_r1/target/product/security/`（`platform.pk8`
+ `platform.x509.pem`）。**换成任何别的 key 都不行**：framework-res 会被
PackageManager 拒收，或者反过来把所有 `android.uid.system` 的应用签名校验打掉 ——
两种结果都是开不了机。AOSP 的 `testkey`（`A4:0D:A8:…`）也不行，指纹对不上。

### 40.5 不能用 jarsigner

`jarsigner` 会把整个 apk 的所有 entry 按 DEFLATE 重写一遍，包括
`resources.arsc`。而**这个 entry 必须是 STORED**：AAPT 打 apk 时就是这么打的，
`AssetManager` 用 `mmap` 直接按偏移读资源表，压缩过的它读不到 —— 结果是资源全丢，
开机第一个 `Resources$NotFoundException` 就来自 framework。

```
19862168  Stored  19862168   0%  resources.arsc     <- 必须是这样
```

`jarsigner -verify` 仍然可以用，只是用来**验证**签名块本身对不对（`jar verified.`），
产物不能拿它签。

### 40.6 手写的 v1 签名 + 4 字节对齐

树里没有 build-tools 的 `apksigner`，所以 v1 签名是脚本自己拼的
（`tools/image/apkresign.py`）：

1. `META-INF/MANIFEST.MF`：每个 entry 一段 `Name:` + `SHA-256-Digest:`，
   72 字节折行、续行以空格开头；
2. `META-INF/CERT.SF`：`SHA-256-Digest-Manifest` 加上每段的
   `SHA-256-Digest`（对 MANIFEST.MF 里那一段的字节算）；
3. `META-INF/CERT.RSA`：`openssl smime -sign -binary -noattr -md sha256`
   出的 DER PKCS#7。

打包顺序照原 apk 抄，每个 entry 的 `compress_type` 也照抄；STORED 的条目补 4 字节
对齐，用的就是 zipalign 自己的办法 —— 往 extra field 里塞一个 id `0xd935` 的填充块：

```python
pad = (4 - ((cur + 30 + len(name)) % 4)) % 4
zi.extra = struct.pack("<HH", 0xD935, pad - 4) + b"\0" * (pad - 4)
```

原 apk 带 APK Signature Scheme v2 块，重签后没有了（v1 only）。Android 7 上 v2 是
可选的，PMS 会退回 v1 校验，这条路是通的 —— 代价是 apk 小了 10 KB：

```
/framework/framework-res.apk   36,713,477 -> 36,703,276
/framework/org...platform-res.apk  579,301 -> 577,142
```

### 40.7 单值补丁：bool 就是 4 个字节

一个 bool 资源在 `resources.arsc` 里是 `ResTable_entry`（8 字节头）后面跟一个
`Res_value`：

```c
struct Res_value { uint16_t size; uint8_t res0; uint8_t dataType; uint32_t data; };
```

`dataType` 是 0x12（`TYPE_INT_BOOLEAN`），`data` 就是 0 或 0xFFFFFFFF。改它不需要
重编，也不用动任何 id：`tools/image/arsc_patch.py` 里就是 `b[e+11] = 0x12;
pack_into("<I", b, e+12, value)`。

CM 平台那两个 bool 就是这么改的（`0x3f050001` / `0x3f050002`，4 字节 each），
改完 `aapt dump --values resources` 的资源 id 全表 diff 是 **0 行**。

### 40.8 空数组怎么塞进去：把 bag 搬到 chunk 末尾

数组不是"另一个 blob"，它的 `ResTable_map` 项是**紧跟在 entry 后面**的。原来的空数组
是 `count = 0` 的 `ResTable_map_entry`，后面紧跟着下一个 entry —— 没有地方放 10 个
item。而且这个 entry 的 offset 表项只能指向"整条 entry（头 + 内联 items）"。

做法（`arsc_patch.py: set_int_array`）：把整条 entry 复制到 type chunk 的**末尾**，
把 item 填进去，然后把 entry offset 表里那一项指向新位置。老的那条留在原地当死空间，
没人读。然后只需要改三个尺寸字段，全是相对值，后面的 chunk 不用动：

```
type chunk size  += 136 / 148
package size     += 同上
table header size += 同上
```

结果：

```
resource 0x0107002e android:array/config_autoBrightnessLevels: <bag>
  Count=10   5 20 60 150 400 1000 2500 6000 10000 20000
resource 0x0107002f ...LcdBacklightValues: <bag>
  Count=11   12 25 45 70 95 120 150 185 220 245 255
resource 0x01120025 android:bool/config_automatic_brightness_available: d=0xffffffff
```

`resources.arsc` 从 19,861,884 长到 19,862,168（+284）。9448 条资源的 spec 全表
逐行 diff **0 行**（连 flags 都一样），`aapt` 的 stderr 是空的。

### 40.9 fix79 改了什么

镜像 `system-fix79.img.zip`（只刷 system，boot 仍是 fix72 那版 #25 内核）：

| 路径 | 从 | 到 |
|---|---|---|
| `/framework/framework-res.apk` | 36,713,477 原厂 | 36,703,276：`automatic_brightness_available=true` + 两条曲线 |
| `/framework/org.cyanogenmod.platform-res.apk` | 579,301 原厂 | 577,142：`proximityCheckOnWake`、`...EnabledByDefault` 均 true |
| `/vendor/bin/kcadsp.sh` | fix78 | 加 `bootwatch`（开机 90 s 内每 2 s 采一次线程状态）、`sec display` 段 |
| `/vendor/bin/kcledguard.sh` | fix78 | 加相位心跳（只写 `kc_led.log`，不写 kmsg） |

另外：`kcledguard.sh` 的保持时间没动（还是 120 s 独占），但每 250 / 100 次循环记
一行 `t=… phase1 v=…` 到 `kc_led.log`，这样"55 秒那一下闪"到底是谁写的就有时间线了。
`kcadsp.sh` 的 `sec display` 打 `mUseSoftwareAutoBrightnessConfig` /
`mAutomaticBrightnessController` / `mProximitySensor` / `mAmbientLux` 和
`dumpsys window policy` 的 proximity 状态 —— 这三件是下一轮的判据。

### 40.10 这一轮要看的

1. **自动亮度**：设置 → 显示 里出现"自适应亮度"。打开后 `sec display` 里
   `mUseSoftwareAutoBrightnessConfig=true`、`mAutomaticBrightnessController` 不是
   null；手遮住光感，`mAmbientLux` 和 `lcd:` 都要跟着变。
2. **距离感应**：`dumpsys display` 里 `mProximitySensor=` 不是 null；设置 → 显示 里
   出现"防止误触"且默认开；手盖住听筒附近按电源键，屏幕不该亮。
3. **开机 25 秒**：`kc_boot.log` 里 sensorservice 那个线程是 D 还是 S。
4. **背光**：`kc_led.log` 里的心跳还在不在，55 s 那一下还有没有。

## 41. 为什么不能重编 framework-res：私有属性会重新编号

这一节记的是 fix79 走错又退回来的那条路，因为它是一次"看起来成功了"的失败。

### 41.1 apktool 能编出来，而且能开机

`apktool d` 解开 framework-res，改 `res/values/config.xml`，`apktool b` 回去，
签名，刷机 —— 这条路是通的，资源也能读到。问题不在能不能跑，在**资源 id 变了**。

```
aapt dump --values resources framework-res.apk | grep 'spec resource'
  原厂   9448 行
  重编   9448 行
  集合   完全相同
  顺序   9246..9448 这 203 行整段不同
```

差的这 203 条是 `android:^attr-private/*`。apktool 把它们解到单独一个
`res/values/^attr-privates.xml`，回编时按**名字排序**重新分配 id，而原厂是 aapt 按
`public.xml` 里的声明顺序分配的。名字一个不少，id 一个不剩，全对不上。

### 41.2 后果：别人的代码还拿着旧 id

`^attr-private` 是 `android` 包里的私有属性，框架自己的 style/layout 用它 —— 那些
跟着 apk 一起重编了，没问题。但镜像里还有一堆**早就编译好的** apk（SystemUI、
Settings、CMParts、CM 设置），它们编译时拿到的是**旧 id**，二进制 XML 里存的就是
数字，运行时不会重新查名字。

于是 `0x01160001` 在它们眼里是 `textColorPrimaryActivated`（颜色），在重编后的表里
变成了 `actionModePopupWindowStyle`（样式引用）。轻则颜色不对，重则
`Resources$NotFoundException` 或者把颜色值当资源 id 用。这类问题**不会在开机时
报错**，只在某个界面被打开的时候出现 —— 是最难查的那种。

所以规则是：**framework-res 不重编，只做原地补丁。** 补丁补不了的东西，就不改。

### 41.3 原地补丁能改什么

| 想改的 | 能不能原地改 |
|---|---|
| bool / int / color / dimen / string 的值 | 能，`Res_value.data` 就 4 字节 |
| 空数组 -> 非空 | 能，见 §40.8（搬 bag） |
| 已有数组改长度 | 能，同一套办法 |
| 加一个新资源、改一个字符串的内容（长度变了） | 不能，会牵动 string pool 和所有偏移 |
| 改 layout / style 的结构 | 不能，等于重编 |

两条曲线的长度是固定的（10 / 11），所以这一轮刚好都在"能"这一列。

### 41.4 验证办法

不是"刷进去看看能不能开机"，那太粗。三个机械检查，任何一个不过就不刷：

```bash
# 1. 资源 id 全表，逐行（含 flags）必须 0 行差异
aapt dump --values resources orig.apk | grep '^\s\+spec resource' > a.txt
aapt dump --values resources new.apk  | grep '^\s\+spec resource' > b.txt
diff a.txt b.txt          # 必须为空

# 2. aapt 自己不能有怨言
aapt dump --values resources new.apk >/dev/null   # stderr 必须为空

# 3. 签名块本身
jarsigner -verify new.apk                          # jar verified.
unzip -v new.apk | grep resources.arsc             # Stored
```

第 2 条是有用的：第一次做的时候 `set_int_array` 忘了把 16 字节的
`ResTable_map_entry` 头一起搬过去，aapt 直接吐

```
ResTable_entry size 0x1 is too small
INVALID RESOURCE 0x0107002e: NON-INTEGER ResTable_entry SIZE: 0x1
```

—— 说明 offset 指到了 map 数据上，而不是 entry 头上。没有这条检查，这个错会一路
带到刷机。

### 41.5 顺带：这些工具在树里了

| 文件 | 干什么 |
|---|---|
| `tools/image/apkresign.py` | `sign`：重打 apktool 产物并按原 apk 的顺序/压缩方式重签；`patch`：替换 `resources.arsc`（`--arsc` 或 `--set OFFSET:HEX`）后重签 |
| `tools/image/arsc_patch.py` | 直接改 `resources.arsc`：`--bool`、`--int-array`、`--dump`，不重编、不动 id |

## 42. 镜像打 zip 会莫名胖 17 MB

fix79 第一次打包出来 402,611,350 字节，fix78 是 384,964,007。内容只差几十 KB，
体积差了 17.6 MB，压缩率从 74% 掉到 73%。

原因：`debugfs` 写文件是**走日志**的。ext4 的 journal 在 1.4 GB 的镜像上是 5615 个
块（21.9 MB），`debugfs -w` 把新数据写进去之后，这 21.9 MB 里全是"近似的元数据"，
压缩不动。而 `zerofree` 只处理**空闲块**，日志块是 in-use，它不碰。

清日志要小心，但这次是安全的：`dumpe2fs -h` 里 `Journal start: 0`、
`sequence: 1` 说明没有待回放的事务，所以把日志体清零不会丢东西。保留头 8 KB
（jbd2 超级块），剩下的从块 +2 开始填零：

```python
# journal inode 8 的 extent 从 debugfs -R "stat <8>" 里读
off = phys_start * 4096 + 8192
zero(off, (phys_end + 1) * 4096 - off)
```

之后 `e2fsck -fn` 依旧干净，`dumpe2fs -h` 依旧显示 `Journal start: 0`，zip 回到
384,057,801。

所以现在的打包顺序固定是：`debugfs` 注入 -> `e2fsck -fn` -> `zerofree` ->
清日志 -> `e2fsck -fn` -> `zip -6`。

## 43. 拆掉按键灯的调试，和两个还没结案的传感器

fix79 的结果是"一半":设置里那个开关出来了,但按下去看不到反应;距离感应还是没动静。
这一轮把能确定的部分做掉(按键灯整套调试),把不能确定的部分改成**一次能问清楚的测量**。

### 43.1 自动亮度:框架这一侧已经对了

`dumpsys display` 在 fix79 里第一次给出了完整的那一段:

```
mUseSoftwareAutoBrightnessConfig=true
mScreenAutoBrightnessSpline=MonotoneCubicSpline{[(0.0, 0.047: ..), (5.0, 0.098: ..),
    ... (20000.0, 1.0: ..)]}                       <- 11 个控制点都在
mLightSensor={Sensor name="SFH7776 Light Sensor", ...}
mScreenBrightness=30
-- Automatic Brightness Controller State --
mLightSensorEnabled=false
mLightSensorEnableTime=0 (94487 ms ago)            <- 从来没开过
mAmbientLux=0.0
mScreenAutoBrightness=-1
```

也就是说:`config_automatic_brightness_available` 和两条曲线都读进去了(fix78 的判断
成立),但 `AutomaticBrightnessController` **一次都没有把光感打开**。它的入口只有一个:

```java
// DisplayPowerController.updatePowerState()
autoBrightnessEnabled = mPowerRequest.useAutoBrightness
        && (state == STATE_ON || doze) && brightness < 0;
mAutomaticBrightnessController.configure(autoBrightnessEnabled, ...);
// AutomaticBrightnessController.configure()
boolean changed = setLightSensorEnabled(enable && !dozing);
```

而 `mPowerRequest.useAutoBrightness` 只来自 PowerManagerService 里那一行:

```java
// PMS.updateDisplayPowerStateLocked()
boolean autoBrightness = (mScreenBrightnessModeSetting ==
        Settings.System.SCREEN_BRIGHTNESS_MODE_AUTOMATIC);
```

`mScreenBrightnessModeSetting` 在 `updateSettingsLocked()` 里重新读,任何一次设置变更
都会走到那里。所以只剩两种解释:要么那个读的时刻 `mode` 还是 0,要么 PMS 的观察者没
把它读进来。

### 43.2 报告的时间点比测试早

`kcadsp.sh` 在 `boot_completed` 之后立刻写报告,而用户是拿到机器才去 设置 -> 显示 打开
开关的。fix79 的 dump 里两个时间点能对上这件事:

- `sec display`(t≈84)说自动亮度没启用;
- `sec led` 里 `setting: ... mode=1`(t≈90)说已经开了。

6 秒之差,报告写的是"打开之前"。更要紧的是后面:

```
158.47 | sen: SFH7776 Light Sensor: last 1 events  ... Proximity Sensor: last 1 events
196.83 | sen: SFH7776 Light Sensor: last 1 events  ... Proximity Sensor: last 1 events
```

到 t=196 光感仍然只有**一个**事件。如果 `mode=1` 真的让 ABC 打开了光感、采样率 250 ms,
这里应该是几十个。所以不是"报告写得早"这么简单 —— 关了灯之后也没有事件。

### 43.3 确定的另一半:那 3 秒里 ALS 一个事件都没发

fix79 的直读探针和 fix78 用的是同一段脚本、同一个窗口:

| | fix78 | fix79 |
|---|---|---|
| `enable_als_sensor` 写入 1 | `before=0 after=1` | `before=0 after=1` |
| `/dev/input/event6` 3 秒内 | 4 个事件(100 / 98 / 100 / 82 lux) | **0 个** |

驱动里 `sfh7776_als_work_handler()` 是**无条件**上报的,每 `als_poll_delay`(250 ms)
一次,不管值有没有变:

```c
luxValue = sfh7776_als_lux_conversion(...);
input_report_abs(data->input_dev_als, ABS_MISC, (int)luxValue);
input_sync(data->input_dev_als);
schedule_delayed_work(&data->als_dwork, msecs_to_jiffies(data->als_poll_delay));
```

所以"没有事件"只有一种含义:**这个 work 没跑**。`enable_als_sensor` 写入是计数器的,
写 1 之后如果 `<=1` 就 `sfh7776_select_control()` + 重新排 work;`before=0` 说明计数器
本来是 0,那一次写入应该正好触发它。

sensorservice 那边记到的那一个事件是 `0.00` —— 那是驱动在 enable 时补发的
`input_report_abs(ABS_VOLUME, serial)`,被 HAL 当成了 lux 值。

结论:光感这条链上有一环是死的,但**从框架状态看不出是哪一环**。三个数就能定:

| 数 | 谁写的 | 含义 |
|---|---|---|
| `mLightSensorEnabled` | 框架(ABC) | false = 框架根本没开 |
| `/sys/class/input/input6/enable_als_sensor` | HAL | 0 = HAL 没往驱动写 |
| `mAmbientLux` / `mLastObservedLux` | 框架(ABC) | 一直是 0 = 驱动没给数据 |

组合起来:框架 true + 驱动 0 → HAL 断了;框架 true + 驱动 1 + lux 0 → 驱动/芯片;
框架 false → 回去查 §43.1 那两行。

### 43.4 距离感应:功能确实在,但判据在 PWM 自己身上

先把"这个 ROM 里到底有没有那个功能"这件事钉死。`services.jar` 的 dex 里有:

```
proximity_on_wake              mProximityWakeEnabled       mProximityWakeSupported
wakeUpWithProximityCheck       runWithProximityCheck       checkProximity
"Not waking up. Proximity sensor is blocked."
"Proximity sensor took too long, wake event already triggered!"
```

最后那条是安全网:传感器不回事件时,电源键最多等一个超时,不会变成砖。`proximity_on_wake`
是 `Settings.System` 的键,PWM 在 init 里按 `config_proximityCheckOnWake` 决定要不要
`getDefaultSensor(TYPE_PROXIMITY)`。

fix79 已经把 `config_proximityCheckOnWake` 和 `...EnabledByDefault` 都设成 true,所以
剩下的可能只有两个:那个 bool 没被读到(PWM 在 SensorService 起来之前就问了一遍),
或者 `Settings.System` 里 `proximity_on_wake` 这一行早就存在且是 0(资源默认值只在
**那一行不存在**时生效)。

`dumpsys window policy` 里 `mProximityWakeSupported` / `mProximityWakeEnabled` 加
`settings get system proximity_on_wake`,这一组就能分开。

顺带一个事实:`dumpsys display` 里 `mProximitySensorEnabled=false` 是**正常**的 ——
那个 handle 是 `LIGHT_ID_PROXIMITY` 的屏幕锁(通话中贴脸关屏)用的,要
`PROXIMITY_SCREEN_OFF_WAKE_LOCK` 才会开。整机空闲时它就是 false。

### 43.5 按键灯:整套拆掉

fix76 到 fix79 围绕"开机时背光闪两下"堆了三样东西:

| 文件 | 干什么 |
|---|---|
| `/vendor/bin/kcbtnled` | 632 KB 静态 ARM,自己解析 CMSettings 的 SQLite 读"按键背光亮度/超时",按键时点灯 |
| `/vendor/bin/kcledguard.sh` | 前两分钟把节点按在 0,记录别人写的每个值 |
| `/vendor/bin/kcbtnlednet.sh` | 200 秒兜底,怕 guard 死在半路导致键永远不亮 |

现在全删了。理由是 fix76 那一条自己就写明了写者是谁:

```
caught v=5 t=7.89 cam= btn=494      <- 7.89 s,值 5,pidof kcbtnled = 494
```

而 fix79 的 `kc_led.log` 把它补完了:

```
start t=6.89 v=0 hold=120s
beat ... phase1 v=0 ...
caught v=5 t=59.60 cam= btn=        <- 抓到,然后没有下文
```

guard 抓到 v=5 之后自己就没了(它该继续 beat 到 120 s),`kcbtnled` 一直没被放行,
直到 `kcbtnlednet` 的 200 秒兜底把它拉起来(`kclog.txt` 里 `[207] kcbtnled fix24 start`)。
而 t≈90 的报告里 `button: 5 of 255` —— 那个 5 是**框架的 lights HAL** 写的,不是这个守护。

所以:闪的那两下 = kcbtnled 启动时点 255、5 秒后淡出、guard 中间把 0 写回去,一前一后
就是两次。没有守护就没有写者。`button-backlight` 现在归框架,而框架这一侧是 fix78 修好的
(`HMI` 符号),这也是为什么它现在能写 5 了 —— 以前根本写不了,才有"7.1 从不点亮按键灯"
那个判断。

### 43.6 报告瘦身

`kcadsp.sh` 从 28 175 字节降到 17 544,行数 604 -> 380。

| 去掉 | 为什么 |
|---|---|
| `bootwatch`(开机 90 s 每 2 s 采线程状态) | 那 25 秒是 ADSP 起不来拖住 audioserver,已经好了 |
| `-- boot stall --` 段 | 同上 |
| `-- direct probe --`(直读 /dev/input/event6) | 被 HAL 抓着的节点读不到东西,换成了 HAL 侧的 `enable_als_sensor` |
| `sec pcm`(21 个 PCM 节点的 status) | 声音好了,只需要一行"有没有忙的节点" |
| `-- audio policy (full, first 110 lines) --` | 麦克风好了 |
| `audiosnap()` / 1200 次 1 秒采样 / `.ev` 文件 | 那是 fix72-fix78 诊断声音用的,每轮往 kmsg 写 40 KB |
| `-- kcledguard --` 段 | guard 没了 |
| `sen:` 每 30 秒一行 | 换成下面那个时间线 |

| 新增 | 为什么 |
|---|---|
| `dispblock`:power + display + window policy + settings + 输入节点,一次 20 行 | 三个判据在同一时刻取,能互相验证 |
| 开机后 5 分钟时间线,每 60 秒一次 `dispblock` | 报告写的时候用户还没走到设置,只有时间线能给出"同一个动作"的前后 |
| 提示语(遮光感 2 秒、盖听筒 3 秒) | 采样是自动的,动作要在窗口里做 |

### 43.7 fix80 改了什么

镜像 `system-fix80.img.zip`(只刷 system,boot 仍是 fix72 那版 #25 内核):

| 路径 | 从 | 到 |
|---|---|---|
| `/vendor/bin/kcbtnled` | 632 016,fix24 自建 | **删除** |
| `/vendor/bin/kcledguard.sh` | fix78 | **删除** |
| `/vendor/bin/kcbtnlednet.sh` | fix78 | **删除** |
| `/etc/init/kyl23-extra.rc` | 三个 service + `sys.kcbtnled.late` 触发器 | 全删,原位留一段说明 |
| `/vendor/bin/kcadsp.sh` | 28 175,604 行 | 17 544,380 行 |
| `/framework/framework-res.apk` | fix79 | 不变(00b8b940) |
| `/framework/org.cyanogenmod.platform-res.apk` | fix79 | 不变(3009dd66) |

### 43.8 这一轮要看的

1. **开机后别再闪**:按键灯只在框架要它亮的时候亮。`kc_led.log` 不会再出现。
2. **时间线**:`/data/local/tmp/kcaudio.txt` 末尾会有 `===== sensor timeline =====`,
   五次 `-- t+60 s --` … 每次 20 行。打开自适应亮度、遮光感、盖听筒都在这五分钟里做。
3. **三个数**:看最后一次采样里 `mLightSensorEnabled`、`input: light=... en=?`、
   `mAmbientLux` —— 见 §43.3 的表。
4. **距离**:`dumpsys window policy` 的 `mProximityWakeSupported` / `mProximityWakeEnabled`
   和 `setting: ... prox=?`。

## 44. 两个传感器的真正原因：一个 chown

fix80 的 dump 把这件事问清楚了，而且答案比前几轮猜的都简单。

### 44.1 框架这一侧已经无可挑剔

```
mUseSoftwareAutoBrightnessConfig=true
mScreenAutoBrightnessSpline=MonotoneCubicSpline{[(0.0, ...), (5.0, ...), ...]}
mLightSensor={Sensor name="SFH7776 Light Sensor", ...}
mLightSensorEnabled=true
mLightSensorEnableTime=56191 (6544 ms ago)        <- 真的开了，不是从来没开
mAmbientLux=0.0
mLastObservedLux=0.0
mAmbientLightRingBuffer=[]                        <- 一个事件都没收到
mScreenAutoBrightness=-1
```

`AutomaticBrightnessController` 这次确实调了 `setLightSensorEnabled(true)`，`mScreenBrightnessModeSetting`
也是 1（那行 `setting: mode=1`）。框架要的做了，事件没来。

### 44.2 剩下的三个数指向同一处

fix80 的报告新增了一行直读驱动的状态：

```
input:   light=/sys/class/input/input6 en=0 poll=250000 | prox=/sys/class/input/input7 en=0
```

`enable_als_sensor` 是 0，`enable_ps_sensor` 也是 0。而且 `als_poll_delay` 是 250000，
正是驱动里 `data->als_poll_delay = 250` 的默认值（show 里 `*1000`）：

```c
static ssize_t sfh7776_show_als_poll_delay(...) { return sprintf(buf, "%d\n", data->als_poll_delay*1000); }
```

也就是说：**HAL 一次都没写成功过这两个节点，连采样率都没写进去**。框架说开、驱动说没开，
中间那一环是 HAL。

### 44.3 为什么写不进去：uid，不是 SELinux

先排掉 SELinux：整机是 permissive（`permissive=1` 出现在每一条 avc 里），所以拒绝写不会
是它。再看驱动：

```c
static DEVICE_ATTR(enable_als_sensor, S_IRUSR|S_IWUSR|S_IRGRP|S_IWGRP, ...);   /* 0660 */
static DEVICE_ATTR(enable_ps_sensor,  S_IRUSR|S_IWUSR|S_IRGRP|S_IWGRP, ...);   /* 0660 */
static DEVICE_ATTR(ps_crosstalk,      S_IRUSR|S_IWUSR|S_IRGRP|S_IWGRP, ...);   /* 0660 */
static struct miscdevice sfh7776_device = { .name = "psals_sensor", ... };     /* 0600 */
```

sysfs 属性默认属主 root:root，`misc_register()` 不给 mode 时也是 0600 root:root。而
`/vendor/lib/hw/sensors.default.so` **不是**一个独立进程：7.1 的 SensorService 在
system_server 里，HAL 是 dlopen 进来的，于是它写文件用的身份是 **uid 1000 (system)**。
0660 root:root 对 uid 1000 来说不可写 —— 每一次 `activate()` 都拿到 EACCES，`enable()`
返回 -1，SensorService 静默放弃，驱动什么都没收到。

HAL 反汇编对得上（`sensors.default.so` 是流媒体预编译，符号还在）：

```
LightSensor::enable(int handle, int en)        @0x5928 (Thumb)
    cmp  r1, #5                 ; handle == LIGHT
    ldr  r3, [r5, #0x14]        ; 缓存
    cmp  r3, r2 / beq  ret 0    ; 没变化就不写
    bl   sysfs_set_input_attr_by_int(path, "enable_als_sensor", en)
    cmp  r0, #0 / blt  ret -1   ; 写失败就直接返回 -1，缓存也不更新
    str  r4, [r5, #0x14]
    bl   sysfs_set_input_attr_by_int(path, "wake", 1)
```

### 44.4 那 24 秒也是同一件事

`nuSensorService starting...`(03.893) → `nuSensorService thread starting...`(28.428)，24.5 s。
构造函数里要做三件事：两个 `readInitialValue()`、一个 `setCrossTalkVal()`（读
`ps_crosstalk`）。这三个都因为同一个 EACCES 失败，而它们带重试。fix80 的 dump 里
`SensorService` 一条错误都没有 —— 不是没失败，是失败被吞在 HAL 里、重试到超时才返回。

顺带：`mProximitySensorEnabled=false` 依旧是正常的（那是通话贴脸关屏的屏幕锁），
`mProximitySensor=` 这次也不是 null，所以距离感应的硬件、句柄、PMS 通路都是好的，
坏的只是"让驱动开始采样"这一步。

### 44.5 原厂是怎么做的

`stock/boot.img` 的 ramdisk 里有 `init.kc.sensor.sh`，`init.rc` 里也有一整段：

```
    chown system input /sys/class/input/input6/enable_als_sensor
    chown system input /sys/class/input/input6/delay
    chown system input /sys/class/input/input6/wake
    chown system input /sys/class/input/input7/enable_ps_sensor
    chown system input /sys/class/input/input7/ps_crosstalk
    ...
on boot
    chown system system /dev/psals_sensor
    start sensor-sh
```

我们的 ramdisk 是 CM 的 msm8926 那套（`init.rc` / `init.qcom.rc` / `init.cm.rc`），
`init.kc.sensor.sh` 和这些 chown 一行都没有 —— 这就是从 fix72 到 fix80 两个传感器一直
"没生效"的全部原因。不是驱动、不是 HAL 版本、不是 SELinux、不是资源里那两个 bool。

### 44.6 fix81 改了什么

新增 `/vendor/bin/kcsensor.sh`，在 `on post-fs-data` 里由 `start kcsensor` 拉起来
（`class core` / `oneshot` / `disabled`）。它按 `/sys/class/input/input*/name` 匹配，
把节点交给 uid 1000 / gid 1004：

| 节点 | 用途 |
|---|---|
| `light/enable_als_sensor`, `light/als_poll_delay` | 光感采样开关与周期 |
| `proximity/enable_ps_sensor`, `proximity/ps_crosstalk` | 距离采样开关与串扰校准 |
| `accelerometer/{enable,delay,wake,mtp_recovery}` | 加速度计 |
| `geomagnetic`/`orientation`/`rotation_vector`/`linear_acceleration`/`gravity` 的 `{enable,delay,wake}` | 其余（含虚拟传感器） |
| `/dev/psals_sensor` | HAL 的 ioctl 通道（crosstalk） |

用数字 `1000:1004` 而不是 `system:input`：这个 ROM 里没有 `/etc/passwd` 和 `/etc/group`
（`debugfs` 查过，`/system/etc/` 下两个文件都不存在），toybox 的 `chown` 解析名字要查它们。
原厂那两个脚本用名字是因为它自己的 rootfs 里有这两份文件。

启动时机是刻意的：`post-fs-data` 在 zygote 之前，而五个 input 设备在内核 probe 阶段就
存在了，所以 HAL 构造时第一次读 `ps_crosstalk` 就已经是 system 的。

### 44.7 报告也跟着改了

| 改 | 为什么 |
|---|---|
| `input:` 后面加 `perm:`（`stat -c '%U:%G %a'`） | 这次的核心判据就是属主，一行看完 |
| 新增 `===== sensors =====`，`dumpsys sensorservice` 的 Sensor List 前 10 行 | display 只告诉你 ABC 拿到了哪个 sensor，不告诉你 handle；而 HAL 的 `activate()` 就是按 handle 分派的 |
| `===== mic =====` 删掉 | 麦克风好了 |
| `-- dmesg usb --`（25 行）删掉 | USB 那套 enable/pid/UDC 的舞蹈早就稳定了，上面五行就是它的结论 |
| 时间线 5×60 s → 6×30 s | fix80 的 dump 是开机后 134 秒抓的，只拿到两个采样点；改成 30 秒一次后，三分钟内就有 7 个点，随时可以抓 |

顺带说明自动亮度那一档为什么是 102：`mScreenBrightnessSetting=30`，但 auto 模式下
PMS 传下去的是 `BRIGHTNESS_DEFAULT`(-1)，`mScreenAutoBrightness=-1` 时 DPC 兜底用
`config_screenBrightnessSettingDefault`，也就是 102。lux 一来这个数就会自己变。

### 44.8 这一轮要看的

1. `perm:` 一行是不是 `system:input 660`（两个节点 + `/dev/psals_sensor`）。
2. `kcsensor:` 一行是不是 `nodes=11 als=yes ps=yes psals=yes`。
3. `===== sensors =====` 里 Light/Proximity 的 handle 是不是 5 / 8。
4. 时间线里 `mLightSensorEnabled=true` 且 `mAmbientLux` 从 0 变成非 0、`mScreenAutoBrightness`
   不再是 -1；遮住光感时 `leds: lcd=` 跟着变。
5. 距离：盖住听筒按电源键，`kclogcat.txt` 里应出现 `Not waking up. Proximity sensor is blocked.`；
   不想用可以在 设置→显示 里关掉（那是 CM 的 `proximity_on_wake`）。
6. 开机：`nuSensorService starting` 到 `thread starting` 应该从 24.5 s 掉到几秒。

## 45. 光感通了，但自动亮度还是不动：把时间常数改短

fix81 的 dump 说明了链条的前半段已经修好，也把后半段的问题放在了明面上。

### 45.1 这一轮确定成立的

```
perm:    system:input 660 system:input 660 system:system 600
input:   light=/sys/class/input/input6 en=1 poll=250000 | prox=.../input7 en=0
mLightSensorEnabled=true   mLightSensorEnableTime=53800
leds:    lcd=85
```

`enable_als_sensor` 终于是 1，`als_poll_delay` 是 HAL 写进去的 250 ms（不再是驱动默认值），
lux 也真的在动：`102 → 98 → 56 → 32 → 10 → 2 → 0 → 100 → 102`。§44 那个 chown 是对的，
`/dev/psals_sensor` 现在也是 `system:system 600`。

### 45.2 但屏幕亮度一次都没跟着动

三次采样（t+0 / t+30 / t+60）里，`mScreenBrightness` 和 `mScreenAutoBrightness` 一直是 **85**，
`leds: lcd=` 也是 85。85 本身说明 ABC 算过一次 —— `mScreenAutoBrightnessSpline` 在 lux=102
处就是 0.33 左右，`0.33 × 255 ≈ 85`；而 `mScreenBrightnessSetting=30`，如果自动亮度没生效，
面板应该是 30。所以"引擎"是转过的，只是**再没转过第二次**：

```
mAmbientLux=102.0            <- 冻在初始化那一次
mLastObservedLux=98.0        <- 但原始采样一直在更新
mAmbientLightRingBuffer=[102.0/490ms, 100.0/750ms, 96.0/260ms, 56.0/250ms,
                         32.0/250ms, 10.0/250ms, 2.0/750ms, ... 0.0/999ms, ...]
```

`mAmbientLux` 只在 `updateAmbientLux()` 里那个门被推开时才更新：

```java
if (ambientLux >= mBrighteningLuxThreshold && nextBrightenTransition <= time
        || ambientLux <= mDarkeningLuxThreshold && nextDarkenTransition <= time) {
    setAmbientLux(ambientLux);
    updateAutoBrightness(true);
}
```

门要同时满足两件事：加权后的 lux 落到 `mDarkeningLuxThreshold`（=102×0.8=**81.6**）以下，
**并且**窗口里连续低于阈值的样本已经存在 `mDarkeningLightDebounceConfig` 那么久。
两者的默认值（AOSP，这台机器上没设备 overlay，所以全是默认值）：

| 资源 | AOSP 默认 | 含义 |
|---|---|---|
| `config_autoBrightnessBrighteningLightDebounce` | 4000 ms | 变亮前要稳定多久 |
| `config_autoBrightnessDarkeningLightDebounce` | 8000 ms | 变暗前要稳定多久 |
| `config_autoBrightnessAmbientLightHorizon` | 10000 ms | 加权平均的时间窗 |
| `config_autoBrightnessLightSensorRate` | 250 ms | 期望的采样周期 |

这套常数是按"光感每 250 ms 无条件上报"设计的。而 sfh7776 的 HAL 只把**变化**上报给框架
（fix81 的 ring buffer 在 3.6 秒里只有两个点，`dumpsys sensorservice` 的 `last 10 events` 也只有一个），
于是"遮盖"这个动作只产生一个低值样本，加权平均要很久才压到 81.6 以下；再叠加 8 秒的
debounce，而窗口本身只有 10 秒 —— 门槛和窗口一样长，落到窗口边上就永远差一点点。

fix81 的 dump 恰好是在"刚遮上 5 秒"时取的（`mAmbientLightRingBuffer` 里那一串
`0→2→6→2→4→2→10→32→56→96→100→102` 是松手后回升的过程），所以那份日志没法区分
"只是慢" 和 "卡死"。两种情况用同一把刀都能切开：**把时间常数改短**。

### 45.3 fix82 改的三个整数

| 资源 | 原值 | 新值 |
|---|---|---|
| `config_autoBrightnessBrighteningLightDebounce` | 4000 | **1000** |
| `config_autoBrightnessDarkeningLightDebounce` | 8000 | **2000** |
| `config_autoBrightnessAmbientLightHorizon` | 10000 | **4000** |

改完以后：遮盖 2 秒左右开始压暗，松手 1 秒左右开始回亮，`lcd:` 从 85 落到 12（lux=0 落在
曲线第一个控制点上）。窗口 4 秒 / 采样 250 ms = 16 个样本，容量比例和 AOSP 原值一致，
不会碰到 `AmbientLightRingBuffer` 的容量边界。

依然是**原地改 `resources.arsc`**，不重编资源：这三个是 `<integer>`，和 bool 一样只是
`Res_value` 的 4 字节 `data`。`tools/image/arsc_patch.py` 为此加了 `--int`。

验证（和 fix79 同一套）：`aapt dump --values resources` 全表 9448 条 spec 逐行 diff 原厂
= **0 行**，stderr 空；三个整数回读 1000/2000/4000，bool 回读 0xffffffff，数组回读 10/11 项；
`jar verified.`；5563 个 STORED 条目全部 4 字节对齐，`resources.arsc` 仍是 Stored。

### 45.4 距离传感器：Settings 这一侧已经通了，PWM 这一侧要间接看

fix81 的 logcat 里有一行是这轮的收获：

```
D ConstraintsHelper: construct key=proximity_on_wake available=true
```

fix78 的时候是 `available=false`（那正是"设置里看不到这个开关"），现在是 true，说明
fix79 对 `org.cyanogenmod.platform-res.apk` 里那两个 bool 的补丁被 Settings 读到了。

PWM 在 `services.jar` 里，读的是同一个资源 id。全 dex 里 `0x3f050001` 只出现一次：

```
$ python3 -c "...find b'\x01\x00\x05\x3f'..."
0x3f050001 出现次数 1
0x3882a4 前4字节 d5401401 后4字节 ...
                    ^^ const v1, 0x3f050001
```

也就是说 PWM 用 `cyanogenmod.platform.R.bool.config_proximityCheckOnWake`（0x3f050001），
和我们补的是同一个值。补丁已经让它是 true，`...EnabledByDefault` 也是 true，所以
`proximity_on_wake` 这一行不存在时默认就是开。

但 PWM 自己不开 dump，`dumpsys window policy` 里没有 `mProximityWake*` 这几个字段
（fix81 的报告只打出了 `mAwake` / `mScreenOnEarly`）。所以这一轮换一个更硬的判据：
**SensorService 的连接表**。PWM 只要 armed，system_server（pid 1741 / uid 1000）就会一直
持有 proximity 这个 handle：

```
Sensors by connection:
Connection Number: 1 | Operating Mode: NORMAL
  Package: android | pid: 1741 | uid: 1000
  Active sensor list:
    0x00000000) SFH7776 Proximity Sensor     <- 有这一行 = PWM 挂上了
```

再加一个计数器：`proxwake: N x 'Not waking up'`。PWM 一旦因为传感器被挡而否决电源键，
就会在 logcat 打 `Not waking up. Proximity sensor is blocked.`，那是唯一的直接证据。

### 45.5 顺带修掉报告里的两个坑

| 问题 | 后果 | 现在 |
|---|---|---|
| `sed -n '/Sensor List/,+10p'` | toybox 的 sed 不认 `,+N` 区间，直接 `bad pattern`，fix81 的 `===== sensors =====` 整段是空的 | 换成 `awk '/Sensor List/{p=1;n=0} p&&n<11'` |
| `dispblock` 只挑十几个字段 | 恰好漏掉 `mRecentLightSamples`、两个阈值、两个 debounce —— 也就是唯一能回答"是滤镜还是传感器"的那几个 | 打印完整的 `Automatic Brightness Controller Configuration/State` 两段（46 行封顶，每行截 190 字符） |
| 时间线 6×30 s、总长 3 分钟 | fix81 的 dump 在 140 秒被取走，遮盖过程刚好落在采样之外 | 20×15 s、总长 5 分钟，末尾写 `===== timeline done =====` |

### 45.6 这一轮要看的

1. `Automatic Brightness Controller Configuration` 里那三个数是不是 1000 / 2000 / 4000。
2. 遮住光感 20 秒，中间任意一次采样：`mAmbientLux` 应该掉到个位数，`mDarkeningLuxThreshold`
   跟着一起掉，`mScreenAutoBrightness` 和 `leds: lcd=` 应该跟着变。
3. 如果 `mRecentLightSamples` 在涨、`mAmbientLux` 仍然不动 —— 那就是滤镜本身坏了，
   下一轮直接绕过它。
4. 距离：`Sensors by connection` 里有没有 `SFH7776 Proximity Sensor`；盖住听筒按电源键后
   `proxwake` 是不是从 0 变成 1。

## 46. 距离感应没生效，不是因为传感器坏，是因为电源键根本不查距离

fix82 报了两件事：自动亮度**通了**，距离感应**没通**。前者是对 §45 那三个时间常数的验收通过，
后者是本轮的全部工作量。

### 46.1 先说清楚：测量工具本身有两处瞎的

fix82 的 `===== sensors =====` 段是空的，`Sensors by connection` 也是空的。日志里明写着：

```
/vendor/bin/kcadsp.sh: awk: not found
/vendor/bin/kcadsp.sh: awk: not found
```

这套 toybox **没有编 awk applet**。§45.5 把 `sed '...+N'` 换成 awk，等于从一个不存在的坑跳进另一个
不存在的坑。于是「距离传感器现在什么状态」这个问题，在 fix82 的数据里**根本没被回答过**——
不是回答"没生效"，是没有数据。

第二处是 `dispblock()` 里抓 ABC 的那一半也是 awk 写的，所以自动亮度那次其实也没有细节，只是
结果对上了。

本轮把 kcadsp.sh 里的 awk 全部清掉，换成三个纯 shell 提取器：

| 函数 | 用途 | 停止条件 |
|---|---|---|
| `grab_from <file> <start> <stop> <maxlines>` | 取两个标记之间的块 | 遇到 `$stop` 或行数封顶 |
| `grab_after <file> <start> <n>` | 从标记往后 n 行 | 行数封顶 |
| `grab_ring <file> <header>` | 取一个 sensor 的完整环形缓冲 | **下一行是空行或含 `Sensor: last`** |

`grab_ring` 的停止条件第一版写的是「非缩进行」，实测把下一个 sensor 的第一条样本也吃进来了
（`[newest lux] -> 2.00` 其实是 prox 的值，两个环挨着）。改成按「下一个环的头 / 空行」判断才对，
因为下一个 ring 的头本身也是缩进的。

### 46.2 传感器是好的，这一点 fix82 的数据已经证明了

抛开空段，`input:` 那行和驱动的 debugfs 是能读到的：

```
input:  prox=/sys/class/input/input7 en=1 poll=...
SFH7776 Proximity Sensor: last 10 events
  ...
  4.00
```

`en=1`（`enable_ps_sensor` 的计数器非零，IRQ 真的开了），等级 4 = `ps_lv` 的无遮挡值
（驱动表 `{4,2,13,0}`，见 `drivers/sensors/sfh7776.c:141`）。所以硬件、驱动、HAL 三段都在线。

### 46.3 真因：`proximity_on_wake` 在 14.1 上管不到电源键

CM 的 `proximity_on_wake` 最终落到 `PowerManagerService.runWithProximityCheck()`。这个方法的
唯一入口是 `PowerManager.wakeUpWithProximityCheck()`，而 `services.jar`（本机是 boot.art 里的
预编译类）里**只有一个调用者**：

```
PhoneWindowManager.wakeUp(..., boolean withProximityCheck)
    -> wakeUpWithProximityCheck()     当 withProximityCheck == true
    -> wakeUp()                       否则
```

而 `withProximityCheck` 的实参是 `event.getKeyCode() == KeyEvent.KEYCODE_WAKEUP`。
**电源键不走这条路**：

```
PhoneWindowManager.interceptPowerKeyDown()
    -> wakeUpFromPowerKey(eventTime)
        -> wakeUp(eventTime, /*allowWakeUpByP*/ false, "powerKey")
```

dex 反汇编逐字确认，`wakeUpFromPowerKey` 方法体里只有一条
`invoke-direct ...->wakeUp(J Z Ljava/lang/String;)Z` —— 三参数那个重载，`withProximityCheck`
写死 false，`runWithProximityCheck` 从头到尾没被调用过。

**结论：`proximity_on_wake=1` 只对 `KEYCODE_WAKEUP` 生效——耳机线控、底座、某些蓝牙键盘上的
专用唤醒键。物理电源键在 AOSP/CM 里从来就不查距离。** 这是既有设计，不是本 port 的 bug，
也解释了为什么"盖住听筒按电源键屏幕照样亮"。

判定阈值顺带记一下，`PowerManagerService`：

```java
PROXIMITY_NEAR_THRESHOLD = 5.0f
// 不挡的条件：distance >= 5.0f || distance >= mProximitySensor.getMaximumRange()
```

也就是说驱动上报 0/1/2 算挡，3/4 算不挡。

### 46.4 为什么不能直接改 dex：这个 ROM 是 boot image only

`/system/framework/*.jar` 全是 **299 字节的桩**，真正的类预编译在 `boot.art` / `boot-*.oat` 里。
往 `services.jar` 塞一个新 dex 进去，等于让镜像里的 `services.jar` 和 boot.art 不一致，
ART 会拒绝加载或者静默走慢路径，而且**没有回退路径**（原 dex 不在 system 里，在 boot 里）。

所以补丁只能打在框架**之前**。

### 46.5 方案：在 evdev 层拦截电源键（kcprox）

新增 `/vendor/bin/kcprox`，一个静态 ARM 守护进程，`late_start` 起来：

```
屏幕亮着        -> 什么都不做（不抓、不开传感器）
屏幕灭了        -> ioctl(kfd, EVIOCGRAB, 1) 独占电源键节点，写 enable_ps_sensor=1
   KEY_POWER 按下，prox <= 2 且距离值 <10 s 内     -> 吞掉
   KEY_POWER 按下，其他情况                        -> uinput 注入一个 KEY_POWER，框架照常唤醒
```

几个刻意的选择：

| 设计 | 原因 |
|---|---|
| `EVIOCGRAB` 绑在 fd 上，不写任何持久状态 | 进程一死内核自动释放，电源键**不会变砖**。这是选 evdev 而不是改 keylayout 或 IPC 的唯一理由 |
| 只在屏幕灭时抓 | 亮屏时电源键要能正常熄屏/长按关机菜单，不能碰 |
| 屏幕状态用 `/sys/class/leds/lcd-backlight/brightness > 0` 判 | lights HAL 真的会写 0，比 `dumpsys power` 便宜一个数量级 |
| `KCPROX_MAX_SWALLOW 3`：连续吞 3 次后第 4 次必放行 | 万一读距离的那条路坏了、屏幕永远点不亮，用户连按四下就能出来 |
| `seen_on` 标志：从没见过亮屏就永不 arm | init 起得太早、backlight 还没初始化时不会误抓 |
| 注入前再读一次 `screen_is_on()` | 挡住的瞬间如果别的路径已经点亮了屏幕，不要重复注入 |
| `inject_power()` 失败就 `ioctl(EVIOCGRAB, 0)` 放开 | uinput 建不起来时宁可放弃拦截，也不能把键扣在自己手里 |
| uinput 完全建不起来 -> `system("/system/bin/input keyevent 26")` | 最后一道兜底 |

uinput 可用性已确认：`CONFIG_INPUT_UINPUT=y` 编进内核，`/dev/uinput` 是 10,223，devtmpfs 关着
所以代码里自己 mknod。该机电源键在 **`qpnp_pon`（event1）**，音量键在 `gpio-keys`（event11），
看 EventHub 日志确定的，所以默认抓 `qpnp_pon`。

`--dry` 的语义：仍然抓、仍然读、仍然注入，只是**不吞**，日志记 `would swallow`。
这样能先验证"距离读得对不对"而不影响正常用机。

### 46.6 顺带把距离变成可测的

fix82 之所以只能靠猜，是因为报告里没有一个地方能读到"遮挡时距离到底是多少"。这一轮加了：

- 每条采样多两行：`prox: newest=N (ts=...) V` 和 `lux: newest=...`，取各自 ring 的最后一条。
- `===== sensors =====` 段重写：`Sensor List` / `-- holders --`（`Sensors by connection`）/
  `-- prox ring --`（完整环）/ `-- light ring --` / `caps:`（`getevent -i` 里的 `ABS_DISTANCE` 值域）/
  `nodes:` / `psdrv:`（dmesg 里 6 条 `ABS_DISTANCE`）/ `-- kcprox --`（`init.svc.kcprox` + 日志尾巴）。
- 时间线里加 **evdev 旁路录制**：`timeout 400 getevent -lt <三个节点>`。evdev 是多读者模型，
  每个 fd 各拿一份完整事件流，**旁路录制不会抢走框架的事件**。末尾汇总 `===== input trace =====`：
  三个节点各自的 `KEY_POWER` down/up 计数、`ABS_DISTANCE` 计数、最近 40 条距离、最近 30 条电源键边沿。

这样"遮挡时距离值多少""按键有没有到达框架""框架有没有收到第二个注入的键"全部是可直接读的事实。

顺带修了个坑：`getevent $EVK $EVP $EVG` 里三个变量可能为空，toybox 的 getevent 会把空字符串
当设备名而**拒绝启动**，整段 trace 全空。改成 `set -- $EVK $EVP $EVG` 再 `"$@"`。

### 46.7 这一轮要看的

刷 fix83 后（只刷 system，boot 保持 fix72 那版 #25 内核）：

```sh
adb shell getprop init.svc.kcprox      # 应该是 running
adb shell cat /data/local/tmp/kcprox.log
```

日志应依次出现：

1. `kcprox: start` / `power key node = /dev/input/event1`
2. 熄屏后 `screen off -> armed`
3. 遮住听筒：`prox=1 -> covered`（N ≤ 2 即算遮挡）
4. 此时按电源键：`power: covered (prox=1) -> swallowed 1/3`，**屏幕应保持黑**
5. 松开手再按：`power: prox=4 -> injected`，屏幕正常点亮

如果第 4 步屏幕还是亮了，看 `===== input trace =====`：`qpnp_pon` 的 `KEY_POWER` 次数和
框架侧收到的是否一致，就能区分是"没吞掉"还是"吞掉了但又注入了一份"。

不想立刻改变行为的话，`kcprox --dry` 手动跑一遍，日志会出现 `would swallow` 而屏幕照常亮。

## 47. CI 每次都在最后一步红：这个构建一直在生成一个坏掉的开机动画

fix83 推上去之后 `Build LineageOS 14.1` 又红了。翻 run 记录才发现不是这一轮的事：

| commit | 结论 | 失败步骤 |
|---|---|---|
| 24d7efe4 (fix83) | failure | Verify the package |
| a0acf365 (fix82) | cancelled | — |
| ffa472e0 (fix81) | failure | Verify the package |
| 35544987 (fix80) | cancelled | — |
| 9d204d71 (fix79) | failure | Verify the package |
| 939c5cac | failure | Verify the package |
| ae6dd409 | failure | Verify the package |

**从 fix76 引入这个步骤起，一次都没通过过。** 而且每次都停在同一条上。

### 47.1 失败的那一条

日志尾部（`set -x`）：

```
+ unzip -p system/media/bootanimation.zip desc.txt
+ head -n 1
+ tr -d '\r'
+ grep -Eq '^[0-9]+ [0-9]+ [0-9]+$'
##[error]Process completed with exit code 1.
```

`unzip` 一句错都没报。这不是"文件不存在"——文件不存在时 Info-ZIP 会打
`cannot find or open`，而这版 unzip 在 `-p` 遇到不存在的成员时干脆什么都不输出，
所以两种情形在日志里长得一模一样。真正的原因要在构建日志里往前翻：

```
[ 92% 26585/28792] Building bootanimation
vendor/cm/bootanimation/generate-bootanimation.sh: line 10: [: : integer expression expected
[ 92% 26586/28792] build .../ETC/bootanimation.zip_intermediates/bootanimation.zip
[ 95% 27509/28792] Install: .../system/media/bootanimation.zip
```

文件确实装进去了。装进去的是**生成出来的**那个。

### 47.2 生成器的两行

`vendor/cm/bootanimation/Android.mk`：

```make
define build-bootanimation
    $(shell) vendor/cm/bootanimation/generate-bootanimation.sh \
    $(PRODUCT_OUT) $(TARGET_SCREEN_WIDTH) $(TARGET_SCREEN_HEIGHT) \
    $(TARGET_BOOTANIMATION_HALF_RES)
endef

ifeq ($(TARGET_BOOTANIMATION),)
    TARGET_BOOTANIMATION := $(TARGET_GENERATED_BOOTANIMATION)
endif

LOCAL_MODULE := bootanimation.zip
LOCAL_MODULE_PATH := $(TARGET_OUT)/media
$(LOCAL_BUILT_MODULE): $(TARGET_BOOTANIMATION)
	@cp $(TARGET_BOOTANIMATION) $@
```

而 `generate-bootanimation.sh`：

```sh
if [ "$HEIGHT" -lt "$WIDTH" ]; then      # line 10
...
echo "$IMAGESCALEWIDTH $IMAGESCALEHEIGHT" 60 > "$OUT/bootanimation/desc.txt"
```

这台设备的 mk 里 **`TARGET_SCREEN_WIDTH` / `TARGET_SCREEN_HEIGHT` / `TARGET_BOOTANIMATION`
一个都没有**。于是：

1. `[ "$HEIGHT" -lt "$WIDTH" ]` 两边都是空串 → `[: : integer expression expected`；
2. `IMAGESCALEWIDTH` 空 → desc.txt 第一行是 `"  60"`（两个空格加 60），不是三个数字；
3. bootanimation 的 `sscanf("%d %d %d")` 得到 1 个字段，`Animation::fps` 留 0，
   `movie()` 拿它做除数 → `eglInitialize` 之后约 90 ms `SIGFPE`。

**这就是 DEVICE_NOTES 23 里那个崩溃。** 当时把它记成"vendor 附带了一个占位动画"，
这个说法是错的：没有谁附带它，**每次构建都在 92% 的位置自己生成它**。

### 47.3 为什么 verify 一直红而设备一直能用

因为交付的 system.img 里那份 `bootanimation.zip` 是我们手工塞进去的（23,894 B，
540x960 的正确版本），不是 CI 产物的那份。CI 的包一直带着坏的动画，只是从没有人
去刷它——它连 artifact 都没上传过，因为 verify 先红了。

所以这一步**抓的是真 bug**，红了五次是对的。要修的是构建，不是判据。

### 47.4 步骤 10 那三行 cp 是死的

原来的 "Install the boot animation"：

```sh
src=device/kyocera/msm8926-common/prebuilt/media/bootanimation.zip
dst=vendor/lineage/prebuilt/bootanimation/bootanimation.zip
cp "$src" "$dst"
unzip -p "$dst" desc.txt | ... grep -Eq '^[0-9]+ [0-9]+ [0-9]+$'
```

**没有任何规则读 `$dst`。** `bootanimation.zip` 这个模块没有 `LOCAL_SRC_FILES`，
它要么 `cp $(TARGET_BOOTANIMATION)`，要么跑生成器。所以这三行 cp 只是把一个
正确的文件放到一个没人看的地方，然后**检查那个副本**——检查通过，产出的却是生成
器写的那个。这是最坏的一种测试：它测的不是要出货的东西。

### 47.5 改了三处

| 文件 | 改动 |
|---|---|
| `BoardConfigCommon.mk` | `TARGET_SCREEN_HEIGHT := 960` / `TARGET_SCREEN_WIDTH := 540`。不是为了好看：生成器把这两个直接喂给整数比较，空了就产出 `"  60"` |
| `lineage-common.mk` | `TARGET_BOOTANIMATION := $(LINEAGE_COMMON_PATH)/prebuilt/media/bootanimation.zip`。非空即跳过生成器，`cp` 原样安装 stock 4.4 那份 |
| `.github/workflows/lineage.yml` | 步骤 10 改名 `Check the boot animation`，删掉死的 cp，改为断言变量已定义、文件存在、desc.txt 首行三数字；verify 里先 `test -f` 再 `head -n 3 \| cat -A` 把内容打出来，最后才判 |

verify 的判据一个字没改——它本来就是对的。改的只是失败时能不能看懂：
`unzip -p` 对缺失成员静默，一个裸 `exit 1` 要花 90 分钟重新构建才知道为什么。

### 47.6 这一轮的教训

一个"检查通过"的绿灯，只有在它检查的是**出货的那份文件**时才有意义。
步骤 10 检查的是副本，verify 检查的是产物——两者矛盾了五次，而每次都是产物那边对。

## 48. fix83 验收：距离感应成立，顺手关掉这一轮的仪表

### 48.1 kcprox.log 逐项对照

fix83 刷入后的日志一共 67 行，每个设计点都在里面：

```
[53.517] start dry=0 key=/dev/input/event1 prox=/dev/input/event7
         proxctl=.../enable_ps_sensor uinput=1
[68.581] screen off -> armed (near=0, grabbed=1)
[70.754] prox=2 -> covered
[72.315] power: covered (age=1510ms) -> swallowed 1/3
[73.279] power: covered (age=2475ms) -> swallowed 2/3
[74.396] prox=4 -> clear
[74.578] power: clear -> wake (age=182ms, swallowed so far 2)
[75.100] screen on  -> released (swallowed=0)
```

| 设计点 | 证据 |
|---|---|
| 抓对了节点 | `key=/dev/input/event1` 是 qpnp_pon，不是 gpio-keys |
| uinput 可用 | `uinput=1`，EventHub 建出 `kcprox-vkeys`（event14） |
| 熄屏才 arm | 亮屏期间一行 `prox=` 都没有 |
| 遮挡判据 | 驱动 `ps_lv` 0/1/2 都进 covered，3/4 退出 |
| 吞键 | `swallowed 1/3`、`2/3`，屏幕保持黑 |
| 松手放行 | `prox=4 -> clear` 后按，`power: clear -> wake`，1 秒内亮屏 |
| 安全网 | `power: covered but limit reached -> wake`，第 4 次强制放行 |
| 计数器复位 | 每次 `screen on -> released` 后 `swallowed=0` |

用户实测"熄屏遮挡按电源键无法唤醒"，与日志一致。**这一项结案。**

### 48.2 但日志里有两个毛病

**一、每次读数都记一行。** 传感器按 HAL 的 poll 周期上报，手靠近听筒边缘时 0→2→3→4 来回跳：

```
[126.363] prox=2 -> covered
[126.466] prox=0 -> covered
[126.670] prox=1 -> covered
[126.676] prox=2 -> covered
[126.779] prox=3 -> clear
[126.983] prox=2 -> covered
[126.985] prox=4 -> clear
```

六行，信息量是"遮挡了一下"。67 行里这样的占一半，真正要看的那四行（swallow/wake）被埋掉。改成**只在 covered↔clear 翻转时写一行**，措辞也从 `prox=2 -> covered` 变成 `prox: covered (2)`。

**二、熄屏那一下的按键被当成了唤醒请求。**

```
[125.968] screen off -> armed (near=0, grabbed=1)
[125.968] power: clear -> wake (age=5011ms, swallowed so far 0)
[127.370] screen on  -> released (swallowed=0)
```

同一毫秒。原因在 evdev 的队列模型：**每个 fd 一条独立队列**，而 kcprox 从启动起就把电源键节点开着，只在 grab 窗口里读。于是亮屏期间按过的每一个键——包括刚把屏幕按灭的那一下——都还躺在缓冲区里。grab 之后第一次 poll 读到的就是它，距离值是旧的（age=5011ms），判 clear，注入，屏幕又亮了。

这个 bug 的表现是"偶尔按电源键熄屏，1 秒后自己亮回来"。129.183 那一次同样成立，只是那会儿盖着传感器，被吞掉了，所以没有可见后果。

修法：grab 成功后先把队列读空再进循环（fd 本来就是 O_NONBLOCK，`read` 到 EAGAIN 为止）。

### 48.3 这一轮的仪表可以拆了

**`kcadsp.sh` 里的 evdev 旁路录制从来没工作过。** fix83 的 dump 里 `/data/local/tmp/kc_input.log` 是 13 行 getevent 的 usage：

```
Usage: getevent [-t] [-n] [-s switchmask] ...
```

toybox 的 getevent 在 `-lt` 加显式设备路径时会打 usage 退出。上一轮写这段时以为"空变量会被当设备名"，用 `set --` 包了一层，但真正的问题不是空变量。整段连同 400 秒的后台进程一起删掉——它要回答的问题（遮挡时距离是多少）已经由每条采样的 `prox: newest=` 直接给出，数据来自驱动自己的 ring buffer，比旁路录制更可靠。

`sensors` 段保留 `Sensor List` / `-- holders --` / `-- prox ring --` / `caps:` / `nodes:` / `-- kcprox --`：这些都是只跑一次的快照，几行输出，以后回归时是第一手证据。

但 fix83 的 `kcaudio.txt` 说明这段里还有三个自己坏掉的地方，一起修：

| 现象 | 原因 | 现在 |
|---|---|---|
| `-- holders --` 空白 | 抓的是 `Sensors by connection`，那是 4.4 的标题；14.1 的 dumpsys 用 `Active sensors:` + `Previous Registrations:` | 改抓 `Active sensors:`，关键是那句 `0 active connections` |
| `caps:` 空白 | `getevent -i <path>` 和 `-lt` 一样打 usage，这台机器的 toybox 不认设备路径 | 改读 `/proc/bus/input/devices` 里 proximity 的 `B: ABS=` 能力位（0x10 = ABS_DISTANCE） |
| `prox: newest=SFH7776 Light Sensor (handle=...)` | `grab_ring` 的最后一个非空行撞上了下一段的标题，`tail -n 1` 取到的是标题不是样本 | 先 `grep -E '[0-9]+ \(ts='` 只留样本行再取最后一条 |

第二条同时也是 `kc_input.log` 只装着 usage 的真正原因——不是 `-lt` 的组合问题，是**任何显式设备路径**都会让它打 usage。上一轮把它归因于"空变量被当设备名"，判断错了。

修完之后这三行才第一次真的有内容。`-- prox ring --` 本身是好的，fix83 的 7 条读数（4,4,3,2,1,0,4）就是遮挡过程最直接的证据。

### 48.4 build.sh 里一个静默的路径 bug

`OUT=${OUT:-../lib}` 在第 49 行给两个 HAL 库用，第 88 行又写了一次 `OUT=${OUT:-../bin}` 给 kcprox。`${X:-default}` 在 X 已赋值时取 X，所以 kcprox 一直被构建到 **`../lib`**，而 `KC_BINS` 装的是 `../bin`。

出货的是 prebuilt，所以没有任何东西失败——`../bin/kcprox` 只是继续保留上一次构建的结果，`ls` 看着一切正常。本地改完代码重新构建、打包，拿到的是旧二进制。改成独立的 `BINDIR`。

### 48.5 CI 产物核对

两个 product 都 success，产物下载后逐层验过（kc01 走 GitHub artifact API 拿 SAS，分段并行过 gh-proxy）：

| 检查 | kc01 | kyl23 |
|---|---|---|
| artifact 大小 | 384,187,657 | 384,190,094 |
| SHA256 | 与日志 digest 一致 `92847bb2…` | — |
| OTA 结构 | boot.img / system.new.dat / system.transfer.list / file_contexts.bin | 同 |
| `system.new.dat` 块数 | 184,286（= transfer.list 的 new 合计） | 184,286 |
| `system.transfer.list` | v4，`cmd n,start,end,...` 成对 range，合计 359,418 块 = 分区大小 | 同 |
| `/vendor/bin/kcprox` | 0755，472,152 B，`a6338f8d…`（与 repo 一致） | 同 |
| `/vendor/bin/kcadsp.sh` | 0755，`1c5e7373…` | — |
| `/etc/init/kyl23-extra.rc` | 0644，`6d08d70d…` | 同 |
| `/media/bootanimation.zip` desc.txt | `540 960 1` | 同 |
| boot.img 内核 | 5,734,616 B，page 2048 | 同 |
| build.prop | `ro.product.model=KC-01`，7.1.2，lcd 240 | `miraie KYL23` |

`e2fsck -fn` 只有一条 `Padding at end of inode bitmap is not set`，这是 block-based OTA 还原的固有差异（未分配的位图尾部在安装时由 update_engine 补），不影响启动。

### 48.6 SELinux：现在还只是"permissive 下能跑"

logcat 里 kcprox 每做一件事都留一条 denied：

```
scontext=u:r:init:s0 tcontext=u:object_r:unlabeled:s0  { execute }
scontext=u:r:init:s0 tcontext=u:object_r:uhid_device:s0 { write ioctl }
scontext=u:r:init:s0 tcontext=u:object_r:input_device:s0 { ioctl }     <- EVIOCGRAB
scontext=u:r:init:s0 tcontext=u:object_r:shell_data_file:s0 { create append }
```

`permissive=1` 所以全部放行。它跑在 `init` 域（rc 里没写 seclabel），文件是 `unlabeled`（system.img 注入时没有 restorecon）。**一旦转 enforcing，`EVIOCGRAB` 会失败，kcprox 会退化成"抓不住键"**——而它抓不住时不会有害（不吞、不注入），只是距离感应又没了。

这是 §44 之后一直挂着的"剩余 15 个域"的一部分，修它要动 boot 里的 file_contexts，和重打 boot 一起做。


## 49. fix84：仪表收摊，顺手把闪光灯和 GPS 的两条断链找出来

这一轮不是修一个 bug，是回答三个问题：哪些诊断已经可以撤、闪光灯为什么不亮、GPS 为什么
看得见卫星却拿不到位置。前两个在代码里查到了底，第三个只剩下一个必须上机才能分辨的分叉。

### 49.1 诊断的账：哪些是哨兵，哪些是化石

判断标准只有一条——**它记录的问题还会不会回来**。会回来的留一行哨兵，不会回来的删掉。
按这个标准过一遍：

| 位置 | 记什么 | 结论 |
|---|---|---|
| `kcadsp.sh` summary | ADSP/USB/serial/声卡/日志存储/adsprpcd 各一行 | 留。每行一次系统调用 |
| `kcadsp.sh` subsys+boot | adsp/modem/wcnss 状态、`boot_adsp` 请求次数 | 留。ADSP 抢在 audioserver 前面起来这件事没有别的证据 |
| `kcadsp.sh` audio | cards / start-exit 计数 / 忙的 PCM / tinyalsa 指纹 | 留 4 行。声音已修，但这 4 行是唯一能一眼看出"又坏了"的地方 |
| `kcadsp.sh` sensors | Sensor List / holders / 两条 ring / caps / psdrv / kcprox 日志 | 留。一次快照，几行输出 |
| `kcadsp.sh` display | 每次采样 5 个 dumpsys（power、display、window policy、window、sensorservice），20 次 | **砍到 3 个 dumpsys × 4 次** |
| `kcadsp.sh` timeline | 5 分钟 20 次采样 | **砍到 1 分钟 4 次** |
| `kcstate.sh` | 408 行健康报告：按键背光/WiFi/audio/camera/baseband | **停用自启** |
| `kccam.sh` | 相机时间线 | 留。相机还没修 |
| `kctail.sh` / `kclogcat` | 高信号 logcat / 全量落盘 | 留。这是 dump 的原料 |
| `kcshut.sh` / `kchalt.sh` | 关机记录 / 关机执行 | 留。前者便宜，后者是功能 |
| `kcdiag` / `kcdiag2` | kcboot 的板级诊断，写 /cache/kc_diag.txt | 留。oneshot，一次几毫秒 |

两处真正动手砍掉的：

**`kcstate.sh` 停自启**。它每 150 秒跑一遍、跑 7 遍、持续 15 分钟，每遍都 `dmesg`、
`logcat -b radio`、拷 sqlite、抓相机日志。而它覆盖的五件事里三件已经修完（按键背光、
WiFi、音频），剩下相机有 `kccam.sh` 专线、基带有 summary 里的 RIL 状态。等于每开机一次
做七遍没人看的功课。脚本留着（`KC_BINS` 里还在），只是不再自己起来。

**`dispblock` 从 5 个 dumpsys 降到 3 个**。`dumpsys window` 和 `dumpsys window policy`
当初是为了看 `mProximitySensorEnabled` 和 PWM 的 `Not waking up`——距离感应在 fix83 之后
走的是 kcprox，这两条早就不再有信息量。自动亮度也一样：46 行 ABC block 换成 9 个关键字
段，足够看出 `mAmbientLux` 在动、`mScreenAutoBrightness` 在跟。采样从 20 次降到 4 次，
一次开机的 dumpsys 调用从 100 次降到 12 次。

省下来的位置给了两个新段：`gps` 和 `camera`（见下）。

### 49.2 闪光灯：两条点亮路径，两条都断了

`/sys/class/leds/torch-light/brightness` 是存在的，内核里注册它的是
`drivers/media/platform/msm/camera_v2/sensor/flash/msm_led_torch.c`：

```c
static struct led_classdev msm_torch_led = { .name = "torch-light", ... };
static void msm_led_torch_brightness_set(struct led_classdev *led_cdev,
                                         enum led_brightness value)
{ led_trigger_event(torch_trigger, value); }
```

也就是说这个节点是个纯粹的 `led_trigger_event`，写 0..255 就亮，不挑写入者。硬件和驱动
都没问题。断的是上面两层：

**第一层，自己的 lights HAL。** `lights7.c` 是 fix77 重写的，当时只搬了背光、按键、电池、
通知这四个，`open_light()` 的 if-else 链里没有 `flashlight` 这一支——框架
`LightsManager` 来要 `flashlight` 时直接拿到 -1，等于这个 ROM 里根本没有手电筒设备。
原厂 4.4 的 `kc_lights.default.so` 里那条 `torch-light` 路径是有的，重写时漏了。
fix84 补上：

```c
static int light_flashlight(...) {
    v = state_is_on(state) ? max_component(state->color) : 0;
    return write_int("/sys/class/leds/torch-light/brightness", v);
}
```

**第二层，快捷磁贴走的根本不是 lights。** 7.1 的 `FlashlightController` 用
`CameraManager.setTorchMode()`，也就是相机 HAL。而这个 ROM 的相机 HAL 从开机起就没加载
成功过，就在 logcat 第 590 行：

```
E HAL: load: module=/vendor/lib/hw/camera.msm8226.so
E HAL: dlopen failed: /system/vendor/lib/libmmcamera_faceproc.so: has text relocations
E CameraService: Could not load camera HAL module: -22 (Invalid argument)
```

bionic 从 5.0 起拒绝带 `DF_TEXTREL` 的 .so，`libmmcamera_faceproc.so` 是这套 blob 里
**唯一**一个带这个标志的库（`readelf -d` 扫过全部 40 多个）。而 `camera.msm8226.so` 对它的
依赖只是 `DT_NEEDED` 里的一行——把两个库的符号表对了一遍，camera 需要的 275 个未定义符号
里，faceproc 能提供的交集只有 `malloc`/`memcpy`/`sqrt` 这类 libc/libm 符号，**没有一个
是 faceproc 独有的**。也就是说这行依赖在链接上是空的，删掉不影响任何符号解析。

fix84 用 `patchelf --remove-needed libmmcamera_faceproc.so` 去掉了它。文件大小一字节没变，
段表偏移逐项相同，SONAME 不变，只有 `.dynamic` 里少一个 `DT_NEEDED`。

要诚实的地方：**这只能让 HAL 加载成功，不等于相机就好了**。4.4 的 `camera_module_t` 里没有
`set_torch_mode` 这个字段（它是 6.0 才加的），所以即使 HAL 起来了，7.1 的
`setTorchMode()` 也很可能返回 `INVALID_OPERATION`。快捷磁贴能不能亮，要刷上去才知道；
但 `LightsManager` 那条路（第三方手电筒 app、`service call lights`、Tasker）现在是通的。

### 49.3 GPS：卫星看得见，位置出不来——三种可能，先分清是哪一种

fix83 的 logcat 里 GPS 只出现在开机那一秒：

```
E LocSvc_eng   : W/set_server called before init. save the address, type: 3,
                 hostname: supl.google.com, port: 7275
E LocSvc_api_v02: I/locClientOpen:2189]: Service instance id is -1
E LocSvc_api_v02: I/---> locClientSendReq line 2333 QMI_LOC_REG_EVENTS_REQ_V02
E LocSvc_api_v02: I/---> locClientSupportMsgCheck line 2433 QMI_LOC_GET_SUPPORTED_MSGS_REQ_V02
```

`locClientOpen` 报 `Service instance id is -1`，但紧接着 `QMI_LOC_REG_EVENTS_REQ_V02` 和
`QMI_LOC_GET_SUPPORTED_MSGS_REQ_V02` 都发出去了。前者是第一个探测实例（`IzatApiV02` 问
batching 支持）失败，后者才是真正的客户端。**能报出卫星，说明这条 QMI LOC 链路是通的**——
SV 报告正是从这里上来的。

所以"有卫星、无位置"只剩三种解释：

1. **没有星历**。这是冷启动的正常状态：卫星信号能跟踪（CN0 有值），但解调一份星历要
   30 秒/颗、凑齐一套要 12.5 分钟，室内或窗边基本凑不齐。而这份 `gps.conf` 里
   `XTRA_SERVER_1/2/3` **全部被注释掉**，`NTP_SERVER=time.gpsonextra.net` 是早已停服的域名，
   `SUPL_HOST` 也是注释的（framework 侧倒是塞了 `supl.google.com:7275`，但那条路要网络
   定位 provider，而 `LocationManagerService` 开机就报 `no network location provider found`）。
   等于**没有任何一条能加速首次定位的通道**。
2. **QMI LOC 服务实例没 attach**。`-1` 如果出现在真正的客户端上，引擎就只能上报 SV、
   不能上报位置。
3. **GPS 周数翻转（WNRO）**。2019-04-06 之后，4.4 时代的 loc 引擎如果没有处理 10-bit 周数
   回绕，解算出的日期会错 19.6 年，星历有效期判断随之失效。很多 2013-2015 的高通设备
   在 2019 年之后彻底定不了位，就是这个原因，而且症状恰好是"看得见卫星、没有位置"。

这三条不能靠猜。`kcadsp.sh` 新增的 `gps` 段就是为此：`/dev/gss` 在不在、gps.conf 里
XTRA/SUPL 各几条、`dumpsys location` 的 provider 状态和最后位置、以及 logcat 里最近
18 条 `LocSvc`/`locClient`。测法是：打开任意 GPSTest/地图，等它列出卫星后**保持一分钟**，
再执行一次 `sh /vendor/bin/kcadsp.sh`（pidfile 在退出时删了，可以重跑），把新报告带回来。

如果日志里出现 `LOC_EVENT_POSITION_REPORT` 却没有 `GnssLocationProvider` 的
`locationReceived`，那是第 3 类里的上报问题；如果连 position report 都没有，就是第 1 或
第 2 类，看 `locClientOpen` 的实例号就能分开。

### 49.4 重打 boot：路已经探通，但没有这一轮出货

转 enforcing 要在 ramdisk 的 `sepolicy` 里补域，而那份文件是编译好的二进制（310,272 B，
1154 个 type、13,874 条规则、63 个 class）。这一轮把工具链跑通了：

```
checkpolicy -b -C -M -o pol.cil sepolicy     # 二进制 -> CIL，1.2 MB
secilc -m -M true -c 30 -o pol.new pol.cil   # CIL -> 二进制
```

往返之后规则数**一条不少（13,874）**，只有 3 个 `typeattributeset` 被剪掉
（`data_file_type`、`qti_debugfs_domain`、`rmt_placeholder`）——这三个属性没有被任何 allow
规则引用，属于死代码。也就是说 `checkpolicy`/`secilc` 这条链可以作为补域的手段。

但这一轮不出 boot 包，原因是顺序问题：**先补域、再逐个 enforcing**，而不是一次把
`androidboot.selinux` 改成 enforcing。补域本身要动三样东西（`sepolicy` 加
`kcprox`/`qmuxd`/`adsprpcd` 等域、`file_contexts.bin` 给 `/vendor/bin/*` 打标签、
rc 里给每个 service 写 `seclabel`），而 `file_contexts.bin` 是二进制格式，反编译比
sepolicy 麻烦一档——AOSP 的 `sefcontext_compile` 只负责文本到二进制，没有反向工具。
这一步单独做一轮，做完仍保持 permissive，确认没有回归之后再谈 enforcing。

### 49.5 fix84 交付

只刷 system，boot 保持 fix72 的 #25 内核。镜像里换了五个文件：

| 路径 | 变化 |
|---|---|
| `/vendor/lib/hw/lights.default.so` | 新增 `flashlight` 分支 -> `torch-light` |
| `/vendor/lib/hw/camera.msm8226.so` | 去掉 `DT_NEEDED libmmcamera_faceproc.so` |
| `/vendor/bin/kcprox` | 重新构建（源码未变） |
| `/vendor/bin/kcadsp.sh` | 砍采样、加 `gps`/`camera` 段 |
| `/etc/init/kyl23-extra.rc` | 停用 `kcstate` 自启 |

看三件事：`grep -c flashlight /vendor/lib/hw/lights.default.so` 至少为 1；
logcat 里 `Could not load camera HAL module` 消失；`dumpsys location` 的 gps 段有内容。
