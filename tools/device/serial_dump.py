#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
serial_dump.py — 通过京瓷 DL 串口通道按 GPT 备份分区（只读）

依赖同目录的 serial_probe.py。

用法
    python serial_dump.py COM13 --list
    python serial_dump.py COM13 --only boot,misc --verify
    python serial_dump.py COM13 --only boot --chunk 1024
    python serial_dump.py COM13 --all --max-mb 128
    python serial_dump.py COM13 --only system --baud 921600

抗断设计（针对设备偶发 END_OF_IMAGE）
    · 单块失败 → 等 50ms 重试；两次失败 → switch-mode 重同步再试
    · 仍失败 → 把块对半拆，最小拆到 1 扇区
    · 整块成功后记住可用块大小，后续沿用
    · 分区块 .part 断点续传，中断重跑自动接着读

安全
    全程只有 0x0C 和 0xA3，没有任何写入命令。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys
import time
import zlib

try:
    import serial
except ImportError:
    sys.stderr.write("缺少 pyserial：pip install pyserial\n")
    raise SystemExit(1)

try:
    from serial_probe import (SerialLink, handshake, vendor_read, port_candidates,
                              drain, SECTOR, BAUDS)
except ImportError:
    sys.stderr.write("找不到 serial_probe.py，请把两个脚本放在同一目录\n")
    raise SystemExit(1)

READ_CRITICAL = {"sbl1", "sbl1bak", "aboot", "abootbak", "rpm", "rpmbak",
                 "tz", "tzbak", "hyp", "hypbak", "modem", "modemst1", "modemst2",
                 "fsg", "fsc", "persist", "devinfo", "keystore"}


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{int(n)}B" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}GB"


class Reader:
    """带重试、重同步、自动拆块的 0xA3 读取器。"""

    def __init__(self, link: SerialLink, ser, chunk: int):
        self.link = link
        self.ser = ser
        self.chunk = max(SECTOR, chunk - chunk % SECTOR)
        self.retries = 0

    def _resync(self) -> bool:
        try:
            drain(self.ser, 1.0)
            handshake(self.link, self.ser)
            return True
        except Exception:
            return False

    def read(self, lba: int, count: int, depth: int = 0) -> bytes:
        last = None
        for attempt in range(3):
            try:
                data = vendor_read(self.link, lba, count)
                if depth > 0 and count < self.chunk:
                    self.chunk = count
                    print(f"\n    块大小调整为 {count}B")
                time.sleep(0.01)
                return data
            except Exception as exc:
                last = exc
                self.retries += 1
                if "被拒绝" in str(exc) or "END_OF_IMAGE" in str(exc):
                    break                      # 设备明确拒绝：直接拆块，别浪费重试
                if attempt == 0:
                    time.sleep(0.05)
                else:
                    print(f"\n    ⟳ LBA {lba} 失败（{exc}），重同步…")
                    if not self._resync():
                        break
        if count > SECTOR and depth < 8:
            half = (count // 2) // SECTOR * SECTOR
            if half >= SECTOR:
                print(f"    ↳ 拆块：{count}B → {half}B + {count - half}B")
                return (self.read(lba, half, depth + 1) +
                        self.read(lba + half // SECTOR, count - half, depth + 1))
        raise last if last else RuntimeError(f"LBA {lba} 读取失败")


def parse_gpt(r: Reader):
    hdr = r.read(1, SECTOR)
    if hdr[:8] != b"EFI PART":
        raise RuntimeError("LBA1 不是 GPT 头")
    hdr_size = struct.unpack_from("<I", hdr, 12)[0]
    hdr_crc = struct.unpack_from("<I", hdr, 16)[0]
    entry_lba = struct.unpack_from("<Q", hdr, 72)[0]
    num = struct.unpack_from("<I", hdr, 80)[0]
    esz = struct.unpack_from("<I", hdr, 84)[0]
    ecrc = struct.unpack_from("<I", hdr, 88)[0]
    backup = struct.unpack_from("<Q", hdr, 32)[0]

    tmp = bytearray(hdr[:hdr_size])
    tmp[16:20] = b"\x00" * 4
    if (zlib.crc32(bytes(tmp)) & 0xFFFFFFFF) != hdr_crc:
        print("⚠ GPT 头 CRC 不符，分区表可能不可靠")

    if not (128 <= esz <= 4096 and 0 < num <= 1024):
        raise RuntimeError(f"分区表参数异常 num={num} esz={esz}")

    total = num * esz
    table = bytearray()
    off = 0
    print(f"  读取分区表：LBA {entry_lba}，{total}B（{total // SECTOR} 扇区）")
    while off < total:
        n = min(r.chunk, total - off)
        n -= n % SECTOR
        table.extend(r.read(entry_lba + off // SECTOR, n))
        off += n
        sys.stdout.write(f"\r    {off}/{total}B")
        sys.stdout.flush()
    sys.stdout.write("\n")
    if (zlib.crc32(bytes(table)) & 0xFFFFFFFF) != ecrc:
        print("⚠ 分区表 CRC 不符（读取可能有误，建议重跑）")

    parts = []
    for i in range(num):
        e = table[i * esz:(i + 1) * esz]
        if len(e) < 128 or e[:16] == b"\x00" * 16:
            continue
        first = struct.unpack_from("<Q", e, 32)[0]
        last = struct.unpack_from("<Q", e, 40)[0]
        name = e[56:128].decode("utf-16-le", "ignore").rstrip("\x00").strip()
        parts.append({"index": i, "name": name or f"part{i}",
                      "first": first, "sectors": last - first + 1})
    return parts, backup


def dump_one(r: Reader, part: dict, outdir: str, do_verify: bool) -> tuple[str, int]:
    size = part["sectors"] * SECTOR
    base = os.path.join(outdir, f"{part['index']:02d}_{part['name']}")
    final, temp = base + ".img", base + ".img.part"

    done = os.path.getsize(temp) if os.path.exists(temp) else 0
    done -= done % SECTOR
    if 0 < done < size:
        print(f"    续传：已有 {human(done)} / {human(size)}")

    if done >= size and os.path.exists(temp):
        os.replace(temp, final)
        print("    已完整，跳过读取")
    else:
        t0 = time.time()
        start = done
        with open(temp, "ab" if done else "wb") as fh:
            off = done
            while off < size:
                n = min(r.chunk, size - off)
                n -= n % SECTOR
                if n == 0:
                    break
                fh.write(r.read(part["first"] + off // SECTOR, n))
                off += n
                elapsed = max(time.time() - t0, 1e-6)
                speed = (off - start) / elapsed
                eta = (size - off) / speed if speed > 0 else 0
                sys.stdout.write(f"\r    {human(off)}/{human(size)}  "
                                 f"{human(speed)}/s  ETA {int(eta // 60):02d}m"
                                 f"{int(eta % 60):02d}s   ")
                sys.stdout.flush()
        sys.stdout.write("\n")
        os.replace(temp, final)

    h = hashlib.sha256()
    with open(final, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    digest = h.hexdigest()
    print(f"    SHA-256 {digest}")

    if do_verify:
        print("    回读校验…")
        h2 = hashlib.sha256()
        off = 0
        while off < size:
            n = min(r.chunk, size - off)
            n -= n % SECTOR
            h2.update(r.read(part["first"] + off // SECTOR, n))
            off += n
        print(f"    校验 {'通过' if h2.hexdigest() == digest else '失败！不要使用该镜像'}")
    return final, size


def main() -> int:
    ap = argparse.ArgumentParser(description="京瓷 DL 串口分区备份（只读）")
    ap.add_argument("port", nargs="?")
    ap.add_argument("--list", action="store_true", help="只列分区")
    ap.add_argument("--only", help="逗号分隔：分区名或序号，如 boot,misc,3")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--max-mb", type=int, default=128)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--chunk", type=int, default=4096, help="单次读取字节数，默认 4096")
    ap.add_argument("--outdir", default="dump")
    ap.add_argument("--baud", type=int)
    args = ap.parse_args()

    port = args.port
    if not port:
        cands = [p for p in port_candidates() if p[0] >= 5]
        if not cands:
            print("没找到京瓷串口，先跑 serial_probe.py --list")
            return 1
        port = cands[0][1].device
        print(f"自动选中 {port}")

    ser = None
    for baud in ((args.baud,) if args.baud else BAUDS):
        try:
            ser = serial.Serial(port, baud, timeout=0.4, write_timeout=2)
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
            link = SerialLink(ser)
            payload, _ = handshake(link, ser)
            print(f"✓ command mode，单包 {payload} B")
            break
        except Exception as exc:
            print(f"✗ {exc}")
            ser.close()
            ser = None
    if ser is None:
        return 2

    r = Reader(link, ser, min(args.chunk, payload))
    try:
        parts, backup_lba = parse_gpt(r)
        print(f"\nGPT 有效：{len(parts)} 个分区，备份头 @LBA {backup_lba}\n")
        print(f"  {'#':>2}  {'名称':<14}{'起始LBA':>11}{'大小':>10}")
        print("  " + "-" * 42)
        for p in parts:
            flag = " *" if p["name"].lower() in READ_CRITICAL else ""
            print(f"  {p['index']:>2}  {p['name']:<14}{p['first']:>11}"
                  f"{human(p['sectors'] * SECTOR):>10}{flag}")
        print("\n  * = 引导/密钥相关，写任何东西之前必须先备份")

        if args.list or not (args.only or args.all):
            print("\n加 --only boot,misc 或 --all 开始备份")
            return 0

        if args.only:
            wanted = {x.strip().lower() for x in args.only.split(",") if x.strip()}
            todo = [p for p in parts
                    if p["name"].lower() in wanted or str(p["index"]) in wanted]
            found = {p["name"].lower() for p in todo} | {str(p["index"]) for p in todo}
            missing = wanted - found
            if missing:
                print(f"⚠ 未找到：{', '.join(sorted(missing))}")
        else:
            todo = parts

        os.makedirs(args.outdir, exist_ok=True)
        ok = True
        for p in todo:
            size = p["sectors"] * SECTOR
            if not args.force and size > args.max_mb * 1024 * 1024:
                print(f"\n跳过 {p['name']}（{human(size)} > {args.max_mb}MB，用 --force）")
                continue
            print(f"\n▶ {p['name']}（{human(size)}）")
            try:
                dump_one(r, p, args.outdir, args.verify)
            except Exception as exc:
                ok = False
                print(f"\n  ✗ 中断：{exc}")
                print("  → 已写入 .part，重跑同一条命令会续传")
                break

        print(f"\n输出目录：{os.path.abspath(args.outdir)}")
        if r.retries:
            print(f"重试/重同步次数：{r.retries}")
        print("完成。" if ok else "有分区未完成。")
        return 0 if ok else 3
    finally:
        ser.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n中断，.part 已保留，可续传。")
        sys.exit(130)
