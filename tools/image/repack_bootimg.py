#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
repack_bootimg.py — 拆开 / 改写 / 换壳重新打包 Android boot-recovery 镜像

三种用法
  1) 只看结构、拆包
  2) 只改 ramdisk 里的 prop（壳不变）—— 用来回答「aboot 到底验不验签」
  3) 换壳 splice —— 用本机原厂镜像的 kernel + QCDT + header 当壳，
     把第三方 recovery（例如从别的机型移植过来的 TWRP）的 ramdisk 装进去

为什么必须换壳
  aboot 在 boot/recovery 镜像末尾的 QCDT 里，按 (msm-id, board-id, soc_rev)
  三元组查设备树。机型不对的表一条都查不到，aboot 在拉起 kernel 之前就停下，
  屏幕停在厂商 logo，ramdisk 根本没有被执行的机会。
  所以跨机型的 recovery 只能换 ramdisk，不能把 kernel / DT 一起搬过来。

用法
    python repack_bootimg.py stock_recovery.img --list
    python repack_bootimg.py stock_recovery.img --extract out/
    python repack_bootimg.py stock_recovery.img --patch-prop ro.secure=0 -o t.img
    python repack_bootimg.py stock_recovery.img \
        --splice-from falcon_twrp.img --splice-parts ramdisk \
        --max-size 16M -o kc01_twrp.img

说明
    --patch-prop / --replace 要求替换前后字节数相同（cpio 内原位改写，
    不重建索引）。长度不等直接拒绝，不会写出半成品。
    --splice-from 默认只取 ramdisk。取 kernel / dt 会明确警告：那等于把
    机型匹配又搞坏了，刷进去必然回到卡 logo。
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import struct
import sys
import zlib

FDT_MAGIC = b"\xd0\x0d\xfe\xed"
MAGICS = {
    b"\x1f\x8b": "gzip",
    b"\xfd7zXZ\x00": "xz",
    b"BZh": "bzip2",
    b"\x02\x21\x4c\x18": "lz4",
    b"\x5d\x00\x00": "lzma",
}


def pg(n: int, page: int) -> int:
    return ((n + page - 1) // page) * page if n else 0


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16] if b else "-"


def parse_size(s: str) -> int:
    """16M / 8MiB / 4096K / 16777216 都认。"""
    t = str(s).strip().lower().replace("_", "").replace(" ", "")
    mult = 1
    for suf, m in (("gib", 1 << 30), ("gb", 1 << 30), ("g", 1 << 30),
                   ("mib", 1 << 20), ("mb", 1 << 20), ("m", 1 << 20),
                   ("kib", 1 << 10), ("kb", 1 << 10), ("k", 1 << 10)):
        if t.endswith(suf):
            t, mult = t[:-len(suf)], m
            break
    return int(float(t) * mult)


# ---------------------------------------------------------------- 头部

def read_header(path: str) -> dict:
    with open(path, "rb") as fh:
        raw = fh.read(4096)
    if raw[:8] != b"ANDROID!":
        raise SystemExit(f"✗ {path} 不是 boot 镜像（开头 {raw[:8].hex(' ')}）")
    page = struct.unpack_from("<I", raw, 36)[0]
    h = {
        "kernel_size": struct.unpack_from("<I", raw, 8)[0],
        "kernel_addr": struct.unpack_from("<I", raw, 12)[0],
        "ramdisk_size": struct.unpack_from("<I", raw, 16)[0],
        "ramdisk_addr": struct.unpack_from("<I", raw, 20)[0],
        "second_size": struct.unpack_from("<I", raw, 24)[0],
        "second_addr": struct.unpack_from("<I", raw, 28)[0],
        "tags_addr": struct.unpack_from("<I", raw, 32)[0],
        "page_size": page,
        "dt_size": struct.unpack_from("<I", raw, 40)[0],
        "f44": struct.unpack_from("<I", raw, 44)[0],
        "name": raw[48:64].rstrip(b"\x00"),
        "cmdline": raw[64:576].split(b"\x00")[0],
        "page_raw": raw[:page],
        "path": path,
    }
    h["dt_off"] = (page + pg(h["kernel_size"], page)
                   + pg(h["ramdisk_size"], page)
                   + pg(h["second_size"], page))
    return h


def read_parts(path: str, h: dict) -> dict:
    page = h["page_size"]
    with open(path, "rb") as fh:
        fh.seek(page)
        kernel = fh.read(h["kernel_size"])
        fh.seek(page + pg(h["kernel_size"], page))
        ramdisk = fh.read(h["ramdisk_size"])
        second = b""
        if h["second_size"]:
            fh.seek(page + pg(h["kernel_size"], page) + pg(h["ramdisk_size"], page))
            second = fh.read(h["second_size"])
        dt = b""
        if h["dt_size"]:
            fh.seek(h["dt_off"])
            dt = fh.read(h["dt_size"])
    return {"kernel": kernel, "ramdisk": ramdisk, "second": second, "dt": dt}


# ---------------------------------------------------------------- ramdisk

def guess_kind(blob: bytes) -> str:
    for magic, kind in MAGICS.items():
        if blob.startswith(magic):
            return kind
    return "raw"


def decompress(blob: bytes) -> tuple:
    kind = guess_kind(blob)
    if kind == "gzip":
        return gzip.decompress(blob), kind
    if kind == "xz":
        import lzma
        return lzma.decompress(blob), kind
    if kind == "bzip2":
        import bz2
        return bz2.decompress(blob), kind
    if kind == "lzma":
        import lzma
        return lzma.decompress(blob, format=lzma.FORMAT_ALONE), kind
    return blob, kind


def compress(raw: bytes, kind: str) -> bytes:
    if kind in ("gzip", "raw"):
        buf = zlib.compressobj(9, zlib.DEFLATED, -15)
        body = buf.compress(raw) + buf.flush()
        hdr = b"\x1f\x8b\x08\x00" + struct.pack("<I", 0) + b"\x02\x03"
        trailer = struct.pack("<II", zlib.crc32(raw) & 0xFFFFFFFF, len(raw) & 0xFFFFFFFF)
        return hdr + body + trailer
    if kind == "xz":
        import lzma
        return lzma.compress(raw, format=lzma.FORMAT_XZ)
    if kind == "bzip2":
        import bz2
        return bz2.compress(raw)
    if kind == "lzma":
        import lzma
        return lzma.compress(raw, format=lzma.FORMAT_ALONE)
    return raw


def find_props(raw: bytes, name: str) -> list:
    """在 default.prop / init.rc 之类文本里找 name=value，返回 [(起, 值起, 值止, 值)]"""
    key = name.encode() + b"="
    out, idx = [], 0
    while True:
        i = raw.find(key, idx)
        if i < 0:
            break
        if i == 0 or raw[i - 1] in (0x0A, 0x00):
            j = i + len(key)
            k = j
            while k < len(raw) and raw[k] not in (0x0A, 0x00):
                k += 1
            out.append((i, j, k, raw[j:k]))
        idx = i + 1
    return out


def patch_bytes(raw: bytes, pairs: list) -> tuple:
    out, done = raw, []
    for old, new in pairs:
        if len(old) != len(new):
            raise SystemExit(f"✗ '{old.decode()}' -> '{new.decode()}' 长度不同"
                             f"（{len(old)} vs {len(new)}），原位改写做不到")
        cnt = out.count(old)
        out = out.replace(old, new)
        done.append((old.decode("utf-8", "replace"),
                     new.decode("utf-8", "replace"), cnt))
    return out, done


# ---------------------------------------------------------------- 打包

def build(h: dict, parts: dict, out_path: str) -> dict:
    page = h["page_size"]
    k, r = parts["kernel"], parts["ramdisk"]
    s, dt = parts["second"], parts["dt"]

    hdr = bytearray(h["page_raw"])          # 壳的 header 原样复制，避免漏字段
    struct.pack_into("<I", hdr, 8, len(k))
    struct.pack_into("<I", hdr, 16, len(r))
    struct.pack_into("<I", hdr, 24, len(s))
    struct.pack_into("<I", hdr, 40, len(dt))

    blob = bytes(hdr)
    blob += k + b"\x00" * (pg(len(k), page) - len(k))
    blob += r + b"\x00" * (pg(len(r), page) - len(r))
    if s:
        blob += s + b"\x00" * (pg(len(s), page) - len(s))
    blob += dt

    with open(out_path, "wb") as fh:
        fh.write(blob)
    return {"size": len(blob), "kernel": len(k), "ramdisk": len(r),
            "second": len(s), "dt": len(dt), "page": page}


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser(description="boot/recovery 镜像拆包、改写、换壳重打包")
    ap.add_argument("image", help="壳镜像（本机原厂 recovery.img）")
    ap.add_argument("-o", "--out", help="输出镜像路径")
    ap.add_argument("--list", action="store_true", help="只看结构")
    ap.add_argument("--extract", metavar="DIR", help="拆出 kernel/ramdisk/dt")
    ap.add_argument("--patch-prop", action="append", default=[], metavar="K=V",
                    help="改 ramdisk 里的 prop，如 ro.secure=0（长度必须相同）")
    ap.add_argument("--replace", action="append", default=[], metavar="OLD=NEW",
                    help="在 ramdisk 内做原位替换，同样要求长度相同")
    ap.add_argument("--splice-from", metavar="IMG",
                    help="从该镜像取段（移植版 TWRP），壳的 header / 地址不动")
    ap.add_argument("--splice-parts", default="ramdisk", metavar="LIST",
                    help="要取的段，逗号分隔：ramdisk,kernel,dt,second（默认 ramdisk）")
    ap.add_argument("--max-size", type=parse_size, default=0, metavar="SIZE",
                    help="输出镜像大小上限，即 recovery 分区字节数。超了直接拒绝")
    args = ap.parse_args()

    h = read_header(args.image)
    parts = read_parts(args.image, h)
    raw_rd, kind = decompress(parts["ramdisk"])

    if args.list or (not args.out and not args.extract and not args.splice_from):
        print(f"\n{os.path.basename(args.image)}  ({os.path.getsize(args.image):,} B)")
        print(f"  page_size      {h['page_size']}")
        print(f"  kernel         {h['kernel_size']:>10,} B   @0x{h['kernel_addr']:08x}"
              f"   sha {sha(parts['kernel'])}")
        print(f"  ramdisk        {h['ramdisk_size']:>10,} B   @0x{h['ramdisk_addr']:08x}"
              f"   ({kind}，解开 {len(raw_rd):,} B)")
        print(f"  second         {h['second_size']:>10,} B   @0x{h['second_addr']:08x}")
        print(f"  dt             {h['dt_size']:>10,} B   @文件偏移 {h['dt_off']:,}"
              f"   sha {sha(parts['dt'])}")
        print(f"  tags           @0x{h['tags_addr']:08x}")
        print(f"  name           {h['name'].decode('ascii', 'replace') or '-'}")
        print(f"  cmdline        {h['cmdline'].decode('ascii', 'replace')}")
        print(f"  ramdisk 开头   {parts['ramdisk'][:8].hex(' ')}  ({kind})")
        print(f"  cpio 开头      {raw_rd[:6]}")
        return 0

    if args.extract:
        os.makedirs(args.extract, exist_ok=True)
        for name, data in (("kernel", parts["kernel"]),
                           ("ramdisk.cpio", raw_rd),
                           ("dt.img", parts["dt"]),
                           ("second", parts["second"])):
            if data:
                p = os.path.join(args.extract, name)
                with open(p, "wb") as fh:
                    fh.write(data)
                print(f"  → {p}  ({len(data):,} B)")
        return 0

    # ---------------- 换壳
    src_parts, want = None, []
    if args.splice_from:
        want = [w.strip().lower() for w in args.splice_parts.split(",") if w.strip()]
        bad = [w for w in want if w not in ("kernel", "ramdisk", "second", "dt")]
        if bad:
            raise SystemExit(f"✗ --splice-parts 有未知段：{','.join(bad)}")
        hs = read_header(args.splice_from)
        src_parts = read_parts(args.splice_from, hs)
        print(f"\n换壳：壳 = {os.path.basename(args.image)}"
              f"  取段 = {os.path.basename(args.splice_from)}:{','.join(want)}")
        for w in want:
            if not src_parts[w]:
                raise SystemExit(f"✗ 源镜像没有 {w} 段（大小为 0）")
            parts[w] = src_parts[w]
            print(f"  ← {w:<8} {len(src_parts[w]):>10,} B   sha {sha(src_parts[w])}"
                  f"   （壳原有 {h[w + '_size']:,} B，sha {sha(read_parts(args.image, h)[w])}）")
        if "kernel" in want or "dt" in want:
            print("  ⚠ 你动了 kernel/dt。aboot 的机型匹配靠的就是 DT，"
                  "换了它就等于回到卡第一屏。除非你确认两边 DT 完全等价，否则别这么做。")
        if "ramdisk" in want:
            raw_rd, sk = decompress(parts["ramdisk"])
            if sk != kind:
                print(f"  ⚠ 源 ramdisk 是 {sk}，壳是 {kind} → 重压为 {kind}")
                parts["ramdisk"] = compress(raw_rd, kind)
            else:
                print(f"  ✓ 压缩格式一致（{kind}），源字节直搬，不重压")

    # ---------------- 改 ramdisk
    orig_rd = raw_rd
    pairs, spans = [], []
    for kv in args.patch_prop:
        if "=" not in kv:
            raise SystemExit(f"✗ --patch-prop 需要 K=V 形式：{kv}")
        kname, kval = kv.split("=", 1)
        hits = find_props(raw_rd, kname)
        if not hits:
            print(f"⚠ ramdisk 里没有 {kname}=…，跳过")
            continue
        same = [x for x in hits if len(x[3]) == len(kval)]
        if not same:
            cur = hits[0][3].decode("utf-8", "replace")
            print(f"⚠ {kname} 当前是 '{cur}'，与 '{kval}' 长度不同，"
                  f"原位改写做不到，跳过（需要重新生成 cpio）")
            continue
        for (_s, vstart, vend, _cur) in same:
            spans.append((vstart, vend, kval.encode()))
        print(f"  ✓ {kname}={kval}  命中 {len(same)} 处")

    if spans:
        buf = bytearray(raw_rd)
        for vstart, vend, new in sorted(spans, reverse=True):
            buf[vstart:vend] = new
        raw_rd = bytes(buf)

    for kv in args.replace:
        if "=" not in kv:
            raise SystemExit(f"✗ --replace 需要 OLD=NEW 形式：{kv}")
        old, new = kv.split("=", 1)
        pairs.append((old.encode(), new.encode()))

    patched = raw_rd
    if pairs:
        patched, done = patch_bytes(patched, pairs)
        for old, new, cnt in done:
            print(f"  ✓ {old} → {new}   命中 {cnt} 处")

    # 只有内容真变了才重压；换壳时若格式一致且没改内容，保留源压缩字节
    if patched != orig_rd:
        parts["ramdisk"] = compress(patched, kind)
    elif not spans and not pairs:
        if not src_parts:
            raise SystemExit("✗ 没有任何可替换的内容，未生成镜像")

    if not args.out:
        raise SystemExit("✗ 需要 -o 指定输出路径")

    # ---------------- 写出 + 上限检查
    stats = build(h, parts, args.out)

    if args.max_size and stats["size"] > args.max_size:
        os.unlink(args.out)
        raise SystemExit(f"✗ 输出 {stats['size']:,} B 超过分区上限 "
                         f"{args.max_size:,} B，已删除。"
                         f"把 TWRP 的 ramdisk 精简（去掉多余的 bin/lib）再试")

    print(f"\n已写出 {args.out}")
    print(f"  kernel  {stats['kernel']:>10,} B   sha {sha(parts['kernel'])}")
    print(f"  ramdisk {stats['ramdisk']:>10,} B   sha {sha(parts['ramdisk'])}"
          f"（{kind}，解开 {len(patched):,} B）")
    print(f"  dt      {stats['dt']:>10,} B   sha {sha(parts['dt'])}")
    print(f"  总大小  {stats['size']:>10,} B")
    if args.max_size:
        print(f"  分区余量 {args.max_size - stats['size']:>+10,} B"
              f"（上限 {args.max_size:,}）")

    # ---------------- 自检
    h2 = read_header(args.out)
    p2 = read_parts(args.out, h2)
    ok = True
    for k in ("kernel_addr", "ramdisk_addr", "second_addr", "tags_addr",
              "page_size", "cmdline"):
        if h[k] != h2[k]:
            print(f"  ✗ {k} 变了：{h[k]} → {h2[k]}")
            ok = False
    if p2["kernel"] != parts["kernel"]:
        print("  ✗ kernel 段与预期不一致")
        ok = False
    if p2["dt"] != parts["dt"]:
        print("  ✗ dt 段与预期不一致")
        ok = False
    if p2["second"] != parts["second"]:
        print("  ✗ second 段与预期不一致")
        ok = False
    rd2, _ = decompress(p2["ramdisk"])
    if rd2 != patched:
        print("  ✗ 重新解压 ramdisk 与预期不符")
        ok = False

    if ok:
        bits = ["header 地址 / cmdline 与原厂壳一致"]
        if src_parts and "kernel" not in want:
            bits.append("kernel 为原厂")
        if src_parts and "dt" not in want:
            bits.append("dt 为原厂")
        if src_parts and "ramdisk" in want:
            bits.append("ramdisk 已换成源镜像的")
        print("  ✓ 自检通过：" + "，".join(bits))
    else:
        print("  ✗ 自检未通过，别刷这个文件")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
