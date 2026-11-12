# -*- coding: utf-8 -*-
"""Deterministic current-period financial health checks.

This module is deliberately independent from the report writer and the gate.
It turns the three statement CSV contract into a traceable evidence object:
period selection, comparable-period values, derived ratios, bridges and
multi-signal flags.  It does not label a company as fraudulent.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import textwrap
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

SCHEMA_VERSION = "1.0"
DEFAULT_CONFIG = {
    "schema_version": SCHEMA_VERSION,
    "rule_version": "financial-health-v2-key-findings",
    "market": "auto",
    "period_policy": "yoy_primary_explainable_qoq",
    "thresholds": {
        "growth_gap_pp": 10.0,
        "margin_decline_pp": 2.0,
        "cash_conversion_floor": 80.0,
        "cash_conversion_decline": 20.0,
        "one_time_profit_share": 20.0,
        "material_non_operating_share": 10.0,
        "assetization_growth_pct": 30.0,
        "inventory_growth_gap_pp": 10.0,
        "bridge_residual_pct": 5.0,
        "seasonality_pct": 80.0,
        "seasonality_normal_pct": 60.0,
        "ocf_decline_pct": 20.0,
        "profit_change_pct": 20.0,
        "financial_asset_profit_share": 10.0,
        "financial_asset_asset_share": 5.0,
        "financial_asset_growth_pct": 20.0,
    },
    "industry_profile": {
        "industry": "",
        "cash_flow_seasonality": "unknown",
        "inventory_review": "auto",
        "financial_asset_review": "auto",
        "cash_flow_note": "",
        "inventory_note": "",
        "overrides": {},
    },
    "filing_policy": {
        "prefer_current_period": True,
        "extensions": [".pdf", ".txt", ".html"],
        "max_excerpts": 12,
    },
    "data_source_policy": {
        "required": ["利润表_按报告期.csv", "资产负债表_按报告期.csv", "现金流量表_按报告期.csv"],
        "optional": ["主要财务指标_按报告期.csv", "主要财务指标_按单季度.csv", "财报附注或PDF"],
        "evidence_level": "L3",
        "independent_cross_validation": "仅存在独立数据生产方交叉验证时标记L4",
    },
    "notes_policy": "three_statements_required_notes_enhance",
}

STATEMENT_FILES = {
    "income_statement": "利润表_按报告期.csv",
    "balance_sheet": "资产负债表_按报告期.csv",
    "cash_flow": "现金流量表_按报告期.csv",
    "indicators_annual": "主要财务指标_按报告期.csv",
    "indicators_quarter": "主要财务指标_按单季度.csv",
}

ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "income": {
        "revenue": ("TOTAL_OPERATE_INCOME", "OPERATE_INCOME", "营业总收入", "营业收入"),
        "operating_cost": ("OPERATE_COST", "营业成本"),
        "total_cost": ("TOTAL_OPERATE_COST", "营业总成本"),
        "operating_profit": ("OPERATE_PROFIT", "营业利润"),
        "total_profit": ("TOTAL_PROFIT", "利润总额"),
        "net_profit": ("NETPROFIT", "净利润"),
        "parent_net_profit": ("PARENT_NETPROFIT", "归母净利润"),
        "minority_interest": ("MINORITY_INTEREST", "少数股东损益"),
        "deduct_parent_net_profit": ("DEDUCT_PARENT_NETPROFIT", "扣非净利润"),
        "basic_eps": ("BASIC_EPS", "基本每股收益", "EPS"),
        "selling_expense": ("SELLING_EXPENSE", "SALE_EXPENSE", "销售费用"),
        "administrative_expense": ("ADMIN_EXPENSE", "MANAGE_EXPENSE", "管理费用"),
        "rd_expense": ("RD_EXPENSE", "RESEARCH_EXPENSE", "ME_RESEARCH_EXPENSE", "研发费用"),
        "finance_expense": ("FINANCE_EXPENSE", "财务费用"),
        "investment_income": ("INVEST_INCOME", "投资收益"),
        "fair_value_change": ("FAIRVALUE_CHANGE_INCOME", "公允价值变动收益"),
        "asset_disposal_income": ("ASSET_DISPOSAL_INCOME", "资产处置收益"),
        "other_income": ("OTHER_INCOME", "其他收益"),
        "exchange_income": ("EXCHANGE_INCOME", "汇兑收益", "汇兑损益"),
        "asset_impairment": ("ASSET_IMPAIRMENT_LOSS", "资产减值损失"),
        "credit_impairment": ("CREDIT_IMPAIRMENT_LOSS", "信用减值损失"),
        "income_tax": ("INCOME_TAX", "所得税费用"),
    },
    "balance": {
        "accounts_receivable": ("ACCOUNTS_RECE", "应收账款"),
        "notes_receivable": ("NOTE_RECE", "应收票据"),
        "contract_asset": ("CONTRACT_ASSET", "合同资产"),
        "inventory": ("INVENTORY", "存货"),
        "raw_material_inventory": ("INVENTORY_RAW_MATERIAL", "RAW_MATERIAL", "原材料"),
        "work_in_progress_inventory": ("INVENTORY_WIP", "WORK_IN_PROGRESS", "在产品"),
        "finished_goods_inventory": ("INVENTORY_FINISHED_GOODS", "FINISHED_GOODS", "库存商品", "产成品"),
        "inventory_impairment_reserve": ("INVENTORY_IMPAIRMENT_RESERVE", "存货跌价准备"),
        "contract_liability": ("CONTRACT_LIAB", "合同负债"),
        "accounts_payable": ("ACCOUNTS_PAYABLE", "应付账款"),
        "notes_payable": ("NOTE_PAYABLE", "应付票据"),
        "other_receivables": ("OTHER_RECE", "其他应收款"),
        "other_payables": ("OTHER_PAYABLE", "其他应付款"),
        "cash": ("MONETARYFUNDS", "货币资金"),
        "restricted_cash": ("RESTRICTED_CASH", "受限资金", "受限货币资金"),
        "short_loan": ("SHORT_LOAN", "短期借款"),
        "long_loan": ("LONG_LOAN", "长期借款"),
        "bond_payable": ("BOND_PAYABLE", "应付债券"),
        "short_finance_payable": ("SHORT_FIN_PAYABLE", "短期融资款"),
        "lease_liability": ("LEASE_LIAB", "租赁负债"),
        "goodwill": ("GOODWILL", "商誉"),
        "intangible_asset": ("INTANGIBLE_ASSET", "无形资产"),
        "development_expense": ("DEVELOP_EXPENSE", "开发支出"),
        "construction_in_progress": ("CONSTRUCTION_IN_PROGRESS", "CIP", "在建工程"),
        "trading_financial_assets": ("TRADE_FINASSET_NOTFVTPL", "TRADE_FINASSET", "交易性金融资产"),
        "fair_value_financial_assets": ("FAIR_VALUE_FINASSET", "公允价值计量金融资产合计"),
        "other_noncurrent_financial_assets": ("OTHER_NONCURRENT_FINASSET", "其他非流动金融资产"),
        "other_equity_investment": ("OTHER_EQUITY_INVEST", "其他权益工具投资"),
        "long_equity_investment": ("LONG_EQUITY_INVEST", "长期股权投资"),
        "available_for_sale_financial_assets": ("AVAILABLE_SALE_FINASSET", "可供出售金融资产"),
        "total_assets": ("TOTAL_ASSETS", "资产总计"),
        "total_liabilities": ("TOTAL_LIABILITIES", "负债合计"),
        "parent_equity": ("TOTAL_PARENT_EQUITY", "归属于母公司股东权益", "归母权益"),
    },
    "cash": {
        "sales_cash": ("SALES_SERVICES", "销售商品、提供劳务收到的现金"),
        "operating_cash_flow": ("NETCASH_OPERATE", "经营活动产生的现金流量净额"),
        "investing_cash_flow": ("NETCASH_INVEST", "投资活动产生的现金流量净额"),
        "financing_cash_flow": ("NETCASH_FINANCE", "筹资活动产生的现金流量净额"),
        "capex": ("CONSTRUCT_LONG_ASSET", "购建固定资产、无形资产和其他长期资产支付的现金"),
        "dividends_paid": ("ASSIGN_DIVIDEND_PORFIT", "分配股利、利润或偿付利息支付的现金"),
        "net_profit": ("NETPROFIT", "净利润"),
        "minority_interest": ("MINORITY_INTEREST", "少数股东损益"),
        "depreciation": ("FA_IR_DEPR", "固定资产折旧"),
        "intangible_amortization": ("IA_AMORTIZE", "无形资产摊销"),
        "asset_impairment": ("ASSET_IMPAIRMENT", "资产减值准备"),
        "receivable_change": ("OPERATE_RECE_REDUCE", "经营性应收项目的减少"),
        "inventory_change": ("INVENTORY_REDUCE", "存货的减少"),
        "payable_change": ("OPERATE_PAYABLE_ADD", "经营性应付项目的增加"),
        "staff_paid": ("PAY_STAFF_CASH", "支付给职工以及为职工支付的现金"),
        "tax_paid": ("PAY_ALL_TAX", "支付的各项税费"),
        "other_operating_paid": ("PAY_OTHER_OPERATE", "支付其他与经营活动有关的现金"),
        "begin_cash": ("BEGIN_CCE", "期初现金及现金等价物余额", "BEGIN_CASH"),
        "end_cash": ("END_CCE", "期末现金及现金等价物余额", "END_CASH"),
        "cash_change": ("CCE_ADD", "现金及现金等价物净增加额"),
        "fx_effect": ("RATE_CHANGE_EFFECT", "汇率变动对现金及现金等价物的影响"),
    },
    "indicator": {
        "gross_margin": ("GROSS_PROFIT_RATIO", "XSMLL", "销售毛利率", "毛利率"),
        "net_margin": ("NET_PROFIT_RATIO", "XSJLL", "销售净利率", "净利率"),
        "roe": ("ROEJQ", "净资产收益率"),
        "tax_rate": ("TAXRATE", "税负率"),
        "total_share": ("TOTAL_SHARE", "总股本"),
    },
}


INDUSTRY_PROFILES: dict[str, dict[str, Any]] = {
    "consumer": {
        "label": "消费品",
        "cash_flow_seasonality": "normal",
        "inventory_review": True,
        "financial_asset_review": True,
        "cash_flow_note": "关注渠道回款、促销备货和现金流稳定性。",
        "inventory_note": "关注库龄、成品和渠道库存，以及跌价准备覆盖。",
    },
    "manufacturing": {
        "label": "制造业",
        "cash_flow_seasonality": "normal",
        "inventory_review": True,
        "financial_asset_review": True,
        "cash_flow_note": "关注原材料采购、应付账款和订单交付。",
        "inventory_note": "区分订单支持的原材料备货和产成品沉淀。",
    },
    "power_equipment": {
        "label": "电力设备/工程项目",
        "cash_flow_seasonality": "q4_collection",
        "inventory_review": False,
        "financial_asset_review": True,
        "cash_flow_note": "项目交付和年末回款可能造成季度现金流集中。",
        "inventory_note": "存货需要结合项目订单和交付周期单独判断。",
    },
    "utility": {
        "label": "公用事业",
        "cash_flow_seasonality": "stable",
        "inventory_review": False,
        "financial_asset_review": True,
        "cash_flow_note": "经营现金流通常较稳定，持续明显下降需解释。",
        "inventory_note": "通常不是核心风险，除非出现异常增长或减值迹象。",
    },
    "railway": {
        "label": "铁路运输",
        "cash_flow_seasonality": "normal",
        "inventory_review": False,
        "financial_asset_review": True,
        "cash_flow_note": "铁路运输现金流受货运量、结算时点、检修和季节性影响；单季波动需结合运量与应收结算解释。",
        "inventory_note": "一般企业存货专项不适用；重点观察固定资产投资、检修支出、应收结算和产业投资。",
    },
    "banking": {
        "label": "银行/金融",
        "cash_flow_seasonality": "financial",
        "inventory_review": False,
        "financial_asset_review": False,
        "cash_flow_note": "一般企业 OCF 口径不适用于金融机构。",
        "inventory_note": "不适用一般企业存货检查。",
    },
    "generic": {
        "label": "未配置行业",
        "cash_flow_seasonality": "unknown",
        "inventory_review": False,
        "financial_asset_review": True,
        "cash_flow_note": "行业现金流季节性未配置。",
        "inventory_note": "行业未配置，关闭自动存货风险结论。",
    },
}


INDUSTRY_ALIASES = {
    "消费": "consumer", "消费品": "consumer", "consumer": "consumer",
    "制造": "manufacturing", "制造业": "manufacturing", "manufacturing": "manufacturing",
    "电力设备": "power_equipment", "电气设备": "power_equipment", "工程项目": "power_equipment",
    "电力设备/工程项目": "power_equipment", "power_equipment": "power_equipment",
    "公用事业": "utility", "utility": "utility",
    "铁路运输": "railway", "铁路": "railway", "railway": "railway",
    "银行": "banking", "金融": "banking", "banking": "banking",
}


def default_config() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_CONFIG, ensure_ascii=False))


def _merge_config(config: dict[str, Any] | None) -> dict[str, Any]:
    merged = default_config()
    if not config:
        return merged
    for key, value in config.items():
        if key == "thresholds" and isinstance(value, dict):
            merged["thresholds"].update(value)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def resolve_industry_profile(config: dict[str, Any] | None = None, project_name: str = "") -> dict[str, Any]:
    cfg = config or {}
    requested = str(cfg.get("industry_profile", {}).get("industry") or "").strip()
    profile_key = INDUSTRY_ALIASES.get(requested, requested if requested in INDUSTRY_PROFILES else "generic")
    base = dict(INDUSTRY_PROFILES.get(profile_key, INDUSTRY_PROFILES["generic"]))
    overrides = cfg.get("industry_profile", {}).get("overrides", {})
    if isinstance(overrides, dict):
        base.update(overrides)
    base["key"] = profile_key
    base["configured"] = bool(requested and profile_key != "generic")
    base["industry"] = requested or base.get("label", "未配置行业")
    if base.get("inventory_review") == "auto":
        base["inventory_review"] = False if not base["configured"] else True
    if base.get("financial_asset_review") == "auto":
        base["financial_asset_review"] = True
    base["inventory_review"] = bool(base.get("inventory_review"))
    base["financial_asset_review"] = bool(base.get("financial_asset_review"))
    base["profile_source"] = "company_override" if overrides else ("industry_config" if base["configured"] else "generic_default")
    return base


def write_default_config(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(default_config(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _norm_key(value: Any) -> str:
    return re.sub(r"[\s_\-（）()]+", "", str(value or "").strip()).lower()


def find_column(df: pd.DataFrame | None, aliases: Iterable[str]) -> str | None:
    if df is None:
        return None
    columns = list(df.columns)
    normalized = {_norm_key(c): c for c in columns}
    for alias in aliases:
        if _norm_key(alias) in normalized:
            return normalized[_norm_key(alias)]
    for alias in aliases:
        key = _norm_key(alias)
        for norm, original in normalized.items():
            # Machine identifiers must match exactly: INVENTORY is not a
            # substitute for INVENTORY_IMPAIRMENT_RESERVE.  Chinese headers
            # may append units, so allow a directional descriptive match.
            if key and re.search(r"[\u4e00-\u9fff]", key) and key in norm:
                return original
    return None


def parse_number(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip().replace(",", "").replace("，", "")
    if text in {"", "-", "—", "–", "N/A", "nan", "None", "null"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        number = float(match.group(0))
    except ValueError:
        return None
    return -abs(number) if negative else number


def _date_column(df: pd.DataFrame | None) -> str | None:
    return find_column(df, ("REPORT_DATE", "报告期", "报告日期", "end_date"))


def _dates(df: pd.DataFrame | None) -> list[date]:
    if df is None:
        return []
    col = _date_column(df)
    if not col:
        return []
    return sorted({x.date() for x in pd.to_datetime(df[col], errors="coerce").dropna()})


def _row(df: pd.DataFrame | None, period: date | None) -> pd.Series | None:
    if df is None or period is None:
        return None
    col = _date_column(df)
    if not col:
        return None
    parsed = pd.to_datetime(df[col], errors="coerce").dt.date
    found = df.loc[parsed == period]
    return found.iloc[0] if not found.empty else None


def _value(df: pd.DataFrame | None, row: pd.Series | None, aliases: Iterable[str]) -> tuple[float | None, str | None]:
    # Providers retain empty legacy columns alongside populated aliases.
    # Select the first non-null alias, preserving legitimate zero values.
    aliases = tuple(aliases)
    fallback = find_column(df, aliases)
    if row is None:
        return None, fallback
    for alias in aliases:
        col = find_column(df, (alias,))
        if col:
            value = parse_number(row.get(col))
            if value is not None:
                return value, col
    return None, fallback


def _text_value(df: pd.DataFrame | None, row: pd.Series | None, aliases: Iterable[str]) -> str | None:
    col = find_column(df, aliases)
    if row is None or not col:
        return None
    value = row.get(col)
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    return str(value).strip()


def _period_type(period: date, report_type: str = "") -> str:
    label = report_type.lower()
    if "半年" in report_type or "中报" in report_type or period.month == 6:
        return "semiannual"
    if "三季" in report_type or period.month == 9:
        return "q3"
    if "年报" in report_type or "annual" in label or period.month == 12:
        return "annual"
    return "q1"


def _report_type(df: pd.DataFrame | None, row: pd.Series | None) -> str:
    if row is None:
        return ""
    col = find_column(df, ("REPORT_TYPE", "报告类型", "REPORT_DATE_NAME"))
    return str(row.get(col, "")) if col else ""


def _prior_same_year_period(df: pd.DataFrame | None, current: date) -> date | None:
    periods = [p for p in _dates(df) if p.year == current.year and p < current]
    return periods[-1] if periods else None


def _previous_period(df: pd.DataFrame | None, current: date) -> date | None:
    periods = [p for p in _dates(df) if p < current]
    return periods[-1] if periods else None


def _same_period_last_year(current: date) -> date:
    try:
        return current.replace(year=current.year - 1)
    except ValueError:
        return current.replace(year=current.year - 1, day=28)


def safe_div(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def change_pct(current: float | None, previous: float | None) -> float | None:
    if not isinstance(current, (int, float)) or not isinstance(previous, (int, float)) or previous == 0:
        return None
    return (current - previous) / abs(previous) * 100.0


def change_pp(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return current - previous


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if hasattr(value, "item"):
        return _clean(value.item())
    return value


def fingerprint_files(data_dir: Path, config_path: Path | None = None) -> dict[str, Any]:
    files: dict[str, str] = {}
    paths = [data_dir / name for name in STATEMENT_FILES.values()]
    paths.extend(sorted(data_dir.glob("*.pdf")))
    paths.extend(sorted(data_dir.glob("*.txt")))
    paths.extend(sorted(data_dir.glob("*.html")))
    if config_path:
        paths.append(config_path)
    for path in paths:
        if path.exists() and path.is_file():
            files[str(path.relative_to(data_dir.parent) if path.is_relative_to(data_dir.parent) else path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256()
    for name, value in sorted(files.items()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(value.encode("ascii"))
        digest.update(b"\n")
    return {"algorithm": "sha256", "files": files, "digest": digest.hexdigest()}


def _load_csv(data_dir: Path, filename: str) -> pd.DataFrame | None:
    path = data_dir / filename
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, dtype=str)
    except Exception:
        return None
    return None if df.empty else df


def _section_values(df: pd.DataFrame | None, row: pd.Series | None, group: str, fields: Iterable[str]) -> tuple[dict[str, float | None], dict[str, str | None]]:
    values: dict[str, float | None] = {}
    columns: dict[str, str | None] = {}
    for field in fields:
        value, col = _value(df, row, ALIASES[group][field])
        values[field] = value
        columns[field] = col
    return values, columns


def _evidence_map(values: dict[str, Any], columns: dict[str, str | None], source_file: str,
                  period: date | None, section: str, unit: str = "原始货币单位") -> dict[str, dict[str, Any]]:
    """Attach stable field-level provenance while keeping numeric values easy to consume."""
    return {
        field: _record(field, value, unit, source_file, columns.get(field), period, section=section)
        for field, value in values.items()
        if field != "unit" and not isinstance(value, dict)
    }


def _prior_balance_period(df: pd.DataFrame | None, current: date, period_type: str) -> date | None:
    """Select the preceding balance-sheet date for the current reporting cadence."""
    if period_type == "annual":
        candidate = _same_period_last_year(current)
        return candidate if _row(df, candidate) is not None else _previous_period(df, current)
    if period_type == "q1":
        candidate = date(current.year - 1, 12, 31)
    elif period_type == "semiannual":
        candidate = date(current.year, 3, 31)
    else:
        candidate = date(current.year, 6, 30)
    return candidate if _row(df, candidate) is not None else _previous_period(df, current)


def _single_period_value(df: pd.DataFrame | None, current: date, field: str, group: str) -> float | None:
    row = _row(df, current)
    current_value, _ = _value(df, row, ALIASES[group][field])
    if current_value is None:
        return None
    prior = _prior_same_year_period(df, current)
    if prior is None or current.month == 12:
        return current_value
    prior_value, _ = _value(df, _row(df, prior), ALIASES[group][field])
    return None if prior_value is None else current_value - prior_value


def _single_period_section(df: pd.DataFrame | None, current: date, group: str, fields: Iterable[str]) -> tuple[dict[str, float | None], dict[str, str | None]]:
    values: dict[str, float | None] = {}
    columns: dict[str, str | None] = {}
    for field in fields:
        values[field] = _single_period_value(df, current, field, group)
        columns[field] = find_column(df, ALIASES[group][field])
    return values, columns


def _single_period_metadata(df: pd.DataFrame | None, current: date | None) -> dict[str, Any]:
    if current is None:
        return {"method": "unavailable", "status": "indeterminate", "prior_cumulative_period": None}
    if current.month == 12:
        return {"method": "direct_annual", "status": "comparable", "prior_cumulative_period": None}
    prior = _prior_same_year_period(df, current)
    if prior is None:
        status = "comparable" if current.month == 3 else "indeterminate"
        return {"method": "direct_first_period" if current.month == 3 else "cumulative_difference",
                "status": status, "prior_cumulative_period": None}
    return {"method": "cumulative_difference", "status": "comparable",
            "prior_cumulative_period": prior.isoformat()}


def _ratio_metrics(income: dict[str, float | None], indicators: dict[str, float | None]) -> dict[str, float | None]:
    revenue = income.get("revenue")
    cost = income.get("operating_cost")
    gross_margin = indicators.get("gross_margin")
    if gross_margin is None:
        gross_margin = safe_div((revenue - cost) if revenue is not None and cost is not None else None, revenue)
        if gross_margin is not None:
            gross_margin *= 100.0
    op_margin = safe_div(income.get("operating_profit"), revenue)
    net_margin = indicators.get("net_margin")
    if net_margin is None:
        net_margin = safe_div(income.get("parent_net_profit"), revenue)
        if net_margin is not None:
            net_margin *= 100.0
    total_expense = income.get("total_cost")
    expense_ratio = safe_div(total_expense, revenue)
    if expense_ratio is not None:
        expense_ratio *= 100.0
    return {
        "gross_margin_pct": gross_margin,
        "operating_margin_pct": op_margin * 100.0 if op_margin is not None else None,
        "net_margin_pct": net_margin,
        "total_cost_to_revenue_pct": expense_ratio,
        "tax_rate_pct": indicators.get("tax_rate"),
        "roe_pct": indicators.get("roe"),
    }


def _growth_map(current: dict[str, float | None], yoy: dict[str, float | None]) -> dict[str, float | None]:
    return {
        key: change_pct(current.get(key), yoy.get(key))
        for key, value in current.items()
        if isinstance(value, (int, float)) or value is None
    }


def _first_number(*values: Any) -> float | None:
    """Return the first non-null numeric value without treating zero as missing."""
    for value in values:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _record(name: str, value: Any, unit: str, source_file: str, source_column: str | None,
            period: date | None, evidence: str = "L3", *, section: str = "") -> dict[str, Any]:
    evidence_id = f"FH.{section or 'metric'}.{name}.{period.isoformat() if period else 'NA'}"
    return {"evidence_id": evidence_id, "value": value, "unit": unit,
            "period": period.isoformat() if period else None, "source_file": source_file,
            "source_column": source_column, "evidence_level": evidence}


def _signal(signal_id: str, direction: str, severity: str, status: str, title: str, actual: Any,
            threshold: Any, formula: str, source_fields: list[str], evidence: str = "L3",
            follow_up: str = "") -> dict[str, Any]:
    return {"id": signal_id, "evidence_id": f"FH.SIGNAL.{signal_id}", "direction": direction, "severity": severity, "status": status,
            "title": title, "actual": actual, "threshold": threshold, "formula": formula,
            "source_fields": source_fields, "evidence_level": evidence,
            "follow_up": follow_up or "结合财报附注、公司公告和下一期回款核实。"}


def _status(condition: bool | None) -> str:
    if condition is None:
        return "indeterminate"
    return "triggered" if condition else "not_triggered"


def _make_signals(current: dict[str, Any], yoy: dict[str, Any], prior_end: dict[str, Any],
                  cf_current: dict[str, Any], cf_yoy: dict[str, Any], bs_current: dict[str, Any],
                  bs_yoy: dict[str, Any], period: date, period_type: str, cfg: dict[str, Any],
                  history_q4: list[dict[str, Any]], industry_profile: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    t = {**DEFAULT_CONFIG["thresholds"], **cfg.get("thresholds", {})}
    revenue_growth = change_pct(current.get("revenue"), yoy.get("revenue"))
    receivable_current_parts = [bs_current.get("accounts_receivable"), bs_current.get("contract_asset")]
    receivable_yoy_parts = [bs_yoy.get("accounts_receivable"), bs_yoy.get("contract_asset")]
    receivable_now = sum(receivable_current_parts) if all(x is not None for x in receivable_current_parts) else None
    receivable_old = sum(receivable_yoy_parts) if all(x is not None for x in receivable_yoy_parts) else None
    receivable_growth = change_pct(receivable_now, receivable_old)
    cash_ratio = safe_div(cf_current.get("operating_cash_flow"), _first_number(current.get("parent_net_profit"), current.get("net_profit")))
    cash_ratio_yoy = safe_div(cf_yoy.get("operating_cash_flow"), _first_number(yoy.get("parent_net_profit"), yoy.get("net_profit")))
    if cash_ratio is not None:
        cash_ratio *= 100.0
    if cash_ratio_yoy is not None:
        cash_ratio_yoy *= 100.0
    ar_condition = None if None in (revenue_growth, receivable_growth, cash_ratio, cash_ratio_yoy) else (
        receivable_growth > revenue_growth + t["growth_gap_pp"] and
        (cash_ratio < t["cash_conversion_floor"] or cash_ratio < cash_ratio_yoy - t["cash_conversion_decline"])
    )
    inventory_growth = change_pct(bs_current.get("inventory"), bs_yoy.get("inventory"))
    ocf_growth = change_pct(cf_current.get("operating_cash_flow"), cf_yoy.get("operating_cash_flow"))
    inventory_applicable = bool((industry_profile or {}).get("inventory_review", False))
    inv_condition = None if not inventory_applicable or None in (revenue_growth, inventory_growth, ocf_growth) else (
        inventory_growth > revenue_growth + t["inventory_growth_gap_pp"] and ocf_growth < 0
    )
    margin_now = current.get("metrics", {})
    margin_old = yoy.get("metrics", {})
    margin_drops = [change_pp(margin_now.get(k), margin_old.get(k)) for k in ("gross_margin_pct", "operating_margin_pct", "net_margin_pct")]
    cost_ratio_change = change_pp(margin_now.get("total_cost_to_revenue_pct"), margin_old.get("total_cost_to_revenue_pct"))
    pressure_condition = None if revenue_growth is None or not any(x is not None for x in [*margin_drops, cost_ratio_change]) else (
        revenue_growth > 0 and (
            any(x is not None and x <= -t["margin_decline_pp"] for x in margin_drops)
            or (cost_ratio_change is not None and cost_ratio_change >= t["margin_decline_pp"])
        )
    )
    parent = current.get("parent_net_profit")
    non_deducted = (parent - current.get("deduct_parent_net_profit")) if parent is not None and current.get("deduct_parent_net_profit") is not None else None
    investment_components = [current.get(k) for k in ("investment_income", "fair_value_change", "asset_disposal_income", "other_income")]
    non_operating = sum(investment_components) if all(x is not None for x in investment_components) else None
    one_time_share = safe_div(abs(non_deducted), abs(parent)) * 100.0 if non_deducted is not None and parent and safe_div(abs(non_deducted), abs(parent)) is not None else None
    non_operating_share = safe_div(abs(non_operating), abs(parent)) * 100.0 if non_operating is not None and parent and safe_div(abs(non_operating), abs(parent)) is not None else None
    one_time_condition = None if one_time_share is None and non_operating_share is None else (
        (one_time_share is not None and one_time_share >= t["one_time_profit_share"])
        or (non_operating_share is not None and non_operating_share >= t["material_non_operating_share"])
    )
    asset_growth_candidates = [
        change_pct(bs_current.get("development_expense"), bs_yoy.get("development_expense")),
        change_pct(bs_current.get("intangible_asset"), bs_yoy.get("intangible_asset")),
        change_pct(bs_current.get("construction_in_progress"), bs_yoy.get("construction_in_progress")),
    ]
    asset_growth_valid = [x for x in asset_growth_candidates if x is not None]
    cap_condition = None if not asset_growth_valid else (
        sum(x >= t["assetization_growth_pct"] for x in asset_growth_valid) >= 2 or max(asset_growth_valid) >= 2 * t["assetization_growth_pct"]
    )
    impairment_values = [current.get("asset_impairment"), current.get("credit_impairment")]
    impair = sum(abs(x) for x in impairment_values) if all(x is not None for x in impairment_values) else None
    impair_share = safe_div(impair, abs(parent)) * 100.0 if impair is not None and parent and safe_div(impair, abs(parent)) is not None else None
    impairment_condition = None if impair_share is None or cash_ratio is None or cash_ratio_yoy is None else (
        impair_share >= t["material_non_operating_share"] and cash_ratio >= cash_ratio_yoy
    )
    contract_growth = change_pct(bs_current.get("contract_liability"), bs_yoy.get("contract_liability"))
    positive_condition = None if None in (contract_growth, revenue_growth, receivable_growth, ocf_growth) else (
        contract_growth > max(10.0, revenue_growth + t["growth_gap_pp"]) and
        receivable_growth <= revenue_growth + t["growth_gap_pp"] and ocf_growth >= 0
    )
    signals = [
        _signal("FH_AR_CASH_DIVERGENCE", "negative", "warn", _status(ar_condition), "应收/合同资产增长快于收入且现金转化恶化",
                 {"revenue_growth_pct": revenue_growth, "receivable_contract_growth_pct": receivable_growth, "ocf_to_profit": cash_ratio},
                 {"growth_gap_pp": t["growth_gap_pp"], "cash_conversion_floor": t["cash_conversion_floor"]},
                 "Δ(应收账款+合同资产)增速 > 收入增速+阈值 且 OCF/净利润低于下限或同比下降",
                 ["income.revenue", "balance.accounts_receivable", "balance.contract_asset", "cash.operating_cash_flow"]),
        _signal("FH_INVENTORY_PRESSURE", "negative", "warn", _status(inv_condition), "存货增长快于收入且经营现金流恶化",
                 {"revenue_growth_pct": revenue_growth, "inventory_growth_pct": inventory_growth, "ocf_growth_pct": ocf_growth},
                 {"growth_gap_pp": t["inventory_growth_gap_pp"]}, "存货增速 > 收入增速+阈值 且 OCF同比下降",
                 ["income.revenue", "balance.inventory", "cash.operating_cash_flow"]),
        _signal("FH_OPERATING_MARGIN_PRESSURE", "negative", "warn", _status(pressure_condition), "收入增长未能转化为经营利润改善",
                 {"revenue_growth_pct": revenue_growth, "margin_change_pp": margin_drops,
                  "cost_to_revenue_change_pp": cost_ratio_change},
                 {"margin_decline_pp": t["margin_decline_pp"]}, "收入同比为正且毛利率/营业利润率/净利率至少一项下降达到阈值",
                 ["income.revenue", "income.operating_profit", "income.operating_cost"]),
        _signal("FH_NON_OPERATING_PROFIT", "negative", "warn", _status(one_time_condition), "一次性或非核心收益对利润贡献较高",
                 {"non_deducted_profit_share": one_time_share, "non_operating_income": non_operating,
                  "non_operating_profit_share": non_operating_share},
                 {"one_time_profit_share": t["one_time_profit_share"],
                  "material_non_operating_share": t["material_non_operating_share"]},
                 "扣非差额/归母净利润或非核心收益/归母净利润达到阈值",
                 ["income.parent_net_profit", "income.deduct_parent_net_profit", "income.investment_income", "income.fair_value_change"]),
        _signal("FH_ASSETIZATION_REVIEW", "negative", "warn", _status(cap_condition), "开发支出/无形资产/在建工程增长异常，需核查资本化",
                 {"growth_pct": asset_growth_candidates}, {"assetization_growth_pct": t["assetization_growth_pct"]},
                 "至少两项资产化相关项目增速达到阈值，或单项达到两倍阈值",
                 ["balance.development_expense", "balance.intangible_asset", "balance.construction_in_progress", "income.rd_expense"]),
        _signal("FH_IMPAIRMENT_CLEANUP", "negative", "warn", _status(impairment_condition), "减值/信用减值较大但现金转化未同步恶化",
                 {"impairment_to_profit": impair_share, "ocf_to_profit": cash_ratio, "prior_ocf_to_profit": cash_ratio_yoy},
                 {"material_share": t["material_non_operating_share"]}, "减值合计/归母净利润达到阈值且 OCF/净利润不低于上年",
                 ["income.asset_impairment", "income.credit_impairment", "cash.operating_cash_flow"]),
        _signal("FH_CONTRACT_ORDER_SUPPORT", "positive", "info", _status(positive_condition), "合同负债增长、回款压力受控且现金流改善",
                 {"contract_liability_growth_pct": contract_growth, "revenue_growth_pct": revenue_growth, "ocf_growth_pct": ocf_growth},
                 {"growth_gap_pp": t["growth_gap_pp"]}, "合同负债增速高于收入增速+阈值、应收增速受控且OCF同比不降",
                 ["balance.contract_liability", "balance.accounts_receivable", "cash.operating_cash_flow"]),
    ]
    if period_type == "annual":
        q4_values = []
        for item in history_q4:
            if item.get("q4_ratio_pct") is not None:
                q4_values.append(item["q4_ratio_pct"])
        q4_current = next((x.get("q4_ratio_pct") for x in history_q4 if x.get("year") == period.year), None)
        if q4_current is not None:
            previous = [x.get("q4_ratio_pct") for x in history_q4 if x.get("year") != period.year and x.get("q4_ratio_pct") is not None]
            recurring = len(previous) >= 1 and all(x >= t["seasonality_pct"] for x in previous)
            q4_condition = q4_current >= t["seasonality_pct"]
            q4_severity = "info" if recurring else "warn"
            q4_title = "经营现金流Q4集中（历史常态季节性）" if recurring else "经营现金流Q4集中（需核查是否单年异常）"
            signals.append(_signal("FH_Q4_OCF_SEASONALITY", "neutral", q4_severity, _status(q4_condition), q4_title,
                                    {"q4_ratio_pct": q4_current, "history_pct": q4_values},
                                    {"seasonality_pct": t["seasonality_pct"], "normal_pct": t["seasonality_normal_pct"]},
                                    "(年报OCF-三季报累计OCF)/年报OCF >= 阈值", ["cash.operating_cash_flow"],
                                    follow_up="区分年末回款季节性与单年异常，结合合同负债和次年一季度回款核实。"))
    return signals


def _make_key_signals(cash_diagnosis: dict[str, Any], profit_diagnosis: dict[str, Any],
                      inventory_review: dict[str, Any], financial_asset_review: dict[str, Any],
                      management_evidence: dict[str, Any]) -> list[dict[str, Any]]:
    cash_status = cash_diagnosis.get("status")
    cash_signal_status = "indeterminate" if cash_status == "indeterminate" else "triggered" if cash_status == "needs_explanation" else "not_triggered"
    profit_status = profit_diagnosis.get("status")
    profit_signal_status = "indeterminate" if profit_status == "indeterminate" else "triggered" if profit_status == "volatile" else "not_triggered"
    inventory_status = inventory_review.get("status")
    inventory_signal_status = "indeterminate" if inventory_status == "indeterminate" else "triggered" if inventory_status == "needs_review" else "not_triggered"
    finance_status = financial_asset_review.get("status")
    finance_signal_status = "indeterminate" if finance_status == "indeterminate" else "triggered" if finance_status == "needs_review" else "not_triggered"
    management_status = management_evidence.get("status")
    management_signal_status = "not_triggered" if management_status == "available" else "indeterminate"
    signals = [
        _signal("FH_CASH_FLOW_EXPLANATION", "negative", "warn", cash_signal_status,
                "经营现金流明显变化，需要解释原因", {
                    "status": cash_status, "ocf_change_pct": cash_diagnosis.get("ocf_change_pct"),
                    "seasonality_status": cash_diagnosis.get("industry_seasonality", {}).get("status"),
                    "driver_count": len(cash_diagnosis.get("drivers", [])),
                }, {"ocf_decline_pct": 20.0},
                "经营现金流显著下降且不能由行业季节性直接解释时，必须结合附注核查原因",
                ["cash.operating_cash_flow", "balance.inventory", "balance.accounts_receivable", "balance.accounts_payable"]),
        _signal("FH_PROFIT_VOLATILITY", "negative", "warn", profit_signal_status,
                "利润大幅波动，需要拆分利润来源", {
                    "parent_net_profit_change_pct": profit_diagnosis.get("parent_net_profit_change_pct"),
                    "operating_profit_delta": profit_diagnosis.get("operating_profit_delta"),
                    "non_operating_delta": profit_diagnosis.get("non_operating_delta"),
                }, {"profit_change_pct": 20.0},
                "归母净利润同比大幅变化或正负方向反转时，拆分主营与非主营因素",
                ["income.parent_net_profit", "income.operating_profit", "income.exchange_income", "income.investment_income"]),
        _signal("FH_INVENTORY_REVIEW", "negative", "warn", inventory_signal_status,
                "存货增加需要结合行业和附注检查", {
                    "applicable": inventory_review.get("applicable"),
                    "status": inventory_status,
                    "inventory_growth_pct": inventory_review.get("inventory_growth_pct"),
                    "growth_gap_pp": inventory_review.get("growth_gap_pp"),
                }, {"inventory_growth_gap_pp": 10.0},
                "仅在适用行业中，存货增速明显高于收入且周转恶化时进入重点核查",
                ["balance.inventory", "income.revenue", "balance.contract_liability"]),
        _signal("FH_FINANCIAL_ASSET_SPECULATION", "negative", "warn", finance_signal_status,
                "非主营投资收益或金融资产贡献较高", {
                    "status": finance_status,
                    "profit_share_pct": financial_asset_review.get("investment_and_fair_value_profit_share_pct"),
                    "asset_share_pct": financial_asset_review.get("market_assets_to_total_assets_pct"),
                }, {"profit_share_pct": 10.0, "asset_share_pct": 5.0},
                "投资收益/公允价值变动或金融资产规模达到关注阈值时，结合附注区分产业投资与金融交易",
                ["income.investment_income", "income.fair_value_change", "balance.trading_financial_assets"]),
        _signal("FH_MANAGEMENT_EXPLANATION", "neutral", "info", management_signal_status,
                "本期管理层解释证据", {
                    "status": management_status,
                    "covered_topics": management_evidence.get("covered_topics", []),
                }, {"current_filing": "本期原版财报或公告文本"},
                "优先读取本期原版财报；缺失时明确披露，不用历史财报替代",
                ["filing.management_discussion", "filing.current_period_report"]),
    ]
    for signal in signals:
        signal["key_finding"] = True
    signals[2]["applicability"] = inventory_review.get("applicable")
    signals[3]["applicability"] = financial_asset_review.get("applicable")
    return signals


def _history_q4(cf: pd.DataFrame | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if cf is None:
        return result
    ocf_col = find_column(cf, ALIASES["cash"]["operating_cash_flow"])
    dcol = _date_column(cf)
    if not ocf_col or not dcol:
        return result
    data = cf.copy()
    data["_date"] = pd.to_datetime(data[dcol], errors="coerce")
    data["_ocf"] = data[ocf_col].map(parse_number)
    for year, group in data.dropna(subset=["_date"]).groupby(data["_date"].dt.year):
        annual = group[group["_date"].dt.month == 12]["_ocf"].dropna()
        q3 = group[group["_date"].dt.month == 9]["_ocf"].dropna()
        if not annual.empty and not q3.empty and annual.iloc[0] != 0:
            result.append({"year": int(year), "q4_ocf": annual.iloc[0] - q3.iloc[0],
                           "annual_ocf": annual.iloc[0], "q4_ratio_pct": (annual.iloc[0] - q3.iloc[0]) / abs(annual.iloc[0]) * 100})
    return result


def _filing_period_tokens(period: date, period_type: str) -> tuple[str, ...]:
    type_tokens = {
        "annual": ("年报", "annual", "年度报告"),
        "semiannual": ("半年", "中报", "中期", "semiannual", "interim", "半年度报告"),
        "q1": ("一季", "q1", "第一季度", "季度报告"),
        "q3": ("三季", "q3", "第三季度", "季度报告"),
    }.get(period_type, ())
    return (str(period.year), period.strftime("%Y-%m-%d"), period.strftime("%Y_%m"), period.strftime("%Y%m"), *type_tokens)


def _current_filing_candidates(data_dir: Path, period: date | None, period_type: str, cfg: dict[str, Any]) -> list[Path]:
    if period is None:
        return []
    if not data_dir.is_dir():
        return []
    extensions = cfg.get("filing_policy", {}).get("extensions", [".pdf", ".txt", ".html"])
    allowed = {str(ext).lower() for ext in extensions}
    files = sorted(path for path in data_dir.iterdir() if path.is_file() and path.suffix.lower() in allowed)
    tokens = _filing_period_tokens(period, period_type)
    result = []
    for path in files:
        name = path.name.lower()
        if str(period.year) not in name:
            continue
        if any(token.lower() in name for token in tokens[1:]):
            result.append(path)
    return result


def _read_filing_pages(path: Path) -> list[tuple[int | None, str]]:
    try:
        if path.suffix.lower() == ".pdf":
            import pdfplumber

            with pdfplumber.open(path) as pdf:
                return [(index, page.extract_text() or "") for index, page in enumerate(pdf.pages, start=1)]
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    if path.suffix.lower() == ".html":
        text = re.sub(r"<[^>]+>", " ", text)
    marked = re.split(r"===== PDF PAGE (\d+) =====", text)
    if len(marked) > 1:
        return [(int(marked[i]), marked[i + 1]) for i in range(1, len(marked), 2)]
    pages = re.split(r"\f|(?=第\s*\d+\s*页)", text)
    return [(None, page) for page in pages if page.strip()]


MANAGEMENT_TOPICS: dict[str, tuple[str, ...]] = {
    "利润": ("营业收入", "净利润", "归母净利润", "毛利率", "利润下降", "利润增长", "盈利", "revenues", "gross margin", "operating profit"),
    "现金流": ("经营活动产生的现金流量净额", "经营现金流", "现金流", "回款", "收款", "cash flow", "cash flows", "prepayments"),
    "汇兑": ("汇兑", "汇率"),
    "存货": ("存货", "原材料", "备货", "跌价", "库龄", "库存"),
    "投资收益": ("投资收益", "公允价值", "金融资产", "理财", "股票", "fair value", "investment gains"),
}


def _extract_management_evidence(data_dir: Path, period: date | None, period_type: str, cfg: dict[str, Any]) -> dict[str, Any]:
    candidates = _current_filing_candidates(data_dir, period, period_type, cfg)
    available = sorted(path.name for path in data_dir.iterdir() if path.is_file() and path.suffix.lower() in {".pdf", ".txt", ".html"}) if data_dir.is_dir() else []
    if not candidates:
        return {
            "status": "missing_current_period",
            "current_period_files": [],
            "available_files": available,
            "excerpts": [],
            "covered_topics": [],
            "message": "未取得与本期报告期匹配的原版财报或公告文本。",
        }
    max_excerpts = int(cfg.get("filing_policy", {}).get("max_excerpts", 12))
    excerpts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path in candidates:
        for page_no, page_text in _read_filing_pages(path):
            normalized = re.sub(r"\s+", " ", page_text).strip()
            if not normalized:
                continue
            section_match = re.search(r"(管理层讨论与分析|经营情况讨论与分析|经营情况|重大事项|财务报告)", normalized)
            section = section_match.group(1) if section_match else "原版财报文本"
            sentences = re.split(r"(?<=[。！？；])|(?<=[.!?;])\s+(?=[A-Z])", normalized)
            for topic, keywords in MANAGEMENT_TOPICS.items():
                for sentence in sentences:
                    if not any(keyword.lower() in sentence.lower() for keyword in keywords):
                        continue
                    if any(token in sentence for token in ("电子信箱", "联系电话", "公司选定的信息披露报纸")):
                        continue
                    quote = textwrap.shorten(sentence, width=220, placeholder="...")
                    key = (quote, topic)
                    if len(quote) < 12 or key in seen:
                        continue
                    seen.add(key)
                    excerpts.append({
                        "topic": topic,
                        "quote": quote,
                        "source_file": path.name,
                        "section": section,
                        "page": page_no,
                        "source_level": "L3",
                    })
    # Read the full filing before selecting evidence. Causal explanations
    # usually occur after front matter and headline financial tables.
    def relevance(item: dict[str, Any]) -> int:
        quote = item["quote"]
        return (6 * bool(re.search(r"主要[系为由]|主要原因|变动原因|所致|由于|原因说明", quote))
                + 2 * bool(re.search(r"增长|下降|增加|减少|提高|降低", quote))
                + 2 * (item["section"] != "原版财报文本"))
    selected = []
    topic_count: dict[str, int] = {}
    for item in sorted(excerpts, key=relevance, reverse=True):
        topic = item["topic"]
        if topic_count.get(topic, 0) >= 3:
            continue
        selected.append(item)
        topic_count[topic] = topic_count.get(topic, 0) + 1
        if len(selected) >= max_excerpts:
            break
    excerpts = selected
    covered = sorted({item["topic"] for item in excerpts})
    return {
        "status": "available" if excerpts else "text_unavailable",
        "current_period_files": [path.name for path in candidates],
        "available_files": available,
        "excerpts": excerpts,
        "covered_topics": covered,
        "message": "已提取与本期重点问题相关的管理层原文证据。" if excerpts else "已找到本期原版财报，但未提取到重点问题相关文本。",
    }


def _cash_history(cf: pd.DataFrame | None, income: pd.DataFrame | None, current: date | None) -> list[dict[str, Any]]:
    if cf is None or current is None:
        return []
    result: list[dict[str, Any]] = []
    for period in _dates(cf):
        if period > current:
            continue
        cf_row = _row(cf, period)
        inc_row = _row(income, period)
        ocf, _ = _value(cf, cf_row, ALIASES["cash"]["operating_cash_flow"])
        profit, _ = _value(income, inc_row, ALIASES["income"]["parent_net_profit"])
        if profit is None:
            profit, _ = _value(cf, cf_row, ALIASES["cash"]["net_profit"])
        result.append({
            "period": period.isoformat(),
            "operating_cash_flow": ocf,
            "parent_net_profit": profit,
            "ocf_to_profit_pct": safe_div(ocf, profit) * 100.0 if safe_div(ocf, profit) is not None else None,
            "report_type": _report_type(cf, cf_row),
        })
    return result[-8:]


def _cash_flow_diagnosis(cf: pd.DataFrame | None, income_df: pd.DataFrame | None, bridges: dict[str, Any],
                         inc_cur: dict[str, Any], inc_yoy: dict[str, Any], cf_cur: dict[str, Any], cf_yoy: dict[str, Any],
                         bs_cur: dict[str, Any], bs_yoy: dict[str, Any], period: date | None, period_type: str,
                         profile: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    thresholds = {**DEFAULT_CONFIG["thresholds"], **cfg.get("thresholds", {})}
    current_ocf = cf_cur.get("operating_cash_flow")
    prior_ocf = cf_yoy.get("operating_cash_flow")
    ocf_change = change_pct(current_ocf, prior_ocf)
    current_profit = _first_number(inc_cur.get("parent_net_profit"), inc_cur.get("net_profit"))
    prior_profit = _first_number(inc_yoy.get("parent_net_profit"), inc_yoy.get("net_profit"))
    current_ratio = safe_div(current_ocf, current_profit) * 100.0 if safe_div(current_ocf, current_profit) is not None else None
    prior_ratio = safe_div(prior_ocf, prior_profit) * 100.0 if safe_div(prior_ocf, prior_profit) is not None else None
    ratio_change = change_pp(current_ratio, prior_ratio)
    decline = None if None in (current_ocf, prior_ocf) else (
        current_ocf < prior_ocf and (abs(ocf_change or 0.0) >= thresholds["ocf_decline_pct"] or (current_ocf < 0 <= prior_ocf))
    )

    wc = bridges.get("working_capital", {})
    changes = wc.get("changes_vs_yoy", {})
    ar_change = sum(changes.get(key) for key in ("accounts_receivable", "contract_asset") if changes.get(key) is not None)
    payable_change = sum(changes.get(key) for key in ("accounts_payable", "notes_payable") if changes.get(key) is not None)
    drivers: list[dict[str, Any]] = []
    driver_values = [
        ("存货/原材料备货", -changes.get("inventory") if changes.get("inventory") is not None else None, "存货期末余额变化的反向现金影响"),
        ("应收账款和合同资产", -ar_change if ar_change else None, "应收及合同资产增加会占用现金"),
        ("应付项目", payable_change if payable_change else None, "应付项目增加提供供应商信用"),
        ("合同负债/预收款", changes.get("contract_liability"), "合同负债增加通常改善当期现金来源"),
        ("税费支付", (cf_yoy.get("tax_paid") - cf_cur.get("tax_paid")) if None not in (cf_cur.get("tax_paid"), cf_yoy.get("tax_paid")) else None, "同比税费支付增加占用现金，减少释放现金"),
        ("职工薪酬支付", (cf_yoy.get("staff_paid") - cf_cur.get("staff_paid")) if None not in (cf_cur.get("staff_paid"), cf_yoy.get("staff_paid")) else None, "同比职工现金支付增加占用现金，减少释放现金"),
    ]
    for label, effect, explanation in driver_values:
        if effect is None:
            continue
        drivers.append({
            "type": label,
            "cash_effect": effect,
            "direction": "增加现金" if effect > 0 else "占用现金" if effect < 0 else "影响有限",
            "explanation": explanation,
            "importance": "重点" if decline and abs(effect) >= max(abs(current_ocf - prior_ocf) * 0.2, 1.0) else "观察",
        })
    drivers.sort(key=lambda item: abs(item["cash_effect"]), reverse=True)
    missing_reasons = []
    if changes.get("inventory") is None:
        missing_reasons.append("存货期末余额")
    if ar_change == 0 and changes.get("accounts_receivable") is None and changes.get("contract_asset") is None:
        missing_reasons.append("应收及合同资产期末余额")
    if cf_cur.get("tax_paid") is None:
        missing_reasons.append("税费支付明细")
    if cf_cur.get("staff_paid") is None:
        missing_reasons.append("职工薪酬支付明细")

    history = _cash_history(cf, income_df, period)
    same_period = []
    if period is not None:
        same_period = [item for item in history if item["period"] != period.isoformat() and item["period"][5:7] == f"{period.month:02d}"]
    seasonality_type = profile.get("cash_flow_seasonality", "unknown")
    seasonality_status = "unknown"
    if decline is not None and decline:
        historical_negative = sum(1 for item in same_period if item.get("operating_cash_flow") is not None and item["operating_cash_flow"] < 0)
        if seasonality_type == "q4_collection" and period_type in {"q1", "semiannual", "q3"} and historical_negative >= 2:
            seasonality_status = "normal"
        elif seasonality_type == "stable":
            seasonality_status = "abnormal"
        elif seasonality_type == "normal" and historical_negative >= max(2, len(same_period) // 2 + 1):
            seasonality_status = "normal"
        elif same_period and historical_negative == len(same_period):
            seasonality_status = "normal"
        else:
            seasonality_status = "unknown"
    elif decline is not None:
        seasonality_status = "not_applicable"

    material_driver = False
    if decline and current_ocf is not None and prior_ocf is not None:
        decline_gap = abs(current_ocf - prior_ocf)
        material_driver = any(
            item.get("cash_effect") is not None
            and abs(item["cash_effect"]) >= max(decline_gap * 0.2, 1.0)
            for item in drivers
        )
    if current_ocf is None or prior_ocf is None:
        status = "indeterminate"
    elif not decline:
        status = "stable"
    elif seasonality_status == "normal":
        status = "seasonal"
    elif material_driver:
        status = "explainable"
    else:
        status = "needs_explanation"
    return {
        "status": status,
        "current_ocf": current_ocf,
        "prior_ocf": prior_ocf,
        "ocf_change_pct": ocf_change,
        "current_ocf_to_profit_pct": current_ratio,
        "prior_ocf_to_profit_pct": prior_ratio,
        "ratio_change_pp": ratio_change,
        "decline_detected": decline,
        "industry_seasonality": {
            "type": seasonality_type,
            "status": seasonality_status,
            "history_same_period": same_period,
            "note": profile.get("cash_flow_note", ""),
        },
        "history": history,
        "drivers": drivers,
        "material_driver_found": material_driver,
        "missing_reasons": missing_reasons,
        "explanation_status": "初步可由经营项目解释" if material_driver else "尚未取得足够原因字段" if decline else "经营现金流未出现需要拆分的明显下降",
        "comparison_basis": "本期与同比期经营现金流，辅以同月份历史报告期比较",
    }


def _profit_diagnosis(inc_cur: dict[str, Any], inc_yoy: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    thresholds = {**DEFAULT_CONFIG["thresholds"], **cfg.get("thresholds", {})}
    parent = inc_cur.get("parent_net_profit")
    parent_yoy = inc_yoy.get("parent_net_profit")
    change = change_pct(parent, parent_yoy)
    volatility = None if None in (parent, parent_yoy) else (
        abs(change or 0.0) >= thresholds["profit_change_pct"] or (parent < 0 <= parent_yoy) or (parent >= 0 > parent_yoy)
    )
    delta = lambda key: (inc_cur.get(key) - inc_yoy.get(key)) if None not in (inc_cur.get(key), inc_yoy.get(key)) else None
    operating_profit_delta = delta("operating_profit")
    below_operating_delta = None
    if None not in (inc_cur.get("total_profit"), inc_cur.get("operating_profit"), inc_yoy.get("total_profit"), inc_yoy.get("operating_profit")):
        below_operating_delta = (inc_cur["total_profit"] - inc_cur["operating_profit"]) - (inc_yoy["total_profit"] - inc_yoy["operating_profit"])
    tax_effect = -delta("income_tax") if delta("income_tax") is not None else None
    minority_effect = None
    if None not in (inc_cur.get("minority_interest"), inc_yoy.get("minority_interest")):
        minority_effect = -delta("minority_interest")
    named_below_operating = [
        ("汇兑损益", delta("exchange_income"), "汇率变化影响"),
        ("投资收益", delta("investment_income"), "已确认投资收益，需结合附注判断来源"),
        ("公允价值变动", delta("fair_value_change"), "未实现估值变动"),
        ("资产处置收益", delta("asset_disposal_income"), "资产处置影响"),
        ("其他收益", delta("other_income"), "其他收益变化"),
        ("资产及信用减值", (delta("asset_impairment") or 0.0) + (delta("credit_impairment") or 0.0)
         if delta("asset_impairment") is not None or delta("credit_impairment") is not None else None, "减值损失变化"),
    ]
    # Investment/fair-value/impairment already enter Chinese GAAP operating profit.
    # Keep them in detail only: adding them again double counts the summary bridge.
    summary_drivers = [
        ("营业利润变化", operating_profit_delta, "主营经营结果"),
        ("营业外净收支变化", below_operating_delta, "营业利润之外的收支变化"),
        ("所得税变化", tax_effect, "税费对归母利润的影响"),
        ("少数股东损益变化", minority_effect, "归母利润分配变化"),
    ]
    detail_drivers = [
        ("营业收入", delta("revenue"), "主营规模变化"),
        ("成本费用", -delta("total_cost") if delta("total_cost") is not None else None, "成本费用变化的利润影响"),
        ("投资收益", delta("investment_income"), "投资收益变化"),
        ("公允价值变动", delta("fair_value_change"), "未实现估值变动"),
        ("汇兑损益", delta("exchange_income"), "汇率变化影响"),
        ("资产处置收益", delta("asset_disposal_income"), "资产处置影响"),
        ("其他收益", delta("other_income"), "其他收益变化"),
        ("资产及信用减值", delta("asset_impairment"), "资产减值损失变化"),
        ("信用减值", delta("credit_impairment"), "信用减值损失变化"),
    ]
    def pack(items: list[tuple[str, float | None, str]]) -> list[dict[str, Any]]:
        result = []
        for label, value, explanation in items:
            if value is None:
                continue
            result.append({"type": label, "profit_effect": value, "direction": "增厚利润" if value > 0 else "拖累利润" if value < 0 else "影响有限", "explanation": explanation})
        return sorted(result, key=lambda item: abs(item["profit_effect"]), reverse=True)
    return {
        "status": "indeterminate" if volatility is None else "volatile" if volatility else "stable",
        "parent_net_profit_change_pct": change,
        "volatility_detected": volatility,
        "parent_net_profit_delta": delta("parent_net_profit"),
        "operating_profit_delta": operating_profit_delta,
        "non_operating_delta": below_operating_delta,
        "summary_drivers": pack(summary_drivers),
        "detail_drivers": pack(detail_drivers),
        "missing_items": [label for label, value, _ in detail_drivers if value is None],
        "conclusion_basis": "归母利润变化按营业利润、营业利润以外项目、税费和少数股东损益拆分",
    }


def _inventory_review(profile: dict[str, Any], bs_cur: dict[str, Any], bs_yoy: dict[str, Any],
                      inc_cur: dict[str, Any], inc_yoy: dict[str, Any], period_type: str,
                      cfg: dict[str, Any]) -> dict[str, Any]:
    if not profile.get("inventory_review"):
        return {"applicable": False, "status": "not_applicable", "conclusion": "当前行业配置不启用自动存货风险判断。", "missing_items": []}
    inventory_growth = change_pct(bs_cur.get("inventory"), bs_yoy.get("inventory"))
    revenue_growth = change_pct(inc_cur.get("revenue"), inc_yoy.get("revenue"))
    cost_now = abs(inc_cur.get("operating_cost")) if inc_cur.get("operating_cost") is not None else None
    cost_old = abs(inc_yoy.get("operating_cost")) if inc_yoy.get("operating_cost") is not None else None
    period_days = {"q1": 90.0, "semiannual": 181.0, "q3": 273.0, "annual": 365.0}
    days_now = bs_cur.get("inventory") / cost_now * period_days.get(period_type, 90.0) if cost_now else None
    days_old = bs_yoy.get("inventory") / cost_old * period_days.get(period_type, 90.0) if cost_old else None
    days_change = change_pct(days_now, days_old)
    contract_growth = change_pct(bs_cur.get("contract_liability"), bs_yoy.get("contract_liability"))
    gap = inventory_growth - revenue_growth if None not in (inventory_growth, revenue_growth) else None
    threshold = float(cfg.get("thresholds", {}).get("inventory_growth_gap_pp", DEFAULT_CONFIG["thresholds"]["inventory_growth_gap_pp"]))
    inventory_pressure = None if gap is None else gap >= threshold and (days_change is None or days_change > 10.0)
    order_supported = inventory_pressure is False and gap is not None and contract_growth is not None and contract_growth > revenue_growth
    missing = []
    for label, value in (("存货余额", bs_cur.get("inventory")), ("营业成本", inc_cur.get("operating_cost")), ("存货跌价准备/库龄", bs_cur.get("inventory_impairment_reserve"))):
        if value is None:
            missing.append(label)
    if inventory_growth is None or revenue_growth is None:
        status = "indeterminate"
    elif inventory_pressure:
        status = "needs_review"
    elif order_supported:
        status = "order_supported"
    else:
        status = "normal"
    return {
        "applicable": True,
        "status": status,
        "inventory_growth_pct": inventory_growth,
        "revenue_growth_pct": revenue_growth,
        "growth_gap_pp": gap,
        "inventory_days": days_now,
        "prior_inventory_days": days_old,
        "inventory_days_change_pct": days_change,
        "contract_liability_growth_pct": contract_growth,
        "missing_items": missing,
        "conclusion": profile.get("inventory_note", "结合行业和附注判断存货变化。"),
    }


def _financial_asset_review(profile: dict[str, Any], bs_cur: dict[str, Any], bs_yoy: dict[str, Any],
                            inc_cur: dict[str, Any], inc_yoy: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    if not profile.get("financial_asset_review"):
        return {"applicable": False, "status": "not_applicable", "conclusion": "当前行业配置不启用非主营金融资产检查。", "components": []}
    market_asset_fields = [
        ("公允价值计量金融资产合计", "fair_value_financial_assets"),
        ("交易性金融资产", "trading_financial_assets"),
        ("其他非流动金融资产", "other_noncurrent_financial_assets"),
        ("其他权益工具投资", "other_equity_investment"),
        ("可供出售金融资产", "available_for_sale_financial_assets"),
    ]
    asset_fields = [*market_asset_fields, ("长期股权投资", "long_equity_investment")]
    components = []
    available = 0
    market_available = 0
    total_assets = bs_cur.get("total_assets")
    prior_total = bs_yoy.get("total_assets")
    for label, key in asset_fields:
        now, old = bs_cur.get(key), bs_yoy.get(key)
        if now is not None or old is not None:
            available += 1
            components.append({
                "type": label,
                "current": now,
                "prior": old,
                "growth_pct": change_pct(now, old),
                "classification": "产业投资余额" if key == "long_equity_investment" else "金融资产余额",
            })
            if key in {field_key for _, field_key in market_asset_fields}:
                market_available += 1
    market_assets = sum(bs_cur.get(key) or 0 for _, key in market_asset_fields) if market_available else None
    prior_market_assets = sum(bs_yoy.get(key) or 0 for _, key in market_asset_fields) if market_available else None
    long_equity_investment = bs_cur.get("long_equity_investment")
    prior_long_equity_investment = bs_yoy.get("long_equity_investment")
    investment_income = inc_cur.get("investment_income")
    fair_value = inc_cur.get("fair_value_change")
    asset_disposal_income = inc_cur.get("asset_disposal_income")
    profit = abs(inc_cur.get("parent_net_profit")) if inc_cur.get("parent_net_profit") not in (None, 0) else None
    profit_share = (abs((investment_income or 0) + (fair_value or 0)) / profit * 100.0) if profit else None
    asset_share = market_assets / total_assets * 100.0 if None not in (market_assets, total_assets) and total_assets else None
    asset_growth = change_pct(market_assets, prior_market_assets)
    threshold = {**DEFAULT_CONFIG["thresholds"], **cfg.get("thresholds", {})}
    risk = None if profit_share is None and asset_share is None else (
        (profit_share is not None and profit_share >= threshold["financial_asset_profit_share"]) or
        (asset_share is not None and asset_share >= threshold["financial_asset_asset_share"] and (asset_growth or 0) >= threshold["financial_asset_growth_pct"])
    )
    status = "indeterminate" if available == 0 and investment_income is None and fair_value is None and asset_disposal_income is None else "needs_review" if risk else "normal"
    return {
        "applicable": True,
        "status": status,
        "components": components,
        "profit_components": [
            {
                "type": "投资收益（已确认，待附注拆分）",
                "current": investment_income,
                "prior": inc_yoy.get("investment_income"),
                "growth_pct": change_pct(investment_income, inc_yoy.get("investment_income")),
                "classification": "可能包含已实现处置收益，也可能包含长期股权投资权益法收益",
            },
            {
                "type": "公允价值变动（浮盈/浮亏候选）",
                "current": fair_value,
                "prior": inc_yoy.get("fair_value_change"),
                "growth_pct": change_pct(fair_value, inc_yoy.get("fair_value_change")),
                "classification": "通常是未实现估值变动，需查金融资产类别和附注",
            },
            {
                "type": "资产处置收益（已确认）",
                "current": asset_disposal_income,
                "prior": inc_yoy.get("asset_disposal_income"),
                "growth_pct": change_pct(asset_disposal_income, inc_yoy.get("asset_disposal_income")),
                "classification": "已确认处置项目，不等同于持续性主营利润",
            },
        ],
        "income_classification": {
            "investment_income": "已确认收益；可能包含已实现处置收益或长期股权投资权益法收益，需查附注",
            "fair_value_change": "公允价值变动；通常包含未实现浮盈/浮亏，需查金融资产类别",
            "long_equity_investment": "长期股权投资；偏产业投资属性，不直接等同于股票/理财交易",
            "asset_disposal_income": "资产处置收益；已确认处置项目，不等同于持续性主营利润",
        },
        "market_value_assets": market_assets,
        "prior_market_value_assets": prior_market_assets,
        "market_assets_growth_pct": asset_growth,
        "market_assets_to_total_assets_pct": asset_share,
        "long_equity_investment": long_equity_investment,
        "prior_long_equity_investment": prior_long_equity_investment,
        "long_equity_investment_growth_pct": change_pct(long_equity_investment, prior_long_equity_investment),
        "investment_income": investment_income,
        "fair_value_change": fair_value,
        "asset_disposal_income": asset_disposal_income,
        "investment_and_fair_value_profit_share_pct": profit_share,
        "classification_note": "投资收益可能包含联营/合营企业收益，需结合附注区分金融交易与产业投资。",
        "conclusion": "非主营投资收益或金融资产规模达到关注阈值，需结合附注核实其可持续性。" if risk else "未发现非主营金融资产对本期利润形成明显支撑的组合信号。",
    }


def _bridge_profit_to_ocf(income_current: dict[str, Any], cf_current: dict[str, Any], residual_limit_pct: float = 5.0) -> dict[str, Any]:
    components = {
        "net_profit": _first_number(cf_current.get("net_profit"), income_current.get("net_profit")),
        "asset_impairment": cf_current.get("asset_impairment"),
        "depreciation": cf_current.get("depreciation"),
        "intangible_amortization": cf_current.get("intangible_amortization"),
        "receivable_change": cf_current.get("receivable_change"),
        "inventory_change": cf_current.get("inventory_change"),
        "payable_change": cf_current.get("payable_change"),
    }
    available = [v for k, v in components.items() if k != "net_profit" and v is not None]
    derived = sum(v for v in components.values() if v is not None)
    target = cf_current.get("operating_cash_flow")
    residual = target - derived if target is not None and available else None
    residual_pct = abs(residual) / max(abs(target), 1.0) * 100 if residual is not None else None
    return {"components": components, "derived_ocf": derived if available and components["net_profit"] is not None else None,
            "reported_ocf": target, "residual": residual, "residual_pct": residual_pct,
            "status": "reconciled" if residual_pct is not None and residual_pct <= residual_limit_pct else ("needs_explanation" if residual_pct is not None else "indeterminate"),
            "formula": "净利润+非现金项目+营运资本项目=经营活动现金流（数据源方向沿用现金流量表）"}


def _bridge_working_capital(bs_current: dict[str, Any], bs_yoy: dict[str, Any], income_current: dict[str, Any], income_yoy: dict[str, Any]) -> dict[str, Any]:
    fields = ["accounts_receivable", "contract_asset", "inventory", "accounts_payable", "notes_payable", "contract_liability"]
    changes = {field: (bs_current.get(field) - bs_yoy.get(field)) if bs_current.get(field) is not None and bs_yoy.get(field) is not None else None for field in fields}
    cash_effect = None
    if all(changes.get(k) is not None for k in fields):
        cash_effect = -changes["accounts_receivable"] - changes["contract_asset"] - changes["inventory"] + changes["accounts_payable"] + changes["notes_payable"] + changes["contract_liability"]
    return {"changes_vs_yoy": changes, "cash_effect_estimate": cash_effect,
            "status": "reconciled" if cash_effect is not None else "indeterminate",
            "revenue_change": (income_current.get("revenue") - income_yoy.get("revenue")) if income_current.get("revenue") is not None and income_yoy.get("revenue") is not None else None,
            "formula": "营运资本现金影响≈-Δ应收-Δ合同资产-Δ存货+Δ应付+Δ合同负债；点值表按期末同比比较"}


def _bridge_cash(cf_current: dict[str, Any], residual_limit_pct: float = 5.0) -> dict[str, Any]:
    begin = cf_current.get("begin_cash")
    end = cf_current.get("end_cash")
    ocf, inv, fin = [cf_current.get(k) for k in ("operating_cash_flow", "investing_cash_flow", "financing_cash_flow")]
    fx = cf_current.get("fx_effect")
    expected = begin + ocf + inv + fin + fx if None not in (begin, ocf, inv, fin, fx) else None
    residual = end - expected if expected is not None and end is not None else None
    residual_pct = abs(residual) / max(abs(end), 1.0) * 100 if residual is not None else None
    return {"begin_cash": begin, "operating_cash_flow": ocf, "investing_cash_flow": inv,
            "financing_cash_flow": fin, "fx_effect": fx, "expected_end_cash": expected,
            "reported_end_cash": end, "residual": residual, "residual_pct": residual_pct,
             "status": "reconciled" if residual_pct is not None and residual_pct <= residual_limit_pct else ("needs_explanation" if residual_pct is not None else "indeterminate"),
            "formula": "期初现金+OCF+投资现金流+筹资现金流+汇率影响=期末现金"}


def build_health_report(data_dir: Path, project_name: str = "", config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _merge_config(config)
    tables = {key: _load_csv(data_dir, filename) for key, filename in STATEMENT_FILES.items()}
    income = tables["income_statement"]
    balance = tables["balance_sheet"]
    cash = tables["cash_flow"]
    limitations: list[dict[str, Any]] = []
    missing_tables = [STATEMENT_FILES[k] for k, v in (("income_statement", income), ("balance_sheet", balance), ("cash_flow", cash)) if v is None]
    if missing_tables:
        limitations.append({"id": "missing_required_statement", "severity": "fail", "detail": "缺少必需三表: " + ", ".join(missing_tables)})
    date_sets = [_dates(x) for x in (income, balance, cash)]
    common = set(date_sets[0]) & set(date_sets[1]) & set(date_sets[2]) if all(date_sets) else set()
    current_period = max(common) if common else (max(date_sets[0]) if date_sets[0] else None)
    if current_period is None:
        limitations.append({"id": "no_current_period", "severity": "fail", "detail": "三表没有可识别的报告期"})
    elif not common:
        limitations.append({"id": "no_common_period", "severity": "fail", "detail": "三表没有共同报告期，无法进行本期三表体检"})
    income_row = _row(income, current_period)
    balance_row = _row(balance, current_period)
    cash_row = _row(cash, current_period)
    report_type = _report_type(income, income_row)
    ptype = _period_type(current_period, report_type) if current_period else "unknown"
    industry_profile = resolve_industry_profile(cfg, project_name)
    yoy_period = _same_period_last_year(current_period) if current_period else None
    prior_end_period = _prior_balance_period(balance, current_period, ptype) if current_period else None
    if current_period and yoy_period and any(_row(table, yoy_period) is None for table in (income, balance, cash)):
        limitations.append({
            "id": "missing_comparable_period",
            "severity": "fail",
            "detail": f"缺少同比可比期 {yoy_period.isoformat()} 的三表数据，无法按同比口径体检",
        })
    if current_period and prior_end_period is None:
        limitations.append({
            "id": "missing_prior_period_end",
            "severity": "fail",
            "detail": "缺少资产负债表可比上期末，无法完成点值比较",
        })
    income_fields = list(ALIASES["income"])
    balance_fields = list(ALIASES["balance"])
    cash_fields = list(ALIASES["cash"])
    indicator = tables["indicators_annual"]
    ind_current = _row(indicator, current_period)
    ind_yoy = _row(indicator, yoy_period)
    inc_cur, inc_cols = _section_values(income, income_row, "income", income_fields)
    inc_yoy, _ = _section_values(income, _row(income, yoy_period), "income", income_fields)
    bs_cur, bs_cols = _section_values(balance, balance_row, "balance", balance_fields)
    bs_yoy, _ = _section_values(balance, _row(balance, yoy_period), "balance", balance_fields)
    bs_prior, _ = _section_values(balance, _row(balance, prior_end_period), "balance", balance_fields)
    cf_cur, cf_cols = _section_values(cash, cash_row, "cash", cash_fields)
    cf_yoy, _ = _section_values(cash, _row(cash, yoy_period), "cash", cash_fields)
    ind_cur, ind_cols = _section_values(indicator, ind_current, "indicator", ALIASES["indicator"])
    ind_yoy, _ = _section_values(indicator, ind_yoy, "indicator", ALIASES["indicator"])
    inc_cur["metrics"] = _ratio_metrics(inc_cur, ind_cur)
    inc_yoy["metrics"] = _ratio_metrics(inc_yoy, ind_yoy)
    inc_cur["growth_pct"] = _growth_map(inc_cur, inc_yoy)
    bs_cur["growth_pct"] = _growth_map(bs_cur, bs_yoy)
    cf_cur["growth_pct"] = _growth_map(cf_cur, cf_yoy)
    flow_single_income, _ = _single_period_section(income, current_period, "income", income_fields) if current_period else ({}, {})
    flow_single_cash, _ = _single_period_section(cash, current_period, "cash", cash_fields) if current_period else ({}, {})
    prior_flow_income, _ = _single_period_section(income, yoy_period, "income", income_fields) if yoy_period else ({}, {})
    prior_flow_cash, _ = _single_period_section(cash, yoy_period, "cash", cash_fields) if yoy_period else ({}, {})
    for section, values in (("income_statement", inc_cur), ("balance_sheet", bs_cur), ("cash_flow", cf_cur)):
        values["unit"] = "原始货币单位（展示时除以1e8转亿元）"
    cf_cur["capex"] = abs(cf_cur["capex"]) if cf_cur.get("capex") is not None else None
    cf_yoy["capex"] = abs(cf_yoy["capex"]) if cf_yoy.get("capex") is not None else None
    cf_cur["free_cash_flow"] = cf_cur.get("operating_cash_flow") - cf_cur["capex"] if None not in (cf_cur.get("operating_cash_flow"), cf_cur.get("capex")) else None
    cf_yoy["free_cash_flow"] = cf_yoy.get("operating_cash_flow") - cf_yoy.get("capex") if None not in (cf_yoy.get("operating_cash_flow"), cf_yoy.get("capex")) else None
    cf_cur["collection_ratio_pct"] = safe_div(cf_cur.get("sales_cash"), inc_cur.get("revenue"))
    cf_yoy["collection_ratio_pct"] = safe_div(cf_yoy.get("sales_cash"), inc_yoy.get("revenue"))
    cf_cur["ocf_to_parent_net_profit_pct"] = safe_div(cf_cur.get("operating_cash_flow"), inc_cur.get("parent_net_profit"))
    cf_yoy["ocf_to_parent_net_profit_pct"] = safe_div(cf_yoy.get("operating_cash_flow"), inc_yoy.get("parent_net_profit"))
    cf_cur["ocf_to_net_profit_pct"] = safe_div(cf_cur.get("operating_cash_flow"), inc_cur.get("net_profit"))
    cf_yoy["ocf_to_net_profit_pct"] = safe_div(cf_yoy.get("operating_cash_flow"), inc_yoy.get("net_profit"))
    for cf_values in (cf_cur, cf_yoy):
        for ratio_name in ("collection_ratio_pct", "ocf_to_parent_net_profit_pct", "ocf_to_net_profit_pct"):
            if cf_values.get(ratio_name) is not None:
                cf_values[ratio_name] *= 100.0
    q4_history = _history_q4(cash)
    bridge_limit = float(cfg.get("thresholds", {}).get("bridge_residual_pct", DEFAULT_CONFIG["thresholds"]["bridge_residual_pct"]))
    bridges = {
        "profit_to_operating_cash_flow": _bridge_profit_to_ocf(inc_cur, cf_cur, bridge_limit),
        "working_capital": _bridge_working_capital(bs_cur, bs_yoy, inc_cur, inc_yoy),
        "cash_reconciliation": _bridge_cash(cf_cur, bridge_limit),
    }
    cash_flow_diagnosis = _cash_flow_diagnosis(
        cash, income, bridges, inc_cur, inc_yoy, cf_cur, cf_yoy, bs_cur, bs_yoy,
        current_period, ptype, industry_profile, cfg,
    ) if current_period else {"status": "indeterminate", "drivers": [], "missing_reasons": ["本期报告期"]}
    profit_diagnosis = _profit_diagnosis(inc_cur, inc_yoy, cfg) if current_period else {"status": "indeterminate", "detail_drivers": [], "summary_drivers": []}
    inventory_review = _inventory_review(industry_profile, bs_cur, bs_yoy, inc_cur, inc_yoy, ptype, cfg) if current_period else {"applicable": False, "status": "indeterminate"}
    financial_asset_review = _financial_asset_review(industry_profile, bs_cur, bs_yoy, inc_cur, inc_yoy, cfg) if current_period else {"applicable": False, "status": "indeterminate"}
    management_evidence = _extract_management_evidence(data_dir, current_period, ptype, cfg)
    legacy_signals = _make_signals(inc_cur, inc_yoy, bs_prior, cf_cur, cf_yoy, bs_cur, bs_yoy, current_period, ptype, cfg, q4_history, industry_profile) if current_period else []
    key_signals = _make_key_signals(cash_flow_diagnosis, profit_diagnosis, inventory_review, financial_asset_review, management_evidence)
    signals = legacy_signals + key_signals
    required_fields = {
        "income_statement": ["revenue", "parent_net_profit"],
        "balance_sheet": ["accounts_receivable", "inventory", "contract_liability"],
        "cash_flow": ["operating_cash_flow"],
    }
    for section, fields in required_fields.items():
        values = {"income_statement": inc_cur, "balance_sheet": bs_cur, "cash_flow": cf_cur}[section]
        missing = [field for field in fields if values.get(field) is None]
        if missing:
            limitations.append({"id": f"missing_fields_{section}", "severity": "warn", "detail": f"{section} 缺少字段: {', '.join(missing)}"})
    notes_files = sorted(str(p.name) for p in data_dir.glob("*.pdf")) + sorted(str(p.name) for p in data_dir.glob("*.txt")) + sorted(str(p.name) for p in data_dir.glob("*.html"))
    if not notes_files:
        limitations.append({"id": "notes_not_available", "severity": "warn", "detail": "未发现原版财报PDF或文本，管理层解释和附注核查不可用"})
    if management_evidence.get("status") != "available":
        limitations.append({"id": "current_filing_not_available", "severity": "warn", "detail": management_evidence.get("message", "本期原版财报证据不可用")})
    if not industry_profile.get("configured"):
        limitations.append({"id": "industry_profile_not_configured", "severity": "warn", "detail": "未配置公司/行业画像，已关闭行业特定存货结论并将现金流季节性标记为未知"})
    forecast_impact = {
        "revenue": "待观察" if cash_flow_diagnosis.get("status") == "needs_explanation" else "维持",
        "profit": "下调" if profit_diagnosis.get("status") == "volatile" or financial_asset_review.get("status") == "needs_review" else "维持",
        "cash_flow": "下调" if cash_flow_diagnosis.get("status") == "needs_explanation" else "维持",
        "valuation_risk": "待观察" if any(s["id"] in {"FH_CASH_FLOW_EXPLANATION", "FH_FINANCIAL_ASSET_SPECULATION"} and s["status"] == "triggered" for s in signals) else "维持",
        "basis": "关键问题导向初筛，需由Agent结合原版财报、附注和预测模型确认；本模块不自动改写估值。",
    }
    config_path = data_dir.parent / "input" / "本期财报体检配置.json"
    fp = fingerprint_files(data_dir, config_path)
    evidence_records = {
        "income_statement": {
            "current": _evidence_map(inc_cur, inc_cols, STATEMENT_FILES["income_statement"], current_period, "income.current"),
            "yoy": _evidence_map(inc_yoy, {field: find_column(income, ALIASES["income"][field]) for field in income_fields}, STATEMENT_FILES["income_statement"], yoy_period, "income.yoy"),
        },
        "balance_sheet": {
            "current": _evidence_map(bs_cur, bs_cols, STATEMENT_FILES["balance_sheet"], current_period, "balance.current"),
            "yoy": _evidence_map(bs_yoy, {field: find_column(balance, ALIASES["balance"][field]) for field in balance_fields}, STATEMENT_FILES["balance_sheet"], yoy_period, "balance.yoy"),
            "prior_period_end": _evidence_map(bs_prior, {field: find_column(balance, ALIASES["balance"][field]) for field in balance_fields}, STATEMENT_FILES["balance_sheet"], prior_end_period, "balance.prior"),
        },
        "cash_flow": {
            "current": _evidence_map(cf_cur, cf_cols, STATEMENT_FILES["cash_flow"], current_period, "cash.current"),
            "yoy": _evidence_map(cf_yoy, {field: find_column(cash, ALIASES["cash"][field]) for field in cash_fields}, STATEMENT_FILES["cash_flow"], yoy_period, "cash.yoy"),
        },
    }
    result = {
        "schema_version": SCHEMA_VERSION,
        "rule_version": cfg.get("rule_version"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "project": project_name or data_dir.parent.name,
        "status": "fail" if any(x["severity"] == "fail" for x in limitations) else ("warn" if limitations or any(s["severity"] == "warn" and s["status"] == "triggered" for s in signals) else "pass"),
        "report_period": {"current": current_period.isoformat() if current_period else None, "report_type": report_type,
                          "period_type": ptype,
                          "announcement_date": _text_value(income, income_row, ("NOTICE_DATE", "公告日期", "公告日")),
                          "yoy": yoy_period.isoformat() if yoy_period else None,
                          "prior_period_end": prior_end_period.isoformat() if prior_end_period else None,
                          "comparable_prior": prior_end_period.isoformat() if prior_end_period else None,
                          "comparison_policy": cfg.get("period_policy")},
        "income_statement": {"current": inc_cur, "yoy": inc_yoy, "current_single_period": flow_single_income, "prior_single_period": prior_flow_income,
                              "source_file": STATEMENT_FILES["income_statement"], "source_columns": inc_cols,
                              "single_period_metadata": _single_period_metadata(income, current_period),
                              "evidence_records": evidence_records["income_statement"]},
        "balance_sheet": {"current": bs_cur, "yoy": bs_yoy, "prior_period_end": bs_prior,
                           "source_file": STATEMENT_FILES["balance_sheet"], "source_columns": bs_cols,
                           "evidence_records": evidence_records["balance_sheet"]},
        "cash_flow": {"current": cf_cur, "yoy": cf_yoy, "current_single_period": flow_single_cash, "prior_single_period": prior_flow_cash,
                       "source_file": STATEMENT_FILES["cash_flow"], "source_columns": cf_cols,
                       "single_period_metadata": _single_period_metadata(cash, current_period),
                       "evidence_records": evidence_records["cash_flow"]},
        "bridges": bridges,
        "signals": signals,
        "industry_context": industry_profile,
        "cash_flow_diagnosis": cash_flow_diagnosis,
        "profit_diagnosis": profit_diagnosis,
        "inventory_review": inventory_review,
        "financial_asset_review": financial_asset_review,
        "management_evidence": management_evidence,
        "forecast_impact": forecast_impact,
        "notes_evidence": {"available_files": notes_files, "status": "available" if notes_files else "unavailable"},
        "limitations": limitations,
        "input_fingerprint": fp,
        "display_convention": {"amount": "亿元=原始货币单位/100000000", "ratio": "百分比",
                               "cash_conversion": "百分比=经营现金流/利润×100", "indeterminate": "null + status=indeterminate"},
    }
    return _clean(result)
