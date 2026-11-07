#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_modversions.py  ——  修补内核模块的 __versions 段（符号版本 / CRC）

用途
    外挂 .ko 加载时报一堆
        mmc_protect: Unknown symbol mmc_wait_for_cmd (err -22)
    而 /proc/kallsyms 里这些符号明明存在（T + __ksymtab_ + __kcrctab_）。
    err -22 = EINVAL，在 kernel/module.c 里只有一个来源：
        resolve_symbol() -> check_version() 返回 0
    也就是「符号找到了，但模块里记录的 CRC 和本内核导出的 CRC 不一致」。

    本脚本把指定符号的版本记录「作废」：把 __versions 里的名字前缀改成 '!'，
    strcmp 必然不再相等，内核就会走 check_version() 的兜底分支：
        pr_debug("no version for \\"%s\\" found: kernel tainted.")
        add_taint(TAINT_FORCED_MODULE); return 1;      <-- 放行
    文件体积、段表、符号表、代码一个字节都不动，只在 __versions 段内改名字。

用法
    python patch_modversions.py mmc_protect.ko --list
    python patch_modversions.py mmc_protect.ko --drop mmc_wait_for_cmd,mmc_register_driver -o out.ko
    python patch_modversions.py out.ko --restore -o back.ko          # 撤掉 '!' 前缀
    python patch_modversions.py mmc_protect.ko --set mmc_wait_for_cmd=0x1a2b3c4d -o out.ko

设计约束
    * 只认 ELF32 / ELF64、ARM 小端也兼容其它架构
    * 只改 __versions 段内的名字字节，改完自动复核「其余字节完全未变」
    * 绝不碰 .strtab / 符号表——那里也有同名符号，改了就真的 Unknown symbol 了
"""

import argparse
import json
import os
import struct
import sys

MODULE_NAME_LEN = 64
MARK = "!"


# ---------------------------------------------------------------- ELF 解析
class Elf:
    def __init__(self, data: bytes):
        if data[:4] != b"\x7fELF":
            raise SystemExit("✗ 不是 ELF 文件")
        self.d = data
        self.cls = data[4]          # 1=ELF32  2=ELF64
        self.end = "<" if data[5] == 1 else ">"
        if self.cls == 1:
            fmt = self.end + "HHIIIIIHHHHHH"
            (self.type, self.machine, self.version, self.entry, self.phoff,
             self.shoff, self.flags, self.ehsize, self.phentsize, self.phnum,
             self.shentsize, self.shnum, self.shstrndx) = struct.unpack_from(fmt, data, 16)
            self.wordsize = 4
        elif self.cls == 2:
            fmt = self.end + "HHIQQQIHHHHHH"
            (self.type, self.machine, self.version, self.entry, self.phoff,
             self.shoff, self.flags, self.ehsize, self.phentsize, self.phnum,
             self.shentsize, self.shnum, self.shstrndx) = struct.unpack_from(fmt, data, 16)
            self.wordsize = 8
        else:
            raise SystemExit(f"✗ 未知 ELF class {self.cls}")
        self.secs = self._read_shdrs()

    def _read_shdrs(self):
        out = []
        for i in range(self.shnum):
            base = self.shoff + i * self.shentsize
            if self.cls == 1:
                (nm, typ, flags, addr, off, size, link, info,
                 align, entsize) = struct.unpack_from(self.end + "10I", self.d, base)
            else:
                (nm, typ, flags, addr, off, size, link, info,
                 align, entsize) = struct.unpack_from(self.end + "IIQQQQIIQQ", self.d, base)
            out.append(dict(i=i, name_off=nm, type=typ, flags=flags, addr=addr,
                            off=off, size=size, link=link, info=info,
                            align=align, entsize=entsize, name=""))
        # 段名表
        if 0 <= self.shstrndx < len(out):
            st = out[self.shstrndx]
            strs = self.d[st["off"]:st["off"] + st["size"]]
            for s in out:
                s["name"] = self._cstr(strs, s["name_off"])
        return out

    @staticmethod
    def _cstr(blob: bytes, off: int):
        if off >= len(blob):
            return ""
        end = blob.find(b"\0", off)
        if end < 0:
            end = len(blob)
        return blob[off:end].decode("utf-8", "replace")

    def find(self, name: str):
        for s in self.secs:
            if s["name"] == name:
                return s
        return None

    def find_by_prefix(self, prefix: str):
        return [s for s in self.secs if s["name"].startswith(prefix)]


# ---------------------------------------------------------------- __versions
def entry_size(elf: Elf, sec: dict):
    """struct modversion_info { unsigned long crc; char name[MODULE_NAME_LEN]; }

    实际见到过的三种：
        total 64  = crc(4) + name[60]     MODULE_NAME_LEN = 64 - sizeof(unsigned long)  ← 最常见
        total 60  = crc(4) + name[56]
        total 68  = crc(4) + name[64]
    靠 sec["size"] 能否整除反推，比信任 sh_entsize 靠谱（modpost 常常不填它）。
    """
    cands = [64, elf.wordsize + 56, elf.wordsize + 64]
    seen = []
    for c in cands:
        if c not in seen:
            seen.append(c)
    if sec["entsize"] and sec["entsize"] in seen and sec["size"] % sec["entsize"] == 0:
        return sec["entsize"]
    for c in seen:
        if sec["size"] and sec["size"] % c == 0:
            return c
    return seen[0]


def read_entries(elf: Elf, sec: dict):
    esz = entry_size(elf, sec)
    nlen = esz - elf.wordsize          # name 字段的真实长度
    off = sec["off"]
    out = []
    n = sec["size"] // esz
    for i in range(n):
        p = off + i * esz
        crc = struct.unpack_from(elf.end + ("I" if elf.wordsize == 4 else "Q"), elf.d, p)[0]
        raw = elf.d[p + elf.wordsize: p + elf.wordsize + nlen]
        name = raw.split(b"\0", 1)[0].decode("utf-8", "replace")
        out.append(dict(i=i, off=p, name_off=p + elf.wordsize, crc=crc,
                        name=name, esz=esz, nlen=nlen))
    return out


def set_name(elf: Elf, ent: dict, newname: str):
    """就地改写名字，长度受 name 字段长度限制"""
    b = newname.encode("utf-8")
    nlen = ent["nlen"]
    if len(b) > nlen - 1:
        raise SystemExit(f"✗ 名字太长（限 {nlen - 1} 字节）: {newname}")
    pad = b + b"\0" * (nlen - len(b))
    data = bytearray(elf.d)
    data[ent["name_off"]: ent["name_off"] + nlen] = pad
    elf.d = bytes(data)


def set_crc(elf: Elf, ent: dict, crc: int):
    data = bytearray(elf.d)
    struct.pack_into(elf.end + ("I" if elf.wordsize == 4 else "Q"), data, ent["off"], crc)
    elf.d = bytes(data)


def recheck(before: bytes, after: bytes, sec: dict, elf: Elf):
    """确认除 __versions 段之外一个字节都没变"""
    if len(before) != len(after):
        raise SystemExit("✗ 文件长度变了，不该发生")
    lo, hi = sec["off"], sec["off"] + sec["size"]
    for i in range(len(before)):
        if before[i] != after[i] and not (lo <= i < hi):
            raise SystemExit(f"✗ 段外字节被改动 @0x{i:x}，已中止")
    return True


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(
        description="修补 .ko 的 __versions 段：作废或改写符号版本记录")
    ap.add_argument("ko", help="目标 .ko 文件")
    ap.add_argument("--list", action="store_true", help="列出 __versions 全部记录")
    ap.add_argument("--drop", default="", help="作废这些符号的版本记录，逗号分隔")
    ap.add_argument("--restore", action="store_true", help="撤销 '!' 前缀")
    ap.add_argument("--set", default="", help="指定 CRC：SYM=0x1234abcd,...")
    ap.add_argument("-o", "--out", default="", help="输出文件（默认 原名+_patched.ko）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = ap.parse_args()

    raw = open(args.ko, "rb").read()
    elf = Elf(raw)
    sec = elf.find("__versions")
    if sec is None:
        # 有的打包工具会写成 .versions 或者带前缀
        cand = [s["name"] for s in elf.secs if "version" in s["name"]]
        raise SystemExit(
            "✗ 这个 .ko 里没有 __versions 段"
            + (f"（倒是看到 {cand}）" if cand else "")
            + "\n  说明它编译时没开 CONFIG_MODVERSIONS，"
              "那 Unknown symbol 就不是版本问题，别用这个脚本。")

    ents = read_entries(elf, sec)
    esz = entry_size(elf, sec)

    if args.list or (not args.drop and not args.set and not args.restore):
        if args.json:
            print(json.dumps(dict(file=args.ko, section=sec["name"],
                                  off=sec["off"], size=sec["size"],
                                  entry_size=esz, count=len(ents),
                                  entries=[dict(crc=f"0x{e['crc']:08x}", name=e["name"])
                                           for e in ents]),
                             ensure_ascii=False, indent=2))
        else:
            print(f"{os.path.basename(args.ko)}  ELF{'32' if elf.cls == 1 else '64'}"
                  f"  {sec['name']} @0x{sec['off']:x}  "
                  f"{sec['size']} B / {esz} B = {len(ents)} 条")
            print(f"{'#':>3}  {'crc':>10}  name")
            for e in ents:
                flag = "  <- 已作废" if e["name"].startswith(MARK) else ""
                print(f"{e['i']:>3}  0x{e['crc']:08x}  {e['name']}{flag}")
        return 0

    byname = {e["name"]: e for e in ents}
    touched = []

    if args.restore:
        for e in ents:
            if e["name"].startswith(MARK):
                new = e["name"][len(MARK):]
                set_name(elf, e, new)
                touched.append((e["name"], new, e["crc"]))
    if args.drop:
        for sym in [x.strip() for x in args.drop.split(",") if x.strip()]:
            e = byname.get(sym)
            if not e:
                alt = byname.get(MARK + sym)
                if alt:
                    print(f"  = {sym} 已经是作废状态，跳过")
                    continue
                print(f"  ! {sym} 不在 __versions 里，跳过")
                continue
            set_name(elf, e, MARK + sym)
            touched.append((sym, MARK + sym, e["crc"]))
    if args.set:
        for item in [x.strip() for x in args.set.split(",") if x.strip()]:
            sym, _, val = item.partition("=")
            e = byname.get(sym) or byname.get(MARK + sym)
            if not e:
                print(f"  ! {sym} 不在 __versions 里，跳过")
                continue
            old = e["crc"]
            set_crc(elf, e, int(val, 0))
            touched.append((sym, f"crc 0x{old:08x} -> {int(val, 0):08x}", old))

    if not touched:
        raise SystemExit("✗ 没有任何改动")

    recheck(raw, elf.d, sec, elf)

    out = args.out or (os.path.splitext(args.ko)[0] + "_patched.ko")
    open(out, "wb").write(elf.d)

    print(f"已写出 {out}  （{len(elf.d):,} B，与原文件等长）")
    print("改动：")
    for a, b, c in touched:
        print(f"  - {a}")
        print(f"  + {b}")
    print("\n复核：__versions 段外字节完全一致 ✓")
    print("所有段表偏移/大小未变 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
