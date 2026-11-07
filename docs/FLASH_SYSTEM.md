# 换系统：刷 `system` + 清 `data` 的完整清单

> 适用：从 DL 模式（SBL1，aboot 之前）把一份 `system.img` 写进去，然后清掉旧的 `/data`。
> 对应命令：`serial_restore.py --part system` + `wipe_data.sh`。
>
> 有一件事先说清楚：**`serial_restore.py` 没有 `--wipe-data` 参数，也不该有。**
> 原因见第 5 节——DL 通道只有 read/write，5 GB 的 `data` 擦不动，清 `data` 只能进 TWRP 做。

---

## 总览

| 阶段 | 做什么 | 在哪做 | 大致耗时 |
|---|---|---|---|
| 0 | 判断 `boot` 要不要一起换 | 电脑前想清楚 | — |
| 1 | 备份现有 `system` | DL 模式 | 25–60 min |
| 2 | 进 DL 模式 | 设备 | 1 min |
| 3 | 测速（建议） | DL 模式 | 5 min |
| 4 | 写 `system` | DL 模式 | 25–60 min |
| 5 | 清 `data` | TWRP | 3 min |
| 6 | 首次开机验收 | 设备 | 5–15 min |

**不可跳过的两步：1（备份）和 6（验收）。** 其余都能重来。

---

## 阶段 0：`boot` 要不要一起换

`system` 里是文件系统，`boot` 里是内核 + ramdisk（含 `init`）。两边必须同代。

| 你的情况 | 刷什么 | 命令 |
|---|---|---|
| 恢复同版本系统的备份 | 只 `system` | `--part system` |
| 换同版本 ROM，内核没动 | 只 `system` | `--part system` |
| 换 Android 大版本（4.4 → 5.1/7.1） | `system` + `boot` | 两条命令，见 4.3 |

判断"是不是同代"最直接的办法：拿 ROM 包里的 `boot.img` 和手上的 `boot.img` 比内核是否一致。

```bash
python tools/image/check_bootimg.py boot_new.img        # 看 page size / kernel / ramdisk 各段
```

跨版本只刷 `system`、留着 4.4 的 `boot`，现象是卡第一屏，或者起来后 zygote 反复崩。
日志在 `log` 分区，见 `DEVICE_NOTES.md` §4。

---

## 阶段 1：备份现有 `system`

**这步不做，刷坏了就回不到出厂系统。**（出厂 OTA 包已经没了，网上也没有 KC-01 的官方 ROM。）

```bash
python serial_dump.py COM13 --only system --force --outdir dump_stock
```

- `--force` 是必须的：默认跳过 128 MB 以上的分区，防止误操作。
- 1,404 MiB。单包从 4 KB 起，设备嫌大会自动降到 2 KB / 1 KB，实际速度看跑出来的 `MB/s`。
- 掉线了重新跑同一条命令即可，`serial_dump.py` 会从断点续。
- 结束后核对：文件大小应为 `1404 × 1024 × 1024 = 1,472,286,720` 字节，末尾不足一包的部分会补 `0x00`。

```bash
ls -l dump_stock/19_system.img
```

顺手把 `boot` 和 `recovery` 也备一份（各 16 MiB，几分钟的事）：

```bash
python serial_dump.py COM13 --only boot,recovery --outdir dump_stock
```

---

## 阶段 2：进 DL 模式

和你当初跑 `serial_dump.py` 时一样：SD 卡根目录放控制文件，插卡上电。

```bash
# FAT32 卡，8 字节，不要带回车
printf 'SDLCRCON' > /mnt/sd/SDCRCON
```

电脑侧确认：

- 设备管理器出现 **KYOCERA High Speed Serial Port**，`0482:xxxx`；
- 端口号（`COM13` 之类）就是后面命令里的第一个参数。

两个前提：

1. **冷启动**（拔电池 → 装电池 → 上电）。写保护位扛得住 SoC 复位，扛不住断电；热复位进来的可能还带着 aboot 上一轮置的位。
2. 卡上**不要放 `set.bin`**。`set.bin` 的 D/E/F 字段还没定死，见 `DEVICE_NOTES.md` §12.5，现在只做落点校准。

退出 DL 回到系统：拔 USB → 取电池 → **拔 SD 卡** → 装电池开机。SD 不拔会再次进 DL。

---

## 阶段 3：测速（建议做，5 分钟）

1.4 GB 是这个通道上最大的一次写入，先拿小分区确认链路。

```bash
python serial_restore.py COM13 --image dump_stock/12_recovery.img --part recovery --verify
```

16 MiB，1024 包。跑完看输出的耗时，乘 87 就是 `system` 的预估时间。

| recovery 耗时 | `system` 预估 |
|---|---|
| 40 s | 约 58 min |
| 60 s | 约 87 min |
| 90 s | 约 130 min |

超过 2 小时就别硬等，先查是不是在反复降级拆包（输出里会出现 `降级`）。

---

## 阶段 4：写 `system`

### 4.1 先空跑

```bash
python serial_restore.py COM13 --image system.img --part system --dry-run
```

检查四行：分区定位（`system @LBA xxxx`）、可写大小 ≥ 镜像大小、SHA-256、`[dry-run]` 那行。
`serial_restore.py` 会自动把 Android sparse 镜像展开成 raw，`zip` 里的要先解出来。

### 4.2 实写

```bash
python serial_restore.py COM13 --image system.img --part system --verify
```

- 不需要 `--allow-critical`。`system` 写坏只是开不了机，冷启动还能重进 DL 写回来。
- `--verify` 在 1.4 GB 上是抽样（32 处 × 64 KB）。要全量回读加 `--verify-full`，但读通道比写慢，能再花一小时。
- 逐块回读是默认开的。**别为了快加 `--no-chunk-verify`**——这条通道的失败方式是静默的，不回读就不知道写没写进去。
- 中途掉线：加 `--resume` 重跑，从 `.wstate` 记的断点续写。

### 4.3 如果 `boot` 也要换

```bash
python serial_restore.py COM13 --image boot_new.img --part boot --verify
```

同样不需要 `--allow-critical`（`boot` 是软砖区）。16 MiB，两三分钟。

> 顺序建议：**先 `boot` 后 `system`**。反过来时如果 `boot` 写失败，你会有一台"新系统 + 旧内核"的机器，卡在第一屏，看起来像 `system` 刷坏了，排查方向会被带偏。

---

## 阶段 5：清 `data`

**为什么不能在 DL 模式做**：DL 通道只有 `0xA3` 读、`0xA1` 写，没有 ERASE。`data` 有 5,093 MiB，
写零要 33 万包、跑四五个小时，而且写完 eMMC 还得再擦一遍。真要擦，`sbl1` 的 `set.bin`
子类型 8 有擦除代码，但那套格式还没验证完。

正确做法是进 TWRP 重新 `mke2fs`，五秒钟完事。

### 5.1 进 TWRP

系统还能起来：

```bash
adb reboot recovery
```

系统起不来：写 misc 的 BCB。

```bash
adb shell su -c "printf 'boot-recovery' | dd of=/dev/block/mmcblk0p26 bs=1 count=32"
adb reboot
```

（`setbcb.sh` 是同一件事的封装，见 `DEVICE_NOTES.md` §10.7。）

### 5.2 跑脚本

```bash
adb push tools/device/wipe_data.sh /tmp/
adb shell sh /tmp/wipe_data.sh --dry-run     # 先看分区和设备对不对
adb shell sh /tmp/wipe_data.sh               # 真格式化
```

脚本做四件事：卸载 → `mke2fs` → **挂载验证** → `chmod 0771`。

文件系统特性这块查清楚了，分两件事说：

**现役这份 TWRP（`twrp-kyl23.img`）不会踩坑。** 从镜像里解出来的 `sbin/mke2fs` 是
e2fsprogs **1.42.9**（sha256 `83804cf2…`，和 `twrp_rd3/sbin/mke2fs` 逐字节相同），
它读 ramdisk 里的 `/etc/mke2fs.conf`，ext4 的默认特性被钉死成：

```
has_journal,extent,huge_file,flex_bg,uninit_bg,dir_nlink,extra_isize
```

没有 `64bit`，没有 `metadata_csum`，也没有 `bigalloc` / `orphan_file`。3.4.0 内核全部支持，
所以在这台上格式化 `data`，直接 `mke2fs -t ext4` 就是安全的。

**坑在换 TWRP 的时候。** e2fsprogs ≥ 1.43 把 `metadata_csum` 变成默认，≥ 1.44 把 `64bit`
变成默认（3.2 以后的 TWRP 大多带这种版本）。那时候 `mke2fs` 会"成功"，重启后 `fs_mgr`
挂不上 `/data`，表现为无限重启，而且没有任何报错指向文件系统。

脚本两头都兜：先用 `-O ^…` 显式关特性（按 e2fsprogs 版本分三级降级，旧版不认特性名就退到下一级），
格式化完立刻 `mount` 一次验证。挂上了才算成功——这一步在两个版本上都值。

手工做同样的事（不想用脚本时）：

```bash
# TWRP 终端
umount /data
mke2fs -t ext4 -O ^64bit -b 4096 -m 0 -L data /dev/block/mmcblk0p20
mount -t ext4 /dev/block/mmcblk0p20 /data && echo OK && umount /data
```

或者用 TWRP 图形界面：**Wipe → Advanced Wipe → 勾 `Data` → Repair or Change File System → Change File System → ext4**。
注意只勾 `Data`，别勾 `Internal Storage` 之外的东西。

### 5.3 `data` 不需要清写保护

`boot` / `recovery` 有写保护，`cache` / `data` 没有（`DEVICE_NOTES.md` §3）。
所以这一步什么都不用做。真正需要清保护的场合是：在 TWRP 里刷 `boot`、
恢复 `recovery` 备份、以及刷带 `boot.img` 的 ROM 包 —— 本仓库的镜像由 `kc_wp.ko`
开机 4 秒自清（`dmesg | grep kc_wp` 确认），换了别的 recovery 才要手动
`echo autofix mmcblk0p12 > /sys/kernel/kc_wp/run`。

---

## 阶段 6：首次开机验收

```bash
adb reboot
```

首次开机要重建 `/data` 下的目录树、跑 dexopt，**5–15 分钟**，中途屏幕停在 logo 或反复转圈都正常。
判断"还在干活"而不是"卡死"：

```bash
adb shell "cat /proc/uptime"          # 能连上就说明起来了
adb shell "ps | grep -c ."           # 进程数在涨
```

验收四项：

| 检查 | 命令 | 期望 |
|---|---|---|
| `system` 挂上了 | `adb shell df -h /system` | 有容量，不是 0 |
| `data` 挂上了 | `adb shell df -h /data` | 约 5 GB |
| 系统版本对 | `adb shell getprop ro.build.display.id` | 和你刷的 ROM 一致 |
| 没有 panic | `adb shell su -c "dd if=/dev/block/mmcblk0p22 of=/sdcard/log.bin bs=1M"` | 拉回来 `strings \| grep -i panic` 为空 |

---

## 失败分支

| 现象 | 大概率原因 | 怎么办 |
|---|---|---|
| 第一阶段就卡住，logo 不动 | `boot` 和 `system` 不同代 | 补刷对应版本的 `boot` |
| 起来后反复重启，`log` 里有 `fs_mgr` 失败 | `/data` 文件系统特性不兼容 | 重进 TWRP 跑 `wipe_data.sh`，看"挂载验证"那行 |
| 卡在 recovery 而不是系统 | misc 里还留着 `boot-recovery` | `printf '\0' \| dd of=/dev/block/mmcblk0p26 bs=1 count=32` |
| `adb` 看不到设备 | MTP/ADB 驱动（主机侧） | `DEVICE_NOTES.md` §9.5 |
| 写 `system` 报 `0x04 … 0x54` | 单包超过固件上限 4096 | 去掉 `--chunk`（默认就是 4096）；别加更大 |
| 写 `system` 报 `0x04 … 0x55` | 写保护还在，或目标越界 | 拔电池冷启动重进 DL；先跑 `--part system --wp-test` |
| 写完回读不一致 | 写保护没清干净 | 冷启动（拔电池）重进 DL 再写一次 |

## 回退

任何一步失败，回到阶段 4 写回备份即可：

```bash
python serial_restore.py COM13 --image dump_stock/19_system.img --part system --verify
```

只要 `sbl1` / `aboot` 没被碰过，DL 模式就一直在。这就是为什么那两个分区默认拒写。
