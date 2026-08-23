#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中国移动穿透回报率输入生成器（项目专用，基于 skill 通用模板 build_penetration_input.py 扩展）
差异点（口径全部写入 判断点说明）：
  1. C/D 用 TTM（2026H1 + 2025FY − 2025H1）而非最新年报（2026-08-13 中报已披露）
  2. 结余 = OCF − 实际资本开支（CONSTRUCT_LONG_ASSET），与旧基线（8/10）口径一致，便于对比
  3. M = 0.75（公司公告承诺 2024-2026 派息率 75% 以上；法2 近3年均值仅交叉参考）
  4. 股本显式 21,687 百万股（东财红筹 SHARE_CAPITAL 为空）
  5. 有息负债 = 短借+长借+应付债+短融+租赁负债+一年内到期非流动负债（口径标注）
  6. 输出 A股(CNY) 与 H股(HKD) 两份输入 JSON
用法:
    python prep_cm_inputs.py --dir 项目目录 [--price-a 97.71] [--price-h 82.05] [--fx 0.8656]
        [--rf-a 0.016964] [--rf-h 0.034] [--k 0.8] [--m 0.75] [--g 0.8]
输出:
    input/穿透回报率_输入_A.json / _H.json / 判断点说明_CM.md
"""
import argparse
import json
from pathlib import Path

import pandas as pd

UNIT = 1e6

def half_rows(df):
    df = df.copy()
    df["REPORT_DATE"] = pd.to_datetime(df["REPORT_DATE"])
    return df[df["REPORT_DATE"].dt.month.isin([6, 12])].sort_values("REPORT_DATE").drop_duplicates("REPORT_DATE", keep="last")

def annual_rows(df):
    df = df.copy()
    df["REPORT_DATE"] = pd.to_datetime(df["REPORT_DATE"])
    df = df[df["REPORT_DATE"].dt.month == 12].sort_values("REPORT_DATE")
    return df[~df["REPORT_DATE"].duplicated(keep="last")]

def v(df, col):
    return pd.to_numeric(df[col], errors="coerce").fillna(0).reset_index(drop=True) / UNIT

def d_sum(df, cols):
    return sum(v(df, c) for c in cols if c in df.columns)

def get_row(df, date):
    r = df[df["REPORT_DATE"] == pd.Timestamp(date)]
    return r.iloc[0] if len(r) else None

def val(r, col):
    if col not in r.index or pd.isna(r[col]):
        return 0.0
    return float(pd.to_numeric(r[col], errors="coerce")) / UNIT

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--price-a", type=float, default=None)
    ap.add_argument("--price-h", type=float, default=None)
    ap.add_argument("--fx", type=float, default=0.8656, help="CNY per HKD 央行中间价")
    ap.add_argument("--rf-a", type=float, default=0.016964)
    ap.add_argument("--rf-h", type=float, default=0.034)
    ap.add_argument("--k", type=float, default=0.8)
    ap.add_argument("--m", type=float, default=0.75, help="公告承诺派息率下限")
    ap.add_argument("--g", type=float, default=0.8, help="维持性Capex系数")
    ap.add_argument("--lambda", type=float, default=0.48, help="经营杠杆（默认0.48=剔除2025异常段后均值；自动λ=-1.86符号不一致弃用）")
    args = ap.parse_args()

    root = Path(args.dir)
    data = root / "data"
    pnl = half_rows(pd.read_csv(data / "利润表_按报告期.csv", encoding="utf-8-sig"))
    cf  = half_rows(pd.read_csv(data / "现金流量表_按报告期.csv", encoding="utf-8-sig"))
    bs  = half_rows(pd.read_csv(data / "资产负债表_按报告期.csv", encoding="utf-8-sig"))
    pa  = annual_rows(pd.read_csv(data / "利润表_按报告期.csv", encoding="utf-8-sig"))
    ca  = annual_rows(pd.read_csv(data / "现金流量表_按报告期.csv", encoding="utf-8-sig"))
    ba  = annual_rows(pd.read_csv(data / "资产负债表_按报告期.csv", encoding="utf-8-sig"))
    div = pd.read_csv(data / "分红送配记录.csv", encoding="utf-8-sig")
    da  = pd.read_csv(data / "日线股价_前复权.csv", encoding="utf-8-sig")
    dh  = pd.read_csv(data / "HK0941日线_前复权.csv", encoding="utf-8-sig")

    # ---- TTM ----
    def ttm(df, col, h1="2026-06-30", fy="2025-12-31", h0="2025-06-30"):
        r1, r2, r3 = get_row(df, h1), get_row(df, fy), get_row(df, h0)
        if r1 is None or r2 is None or r3 is None:
            raise RuntimeError(f"缺报告期: {col}")
        return float(v(pd.DataFrame([r1]), col).iloc[0] + v(pd.DataFrame([r2]), col).iloc[0] - v(pd.DataFrame([r3]), col).iloc[0])

    C = ttm(pnl, "PARENT_NETPROFIT")
    D = ttm(cf, "FA_IR_DEPR") + ttm(cf, "IA_AMORTIZE") + ttm(cf, "LPE_AMORTIZE") + ttm(cf, "USERIGHT_ASSET_AMORTIZE")
    capex_ttm = ttm(cf, "CONSTRUCT_LONG_ASSET")
    ocf_ttm = ttm(cf, "NETCASH_OPERATE")

    # ---- 年报序列（由新到旧）----
    years = [d.year for d in ca["REPORT_DATE"]][-6:]
    ocf_new = list(reversed(v(ca, "NETCASH_OPERATE")))[:6]
    capex_new = list(reversed(v(ca, "CONSTRUCT_LONG_ASSET")))[:6]
    rev_new = list(reversed(v(pa, "OPERATE_INCOME")))[:6]
    ni_new = list(reversed(v(pa, "PARENT_NETPROFIT")))[:6]
    surplus_new = [round(o - c, 1) for o, c in zip(ocf_new, capex_new)]
    AA_2y = round((surplus_new[0] + surplus_new[1]) / 2, 1)
    AA_all = round(sum(surplus_new[:5]) / 5, 1)
    AA_ttm = round(ocf_ttm - capex_ttm, 1)
    # D 年报（由新到旧）: 用 D 列直接算
    d_years = []
    for _, row in ca.tail(6).iterrows():
        s = 0.0
        for c in ["FA_IR_DEPR", "IA_AMORTIZE", "LPE_AMORTIZE", "USERIGHT_ASSET_AMORTIZE"]:
            if c in ca.columns and pd.notna(row[c]):
                s += float(pd.to_numeric(row[c], errors="coerce")) / UNIT
        d_years.append(round(s, 1))
    d_new = list(reversed(d_years))
    g_ratios = [round(c / d, 3) for c, d in zip(capex_new, d_new) if d > 0][:3]
    g_note = f"近3年 Capex/D&A = {g_ratios}；TTM 比值 {round(capex_ttm/D, 3)}"

    # ---- 支付率 ----
    dv = div.copy()
    dv["报告期"] = pd.to_datetime(dv["报告期"])
    dv["DPS"] = pd.to_numeric(dv["现金分红-现金分红比例"], errors="coerce") / 10.0
    dv["财年"] = dv["报告期"].dt.year
    dps_fy = dv[dv["DPS"] > 0].groupby("财年")["DPS"].sum()
    shares = 21687.0  # 百万股（A+H；东财红筹 SHARE_CAPITAL 为空）
    eps_series = {}
    for _, row in pa.tail(4).iterrows():
        y = pd.to_datetime(row["REPORT_DATE"]).year
        eps_series[y] = float(pd.to_numeric(row.get("BASIC_EPS"), errors="coerce")) if pd.notna(row.get("BASIC_EPS")) else None
    m2_list = []
    for y in [2025, 2024, 2023]:
        if y in dps_fy.index and y in ni_new[-3:]:
            pass
    ni_by_year = {int(pd.to_datetime(r["REPORT_DATE"]).year): float(pd.to_numeric(r["PARENT_NETPROFIT"], errors="coerce"))/UNIT for _, r in pa.tail(4).iterrows()}
    m2_list = [round(dps_fy[y] * shares / ni_by_year[y], 4) for y in [2025, 2024, 2023] if y in dps_fy.index and y in ni_by_year and ni_by_year[y] > 0]
    m1_list = [round(dps_fy[y] / eps_series[y], 4) for y in [2025, 2024, 2023] if y in dps_fy.index and eps_series.get(y)]
    M2_mean = round(sum(m2_list) / len(m2_list), 4) if m2_list else None
    M2_min = round(min(m2_list), 4) if m2_list else None
    M1_mean = round(sum(m1_list) / len(m1_list), 4) if m1_list else None

    # ---- 资产负债表（2026-06-30）----
    rb = get_row(bs, "2026-06-30")
    net_cash_narrow = val(rb, "MONETARYFUNDS")
    net_cash_broad = net_cash_narrow + val(rb, "TRADE_FINASSET_NOTFVTPL") + val(rb, "TRADE_FINASSET")
    debt = (val(rb, "SHORT_LOAN") + val(rb, "LONG_LOAN") + val(rb, "BOND_PAYABLE")
            + val(rb, "SHORT_BOND_PAYABLE") + val(rb, "LEASE_LIAB") + val(rb, "NONCURRENT_LIAB_1YEAR"))
    goodwill = val(rb, "GOODWILL")
    total_assets = val(rb, "TOTAL_ASSETS")
    nca = val(rb, "TOTAL_CURRENT_ASSETS") - val(rb, "TOTAL_CURRENT_LIAB")
    book_equity = val(rb, "TOTAL_PARENT_EQUITY")
    ebitda = round(ttm(pnl, "OPERATE_PROFIT") + D, 1) if "OPERATE_PROFIT" in pnl.columns else round(C + D, 1)
    fcf = round(ocf_ttm - capex_ttm, 1)
    dps_2025 = round(float(dps_fy.get(2025, 0)), 4)
    dps_2026e_mid = 2.51  # 2026 中期股息（2026-08-13 公告）
    low10_a = float(da["close"].min())
    low10_h = float(dh["close"].min())
    price_a = args.price_a if args.price_a else float(pd.read_csv(data / "日线股价.csv", encoding="utf-8-sig")["close"].iloc[-1])
    price_h = args.price_h if args.price_h else float(dh["close"].iloc[-1])

    hkd_per_cny = 1.0 / args.fx
    market_cap_a = round(price_a * shares, 1)
    market_cap_h = round(price_h * shares, 1)

    def cfg_a():
        return {
            "company": "中国移动", "code": "600941.SH", "date": "2026-08-15",
            "price": round(price_a, 2), "market_cap": market_cap_a, "shares": shares,
            "net_profit_C": round(C, 1), "depreciation_D": round(D, 1),
            "capex_ratio_G": args.g, "profit_discount_k": args.k, "payout_M": args.m,
            "aa_2y": AA_2y, "aa_all": AA_all, "rf": args.rf_a, "cycle_adjust_pct": 0.0,
            "base_revenue": round(ttm(pnl, "OPERATE_INCOME"), 1),
            "lambda": getattr(args, "lambda"),
            "surplus_series": surplus_new[:5],
            "revenue_series": [round(x, 1) for x in rev_new[:5]],
            "net_cash": round(net_cash_broad, 1), "interest_bearing_debt": round(debt, 1),
            "ebitda": ebitda, "fcf": fcf, "goodwill": round(goodwill, 1),
            "total_assets": round(total_assets, 1), "dps": dps_2025,
            "net_current_assets": round(nca, 1), "book_equity": round(book_equity, 1),
            "low_10y_close": round(low10_a, 2),
            "grid_gs": [0.5, 0.7, 0.9],
            "ii_floor": 0.035, "rf_margin": 0.02,
        }

    def cfg_h():
        c = cfg_a()
        c.update({
            "company": "中国移动", "code": "0941.HK", "date": "2026-08-15",
            "price": round(price_h, 2), "market_cap": market_cap_h,
            "rf": args.rf_h, "low_10y_close": round(low10_h, 2),
        })
        for k in ["net_profit_C", "depreciation_D", "aa_2y", "aa_all", "base_revenue",
                  "net_cash", "interest_bearing_debt", "ebitda", "fcf", "goodwill",
                  "total_assets", "net_current_assets", "book_equity"]:
            c[k] = round(c[k] * hkd_per_cny, 1)
        c["surplus_series"] = [round(x * hkd_per_cny, 1) for x in c["surplus_series"]]
        c["revenue_series"] = [round(x * hkd_per_cny, 1) for x in c["revenue_series"]]
        c['ii_floor'] = 0.05
        c['rf_margin'] = 0.03
        c['dps'] = round(dps_2025 * hkd_per_cny, 4)
        c["shares"] = shares
        return c

    ca_ = cfg_a(); ch_ = cfg_h()
    out = root / "input"
    out.mkdir(parents=True, exist_ok=True)
    (out / "穿透回报率_输入_A.json").write_text(json.dumps(ca_, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "穿透回报率_输入_H.json").write_text(json.dumps(ch_, ensure_ascii=False, indent=2), encoding="utf-8")

    fx_hkd = hkd_per_cny
    lines = [
        f"# 中国移动穿透回报率输入 — 判断点说明（2026-08-15 复评）",
        "",
        "> 由 scripts/prep_cm_inputs.py 从三表自动计算（TTM 口径），口径与旧基线（2026-08-10）的差异如下。",
        "",
        "## 关键口径（人判断点，已确认）",
        f"1. **C/D 用 TTM**（2026H1+2025FY−2025H1）：C={C:.1f} 百万 / D={D:.1f} 百万（2025 年报口径 C=137,095 / D=189,999 并列参考）",
        f"2. **结余 = OCF − 实际资本开支**（与旧基线一致）：序列(新→旧) {surplus_new}；AA_2y={AA_2y} / AA_all={AA_all} / TTM结余={AA_ttm}",
        f"3. **M = {args.m}**：公司公告承诺 2024-2026 派息率 75% 以上（2025 实际 75%，2026 中期股息 2.51 元同比+0.3%『稳中有升』）；法2 近3年 {m2_list}（均值 {M2_mean} / 最低 {M2_min}），法1 {m1_list}（均值 {M1_mean}）",
        f"4. **k = {args.k}**：中-强可预测（垄断电信，但 DICT 占比上升+2026 增值税扰动 → 保守取 0.8；0.9 作为敏感性重跑）",
        f"5. **G = {args.g}**：{g_note}；Capex 下行期（2021 峰值 2,073 亿 → 2026 指引 1,366 亿），维持性系数取 0.8",
        f"6. **股本 = {shares} 百万股**（A+H 同股同权；东财红筹 SHARE_CAPITAL 为空，显式指定）",
        f"7. **有息负债口径**（2026-06-30）：短借+长借+应付债+短融+租赁负债+一年内到期非流动负债 = {debt:.1f} 百万；广义净现金 = 货币资金+交易性金融资产 = {net_cash_broad:.1f} 百万",
        f"8. **Rf（A股）= {args.rf_a:.4f}**（中国10Y 1.6964%，2026-08-14 中债）；**Rf（H股）= {args.rf_h:.4f}**（香港10Y ~3.4%，2026-07 HKMA，估计值）；II(A)=max(3.5%, Rf+2%)；II(H)=max(5%, Rf+3%)——与旧基线（H股 Rf+2%）不同，按 methodology v2.1-beta 执行",
        f"9. **汇率**：1 HKD = {args.fx} CNY（央行中间价，需核对最新），1 CNY = {fx_hkd:.4f} HKD",
        f"10. **现价**：A股 {price_a} 元 / H股 {price_h} 港元（2026-08-14 收盘）",
        f"11. **AA 敏感性**：2025 年 OCF 单年 -26%（DICT 采购），AA_2y={AA_2y} 受其拖累；剔除 2025 年（2024/2023 均值）={(surplus_new[1]+surplus_new[2])/2:.1f}；TTM 结余 {AA_ttm}（2026H1 OCF +37% 已回升）",
        "",
        "## 输出",
        "- input/穿透回报率_输入_A.json（CNY）",
        "- input/穿透回报率_输入_H.json（HKD，全部金额×{:.4f})".format(fx_hkd),
    ]
    (out / "判断点说明_CM.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"A": ca_, "H": ch_}, ensure_ascii=False, indent=2)[:4000])

if __name__ == "__main__":
    main()
