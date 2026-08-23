#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中国移动数据摘要：H1 2026 中报关键数字 + 五年财务序列 + TTM（B4 分析输入）
用法: python summary_data.py --dir "项目目录"
输出: data/关键指标计算.json（所有计算数字，报告数字以此为唯一真值）
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

UNIT = 1e6  # 元 -> 百万元

def annual(df):
    df = df.copy()
    df["REPORT_DATE"] = pd.to_datetime(df["REPORT_DATE"])
    df = df[df["REPORT_DATE"].dt.month == 12].sort_values("REPORT_DATE")
    return df[~df["REPORT_DATE"].duplicated(keep="last")]

def half(df):
    df = df.copy()
    df["REPORT_DATE"] = pd.to_datetime(df["REPORT_DATE"])
    return df[df["REPORT_DATE"].dt.month.isin([6, 12])].sort_values("REPORT_DATE").drop_duplicates("REPORT_DATE", keep="last")

def v(df, col):
    return pd.to_numeric(df[col], errors="coerce").fillna(0) / UNIT

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    args = ap.parse_args()
    data = Path(args.dir) / "data"
    pnl_all = pd.read_csv(data / "利润表_按报告期.csv", encoding="utf-8-sig")
    cf_all = pd.read_csv(data / "现金流量表_按报告期.csv", encoding="utf-8-sig")
    bs_all = pd.read_csv(data / "资产负债表_按报告期.csv", encoding="utf-8-sig")
    ind = pd.read_csv(data / "主要财务指标_按报告期.csv", encoding="utf-8-sig")
    div = pd.read_csv(data / "分红送配记录.csv", encoding="utf-8-sig")
    daily_a = pd.read_csv(data / "日线股价.csv", encoding="utf-8-sig")
    daily_h = pd.read_csv(data / "HK0941日线.csv", encoding="utf-8-sig")

    out = {}
    # 最新报告期
    pnl = half(pnl_all)
    cfh = half(cf_all)
    bsh = half(bs_all)
    out["最新报告期"] = str(pnl["REPORT_DATE"].iloc[-1].date())
    out["报告期列表"] = [str(d.date()) for d in pnl["REPORT_DATE"]]

    # H1 2026 vs H1 2025 vs FY2025
    def row(df, date):
        r = df[df["REPORT_DATE"] == pd.Timestamp(date)]
        return r.iloc[0] if len(r) else None

    for label, d in [("2025FY", "2025-12-31"), ("2025H1", "2025-06-30"), ("2026H1", "2026-06-30")]:
        ri, rc, rb = row(pnl, d), row(cfh, d), row(bsh, d)
        if ri is None:
            continue
        o = {"营收(百万)": float(v(pd.DataFrame([ri]), "OPERATE_INCOME").iloc[0]),
             "归母净利(百万)": float(v(pd.DataFrame([ri]), "PARENT_NETPROFIT").iloc[0]),
             "扣非归母(百万)": float(v(pd.DataFrame([ri]), "DEDUCT_PARENT_NETPROFIT").iloc[0]) if "DEDUCT_PARENT_NETPROFIT" in ri else None}
        if rc is not None:
            o["OCF(百万)"] = float(v(pd.DataFrame([rc]), "NETCASH_OPERATE").iloc[0])
            o["capex(百万)"] = float(v(pd.DataFrame([rc]), "CONSTRUCT_LONG_ASSET").iloc[0])
            o["D&A(百万)"] = float(v(pd.DataFrame([rc]), "FA_IR_DEPR").iloc[0] + v(pd.DataFrame([rc]), "IA_AMORTIZE").iloc[0] + v(pd.DataFrame([rc]), "LPE_AMORTIZE").iloc[0] + v(pd.DataFrame([rc]), "USERIGHT_ASSET_AMORTIZE").iloc[0])
        out[label] = o

    # TTM (2026H1 + 2025FY - 2025H1)
    ttm_rev = out["2026H1"]["营收(百万)"] + out["2025FY"]["营收(百万)"] - out["2025H1"]["营收(百万)"]
    ttm_ni = out["2026H1"]["归母净利(百万)"] + out["2025FY"]["归母净利(百万)"] - out["2025H1"]["归母净利(百万)"]
    ttm_ocf = out["2026H1"]["OCF(百万)"] + out["2025FY"]["OCF(百万)"] - out["2025H1"]["OCF(百万)"]
    ttm_d = out["2026H1"]["D&A(百万)"] + out["2025FY"]["D&A(百万)"] - out["2025H1"]["D&A(百万)"]
    ttm_capex = out["2026H1"]["capex(百万)"] + out["2025FY"]["capex(百万)"] - out["2025H1"]["capex(百万)"]
    out["TTM(2026H1口径)"] = {"营收": round(ttm_rev, 1), "归母净利": round(ttm_ni, 1), "OCF": round(ttm_ocf, 1), "D&A": round(ttm_d, 1), "capex": round(ttm_capex, 1)}

    # 五年年报序列（由新到旧）
    pa, ca, ba = annual(pnl_all), annual(cf_all), annual(bs_all)
    pa = pa.tail(6); ca = ca.tail(6); ba = ba.tail(6)
    yrs = [d.year for d in pa["REPORT_DATE"]]
    seq = {"年份": yrs,
           "营收": [round(x, 1) for x in v(pa, "OPERATE_INCOME")],
           "归母净利": [round(x, 1) for x in v(pa, "PARENT_NETPROFIT")],
           "扣非归母": [round(x, 1) for x in v(pa, "DEDUCT_PARENT_NETPROFIT")],
           "OCF": [round(x, 1) for x in v(ca, "NETCASH_OPERATE")],
           "capex": [round(x, 1) for x in v(ca, "CONSTRUCT_LONG_ASSET")],
           "D&A": [round(x, 1) for x in (v(ca, "FA_IR_DEPR") + v(ca, "IA_AMORTIZE") + v(ca, "LPE_AMORTIZE") + v(ca, "USERIGHT_ASSET_AMORTIZE"))],
           "货币资金": [round(x, 1) for x in v(ba, "MONETARYFUNDS")],
           "归母权益": [round(x, 1) for x in v(ba, "TOTAL_PARENT_EQUITY")],
           "总资产": [round(x, 1) for x in v(ba, "TOTAL_ASSETS")],
           "有息负债": [round(x, 1) for x in (v(ba, "SHORT_LOAN") + v(ba, "LONG_LOAN") + v(ba, "BOND_PAYABLE") + v(ba, "SHORT_BOND_PAYABLE"))],
           }
    seq["FCF(OCF-capex)"] = [round(a - b, 1) for a, b in zip(seq["OCF"], seq["capex"])]
    seq["结余(OCF-capex)"] = seq["FCF(OCF-capex)"]
    out["五年序列(由新到旧)"] = seq

    # 分红
    d = div.copy()
    d["报告期"] = pd.to_datetime(d["报告期"])
    d["DPS"] = pd.to_numeric(d["现金分红-现金分红比例"], errors="coerce") / 10.0
    d["财年"] = d["报告期"].dt.year
    dps = d[d["DPS"] > 0].groupby("财年")["DPS"].sum().sort_index()
    out["DPS按财年(元)"] = {str(k): round(float(v2), 4) for k, v2 in dps.items()}
    out["分红记录明细"] = d[["报告期", "现金分红-现金分红比例", "除权除息日"]].astype(str).to_dict("records")

    # 股价
    da = daily_a.copy(); da["date"] = pd.to_datetime(da["date"])
    out["A股最新收盘"] = float(da["close"].iloc[-1])
    out["A股最新交易日"] = str(da["date"].iloc[-1].date())
    dh = daily_h.copy(); dh["date"] = pd.to_datetime(dh["date"])
    out["H股最新收盘"] = float(dh["close"].iloc[-1])
    out["H股最新交易日"] = str(dh["date"].iloc[-1].date())

    # 财务指标（最新年报 ROE/BPS/EPS）
    ia = annual(ind)
    lr = ia.iloc[-1]
    def gv(r, col):
        return float(pd.to_numeric(r.get(col), errors="coerce")) if pd.notna(r.get(col)) else None
    out["财务指标最新年报"] = {"年份": int(pd.to_datetime(lr["REPORT_DATE"]).year), "ROE加权": gv(lr, "ROEJQ"), "BPS": gv(lr, "BPS"), "EPS": gv(lr, "EPSJB")}

    (data / "关键指标计算.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2)[:6000])

if __name__ == "__main__":
    main()
