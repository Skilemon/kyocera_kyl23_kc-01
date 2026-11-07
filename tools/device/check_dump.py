#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_dump.py — 分区 dump 体检（本地 PC 跑，不连设备）

回答三个问题：
    1. 这个文件是不是某个分区该有的东西（magic / 大小对不对）
    2. 有没有备份成空文件（dd 权限不足时常见，全 0 但大小正常）
    3. 和 GPT 表里记录的分区大小是否吻合

用法
    python check_dump.py D:\\KC-01\\backup
    python check_dump.py D:\\KC-01\\backup --gpt dump\\gpt_entries.bin
    python check_dump.py D:\\KC-01\\backup --hash          # 算完整 SHA-256（大文件慢）

判读
    magic 一栏写「?」且非零比例很低  → 文件可能有，但不像该分区的开头，dd 起止位置可能不对
    magic 写「全 0」                  → dd 读失败（多半是权限问题），文件是废的
    大小与 GPT 不符                   → dd 用了错误的 bs/count，或读的是符号链接指向的别处
"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys
import zlib

SECTOR = 512

# KC-01 / KYL23 的完整分区表（来自本机备份 GPT，单位：字节）
KC01_SIZES = {
    "modem": 67108864, "sbl1": 1048576, "sbl1bak": 1048576, "sdi": 1048576,
    "aboot": 2097152, "abootbak": 2097152, "rpm": 1048576, "rpmbak": 1048576,
    "boot": 16777216, "tz": 1048576, "tzbak": 1048576, "recovery": 16777216,
    "fota": 16777216, "fotabk": 16777216, "sdibk": 1048576, "abootbk": 2097152,
    "rpmbk": 1048576, "tzbk": 1048576, "system": 1472200704,
    "userdata": 5468323840, "cache": 480378880, "log": 20971520,
    "logwork": 20971520, "bootwork": 4194304, "rom": 4194304, "misc": 6291456,
    "ddr": 1048576, "fsg": 8388608, "fsc": 1048576, "ssd": 1048576,
    "pad": 1048576, "carrier": 8388608, "fotamng": 4194304,
    "reserve1": 104857600, "persist": 8388608, "dnand": 8388608,
    "sysprop": 8388608, "modemst1": 1572864, "modemst2": 1572864,
    "bfss1": 4194304, "bfss2": 8388608, "sysprop2": 8388608,
    "reserve2": 6274560,
}

# 原厂就没写内容的槽位/预留区，全 0 是正常的（不是 dd 失败）
KC01_EMPTY_OK = {"ddr", "fsc", "logwork", "pad", "reserve1", "reserve2",
                 "rom", "rpmbk", "sdibk", "ssd", "tzbk", "misc"}
MAGICS = [
    (b"ANDROID!", "boot/recovery"),
    (b"EFI PART", "GPT头"),
    (b"MSDOS5.0", "FAT16"),
    (b"\xeb\x3c\x90", "FAT"),
    (b"\xe2\xe1\xf5\xe0", "exFAT"),
    (b"\xd1\xdc\x4a\x1e", "高通MBN"),
    (b"UBI#", "UBI"),
    (b"\x27\x05\x19\x56", "uImage"),
    (b"\x1f\x8b\x08", "gzip"),
    (b"BZh", "bzip2"),
    (b"\xfd7zXZ", "xz"),
]


def sniff(head: bytes, size: int) -> str:
    if not any(head):
        return "全 0"
    for magic, name in MAGICS:
        if head.startswith(magic):
            return name
    # ext2/3/4: superblock @0x438 的 s_magic = 0xEF53
    if len(head) > 0x43A and head[0x438:0x43A] == b"\x53\xef":
        return "ext4"
    if head.startswith(b"\x7fELF"):
        return "ELF"
    if len(head) > 1024 and head[1024:1026] == b"\x53\xef":
        return "ext4(off1k)"
    printable = sum(1 for b in head[:64] if 32 <= b < 127)
    return f"?({printable}/64可打印)" if printable > 48 else "?"


def nonzero_ratio(path: str, size: int, samples: int = 24) -> float:
    """抽样估算非零比例：每个采样点读 4KB。"""
    if size == 0:
        return 0.0
    step = max(4096, size // samples)
    hit = total = 0
    with open(path, "rb") as fh:
        off = 0
        while off < size:
            fh.seek(off)
            blk = fh.read(min(4096, size - off))
            if not blk:
                break
            total += 1
            if any(blk):
                hit += 1
            off += step
    return hit / total if total else 0.0


def parse_gpt_entries(path: str) -> dict[str, int]:
    """从 gpt_entries.bin 读 分区名 -> 字节大小。"""
    with open(path, "rb") as fh:
        blob = fh.read()
    if len(blob) < 128:
        return {}
    out: dict[str, int] = {}
    esz = 128
    num = len(blob) // esz
    for i in range(num):
        e = blob[i * esz:(i + 1) * esz]
        if e[:16] == b"\x00" * 16:
            continue
        first = struct.unpack_from("<Q", e, 32)[0]
        last = struct.unpack_from("<Q", e, 40)[0]
        name = e[56:128].decode("utf-16-le", "ignore").rstrip("\x00").strip()
        if name:
            out[name.lower()] = (last - first + 1) * SECTOR
    return out


def human(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024 or unit == "G":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}G"


def main() -> int:
    ap = argparse.ArgumentParser(description="分区 dump 体检")
    ap.add_argument("dir", help="dump 所在目录")
    ap.add_argument("--gpt", help="gpt_entries.bin 路径，用于核对分区大小")
    ap.add_argument("--hash", action="store_true", help="计算完整 SHA-256")
    ap.add_argument("--profile", choices=["kc01"], help="内置机型分区表（免 --gpt）")
    args = ap.parse_args()

    if not os.path.isdir(args.dir):
        print(f"目录不存在：{args.dir}")
        return 2

    empty_ok: set[str] = set()
    if args.profile == "kc01":
        gpt = dict(KC01_SIZES)
        empty_ok = KC01_EMPTY_OK
    else:
        gpt = parse_gpt_entries(args.gpt) if args.gpt and os.path.exists(args.gpt) else {}
    if args.gpt and not gpt:
        print(f"⚠ 读不出分区表：{args.gpt}")

    files = sorted(
        f for f in os.listdir(args.dir)
        if os.path.isfile(os.path.join(args.dir, f))
        and f.lower().endswith((".img", ".bin", ".dd", ".raw"))
    )
    if not files:
        print("目录里没有 .img/.bin/.dd/.raw 文件")
        return 1

    print(f"\n目录：{args.dir}")
    if args.profile:
        print(f"机型配置：{args.profile}（{len(gpt)} 个分区，"
              f"{len(empty_ok)} 个槽位允许为空）")
    elif gpt:
        print(f"参考分区表：{args.gpt}（{len(gpt)} 个分区）")
    print()
    print(f"  {'文件':<22}{'大小':>9}  {'非零':>5}  {'magic':<16}{'GPT':<10}SHA256")
    print("  " + "-" * 82)

    problems = 0
    for fn in files:
        path = os.path.join(args.dir, fn)
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            head = fh.read(2048)
        magic = sniff(head, size)
        ratio = nonzero_ratio(path, size)

        stem = os.path.splitext(fn)[0].lower()
        key = stem.split("_")[-1] if "_" in stem else stem
        note = "-"
        if gpt:
            want = gpt.get(key) or gpt.get(stem)
            if want is None:
                note = "未在表中"
            elif want == size:
                note = "✓"
            else:
                note = f"✗ 应{human(want)}"
                problems += 1
        elif size % SECTOR:
            note = "非512倍数"
            problems += 1

        if magic == "全 0" and key in empty_ok:
            note = "空(正常)"

        digest = ""
        if args.hash:
            h = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            digest = h.hexdigest()[:16]

        flag = " "
        if magic == "全 0" and key not in empty_ok:
            flag = "!"
            problems += 1
        elif ratio < 0.02 and magic.startswith("?"):
            flag = "!"
            problems += 1
        print(f" {flag}{fn:<21}{human(size):>9}  {ratio * 100:>4.0f}%  "
              f"{magic:<16}{note:<10}{digest}")

    print()
    if problems:
        print(f"⚠ {problems} 个文件有问题，标了 ! 或 GPT ✗ 的要重新 dd")
        print("  常见原因：su 没生效（读出来是全 0）、dd 的 bs/count 算错、"
              "用的是 by-name 符号链接但解析到了错误的块设备")
    else:
        print("✓ 全部通过：大小与 GPT 一致、magic 正常、非零比例合理")
    print("\n提醒：文件存在 ≠ 能写回去。如果目标分区有 eMMC 写保护，"
          "恢复时照样会被丢数据，先用「原样写回再读比对」验证。")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
