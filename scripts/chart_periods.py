#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the latest actual-period chart evidence from statement CSVs.

Run: python scripts/chart_periods.py --dir <batch>
Writes reports/图表最新期数据.json. Amounts remain in raw statement units;
renderers convert explicitly. YTD flows and snapshot stocks are never annualised.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import copy
from pathlib import Path

import pandas as pd

FILES = {"income": "利润表_按报告期.csv", "balance": "资产负债表_按报告期.csv",
         "cash": "现金流量表_按报告期.csv", "indicator": "主要财务指标_按报告期.csv"}
FIELDS = {
    "revenue": ("income", ("TOTAL_OPERATE_INCOME", "OPERATE_INCOME", "营业总收入", "营业收入")),
    "profit": ("income", ("PARENT_NETPROFIT", "归母净利润", "归母净利")),
    "cost": ("income", ("OPERATE_COST", "营业成本")),
    "ocf": ("cash", ("NETCASH_OPERATE", "经营活动产生的现金流量净额")),
    "capex": ("cash", ("CONSTRUCT_LONG_ASSET", "购建固定资产、无形资产和其他长期资产支付的现金")),
    "assets": ("balance", ("TOTAL_ASSETS", "资产总计")),
    "liabilities": ("balance", ("TOTAL_LIABILITIES", "负债合计")),
    "equity": ("balance", ("TOTAL_PARENT_EQUITY", "归属于母公司股东权益", "归母权益")),
    "shares": ("balance", ("SHARE_CAPITAL", "TOTAL_SHARE", "股本", "实收资本（或股本）")),
    "cash": ("balance", ("MONETARYFUNDS", "货币资金")),
    "short_loan": ("balance", ("SHORT_LOAN", "短期借款")),
    "long_loan": ("balance", ("LONG_LOAN", "长期借款")),
    "bond": ("balance", ("BOND_PAYABLE", "应付债券")),
    "due_1y": ("balance", ("NONCURRENT_LIAB_1YEAR", "一年内到期的非流动负债")),
    "lease": ("balance", ("LEASE_LIAB", "租赁负债")),
    "roe": ("indicator", ("ROEJQ", "ROE", "净资产收益率", "加权平均净资产收益率")),
    "bps": ("indicator", ("BPS", "每股净资产")),
}
CHART_METRICS = {"图01": ("revenue", "profit"), "图02": ("roe", "bps"),
                 "图04": ("gross_margin", "net_margin", "roe"),
                 "图05": ("ocf", "capex", "fcf"),
                 "图12": ("profit",),
                 "图15": ("liability_ratio", "debt_ratio", "net_cash")}
NAMES = {"revenue": "营业总收入", "profit": "归母净利润", "roe": "累计ROE（非年化）",
         "bps": "期末每股净资产", "gross_margin": "累计毛利率", "net_margin": "累计归母净利率",
         "ocf": "经营现金流", "capex": "资本开支", "fcf": "自由现金流",
         "liability_ratio": "期末资产负债率", "debt_ratio": "期末有息债务/总资产",
         "net_cash": "期末现金减有息债务"}
RATIOS = {"roe", "gross_margin", "net_margin", "liability_ratio", "debt_ratio"}
STOCKS = {"bps", "liability_ratio", "debt_ratio", "net_cash"}


def _number(v):
    try:
        x = float(str(v).replace(",", "").replace("%", ""))
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _read(path):
    if not path.exists():
        return None
    df = pd.read_csv(path, encoding="utf-8-sig")
    col = next((c for c in ("REPORT_DATE", "报告期", "报告日期", "日期", "end_date") if c in df), None)
    if col is None:
        return None
    df["_period"] = pd.to_datetime(df[col], errors="coerce")
    return df.dropna(subset=["_period"]).sort_values("_period").drop_duplicates("_period", keep="last").set_index("_period")


def _ratio(a, b):
    return None if a is None or b in (None, 0) else 100 * a / b


def period_label(period):
    d = pd.Timestamp(period)
    return f"{d.year}全年" if d.month == 12 else f"{d.year}年1—{d.month}月"


def build_period_pack(project):
    project = Path(project)
    frames = {k: _read(project / "data" / f) for k, f in FILES.items()}
    dates = [df.index.max() for k, df in frames.items() if k != "indicator" and df is not None and len(df)]
    if not dates:
        return {"schema_version": 1, "latest_period": None, "comparisons": [], "source_sha256": {}}
    latest = max(dates)
    prior = latest - pd.DateOffset(years=1)

    def snapshot(period):
        values, evidence = {}, {}
        for key, (group, aliases) in FIELDS.items():
            df = frames[group]
            value, column = None, None
            if df is not None and period in df.index:
                row = df.loc[period]
                for c in aliases:
                    if c in row and _number(row[c]) is not None:
                        value, column = _number(row[c]), c
                        break
            values[key] = value
            evidence[key] = {"file": FILES[group], "column": column, "period": str(period.date())}
        v = values
        v["fcf"] = None if v["ocf"] is None or v["capex"] is None else v["ocf"] - v["capex"]
        v["gross_margin"] = _ratio(None if v["revenue"] is None or v["cost"] is None else v["revenue"] - v["cost"], v["revenue"])
        v["net_margin"] = _ratio(v["profit"], v["revenue"])
        # Missing debt components stay unknown unless the provider explicitly reports zero.
        # Columns present but entirely empty may mean no such instrument; this must be declared.
        policy_file = project / "input" / "图表期间配置.json"
        policy = json.loads(policy_file.read_text(encoding="utf-8-sig")) if policy_file.exists() else {}
        absent_zero = policy.get("debt_absent_as_zero", [])
        debt_fields = ("short_loan", "long_loan", "bond", "due_1y", "lease")
        components = [0.0 if v[k] is None and k in absent_zero else v[k] for k in debt_fields]
        debt = None if any(x is None for x in components) else sum(components)
        v["liability_ratio"], v["debt_ratio"] = _ratio(v["liabilities"], v["assets"]), _ratio(debt, v["assets"])
        v["net_cash"] = None if v["cash"] is None or debt is None else v["cash"] - debt
        if v["bps"] is None and v["equity"] is not None and v["shares"] not in (None, 0):
            v["bps"] = v["equity"] / v["shares"]
            evidence["bps"] = {"formula": "parent_equity/share_capital", "period": str(period.date())}
        return {"period": str(period.date()), "label": period_label(period), "values": v,
                "source_fields": evidence, "debt_absent_as_zero": absent_zero}

    hashes = {f: hashlib.sha256((project / "data" / f).read_bytes()).hexdigest()
              for f in FILES.values() if (project / "data" / f).exists()}
    quarter_dates = [latest - pd.DateOffset(years=1), latest - pd.offsets.QuarterEnd(), latest]
    flow_fields = ('revenue', 'profit', 'cost', 'ocf', 'capex')
    def quarter_snapshot(date):
        current = snapshot(date)
        current['cumulative_values'] = copy.deepcopy(current['values'])
        previous_date = date - pd.offsets.QuarterEnd()
        previous = snapshot(previous_date)
        for key in flow_fields:
            x = current['values'].get(key)
            y = 0 if date.month == 3 else previous['values'].get(key)
            current['values'][key] = None if x is None or y is None else x-y
        v = current['values']
        v['fcf'] = None if v['ocf'] is None or v['capex'] is None else v['ocf']-v['capex']
        v['gross_margin'] = _ratio(None if v['revenue'] is None or v['cost'] is None else v['revenue']-v['cost'], v['revenue'])
        v['net_margin'] = _ratio(v['profit'],v['revenue'])
        current['label'] = f'{date.year}Q{(date.month-1)//3+1}'
        current['flow_basis'] = 'single_quarter'
        current['previous_cumulative_period'] = None if date.month == 3 else str(previous_date.date())
        return current
    quarter_rows = [quarter_snapshot(d) for d in quarter_dates]
    history_dates = sorted({d for k,df in frames.items() if k != 'indicator' and df is not None for d in df.index
                            if latest.year-11 <= d.year <= latest.year and d <= latest and d.month in (3,6,9,12)})
    history = [quarter_snapshot(d) for d in history_dates]
    income = frames['income']
    has_interim = income is not None and any(d.month != 12 for d in income.index)
    return {"schema_version": 3, "latest_period": str(latest.date()),
            "basis": "FY" if latest.month == 12 else "YTD", "is_forecast": False,
            "comparisons": [snapshot(prior), snapshot(latest)], "quarter_comparisons": quarter_rows,
            "history": history, "has_interim_income": has_interim,
            "source_sha256": hashes}


def refresh_period_pack(project):
    project = Path(project)
    pack = build_period_pack(project)
    out = project / "reports" / "图表最新期数据.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return pack


def comparison_labels(pack):
    return [r['label']+'\n'+basis for r,basis in zip(pack['quarter_comparisons'],('同比基期','环比基期','本期实际'))]


def chart_values(pack, key):
    values = [r['values'].get(key) for r in pack['quarter_comparisons']]
    return values


def changes(pack, key):
    values = chart_values(pack, key)
    current = values[-1]
    result = {}
    for kind,index in (('yoy',0),('qoq',1)):
        base = values[index]
        if key == 'roe' and kind == 'qoq':
            result[kind] = {'value':None,'type':'not_applicable','label':'累计ROE不适用'}
        elif base is None or current is None:
            result[kind] = {'value':None,'type':'missing','label':'不可比/未披露'}
        elif key in RATIOS:
            delta = current-base
            result[kind] = {'value':delta,'type':'pp','label':f'{delta:+.2f}pct'}
        elif base > 0 and current >= 0:
            delta = (current/base-1)*100
            result[kind] = {'value':delta,'type':'percent','label':f'{delta:+.2f}%'}
        else:
            delta = current-base
            unit = '元' if key == 'bps' else '亿元'
            divisor = 1 if key == 'bps' else 1e8
            turn = '，转正' if base < 0 < current else '，转负' if current < 0 < base else ''
            result[kind] = {'value':delta,'type':'absolute','label':f'{delta/divisor:+.2f}{unit}{turn}'}
    return result


def annual_growth(pack, key, years):
    """Compare adjacent complete fiscal years; never annualise an interim row."""
    annual = {int(row['period'][:4]): row['cumulative_values'].get(key)
              for row in pack['history'] if row['period'].endswith('-12-31')
              and row['period'] <= pack['latest_period']}
    result = []
    for year in years:
        current, prior = annual.get(year), annual.get(year-1)
        if current is None or prior is None:
            result.append(None)
        elif key in RATIOS:
            result.append(current-prior)
        elif key == 'net_cash':
            # 净现金（余额指标）：计算年度净增减额（亿元），消除常年为负导致的空折线
            result.append((current - prior) / 1e8)
        else:
            # 流量指标（营收/净利/现金流等）：基期非零时计算连续变化率，即使跨零/负值折线依然连续
            if prior != 0:
                result.append((current - prior) / abs(prior) * 100)
            else:
                result.append(None)
    return result


def extend_chart_input(value, chart_id, pack):
    """Append actuals to the ORIGINAL chart data; do not create auxiliary axes."""
    if not pack.get('latest_period') or pack.get('basis') == 'FY':
        return value
    labels = comparison_labels(pack)
    if chart_id in ('图01', '图02'):
        df = value.tail(12).copy()
        df['_chart_label'] = [pd.Timestamp(d).strftime('%Y') for d in df['REPORT_DATE']]
        rows = []
        for i, source in enumerate(pack['quarter_comparisons']):
            row = {'REPORT_DATE': pd.Timestamp(source['period']), '_chart_label': labels[i]}
            for key in CHART_METRICS[chart_id]:
                for alias in FIELDS[key][1]:
                    row[alias] = chart_values(pack,key)[i]
            rows.append(row)
        return pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
    op = copy.deepcopy(value)
    section, label_key, mapping = {
        '图04': ('profitability', 'labels', {'毛利率':'gross_margin','净利率':'net_margin','ROE':'roe'}),
        '图05': ('cashflow', 'labels', {'OCF':'ocf','Capex':'capex','FCF':'fcf'}),
        '图15': ('leverage', 'labels', {'资产负债率':'liability_ratio','有息负债率':'debt_ratio','净现金':'net_cash'}),
        '图12': ('forecast', 'labels_hist', {'np_hist':'profit'}),
    }[chart_id]
    if section not in op:
        return op
    d = op[section]
    old_length = len(d[label_key])
    d[label_key].extend(labels)
    for target, key in mapping.items():
        divisor = 1 if key in RATIOS or key == 'bps' else 1e8
        d[target] = list(d.get(target, [None] * old_length)) + [float('nan') if v is None else v/divisor for v in chart_values(pack,key)]
    # D&A lacks current-period notes; leave the latest points missing, never zero.
    if section == 'cashflow' and d.get('D_A'):
        d['D_A'] = list(d['D_A']) + [float('nan')]*3
    if section == 'profitability':
        d['ROE名称'] = '累计ROE（非年化；不作环比）'
    return op


def record_integrated_figure(fig, chart_id, pack):
    if fig is None or not pack.get('latest_period') or pack.get('basis') == 'FY':
        return fig
    axes = fig.axes
    def bar(a, index):
        return list(a.containers[index].datavalues)[-3:]
    def line(a, index):
        return list(a.lines[index].get_ydata())[-3:]
    plotted = {
        '图01': lambda: {'revenue':bar(axes[0],0),'profit':line(axes[1],0)},
        '图02': lambda: {'roe':bar(axes[0],0),'bps':line(axes[1],0)},
        '图04': lambda: {'gross_margin':line(axes[0],0),'net_margin':line(axes[0],1),'roe':bar(axes[1],0)},
        '图05': lambda: {'ocf':bar(axes[0],0),'capex':bar(axes[0],1),'fcf':line(axes[1],0)},
        '图15': lambda: {'liability_ratio':line(axes[0],0),'debt_ratio':line(axes[0],1),'net_cash':bar(axes[1],0)},
        '图12': lambda: {'profit':bar(axes[0],0)},
    }[chart_id]()
    fig._latest_values = {key:[None if x is None or not math.isfinite(float(x)) else float(x)*(1 if key in RATIOS or key == 'bps' else 1e8) for x in values] for key,values in plotted.items()}
    artist_map = {
        '图01': lambda: {'revenue':axes[0].containers[0], 'profit':axes[1].lines[0]},
        '图02': lambda: {'roe':axes[0].containers[0], 'bps':axes[1].lines[0]},
        '图04': lambda: {'gross_margin':axes[0].lines[0], 'net_margin':axes[0].lines[1], 'roe':axes[1].containers[0]},
        '图05': lambda: {'ocf':axes[0].containers[0], 'capex':axes[0].containers[1], 'fcf':axes[1].lines[0]},
        '图15': lambda: {'liability_ratio':axes[0].lines[0], 'debt_ratio':axes[0].lines[1], 'net_cash':axes[1].containers[0]},
        '图12': lambda: {'profit':axes[0].containers[0]},
    }[chart_id]()
    # Break FY-to-quarter connectors within the SAME axes.
    latest_start = None
    for ax in axes:
        for ln in list(ax.lines):
            x, y = list(ln.get_xdata()), list(ln.get_ydata())
            if len(x) >= 4 and len(x) == len(y) == len(ax.get_xticks()) and any('本期实际' in t.get_text() for t in ax.get_xticklabels()):
                split = len(x) - 3
                latest_start = split
                ln.set_data(x[:split], y[:split])
                ax.plot(x[split:], y[split:], color=ln.get_color(), marker=ln.get_marker(),
                        linewidth=ln.get_linewidth(), linestyle=ln.get_linestyle(), markersize=ln.get_markersize(), label='_nolegend_')
    labels = axes[0].get_xticklabels()
    actual_positions = [i for i,t in enumerate(labels) if '基期' in t.get_text() or '本期实际' in t.get_text()]
    if actual_positions:
        start = actual_positions[0]
        axes[0].axvline(start-.5, color='#B07A32', linestyle=':', linewidth=1.2)
        axes[0].axvspan(start-.48, start+2.48, facecolor='#FFEBC6', alpha=.35, zorder=-1)
    note = '末三列：上年同季 / 上季度 / 本季度；流量和利润率为单季，BPS/杠杆为期末值；累计ROE不作环比'
    missing = [NAMES[k] for k in CHART_METRICS[chart_id] if chart_values(pack,k)[-1] is None]
    if missing:
        note += '；最新期未披露：' + '、'.join(missing)
    fig.text(.5, -.06, note, ha='center', va='top', fontsize=8, color='#6F552E')
    fig._latest_period = pack['latest_period']
    fig._latest_chart_id = chart_id
    fig._integrated_latest = True
    fig._display_basis = 'single_quarter_and_snapshot; ROE=YTD_yoy_only'
    return fig


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True)
    args = ap.parse_args()
    pack = refresh_period_pack(args.dir)
    print(f"[最新期图表证据] {pack['latest_period']} / {pack.get('basis', 'missing')}")
    return 0 if pack["latest_period"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
