#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_bootimg.py — 比对 boot/recovery 镜像的头部参数与内嵌 DT（设备树）

刷自制 recovery（TWRP 等）之前先跑一遍。它回答两个问题：
  1. 内存布局参数（kernel_addr / ramdisk_addr / tags_addr / page_size）是否一致
     —— 不一致，aboot 加载后立刻跑飞，必然失败
  2. 追加的 DT 里，有没有和原厂相同的那份 DTB
     —— 没有，LK 会报 "Device tree not found"，同样起不来

DT 表的封装格式在不同代 Qualcomm 工具链上不一样（0x00564400 / "QCDT" 两种魔数，
表头 16~40 字节不定），所以这里不做硬编码假设：先按一批候选布局试探，用
「条目里的 offset 是否正好落在一份 FDT 上」验证，取命中最好的那种。表头全试不
通时退化成直接扫 FDT 魔数，按 DTB 内容哈希比对——这条路不依赖表头，最稳。

用法
    python check_bootimg.py 原厂recovery.img 自制.img            # 头部对比
    python check_bootimg.py 原厂recovery.img 自制.img --dt       # 追加 DT 对比
    python check_bootimg.py 自制.img --dt --raw                  # 附 DT 段前 64 字节
    python check_bootimg.py 自制.img                             # 只看单文件

判读
    地址类全部 ✓、DT 有共有 DTB  → 参数层面没问题，可以试刷
    地址不一致                   → 别刷，改 boardconfig 重新打包
    DT 无共有 DTB                → 别刷，LK 找不到本机 DTB
"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys

PAGE_CANDIDATES = (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536)
FDT_MAGIC = b"\xd0\x0d\xfe\xed"
QCDT_ASCII = b"QCDT"
QCDT_LE = 0x00564400

HARD_KEYS = ("kernel_addr", "ramdisk_addr", "second_addr", "tags_addr", "page_size")


# ---------------------------------------------------------------- 头部解析

def parse(path: str) -> dict:
    with open(path, "rb") as fh:
        raw = fh.read(4096)
    if len(raw) < 64:
        return {"error": "文件太短"}
    if raw[:8] != b"ANDROID!":
        return {"error": f"不是 boot 镜像（开头 {raw[:8].hex(' ')}）"}

    d = {
        "path": path,
        "size": os.path.getsize(path),
        "kernel_size": struct.unpack_from("<I", raw, 8)[0],
        "kernel_addr": struct.unpack_from("<I", raw, 12)[0],
        "ramdisk_size": struct.unpack_from("<I", raw, 16)[0],
        "ramdisk_addr": struct.unpack_from("<I", raw, 20)[0],
        "second_size": struct.unpack_from("<I", raw, 24)[0],
        "second_addr": struct.unpack_from("<I", raw, 28)[0],
        "tags_addr": struct.unpack_from("<I", raw, 32)[0],
        "page_size": struct.unpack_from("<I", raw, 36)[0],
        "f40": struct.unpack_from("<I", raw, 40)[0],
        "f44": struct.unpack_from("<I", raw, 44)[0],
        "name": raw[48:64].split(b"\x00")[0].decode("ascii", "replace"),
        "cmdline": raw[64:576].split(b"\x00")[0].decode("ascii", "replace"),
        "head": raw[:64],
    }
    # 高通布局里 offset 40 是 dt_size；AOSP v1+ 是 header_version，靠取值区分
    d["header_version"] = d["f40"] if d["f40"] <= 4 else None
    d["dt_size"] = d["f40"] if d["f40"] > 4 else 0
    d["os_version"] = d["f44"] if d["header_version"] is not None else 0
    d["page_ok"] = d["page_size"] in PAGE_CANDIDATES
    if d["page_ok"]:
        ps = d["page_size"]

        def pg(n):
            return ((n + ps - 1) // ps) * ps if n else 0

        d["expect_size"] = (ps + pg(d["kernel_size"]) + pg(d["ramdisk_size"])
                            + pg(d["second_size"]) + pg(d["dt_size"]))
        d["dt_off"] = (ps + pg(d["kernel_size"]) + pg(d["ramdisk_size"])
                       + pg(d["second_size"]))
    else:
        d["expect_size"] = None
        d["dt_off"] = None
    return d


def kernel_hint(path: str, d: dict) -> str:
    if not d["page_ok"] or not d["kernel_size"]:
        return "空"
    try:
        with open(path, "rb") as fh:
            fh.seek(d["page_size"])
            head = fh.read(64)
    except OSError:
        return "读取失败"
    if head[:2] == b"\x1f\x8b":
        return "gzip 压缩内核"
    if head[:4] == b"\x7fELF":
        return "ELF"
    if len(head) >= 0x28 and struct.unpack_from("<I", head, 0x24)[0] == 0x016f2818:
        return "ARM zImage"
    if head[:8] == b"ANDROID!":
        return "嵌套 boot 镜像？"
    return f"?（{head[:4].hex(' ')}）"


# ---------------------------------------------------------------- FDT 解析

def walk_fdt(blob: bytes) -> list:
    """返回 [(节点路径, 属性名, 字符串列表), ...]，只取 model / compatible"""
    if blob[:4] != FDT_MAGIC or len(blob) < 40:
        return []
    (totalsize, off_struct, off_strings, _rsv, _ver, _lastcomp,
     _cpuid, _ss, _sst) = struct.unpack_from(">9I", blob, 4)

    out, path = [], []
    pos = off_struct
    limit = min(len(blob), totalsize)
    if off_struct >= limit:
        return []
    while pos + 4 <= limit:
        tok = struct.unpack_from(">I", blob, pos)[0]
        pos += 4
        if tok == 1:                                    # FDT_BEGIN_NODE
            end = blob.find(b"\x00", pos, limit)
            if end < 0:
                break
            path.append(blob[pos:end].decode("utf-8", "replace"))
            pos = (end + 1 + 3) & ~3
        elif tok == 2:                                  # FDT_END_NODE
            if path:
                path.pop()
        elif tok == 3:                                  # FDT_PROP
            if pos + 8 > limit:
                break
            ln, nameoff = struct.unpack_from(">2I", blob, pos)
            pos += 8
            val = blob[pos:pos + ln]
            pos = (pos + ln + 3) & ~3
            ns = off_strings + nameoff
            ne = blob.find(b"\x00", ns, limit)
            if ne < 0:
                break
            pname = blob[ns:ne].decode("utf-8", "replace")
            if pname in ("model", "compatible"):
                out.append(("/" + "/".join(path) if path else "/", pname,
                            [s for s in val.split(b"\x00") if s]))
        elif tok == 4:                                  # FDT_NOP
            continue
        elif tok == 9:                                  # FDT_END
            break
        else:
            break
    return out


def fdt_models(blob: bytes) -> list:
    res = []
    for _node, _prop, vals in walk_fdt(blob):
        for v in vals:
            s = v.decode("utf-8", "replace").strip()
            if s and s not in res:
                res.append(s)
        if len(res) >= 3:
            break
    return res[:3]


def scan_fdts(blob: bytes) -> list:
    """扫描 DT 段里所有 FDT，返回 [{off, size, models, sha}]"""
    res, i, n = [], 0, len(blob)
    while True:
        i = blob.find(FDT_MAGIC, i)
        if i < 0 or i + 40 > n:
            break
        total = struct.unpack_from(">I", blob, i + 4)[0]
        if 64 <= total <= n - i:
            sub = blob[i:i + total]
            res.append({"off": i, "size": total, "models": fdt_models(sub),
                        "sha": hashlib.sha256(sub).hexdigest()[:16]})
            i += total
        else:
            i += 4
    return res


# ---------------------------------------------------------------- DT 段解析

def _eval_layout(blob: bytes, eoff: int, esize: int, count: int, fdts: set) -> list:
    """按给定布局解析条目；hit 表示 offset 正好落在一份真实 FDT 上"""
    if not (16 <= eoff <= 512) or not (16 <= esize <= 256) or not (1 <= count <= 128):
        return []
    if eoff + count * esize > len(blob):
        return []
    out = []
    for i in range(count):
        base = eoff + i * esize
        if base + 20 > len(blob):
            break
        plat, var, soc, off, sz = struct.unpack_from("<5I", blob, base)
        ok = sz > 0 and off + sz <= len(blob) and off in fdts
        out.append({"platform": plat, "variant": var, "soc": soc,
                    "offset": off, "size": sz, "hit": ok})
    return out


def parse_table(blob: bytes, fdts: list) -> tuple:
    """返回 (kind, entries)；entries 为 None 表示布局没试通"""
    if blob[:4] == FDT_MAGIC:
        return ("单份 FDT", [])

    fset = {f["off"] for f in fdts}
    best = None

    def consider(kind, eoff, esize, count, declared=None):
        nonlocal best
        cand = _eval_layout(blob, eoff, esize, count, fset)
        if not cand:
            return
        hits = sum(1 for c in cand if c["hit"])
        if hits < max(1, len(cand) // 2):
            return
        # 命中数优先；其次条目数与 FDT 数吻合；再优先表头自报的 entry_size
        key = (hits, -abs(len(cand) - len(fdts)),
               1 if declared is not None and esize == declared else 0)
        if best is None or key > best[0]:
            best = (key, cand, kind)

    if blob[:4] == QCDT_ASCII:
        ver = struct.unpack_from("<I", blob, 4)[0]
        n1 = struct.unpack_from("<I", blob, 8)[0]
        n2 = struct.unpack_from("<I", blob, 12)[0]
        declared = n2 if 16 <= n2 <= 256 else None
        for count in {n1, n2, len(fdts)}:
            for eoff in (16, 20, 24, 28, 32, 40, 48, 64):
                for esize in (24, 32, 40, 48, 64):
                    consider(f'QCDT(ASCII) v{ver} / 表头 {eoff}B / 条目 {esize}B',
                             eoff, esize, count, declared)
    elif struct.unpack_from("<I", blob, 0)[0] == QCDT_LE:
        _t, hsize, esize, count, eoff, ver, _r = struct.unpack_from("<7I", blob, 4)
        for e in {eoff, hsize, 32, 40}:
            for s in {esize, 32, 40, 64}:
                consider(f"QCDT(0x00564400) v{ver} / 表头 {e}B / 条目 {s}B",
                         e, s, count, esize)

    if best is None:
        return ("未知表头", None)
    entries = [c for c in best[1] if c["hit"]]
    return (best[2], entries)


def load_dt(path: str, d: dict) -> dict:
    info = {"ok": False, "reason": "", "size": d["dt_size"], "off": d["dt_off"],
            "kind": "?", "entries": None, "fdts": [], "head": b""}
    if not d["dt_off"] or not d["dt_size"]:
        info["reason"] = "头部 dt_size=0，没有追加 DT"
        return info
    end = d["dt_off"] + d["dt_size"]
    if os.path.getsize(path) < end:
        info["reason"] = (f"文件只有 {os.path.getsize(path):,} B，"
                          f"装不下 DT（需要到 {end:,} B）")
        return info

    with open(path, "rb") as fh:
        fh.seek(d["dt_off"])
        blob = fh.read(d["dt_size"])
    if len(blob) < 32:
        info["reason"] = "DT 段太短"
        return info

    info["head"] = blob[:64]
    info["fdts"] = scan_fdts(blob)
    info["kind"], info["entries"] = parse_table(blob, info["fdts"])
    info["ok"] = bool(info["fdts"]) or info["entries"] is not None
    if not info["ok"]:
        info["reason"] = f"DT 段开头 {blob[:8].hex(' ')}，既无 FDT 也无可用表头"
    return info


def print_dt(name: str, info: dict, raw: bool = False) -> None:
    print(f"\n{name} 的追加 DT：")
    print(f"  位置 {info['off']:,} B，大小 {info['size']:,} B，格式 {info['kind']}")
    if raw and info["head"]:
        print(f"  前 64 字节：{info['head'].hex(' ')}")
    if not info["ok"]:
        print(f"  ✗ {info['reason']}")
        return

    if info["entries"]:
        print(f"  {'#':>2}  {'platform':>10}  {'variant':>10}  {'soc':>6}  "
              f"{'条内大小':>12}  {'DTB':>16}  model")
        print("  " + "-" * 100)
        for i, e in enumerate(info["entries"]):
            f = next((x for x in info["fdts"] if x["off"] == e["offset"]), None)
            model = " / ".join(f["models"])[:32] if f else "-"
            print(f"  {i:>2}  0x{e['platform']:08x}  0x{e['variant']:08x}  "
                  f"0x{e['soc']:04x}  {e['size']:>12,}  "
                  f"{(f['sha'] if f else '-'):>16}  {model}")
    else:
        print("  表头布局未识别，改按 DTB 内容比对（这个更可靠）：")

    print(f"  DT 段内共 {len(info['fdts'])} 份 DTB：")
    for f in info["fdts"]:
        print(f"    +{f['off']:>9,}  {f['size']:>9,} B  {f['sha']}  "
              f"{' / '.join(f['models'])[:44] or '-'}")


# ---------------------------------------------------------------- 主流程

def word_diff(a: str, b: str) -> tuple:
    A, B = a.split(), b.split()
    return [t for t in A if t not in B], [t for t in B if t not in A]


def single(path: str, with_dt: bool, raw: bool) -> int:
    a = parse(path)
    if "error" in a:
        print(f"✗ {path}: {a['error']}")
        return 2
    print(f"\n{os.path.basename(path)}  ({a['size']:,} B)")
    for k in ("kernel_size", "kernel_addr", "ramdisk_size", "ramdisk_addr",
              "second_size", "second_addr", "tags_addr", "page_size",
              "header_version", "dt_size", "name"):
        print(f"  {k:<16} {a[k]}")
    print(f"  kernel 段        {kernel_hint(path, a)}")
    print(f"  cmdline          {a['cmdline'] or '-'}")
    if a["expect_size"]:
        print(f"  按页对齐推算      {a['expect_size']:,} B（实际 {a['size']:,} B）")
    if not a["page_ok"]:
        print(f"\n⚠ page_size={a['page_size']} 不像标准值，header 布局可能非标")
        print("  前 64 字节：" + a["head"].hex(" "))
    if with_dt:
        print_dt(os.path.basename(path), load_dt(path, a), raw)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="boot/recovery 镜像头部与 DT 对比")
    ap.add_argument("ref", help="原厂镜像（参照）")
    ap.add_argument("new", nargs="?", help="待刷入的镜像")
    ap.add_argument("--dt", action="store_true", help="解析并对比追加的 DT")
    ap.add_argument("--raw", action="store_true", help="打印 DT 段前 64 字节")
    ap.add_argument("--strict-dt", action="store_true",
                    help="dt_size 不同也算硬失败（默认只警告）")
    args = ap.parse_args()

    if not args.new:
        return single(args.ref, args.dt, args.raw)

    a, b = parse(args.ref), parse(args.new)
    for tag, d in (("参照", a), ("待刷", b)):
        if "error" in d:
            print(f"✗ {tag} {d.get('path')}: {d['error']}")
            return 2

    print(f"\n参照：{os.path.basename(args.ref)}  ({a['size']:,} B)")
    print(f"待刷：{os.path.basename(args.new)}  ({b['size']:,} B)\n")
    print(f"  {'参数':<16}{'参照':>16}{'待刷':>16}   判定")
    print("  " + "-" * 62)

    hard = 0
    for k in HARD_KEYS + ("header_version",):
        va, vb = a[k], b[k]
        if va is None or vb is None:
            mark = "-"
        elif va == vb:
            mark = "✓"
        else:
            mark = "✗ 不一致"
            hard += 1
        print(f"  {k:<16}{str(va):>16}{str(vb):>16}   {mark}")

    soft = 0
    mark = "✓" if a["dt_size"] == b["dt_size"] else "⚠ 不同"
    if a["dt_size"] != b["dt_size"]:
        soft += 1
    print(f"  {'dt_size':<16}{a['dt_size']:>16,}{b['dt_size']:>16,}   {mark}")

    for k in ("kernel_size", "ramdisk_size"):
        print(f"  {k:<16}{a[k]:>16,}{b[k]:>16,}   {'变' if a[k] != b[k] else '同'}")

    print(f"  {'kernel 段':<16}{kernel_hint(args.ref, a):>16}"
          f"{kernel_hint(args.new, b):>16}   -")
    print(f"  {'name':<16}{a['name'] or '-':>16}{b['name'] or '-':>16}   -")

    same_cmd = a["cmdline"] == b["cmdline"]
    print(f"  {'cmdline':<16}{'一致' if same_cmd else '有差异':>16}")
    if not same_cmd:
        soft += 1
        only_a, only_b = word_diff(a["cmdline"], b["cmdline"])
        print("\n  cmdline 全文对比：")
        print(f"    参照   {a['cmdline']}")
        print(f"    待刷   {b['cmdline']}")
        if only_a:
            print(f"    - 仅参照有  {' '.join(only_a)}")
        if only_b:
            print(f"    + 仅待刷有  {' '.join(only_b)}")

    oversize = 0
    if b["expect_size"] and b["size"] < b["expect_size"]:
        print(f"\n⚠ 文件只有 {b['size']:,} B，按页对齐至少要 {b['expect_size']:,} B，"
              f"可能被截断")
        oversize += 1
    if b["size"] > 16 * 1024 * 1024:
        print("\n⚠ 超过 16MB，recovery 分区放不下")
        oversize += 1

    verdict = None
    if args.dt:
        ia, ib = load_dt(args.ref, a), load_dt(args.new, b)
        print_dt(os.path.basename(args.ref), ia, args.raw)
        print_dt(os.path.basename(args.new), ib, args.raw)

        if ia["ok"] and ib["ok"]:
            sa = {f["sha"] for f in ia["fdts"]}
            sb = {f["sha"] for f in ib["fdts"]}
            common = sa & sb
            print(f"\n  DTB 内容比对：参照 {len(sa)} 份，待刷 {len(sb)} 份，"
                  f"逐字节相同的 {len(common)} 份")
            for h in sorted(common):
                f = next(x for x in ib["fdts"] if x["sha"] == h)
                print(f"    ✓ {h}  {' / '.join(f['models'])[:44] or '-'}")
            if common:
                verdict = ("ok", f"待刷镜像里有 {len(common)} 份与原厂逐字节相同的 DTB，"
                                 f"本机板型在，LK 能选中")
            else:
                cand = [f for f in ib["fdts"] if f["models"]] or ib["fdts"]
                hint = " / ".join(cand[0]["models"])[:40] if cand else "-"
                verdict = ("bad", f"待刷镜像的 DT 里没有一份与原厂相同（其中一份是 "
                                  f"{hint}），LK 大概率报 Device tree not found")
        elif ia["ok"] and not b["dt_size"]:
            verdict = ("bad", "待刷镜像没有追加 DT，而原厂有；LK 找不到 DTB 会直接失败")
        elif ia["ok"] and not ib["ok"]:
            verdict = ("bad", f"待刷镜像的 DT 段无法解析：{ib['reason']}")

    print()
    if verdict and verdict[0] == "bad":
        print(f"✗ {verdict[1]}")
        print("  正确做法：用原厂 recovery.img 的内核与 DT，只替换 ramdisk 重新打包")
        return 1
    if hard:
        print(f"✗ {hard} 项地址/对齐参数不兼容，先改参数重新打包，别刷")
        print("  这几个值必须和原厂一致，否则 aboot 加载后会立刻跑飞")
        return 1
    if oversize:
        print(f"✗ {oversize} 项体积问题（截断或超过分区），先修好再刷")
        return 1
    if verdict and verdict[1]:
        print(f"✓ {verdict[1]}")
    if soft and not args.strict_dt:
        print(f"⚠ {soft} 项有差异但不属地址类，见上方逐条说明")
    print("✓ 地址与对齐参数完全一致。若刷后仍卡 logo，才轮到签名或镜像本身")
    if not args.dt:
        print("  建议加 --dt 再看一眼 DTB 是否对得上")
    return 0


if __name__ == "__main__":
    sys.exit(main())
