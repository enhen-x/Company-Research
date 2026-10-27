"""Bounded fetch and verified reuse with isolated synthetic datasets only."""
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import fetch_with_fallback as adapter
from bounded_fetch import FetchError, job


@pytest.fixture
def synthetic_fetch(tmp_path, monkeypatch):
    clock = SimpleNamespace(elapsed=10.0, epoch=2_000_000_000.0)
    calls = []
    candidate = job("isolated_fixture", "success")
    monkeypatch.setattr(adapter, "time", SimpleNamespace(
        monotonic=lambda: clock.elapsed, time=lambda: clock.epoch))
    monkeypatch.setattr(adapter, "dataset_specs", lambda *args: [
        ("isolated synthetic", "synthetic.csv", [candidate])])

    def fetch(spec, **options):
        calls.append((spec, options))
        return pd.DataFrame({"synthetic_value": [len(calls)]}), [{"status": "PASS"}]

    monkeypatch.setattr(adapter, "fetch_job", fetch)
    return clock, calls, candidate


def _fetch(tmp_path, **options):
    options.setdefault("success_ttl", 60)
    return adapter.fetch_datasets("000001", "SZ", tmp_path, **options)


def _rewrite_manifest(tmp_path, change):
    path = tmp_path / "拉取清单.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    change(manifest)
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def test_verified_success_reuses_original_timestamp_until_ttl_expires(tmp_path, synthetic_fetch):
    clock, calls, _ = synthetic_fetch
    first = _fetch(tmp_path)
    original = (tmp_path / "synthetic.csv").read_bytes()
    clock.epoch += 30
    cached = _fetch(tmp_path)
    item = cached["datasets"][0]
    assert len(calls) == 1
    assert item["status"] == "cached" and item["attempts"] == []
    assert item["reused_from_run_id"] == first["run_id"]
    assert item["fetched_epoch"] == first["datasets"][0]["fetched_epoch"]
    assert (tmp_path / "synthetic.csv").read_bytes() == original
    assert cached["status"] == "PASS"

    # Reuse must not extend the original successful request's lifetime.
    clock.epoch += 30
    expired = _fetch(tmp_path)
    assert len(calls) == 2 and expired["datasets"][0]["status"] == "success"
    assert expired["datasets"][0]["fetched_epoch"] == clock.epoch


@pytest.mark.parametrize("changed", ["hash", "missing_file", "stock", "source", "report_date", "future_stamp", "boolean_stamp", "force"])
def test_reuse_requires_verified_identity_content_and_period(tmp_path, synthetic_fetch, changed):
    _, calls, _ = synthetic_fetch
    _fetch(tmp_path, report_date="2026-06-30")
    options = {"report_date": "2026-06-30"}
    if changed == "hash":
        with (tmp_path / "synthetic.csv").open("ab") as output:
            output.write(b"\n")
    elif changed == "missing_file":
        (tmp_path / "synthetic.csv").unlink()
    elif changed == "stock":
        _rewrite_manifest(tmp_path, lambda data: data["stock"].update(symbol="SH.000001"))
    elif changed == "source":
        _rewrite_manifest(tmp_path, lambda data: data["datasets"][0].update(source="other.source"))
    elif changed == "report_date":
        options["report_date"] = "2026-09-30"
    elif changed in ("future_stamp", "boolean_stamp"):
        stamp = 2_000_000_001.0 if changed == "future_stamp" else True
        _rewrite_manifest(tmp_path, lambda data: data["datasets"][0].update(fetched_epoch=stamp))
    elif changed == "force":
        options["force"] = True
    result = _fetch(tmp_path, **options)
    item = result["datasets"][0]
    assert len(calls) == 2 and item["status"] == "success"
    assert item["sha256"] == hashlib.sha256((tmp_path / "synthetic.csv").read_bytes()).hexdigest()
    assert item["report_date"] == options["report_date"]


def test_zero_success_ttl_disables_reuse(tmp_path, synthetic_fetch):
    _, calls, _ = synthetic_fetch
    _fetch(tmp_path)
    result = adapter.fetch_datasets("000001", "SZ", tmp_path, success_ttl=0)
    assert len(calls) == 2 and result["datasets"][0]["status"] == "success"


def test_one_deadline_bounds_all_candidates_and_datasets(tmp_path, synthetic_fetch, monkeypatch):
    clock, calls, candidate = synthetic_fetch
    alternate = job("isolated_fixture", "alternate")
    monkeypatch.setattr(adapter, "dataset_specs", lambda *args: [
        ("first", "first.csv", [candidate, alternate]),
        ("second", "second.csv", [candidate])])
    (tmp_path / "second.csv").write_text("existing synthetic data", encoding="utf-8")

    def exhaust_budget(spec, **options):
        calls.append((spec, options))
        clock.elapsed = options["deadline"]
        raise FetchError("isolated budget timeout", [{"status": "TIMEOUT"}])

    monkeypatch.setattr(adapter, "fetch_job", exhaust_budget)
    result = _fetch(tmp_path, total_budget=5, timeout=30, retries=3)
    assert len(calls) == 1 and calls[0][1]["deadline"] == 15
    assert calls[0][1]["timeout"] == 30 and calls[0][1]["retries"] == 3
    assert result["status"] == "WARN" and result["total_budget_seconds"] == 5
    assert all(item["budget_exhausted"] for item in result["datasets"])
    assert result["datasets"][0]["attempts"] == [{"status": "TIMEOUT"}]
    assert result["datasets"][1]["attempts"] == []
    assert result["datasets"][1]["old_file_preserved"] is True
    assert (tmp_path / "second.csv").read_text(encoding="utf-8") == "existing synthetic data"


def test_all_attempts_receive_same_remaining_batch_deadline(tmp_path, synthetic_fetch, monkeypatch):
    clock, calls, candidate = synthetic_fetch
    monkeypatch.setattr(adapter, "dataset_specs", lambda *args: [
        ("first", "first.csv", [candidate]), ("second", "second.csv", [candidate])])

    def success(spec, **options):
        calls.append((spec, options))
        clock.elapsed += 1
        return pd.DataFrame({"synthetic_value": [1]}), [{"status": "PASS"}]

    monkeypatch.setattr(adapter, "fetch_job", success)
    result = _fetch(tmp_path, total_budget=5)
    assert result["status"] == "PASS"
    assert len(calls) == 2 and [options["deadline"] for _, options in calls] == [15, 15]


@pytest.mark.parametrize("previous_count", [None, "7", 1.5, True, -3, {}, []])
def test_invalid_retention_counter_and_stock_shape_do_not_crash(tmp_path, synthetic_fetch, previous_count):
    _, calls, _ = synthetic_fetch
    _fetch(tmp_path)
    _rewrite_manifest(tmp_path, lambda data: data.update(
        stock=["invalid stock metadata"], older_runs_not_retained=previous_count))
    result = _fetch(tmp_path)
    assert len(calls) == 2 and result["status"] == "PASS"
    assert result["older_runs_not_retained"] == 0
    assert result["stock"] == {"code": "000001", "symbol": "SZ.000001"}


@pytest.mark.parametrize("raw", ["{broken", "[]", "null", '{"stock":null,"runs":{},"datasets":{}}'])
def test_damaged_manifest_is_replaced_by_completed_run(tmp_path, synthetic_fetch, raw):
    (tmp_path / "拉取清单.json").write_text(raw, encoding="utf-8")
    result = _fetch(tmp_path)
    saved = json.loads((tmp_path / "拉取清单.json").read_text(encoding="utf-8"))
    assert saved == result and saved["status"] == "PASS"
    assert saved["datasets"][0]["status"] == "success"
    assert len(saved["runs"]) <= 20


def test_run_history_stays_bounded_and_counts_discarded_runs(tmp_path, synthetic_fetch):
    for _ in range(24):
        result = _fetch(tmp_path)
    assert len(result["runs"]) == 20
    assert result["older_runs_not_retained"] == 4
    assert len({run["run_id"] for run in result["runs"]}) == 20
    assert result["runs"][-1]["run_id"] == result["run_id"]
    assert all(run["status"] == "PASS" for run in result["runs"])


@pytest.mark.parametrize("option,value", [("total_budget", 0), ("total_budget", -1), ("total_budget", True),
                                         ("total_budget", float("inf")), ("success_ttl", float("nan")),
                                         ("success_ttl", -1), ("success_ttl", "60")])
def test_invalid_budget_or_ttl_rejected_before_fetch(tmp_path, synthetic_fetch, option, value):
    _, calls, _ = synthetic_fetch
    with pytest.raises(ValueError, match=option):
        adapter.fetch_datasets("000001", "SZ", tmp_path, **{option: value})
    assert not calls and not (tmp_path / "拉取清单.json").exists()
