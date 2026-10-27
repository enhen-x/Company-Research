#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运营补充数据 JSON 构建器（图表 --ops 输入，B6.1 前置）
数据来源：data/*.csv 自动计算（估值带/杠杆/DPS）+ 硬编码表（分部/同行/预测/目标价/穿透回报率，
来源与日期标注于注释与输出 JSON 的 note 字段）。
用法: python build_ops.py --dir 项目目录
输出: input/运营补充数据.json
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

UNIT = 1e6

def annual(df):
    df = df.copy()
    df["REPORT_DATE"] = pd.to_datetime(df["REPORT_DATE"])
    return df[df["REPORT_DATE"].dt.month == 12].sort_values("REPORT_DATE").drop_duplicates("REPORT_DATE", keep="last")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    args = ap.parse_args()
    root = Path(args.dir)
    data = root / "data"

    pnl = annual(pd.read_csv(data / "利润表_按报告期.csv", encoding="utf-8-sig"))
    bs = annual(pd.read_csv(data / "资产负债表_按报告期.csv", encoding="utf-8-sig"))
    cf = annual(pd.read_csv(data / "现金流量表_按报告期.csv", encoding="utf-8-sig"))
    daily = pd.read_csv(data / "日线股价.csv", encoding="utf-8-sig")
    daily_qfq = pd.read_csv(data / "日线股价_前复权.csv", encoding="utf-8-sig")
    div = pd.read_csv(data / "分红送配记录.csv", encoding="utf-8-sig")

    def col(df, name):
        return df[name] if name in df.columns else None

    shares = 21687.0  # 百万股
    # 年报系列（亿）
    rev = (pd.to_numeric(col(pnl, "OPERATE_INCOME"), errors="coerce") / 1e8).round(0).tolist()
    ni = (pd.to_numeric(col(pnl, "PARENT_NETPROFIT"), errors="coerce") / 1e8).round(0).tolist()
    ocf = (pd.to_numeric(col(cf, "NETCASH_OPERATE"), errors="coerce") / 1e8).round(0).tolist()
    # 公司披露口径资本开支（2021-2025 公司年报；2026H1 公司中报）
    capex_company = [2073, 1896, 1813, 1639, 1509, 610]
    ocf_h1 = 1149.0
    labels_cf = ["2021", "2022", "2023", "2024", "2025", "2026H1"]
    ocf_full = ocf[-5:] + [ocf_h1]
    fcf_full = [round(o - c, 0) for o, c in zip(ocf_full, capex_company)]

    # 资产负债率 & 净现金（广义=货币资金+交易性金融资产；有息=长借+短借+应付债+短融+租赁+一年内到期）
    def bsv(r, name):
        if name not in r.index or pd.isna(r[name]):
            return 0.0
        return float(pd.to_numeric(r[name], errors="coerce")) / UNIT

    def bsc(df, name):
        if name not in df.columns:
            return [0.0] * len(df)
        return (pd.to_numeric(df[name], errors="coerce").fillna(0) / UNIT).tolist()

    ta = bsc(bs, "TOTAL_ASSETS"); tl = bsc(bs, "TOTAL_LIABILITIES")
    cash = bsc(bs, "MONETARYFUNDS"); fin = bsc(bs, "TRADE_FINASSET_NOTFVTPL")
    debt = [sum(x) for x in zip(bsc(bs, "SHORT_LOAN"), bsc(bs, "LONG_LOAN"), bsc(bs, "BOND_PAYABLE"),
                                bsc(bs, "SHORT_BOND_PAYABLE"), bsc(bs, "LEASE_LIAB"), bsc(bs, "NONCURRENT_LIAB_1YEAR"))]
    lev_years = [d.year for d in bs["REPORT_DATE"]]
    keep = [i for i, y in enumerate(lev_years) if y >= 2018]
    lev_labels = [str(lev_years[i]) for i in keep]
    lev_ratio = [round(tl[i] / ta[i] * 100, 1) for i in keep if ta[i] > 0]
    net_cash = [round((cash[i] + fin[i] - debt[i]) / 100, 0) for i in keep]

    # DPS/支付率
    dv = div.copy()
    dv["报告期"] = pd.to_datetime(dv["报告期"])
    dv["DPS"] = pd.to_numeric(dv["现金分红-现金分红比例"], errors="coerce") / 10.0
    dv["财年"] = dv["报告期"].dt.year
    dps_fy = dv[dv["DPS"] > 0].groupby("财年")["DPS"].sum()
    eps_by_year = {int(pd.to_datetime(r["REPORT_DATE"]).year): float(pd.to_numeric(r["BASIC_EPS"], errors="coerce")) for _, r in pnl.iterrows()}
    dps_labels = [str(y) for y in [2021, 2022, 2023, 2024, 2025] if y in dps_fy.index]
    dps_vals = [round(float(dps_fy[int(y)]), 4) for y in dps_labels]
    payout = [round(dps_fy[int(y)] / eps_by_year[int(y)] * 100, 1) for y in dps_labels if eps_by_year.get(int(y))]

    # 估值带：每日 PE(TTM)/PB（不复权价 vs 年度净利/BPS）
    eps_ttm = {2022: 5.79, 2023: 6.10, 2024: 6.39, 2025: 6.35}  # 归母净利/股本，手算锚（2022:1255/216.87... 用脚本重算）
    eps_ttm = {}
    ni_by_year = {int(pd.to_datetime(r["REPORT_DATE"]).year): float(pd.to_numeric(r["PARENT_NETPROFIT"], errors="coerce")) / 1e8 for _, r in pnl.iterrows()}
    for y, n in ni_by_year.items():
        if y >= 2022:
            eps_ttm[y] = round(n * 1e8 / (shares * 1e6), 3)
    bps_by_year = {}
    for _, r in bs.iterrows():
        y = int(pd.to_datetime(r["REPORT_DATE"]).year)
        if y >= 2022:
            eq = float(pd.to_numeric(r["TOTAL_PARENT_EQUITY"], errors="coerce")) / 1e8
            bps_by_year[y] = round(eq * 1e8 / (shares * 1e6), 3)
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values("date")
    daily["year"] = daily["date"].dt.year
    pe_rows, pb_rows = [], []
    for y in [2022, 2023, 2024, 2025]:
        sub = daily[daily["year"] == y]
        if sub.empty or y not in eps_ttm:
            continue
        pes = (sub["close"] / eps_ttm[y]).tolist()
        pbs = (sub["close"] / bps_by_year[y]).tolist()
        pe_rows.append({"y": y, "high": round(max(pes), 1), "low": round(min(pes), 1), "mean": round(float(np.mean(pes)), 1)})
        pb_rows.append({"y": y, "high": round(max(pbs), 2), "low": round(min(pbs), 2), "mean": round(float(np.mean(pbs)), 2)})
    cur_close = float(daily["close"].iloc[-1])
    pe_cur = round(cur_close * shares / 131794.0, 1)  # TTM 口径（2026H1+2025FY-2025H1 归母净利 1,317.94 亿）
    pb_cur = round(cur_close / bps_by_year[2025], 2) if 2025 in bps_by_year else None
    pe_band = {"标题": "图13 PE_TTM 估值带（A股，年度口径）", "labels": [str(r["y"]) for r in pe_rows] + ["当前"],
               "pe_ttm": [r["mean"] for r in pe_rows] + [pe_cur],
               # 当前点没有完整的年度 TTM 区间，使用单点而非复制全历史边界。
               "pe_high": [r["high"] for r in pe_rows] + [pe_cur],
               "pe_low": [r["low"] for r in pe_rows] + [pe_cur],
               "pe_mean": [r["mean"] for r in pe_rows] + [pe_cur]}
    pb_band = {"标题": "图14 PB 估值带（A股，年度口径）", "labels": [str(r["y"]) for r in pb_rows] + ["当前"],
               "pb": [r["mean"] for r in pb_rows] + [pb_cur],
               "pb_high": [r["high"] for r in pb_rows] + [pb_cur],
               "pb_low": [r["low"] for r in pb_rows] + [pb_cur]}

    # 图06 标的身份必须唯一且显式；中国移动 A/H 两个证券行中仅 A 股目标行标记为标的。
    peers = [dict(row, **{"标的": row.get("公司") == "中国移动(A)"}) for row in [
            {"公司": "中国移动(A)", "PE": 16.1, "PB": 1.52, "ROE": 9.9, "营收增速": -1.1, "净利增速": -6.3},
            {"公司": "中国移动(H)", "PE": 11.7, "PB": 1.08, "ROE": 9.9, "营收增速": -1.1, "净利增速": -6.3},
            {"公司": "中国电信(A)", "PE": 18.1, "PB": 1.30, "ROE": 7.5, "营收增速": -2.3, "净利增速": -17.1},
            {"公司": "中国联通(A)", "PE": 15.6, "PB": 1.00, "ROE": 5.0, "营收增速": -0.5, "净利增速": -18.0},
            {"公司": "Verizon", "PE": 10.8, "PB": 1.90, "ROE": 13.2, "营收增速": 2.5, "净利增速": -1.7},
            {"公司": "AT&T", "PE": 7.7, "PB": 1.40, "ROE": 12.0, "营收增速": 2.8, "净利增速": 15.0},
            {"公司": "T-Mobile", "PE": 20.3, "PB": 3.68, "ROE": 18.2, "营收增速": 11.3, "净利增速": 20.0},
            {"公司": "NTT", "PE": 12.1, "PB": 1.32, "ROE": 10.4, "营收增速": 5.1, "净利增速": 8.0},
            {"公司": "KDDI", "PE": 14.8, "PB": 2.04, "ROE": 14.0, "营收增速": 5.6, "净利增速": 5.0},
        ]]
    ops = {
        "target": {"公司": "中国移动(A)", "代码": "600941"},
        "segment": {
            "标题": "图03 分部营收构成（主营业务三大主业，亿元）",
            "labels": ["2024", "2025", "2026H1"],
            "series": [
                {"name": "通信服务", "values": [7220, 7149, 3504]},
                {"name": "算力服务", "values": [808, 898, 529]},
                {"name": "智能服务", "values": [862, 908, 493]},
                {"name": "其他业务", "values": [1513, 1547, 854]},
            ],
            "增速": {"合计增速": [1.7, 0.9, -1.1]},
        },
        "profitability": {
            "标题": "图04 盈利能力趋势（毛利率口径用 EBITDA率 替代）",
            "labels": ["2021", "2022", "2023", "2024", "2025", "2026H1"],
            "毛利率": [33.7, 33.5, 32.9, 32.9, 32.3, 32.3],  # EBITDA率（占营运收入）
            "净利率": [13.7, 13.4, 13.1, 13.3, 13.1, 14.7],
            "ROE": [10.2, 10.2, 10.2, 10.4, 9.9, 5.2],
        },
        "cashflow": {
            "标题": "图05 现金流结构（公司披露口径，亿元）",
            "labels": labels_cf,
            "OCF": ocf_full,
            "D_A": [1930, 2001, 2071, 1911, 1900, 954],
            "Capex": capex_company,
            "FCF": fcf_full,
        },
        "peers": peers,
        "targets": {
            "labels": ["当前价", "悲观PE", "基准PE", "乐观PE", "DCF基准", "龟龟买入价", "龟龟门槛价"],
            "values": [97.71, 84, 94, 103, 119, 98.64, 96.79],
            "注": "A股 12M 目标价区间 84-103（2026E EPS 6.09×PE 13.8-16.9x）；DCF 基准 119 元（WACC 5.5%/g 1.0%，2026-08-15 重算）；龟龟口径 98.64/96.79 元（R_eff=II 对应价，脚本输出）",
        },
        "penetration": {
            "labels": ["A股R*(主)", "A股GG(校验)", "H股R*(主)", "H股GG(校验)"],
            "gg": [3.73, 4.17, 5.14, 5.74],
            "ii": 3.70,
            "注": "A股门槛 II=3.70%（中国10Y 1.6964%+2pct）；H股门槛 II=6.50%（香港10Y 3.5%+3pct，另表披露）；k=0.8/M=75%/TTM口径",
        },
        "sensitivity": {
            "xlabel": "收入情景（×基准）", "ylabel": "GG（%）",
            "x": [1.0, 0.9, 0.8, 0.7],
            "系列": [{"name": "GG(A股, λ=0.48)", "y": [4.17, 2.40, 0.62, -1.15]}],
            "门槛": 3.70,
            "标题": "图11 收入下滑敏感性（A股，现金口径 GG）",
        },
        "forecast": {
            "标题": "图12 盈利预测：历史与三情景（归母净利，亿元）",
            "labels_hist": ["2021", "2022", "2023", "2024", "2025"],
            "np_hist": [1159, 1255, 1318, 1384, 1371],
            "labels_fcast": ["2026E", "2027E", "2028E"],
            "悲观": [1280, 1300, 1320], "基准": [1320, 1350, 1390], "乐观": [1350, 1410, 1480],
        },
        "pe_band": pe_band,
        "pb_band": pb_band,
        "leverage": {
            "标题": "图15 杠杆与负债结构（A股）",
            "labels": lev_labels,
            "资产负债率": lev_ratio,
            "有息负债率": [round(debt[i] / ta[i] * 100, 1) for i in keep if ta[i] > 0],
            "净现金": net_cash,
        },
        "dps": {"labels": dps_labels, "dps": dps_vals, "支付率": payout,
                "注": "DPS 为财年全年（中期+末期）；支付率=DPS/EPS（法1），2021 为 A股上市前口径"},
    }
    out = root / "input"
    out.mkdir(exist_ok=True)
    (out / "运营补充数据.json").write_text(json.dumps(ops, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] {out / '运营补充数据.json'}")
    print("PE带:", pe_band)
    print("PB带:", pb_band)
    print("杠杆:", lev_labels, lev_ratio, net_cash)
    print("DPS:", dps_labels, dps_vals, payout)

if __name__ == "__main__":
    main()
