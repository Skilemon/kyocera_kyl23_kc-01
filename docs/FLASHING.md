# 刷入 recovery

## 一句话

**这台机器不能直接 `dd`。** boot / recovery 分区有硬件写保护，`dd` 会打印
`1797+0 records out`、`sync` 也返回成功，但数据全部被丢弃，重启后还是原来的镜像。
得先用 `kc_wp.ko`（本仓库自带）清掉写保护位再写，**并且中间不能重启**。

---

## 为什么

- 写保护位是 **eMMC 层面** 的，不是文件系统权限，`supersu` 和 `chmod` 都绕不过
- 只有 MMC **CMD29** 能清它
- 状态是 **易失** 的：每次上电由 aboot 重新置上，所以解锁完必须马上写
- `cache` 分区没有保护（可以拿它验证「dd 到底能不能写」）

---

## 准备

1. 设备已 root（`su` 可用），或已经能进本仓库产出的 TWRP
2. 已备份全部分区（至少 `recovery`、`boot`、`system`、`persist`、`modem`）
3. 电脑上有 `adb`，镜像和 `kc_wp.ko` 已 `adb push` 到 `/data/local/tmp/`

---

## 刷入流程

### 1. 确认分区节点

```bash
adb shell "su -c 'readlink -f /dev/block/platform/msm_sdcc.1/by-name/recovery'"
```

应当返回 `/dev/block/mmcblk0p12`。**记下这个编号**，下面每一步都要用对；
写错名字（比如占位符 `mmcblk0pX`）会让内核 oops 并卡死。

### 2. 确认写保护已被清掉

**在 TWRP 里：镜像自己会做。** `kc_wp.ko` 已经打进 `/sbin`，由 stock `init.rc` 的
`on init` 段 `insmod`，模块起来后 4 秒自己扫一遍 `mmcblk0p12` / `mmcblk0p11`：

```bash
adb shell "dmesg | grep kc_wp"
#   kc_wp: boot: 自动清除完成（2 个分区）
adb shell "ls /sys/kernel/kc_wp/"            # run  present
```

**在系统里（Android 已启动）** 得自己加载，且普通 `insmod` 会被 SELinux 拒，
要用京瓷自己的加载器：

```bash
adb push kc_wp.ko /data/local/tmp/
adb shell "su -c '/system/xbin/insmod_as_wlan /data/local/tmp/kc_wp.ko'"
adb shell "su -c 'ls /sys/kernel/kc_wp/'"
```

`insmod_as_wlan` 前面几行 `rmmod wlan failed` 是正常噪声。

### 3. 清除写保护（自清没赶上时手动补一刀）

```bash
adb shell "su -c 'echo autofix mmcblk0p12 > /sys/kernel/kc_wp/run'"
adb shell "su -c 'dmesg | grep -A1 kc_wp'"     # 看每个分区的 ret / R1
```

`autofix` 会按扇区和字节两种口径各扫一遍，并打印「起始 WP 组类型 x -> y」。
出现 `OUT_OF_RANGE`（`R1=0x80000900`）说明那一轮地址口径不对，让模块自己换下一种。
只想看状态不动数据：

```bash
adb shell "su -c 'echo info > /sys/kernel/kc_wp/run'"    # EXT_CSD 的 WP 组位图
```

`0x5555…` = 全是临时保护（正常，可清）；出现 `10` / `11` 组说明有上电/永久保护，
那种清不掉，只能换分区规划。

### 4. 写入（清完立刻做，不要重启）

```bash
adb shell "su -c 'dd if=/data/local/tmp/recovery.img of=/dev/block/mmcblk0p12 bs=4096; sync'"
```

### 5. 回读验证

读开头 16 字节，和镜像文件的头 16 字节逐字节比：

```bash
adb shell "su -c 'dd if=/dev/block/mmcblk0p12 bs=16 count=1 2>/dev/null | od -An -tx1'"
```

开头一定是 `41 4e 44 52 4f 49 44 21`（`ANDROID!`）。读回来还是别的镜像的头，
就说明保护位没清掉，`dd` 白写了。

想核对整段写入是否一致，比 md5 更直接：

```bash
adb shell "su -c 'dd if=/dev/block/mmcblk0p12 bs=4096 count=<镜像大小/4096> 2>/dev/null | md5sum'"
```

和本地 `md5sum recovery.img` 对比即可。Android 4.4 自带的 toolbox `md5` 不吃 stdin，
所以必须写成 `dd | md5sum`，不能直接 `md5 /dev/block/...`。

### 6. 重启进 recovery

**硬件按键在这台机器上进不了 recovery。** 这一点折腾了很多轮，最后从 `aboot.img` 里
拿到了确定答案（[DEVICE_NOTES.md](DEVICE_NOTES.md) 第 10 节）：aboot 里通往 fastboot 和
recovery 的按键分支都没有被链接进来，`is_fastboot_key` 那句日志字符串零引用。

实测到的三种表现，长得完全一样，所以**不要用屏幕判断成败**：

| 操作 | 结果 | 说明 |
|---|---|---|
| 音量上 + 音量下 + 电源 | 进**安全模式** | aboot 不认三键，走正常启动；是 Android 的 `init` 检测到音量上按住才进的安全模式 |
| 音量上 + 电源 | 震 2 次后进系统 | aboot 收到按键了，但没有对应分支 |
| 音量下 + 电源 | 震 2 次后进系统 | 同上 |

### 能用的两条路

```bash
adb reboot recovery
```

系统能起来、adb 可用时用这条。

```bash
# 系统能起来但已经明显要坏，想确保下一次落在 recovery 里
adb shell su -c "printf boot-recovery | dd of=/dev/block/mmcblk0p26 bs=1 conv=notrunc"
adb reboot
```

第二条写的是 misc 分区的 BCB 命令 —— aboot 唯一实现的那个入口。它不经过 Android 的
`reboot` 服务，所以系统半死时也用得上。recovery 启动后会自己清掉这条命令；如果没清，
进系统后立刻用 `tools/device/setbcb.sh --show` 确认并手动抹掉，否则每次开机都会再进 recovery。

### 进去之后怎么判断成功

**不要用屏幕判断。** 这个 TWRP 是「原厂 4.4 init + TWRP 载荷」，init 要先拉起 ueventd、
healthd、预挂载 `/system`，才 `exec` TWRP，**黑屏 30–60 秒是正常的**。看 USB：

```bash
adb devices        # 有设备 = 进的是 recovery
fastboot devices   # 有设备 = 进的是 bootloader
```

两者都没有、而且手机自己重启进了系统，说明 misc 里的 BCB 没被读到——回去重写一次，
并确认 `setbcb.sh --show` 回读出来确实是 `boot-recovery`。

### 系统完全起不来时

只剩 EDL（`05C6:9008`），需要拆机短接 eMMC 时钟脚，见文末「关于 9008 / EDL」。
**这就是为什么全分区备份才是唯一的保险，而不是按键。**

---

## 回滚

recovery 分区坏了**不影响正常开机**（boot 分区没动过），长按电源 15–20 秒即可强制重启。

要恢复原厂 recovery：

```bash
adb push recovery_stock.img /data/local/tmp/
# 重做步骤 2 → 3 → 4，把 if= 换成 recovery_stock.img
```

`recovery_stock.img` 是 16,777,216 字节的完整分区镜像。

---

## 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `dd` 成功但读回没变 | 写保护没清掉 | `dmesg \| grep kc_wp`，确认「自动清除完成」出现过 |
| dmesg 里有 `OUT_OF_RANGE`（`R1=0x80000900`） | CMD29 的地址口径不对（字节 vs 扇区） | `kc_wp.ko` 会自动换另一种口径重试；两者都失败说明该分区在上电/永久 WP 组里 |
| 卡在开机 logo | 内核没被加载，通常是 DT 表不对 | 用 `tools/image/check_image.py` 检查镜像 |
| 开机进系统但按物理键进不了 recovery | **aboot 没实现按键进 recovery**，不是镜像问题 | 用 `adb reboot recovery`，或写 misc 的 `boot-recovery`，见第 6 步 |
| `insmod` 报 `Unknown symbol (err -22)` | 模块 CRC 和本机内核不匹配 | 用本仓库 `prebuilt/kc_wp.ko`，别自己重编 |
| 写入后设备无响应 | 正常现象，清保护时 I/O 会停几秒 | 等待，不要断电 |

---

## 在 TWRP 里刷：保护已经被镜像自己清掉了

TWRP 也是被 aboot 拉起来的，aboot 每次上电都会把 boot / recovery（以及 system）重新保护上，
所以 **TWRP 里的 `dd`、恢复备份、刷带 `boot.img` 的 ROM 包，都会「报成功但没写进去」**——
除非先把保护清掉。

本仓库产出的镜像**不需要手动做这一步**：`kc_wp.ko` 已经打进 `/sbin`，由 stock `init.rc` 的
`on init` 段 `insmod`，模块自己起一个 delayed work，4 秒后把 `mmcblk0p12`（recovery）和
`mmcblk0p11`（boot）扫一遍清掉，失败每 500 ms 重试，最多 15 次。日志进内核缓冲区：

```bash
# TWRP 终端里，确认自清跑过
dmesg | grep kc_wp
#   kc_wp: boot: 自动清除完成（2 个分区）
```

需要手动补一刀时（比如换了分区、自清没赶上）：

```bash
echo "autofix mmcblk0p12 mmcblk0p11" > /sys/kernel/kc_wp/run   # 清保护
echo "info"                          > /sys/kernel/kc_wp/run   # 看 EXT_CSD 的 WP 组状态
```

也可以 `adb push tools/flash/wp_fix.sh /sdcard/` 后在 TWRP 里 `sh /sdcard/wp_fix.sh`。
自检走 `tools/flash/wpcheck.sh`：清保护 → 写魔数回读 → 刷镜像 → 双 md5。

> 原厂的 `mmc_protect.ko` 已经不用了：它把 `start_sect << 9` 当 CMD29 参数发出去，
> 而 >2 GB 的卡按 JEDEC 要按**扇区**给地址，于是每条命令都 `OUT_OF_RANGE`，
> sysfs 的 `clear` 却照样返回成功。`kc_wp.ko` 两种口径都扫。细节见
> [DEVICE_NOTES.md](DEVICE_NOTES.md) §12.6。

> 注意区分：**DL 模式（SBL1）不需要这一步**，写保护还没被置上，见
> [DEVICE_NOTES.md](DEVICE_NOTES.md) 第 12 节。

---

## 换系统（system + data）的完整清单

刷 `system.img` 和清 `/data` 的逐步清单、时间估算、失败分支，见
**[FLASH_SYSTEM.md](FLASH_SYSTEM.md)**。一条命令跑完的编排器是
`tools/device/flash_system.py --image system.img --backup --wipe-data`。

---

## 关于 9008 / EDL

**不要把它当救星。** 这台机器没有验证过能进 9008，而且即使进了，Sahara 协议
同样受 eMMC 写保护约束——写保护是在存储控制器层面生效的，换一条写入通道并不会绕过它。

真正的保险是那份 1.86 GB 的全分区备份。
