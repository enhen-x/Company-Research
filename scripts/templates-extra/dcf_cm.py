#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FCFF DCF 模板（参数化，2026-08-15 由中国移动公司专用版改造）。

用法：
    python dcf_cm.py --config input/dcf_cm_input.json [--out reports/dcf_cm_output.json]

输入 JSON 字段（全部必填，金额统一为亿元）：
{
  "company": "中国移动", "code": "600941.SH", "date": "2026-08-15",
  "shares_mm": 216870.0,                  # 总股本（百万股）
  "net_cash_yi": 2229.12,                 # 净现金（亿元）
  "fcf_paths": {                          # 各情景 5 年 FCF 路径（亿元）
    "悲观": [900, 950, 1000, 1050, 1100],
    "基准": [1150, 1200, 1250, 1300, 1350],
    "乐观": [1350, 1400, 1450, 1500, 1550]
  },
  "wacc_grid": [0.045, 0.05, 0.055, 0.06],
  "g_grid": [0.0, 0.005, 0.01, 0.015],
  "base_scenario": "基准", "base_wacc": 0.055, "base_g": 0.01,
  "price": 17.01,                # 可选：当前股价，用于校验 DCF 每股价值与现价比值是否异常（单位错误拦截）
  "口径": "FCFF；净现金 2,229.12 亿（2026-06-30 广义 3,217.40 - 有息负债 988.28）；股本 216.87 亿股；金额亿元",
  "terminal_note": "终值占比约 79%-82%，DCF 对 g 与 WACC 高度敏感，仅作相对估值交叉锚（GG 主导）"
}

输出：reports/dcf_cm_output.json（meta/scenarios/sensitivity_基准/terminal_note，per_share 元/股）。
改造前为模板内硬编码公司参数；现在全部由 --config 驱动，复制到项目 scripts/ 后只需写输入 JSON。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def pv(fcf_path, wacc, g, net_cash_yi, shares_mm):
    yrs = len(fcf_path)
    disc = [(1 + wacc) ** (i + 1) for i in range(yrs)]
    pv_fcf = sum(f / d for f, d in zip(fcf_path, disc))
    tv = fcf_path[-1] * (1 + g) / (wacc - g)
    pv_tv = tv / disc[-1]
    ev = pv_fcf + pv_tv
    equity = ev + net_cash_yi
    return {
        "wacc": round(wacc, 4),
        "g": round(g, 4),
        "pv_fcf": round(pv_fcf, 1),
        "pv_tv": round(pv_tv, 1),
        "ev": round(ev, 1),
        "equity": round(equity, 1),
        "per_share": round(equity * 100 / shares_mm, 2),
        "tv_share": round(pv_tv / ev, 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="FCFF DCF 模板（--config 参数化）")
    ap.add_argument("--config", required=True, help="input/dcf_cm_input.json（字段见文件头部）")
    ap.add_argument("--out", default="", help="输出路径（默认 reports/dcf_cm_output.json）")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    ROOT = Path(__file__).resolve().parents[1]
    OUT = Path(args.out) if args.out else ROOT / "reports" / "dcf_cm_output.json"
    OUT.parent.mkdir(parents=True, exist_ok=True)

    shares_mm = float(cfg["shares_mm"])
    net_cash = float(cfg["net_cash_yi"])
    paths = cfg["fcf_paths"]
    wacc_grid, g_grid = cfg["wacc_grid"], cfg["g_grid"]
    base_name = cfg.get("base_scenario", "基准")
    base_wacc, base_g = cfg.get("base_wacc", 0.055), cfg.get("base_g", 0.01)
    price_ref = float(cfg.get("price", 0) or 0)

    out = {
        "meta": {
            "company": cfg["company"], "code": cfg["code"], "date": cfg["date"],
            "口径": cfg.get("口径", ""),
        },
        "fcf_paths": paths,
        "scenarios": {},
        "sensitivity_基准": {},
        "terminal_note": cfg.get("terminal_note", ""),
    }
    for name, path in paths.items():
        out["scenarios"][name] = pv(path, base_wacc, base_g, net_cash, shares_mm)
    base = paths.get(base_name) or list(paths.values())[0]
    for w in wacc_grid:
        row = {}
        for g in g_grid:
            row[str(g)] = pv(base, w, g, net_cash, shares_mm)["per_share"]
        out["sensitivity_基准"][str(w)] = row

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] {OUT}")
    for k, v in out["scenarios"].items():
        print(f"  {k}: {v['per_share']} 元/股（终值占比 {v['tv_share']*100:.0f}%）")
    # 输入合理性校验（2026-08-23 中远海控批次：shares_mm 单位易错 10x，静默得到错误每股值）
    for k, v in out["scenarios"].items():
        if v["per_share"] < 0.5 or v["per_share"] > 500:
            print(f"[WARN] {k} 每股价值 {v['per_share']} 元异常——请检查 shares_mm 是否为『百万股』"
                  f"（如 152.68 亿股 → 15268.136），或 fcf_paths 单位是否为亿元")
    base_px = out["scenarios"][base_name]["per_share"]
    if not (0.5 <= base_px <= 500):
        print("[FAIL] 基准每股价值超出合理区间（0.5~500 元），请修正输入后重跑")
        return 1
    if price_ref and price_ref > 0:
        ratio = base_px / price_ref
        if ratio < 0.2 or ratio > 5:
            print(f"[WARN] 基准每股价值 {base_px} 元 与现价 {price_ref} 元之比 {ratio:.2f} 偏离过大"
                  f"——请检查 shares_mm 是否为『百万股』（如 152.68 亿股 → 15268.136）、fcf_paths 单位是否为亿元")
    print(f"[OK] 输入校验通过：shares_mm={shares_mm} 百万股，基准每股 {base_px} 元")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())