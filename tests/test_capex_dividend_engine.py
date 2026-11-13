"""Tests for Capex & Dividend Transition Engine integration into company-research-v3."""
import json
import sys
from pathlib import Path

import pandas as pd

import capex_dividend_engine as cde
from chart_qc import FIG_MAP, _capex_trigger_status, check_listing_vs_embed


def _write_sample_batch(batch: Path, *, with_projects: bool = True) -> None:
    data = batch / "data"
    data.mkdir(parents=True, exist_ok=True)
    yrs = ["2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"]

    pd.DataFrame({
        "REPORT_DATE": yrs,
        "NETCASH_OPERATE": [200e8, 220e8, 240e8, 260e8, 315.7e8],
        "CONSTRUCT_LONG_ASSET": [120e8, 150e8, 230e8, 235e8, 214.38e8],
    }).to_csv(data / "现金流量表_按报告期.csv", index=False, encoding="utf-8-sig")

    pd.DataFrame({
        "REPORT_DATE": yrs,
        "CIP": [300e8, 350e8, 420e8, 460e8, 410e8],
        "FIXED_ASSET": [1000e8, 1050e8, 1100e8, 1150e8, 1250e8],
        "TOTAL_LIABILITIES": [1400e8, 1500e8, 1600e8, 1650e8, 1620e8],
        "TOTAL_ASSETS": [2200e8, 2350e8, 2500e8, 2600e8, 2650e8],
        "MONETARYFUNDS": [80e8, 85e8, 90e8, 95e8, 110e8],
    }).to_csv(data / "资产负债表_按报告期.csv", index=False, encoding="utf-8-sig")

    pd.DataFrame({
        "REPORT_DATE": yrs,
        "PARENT_NETPROFIT": [50e8, 48e8, 67e8, 66.4e8, 73.93e8],
        "NETPROFIT": [85e8, 82e8, 120e8, 122e8, 134.61e8],
        "FE_INTEREST_EXPENSE": [42e8, 43e8, 44e8, 42e8, 40.92e8],
    }).to_csv(data / "利润表_按报告期.csv", index=False, encoding="utf-8-sig")

    pd.DataFrame({
        "报告期": yrs,
        "总股本": [7.45e9] * 5,
        "现金分红-现金分红比例描述": ["10派2.5元", "10派2.8元", "10派4.95元", "10派4.9元", "10派5.458元"],
        "除权除息日": ["2022-07-01", "2023-07-01", "2024-07-01", "2025-07-01", "2026-07-01"],
    }).to_csv(data / "分红送配记录.csv", index=False, encoding="utf-8-sig")

    dates = pd.date_range("2020-01-02", "2026-08-01", freq="W")
    pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "close": [10.0 + i * 0.02 for i in range(len(dates))],
    }).to_csv(data / "日线股价_前复权.csv", index=False, encoding="utf-8-sig")


def test_capex_engine_init_and_run_consolidated_fcfe(tmp_path):
    batch = tmp_path / "SH.600886 国投电力" / "2026_11_13"
    _write_sample_batch(batch)

    rc_init = cde.main(["--dir", str(batch), "--init-template", "--company", "国投电力", "--code", "600886"])
    assert rc_init == 0
    cfg_path = batch / "input" / "capex_dividend_plan.json"
    assert cfg_path.is_file()

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["capex_plan"]["key_projects"] = [
        {
            "project_name": "示例水电站",
            "budget_billion": 200.0,
            "invested_billion": 150.0,
            "remaining_billion": 50.0,
            "progress": "75%",
            "expected_completion": "2026年底",
            "impact": "转固后贡献增量现金流",
        }
    ]
    cfg["dividend_commitment"]["statutory_floor_payout_ratio"] = 0.55
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    rc_run = cde.main(["--dir", str(batch)])
    assert rc_run == 0

    chart_dir = batch / "reports" / "图表"
    assert (chart_dir / "图19_Capex规划与股价联动.png").is_file()
    assert (chart_dir / "图20_重大在建工程转固时间轴.png").is_file()
    assert (chart_dir / "图21_分红可行性与造血留存.png").is_file()
    assert (batch / "reports" / "Capex与分红跃迁专项.md").is_file()

    out_json = json.loads((batch / "reports" / "capex_dividend_analysis.json").read_text(encoding="utf-8"))
    row_2025 = next(r for r in out_json["combined_timeseries"] if r["year"] == "2025")
    # 315.70 - 214.38 - 40.92 = 60.40 -> 60.40 / 134.61 = 0.45 (not 1.37x parent distortion)
    assert row_2025["FCFE"] == 60.40
    assert row_2025["FCFE_NP_Ratio"] == 0.45
    assert 54.0 <= row_2025["Payout_Ratio"] <= 56.0


def test_chart_qc_capex_conditional_gating(tmp_path):
    assert 19 in FIG_MAP and 20 in FIG_MAP and 21 in FIG_MAP
    (tmp_path / "input").mkdir(parents=True)
    assert _capex_trigger_status(tmp_path) == (False, False)

    lines = ["| 图19 | capex | §4 |", "| 图20 | timeline | §4 |", "| 图21 | fcf | §6 |"]
    assert check_listing_vs_embed(lines, tmp_path) == []

    (tmp_path / "input" / "capex_dividend_plan.json").write_text(
        json.dumps({"enabled": True, "capex_plan": {"key_projects": [{"project_name": "A"}]}}),
        encoding="utf-8",
    )
    assert _capex_trigger_status(tmp_path) == (True, True)
    issues = check_listing_vs_embed(lines, tmp_path)
    assert any("图19" in x for x in issues)
    assert any("图21" in x for x in issues)
