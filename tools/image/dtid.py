#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dtid.py — 读出原厂镜像里 DT 的「机型匹配键」，并给出 DTS 该怎么写

背景
    aboot 拉起 kernel 之前，拿自己编译进去的 (msm-id, board-id, soc_rev)
    去镜像末尾 QCDT 的条目表里逐条比对，三项全等才取那份 DTB。
    源码树里的板级 dts（比如 msm8926-720p-mtp.dts）通常还留着高通公版的
    board-id = <8 0>，跟真机对不上，编出来的镜像一律卡第一屏。

    真机的键值只能从「能开机的原厂镜像」里读——原厂 recovery.img 就是。

用法
    python dtid.py recovery_stock.img
    python dtid.py recovery_stock.img --dts msm8926-720p-mtp.dts
    python dtid.py recovery_stock.img --json

    --dts   顺便检查你的 dts 里写死的 qcom,msm-id / qcom,board-id
            是否出现在真机表里，不出现就直接判死
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_bootimg as C          # noqa: E402  复用现成的 boot 头 + QCDT 解析


def read_dts_props(path: str) -> dict:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        txt = fh.read()
    out = {}
    for key in ("qcom,msm-id", "qcom,board-id", "qcom,pmic-id"):
        m = re.search(re.escape(key) + r"\s*=\s*<([^>]*)>", txt)
        if m:
            try:
                out[key] = [int(x, 0) for x in m.group(1).split()]
            except ValueError:
                out[key] = []
        else:
            out[key] = None
    m = re.search(r'\bmodel\s*=\s*"([^"]*)"', txt)
    out["model"] = m.group(1) if m else ""
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="提取原厂镜像 QCDT 的机型匹配键")
    ap.add_argument("image", help="能开机的原厂 boot.img / recovery.img")
    ap.add_argument("--dts", help="要校验的板级 dts")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args()

    d = C.parse(args.image)
    info = C.load_dt(args.image, d)
    if not info["ok"] or info["entries"] is None:
        print(f"✗ 读不出 DT 表：{info['reason'] or info['kind']}")
        return 1
    if not info["entries"]:
        print("✗ DT 段里没有可用条目")
        return 1

    # 按 (msm-id, board-id, soc_rev) 归并，并记下每条的 model
    groups = {}
    for e in info["entries"]:
        key = (e["platform"], e["variant"], e["soc"])
        groups.setdefault(key, {"n": 0, "sizes": []})
        groups[key]["n"] += 1
        groups[key]["sizes"].append(e["size"])

    models = {}
    for f in info["fdts"]:
        models[f["off"]] = f["models"]
    # 条目偏移 → model 名字，用于人眼确认
    off2model = {f["off"]: (f["models"][0] if f["models"] else "") for f in info["fdts"]}
    entry_models = {}
    for e in info["entries"]:
        entry_models.setdefault((e["platform"], e["variant"], e["soc"]),
                                off2model.get(e["offset"], ""))

    if args.json:
        print(json.dumps({
            "image": os.path.basename(args.image),
            "format": info["kind"],
            "dt_size": info["size"],
            "fdt_count": len(info["fdts"]),
            "entry_count": len(info["entries"]),
            "keys": [{"msm_id": k[0], "board_id": k[1], "soc_rev": k[2],
                      "entries": v["n"], "model": entry_models.get(k, "")}
                     for k, v in sorted(groups.items(), key=lambda x: -x[1]["n"])],
        }, ensure_ascii=False, indent=2))
        return 0

    print(f"\n{os.path.basename(args.image)}")
    print(f"  DT 段 {info['size']:,} B  @{info['off']:,}")
    print(f"  格式 {info['kind']}")
    print(f"  FDT {len(info['fdts'])} 份，表条目 {len(info['entries'])} 条，"
          f"去重后 {len(groups)} 个匹配键\n")

    print(f"  {'msm-id':>7} {'board-id':>9} {'soc_rev':>8} {'条目':>5}  model")
    print("  " + "-" * 72)
    ranked = sorted(groups.items(), key=lambda x: -x[1]["n"])
    for (mid, bid, soc), v in ranked:
        print(f"  {mid:>7} {bid:>9} {soc:>8} {v['n']:>5}  {entry_models.get((mid, bid, soc), '')}")

    mid, bid, soc = ranked[0][0]
    print(f"\n  真机最可能的键：msm-id={mid}  board-id={bid}  soc_rev={soc}"
          f"  （{ranked[0][1]['n']} 条同键条目，说明厂商为它准备了多份 DTB）")
    print("\n  板级 dts 里应当这样写：")
    print(f"      qcom,msm-id   = <{mid} 0>;        /* 0x{mid:x} */")
    print(f"      qcom,board-id = <{bid} {soc}>;        /* 0x{bid:x} {soc} */")
    print("\n  若 dts 里不写 msm-id，则打包 DTB 时必须补参数：")
    print(f"      dtbToolCM ... -m {mid} -b {bid}")

    if args.dts:
        p = read_dts_props(args.dts)
        print(f"\n校验 {os.path.basename(args.dts)}")
        print(f"  model = \"{p['model']}\"")
        got_mid = (p["qcom,msm-id"] or [0])[0]
        bid_v = p["qcom,board-id"]
        got_bid = bid_v[0] if bid_v else 0
        got_soc = bid_v[1] if bid_v and len(bid_v) > 1 else 0
        for key, shown in (("qcom,msm-id", got_mid), ("qcom,board-id", got_bid)):
            val = p[key]
            if val is None:
                print(f"  ✗ {key} 没有写")
            else:
                print(f"  · {key} = <{' '.join(map(str, val))}>")
        combo = (got_mid, got_bid, got_soc)
        print()
        if p["qcom,msm-id"] is None:
            print("  → 结论：没有 qcom,msm-id，dtbToolCM 会填 0 或要求 -m 参数；"
                  "不补就是卡第一屏")
        elif combo in groups:
            print(f"  → 结论：三元组 ({got_mid}, {got_bid}, {got_soc}) 在真机表里，"
                  f"aboot 能选中这份 DTB ✓")
        else:
            near = [k for k in groups if k[0] == got_mid]
            print(f"  → 结论：三元组 ({got_mid}, {got_bid}, {got_soc}) 不在真机表里，"
                  f"aboot 会停在第一屏 ✗")
            if near:
                print(f"     同 msm-id 的合法 board-id："
                      f"{', '.join(str(k[1]) for k in near)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
