#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G8-PERIOD: latest actual financial period, basis, values and artifact checks.

Run: python scripts/chart_period_qc.py --dir <batch>
Writes reports/图表最新期审核.json. Market dates and forecast labels cannot
substitute for a financial chart's latest actual-period values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

from chart_periods import build_period_pack, CHART_METRICS, chart_values
from financial_history_charts import series_data, growth_line_failures


def _load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _same(a, b):
    if a is None or b is None:
        return a is b
    return isinstance(a, (float, int)) and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-7)


def check_chart_periods(project):
    project = Path(project)
    warnings, failures = [], []
    expected = build_period_pack(project)
    latest = expected.get("latest_period")
    if not latest:
        return warnings, ["G8-PERIOD: 原始三表无可识别报告期"]
    try:
        saved = _load(project / "reports" / "图表最新期数据.json")
        manifest = _load(project / "reports" / "图表期间覆盖.json")
        ops = _load(project / "input" / "运营补充数据.json")
    except (OSError, ValueError) as exc:
        return warnings, [f"G8-PERIOD: 缺少/损坏最新期产物，须重建图表：{exc}"]
    if saved != expected or manifest.get("source_sha256") != expected["source_sha256"]:
        failures.append("G8-PERIOD: 原始三表与图表证据/指纹不一致，图表已过期")
    if manifest.get("latest_statement_period") != latest:
        failures.append(f"G8-PERIOD: 图表报告期未覆盖原始数据最新期 {latest}")
    ops_file = project / "input" / "运营补充数据.json"
    if manifest.get("ops_sha256") != hashlib.sha256(ops_file.read_bytes()).hexdigest():
        failures.append("G8-PERIOD: 运营/分部/同行输入变化后未重建图表")
    exemptions = _load(project / "input" / "图表豁免.json") if (project / "input" / "图表豁免.json").exists() else {}
    exempt = {str(e.get("图", "")).split("_")[0] for e in exemptions.get("豁免", [])}
    charts = manifest.get("charts", {})
    for chart, entry in charts.items():
        path = project / "reports" / "图表" / entry.get("file", "__missing__")
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry.get("png_sha256"):
            failures.append(f"G8-PERIOD: {chart} PNG 缺失或与本次构图清单不一致")
        layout=entry.get('layout',{})
        if (layout.get('number_format')!={'max_decimal_places':2,'small_nonzero':'inequality','trim_trailing_zeros':True}
            or layout.get('number_format_violations') != []):
            failures.append(f'G8-PERIOD: {chart} 数字格式未审计或存在超过2位小数的图中文字')
        if layout.get('native'):
            gaps=[v for v in [layout.get('header_gap_pt'),layout.get('footer_gap_pt'),*layout.get('row_gaps_pt',[])] if v is not None]
            if not layout.get('measured') or layout.get('text_collisions',[]) or layout.get('text_out_of_bounds',[]) or any(not 3<=v<=26 for v in gaps):
                failures.append(f'G8-PERIOD: {chart} 原生图表的标题/图例/脚注间距或文字碰撞不合格')
    for chart, metrics in CHART_METRICS.items():
        if chart in exempt:
            continue
        d = charts.get(chart, {})
        if expected.get('has_interim_income') or d.get('layout',{}).get('grouped_by_year'):
            failures.extend(f'G8-PERIOD: {chart} {message}' for message in
                            growth_line_failures(expected,chart,d.get('growth_lines',{}),ops))
        if expected["basis"] == "YTD":
            if d.get("latest_period") != latest:
                failures.append(f"G8-PERIOD: {chart} 仍停留在年报，必须绘制 {latest} 最新实际同口径面板")
            if d.get("basis") != "YTD" or d.get("is_forecast") is not False:
                failures.append(f"G8-PERIOD: {chart} 累计期间被混成全年或预测")
            if d.get('integrated_original_axes') is not True:
                failures.append(f"G8-PERIOD: {chart} 最新实际未整合进原图序列，不接受右侧附加面板")
            layout = d.get('layout', {})
            if layout.get('number_format')!={'max_decimal_places':2,'small_nonzero':'inequality','trim_trailing_zeros':True}:
                failures.append(f"G8-PERIOD: {chart} 缺少最多2位小数与极小非零值格式声明")
            if layout.get('axes_count') != 2*len(metrics) or layout.get('latest_tick_visible') is not True or layout.get('grouped_by_year') is not True:
                failures.append(f"G8-PERIOD: {chart} 原图坐标系/最新年份可见标签检查失败")
            if layout.get('right_gutter_ratio', 1) > .20:
                failures.append(f"G8-PERIOD: {chart} 右侧空白超过20%，请检查外置图例布局")
            if not layout.get('measured') or layout.get('annotation_collisions') != []:
                failures.append(f"G8-PERIOD: {chart} 缺少测量式布局审核或柱上数字重叠")
            gaps=[layout.get('header_gap_pt'),layout.get('footer_gap_pt'),*layout.get('row_gaps_pt',[])]
            if any(not isinstance(v,(int,float)) or not 3<=v<=26 for v in gaps):
                failures.append(f"G8-PERIOD: {chart} 图例/子图/脚注间距不合格：{gaps}")
            for metric in metrics:
                data=series_data(expected,metric)
                counts=layout.get('bar_label_counts',{}).get(metric,{})
                if (counts.get('annual') != sum(v is not None for v in data['annual']) or
                    counts.get('quarter') != sum(v is not None for seq in data['quarters'] for v in seq) or
                    counts.get('text_matches_values') is not True or counts.get('number_format_valid') is not True):
                    failures.append(f"G8-PERIOD: {chart}/{metric} 年度/季度柱上数字缺失或与柱值不符")
                actual = d.get("rendered_values", {}).get(metric, [])
                required = chart_values(expected, metric)
                if len(actual) != 3 or any(not _same(a, b) for a, b in zip(actual, required)):
                    failures.append(f"G8-PERIOD: {chart}/{metric} 图中数值与上年同季/上季/本季原表不符")
                if d.get('display_basis') != 'year_grouped_annual_quarters; flows=single_quarter; stocks=end; ROE=YTD':
                    failures.append(f"G8-PERIOD: {chart} 未正确声明单季/期末/累计ROE口径")
                if required[-1] is None:
                    warnings.append(f"G8-PERIOD: {chart}/{metric} 最新期字段不可得，图中必须明确未披露")
        elif chart in {"图04", "图05", "图15"}:
            section = {"图04": "profitability", "图05": "cashflow", "图15": "leverage"}[chart]
            if not any(str(latest[:4]) in str(x) for x in ops.get(section, {}).get("labels", [])):
                failures.append(f"G8-PERIOD: {chart} 未覆盖最新完整财年 {latest[:4]}")
        path = project / "reports" / "图表" / d.get("file", "__missing__")
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != d.get("png_sha256"):
            failures.append(f"G8-PERIOD: {chart} PNG 缺失或与本次构图清单不一致")

    iw, inf = check_period_inputs(project, expected=expected, ops=ops, exempt=exempt)
    warnings.extend(iw); failures.extend(inf)
    return warnings, failures



def check_period_inputs(project, *, expected=None, ops=None, exempt=None):
    """Cheap input-only preflight; the full period gate reuses the same rules."""
    project = Path(project)
    warnings, failures = [], []
    try:
        expected = expected if expected is not None else build_period_pack(project)
        ops = ops if ops is not None else _load(project / "input" / "运营补充数据.json")
        if exempt is None:
            config = _load(project / "input" / "图表豁免.json")
            exempt = {str(e.get("图", "")).split("_")[0] for e in config.get("豁免", [])}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return warnings, [f"G8-PERIOD 输入预检失败：{exc}"]
    latest = expected.get("latest_period")
    if not latest:
        return warnings, ["G8-PERIOD: 原始三表无可识别报告期"]
    # Segments, peers and dividends have independent disclosure calendars.
    # A dated documented exception is allowed; painting the market date is not.
    for chart, section in (("图03", "segment"), ("图06", "peers_period"), ("图07", "dps")):
        if chart in exempt:
            continue
        review = ops.get(section, {}).get("period_review", {})
        if not review:
            failures.append(f"G8-PERIOD: {chart} 缺少独立期间核查 period_review")
            continue
        if review.get("checked_through") != latest or not review.get("source"):
            failures.append(f"G8-PERIOD: {chart} 未基于最新财报核查期间/来源")
        end = str(review.get("period_end", ""))
        if not end or end > latest:
            failures.append(f"G8-PERIOD: {chart} 数据期缺失或超出本次最新实际期")
        if end != latest and not str(review.get("reason", "")).strip():
            failures.append(f"G8-PERIOD: {chart} 沿用较早期间但未解释披露边界")
        if chart == "图03":
            labels = ops.get("segment", {}).get("labels", [])
            year = end[:4]
            if not any(year in str(lab) for lab in labels):
                failures.append("G8-PERIOD: 图03 虽有期间声明但实际分部图未包含该期")
            if review.get("basis") == "H1" and not any(year in str(lab) and re.search(r"H1|半年", str(lab), re.I) and not re.search(r"\dE|预测", str(lab)) for lab in labels):
                failures.append("G8-PERIOD: 图03 半年实际必须在图内明确H1/半年，不能冒充全年或预测")
            if review.get("basis") not in ("FY", "H1", "YTD"):
                failures.append("G8-PERIOD: 图03 必须区分全年/半年/累计口径")
        if chart == "图06":
            peers = ops.get("peers", [])
            if not peers or any(p.get("报告期") != end for p in peers):
                failures.append("G8-PERIOD: 图06 同行必须采用统一实际财务报告期")
        if chart == "图07" and not review.get("current_fiscal_year_status"):
            failures.append("G8-PERIOD: 图07 缺少本财年方案是否披露的说明")
        if end != latest:
            warnings.append(f"G8-PERIOD: {chart} 最新可比期 {end}；{review.get('reason')}")
    return warnings, failures

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--inputs-only", action="store_true", help="仅检查输入期间；用于构图前预检")
    args = ap.parse_args()
    project = Path(args.dir)
    warnings, failures = check_period_inputs(project) if args.inputs_only else check_chart_periods(project)
    result = {"status": "FAIL" if failures else "PASS", "warnings": warnings, "failures": failures}
    (project / "reports").mkdir(parents=True, exist_ok=True)
    output = "图表期间输入预检.json" if args.inputs_only else "图表最新期审核.json"
    (project / "reports" / output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for warning in warnings:
        print(f"[WARN] {warning}")
    for failure in failures:
        print(f"[FAIL] {failure}")
    print(f"G8-PERIOD: {result['status']}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
