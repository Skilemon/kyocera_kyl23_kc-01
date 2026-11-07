# 组合键进 recovery：怎么测才有结论

## 0. 先说清楚为什么之前的测试全是白测

前几轮试了十几种组合，结论都是「卡 logo → 震动 → 进系统」。这个现象**同时**符合三种
完全不同的原因：

| 真实情况 | 屏幕表现 |
|---|---|
| 按键没被 aboot 接受，走 normal boot | 卡 logo → 进系统 |
| 进了 recovery，但 init 卡在 mount /cache，看门狗 13 秒后复位 | 卡 logo → 自动重启 → 进系统 |
| 进了 recovery 并且起来了，只是 TWRP 显示没初始化完就复位 | 卡 logo → 自动重启 → 进系统 |

眼睛分不出来，所以每试一次都得不到信息。**必须先有观测手段，再谈按键。**

观测分两层，缺一不可：

| 层 | 手段 | 能回答什么 |
|---|---|---|
| 主机侧 | USB 设备时间线 | 有没有跑起一个带 adbd 的系统，是哪一个 |
| 设备侧 | log 分区 p22 的 PET 表 | 这一次是不是被复位了，复位原因是什么 |

底层依据：**recovery 的 `init.rc` 把 `idVendor/idProduct` 写成 `18D1:D001`，正常系统是
Kyocera 的 `0482:xxxx`。** 只要在电脑上看到 `18D1` 出现，就是进了 recovery，跟屏幕
黑不黑、卡不卡没有关系。

---

## 1. 准备：主机侧 USB 时间线

在**按键之前**就在 Windows 上跑起来，让它一直记：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\keytest.ps1 -Mode watch
```

输出长这样，每行带相对秒数：

```
   3.21  ADD  USB\VID_18D1&PID_D001\5bb64bcc        Android ADB Interface
   9.04  DEL  USB\VID_18D1&PID_D001\5bb64bcc
  31.87  ADD  USB\VID_0482&PID_09xx\5bb64bcc         miraie KYL23
```

`18D1` 出现 = 进了 recovery；只有 `0482` = 走了正常系统；`05C6` = 进了 fastboot/EDL。

> 轮询粒度约 1–2 秒（`Get-PnpDevice` 本身要这个时间），对「5 秒还是 30 秒」这种判断足够。
> 脚本要管理员权限才能看到全部设备。

## 2. 准备：设备侧复位记录

每次测完、设备进系统后跑：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\keytest.ps1 -Mode dump
```

它抓三样东西：

- `p22` 分区最前面 4 KB —— **PET 表**，每次复位一条记录，格式是
  `KERNEL / HW WATCH DOG / 2026-09-01 17:24:43 UTC (LAST PET) / 版本 / msm8226`
- `/proc/cmdline` —— 本次启动参数
- `/proc/last_kmsg` 尾部 —— 上次复位前的内核日志

PET 表是最关键的证据：**每按一次键、每复位一次，条目就多一条。** 如果一次按键尝试
之后 PET 多出一条 `HW WATCH DOG`，说明设备进了一个会挂的镜像然后被看门狗打死——那
就是 recovery，按键其实是有效的。

### 怎么读 PET

这是从这台机器上真实抓到的一组：

```
KERNEL / HW WATCH DOG  / 2026-09-01 17:24:43 / 102.0.1e20 / msm8226
KERNEL / HW WATCH DOG  / 2026-09-01 17:44:24 / 102.0.1e20 / msm8226
KERNEL / KERNEL PANIC  / 1970-01-01 01:15:43 / 201.1.0a20 / msm8226
KERNEL / HW WATCH DOG  / 2026-09-01 17:24:18 / 102.0.1e20 / msm8226
```

| 字段 | 读法 |
|---|---|
| 复位原因 | `HW WATCH DOG` = 内核没响应，硬件看门狗拉的；`KERNEL PANIC` = 内核自己崩的 |
| 时间 | `2026-*` 说明那次启动拿到了 RTC；**`1970-*` 说明那次没拿到——recovery 不读 RTC，正常系统会**，所以 1970 的条目大概率就是进 recovery 那一次 |
| 版本 | `201.1.0a20` 是原厂 4.4.4（本镜像 ramdisk 的基础），`102.0.1e20` 是另一版固件 |

上面第三行就是一条 **1970 + KERNEL PANIC**：recovery 的内核起来过，然后崩了。说明这条路
走得通，只是走到了会崩的地方——这正是 `--boot-trace` 要抓的东西，不是按键的问题。

**测一次，记一次 PET 条数。** 条数不变 = 那次按键连内核都没换；条数 +1 且原因是
`HW WATCH DOG` = 换了内核但卡死；`+1` 且 `KERNEL PANIC` = 崩在某个驱动初始化上。

---

## 3. 先做对照实验（不要跳过）

在不知道「成功长什么样」之前测按键，等于闭眼调参。

1. 系统里执行 `adb reboot recovery`，同时主机侧 `-Mode watch` 已经在跑。
2. 记下三件事：**`18D1` 在第几秒出现**、**屏幕在这之前是什么样**、**多久之后设备消失
   或复位**。
3. 设备回到系统后 `-Mode dump`，记下 PET 表增加了几条、原因是什么。

这一次的结果就是「基线」。之后每次按键，只问一句：**和基线像不像？**

对照表：

| 基线里的环节 | 出现在第几秒 | 现象 |
|---|---|---|
| 屏幕变化 | ___ |  |
| 第一次震动 | ___ |  |
| `18D1` 出现 | ___ |  |
| 复位 / 断开 | ___ |  |

### 3.1 一份真实基线（KC-01，`adb reboot recovery`）

已经把电脑上无关设备（蓝牙、指纹、摄像头、键鼠）删掉，只留这台机器的行：

```
 1.11  ADD  USB\VID_0482&PID_0A27&MI_00           KC-01
 1.14  ADD  USB\VID_0482&PID_0A27\5BB64BCC        USB Composite Device
 1.15  ADD  USB\VID_0482&PID_0A27&MI_01           Android Composite ADB Interface
11.44  DEL  USB\VID_0482&PID_0A27  ×3 个节点
20.27  ADD  USB\VID_18D1&PID_D001\5BB64BCC       Android Composite ADB Interface
21.66  ADD  USB\VID_18D1&PID_4EE2\5BB64BCC       USB Composite Device
21.66  ADD  USB\VID_18D1&PID_4EE2&MI_00          MTP
21.68  ADD  USB\VID_18D1&PID_4EE2&MI_01          Android Bootloader Interface
21.68  DEL  USB\VID_18D1&PID_D001\5BB64BCC
```

三个必须记住的数字：

| 观察 | 含义 |
|---|---|
| **8.8 秒**（11.44 → 20.27） | 从系统 USB 掉线到 recovery adbd 上线。这段就是 recovery 内核起来 + init 挂 `/system` 的时间，**按键测试时至少要等 30 秒再下结论** |
| **1.4 秒**（20.27 → 21.68） | `18D1:D001` 只活这么久，TWRP 一起来就 `Enable_MTP()` 切到 `4EE2`。**轮询粒度 1–2 秒，可能刚好错过这个窗口**，所以判据要放宽成「出现任何 `18D1`」 |
| **`MI_00 → MTP`** | MTP 链路是通的，驱动名字直接就是 `MTP` |

两处容易误读的地方：

- `18D1:4EE2&MI_01` 显示成 **Android Bootloader Interface**，那是电脑上装了 Google USB Driver
  （`android_winusb.inf`）抢着匹配的结果，不影响 adb，也不影响 MTP。
- `18D1:D001` 这一段是「TWRP 还没启用 MTP」的过渡态，不是失败。

**这份基线说明 `adb reboot recovery` 这条路是完整可用的，MTP 也是好的。** 组合键要做的只是
复现这串 `18D1`。

---

## 4. 按键矩阵

### 4.0 先解决「插不插线」

这是个死结：**要观测就必须插线，但插线本身会改变 aboot 的判定**——高通平台在 USB 插入
时会先做充电器识别，充电模式优先于正常启动，按键就可能被忽略。

解法是错开时间。aboot 采样按键只发生在**通电后的头 1–2 秒**，而 recovery 要 8 秒以后
才把 adbd 拉起来。所以：

1. 断电（长按电源 15 秒，屏幕全黑）
2. 按住组合键，**不要插线**
3. 保持按住，等 2 秒（aboot 已经采样完）
4. **这时候才插线**，继续按住
5. 盯 `watch` 的输出 30 秒

这样按键判定发生在「没有线」的环境里，观测又赶在 `18D1` 出现之前把线接上了。

如果嫌这个时机太难，先整套流程插着线跑一轮，再拔线盲测一轮，两边对比——**如果插线那轮
一直进不去、拔线那轮能看到 PET 多出一条 watchdog，那就证明线的影响是决定性的**。

### 4.1 组合和时机

已知事实：**正常开机不震动；只要震动，就说明 aboot 已经收到按键了。** 所以「震动了」
不等于「进 recovery 了」——aboot 收到键，但可能选了 normal boot。

关键在于**震动之后手怎么放**。逐条试，每条之间强制重启一次（`adb reboot`），避免
状态串味。

| # | 组合 | 松手时机 | 想验证什么 |
|---|---|---|---|
| 1 | 音量下 + 电源 | 屏幕亮起后**只松电源**，音量下按住不放，等到出画面或自动重启 | 官方手法，音量下是 recovery 键还是 fastboot 键 |
| 2 | 音量上 + 电源 | 同上 | 高通平台最常见的是**音量上**进 recovery，不是音量下 |
| 3 | 音量上 + 音量下 + 电源 | 三键全按住，一直不松 | 三键是否等价于 bootloader 菜单 |
| 4 | 音量上 + 音量下 + 电源 | 亮屏后**只松电源**，两个音量键按住 | 上次「卡 logo 后强制重启」那次用的就是这个，重点复测 |
| 5 | 音量上 + 音量下 | 先按住两键，**再插 USB 线** | 4.4 高通机常在 USB 插入瞬间采样按键 |
| 6 | 音量上 | 断电（拔电池/长按电源 10 秒），按住音量上，**再装电池或插电** | 绕过 aboot 的「已开机」状态 |
| 7 | 音量下 + 电源 | 按住 15 秒以上不松 | 长按是否会二次触发 recovery/fastboot |

每条记录四列，抄进下面的表：

| # | 震动（几次/第几秒） | 屏幕 | `18D1` 出现？ | 自动重启？ |
|---|---|---|---|---|
| 1 |  |  |  |  |
| 2 |  |  |  |  |
| … |  |  |  |  |

---

## 5. 结论怎么读

把每一条的结果套进这张表，**只有第一种和第五种需要继续调手法，其余都是别的问题**：

| USB 时间线 | 自动重启 | 结论 | 下一步 |
|---|---|---|---|
| `18D1` 出现并保持 | 否 | **按键成功，进了 recovery** | 屏幕是 TWRP 就成了；黑屏则查显示 |
| `18D1` 出现后消失 | 是 | 按键成功，recovery 起来了又挂 | 查 `--boot-trace` 的 `run*_stage*.txt`，卡在 mount |
| 没有 `18D1`，只有 `0482` | 否 | 按键被 aboot 吃掉了，走了 normal boot | 换组合，重点试 #2 #5 #6 |
| 没有 `18D1`，`0482` 出现得很晚 | 是 | 进了一个起不来的镜像，内核就挂了 | 抓 PET 看是 `KERNEL PANIC` 还是 `HW WATCH DOG` |
| `05C6:9008` / `05C6:900E` | — | 进了 EDL 或 fastboot | 这个组合是 fastboot 键，不是 recovery 键 |

### 关于「震动几下」

这是**最有价值但一直被忽略的线索**。很多高通机型的 aboot 用震动次数编码结果：

- 1 短震 = 进入 normal boot
- 2 短震 = 进入 recovery
- 3 短震 = 进入 fastboot
- 长震 = 电量不足 / 错误

下次测的时候**数清楚几次、间隔多长、在第几秒**。如果 #1 和 #4 的震动次数不同，那基本
就能确定哪个组合被 aboot 认成了 recovery——然后再去看 USB 有没有出现 `18D1`，两边一
对上，结论就闭合了。

---

## 6. 如果最后确认按键根本不进 recovery

那就是 aboot 的按键表被 Kyocera 改过，或者这台机器有区域锁。此时不要再耗在按键上：

- `adb reboot recovery` 一直是可用的，日常用它。
- 真需要「无系统时进 recovery」，可以走 **misc 分区写 BCB**：把 `boot-recovery` 写进
  `mmcblk0p26` 前 32 字节，下次开机 aboot 会直接引导 recovery，等价于物理按键。注意
  写进去这一步本身要系统能起来一次；写完之后的每次开机都不再依赖 Android。
- **`reboot-bootloader` 写进去没用**，它不是 BCB 命令，aboot 里也没有对应的代码分支
  （见 `docs/DEVICE_NOTES.md` 10）。BCB 只支持 `boot-recovery` 和 `update-radio`。
- 但前提是 recovery 本身得能起来。目前 `adb reboot recovery` 能进，说明镜像没问题；
  如果按键路径进去就挂，那差异在 aboot 传的参数上，得抓两边的 `cmdline` 对比。
