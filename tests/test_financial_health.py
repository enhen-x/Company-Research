"""Focused tests for B3.5 financial-health evidence and G22."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from financial_health_check import HEALTH_CHARTS, run
from financial_health_core import build_health_report
from financial_health_qc import _check


def _write_batch(tmp_path: Path, current: date, report_type: str, *, overrides: dict | None = None) -> Path:
    batch = tmp_path / "batch"
    data = batch / "data"
    (batch / "input").mkdir(parents=True)
    (batch / "reports").mkdir()
    overrides = overrides or {}
    dates = [current]
    yoy = current.replace(year=current.year - 1)
    dates.append(yoy)
    if current.month == 3:
        dates.append(date(current.year - 1, 12, 31))
    elif current.month == 6:
        dates.append(date(current.year, 3, 31))
    elif current.month == 9:
        dates.append(date(current.year, 6, 30))
    elif current.month == 12:
        dates.append(date(current.year, 9, 30))
        dates.append(date(current.year - 1, 9, 30))
    dates = sorted(set(dates))

    def value(kind: str, field: str, period: date, default: float) -> float:
        return overrides.get(kind, {}).get(period.isoformat(), {}).get(field, default)

    income_rows = []
    balance_rows = []
    cash_rows = []
    for period in dates:
        is_current = period == current
        is_yoy = period == yoy
        scale = 100.0 if is_yoy else 120.0 if is_current else 80.0
        income_rows.append({
            "REPORT_DATE": period.isoformat(), "REPORT_TYPE": report_type,
            "TOTAL_OPERATE_INCOME": value("income", "revenue", period, scale),
            "OPERATE_COST": value("income", "cost", period, scale * 0.6),
            "TOTAL_OPERATE_COST": value("income", "total_cost", period, scale * 0.62),
            "OPERATE_PROFIT": value("income", "operating_profit", period, scale * 0.15),
            "TOTAL_PROFIT": value("income", "total_profit", period, scale * 0.14),
            "NETPROFIT": value("income", "net_profit", period, scale * 0.12),
            "PARENT_NETPROFIT": value("income", "parent_net_profit", period, scale * 0.12),
            "DEDUCT_PARENT_NETPROFIT": value("income", "deduct_parent_net_profit", period, scale * 0.11),
            "INVEST_INCOME": value("income", "investment_income", period, 0),
            "FAIRVALUE_CHANGE_INCOME": value("income", "fair_value_change", period, 0),
            "ASSET_DISPOSAL_INCOME": value("income", "asset_disposal_income", period, 0),
            "OTHER_INCOME": value("income", "other_income", period, 0),
            "EXCHANGE_INCOME": value("income", "exchange_income", period, 0),
            "ASSET_IMPAIRMENT_LOSS": value("income", "asset_impairment", period, 0),
            "CREDIT_IMPAIRMENT_LOSS": value("income", "credit_impairment", period, 0),
            "INCOME_TAX": value("income", "income_tax", period, scale * 0.02),
            "MINORITY_INTEREST": value("income", "minority_interest", period, 0),
        })
        balance_rows.append({
            "REPORT_DATE": period.isoformat(), "REPORT_TYPE": report_type,
            "ACCOUNTS_RECE": value("balance", "accounts_receivable", period, scale * 0.2),
            "CONTRACT_ASSET": value("balance", "contract_asset", period, scale * 0.03),
            "INVENTORY": value("balance", "inventory", period, scale * 0.25),
            "CONTRACT_LIAB": value("balance", "contract_liability", period, scale * 0.15),
            "ACCOUNTS_PAYABLE": value("balance", "accounts_payable", period, scale * 0.2),
            "NOTE_PAYABLE": value("balance", "notes_payable", period, scale * 0.05),
            "NOTE_RECE": value("balance", "notes_receivable", period, scale * 0.02),
            "MONETARYFUNDS": value("balance", "cash", period, 500),
            "TOTAL_ASSETS": value("balance", "total_assets", period, 1000),
            "TRADE_FINASSET": value("balance", "trading_financial_assets", period, 0),
            "OTHER_NONCURRENT_FINASSET": value("balance", "other_noncurrent_financial_assets", period, 0),
            "OTHER_EQUITY_INVEST": value("balance", "other_equity_investment", period, 0),
            "LONG_EQUITY_INVEST": value("balance", "long_equity_investment", period, 0),
            "SHORT_LOAN": 0, "LONG_LOAN": 0, "BOND_PAYABLE": 0,
            "LEASE_LIAB": 0, "GOODWILL": 0, "INTANGIBLE_ASSET": 10,
            "DEVELOP_EXPENSE": 0, "CIP": 20,
        })
        ocf = value("cash", "operating_cash_flow", period, scale * 0.14)
        investing = value("cash", "investing_cash_flow", period, -10)
        financing = value("cash", "financing_cash_flow", period, 0)
        begin = 500.0
        end = begin + ocf + investing + financing
        cash_rows.append({
            "REPORT_DATE": period.isoformat(), "REPORT_TYPE": report_type,
            "SALES_SERVICES": value("cash", "sales_cash", period, scale * 0.9),
            "NETCASH_OPERATE": ocf, "NETCASH_INVEST": investing,
            "NETCASH_FINANCE": financing, "CONSTRUCT_LONG_ASSET": -5,
            "BEGIN_CCE": begin, "END_CCE": end, "RATE_CHANGE_EFFECT": 0,
            "NETPROFIT": value("cash", "net_profit", period, scale * 0.12),
            "ASSET_IMPAIRMENT": 0, "FA_IR_DEPR": 2, "IA_AMORTIZE": 1,
            "OPERATE_RECE_REDUCE": 1, "INVENTORY_REDUCE": 1,
            "OPERATE_PAYABLE_ADD": 1,
        })
    data.mkdir()
    pd.DataFrame(income_rows).to_csv(data / "利润表_按报告期.csv", index=False)
    pd.DataFrame(balance_rows).to_csv(data / "资产负债表_按报告期.csv", index=False)
    pd.DataFrame(cash_rows).to_csv(data / "现金流量表_按报告期.csv", index=False)
    return batch


def _configure_industry(batch: Path, industry: str) -> None:
    config = {"industry_profile": {"industry": industry}}
    (batch / "input" / "本期财报体检配置.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize("current_paid,prior_paid,expected", [(25, 10, -15), (5, 10, 5)])
def test_tax_and_staff_cash_outflow_directions(tmp_path, current_paid, prior_paid, expected):
    batch = _write_batch(tmp_path, date(2025, 6, 30), "半年报")
    path = batch / "data" / "现金流量表_按报告期.csv"
    cash = pd.read_csv(path)
    for field in ("PAY_ALL_TAX", "PAY_STAFF_CASH"):
        cash[field] = prior_paid
        cash.loc[cash["REPORT_DATE"] == "2025-06-30", field] = current_paid
    cash.to_csv(path, index=False)
    result = build_health_report(batch / "data", batch.name)
    drivers = {item["type"]: item for item in result["cash_flow_diagnosis"]["drivers"]}
    for label in ("税费支付", "职工薪酬支付"):
        assert drivers[label]["cash_effect"] == expected
        assert drivers[label]["direction"] == ("占用现金" if expected < 0 else "增加现金")


@pytest.mark.parametrize(
    ("period", "report_type", "expected"),
    [
        (date(2025, 12, 31), "年报", "annual"),
        (date(2025, 6, 30), "半年报", "semiannual"),
        (date(2025, 3, 31), "一季报", "q1"),
        (date(2025, 9, 30), "三季报", "q3"),
    ],
)
def test_report_period_identification(tmp_path, period, report_type, expected):
    batch = _write_batch(tmp_path, period, report_type)
    result = build_health_report(batch / "data", batch.name)
    assert result["report_period"]["current"] == period.isoformat()
    assert result["report_period"]["period_type"] == expected
    assert result["report_period"]["yoy"] == period.replace(year=period.year - 1).isoformat()


def test_cumulative_values_are_converted_to_single_period(tmp_path):
    current = date(2025, 6, 30)
    batch = _write_batch(tmp_path, current, "半年报", overrides={
        "income": {"2025-06-30": {"revenue": 300}, "2025-03-31": {"revenue": 100}},
        "cash": {"2025-06-30": {"operating_cash_flow": 40}, "2025-03-31": {"operating_cash_flow": 10}},
    })
    result = build_health_report(batch / "data", batch.name)
    assert result["income_statement"]["current_single_period"]["revenue"] == pytest.approx(200)
    assert result["cash_flow"]["current_single_period"]["operating_cash_flow"] == pytest.approx(30)
    assert result["income_statement"]["single_period_metadata"]["status"] == "comparable"


def test_missing_comparable_period_is_hard_failure(tmp_path):
    batch = _write_batch(tmp_path, date(2025, 6, 30), "半年报")
    for filename in ("利润表_按报告期.csv", "资产负债表_按报告期.csv", "现金流量表_按报告期.csv"):
        path = batch / "data" / filename
        frame = pd.read_csv(path)
        frame = frame[frame["REPORT_DATE"] != "2024-06-30"]
        frame.to_csv(path, index=False)
    result = build_health_report(batch / "data", batch.name)
    assert any(item["id"] == "missing_comparable_period" and item["severity"] == "fail" for item in result["limitations"])


def test_inventory_signal_requires_multiple_indicators(tmp_path):
    current = date(2025, 9, 30)
    batch = _write_batch(tmp_path, current, "三季报", overrides={
        "income": {
            "2025-09-30": {"revenue": 150, "parent_net_profit": 20, "net_profit": 20},
            "2024-09-30": {"revenue": 100, "parent_net_profit": 20, "net_profit": 20},
        },
        "balance": {
            "2025-09-30": {"inventory": 250}, "2024-09-30": {"inventory": 100},
        },
        "cash": {
            "2025-09-30": {"operating_cash_flow": 10}, "2024-09-30": {"operating_cash_flow": 20},
        },
    })
    result = build_health_report(batch / "data", batch.name)
    signal = next(item for item in result["signals"] if item["id"] == "FH_INVENTORY_PRESSURE")
    assert signal["status"] == "indeterminate"
    assert signal["evidence_id"] == "FH.SIGNAL.FH_INVENTORY_PRESSURE"
    key_signal = next(item for item in result["signals"] if item["id"] == "FH_INVENTORY_REVIEW")
    assert key_signal["status"] == "not_triggered"
    assert result["inventory_review"]["applicable"] is False


def test_missing_impairment_fields_are_indeterminate(tmp_path):
    batch = _write_batch(tmp_path, date(2025, 3, 31), "一季报")
    income_path = batch / "data" / "利润表_按报告期.csv"
    income = pd.read_csv(income_path)
    income.drop(columns=["ASSET_IMPAIRMENT_LOSS", "CREDIT_IMPAIRMENT_LOSS"]).to_csv(income_path, index=False)
    result = build_health_report(batch / "data", batch.name)
    signal = next(item for item in result["signals"] if item["id"] == "FH_IMPAIRMENT_CLEANUP")
    assert signal["status"] == "indeterminate"
    assert signal["actual"]["impairment_to_profit"] is None


def test_q4_recurring_seasonality_is_not_a_risk(tmp_path):
    current = date(2025, 12, 31)
    batch = _write_batch(tmp_path, current, "年报", overrides={
        "cash": {
            "2024-09-30": {"operating_cash_flow": 10}, "2024-12-31": {"operating_cash_flow": 100},
            "2025-09-30": {"operating_cash_flow": 10}, "2025-12-31": {"operating_cash_flow": 100},
        }
    })
    result = build_health_report(batch / "data", batch.name)
    signal = next(item for item in result["signals"] if item["id"] == "FH_Q4_OCF_SEASONALITY")
    assert signal["status"] == "triggered"
    assert signal["severity"] == "info"


def test_cash_flow_decline_is_explained_by_inventory_and_not_upgraded(tmp_path):
    batch = _write_batch(tmp_path, date(2025, 6, 30), "半年报", overrides={
        "cash": {
            "2025-06-30": {"operating_cash_flow": 40},
            "2024-06-30": {"operating_cash_flow": 100},
        },
        "balance": {
            "2025-06-30": {"inventory": 300},
            "2024-06-30": {"inventory": 100},
        },
    })
    _configure_industry(batch, "制造业")
    result = build_health_report(batch / "data", batch.name, json.loads((batch / "input" / "本期财报体检配置.json").read_text(encoding="utf-8")))
    diagnosis = result["cash_flow_diagnosis"]
    assert diagnosis["status"] == "explainable"
    assert diagnosis["material_driver_found"] is True
    assert diagnosis["drivers"][0]["type"] == "存货/原材料备货"
    signal = next(item for item in result["signals"] if item["id"] == "FH_CASH_FLOW_EXPLANATION")
    assert signal["status"] == "not_triggered"


def test_engineering_q1_negative_cash_flow_matches_seasonality(tmp_path):
    batch = _write_batch(tmp_path, date(2025, 3, 31), "一季报", overrides={
        "cash": {
            "2025-03-31": {"operating_cash_flow": -20},
            "2024-03-31": {"operating_cash_flow": -5},
        },
    })
    _configure_industry(batch, "电力设备/工程项目")
    config = json.loads((batch / "input" / "本期财报体检配置.json").read_text(encoding="utf-8"))
    result = build_health_report(batch / "data", batch.name, config)
    assert result["cash_flow_diagnosis"]["status"] == "seasonal"
    assert next(item for item in result["signals"] if item["id"] == "FH_CASH_FLOW_EXPLANATION")["status"] == "not_triggered"


def test_profit_decline_from_exchange_loss_is_separated_from_growing_revenue(tmp_path):
    batch = _write_batch(tmp_path, date(2025, 6, 30), "半年报", overrides={
        "income": {
            "2025-06-30": {"revenue": 130, "operating_profit": 14, "parent_net_profit": 10, "net_profit": 10, "exchange_income": -5},
            "2024-06-30": {"revenue": 100, "operating_profit": 16, "parent_net_profit": 16, "net_profit": 16, "exchange_income": 0},
        },
    })
    result = build_health_report(batch / "data", batch.name)
    diagnosis = result["profit_diagnosis"]
    assert diagnosis["status"] == "volatile"
    assert diagnosis["parent_net_profit_change_pct"] < 0
    assert diagnosis["detail_drivers"]
    exchange = next(item for item in diagnosis["detail_drivers"] if item["type"] == "汇兑损益")
    assert exchange["profit_effect"] < 0
    assert result["income_statement"]["current"]["growth_pct"]["revenue"] > 0


def test_consumer_normal_order_supported_inventory_does_not_trigger_risk(tmp_path):
    batch = _write_batch(tmp_path, date(2025, 9, 30), "三季报", overrides={
        "income": {
            "2025-09-30": {"revenue": 120}, "2024-09-30": {"revenue": 100},
        },
        "balance": {
            "2025-09-30": {"inventory": 125, "contract_liability": 25},
            "2024-09-30": {"inventory": 100, "contract_liability": 15},
        },
    })
    _configure_industry(batch, "消费品")
    config = json.loads((batch / "input" / "本期财报体检配置.json").read_text(encoding="utf-8"))
    result = build_health_report(batch / "data", batch.name, config)
    assert result["inventory_review"]["status"] in {"normal", "order_supported"}
    assert next(item for item in result["signals"] if item["id"] == "FH_INVENTORY_REVIEW")["status"] == "not_triggered"


def test_consumer_inventory_growth_and_turnover_deterioration_requires_review(tmp_path):
    batch = _write_batch(tmp_path, date(2025, 9, 30), "三季报", overrides={
        "income": {
            "2025-09-30": {"revenue": 150}, "2024-09-30": {"revenue": 100},
        },
        "balance": {
            "2025-09-30": {"inventory": 250}, "2024-09-30": {"inventory": 100},
        },
        "cash": {
            "2025-09-30": {"operating_cash_flow": 10}, "2024-09-30": {"operating_cash_flow": 20},
        },
    })
    _configure_industry(batch, "消费品")
    config = json.loads((batch / "input" / "本期财报体检配置.json").read_text(encoding="utf-8"))
    result = build_health_report(batch / "data", batch.name, config)
    assert result["inventory_review"]["status"] == "needs_review"
    assert next(item for item in result["signals"] if item["id"] == "FH_INVENTORY_REVIEW")["status"] == "triggered"


def test_financial_asset_profit_contribution_requires_review(tmp_path):
    batch = _write_batch(tmp_path, date(2025, 6, 30), "半年报", overrides={
        "income": {
            "2025-06-30": {"parent_net_profit": 20, "investment_income": 5},
            "2024-06-30": {"parent_net_profit": 15, "investment_income": 0},
        },
        "balance": {
            "2025-06-30": {"trading_financial_assets": 100, "total_assets": 1000},
            "2024-06-30": {"trading_financial_assets": 80, "total_assets": 1000},
        },
    })
    result = build_health_report(batch / "data", batch.name)
    assert result["financial_asset_review"]["status"] == "needs_review"
    assert next(item for item in result["signals"] if item["id"] == "FH_FINANCIAL_ASSET_SPECULATION")["status"] == "triggered"


def test_financial_asset_review_keeps_profit_nature_separate(tmp_path):
    batch = _write_batch(tmp_path, date(2025, 6, 30), "半年报", overrides={
        "income": {
            "2025-06-30": {"investment_income": 8, "fair_value_change": 3, "asset_disposal_income": 2},
        },
        "balance": {
            "2025-06-30": {"long_equity_investment": 240},
            "2024-06-30": {"long_equity_investment": 200},
        },
    })
    result = build_health_report(batch / "data", batch.name)
    review = result["financial_asset_review"]
    assert review["long_equity_investment"] == 240
    assert review["asset_disposal_income"] == 2
    assert [item["type"] for item in review["profit_components"]] == [
        "投资收益（已确认，待附注拆分）", "公允价值变动（浮盈/浮亏候选）", "资产处置收益（已确认）"
    ]
    assert "长期股权投资权益法收益" in review["income_classification"]["investment_income"]


def test_management_explanation_extracts_topic_and_source(tmp_path):
    batch = _write_batch(tmp_path, date(2025, 6, 30), "半年报")
    (batch / "data" / "2025_半年报.txt").write_text(
        "管理层讨论与分析\n本期归母净利润下降主要由于汇兑损失增加，主营业务收入保持增长。\n经营情况说明：原材料备货增加导致经营现金流下降。",
        encoding="utf-8",
    )
    result = build_health_report(batch / "data", batch.name)
    evidence = result["management_evidence"]
    assert evidence["status"] == "available"
    assert {item["topic"] for item in evidence["excerpts"]} >= {"利润", "汇兑", "现金流", "存货"}
    assert all(item["source_file"] == "2025_半年报.txt" for item in evidence["excerpts"])


def test_missing_management_filing_is_a_warning_not_a_conclusion(tmp_path):
    batch = _write_batch(tmp_path, date(2025, 6, 30), "半年报")
    result = build_health_report(batch / "data", batch.name)
    assert result["management_evidence"]["status"] == "missing_current_period"
    assert any(item["id"] == "current_filing_not_available" and item["severity"] == "warn" for item in result["limitations"])


def _report_for_health(result: dict) -> str:
    sections = "\n".join(f"### {name}" for name in (
        "本期财报结论先行", "现金流：赚的是真钱还是账面利润", "经营现金流变化原因",
        "利润波动原因", "存货专项检查", "非主营投资和金融资产检查",
        "管理层解释与数据验证", "财务美化/劣化风险信号",
        "对全年预测和估值的影响",
    ))
    ids = "\n".join(item["title"] for item in result["signals"] if item.get("key_finding") and item["status"] in {"triggered", "indeterminate"})
    charts = "\n".join(f"![体检图](图表/{name})" for name in HEALTH_CHARTS)
    impact = "\n".join(str(result.get("forecast_impact", {}).get(key, "待观察")) for key in ("revenue", "profit", "cash_flow", "valuation_risk"))
    return f"# 报告\n\n## §4.3 本期财报体检\n\n{sections}\n\n{charts}\n\n{ids}\n\n{impact}\n\n引用 reports/本期财报体检.json\n"


def test_run_generates_reader_facing_framework_and_fixed_charts(tmp_path):
    batch = _write_batch(tmp_path, date(2025, 3, 31), "一季报")
    _, _, result = run(batch)
    section_path = batch / "reports" / "本期财报体检_成文框架.md"
    section = section_path.read_text(encoding="utf-8")
    assert "现金流：赚的是真钱还是账面利润" in section
    assert "**" in section
    assert "source_fields" not in section
    assert "income." not in section
    assert "balance." not in section
    assert "cash." not in section
    assert "利润波动原因" in section
    assert all((batch / "reports" / "图表" / name).is_file() for name in HEALTH_CHARTS)


def test_g22_allows_warn_but_blocks_stale_evidence(tmp_path):
    batch = _write_batch(tmp_path, date(2025, 3, 31), "一季报")
    json_path, _, result = run(batch)
    report_path = batch / "reports" / "测试_分析报告.md"
    report_path.write_text(_report_for_health(result), encoding="utf-8")
    checks, exit_code = _check(batch, report_path)
    assert exit_code == 0
    assert any(item["status"] == "WARN" for item in checks)

    with (batch / "data" / "利润表_按报告期.csv").open("a", encoding="utf-8") as handle:
        handle.write("\n")
    _, stale_exit = _check(batch, report_path)
    assert stale_exit == 1


def test_g22_rejects_non_numeric_statement_value_and_tampered_summary(tmp_path):
    batch = _write_batch(tmp_path, date(2025, 3, 31), "一季报")
    _, summary_path, result = run(batch)
    report_path = batch / "reports" / "测试_分析报告.md"
    report_path.write_text(_report_for_health(result), encoding="utf-8")

    evidence_path = batch / "reports" / "本期财报体检.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["income_statement"]["current"]["revenue"] = "120"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    checks, exit_code = _check(batch, report_path)
    assert exit_code == 1
    assert next(item for item in checks if item["id"] == "json_field_types")["status"] == "FAIL"

    _, summary_path, result = run(batch)
    report_path.write_text(_report_for_health(result), encoding="utf-8")
    summary_path.write_text(summary_path.read_text(encoding="utf-8") + "\n手工篡改\n", encoding="utf-8")
    checks, exit_code = _check(batch, report_path)
    assert exit_code == 1
    assert next(item for item in checks if item["id"] == "summary_consistency")["status"] == "FAIL"


def test_separate_notes_do_not_double_count_account_totals(tmp_path):
    batch = _write_batch(tmp_path, date(2026, 6, 30), "中报")
    file = batch / "data" / "资产负债表_按报告期.csv"
    frame = pd.read_csv(file)
    frame["NOTE_ACCOUNTS_PAYABLE"] = frame["ACCOUNTS_PAYABLE"] + frame["NOTE_PAYABLE"]
    frame["NOTE_ACCOUNTS_RECE"] = frame["ACCOUNTS_RECE"] + frame["NOTE_RECE"]
    frame.to_csv(file, index=False, encoding="utf-8-sig")
    report = build_health_report(batch / "data")
    cur = report["balance_sheet"]["current"]
    assert cur["notes_payable"] == pytest.approx(6.0)
    assert cur["notes_receivable"] == pytest.approx(2.4)
    wc = report["bridges"]["working_capital"]
    assert wc["changes_vs_yoy"]["notes_payable"] == pytest.approx(1.0)
