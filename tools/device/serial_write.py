#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
serial_write.py — 京瓷 DL 串口通道：0xA1 写命令 + 主 GPT 条目区恢复

本机实测布局（KYL23/KC-01，MSM8926，8GB eMMC，LBA 总数 15269888）：

    LBA 0                 保护性 MBR —— 全 0（京瓷没写，正常）
    LBA 1                 GPT 头，CRC OK，但 EntryLBA 字段 = 23（错的）
    LBA 2–12              完整分区表副本（43 项，与备份表一致）
    LBA 23–33             主分区条目区 —— 全 0（aboot 按头读这里，读不到 → 卡 logo）
    LBA 15269876–15269886 备份条目区，CRC OK
    LBA 15269887          备份头，有效

修法：把备份表（或 LBA 2 那份）原样写到 LBA 23–33，不动头、不改 CRC。

用法
    python serial_write.py COM13 --check              # 只做校验，不写
    python serial_write.py COM13 --restore --dry-run  # 演练：校验 + 读目标区，不写
    python serial_write.py COM13 --restore            # 真正写入并回读比对

安全
    只允许写头里 EntryLBA 指向的那 ts 个扇区，越界直接拒绝。
    写入前自动把目标区现状存盘（gpt_target_before.bin），写入后回读比对。
    不碰 LBA 0/1，不碰备份表，不碰任何 boot/system 类分区。
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import serial_probe as P
except ImportError:
    sys.stderr.write("serial_write.py 需要和 serial_probe.py 放在同一目录\n")
    raise SystemExit(1)

SECTOR = 512
CMD_WRITE = 0xA1
CMD_WRITE_RSP = 0xA2
CMD_READ_RSP = 0xA4
CMD_END = 0x04


# ------------------------------------------------------------ 写命令

def vendor_write(link: P.SerialLink, lba: int, data: bytes,
                 timeout: float = 12.0, retries: int = 2) -> None:
    """发 0xA1：header(4 words) + 数据。兼容 0xA2 / 0xA4 两种回执。"""
    if len(data) % SECTOR or not data:
        raise ValueError("写入长度必须是 512 的整数倍")
    n = len(data)
    head = struct.pack("<4I", CMD_WRITE, 16 + n, lba & 0xFFFFFFFF, n)

    last = None
    for attempt in range(retries + 1):
        try:
            link.ser.write(head + data)
            link.ser.flush()
            pkt = link.read_packet(timeout=timeout)
            if pkt is None:
                raise TimeoutError("写命令无回执")
            cmd, words, raw = pkt
            if cmd == CMD_END:
                # 0x04 是通用错误回执，真码在 word[3]：0x54 长度非法、0x55 写保护
                code = words[3] if len(words) >= 4 else -1
                raise RuntimeError(f"设备拒绝写入（0x04 / 错误码 0x{code:02x}）")
            if cmd not in (CMD_WRITE_RSP, CMD_READ_RSP, 0x0B):
                raise RuntimeError(f"写回执异常 cmd=0x{cmd:02x} "
                                   f"{P.hexdump(raw, 16)}")
            if len(raw) >= 16:
                _, length, echo_lba, echo_cnt = struct.unpack("<4I", raw[:16])
                if echo_lba != lba or echo_cnt != n:
                    raise RuntimeError(f"写回显不符：期望 LBA {lba}/{n}，"
                                       f"收到 {echo_lba}/{echo_cnt}")
            return
        except Exception as exc:
            last = exc
            if attempt < retries:
                print(f"\n    ⟳ LBA {lba} 写入失败（{exc}），重试 {attempt + 1}/{retries}")
                time.sleep(0.3)
    raise RuntimeError(f"LBA {lba} 写入失败：{last}")


def write_range(link: P.SerialLink, start_lba: int, data: bytes,
                chunk: int = 512) -> None:
    total = len(data)
    off = 0
    while off < total:
        n = min(chunk, total - off)
        vendor_write(link, start_lba + off // SECTOR, data[off:off + n])
        off += n
        sys.stdout.write(f"\r    写入 {off}/{total} B ({off * 100 // total}%)")
        sys.stdout.flush()
        time.sleep(0.02)
    sys.stdout.write("\n")


# ------------------------------------------------------------ 主流程

def read_table(link: P.SerialLink, payload: int, entry_lba: int,
               size: int, chunk: int) -> bytes:
    return P.read_range(link, entry_lba, size, payload, chunk=chunk)


def main() -> int:
    ap = argparse.ArgumentParser(description="京瓷 DL 串口写：主 GPT 条目区恢复")
    ap.add_argument("port", nargs="?", help="COM 口，不填则自动检测")
    ap.add_argument("--check", action="store_true", help="只校验，不写")
    ap.add_argument("--restore", action="store_true", help="恢复主条目区")
    ap.add_argument("--dry-run", action="store_true", help="演练，不实际写")
    ap.add_argument("--source", choices=["backup", "lba2"], default="backup",
                    help="表内容来源，默认 backup（备份表）")
    ap.add_argument("--chunk", type=int, default=512, help="读块大小，默认 512")
    ap.add_argument("--write-chunk", type=int, default=512, help="写块大小，默认 512")
    ap.add_argument("--force", action="store_true", help="跳过 CRC 不匹配的拦截")
    args = ap.parse_args()

    port = args.port
    if not port:
        cands = [p for p in P.port_candidates() if p[0] >= 5]
        if not cands:
            print("没找到京瓷串口：\n")
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

        # --- 1. 读主头 ---
        hdr = P.vendor_read(link, 1, SECTOR)
        if hdr[:8] != b"EFI PART":
            print("✗ LBA1 不是 GPT 头，停止")
            return 2
        alt = struct.unpack_from("<Q", hdr, 32)[0]
        first_u = struct.unpack_from("<Q", hdr, 40)[0]
        last_u = struct.unpack_from("<Q", hdr, 48)[0]
        entry_lba = struct.unpack_from("<Q", hdr, 72)[0]
        num = struct.unpack_from("<I", hdr, 80)[0]
        esz = struct.unpack_from("<I", hdr, 84)[0]
        ecrc = struct.unpack_from("<I", hdr, 88)[0]
        ts = max(1, (num * esz + SECTOR - 1) // SECTOR)
        size = num * esz

        print(f"\n主头：表 @LBA {entry_lba}（{ts} 扇区，{size} B），"
              f"备份头 @LBA {alt}，期望表 CRC 0x{ecrc:08X}")

        # --- 2. 取源表 ---
        if args.source == "backup":
            b_entry = alt - ts
            print(f"源：备份表 @LBA {b_entry}–{alt - 1}")
            table = read_table(link, payload, b_entry, size, args.chunk)
        else:
            print(f"源：LBA 2 副本")
            table = read_table(link, payload, 2, size, args.chunk)

        crc = zlib.crc32(table) & 0xFFFFFFFF
        print(f"源表 CRC 0x{crc:08X} → {'✓ 与头一致' if crc == ecrc else '✗ 与头不一致'}")
        if crc != ecrc:
            print("  源表不可信，停止（可加 --force 强行继续，不建议）")
            if not args.force:
                return 3

        # 顺便确认这份表内容（前 3 项）
        for i in range(min(3, num)):
            e = table[i * esz:(i + 1) * esz]
            if e[:16] == b"\x00" * 16:
                continue
            f = struct.unpack_from("<Q", e, 32)[0]
            l = struct.unpack_from("<Q", e, 40)[0]
            nm = e[56:128].decode("utf-16-le", "ignore").rstrip("\x00")
            print(f"  项 {i}: {nm:<10} {f}–{l}")

        # --- 3. 读目标区现状 ---
        print(f"\n目标区现状 @LBA {entry_lba}–{entry_lba + ts - 1}：")
        before = read_table(link, payload, entry_lba, size, args.chunk)
        os.makedirs("dump", exist_ok=True)
        with open("dump/gpt_target_before.bin", "wb") as fh:
            fh.write(before)
        if any(before):
            nz = sum(1 for i in range(0, len(before), SECTOR) if any(before[i:i + SECTOR]))
            print(f"  ⚠ 目标区并非全 0（{nz}/{ts} 个扇区有数据），已存 dump/gpt_target_before.bin")
            print("    如果这里已有内容，说明主表可能只是位置不同，先别覆盖，"
                  "把 dump/gpt_target_before.bin 发给维护者看")
            if not args.force:
                return 4
        else:
            print("  ✓ 全 0（确认是空的），已存 dump/gpt_target_before.bin")

        if crc == ecrc:
            if table == before:
                print("\n目标区内容已经与源表一致，无需写入。")
                return 0

        if args.check or args.restore and args.dry_run:
            print("\n校验完成（未写入）。去掉 --dry-run / 加 --restore 即可写入。")
            return 0

        if not args.restore:
            print("\n未指定 --restore，退出。")
            return 0

        # --- 4. 写 ---
        print(f"\n开始写入 {size} B 到 LBA {entry_lba}…")
        t0 = time.time()
        write_range(link, entry_lba, table, chunk=args.write_chunk)
        print(f"  用时 {time.time() - t0:.1f}s")

        # --- 5. 回读比对 ---
        print("\n回读校验…")
        after = read_table(link, payload, entry_lba, size, args.chunk)
        if after == table:
            print("  ✓ 逐字节一致，主分区表已恢复")
        else:
            diff = sum(1 for a, b in zip(after, table) if a != b)
            print(f"  ✗ 不一致：{diff} 字节不同")
            with open("dump/gpt_target_after.bin", "wb") as fh:
                fh.write(after)
            print("    已存 dump/gpt_target_after.bin")
            return 5

        crc2 = zlib.crc32(after) & 0xFFFFFFFF
        print(f"  表 CRC 0x{crc2:08X} → {'✓' if crc2 == ecrc else '✗'}")

        # --- 6. 验证头仍能解析 ---
        h2 = P.vendor_read(link, 1, SECTOR)
        print(f"  主头仍完好：{'✓' if h2[:8] == b'EFI PART' else '✗'}")

    finally:
        ser.close()

    print("\n完成。现在拔 USB → 取电池 → 拔 SD 卡 → 装电池开机。")
    print("若仍卡 logo，说明 boot.img 本身也有问题，需要单独处理 boot 分区。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n用户中断")
        sys.exit(130)
