#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SOTP 分部估值（Sum-of-the-Parts）模板 —— 平台型公司强制模块（2026-08-22 新增）

用途：当标的为「平台型/多估值锚」公司（如昊华科技：氟化工周期+电子特气成长+航空材料稀缺，
     分部适用估值方法/倍数差异大）时，单一综合 PE/PB 会掩盖"现价透支来自哪个分部"，
     必须用 SOTP 分部估值交叉验证（company-research B4.6 + framework.md §B4.6-SOTP）。

触发规则（detect_platform，可自动计算；满足任一组合即建议触发，最终由分析确认）：
  C1 分部数 ≥3 且最大分部营收占比 ≤70%（多业务并存，非单一主导）
  C2 第二大分部占比 ≥10%（存在第二个有分量的业务）
  C3 分部间估值锚差异大：分部营收 CAGR 极差 >20%（成本结构/成长性分化 → 适用不同估值方法）
  C4 存在"成长/主题分部"（agent 在 sotp_输入.json 标注 growth=true 确认）
  建议触发：C1 且（C2 或 C3 或 C4）；单一业务公司（最大分部 >70%）不触发。

用法：
  python sotp_valuation.py --dir <批次目录> --detect-only    # 只检测平台型并写 input/sotp_触发.json
  python sotp_valuation.py --dir <批次目录>                  # 检测 + 计算，输出 reports/sotp_输出.json
  python sotp_valuation.py --selftest                         # 用昊华科技校准用例自检

输入：input/sotp_输入.json（分部盈利/倍数/调整项；分部净利为估算时须标注"手算/补充"）
输出：reports/sotp_输出.json（纯 JSON，全部数字可复算）+ input/sotp_触发.json（触发状态）
图表：图18 由 analyze_charts.py fig_sotp 生成（ops 键 sotp，数据来自 sotp_输出.json）

计算链：
  分部价值_i = 分部盈利_i × 倍数_i            # basis=net_profit: PE；basis=ebitda: EV/EBITDA（扣该分部净债务）
  EV = Σ 分部价值_i
  股权价值 = EV × 控股折价 + 净现金 − 少数股东权益 ± 其他
  每股 SOTP = 股权价值 / 总股本；区间 = [低倍数加总, 高倍数加总]
  溢价 = 现价 / SOTP − 1；贡献度 = 分部价值 / EV
结论模板（脚本生成，报告 §6 SOTP 小节引用）：识别"现价透支来自哪个分部"+"市场隐含 vs SOTP 加权倍数"。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def detect_platform(segment: dict | None) -> dict:
    """从 运营补充数据.json 的 segment 键自动检测平台型公司。segment 结构：
    {"labels":["2023","2024","2025"], "series":[{"name":"A","values":[1,2,3]}], ...}"""
    reasons, checks = [], {}
    if not segment or not segment.get("series") or not segment.get("labels"):
        return {"enabled": False, "reasons": ["无分部数据（segment 缺失），无法检测，默认不触发"], "checks": checks}
    n = len(segment["labels"])
    last_idx = n - 1
    rows = []
    for s in segment["series"]:
        vals = s.get("values", [])
        if len(vals) > last_idx:
            v = float(vals[last_idx])
            if v > 0:
                rows.append({"name": s["name"], "revenue": v})
    total = sum(r["revenue"] for r in rows)
    for r in rows:
        r["pct"] = r["revenue"] / total
    rows.sort(key=lambda r: -r["pct"])
    n_seg = len(rows)
    max_pct = rows[0]["pct"] if rows else 0.0
    sec_pct = rows[1]["pct"] if len(rows) > 1 else 0.0
    checks["分部数"] = n_seg
    checks["最大分部占比"] = round(max_pct, 4)
    checks["第二大分部占比"] = round(sec_pct, 4)
    c1 = n_seg >= 3 and max_pct <= 0.70
    c2 = sec_pct >= 0.10
    growth = []
    if len(segment["labels"]) >= 2:
        first_idx = 0
        for s in segment["series"]:
            vals = s.get("values", [])
            if len(vals) > first_idx and len(vals) > last_idx:
                v0, v1 = float(vals[first_idx]), float(vals[last_idx])
                if v0 > 0 and v1 > 0:
                    growth.append((v1 / v0) ** (1 / max(last_idx - first_idx, 1)) - 1)
    g_range = (max(growth) - min(growth)) if len(growth) >= 2 else 0.0
    checks["分部营收CAGR极差"] = round(g_range, 4)
    c3 = g_range > 0.20
    c4 = False  # 由 agent 在 sotp_输入.json 标注 growth=true 确认
    reasons.append(f"C1 分部数 {n_seg}≥3 且最大占比 {max_pct:.1%}≤70%: {'✓' if c1 else '✗'}")
    reasons.append(f"C2 第二大分部占比 {sec_pct:.1%}≥10%: {'✓' if c2 else '✗'}")
    reasons.append(f"C3 分部营收CAGR极差 {g_range:.1%}>20%（成长/成本分化→估值锚不同）: {'✓' if c3 else '✗'}")
    reasons.append("C4 存在成长/主题分部：由分析在 sotp_输入.json 标注 growth=true 确认")
    enabled = c1 and (c2 or c3 or c4)
    verdict = "平台型公司（建议强制 SOTP）" if enabled else "非平台型（SOTP 可选/跳过）"
    reasons.append(f"判定：{verdict}")
    return {"enabled": enabled, "reasons": reasons, "checks": checks}


def compute_sotp(cfg: dict) -> dict:
    price = cfg["price"]
    shares = cfg["shares"]
    segs = cfg["segments"]
    adj = cfg.get("adjustments", {})
    holding_discount = float(adj.get("holding_discount", 1.0))
    net_cash = float(adj.get("net_cash", 0.0))
    minority = float(adj.get("minority", 0.0))   # 正数=扣除
    other = float(adj.get("other", 0.0))

    out_segs, ev, ev_low, ev_high = [], 0.0, 0.0, 0.0
    for s in segs:
        profit = float(s["profit"])
        m = float(s["multiple"])
        ml = float(s.get("multiple_low", m))
        mh = float(s.get("multiple_high", m))
        v, vl, vh = profit * m, profit * ml, profit * mh
        ev += v; ev_low += vl; ev_high += vh
        out_segs.append({
            "name": s["name"], "basis": s.get("basis", "net_profit"), "profit": profit,
            "method": s.get("method", "PE"), "peer": s.get("peer", ""),
            "multiple": m, "multiple_low": ml, "multiple_high": mh,
            "value": round(v, 1), "value_low": round(vl, 1), "value_high": round(vh, 1),
            "growth": s.get("growth"), "note": s.get("note", ""),
        })
    for o in out_segs:
        o["pct"] = round(o["value"] / ev, 4) if ev else 0.0

    equity = ev * holding_discount + net_cash - minority + other
    equity_low = ev_low * holding_discount + net_cash - minority + other
    equity_high = ev_high * holding_discount + net_cash - minority + other
    per = equity / shares
    per_low = equity_low / shares
    per_high = equity_high / shares
    premium = price / per - 1 if per else None

    total_profit = sum(o["profit"] for o in out_segs if o["basis"] == "net_profit")
    actual_np = cfg.get("net_profit_actual")
    np_denom = actual_np if actual_np else total_profit
    weighted_pe = (ev / total_profit) if total_profit else None
    implied_pe = (price * shares) / np_denom if np_denom else None

    top2 = sorted(out_segs, key=lambda o: -o["value"])[:2]
    conclusion = (
        f"SOTP 分部估值：{len(out_segs)} 个分部按各自估值锚加总，EV≈{ev:.0f} 亿元"
        f"（区间 [{ev_low:.0f}, {ev_high:.0f}]），经控股折价 {holding_discount:.2f}×、净现金 {net_cash:.1f} 亿、"
        f"少数股东 −{minority:.1f} 亿后，股权价值≈{equity:.0f} 亿，每股 SOTP={per:.1f} 元"
        f"（区间 [{per_low:.1f}, {per_high:.1f}]）。现价 {price:.2f} 元较 SOTP 中枢溢价 {premium*100:.0f}%"
        f"{'、且高于 SOTP 乐观区间上沿 ' + f'{per_high:.1f}' + ' 元' if price > per_high else ''}。"
        f"价值贡献前二分部为「{top2[0]['name']}」（{top2[0]['value']:.0f} 亿，{top2[0]['pct']*100:.0f}%）与"
        f"「{top2[1]['name']}」（{top2[1]['value']:.0f} 亿，{top2[1]['pct']*100:.0f}%）。"
        f"市场隐含整体 PE≈{implied_pe:.1f}x，显著高于 SOTP 加权 PE≈{weighted_pe:.1f}x——"
        f"现价超出 SOTP 的部分为市场对全平台的主题/成长溢价，而非当期盈利支撑；"
        f"若主题/景气退潮，估值向 SOTP 中枢回归的压力大。"
    )
    return {
        "company": cfg.get("company", ""), "code": cfg.get("code", ""), "date": cfg.get("date", ""),
        "price": price, "shares": shares,
        "segments": out_segs,
        "adjustments": {"holding_discount": holding_discount, "net_cash": net_cash, "minority": minority, "other": other},
        "ev_total": round(ev, 1), "ev_low": round(ev_low, 1), "ev_high": round(ev_high, 1),
        "equity": round(equity, 1), "equity_low": round(equity_low, 1), "equity_high": round(equity_high, 1),
        "per_share": round(per, 2), "per_share_low": round(per_low, 2), "per_share_high": round(per_high, 2),
        "premium": round(premium, 4) if premium is not None else None,
        "implied_pe": round(implied_pe, 1) if implied_pe else None,
        "sotp_weighted_pe": round(weighted_pe, 1) if weighted_pe else None,
        "conclusion": conclusion,
    }


SELFTEST = {
    "company": "昊华科技", "code": "600378", "date": "2026-08-21",
    "price": 47.24, "shares": 12.9, "net_profit_actual": 14.44,
    "segments": [
        {"name": "高端氟材料", "basis": "net_profit", "profit": 7.4, "method": "PE",
         "peer": "巨化/三美/永和", "multiple": 22.0, "multiple_low": 18.0, "multiple_high": 26.0,
         "growth": 0.31, "note": "分部净利估算（毛利×净利/毛利系数），手算/补充"},
        {"name": "高端制造化工材料", "basis": "net_profit", "profit": 3.96, "method": "PE",
         "peer": "航空材料稀缺标的（无直接上市同行）", "multiple": 35.0, "multiple_low": 30.0, "multiple_high": 45.0,
         "growth": 0.03, "note": "民航轮胎/密封/涂料，稀缺溢价（主观假设）"},
        {"name": "电子化学品", "basis": "net_profit", "profit": 0.94, "method": "PE",
         "peer": "中船特气/南大光电/华特气体", "multiple": 60.0, "multiple_low": 40.0, "multiple_high": 80.0,
         "growth": 0.24, "note": "电子特气国产替代，但体量小、含氟气体均价下行，倍数低于纯特气同行"},
        {"name": "工程技术服务", "basis": "net_profit", "profit": 1.33, "method": "PE",
         "peer": "工程服务类", "multiple": 15.0, "multiple_low": 12.0, "multiple_high": 20.0,
         "growth": 0.07, "note": "碳减排 PSA/催化剂，工程服务估值"},
        {"name": "贸易及其他", "basis": "net_profit", "profit": 0.09, "method": "PE",
         "peer": "贸易类", "multiple": 10.0, "multiple_low": 8.0, "multiple_high": 12.0, "growth": -0.24, "note": ""},
    ],
    "adjustments": {"holding_discount": 1.0, "net_cash": 24.7, "minority": 6.35, "other": 0.0},
}


def main() -> int:
    ap = argparse.ArgumentParser(description="SOTP 分部估值（平台型公司强制模块）")
    ap.add_argument("--dir", default=".", help="批次目录（含 input/ 与 reports/）")
    ap.add_argument("--input", default="input/sotp_输入.json", help="SOTP 输入 JSON 路径（相对 --dir）")
    ap.add_argument("--detect-only", action="store_true", help="仅检测平台型，不计算")
    ap.add_argument("--selftest", action="store_true", help="用昊华科技校准用例自检")
    args = ap.parse_args()

    if args.selftest:
        r = compute_sotp(SELFTEST)
        print(json.dumps({k: r[k] for k in ("per_share", "per_share_low", "per_share_high", "premium", "implied_pe", "sotp_weighted_pe")}, ensure_ascii=False, indent=2))
        print("结论:", r["conclusion"])
        return 0

    root = Path(args.dir)
    ops_f = root / "input" / "运营补充数据.json"
    segment = None
    if ops_f.exists():
        try:
            segment = json.loads(ops_f.read_text(encoding="utf-8")).get("segment")
        except Exception as exc:
            print(f"[WARN] 读取运营补充数据失败: {exc}")
    trig = detect_platform(segment)
    (root / "input" / "sotp_触发.json").write_text(json.dumps(trig, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[触发] enabled={trig['enabled']}")
    for r in trig["reasons"]:
        print("   ", r)

    if args.detect_only:
        return 0

    if not trig["enabled"]:
        print("[跳过] 非平台型公司，SOTP 可选（如仍做，可手动设 sotp_输入.json 并 --force）")
        return 0

    inp_f = root / args.input
    if not inp_f.exists():
        print(f"❌ 触发平台型但缺少 {inp_f}：请按模板填写分部盈利/倍数后重跑")
        return 1
    cfg = json.loads(inp_f.read_text(encoding="utf-8"))
    cfg.setdefault("company", "")
    cfg.setdefault("code", "")
    cfg.setdefault("date", "")
    out = compute_sotp(cfg)
    out["trigger"] = trig
    (root / "reports" / "sotp_输出.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] reports/sotp_输出.json：每股 SOTP={out['per_share']} 元（区间 [{out['per_share_low']}, {out['per_share_high']}]），现价溢价 {out['premium']*100:.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
