#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
flash_system.py — 一条命令跑完「备份 → 写 system → 清 data」的编排器

它自己不搬数据，只按顺序调两个已经验证过的工具：
    serial_dump.py      DL 模式备份
    serial_restore.py   DL 模式写回
    wipe_data.sh        在 TWRP 里格式化 /data

边界（故意不做的事）
    · 不清写保护：DL 模式本来就没有保护（aboot 还没跑）。TWRP 里的 /data 也没保护。
    · 不碰 sbl1 / aboot / misc / persist：这些分区不在流程里。
    · 不自动猜 boot 要不要一起刷：拿不准就停下来问你。

用法
    python flash_system.py --image system.img --backup
    python flash_system.py --image system.img --backup --wipe-data
    python flash_system.py --image system.img --part system --com COM13 --yes

    --backup      刷之前把现有 system 备份到 dump_stock/
    --wipe-data   写完之后进 TWRP 格式化 /data
    --boot        顺带刷 boot.img（跨大版本时必须）
    --com         COM 口，不填让 serial_restore 自己找
    --yes         不逐步确认
    --dry-run     只打印将要执行的命令
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable or "python"


def say(msg: str = "") -> None:
    print(msg, flush=True)


def step(n: int, title: str) -> None:
    say()
    say("=" * 62)
    say(f"  阶段 {n}  {title}")
    say("=" * 62)


def ask(args, prompt: str) -> bool:
    if args.yes:
        say(f"  (--yes 跳过确认) {prompt}")
        return True
    try:
        return input(f"  {prompt} [回车继续 / n 中止] ").strip().lower() not in ("n", "no")
    except (EOFError, KeyboardInterrupt):
        say("\n已中止。")
        return False


def run(args, cmd: list[str], *, check: bool = True) -> int:
    line = " ".join(cmd)
    if args.dry_run:
        say(f"  [dry-run] {line}")
        return 0
    say(f"  $ {line}")
    rc = subprocess.call(cmd)
    if rc != 0 and check:
        say(f"\n✗ 命令返回 {rc}，停下来。修好之后从这一步重跑即可。")
        raise SystemExit(rc)
    return rc


def have_adb() -> bool:
    return shutil.which("adb") is not None


def adb(*a: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["adb"] + list(a), capture_output=True, text=True, timeout=timeout)


def wait_adb(timeout: int, want_state: str | None = None) -> bool:
    """等 adb 出现；want_state 为 'recovery' 时还要匹配状态。"""
    say(f"  等待 adb 设备（最多 {timeout}s）…")
    end = time.time() + timeout
    while time.time() < end:
        try:
            out = adb("devices").stdout
        except Exception:
            out = ""
        for ln in out.splitlines()[1:]:
            parts = ln.split()
            if len(parts) >= 2 and parts[1] != "offline":
                if want_state is None or parts[1] == want_state:
                    say(f"  ✓ 看到 {parts[0]} ({parts[1]})")
                    return True
        time.sleep(2)
    say("  ✗ 等不到 adb 设备")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="刷 system + 清 data 的编排器")
    ap.add_argument("--image", required=True, help="system.img（raw 或 sparse）")
    ap.add_argument("--part", default="system")
    ap.add_argument("--boot", help="顺带刷这个 boot.img")
    ap.add_argument("--com", help="COM 口")
    ap.add_argument("--backup", action="store_true", help="先备份现有分区")
    ap.add_argument("--backup-dir", default="dump_stock")
    ap.add_argument("--wipe-data", action="store_true", help="写完进 TWRP 清 /data")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    img = os.path.abspath(args.image)
    if not os.path.exists(img):
        say(f"✗ 找不到 {img}")
        return 2
    size = os.path.getsize(img)
    say(f"镜像：{img}")
    say(f"大小：{size / 1048576:.1f} MiB")

    com = [args.com] if args.com else []

    # ---------------- 0. 提示 boot 同代问题 ----------------
    step(0, "确认 boot 与 system 同代")
    if args.part.lower() == "system":
        say("  system 里是文件系统，boot 里是内核 + ramdisk（含 init），两者必须同代。")
        say("  同版本恢复 / 同版本换 ROM → 只刷 system 就行；换 Android 大版本 → 必须带 boot。")
        if not args.boot:
            if not ask(args, "确认这次不需要换 boot？"):
                say("  那就把 ROM 包里的 boot.img 用 --boot 传进来，重跑。")
                return 0

    # ---------------- 1. 备份 ----------------
    step(1, "备份现有分区")
    if args.backup:
        os.makedirs(args.backup_dir, exist_ok=True)
        # serial_dump 的输出名是 <序号>_<分区名>.img，用后缀判断有没有备份过
        olds = [f for f in os.listdir(args.backup_dir) if f.endswith(f"_{args.part}.img")]
        if olds:
            say(f"  {args.backup_dir}/ 里已经有 {olds[0]}，跳过（要重备份就先删掉它）")
        else:
            say(f"  备份 {args.part} → {args.backup_dir}/")
            say("  1.4 GB 大概 25–60 分钟，掉线重跑同一条命令即可。")
            if not ask(args, "开始备份？"):
                return 0
            run(args, [PY, os.path.join(HERE, "serial_dump.py"), *com,
                       "--only", args.part, "--force", "--outdir", args.backup_dir])
    else:
        say("  ! 没有加 --backup。")
        say("    刷完发现新系统不对，就只能靠手上别的备份回滚了。")
        if not ask(args, "确定不备份？"):
            return 0

    # ---------------- 2. 测速（可选） ----------------
    step(2, "写入通道自检（可选）")
    rec = os.path.join(args.backup_dir, "12_recovery.img")
    if os.path.exists(rec):
        say(f"  找到 {rec}，可以先拿它试写，验证通道和速度。")
        if ask(args, "先试写 recovery？"):
            run(args, [PY, os.path.join(HERE, "serial_restore.py"), *com,
                       "--image", rec, "--part", "recovery", "--verify"])
    else:
        say("  没有 recovery 备份，跳过自检。第一次就写 1.4 GB 属于盲写，不建议。")

    # ---------------- 3. 写 boot ----------------
    if args.boot:
        step(3, "写 boot")
        say("  先刷 boot：反过来的话，boot 失败会留下「新 system + 旧内核」，")
        say("  现象是卡第一屏，看起来像 system 刷坏了，容易把排查方向带偏。")
        if not ask(args, "开始写 boot？"):
            return 0
        run(args, [PY, os.path.join(HERE, "serial_restore.py"), *com,
                   "--image", os.path.abspath(args.boot), "--part", "boot", "--verify"])

    # ---------------- 4. 写 system ----------------
    step(4, f"写 {args.part}")
    say("  不需要 --allow-critical：这个分区写坏只是开不了机，冷启动还能重进 DL 写回来。")
    rc = run(args, [PY, os.path.join(HERE, "serial_restore.py"), *com,
                    "--image", img, "--part", args.part, "--verify"], check=False)
    if rc != 0:
        say("\n✗ 写入失败。")
        say("  · 加了 --resume 从断点续写：")
        say(f"    {PY} serial_restore.py {' '.join(com)} --image {img} "
            f"--part {args.part} --resume --verify")
        say("  · 反复回读不一致 → 冷启动（拔电池）重进 DL 再试一次")
        return rc

    # ---------------- 5. 清 data ----------------
    step(5, "清 data")
    if not args.wipe_data:
        say("  跳过（没加 --wipe-data）。")
        say("  同版本 ROM 通常不用清；跨大版本不清的话 vold 起不来，会反复重启。")
        say("  想清就重跑加 --wipe-data，或者在 TWRP 里手动跑 tools/wipe_data.sh。")
        return 0

    if args.dry_run:
        say("  [dry-run] 将执行：adb reboot recovery → push wipe_data.sh → sh 执行 → adb reboot")
        return 0

    if not have_adb():
        say("  ✗ 找不到 adb。手动进 TWRP 跑 tools/wipe_data.sh 吧。")
        return 6

    say("  现在要重启进 TWRP。若 boot 与 system 不同代，这一步可能进不去，")
    say("  那就等补刷正确的 boot 之后再清。")
    if not ask(args, "重启进 TWRP？"):
        return 0

    adb("reboot", "recovery", timeout=30)
    if not wait_adb(180, "recovery"):
        say("  ✗ 没进到 recovery。")
        say("    系统能起的话，在系统里执行：")
        say("      adb shell su -c \"printf 'boot-recovery' | dd of=/dev/block/mmcblk0p26 bs=1 count=32\"")
        say("      adb reboot")
        say("    然后再重跑本脚本加 --wipe-data（或手动跑 wipe_data.sh）。")
        return 7

    local_sh = os.path.join(HERE, "wipe_data.sh")
    adb("push", local_sh, "/tmp/wipe_data.sh")
    run(args, ["adb", "shell", "sh", "/tmp/wipe_data.sh", "--dry-run"], check=False)
    if not ask(args, "上面是 dry-run 结果，确认格式化 /data？"):
        return 0
    rc = run(args, ["adb", "shell", "sh", "/tmp/wipe_data.sh"], check=False)
    if rc != 0:
        say("\n✗ 格式化没通过（大概率是挂载验证失败，内核不认文件系统特性）。")
        say("  TWRP 里手动来一遍：")
        say("    e2fsck -f -y /dev/block/mmcblk0p20")
        say("    mke2fs -t ext4 -O ^64bit -b 4096 -m 0 -L data /dev/block/mmcblk0p20")
        return rc

    # ---------------- 6. 重启 ----------------
    step(6, "重启并验收")
    if ask(args, "现在重启进系统？"):
        adb("reboot", timeout=30)
    say("  首次开机 5–15 分钟，停在 logo 是正常的。起来后验收：")
    say("    adb shell df -h /system    # 有容量")
    say("    adb shell df -h /data      # 约 5 GB")
    say("    adb shell getprop ro.build.display.id")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
