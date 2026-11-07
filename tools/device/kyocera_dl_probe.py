#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kyocera_dl_probe.py — 京瓷 DL 模式（USB 0482:xxxx）厂商协议「只读」探测

背景
    京瓷部分机型的 SBL1 在 SD 卡标记（NOTPUSH / CHKCODE，内容 DEVKEYDL）触发后，
    会枚举成 0482:xxxx 而不是高通的 05c6:9008，并运行一套改过的 Sahara：
    握手完成后除了标准命令，还注册了厂商私有命令
        0xA3 = 读 eMMC（start_lba, byte_count）
        0xA1 = 写 eMMC（本脚本绝不发送）
    这套命令在 KYF37（MSM8909 / Android 5.1.1）上已实测可用，无需上传 firehose。
    KYL23 / KC-01（MSM8926 / Android 4.4.4）是否存在同样的 handler，尚未验证 ——
    本脚本就是用来验证这一点的。

本脚本只做三件事
    1. switch-mode 请求一次新的 hello → 标准 Sahara 握手 → 进入 command mode
    2. 发 0xA3 读 LBA0（可指定 --lba/--sectors），看是否返回 0xA4
    3. 可选解析 GPT、把读到的数据存盘

安全边界
    · 代码里不存在 0xA1（写）路径，也不会擦除、不会改分区表
    · 不发 USB device reset（京瓷 DL 模式对 reset 处理很差，可能把主机 USB 栈挂住）
    · 退出方式：拔 USB → 取电池 → 拔 SD 卡 → 装电池开机（SD 卡不拔会再次进 DL）

用法
    python3 kyocera_dl_probe.py --list
    python3 kyocera_dl_probe.py                      # 默认读 LBA0，1 个扇区
    python3 kyocera_dl_probe.py --gpt                # 读 LBA0 + 解析 GPT 分区表
    python3 kyocera_dl_probe.py --lba 1 --sectors 1 --out gpt_header.bin
    python3 kyocera_dl_probe.py --pid 0x0a7f --verbose

依赖
    pip install pyusb
    Linux 需要 libusb-1.0；Windows 需要用 Zadig 把 0482:xxxx 的驱动换成 WinUSB/libusb。
    Linux 权限不够时加 udev 规则：
        SUBSYSTEM=="usb", ATTR{idVendor}=="0482", MODE="0666"
    然后 sudo udevadm control --reload && sudo udevadm trigger

退出码
    0 成功读到数据        1 没找到设备        2 握手失败
    3 设备无 0xA3 handler 4 读回数据校验失败
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
import zlib

try:
    import usb.core
    import usb.util
except ImportError:  # pragma: no cover
    sys.stderr.write("缺少 pyusb，请先执行：pip install pyusb\n")
    raise SystemExit(1)


# ---------------------------------------------------------------- 常量

KYOCERA_VID = 0x0482
QUALCOMM_VID = 0x05C6
KNOWN_KYOCERA_PIDS = {
    0x0A7F: "KYF37 vendor DL（已实测）",
}

CMD_HELLO = 0x01
CMD_HELLO_RSP = 0x02
CMD_READ_DATA = 0x03
CMD_END_OF_IMAGE = 0x04
CMD_DONE_RSP = 0x06
CMD_RESET = 0x07
CMD_MEM_DEBUG = 0x09
CMD_READY = 0x0B          # command ready
CMD_SWITCH_MODE = 0x0C    # 请求切换模式 / 重新 hello
CMD_EXEC = 0x0D

CMD_VENDOR_READ = 0xA3
CMD_VENDOR_READ_RSP = 0xA4
CMD_VENDOR_WRITE = 0xA1   # 仅用于识别，本脚本不发送

CMD_NAMES = {
    CMD_HELLO: "HELLO",
    CMD_HELLO_RSP: "HELLO_RSP",
    CMD_READ_DATA: "READ_DATA",
    CMD_END_OF_IMAGE: "END_OF_IMAGE",
    CMD_DONE_RSP: "DONE_RSP",
    CMD_RESET: "RESET",
    CMD_MEM_DEBUG: "MEM_DEBUG",
    CMD_READY: "COMMAND_READY",
    CMD_SWITCH_MODE: "SWITCH_MODE",
    CMD_EXEC: "EXEC",
    CMD_VENDOR_READ: "VENDOR_READ",
    CMD_VENDOR_READ_RSP: "VENDOR_READ_RSP",
    CMD_VENDOR_WRITE: "VENDOR_WRITE",
}

MODE_COMMAND = 3
SECTOR = 512
MAX_VENDOR_PAYLOAD = 0x3E00   # 实测单次读上限，必须扇区对齐


# ---------------------------------------------------------------- 工具

def die(msg: str, code: int = 1) -> "None":
    sys.stderr.write(msg.rstrip() + "\n")
    raise SystemExit(code)


def hexdump(data: bytes, base: int = 0, limit: int = 256) -> str:
    out = []
    view = data[:limit]
    for off in range(0, len(view), 16):
        chunk = view[off:off + 16]
        hexs = " ".join(f"{b:02x}" for b in chunk)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        out.append(f"{base + off:08x}  {hexs:<47}  |{text}|")
    if len(data) > limit:
        out.append(f"... 共 {len(data)} 字节，仅显示前 {limit} 字节")
    return "\n".join(out)


def cmd_name(cmd: int) -> str:
    return CMD_NAMES.get(cmd, f"0x{cmd:02x}")


def list_usb_devices() -> int:
    print("扫描 USB（KYOCERA 0482 / Qualcomm 05c6）…\n")
    found = 0
    try:
        devices = list(usb.core.find(find_all=True))
    except Exception as exc:  # 无 libusb 后端时给出可读提示
        die(f"无法枚举 USB：{exc}\n"
            "  Linux 请确认已安装 libusb-1.0-0；Windows 请确认已用 Zadig 安装 WinUSB。")

    for dev in devices:
        if dev.idVendor not in (KYOCERA_VID, QUALCOMM_VID):
            continue
        found += 1
        tag = "KYOCERA" if dev.idVendor == KYOCERA_VID else "QUALCOMM"
        note = KNOWN_KYOCERA_PIDS.get(dev.idProduct, "")
        try:
            product = usb.util.get_string(dev, dev.iProduct) or ""
        except Exception:
            product = ""
        try:
            serial = usb.util.get_string(dev, dev.iSerialNumber) or ""
        except Exception:
            serial = ""
        print(f"  [{tag}] {dev.idVendor:04x}:{dev.idProduct:04x}  "
              f"bus {dev.bus} addr {dev.address}  {note}")
        if product:
            print(f"           product: {product}")
        if serial:
            print(f"           serial : {serial}")
        try:
            for cfg in dev:
                for itf in cfg:
                    if itf.bInterfaceClass == 0xFF or itf.bNumEndpoints:
                        eps = " ".join(
                            f"0x{ep.bEndpointAddress:02x}"
                            f"({'IN' if ep.bEndpointAddress & 0x80 else 'OUT'},"
                            f"{ep.wMaxPacketSize})"
                            for ep in itf
                        )
                        print(f"           itf {itf.bInterfaceNumber}: "
                              f"class 0x{itf.bInterfaceClass:02x} eps {eps}")
        except Exception:
            pass
    if not found:
        print("  没有找到 0482 / 05c6 设备。")
        print("  · 若屏幕停在开机 logo、lsusb 也没有 0482：说明还没进 DL 模式")
        print("  · 若看到 05c6:9008：这是高通标准 EDL，不是京瓷厂商协议，本脚本不适用")
        return 1
    return 0


# ---------------------------------------------------------------- 传输层

class Link:
    """Sahara 报文收发：8 字节头（cmd, len）+ 负载，全部 little-endian uint32。"""

    def __init__(self, dev, ep_out, ep_in, in_size: int, timeout: float, verbose: bool):
        self.dev = dev
        self.ep_out = ep_out
        self.ep_in = ep_in
        self.in_size = in_size
        self.timeout = timeout
        self.verbose = verbose

    # ---- 底层
    def send_words(self, *words: int, payload: bytes = b"") -> None:
        data = struct.pack("<" + "I" * len(words), *words) + payload
        if self.verbose:
            print(f"  -> {data[:32].hex()}{'…' if len(data) > 32 else ''} "
                  f"({len(data)}B)")
        written = self.ep_out.write(data, timeout=int(self.timeout * 1000))
        if written != len(data):
            raise IOError(f"短写：{written}/{len(data)}")

    def read_exact(self, n: int, timeout: float | None = None) -> bytes:
        timeout = self.timeout if timeout is None else timeout
        buf = bytearray()
        deadline = time.monotonic() + timeout
        while len(buf) < n:
            remain = deadline - time.monotonic()
            if remain <= 0:
                raise TimeoutError(f"读超时：已收 {len(buf)}/{n} 字节")
            chunk = bytes(self.ep_in.read(min(self.in_size, n - len(buf)),
                                          timeout=max(1, int(remain * 1000))))
            if not chunk:
                continue
            buf.extend(chunk)
            deadline = time.monotonic() + timeout
        return bytes(buf)

    def read_packet(self, timeout: float | None = None):
        """返回 (cmd, words) 或 None（超时）。words 含 cmd/len。"""
        try:
            head = self.read_exact(8, timeout)
        except TimeoutError:
            return None
        cmd, length = struct.unpack("<II", head)
        if length < 8 or length > 0x100000:
            raise ValueError(f"报文长度异常：cmd=0x{cmd:02x} len={length}")
        body = self.read_exact(length - 8, timeout) if length > 8 else b""
        raw = head + body
        words = list(struct.unpack("<" + "I" * (length // 4), raw[: length // 4 * 4]))
        if self.verbose:
            print(f"  <- cmd={cmd_name(cmd)} len={length} "
                  f"{raw[:32].hex()}{'…' if len(raw) > 32 else ''}")
        return cmd, words, raw

    def drain(self, rounds: int = 6, timeout: float = 0.05) -> None:
        """清掉设备里可能残留的报文（不影响 flash）。"""
        for _ in range(rounds):
            try:
                if not self.ep_in.read(self.in_size, timeout=int(timeout * 1000)):
                    return
            except Exception:
                return


def open_link(vid: int, pid: int | None, timeout: float, verbose: bool) -> Link:
    if pid is None:
        devs = [d for d in usb.core.find(find_all=True) if d.idVendor == vid]
        if not devs:
            die(f"没有找到 VID 0x{vid:04x} 的设备。先跑 --list 确认设备在场。", 1)
        dev = devs[0]
    else:
        dev = usb.core.find(idVendor=vid, idProduct=pid)
        if dev is None:
            die(f"没有找到 {vid:04x}:{pid:04x}。先跑 --list。", 1)

    try:
        dev.set_configuration()
    except usb.core.USBError as exc:
        # 已经配置过会报 EBUSY/“Resource busy”，不算错误
        if getattr(exc, "errno", None) not in (16, None):
            if "busy" not in str(exc).lower():
                raise

    cfg = dev.get_active_configuration()
    itf = None
    for candidate in cfg:
        if candidate.bNumEndpoints >= 2:
            itf = candidate
            break
    if itf is None:
        die("该设备没有可用的批量端点，可能不是 DL 模式。", 2)

    try:
        if dev.is_kernel_driver_active(itf.bInterfaceNumber):
            dev.detach_kernel_driver(itf.bInterfaceNumber)
    except Exception:
        pass

    usb.util.claim_interface(dev, itf.bInterfaceNumber)

    ep_out = ep_in = None
    for ep in itf:
        is_bulk = (ep.bmAttributes & 0x03) == 0x02
        if not is_bulk:
            continue
        if ep.bEndpointAddress & 0x80 and ep_in is None:
            ep_in = ep
        elif not ep.bEndpointAddress & 0x80 and ep_out is None:
            ep_out = ep
    if ep_out is None or ep_in is None:
        die("找不到 bulk IN/OUT 端点。", 2)

    in_size = ep_in.wMaxPacketSize or 4096
    if not 512 <= in_size <= 65536:
        in_size = 4096

    if verbose:
        print(f"接口 {itf.bInterfaceNumber}  OUT=0x{ep_out.bEndpointAddress:02x} "
              f"IN=0x{ep_in.bEndpointAddress:02x}  in_size={in_size}")
    return Link(dev, ep_out, ep_in, in_size, timeout, verbose)


# ---------------------------------------------------------------- 握手

def handshake(link: Link, verbose: bool):
    """返回 (max_packet_size, hello_words)；失败抛异常。"""
    link.drain()

    hello = None
    for attempt in range(1, 4):
        link.send_words(CMD_SWITCH_MODE, 12, MODE_COMMAND)
        pkt = link.read_packet(timeout=2.0)
        if pkt is None:
            if verbose:
                print(f"  第 {attempt} 次 switch-mode 无回应")
            continue
        cmd, words, _ = pkt
        if cmd == CMD_READY:
            return MAX_VENDOR_PAYLOAD, None      # 已处于 command mode
        if cmd == CMD_HELLO:
            hello = words
            break
        if cmd == CMD_END_OF_IMAGE:
            raise RuntimeError(f"设备返回 END_OF_IMAGE（0x{words[0]:02x}），通常表示上一条命令失败")

    if hello is None:
        raise TimeoutError("3 次 switch-mode 都没收到 HELLO")

    if len(hello) != 12:
        raise RuntimeError(f"HELLO 长度 {len(hello) * 4} 字节，非预期的 48 字节")

    version, min_version, max_pkt, mode = hello[2], hello[3], hello[4], hello[5]
    print(f"HELLO: 协议 v{version} (min v{min_version})  max_packet={max_pkt}  mode={mode}")

    # 标准 HELLO 响应：cmd=2, len=48, v=2, compat=1, status=0, mode=3(command)
    link.send_words(CMD_HELLO_RSP, 48, 2, 1, 0, MODE_COMMAND, 0, 0, 0, 0, 0, 0)

    for _ in range(6):
        pkt = link.read_packet(timeout=2.0)
        if pkt is None:
            raise TimeoutError("发出 HELLO 响应后没收到 COMMAND_READY")
        cmd, words, _ = pkt
        if cmd == CMD_READY:
            print("握手完成：已进入 command mode")
            return max_pkt if 512 <= (max_pkt or 0) <= 0x10000 else MAX_VENDOR_PAYLOAD, hello
        if verbose:
            print(f"  握手期间忽略报文 {cmd_name(cmd)}")
    raise TimeoutError("迟迟没有 COMMAND_READY")


# ---------------------------------------------------------------- 厂商读

def vendor_read(link: Link, lba: int, count: int, timeout: float) -> bytes:
    if count <= 0 or count % SECTOR:
        die("读取长度必须是 512 的正整数倍。", 1)
    if lba > 0xFFFFFFFF:
        die("该协议只有 32 位 LBA，超出范围。", 1)

    link.send_words(CMD_VENDOR_READ, 16, lba & 0xFFFFFFFF, count)

    try:
        head = link.read_exact(16, timeout)
    except TimeoutError:
        raise TimeoutError("0xA3 无回应 —— 这台 SBL 很可能没有厂商读 handler")

    cmd, length, echo_lba, echo_cnt = struct.unpack("<IIII", head)
    if cmd == CMD_END_OF_IMAGE:
        raise RuntimeError("设备以 END_OF_IMAGE 拒绝了 0xA3（命令不支持或状态不对）")
    if cmd != CMD_VENDOR_READ_RSP:
        raise RuntimeError(f"期望 0xA4，实际收到 0x{cmd:02x}")
    if length != 16 + count:
        raise RuntimeError(f"0xA4 长度字段异常：{length}，期望 {16 + count}")
    if echo_lba != lba or echo_cnt != count:
        raise RuntimeError(f"回显不匹配：lba={echo_lba} cnt={echo_cnt}")

    data = link.read_exact(count, timeout)
    return data


def read_range(link: Link, start_lba: int, total_bytes: int, timeout: float) -> bytes:
    """按 0x3E00 上限分块读，块大小保持扇区对齐。"""
    out = bytearray()
    chunk = min(MAX_VENDOR_PAYLOAD, total_bytes)
    chunk -= chunk % SECTOR
    chunk = max(chunk, SECTOR)
    offset = 0
    while offset < total_bytes:
        n = min(chunk, total_bytes - offset)
        n -= n % SECTOR
        if n == 0:
            break
        out.extend(vendor_read(link, start_lba + offset // SECTOR, n, timeout))
        offset += n
        pct = offset * 100 // total_bytes
        sys.stdout.write(f"\r  读取 {offset}/{total_bytes} 字节 ({pct}%)")
        sys.stdout.flush()
    sys.stdout.write("\n")
    return bytes(out)


# ---------------------------------------------------------------- GPT

def parse_gpt(link: Link, timeout: float) -> None:
    print("\n读取 GPT 头（LBA1）…")
    hdr = vendor_read(link, 1, SECTOR, timeout)
    if hdr[:8] != b"EFI PART":
        print("  LBA1 不是 GPT 头（签名不匹配），可能不是 eMMC 主盘或分区表非标准。")
        print(hexdump(hdr, base=0, limit=96))
        return

    rev = struct.unpack_from("<I", hdr, 8)[0]
    hdr_size = struct.unpack_from("<I", hdr, 12)[0]
    hdr_crc = struct.unpack_from("<I", hdr, 16)[0]
    cur_lba = struct.unpack_from("<Q", hdr, 24)[0]
    backup_lba = struct.unpack_from("<Q", hdr, 32)[0]
    first_usable = struct.unpack_from("<Q", hdr, 40)[0]
    last_usable = struct.unpack_from("<Q", hdr, 48)[0]
    disk_guid = hdr[56:72].hex()
    entry_lba = struct.unpack_from("<Q", hdr, 72)[0]
    num_entries = struct.unpack_from("<I", hdr, 80)[0]
    entry_size = struct.unpack_from("<I", hdr, 84)[0]
    entries_crc = struct.unpack_from("<I", hdr, 88)[0]

    tmp = bytearray(hdr[:hdr_size])
    tmp[16:20] = b"\x00\x00\x00\x00"
    crc_ok = (zlib.crc32(bytes(tmp)) & 0xFFFFFFFF) == hdr_crc

    print(f"  版本 0x{rev:08x}  头大小 {hdr_size}  自身 CRC {'OK' if crc_ok else '不符'}")
    print(f"  当前 LBA {cur_lba} / 备份 LBA {backup_lba}   "
          f"可用区 {first_usable}–{last_usable}")
    print(f"  分区表 @ LBA {entry_lba}，{num_entries} 项 × {entry_size} 字节")
    print(f"  disk GUID {disk_guid}")

    if entry_size < 128 or num_entries == 0 or num_entries > 1024:
        print("  分区表参数异常，跳过解析。")
        return

    total = num_entries * entry_size
    print("读取分区表…")
    table = read_range(link, entry_lba, total, timeout)
    ok = (zlib.crc32(table) & 0xFFFFFFFF) == entries_crc
    print(f"  分区表 CRC {'OK' if ok else '不符（读到的数据可能不完整）'}")

    print(f"\n  {'#':>2}  {'起始LBA':>10}  {'结束LBA':>10}  {'大小':>8}  名称")
    print("  " + "-" * 58)
    for i in range(num_entries):
        e = table[i * entry_size:(i + 1) * entry_size]
        if len(e) < 128 or e[:16] == b"\x00" * 16:
            continue
        first = struct.unpack_from("<Q", e, 32)[0]
        last = struct.unpack_from("<Q", e, 40)[0]
        name = e[56:128].decode("utf-16-le", "ignore").rstrip("\x00").strip()
        size_kb = (last - first + 1) * SECTOR / 1024
        size_txt = f"{size_kb / 1024:.1f}M" if size_kb >= 1024 else f"{size_kb:.0f}K"
        print(f"  {i:>2}  {first:>10}  {last:>10}  {size_txt:>8}  {name or '-'}")

    print("\n  提示：boot 一般在 16–40MB 之间，system 是最大的那个，"
          "misc 通常很小（<8MB），persist/modemst1/modemst2 不要乱写。")


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser(
        description="京瓷 DL 模式厂商协议只读探测（0xA3），不会写入任何数据",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--list", action="store_true", help="只枚举 USB 设备，不通信")
    ap.add_argument("--vid", default="0x0482", help="USB VID，默认 0x0482（京瓷）")
    ap.add_argument("--pid", default=None, help="USB PID，如 0x0a7f；不填则取第一个同 VID 设备")
    ap.add_argument("--lba", type=lambda s: int(s, 0), default=0, help="起始 LBA，默认 0")
    ap.add_argument("--sectors", type=int, default=1, help="读取扇区数，默认 1")
    ap.add_argument("--gpt", action="store_true", help="读完 LBA0 后再解析 GPT 分区表")
    ap.add_argument("--out", help="把读到的数据写入该文件")
    ap.add_argument("--timeout", type=float, default=5.0, help="单次读超时秒数，默认 5")
    ap.add_argument("--verbose", "-v", action="store_true", help="打印收发报文")
    args = ap.parse_args()

    if args.list:
        return list_usb_devices()

    vid = int(args.vid, 0)
    pid = int(args.pid, 0) if args.pid else None

    print("=" * 62)
    print("京瓷 DL 厂商协议探测（只读）")
    print("=" * 62)
    print("⚠ 全程只发 0xA3 读命令，不会写入/擦除任何分区。")
    print("⚠ 探测完退出：拔 USB → 取电池 → 拔 SD 卡 → 装电池开机。")
    print()

    link = open_link(vid, pid, args.timeout, args.verbose)

    try:
        max_pkt, hello = handshake(link, args.verbose)
    except TimeoutError as exc:
        print(f"\n✗ 握手失败：{exc}")
        print("  可能原因：")
        print("   · 这是高通标准 EDL（05c6:9008），不是京瓷厂商 DL —— 换机器/模式")
        print("   · 设备已经过了 Sahara 阶段，或 SBL1 里没有这个私有命令集")
        print("   · USB 线只供电不走数据，或被其他程序（QFIL/手机助手）占用")
        return 2
    except Exception as exc:
        print(f"\n✗ 握手异常：{exc}")
        return 2

    print(f"单次读上限按 {min(max_pkt or MAX_VENDOR_PAYLOAD, MAX_VENDOR_PAYLOAD)} 字节处理")

    nbytes = args.sectors * SECTOR
    print(f"\n读 LBA {args.lba}，{args.sectors} 扇区（{nbytes} 字节）…")
    try:
        data = read_range(link, args.lba, nbytes, args.timeout)
    except TimeoutError as exc:
        print(f"\n✗ {exc}")
        print("  → 结论：这台 SBL 没有 0xA3 读 handler（或需要不同的握手变体）")
        print("  → 数据没有被改动，直接按上面的步骤退出即可")
        return 3
    except Exception as exc:
        print(f"\n✗ 读失败：{exc}")
        return 4

    print(f"✓ 收到 {len(data)} 字节")
    print(hexdump(data, base=args.lba * SECTOR))

    if args.out:
        with open(args.out, "wb") as fh:
            fh.write(data)
        print(f"\n已保存到 {args.out}")

    if args.gpt:
        try:
            parse_gpt(link, args.timeout)
        except Exception as exc:
            print(f"\nGPT 解析失败：{exc}")

    print("\n完成。退出方式：拔 USB → 取电池 → 取出 SD 卡 → 装电池开机。")
    print("（SD 卡不拔，下次开机还会进 DL 模式）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n中断。设备状态未改变，按拔电流程退出。")
        sys.exit(130)
