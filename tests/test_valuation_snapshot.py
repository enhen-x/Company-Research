"""Known-answer tests for the offline B2 valuation adapter; no external APIs."""
import builtins
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import types

import pandas as pd
import pytest

import valuation_engine
from valuation_engine import ValuationEngine
from valuation_snapshot import SnapshotError, ValuationSnapshot


@pytest.fixture
def batch(tmp_path):
    batch = tmp_path / "2026_10_27"
    (batch / "data").mkdir(parents=True)
    periods = ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31", "2021-12-31"]
    rows = [{"SECUCODE": "600039.SH", "SECURITY_CODE": "600039", "SECURITY_NAME_ABBR": "合成测试", "CURRENCY": "CNY", "REPORT_DATE": period} for period in periods]
    datasets = []
    def write(filename, source, frame):
        frame.to_csv(batch / "data" / filename, index=False)
        datasets.append({"file": filename, "source": source, "status": "success"})
    income = pd.DataFrame(rows).assign(OPERATE_INCOME=[1200, 1100, 1000, 950, 900], PARENT_NETPROFIT=[120, 110, 100, 95, 90], BASIC_EPS=[1.2, 1.1, 1, .95, .9], TOTAL_PROFIT=[150, 140, 130, 120, 110], INCOME_TAX=[30, 28, 26, 24, 22], FE_INTEREST_EXPENSE=[12, 11, 10, 9, 8], FINANCE_EXPENSE=[-10, -9, -8, -7, -6])
    write("利润表_按报告期.csv", "akshare.stock_profit_sheet_by_report_em", income)
    write("资产负债表_按报告期.csv", "资产负债表", pd.DataFrame(rows).assign(SHORT_LOAN=20, LONG_LOAN=30, BOND_PAYABLE=0, NONCURRENT_LIAB_1YEAR=10, TOTAL_PARENT_EQUITY=500))
    write("现金流量表_按报告期.csv", "现金流量表", pd.DataFrame(rows).assign(NETCASH_OPERATE=[200, 180, 170, 160, 150], CONSTRUCT_LONG_ASSET=40, ASSIGN_DIVIDEND_PORFIT=500))
    write("主要财务指标_按报告期.csv", "主要财务指标（按报告期）", pd.DataFrame(rows).assign(ROEJQ=20, FCFF_FORWARD=99999, FCFF_BACK=88888))
    write("公司概况.csv", "fetch_sources.tencent_info", pd.DataFrame({"item": ["最新价", "总市值", "总股本", "市盈率(TTM)", "市净率"], "value": [10, 1e9, 1e8, 12, 2]}))
    write("日线股价.csv", "日线行情（不复权）", pd.DataFrame({"date": periods, "close": [12, 11, 10, 9, 8]}))
    write("分红送配记录.csv", "分红送配记录", pd.DataFrame({"报告期": ["2025-06-30", "2025-12-31", "2024-12-31", "2023-12-31", "2026-06-30"], "现金分红-现金分红比例": [1, 2, 3, 2, 100], "总股本": [100, 100, 100, 100, 100], "方案进度": ["实施分配", "实施分配", "实施分配", "实施分配", "董事会预案"], "除权除息日": ["2025-09-01", "2026-06-01", "2025-06-01", "2024-06-01", "2026-12-01"]}))
    (batch / "data" / "拉取清单.json").write_text(json.dumps({"stock": {"symbol": "SH.600039", "code": "600039", "name": "合成测试"}, "started_at": "2026-10-27T12:00:00", "datasets": datasets}, ensure_ascii=False), encoding="utf-8")
    return batch


def mutate_csv(batch, filename, mutate):
    path = batch / "data" / filename
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    mutate(frame)
    frame.to_csv(path, index=False)


def manifest_change(batch, mutate):
    path = batch / "data" / "拉取清单.json"
    obj = json.loads(path.read_text(encoding="utf-8"))
    mutate(obj)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def test_known_units_true_interest_and_per_ten_share_dividends(batch):
    client = ValuationSnapshot(batch)
    engine = ValuationEngine(client.ts_code, str(batch / "reports"), client)
    info = engine._basic_info()
    assert info["close"] == 10
    assert info["mkt_cap_mm"] == 1000
    assert info["total_shares"] == 1e8
    assert engine._annual_df("income").iloc[0]["int_exp"] == 12
    assert engine.compute_wacc()["kd_pre"] == 20
    assert dict(engine._aggregate_annual_dps())["2025"] == pytest.approx(.3)
    assert client._get_payout_by_year()["2025"] == pytest.approx(25)
    assert client._store["cashflow"].iloc[0]["c_pay_dist_dpcp_int_exp"] == 500
    assert "c_pay_dist_dpcp" not in client._store["cashflow"]
    assert "fcff" not in client._store["fina_indicators"]
    assert any("share-count precision" in text for text in client.limitations)


def test_missing_bond_and_true_interest_stay_unknown_not_zero_or_finance_expense(batch):
    mutate_csv(batch, "资产负债表_按报告期.csv", lambda frame: frame.__setitem__("BOND_PAYABLE", ""))
    mutate_csv(batch, "利润表_按报告期.csv", lambda frame: frame.drop(columns=["FE_INTEREST_EXPENSE"], inplace=True))
    client = ValuationSnapshot(batch)
    engine = ValuationEngine(client.ts_code, "unused", client)
    assert pd.isna(client._get_annual_df("balance_sheet").iloc[0]["bond_payable"])
    assert pd.isna(client._get_annual_df("income").iloc[0]["int_exp"])
    assert engine.compute_wacc()["wacc"] is None
    assert "assumption" in engine.compute_wacc()["parameter_sources"]["kd_pre"]


@pytest.mark.parametrize("mutation,code", [
    (lambda f: f.__setitem__("CURRENCY", "USD"), "CURRENCY_MISMATCH"),
    (lambda f: f.__setitem__("SECUCODE", "600887.SH"), "STOCK_MISMATCH"),
    (lambda f: f.__setitem__("UNIT", "万元"), "UNKNOWN_AMOUNT_UNIT"),
    (lambda f: f.__setitem__("REPORT_DATE", "2027-12-31"), "INVALID_PERIOD"),
    (lambda f: f.__setitem__("REPORT_DATE", "2025-12-31T00:00:00+08:00"), "INVALID_PERIOD"),
    (lambda f: f.__setitem__("REPORT_DATE", "2025-12-31"), "DUPLICATE_PERIOD"),
    (lambda f: f.drop(columns=["CURRENCY"], inplace=True), "UNKNOWN_STATEMENT_IDENTITY_OR_UNITS"),
    (lambda f: f.__setitem__("PARENT_NETPROFIT", "inf"), "INVALID_NUMBER"),
])
def test_bad_statement_identity_currency_units_periods_are_rejected(batch, mutation, code):
    mutate_csv(batch, "利润表_按报告期.csv", mutation)
    with pytest.raises(SnapshotError) as error:
        ValuationSnapshot(batch)
    assert error.value.payload["code"] == code


def test_mismatched_annual_period_is_insufficient(batch):
    mutate_csv(batch, "现金流量表_按报告期.csv", lambda frame: frame.drop(index=0, inplace=True))
    with pytest.raises(SnapshotError) as error:
        ValuationSnapshot(batch)
    assert error.value.payload["code"] == "ANNUAL_PERIOD_MISMATCH"
    assert error.value.payload["status"] == "INSUFFICIENT_DATA"


@pytest.mark.parametrize("mutation,code", [
    (lambda obj: obj["stock"].update(symbol="HK.00700", code="00700"), "UNSUPPORTED_MARKET_OR_IDENTITY"),
    (lambda obj: obj["datasets"][0].update(source="unknown"), "UNSUPPORTED_SOURCE"),
    (lambda obj: obj["datasets"][0].update(sha256="wrong"), "HASH_MISMATCH"),
    (lambda obj: obj["datasets"][0].update(status="failed"), "UNVERIFIED_DATASET"),
    (lambda obj: obj["datasets"].append(obj["datasets"][0].copy()), "DUPLICATE_DATASET"),
    (lambda obj: obj["datasets"][0].update(file=[]), "INVALID_MANIFEST"),
    (lambda obj: obj["datasets"][0].update(source={}), "UNSUPPORTED_SOURCE"),
    (lambda obj: obj["datasets"][0].update(status=[]), "UNVERIFIED_DATASET"),
    (lambda obj: obj.update(started_at=1000), "UNKNOWN_SNAPSHOT_DATE"),
    (lambda obj: obj.pop("started_at"), "UNKNOWN_SNAPSHOT_DATE"),
])
def test_unverified_or_unknown_manifest_cannot_supply_units(batch, mutation, code):
    manifest_change(batch, mutation)
    with pytest.raises(SnapshotError) as error:
        ValuationSnapshot(batch)
    assert error.value.payload["code"] == code


def test_chinese_price_schema_supported_without_adjusted_fallback(batch):
    mutate_csv(batch, "日线股价.csv", lambda frame: frame.rename(columns={"date": "日期", "close": "收盘"}, inplace=True))
    mutate_csv(batch, "日线股价.csv", lambda frame: frame.__setitem__("股票代码", "600039"))
    client = ValuationSnapshot(batch)
    assert client._store["weekly_prices"].iloc[0]["close"] == 12
    path = batch / "data" / "日线股价.csv"
    path.rename(batch / "data" / "日线股价_前复权.csv")
    manifest_change(batch, lambda obj: obj.__setitem__("datasets", [row for row in obj["datasets"] if row["file"] != "日线股价.csv"]))
    client = ValuationSnapshot(batch)
    assert client._store["weekly_prices"].empty


def test_cli_offline_never_imports_provider_or_reads_credentials_and_is_idempotent(batch, monkeypatch, capsys):
    real_import = builtins.__import__
    def restricted_import(name, *args, **kwargs):
        if name.split(".")[0] in {"tushare", "tushare_collector", "akshare", "requests", "yfinance"}:
            raise AssertionError("Unexpected provider import: " + name)
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", restricted_import)
    monkeypatch.setattr(valuation_engine, "get_token", lambda: (_ for _ in ()).throw(AssertionError("credential access")))
    before = {p.relative_to(batch).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns) for p in batch.rglob("*") if p.is_file()}
    assert valuation_engine.main(["--dir", str(batch)]) == 0
    output = batch / "reports" / "valuation_computed.md"
    text = output.read_text(encoding="utf-8")
    assert "600039.SH" in text and "当前批次离线快照" in text
    assert "INSUFFICIENT_DATA" in text
    assert "cashflow_basis must explicitly" in text
    assert "数据快照采集时间: 2026-10-27T12:00:00" in text
    os.utime(output, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))
    snap = (output.read_bytes(), output.stat().st_mtime_ns)
    assert valuation_engine.main(["--dir", str(batch)]) == 0
    assert (output.read_bytes(), output.stat().st_mtime_ns) == snap
    for relative, value in before.items():
        path = batch / relative
        assert (path.read_bytes(), path.stat().st_mtime_ns) == value
    status_lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert status_lines[-1]["changed"] is False
    assert not list(batch.rglob("*.tmp"))


def test_cli_incomplete_input_has_machine_status_and_preserves_previous_output(batch, capsys):
    report = batch / "reports" / "valuation_computed.md"
    report.parent.mkdir()
    report.write_text("previous owned output", encoding="utf-8")
    (batch / "data" / "现金流量表_按报告期.csv").unlink()
    assert valuation_engine.main(["--dir", str(batch)]) == 3
    assert json.loads(capsys.readouterr().out)["status"] == "INSUFFICIENT_DATA"
    assert report.read_text(encoding="utf-8") == "previous owned output"


def test_explicit_contract_stays_explicit_and_no_provider_fcff_is_inferred(batch):
    contract = {"cashflow_basis": "FCFE", "currency": "CNY", "amount_unit": "raw", "cashflow_scope": "parent_common", "historical_source": "explicit", "historical_cashflows": [{"period": "20251231", "value": 200, "evidence_id": "fixture.2025"}, {"period": "20241231", "value": 180, "evidence_id": "fixture.2024"}]}
    client = ValuationSnapshot(batch, contract=contract)
    engine = ValuationEngine(client.ts_code, "unused", client)
    result = engine.dcf_stable(engine.compute_wacc())
    assert result is not None
    assert result["cashflow_basis"] == "FCFE"


def test_direct_cli_runs_without_credentials_in_a_fresh_process(batch, tmp_path):
    # Install an import trap in a fresh child; this also exercises the watchdog.
    traps = tmp_path / "trap"
    traps.mkdir()
    (traps / "sitecustomize.py").write_text("import builtins\n_real = builtins.__import__\ndef _guard(name,*a,**kw):\n    if name.split('.')[0] in {'tushare','tushare_collector','akshare','requests','yfinance'}: raise RuntimeError('network/provider import forbidden')\n    return _real(name,*a,**kw)\nbuiltins.__import__ = _guard\n", encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(traps), TUSHARE_TOKEN="", TUSHARE_API_URL="")
    result = subprocess.run([sys.executable, str(Path(valuation_engine.__file__)), "--dir", str(batch), "--total-timeout", "30"], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"mode": "offline_batch"' in result.stdout


def test_json_and_csv_read_limits_are_enforced(batch, monkeypatch):
    import valuation_snapshot
    monkeypatch.setattr(valuation_snapshot, "MAX_JSON_BYTES", 10)
    with pytest.raises(SnapshotError) as error:
        ValuationSnapshot(batch)
    assert error.value.payload["code"] == "READ_LIMIT"


@pytest.mark.parametrize("name,value,expected", [("MAX_CSV_BYTES", 10, "READ_LIMIT"), ("MAX_ROWS", 2, "CSV_SIZE_OR_SCHEMA")])
def test_csv_byte_and_row_bounds(batch, monkeypatch, name, value, expected):
    import valuation_snapshot
    monkeypatch.setattr(valuation_snapshot, name, value)
    with pytest.raises(SnapshotError) as error:
        ValuationSnapshot(batch)
    assert error.value.payload["code"] == expected


@pytest.mark.parametrize("raw,expected", [("[]", "INVALID_JSON_ROOT"), ('{"x":NaN}', "INVALID_JSON"), ('{"x":1e999}', "INVALID_JSON"), ("{broken", "INVALID_JSON"), ('{"x":' + '[' * 40 + '0' + ']' * 40 + '}', "JSON_DEPTH")], ids=["array-root", "nan", "overflow-number", "syntax", "nesting-depth"])
def test_malformed_json_is_structured(batch, raw, expected):
    (batch / "data" / "拉取清单.json").write_text(raw, encoding="utf-8")
    with pytest.raises(SnapshotError) as error:
        ValuationSnapshot(batch)
    assert error.value.payload["code"] == expected


def test_json_parser_recursion_failure_is_structured(batch, monkeypatch):
    import valuation_snapshot
    def recursion(*args, **kwargs):
        raise RecursionError("maximum recursion depth exceeded while decoding JSON")
    monkeypatch.setattr(valuation_snapshot.json, "loads", recursion)
    with pytest.raises(SnapshotError) as error:
        ValuationSnapshot(batch)
    assert error.value.payload["code"] == "INVALID_JSON"


def test_missing_cash_ratio_is_unknown_even_without_exdate(batch):
    path = batch / "data" / "分红送配记录.csv"
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    frame.loc[len(frame)] = ["2020-12-31", "", "100", "实施分配", ""]
    frame.to_csv(path, index=False)
    client = ValuationSnapshot(batch)
    assert "2020" not in client._get_payout_by_year()
    assert any("cash distribution remains unknown" in text for text in client.limitations)


def test_cli_relative_contract_and_canonical_output_scope(batch, capsys):
    contract = {"cashflow_basis": "FCFE", "currency": "CNY", "amount_unit": "raw", "cashflow_scope": "parent_common", "historical_source": "explicit", "historical_cashflows": [{"period": "20251231", "value": 200, "evidence_id": "fixture.2025"}, {"period": "20241231", "value": 180, "evidence_id": "fixture.2024"}]}
    (batch / "contract.json").write_text(json.dumps(contract), encoding="utf-8")
    assert valuation_engine.main(["--dir", str(batch), "--contract", "contract.json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["method_status"]["DCF"]["status"] == "COMPUTED"
    report = batch / "reports" / "valuation_computed.md"
    original = report.read_bytes()
    assert valuation_engine.main(["--dir", str(batch), "--output-dir", str(batch / "other")]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "OUTPUT_SCOPE"
    assert report.read_bytes() == original
    assert not (batch / "other").exists()


def test_legacy_provider_cli_and_no_cache_still_use_original_collection_path(tmp_path, monkeypatch):
    state = {}
    class Client:
        def __init__(self, token):
            state["token"] = token
            self._cache_enabled = True
            self._store = {}
            state["client"] = self
        def assemble_data_pack(self, code):
            state["collected"] = code
    class Engine:
        def __init__(self, code, output_dir, client):
            state["engine_code"] = code
            state["output_dir"] = output_dir
        def run(self):
            return "# provider fixture\n"
    provider = types.ModuleType("tushare_collector")
    provider.TushareClient = Client
    monkeypatch.setitem(sys.modules, "tushare_collector", provider)
    monkeypatch.setattr(valuation_engine, "get_token", lambda: "fixture-token")
    monkeypatch.setattr(valuation_engine, "ValuationEngine", Engine)
    output_dir = tmp_path / "provider"
    assert valuation_engine.main(["--code", "600039.SH", "--output-dir", str(output_dir), "--no-cache"]) == 0
    assert state["token"] == "fixture-token"
    assert state["collected"] == state["engine_code"] == "600039.SH"
    assert state["client"]._cache_enabled is False
    assert (output_dir / "valuation_computed.md").read_text(encoding="utf-8") == "# provider fixture\n"
