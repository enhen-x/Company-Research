#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Capex 与分红跃迁引擎 (Capex & Dividend Transition Engine)
版本：v3.1-skill-integrated

职责：
1. 读取标准调研批次目录（<dir>/data/*.csv 与 <dir>/input/capex_dividend_plan.json）；
2. 从分红送配记录.csv、三大财务报表、前复权日线中刚性锁定历史实际口径（无主观幻想/手算漂移）；
3. 采用同合并扣息口径计算真实分红覆盖能力：(OCF - Capex - 费用化利息) / 合并净利润，与实际分红率对照；
4. 自动输出三张报告级高清 PNG（图19/图20/图21 -> reports/图表/）与结构化 JSON + Markdown 模块：
   - 图19_Capex规划与股价联动.png -> §4.2 现金流与盈利质量
   - 图20_重大在建工程转固时间轴.png -> §4.2 现金流与盈利质量
   - 图21_分红可行性与造血留存.png -> §6.4 估值结论与安全边际
   - reports/capex_dividend_analysis.json
   - reports/Capex与分红跃迁专项.md

用法：
    python scripts/capex_dividend_engine.py --dir . --init-template --company <名称> --code <代码>
    python scripts/capex_dividend_engine.py --dir .
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'PingFang SC', 'Source Han Sans CN', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False


def _pick_col(df: pd.DataFrame, *candidates: str) -> str | None:
    for cand in candidates:
        if cand in df.columns:
            return cand
    upper_map = {str(c).upper(): c for c in df.columns}
    for cand in candidates:
        if cand.upper() in upper_map:
            return upper_map[cand.upper()]
    return None


def _num_series(df: pd.DataFrame, col: str | None, default: float = 0.0) -> pd.Series:
    if col is None or col not in df.columns:
        return pd.Series(default, index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors='coerce').fillna(default)


def _extract_year_dps(sub_div: pd.DataFrame, np_val_yuan: float) -> tuple[float, float, str]:
    """从单年度所有分红送配记录（含中期+末期/特别分红）合计每股股息、实际分红率与最近除权日。"""
    total_dps = 0.0
    total_cash_div = 0.0
    has_div = False
    latest_ex_date = ""

    for _, d_row in sub_div.iterrows():
        sh = pd.to_numeric(d_row.get('总股本', np.nan), errors='coerce')
        dps = np.nan
        desc = str(d_row.get('现金分红-现金分红比例描述', '') or '')
        m = re.search(r'10\s*派\s*([\d\.]+)\s*元', desc)
        if m:
            dps = float(m.group(1)) / 10.0
        else:
            ratio_10 = pd.to_numeric(d_row.get('现金分红-现金分红比例', np.nan), errors='coerce')
            if pd.notnull(ratio_10) and ratio_10 >= 0:
                dps = float(ratio_10) / 10.0

        if pd.notnull(dps) and dps > 0:
            has_div = True
            total_dps += dps
            if pd.notnull(sh) and sh > 0:
                total_cash_div += dps * float(sh)

        ex_date = ''
        for dc in ('除权除息日', '股权登记日', '预案公告日'):
            val = d_row.get(dc, '')
            if pd.notnull(val) and str(val).strip() not in ('', 'nan', 'None'):
                ex_date = str(val).strip()[:10]
                break
        if ex_date and ex_date > latest_ex_date:
            latest_ex_date = ex_date

    if not has_div:
        return np.nan, np.nan, ""

    payout = (total_cash_div / np_val_yuan * 100.0) if (total_cash_div > 0 and np_val_yuan > 0) else np.nan
    return round(total_dps, 4), (round(payout, 2) if pd.notnull(payout) else np.nan), latest_ex_date


def init_template(project_dir: Path, config_path: Path, company: str = "", code: str = "") -> Path:
    """根据已有 data/*.csv 自动生成可编辑的 input/capex_dividend_plan.json 模板。"""
    data_dir = project_dir / "data"
    if not company or not code:
        parent_name = project_dir.parent.name
        m = re.match(r"^(?:SH|SZ|BJ|HK)\.(\d{5,6})\s+(.+)$", parent_name)
        if m:
            code = code or m.group(1)
            company = company or m.group(2)

    latest_price = None
    total_shares_b = None
    for px_name in ("日线股价_前复权.csv", "日线股价.csv"):
        px_p = data_dir / px_name
        if px_p.is_file():
            try:
                px = pd.read_csv(px_p, encoding="utf-8-sig")
                c_col = _pick_col(px, "close", "收盘")
                if c_col and not px.empty:
                    latest_price = round(float(pd.to_numeric(px[c_col], errors="coerce").dropna().iloc[-1]), 2)
                    break
            except Exception:
                pass

    div_p = data_dir / "分红送配记录.csv"
    if div_p.is_file():
        try:
            dv = pd.read_csv(div_p, encoding="utf-8-sig")
            if "总股本" in dv.columns:
                sh = pd.to_numeric(dv["总股本"], errors="coerce").dropna()
                if not sh.empty:
                    total_shares_b = round(float(sh.iloc[-1]) / 1e8, 3)
        except Exception:
            pass

    cf_p = data_dir / "现金流量表_按报告期.csv"
    inc_p = data_dir / "利润表_按报告期.csv"
    last_year = 2025
    last_ocf = last_capex = last_np = last_cnp = last_int = 0.0
    if cf_p.is_file() and inc_p.is_file():
        try:
            cf = pd.read_csv(cf_p, encoding="utf-8-sig")
            inc = pd.read_csv(inc_p, encoding="utf-8-sig")
            cf_ann = cf[cf["REPORT_DATE"].astype(str).str.contains("-12-31")].sort_values("REPORT_DATE")
            inc_ann = inc[inc["REPORT_DATE"].astype(str).str.contains("-12-31")].sort_values("REPORT_DATE")
            if not cf_ann.empty and not inc_ann.empty:
                last_year = int(str(cf_ann.iloc[-1]["REPORT_DATE"])[:4])
                last_ocf = round(float(pd.to_numeric(cf_ann.iloc[-1].get("NETCASH_OPERATE", 0), errors="coerce") or 0) / 1e8, 2)
                last_capex = round(float(pd.to_numeric(cf_ann.iloc[-1].get("CONSTRUCT_LONG_ASSET", 0), errors="coerce") or 0) / 1e8, 2)
                last_np = round(float(pd.to_numeric(inc_ann.iloc[-1].get("PARENT_NETPROFIT", 0), errors="coerce") or 0) / 1e8, 2)
                last_cnp = round(float(pd.to_numeric(inc_ann.iloc[-1].get("NETPROFIT", last_np * 1e8), errors="coerce") or 0) / 1e8, 2)
                int_raw = inc_ann.iloc[-1].get("FE_INTEREST_EXPENSE")
                if pd.isna(int_raw):
                    int_raw = inc_ann.iloc[-1].get("FINANCE_EXPENSE", 0)
                last_int = round(float(pd.to_numeric(int_raw, errors="coerce") or 0) / 1e8, 2)
        except Exception:
            pass

    f_years = [f"{last_year + 1}E", f"{last_year + 2}E", f"{last_year + 3}E"]
    mkt_cap = round((latest_price or 0) * (total_shares_b or 0), 2) if (latest_price and total_shares_b) else None
    template = {
        "enabled": True,
        "stock_code": code or "000000",
        "stock_name": company or "示例公司",
        "industry": "待填细分行业",
        "current_status": {
            "latest_price": latest_price or 0.0,
            "total_shares_billion": total_shares_b or 1.0,
            "current_market_cap_billion": mkt_cap or 0.0,
            "current_pe_ttm": 0.0,
            "current_dividend_yield": 0.0
        },
        "capex_plan": {
            "cycle_phase": "待填（如：Capex 峰值见顶回落拐点期 / 稳态现金牛期）",
            "peak_year": "待核年报在建规划（如：2023 年见顶 / 2026E-2027E 集中投产）",
            "trend_summary": "待结合年报董事会资本开支计划、在建工程附注及业绩会指引补充。",
            "forecast_years": f_years,
            "planned_capex_billion": [last_capex, round(last_capex * 0.9, 2), round(last_capex * 0.8, 2)],
            "projected_ocf_billion": [last_ocf, round(last_ocf * 1.03, 2), round(last_ocf * 1.06, 2)],
            "projected_netprofit_billion": [last_np, round(last_np * 1.05, 2), round(last_np * 1.10, 2)],
            "projected_consolidated_netprofit_billion": [last_cnp, round(last_cnp * 1.05, 2), round(last_cnp * 1.10, 2)],
            "projected_interest_expense_billion": [last_int, round(last_int * 0.95, 2), round(last_int * 0.90, 2)],
            "key_projects": []
        },
        "dividend_commitment": {
            "statutory_floor_payout_ratio": 0.50,
            "announcement_date": "",
            "policy_title": "未来三年股东回报规划（待核年报与公告正文）"
        }
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[INIT] 已生成模板输入：{config_path}（请结合年报/公告核实并补充 capex_plan 与 dividend_commitment 后运行）")
    return config_path


def load_company_data(raw_data_dir: Path, plan_json_path: Path):
    """读取历史财务数据、股价数据与规划输入，确保同合并扣息口径严密准确。"""
    plan = json.loads(plan_json_path.read_text(encoding='utf-8-sig'))

    cf = pd.read_csv(raw_data_dir / '现金流量表_按报告期.csv', encoding='utf-8-sig')
    bs = pd.read_csv(raw_data_dir / '资产负债表_按报告期.csv', encoding='utf-8-sig')
    inc = pd.read_csv(raw_data_dir / '利润表_按报告期.csv', encoding='utf-8-sig')
    div_path = raw_data_dir / '分红送配记录.csv'
    div = pd.read_csv(div_path, encoding='utf-8-sig') if div_path.is_file() else pd.DataFrame()

    # 读取前复权股价数据
    px_path = raw_data_dir / '日线股价_前复权.csv'
    if not px_path.is_file():
        px_path = raw_data_dir / '日线股价.csv'
    px_df = pd.read_csv(px_path, encoding='utf-8-sig')
    d_col = _pick_col(px_df, 'date', '日期', 'trade_date')
    c_col = _pick_col(px_df, 'close', '收盘', '收盘价')
    px_df['date'] = pd.to_datetime(px_df[d_col], errors='coerce')
    px_df['close'] = pd.to_numeric(px_df[c_col], errors='coerce')
    px_df = px_df.dropna(subset=['date', 'close'])
    px_df = px_df[px_df['date'] >= '2020-01-01'].sort_values('date').copy()
    if px_df.empty:
        px_df = pd.read_csv(px_path, encoding='utf-8-sig')
        px_df['date'] = pd.to_datetime(px_df[d_col], errors='coerce')
        px_df['close'] = pd.to_numeric(px_df[c_col], errors='coerce')
        px_df = px_df.dropna(subset=['date', 'close']).sort_values('date').copy()

    # 统一提取年报数据（12-31）
    for frame in (cf, bs, inc):
        frame['year'] = frame['REPORT_DATE'].astype(str).str[:4]
    cf_ann = cf[cf['REPORT_DATE'].astype(str).str.contains('-12-31')].drop_duplicates('year', keep='last').sort_values('REPORT_DATE')
    bs_ann = bs[bs['REPORT_DATE'].astype(str).str.contains('-12-31')].drop_duplicates('year', keep='last').sort_values('REPORT_DATE')
    inc_ann = inc[inc['REPORT_DATE'].astype(str).str.contains('-12-31')].drop_duplicates('year', keep='last').sort_values('REPORT_DATE')

    if not div.empty and '报告期' in div.columns:
        div['year'] = div['报告期'].astype(str).str[:4]
        div_ann = div[div['报告期'].astype(str).str.contains('-12-31|-06-30|-09-30|-03-31', regex=True)].sort_values('报告期')
    else:
        div_ann = pd.DataFrame(columns=['year'])

    # 严格区分：归母净利润用于分红率计算；合并净利润 + 费用化利息支出用于同口径扣息 FCFE 覆盖率
    np_col = _pick_col(inc_ann, 'PARENT_NETPROFIT', '归母净利润', 'NETPROFIT')
    consol_col = _pick_col(inc_ann, 'NETPROFIT', '净利润') or np_col
    inc_cols = ['year', np_col]
    if consol_col and consol_col not in inc_cols:
        inc_cols.append(consol_col)
    for opt in ('FE_INTEREST_EXPENSE', 'FINANCE_EXPENSE'):
        c = _pick_col(inc_ann, opt)
        if c and c not in inc_cols:
            inc_cols.append(c)

    bs_keep = ['year']
    for col in ('CIP', 'FIXED_ASSET', 'TOTAL_LIABILITIES', 'TOTAL_ASSETS', 'MONETARYFUNDS'):
        c = _pick_col(bs_ann, col)
        if c and c not in bs_keep:
            bs_keep.append(c)

    cf_keep = ['year']
    for col in ('NETCASH_OPERATE', 'CONSTRUCT_LONG_ASSET'):
        c = _pick_col(cf_ann, col)
        if c and c not in cf_keep:
            cf_keep.append(c)

    merged = pd.merge(cf_ann[cf_keep], bs_ann[bs_keep], on='year', how='inner')
    merged = pd.merge(merged, inc_ann[inc_cols], on='year', how='inner')

    start_year = str(plan.get('history_start_year', '2020'))
    hist_df = merged[merged['year'] >= start_year].copy().sort_values('year')
    hist_df['is_forecast'] = False

    hist_df['OCF'] = (_num_series(hist_df, _pick_col(hist_df, 'NETCASH_OPERATE')) / 1e8).round(2)
    hist_df['Capex'] = (_num_series(hist_df, _pick_col(hist_df, 'CONSTRUCT_LONG_ASSET')) / 1e8).round(2)
    hist_df['FCF'] = (hist_df['OCF'] - hist_df['Capex']).round(2)

    fe_col = _pick_col(hist_df, 'FE_INTEREST_EXPENSE')
    fin_col = _pick_col(hist_df, 'FINANCE_EXPENSE')
    if fe_col and fin_col:
        int_raw = pd.to_numeric(hist_df[fe_col], errors='coerce').fillna(
            pd.to_numeric(hist_df[fin_col], errors='coerce')
        ).fillna(0.0)
    elif fe_col:
        int_raw = pd.to_numeric(hist_df[fe_col], errors='coerce').fillna(0.0)
    elif fin_col:
        int_raw = pd.to_numeric(hist_df[fin_col], errors='coerce').fillna(0.0)
    else:
        int_raw = pd.Series(0.0, index=hist_df.index)
    # 利息支出取非负值（若财务费用净收益为负值说明利息收入大于利息支出，扣息压力按 0 计避免反向虚增 FCFE）
    int_raw = int_raw.clip(lower=0.0)
    hist_df['InterestExp'] = (int_raw / 1e8).round(2)
    hist_df['FCFE'] = (hist_df['FCF'] - hist_df['InterestExp']).round(2)

    hist_df['CIP'] = (_num_series(hist_df, _pick_col(hist_df, 'CIP')) / 1e8).round(2)
    hist_df['FA'] = (_num_series(hist_df, _pick_col(hist_df, 'FIXED_ASSET')) / 1e8).round(2)
    hist_df['NetProfit'] = (_num_series(hist_df, np_col) / 1e8).round(2)
    hist_df['ConsolNP'] = (_num_series(hist_df, consol_col) / 1e8).round(2)

    hist_df['Capex_OCF_Ratio'] = np.where(hist_df['OCF'] > 0, (hist_df['Capex'] / hist_df['OCF'] * 100).round(1), np.nan)
    hist_df['Retention_Ratio'] = np.where(hist_df['OCF'] > 0, ((1 - hist_df['Capex'] / hist_df['OCF']) * 100).round(1), np.nan)
    hist_df['FCF_NP_Ratio'] = np.where(hist_df['ConsolNP'] > 0, (hist_df['FCF'] / hist_df['ConsolNP']).round(2), np.nan)
    hist_df['FCFE_NP_Ratio'] = np.where(hist_df['ConsolNP'] > 0, (hist_df['FCFE'] / hist_df['ConsolNP']).round(2), np.nan)
    hist_df['CIP_FA_Ratio'] = np.where(hist_df['FA'] > 0, (hist_df['CIP'] / hist_df['FA'] * 100).round(1), np.nan)
    tot_assets = _num_series(hist_df, _pick_col(hist_df, 'TOTAL_ASSETS'))
    tot_liab = _num_series(hist_df, _pick_col(hist_df, 'TOTAL_LIABILITIES'))
    hist_df['Debt_Ratio'] = np.where(tot_assets > 0, (tot_liab / tot_assets * 100).round(1), np.nan)

    # 脚本刚性提取历年真实分红实施数据（含中期+末期汇总）
    dps_list, payout_list, eps_list, div_milestones = [], [], [], []
    total_shares_plan = float(plan.get('current_status', {}).get('total_shares_billion', 1.0) or 1.0)

    for _, r in hist_df.iterrows():
        y = r['year']
        np_val = float(r['NetProfit']) * 1e8
        sub_div = div_ann[div_ann['year'] == y] if not div_ann.empty else pd.DataFrame()
        if not sub_div.empty:
            dps, payout, ex_date = _extract_year_dps(sub_div, np_val)
            sh_series = pd.to_numeric(sub_div.get('总股本', np.nan), errors='coerce').dropna()
            sh = float(sh_series.iloc[-1]) if not sh_series.empty else (total_shares_plan * 1e8)
            eps = (np_val / sh) if sh > 0 else np.nan
            dps_list.append(dps)
            payout_list.append(payout)
            eps_list.append(round(eps, 4) if pd.notnull(eps) else np.nan)
            if pd.notnull(dps) and ex_date:
                po_txt = f" (分红率{payout:.1f}%)" if pd.notnull(payout) else ""
                div_milestones.append({
                    'date': ex_date,
                    'year': y,
                    'dps': dps,
                    'payout': round(payout, 1) if pd.notnull(payout) else None,
                    'desc': f"10派{dps*10:.2f}元",
                    'title': f"{y}分红实施",
                    'detail': f"10派{dps*10:.2f}元{po_txt}"
                })
        else:
            dps_list.append(np.nan)
            payout_list.append(np.nan)
            eps_list.append(np.nan)

    hist_df['DPS'] = dps_list
    hist_df['Payout_Ratio'] = payout_list
    hist_df['EPS'] = eps_list

    # 拼接入未来规划数据
    capex_p = plan['capex_plan']
    forecast_years = capex_p['forecast_years']
    f_capex = capex_p['planned_capex_billion']
    f_ocf = capex_p['projected_ocf_billion']
    f_np = capex_p['projected_netprofit_billion']
    f_consol_np = capex_p.get('projected_consolidated_netprofit_billion', f_np)
    f_int = capex_p.get('projected_interest_expense_billion', [0.0] * len(forecast_years))

    f_rows = []
    for i, y in enumerate(forecast_years):
        c = float(f_capex[i])
        o = float(f_ocf[i])
        np_val = float(f_np[i])
        c_np_val = float(f_consol_np[i])
        int_val = float(f_int[i])
        fcf = round(o - c, 2)
        fcfe = round(fcf - int_val, 2)
        f_rows.append({
            'year': str(y),
            'is_forecast': True,
            'OCF': round(o, 2),
            'Capex': round(c, 2),
            'FCF': fcf,
            'InterestExp': round(int_val, 2),
            'FCFE': fcfe,
            'CIP': np.nan,
            'FA': np.nan,
            'NetProfit': round(np_val, 2),
            'ConsolNP': round(c_np_val, 2),
            'Capex_OCF_Ratio': round(c / o * 100, 1) if o > 0 else np.nan,
            'Retention_Ratio': round((1 - c / o) * 100, 1) if o > 0 else np.nan,
            'FCF_NP_Ratio': round(fcf / c_np_val, 2) if c_np_val > 0 else np.nan,
            'FCFE_NP_Ratio': round(fcfe / c_np_val, 2) if c_np_val > 0 else np.nan,
            'CIP_FA_Ratio': np.nan,
            'Debt_Ratio': np.nan,
            'DPS': np.nan,
            'EPS': round(np_val / total_shares_plan, 4) if total_shares_plan > 0 else np.nan,
            'Payout_Ratio': np.nan
        })
    forecast_df = pd.DataFrame(f_rows)

    cols_keep = [
        'year', 'is_forecast', 'OCF', 'Capex', 'FCF', 'InterestExp', 'FCFE',
        'CIP', 'FA', 'NetProfit', 'ConsolNP', 'Capex_OCF_Ratio', 'Retention_Ratio',
        'FCF_NP_Ratio', 'FCFE_NP_Ratio', 'CIP_FA_Ratio', 'Debt_Ratio', 'DPS', 'EPS', 'Payout_Ratio'
    ]
    combined_df = pd.concat([hist_df[cols_keep], forecast_df[cols_keep]], ignore_index=True)

    return plan, hist_df, combined_df, px_df, div_milestones


def plot_capex_fcf_and_price(plan, combined_df, px_df, div_milestones, output_img_path: Path):
    """生成图19：Capex 全景规划曲线 + 前复权股价与全量分红实施进度上下联动图。"""
    fig, (ax1, ax_px) = plt.subplots(
        2, 1, figsize=(11.5, 9.4), dpi=300,
        gridspec_kw={'height_ratios': [1.3, 0.95], 'hspace': 0.34}
    )

    years = combined_df['year'].tolist()
    x = np.arange(len(years))
    bar_width = 0.42
    is_f = combined_df['is_forecast'].values
    hist_mask = ~is_f
    fore_mask = is_f

    capex_vals = combined_df['Capex'].values
    ocf_vals = combined_df['OCF'].values
    ratio_vals = combined_df['Capex_OCF_Ratio'].values

    ax1.bar(x[hist_mask], capex_vals[hist_mask], width=bar_width, color='#2563EB', alpha=0.88,
            label='资本开支 (Capex 实际)', edgecolor='#1D4ED8', linewidth=1.2)
    if np.any(fore_mask):
        ax1.bar(x[fore_mask], capex_vals[fore_mask], width=bar_width, color='#93C5FD', alpha=0.55,
                hatch='///', label='资本开支 (Capex 规划指引)', edgecolor='#2563EB', linestyle='--', linewidth=1.5)

    ax1.plot(x, ocf_vals, color='#059669', marker='o', markersize=6.5,
             linewidth=2.5, label='经营性净现金流 (OCF 造血)', zorder=5)

    for i in range(len(years)):
        val = capex_vals[i]
        txt_color = '#1E3A8A' if not is_f[i] else '#1D4ED8'
        ax1.annotate(f"{val:.1f}亿", xy=(x[i], val), xytext=(0, 4), textcoords="offset points",
                     ha='center', va='bottom', fontsize=8.8, fontweight='bold', color=txt_color)
        ax1.annotate(f"{ocf_vals[i]:.1f}", xy=(x[i], ocf_vals[i]), xytext=(0, 7), textcoords="offset points",
                     ha='center', va='bottom', fontsize=8.3, color='#065F46', fontweight='semibold')

    ax1.fill_between(x, capex_vals, ocf_vals, where=(ocf_vals >= capex_vals),
                     interpolate=True, color='#10B981', alpha=0.12, label='自由现金流盈余 (FCF > 0)')
    ax1.fill_between(x, capex_vals, ocf_vals, where=(ocf_vals < capex_vals),
                     interpolate=True, color='#EF4444', alpha=0.15, label='现金流失血吞噬 (FCF < 0)')

    max_cf = float(max(np.nanmax(capex_vals), np.nanmax(ocf_vals), 1.0))
    ax1.set_ylabel('现金流与开支 (亿元)', fontsize=10.5, fontweight='bold', color='#1E293B', labelpad=8)
    ax1.set_ylim(min(0.0, float(np.nanmin(ocf_vals)) * 1.15), max_cf * 1.38)
    ax1.set_xticks(x)
    ax1.set_xticklabels(years, fontsize=9.8, fontweight='bold', color='#334155')

    ax2 = ax1.twinx()
    valid_r = ~np.isnan(ratio_vals)
    if np.any(valid_r):
        ax2.plot(x[valid_r], ratio_vals[valid_r], color='#DC2626', linestyle='-.', marker='s', markersize=5.2,
                 linewidth=1.8, label='Capex 占 OCF 比率 (%)', zorder=6)
        for i in range(len(years)):
            r = ratio_vals[i]
            if np.isnan(r):
                continue
            ax2.annotate(f"{r:.1f}%", xy=(x[i], r), xytext=(0, -13 if r > 100 else 6),
                         textcoords="offset points", ha='center', va='bottom' if r <= 100 else 'top',
                         fontsize=8.0, color='#B91C1C', fontweight='bold')
        max_r = float(np.nanmax(ratio_vals))
        ax2.set_ylim(0, max(max_r * 1.45, 120.0))
    else:
        ax2.set_ylim(0, 150.0)
    ax2.set_ylabel('Capex / OCF 强度比率 (%)', fontsize=10.5, fontweight='bold', color='#DC2626', labelpad=8)
    ax2.axhline(100, color='#94A3B8', linestyle=':', linewidth=1.0, alpha=0.8)

    for ax in (ax1, ax2):
        ax.spines['top'].set_visible(False)
    ax1.spines['right'].set_visible(False)
    ax2.spines['left'].set_visible(False)
    ax1.yaxis.grid(True, linestyle='--', color='#F1F5F9', linewidth=0.8, zorder=0)

    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax2.get_legend_handles_labels()
    ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc='upper right', frameon=True, framealpha=0.92,
               facecolor='#FFFFFF', edgecolor='#E2E8F0', fontsize=8.3, ncol=2)
    ax1.set_title("【图A】资本开支规划、造血现金流与 Capex 强度拐点全景",
                  fontsize=11.5, fontweight='bold', color='#0F172A', pad=10)

    # 下图：前复权股价 + 全量分红节点
    if not px_df.empty:
        ax_px.plot(px_df['date'], px_df['close'], color='#4338CA', linewidth=1.8, label='历史收盘价 (前复权)')
        min_p, max_p = float(px_df['close'].min()), float(px_df['close'].max())
        ax_px.fill_between(px_df['date'], min_p * 0.95, px_df['close'], color='#6366F1', alpha=0.08)
        ax_px.set_ylim(min_p * 0.88, max_p * 1.45)

        plan_date_str = str(plan.get('dividend_commitment', {}).get('announcement_date', '') or '').strip()
        floor_raw = plan.get('dividend_commitment', {}).get('statutory_floor_payout_ratio')
        floor_pct = int(round(float(floor_raw) * 100)) if floor_raw else None
        if plan_date_str:
            try:
                p_dt = pd.to_datetime(plan_date_str)
                sub_p = px_df[px_df['date'] <= p_dt]
                cur_p = float(sub_p.iloc[-1]['close']) if not sub_p.empty else (min_p + max_p) / 2
                ax_px.axvline(p_dt, color='#B91C1C', linestyle='-', linewidth=1.8, alpha=0.85, zorder=4)
                txt = f"★ 发布《股东回报规划》\n承诺保底分红 ≥{floor_pct}%" if floor_pct else "★ 发布《股东回报规划》"
                ax_px.annotate(
                    txt, xy=(p_dt, cur_p), xytext=(-45, 50), textcoords="offset points",
                    ha='center', va='bottom', fontsize=8.5, fontweight='bold', color='#7F1D1D',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='#FEE2E2', edgecolor='#EF4444', linewidth=1.2, alpha=0.95),
                    arrowprops=dict(arrowstyle='->', color='#B91C1C', lw=1.2)
                )
            except Exception:
                pass

        for idx, m in enumerate(div_milestones):
            try:
                m_date = pd.to_datetime(m['date'])
                sub_px = px_df[px_df['date'] <= m_date]
                if not sub_px.empty:
                    cur_p = float(sub_px.iloc[-1]['close'])
                    ax_px.axvline(m_date, color='#0284C7', linestyle='--', linewidth=1.0, alpha=0.7)
                    offset_y = 12 if (idx % 2 == 0) else 32
                    po_suffix = f" (实际{m['payout']:.1f}%)" if m.get('payout') is not None else ""
                    ax_px.annotate(
                        f"{m['title']}\n{m['desc']}{po_suffix}",
                        xy=(m_date, cur_p), xytext=(0, offset_y), textcoords="offset points",
                        ha='center', va='bottom', fontsize=7.6, fontweight='bold', color='#0369A1',
                        bbox=dict(boxstyle='round,pad=0.2', facecolor='#E0F2FE', edgecolor='#7DD3FC', alpha=0.9),
                        arrowprops=dict(arrowstyle='->', color='#0284C7', lw=0.9)
                    )
            except Exception:
                continue

        ax_px.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        ax_px.xaxis.set_major_locator(mdates.YearLocator())

    ax_px.set_ylabel('股价 (元/前复权)', fontsize=10.5, fontweight='bold', color='#1E293B', labelpad=8)
    ax_px.set_xlabel('交易时间', fontsize=10.0, color='#475569', labelpad=6)
    ax_px.spines['top'].set_visible(False)
    ax_px.spines['right'].set_visible(False)
    ax_px.yaxis.grid(True, linestyle='--', color='#F1F5F9', linewidth=0.8)
    ax_px.set_title("【图B】历史股价走势与历年实际分红实施节点标注",
                    fontsize=11.5, fontweight='bold', color='#0F172A', pad=10)

    fig.suptitle(f"图19 {plan['stock_name']} ({plan['stock_code']})：资本开支全景、分红规划实施与股价联动 → §4 财务分析",
                 fontsize=13.5, fontweight='bold', color='#0F172A', y=0.99)

    output_img_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_img_path, dpi=300, bbox_inches='tight')
    plt.close(fig)


def plot_construction_timeline(plan, output_img_path: Path) -> bool:
    """生成图20：重大在建工程推进时间轴与已投/待投资本开支堆叠图。"""
    projects = plan.get('capex_plan', {}).get('key_projects', [])
    if not projects:
        return False

    fig, ax = plt.subplots(figsize=(10.5, max(3.6, 1.3 + 0.9 * len(projects))), dpi=300)

    p_names = [p['project_name'] for p in projects][::-1]
    invested = [float(p.get('invested_billion', p['budget_billion'] * 0.8)) for p in projects][::-1]
    remaining = [float(p.get('remaining_billion', p['budget_billion'] * 0.2)) for p in projects][::-1]
    progress = [str(p.get('progress', '-')) for p in projects][::-1]
    completions = [str(p.get('expected_completion', '-')) for p in projects][::-1]

    y_pos = np.arange(len(p_names))
    bar_height = 0.38

    ax.barh(y_pos, invested, height=bar_height, color='#2563EB', alpha=0.9,
            edgecolor='#1D4ED8', label='已投入资本开支 (亿元)')
    ax.barh(y_pos, remaining, left=invested, height=bar_height, color='#E2E8F0', alpha=0.95,
            edgecolor='#94A3B8', hatch='///', label='剩余待投资本开支 (亿元)')

    for i in range(len(p_names)):
        inv = invested[i]
        rem = remaining[i]
        tot = inv + rem
        if inv > 0.5:
            ax.text(inv / 2, y_pos[i], f"已投 {inv:.1f}亿 ({progress[i]})",
                    ha='center', va='center', color='#FFFFFF', fontsize=8.8, fontweight='bold')
        if rem > max(1.0, tot * 0.08):
            ax.text(inv + rem / 2, y_pos[i], f"待投 {rem:.1f}亿",
                    ha='center', va='center', color='#475569', fontsize=8.3, fontweight='bold')
        ax.text(tot + max(0.5, tot * 0.02), y_pos[i], f"[预计转固达产] {completions[i]}",
                ha='left', va='center', color='#B91C1C', fontsize=8.8, fontweight='bold')

    ax.set_yticks(y_pos)
    ax.set_yticklabels(p_names, fontsize=9.8, fontweight='bold', color='#1E293B')
    ax.set_xlabel('项目资本开支总额 (亿元)', fontsize=10.5, fontweight='bold', color='#1E293B', labelpad=8)

    max_tot = max([i + r for i, r in zip(invested, remaining)] or [10.0])
    ax.set_xlim(0, max_tot * 1.55)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.xaxis.grid(True, linestyle='--', color='#F1F5F9', linewidth=0.8)
    ax.set_title(f"图20 {plan['stock_name']}：重大在建工程已投/待投资本开支与转固时间轴 → §4 财务分析",
                 fontsize=12.0, fontweight='bold', color='#0F172A', pad=12)
    ax.legend(loc='lower right', frameon=True, facecolor='#FFFFFF', edgecolor='#E2E8F0', fontsize=9.0)

    output_img_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_img_path, dpi=300, bbox_inches='tight')
    plt.close(fig)
    return True


def plot_fcf_coverage_and_retention(plan, combined_df, output_img_path: Path):
    """
    生成图21：提高分红率财务可行性硬指标走势图（同合并扣息口径 + 分级负轴压缩视觉排版）
    - 图A：扣息自由现金流覆盖倍数 (OCF - Capex - 费用化利息) / 合并净利润 vs 历年实际分红率
    - 图B：经营现金流自主留存空间 (1 - Capex / OCF) 走势图
    """
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11.4, 9.2), dpi=300,
        gridspec_kw={'height_ratios': [1.2, 1.0], 'hspace': 0.45}
    )

    years = combined_df['year'].tolist()
    x = np.arange(len(years))
    is_f = combined_df['is_forecast'].values
    hist_mask = ~is_f
    fore_mask = is_f

    fcfe_np = pd.to_numeric(combined_df['FCFE_NP_Ratio'], errors='coerce').values
    payout_ratio_x = (pd.to_numeric(combined_df['Payout_Ratio'], errors='coerce') / 100.0).values
    retention = pd.to_numeric(combined_df['Retention_Ratio'], errors='coerce').values

    floor_raw = plan.get('dividend_commitment', {}).get('statutory_floor_payout_ratio')
    floor_ratio = float(floor_raw) if (floor_raw is not None and float(floor_raw) > 0) else 0.50
    floor_pct = int(round(floor_ratio * 100))

    finite_fcfe = fcfe_np[np.isfinite(fcfe_np)]
    raw_min = float(np.min(finite_fcfe)) if len(finite_fcfe) else 0.0
    if raw_min < -1.2:
        neg_scale = min(0.55, round(0.75 / abs(raw_min), 2))
    else:
        neg_scale = 1.0

    def map_y(arr):
        a = np.asarray(arr, dtype=float)
        return np.where(np.isnan(a), np.nan, np.where(a >= 0, a, a * neg_scale))

    fcfe_plot = map_y(fcfe_np)
    payout_plot = map_y(payout_ratio_x)

    valid_hist = hist_mask & np.isfinite(fcfe_plot)
    if np.any(valid_hist):
        ax1.plot(x[valid_hist], fcfe_plot[valid_hist], color='#0D9488', marker='o', markersize=6.8,
                 linewidth=2.3, label='历史 扣息FCFE / 合并净利润', zorder=6)

    fore_idxs = np.where(fore_mask)[0]
    if len(fore_idxs) > 0:
        split_idx = int(fore_idxs[0])
        seg_start = max(0, split_idx - 1)
        seg_x = x[seg_start:]
        seg_y = fcfe_plot[seg_start:]
        ok_seg = np.isfinite(seg_y)
        if np.any(ok_seg):
            ax1.plot(seg_x[ok_seg], seg_y[ok_seg], color='#14B8A6', marker='s', markersize=6.2,
                     linewidth=2.1, linestyle='--', label='规划指引 扣息FCFE / 合并净利润', zorder=6)

    valid_po = hist_mask & np.isfinite(payout_ratio_x)
    if np.any(valid_po):
        ax1.plot(x[valid_po], payout_plot[valid_po], color='#2563EB', marker='D', markersize=5.5,
                 linewidth=1.8, linestyle=':', label='历年实际分红率 (归母口径/100)', zorder=5)

    ax1.axhline(floor_ratio, color='#D97706', linestyle='--', linewidth=1.6,
                label=f'本公司法定保底分红线 ({floor_pct}% / {floor_ratio:.2f}x)', zorder=3)
    if floor_pct < 70:
        ax1.axhline(0.70, color='#7C3AED', linestyle='-.', linewidth=1.3,
                    label='70% 高息现金牛跃迁线 (0.70x)', zorder=3)
    max_fcfe = float(np.max(finite_fcfe)) if len(finite_fcfe) else 0.0
    show_100 = (max_fcfe >= 0.70)
    if show_100:
        ax1.axhline(1.00, color='#059669', linestyle='-.', linewidth=1.3,
                    label='100% 净现金全额覆盖线 (1.00x)', zorder=3)
    ax1.axhline(0.00, color='#475569', linestyle='-', linewidth=1.15 if neg_scale < 1.0 else 0.9, alpha=0.8, zorder=2)

    finite_po = payout_ratio_x[np.isfinite(payout_ratio_x)]
    max_po = float(np.max(finite_po)) if len(finite_po) else 0.0
    raw_max = float(max(max_fcfe, max_po, floor_ratio, 0.70 if floor_pct < 70 else 0.75))
    if show_100:
        raw_max = max(raw_max, 1.00)
    y_min_plot = float(map_y(min(raw_min, 0.0))) - 0.22
    y_max_plot = raw_max + 0.20
    ax1.set_ylim(y_min_plot, y_max_plot)

    ax1.fill_between(x, floor_ratio, y_max_plot, color='#10B981', alpha=0.055,
                     label=f'内生覆盖保底分红安全区 (≥{floor_ratio:.2f}x)', zorder=1)

    pos_ticks = [0.0, 0.25, 0.50, 0.75]
    if y_max_plot >= 1.02:
        pos_ticks.append(1.00)
    if y_max_plot >= 1.25:
        pos_ticks.append(1.25)
    if y_max_plot >= 1.52:
        pos_ticks.append(1.50)

    if neg_scale < 1.0:
        step = 1.0 if raw_min < -2.0 else 0.5
        neg_raw = []
        v = -step
        while v >= raw_min - 0.35:
            neg_raw.append(v)
            v -= step
        all_raw_ticks = sorted(neg_raw) + pos_ticks
        ax1.set_yticks([float(map_y(t)) for t in all_raw_ticks])
        ax1.set_yticklabels([
            f"{t:.2f}" if (t > 0 and abs(t * 100 - round(t * 100 / 25) * 25) < 1e-6) else f"{t:.1f}"
            for t in all_raw_ticks
        ])
        ax1.text(0.988, 0.035, f"注：负值区间按 {neg_scale:.2f}x 比例压缩展示，以清晰对比 [0~1.0x] 分红门槛区",
                 transform=ax1.transAxes, fontsize=7.8, color='#64748B', ha='right', va='bottom',
                 bbox=dict(boxstyle='round,pad=0.2', facecolor='#F8FAFC', edgecolor='#E2E8F0', alpha=0.9))
    else:
        ax1.set_yticks(pos_ticks + ([-0.25] if y_min_plot < -0.2 else []) + ([-0.50] if y_min_plot < -0.45 else []))

    h_lines = [0.0, floor_ratio] + ([0.70] if floor_pct < 70 else []) + ([1.00] if show_100 else [])

    for i in range(len(years)):
        val = fcfe_np[i]
        val_p = fcfe_plot[i]
        if not np.isfinite(val):
            continue
        c = '#0F766E' if not is_f[i] else '#0D9488'
        po_val = payout_ratio_x[i] if np.isfinite(payout_ratio_x[i]) else None

        go_up = val >= 0
        if val >= 0:
            for hl in h_lines:
                if 0 < (hl - val) < 0.16:
                    go_up = False
                    break
        if po_val is not None and abs(val_p - float(map_y(po_val))) < 0.18:
            go_up = (val >= po_val)

        y_off = 8 if go_up else -11
        va_align = 'bottom' if go_up else 'top'
        if abs(val_p) < 0.05:
            y_off = 9 if go_up else -12

        ax1.annotate(
            f"{val:.2f}x", xy=(x[i], val_p), xytext=(0, y_off), textcoords="offset points",
            ha='center', va=va_align, fontsize=8.6, fontweight='bold', color=c,
            bbox=dict(boxstyle='round,pad=0.14', facecolor='#FFFFFF', edgecolor='none', alpha=0.90),
            zorder=9
        )

    for i in range(len(years)):
        if valid_po[i]:
            pv = payout_ratio_x[i]
            fv = fcfe_np[i] if np.isfinite(fcfe_np[i]) else -99.0
            if 0.57 <= pv <= 0.68 and fv < pv - 0.25:
                po_up = False
            elif abs(pv - fv) < 0.18:
                po_up = (pv > fv)
            else:
                po_up = True
            if abs(pv - floor_ratio) < 0.03 and fv >= pv - 0.15:
                po_up = (fv < pv)

            po_off = 7 if po_up else -11
            po_va = 'bottom' if po_up else 'top'
            ax1.annotate(
                f"{pv*100:.1f}%", xy=(x[i], float(map_y(pv))), xytext=(0, po_off), textcoords="offset points",
                ha='center', va=po_va, fontsize=7.7, fontweight='bold', color='#1D4ED8',
                bbox=dict(boxstyle='round,pad=0.12', facecolor='#EFF6FF', edgecolor='none', alpha=0.92),
                zorder=8
            )

    ax1.set_xticks(x)
    ax1.set_xticklabels(years, fontsize=9.8, fontweight='bold', color='#334155')
    ax1.set_ylabel('扣息FCFE / 合并净利润 (倍)', fontsize=10.2, fontweight='bold', color='#1E293B', labelpad=8)
    ax1.spines['top'].set_visible(False)
    ax1.spines['right'].set_visible(False)
    ax1.yaxis.grid(True, linestyle='--', color='#F1F5F9', linewidth=0.8)

    ax1.legend(loc='lower center', bbox_to_anchor=(0.5, 1.02), frameon=True,
               facecolor='#FFFFFF', edgecolor='#E2E8F0', fontsize=8.2, ncol=3)
    ax1.set_title("【图A】扣息自由现金流(FCFE)对合并净利润覆盖倍数 vs 实际分红率",
                  fontsize=11.5, fontweight='bold', color='#0F172A', pad=52)

    # 下子图：(1 - Capex/OCF) 现金留存率
    bar_width = 0.42
    ret_clean = np.where(np.isfinite(retention), retention, 0.0)
    colors = ['#10B981' if r >= 0 else '#EF4444' for r in ret_clean]
    ax2.bar(x, ret_clean, width=bar_width, color=colors, alpha=0.84,
            edgecolor=['#059669' if r >= 0 else '#DC2626' for r in ret_clean], linewidth=1.1)

    ax2.axhline(0.0, color='#334155', linestyle='-', linewidth=1.1, label='0% 现金流收支平衡线', zorder=3)
    ax2.axhline(50.0, color='#059669', linestyle='--', linewidth=1.4, label='50% 稳态现金牛门槛线 (留存率 ≥ 50%)', zorder=3)

    for i in range(len(years)):
        if not np.isfinite(retention[i]):
            continue
        r = retention[i]
        if 33.0 <= r <= 53.0:
            ax2.annotate(f"{r:.1f}%", xy=(x[i], r), xytext=(0, -13), textcoords="offset points",
                         ha='center', va='top', fontsize=8.5, fontweight='bold', color='#FFFFFF', zorder=7)
        else:
            ax2.annotate(
                f"{r:.1f}%", xy=(x[i], r), xytext=(0, 5 if r >= 0 else -11), textcoords="offset points",
                ha='center', va='bottom' if r >= 0 else 'top',
                fontsize=8.5, fontweight='bold', color='#065F46' if r >= 0 else '#B91C1C',
                bbox=dict(boxstyle='round,pad=0.1', facecolor='#FFFFFF', edgecolor='none', alpha=0.75),
                zorder=7
            )

    finite_ret = retention[np.isfinite(retention)]
    r_min = min(float(np.min(finite_ret)) * 1.28, -30.0) if len(finite_ret) else -30.0
    r_max = max(float(np.max(finite_ret)) * 1.32, 75.0) if len(finite_ret) else 75.0
    ax2.set_ylim(r_min, r_max)
    ax2.set_xticks(x)
    ax2.set_xticklabels(years, fontsize=9.8, fontweight='bold', color='#334155')
    ax2.set_ylabel('现金留存率 (1 - Capex/OCF) %', fontsize=10.2, fontweight='bold', color='#1E293B', labelpad=8)
    ax2.spines['top'].set_visible(False)
    ax2.spines['right'].set_visible(False)
    ax2.yaxis.grid(True, linestyle='--', color='#F1F5F9', linewidth=0.8)
    ax2.legend(loc='lower right', frameon=True, facecolor='#FFFFFF', edgecolor='#E2E8F0', fontsize=8.5)
    ax2.set_title("【图B】经营现金流自主留存空间 (1 - Capex/OCF) 走势图（未扣利息与分红前）",
                  fontsize=11.5, fontweight='bold', color='#0F172A', pad=10)

    fig.suptitle(f"图21 {plan['stock_name']} ({plan['stock_code']})：提高分红率财务可行性与造血留存走向 → §6 估值",
                 fontsize=13.0, fontweight='bold', color='#0F172A', y=1.01)

    output_img_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_img_path, dpi=300, bbox_inches='tight')
    plt.close(fig)


def generate_markdown_report(plan, combined_df, has_timeline: bool, output_md_path: Path):
    """生成可直接嵌入统一十章主报告 §4.2 与 §6.4 的 Markdown 专项模块。"""
    name = plan['stock_name']
    code = plan['stock_code']
    status = plan.get('current_status', {})
    capex_p = plan['capex_plan']
    div_p = plan.get('dividend_commitment', {})

    hist_rows = []
    hist_actual_payouts = []
    for _, r in combined_df.iterrows():
        y = r['year']
        tag = "*(规划指引)*" if r['is_forecast'] else "*(实际)*"
        fcf_str = f"+{r['FCF']:.2f}" if r['FCF'] > 0 else f"{r['FCF']:.2f}"
        fcfe_str = f"+{r['FCFE']:.2f}" if r['FCFE'] > 0 else f"{r['FCFE']:.2f}"
        dps_str = f"{r['DPS']:.3f}" if pd.notnull(r['DPS']) else "-"
        payout_str = f"{r['Payout_Ratio']:.2f}%" if pd.notnull(r['Payout_Ratio']) else "-"
        if not r['is_forecast'] and pd.notnull(r['Payout_Ratio']):
            hist_actual_payouts.append((y, float(r['Payout_Ratio'])))
        cov_str = f"{r['FCFE_NP_Ratio']:.2f}x" if pd.notnull(r['FCFE_NP_Ratio']) else "-"
        ret_str = f"{r['Retention_Ratio']:.1f}%" if pd.notnull(r['Retention_Ratio']) else "-"
        hist_rows.append(
            f"| **{y}** {tag} | {r['OCF']:.2f} | {r['Capex']:.2f} | {fcf_str} | {r['InterestExp']:.2f} | {fcfe_str} | "
            f"{r['ConsolNP']:.2f} | {cov_str} | {ret_str} | {r['NetProfit']:.2f} | {dps_str} | {payout_str} |"
        )
    table_hist = "\n".join(hist_rows)
    actual_payout_summary = "、".join([f"{y}年为 {po:.1f}%" for y, po in hist_actual_payouts[-3:]]) or "暂缺近三年完整分红实施记录"

    projects = capex_p.get('key_projects', [])
    proj_rows = []
    for p in projects:
        inv = float(p.get('invested_billion', p['budget_billion'] * 0.8))
        rem = float(p.get('remaining_billion', p['budget_billion'] * 0.2))
        proj_rows.append(
            f"| **{p['project_name']}** | {p['budget_billion']:.1f} 亿 | {inv:.1f} 亿 ({p.get('progress', '-')}) | {rem:.1f} 亿 | {p.get('expected_completion', '-')} | {p.get('impact', '-')} |"
        )
    table_proj = "\n".join(proj_rows)

    hist_only = combined_df[~combined_df['is_forecast']]
    fore_only = combined_df[combined_df['is_forecast']]
    latest_h = hist_only.iloc[-1] if not hist_only.empty else combined_df.iloc[0]
    first_f = fore_only.iloc[0] if not fore_only.empty else latest_h
    last_f = fore_only.iloc[-1] if not fore_only.empty else latest_h

    y_h = str(latest_h['year'])
    y_f1 = str(first_f['year'])
    y_fn = str(last_f['year'])
    fcfe_h = float(latest_h['FCFE_NP_Ratio']) if pd.notnull(latest_h['FCFE_NP_Ratio']) else 0.0
    fcfe_f1 = float(first_f['FCFE_NP_Ratio']) if pd.notnull(first_f['FCFE_NP_Ratio']) else 0.0
    fcfe_fn = float(last_f['FCFE_NP_Ratio']) if pd.notnull(last_f['FCFE_NP_Ratio']) else 0.0
    ret_h = float(latest_h['Retention_Ratio']) if pd.notnull(latest_h['Retention_Ratio']) else 0.0
    ret_f1 = float(first_f['Retention_Ratio']) if pd.notnull(first_f['Retention_Ratio']) else 0.0

    floor_raw = div_p.get('statutory_floor_payout_ratio')
    floor_ratio = float(floor_raw) if (floor_raw is not None and float(floor_raw) > 0) else 0.50
    floor_p = int(round(floor_ratio * 100))

    if fcfe_h >= floor_ratio:
        floor_support_text = (
            f"{y_h} 年扣息 FCFE/合并净利润达到 **{fcfe_h:.2f}x**，已站上公司承诺的法定保底分红线（**{floor_p}% / {floor_ratio:.2f}x**），"
            f"表明现金分红可由当年内生扣息自由现金流全额覆盖，无需新增净负债。"
        )
    else:
        cross_rows = fore_only[fore_only['FCFE_NP_Ratio'] >= floor_ratio]
        if not cross_rows.empty:
            cross_y = str(cross_rows.iloc[0]['year'])
            floor_support_text = (
                f"{y_h} 年扣息 FCFE/合并净利润为 **{fcfe_h:.2f}x**（暂低于 **{floor_p}% / {floor_ratio:.2f}x** 保底线），"
                f"主要受在建工程支出与有息负债利息尚处高位制约；按当前规划，预计 **{cross_y}** 起将跨越 {floor_ratio:.2f}x 线，实现内生现金流对保底分红的全额覆盖。"
            )
        else:
            floor_support_text = (
                f"{y_h} 年扣息 FCFE/合并净利润为 **{fcfe_h:.2f}x**，{y_f1} 规划期因续建项目为 **{fcfe_f1:.2f}x**，低于 **{floor_p}% / {floor_ratio:.2f}x** 保底红线；"
                f"说明现阶段分红部分依赖低息项目贷分担建设期资本开支，待 {y_fn} 在建转固后回升至 **{fcfe_fn:.2f}x**。"
            )

    if fcfe_fn >= 0.70:
        upside_text = (
            f"随资本开支收缩及财务费用递减，{y_fn} 扣息覆盖倍数预计升至 **{fcfe_fn:.2f}x**（突破 **0.70x** 高息现金牛门槛），"
            f"在财务机制上具备向 **70%+** 更高分红率跃迁的内生造血基础。"
        )
    else:
        upside_text = (
            f"{y_fn} 扣息覆盖倍数回升至 **{fcfe_fn:.2f}x**，暂未突破 0.70x 门槛；在核心续建项目全面转固降负债前，"
            f"维持当前 **{floor_p}%** 保底分红契约是最匹配资产周期的稳健选择。"
        )

    if ret_f1 >= 50.0:
        ret_conclusion = f"留存率已达 **{ret_f1:.1f}%**（突破稳态现金牛 ≥50% 门槛线），表明公司税后经营现金流在覆盖全部资本开支后仍有超过一半的盈余可用于偿付利息与分红。"
    elif ret_f1 >= 20.0:
        ret_conclusion = f"留存率回升至 **{ret_f1:.1f}%** 稳健区间，表明内生经营现金流已可覆盖全部资本开支并留出一定余量用于还息与股东分红。"
    else:
        ret_conclusion = f"规划施工期留存率阶段性收敛至 **{ret_f1:.1f}%**（略高于或接近 0% 收支平衡线），说明新增重大工程仍需借助外部低息项目贷配合。"

    timeline_block = ""
    if has_timeline and table_proj:
        timeline_block = f"""![图20 重大在建工程转固时间轴](图表/图20_重大在建工程转固时间轴.png)

| 项目名称 | 预算总额 | 已投资本开支 (进度) | 剩余待投资金 | 预计转固/达产时间 | 对现金流与利润的影响 |
| :--- | :---: | :---: | :---: | :---: | :--- |
{table_proj}
"""
    else:
        timeline_block = "> 注：当前暂无具体拆分重大在建工程项目清单，`图20_重大在建工程转固时间轴.png` 跳过；重大工程投资节奏见总量规划对账表。\n"

    content = f"""# {name}（{code}）：资本开支规划、在建转固与分红可行性专项模块

> **对齐主报告章节**：以下小节可直接嵌入 `report-template.md` v3 的 **§4.2 现金流与盈利质量**（`#### 4.2.1`）与 **§6.4 估值结论与安全边际**（`#### 6.4.1`），不改变主报告一级/三级固定骨架。  
> **口径说明**：A 股 `OCF` 未扣除利息且为合并口径，故采用同合并口径 `扣息FCFE = OCF - Capex - 费用化利息` 除以 `合并净利润`；`实际分红率` 严格以 `年度分红总额 ÷ 归母净利润` 核算。

---

#### 4.2.1 未来资本开支规划、重大在建转固与自由现金流拐点（嵌入 §4.2 末尾）

![图19 Capex规划、在建转固与股价联动](图表/图19_Capex规划与股价联动.png)

| 年份 | OCF (亿) | Capex (亿) | 未扣息FCF (亿) | 费用化利息 (亿) | 扣息FCFE (亿) | 合并净利润 (亿) | 扣息FCFE/合并NP | 留存率 (1-Capex/OCF) | 归母净利润 (亿) | 每股股息 (元) | 实际分红率 (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
{table_hist}

{timeline_block}
- **资本开支周期阶段**：**{capex_p.get('cycle_phase', '-')}**；峰值与拐点：{capex_p.get('peak_year', '-')}。{capex_p.get('trend_summary', '')}

---

#### 6.4.1 分红承诺与提高分红率财务可行性评估（嵌入 §6.4 末尾）

![图21 提高分红率财务可行性与造血留存](图表/图21_分红可行性与造血留存.png)

- **扣息自由现金流覆盖倍数 (FCFE / 合并NP) vs 实际分红率**：由 {y_h} 年的 **{fcfe_h:.2f}x** 演进至规划期 {y_f1} 年的 **{fcfe_f1:.2f}x**、{y_fn} 年的 **{fcfe_fn:.2f}x**。
  - **保底分红支撑性**：{floor_support_text}
  - **分红率提升财务空间**：{upside_text}
- **经营现金流自主留存空间 (1 - Capex / OCF)**：{y_h} 年为 **{ret_h:.1f}%**，{y_f1} 年规划指引为 **{ret_f1:.1f}%**。{ret_conclusion}
- **股东回报承诺与历史履约**：依据{div_p.get('policy_title', '股东回报规划')}，法定保底分红比例为 **不低于 {floor_p}%**；近三年实际分红率（{actual_payout_summary}）。
"""
    output_md_path.parent.mkdir(parents=True, exist_ok=True)
    output_md_path.write_text(content, encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="company-research-v3 Capex 与分红跃迁引擎")
    parser.add_argument("--dir", default=".", help="研究批次根目录（含 data/ 与 input/）")
    parser.add_argument("--config", default="", help="capex_dividend_plan.json 路径（默认 <dir>/input/capex_dividend_plan.json）")
    parser.add_argument("--init-template", action="store_true", help="根据 data/*.csv 生成 input/capex_dividend_plan.json 模板")
    parser.add_argument("--company", default="", help="--init-template 时可选指定公司名")
    parser.add_argument("--code", default="", help="--init-template 时可选指定股票代码")
    parser.add_argument("--out-dir", default="", help="图表输出目录（默认 <dir>/reports/图表）")
    parser.add_argument("--json-out", default="", help="JSON 输出路径（默认 <dir>/reports/capex_dividend_analysis.json）")
    parser.add_argument("--md-out", default="", help="Markdown 模块输出路径（默认 <dir>/reports/Capex与分红跃迁专项.md）")
    args = parser.parse_args(argv)

    project_dir = Path(args.dir).resolve()
    config_path = Path(args.config).resolve() if args.config else (project_dir / "input" / "capex_dividend_plan.json")

    if args.init_template:
        init_template(project_dir, config_path, company=args.company, code=args.code)
        return 0

    if not config_path.is_file():
        print(f"[SKIP] 未找到 {config_path}；如需启用 Capex 与分红跃迁分析，请先运行 --init-template 生成并补充")
        return 0

    plan_preview = json.loads(config_path.read_text(encoding='utf-8-sig'))
    if plan_preview.get("enabled") is False:
        print(f"[SKIP] {config_path.name} 中 enabled=false，跳过 Capex 与分红跃迁引擎")
        return 0

    raw_data_dir = project_dir / "data"
    out_dir = Path(args.out_dir).resolve() if args.out_dir else (project_dir / "reports" / "图表")
    json_out = Path(args.json_out).resolve() if args.json_out else (project_dir / "reports" / "capex_dividend_analysis.json")
    md_out = Path(args.md_out).resolve() if args.md_out else (project_dir / "reports" / "Capex与分红跃迁专项.md")

    plan, hist_df, combined_df, px_df, div_milestones = load_company_data(raw_data_dir, config_path)

    c1 = out_dir / "图19_Capex规划与股价联动.png"
    c2 = out_dir / "图20_重大在建工程转固时间轴.png"
    c3 = out_dir / "图21_分红可行性与造血留存.png"

    plot_capex_fcf_and_price(plan, combined_df, px_df, div_milestones, c1)
    has_timeline = plot_construction_timeline(plan, c2)
    plot_fcf_coverage_and_retention(plan, combined_df, c3)

    json_out.parent.mkdir(parents=True, exist_ok=True)
    records = combined_df.where(pd.notnull(combined_df), None).to_dict(orient='records')
    json_out.write_text(
        json.dumps({
            'plan': plan,
            'has_timeline_chart': has_timeline,
            'charts': {
                '图19': str(c1.relative_to(project_dir)).replace("\\", "/") if c1.is_relative_to(project_dir) else str(c1),
                '图20': (str(c2.relative_to(project_dir)).replace("\\", "/") if c2.is_relative_to(project_dir) else str(c2)) if has_timeline else None,
                '图21': str(c3.relative_to(project_dir)).replace("\\", "/") if c3.is_relative_to(project_dir) else str(c3),
            },
            'combined_timeseries': records,
            'dividend_milestones': div_milestones
        }, ensure_ascii=False, indent=2) + "\n",
        encoding='utf-8'
    )

    generate_markdown_report(plan, combined_df, has_timeline, md_out)
    print(f"[OK] 图19：{c1}")
    if has_timeline:
        print(f"[OK] 图20：{c2}")
    print(f"[OK] 图21：{c3}")
    print(f"[OK] JSON：{json_out}")
    print(f"[OK] Markdown：{md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
