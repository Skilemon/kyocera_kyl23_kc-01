# tools/

按「跑在哪一侧」分组，不是按语言分。每个目录都能独立拿出来用：`image/` 只需要 python3，
`kernel/` 需要 ARM 交叉工具链，`device/` 需要插着机器。

```
tools/
├── image/     组装镜像、体检镜像（纯离线，python3 即可）
├── kernel/    内核与内核模块：源码、编译、DT 提取、aboot 反汇编
├── device/    真机操作：DL 模式串口通道、分区备份/写回、Windows 侧脚本
├── flash/     在 TWRP 里跑的小脚本（推 /sdcard 后 sh）
├── repack/    写保护镜像的逐版重打包链（wp2 → wp6）
└── repo/      这个仓库自身的维护工具（走 REST 推送）
```

---

## image/ — 组装与体检

| 脚本 | 干什么 | 备注 |
|---|---|---|
| `mkhybrid.py` | 把 TWRP 载荷装进原厂 4.4.4 recovery ramdisk，产出可刷镜像 | **CI 主路径**，命令行长参数见 `--help` |
| `check_image.py` | 刷前自检：尺寸、页对齐、ramdisk/FDT 位置、字体数、模块存在性 | CI 卡口，任一不满足直接失败 |
| `cpioutil.py` | newc(cpio) 读写，字段全部小写十六进制 | 被 `slim_fonts.py` 引用 |
| `slim_fonts.py` | 裁/合并 TWRP 字体；`--single-font` 只留一套中英共用 | 省 233 KB，代价是 `fixed` 不再等宽 |
| `check_bootimg.py` | 解析 boot/recovery 头（kernel/ramdisk/second/dt 的偏移与尺寸） | 被 `dtid.py`、`dtimg.py` 引用 |
| `repack_bootimg.py` | 拆开 / 换内核 / 换壳重打 boot-recovery 镜像 | **boot.yml 用它换内核** |
| `dtid.py` | 读出原厂镜像里 DT 的机型匹配键 | 判断 DTS 该怎么写 |
| `dtimg.py` | 从原厂 dt 段里只捞出本机要的 DTB，重建小 dt.img | |

`check_bootimg.py`、`repack_bootimg.py`、`dtid.py`、`dtimg.py` 有相互 import，
**四个文件必须同目录**（各自用 `sys.path.insert(0, dirname(__file__))` 兜底）。

## kernel/ — 内核与模块

| 路径 | 干什么 |
|---|---|
| `kc_wp/` | eMMC 写保护清除模块：`kc_wp.c` + `Makefile` + `README.md`（编译参数、调参、日志解读） |
| `patch_modversions.py` | 改 `.ko` 的 `__versions` 名字前缀，绕开符号 CRC 不匹配（`err -22`） |
| `aboot_base.py` | aboot 文件偏移 ↔ 加载地址换算 |
| `dump_analysis/` | 在 `aboot.img` / `sbl1.img` 里定位 CMD28/CMD29 的反汇编脚本（依赖 capstone） |

内核源码本身不入库（480 MB），CI 从 LineageOS `android_kernel_motorola_msm8226` 的
`cm-14.1` 分支 clone，再叠 `kernel-overlay/` + `kernel-patches/`。

## device/ — 真机操作

| 脚本 | 干什么 |
|---|---|
| `serial_probe.py` | DL 模式（SBL1）串口握手 + 只读探测 |
| `serial_dump.py` | DL 模式按 GPT 备份分区（整机备份就是它做的） |
| `serial_write.py` | DL 模式写 GPT 条目区（已实测可行） |
| `serial_restore.py` | DL 模式按分区刷回备份（刷坏了从这儿回滚） |
| `flash_partition.py` | DL 通道直接写指定 eMMC 分区 |
| `kyocera_dl_probe.py` | 厂商协议只读探测（早期逆向，`0xA3` 读 / `0xA1` 写） |
| `flash_system.py` | 编排：备份 → 写 system → 清 data |
| `wipe_data.sh` | TWRP 里格式化 /data（关掉 3.4 内核不认的 fs 特性） |
| `setbcb.sh` | 系统内写 misc 的 `boot-recovery`（进 recovery 的兜底手段） |
| `check_dump.py` | 分区 dump 体检（离线，不连设备） |
| `fastboot_try.ps1` | Windows 侧生成 BCB 文件 |
| `keytest.ps1` | USB 时间线 / 按键判定（`18D1` recovery、`0482` 系统、`05C6` EDL） |
| `verify_recovery.ps1` | Windows 侧 recovery 刷写校验 |

## flash/ — 在 TWRP 里跑

| 脚本 | 干什么 |
|---|---|
| `wpcheck.sh` | 清写保护 → 写魔数回读 → 刷镜像 → 双 md5 对比 |
| `wp_fix.sh` | 手动兜底清保护（镜像里**不带**，`adb push` 到 `/sdcard` 再 `sh`） |

`README.md` 是这两个脚本的使用说明。

## repack/ — 写保护镜像的逐版重打包链

`repack_wp.py` → `wp3` → `wp4` → `wp5` → `wp6`，每一版只换一个变量（模块、脚本、
`init.rc` 行）。**只作记录**，CI 不走这条链。

参与打包的原厂镜像和中间产物不进仓库，用 `KC_IMG_DIR` 指向存放它们的目录：

```bash
KC_IMG_DIR=/path/to/images python3 tools/repack/repack_wp6.py
```

重跑可复现 wp5 `714383e8`、wp6 `f4ec23f8`。

## repo/ — 仓库自身维护

| 脚本 | 干什么 |
|---|---|
| `gh_push.py` | 走 GitHub REST API 推送（`git push` 在受限网络里会卡住时用）；`GH_TOKEN` 从环境变量读，`--repo` 默认取 `remote.origin.url` |
