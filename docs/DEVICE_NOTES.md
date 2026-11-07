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
| boot | mmcblk0p11 | 16 MiB | 内核（有写保护） |
| recovery | mmcblk0p12 | 16 MiB | recovery（有写保护） |
| system | mmcblk0p19 | 1,404 MiB | 系统 |
| userdata | mmcblk0p20 | 5,093 MiB | 数据 |
| cache | mmcblk0p21 | 458 MiB | 缓存（无保护） |
| log | mmcblk0p22 | 20 MiB | **Kyocera ram console，最近一次启动的完整 dmesg** |
| logwork | mmcblk0p23 | 20 MiB | 上一条的备份槽 |
| misc | mmcblk0p26 | 6 MiB | BCB |
| DDR | mmcblk0p27 | 1 MiB | 太小，装不下内存转储 |
| persist | mmcblk0p28 | 8 MiB | 单机校准 |
| carrier | mmcblk0p32 | 8 MiB | 运营商配置 |
| sysprop | mmcblk0p37 | 8 MiB | 系统属性分区 |

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
