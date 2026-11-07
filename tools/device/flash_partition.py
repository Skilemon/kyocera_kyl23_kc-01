#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
flash_partition.py — 京瓷 DL 串口：把镜像直接写进 eMMC 分区

背景
    这台机器的内核层存在「按分区靶向」的写保护：往 cache（mmcblk0p21）dd
    写能成功落盘，往 recovery（mmcblk0p12）dd 写却报告 1797 块全部写完、
    sync 之后读回还是原内容，BLKROSET/CSD 都查不出只读标志。
    结论是软件层在 bio 层丢弃了目标分区的写请求。

    但 SBL 的 Sahara 通道不经过内核，之前用 0xA1 成功写回过 GPT 主表。
    本脚本就是把这个能力扩到分区级：进 DL 模式，直接从 LBA 层灌镜像。

用法
    # 只看不改：读分区现状 + 算文件哈希
    python flash_partition.py COM13 --part recovery --file test_trimmed.img --dry-run

    # 真正写入（约 6–20 分钟，取决于设备接受的写块大小）
    python flash_partition.py COM13 --part recovery --file test_trimmed.img

    # 只回读比对，确认上一次写进去的内容还在
    python flash_partition.py COM13 --part recovery --file test_trimmed.img --verify-only

    # 回滚：把原厂镜像写回去
    python flash_partition.py COM13 --part recovery --file kcbak/recovery.img

安全
    * 分区起点/长度一律从设备 GPT 实时读取，不写死
    * 只允许 recovery / boot / cache / fota / misc，其余名字直接拒绝
    * 镜像比分区大就拒绝，避免写到隔壁分区
    * 写前打印目标区头部状态（是原厂还是已裁版本），--dry-run 可先看
    * 写后回读校验：默认校验头部 + dt 段，--verify full 做全量
"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import serial_probe as P
    import serial_write as W
except ImportError:
    sys.stderr.write("需要 serial_probe.py 和 serial_write.py 在同一目录\n")
    raise SystemExit(1)

SECTOR = 512
ALLOWED = {"recovery", "boot", "cache", "fota", "misc"}
GUARDED = {"boot"}                      # 写这些要额外 --force


def describe_bootimg(blob: bytes) -> str:
    """从镜像头判断是原厂还是裁剪版。"""
    if len(blob) < 64 or blob[:8] != b"ANDROID!":
        if not any(blob):
            return "全 0（空）"
        return f"不是 Android 镜像（{P.hexdump(blob, 16)}）"
    k = struct.unpack_from("<I", blob, 8)[0]
    r = struct.unpack_from("<I", blob, 16)[0]
    dt = struct.unpack_from("<I", blob, 40)[0]
    page = struct.unpack_from("<I", blob, 36)[0]
    tag = "裁剪版（dt 已裁）" if dt < 1_000_000 else "原厂（dt 完整 5.18MB）"
    return (f"{tag}  kernel={k:,} ramdisk={r:,} dt={dt:,} page={page}")


def find_part(parts: list[dict], name: str) -> dict | None:
    for p in parts:
        if p["name"].lower() == name.lower():
            return p
    return None


def write_image(link: P.SerialLink, start_lba: int, data: bytes,
                chunk: int = 4096) -> int:
    """按 0xA1 写整段，自动降块。返回最终使用的块大小。"""
    total = len(data)
    off = 0
    t0 = time.time()
    last_report = 0.0
    start_chunk = chunk

    while off < total:
        n = min(chunk, total - off)
        n -= n % SECTOR
        if n <= 0:
            break
        while True:
            try:
                W.vendor_write(link, start_lba + off // SECTOR,
                               data[off:off + n], retries=1)
                break
            except Exception as exc:
                if chunk <= SECTOR:
                    raise SystemExit(f"\n✗ 写 LBA {start_lba + off // SECTOR} 失败：{exc}")
                chunk //= 2
                chunk -= chunk % SECTOR
                n = min(chunk, total - off)
                n -= n % SECTOR
                sys.stdout.write(f"\n    ↓ 写块降到 {chunk} B（{exc}）\n")
        off += n

        now = time.time()
        if now - last_report > 1.0 or off >= total:
            last_report = now
            pct = off * 100 // total
            speed = off / max(now - t0, 1e-6) / 1024
            eta = (total - off) / max(off / max(now - t0, 1e-6), 1)
            sys.stdout.write(f"\r    写入 {off:,}/{total:,} B ({pct}%) "
                             f"{speed:.0f} KB/s  剩 {eta:.0f}s")
            sys.stdout.flush()

    sys.stdout.write("\n")
    if chunk != start_chunk:
        print(f"  ⓘ 写块从 {start_chunk} B 降到 {chunk} B")
    return chunk


def verify_range(link: P.SerialLink, payload: int, start_lba: int,
                 expect: bytes, label: str, chunk: int = 1024) -> bool:
    print(f"\n  回读校验 {label}（{len(expect):,} B）…")
    got = P.read_range(link, start_lba, len(expect), payload, chunk=chunk)
    if got == expect:
        print(f"  ✓ {label} 逐字节一致")
        return True
    diff = sum(1 for a, b in zip(got, expect) if a != b)
    first = next(i for i, (a, b) in enumerate(zip(got, expect)) if a != b)
    print(f"  ✗ {label} 有 {diff:,} 字节不同，首个差异在 offset {first:,}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="京瓷 DL 串口：写入指定分区")
    ap.add_argument("port", nargs="?", help="COM 口，不填自动检测")
    ap.add_argument("--part", required=True, help="分区名，如 recovery")
    ap.add_argument("--file", required=True, help="要写入的镜像")
    ap.add_argument("--dry-run", action="store_true", help="只看不写")
    ap.add_argument("--verify-only", action="store_true", help="只回读比对")
    ap.add_argument("--force", action="store_true", help="写 boot 等受保护分区时必需")
    ap.add_argument("--write-chunk", type=int, default=4096, help="初始写块，默认 4096")
    ap.add_argument("--verify", choices=["head", "full"], default="head",
                    help="校验范围：head=头部+dt段（默认），full=整个镜像")
    args = ap.parse_args()

    name = args.part.lower()
    if name not in ALLOWED:
        print(f"✗ 只允许写 {', '.join(sorted(ALLOWED))}，拒绝 {args.part}")
        return 2
    if name in GUARDED and not args.force:
        print(f"✗ {name} 属于关键分区，确认无误请加 --force")
        return 2
    if not os.path.isfile(args.file):
        print(f"✗ 文件不存在：{args.file}")
        return 2

    data = open(args.file, "rb").read()
    print(f"\n镜像：{args.file}")
    print(f"       {len(data):,} B   sha256 {hashlib.sha256(data).hexdigest()[:32]}…")
    print(f"       头部：{describe_bootimg(data[:2048])}")

    port = args.port
    if not port:
        cands = [p for p in P.port_candidates() if p[0] >= 5]
        if not cands:
            print("\n没找到京瓷串口：")
            P.show_ports()
            return 1
        port = cands[0][1].device
        print(f"自动选中 {port}（{cands[0][1].description}）")

    ser = P.serial.Serial(port, 115200, timeout=2.0, write_timeout=12.0)
    ser.dtr = False
    ser.rts = False
    link = P.SerialLink(ser, timeout=3.0)

    try:
        print(f"\n=== {port} @ 115200 ===")
        payload, _ = P.handshake(link, ser)

        print("\n读取分区表…")
        parts = P.parse_gpt(link, payload)
        if not parts:
            print("✗ 分区表读不出来，先确认设备在 DL 模式且主表完好")
            return 3

        part = find_part(parts, name)
        if not part:
            print(f"✗ 表里没有名为 {name} 的分区")
            return 3
        start, cnt = part["first"], part["sectors"]
        cap = cnt * SECTOR
        print(f"\n目标：{name}  @LBA {start:,}  {cnt:,} 扇区  {cap:,} B "
              f"({cap / 1048576:.2f} MB)")
        if len(data) > cap:
            print(f"✗ 镜像 {len(data):,} B 超过分区 {cap:,} B，拒绝（会写穿到隔壁分区）")
            return 4
        print(f"      写入占分区 {len(data) * 100 / cap:.1f}%，"
              f"尾部 {cap - len(data):,} B 不动")

        head_now = P.vendor_read(link, start, 2048)
        print(f"\n分区现状：{describe_bootimg(head_now)}")

        if args.verify_only:
            ok = True
            if args.verify == "full":
                ok &= verify_range(link, payload, start, data, "整个镜像")
            else:
                ok &= verify_range(link, payload, start, data[:2048], "头部 2KB")
                if len(data) > 2048:
                    dt_off = 2048
                    k = struct.unpack_from("<I", data, 8)[0]
                    r = struct.unpack_from("<I", data, 16)[0]
                    pg = lambda n: ((n + 2047) // 2048) * 2048
                    dt_off = 2048 + pg(k) + pg(r)
                    dt_len = struct.unpack_from("<I", data, 40)[0]
                    if dt_len and dt_off + dt_len <= len(data):
                        ok &= verify_range(link, payload, start + dt_off // SECTOR,
                                           data[dt_off:dt_off + dt_len],
                                           f"dt 段 @0x{dt_off:X}")
            print("\n结论：" + ("✓ 分区内容与文件一致" if ok else "✗ 不一致，需要重写"))
            return 0 if ok else 5

        if args.dry_run:
            print("\n演练结束（未写入）。去掉 --dry-run 开始写。")
            return 0

        print(f"\n开始写入 {len(data):,} B 到 LBA {start:,}…")
        t0 = time.time()
        used = write_image(link, start, data, chunk=args.write_chunk)
        print(f"  用时 {time.time() - t0:.0f}s，最终写块 {used} B")

        print("\n回读校验…")
        ok = True
        if args.verify == "full":
            ok &= verify_range(link, payload, start, data, "整个镜像")
        else:
            ok &= verify_range(link, payload, start, data[:2048], "头部 2KB")
            k = struct.unpack_from("<I", data, 8)[0]
            r = struct.unpack_from("<I", data, 16)[0]
            pg = lambda n: ((n + 2047) // 2048) * 2048
            dt_off = 2048 + pg(k) + pg(r)
            dt_len = struct.unpack_from("<I", data, 40)[0]
            if dt_len and dt_off + dt_len <= len(data):
                ok &= verify_range(link, payload, start + dt_off // SECTOR,
                                   data[dt_off:dt_off + dt_len],
                                   f"dt 段 @0x{dt_off:X}")

        print()
        if ok:
            print("✓ 写入成功。现在拔 USB → 取电池 → 拔 SD 卡 → 装电池，"
                  "按住键序进 recovery。")
            print("  进 recovery 后立刻重启回系统，用 verify_recovery.ps1 确认"
                  "分区没被改写。")
        else:
            print("✗ 校验不通过。分区可能只写了一半。")
            print("  不要重启进系统，直接再跑一次本脚本；")
            print(f"  或回滚：python flash_partition.py {port} --part {name} "
                  f"--file kcbak/recovery.img")
        return 0 if ok else 5

    finally:
        ser.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n用户中断")
        sys.exit(130)
