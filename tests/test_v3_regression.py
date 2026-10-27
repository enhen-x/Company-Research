"""Regression harness invariants: coverage, source protection, accounting and bounded orchestration."""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

import v3_regression as regression


def test_discovery_chooses_latest_batch_with_data_and_ignores_other_stocks(tmp_path):
    company = tmp_path / "SH.600039 四川路桥"
    for date in ("2026_10_20", "2026_10_27"):
        data = company / date / "data"
        data.mkdir(parents=True)
        (data / "利润表_按报告期.csv").write_text("x\n1\n", encoding="utf-8")
    empty = company / "2026_10_28" / "data"
    empty.mkdir(parents=True)
    (tmp_path / "SH.600887 伊利股份" / "2026_10_13" / "data").mkdir(parents=True)

    result = regression.discover_batches(tmp_path, ("600039",))
    assert result["600039"].name == "2026_10_27"
    assert set(result) == {"600039"}


def test_copy_is_minimal_and_records_source_hashes(tmp_path):
    batch = tmp_path / "2026_10_27"
    (batch / "data").mkdir(parents=True)
    (batch / "input").mkdir()
    (batch / "data" / "利润表_按报告期.csv").write_text("a\n1\n", encoding="utf-8")
    (batch / "data" / "年报.pdf").write_bytes(b"large source omitted")
    (batch / "input" / "研究模型.json").write_text("{}", encoding="utf-8")
    temp = tmp_path / "temporary"
    hashes = regression._copy_case(batch, temp)

    assert set(hashes) == {"data/利润表_按报告期.csv", "input/研究模型.json"}
    assert not (temp / "data" / "年报.pdf").exists()
    assert hashes["data/利润表_按报告期.csv"] == regression._sha(batch / "data" / "利润表_按报告期.csv")


@pytest.mark.parametrize(
    "cases,expected",
    [([], "INCOMPLETE"), ([{"status": "SKIP"}], "INCOMPLETE"),
     ([{"status": "PASS"}, {"status": "SKIP"}], "INCOMPLETE"),
     ([{"status": "FAIL"}, {"status": "SKIP"}], "FAIL"),
     ([{"status": "TIMEOUT"}, {"status": "PASS"}], "FAIL"),
     ([{"status": "PASS"}, {"status": "PASS"}], "PASS")],
)
def test_phase_never_passes_with_missing_coverage_and_failure_wins(cases, expected):
    assert regression._phase_status(cases) == expected


def test_valuation_audit_checks_source_units_and_unknown_debt_remains_null(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "input").mkdir()
    period = "2025-12-31"
    pd.DataFrame([{"REPORT_DATE": period, "PARENT_NETPROFIT": 12_000_000,
                   "OPERATE_INCOME": 80_000_000}]).to_csv(tmp_path / "data" / "利润表_按报告期.csv", index=False)
    pd.DataFrame([{"REPORT_DATE": period, "MONETARYFUNDS": 5_000_000,
                   "TOTAL_ASSETS": 100_000_000}]).to_csv(tmp_path / "data" / "资产负债表_按报告期.csv", index=False)
    pd.DataFrame([{"REPORT_DATE": period, "NETCASH_OPERATE": 9_000_000,
                   "CONSTRUCT_LONG_ASSET": 2_000_000}]).to_csv(tmp_path / "data" / "现金流量表_按报告期.csv", index=False)
    config = {"financial_period": period, "net_profit_C": 12, "base_revenue": 80,
              "cash_balance": 5, "total_assets": 100, "fcf": 7,
              "interest_bearing_debt": None, "low_10y_close": None, "cash_protection": None}
    (tmp_path / "input" / "穿透回报率_输入.json").write_text(json.dumps(config), encoding="utf-8")

    result = regression._valuation_audit(tmp_path)
    assert result["status"] == "PASS"
    assert result["checks"]["interest_bearing_debt"]["complete_components"] is False
    assert result["checks"]["fcf"]["unit"] == "百万元"


def test_valuation_audit_rejects_invented_zero_debt_when_components_missing(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "input").mkdir()
    period = "2025-12-31"
    pd.DataFrame([{"REPORT_DATE": period, "PARENT_NETPROFIT": 1_000_000,
                   "OPERATE_INCOME": 2_000_000}]).to_csv(tmp_path / "data" / "利润表_按报告期.csv", index=False)
    pd.DataFrame([{"REPORT_DATE": period, "MONETARYFUNDS": 1_000_000,
                   "TOTAL_ASSETS": 4_000_000, "SHORT_LOAN": 0}]).to_csv(tmp_path / "data" / "资产负债表_按报告期.csv", index=False)
    pd.DataFrame([{"REPORT_DATE": period, "NETCASH_OPERATE": 3_000_000,
                   "CONSTRUCT_LONG_ASSET": 1_000_000}]).to_csv(tmp_path / "data" / "现金流量表_按报告期.csv", index=False)
    config = {"financial_period": period, "net_profit_C": 1, "base_revenue": 2,
              "cash_balance": 1, "total_assets": 4, "fcf": 2,
              "interest_bearing_debt": 0, "low_10y_close": None, "cash_protection": None}
    (tmp_path / "input" / "穿透回报率_输入.json").write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="缺项却未保留null"):
        regression._valuation_audit(tmp_path)


def test_phase_rerun_replaces_only_requested_phase_and_missing_stock_is_skip(tmp_path, monkeypatch):
    output = tmp_path / "summary.json"
    output.write_text(json.dumps({"schema_version": 1, "root": str(tmp_path.resolve()),
                                  "stocks": ["600039"], "phases": {"topics": {"status": "old"},
                                  "valuation": {"status": "retained"}}}), encoding="utf-8")
    monkeypatch.setattr(regression, "discover_batches", lambda root, stocks: {})

    result = regression.run_suite(tmp_path, ("600039",), "topics", output, case_timeout=20)
    assert result["phases"]["topics"]["status"] == "INCOMPLETE"
    assert result["phases"]["topics"]["cases"][0]["status"] == "SKIP"
    assert result["phases"]["valuation"]["status"] == "retained"
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_worker_timeout_result_does_not_mutate_historical_source(tmp_path, monkeypatch):
    batch = tmp_path / "SH.600039 四川路桥" / "2026_10_27"
    (batch / "data").mkdir(parents=True)
    source = batch / "data" / "利润表_按报告期.csv"
    source.write_text("x\n1\n", encoding="utf-8")

    def timeout(command, **kwargs):
        return {"status": "TIMEOUT", "elapsed_seconds": kwargs["timeout"], "output": "bounded"}

    monkeypatch.setattr(regression, "run_process", timeout)
    result = regression._run_case(batch, "600039", "topics", 10)

    assert result["status"] == "TIMEOUT"
    assert result["source_unchanged"] is True
    assert source.read_text(encoding="utf-8") == "x\n1\n"
    assert len(list(tmp_path.iterdir())) == 1


def test_one_stock_timeout_does_not_prevent_later_stock_and_cannot_be_masked(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(regression, "discover_batches", lambda root, stocks: {code: tmp_path / code for code in stocks})

    def run_case(batch, code, phase, timeout):
        calls.append(code)
        return {"code": code, "status": "TIMEOUT" if code == "600039" else "PASS"}

    monkeypatch.setattr(regression, "_run_case", run_case)
    result = regression.run_suite(tmp_path, ("600039", "600887"), "runtime", tmp_path / "summary.json", case_timeout=10)
    assert calls == ["600039", "600887"]
    assert result["phases"]["runtime"]["status"] == "FAIL"
    assert result["last_invocation"]["status"] == "FAIL"


def test_all_phase_failure_is_not_hidden_by_later_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(regression, "discover_batches", lambda root, stocks: {"600039": tmp_path})
    monkeypatch.setattr(regression, "_run_case", lambda batch, code, phase, timeout: {
        "code": code, "status": "FAIL" if phase == "topics" else "PASS"})

    result = regression.run_suite(tmp_path, ("600039",), "all", tmp_path / "summary.json", case_timeout=10)
    assert result["phases"]["runtime"]["status"] == "PASS"
    assert result["last_invocation"]["status"] == "FAIL"


def test_real_worker_preserves_missing_input_as_incomplete_and_cleans_temp(tmp_path):
    batch = tmp_path / "SH.600039 四川路桥" / "2026_10_27"
    (batch / "data").mkdir(parents=True)
    source = batch / "data" / "主要财务指标_按报告期.csv"
    source.write_text("REPORT_DATE,BPS\n2025-12-31,5\n", encoding="utf-8")

    result = regression._run_case(batch, "600039", "topics", 20)
    assert result["status"] == "INCOMPLETE"
    assert result["research_status"] == "INCOMPLETE"
    assert result["research_completed"] is False
    assert result["source_unchanged"] is True
    assert not (batch / "reports").exists()
    command = result["steps"][0]["command"]
    temporary_project = Path(command[command.index("--dir") + 1])
    assert not temporary_project.exists()


def test_cache_probe_never_fetches_and_second_cycle_does_not_create_files(tmp_path):
    (tmp_path / "data").mkdir()
    profile = tmp_path / "data" / "公司概况.csv"
    profile.write_text("item,value\n总股本,1000000\n", encoding="utf-8")
    before = regression._sha(profile)

    result = regression._cache_reuse_check(tmp_path, "600039")
    assert result["status"] == "PASS"
    assert result["network_calls"] == 0
    assert result["cycles"] == 2
    assert result["same_file_set"] is True
    assert regression._sha(profile) == before


def test_known_data_gap_is_confirmed_against_source_not_error_text_only(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    pd.DataFrame([{"REPORT_DATE": "2025-12-31", "FA_IR_DEPR": 1,
                   "IA_AMORTIZE": 2, "LPE_AMORTIZE": 3,
                   "USERIGHT_ASSET_AMORTIZE": None}]).to_csv(data / "现金流量表_按报告期.csv", index=False)
    gaps = regression._confirmed_depreciation_gap(data)
    assert gaps == [{"period": "2025-12-31", "missing_fields": ["USERIGHT_ASSET_AMORTIZE"]}]


def test_wrong_report_period_or_unit_conversion_fails_independent_valuation_audit(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "input").mkdir()
    pd.DataFrame([{"REPORT_DATE": "2025-12-31", "PARENT_NETPROFIT": 12_000_000,
                   "OPERATE_INCOME": 80_000_000}]).to_csv(tmp_path / "data" / "利润表_按报告期.csv", index=False)
    config = {"financial_period": "2025-12-31", "net_profit_C": 1200}
    (tmp_path / "input" / "穿透回报率_输入.json").write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="与源CSV不符"):
        regression._valuation_audit(tmp_path)


@pytest.fixture
def build_batch(tmp_path, monkeypatch):
    batch = tmp_path / "history" / "SH.600039 四川路桥" / "2026_10_27"
    files = {"data/source.csv": "actual,1\n", "input/config.json": "{\"fact\":1}",
             "reports/四川路桥_600039_分析报告.md": "# Main report\n",
             "reports/四川路桥_600039_分析报告.html": "stale main HTML",
             "reports/四川路桥_600039_图表.html": "stale interactive HTML",
             "reports/流水线执行状态.json": "{\"status\":\"PASS\"}",
             "reports/图表期间覆盖.json": "stale derived coverage",
             "reports/图表最新期数据.json": "stale derived latest",
             "reports/图表/图01_旧图.png": "stale fixed PNG",
             "reports/图表/体检_盈利.png": "genuine health PNG",
             "reports/本期财报体检.json": "{\"project\":\"2026_10_27\"}",
             "reports/本期财报体检_证据摘要.md": "genuine health evidence",
             "scripts/gate_all.py": "old gate script",
             "scripts/__pycache__/old.pyc": "cache",
             ".browser_qa_profile/locked": "runtime browser cache"}
    for name, text in files.items():
        path = batch / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    skill = tmp_path / "skill"
    (skill / "scripts" / "__pycache__").mkdir(parents=True)
    (skill / "scripts" / "gate_all.py").write_text("current gate script", encoding="utf-8")
    (skill / "scripts" / "chart_qc.py").write_text("current chart QC", encoding="utf-8")
    (skill / "scripts" / "__pycache__" / "stale.pyc").write_bytes(b"cache")
    monkeypatch.setattr(regression, "SKILL", skill)
    return batch


def _write_successful_build(project, *, ledger_updates=None, artifacts=True):
    ledger = {"status": "PASS", "mode": "BUILD", "legacy": False, "technical_pass": True,
              "build_completed": True, "fully_rebuilt": True, "delivery_ready": True,
              "stages": [{"name": "actual rebuild", "status": "PASS", "elapsed_seconds": 1.25}],
              "elapsed_seconds": 1.25, "run_id": "fresh-run"}
    ledger.update(ledger_updates or {})
    (project / "reports" / "流水线执行状态.json").write_text(json.dumps(ledger), encoding="utf-8")
    if artifacts:
        for name in ("reports/四川路桥_600039_分析报告.html", "reports/四川路桥_600039_图表.html",
                     "reports/图表/图01_新图.png"):
            (project / name).write_text("new build artifact", encoding="utf-8")
    return {"status": "PASS", "exit_code": 0, "elapsed_seconds": 1.5, "output": "fresh gate output"}


def test_build_owns_temp_preserves_date_and_sources_and_synchronizes_current_scripts(build_batch, monkeypatch):
    before = regression._batch_hashes(build_batch)
    projects = []

    def gate(command, **kwargs):
        project = kwargs["cwd"]
        projects.append(project)
        assert project.name == build_batch.name == "2026_10_27"
        assert project.exists() and project.parent.exists()
        assert command[command.index("--stage-timeout") + 1] == "300"
        assert command[command.index("--total-timeout") + 1] == "1200"
        assert "--check-only" not in command and "--legacy" not in command and "--incremental" not in command
        assert (project / "scripts" / "gate_all.py").read_text(encoding="utf-8") == "current gate script"
        assert (project / "scripts" / "chart_qc.py").read_text(encoding="utf-8") == "current chart QC"
        assert not (project / "scripts" / "__pycache__").exists()
        assert not (project / ".browser_qa_profile").exists()
        for name in ("reports/图表/图01_旧图.png", "reports/流水线执行状态.json",
                     "reports/图表期间覆盖.json", "reports/图表最新期数据.json",
                     "reports/四川路桥_600039_分析报告.html", "reports/四川路桥_600039_图表.html"):
            assert not (project / name).exists()
        for name in ("data/source.csv", "input/config.json", "reports/四川路桥_600039_分析报告.md",
                     "reports/图表/体检_盈利.png", "reports/本期财报体检.json", "reports/本期财报体检_证据摘要.md"):
            assert (project / name).read_bytes() == (build_batch / name).read_bytes()
        return _write_successful_build(project)

    monkeypatch.setattr(regression, "run_process", gate)
    result = regression._run_build_case(build_batch, "600039")
    assert result["status"] == "PASS"
    assert result["technical_pass"] and result["build_completed"]
    assert result["research_status"] == "INCOMPLETE" and result["research_completed"] is False
    assert result["human_review"] == "NOT_ASSESSED"
    assert result["source_unchanged"] and result["temporary_source_unchanged"]
    assert result["source_hashes_before"] == before == result["source_hashes_after"]
    assert result["gate_ledger"]["stages"][0]["elapsed_seconds"] == 1.25
    assert result["artifacts"]["fixed_png_count"] == 1 and result["artifacts"]["health_png_count"] == 1
    assert result["artifacts"]["main_html_present"] and result["artifacts"]["interactive_html_present"]
    assert result["temporary_directory_removed"] and not projects[0].parent.exists()
    assert (build_batch / "reports" / "图表" / "图01_旧图.png").exists()


@pytest.mark.parametrize("ledger_updates", [
    {"mode": "CHECK_ONLY"}, {"legacy": True}, {"fully_rebuilt": False},
    {"build_completed": False}, {"technical_pass": False}, {"delivery_ready": False},
    {"stages": [{"name": "old", "status": "REUSED"}]},
    {"stages": [{"name": "blocked", "status": "BLOCKED"}]}, {"stages": []},
])
def test_build_rejects_check_only_legacy_reused_or_incomplete_completion(build_batch, monkeypatch, ledger_updates):
    monkeypatch.setattr(regression, "run_process", lambda command, **kwargs:
                        _write_successful_build(kwargs["cwd"], ledger_updates=ledger_updates))
    result = regression._run_build_case(build_batch, "600039")
    assert result["status"] == "FAIL" and result["technical_pass"] is False
    assert result["temporary_directory_removed"] and result["source_unchanged"]


@pytest.mark.parametrize("status,exit_code", [("TIMEOUT", None), ("FAIL", 7)])
def test_build_process_failure_cannot_be_masked_by_passing_ledger(build_batch, monkeypatch, status, exit_code):
    def gate(command, **kwargs):
        result = _write_successful_build(kwargs["cwd"])
        return {**result, "status": status, "exit_code": exit_code, "output": "prefix" + "x" * 9000 + "failure-tail"}
    monkeypatch.setattr(regression, "run_process", gate)
    result = regression._run_build_case(build_batch, "600039")
    assert result["status"] == status and not result["technical_pass"]
    assert len(result["failure_tail"]) == 8000 and result["failure_tail"].endswith("failure-tail")
    assert result["temporary_directory_removed"] and result["source_unchanged"]


def test_build_missing_fresh_ledger_cannot_reuse_historical_pass(build_batch, monkeypatch):
    monkeypatch.setattr(regression, "run_process", lambda *args, **kwargs:
                        {"status": "PASS", "exit_code": 0, "output": "no fresh ledger"})
    result = regression._run_build_case(build_batch, "600039")
    assert result["status"] == "FAIL" and "ledger_error" in result
    assert result["temporary_directory_removed"]


def test_build_missing_fresh_artifacts_cannot_pass(build_batch, monkeypatch):
    monkeypatch.setattr(regression, "run_process", lambda command, **kwargs:
                        _write_successful_build(kwargs["cwd"], artifacts=False))
    result = regression._run_build_case(build_batch, "600039")
    assert result["status"] == "FAIL" and result["artifacts"]["fixed_png_count"] == 0


def test_build_preserves_preflight_failure_reason_when_artifacts_were_never_built(build_batch, monkeypatch):
    def preflight_failure(command, **kwargs):
        result = _write_successful_build(kwargs["cwd"], artifacts=False, ledger_updates={
            "status": "FAIL", "error": "missing period_review input evidence",
            "technical_pass": False, "build_completed": False,
            "stages": [{"name": "period preflight", "status": "FAIL", "elapsed_seconds": 2}]})
        return {**result, "status": "FAIL", "exit_code": 1, "output": "missing period_review input evidence"}
    monkeypatch.setattr(regression, "run_process", preflight_failure)
    result = regression._run_build_case(build_batch, "600039")
    assert result["status"] == "FAIL" and result["error"] == "missing period_review input evidence"
    assert result["artifacts"]["fixed_png_count"] == 0


def test_build_exception_still_cleans_parent_owned_temp(build_batch, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("controlled gate failure")
    monkeypatch.setattr(regression, "run_process", broken)
    result = regression._run_build_case(build_batch, "600039")
    assert result["status"] == "FAIL" and "controlled gate failure" in result["error"]
    assert result["temporary_directory_removed"] and result["source_unchanged"]


@pytest.mark.parametrize("mutate_history", [False, True])
def test_build_detects_protected_source_changes(build_batch, monkeypatch, mutate_history):
    def gate(command, **kwargs):
        project = kwargs["cwd"]
        target = build_batch if mutate_history else project
        (target / "data" / "source.csv").write_text("changed fact", encoding="utf-8")
        return _write_successful_build(project)
    monkeypatch.setattr(regression, "run_process", gate)
    result = regression._run_build_case(build_batch, "600039")
    assert result["status"] == "FAIL" and not result["technical_pass"]
    assert result["source_unchanged"] is (not mutate_history)
    assert result["temporary_source_unchanged"] is mutate_history
    assert result["temporary_directory_removed"]


def test_build_ambiguous_report_is_incomplete_and_does_not_execute(build_batch, monkeypatch):
    (build_batch / "reports" / "额外_600039_分析报告.md").write_text("extra", encoding="utf-8")
    monkeypatch.setattr(regression, "run_process", lambda *args, **kwargs: pytest.fail("must not execute"))
    result = regression._run_build_case(build_batch, "600039")
    assert result["status"] == "INCOMPLETE" and result["temporary_directory_removed"]
    assert result["source_unchanged"]


def test_build_only_updates_own_summary_phase_even_with_different_selected_stocks(tmp_path, monkeypatch):
    output = tmp_path / "summary.json"
    original = {"schema_version": 1, "root": str(tmp_path.resolve()), "stocks": list(regression.DEFAULT_STOCKS),
                "phases": {"topics": {"status": "old topics"}, "runtime": {"status": "old runtime"}}}
    output.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(regression, "discover_batches", lambda *args: {"600039": tmp_path})
    calls = []
    def build(batch, code, **kwargs):
        calls.append((code, kwargs))
        return {"code": code, "status": "PASS"}
    monkeypatch.setattr(regression, "_run_build_case", build)
    monkeypatch.setattr(regression, "_run_case", lambda *args: pytest.fail("must use parent build"))
    result = regression.run_suite(tmp_path, ("600039",), "build", output)
    assert calls == [("600039", {"stage_timeout": 300, "total_timeout": 1200})]
    assert result["phases"]["topics"] == original["phases"]["topics"]
    assert result["phases"]["runtime"] == original["phases"]["runtime"]
    assert result["phases"]["build"]["stocks"] == ["600039"]
    assert result["last_invocation"]["stocks"] == ["600039"]
    assert result["stocks"] == list(regression.DEFAULT_STOCKS)


def test_all_remains_original_three_phases_and_never_runs_build(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(regression, "discover_batches", lambda *args: {"600039": tmp_path})
    monkeypatch.setattr(regression, "_run_build_case", lambda *args, **kwargs: pytest.fail("all excludes build"))
    def phase(batch, code, name, timeout):
        calls.append(name)
        return {"status": "PASS"}
    monkeypatch.setattr(regression, "_run_case", phase)
    result = regression.run_suite(tmp_path, ("600039",), "all", tmp_path / "summary.json")
    assert calls == ["topics", "valuation", "runtime"]
    assert set(result["phases"]) == {"topics", "valuation", "runtime"}


def test_build_selected_stock_rerun_preserves_other_build_case_evidence(tmp_path, monkeypatch):
    output = tmp_path / "summary.json"
    evidence = {"code": "600039", "status": "PASS", "source_unchanged": True,
                "gate_ledger": {"run_id": "original-fresh-run"}}
    old_selected = {"code": "600887", "status": "FAIL", "old_evidence": True}
    output.write_text(json.dumps({"root": str(tmp_path.resolve()), "stocks": list(regression.DEFAULT_STOCKS),
                                 "phases": {"build": {"cases": [evidence, old_selected]}}}), encoding="utf-8")
    monkeypatch.setattr(regression, "discover_batches", lambda root, stocks: {code: tmp_path for code in stocks})
    monkeypatch.setattr(regression, "_run_build_case", lambda batch, code, **kwargs: {"code": code, "status": "PASS"})
    result = regression.run_suite(tmp_path, ("600887", "601899"), "build", output)
    built = result["phases"]["build"]
    assert built["cases"] == [evidence, {"code": "600887", "status": "PASS"}, {"code": "601899", "status": "PASS"}]
    assert built["retained_case_codes"] == ["600039"]
    assert built["invocation_stocks"] == ["600887", "601899"]
    assert built["stocks"] == list(regression.DEFAULT_STOCKS) and built["requested"] == 3
    assert built["status"] == "PASS"


@pytest.mark.parametrize("stage,total", [(0, 1200), (-1, 1200), (True, 1200),
                                                  (float("nan"), 1200), (300, float("inf")), (300, 299)])
def test_build_rejects_invalid_budgets_before_copy(tmp_path, stage, total):
    with pytest.raises(ValueError):
        regression._run_build_case(tmp_path / "absent", "600039", stage_timeout=stage, total_timeout=total)


def test_worker_cannot_silently_claim_build(tmp_path):
    with pytest.raises(SystemExit) as exc:
        regression.main(["--worker", "--phase", "build", "--project", str(tmp_path)])
    assert exc.value.code == 2 and not (tmp_path / "worker-result.json").exists()
