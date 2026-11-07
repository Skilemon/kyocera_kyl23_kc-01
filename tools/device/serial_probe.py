#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
serial_probe.py — 京瓷 DL 模式「串口」通道读写探测（默认只读）

已在 KYL23/KC-01 上验证：
    0482 设备枚举为 "KYOCERA High Speed Serial Port"（CDC），
    Sahara 报文直接跑在 COM 口上，不需要 WinUSB、不需要 firehose。
    握手：0x0C,12,3 → HELLO(48B) → HELLO_RSP → 0x0B
    读：  0xA3,16,lba,count → 0xA4 + 数据

用法
    python serial_probe.py                          # 自动找口 + 握手
    python serial_probe.py --read                   # 读 LBA0
    python serial_probe.py --lba 1 --sectors 1      # 读 GPT 头
    python serial_probe.py --gpt                    # 读 LBA0/1 + 解析分区表
    python serial_probe.py --gpt --dump-all         # 备份 GPT 里所有非空分区到 ./dump/
    python serial_probe.py --scan                   # 扫前 64MB 找非零扇区
    python serial_probe.py --map                    # 关键 LBA 只读扫描（含备份 GPT）

安全
    只发 0x0C 和 0xA3，没有任何写命令。
    退出：拔 USB → 取电池 → 拔 SD → 装电池开机（SD 不拔会再次进 DL）。
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import time
import zlib

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.stderr.write("缺少 pyserial，请先执行：pip install pyserial\n")
    raise SystemExit(1)

KYOCERA_VID = 0x0482
BAUDS = (115200, 921600, 460800, 57600)
SECTOR = 512
DEFAULT_MAX_PAYLOAD = 0x1200          # 实测 hello 报 4608，按 512 对齐 = 9 扇区

CMD_HELLO = 0x01
CMD_HELLO_RSP = 0x02
CMD_END_OF_IMAGE = 0x04
CMD_READY = 0x0B
CMD_SWITCH_MODE = 0x0C
CMD_VENDOR_READ = 0xA3
CMD_VENDOR_READ_RSP = 0xA4

NAMES = {
    CMD_HELLO: "HELLO", CMD_HELLO_RSP: "HELLO_RSP",
    CMD_END_OF_IMAGE: "END_OF_IMAGE", CMD_READY: "COMMAND_READY",
    CMD_SWITCH_MODE: "SWITCH_MODE", CMD_VENDOR_READ: "VENDOR_READ",
    CMD_VENDOR_READ_RSP: "VENDOR_READ_RSP",
}


# ------------------------------------------------------------ 基础

def hexdump(data: bytes, limit: int = 64) -> str:
    view = data[:limit]
    s = " ".join(f"{b:02x}" for b in view)
    return s + (f" …(+{len(data) - limit}B)" if len(data) > limit else "")


def port_candidates():
    scored = []
    for p in list_ports.comports():
        hwid = (p.hwid or "").upper()
        desc = " ".join(x for x in (p.description, p.manufacturer, p.product) if x).upper()
        score = 0
        if f"VID:PID={KYOCERA_VID:04X}" in hwid or f"VID_{KYOCERA_VID:04X}" in hwid:
            score += 10
        if "KYOCERA" in desc or "KYOCERA" in hwid:
            score += 5
        if "SERIAL" in desc:
            score += 1
        scored.append((score, p))
    scored.sort(key=lambda t: -t[0])
    return scored


def show_ports() -> None:
    ports = port_candidates()
    if not ports:
        print("没有检测到任何串口。")
        print("  管理员 PowerShell: Get-CimInstance Win32_SerialPort | ft DeviceID,Name,PNPDeviceID -Auto")
        return
    print(f"{'COM':<8}{'VID:PID':<14}描述")
    print("-" * 62)
    for score, p in ports:
        vidpid = f"{p.vid:04X}:{p.pid:04X}" if p.vid else "-"
        print(f"{p.device:<8}{vidpid:<14}{p.description}{'  ← 京瓷' if score >= 5 else ''}")


# ------------------------------------------------------------ 传输

class SerialLink:
    def __init__(self, ser, timeout: float = 2.0):
        self.ser = ser
        self.timeout = timeout

    def read_exact(self, n: int, timeout: float | None = None) -> bytes:
        timeout = self.timeout if timeout is None else timeout
        buf = bytearray()
        deadline = time.monotonic() + timeout
        while len(buf) < n:
            if time.monotonic() > deadline:
                raise TimeoutError(f"读超时：{len(buf)}/{n}")
            chunk = self.ser.read(n - len(buf))
            if chunk:
                buf.extend(chunk)
                deadline = time.monotonic() + timeout
        return bytes(buf)

    def read_packet(self, timeout: float | None = None):
        try:
            head = self.read_exact(8, timeout)
        except TimeoutError:
            return None
        cmd, length = struct.unpack("<II", head)
        if length < 8 or length > 0x200000:
            raise ValueError(f"长度异常 cmd=0x{cmd:02x} len={length}")
        body = self.read_exact(length - 8, timeout) if length > 8 else b""
        raw = head + body
        words = list(struct.unpack("<" + "I" * (length // 4), raw[: length // 4 * 4]))
        return cmd, words, raw

    def send(self, *words: int) -> None:
        self.ser.write(struct.pack("<" + "I" * len(words), *words))
        self.ser.flush()


def drain(ser, seconds: float = 0.4) -> bytes:
    end = time.monotonic() + seconds
    buf = bytearray()
    while time.monotonic() < end:
        chunk = ser.read(4096)
        if chunk:
            buf.extend(chunk)
            end = time.monotonic() + 0.15
    return bytes(buf)


def handshake(link: SerialLink, ser) -> tuple[int, bool]:
    """返回 (max_payload, already_command_mode)。失败抛异常。"""
    drain(ser, 0.3)
    for _ in range(3):
        link.send(CMD_SWITCH_MODE, 12, 3)
        pkt = link.read_packet(timeout=1.5)
        if pkt is None:
            continue
        cmd, words, raw = pkt
        print(f"  ← {NAMES.get(cmd, hex(cmd))} len={len(raw)} {hexdump(raw, 24)}")
        if cmd == CMD_READY:
            return DEFAULT_MAX_PAYLOAD, True
        if cmd == CMD_HELLO:
            if len(words) < 6:
                raise RuntimeError("HELLO 长度异常")
            version, minver, maxpkt, mode = words[2], words[3], words[4], words[5]
            print(f"  HELLO v{version} min v{minver} max_packet={maxpkt} mode={mode}")
            link.send(CMD_HELLO_RSP, 48, 2, 1, 0, 3, 0, 0, 0, 0, 0, 0)
            for _ in range(6):
                p2 = link.read_packet(timeout=2.0)
                if p2 is None:
                    break
                c2, _, r2 = p2
                print(f"  ← {NAMES.get(c2, hex(c2))} len={len(r2)}")
                if c2 == CMD_READY:
                    payload = maxpkt if SECTOR <= (maxpkt or 0) <= 0x10000 else DEFAULT_MAX_PAYLOAD
                    payload -= payload % SECTOR
                    return payload, False
            raise TimeoutError("没等到 COMMAND_READY")
        if cmd == CMD_END_OF_IMAGE:
            raise RuntimeError("END_OF_IMAGE：上一条命令被拒")
    raise TimeoutError("3 次 switch-mode 都没有 HELLO")


def vendor_read(link: SerialLink, lba: int, count: int, timeout: float = 3.0) -> bytes:
    link.send(CMD_VENDOR_READ, 16, lba & 0xFFFFFFFF, count)
    pkt = link.read_packet(timeout=timeout)
    if pkt is None:
        raise TimeoutError(f"LBA {lba} 无回应")
    cmd, words, raw = pkt
    if cmd == CMD_END_OF_IMAGE:
        raise RuntimeError(f"LBA {lba} 被拒绝（END_OF_IMAGE）")
    if cmd != CMD_VENDOR_READ_RSP:
        raise RuntimeError(f"LBA {lba} 期望 0xA4，收到 0x{cmd:02x}")
    _, length, echo_lba, echo_cnt = struct.unpack("<IIII", raw[:16])
    if length != 16 + count or echo_lba != lba or echo_cnt != count:
        raise RuntimeError(f"回显异常 len={length} lba={echo_lba} cnt={echo_cnt}")
    data = raw[16:]
    if len(data) < count:
        data += link.read_exact(count - len(data), timeout)
    return data[:count]


def read_range(link: SerialLink, start_lba: int, total: int, max_payload: int,
               timeout: float = 3.0, chunk: int | None = None) -> bytes:
    limit = chunk or min(max_payload, 1024)      # 设备对 >1024B 的读会回 END_OF_IMAGE
    chunk = limit - (limit % SECTOR)
    chunk = max(SECTOR, chunk)
    out = bytearray()
    off = 0
    while off < total:
        n = min(chunk, total - off)
        n -= n % SECTOR
        if n == 0:
            break
        out.extend(vendor_read(link, start_lba + off // SECTOR, n, timeout))
        off += n
        sys.stdout.write(f"\r    {off}/{total} B ({off * 100 // total}%)")
        sys.stdout.flush()
    sys.stdout.write("\n")
    return bytes(out)


# ------------------------------------------------------------ GPT

def parse_gpt(link: SerialLink, max_payload: int, save_dir: str | None = None) -> list[dict]:
    hdr = vendor_read(link, 1, SECTOR)
    if hdr[:8] != b"EFI PART":
        print("  LBA1 不是 GPT 头：", hexdump(hdr, 32))
        if not any(hdr):
            print("  → LBA1 也是全 0，说明读到的不是 user 区，或寻址基准不对")
        return []

    hdr_size = struct.unpack_from("<I", hdr, 12)[0]
    hdr_crc = struct.unpack_from("<I", hdr, 16)[0]
    entry_lba = struct.unpack_from("<Q", hdr, 72)[0]
    num = struct.unpack_from("<I", hdr, 80)[0]
    esz = struct.unpack_from("<I", hdr, 84)[0]
    ecrc = struct.unpack_from("<I", hdr, 88)[0]

    tmp = bytearray(hdr[:hdr_size])
    tmp[16:20] = b"\x00" * 4
    print(f"  GPT 头 CRC {'OK' if (zlib.crc32(bytes(tmp)) & 0xFFFFFFFF) == hdr_crc else '不符'}"
          f"，表 @LBA {entry_lba}，{num}×{esz}")

    if esz < 128 or esz > 4096 or num == 0 or num > 1024:
        print("  分区表参数异常，跳过")
        return []

    table = read_range(link, entry_lba, num * esz, max_payload)
    print(f"  分区表 CRC {'OK' if (zlib.crc32(table) & 0xFFFFFFFF) == ecrc else '不符'}")

    parts = []
    print(f"\n  {'#':>2}  {'起始':>10}  {'结束':>10}  {'大小':>8}  名称")
    print("  " + "-" * 56)
    for i in range(num):
        e = table[i * esz:(i + 1) * esz]
        if len(e) < 128 or e[:16] == b"\x00" * 16:
            continue
        first = struct.unpack_from("<Q", e, 32)[0]
        last = struct.unpack_from("<Q", e, 40)[0]
        name = e[56:128].decode("utf-16-le", "ignore").rstrip("\x00").strip()
        kb = (last - first + 1) * SECTOR / 1024
        size = f"{kb / 1024:.1f}M" if kb >= 1024 else f"{kb:.0f}K"
        print(f"  {i:>2}  {first:>10}  {last:>10}  {size:>8}  {name or '-'}")
        parts.append({"index": i, "name": name, "first": first, "last": last,
                      "sectors": last - first + 1})

    if save_dir:
        os.makedirs(save_dir, exist_ok=True)
        with open(os.path.join(save_dir, "gpt_header.bin"), "wb") as fh:
            fh.write(hdr)
        with open(os.path.join(save_dir, "gpt_entries.bin"), "wb") as fh:
            fh.write(table)
        print(f"\n  已保存 gpt_header.bin / gpt_entries.bin 到 {save_dir}")
    return parts


def parse_gpt_at(link: SerialLink, lba: int, max_payload: int,
                 chunk: int | None = None) -> list[dict]:
    """在任意 LBA 解析 GPT 头（用于主表损坏时读备份表）。"""
    hdr = vendor_read(link, lba, SECTOR)
    if hdr[:8] != b"EFI PART":
        print(f"  LBA {lba} 不是 GPT 头：{hexdump(hdr, 32)}")
        if not any(hdr):
            print("  → 全 0，这个位置没有 GPT")
        return []

    hsize = struct.unpack_from("<I", hdr, 12)[0]
    hcrc = struct.unpack_from("<I", hdr, 16)[0]
    my_lba = struct.unpack_from("<Q", hdr, 24)[0]
    alt_lba = struct.unpack_from("<Q", hdr, 32)[0]
    first_u = struct.unpack_from("<Q", hdr, 40)[0]
    last_u = struct.unpack_from("<Q", hdr, 48)[0]
    entry_lba = struct.unpack_from("<Q", hdr, 72)[0]
    num = struct.unpack_from("<I", hdr, 80)[0]
    esz = struct.unpack_from("<I", hdr, 84)[0]
    ecrc = struct.unpack_from("<I", hdr, 88)[0]

    tmp = bytearray(hdr[:hsize])
    tmp[16:20] = b"\x00" * 4
    hdr_ok = (zlib.crc32(bytes(tmp)) & 0xFFFFFFFF) == hcrc

    print(f"  头 @LBA {lba}: 自身 LBA {my_lba} / 另一份 {alt_lba}")
    print(f"  可用区 {first_u}–{last_u}，表 @LBA {entry_lba}，{num}×{esz}B，"
          f"头 CRC {'OK' if hdr_ok else '不符'}")

    if not (128 <= esz <= 4096 and 0 < num <= 1024):
        print("  参数异常，放弃")
        return []

    table = read_range(link, entry_lba, num * esz, max_payload, chunk=chunk)
    ok = (zlib.crc32(table) & 0xFFFFFFFF) == ecrc
    nonzero = sum(1 for i in range(num)
                  if table[i * esz:i * esz + 16] not in (b"", b"\x00" * 16))
    print(f"  表 CRC {'OK' if ok else '不符'}，非空条目 {nonzero}/{num}")
    if nonzero == 0:
        print("  → 表内容全 0：这份 GPT 的条目区已被清空")

    parts = []
    print(f"\n  {'#':>2}  {'起始':>10}  {'结束':>10}  {'大小':>8}  名称")
    print("  " + "-" * 56)
    for i in range(num):
        e = table[i * esz:(i + 1) * esz]
        if len(e) < 128 or e[:16] == b"\x00" * 16:
            continue
        first = struct.unpack_from("<Q", e, 32)[0]
        last = struct.unpack_from("<Q", e, 40)[0]
        name = e[56:128].decode("utf-16-le", "ignore").rstrip("\x00").strip()
        kb = (last - first + 1) * SECTOR / 1024
        size = f"{kb / 1024:.1f}M" if kb >= 1024 else f"{kb:.0f}K"
        print(f"  {i:>2}  {first:>10}  {last:>10}  {size:>8}  {name or '-'}")
        parts.append({"index": i, "name": name, "first": first,
                      "sectors": last - first + 1})
    return parts


def _sig(data: bytes) -> str:
    """给一个扇区打个可读标记：文件系统/分区表签名。"""
    if not any(data):
        return "-"
    head = data[:8]
    if head == b"EFI PART":
        return "EFI PART"
    for magic, name in ((b"\xa2\xa0\xd0\xeb", "GPT项"), (b"\x00\x00\x00\x00\x00\x00\x00\x00", "空"),
                        (b"ANDROID!", "ANDROID!"), (b"\xeb\x3c\x90", "FAT"),
                        (b"\xe2\xe1\xf5\xe0", "exFAT"), (b"MSDOS5.0", "FAT16"),
                        (b"\x53\xef", "ext"), (b"LP", "LZ4/NT")):
        if data.startswith(magic):
            return name
    if all(32 <= b < 127 for b in head):
        return head.decode("ascii")
    return "数据"


def map_lbas(link: SerialLink, samples: int = 24) -> None:
    """只读扫描：主 GPT 表区、备份 GPT、可用区抽样，判断哪些 LBA 真的能读出数据。

    全部按单扇区读（设备对多扇区读会回 END_OF_IMAGE）。
    """
    hdr = vendor_read(link, 1, SECTOR)
    if hdr[:8] != b"EFI PART":
        print("  LBA1 不是 GPT 头，无法推导布局：" + hexdump(hdr, 32))
        return

    alt = struct.unpack_from("<Q", hdr, 32)[0]
    first_u = struct.unpack_from("<Q", hdr, 40)[0]
    last_u = struct.unpack_from("<Q", hdr, 48)[0]
    entry_lba = struct.unpack_from("<Q", hdr, 72)[0]
    num = struct.unpack_from("<I", hdr, 80)[0]
    esz = struct.unpack_from("<I", hdr, 84)[0]
    ts = max(1, (num * esz + SECTOR - 1) // SECTOR)

    print(f"  主表 @LBA {entry_lba}–{entry_lba + ts - 1}（{ts} 扇区），"
          f"备份头 @LBA {alt}，可用区 {first_u}–{last_u}")

    points: list[tuple[int, str]] = [(1, "GPT头")]
    for i in range(ts):
        points.append((entry_lba + i, "主表"))
    # 标准 GPT 表位置的对照点（有些工具会把表挪回 2）
    points.append((2, "标准表位"))

    btag = ""
    if 0 < alt <= last_u + 64:
        try:
            bh = vendor_read(link, alt, SECTOR)
        except Exception as exc:
            bh = b""
            print(f"  备份头 LBA {alt} 读失败：{exc}")
        if bh[:8] == b"EFI PART":
            btag = "EFI PART"
            b_entry = struct.unpack_from("<Q", bh, 72)[0]
            print(f"  ✓ 备份头有效，备份表在 LBA {b_entry}–{b_entry + ts - 1}")
            for i in range(ts):
                points.append((b_entry + i, "备份表"))
        elif bh:
            btag = _sig(bh)
            print(f"  ✗ 备份头不是 EFI PART（{btag}）：" + hexdump(bh, 24))
        else:
            print(f"  ✗ 备份头 LBA {alt} 读不到内容")
        points.append((alt, "备份头"))

    # 可用区内均匀抽样，用来判断“是不是只有 LBA1 能读”
    span = max(1, last_u - first_u)
    for k in range(samples):
        points.append((first_u + span * k // samples, "抽样"))

    seen: set[int] = set()
    uniq = []
    for lba, tag in points:
        if lba in seen or lba < 0:
            continue
        seen.add(lba)
        uniq.append((lba, tag))

    print(f"\n  {'LBA':>12}  {'区域':<8} {'签名':<10} 前 16 字节")
    print("  " + "-" * 64)
    nz = 0
    hits: list[tuple[int, str]] = []
    for idx, (lba, tag) in enumerate(uniq, 1):
        try:
            d = vendor_read(link, lba, SECTOR)
            mark = _sig(d)
            if any(d):
                nz += 1
                hits.append((lba, mark))
            flag = "★" if any(d) else " "
            print(f"  {flag}{lba:>11}  {tag:<8} {mark:<10} {d[:16].hex(' ') if any(d) else '-'}")
        except Exception as exc:
            print(f"   {lba:>11}  {tag:<8} {'读取失败':<10} {exc}")

    print(f"\n  合计 {len(uniq)} 个点，非零 {nz} 个")
    if hits:
        print("  非零位置：" + "、".join(f"{l}({m})" for l, m in hits))
    else:
        print("  ⚠ 除 LBA1 外全部为 0 —— 说明读通道只放行了 GPT 头，或分区数据真的被擦空")


# ------------------------------------------------------------ 主流程

def main() -> int:
    ap = argparse.ArgumentParser(description="京瓷 DL 串口通道探测（只读）")
    ap.add_argument("port", nargs="?", help="COM 口，不填则自动检测")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--read", action="store_true", help="读 LBA0")
    ap.add_argument("--lba", type=lambda s: int(s, 0), default=None)
    ap.add_argument("--sectors", type=int, default=1)
    ap.add_argument("--out", help="保存读到的数据")
    ap.add_argument("--gpt", action="store_true", help="解析 GPT 并列出分区")
    ap.add_argument("--scan", action="store_true", help="扫前 64MB，找非零扇区")
    ap.add_argument("--gpt-at", type=lambda s: int(s, 0), default=None,
                    help="在指定 LBA 解析 GPT（读备份表用，如 0xE8FFFF）")
    ap.add_argument("--chunk", type=int, default=1024, help="单块字节数，默认 1024")
    ap.add_argument("--map", action="store_true", help="只读扫描关键 LBA（主表/备份表/抽样）")
    ap.add_argument("--map-samples", type=int, default=24, help="可用区抽样点数，默认 24")
    ap.add_argument("--hexdump", type=int, default=64, help="打印前 N 字节，默认 64")
    ap.add_argument("--baud", type=int)
    args = ap.parse_args()

    if args.list:
        show_ports()
        return 0

    port = args.port
    if not port:
        cands = [p for p in port_candidates() if p[0] >= 5]
        if not cands:
            print("没找到京瓷串口：\n")
            show_ports()
            return 1
        port = cands[0][1].device
        print(f"自动选中 {port}（{cands[0][1].description}）")

    ser = None
    for baud in ((args.baud,) if args.baud else BAUDS):
        try:
            ser = serial.Serial(port, baud, timeout=0.4, write_timeout=2)
        except Exception as exc:
            print(f"{port} @ {baud}: 打不开 {exc}")
            continue
        print(f"=== {port} @ {baud} ===")
        try:
            try:
                ser.dtr = False
                ser.rts = False
            except Exception:
                pass
            link = SerialLink(ser)
            payload, _ = handshake(link, ser)
            print(f"  ✓ command mode，单包上限 {payload} B")
            break
        except Exception as exc:
            print(f"  ✗ {exc}")
            ser.close()
            ser = None
            continue
    if ser is None:
        print("握手失败。确认设备仍在 DL 模式，且没有别的程序占用串口。")
        return 2

    try:
        if args.scan:
            print("\n扫描前 64MB（每 512B 标记是否全零）…")
            base = 0
            for _ in range(64 * 2):
                blk = read_range(link, base, 512 * 512, payload)   # 256KB/块
                nz = [i for i in range(0, len(blk), 512) if any(blk[i:i + 512])]
                if nz:
                    print(f"  LBA {base + nz[0] // 512} 起有数据（{len(nz)} 个非零扇区）")
                    break
                base += 512
            else:
                print("  前 64MB 全是 0 —— 读的不是 user 区，或数据通路有问题")

        if args.map:
            print("\n扫描关键 LBA（全部单扇区只读）…")
            map_lbas(link, args.map_samples)

        if args.gpt:
            print("\n解析 GPT…")
            parse_gpt(link, payload, save_dir="dump")

        if args.gpt_at is not None:
            print(f"\n解析 LBA {args.gpt_at} 的 GPT 头…")
            parse_gpt_at(link, args.gpt_at, payload, chunk=args.chunk)

        if args.read or args.lba is not None:
            lba = 0 if args.lba is None else args.lba
            n = args.sectors * SECTOR
            print(f"\n读 LBA {lba}，{args.sectors} 扇区…")
            data = read_range(link, lba, n, payload, chunk=args.chunk)
            print("  " + hexdump(data, args.hexdump))
            if not any(data):
                print("  ⚠ 全 0。若 LBA0 全 0 属正常（有些机型没有保护性 MBR），"
                      "但请用 --lba 1 确认 GPT 头")
            if args.out:
                with open(args.out, "wb") as fh:
                    fh.write(data)
                print(f"  已保存 {args.out}（{len(data)} B）")
    finally:
        ser.close()

    print("\n完成。退出：拔 USB → 取电池 → 拔 SD → 装电池开机。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n中断。")
        sys.exit(130)
