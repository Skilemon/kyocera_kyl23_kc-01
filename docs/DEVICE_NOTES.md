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

## 28. 声音（三）：fix67 的内核根本没刷进去；而 ADSP 一起来声音就没问题

fix67 把触发搬进了内核、把 `kcadsp` 改成观察者。这份 dump 说明两件事：
**那版内核不在设备上**，而**只要 ADSP 在 audioserver 之前起来，音频栈就是好的**。

### 28.1 三次开机，没有一次是 #24

`21_log.img` 里三个 `Linux version`（新的在前，环形缓冲回卷后低偏移是最新的）：

| 段 | 内核 | 构建机 | 最长 uptime | pil_boot | audioserver 退出 | adsprpcd |
|---|---|---|---|---|---|---|
| s0 | `#23 Mon Nov 16 13:40:03` | `root@8ded1cdd5b47` | 509 s | **无** | **32 次** | 255 |
| s1 | `#23 Mon Nov 16 13:40:03` | `root@8ded1cdd5b47` | 160 s | **有** | **0 次** | 常驻 |
| s2 | `#22 Mon Nov 16 00:15:43` | `root@ad17b0cbe76d` | 639 s | 无 | 30 次 | 255 |

`boot-fix67.img` 里确实是 `#24 … 18:26:20`（解 gzip 验过），但设备上三个 session 一个
`#24` 都没有。**boot 分区没写进去**，所以 `0003` 那个内核重试一次也没跑过——s0 里连
`adsp-loader:` 这一行都不存在，`loading from` 也没有。

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

### 28.6 刷完先确认这两行

```
adb shell cat /proc/version            # 必须是 #25 SMP PREEMPT ... 19:12:22
grep -a "KCADSP start" 21_log.img      # kernel=#25 expect=#25
```

boot 没写进去的表现是：`/proc/version` 还是 `#23`，dump 里没有 `adsp-loader:` 行，
`KCADSP start` 那行 `kernel=#23`。这种情况下先按 `docs/FLASHING.md` 清写保护再写，
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
