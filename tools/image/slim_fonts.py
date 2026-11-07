#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
slim_fonts.py — 裁剪 TWRP 的中文字体，给 ramdisk 腾空间

背景
    twrp-kyl23.img 里塞了三套字体：
        DroidSansFallback.ttf   3,725,920  ← 中文，占大头
        DroidSansMono.ttf         108,128  ← 终端等宽
        RobotoCondensed-Regular   125,332  ← 英文界面
    中文那套收了 4E00–9FFF 全部 20,992 个汉字，但 TWRP 界面文案去重只有 495 字。

    DroidSansFallback 本身就带完整 ASCII（95/95）和大部分 Latin-1，所以它已经是
    「一套中英文通吃」的字体，不需要再配一套英文的。

两种做法
    A. 只裁中文（默认）：替换 DroidSansFallback.ttf 的内容，文件名不动，
       XML 一行都不用改（zh_CN.xml 的 fontoverride 本来就在指它）。
    B. 只留一套（--single-font）：把所有 XML 里的 RobotoCondensed-Regular.ttf
       和 DroidSansMono.ttf 统统改指 DroidSansFallback.ttf，再删掉这两个文件。
       英文字体合计 233 KB，换来的是「中英文同字形」，以及少维护两套字体。

    dt（设备树）要跟着往前挪。aboot 不用绝对偏移，它是按 header 里的
    kernel_size / ramdisk_size 逐段页对齐往下算的：
        dt = page_align(kernel) + page_align(ramdisk) + page_align(second)
    ramdisk 变短了 dt 就必须前移，否则 aboot 读到一串零 —— 镜像起不来。
    总长仍然补齐到原来的 16 MiB，多出来的落在文件尾部。

用法
    python slim_fonts.py twrp-kyl23.img -o twrp-kyl23-slim.img
    python slim_fonts.py twrp-kyl23.img -o slim.img --level ui
    python slim_fonts.py twrp-kyl23.img -o single.img --single-font --level full
    python slim_fonts.py twrp-kyl23.img --report          # 只看体积，不产出

    --single-font   只留 DroidSansFallback 一套，改 XML 并删掉另两个字体
    --level ui      只留界面用字（495），约 110 KB，中文文件名会大量缺字
    --level gb2312  GB2312 一二级 6,763 字，约 1.04 MB（默认）
    --level gbk     GBK 全集 21,791 字，约 2.94 MB
    --level full    不裁，只重打包（用来验证流程）

依赖
    pip install fonttools
"""

from __future__ import annotations

import argparse
import gzip
import os
import re
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cpioutil as C

PAGE = 2048
FONT_ZH = b"twres/fonts/DroidSansFallback.ttf"
FONT_EN = b"twres/fonts/RobotoCondensed-Regular.ttf"
FONT_MONO = b"twres/fonts/DroidSansMono.ttf"
FONT_ZH_NAME = b"DroidSansFallback.ttf"
FONT_EN_NAME = b"RobotoCondensed-Regular.ttf"
FONT_MONO_NAME = b"DroidSansMono.ttf"
LANG_ZH = b"twres/languages/zh_CN.xml"


# ---------------------------------------------------------------- 镜像
def align(n: int, p: int) -> int:
    return (n + p - 1) // p * p


def read_image(path: str):
    d = open(path, "rb").read()
    if d[:8] != b"ANDROID!":
        raise SystemExit("✗ 不是 boot/recovery 镜像")
    ks, = struct.unpack_from("<I", d, 8)
    rs, = struct.unpack_from("<I", d, 16)
    ds, = struct.unpack_from("<I", d, 40)
    ps, = struct.unpack_from("<I", d, 36)

    # ramdisk 未必正好在页对齐处（这份镜像有 1568 B 的缝），扫 gzip 魔数定位
    base = ps + ((ks + ps - 1) // ps) * ps
    rd_off = None
    for o in range(base, min(base + 8192, len(d) - 3)):
        if d[o:o + 3] == b"\x1f\x8b\x08":
            rd_off = o
            break
    if rd_off is None:
        raise SystemExit("✗ 找不到 ramdisk 的 gzip 头")

    # dt 不在 ramdisk 末尾紧跟着，而是下一个页边界；原镜像里就是 QCDT 的起点
    dt_abs = align(rd_off + rs, ps)
    if d[dt_abs:dt_abs + 4] != b"QCDT":
        scan = d.find(b"QCDT", rd_off + rs, min(rd_off + rs + 8192, len(d)))
        if scan < 0:
            raise SystemExit("✗ ramdisk 之后 8 KB 内找不到 QCDT")
        dt_abs = scan
    return dict(raw=d, page=ps, kernel=ks, ramdisk=rs, dt=ds,
                rd_off=rd_off, dt_abs=dt_abs, total=len(d))


def assemble(info: dict, new_ramdisk: bytes) -> tuple[bytes, int]:
    """按 aboot 的算法重排：kernel 段照抄，新 ramdisk，页对齐，再放 dt。

    返回 (镜像, dt 的新起点)。总长仍补到原来的 16 MiB。
    """
    d = info["raw"]
    page = info["page"]
    hdr = bytearray(d[:page])
    struct.pack_into("<I", hdr, 16, len(new_ramdisk))
    out = bytearray(bytes(hdr))
    out += d[page:info["rd_off"]]              # kernel 段（含它到 ramdisk 之间那段缝）
    out += new_ramdisk
    out += b"\x00" * (align(len(out), page) - len(out))
    dt_new = len(out)
    out += d[info["dt_abs"]:info["dt_abs"] + info["dt"]]
    if len(out) < info["total"]:
        out += b"\x00" * (info["total"] - len(out))
    return bytes(out), dt_new


# ---------------------------------------------------------------- 字符集
def gb2312(lo: int, hi: int) -> str:
    out = []
    for h in range(lo, hi):
        for l in range(0xA1, 0xFF):
            try:
                out.append(bytes([h, l]).decode("gb2312"))
            except Exception:
                pass
    return "".join(out)


def gbk_all() -> str:
    out = []
    for h in range(0x81, 0xFF):
        for l in range(0x40, 0xFF):
            if l == 0x7F:
                continue
            try:
                out.append(bytes([h, l]).decode("gbk"))
            except Exception:
                pass
    return "".join(out)


def charset(level: str, zh_xml: bytes) -> str:
    latin = "".join(chr(c) for c in range(0x20, 0x7F))
    latin += "".join(chr(c) for c in range(0xA0, 0x100))     # ° 之类
    latin += "".join(chr(c) for c in range(0x2000, 0x2070))  # — “ ” …
    latin += "".join(chr(c) for c in range(0x3000, 0x3040))  # 中文标点
    latin += "".join(chr(c) for c in range(0xFF00, 0xFFF0))  # 全角

    text = zh_xml.decode("utf-8", "ignore")
    ui = "".join(sorted({c for c in re.sub(r"<[^>]+>", "\n", text)
                         if "\u4e00" <= c <= "\u9fff"}))

    if level == "ui":
        return latin + ui
    if level == "gb2312":
        return latin + gb2312(0xB0, 0xD8) + gb2312(0xD8, 0xF8) + ui
    if level == "gbk":
        return latin + gbk_all() + ui
    return ""           # full：不裁


def subset_font(src: bytes, text: str, out_path: str) -> int:
    try:
        from fontTools import subset
    except ImportError:
        raise SystemExit("✗ 需要 fontTools：pip install fonttools")

    with tempfile.NamedTemporaryFile(suffix=".ttf", delete=False) as fh:
        fh.write(src)
        src_path = fh.name
    try:
        subset.main([src_path, "--text=" + text, "--output-file=" + out_path,
                     "--layout-features=", "--no-hinting", "--desubroutinize",
                     "--drop-tables+=GSUB,GPOS,GDEF,DSIG"])
    finally:
        os.remove(src_path)
    return os.path.getsize(out_path)


# ---------------------------------------------------------------- 单一字体
def retarget_refs(ents) -> list:
    """把所有 XML 里指向英文字体的 filename= 改到 DroidSansFallback。"""
    hit = []
    pat = re.compile(rb'filename="([^"]+)"')
    for e in ents:
        if not e["name"].endswith(b".xml"):
            continue
        n = [0]

        def sub(m, n=n):
            if m.group(1) in (FONT_EN_NAME, FONT_MONO_NAME):
                n[0] += 1
                return b'filename="' + FONT_ZH_NAME + b'"'
            return m.group(0)

        new = pat.sub(sub, e["data"])
        if n[0]:
            e["data"] = new
            hit.append((e["name"].decode(), n[0]))
    return hit


def drop_extra_fonts(ents) -> list:
    """删掉英文字体条目，返回被删的 (名字, 大小)。"""
    gone = []
    keep = []
    for e in ents:
        if e["name"] in (FONT_EN, FONT_MONO):
            gone.append((e["name"].decode(), len(e["data"])))
        else:
            keep.append(e)
    ents[:] = keep
    return gone


def check_refs(ents):
    """扫描所有 XML 的 font filename=，核对 twres/fonts/ 里是否真有这个文件。"""
    have = {e["name"].rsplit(b"/", 1)[-1]
            for e in ents if e["name"].startswith(b"twres/fonts/")}
    refs, miss = 0, []
    for e in ents:
        if not e["name"].endswith(b".xml"):
            continue
        for m in re.finditer(rb'filename="([^"]+\.ttf)"', e["data"]):
            refs += 1
            if m.group(1) not in have:
                miss.append((e["name"].decode(), m.group(1).decode()))
    return refs, have, miss


# ---------------------------------------------------------------- 主流程
def gz_len(b: bytes) -> int:
    return len(gzip.compress(b, 9))


def main() -> int:
    ap = argparse.ArgumentParser(description="裁剪 TWRP 中文字体")
    ap.add_argument("image", help="TWPR 镜像，如 twrp-kyl23.img")
    ap.add_argument("-o", "--out", help="输出镜像")
    ap.add_argument("--level", default="gb2312",
                    choices=("ui", "gb2312", "gbk", "full"))
    ap.add_argument("--single-font", action="store_true",
                    help="只留 DroidSansFallback 一套：改 XML 引用并删掉另两个字体")
    ap.add_argument("--report", action="store_true", help="只报体积，不写文件")
    args = ap.parse_args()

    info = read_image(args.image)
    cpio = gzip.decompress(info["raw"][info["rd_off"]:info["rd_off"] + info["ramdisk"]])
    ents, end = C.parse(cpio)
    if end != len(cpio):
        raise SystemExit("✗ ramdisk 的 cpio 没解析完整，先别动")

    zh = next((e for e in ents if e["name"] == FONT_ZH), None)
    en = next((e for e in ents if e["name"] == FONT_EN), None)
    mo = next((e for e in ents if e["name"] == FONT_MONO), None)
    zx = next((e for e in ents if e["name"] == LANG_ZH), None)
    if not zh or not zx:
        raise SystemExit("✗ 镜像里没有中文字体或 zh_CN.xml")

    print(f"镜像      {args.image}  {info['total']:,} B")
    print(f"ramdisk   压缩 {info['ramdisk']:,} B / 解压 {len(cpio):,} B，{len(ents)} 个条目")
    print(f"字体      DroidSansFallback {len(zh['data']):,} B")
    if en:
        print(f"          RobotoCondensed  {len(en['data']):,} B")
    if mo:
        print(f"          DroidSansMono    {len(mo['data']):,} B")

    if args.level == "full":
        new_font = zh["data"]
    else:
        text = charset(args.level, zx["data"])
        tmp = tempfile.mktemp(suffix=".ttf")
        size = subset_font(zh["data"], text, tmp)
        new_font = open(tmp, "rb").read()
        os.remove(tmp)
        print(f"\n裁剪档位  {args.level}  字符 {len(set(text)):,}  "
              f"{len(zh['data']):,} → {size:,} B "
              f"({size * 100 // len(zh['data'])}%)")

    zh["data"] = new_font

    # --- 单一字体：先把引用改掉，再删文件（顺序反了会短暂出现悬空引用）
    dropped, hits = [], []
    if args.single_font:
        hits = retarget_refs(ents)
        dropped = drop_extra_fonts(ents)
        print(f"\n单一字体  改写 {len(hits)} 个 XML 的 {sum(n for _, n in hits)} 处引用")
        for name, n in hits:
            print(f"          {name}  ×{n}")
        for name, sz in dropped:
            print(f"          删除 {name}  {sz:,} B")

    new_cpio = C.build(ents)
    new_gz = gzip.compress(new_cpio, 9)

    delta_rd = len(new_gz) - info["ramdisk"]
    print(f"\nramdisk   压缩 {info['ramdisk']:,} → {len(new_gz):,} B "
          f"({'省' if delta_rd < 0 else '多'} {abs(delta_rd):,} B)")
    dt_new = align(info["rd_off"] + len(new_gz), info["page"])
    print(f"dt 位置   {info['dt_abs']:,} → {dt_new:,} B（前移 "
          f"{info['dt_abs'] - dt_new:,}）")
    print("（aboot 按 kernel_size/ramdisk_size 页对齐算 dt 的偏移，所以 ramdisk 一短，")
    print("  dt 必须跟着前移；镜像总长仍是 16 MiB，多出来的零落在文件尾部）")

    if args.report or not args.out:
        refs, have, miss = check_refs(ents)
        print(f"\n字体引用  {refs} 处 → {sorted(x.decode() for x in have)}")
        if miss:
            for xml, f in miss:
                print(f"  ✗ {xml} 引用了不存在的 {f}")
        return 0

    img, dt_new = assemble(info, new_gz)
    with open(args.out, "wb") as fh:
        fh.write(img)

    # 自检：与原镜像比，差异应只在 header 的 ramdisk_size 和 ramdisk 区
    d = info["raw"]
    ok_prefix = img[:16] == d[:16] and img[20:info["rd_off"]] == d[20:info["rd_off"]]
    ok_dt = img[dt_new:dt_new + info["dt"]] == d[info["dt_abs"]:info["dt_abs"] + info["dt"]]
    ok_dtpos = dt_new == align(info["rd_off"] + len(new_gz), info["page"])
    ok_pad = not any(img[dt_new + info["dt"]:])
    ok_size = len(img) == info["total"]

    # 回读确认
    back = gzip.decompress(img[info["rd_off"]:info["rd_off"] + len(new_gz)])
    ents2, end2 = C.parse(back)
    got = next(e for e in ents2 if e["name"] == FONT_ZH)["data"]
    refs, have, miss = check_refs(ents2)
    leftovers = [n.decode() for n, _ in dropped
                 if any(e["name"].endswith(n.encode()[-20:]) for e in ents2)]

    ok_cpio = end2 == len(back)
    ok_font = got == new_font
    ok_ref = not miss
    ok_gone = not leftovers

    print(f"\n写出 {args.out}  {len(img):,} B")
    print(f"  header/kernel 段未动 : {'✓' if ok_prefix else '✗'}")
    print(f"  dt 整块搬到了 {dt_new:,} : {'✓' if ok_dt else '✗'}"
          f"（页对齐 {align(info['rd_off'] + len(new_gz), info['page']):,}"
          f" {'✓' if ok_dtpos else '✗'}）")
    print(f"  dt 之后全是零填充    : {'✓' if ok_pad else '✗'}")
    print(f"  总长与原来一致       : {'✓' if ok_size else '✗'}")
    print(f"  回读字体一致         : {'✓' if ok_font else '✗'}")
    print(f"  cpio 解析完整        : {'✓' if ok_cpio else '✗'}  "
          f"{len(ents2)} 个条目（原 {len(ents) + len(dropped)}）")
    print(f"  字体引用都有对应文件 : {'✓' if ok_ref else '✗'}  "
          f"{refs} 处引用 → {sorted(x.decode() for x in have)}")
    if not ok_ref:
        for xml, f in miss:
            print(f"      ✗ {xml} 引用了不存在的 {f}")
    if dropped:
        print(f"  英文字体已删除       : {'✓' if ok_gone else '✗'}")

    if not (ok_prefix and ok_dt and ok_dtpos and ok_pad and ok_size
            and ok_font and ok_cpio and ok_ref and ok_gone):
        print("\n✗ 自检没过，别刷这个镜像。")
        return 8

    print("\n刷之前先看一眼：python check_bootimg.py " + args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
