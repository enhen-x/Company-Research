#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""财务摘要与股价位置提取模板：五年趋势 + 分红 + 股价分位 -> reports/财务摘要.csv。

数据依赖（research_pipeline 或 fetch_supplement 产出，均在 --dir/data/）：
    利润表_按报告期.csv / 资产负债表_按报告期.csv / 主要财务指标_按报告期.csv /
    分红送配记录.csv / 日线股价.csv / 日线股价_前复权.csv
字段名以东财接口为准（PARENT_NETPROFIT / TOTAL_PARENT_EQUITY / BPS / ROEJQ 等），
不同接口版本字段名变化时自动尝试常见别名。

用法：
    python extract_financials.py --dir "G:\\理财\\个股分析\\SH.601319 中国人保" --code 601319 --name 中国人保

输出：
    控制台摘要 + reports/财务摘要.csv（利润/资产/指标/分红/股价分位各一区块）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


def p(msg: str) -> None:
    print(msg, flush=True)


def num(v) -> float | None:
    try:
        if v is None or str(v).strip() in ("", "nan", "None"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def load(data_dir: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(data_dir / f"{name}.csv", encoding="utf-8", dtype=str)


def first_num(row: pd.Series, cols: list[str]) -> float | None:
    for c in cols:
        v = row.get(c)
        n = num(v)
        if n is not None:
            return n
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="财务摘要与股价位置提取模板")
    ap.add_argument("--dir", required=True, help="项目目录（含 data/ 与 reports/）")
    ap.add_argument("--code", required=True, help="标的代码")
    ap.add_argument("--name", default="", help="公司名称（可选）")
    ap.add_argument("--years", default="5", help="提取最近 N 个年报（默认 5）")
    args = ap.parse_args()

    proj = Path(args.dir)
    data_dir = proj / "data"
    (proj / "reports").mkdir(parents=True, exist_ok=True)
    n_years = int(args.years)

    # 报告期筛选：取各年 12-31 的最后 N 个
    pl = load(data_dir, "利润表_按报告期")
    pl["REPORT_DATE"] = pd.to_datetime(pl["REPORT_DATE"])
    pl_y = pl[pl["REPORT_DATE"].dt.month == 12].sort_values("REPORT_DATE").tail(n_years)

    bs = load(data_dir, "资产负债表_按报告期")
    bs["REPORT_DATE"] = pd.to_datetime(bs["REPORT_DATE"])
    bs_y = bs[bs["REPORT_DATE"].dt.month == 12].sort_values("REPORT_DATE").tail(n_years)

    fi = load(data_dir, "主要财务指标_按报告期")
    fi["REPORT_DATE"] = pd.to_datetime(fi["REPORT_DATE"])
    fi_y = fi[fi["REPORT_DATE"].dt.month == 12].sort_values("REPORT_DATE").tail(n_years)

    p(f"=== {args.name or args.code} 财务摘要（最近 {n_years} 个年报）===")

    # 1) 利润表
    rows = []
    for _, r in pl_y.iterrows():
        rows.append({
            "报告期": r["REPORT_DATE"].strftime("%Y-%m-%d"),
            "营业总收入(亿)": round((num(r.get("OPERATE_INCOME")) or 0) / 1e8, 2),
            "归母净利(亿)": round((num(r.get("PARENT_NETPROFIT")) or 0) / 1e8, 2),
            "扣非归母(亿)": round((num(r.get("DEDUCT_PARENT_NETPROFIT")) or 0) / 1e8, 2),
            "投资收益(亿)": round((num(r.get("INVEST_INCOME")) or 0) / 1e8, 2),
            "公允价值变动(亿)": round((num(r.get("FAIRVALUE_CHANGE")) or 0) / 1e8, 2),
            "归母净利YoY%": num(r.get("PARENT_NETPROFIT_YOY")),
        })
    df_pl = pd.DataFrame(rows)
    p("\n--- 利润表（亿元）---")
    p(df_pl.to_string(index=False))

    # 2) 资产负债表（归母净资产）
    rows = []
    for _, r in bs_y.iterrows():
        rows.append({
            "报告期": r["REPORT_DATE"].strftime("%Y-%m-%d"),
            "总资产(亿)": round((num(r.get("TOTAL_ASSETS")) or 0) / 1e8, 2),
            "总负债(亿)": round((num(r.get("TOTAL_LIABILITIES")) or 0) / 1e8, 2),
            "归母净资产(亿)": round((first_num(r, ["TOTAL_PARENT_EQUITY", "PARENT_EQUITY",
                                                   "PARENT_EQUITY_BALANCE"]) or 0) / 1e8, 2),
            "少数股东权益(亿)": round((num(r.get("MINORITY_EQUITY")) or 0) / 1e8, 2),
        })
    df_bs = pd.DataFrame(rows)
    p("\n--- 资产负债表（亿元）---")
    p(df_bs.to_string(index=False))

    # 3) 财务指标
    rows = []
    for _, r in fi_y.iterrows():
        rows.append({
            "报告期": r["REPORT_DATE"].strftime("%Y-%m-%d"),
            "EPS": num(r.get("BASIC_EPS")),
            "BPS": num(r.get("BPS")),
            "ROE加权%": num(r.get("ROEJQ")),
            "投资收益率ROI%": num(r.get("TOTAL_ROI")),
            "净投资收益率%": num(r.get("NET_ROI")),
        })
    df_fi = pd.DataFrame(rows)
    p("\n--- 财务指标 ---")
    p(df_fi.to_string(index=False))

    # 4) 分红（最近 12 条）
    div = load(data_dir, "分红送配记录")
    p("\n--- 分红送配记录（最近 12 条）---")
    p(div.tail(12).to_string(index=False))

    # 5) 股价分位（前复权 + 不复权）
    out = {"股价分位": {}}
    for fname, key in [("日线股价_前复权.csv", "前复权"), ("日线股价.csv", "不复权")]:
        f = data_dir / fname
        if not f.exists():
            p(f"\n[WARN] 缺少 {fname}，跳过分位计算")
            continue
        df = pd.read_csv(f, encoding="utf-8")
        df["date"] = pd.to_datetime(df["date"])
        cur = float(df.iloc[-1]["close"])
        d = {
            "最新收盘": round(cur, 3),
            "日期": str(df.iloc[-1]["date"].date()),
            "区间最低": round(float(df["close"].min()), 3),
            "最低日期": str(df.loc[df["close"].idxmin(), "date"].date()),
            "区间最高": round(float(df["close"].max()), 3),
            "最高日期": str(df.loc[df["close"].idxmax(), "date"].date()),
            "当前分位%": round((df["close"] < cur).mean() * 100, 1),
        }
        for y in (3, 5):
            sub = df[df["date"] >= df["date"].max() - pd.DateOffset(years=y)]
            d[f"近{y}年分位%"] = round((sub["close"] < cur).mean() * 100, 1)
            d[f"近{y}年最低"] = round(float(sub["close"].min()), 3)
            d[f"近{y}年最高"] = round(float(sub["close"].max()), 3)
        out["股价分位"][key] = d
        p(f"\n--- 股价分位（{key}）---")
        p(d)

    # 汇总写出
    blocks = {"利润表": df_pl, "资产负债表": df_bs, "财务指标": df_fi}
    with open(proj / "reports" / "财务摘要.csv", "w", encoding="utf-8-sig") as fh:
        for sec, df in blocks.items():
            fh.write(f"\n### {sec}\n")
            df.to_csv(fh, index=False)
    p(f"\n[DONE] 摘要已写入 reports/财务摘要.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
