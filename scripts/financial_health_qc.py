#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G22 quality gate for the current-period financial health evidence package."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from financial_health_check import HEALTH_CHARTS, render_evidence, render_report_section, run
from financial_health_core import DEFAULT_CONFIG, build_health_report, default_config, fingerprint_files


REQUIRED_REPORT_SECTIONS = (
    "本期财报结论先行",
    "现金流：赚的是真钱还是账面利润",
    "经营现金流变化原因",
    "利润波动原因",
    "存货专项检查",
    "非主营投资和金融资产检查",
    "管理层解释与数据验证",
    "财务美化/劣化风险信号",
    "对全年预测和估值的影响",
)


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, str(exc)
    if not isinstance(value, dict):
        return None, "JSON 根节点必须为对象"
    return value, None


def _contains_signal(report_text: str, signal: dict[str, Any]) -> bool:
    signal_id = str(signal.get("id", ""))
    title = str(signal.get("title", ""))
    return bool((signal_id and signal_id in report_text) or (title and title in report_text))


def _report_section(text: str) -> str:
    match = re.search(r"(?ms)^#{1,6}\s*§4\.3\b.*?(?=^#{1,6}\s*§4\.4\b|\Z)", text)
    return match.group(0) if match else text


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonical(val) for key, val in sorted(value.items()) if key != "generated_at"}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def _numeric_tree_errors(value: Any, path: str) -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            errors.extend(_numeric_tree_errors(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(_numeric_tree_errors(item, f"{path}[{index}]"))
    elif value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
        errors.append(path)
    return errors


def _numeric_fields_valid(section: Any, section_name: str) -> list[str]:
    """Validate only numeric statement scopes; provenance metadata is textual by contract."""
    if not isinstance(section, dict):
        return [section_name]
    scopes = {
        "current", "yoy", "prior_period_end", "current_single_period", "prior_single_period",
    }
    errors: list[str] = []
    for scope in scopes:
        values = section.get(scope)
        if values is None:
            continue
        if not isinstance(values, dict):
            errors.append(f"{section_name}.{scope}")
            continue
        for field, value in values.items():
            if field == "unit":
                continue
            errors.extend(_numeric_tree_errors(value, f"{section_name}.{scope}.{field}"))
    return errors


def _legacy_check(project_dir: Path, report: Path | None = None, refresh: bool = False) -> tuple[list[dict[str, Any]], int]:
    project_dir = project_dir.resolve()
    data_dir = project_dir / "data"
    input_dir = project_dir / "input"
    reports_dir = project_dir / "reports"
    evidence_path = reports_dir / "本期财报体检.json"
    summary_path = reports_dir / "本期财报体检_证据摘要.md"
    section_path = reports_dir / "本期财报体检_成文框架.md"
    chart_paths = [reports_dir / "图表" / name for name in HEALTH_CHARTS]
    config_path = input_dir / "本期财报体检配置.json"
    checks: list[dict[str, Any]] = []

    def add(check_id: str, status: str, detail: str) -> None:
        checks.append({"id": check_id, "status": status, "detail": detail})

    for filename in ("利润表_按报告期.csv", "资产负债表_按报告期.csv", "现金流量表_按报告期.csv"):
        add(f"required_{filename}", "PASS" if (data_dir / filename).is_file() else "FAIL", f"data/{filename}")
    if not config_path.is_file():
        add("config", "FAIL", "缺少 input/本期财报体检配置.json")
    else:
        config, error = _load_json(config_path)
        add("config_json", "PASS" if config is not None else "FAIL", error or "配置可解析")

    if refresh or not evidence_path.is_file() or not summary_path.is_file() or not section_path.is_file() or any(not path.is_file() for path in chart_paths):
        try:
            run(project_dir)
        except Exception as exc:
            add("evidence_generation", "FAIL", f"证据包生成失败: {exc}")
    evidence, error = _load_json(evidence_path) if evidence_path.is_file() else (None, "证据 JSON 不存在")
    add("evidence_json", "PASS" if evidence is not None else "FAIL", error or "证据 JSON 可解析")
    if evidence is None:
        return checks, 1

    period = evidence.get("report_period", {})
    has_period = bool(period.get("current"))
    has_yoy = bool(period.get("yoy"))
    add("current_period", "PASS" if has_period else "FAIL", str(period.get("current") or "缺少本期报告期"))
    add("comparable_period", "PASS" if has_yoy else "FAIL", str(period.get("yoy") or "缺少同比可比期"))
    limitations = evidence.get("limitations", [])
    hard_limits = [x for x in limitations if x.get("severity") == "fail"]
    add("period_limitations", "FAIL" if hard_limits else "PASS", "; ".join(x.get("id", "") for x in hard_limits) or "无期间硬失败")

    convention = evidence.get("display_convention", {})
    add("display_convention", "PASS" if convention.get("amount") and convention.get("ratio") else "FAIL", "金额/比例展示口径")
    required_top = ("schema_version", "report_period", "income_statement", "balance_sheet", "cash_flow", "bridges", "signals", "forecast_impact", "limitations", "input_fingerprint")
    missing_top = [key for key in required_top if key not in evidence]
    schema_ok = not missing_top and str(evidence.get("schema_version")) == "1.0"
    schema_detail = "JSON 顶层契约完整" if schema_ok else "缺少/错误字段: " + ", ".join(missing_top or ["schema_version"])
    add("json_schema", "PASS" if schema_ok else "FAIL", schema_detail)
    type_errors = _numeric_fields_valid(evidence.get("income_statement", {}), "income_statement")
    type_errors += _numeric_fields_valid(evidence.get("balance_sheet", {}), "balance_sheet")
    type_errors += _numeric_fields_valid(evidence.get("cash_flow", {}), "cash_flow")
    add("json_field_types", "PASS" if not type_errors else "FAIL", "金额和比例字段类型合法" if not type_errors else "字段类型异常: " + ", ".join(type_errors[:5]))
    signal_errors = [
        str(index) for index, signal in enumerate(evidence.get("signals", []))
        if not isinstance(signal, dict) or not signal.get("id") or not signal.get("evidence_id")
        or signal.get("status") not in {"triggered", "not_triggered", "indeterminate"}
        or signal.get("direction") not in {"positive", "negative", "neutral"}
        or not isinstance(signal.get("source_fields"), list)
    ]
    add("signal_schema", "FAIL" if signal_errors else "PASS", "信号字段契约完整" if not signal_errors else "信号字段异常: " + ", ".join(signal_errors[:5]))
    signals = evidence.get("signals", [])
    if not isinstance(signals, list):
        signals = []
    impact = evidence.get("forecast_impact", {})
    impact_keys = ("revenue", "profit", "cash_flow", "valuation_risk")
    invalid_impacts = [key for key in impact_keys if impact.get(key) not in {"上调", "维持", "下调", "待观察"}]
    add("forecast_impact_schema", "FAIL" if invalid_impacts else "PASS", "预测/估值影响枚举合法" if not invalid_impacts else "非法枚举: " + ", ".join(invalid_impacts))
    missing_evidence_ids = []
    for section_name in ("income_statement", "balance_sheet", "cash_flow"):
        for scope, records in evidence.get(section_name, {}).get("evidence_records", {}).items():
            if isinstance(records, dict):
                missing_evidence_ids.extend(f"{section_name}.{scope}.{field}" for field, record in records.items() if not record.get("evidence_id") or not record.get("source_file"))
    add("evidence_provenance", "FAIL" if missing_evidence_ids else "PASS", "核心字段来源和 evidence_id 完整" if not missing_evidence_ids else "缺少: " + ", ".join(missing_evidence_ids[:5]))
    fingerprint = evidence.get("input_fingerprint", {})
    current_fp = fingerprint_files(data_dir, config_path)
    add("input_fingerprint", "PASS" if fingerprint.get("digest") == current_fp.get("digest") else "FAIL", "输入文件指纹一致" if fingerprint.get("digest") == current_fp.get("digest") else "输入已变化，证据包需要刷新")

    try:
        config = default_config()
        if config_path.is_file():
            loaded_config, _ = _load_json(config_path)
            if loaded_config:
                config.update({key: value for key, value in loaded_config.items() if key != "thresholds"})
                config["thresholds"].update(loaded_config.get("thresholds", {}))
        recalculated = build_health_report(data_dir, project_dir.name, config)
        equal = _canonical(recalculated) == _canonical(evidence)
        add("recalculation", "PASS" if equal else "FAIL", "证据包核心结果可复算" if equal else "JSON 与当前三表重新计算结果不一致")
    except Exception as exc:
        add("recalculation", "FAIL", f"无法重新计算: {exc}")

    for bridge_name, bridge in evidence.get("bridges", {}).items():
        if bridge_name == "working_capital":
            status = bridge.get("status")
        else:
            status = bridge.get("status")
        if status == "needs_explanation":
            add(f"bridge_{bridge_name}", "WARN", f"桥接残差 {bridge.get('residual_pct')}% 超过 {DEFAULT_CONFIG['thresholds']['bridge_residual_pct']}%")
        elif status == "indeterminate":
            add(f"bridge_{bridge_name}", "WARN", "桥接字段不足，无法完全复算")
        else:
            add(f"bridge_{bridge_name}", "PASS", "桥接可复算")

    if not summary_path.is_file():
        add("evidence_summary", "FAIL", "缺少 Markdown 证据摘要")
    else:
        summary_text = summary_path.read_text(encoding="utf-8")
        digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        try:
            expected_summary = render_evidence(evidence, digest)
            summary_matches = summary_text.replace("\r\n", "\n") == expected_summary.replace("\r\n", "\n")
            summary_detail = "摘要与 JSON 可复算一致" if summary_matches else "摘要与 JSON 生成结果不一致"
        except Exception as exc:
            summary_matches = False
            summary_detail = f"无法从 JSON 复算摘要: {exc}"
        add("summary_consistency", "PASS" if summary_matches else "FAIL", summary_detail)
        add("summary_period", "PASS" if str(period.get("current") or "—") in summary_text else "FAIL", "摘要包含本期报告期")
        disclosure_signals = [s for s in signals if s.get("status") in {"triggered", "indeterminate"}]
        missing_ids = [s.get("id") for s in disclosure_signals if s.get("id") not in summary_text]
        add("summary_signals", "FAIL" if missing_ids else "PASS", "缺少信号: " + ", ".join(missing_ids) if missing_ids else "触发信号均在摘要中")
        missing_impacts = [key for key in ("revenue", "profit", "cash_flow", "valuation_risk") if str(evidence.get("forecast_impact", {}).get(key)) not in summary_text]
        add("summary_forecast_impact", "FAIL" if missing_impacts else "PASS", "摘要缺少: " + ", ".join(missing_impacts) if missing_impacts else "预测/估值影响均在摘要中")

    report_candidates = [report] if report else sorted(reports_dir.glob("*_分析报告.md"))
    if report_candidates and report_candidates[0].is_file():
        report_path = report_candidates[0]
        text = report_path.read_text(encoding="utf-8")
        missing_sections = [section for section in REQUIRED_REPORT_SECTIONS if section not in text]
        add("report_section", "FAIL" if missing_sections else "PASS", "缺少: " + ", ".join(missing_sections) if missing_sections else "§4.3 七个必备小节均存在")
        add("report_json_reference", "PASS" if "本期财报体检.json" in text else "FAIL", "主报告引用体检 JSON")
        disclosure_signals = [s for s in signals if s.get("status") in {"triggered", "indeterminate"}]
        missing_ids = [s.get("id") for s in disclosure_signals if not _contains_signal(text, s)]
        add("report_triggered_signals", "FAIL" if missing_ids else "PASS", "缺少: " + ", ".join(missing_ids) if missing_ids else "触发信号均已披露")
        impact = evidence.get("forecast_impact", {})
        missing_impacts = [key for key in ("revenue", "profit", "cash_flow", "valuation_risk") if not impact.get(key)]
        add("forecast_impact", "FAIL" if missing_impacts else "PASS", "缺少: " + ", ".join(missing_impacts) if missing_impacts else "预测/估值影响字段完整")
    else:
        add("report_section", "FAIL", "未找到主报告，无法核验 §4.3")

    add(
        "health_charts",
        "PASS" if all(path.is_file() for path in chart_paths) else "FAIL",
        "五张固定体检图均存在" if all(path.is_file() for path in chart_paths) else "缺少: " + ", ".join(path.name for path in chart_paths if not path.is_file()),
    )
    if section_path.is_file():
        section_text = section_path.read_text(encoding="utf-8")
        digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        try:
            expected_section = render_report_section(evidence, digest)
            section_matches = section_text.replace("\r\n", "\n") == expected_section.replace("\r\n", "\n")
            add("report_framework_consistency", "PASS" if section_matches else "FAIL", "成文框架与 JSON 可复算一致" if section_matches else "成文框架与 JSON 生成结果不一致")
        except Exception as exc:
            add("report_framework_consistency", "FAIL", f"无法复算成文框架: {exc}")
    else:
        add("report_framework_consistency", "FAIL", "缺少本期财报体检_成文框架.md")

    if report_candidates and report_candidates[0].is_file():
        report_section = _report_section(report_candidates[0].read_text(encoding="utf-8"))
        missing_charts = [path.name for path in chart_paths if path.name not in report_section]
        add("report_health_charts", "FAIL" if missing_charts else "PASS", "§4.3 已嵌入五张体检图" if not missing_charts else "§4.3 缺少: " + ", ".join(missing_charts))
        internal_patterns = ("source_fields", "income.", "balance.", "cash.")
        leaked = [pattern for pattern in internal_patterns if pattern in report_section]
        add("report_human_readable", "FAIL" if leaked else "PASS", "§4.3 未发现内部字段路径" if not leaked else "§4.3 含内部字段路径: " + ", ".join(leaked))

    return checks, 1 if any(item["status"] == "FAIL" for item in checks) else 0


def _key_signal_ids(evidence: dict[str, Any]) -> set[str]:
    return {
        str(signal.get("id"))
        for signal in evidence.get("signals", [])
        if signal.get("key_finding") and signal.get("id") in {
            "FH_CASH_FLOW_EXPLANATION", "FH_PROFIT_VOLATILITY",
            "FH_INVENTORY_REVIEW", "FH_FINANCIAL_ASSET_SPECULATION",
        }
    }


def _is_applicable_signal(signal: dict[str, Any]) -> bool:
    applicability = signal.get("applicability")
    return applicability is not False


def _check(project_dir: Path, report: Path | None = None, refresh: bool = False) -> tuple[list[dict[str, Any]], int]:
    """Run the key-question G22 checks.

    Missing optional evidence and a triggered signal are reportable WARNs.  A
    FAIL is reserved for a missing/invalid evidence contract, stale inputs, or
    a report that omits a required reader-facing answer.
    """
    project_dir = project_dir.resolve()
    data_dir = project_dir / "data"
    input_dir = project_dir / "input"
    reports_dir = project_dir / "reports"
    evidence_path = reports_dir / "本期财报体检.json"
    summary_path = reports_dir / "本期财报体检_证据摘要.md"
    section_path = reports_dir / "本期财报体检_成文框架.md"
    config_path = input_dir / "本期财报体检配置.json"
    chart_paths = [reports_dir / "图表" / name for name in HEALTH_CHARTS]
    checks: list[dict[str, Any]] = []

    def add(check_id: str, status: str, detail: str) -> None:
        checks.append({"id": check_id, "status": status, "detail": detail})

    required_files = ("利润表_按报告期.csv", "资产负债表_按报告期.csv", "现金流量表_按报告期.csv")
    for filename in required_files:
        add(f"required_{filename}", "PASS" if (data_dir / filename).is_file() else "FAIL", f"data/{filename}")
    loaded_config, config_error = _load_json(config_path) if config_path.is_file() else (None, "缺少配置文件")
    add("config_json", "PASS" if loaded_config is not None else "FAIL", config_error or "配置可解析")

    artifacts_missing = (not evidence_path.is_file() or not summary_path.is_file() or not section_path.is_file()
                         or any(not path.is_file() for path in chart_paths))
    if (artifacts_missing or refresh) and all((data_dir / name).is_file() for name in required_files):
        try:
            run(project_dir)
        except Exception as exc:
            add("evidence_generation", "FAIL", f"证据包生成失败: {exc}")
    evidence, error = _load_json(evidence_path) if evidence_path.is_file() else (None, "证据 JSON 不存在")
    add("evidence_json", "PASS" if evidence is not None else "FAIL", error or "证据 JSON 可解析")
    if evidence is None:
        return checks, 1

    period = evidence.get("report_period", {})
    add("current_period", "PASS" if period.get("current") else "FAIL", str(period.get("current") or "缺少本期报告期"))
    add("comparable_period", "PASS" if period.get("yoy") else "FAIL", str(period.get("yoy") or "缺少同比可比期"))
    hard_limits = [item for item in evidence.get("limitations", []) if item.get("severity") == "fail"]
    add("period_limitations", "FAIL" if hard_limits else "PASS", "; ".join(item.get("id", "") for item in hard_limits) or "无期间硬失败")

    convention = evidence.get("display_convention", {})
    add("display_convention", "PASS" if convention.get("amount") and convention.get("ratio") else "FAIL", "金额/比例展示口径")
    required_top = (
        "schema_version", "report_period", "income_statement", "balance_sheet", "cash_flow", "bridges",
        "signals", "industry_context", "cash_flow_diagnosis", "profit_diagnosis", "inventory_review",
        "financial_asset_review", "management_evidence", "forecast_impact", "limitations", "input_fingerprint",
    )
    missing_top = [key for key in required_top if key not in evidence]
    schema_ok = not missing_top and str(evidence.get("schema_version")) == "1.0"
    add("json_schema", "PASS" if schema_ok else "FAIL", "关键问题 JSON 契约完整" if schema_ok else "缺少/错误字段: " + ", ".join(missing_top or ["schema_version"]))

    type_errors = _numeric_fields_valid(evidence.get("income_statement", {}), "income_statement")
    type_errors += _numeric_fields_valid(evidence.get("balance_sheet", {}), "balance_sheet")
    type_errors += _numeric_fields_valid(evidence.get("cash_flow", {}), "cash_flow")
    add("json_field_types", "PASS" if not type_errors else "FAIL", "金额和比例字段类型合法" if not type_errors else "字段类型异常: " + ", ".join(type_errors[:5]))

    signals = evidence.get("signals", []) if isinstance(evidence.get("signals"), list) else []
    signal_errors = [
        str(index) for index, signal in enumerate(signals)
        if not isinstance(signal, dict) or not signal.get("id") or not signal.get("evidence_id")
        or signal.get("status") not in {"triggered", "not_triggered", "indeterminate"}
        or signal.get("direction") not in {"positive", "negative", "neutral"}
        or not isinstance(signal.get("source_fields"), list)
    ]
    add("signal_schema", "FAIL" if signal_errors else "PASS", "信号字段契约完整" if not signal_errors else "信号字段异常: " + ", ".join(signal_errors[:5]))
    impact = evidence.get("forecast_impact", {})
    invalid_impacts = [key for key in ("revenue", "profit", "cash_flow", "valuation_risk") if impact.get(key) not in {"上调", "维持", "下调", "待观察"}]
    add("forecast_impact_schema", "FAIL" if invalid_impacts else "PASS", "预测影响枚举合法" if not invalid_impacts else "非法枚举: " + ", ".join(invalid_impacts))

    missing_provenance: list[str] = []
    for section_name in ("income_statement", "balance_sheet", "cash_flow"):
        records = evidence.get(section_name, {}).get("evidence_records", {})
        for scope, values in records.items():
            if isinstance(values, dict):
                missing_provenance.extend(
                    f"{section_name}.{scope}.{field}" for field, record in values.items()
                    if not isinstance(record, dict) or not record.get("evidence_id") or not record.get("source_file")
                )
    add("evidence_provenance", "FAIL" if missing_provenance else "PASS", "核心字段来源和 evidence_id 完整" if not missing_provenance else "缺少: " + ", ".join(missing_provenance[:5]))

    fingerprint = evidence.get("input_fingerprint", {})
    current_fp = fingerprint_files(data_dir, config_path)
    fp_ok = fingerprint.get("digest") == current_fp.get("digest")
    add("input_fingerprint", "PASS" if fp_ok else "FAIL", "输入文件指纹一致" if fp_ok else "输入已变化，证据包需要刷新")

    try:
        recalculated = build_health_report(data_dir, project_dir.name, loaded_config or default_config())
        equal = _canonical(recalculated) == _canonical(evidence)
        add("recalculation", "PASS" if equal else "FAIL", "证据包核心结果可复算" if equal else "JSON 与当前三表重新计算结果不一致")
    except Exception as exc:
        add("recalculation", "FAIL", f"无法重新计算: {exc}")

    cash_diag = evidence.get("cash_flow_diagnosis", {})
    profit_diag = evidence.get("profit_diagnosis", {})
    inventory = evidence.get("inventory_review", {})
    finance = evidence.get("financial_asset_review", {})
    management = evidence.get("management_evidence", {})
    if cash_diag.get("status") == "needs_explanation":
        add("cash_flow_explanation", "WARN", "经营现金流下降超出已识别季节性，需要原因分析和附注核实")
    elif cash_diag.get("status") in {"indeterminate", None}:
        add("cash_flow_explanation", "WARN", "现金流诊断数据不足，需明确披露解释缺口")
    else:
        add("cash_flow_explanation", "PASS", f"现金流状态：{cash_diag.get('status')}")
    if profit_diag.get("status") == "volatile":
        add("profit_volatility", "WARN", "利润大幅波动，报告需拆分主营和非主营因素")
    elif profit_diag.get("status") == "indeterminate":
        add("profit_volatility", "WARN", "利润可比数据不足，报告需明确归因限制")
    else:
        add("profit_volatility", "PASS", "利润未达到大幅波动重点解释阈值")
    if inventory.get("applicable"):
        add("inventory_review", "PASS" if inventory.get("status") not in {None, "indeterminate"} else "WARN", f"适用存货检查，结论：{inventory.get('status') or '数据不足'}")
    else:
        add("inventory_review", "PASS", "当前行业不适用自动存货专项检查")
    if finance.get("status") == "needs_review":
        add("financial_asset_review", "WARN", "非主营投资或金融资产贡献达到关注程度，需要附注核实")
    elif finance.get("status") == "indeterminate":
        add("financial_asset_review", "WARN", "金融资产字段不足，无法完整判断")
    else:
        add("financial_asset_review", "PASS", f"金融资产检查状态：{finance.get('status') or '待核实'}")
    add("management_evidence", "PASS" if management.get("status") == "available" else "WARN", "已取得本期管理层重点原文" if management.get("status") == "available" else "本期管理层解释未取得，不阻断体检")
    industry = evidence.get("industry_context", {})
    add("industry_profile", "PASS" if industry.get("configured") else "WARN", "行业画像已配置" if industry.get("configured") else "行业画像未配置，关闭行业特定存货结论")

    if not summary_path.is_file():
        add("evidence_summary", "FAIL", "缺少 Markdown 证据摘要")
    else:
        summary_text = summary_path.read_text(encoding="utf-8")
        digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        try:
            expected_summary = render_evidence(evidence, digest)
            summary_matches = summary_text.replace("\r\n", "\n") == expected_summary.replace("\r\n", "\n")
            summary_detail = "摘要与 JSON 可复算一致" if summary_matches else "摘要与 JSON 生成结果不一致"
        except Exception as exc:
            summary_matches = False
            summary_detail = f"无法从 JSON 复算摘要: {exc}"
        add("summary_consistency", "PASS" if summary_matches else "FAIL", summary_detail)
        add("summary_period", "PASS" if str(period.get("current") or "—") in summary_text else "FAIL", "摘要包含本期报告期")
        key_ids = _key_signal_ids(evidence)
        missing_ids = [signal_id for signal_id in key_ids if signal_id not in summary_text]
        add("summary_key_signals", "FAIL" if missing_ids else "PASS", "摘要缺少: " + ", ".join(missing_ids) if missing_ids else "关键问题信号均在摘要中")

    report_candidates = [report] if report else sorted(reports_dir.glob("*_分析报告.md"))
    report_path = report_candidates[0] if report_candidates else None
    if report_path and report_path.is_file():
        report_text = report_path.read_text(encoding="utf-8")
        report_section = _report_section(report_text)
        missing_sections = [section for section in REQUIRED_REPORT_SECTIONS if section not in report_text]
        add("report_section", "FAIL" if missing_sections else "PASS", "缺少: " + ", ".join(missing_sections) if missing_sections else "关键问题导向 §4.3 小节完整")
        add("report_json_reference", "PASS" if "本期财报体检.json" in report_section else "FAIL", "主报告引用体检 JSON")
        triggered = [signal for signal in signals if signal.get("status") in {"triggered", "indeterminate"} and signal.get("id") in _key_signal_ids(evidence) and _is_applicable_signal(signal)]
        missing_triggered = [signal.get("id") for signal in triggered if not _contains_signal(report_section, signal)]
        add("report_key_signals", "FAIL" if missing_triggered else "PASS", "缺少: " + ", ".join(missing_triggered) if missing_triggered else "触发的关键问题均已用业务语言披露")
        missing_impacts = [key for key in ("revenue", "profit", "cash_flow", "valuation_risk") if str(impact.get(key)) not in report_section]
        add("forecast_impact", "FAIL" if missing_impacts else "PASS", "缺少: " + ", ".join(missing_impacts) if missing_impacts else "预测影响字段完整")
        if cash_diag.get("status") == "needs_explanation" and "原因分析结论" not in report_section:
            add("report_cash_reason_detail", "FAIL", "经营现金流下降但正文没有原因分析或解释缺口")
        else:
            add("report_cash_reason_detail", "PASS", "现金流原因分析或解释缺口已披露")
        if management.get("status") != "available":
            add("report_management_limitation", "PASS" if "本期管理层解释未取得" in report_section else "WARN", "已披露管理层原文缺失" if "本期管理层解释未取得" in report_section else "管理层解释缺失，报告建议明确披露")
        leaked = [pattern for pattern in ("source_fields", "income.", "balance.", "cash.") if pattern in report_section]
        add("report_human_readable", "FAIL" if leaked else "PASS", "§4.3 未发现内部字段路径" if not leaked else "§4.3 含内部字段路径: " + ", ".join(leaked))
        if inventory.get("applicable"):
            inventory_words = ("正常备货", "订单/预收支持", "需要观察", "存在减值压力", "无法判断", "当前行业不适用")
            add("report_inventory_conclusion", "PASS" if any(word in report_section for word in inventory_words) else "FAIL", "适用存货检查结论已披露")
        if finance.get("status") == "needs_review":
            add("report_financial_asset_conclusion", "PASS" if "非主营投资" in report_section else "FAIL", "重要非主营投资风险已披露")
    else:
        add("report_section", "FAIL", "未找到主报告，无法核验 §4.3")

    charts_ok = all(path.is_file() for path in chart_paths)
    add("health_charts", "PASS" if charts_ok else "FAIL", "五张固定体检图均存在" if charts_ok else "缺少: " + ", ".join(path.name for path in chart_paths if not path.is_file()))
    layout_path=reports_dir/'本期财报体检_图表排版审核.json'
    layout,error=_load_json(layout_path)
    layout_errors=[]
    for path in chart_paths:
        entry=(layout or {}).get(path.name,{})
        gaps=[entry.get('header_gap_pt'),entry.get('footer_gap_pt'),*entry.get('row_gaps_pt',[])]
        if (entry.get('number_format')!={'max_decimal_places':2,'small_nonzero':'inequality','trim_trailing_zeros':True}
            or entry.get('number_format_violations') != []):
            layout_errors.append(path.name+'：数字格式未审计或超过2位小数')
        if (not entry.get('measured') or entry.get('text_collisions',[]) or entry.get('text_out_of_bounds',[]) or
            any(not isinstance(v,(int,float)) or not 3<=v<=26 for v in gaps) or
            not path.is_file() or entry.get('png_sha256')!=hashlib.sha256(path.read_bytes()).hexdigest()):
            layout_errors.append(path.name)
    add('health_chart_layout','FAIL' if layout_errors or error else 'PASS',
        error or ('排版间距/文字碰撞/PNG指纹不合格：'+','.join(layout_errors) if layout_errors else '五张体检图按实际边界排布，间距、文字与PNG指纹检查通过'))
    if section_path.is_file():
        section_text = section_path.read_text(encoding="utf-8")
        digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        try:
            expected_section = render_report_section(evidence, digest)
            matches = section_text.replace("\r\n", "\n") == expected_section.replace("\r\n", "\n")
            add("report_framework_consistency", "PASS" if matches else "FAIL", "成文框架与 JSON 可复算一致" if matches else "成文框架与 JSON 生成结果不一致")
        except Exception as exc:
            add("report_framework_consistency", "FAIL", f"无法复算成文框架: {exc}")
    else:
        add("report_framework_consistency", "FAIL", "缺少本期财报体检_成文框架.md")
    if report_path and report_path.is_file():
        report_section = _report_section(report_path.read_text(encoding="utf-8"))
        missing_charts = [path.name for path in chart_paths if path.name not in report_section]
        add("report_health_charts", "FAIL" if missing_charts else "PASS", "§4.3 已嵌入五张体检图" if not missing_charts else "§4.3 缺少: " + ", ".join(missing_charts))

    return checks, 1 if any(item["status"] == "FAIL" for item in checks) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="G22 本期财报体检门控")
    parser.add_argument("--dir", required=True, help="批次目录")
    parser.add_argument("--report", default="", help="主报告相对路径")
    parser.add_argument("--refresh", action="store_true", help="先重新生成证据包")
    args = parser.parse_args()
    report = Path(args.report) if args.report else None
    if report and not report.is_absolute():
        report = Path(args.dir) / report
    checks, exit_code = _check(Path(args.dir), report, args.refresh)
    print("\nG22 本期财报体检门控")
    for item in checks:
        print(f"[{item['status']}] {item['id']}: {item['detail']}")
    print("G22: FAIL" if exit_code else "G22: PASS（WARN 项不阻断交付）")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
