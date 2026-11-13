# -*- coding: utf-8 -*-
"""chart_qc.py —— 图表质量门（company-research skill，G8/G8-SENS/G8-INDUSTRY 门控脚本）

修复背景（2026-08-14）：长虹华意/京沪高铁等项目中反复出现
  - 图号与章节映射错乱（如分红支付率图被丢进附录）
  - 多量纲序列共用单轴导致数量级压平（营收~百亿 vs 归母净利~数亿）
  - Markdown 表格结构损坏（口径注混入表格行、分隔线错位）
  - HTML 渲染后仍残留相对路径图片引用
本脚本把上述检查固化为可复算门控，成稿前必须运行。

图号映射（2026-08-17）：图16=行业成本与价格走势（§2 行业分析/宏观与行业），
图17=复验偏差图（台账，基线建立时跳过）——与 SKILL.md §B4.3 一致。
G8-INDUSTRY：行业适用标的（data/行业成本价格.csv 存在，或
input/行业成本价格配置.json required=true）必须通过
fetch_industry_cost_price.py 的 CSV 契约审计，且有 cost+price 双序列、
≥2 个来源与图16 嵌入——防止“宏观与行业”章节只有文字没有图表。

用法：
    python scripts/chart_qc.py --dir <项目目录> --report reports/<报告>.md [--html reports/<报告>.html]
    # 校验：图号→章节映射 / PNG 存在且被引用 / HTML 无残留 / Markdown 表格结构

    python scripts/chart_qc.py --dir <项目目录> --list-png
    # 列出 reports/图表/*.png 与图号映射（快速盘点）

退出码：0=全部通过；1=存在 FAIL 项（门控不通过）。
"""
from __future__ import annotations

import time
import argparse
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

# ─── B4.3 固定图号→章节映射（与 SKILL.md §B4.3 / framework.md D1 保持一致，禁止自创编号） ───
FIG_MAP = {
    1:  (4, "营收与归母净利"),
    2:  (4, "ROE与每股净资产"),
    3:  (3, "分部营收构成与增速"),
    4:  (4, "盈利能力趋势"),
    5:  (4, "现金流结构"),
    6:  (6, "同行估值与增长对比"),
    7:  (4, "DPS与支付率"),
    8:  (6, "股价历史位置与关键价格锚"),
    9:  (7, "多框架目标价对比"),
    10: (6, "穿透回报率GG vs 门槛II"),
    11: (6, "穿透回报率敏感性"),
    12: (5, "盈利预测：历史与三情景"),
    13: (6, "PE_TTM估值带"),
    14: (6, "PB估值带"),
    15: (4, "杠杆与负债结构"),
    16: (2, "行业成本与价格走势"),
    17: (None, "复验偏差图（台账，基线建立时跳过）"),
    18: (6, "分部估值SOTP（平台型公司强制）"),
    19: (4, "Capex规划、在建转固与股价联动（启用Capex引擎时生成）"),
    20: (4, "重大在建工程转固时间轴（启用Capex引擎且含在建清单时生成）"),
    21: (6, "提高分红率财务可行性与造血留存（启用Capex引擎时生成）"),
}

# 章节标题→章节号（用于定位图引用所在章节）
_SECTION_KEYS = [
    ("投资摘要", 1), ("行业分析", 2), ("宏观与行业", 2), ("公司分析", 3), ("财务分析", 4),
    ("盈利预测", 5), ("估值", 6), ("投资建议", 7), ("催化剂", 8),
    ("风险", 9), ("附录", 10),
]

# 图号→建议章节号（按 B4.3）；章节号 None 表示不校验（图16 台账）
FIG_SECTION = {k: v[0] for k, v in FIG_MAP.items()}


def _capex_trigger_status(project: Path) -> tuple[bool, bool]:
    """返回 (enabled, has_projects)：仅当 input/capex_dividend_plan.json 存在且 enabled!=false 时触发图19-21。"""
    p = project / "input" / "capex_dividend_plan.json"
    if not p.is_file():
        return False, False
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return True, False
    if not isinstance(data, dict) or data.get("enabled") is False:
        return False, False
    projs = data.get("capex_plan", {}).get("key_projects", [])
    return True, bool(isinstance(projs, list) and len(projs) > 0)


def _chart_exemptions(project: Path) -> set[str]:
    """Only explicit, nonempty reasons exempt missing charts; supplied data is checked."""
    path = project / "input/图表豁免.json"
    if not path.exists():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    entries = payload.get("豁免") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise ValueError("图表豁免必须为列表")
    found = set()
    for entry in entries:
        if (not isinstance(entry, dict) or not isinstance(entry.get("原因"), str)
                or not entry["原因"].strip() or not isinstance(entry.get("图"), str)):
            raise ValueError("每项图表豁免须有原因")
        label = str(entry.get("图", "")).split("_")[0]
        if label not in {f"图{i:02d}" for i in FIG_MAP}:
            raise ValueError(f"未知图号：{label}")
        found.add(label)
    return found


def _section_no_of(heading: str) -> int | None:
    for key, no in _SECTION_KEYS:
        if key in heading:
            return no
    return None


def _embedding_section(md_lines: list[str], embed_idx: int) -> int | None:
    """图引用行之前最近的章节标题（跳过表格行与图表清单）。"""
    for j in range(embed_idx - 1, -1, -1):
        line = md_lines[j].strip()
        if line.startswith("|"):
            continue
        m = re.match(r"^#{2,4}\s+(.+)$", line)
        if m:
            return _section_no_of(m.group(1))
    return None


def _split_cells(line: str) -> list[str]:
    """按 | 拆列，跳过反斜杠转义的管道符（GFM 合法转义，防止误拆）。"""
    parts, buf, esc = [], [], False
    for ch in line.strip().strip("|"):
        if ch == "\\" and not esc:
            esc = True
            continue
        if ch == "|" and not esc:
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
        esc = False
    if buf:
        parts.append("".join(buf).strip())
    return parts


def check_listing_vs_embed(md_lines: list[str], project: Path | None = None) -> list[str]:
    """附录图表清单（| 图NN | 内容 | 位置 |）标注的章节 vs 实际嵌入章节必须一致。"""
    issues = []
    project = Path(project) if project is not None else Path(__file__).resolve().parents[1]
    _exempt = set()
    try:
        _exempt = _chart_exemptions(project)
    except (OSError, ValueError):
        issues.append("input/图表豁免.json 无效")
    # SOTP is optional when platform detection is disabled. Treat an appendix
    # row for the skipped Figure 18 as non-embeddable, matching the main gate.
    try:
        _sotp = project / "input" / "sotp_触发.json"
        if _sotp.exists() and json.loads(_sotp.read_text(encoding="utf-8-sig")).get("enabled") is False:
            _exempt.add("图18")
    except Exception:
        pass
    _capex_on, _capex_tl = _capex_trigger_status(project)
    if not _capex_on:
        _exempt.update({"图19", "图20", "图21"})
    elif not _capex_tl:
        _exempt.add("图20")
    listing = {}
    for i, line in enumerate(md_lines):
        m = re.match(r"^\|\s*图(\d{2})\s*\|([^|]*)\|\s*(\S+)\s*\|", line.strip())
        if m:
            no = int(m.group(1))
            if no not in listing:
                listing[no] = (i, m.group(3).strip())
    for no, (lst_idx, where) in listing.items():
        if f"图{no:02d}" in _exempt:
            continue
        # 找到实际嵌入行
        embeds = [j for j, l in enumerate(md_lines)
                  if re.match(rf"^!\[图{no:02d}", l.strip()) and not l.strip().startswith("|")]
        if not embeds:
            issues.append(f"图{no:02d} 清单标注 {where}，但正文未嵌入")
            continue
        got = _embedding_section(md_lines, embeds[0])
        want_no = None
        for key, sec_no in _SECTION_KEYS:
            if where in ("§" + str(sec_no), str(sec_no), f"{sec_no}", f"§{sec_no}.", "附录"):
                want_no = 10 if where.startswith("附录") else sec_no
                break
        if want_no is not None and got is not None and got != want_no:
            issues.append(
                f"图{no:02d} 清单标注 {where}，实际嵌入 §{got}（清单与实际不一致）")
    return issues


def check_markdown_tables(md_lines: list[str]) -> list[str]:
    """校验 Markdown 表格：表头后必须有分隔行；每行单元格数一致。"""
    issues = []
    for i, line in enumerate(md_lines):
        if not line.strip().startswith("|"):
            continue
        cells = _split_cells(line)
        n = len(cells)
        # 分隔行：/^\|?[\s:|-]+\|?$/ 且含至少一个 -
        is_sep = bool(re.match(r"^\|?[\s:\-|]+\|?$", line.strip())) and "-" in line
        if is_sep:
            continue
        # 表头行：上一行是空行/非表格行，下一行必须是分隔行
        if i + 1 < len(md_lines) and re.match(r"^\|?[\s:\-|]+\|?$", md_lines[i + 1].strip()) and "-" in md_lines[i + 1]:
            continue  # 表头行（下行为分隔行）
        # 数据行：与最近分隔行的列数比较
        for j in range(i - 1, max(i - 5, -1), -1):
            prev = md_lines[j].strip()
            if re.match(r"^\|?[\s:\-|]+\|?$", prev) and "-" in prev:
                pn = len(_split_cells(prev))
                if n != pn:
                    issues.append(f"L{i+1}: 表格行单元格数 {n} != 分隔行 {pn}（表格结构损坏）")
                break
    return issues



def _find_json_by_keys(project: Path, required: set[str]) -> dict | None:
    """Find an input JSON containing all required keys.

    The operational supplement is the primary chart input. Prefer it when
    several input files expose the same contract, while still allowing model
    assumptions to provide contracts absent from the chart input.
    """
    input_dir = project / "input"
    if not input_dir.exists():
        return None
    preferred = input_dir / "运营补充数据.json"
    candidates = ([preferred] if preferred.exists() else []) + [
        p for p in sorted(input_dir.glob("*.json")) if p != preferred
    ]
    for p in candidates:
        try:
            obj = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if isinstance(obj, dict) and required.issubset(obj.keys()):
            return obj
    return None


def _derived_sensitivity(project: Path) -> dict | None:
    """Reconstruct the default Figure 11 series from calculator output."""
    path = project / "reports" / "穿透回报率_输出.json"
    try:
        output = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    rows = output.get("single_year")
    if not isinstance(rows, list):
        return None
    points = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            x = float(row["k"])
            y = float(row["gg"]) * 100.0
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(x) and math.isfinite(y):
            points.append((x, y))
    if not points or output.get("II") is None:
        return None
    return {
        "mode": "script_cash_surplus",
        "x": [x for x, _ in points],
        "系列": [{"name": "GG · 单年下滑情景", "y": [y for _, y in points]}],
        "门槛": float(output["II"]) * 100.0,
    }


def check_sensitivity_contract(project: Path, report_text: str) -> tuple[list[str], list[str]]:
    """G8-SENS: validate Figure 11 data, axis semantics, and flat-line disclosure."""
    warnings, failures = [], []
    fig11 = chr(22270) + "11"
    chart_dir_name = chr(22270) + chr(34920)
    series_key = chr(31995) + chr(21015)
    threshold_key = chr(38376) + chr(27099)
    manual_marker = chr(25163) + chr(31639) + "/" + chr(34917) + chr(20805)
    report_pattern = r"!\[" + re.escape(fig11) + r"[^\]]*\]\(" + re.escape(chart_dir_name) + r"/[^)]+\.png\)"
    if not re.search(report_pattern, report_text):
        return warnings, failures

    ops = _find_json_by_keys(project, {"sensitivity"})
    sensitivity = ops.get("sensitivity") if ops is not None else None
    if sensitivity is None:
        sensitivity = _derived_sensitivity(project)
        if sensitivity is not None:
            warnings.append("G8-SENS: Figure 11 sensitivity was reconstructed from 穿透回报率_输出.json")
    if sensitivity is None:
        failures.append("G8-SENS: Figure 11 is embedded but input JSON has no sensitivity data")
        return warnings, failures
    if not isinstance(sensitivity, dict):
        failures.append("G8-SENS: sensitivity must be an object")
        return warnings, failures

    x = sensitivity.get("x")
    series = sensitivity.get(series_key) or sensitivity.get("series")
    if not isinstance(x, list) or not x:
        failures.append("G8-SENS: Figure 11 has no non-empty x scenario sequence")
        return warnings, failures
    if not isinstance(series, list) or not series:
        failures.append("G8-SENS: Figure 11 has no non-empty series")
        return warnings, failures

    def numeric_list(values) -> bool:
        return all(isinstance(v, (int, float)) and math.isfinite(float(v)) for v in values)

    if not numeric_list(x):
        failures.append("G8-SENS: x contains non-numeric or NaN/Inf values")
    x_span = max(map(float, x)) - min(map(float, x)) if numeric_list(x) else 0.0
    sensitivity_disclosure = " ".join(str(v) for v in (
        sensitivity.get("注", ""), sensitivity.get("note", "")))
    # A decimal such as λ=0.0117 is not a disclosure of zero exposure.
    zero_lambda_pattern = r"(?:lambda|λ)\s*=\s*[+-]?0(?:\.0*)?(?![\d.])"
    for idx, item in enumerate(series):
        if not isinstance(item, dict) or not isinstance(item.get("y"), list):
            failures.append(f"G8-SENS: series {idx + 1} has no y sequence")
            continue
        y = item["y"]
        if len(y) != len(x):
            failures.append(f"G8-SENS: series {idx + 1} x/y length mismatch ({len(x)} vs {len(y)})")
            continue
        if not numeric_list(y):
            failures.append(f"G8-SENS: series {idx + 1} contains non-numeric or NaN/Inf values")
            continue
        y_span = max(map(float, y)) - min(map(float, y))
        mode = str(sensitivity.get("mode", "")).lower()
        disclosure = " ".join(str(v) for v in (item.get("name", ""), sensitivity_disclosure))
        explicit_manual = (
            mode in {"manual_cash_surplus", "manual", "not_applicable"}
            or re.search(zero_lambda_pattern, disclosure, re.I)
            or re.search(r"未建模|未映射|水平线|平线|手算|手工|补充|降级", disclosure, re.I)
        )
        if x_span > 1e-9 and y_span <= 1e-9:
            if not explicit_manual:
                failures.append(
                    f"G8-SENS: series {idx + 1} is flat while x varies (x_span={x_span:g}); "
                    "fix the calculation or disclose lambda=0/unmodeled/manual supplemental semantics"
                )
            else:
                warnings.append(f"G8-SENS: series {idx + 1} is flat while x varies, but the input declares a degraded/unmodeled supplemental mode")

    model = _find_json_by_keys(project, {"lambda"})
    xlabel = str(sensitivity.get("xlabel", "")).lower()
    mode = str(sensitivity.get("mode", "")).lower()
    # Match an actual revenue-factor axis, not a disclosure such as
    # "不代表收入弹性" in an otherwise valid pressure-factor label.
    revenue_axis = bool(re.search(
        r"(?:收入\s*(?:倍数|情景|系数)|revenue\s*(?:multiple|scenario|factor)|income\s*(?:multiple|scenario|factor))",
        xlabel, re.I,
    ))
    lambda_zero = False
    if model is not None:
        try:
            lambda_zero = float(model.get("lambda", 0) or 0) == 0
        except (TypeError, ValueError):
            pass
    lambda_zero = lambda_zero or bool(re.search(zero_lambda_pattern, sensitivity_disclosure, re.I))
    if lambda_zero:
        if revenue_axis and mode not in {"manual_cash_surplus", "manual", "not_applicable"}:
            failures.append("G8-SENS: lambda=0 but Figure 11 is still labelled as a revenue multiple")
        if mode in {"manual_cash_surplus", "manual"}:
            if manual_marker not in report_text and "manual" not in report_text.lower():
                failures.append("G8-SENS: manual sensitivity mode is not disclosed in the report")

    threshold = sensitivity.get(threshold_key)
    if threshold is None or not isinstance(threshold, (int, float)) or not math.isfinite(float(threshold)):
        failures.append("G8-SENS: Figure 11 has no valid threshold line")

    # The chart input is intentionally editable for custom views, but modes
    # that claim to be script-backed must stay numerically tied to the
    # deterministic calculator output. Manual modes remain allowed and receive
    # a warning when their copied values drift.
    output_path = project / "reports" / "穿透回报率_输出.json"
    try:
        output = json.loads(output_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        output = None
    mode = str(sensitivity.get("mode", "")).lower()
    if isinstance(output, dict) and mode in {"script_cash_surplus", "cash_surplus", "manual_cash_surplus", "manual", "g_grid", "capex_g"}:
        if mode in {"script_cash_surplus", "cash_surplus", "manual_cash_surplus", "manual"}:
            rows = output.get("single_year")
            x_key, y_key = "k", "gg"
        else:
            rows = output.get("g_grid")
            x_key, y_key = "G", "oe_yield"
        expected = {}
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    try:
                        expected[round(float(row[x_key]), 8)] = float(row[y_key]) * 100.0
                    except (KeyError, TypeError, ValueError):
                        continue
        mismatches = []
        for index, item in enumerate(series or []):
            if not isinstance(item, dict):
                continue
            ys = item.get("y") or []
            for xi, yi in zip(x, ys):
                try:
                    exp = expected.get(round(float(xi), 8))
                    actual = float(yi)
                except (TypeError, ValueError):
                    continue
                if exp is None or abs(actual - exp) > max(0.02, abs(exp) * 0.001):
                    mismatches.append(f"series {index + 1} x={xi:g}: chart={actual:g}, script={exp if exp is not None else 'missing'}")
        if threshold is not None and output.get("II") is not None:
            expected_threshold = float(output["II"]) * 100.0
            if abs(float(threshold) - expected_threshold) > 0.02:
                mismatches.append(f"threshold: chart={float(threshold):g}, script={expected_threshold:g}")
        if mismatches:
            detail = "；".join(mismatches[:3])
            message = f"G8-SENS: 图11与穿透回报率脚本输出不一致（{detail}）"
            if mode in {"script_cash_surplus", "cash_surplus", "g_grid", "capex_g"}:
                failures.append(message)
            else:
                warnings.append(message)
    return warnings, failures


def check_industry_contract(project: Path, report_text: str) -> tuple[list[str], list[str]]:
    """G8-INDUSTRY：行业适用标的必须有成本线、价格线和可追溯来源。

    激活条件：data/行业成本价格.csv 存在，或 input/行业成本价格配置.json
    required=true（fetch_industry_cost_price.py 生成）；两者都没有则跳过。
    """
    warnings, failures = [], []
    data_path = project / "data" / "行业成本价格.csv"
    config_path = project / "input" / "行业成本价格配置.json"
    config_required = False
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            failures.append(f"G8-INDUSTRY: invalid config: {exc}")
            return warnings, failures
        config_required = bool(config.get("required", True))
    if not config_required and not data_path.exists():
        return warnings, failures
    if not data_path.exists():
        failures.append("G8-INDUSTRY: required data/行业成本价格.csv is missing")
        return warnings, failures
    audit_path = project / "data" / "行业成本价格_审计.json"
    if audit_path.exists():
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            if audit.get("status") == "fail":
                failures.append("G8-INDUSTRY: 行业成本价格_审计.json status=fail")
        except Exception:
            warnings.append("G8-INDUSTRY: cannot read 行业成本价格_审计.json")
    else:
        warnings.append("G8-INDUSTRY: 行业成本价格_审计.json 缺失（应先运行 fetch_industry_cost_price.py --dir . --profile <行业>）")
    try:
        import csv
        with data_path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except Exception as exc:
        failures.append(f"G8-INDUSTRY: cannot read industry CSV: {exc}")
        return warnings, failures
    required_cols = {"date", "series", "value", "unit", "role", "source", "source_date"}
    if not rows or not required_cols.issubset(rows[0]):
        failures.append("G8-INDUSTRY: CSV schema missing required columns")
        return warnings, failures
    roles = {str(r.get("role", "")).strip() for r in rows}
    for role in ("cost", "price"):
        if role not in roles:
            failures.append(f"G8-INDUSTRY: missing required role={role}")
    groups = {}
    sources = set()
    for r in rows:
        try:
            value = float(r.get("value", ""))
            if not math.isfinite(value) or value <= 0:
                failures.append("G8-INDUSTRY: value must be finite and positive")
        except Exception:
            failures.append("G8-INDUSTRY: value is not numeric")
        key = (r.get("series", ""), r.get("date", ""))
        groups[key] = groups.get(key, 0) + 1
        if r.get("source", "").strip():
            sources.add(r["source"].strip())
        if not r.get("source_date", "").strip():
            failures.append("G8-INDUSTRY: source_date is required")
    if any(v > 1 for v in groups.values()):
        failures.append("G8-INDUSTRY: duplicate series/date rows")
    for series in sorted({r.get("series", "") for r in rows}):
        if sum(1 for r in rows if r.get("series", "") == series) < 3:
            failures.append(f"G8-INDUSTRY: series too short: {series}")
    if len(sources) < 2:
        warnings.append("G8-INDUSTRY: fewer than two named data producers; core trend evidence is L3")
    if "成本" not in report_text or "价格" not in report_text:
        failures.append("G8-INDUSTRY: report must interpret cost-price transmission")
    if not re.search(r"!\[图16[^\]]*\]\(图表/图16_[^)]+\.png\)", report_text):
        failures.append("G8-INDUSTRY: report does not embed Figure 16")
    rw, rf = _check_fig16_render(project)
    warnings.extend(rw); failures.extend(rf)
    return warnings, failures


def _check_fig16_render(project: Path) -> tuple[list[str], list[str]]:
    """G8-INDUSTRY 渲染级检查（图16 v3）：无 NaN 断点、双轴+供需面板结构、刻度不重叠。

    2026-08-17 新增（伊利反馈）：①数据断点——跨序列日期错位会在共享 x 上产生
    NaN 断线，任何序列线/柱含 NaN 即 FAIL；②底部横坐标文字重合——渲染后检测
    x 刻度标签窗口重叠，重叠即 FAIL，刻度过多（>14）给 WARN；③v2 结构——
    volume 供需面板柱状图与价格/价差右轴必须存在。
    """
    warnings, failures = [], []
    csv_path = project / "data" / "行业成本价格.csv"
    script = project / "scripts" / "analyze_charts.py"
    if not csv_path.exists() or not script.exists():
        return warnings, failures
    try:
        import importlib.util
        import numpy as np
        import matplotlib.pyplot as plt
        spec = importlib.util.spec_from_file_location("_proj_analyze_charts", script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        d = mod.load_industry_cost_price(project / "data")
        if not d:
            warnings.append("G8-INDUSTRY: 图16 渲染级检查无法加载行业数据，跳过断点/刻度检查")
            return warnings, failures
        fig = mod.fig_industry_cost_price({}, project / "data")
        if fig is None:
            failures.append("G8-INDUSTRY: fig_industry_cost_price 返回 None（图16 无法生成，检查 CSV 契约）")
            return warnings, failures
        # 1) 断点检查：任何线/柱含 NaN → FAIL
        for ax in fig.axes:
            for ln in ax.lines:
                xd, yd = ln.get_xdata(), ln.get_ydata()
                if np.isnan(xd).any() or np.isnan(yd).any():
                    failures.append(f"G8-INDUSTRY: 图16 数据断点（NaN）：{ln.get_label()}")
            for cont in getattr(ax, "containers", []):
                for bar in cont:
                    if np.isnan(bar.get_height()):
                        failures.append("G8-INDUSTRY: 图16 供需面板存在 NaN 柱（数据断点）")
        # 2) v2 结构：供需面板（含柱状容器）+ 价格/价差右轴
        roles = [s.get("role", "") for s in d["series"]]
        if "volume" in roles:
            volume_ax = next((ax for ax in fig.axes if getattr(ax, "containers", [])), None)
            if volume_ax is None:
                failures.append("G8-INDUSTRY: 图16 缺少供需（volume）面板柱状图")
        ylabs = {ax.get_ylabel() for ax in fig.axes}
        if not any(("价格" in y or "价差" in y) for y in ylabs):
            failures.append("G8-INDUSTRY: 图16 缺少价格/价差右轴（须成本/价格原始值双轴）")
        # 3) 横坐标刻度重合检查
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        visible = [lb for ax in fig.axes for lb in ax.get_xticklabels()
                   if lb.get_visible() and lb.get_text().strip()]
        prev_ext = None
        for lb in visible:
            ext = lb.get_window_extent(renderer)
            if prev_ext is not None and ext.x0 < prev_ext.x1 - 0.5:
                failures.append(f"G8-INDUSTRY: 图16 底部横坐标刻度文字重合（{lb.get_text()}），须稀疏刻度")
                break
            prev_ext = ext
        if len(visible) > 14:
            warnings.append(f"G8-INDUSTRY: 图16 横坐标刻度过多（{len(visible)} 个），存在重合风险")
        plt.close(fig)
    except Exception as exc:
        warnings.append(f"G8-INDUSTRY: 图16 渲染级检查异常（{exc}），需人工复核断点与刻度重合")
    return warnings, failures

def _load_ops(path: Path) -> dict:
    """Read a bounded JSON object before inspecting chart-specific structures."""
    limit = 10 * 1024 * 1024
    if path.stat().st_size > limit:
        raise ValueError("运营输入超过 10 MiB 上限")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("运营输入超过 10 MiB 上限")
    ops = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(ops, dict):
        raise ValueError("运营输入顶层必须是对象")
    return ops


def _ops_shape_errors(ops: dict) -> list[str]:
    """Reject malformed containers so QC reports a failure without a traceback."""
    errors = []
    sections = {
        "segment": ("labels", "series"),
        "forecast": ("labels_hist", "labels_fcast", "np_hist", "悲观", "基准", "乐观"),
        "sensitivity": ("x", "系列"),
        "pe_band": ("labels", "pe_high", "pe_low", "pe_ttm", "pe_mean"),
        "pb_band": ("labels", "pb_high", "pb_low", "pb"),
        "cashflow": ("labels", "OCF", "Capex", "FCF"),
        "profitability": ("labels", "毛利率", "净利率", "ROE"),
        "dps": ("labels", "dps", "支付率"),
        "leverage": ("labels", "资产负债率", "有息负债率", "净现金"),
        "targets": ("labels", "values"),
        "penetration": ("labels", "gg"),
    }
    for key, arrays in sections.items():
        value = ops.get(key)
        if value is None:
            continue
        if not isinstance(value, dict):
            errors.append(f"{key} 必须是对象")
            continue
        for field in arrays:
            if value.get(field) is not None and not isinstance(value[field], list):
                errors.append(f"{key}.{field} 必须是列表")
    for key, series_key, values_key in (("segment", "series", "values"), ("sensitivity", "系列", "y")):
        section = ops.get(key)
        if not isinstance(section, dict):
            continue
        series = section.get(series_key)
        if isinstance(series, list):
            for index, row in enumerate(series):
                if not isinstance(row, dict):
                    errors.append(f"{key}.{series_key}[{index}] 必须是对象")
                elif row.get(values_key) is not None and not isinstance(row[values_key], list):
                    errors.append(f"{key}.{series_key}[{index}].{values_key} 必须是列表")
        if key == "segment" and section.get("增速") is not None:
            growth = section["增速"]
            if not isinstance(growth, dict):
                errors.append("segment.增速 必须是对象")
            elif growth.get("合计增速") is not None and not isinstance(growth["合计增速"], list):
                errors.append("segment.增速.合计增速 必须是列表")
    return errors


def check_ops_contract(project: Path) -> tuple[list[str], list[str]]:
    """G8-OPS: 运营图表数据契约检查（2026-08-18 新增，牧原批次反馈）。

    防五类静默失败：①ops 键名与模板期望不符导致数据被丢弃；②图数据序列长度与
    labels 不一致；③杠杆比率/单位/缺失值语义错误；④敏感性图出现未解释的水平线；
    ⑤同行图在亏损期 PE 全部缺失导致空子图。缺失数据只有在明确披露口径时才允许
    继续，否则 FAIL。
    """
    warnings, failures = [], []
    try:
        exempt = _chart_exemptions(project)
    except (OSError, ValueError):
        exempt = set()
        failures.append("G8-OPS: 图表豁免配置无效")
    for fname in ("input/运营补充数据.json", "input/模型假设.json"):
        ops_path = project / fname
        if not ops_path.exists():
            continue
        try:
            ops = _load_ops(ops_path)
        except Exception as exc:
            failures.append(f"G8-OPS: 读取 {fname} 失败: {exc}")
            continue
        shape_errors = _ops_shape_errors(ops)
        if shape_errors:
            failures.extend(f"G8-OPS: {fname}: {error}" for error in shape_errors)
            continue
        lev = ops.get("leverage")
        if lev:
            for k in ("资产负债率", "净现金"):
                if k not in lev:
                    failures.append(f"G8-OPS: leverage 缺少模板必需键 {k}——图15 无法形成完整杠杆/净现金图")
            if "有息负债" in lev and "有息负债率" not in lev:
                failures.append("G8-OPS: leverage 含'有息负债'但缺'有息负债率'——请提供有息负债/总资产比率，禁止把金额误当比率")
            for ratio_key in ("资产负债率", "有息负债率"):
                seq = lev.get(ratio_key)
                if seq is None:
                    continue
                if not isinstance(seq, list):
                    failures.append(f"G8-OPS: leverage.{ratio_key} 必须是列表（单位为百分比）")
                    continue
                finite = []
                for idx, value in enumerate(seq):
                    if value is None:
                        continue
                    try:
                        value = float(value)
                    except (TypeError, ValueError):
                        failures.append(f"G8-OPS: leverage.{ratio_key}[{idx}] 不是数值")
                        continue
                    if not math.isfinite(value):
                        failures.append(f"G8-OPS: leverage.{ratio_key}[{idx}] 为 NaN/Inf")
                    elif value < 0 or value > 100:
                        failures.append(f"G8-OPS: leverage.{ratio_key}[{idx}]={value:g}% 超出 0-100% 合理范围——疑似金额/现金分母口径错误")
                    else:
                        finite.append(value)
                if not finite:
                    warnings.append(f"G8-OPS: leverage.{ratio_key} 无有效比率值——对应曲线为空")
            cash_seq = lev.get("净现金")
            if isinstance(cash_seq, list) and any(v is None for v in cash_seq):
                disclosure = " ".join(str(lev.get(k, "")) for k in ("注", "净现金注"))
                if not re.search(r"缺失|未披露|不可得|不完整|NA|None", disclosure, re.I):
                    failures.append("G8-OPS: leverage.净现金含缺失值但没有在注释中披露——禁止静默补零或绘制为负值")
            if "净现金单位" not in lev:
                warnings.append("G8-OPS: leverage 缺少净现金单位（建议显式提供‘亿元RMB’等单位，防止百万元/亿元错标）")
        # The operational supplement is the main chart input and must carry
        # peers. A model-assumption file may omit peers unless it declares them.
        peers = ops.get("peers")
        should_check_peers = fname == "input/运营补充数据.json" or "peers" in ops
        if "图06" in exempt and (peers is None or peers == []):
            should_check_peers = False
        if should_check_peers and (not isinstance(peers, list) or not peers):
            failures.append("G8-OPS: peers 缺失或为空——图06 同行估值与增长对比没有可审计数据")
        elif should_check_peers and any(not isinstance(row, dict) for row in peers):
            failures.append("G8-OPS: peers 每行必须为对象")
        elif should_check_peers:
            # 图06 必须显式声明且仅声明一个标的公司；不能依赖名称猜测或旧版“高亮”字段。
            targets = [p for p in peers if p.get("标的") is True or p.get("target") is True]
            if len(targets) == 0:
                failures.append("G8-OPS: peers 缺少唯一标的标记（请在目标公司行设置 标的=true；禁止用高亮字段代替）")
            elif len(targets) > 1:
                failures.append(f"G8-OPS: peers 标的标记数量为 {len(targets)}，必须恰好 1 个")
            else:
                target = targets[0]
                missing = [k for k in ("公司", "PB", "ROE", "营收增速", "净利增速")
                           if target.get(k) is None]
                if missing:
                    failures.append(f"G8-OPS: 图06 标的公司 {target.get('公司', '?')} 缺少字段 {','.join(missing)}——疑似目标公司数据缺失")
                elif target.get("PE") is None:
                    warnings.append(f"G8-OPS: 图06 标的公司 {target.get('公司', '?')} PE 无定义，将使用 PB vs ROE；请在报告说明盈利口径")
                declared = ops.get("target")
                if isinstance(declared, dict):
                    for k in ("公司", "代码"):
                        if declared.get(k) and target.get(k) and str(declared[k]) != str(target[k]):
                            failures.append(f"G8-OPS: 顶层 target.{k}={declared[k]} 与 peers 标的行 {target.get(k)} 不一致")
            # 同行行不能重复同一公司，避免目标公司被追加后仍有旧行覆盖/错标。
            names = [str(p.get("公司", "")).strip() for p in peers]
            dup_names = sorted({n for n in names if n and names.count(n) > 1})
            if dup_names:
                failures.append(f"G8-OPS: peers 存在重复公司行 {','.join(dup_names)}——请保留一行并明确标的身份")
            pe_pos = [p.get("PE") for p in peers if isinstance(p.get("PE"), (int, float)) and p.get("PE", 0) > 0]
            has_pb = any(p.get("PB") is not None for p in peers)
            if len(pe_pos) < 3:
                if not has_pb:
                    failures.append("G8-OPS: peers 全部 PE 缺失/<=0 且未提供 PB——图06 左面板将为空子图（请在 ops 补 PB 或改口径并在报告说明）")
                else:
                    warnings.append("G8-OPS: peers 亏损期 PE 失真且已提供 PB——确认图06 左面板降级为 PB vs ROE 并在报告中说明")
            # 增速面板（图06 右面板）完整性：<2 点判 FAIL（近空图），2 点 WARN（对比意义有限）
            growth_pts = [p for p in peers
                          if isinstance(p.get("营收增速"), (int, float)) and isinstance(p.get("净利增速"), (int, float))]
            if len(growth_pts) < 2:
                failures.append(f"G8-OPS: peers 增速面板数据点 {len(growth_pts)}<2——图06 右面板（营收增速 vs 净利增速）将近空；请运行更新后的 fetch_peers_financials.py（F10 已输出营收增速%/净利增速%）重拉同行，或在 ops 手工补齐")
            elif len(growth_pts) < 3:
                warnings.append(f"G8-OPS: peers 增速面板仅 {len(growth_pts)} 个数据点（<3）——图06 右面板对比意义有限，请在报告中说明")
        seg = ops.get("segment")
        if seg:
            labels = seg.get("labels") or []
            for s in seg.get("series") or []:
                if len(s.get("values") or []) != len(labels):
                    warnings.append(f"G8-OPS: segment 系列 {s.get('name')} 长度 {len(s.get('values') or [])} != labels {len(labels)}")
            g = (seg.get("增速") or {}).get("合计增速")
            if g and len(g) != len(labels):
                warnings.append(f"G8-OPS: segment 合计增速长度 {len(g)} != labels {len(labels)}")
        # 通用图契约：label 键 + 数值键 长度/有限值检查（数值序列全空 → 空子图）
        for key, label_key, num_keys in [
            ("pe_band", "labels", ["pe_high", "pe_low", "pe_ttm", "pe_mean"]),
            ("pb_band", "labels", ["pb_high", "pb_low", "pb"]),
            ("cashflow", "labels", ["OCF", "Capex", "FCF"]),
            ("profitability", "labels", ["毛利率", "净利率", "ROE"]),
            ("dps", "labels", ["dps", "支付率"]),
            ("leverage", "labels", ["资产负债率", "净现金"]),
            ("targets", "labels", ["values"]),
            ("penetration", "labels", ["gg"]),
        ]:
            d = ops.get(key)
            if not d:
                continue
            lab = d.get(label_key) or []
            for k in num_keys:
                if k not in d:
                    continue
                seq = d[k]
                if isinstance(seq, list):
                    if len(seq) != len(lab):
                        warnings.append(f"G8-OPS: {key}.{k} 长度 {len(seq)} != {label_key} {len(lab)}")
                    if seq:
                        vals = []
                        for v in seq:
                            try:
                                if v is not None and math.isfinite(float(v)):
                                    vals.append(float(v))
                            except (TypeError, ValueError):
                                continue
                        if not vals:
                            warnings.append(f"G8-OPS: {key}.{k} 全为空值/NaN——对应图将空子图或失真")
        fc = ops.get("forecast")
        if fc:
            lh = fc.get("labels_hist") or []
            lf = fc.get("labels_fcast") or []
            if len(fc.get("np_hist") or []) != len(lh):
                warnings.append(f"G8-OPS: forecast.np_hist 长度 {len(fc.get('np_hist') or [])} != labels_hist {len(lh)}")
            for k in ("悲观", "基准", "乐观"):
                if k in fc:
                    if len(fc[k] or []) != len(lf):
                        warnings.append(f"G8-OPS: forecast.{k} 长度 {len(fc[k] or [])} != labels_fcast {len(lf)}")
                    if fc[k]:
                        vals = [v for v in fc[k] if isinstance(v, (int, float)) and str(v) not in ("nan", "None")]
                        if not vals:
                            warnings.append(f"G8-OPS: forecast.{k} 全为空值/NaN——图12 空子图")
        sens = ops.get("sensitivity")
        if sens:
            x = sens.get("x") or []
            x_values = []
            for value in x:
                try:
                    if math.isfinite(float(value)):
                        x_values.append(float(value))
                except (TypeError, ValueError):
                    continue
            if len(x_values) < 2 or len(set(x_values)) < 2:
                failures.append("G8-SENS: 图11 x 轴必须至少有两个不同的有限数值")
            for ser in sens.get("系列") or []:
                y = ser.get("y") or []
                if len(y) != len(x):
                    failures.append(f"G8-OPS: sensitivity 系列 {ser.get('name')} 长度 {len(y)} != x {len(x)}——图11 将断裂或错位")
                fin = []
                for value in y:
                    try:
                        if value is not None and math.isfinite(float(value)):
                            fin.append(float(value))
                    except (TypeError, ValueError):
                        continue
                if y and not fin:
                    failures.append(f"G8-OPS: sensitivity 系列 {ser.get('name')} 全为空值/NaN——图11 空子图")
    return warnings, failures


def check_valuation_band_contract(project: Path) -> tuple[list[str], list[str]]:
    """G8-VALUATION-BAND: 估值带必须是逐时点区间，而非全历史常数复制。

    旧版项目把全历史 max/min/mean 复制到每个年份，图形看似有阴影，实际没有
    估值区间随时间变化。PE校验low <= mean <= high；PB的pb为实际市场值，
    可以越过滚动分位带（突破本身就是有效信息），只校验low <= high。
    """
    warnings, failures = [], []
    path = project / "input" / "运营补充数据.json"
    if not path.exists():
        return warnings, failures
    try:
        ops = _load_ops(path)
    except Exception as exc:
        return warnings, [f"G8-VALUATION-BAND: 无法读取运营补充数据: {exc}"]
    shape_errors = _ops_shape_errors(ops)
    if shape_errors:
        return warnings, [f"G8-VALUATION-BAND: {error}" for error in shape_errors]
    specs = {
        "pe_band": ("PE", ("pe_low", "pe_mean", "pe_high")),
        "pb_band": ("PB", ("pb_low", "pb", "pb_high")),
    }
    for key, (label, fields) in specs.items():
        d = ops.get(key)
        if not d:
            continue
        labels = d.get("labels") or []
        arrays = {f: d.get(f) for f in fields}
        if any(not isinstance(v, list) for v in arrays.values()):
            failures.append(f"G8-VALUATION-BAND: {key} 缺少完整区间字段 {','.join(fields)}")
            continue
        if any(len(v) != len(labels) for v in arrays.values()):
            failures.append(f"G8-VALUATION-BAND: {key} 区间字段长度与 labels 不一致")
            continue
        rows = []
        for i in range(len(labels)):
            vals = []
            for f in fields:
                try:
                    x = float(arrays[f][i])
                except (TypeError, ValueError):
                    x = float("nan")
                vals.append(x)
            rows.append(vals)
        valid = [r for r in rows if all(np.isfinite(x) for x in r)]
        if len(valid) < 3:
            warnings.append(f"G8-VALUATION-BAND: {key} 有效时点仅 {len(valid)} 个，无法确认历史区间变化")
            continue
        bad_order = [i for i, r in enumerate(rows) if all(np.isfinite(x) for x in r)
                     and not (r[0] <= r[2] if key == "pb_band" else r[0] <= r[1] <= r[2])]
        if bad_order:
            order_rule = "low <= high" if key == "pb_band" else "low <= mean <= high"
            failures.append(f"G8-VALUATION-BAND: {key} 存在 {order_rule} 违反的时点（索引 {bad_order[:5]}）")
        low_values = {round(r[0], 8) for r in valid}
        mid_values = {round(r[1], 8) for r in valid}
        high_values = {round(r[2], 8) for r in valid}
        if len(low_values) == 1 and len(high_values) == 1:
            failures.append(f"G8-VALUATION-BAND: {label} 高低边界在全部时点恒定——疑似把全历史 max/min 复制到每年")
        elif len(low_values) == 1 or len(high_values) == 1:
            warnings.append(f"G8-VALUATION-BAND: {label} 仅一侧边界变化，确认是否为真实数据口径")
        if len(mid_values) == 1:
            warnings.append(f"G8-VALUATION-BAND: {label} 中枢在全部时点恒定，确认是否误用了全历史均值")
    return warnings, failures


def check_report(report_md: Path, html_path: Path | None, chart_dir: Path,
                skip_map: bool = False) -> tuple[list[str], list[str]]:
    """返回 (warnings, failures)。"""
    warnings, failures = [], []
    text = report_md.read_text(encoding="utf-8")
    md_lines = text.splitlines()
    exempt = set()
    try:
        exempt = _chart_exemptions(report_md.parents[1])
    except (OSError, ValueError):
        failures.append("input/图表豁免.json 无法解析")

    # 1) PNG 存在性 + 引用一致性
    png_files = {p.stem for p in chart_dir.glob("图*.png")} if chart_dir.exists() else set()
    for png_stem in png_files:
        if png_stem.split("_")[0] in exempt:
            failures.append(f"已豁免图仍有PNG，须明确处理旧产物：{png_stem}.png")
    refs = re.findall(r"!\[图(\d{2})[^\]]*\]\(图表/([^)]+\.png)\)", text)
    ref_fig_nos, ref_fnames = [int(a) for a, _ in refs], [b for _, b in refs]
    # SOTP 触发状态（平台型公司 → 图18 强制）
    sotp_trig = False
    try:
        _t = json.loads((report_md.parents[1] / "input" / "sotp_触发.json").read_text(encoding="utf-8"))
        sotp_trig = bool(_t.get("enabled"))
    except Exception:
        pass
    capex_trig, capex_has_tl = _capex_trigger_status(report_md.parents[1])
    for no in sorted(FIG_MAP):
        if no in (17,):
            continue
        if f"图{no:02d}" in exempt:
            continue
        if no == 18 and not sotp_trig:
            continue  # 非平台型公司：图18 可选，不强制
        if no in (19, 21) and not capex_trig:
            continue  # 未启用 Capex 与分红跃迁引擎时可选，不强制
        if no == 20 and (not capex_trig or not capex_has_tl):
            continue  # 未启用引擎或无重大在建清单时跳过图20
        if no not in ref_fig_nos:
            if no == 18:
                failures.append("图18（分部估值SOTP）触发平台型但未嵌入报告 §6——请运行 sotp_valuation.py 并补图18")
            elif no in (19, 20, 21):
                failures.append(f"图{no:02d}（{FIG_MAP[no][1]}）已配置 input/capex_dividend_plan.json 但未嵌入报告 §{FIG_MAP[no][0]}——请运行 capex_dividend_engine.py 并嵌入")
            else:
                warnings.append(f"图{no:02d}（{FIG_MAP[no][1]}）未在报告中嵌入（行业不适用需在交付清单说明）")
    for fname in ref_fnames:
        if not (chart_dir / fname).exists():
            failures.append(f"引用图片不存在: 图表/{fname}")
    for png_stem in png_files:
        if png_stem not in {Path(f).stem for f in ref_fnames}:
            warnings.append(f"PNG 已生成但未被引用: {png_stem}.png")
    
    # 1.1) PNG 完整性/尺寸（G8：损坏或过小 PNG 判定为生成异常）
    for png in sorted(chart_dir.glob("图*.png")) if chart_dir.exists() else []:
        try:
            with open(png, "rb") as f:
                head = f.read(26)
            if head[:8] != b"\x89PNG\r\n\x1a\n":
                failures.append(f"PNG 损坏（非 PNG 头）: {png.name}")
                continue
            w = int.from_bytes(head[16:20], "big")
            h = int.from_bytes(head[20:24], "big")
            if w < 800 or h < 400:
                warnings.append(f"PNG 尺寸偏小 {w}x{h}（预期 ≥800x400）: {png.name}")
        except Exception as exc:
            failures.append(f"PNG 读取失败: {png.name} ({exc})")

    # 2) 图号→章节映射（B4.3）
    for i, line in enumerate(md_lines):
        m = re.match(r"^!\[图(\d{2})", line.strip())
        if not m:
            continue
        no = int(m.group(1))
        want = FIG_SECTION.get(no)
        got = _embedding_section(md_lines, i)
        if not skip_map and want is not None and got is not None and got != want:
            failures.append(
                f"L{i+1}: 图{no:02d}（{FIG_MAP[no][1]}）应嵌入 §{want}，实际在 §{got}（章节映射错位）")
    
    # 2.1) 每图嵌入唯一性 + alt text 标题检查（B4.2：每图必须有标题）
    for no in sorted(FIG_MAP):
        if no == 17:
            continue
        embed_lines = [l for l in md_lines if re.match(rf"^!\[图{no:02d}", l.strip())]
        if len(embed_lines) > 1:
            warnings.append(f"图{no:02d} 在正文嵌入 {len(embed_lines)} 次（应每图只嵌入一次，附录清单除外）")
        elif len(embed_lines) == 1:
            m = re.match(rf"^!\[图{no:02d}\s*([^\]]*)\]", embed_lines[0].strip())
            if m and not m.group(1).strip():
                warnings.append(f"图{no:02d} 嵌入行缺少标题（应为 ![图{no:02d} 标题](图表/...)）")

    # 3) HTML 残留相对路径图片（未 base64 内嵌）
    if html_path is not None and html_path.exists():
        html_text = html_path.read_text(encoding="utf-8")
        residual = re.findall(r'src="(?:\.\./|\./)?图表/图\d+', html_text)
        if residual:
            failures.append(f"HTML 存在未内嵌的图片引用: {len(residual)} 处（应 base64 内嵌）")
        missing = re.findall(r'\.png(?:[?"\'])', html_text)
        if not re.search(r"data:image/png;base64", html_text) and refs:
            failures.append("HTML 无 base64 内嵌图片，疑似未渲染")
    
    # 3.1) 交互 HTML 面板检查（Plotly 交互图 reports/<公司>_<代码>_图表.html，trace ≥1）
    inter_htms = sorted(chart_dir.parent.glob("*_图表.html")) if chart_dir.parent.exists() else []
    if not inter_htms:
        failures.append("缺少 Plotly 交互图表 HTML（reports/<公司>_<代码>_图表.html）")
    for ih in inter_htms:
        ih_text = ih.read_text(encoding="utf-8")
        n_panels = len(re.findall(r'class=["\'][^"\']*\bplotly-graph-div\b', ih_text))
        if n_panels == 0:
            failures.append(f"交互 HTML 未检测到图表面板（可能为空模板）: {ih.name}")
        else:
            print(f"[HTML] 交互图面板数: {ih.name} = {n_panels}")
    # 3.5) 运营图表数据契约（G8-OPS）
    sw, sfail = check_sensitivity_contract(report_md.parent.parent, text)
    warnings.extend(sw); failures.extend(sfail)
    ow, ofail = check_ops_contract(report_md.parent.parent)
    warnings.extend(ow); failures.extend(ofail)
    vw, vfail = check_valuation_band_contract(report_md.parent.parent)
    warnings.extend(vw); failures.extend(vfail)
    from chart_period_qc import check_chart_periods
    pw, pfail = check_chart_periods(report_md.parent.parent)
    warnings.extend(pw); failures.extend(pfail)
    # 4) Markdown 表格结构
    failures.extend(check_markdown_tables(md_lines))
    iw, ifail = check_industry_contract(report_md.parent.parent, text)
    warnings.extend(iw); failures.extend(ifail)
    rw, rf = _check_render_quality(chart_dir.parents[1])
    warnings.extend(rw); failures.extend(rf)

    # 4.1) 附录图表清单 vs 实际嵌入位置
    failures.extend(check_listing_vs_embed(md_lines, report_md.parent.parent))

    # 4.2) 图表完整性：图01-15 PNG 必须存在；图16/17 需在 input/图表豁免.json 声明（禁止静默跳过）
    proj_root = chart_dir.parents[1]  # 批次根目录（chart_dir = reports/图表）
    for no in range(1, 16):
        if list(chart_dir.glob(f"图{no:02d}_*.png")):
            continue
        if f"图{no:02d}" in exempt:
            warnings.append(f"G8-完整: 图{no:02d} 未生成但已在 input/图表豁免.json 声明（交付清单须说明原因）")
        else:
            failures.append(f"G8-完整: 图{no:02d} PNG 缺失且未声明豁免（input/图表豁免.json）——请补 --ops 数据或声明豁免")
    if not list(chart_dir.glob("图16_*.png")):
        if f"图16" in exempt:
            pass  # 已豁免（行业不适用）
        elif (proj_root / "input" / "行业成本价格配置.json").exists() or (proj_root / "data" / "行业成本价格.csv").exists():
            failures.append("G8-完整: 行业成本—价格已配置（配置/CSV 存在）但图16 未生成")
        else:
            warnings.append("G8-完整: 图16 未生成且无行业成本—价格配置——按行业不适用处理，请在 input/图表豁免.json 声明以固化")

    # 5) 图表清单（附录 10.4）与嵌入一致性
    for no in sorted(FIG_MAP):
        if no == 17:
            continue
        if no in (19, 21) and not capex_trig:
            continue
        if no == 20 and (not capex_trig or not capex_has_tl):
            continue
        if f"图{no:02d}" in exempt:
            continue
        if f"| 图{no:02d} " not in text:
            sec, fname_cn = FIG_MAP.get(no, (None, ""))
            warnings.append(f"附录图表清单缺少 图{no:02d} 行（预置占位：| 图{no:02d} | 图表/图{no:02d}_*.png | §{sec or chr(8212)} | {fname_cn} |，报告模板附录 10.4 应预置全部图号行）")
    
    # 6) analyze_charts.py 标题编号静态检查（防新增 fig 函数忘写"图NN"，B4.2 每图必须有编号）
    ac = chart_dir.parents[1] / "scripts" / "analyze_charts.py"
    if ac.exists():
        for i, src_line in enumerate(ac.read_text(encoding="utf-8").splitlines()):
            if "→ §" in src_line and ("set_title(" in src_line or "suptitle(" in src_line) and "图" not in src_line:
                warnings.append(f"analyze_charts.py L{i+1}: 标题含章节指向但缺图号: {src_line.strip()[:60]}")
            if re.search(r"d\.get\(.*?\)\s*\+\s*[\"']\s*→\s*§", src_line):
                failures.append(f"analyze_charts.py L{i+1}: 数据标题直接追加章节后缀，可能生成重复箭头——请使用 _section_title()")
    return warnings, failures


def _render_data_texts(ax):
    """数据坐标（transData）的 text 标注列表。"""
    out = []
    for t in ax.texts:
        try:
            if t.get_transform() == ax.transData:
                out.append(t)
        except Exception:
            pass
    return out


_VALUE_LABEL_RE = re.compile(r"^[-+]?[\d,.]{1,}(?:%|x)?$")


def _render_is_value_label(t) -> bool:
    """是否为数值型短标注（如 "1,234" / "56.2%" / "7.06x"）。"""
    s = t.get_text().strip()
    if not s:
        return False
    return bool(re.fullmatch(_VALUE_LABEL_RE, s))


def _render_num_x(ax, v):
    """把轴上的 x 值转成数值坐标：日期（datetime/Timestamp/datetime64）→ matplotlib
    日期数值；数值直接转；字符串分类轴映射为类别序号（经 xtick 标签查找）；
    无法转换返回 None。"""
    from datetime import datetime, date
    if isinstance(v, (datetime, date)) or type(v).__name__ in ("Timestamp", "datetime64"):
        try:
            import matplotlib.dates as mdates
            f = float(mdates.date2num(v))
            return f if np.isfinite(f) else None
        except Exception:
            pass
    try:
        f = float(v)
        return f if np.isfinite(f) else None
    except Exception:
        pass
    try:
        positions = ax.get_xticks()
        labels = [t_.get_text() for t_ in ax.get_xticklabels()]
        for pos, lab in zip(positions, labels):
            if lab == str(v):
                return float(pos)
    except Exception:
        pass
    return None


def _render_anchor_of(ax, x_data, y_target, renderer):
    """同一 x 数据坐标下最近的线/柱锚点（数据坐标），返回 (x, y) 或 None。
    同 x 多序列（如三情景预测折线同列）时按 y 距离择优，避免距离检查挂错序列。"""
    best, best_d, best_dy = None, None, None
    yt = float(y_target) if y_target is not None else None
    for ln in ax.lines:
        xd, yd = ln.get_xdata(), ln.get_ydata()
        for xx, yy in zip(xd, yd):
            nx = _render_num_x(ax, xx)
            if nx is None:
                continue
            try:
                ny = float(yy)
                if not np.isfinite(ny):
                    continue
            except (TypeError, ValueError):
                continue
            d = abs(nx - float(x_data))
            dy = abs(ny - yt) if yt is not None else 0.0
            if (best_d is None or d < best_d - 1e-9
                    or (abs(d - best_d) < 1e-9 and dy < best_dy)):
                best_d, best_dy, best = d, dy, (nx, ny)
    for pch in ax.patches:
        try:
            bx = pch.get_x() + pch.get_width() / 2
            by = pch.get_y() + pch.get_height()
        except Exception:
            continue
        d = abs(float(bx) - float(x_data))
        dy = abs(float(by) - yt) if yt is not None else 0.0
        if (best_d is None or d < best_d - 1e-9
                or (abs(d - best_d) < 1e-9 and dy < best_dy)):
            best_d, best_dy, best = d, dy, (float(bx), float(by))
    if best is not None and best_d < 0.75:
        return best
    return None


def _render_data_bbox(ax, renderer):
    """所有线数据点 + 柱角点的窗口包围盒；无数据返回 None。"""
    pts = []
    for ln in ax.lines:
        xd, yd = ln.get_xdata(), ln.get_ydata()
        for xx, yy in zip(xd, yd):
            nx = _render_num_x(ax, xx)
            if nx is None:
                continue
            try:
                ny = float(yy)
                if not np.isfinite(ny):
                    continue
            except (TypeError, ValueError):
                continue
            pts.append(ax.transData.transform((nx, ny)))
    for pch in ax.patches:
        try:
            for c in pch.get_bbox().corners():
                pts.append(ax.transData.transform(c))
        except Exception:
            pass
    if not pts:
        return None
    xs = [pt[0] for pt in pts]; ys = [pt[1] for pt in pts]
    from matplotlib.transforms import Bbox
    return Bbox.from_extents(min(xs), min(ys), max(xs), max(ys))


def _render_overlap_ratio(a, b) -> float:
    """a 与 b 的交集面积 / a 面积。"""
    ix = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    iy = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    inter = ix * iy
    return inter / max(a.width * a.height, 1e-9)


def _render_text_overlap(a, b) -> bool:
    """两个窗口 bbox 是否相交（用于标注互叠检测）。"""
    ix = min(a.x1, b.x1) - max(a.x0, b.x0)
    iy = min(a.y1, b.y1) - max(a.y0, b.y0)
    return ix > 0 and iy > 0



def _check_figure_xticks(fig, label):
    """Inspect final rendered geometry; shared by legacy and combined render checks."""
    warnings, failures = [], []
    renderer = fig.canvas.get_renderer()
    for ax in fig.axes:
        visible = [lb for lb in ax.get_xticklabels() if lb.get_visible() and lb.get_text().strip()]
        if len(visible)>14:
            warnings.append(f"G8: {label} 横坐标刻度过多（{len(visible)} 个），存在重合风险")
        previous = None
        for lb in visible:
            extent = lb.get_window_extent(renderer)
            if previous is not None and extent.x0 < previous.x1-.5:
                failures.append(f"G8: {label} 横坐标刻度文字重合（{lb.get_text()}），须稀疏刻度/旋转")
                break
            previous = extent
    return warnings, failures

def _check_render_quality(project: Path) -> tuple[list[str], list[str]]:
    """G8-RENDER 渲染级门控（2026-08-18 新增，平安批次校准；2026-08-18 v2 扩展）：
    ① 数据标注越界（transData 文本超出坐标区 >2px）→ FAIL；
    ② 图例遮挡数据区（图例 bbox 与数据 bbox 重叠 >20%）→ FAIL；
    ③ 双轴折线标注离锚点过远（>40px）→ FAIL（>25px → WARN）；
    ④ 图06 同行估值对比必须为散点（须含 scatter collection，柱形 → FAIL/WARN）；
    ⑤ 数据标注互相重叠（同轴两个数值型标注 bbox 相交，图12 三情景标注重合校准）→ FAIL；
    ⑥ axes 占位比例（高度 <40% → FAIL / <55% → WARN；宽度 <55% → WARN，图15 高度只占 3/5 校准）；
    ⑦ 标题/脚注撑宽画布（tight bbox 宽 > 图宽×1.05，图04 数据区只占 3/5 宽度校准）→ WARN；
    ⑧ 图03 分部营收构成（2026-08-19 顺丰校准）：必须为环形饼图（无 Wedge 且含柱 → FAIL）；
       图例必须在图上方（位于图右侧挤压绘图区 → FAIL；图例底边低于 axes 顶边 → FAIL）；
       图题(suptitle)/轴标题与图例重叠 → FAIL（防 set_title 子图标题伸入顶部图例）。
    校验前先应用项目 analyze_charts.py 的 _auto_fix_layout 与 _auto_height（与保存渲染一致），
    保证门控校验的图 = 实际保存的 PNG。
    """
    warnings, failures = [], []
    timings = []
    script = project / "scripts" / "analyze_charts.py"
    if not script.exists():
        return warnings, failures
    try:
        import importlib.util
        import matplotlib.pyplot as plt
        spec = importlib.util.spec_from_file_location("_qc_render", script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        data_dir = project / "data"
        ops = {}
        opf = project / "input" / "运营补充数据.json"
        if opf.exists():
            ops = json.loads(opf.read_text(encoding="utf-8"))
        if hasattr(mod, "_bind_script_sensitivity"):
            ops = mod._bind_script_sensitivity(project, ops)
        ind = mod.load_industry_cost_price(data_dir)
        if ind and "industry_cost_price" not in ops:
            ops["industry_cost_price"] = ind
        mod.configure_latest(data_dir)
        pl_raw = mod.load_csv(data_dir, "利润表_按报告期.csv")
        fi_raw = mod.load_csv(data_dir, "主要财务指标_按报告期.csv")
        div = mod.load_csv(data_dir, "分红送配记录.csv")
        pl_y = mod.year_rows(pl_raw) if pl_raw is not None else None
        fi_y = mod.year_rows(fi_raw) if fi_raw is not None else None
        jobs = [
            ("图01", lambda: mod.fig_revenue(pl_y) if pl_y is not None else None),
            ("图02", lambda: mod.fig_roe_bps(fi_y) if fi_y is not None else None),
            ("图03", lambda: mod.fig_segment(ops)),
            ("图04", lambda: mod.fig_profitability(ops)),
            ("图05", lambda: mod.fig_cashflow(ops)),
            ("图06", lambda: mod.fig_peers(ops)),
            ("图07", lambda: mod.fig_dps(div, ops)),
            ("图08", lambda: mod.fig_price(data_dir)),
            ("图09", lambda: mod.fig_targets(ops)),
            ("图10", lambda: mod.fig_penetration(ops)),
            ("图11", lambda: mod.fig_sensitivity(ops)),
            ("图12", lambda: mod.fig_forecast(ops)),
            ("图13", lambda: mod.fig_pe_band(ops)),
            ("图14", lambda: mod.fig_pb_band(ops)),
            ("图15", lambda: mod.fig_leverage(ops)),
            ("图16", lambda: mod.fig_industry_cost_price(ops, data_dir)),
        ]
        exempt = _chart_exemptions(project)
        for index, (label, fn) in enumerate(jobs, 1):
            if label in exempt:
                continue
            tick = time.monotonic()
            print(f"[G8-RENDER] {index}/{len(jobs)} {label}：构图、刻度和布局检查", flush=True)
            try:
                fig = fn()
            except Exception as exc:
                failures.append(f"G8-RENDER: {label} 无法重建：{exc}")
                continue
            if fig is None:
                continue
            try:
                if hasattr(mod, "_auto_fix_layout"):
                    mod._auto_fix_layout(fig)
                else:
                    fig.canvas.draw()
                if hasattr(mod, "_auto_height"):
                    mod._auto_height(fig)   # 与保存渲染一致（G8-RENDER 高度自适应）
                renderer = fig.canvas.get_renderer()
                xw, xf = _check_figure_xticks(fig, label)
                warnings.extend(xw); failures.extend(xf)
                if getattr(fig,'_year_grouped',False):
                    from financial_history_charts import growth_line_evidence, growth_line_failures
                    from chart_numbers import valid_number_label
                    failures.extend(f'G8-RENDER: {label} {message}' for message in
                                    growth_line_failures(mod.LATEST_PACK,label,growth_line_evidence(fig),ops))
                    for ax in fig.axes:
                        if hasattr(ax,'_history_twin'):
                            ticks=[t.get_text() for t in ax._history_twin.get_yticklabels() if t.get_visible()]
                            if any(not valid_number_label(t) for t in ticks) or len(ticks)!=len(set(ticks)):
                                failures.append(f'G8-RENDER: {label} 年度同比轴刻度超过两位小数或舍入后重复')
                if hasattr(fig,'_layout_audit'):
                    audit=getattr(fig,'_layout_audit',{})
                    if (audit.get('number_format')!={'max_decimal_places':2,'small_nonzero':'inequality','trim_trailing_zeros':True}
                        or audit.get('number_format_violations') != []):
                        failures.append(f'G8-RENDER: {label} 数字格式未审计或实际图中文字超过2位小数')
                    if getattr(fig,'_year_grouped',False) and any(c.get('number_format_valid') is not True or c.get('text_matches_values') is not True for c in audit.get('bar_label_counts',{}).values()):
                        failures.append(f'G8-RENDER: {label} 柱值标注超过2位小数、非零误标为0或显示值不符')
                    gaps=[audit.get('header_gap_pt'),audit.get('footer_gap_pt'),*audit.get('row_gaps_pt',[])]
                    gaps=[v for v in gaps if v is not None]
                    if (not audit.get('measured') or audit.get('annotation_collisions',[]) != [] or audit.get('text_collisions',[]) != [] or audit.get('text_out_of_bounds',[]) != [] or
                        any(not isinstance(v,(float,int)) or not 3<=v<=26 for v in gaps)):
                        failures.append(f'G8-RENDER: {label} 实际重建的柱值/图例/子图/脚注布局不合格：{audit}')
                # ⑥ axes 占位比例（按唯一 position 去重，twinx 共享位置只检一次）
                seen_pos = set()
                pos_list = []
                for ax in fig.axes:
                    ab = ax.get_window_extent(renderer)
                    key = (round(ab.x0), round(ab.y0), round(ab.x1), round(ab.y1))
                    if key in seen_pos:
                        continue
                    seen_pos.add(key)
                    pos_list.append(ab)
                fh = fig.bbox.height
                fw = fig.bbox.width
                # 堆叠多面板（同列 subplots，如 图16 成本/价格 + 供需面板）：面板高度由设计比例决定，
                # 轴外元素挤压应看"总数据区高度"（2026-08-22 牧原校准：逐面板检查会误伤供需下方面板）。
                if len(pos_list) == 1:
                    groups = [pos_list]
                else:
                    groups = []
                    # Grid axes are row-major: group complete columns, not only
                    # adjacent axes (latest-period segment donuts may span rows).
                    for ab in pos_list:
                        group = next((g for g in groups if abs(ab.x0 - g[0].x0) < 5 and abs(ab.width - g[0].width) < 5), None)
                        if group is None:
                            groups.append([ab])
                        else:
                            group.append(ab)
                for g in groups:
                    top = max(ab.y1 for ab in g); bot = min(ab.y0 for ab in g)
                    if fh > 0:
                        r_h = (top - bot) / fh
                        if r_h < 0.40:
                            failures.append(
                                f"G8-RENDER: {label} axes 高度仅占图 {r_h*100:.0f}%（<40%，图高被压缩/只占 3/5）——请用 _auto_height 或精简轴外元素（图例/脚注）")
                        elif r_h < 0.55:
                            warnings.append(
                                f"G8-RENDER: {label} axes 高度占图 {r_h*100:.0f}%（<55%），建议 _auto_height 拉满")
                # 宽度仅对单图（1 个唯一 position，含 twinx）检查——多面板每面板宽度天然 <100%
                if fw > 0 and len(pos_list) == 1:
                    r_w = pos_list[0].width / fw
                    if r_w < 0.55:
                        warnings.append(
                            f"G8-RENDER: {label} axes 宽度占图 {r_w*100:.0f}%（<55%，数据区宽度被挤压）")
                # ⑦ 标题/脚注撑宽画布（tight bbox 宽 > 图宽×1.05 → 数据区相对变窄）
                try:
                    bb = fig.get_tightbbox(renderer)
                    if bb.width > fig.bbox.width * 1.05:
                        warnings.append(
                            f"G8-RENDER: {label} 标题/脚注撑宽画布（tight bbox {bb.width:.1f} 英寸 > 图宽 {fig.bbox.width:.1f}×1.05）——请精简标题，防数据区只占部分宽度")
                except Exception:
                    pass
                for ax in fig.axes:
                    ab = ax.get_window_extent(renderer)
                    # ① 标注越界
                    for t in _render_data_texts(ax):
                        tb = t.get_window_extent(renderer)
                        if (tb.y1 > ab.y1 + 2 or tb.y0 < ab.y0 - 2
                                or tb.x1 > ab.x1 + 2 or tb.x0 < ab.x0 - 2):
                            failures.append(
                                f"G8-RENDER: {label} 数据标注越界（{t.get_text()!r}）——请检查标注偏移/ylim 留白")
                    # ③ 双轴标注离锚点过远（仅数值型短标注；标题/门槛/脚注不参与）
                    for t in _render_data_texts(ax):
                        if not _render_is_value_label(t):
                            continue
                        try:
                            xd, yd = t.get_position()
                        except Exception:
                            continue
                        anchor = _render_anchor_of(ax, xd, yd, renderer)
                        if anchor is None:
                            continue
                        tp = t.get_window_extent(renderer)
                        ap = ax.transData.transform(anchor)
                        d = abs(tp.y0 - ap[1])
                        if d > 40:
                            failures.append(
                                f"G8-RENDER: {label} 数据标注离锚点过远（{t.get_text()!r}，{d:.0f}px）——请用 _auto_fix_layout 或减小标注偏移")
                        elif d > 25:
                            warnings.append(
                                f"G8-RENDER: {label} 数据标注距锚点偏大（{t.get_text()!r}，{d:.0f}px）")
                    # ⑤ 数据标注互相重叠（图12 三情景标注重合校准）
                    vlabels = [(t, t.get_window_extent(renderer))
                               for t in _render_data_texts(ax) if _render_is_value_label(t)]
                    for i in range(len(vlabels)):
                        for j in range(i + 1, len(vlabels)):
                            if _render_text_overlap(vlabels[i][1], vlabels[j][1]):
                                failures.append(
                                    f"G8-RENDER: {label} 数据标注互相重叠（{vlabels[i][0].get_text()!r} 与 {vlabels[j][0].get_text()!r}）——请错开标注或修复锚点择优")
                    # ② 图例遮挡数据区
                    leg = ax.get_legend()
                    if leg is not None:
                        lb = leg.get_window_extent(renderer)
                        db = _render_data_bbox(ax, renderer)
                        if db is not None:
                            r = _render_overlap_ratio(lb, db)
                            if r > 0.20:
                                failures.append(
                                    f"G8-RENDER: {label} 图例遮挡数据区（重叠 {r*100:.0f}%）——请移到轴外或调整 loc")
                            elif r > 0.10:
                                warnings.append(
                                    f"G8-RENDER: {label} 图例与数据区重叠 {r*100:.0f}%，建议移到轴外")
                # ④ 图06 同行估值对比必须散点
                if label == "图06":
                    scatters = [c for ax in fig.axes for c in ax.collections]
                    from matplotlib.patches import Rectangle
                    bars = [p_ for ax in fig.axes for p_ in ax.patches if isinstance(p_, Rectangle)]
                    if not scatters:
                        failures.append(
                            "G8-RENDER: 图06 同行估值对比应使用散点图（未检测到 scatter collection）——禁止柱状图堆叠对比")
                    elif bars:
                        warnings.append(
                            f"G8-RENDER: 图06 存在 {len(bars)} 个柱形 patch，建议同行估值对比纯散点（估值×盈利双维）")
                # ⑧ 图03 分部营收构成：环形饼图 + 图例在上 + 标题不与图例重叠（2026-08-19 顺丰校准）
                if label == "图03":
                    from matplotlib.patches import Wedge, Rectangle
                    wedges = [p_ for ax in fig.axes for p_ in ax.patches if isinstance(p_, Wedge)]
                    bars = [p_ for ax in fig.axes for p_ in ax.patches if isinstance(p_, Rectangle)]
                    if not wedges and bars:
                        failures.append(
                            "G8-RENDER: 图03 分部营收构成应使用环形饼图（未检测到 Wedge patch，疑似堆叠柱状图）——改为环形饼图：图例上方、年份+营收放环心")
                    elif wedges and bars:
                        warnings.append(
                            f"G8-RENDER: 图03 同时存在饼图与 {len(bars)} 个柱形 patch，建议纯环形饼图")
                    leg = fig.legends[0] if fig.legends else None
                    if leg is not None and fig.axes:
                        lb = leg.get_window_extent(renderer)
                        abs_ = [ax.get_window_extent(renderer) for ax in fig.axes]
                        max_x1 = max(ab.x1 for ab in abs_)
                        top_y1 = max(ab.y1 for ab in abs_)
                        if lb.x0 > max_x1 + 5:
                            failures.append(
                                "G8-RENDER: 图03 图例置于图右侧挤压绘图区——应放图上方（fig.legend(loc='upper center', ncol=N)）")
                        elif lb.y0 < top_y1 - 5:
                            failures.append(
                                "G8-RENDER: 图03 图例未在图上方（图例底边低于 axes 顶边）——图例需在绘图区之上，防与轴标题/数据重叠")
                # 图题(suptitle)/轴标题 与 图例 重叠（图03 图题-图例、子图标题-图例校准，2026-08-19）
                if fig.legends:
                    leg_boxes = [lg.get_window_extent(renderer) for lg in fig.legends]
                    try:
                        if fig._suptitle is not None and fig._suptitle.get_text().strip():
                            stb = fig._suptitle.get_window_extent(renderer)
                            for lb in leg_boxes:
                                if _render_text_overlap(stb, lb):
                                    failures.append(
                                        f"G8-RENDER: {label} 图题(suptitle)与图例重叠——请分段布局（图题→图例→图表），图例 bbox_to_anchor y 下移至 axes 之上")
                    except Exception:
                        pass
                    for ax in fig.axes:
                        ttl = ax.get_title()
                        if not ttl:
                            continue
                        try:
                            tb = ax.title.get_window_extent(renderer)
                        except Exception:
                            continue
                        for lb in leg_boxes:
                            if _render_text_overlap(tb, lb):
                                failures.append(
                                    f"G8-RENDER: {label} 轴标题与图例重叠（{ttl!r}）——子图标题勿用 set_title 置于图例区域，改环心标注/图题合并")
            finally:
                plt.close(fig)
                elapsed = round(time.monotonic()-tick, 3)
                timings.append({"chart":label, "elapsed_seconds":elapsed})
                print(f"[G8-RENDER] {label} 完成，{elapsed:.2f}s", flush=True)
    except Exception as exc:
        failures.append(f"G8-RENDER: 渲染级检查异常（{exc}），检查未完成")
    from run_support import atomic_json
    atomic_json(project / "reports" / "图表检查计时.json", {"charts":timings, "status":"FAIL" if failures else "PASS", "xticks_shared_render":True})
    return warnings, failures


def _check_all_xticks(project: Path) -> tuple[list[str], list[str]]:
    """G8 全图横坐标刻度检查（2026-08-17 新增，伊利反馈）：逐张渲染全部图，
    应用生成脚本的 _fix_xtick_overlap 后，检测任意轴横坐标刻度文字重合
    （重合→FAIL）；刻度 >14 个 → WARN。防“年份/月度标签过多导致底部文字重叠”。
    """
    warnings, failures = [], []
    script = project / "scripts" / "analyze_charts.py"
    if not script.exists():
        return warnings, failures
    try:
        import importlib.util
        import matplotlib.pyplot as plt
        spec = importlib.util.spec_from_file_location("_qc_all_analyze", script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        data_dir = project / "data"
        ops = {}
        opf = project / "input" / "运营补充数据.json"
        if opf.exists():
            ops = json.loads(opf.read_text(encoding="utf-8"))
        if hasattr(mod, "_bind_script_sensitivity"):
            ops = mod._bind_script_sensitivity(project, ops)
        ind = mod.load_industry_cost_price(data_dir)
        if ind and "industry_cost_price" not in ops:
            ops["industry_cost_price"] = ind
        mod.configure_latest(data_dir)
        pl_raw = mod.load_csv(data_dir, "利润表_按报告期.csv")
        fi_raw = mod.load_csv(data_dir, "主要财务指标_按报告期.csv")
        div = mod.load_csv(data_dir, "分红送配记录.csv")
        pl_y = mod.year_rows(pl_raw) if pl_raw is not None else None
        fi_y = mod.year_rows(fi_raw) if fi_raw is not None else None
        jobs = [
            ("图01", lambda: mod.fig_revenue(pl_y) if pl_y is not None else None),
            ("图02", lambda: mod.fig_roe_bps(fi_y) if fi_y is not None else None),
            ("图03", lambda: mod.fig_segment(ops)),
            ("图04", lambda: mod.fig_profitability(ops)),
            ("图05", lambda: mod.fig_cashflow(ops)),
            ("图06", lambda: mod.fig_peers(ops)),
            ("图07", lambda: mod.fig_dps(div, ops)),
            ("图08", lambda: mod.fig_price(data_dir)),
            ("图09", lambda: mod.fig_targets(ops)),
            ("图10", lambda: mod.fig_penetration(ops)),
            ("图11", lambda: mod.fig_sensitivity(ops)),
            ("图12", lambda: mod.fig_forecast(ops)),
            ("图13", lambda: mod.fig_pe_band(ops)),
            ("图14", lambda: mod.fig_pb_band(ops)),
            ("图15", lambda: mod.fig_leverage(ops)),
            ("图16", lambda: mod.fig_industry_cost_price(ops, data_dir)),
        ]
        exempt = _chart_exemptions(project)
        for label, fn in jobs:
            if label in exempt:
                continue
            try:
                fig = fn()
            except Exception:
                continue
            if fig is None:
                continue
            try:
                if hasattr(mod, "_fix_xtick_overlap"):
                    mod._fix_xtick_overlap(fig)
                else:
                    fig.canvas.draw()
                renderer = fig.canvas.get_renderer()
                for ax in fig.axes:
                    vis = [lb for lb in ax.get_xticklabels()
                           if lb.get_visible() and lb.get_text().strip()]
                    if len(vis) > 14:
                        warnings.append(f"G8: {label} 横坐标刻度过多（{len(vis)} 个），存在重合风险")
                    prev_ext = None
                    for lb in vis:
                        ext = lb.get_window_extent(renderer)
                        if prev_ext is not None and ext.x0 < prev_ext.x1 - 0.5:
                            failures.append(
                                f"G8: {label} 横坐标刻度文字重合（{lb.get_text()}），须稀疏刻度/旋转")
                            break
                        prev_ext = ext
            finally:
                plt.close(fig)
    except Exception as exc:
        warnings.append(f"G8: 全图横坐标刻度检查异常（{exc}），需人工复核刻度重合")
    return warnings, failures


def main() -> int:
    ap = argparse.ArgumentParser(description="图表质量门（G8）")
    ap.add_argument("--dir", default=".", help="项目目录")
    ap.add_argument("--report", default="", help="报告 MD 路径（相对 --dir，如 reports/xx.md）")
    ap.add_argument("--html", default="", help="报告 HTML 路径（相对 --dir，缺省按 report 同名推断）")
    ap.add_argument("--list-png", action="store_true", help="仅盘点 PNG 与图号映射")
    ap.add_argument("--no-map-check", action="store_true",
                    help="跳过 B4.3 固定图号映射检查（历史项目自编号豁免；清单一致性检查仍执行）")
    args = ap.parse_args()

    proj = Path(args.dir).resolve()
    chart_dir = proj / "reports" / "图表"

    if args.list_png:
        print("图号→章节映射（B4.3，禁止自创编号）：")
        for no in sorted(FIG_MAP):
            sec, name = FIG_MAP[no]
            print(f"  图{no:02d} -> §{sec if sec else '—'} {name}")
        print(f"\nreports/图表/ 现有 PNG {len(list(chart_dir.glob('图*.png')))} 张：")
        for p in sorted(chart_dir.glob("图*.png")):
            print(f"  {p.name}  ({p.stat().st_size/1024:.0f} KB)")
        return 0

    if not args.report:
        print("用法：--report reports/<报告>.md [--html reports/<报告>.html]")
        return 2

    report_md = Path(args.report) if Path(args.report).is_absolute() else proj / args.report
    html_path = None
    if args.html:
        html_path = Path(args.html) if Path(args.html).is_absolute() else proj / args.html
    else:
        cand = report_md.with_suffix(".html")
        if cand.exists():
            html_path = cand

    if not report_md.exists():
        print(f"❌ 报告不存在: {report_md}")
        return 1

    skip_map = args.no_map_check
    warnings, failures = check_report(report_md, html_path, chart_dir, skip_map=skip_map)

    print(f"=== 图表质量门（G8）===")
    print(f"报告: {report_md.name} ｜ 图表目录: {chart_dir}")
    print(f"PNG 数: {len(list(chart_dir.glob('图*.png')))}")
    for w in warnings:
        print(f"  [WARN] {w}")
    for f_ in failures:
        print(f"  [FAIL] {f_}")
    if not failures:
        print("结论: ✅ 通过（WARN 项需在交付清单说明）")
        return 0
    print("结论: ❌ 未通过，修复后重跑")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
