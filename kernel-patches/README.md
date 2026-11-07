# prebuilt/kernel 的来历

`device/kyocera/msm8926-common/prebuilt/kernel` 在 2026-11 之前是原厂
`recovery.img` 里原样取出的 zImage。现在它是由京瓷发布的 GPL 源码自己编出来的，
源码改动全部记录在本目录的 patch 里。

## 为什么不再用原厂内核

原厂 zImage 里有两处京瓷私有的东西，都挡着 TWRP：

1. **insmod 钩子** — `security/selinux/hooks.c` 里的
   `selinux_kernel_setup_load_info()`，在 `kernel/module.c` 的
   `load_module()` 调 `init_module()` 之前判定：

   ```c
   /* Only init process can insmod as root */
   if (current_uid() == 0 && current->pid != 1)
           goto err;
   for (i = 0; kc_module_checklist[i]; i++)
           if (!strcmp(kc_module_checklist[i], kmod_name))
                   return 0;
   err:
           pr_warn("no permission in %s pid=%d pname=%s module=%s\n", ...);
           return KC_IN_SPECIAL_MODE ? 0 : -EPERM;
   ```

   `kc_module_checklist[]` 只有 `"wlan"`，所以除了 1 号进程加载 wlan，
   其余 insmod 一律 `-EPERM`，且这条路径上的 `sysfs_create_group()` 失败会让
   模块被静默卸载 —— 现场看到的是
   `no permission in selinux_kernel_setup_load_info pid=1 pname=init module=mmc_protect`
   加上 `/sys/kernel/mmc_protect` 目录不存在。

   放行条件是 `KC_IN_SPECIAL_MODE`，即 cmdline 带 `kcdroidboot.mode=f-ksg`
   或 `androidboot.mode=kcfactory`（`hooks.c:148/159` 的两个 `early_param`）。

2. **eMMC 写保护** — 内核源码树里搜不到 `mmc_protect`（只有
   `omap_hsmmc.c` 里一个无关的 `omap_hsmmc_protect_card()`，那是 SD 卡盖检测），
   说明拦截逻辑完全在外挂的 `mmc_protect.ko` 里。也就是说：**不加载那个模块，
   就没有写保护**。原厂是靠 recovery 的 init 去 insmod 它才生效的。

两件事叠在一起才是"TWRP 里 dd 写 boot/recovery 静默无效"。换掉内核之后两件
一起消失，镜像里也就不再需要 `--module`。

## 源码

| | |
|---|---|
| 来源 | 京瓷 GPL 发布包 `kyl23_kernel.tar.gz`（KYL23 / KYL23-J，2016） |
| 版本 | Linux **3.4.0**（`Makefile`: VERSION 3 / PATCHLEVEL 4 / SUBLEVEL 0） |
| 基线 | CAF `LNX.LA.3.5.1-06610-8x26.0`，2014-07-03，见包内 `HowToBuild` |
| 板级 | `arch/arm/boot/dts/msm8226-720p-mtp.dtsi` 里有 `mdss_dsi_nt35590_720p_video`（京瓷面板）、`atmel_mxt_kc@4a`（京瓷触摸）、`kc,rcv-amp-gpio-*`（京瓷音频） |
| 配置 | `arch/arm/configs/msm8226_defconfig` |

选它而不是 LineageOS 的 3.4.113，是因为面板/触摸/传感器/音频/电源的驱动和 dts
节点全在这一棵树里，换基线就得重写这些，而它们恰好是最容易"点亮但黑屏 / 触摸失效"
的部分。3.4.113 只作为后续补丁源。

## 编译

```sh
sudo apt-get install -y gcc-arm-linux-gnueabi      # 13.3.0，Ubuntu 24.04
: > .scmversion                                     # 见下，去掉版本号里的 '+'
make ARCH=arm CROSS_COMPILE=arm-linux-gnueabi- \
     KCFLAGS="-fcommon -Wno-error -std=gnu89" -j$(nproc) zImage
```

`.scmversion` 是必须的：`CONFIG_LOCALVERSION=""` + `CONFIG_LOCALVERSION_AUTO=n` 之后，
`scripts/setlocalversion` 仍然会给不在 tag 上的树补一个 `+`，变成 `3.4.0+`；
空的 `.scmversion` 让它输出空串，`uname -r` 才是 `3.4.0`。

这一条不是洁癖：`prebuilt/mmc_protect.ko` 是原厂的，`vermagic` 写死成
`3.4.0 SMP preempt mod_unload modversions ARMv7`，而写保护仍然要靠它（见 §12.6）。
内核 release 差一个字符，`insmod` 就报 `version magic ... should be ...`。

产物 `arch/arm/boot/zImage`，5,730,752 B，MD5 `3d87f8d8c7a3153be3064c2560fa3a98`
（原厂 5,808,608 B / `40aada0058c8b0aadd00f5a5bc75166a`）。

原厂那套工具链是 gcc 4.8 era，直接拿 gcc 13 编会死在十几个点上，改动见 patch。

## 补丁

`0001-kyocera-3.4.0-build-with-gcc13-and-drop-kc-insmod-hook.patch`
（56 个文件，30 KB）分四类：

**一、拆掉 insmod 钩子（本项目的起因）**

`security/selinux/hooks.c` 把 `selinux_kernel_setup_load_info()` 改成直接
`return 0`，注册项保留（`struct security_operations` 布局不变），文件里其它
KC 策略（`hooks.c:1934/2680/2723`）一个没动。

没有采用"把 `KC_IN_SPECIAL_MODE` 宏改成 `(1)`"或"关掉
`CONFIG_SECURITY_SELINUX_KC`"，原因分别是：

* 改宏会连带放开另外三处 KC 策略，副作用不可控；
* 关 CONFIG 会编译不过也跑不了 —— `security/security.c:783` 的调用点没有
  `#ifdef` 保护，成员不再被赋值就是空指针。

编译产物验证（地址随编译变动，以 `System.map` 为准）：

```
c02ff124 <selinux_kernel_setup_load_info>:
c02ff124:  e3a00000   mov  r0, #0
c02ff128:  e12fff1e   bx   lr
```

**二、让 3.4 能在 gcc 13 下编过**

| 文件 | 改动 | 原因 |
|---|---|---|
| `include/linux/compiler-gcc13.h` | 新增 | `compiler-gcc.h` 末尾 `#include gcc_header(__GNUC__)` 会展开成 `compiler-gcc13.h`，没有这个文件每个 .c 都编不过。内容按 `GCC_VERSION` 重建（这棵树早于 `GCC_VERSION`，得自己定义），并**不定义** `__compiletime_error` —— 否则 `builtin_constant_p` 折叠差异会让几处 `ilog2()` 走到 `____ilog2_NaN()`，那些文件直接汇编失败（`.err encountered`） |
| `scripts/gcc-wrapper.py` | python2 → python3；警告不再致命 | 原版是 `print "..."`，python3 下 SyntaxError，所有编译单元失败；另外"任何警告即失败 + 删 .o"在 gcc 13 下等于要改几百个无关文件 |
| `kernel/timeconst.pl` | `defined(@val)` → `@val` | perl 5.22 起禁止 `defined(@array)`，`kernel/timeconst.h` 生成失败 |
| `arch/arm/include/asm/uaccess.h` | `get_user`/`put_user` 改走 `__get_user_err`/`__put_user_err`（纯 asm 占位符）+ `__kc_user_range_bad()` 范围检查 | 原实现用 `bl __put_user_4` + `register asm("r2")` 绑定 + `__asmeq` 断言。gcc 13 在个别文件里把值放到 r3，断言失败 → `.ifnc r3,r2 ; .err`。改成内联 asm 写法，与寄存器分配无关。**改写时踩了两个坑，见下节** |
| `make HOSTCFLAGS -fcommon` | 顶层 Makefile | gcc 10+ 默认 `-fno-common`，`scripts/dtc` 的 `yylloc` 直接重复定义 |
| `arch/arm/mm/*.S` 等 31 个 | `.section x, #alloc, #execinstr` → `.section x, "ax"` | binutils 2.42 不认 `#alloc` 这种老写法 |
| `arch/arm/mach-msm/pm-boot.c` | `__init` / `__ref` 注解 | 新 gcc 下 `msm_pm_boot_probe` 落进 `.devinit.text` 却引用 `.init.text`，modpost 报 section mismatch 并中止 |

**二·补记：改写 `get_user`/`put_user` 时踩的两个坑**

第一版改写直接导致内核起不来：`Failed to execute /init`、`Kernel panic - not syncing: No init found`，
`kernel_execve()` 返回 `-14`。原因有两个，都跟"看起来等价"有关：

1. **`addr_limit - 1` 的语义不能丢。** 本树 `KERNEL_DS == 0`（`uaccess.h:55` 的注释写着
   "actually 0x1,0000,0000"），内核线程的 `addr_limit` 就是 `0`。原实现把
   `addr_limit - 1` 传给 `__get_user_4` 这个 helper，`0 - 1` 左移成 `0xffffffff`，
   于是"上限无穷大"，内核指针（`0xc0xxxxxx`）全部放行。改用 `__range_ok()` 时传的是
   原值 `0`，`0xc0008000 + 4 > 0` 恒成立，**每个内核指针都被判越界**。

   正确判据是 `addr + sizeof(*p) - 1 <= addr_limit - 1`，且要写成
   `addr > (addr_limit - 1) - size + 1` 以避免 32 位回绕。

2. **`err` 必须从 0 起。** `__get_user_asm_word()` 的**成功路径不写 `err`**——
   只有 `.fixup` 里的 `mov %0, %3` 会写。所以 `long __gu_err = 0;` 是必须的，
   写成 `= -EFAULT` 会让每次 `get_user` 都返回 `-EFAULT`，即使读成功了。

这两个错误叠在一起的表现是：驱动全部 probe 成功、initramfs 解包正常、
`Freeing init memory` 正常，唯独 `exec /init` 返回 `-14`。定位方法是往
`init/main.c` 的 `run_init_process()`、`fs/exec.c` 的 `search_binary_handler()`
前后、`fs/binfmt_elf.c` 的每个检查点加 `pr_err`，刷一次机看 `last_kmsg`。
`KCEXEC: argc=1 envc=2` 没打出来而 `exec /init -> -14` 打出来了，
就说明败在 `count(argv)` / `copy_strings()` 里的 `get_user`。

**三、补上厂商树缺失的 include 路径**

`smd_private.h`、`oem-chg_param.h`、`oem-bms.h`、`qdsp6v2/msm-pcm-routing-v2.h`、
`mdss_mdp_trace.h` 这类"就在隔壁目录"的头文件，源码用尖括号引用，而对应
Makefile 里没有 `ccflags-y`。发布包像是漏了一批 `-I`，共 12 个目录补了
`ccflags-y += -I$(srctree)/<dir>`；`qpnp-adc-common.c`、`at24.c`、`board-8226.c`、
`msm-pcm.h` 里四条 `<../...>` 改成引号形式（相对当前文件解析）。

**四、构建开关**

`.config` 打开 `CONFIG_DEBUG_SECTION_MISMATCH=y`（仅用于看报告）。
`CONFIG_SECURITY_SELINUX_KC` 保持 `=y` —— 钩子函数还在，只是空实现。

## 复核方法

```sh
python3 tools/image/check_image.py twrp-kyl23.img --max-size 16777216 --max-fonts 1
arm-linux-gnueabi-nm vmlinux | grep selinux_kernel_setup_load_info
arm-linux-gnueabi-objdump -d --start-address=0xc02ff124 --stop-address=0xc02ff12c vmlinux
```

## 下一步

3.4.113 的稳定补丁作为第二批合入（同 3.4 大版本，`git merge` 可控）。
合之前先确认这一版在真机上能进 TWRP、能写 boot/recovery。

已确认（2026-11-07）：新内核能正常进入 TWRP，`last_kmsg` 里 `/init`、`/sbin/ueventd`、
`/sbin/healthd`、`/sbin/recovery`（PIE）、`/sbin/pigz` 全部 `search_binary_handler -> 0`，
无 panic、无 AVC denial。写保护是否消失待测。
