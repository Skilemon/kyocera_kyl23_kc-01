#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dtimg.py — 从原厂镜像的 dt 段里，只捞出本机需要的那几份 DTB，重建成一个小 dt.img

为什么要做这个
    KC-01/KYL23 的 dt 段有 5,179,392 B，塞了 32 份高通公版 DTB（CDP/FLUID/
    MTP/QRD/Simulator，8226/8926/apq8026 全平台都在）。而 recovery 分区只有
    16 MiB，kernel 5.8 MB + 原厂 dt 5.18 MB 之后只剩 5.5 MB 给 ramdisk，
    TWRP 的 ramdisk 根本塞不进去。
    真机只用得上其中一两份，裁掉其余的，dt 段能从 5.18 MB 降到 320 KB。

匹配规则（aboot 的做法）
    拿 (msm-id, board-id, soc_rev) 三元组去 QCDT 表里逐条比，全等才取那份 DTB。
      msm-id    : MSM8926 = 200，同族还有 224
      board-id  : 从 /sys/devices/soc0/hw_platform 读，MTP = 8
      soc_rev   : 0 / 2，跟 SoC 版本有关，不确定就把几种都留下

用法
    # 先看原厂 dt 段里都有什么
    python dtimg.py recovery.img --list

    # 捞出 MTP 的两份（soc_rev 0 和 2），msm-id 200/224 双写，最大化兼容
    python dtimg.py recovery.img --board-id 8 --msm-id 200,224 -o kc01_dt.img

    # 直接把 dt 段替换回镜像（顺带检查总大小）
    python dtimg.py recovery.img --board-id 8 -o kc01_dt.img --patch boot.img -O test.img
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_bootimg as C          # noqa: F401  (保留给 load_dt 复用)
import repack_bootimg as R

HDR = 16          # QCDT ASCII v2 头：magic(4) ver(4) count(4) entry_size(4)
ENT = 24          # 每条：5 个 u32 + 4 字节 padding


def get_dt_segment(image: str) -> tuple:
    h = R.read_header(image)
    if not h["dt_size"]:
        raise SystemExit(f"✗ {image} 头部 dt_size=0，没有单独的 dt 段")
    with open(image, "rb") as fh:
        fh.seek(h["dt_off"])
        return fh.read(h["dt_size"]), h


def parse_entries(blob: bytes) -> list:
    """按 QCDT ASCII v2 解析；用「offset 是否落在真实 FDT 上」来验证布局

    注意：头部第 4 个字段（offset 12）在本机的 dt.img 里是 0x91=145，
    并不是条目长度。真实条目长度要靠命中率反推，2024 年以前的 QC 工具
    在 v2 上用过 20/24/32 三种，这里逐个试，选命中最高的。
    """
    if blob[:4] != b"QCDT":
        raise SystemExit(f"✗ dt 段不是 QCDT 格式（开头 {blob[:8].hex(' ')}）")
    fdt_offs = {f["off"] for f in C.scan_fdts(blob)}
    ver, count, declared = struct.unpack_from("<3I", blob, 4)

    best = None
    for esz in (24, 20, 32, 28):
        rows, hit = [], 0
        for i in range(count):
            base = HDR + i * esz
            if base + 20 > len(blob):
                break
            a, b, c, off, sz = struct.unpack_from("<5I", blob, base)
            ok = off in fdt_offs
            hit += ok
            rows.append({"i": i, "a": a, "b": b, "soc": c, "off": off,
                         "size": sz, "ok": ok, "esz": esz})
        if rows and (best is None or hit > best[0]):
            best = (hit, rows, esz)
    if not best:
        raise SystemExit("✗ 解析不出条目")
    hit, rows, esz = best
    print(f"  条目长度按 {esz} B 解析，{hit}/{len(rows)} 条命中")
    if hit < len(rows) // 2:
        raise SystemExit("✗ 表布局没对上，先别用这个文件")
    return rows


def build(entries: list, blobs: dict, out_path: str) -> dict:
    """entries: [(msm_id, board_id, soc_rev, key)]，blobs: {key: bytes}"""
    n = len(entries)
    head = struct.pack("<4I", 0x54444351, 2, n, ENT)
    table = bytearray()
    # 数据区从头部之后 2048 对齐开始，跟原厂习惯一致
    data_start = R.pg(HDR + n * ENT, 2048)
    off = data_start
    placed = {}
    for (mid, bid, soc, key) in entries:
        if key not in placed:
            placed[key] = off
            off += R.pg(len(blobs[key]), 2048)
        table += struct.pack("<5I", mid, bid, soc, placed[key], len(blobs[key])) + b"\x00" * 4

    buf = bytearray(head + table)
    buf += b"\x00" * (data_start - len(buf))
    for key, start in sorted(placed.items(), key=lambda x: x[1]):
        assert len(buf) == start, (len(buf), start)
        buf += blobs[key]
        buf += b"\x00" * (R.pg(len(blobs[key]), 2048) - len(blobs[key]))

    with open(out_path, "wb") as fh:
        fh.write(bytes(buf))
    return {"size": len(buf), "entries": n, "unique": len(placed)}


def main() -> int:
    ap = argparse.ArgumentParser(description="从原厂 dt 段裁剪出只含本机 DTB 的小 dt.img")
    ap.add_argument("image", help="原厂 boot.img / recovery.img")
    ap.add_argument("--list", action="store_true", help="列出 dt 段里所有条目")
    ap.add_argument("--model", default="8926 MTP",
                    help="按 DTB 里的 model 字符串筛选（默认 '8926 MTP'）")
    ap.add_argument("--board-id", default="", help="额外按 board-id 过滤，逗号分隔")
    ap.add_argument("--soc-rev", default="", help="额外按 soc_rev 过滤，留空表示全留")
    ap.add_argument("-o", "--out", help="输出的 dt.img")
    ap.add_argument("--patch", metavar="IMG", help="把新 dt 段写回这个镜像")
    ap.add_argument("-O", dest="out_img", help="--patch 的输出镜像路径")
    args = ap.parse_args()

    blob, h = get_dt_segment(args.image)
    print(f"\n{os.path.basename(args.image)} 的 dt 段")
    print(f"  {h['dt_size']:,} B @{h['dt_off']:,}   QCDT v2")
    rows = parse_entries(blob)

    if args.list:
        fdt = {f["off"]: f for f in C.scan_fdts(blob)}
        print(f"\n  {'#':>3} {'a':>7} {'b':>4} {'soc':>7} {'off':>9} {'size':>8}  model")
        print("  " + "-" * 88)
        for r in rows:
            f = fdt.get(r["off"])
            m = (f["models"][0] if f and f["models"] else "?")
            print(f"  {r['i']:>3} {r['a']:>7} {r['b']:>4} {r['soc']:>7} "
                  f"{r['off']:>9} {r['size']:>8}  {m}")
        return 0

    fdt = {f["off"]: f for f in C.scan_fdts(blob)}
    want_bid = {int(x, 0) for x in args.board_id.split(",") if x.strip()}
    want_soc = {int(x, 0) for x in args.soc_rev.split(",") if x.strip()}

    def model_of(off):
        f = fdt.get(off)
        return " ".join(f["models"]) if f and f["models"] else ""

    sel = [r for r in rows
           if r["ok"] and args.model.lower() in model_of(r["off"]).lower()
           and (not want_bid or r["a"] in want_bid)
           and (not want_soc or r["soc"] in want_soc)]
    if not sel:
        raise SystemExit("✗ 没有匹配的条目，用 --list 看看表里都有什么")

    blobs = {}
    for r in sel:
        key = r["off"]
        blobs[key] = blob[r["off"]:r["off"] + r["size"]]

    entries = [(r["a"], r["b"], r["soc"], r["off"]) for r in sel]
    stats = build(entries, blobs, args.out)
    saving = h["dt_size"] - stats["size"]
    print(f"\n保留 {stats['entries']} 条条目、{stats['unique']} 份 DTB：")
    for r in sel:
        print(f"  msm-id={r['a']} board-id={r['b']} soc_rev={r['soc']}  "
              f"{r['size']:,} B")
    print(f"\n已写出 {args.out}  {stats['size']:,} B")
    print(f"  原 dt 段 {h['dt_size']:,} B → {stats['size']:,} B，"
          f"省下 {saving:,} B（{saving/1048576:.2f} MB）")

    if args.patch:
        src_h = R.read_header(args.patch)
        parts = R.read_parts(args.patch, src_h)
        parts["dt"] = open(args.out, "rb").read()
        out_img = args.out_img or (args.patch + ".new.img")
        st = R.build(src_h, parts, out_img)
        print(f"\n已写出 {out_img}  总大小 {st['size']:,} B")
        print(f"  ramdisk 可用余量 {16777216 - st['size']:,} B"
              f"（按 16 MiB 分区算）")
        print(f"  kernel {st['kernel']:,} / ramdisk {st['ramdisk']:,} / dt {st['dt']:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
