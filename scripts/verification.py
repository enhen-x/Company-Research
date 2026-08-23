#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复验助手（通用）：刷新数据 → 计算实际值 → 与《估值模型.json》基线预测对比

用法（复验时运行，需联网；在项目根目录执行）：
    python scripts/verification.py [--code 002468]
项目目录名需为 {市场}.{代码} {公司名} 格式，自动识别代码；输出控制台对比表 + data/验证快照.json。

行业成本—价格数据（data/行业成本价格.csv）无稳定免费接口，复验时按
references/framework.md §B2.2 手工刷新月度观测点（双源交叉验证），
重跑 fetch_industry_cost_price.py 审计后更新图16 与跟踪台账。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import akshare as ak
import numpy as np
import pandas as pd

ROOT = Path.cwd()
DATA = ROOT / "data"
REPORTS = ROOT / "reports"


def col(df, *keys):
    for c in df.columns:
        if all(k.upper() in c.upper() for k in keys):
            return c
    return None


def fetch(fname: str, fn, retries: int = 2) -> pd.DataFrame | None:
    for i in range(1, retries + 1):
        try:
            df = fn()
            if df is not None and not df.empty:
                tmp = (DATA / fname).with_suffix(".tmp")
                df.to_csv(tmp, index=False, encoding="utf-8-sig")
                tmp.replace(DATA / fname)
                print(f"[刷新] {fname}: {len(df)} 行")
                return df
        except Exception as exc:
            print(f"[刷新] {fname} 第{i}次失败: {exc}")
    print(f"[刷新] {fname} 失败，沿用本地数据")
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", help="6 位股票代码（默认从项目目录名识别）")
    args = parser.parse_args()

    m = re.search(r"([A-Z]{2})\.(\d{6})", ROOT.name) if ROOT.name else None
    if args.code:
        code = args.code
        market = "SH" if code.startswith(("6", "9")) else ("BJ" if code.startswith(("4", "8", "92")) else "SZ")
    elif m:
        market, code = m.group(1), m.group(2)
    else:
        print("❌ 无法识别股票代码，请用 --code 指定")
        return

    print("=" * 66)
    print(f"{ROOT.name} 复验助手：数据刷新 + 预测对比（基线见 reports/估值模型.json）")
    print("=" * 66)

    em_symbol = f"{market}{code}"
    fetch("利润表_按报告期.csv",
          lambda: ak.stock_profit_sheet_by_report_em(symbol=em_symbol))
    fetch("资产负债表_按报告期.csv",
          lambda: ak.stock_balance_sheet_by_report_em(symbol=em_symbol))
    fetch("主要财务指标_按报告期.csv",
          lambda: ak.stock_financial_analysis_indicator_em(
              symbol=f"{code}.{market}", indicator="按报告期"))
    # 日线刷新：优先腾讯源（与 research_pipeline/fetch_supplement/图表同源，避免新浪/腾讯行数差异覆盖不一致）；
    # 刷新前先备份现有 CSV（保留原源数据可回溯）。
    daily_src = Path(DATA / "日线股价.csv")
    if daily_src.exists():
        bak = daily_src.with_suffix(".bak_" + pd.Timestamp.now().strftime("%Y%m%d_%H%M"))
        daily_src.replace(bak)
        print(f"[备份] 日线股价.csv -> {bak.name}")
    daily = None
    for src_name, fn in [
        ("腾讯", lambda: ak.stock_zh_a_hist_tx(
            symbol=f"{market.lower()}{code}", start_date="20000101",
            end_date="20991231", adjust="")),
        ("新浪", lambda: ak.stock_zh_a_daily(symbol=f"{market.lower()}{code}")),
    ]:
        try:
            daily = fn()
            if daily is not None and not daily.empty:
                daily.to_csv(daily_src, index=False, encoding="utf-8-sig")
                print(f"[刷新] 日线股价.csv（{src_name}源）: {len(daily)} 行")
                break
        except Exception as exc:
            print(f"[刷新] 日线（{src_name}源）失败: {exc}")
    if daily is None:
        print("[刷新] 日线两源均失败，沿用本地备份")

    inc = pd.read_csv(DATA / "利润表_按报告期.csv", dtype=str)
    bs = pd.read_csv(DATA / "资产负债表_按报告期.csv", dtype=str)
    ind = pd.read_csv(DATA / "主要财务指标_按报告期.csv", dtype=str)
    px = pd.read_csv(DATA / "日线股价.csv", dtype=str)

    dc_i = col(inc, "REPORT", "DATE")
    inc[dc_i] = pd.to_datetime(inc[dc_i], errors="coerce")
    inc = inc.dropna(subset=[dc_i]).sort_values(dc_i)
    ni_col = "PARENT_NETPROFIT"
    inc[ni_col] = pd.to_numeric(inc[ni_col], errors="coerce")
    latest_q = inc.iloc[-1]
    ann_ni = {int(r[dc_i].year): r[ni_col] for _, r in inc[inc[dc_i].dt.month == 12].iterrows()}

    d = latest_q[dc_i]
    cum = latest_q[ni_col]
    if d.month == 12:
        ttm_ni = cum
    else:
        prev_ann = ann_ni.get(d.year - 1, np.nan)
        prev_same = inc[(inc[dc_i].dt.year == d.year - 1) & (inc[dc_i].dt.month == d.month)]
        prev_same_v = prev_same.iloc[0][ni_col] if not prev_same.empty else np.nan
        ttm_ni = cum + prev_ann - prev_same_v if np.isfinite(prev_ann) and np.isfinite(prev_same_v) else np.nan

    eq_c = col(bs, "TOTAL_PARENT_EQUITY")
    bps_c = col(ind, "BPS")
    dc_b = col(bs, "REPORT", "DATE")
    dc_n = col(ind, "REPORT", "DATE")
    bs[dc_b] = pd.to_datetime(bs[dc_b], errors="coerce")
    ind[dc_n] = pd.to_datetime(ind[dc_n], errors="coerce")
    bs[eq_c] = pd.to_numeric(bs[eq_c], errors="coerce")
    ind[bps_c] = pd.to_numeric(ind[bps_c], errors="coerce")
    eq_now = bs.loc[bs[dc_b] == d, eq_c]
    bps_now = ind.loc[ind[dc_n] == d, bps_c]
    shares = float(eq_now.iloc[0]) / float(bps_now.iloc[0]) if not eq_now.empty and not bps_now.empty else np.nan
    # 2026-08-23 中远海控批次校准：总股本优先取 公司概况.csv（腾讯实时，含回购注销），
    # 净资产/BPS 推算值为最新报告期口径，二者偏差>2% 时告警
    prof_f = DATA / "公司概况.csv"
    if prof_f.exists():
        try:
            pdf = pd.read_csv(prof_f, encoding="utf-8-sig", dtype=str)
            pvals = dict(zip(pdf.iloc[:, 0], pdf.iloc[:, 1]))
            for k, v in pvals.items():
                if "总股本" in str(k):
                    p_shares = float(v) / 1e6
                    if np.isfinite(shares) and abs(p_shares - shares) / shares > 0.02:
                        print(f"[WARN] 股本口径偏差：公司概况 {p_shares:.2f} 百万股 vs 净资产/BPS 推算 {shares:.2f} 百万股（采用公司概况）")
                    shares = p_shares
                    break
        except Exception as exc:
            print(f"[WARN] 读取公司概况失败: {exc}")

    px_c = px.columns[0]
    close_c = [c for c in px.columns if "close" in c.lower() or "收盘" in c][0]
    px[px_c] = pd.to_datetime(px[px_c], errors="coerce")
    px[close_c] = pd.to_numeric(px[close_c], errors="coerce")
    px = px.dropna(subset=[px_c, close_c]).sort_values(px_c)
    price = float(px.iloc[-1][close_c])
    price_date = px.iloc[-1][px_c]

    eps_ttm = ttm_ni / shares if np.isfinite(ttm_ni) and shares else np.nan
    pe_ttm = price / eps_ttm if eps_ttm and eps_ttm > 0 else np.nan
    pb = price / bps_now.iloc[0] if not bps_now.empty and bps_now.iloc[0] > 0 else np.nan
    mkt_cap = price * shares / 1e8 if shares else np.nan

    model_path = REPORTS / "估值模型.json"
    model = json.loads(model_path.read_text(encoding="utf-8")) if model_path.exists() else {}
    base_ni = model.get("scenarios", {}).get("基准", {})
    target = model.get("target_price")

    print("\n实际值 vs 基线：")
    rows = [
        ("最新报告期", str(latest_q[dc_i].date()), ""),
        ("最新累计归母净利(亿)", round(float(cum) / 1e8, 2),
         f"基准全年 {base_ni.get('2026', '?')} 亿" if base_ni else ""),
        ("TTM 归母净利(亿)", round(ttm_ni / 1e8, 2) if np.isfinite(ttm_ni) else None, ""),
        ("总股本(亿股)", round(shares / 1e8, 2) if shares else None, ""),
        ("最新收盘(元)", round(price, 2), str(price_date.date())),
        ("PE_TTM", round(pe_ttm, 1) if np.isfinite(pe_ttm) else None, ""),
        ("PB", round(pb, 2) if np.isfinite(pb) else None, ""),
        ("总市值(亿)", round(mkt_cap, 1) if np.isfinite(mkt_cap) else None, ""),
        ("目标价", target, ""),
    ]
    for name, actual, note in rows:
        print(f"  {name}: {actual}  ｜ {note}")

    if np.isfinite(cum) and base_ni:
        y = max((k for k in base_ni if str(k).isdigit()), key=lambda s: int(s))
        progress = float(cum) / 1e8 / base_ni[y] * 100
        print(f"\n{y}E 完成进度：{float(cum)/1e8:.2f} 亿 / {base_ni[y]} 亿 = {progress:.0f}%")

    snap = {
        "generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
        "symbol": f"{market}.{code}", "latest_report_date": str(latest_q[dc_i].date()),
        "latest_cumulative_ni_yi": round(float(cum) / 1e8, 2),
        "ttm_ni_yi": round(ttm_ni / 1e8, 2) if np.isfinite(ttm_ni) else None,
        "shares_yi": round(shares / 1e8, 2) if shares else None,
        "price": round(price, 2), "price_date": str(price_date.date()),
        "pe_ttm": round(pe_ttm, 1) if np.isfinite(pe_ttm) else None,
        "pb": round(pb, 2) if np.isfinite(pb) else None,
        "market_cap_yi": round(mkt_cap, 1) if np.isfinite(mkt_cap) else None,
        "baseline": model,
    }
    (DATA / "验证快照.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n[完成] 快照已保存: data/验证快照.json")
    print("下一步：将数字填入 reports/跟踪验证台账.md，偏差归因并更新 skill 迭代日志。")


if __name__ == "__main__":
    main()
