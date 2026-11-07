#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
serial_restore.py — 通过京瓷 DL（SBL1 厂商命令）通道把备份镜像写回 eMMC

背景
    这台机器在 SBL1 停下来时（USB 0482:xxxx + 握手），aboot 还没跑，
    eMMC 的临时写保护还没被 aboot 置上，所以这个通道可以直接写
    boot / recovery / system —— 出厂产线就是走这条路。

    已经在本机验证过的部分：写 GPT 条目区 → 回读一致 → 开机正常。
    这个脚本把它扩展成「按分区名刷回任意备份镜像」。

用法
    python serial_restore.py --list
    python serial_restore.py COM13 --list
    python serial_restore.py COM13 --part recovery --wp-test
    python serial_restore.py COM13 --image dump/12_recovery.img --part recovery --verify
    python serial_restore.py COM13 --image dump/19_system.img --part system
    python serial_restore.py COM13 --image boot.img --part boot --verify
    python serial_restore.py COM13 --image boot.img --lba 0x123456 --verify
    python serial_restore.py COM13 --image system.img --part system --dry-run

    --chunk      单包数据字节数，默认 4096（固件硬上限，见下），可降不要升
    --read-chunk 回读时单次读的字节数，默认 1024；被拒会自动对半降
    --wp-test    只做「读—原样写回—再读」的写保护自检，不动数据
    --no-chunk-verify   不逐块回读（快一倍，结尾仍可用 --verify 做整体校验）
    --verify     写完后整块回读算 SHA-256 与本地比对
    --resume     从 <image>.wstate 记录的断点继续（断电/掉线后用）

单包上限是从 sbl1 里读出来的，不是试出来的
    0xA1 写处理函数 @0xf802029c：n = word[3]
        cmp.w r5, #0x1000   ; 0xf80202f0
        bls   ok            ; ≤ 4096 才去写盘
        ...  movs r0, #0x54 ; 否则回错误码 0x54
    0xA3 读处理函数 @0xf80201fc 同样卡 #0x1000（0xf802022e）。
    收包缓冲 0x1200 = 4608（0xf8021118），所以 4096 + 16 字节头刚好塞得下，
    再大连收包这一层都过不去（错误码 8）。

    设备的错误回执统一是 cmd=0x04（就是 Sahara 里的 END_OF_IMAGE），
    真正的错误码放在第 4 个字里（0xf8020440 里 str r0,[r4,#0xc]）：
        0x05 头部两个长度字段与实收不符   0x08 请求超过 4608 收包缓冲
        0x54 长度非法（0 或 > 4096）      0x55 底层 eMMC 读/写失败
    所以日志里那句 “END_OF_IMAGE” 从来都不是「镜像结束」，是「这条命令被拒」。

    还有一个后果：长度类拒绝时设备根本没把数据读完，残包留在收包缓冲里，
    后续命令会被当成垃圾解析 —— 这就是「拆块之后连 512B 也失败」的原因。
    所以长度类拒绝一律不重试、不拆块，整条链路重新握手。

安全
    · 只拦「写坏就进不了这个通道」的分区：sbl1/aboot/tz/rpm/modem/persist/misc 等，
      要写必须加 --allow-critical，且必须先 serial_dump.py 备份过。
    · boot / recovery / system 可以写坏后重进本通道救回来，所以不拦，
      只在写 boot / recovery 时提示「起不来但可救」。它们不在拒写名单里。
    · 默认拒绝写 LBA 0/1（GPT 本体），要写必须加 --gpt。
    · 镜像大于分区、或目标区间压到下一个分区，一律拒绝，不写。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import serial_probe as P
except ImportError:
    sys.stderr.write("serial_restore.py 需要和 serial_probe.py 放在同一目录\n")
    raise SystemExit(1)

SECTOR = 512
CMD_WRITE = 0xA1
CMD_WRITE_RSP = 0xA2
CMD_READ_RSP = 0xA4
CMD_READY = 0x0B
CMD_ERR = 0x04                   # 设备所有错误都用它回执，真码在 word[3]

RECV_MAX = 0x1200                # 4608：sbl1 收包缓冲，0xf8021118
MAX_CHUNK = 0x1000               # 4096：写/读各自长度硬上限，0xf80202f0 / 0xf802022e
MAX_READ = 0x1000
LENGTH_CODES = (0x08, 0x54)      # 长度类拒绝：设备没吃完数据，不能就地重试

ERR_TEXT = {
    0x05: "头部两个长度字段与实际收到的字节数不符",
    0x08: "请求超过 4608B 收包缓冲，设备根本没接收",
    0x0A: "回执长度不符",
    0x0C: "回执发送失败",
    0x17: "回执发送超时",
    0x54: "长度非法（0 或超过 4096B）",
    0x55: "底层 eMMC 读/写失败（写保护、坏块或超范围）",
}

CRITICAL = {"sbl1", "sbl1bak", "aboot", "abootbak", "rpm", "rpmbak", "tz", "tzbak",
            "hyp", "hypbak", "modem", "modemst1", "modemst2", "fsg", "fsc",
            "persist", "devinfo", "keystore", "misc", "DDR", "ssd", "sdi"}

# 写坏之后开不了机，但还能重新进 DL 通道写回来 —— 不拦，只提示
SOFT = {"boot", "recovery", "system", "bootbak", "recoverybak"}


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{int(n)}B" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}GB"


def hexdump(data: bytes, limit: int = 32) -> str:
    return " ".join(f"{b:02x}" for b in data[:limit])


class DeviceRejected(RuntimeError):
    """设备回了 0x04：命令被拒，错误码在 word[3]。"""

    def __init__(self, code: int, lba: int, n: int):
        self.code = code
        self.lba = lba
        self.n = n
        text = ERR_TEXT.get(code, "未记录的错误码")
        super().__init__(f"设备回执 0x04 错误码 0x{code:02x}（{text}）@LBA {lba} len={n}")


class LinkDead(RuntimeError):
    pass


# ------------------------------------------------------------ 传输

class Link:
    def __init__(self, ser, payload: int, chunk: int, read_chunk: int = 1024):
        self.ser = ser
        self.payload = payload or RECV_MAX
        # 单包数据上限 = min(握手报的 4608 - 16 字节头, 固件长度检查 4096)，对齐到扇区
        cap = min(self.payload - 16, MAX_CHUNK)
        cap -= cap % SECTOR
        self.chunk = max(SECTOR, min(chunk, cap))
        self.read_chunk = max(SECTOR, min(read_chunk, MAX_READ))
        self.retries = 0
        self.splits = 0
        self.dirty = False        # 上一次命令被拒，收包缓冲里可能还压着数据
        self.ref = None           # LBA 1 的原始内容，用来判断链路还活着

    # -- 底层
    def _packet(self, timeout: float):
        return P.SerialLink(self.ser, timeout).read_packet(timeout)

    def healthy(self) -> bool:
        if self.ref is None:
            return True
        try:
            return self.read(1, SECTOR) == self.ref
        except Exception:
            return False

    def resync(self, rounds: int = 3) -> bool:
        """被拒之后重新握手。设备收包缓冲里可能还留着没吃完的数据，
        只有重新握手 + 读一次 GPT 头都对得上，才算链路干净。"""
        for _ in range(rounds):
            P.drain(self.ser, 0.6)
            try:
                P.handshake(P.SerialLink(self.ser, 1.0), self.ser)
            except Exception:
                continue
            if self.healthy():
                self.dirty = False
                return True
        return False

    # -- 写
    def write(self, lba: int, data: bytes, timeout: float = 20.0) -> None:
        n = len(data)
        if n > self.chunk or n % SECTOR:
            raise ValueError(f"写长度 {n} 不合法（上限 {self.chunk}，且须 512 对齐）")
        head = struct.pack("<4I", CMD_WRITE, 16 + n, lba & 0xFFFFFFFF, n)
        self.ser.write(head + data)
        self.ser.flush()
        pkt = self._packet(timeout)
        if pkt is None:
            raise TimeoutError("写命令无回执")
        cmd, words, raw = pkt
        if cmd == CMD_ERR:
            code = words[3] if len(words) >= 4 else -1
            # 长度类拒绝里设备没把数据读完，残包还在它缓冲里；其它错误已经吃完，
            # 链路是干净的，不必每次都被迫重新握手
            self.dirty = code in LENGTH_CODES
            raise DeviceRejected(code, lba, n)
        if cmd not in (CMD_WRITE_RSP, CMD_READ_RSP, CMD_READY):
            raise RuntimeError(f"写回执异常 cmd=0x{cmd:02x} {hexdump(raw, 16)}")
        if len(raw) >= 16:
            _, length, echo_lba, echo_cnt = struct.unpack("<4I", raw[:16])
            if echo_lba != (lba & 0xFFFFFFFF) or echo_cnt != n:
                raise RuntimeError(f"写回显不符：{echo_lba}/{echo_cnt} != {lba}/{n}")

    def write_block(self, lba: int, data: bytes, depth: int = 0) -> None:
        """写一块。长度类拒绝不重试也不拆块 —— 设备没把数据吃完，
        再发什么都会被当成垃圾解析，只能整条链路重新握手。"""
        if self.dirty and not self.resync():
            raise LinkDead(
                "链路已经脏了：上一次被拒的数据还压在设备的收包缓冲里，"
                "后面的命令没法再解析。\n"
                "  处理：拔 USB → 取电池 → 等 2 秒 → 装电池重进 DL 模式，"
                "然后加 --resume 续写。")
        last = None
        for attempt in range(2):
            try:
                self.write(lba, data)
                if depth > 0 and len(data) < self.chunk:
                    self.chunk = len(data)
                    print(f"\n    块大小降为 {len(data)}B")
                return
            except DeviceRejected as exc:
                last = exc
                self.retries += 1
                if exc.code in LENGTH_CODES:
                    break
                if attempt == 0 and self.resync():
                    continue
                break
            except Exception as exc:
                last = exc
                self.retries += 1
                if attempt == 0:
                    time.sleep(0.05)
                    continue
                print(f"\n    ⟳ LBA {lba} 失败（{exc}），重同步…")
                if not self.resync():
                    break
        length_err = isinstance(last, DeviceRejected) and last.code in LENGTH_CODES
        if len(data) > SECTOR and depth < 2 and not length_err:
            half = (len(data) // 2) // SECTOR * SECTOR
            print(f"\n    ↳ 拆块：{len(data)}B → {half}B + {len(data) - half}B")
            self.splits += 1
            self.write_block(lba, data[:half], depth + 1)
            self.write_block(lba + half // SECTOR, data[half:], depth + 1)
            return
        hint = ""
        if isinstance(last, DeviceRejected) and last.code == 0x55:
            hint = ("\n  这一片 eMMC 直接拒绝写入，不是包大小的问题："
                    "写保护还在、坏块、或目标超出可用区。\n"
                    "  先在同一个分区上跑 --wp-test 确认；如果它也被 0x55 挡住，"
                    "就是写保护没清 —— 拔电池冷启动重进 DL。")
        raise RuntimeError(f"LBA {lba} 写入失败：{last}{hint}")

    # -- 读
    def read(self, lba: int, count: int) -> bytes:
        out = bytearray()
        off = 0
        while off < count:
            n = min(self.read_chunk, count - off)
            n -= n % SECTOR
            attempt = 0
            while True:
                try:
                    out.extend(P.vendor_read(P.SerialLink(self.ser),
                                             lba + off // SECTOR, n))
                    break
                except Exception as exc:
                    attempt += 1
                    # 读被拒不会留下残余数据（请求里没有 payload），可以放心对半降
                    if n > SECTOR and ("END_OF_IMAGE" in str(exc) or "拒绝" in str(exc)):
                        n = max(SECTOR, n // 2)
                        continue
                    if attempt >= 3:
                        raise RuntimeError(f"LBA {lba + off // SECTOR} 读取失败：{exc}")
                    time.sleep(0.05)
                    if attempt == 2:
                        self.resync()
            off += n
        return bytes(out)


# ------------------------------------------------------------ GPT

def load_gpt(link: Link) -> tuple[list[dict], int]:
    hdr = link.read(1, SECTOR)
    if hdr[:8] != b"EFI PART":
        raise RuntimeError("LBA1 不是 GPT 头（分区表可能已损坏，用 --lba 直接指定）")
    link.ref = hdr                     # 之后重新握手时拿它判断链路是否还活着
    entry_lba = struct.unpack_from("<Q", hdr, 72)[0]
    num = struct.unpack_from("<I", hdr, 80)[0]
    esz = struct.unpack_from("<I", hdr, 84)[0]
    if not (128 <= esz <= 4096 and 0 < num <= 1024):
        raise RuntimeError(f"GPT 参数异常 num={num} esz={esz}")
    total = num * esz
    table = bytearray()
    off = 0
    while off < total:
        n = min(4096, total - off)
        n -= n % SECTOR
        table.extend(link.read(entry_lba + off // SECTOR, n))
        off += n
    parts = []
    for i in range(num):
        e = table[i * esz:(i + 1) * esz]
        if len(e) < 128 or e[:16] == b"\x00" * 16:
            continue
        first = struct.unpack_from("<Q", e, 32)[0]
        last = struct.unpack_from("<Q", e, 40)[0]
        name = e[56:128].decode("utf-16-le", "ignore").rstrip("\x00").strip()
        parts.append({"index": i, "name": name or f"part{i}",
                      "first": first, "last": last,
                      "sectors": last - first + 1})
    return parts, entry_lba


# ------------------------------------------------------------ sparse

SPARSE_MAGIC = 0xED26FF3A


def is_sparse(path: str) -> bool:
    with open(path, "rb") as fh:
        head = fh.read(4)
    return len(head) == 4 and struct.unpack("<I", head)[0] == SPARSE_MAGIC


def expand_sparse(path: str) -> tuple[str, int]:
    """把 Android sparse 镜像展开成 raw，返回 (临时文件, 字节数)。

    ROM 包里带的 system.img 常常是 sparse；直接按 raw 写进去等于把一堆
    chunk 头当数据烧进分区，开不了机。
    """
    import tempfile

    out = tempfile.NamedTemporaryFile(prefix="sparse_", suffix=".img",
                                      dir=os.path.dirname(os.path.abspath(path)),
                                      delete=False)
    with open(path, "rb") as fh:
        hdr = fh.read(28)
        magic, major, _minor, fhsz, chsz, blk, total_blk, total_chk, _crc = \
            struct.unpack("<IHHHHIIII", hdr)
        if magic != SPARSE_MAGIC:
            raise RuntimeError("不是 sparse 镜像")
        if major != 1:
            raise RuntimeError(f"sparse 版本 {major} 不支持")
        fh.seek(fhsz)
        written = 0
        try:
            for _ in range(total_chk):
                ch = fh.read(chsz)
                if len(ch) < chsz:
                    raise RuntimeError("sparse 文件被截断")
                ctype, _res, csz, tsz = struct.unpack("<HHII", ch[:12])
                body = fh.read(tsz - chsz)
                if ctype == 0xCAC1:                     # raw
                    out.write(body)
                    written += csz * blk
                elif ctype == 0xCAC2:                   # fill
                    fill = body[:4].ljust(4, b"\x00")
                    out.write(fill * (csz * blk // 4))
                    written += csz * blk
                elif ctype == 0xCAC3:                   # don't care
                    out.seek(csz * blk - 1, os.SEEK_CUR)
                    out.write(b"\x00")
                    written += csz * blk
                elif ctype == 0xCAC4:                   # crc32
                    pass
                else:
                    raise RuntimeError(f"未知 chunk 类型 0x{ctype:04x}")
        finally:
            out.close()
    return out.name, written


# ------------------------------------------------------------ 写保护自检

def wp_test(link: Link, lba: int, name: str) -> int:
    """读一扇区 → 原样写回 → 再读比对。数据不变，只验证这一片能不能写。"""
    print(f"\n写保护自检 @{name} LBA {lba}：读 → 原样写回 → 再读")
    try:
        orig = link.read(lba, SECTOR)
    except Exception as exc:
        print(f"  ✗ 连读都失败：{exc}")
        print("    链路本身有问题，不是写保护。重新插拔后重进 DL 模式。")
        return 8
    try:
        link.write(lba, orig)
    except DeviceRejected as exc:
        if exc.code == 0x55:
            print("  ✗ 写被底层拒绝（0x55）：这一片 eMMC 是写保护状态，或落在保护区里。")
            print("    常见原因是热复位进的 DL —— aboot 上一轮置的保护还在。")
            print("    拔 USB → 取电池 → 等 2 秒 → 装电池重进 DL，再试一次。")
            return 9
        print(f"  ✗ 写被拒：{exc}")
        return 9
    except Exception as exc:
        print(f"  ✗ 写失败：{exc}")
        return 9
    try:
        back = link.read(lba, SECTOR)
    except Exception as exc:
        print(f"  ✗ 写之后读不回来：{exc}")
        return 9
    if back == orig:
        print("  ✓ 能写（写回的是原内容，分区数据没动）")
        return 0
    print("  ✗ 写完回读不一致：这一片写进去会被改写，别继续刷，先查原因")
    return 9


# ------------------------------------------------------------ 主流程

def main() -> int:
    ap = argparse.ArgumentParser(description="京瓷 DL 通道：按分区写回备份镜像")
    ap.add_argument("port", nargs="?", help="COM 口，不填则自动检测")
    ap.add_argument("--list", action="store_true", help="只列分区")
    ap.add_argument("--image", help="要写入的镜像文件")
    ap.add_argument("--part", help="目标分区名或序号，如 recovery / 12")
    ap.add_argument("--lba", type=lambda s: int(s, 0), help="直接指定起始 LBA（替代 --part）")
    ap.add_argument("--chunk", type=lambda s: int(s, 0), default=MAX_CHUNK,
                    help=f"单包数据字节数，默认 {MAX_CHUNK}，固件上限也是它")
    ap.add_argument("--read-chunk", type=lambda s: int(s, 0), default=1024,
                    help="回读单次字节数，默认 1024")
    ap.add_argument("--wp-test", action="store_true",
                    help="只做写保护自检（读→原样写回→再读），不刷镜像")
    ap.add_argument("--no-chunk-verify", action="store_true", help="不逐块回读")
    ap.add_argument("--verify", action="store_true", help="写完回读校验（>128MB 默认抽样）")
    ap.add_argument("--verify-full", action="store_true", help="无论多大都做整块 SHA-256")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--allow-critical", action="store_true")
    ap.add_argument("--gpt", action="store_true", help="允许写 LBA 0/1")
    ap.add_argument("--force", action="store_true", help="忽略镜像大于分区")
    args = ap.parse_args()

    # --- 打开串口
    port = args.port
    if not port:
        cands = [p for p in P.port_candidates() if p[0] >= 5]
        if not cands:
            print("没找到京瓷串口：\n")
            P.show_ports()
            return 1
        port = cands[0][1].device
        print(f"自动选中 {port}（{cands[0][1].description}）")

    ser = None
    payload = None
    for baud in P.BAUDS:
        try:
            ser = P.serial.Serial(port, baud, timeout=0.4, write_timeout=30)
        except Exception as exc:
            print(f"{port} @ {baud}: {exc}")
            continue
        print(f"=== {port} @ {baud} ===")
        try:
            try:
                ser.dtr = False
                ser.rts = False
            except Exception:
                pass
            payload, _ = P.handshake(P.SerialLink(ser), ser)
            break
        except Exception as exc:
            print(f"✗ {exc}")
            ser.close()
            ser = None
    if ser is None:
        print("握手失败。确认设备停在 DL 模式，且没有别的程序占用串口。")
        return 2

    if args.chunk > MAX_CHUNK:
        print(f"! --chunk {args.chunk} 超过固件上限 {MAX_CHUNK}，按 {MAX_CHUNK} 走")
    link = Link(ser, payload, min(args.chunk, MAX_CHUNK), args.read_chunk)
    print(f"✓ command mode，收包上限 {payload}B，单包数据 {link.chunk}B")

    tmp_img = None
    try:
        # --- 分区表
        parts, entry_lba = load_gpt(link)
        print(f"GPT 有效：{len(parts)} 个分区，条目区 @LBA {entry_lba}\n")
        print(f"  {'#':>2}  {'名称':<14}{'起始LBA':>11}{'扇区数':>10}{'大小':>10}")
        print("  " + "-" * 50)
        for p in parts:
            n = p["name"].lower()
            if n in {c.lower() for c in CRITICAL}:
                flag = " *"
            elif n in {c.lower() for c in SOFT}:
                flag = " ~"
            else:
                flag = ""
            print(f"  {p['index']:>2}  {p['name']:<14}{p['first']:>11}"
                  f"{p['sectors']:>10}{human(p['sectors'] * SECTOR):>10}{flag}")
        print("\n  * = 写坏即砖，连本通道都进不去；要写必须 --allow-critical")
        print("  ~ = 写坏开不了机，但能重新进本通道写回；直接写，不需 --allow-critical")

        if args.list or (not args.image and not args.wp_test):
            print("\n用法：--image <文件> --part <分区名> [--verify]")
            print("      --part <分区名> --wp-test            # 只测这一片能不能写")
            return 0

        # --- 定位目标
        if args.part:
            key = args.part.strip().lower()
            hit = [p for p in parts if p["name"].lower() == key or str(p["index"]) == key]
            if not hit:
                print(f"✗ 没有分区 {args.part}")
                return 3
            target = hit[0]
            start_lba, zone = target["first"], target["sectors"]
            name = target["name"]
        elif args.lba is not None:
            start_lba = args.lba
            nxt = min([p["first"] for p in parts if p["first"] > start_lba] or [start_lba + (1 << 20)])
            zone = nxt - start_lba
            name = f"LBA 0x{start_lba:x}"
            target = {"last": start_lba + zone - 1}
        else:
            print("✗ 需要 --part 或 --lba")
            return 3

        # --- 写保护自检（不动数据）
        if args.wp_test:
            if start_lba <= 1 and not args.gpt:
                print("\n✗ 目标是 LBA 0/1（GPT 本体），要测请加 --gpt")
                return 4
            return wp_test(link, target["last"], name)

        # --- 安全检查
        key_name = name.lower()
        if key_name in {c.lower() for c in CRITICAL} and not args.allow_critical:
            print(f"\n✗ {name} 是关键分区，写坏就是砖，这个通道也就进不去了。")
            print("  确认已用 serial_dump.py 备份，再加 --allow-critical 重跑。")
            return 4
        if key_name in {c.lower() for c in SOFT}:
            print(f"\n! {name} 写坏后开不了机，但还能冷启动重进 DL 模式写回来。")
            print("  前提是手上有这份镜像的备份。")
        if start_lba <= 1 and not args.gpt:
            print("\n✗ 目标是 LBA 0/1（GPT 本体），要写请加 --gpt")
            return 4

        # --- 镜像（sparse 先展开，否则会把 chunk 头当数据烧进去）
        img = args.image
        if is_sparse(img):
            print("\n检测到 Android sparse 镜像，展开成 raw…")
            img, size = expand_sparse(img)
            tmp_img = img
            print(f"  → {img}  {human(size)}")
        else:
            size = os.path.getsize(img)
        if size == 0:
            print("✗ 镜像是空文件")
            return 5
        if size > zone * SECTOR:
            msg = (f"✗ 镜像 {human(size)} 超过目标区 {human(zone * SECTOR)}")
            if not args.force:
                print(msg + "，拒绝写入")
                return 5
            print(msg + "，--force 继续")
        tail = size % SECTOR
        write_size = size if tail == 0 else size + SECTOR - tail
        if write_size > zone * SECTOR:
            print(f"✗ 按扇区补齐后 {human(write_size)} 仍超界，拒绝")
            return 5

        print(f"\n目标：{name} @LBA {start_lba}，可写 {human(zone * SECTOR)}")
        print(f"镜像：{img}  {human(size)}"
              + (f"（补齐到 {human(write_size)}）" if tail else ""))
        if tail:
            print("  末扇区不足 512B，会用 0xFF 补齐 —— 只在镜像本身是整扇区快照时才安全")

        h = hashlib.sha256()
        with open(img, "rb") as fh:
            for blk in iter(lambda: fh.read(1 << 20), b""):
                h.update(blk)
        digest = h.hexdigest()
        print(f"SHA-256 {digest}")

        state_path = img + ".wstate"
        off = 0
        if args.resume and os.path.exists(state_path):
            st = json.load(open(state_path))
            if st.get("sha256") == digest and st.get("start_lba") == start_lba:
                off = st.get("offset", 0) // SECTOR * SECTOR
                print(f"续写：从 {human(off)} 继续")
            else:
                print("续写状态与当前镜像/目标不符，忽略")

        if args.dry_run:
            print(f"\n[dry-run] 将写入 {human(write_size - off)} 到 LBA {start_lba + off // SECTOR}，未执行。")
            return 0

        # --- 写入
        blocks = (write_size - off + link.chunk - 1) // link.chunk
        print(f"\n开始写入（单包 {link.chunk}B，约 {blocks} 包）…")
        t0 = time.time()
        chunk_verify = not args.no_chunk_verify and write_size <= 64 * 1024 * 1024
        with open(img, "rb") as fh:
            while off < write_size:
                n = min(link.chunk, write_size - off)
                n -= n % SECTOR
                if n == 0:
                    break
                fh.seek(off)
                data = fh.read(n)
                if len(data) < n:
                    data += b"\xff" * (n - len(data))
                lba = start_lba + off // SECTOR
                link.write_block(lba, data)
                if chunk_verify:
                    back = link.read(lba, n)
                    if back != data:
                        bad = sum(1 for a, b in zip(back, data) if a != b)
                        print(f"\n  ✗ 回读不符 @LBA {lba}：{bad} 字节不同，停止")
                        json.dump({"sha256": digest, "start_lba": start_lba, "offset": off},
                                  open(state_path, "w"))
                        return 6
                off += n
                json.dump({"sha256": digest, "start_lba": start_lba, "offset": off},
                          open(state_path, "w"))
                el = max(time.time() - t0, 1e-6)
                sp = off / el
                eta = (write_size - off) / sp if sp > 0 else 0
                sys.stdout.write(f"\r    {human(off)}/{human(write_size)}  {human(sp)}/s  "
                                 f"ETA {int(eta // 60):02d}m{int(eta % 60):02d}s   ")
                sys.stdout.flush()
        sys.stdout.write("\n")
        print(f"用时 {time.time() - t0:.1f}s"
              + (f"，拆块 {link.splits} 次" if link.splits else "")
              + (f"，重试 {link.retries} 次" if link.retries else ""))

        if os.path.exists(state_path):
            os.remove(state_path)

        # --- 整体校验
        if args.verify:
            full = args.verify_full or size <= 128 * 1024 * 1024
            if full:
                print("\n整块回读校验…")
                h2 = hashlib.sha256()
                o = 0
                while o < size:
                    n = min(link.read_chunk, size - o)
                    n -= n % SECTOR
                    h2.update(link.read(start_lba + o // SECTOR, n))
                    o += n
                    sys.stdout.write(f"\r    {human(min(o, size))}/{human(size)}")
                    sys.stdout.flush()
                sys.stdout.write("\n")
                if h2.hexdigest() == digest:
                    print("  ✓ SHA-256 一致，写入内容与备份完全相同")
                else:
                    print("  ✗ SHA-256 不一致！不要重启，重新写一遍")
                    return 7
            else:
                print(f"\n抽样校验（{human(size)} 太大，整块回读要跑很久；"
                      f"要全量加 --verify-full）")
                blk = 64 * 1024
                bad = 0
                with open(img, "rb") as fh:
                    for k in range(32):
                        o = (size - blk) * k // 31
                        o -= o % SECTOR
                        fh.seek(o)
                        want = fh.read(blk)
                        got = link.read(start_lba + o // SECTOR, len(want))
                        if got != want:
                            bad += 1
                            print(f"    ✗ @{human(o)} 不符")
                print(f"  抽样 32 处，不一致 {bad} 处"
                      + ("，通过" if bad == 0 else "，别重启"))
                if bad:
                    return 7

        # 分区外溢检查：写到的最后一个 LBA 是否越界
        end_lba = start_lba + write_size // SECTOR
        if args.part and end_lba - 1 > target["last"]:
            print(f"  ⚠ 写入越过分区末尾（{end_lba - 1} > {target['last']}），检查镜像大小")

    except LinkDead as exc:
        print(f"\n✗ {exc}")
        return 8
    except Exception as exc:
        print(f"\n✗ {exc.__class__.__name__}: {exc}")
        return 9
    finally:
        ser.close()
        if tmp_img and os.path.exists(tmp_img):
            os.remove(tmp_img)

    print("\n完成。拔 USB → 取电池 → 拔 SD 卡 → 装电池开机。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n中断。加 --resume 可续写。")
        sys.exit(130)
