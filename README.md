# Kyocera KC-01 / miraie KYL23 — TWRP 设备树

京瓷 msm8926 机型的 TWRP / ROM 设备树。当前目标：**为 KYL23 构建可用的 TWRP recovery**，之后在同一套设备树上扩展 LineageOS。

- 机型：KC-01（KYV36）、miraie KYL23
- SoC：Qualcomm MSM8926（msm8226 平台，四核 Krait，Adreno 305）
- 屏幕：720×1280
- 出厂系统：Android 4.4.4，内核 Linux 3.4
- recovery 分区：16 MiB

---

## 仓库结构

```
.github/workflows/
└── twrp.yml                  手动触发 → 产 twrp-<device>.img

device/kyocera/
├── msm8926-common/          两台机器共享的部分
│   ├── BoardConfigCommon.mk   平台、内核参数、分区尺寸
│   ├── msm8926-common.mk      公共 product 片段 + TWRP 标志
│   ├── Android.mk             把预置 QCDT blob 放到 $(PRODUCT_OUT)/dt.img
│   ├── mkqcdt.py              写 QCDT（工具，不参与最终镜像生成）
│   ├── qcdt-keys.txt          QCDT 表项键值（原厂原样，40 组）
│   ├── recovery.fstab         取自原厂 recovery 的真实 fstab
│   └── prebuilt/
│       ├── kernel             自编译的京瓷 3.4.0 recovery 内核（真机验证过）
│       ├── kc_wp.ko           写保护清除模块（开机 4s 自清，见下）
│       ├── dtb/msm8926-mtp.dtb  单份 DTB（供 mkqcdt.py 使用）
│       ├── stock/
│       │   ├── ramdisk.gz       原厂 recovery 的 ramdisk（提供 4.4.4 init 体系）
│       │   ├── dtb-kyl23.img    原厂 QCDT blob（1,290,240 B，40 条表项）
│       │   └── kernel-stock.kyl23  原厂 zImage（存档，对照组）
│       └── twres/              界面覆盖层：只做中文本地化
│           ├── languages/zh_CN.xml         简体中文（manifest 默认不带）
│           └── fonts/DroidSansFallback.ttf 中文字形（zh_CN.xml 的 fontoverride 指它）
├── kc01/                    KC-01 专属
└── kyl23/                   KYL23 专属

kernel-overlay/             叠加到上游内核树上的京瓷驱动与配置（编译内核时用）
kernel-patches/             让京瓷 3.4.0 用 gcc13 编过的补丁

tools/                      按「跑在哪一侧」分组，详见 tools/README.md
├── image/                  组装镜像、体检镜像（纯离线，python3 即可）
├── kernel/                 内核模块：源码、编译、符号修补
├── device/                 真机操作：DL 模式通道、分区备份/写回
└── flash/                  在 TWRP 里跑的小脚本（推 /sdcard 后 sh）

docs/
├── DEVICE_NOTES.md         实测数据与踩过的坑
├── FLASHING.md             刷机流程（必读）
├── FLASH_SYSTEM.md         换系统：备份 → 写 system → 清 data
└── KEYCOMBO_TEST.md        按键组合的可观测测法
```

## 内核：自编译的京瓷 3.4.0

`prebuilt/kernel` 是从**京瓷公开的 GPL 3.4.0 源码**编出来的（CAF
`LNX.LA.3.5.1-06610-8x26.0`，基线 `a472d41`），不是原厂 zImage。换掉原厂内核的理由很具体：
京瓷在里面加了一个自定义 LSM 钩子 `selinux_kernel_setup_load_info`
（`security/selinux/hooks.c`），它拒绝 init 加载任何非 wlan 模块——连清 eMMC 写保护的
`kc_wp.ko` 都进不来。补丁把它改成 `mov r0,#0; bx lr`，同时把 release 压回严格的
`3.4.0`（`CONFIG_LOCALVERSION=""`、`LOCALVERSION_AUTO=n`、无 `.scmversion`），
这样预编译模块的 vermagic 才对得上。56 个文件的 gcc 13 适配补丁、以及两个
`get_user`/`put_user` 的坑，都记在 [`kernel-patches/README.md`](kernel-patches/README.md)。

构建**不编译内核**，直接用这份 `prebuilt/kernel`，CI 因此只需 30–60 分钟。

原厂内核没有丢，存档在 `prebuilt/stock/kernel-stock.kyl23`
（5,808,608 B，md5 `40aada0058c8b0aadd00f5a5bc75166a`）。要回滚原厂内核，把 `--kernel`
指向它即可；它配合 `stock/ramdisk.gz` 就是一份完整可刷的组合。

要改内核（后期 ROM 阶段）时把 `KYOCERA_BUILD_KERNEL=true` 传进去：

```bash
export KYOCERA_BUILD_KERNEL=true
```

此时会克隆 [LineageOS `android_kernel_motorola_msm8226`](https://github.com/LineageOS/android_kernel_motorola_msm8226)（cm-14.1，Linux 3.4.113），把 `kernel-overlay/` 覆盖上去，用 `msm8926-kyocera_defconfig` 编译。**这条路径尚未验证过能否启动**，见 `docs/DEVICE_NOTES.md`。

仓库里曾经有一份 480 MB 的内核树，构建时被 `rm -rf` 后重新克隆，从未被使用，已删除。

---

## 为什么需要 `mkhybrid.py`

`mka recoveryimage` 产出的 `recovery.img` **不能直接刷**。这台机器跑的是 Kyocera 定制的 Linux 3.4.0，init 是 Android 4.4.4 那一代；TWRP 7.1 的 init 在它上面建不起属性区：

```
init: selinux_android_file_context_handle: Error getting file context handle
SELinux: Context u:object_r:properties_serial:s0 is not valid (left unmapped)
init: Failed to initialize property area
Kernel panic - not syncing: Attempted to kill init! exitcode=0x00000100
```

`/dev/__properties__` 在 4.4 是单个文件，从 7.0 起变成按 SELinux 上下文拆分的目录，还需要一个 `properties_serial`。这个断层没法在 ramdisk 层面补。

所以做法是反过来：**保留原厂 4.4.4 的 init / ueventd / healthd / adbd / sepolicy（这套在真机上确认能启动），把 TWRP 的 `/sbin` 载荷装进去**。原厂 `init.rc` 里本来就有 `service recovery /sbin/recovery`，init 会替我们 exec TWRP。

`tools/image/mkhybrid.py` 就是把这套合并固化下来，过程中必须遵守四条规则，每一条都是真机试出来的：

| 规则 | 不遵守的后果 |
|---|---|
| ramdisk 必须 gzip，不能 LZMA | 这内核没编 `CONFIG_RD_LZMA`，解压失败 → 空 rootfs → 秒级复位 |
| `/sbin` 整棵子树 0755/0777 | busybox 动态链接 `/sbin/linker`，权限 0750 时 `adb shell` 报 `Permission denied (13)` |
| QCDT 必须用原厂那 40 条（8 份 DTB） | 合并成 1 份 → aboot 给内核一份别的板子的 DT → 亮 logo 后 3 秒重启 |
| `init.rc` 里要有 `sys.usb.config` 的触发段 | TWRP 界面显示「MTP 已启用」，电脑上只有 adb（见 `docs/DEVICE_NOTES.md` 9） |
| 电脑上不能留着这个 VID 的旧设备记录 | 设备能枚举成 `18D1:4EE2`，但 Windows 把旧记录的网卡类设置硬套过来，MTP 驱动装不上（见 §9.5） |

---

## 构建

在 GitHub Actions 里手动触发 `Build TWRP`：

- `device`：`all`（默认，一次出两台）、`kyl23` 或 `kc01`
- `build_kernel`：`false`（默认，用 prebuilt 内核）或 `true`（从源码编译）

`all` 会展开成两个并行的 job（`plan` → matrix），各出一份镜像，互不影响：一台编译失败不会连累另一台，日志和 artifact 也是分开的。用原厂内核时单台约 **10 分钟**，两台并行总耗时仍是约 10 分钟（runner 分钟数翻倍）。产物是 artifact `twrp-kyl23` / `twrp-kc01`，各含一个同名的 `.img`。

> 两个代号现在共用 `msm8926-common/prebuilt` 下的**同一份**原厂内核、ramdisk 和 QCDT blob，所以两份镜像除了 `ro.product.device`、型号串和 `TW_DEVICE_VERSION` 之外完全一致。如果 KYL23 是另一批次的硬件（2016 的 201.x 版本），要让它同样能开机，得把那一台的 `recovery.img` 解出来的 kernel/ramdisk 放进它自己的 `prebuilt/`，见 `docs/DEVICE_NOTES.md`。

CI 的顺序是：`mka recoveryimage` 得到 `out/.../recovery/root`，然后 `tools/image/mkhybrid.py` 用它组装最终镜像，最后 `tools/image/check_image.py` 把关。以下任一情况都会让 CI **直接失败**而不是上传：

| 检查 | 不通过时的后果 |
|---|---|
| QCDT 表项里 `msm_id` 全为 0 | 刷进去卡开机 logo |
| QCDT 表项不是 24 字节 | 同上 |
| QCDT 里本机键没指向 `0xec800` | 亮 logo 后 3 秒重启 |
| 镜像超过 16 MiB | dd 静默截断 |
| ramdisk 缺失、过小，或不是 gzip | 进不了 TWRP |
| `/sbin` 或 busybox 不可执行 | adb shell 用不了 |
| `zh_CN.xml` 引用的字体没打进 ramdisk | 界面全是方块 |
| `init.rc` 缺 `/system` 挂载或 `sys.usb.config` 段 | 挂不上 System / MTP 用不了 |

### 语言

构建出来默认带 19 种语言、没有中日韩。组装时用 `--languages en,zh_CN` 只保留英文和简体中文，
再用 `--twres-overlay` 把 `prebuilt/twres/` 里的 `zh_CN.xml` 和 `DroidSansFallback.ttf` 盖进
`twres/`。中文切换在 TWRP 的 **Settings → Language** 里，首次启动仍是英文。

字体不能省：`RobotoCondensed-Regular.ttf` 没有中文字形，只加 `zh_CN.xml` 会显示成方块。
整套中文占掉 3.7 MB（字体）+ 45 KB（语言文件），删掉其余 18 种语言省回 860 KB，
镜像余量从 2.84 MB 降到 1.22 MB。要加别的语言，把对应的 `.xml` 放进 `prebuilt/twres/languages/`
并加进 `--languages` 即可；`mkhybrid.py` 会检查它引用的字体在不在。

`.github/workflows/twrp.yml` 用的就是同一套参数（`--languages en,zh_CN --single-font`，
检查时带 `--max-fonts 1`），所以云端出的镜像和本地出的一致。

加上 `--single-font` 就只留 `DroidSansFallback.ttf` 一套：它覆盖全部 ASCII 和 20,902/20,992
个汉字，另两套（`RobotoCondensed` 125 KB + `DroidSansMono` 108 KB）在字形上没有增量，
只在排版上有——拉丁字符平均宽 12%、行高多 11.7%、`fixed` 不再等宽。省 162 KB 压缩后空间，
代价是英文界面略微变挤、终端日志对不齐。取舍见 `docs/DEVICE_NOTES.md` 13.8。

---

## 本地构建

```bash
repo init -u https://github.com/minimal-manifest-twrp/platform_manifest_twrp_omni.git -b twrp-7.1
repo sync -c -j8
cp -r <this-repo>/device/kyocera device/

source build/envsetup.sh
lunch omni_kyl23-eng
mka recoveryimage

# 关键的一步：把载荷装进原厂 ramdisk
D=<this-repo>/device/kyocera/msm8926-common/prebuilt
python3 <this-repo>/tools/image/mkhybrid.py \
    --kernel    "$D/kernel" \
    --ramdisk   "$D/stock/ramdisk.gz" \
    --dt        "$D/stock/dtb-kyl23.img" \
    --twrp-root out/target/product/kyl23/recovery/root \
    --twres-overlay "$D/twres" \
    --languages en,zh_CN \
    --single-font \
    --module    "$D/kc_wp.ko" \
    --out       twrp-kyl23.img

python3 <this-repo>/tools/image/check_image.py twrp-kyl23.img \
    --max-size 16777216 --max-fonts 1 --require-module kc_wp.ko
```

`--kernel` 指向的 `prebuilt/kernel` 是**从京瓷 3.4.0 源码自编译**的 zImage，
不是原厂那份。换掉它是因为原厂内核里有个私有 LSM 钩子
（`selinux_kernel_setup_load_info`）拒绝 init 加载任何非 wlan 模块，连
`kc_wp.ko` 都进不来。源码补丁和重编方法见
[kernel-patches/README.md](kernel-patches/README.md)。

**但写保护不在内核里。** 实测换内核后 `dd` 写 `mmcblk0p12` 依旧"报成功、回读没变"：
保护做在 eMMC 卡级的 WP group 上，aboot 每次上电用 CMD28 置上，只有 CMD29 能解。

原厂 `mmc_protect.ko` 走不通：它把 `start_sect << 9`（字节地址）当 CMD29 参数，
而 JEDEC 规定容量超过 2 GB 的卡改用扇区寻址，于是命令打偏 512 倍——实测
`CMD31 arg=0x05f00000` 直接 `-110 / OUT_OF_RANGE`，而它的 `clear` 还是报成功。
**所以这个模块已经从镜像里彻底删掉**（`insmod` 行和 `sbin/mmc_protect.ko` 都不再有），
留着只会误导手动排查。改用自编的 `kc_wp.ko`：偏移由 `bd_part->start_sect` 直接取，按 512 扇区
（256KB）步长扫整个分区——比任何 eMMC 的 WP 组都小，保证组起点必被踩到——
再两套地址口径各做一次 CMD31 复查。

**清除动作由模块自己发起**，不再靠 `init.rc` 的 `exec`：`insmod` 之后 4 秒在
workqueue 里干活，`/dev/block/mmcblk0p12` 还没出现就每 500ms 重试，最多 15 次。
原因是 `exec` 路线有两个躲不开的坑：`/dev` 节点由 ueventd 在 `class_start`
之后才建，时序不定；`/tmp` 又会被 TWRP 启动时重挂成新的 tmpfs，init 阶段写的
日志直接消失（`/tmp/wp_fix.log` 一直"找不到"就是这么来的）。现在所有输出只走
`dmesg`，重启后也能从 `last_kmsg` 里查到：

```
    insmod /sbin/kc_wp.ko        # 4s 后自动清 p12 / p11，日志进 kmsg
    class_start default
```

参数可覆盖：`insmod kc_wp.ko parts="mmcblk0p12 mmcblk0p11" delay=4000 retry=15
autofix=0`。镜像里**不带** `wp_fix.sh`（CI 只注入 `kc_wp.ko`）；要手动补一刀，先
`adb push tools/flash/wp_fix.sh /sdcard/`，再在 TWRP 里 `sh /sdcard/wp_fix.sh`，
或者干脆 `echo "autofix mmcblk0p12" > /sys/kernel/kc_wp/run`。

排查「进 recovery 后卡死被看门狗复位」时，加上 `--boot-trace`：它会在挂 `/system` 前后各往 `/cache` 写一份 dmesg，硬复位不丢。见 [docs/DEVICE_NOTES.md](docs/DEVICE_NOTES.md) 第 8 节。

**物理键进不了 recovery，这不是手法问题。** 拆开 `aboot.img` 确认：fastboot 命令表整块没被链接进来，按键分支也是死的，三键只会进安全模式。能用的只有 `adb reboot recovery`，以及往 misc 写 `boot-recovery`（系统还能起来一次时的兜底）。证据链和判定表见 [docs/DEVICE_NOTES.md](docs/DEVICE_NOTES.md) 第 10 节。

```bash
python3 <this-repo>/tools/image/mkhybrid.py ... --boot-trace --out twrp-kyl23-trace.img
```

`dt.img` 由 `device/kyocera/msm8926-common/Android.mk` 从 `prebuilt/stock/dtb-kyl23.img` 复制而来，不需要 `dtbToolCM`，也不要用 `mkqcdt.py` 重新生成——那会把 40 条表塌成 1 份 DTB。默认不碰内核；要自己编内核时加上：

```bash
export KYOCERA_BUILD_KERNEL=true
git clone --depth 1 -b cm-14.1 https://github.com/LineageOS/android_kernel_motorola_msm8226.git kernel/kyocera/kyl23
cp -r <this-repo>/kernel-overlay/. kernel/kyocera/kyl23/

# 编完后把内核传给 mkhybrid
python3 <this-repo>/tools/image/mkhybrid.py ... \
    --kernel out/target/product/kyl23/obj/KERNEL_OBJ/arch/arm/boot/zImage
```

---

## 刷入

**不要直接 `dd`。** 这台机器的 boot / recovery 分区有硬件写保护，`dd` 会报告成功但数据全部被丢弃，重启后依然是从前的镜像。完整流程见 [docs/FLASHING.md](docs/FLASHING.md)。

---

## 已知限制

- **内核只允许 init 进程挂载 `/system`**。`selinux_mount()` 里有一段京瓷自加的判断，命中时直接 `return -EPERM`，位置在 `avc_has_perm()` 之前，所以 `androidboot.selinux=permissive` 对它无效。表现为 TWRP 的 Mount 页勾不上 System，日志里是 `no permission mount /system/... by non-init process`。当前绕过方式：`init.rc` 的 `on boot` 段由 init 自己挂（`mkhybrid.py` 已内置）。副作用是**不能在 TWRP 里卸载 System 后重新挂载**，卸载后只能重启恢复。
- `lineage_*` 目标只是占位，缺少 vendor blobs 与 msm8926 通用设备树，**不能直接出 ROM**。
- KC-01 与 KYL23 的硬件差异目前只确认了一部分（见 `docs/DEVICE_NOTES.md` 的「待验证」一节），common 层只放已实测的内容。
- TWRP 的加密支持（`TW_INCLUDE_CRYPTO`）默认关闭，原厂 userdata 走 `encryptable=/persist/udf` 的旧 qseecom 路径，需要单独验证。
- 原厂 adbd 是 4.4 的，编译时关掉了 `ALLOW_ADBD_ROOT`，`adb root` 不起作用，`adb shell` 固定是 uid 2000，**不能 `dd` 分区**。要 root 操作请用 TWRP 自带的 Terminal。
- 同理，`/cache` 的根 inode 是 `0770 system:cache`，**uid 2000 连 `ls /cache` 都不行**（`Permission denied`）。这不是坏掉，读 `/cache/recovery` 下的东西请用 TWRP 的 Terminal，见 `docs/DEVICE_NOTES.md` 8.1。
- **`/system/bin` 下的 4.4 程序在 TWRP 里直接跑会链接失败**（`cannot locate symbol "android_get_application_target_sdk_version"`）。TWRP 的 `recovery`/`busybox` 没有 RPATH，只能靠 `LD_LIBRARY_PATH=/sbin` 找自己的 bionic，而原厂程序因此被劫持到 7.1 的 `libc.so`。`adb shell` 和 `/system/bin/sh` 已经在 `mkhybrid.py` 里单独处理掉了（改 adbd 的写死路径 + 挂载后 bind mount），其余程序要先 `unset LD_LIBRARY_PATH`，详见 `docs/DEVICE_NOTES.md` 7.5。

- **系统彻底起不来时，救砖靠 DL 模式（SBL1），不是靠按键。** 这台机器在 aboot 之前会停在京瓷自己的下载模式（USB `0482:xxxx` + Sahara 握手），可以 `0xA3` 读、`0xA1` 写，**这个阶段写保护还没被 aboot 置上**，因此能直接写回 system / boot / recovery。工具是 `tools/device/serial_restore.py`，前提是先把全分区备份拿出来。见 `docs/DEVICE_NOTES.md` 第 12 节。
  刷之前先跑 `serial_restore.py COM13 --part recovery --wp-test`：它只读一扇区、原样写回、再读一遍，数据不变，但能立刻分清「写保护没清（`0x55`）」和「包太大（`0x54`）」。单包上限是固件里的 `0x1000`（4096 B），不是可以随便试出来的值，见 §12.7。
- **`lookup_bdev()` 不会打开设备。** 它只做 `bd_acquire()`，返回的 `bdev` 上 `bd_part`、`bd_contains` 全是 `NULL`。要分区表信息或上溯整盘，必须 `blkdev_get_by_path(path, FMODE_READ, NULL)`，用完 `blkdev_put()`。`kc_wp.ko` 第一版就是栽在这——报 `no gendisk/driverfs_dev` 之后 `autofix` 又"拿不到分区信息"，两处同一个原因。
- **分区盘的 gendisk 没有 `driverfs_dev`。** `mmcblk0pN` 由 `add_partition()` 建立，`block/partition-generic.c` 不设这个字段（`alloc_disk_node` 清成 NULL），只有整盘 `mmcblk0` 才 `driverfs_dev = &card->dev`。拿 `mmc_card` 要沿 `bd_contains` 上溯一层。
- **写保护在 eMMC 卡上，不在内核里，换内核去不掉。** aboot 每次上电用 CMD28 置 WP group，`dd` 于是"报成功、回读没变"。镜像用 `kc_wp.ko` 发 CMD29（偏移取 `bd_part->start_sect`，字节/扇区两种口径都扫），由模块在 `insmod` 后 4 秒自动跑一遍（`dmesg | grep kc_wp` 看结果，不写 `/tmp`）；手动兜底 `adb push tools/flash/wp_fix.sh /sdcard/` 后在 TWRP 里 `sh /sdcard/wp_fix.sh`，或直接 `echo "autofix mmcblk0p12" > /sys/kernel/kc_wp/run`；要看 EXT_CSD 就 `echo info > /sys/kernel/kc_wp/run`。原厂 `mmc_protect.ko` 已从镜像移除（地址单位算错，`clear` 报成功但无效）。见 `docs/DEVICE_NOTES.md` §12.6。
- **物理键和 fastboot 都进不去 recovery**。`aboot` 里 fastboot 命令表整块未被链接，按键分支也是死的：三键（音量上+下+电源）只会触发 Android 的安全模式，音量上/下+电源只是震两下然后正常启动。唯一入口是 `adb reboot recovery`，系统半死时用 misc 的 BCB 命令 `boot-recovery`。系统彻底起不来就只剩 EDL 短接，见 `docs/DEVICE_NOTES.md` 第 10 节。

## 参考

- 上游内核：[LineageOS/android_kernel_motorola_msm8226](https://github.com/LineageOS/android_kernel_motorola_msm8226)
- 移植母本：`device/motorola/thea`（同代 msm8226 机型）
- 最小 TWRP 清单：[minimal-manifest-twrp](https://github.com/minimal-manifest-twrp/platform_manifest_twrp_omni)
