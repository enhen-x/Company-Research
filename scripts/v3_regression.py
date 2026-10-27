#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bounded offline replay for V3 changes across real local stock batches."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

from run_support import atomic_json, now, run_process

SKILL = Path(__file__).resolve().parent.parent
DATA_FILES = (
    "利润表_按报告期.csv", "资产负债表_按报告期.csv", "现金流量表_按报告期.csv",
    "主要财务指标_按报告期.csv", "分红送配记录.csv", "公司概况.csv", "日线股价.csv",
)
INPUT_FILES = ("研究模型.json", "预测基线.json")
VALID_PHASES = {"topics", "valuation", "runtime", "build", "all"}
DEFAULT_STOCKS = ("600039", "600887", "601899")
BUILD_RUNTIME_NAMES = {".browser_qa_profile", "__pycache__", ".pytest_cache", ".cache",
                       ".screener_cache", ".fetch_cache", ".gate.lock", "Thumbs.db", ".DS_Store"}


def _build_runtime_name(name):
    return name in BUILD_RUNTIME_NAMES or name.endswith((".pyc", ".pyo"))


def _batch_hashes(batch):
    """Hash all historical files except transient runtime caches (which may be locked)."""
    hashes = {}
    for folder, dirs, files in os.walk(batch):
        dirs[:] = sorted(name for name in dirs if not _build_runtime_name(name))
        for name in sorted(files):
            if not _build_runtime_name(name):
                path = Path(folder) / name
                hashes[path.relative_to(batch).as_posix()] = _sha(path)
    return hashes


def _copy_build_case(batch, project):
    """Copy a full batch, substituting the current skill's script tree only."""
    def ignore_historical(folder, names):
        return [name for name in names if _build_runtime_name(name)
                or (Path(folder) == batch and name == "scripts")]

    shutil.copytree(batch, project, ignore=ignore_historical)
    shutil.copytree(SKILL / "scripts", project / "scripts",
                    ignore=lambda folder, names: [name for name in names if _build_runtime_name(name)])


def _clear_build_outputs(project, report):
    """Remove only derived build outputs in the owned temporary copy."""
    outputs = [report.with_suffix(".html"), project / "reports" / "流水线执行状态.json",
               project / "reports" / "图表期间覆盖.json", project / "reports" / "图表最新期数据.json"]
    outputs.extend((project / "reports").glob("*_图表.html"))
    outputs.extend(path for path in (project / "reports" / "图表").glob("*.png")
                   if re.fullmatch(r"图\d{2}_.*\.png", path.name))
    removed = []
    for path in sorted(set(outputs)):
        if path.is_file():
            path.unlink()
            removed.append(path.relative_to(project).as_posix())
    return removed


def _run_build_case(batch, code, *, stage_timeout=300, total_timeout=1200):
    """Parent-owned isolation survives a killed gate worker and is always cleaned."""
    for name, value in (("stage-timeout", stage_timeout), ("total-timeout", total_timeout)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name}必须是有限正数")
    if stage_timeout > total_timeout:
        raise ValueError("stage-timeout不能大于total-timeout")
    batch = Path(batch).resolve()
    before = _batch_hashes(batch)
    payload = {"code": code, "company": batch.parent.name, "batch": str(batch), "phase": "build",
               "status": "FAIL", "technical_pass": False, "build_completed": False,
               "research_completed": False, "research_status": "NOT_ASSESSED", "human_review": "NOT_ASSESSED",
               "source_hashes_before": before, "source_hash_scope": "all files except runtime caches",
               "excluded_runtime_names": sorted(BUILD_RUNTIME_NAMES),
               "budgets_seconds": {"stage": stage_timeout, "total": total_timeout}}
    temporary_root = None
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix=f"v3_build_{code}_") as temp_name:
            temporary_root = Path(temp_name)
            project = temporary_root / batch.name
            payload.update(temporary_project=str(project), original_batch_name_preserved=project.name == batch.name)
            _copy_build_case(batch, project)
            reports = sorted((project / "reports").glob("*_分析报告.md"))
            if len(reports) != 1:
                payload.update(status="INCOMPLETE", error="完整构建需要唯一 *_分析报告.md 主报告", report_candidates=[p.name for p in reports])
            else:
                report = reports[0]
                protected = {name: digest for name, digest in before.items()
                             if name.startswith(("data/", "input/")) or name == report.relative_to(project).as_posix()}
                payload["temporary_source_hashes_before"] = {name: _sha(project / name) for name in protected}
                if protected != payload["temporary_source_hashes_before"]:
                    raise ValueError("临时副本的原始数据/输入/主报告与历史源哈希不一致")
                payload["removed_stale_outputs"] = _clear_build_outputs(project, report)
                payload["synchronized_script_hashes"] = {name: digest for name, digest in _batch_hashes(project / "scripts").items()}
                command = [sys.executable, "-B", "-X", "utf8", "-u", str(project / "scripts" / "gate_all.py"),
                           "--dir", str(project), "--report", str(report.relative_to(project)),
                           "--stage-timeout", str(stage_timeout), "--total-timeout", str(total_timeout), "--heartbeat", "10"]
                outcome = run_process(command, cwd=project, timeout=total_timeout,
                                      heartbeat=min(10, total_timeout), label=f"{code} full build", echo=False)
                payload["execution"] = {key: value for key, value in outcome.items() if key != "output"}
                ledger_path = project / "reports" / "流水线执行状态.json"
                try:
                    ledger = json.loads(ledger_path.read_text(encoding="utf-8-sig"))
                    if not isinstance(ledger, dict):
                        raise ValueError("执行账本必须为对象")
                except (OSError, ValueError) as exc:
                    ledger = {}
                    payload["ledger_error"] = str(exc)
                payload["gate_ledger"] = {key: ledger[key] for key in (
                    "run_id", "status", "technical_pass", "build_completed", "fully_rebuilt", "delivery_ready", "mode",
                    "legacy", "research_quality", "human_research_review", "research_checks", "stages", "elapsed_seconds", "error") if key in ledger}
                stages = ledger.get("stages", [])
                stages_complete = (isinstance(stages, list) and bool(stages)
                                   and all(isinstance(s, dict) and s.get("status") in ("PASS", "SKIP") for s in stages))
                passed = (outcome.get("status") == "PASS" and outcome.get("exit_code") == 0
                          and ledger.get("status") == "PASS" and ledger.get("mode") == "BUILD"
                          and ledger.get("legacy") is False
                          and all(ledger.get(key) is True for key in ("technical_pass", "build_completed", "fully_rebuilt", "delivery_ready"))
                          and stages_complete)
                payload.update(status="PASS" if passed else "TIMEOUT" if outcome.get("status") == "TIMEOUT" else "FAIL",
                               technical_pass=passed, build_completed=passed)
                if not passed:
                    payload["failure_tail"] = outcome.get("output", "")[-8000:]
                    payload["error"] = ledger.get("error") or payload.get("ledger_error") or "完整构建进程或阶段未全部通过"
                payload["stage_failures"] = [{"name": s.get("name"), "status": s.get("status"),
                                                "error": s.get("error") or s.get("reason")}
                                               for s in ledger.get("stages", []) if isinstance(s, dict) and s.get("status") in ("FAIL", "TIMEOUT", "BLOCKED")]
                fixed = sorted(path for path in (project / "reports" / "图表").glob("*.png")
                               if re.fullmatch(r"图\d{2}_.*\.png", path.name))
                health = sorted((project / "reports" / "图表").glob("体检_*.png"))
                htmls = [report.with_suffix(".html"), *sorted((project / "reports").glob("*_图表.html"))]
                payload["artifacts"] = {"fixed_png_count": len(fixed), "health_png_count": len(health),
                                        "fixed_pngs": [p.name for p in fixed],
                                        "main_html_present": report.with_suffix(".html").is_file(),
                                        "interactive_html_present": bool(list((project / "reports").glob("*_图表.html"))),
                                        "sha256": {p.relative_to(project).as_posix(): _sha(p) for p in [*fixed, *health, *htmls] if p.is_file()}}
                artifacts_ready = (payload["artifacts"]["fixed_png_count"] > 0
                                   and payload["artifacts"]["main_html_present"]
                                   and payload["artifacts"]["interactive_html_present"])
                if passed and not artifacts_ready:
                    payload.update(status="FAIL", technical_pass=False, build_completed=False,
                                   error="完整构建账本通过，但固定图表或HTML产物缺失")
                payload["temporary_source_hashes_after"] = {name: _sha(project / name) if (project / name).is_file() else None for name in protected}
                payload["temporary_source_unchanged"] = protected == payload["temporary_source_hashes_after"]
                model = project / "input" / "研究模型.json"
                research = project / "reports" / "研究模型_输出.json"
                payload["research_status"] = "INCOMPLETE" if not model.is_file() else "NOT_ASSESSED"
                if model.is_file() and research.is_file():
                    try:
                        result = json.loads(research.read_text(encoding="utf-8-sig"))
                        payload["research_status"] = result.get("status", "NOT_ASSESSED") if isinstance(result, dict) else "INVALID"
                    except (OSError, ValueError):
                        payload["research_status"] = "INVALID"
                if not payload["temporary_source_unchanged"]:
                    payload.update(status="FAIL", technical_pass=False, build_completed=False,
                                   error="构建修改了临时副本的原始数据/输入/主报告，不能认定同输入回放通过")
    except Exception as exc:
        payload.update(status="FAIL", technical_pass=False, build_completed=False, error=f"{type(exc).__name__}: {exc}")
    finally:
        after = _batch_hashes(batch)
        payload.update(source_hashes_after=after, source_unchanged=before == after,
                       changed_source_files=sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name)),
                       temporary_root=str(temporary_root) if temporary_root else None,
                       temporary_directory_removed=temporary_root is None or not temporary_root.exists(),
                       elapsed_seconds=round(time.monotonic() - started, 3))
        if not payload["source_unchanged"] or not payload["temporary_directory_removed"]:
            payload.update(status="FAIL", technical_pass=False, build_completed=False,
                           error="历史源文件变化或临时目录未清理；完整构建回放未通过")
    return payload


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _company_dirs(root: Path):
    for path in root.iterdir() if root.is_dir() else ():
        match = re.match(r"(?:SH|SZ|BJ)\.(\d{6})(?:\s|$)", path.name)
        if path.is_dir() and match:
            yield match.group(1), path


def discover_batches(root, stocks=DEFAULT_STOCKS):
    """Choose each requested stock's newest dated batch that contains data."""
    root = Path(root)
    found = {}
    for code, company_dir in _company_dirs(root):
        if code not in stocks:
            continue
        candidates = []
        for batch in company_dir.iterdir():
            if not batch.is_dir() or not re.match(r"^\d{4}_\d{2}_\d{2}$", batch.name):
                continue
            data = batch / "data"
            if data.is_dir() and any(p.is_file() for p in data.iterdir()):
                candidates.append(batch)
        if candidates:
            newest = max(candidates, key=lambda p: p.name)
            if code not in found or newest.name > found[code].name:
                found[code] = newest
    return found


def _selected_files(batch: Path):
    result = []
    for name in DATA_FILES:
        path = batch / "data" / name
        if path.is_file():
            result.append((path, Path("data") / name))
    for name in INPUT_FILES:
        path = batch / "input" / name
        if path.is_file():
            result.append((path, Path("input") / name))
    return result


def _copy_case(batch: Path, temp: Path):
    hashes = {}
    for source, relative in _selected_files(batch):
        destination = temp / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        hashes[str(relative).replace("\\", "/")] = _sha(source)
    return hashes


def _tree_files(path: Path):
    return sorted(p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file())


def _run_step(command, cwd, deadline, label):
    remaining = deadline - time.monotonic()
    if remaining <= 0.05:
        return {"status": "TIMEOUT", "elapsed_seconds": 0, "output": "case budget exhausted"}
    return run_process(command, cwd=cwd, timeout=remaining, heartbeat=min(10, max(1, remaining / 3)),
                       label=label, echo=False)


def _valuation_audit(project: Path):
    """Independent CSV-to-JSON checks; missing debt components must stay null."""
    import math
    import pandas as pd

    out_path = project / "input" / "穿透回报率_输入.json"
    def reject_constant(value):
        raise ValueError(f"JSON含非有限数：{value}")

    cfg = json.loads(out_path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    period = pd.Timestamp(cfg["financial_period"])

    def frame(name):
        return pd.read_csv(project / "data" / name, encoding="utf-8-sig")

    def row_at(name, date):
        df = frame(name)
        if "REPORT_DATE" not in df.columns:
            raise ValueError(f"{name} 缺少 REPORT_DATE")
        dates = pd.to_datetime(df["REPORT_DATE"], errors="coerce")
        rows = df.loc[dates.eq(date)]
        return None if rows.empty else rows.iloc[-1]

    checks = {}
    expected_fields = (
        ("利润表_按报告期.csv", "PARENT_NETPROFIT", "net_profit_C"),
        ("利润表_按报告期.csv", "OPERATE_INCOME", "base_revenue"),
        ("资产负债表_按报告期.csv", "MONETARYFUNDS", "cash_balance"),
        ("资产负债表_按报告期.csv", "TOTAL_ASSETS", "total_assets"),
    )
    for filename, column, key in expected_fields:
        row = row_at(filename, period)
        if row is None or column not in row.index or pd.isna(pd.to_numeric(row[column], errors="coerce")):
            raise ValueError(f"原始CSV无法独立核对 {filename}:{column}")
        expected = float(row[column]) / 1e6
        actual = cfg.get(key)
        if actual is None or not math.isclose(float(actual), expected, rel_tol=1e-9, abs_tol=1e-8):
            raise ValueError(f"{key} 与源CSV不符：actual={actual!r}, expected={expected!r}")
        checks[key] = {"actual": actual, "expected": expected, "unit": "百万元"}

    cf = row_at("现金流量表_按报告期.csv", period)
    if cf is None:
        raise ValueError("现金流量表没有与估值期对应的原始行")
    ocf, capex = (pd.to_numeric(cf.get(name), errors="coerce") for name in ("NETCASH_OPERATE", "CONSTRUCT_LONG_ASSET"))
    if pd.isna(ocf) or pd.isna(capex):
        raise ValueError("FCF源数据不全，不能用0代替")
    expected_fcf = (float(ocf) - float(capex)) / 1e6
    if cfg.get("fcf") is None or not math.isclose(float(cfg["fcf"]), expected_fcf, rel_tol=1e-9, abs_tol=1e-8):
        raise ValueError(f"fcf 与源CSV不符：actual={cfg.get('fcf')!r}, expected={expected_fcf!r}")
    checks["fcf"] = {"actual": cfg["fcf"], "expected": expected_fcf, "unit": "百万元"}

    bs = row_at("资产负债表_按报告期.csv", period)
    goodwill = pd.to_numeric(bs.get("GOODWILL"), errors="coerce")
    if pd.isna(goodwill) and cfg.get("goodwill") is not None:
        raise ValueError("商誉源数据缺失却未保留null")
    debt_cols = ("SHORT_LOAN", "LONG_LOAN", "BOND_PAYABLE", "SHORT_BOND_PAYABLE")
    debt_values = [pd.to_numeric(bs.get(name), errors="coerce") for name in debt_cols]
    debt_complete = all(pd.notna(v) for v in debt_values)
    if debt_complete:
        expected_debt = sum(float(v) for v in debt_values) / 1e6
        if cfg.get("interest_bearing_debt") is None or not math.isclose(float(cfg["interest_bearing_debt"]), expected_debt, rel_tol=1e-9, abs_tol=1e-8):
            raise ValueError("有息负债未按四项完整源数据核算")
    elif cfg.get("interest_bearing_debt") is not None:
        raise ValueError("有息负债有缺项却未保留null")
    checks["interest_bearing_debt"] = {"complete_components": debt_complete,
                                       "actual": cfg.get("interest_bearing_debt"), "unit": "百万元"}
    if cfg.get("low_10y_close") is not None or cfg.get("cash_protection") is not None:
        raise ValueError("未验证的低价/现金保护值必须为null")
    return {"status": "PASS", "checks": checks}


def _template_check():
    """Protect the fixed report frame while new research stays inside its sections."""
    text = (SKILL / "references" / "report-template.md").read_text(encoding="utf-8")
    marker = chr(96) * 3
    template = text.split(marker + "markdown", 1)[1].split(marker, 1)[0]
    chapters = re.findall(r"^## (\d+)\. (.+)$", template, flags=re.M)
    expected = ["投资摘要", "宏观与行业分析", "公司分析", "财务分析", "盈利预测", "估值分析",
                "投资建议与目标价", "催化剂与跟踪", "风险与反证条件", "附录"]
    if chapters != [(str(i), title) for i, title in enumerate(expected, 1)]:
        raise ValueError("固定十章报告结构不一致")
    required = ["### §4.1 盈利与资产负债表", "### §4.2 现金流与盈利质量",
                "### §4.3 本期财报体检", "### §4.4 同行业比较"]
    if any(title not in template for title in required):
        raise ValueError("固定财务分析小节缺失")
    return {"status": "PASS", "chapters": len(chapters),
            "heading_count": len(re.findall(r"^#{1,6} ", template, flags=re.M))}


def _confirmed_depreciation_gap(data: Path):
    """A known source-data gap may be an expected stop, never an invented zero."""
    import math
    import pandas as pd

    frame = pd.read_csv(data / "现金流量表_按报告期.csv", encoding="utf-8-sig")
    dates = pd.to_datetime(frame["REPORT_DATE"], errors="coerce")
    frame = frame.loc[dates.dt.month.eq(12)].assign(_date=dates).sort_values("_date").tail(5)

    def usable(value):
        number = pd.to_numeric(value, errors="coerce")
        return pd.notna(number) and math.isfinite(float(number))

    gaps = []
    for _, row in frame.iterrows():
        if any(usable(row.get(name)) for name in ("DEPR_AMORT", "TOTAL_DEPR_AMORT")):
            continue
        needed = ["FA_IR_DEPR", "IA_AMORTIZE", "LPE_AMORTIZE"]
        if "USERIGHT_ASSET_AMORTIZE" in frame.columns:
            needed.append("USERIGHT_ASSET_AMORTIZE")
        missing = [name for name in needed if not usable(row.get(name))]
        if missing:
            gaps.append({"period": str(row["_date"].date()), "missing_fields": missing})
    return gaps


def _cache_reuse_check(project: Path, code: str):
    """Reuse real CSV bytes with explicitly synthetic TTL metadata, without networking."""
    import fetch_with_fallback as fetcher
    from fetch_sources import dataset_specs

    profile = project / "data" / "公司概况.csv"
    if not profile.is_file():
        return {"status": "SKIP", "reason": "无公司概况CSV，不能测试缓存复用"}
    market = "SH" if code.startswith(("6", "9")) else "BJ" if code.startswith(("4", "8", "92")) else "SZ"
    _, filename, candidates = dataset_specs(code, market, {"profile"})[0]
    manifest = project / "data" / "拉取清单.json"
    atomic_json(manifest, {"stock": {"symbol": market + "." + code}, "datasets": [{
        "file": filename, "status": "success", "source": candidates[0]["module"] + "." + candidates[0]["function"],
        "fetched_epoch": time.time(), "sha256": _sha(profile), "report_date": None}],
        "fixture_note": "TTL metadata is synthetic; CSV bytes are an unchanged real local sample"})
    original = fetcher.fetch_job
    calls = []

    def forbidden_network(*args, **kwargs):
        calls.append(True)
        raise AssertionError("离线缓存测试不得调用网络")

    fetcher.fetch_job = forbidden_network
    file_sets = []
    try:
        for _ in range(2):
            result = fetcher.fetch_datasets(code, market, profile.parent, items={"profile"},
                                            success_ttl=60, total_budget=5)
            if any(item.get("status") != "cached" for item in result["datasets"]):
                raise ValueError("TTL缓存未命中")
            file_sets.append(set(_tree_files(project)))
    finally:
        fetcher.fetch_job = original
    if calls or file_sets[0] != file_sets[1]:
        raise ValueError("缓存重复运行触发网络或增加文件")
    return {"status": "PASS", "network_calls": 0, "cycles": 2, "same_file_set": True,
            "fixture_note": "仅TTL元数据为测试夹具；不表示当期联网结果"}


def _worker(project: Path, code: str, company: str, phase: str, timeout: float):
    scripts = SKILL / "scripts"
    python = sys.executable
    deadline = time.monotonic() + timeout
    steps, failures = [], []

    def step(name, script, args=(), allow_codes=()):
        result = _run_step([python, "-B", "-X", "utf8", "-u", str(scripts / script), *map(str, args)],
                           project, deadline, f"{code} {name}")
        result["output"] = result.get("output", "")[-4000:]
        result["accepted_exit"] = result.get("exit_code") in (0, *allow_codes)
        if (script == "build_penetration_input.py" and result.get("exit_code") == 1
                and "ValueError: 折旧摊销核心字段缺失" in result.get("output", "")):
            gaps = _confirmed_depreciation_gap(project / "data")
            if gaps:
                result["expected_outcome"] = "INPUT_INCOMPLETE"
                result["confirmed_source_gaps"] = gaps
                result["accepted_exit"] = True
        steps.append({"name": name, **result})
        if result.get("status") == "TIMEOUT" or not result["accepted_exit"]:
            failures.append(name)
        return result

    data = project / "data"
    input_dir = project / "input"
    required_builder = ("利润表_按报告期.csv", "资产负债表_按报告期.csv", "现金流量表_按报告期.csv",
                       "分红送配记录.csv", "日线股价.csv")
    has_builder_data = all((data / name).is_file() for name in required_builder)
    report = {"code": code, "company": company, "steps": steps, "research_completed": False}

    if phase == "topics":
        try:
            report["report_structure"] = _template_check()
        except Exception as exc:
            failures.append("report_structure")
            report["report_structure"] = {"status": "FAIL", "error": str(exc)}
        if has_builder_data:
            built = step("build_for_topics_audit", "build_penetration_input.py", [
                "--data", data, "--out", input_dir, "--company", company, "--code", code, "--overwrite"])
            if built.get("status") == "PASS":
                try:
                    report["financial_unit_audit"] = _valuation_audit(project)
                except Exception as exc:
                    failures.append("financial_unit_audit")
                    report["financial_unit_audit"] = {"status": "FAIL", "error": str(exc)}
            elif built.get("expected_outcome") == "INPUT_INCOMPLETE":
                report["status"] = "INCOMPLETE"
                report["financial_unit_audit"] = {"status": "INCOMPLETE", "reason": "已确认折旧摊销源缺口，建模安全停止"}
        else:
            report["status"] = "INCOMPLETE"
            report["financial_unit_audit"] = {"status": "SKIP", "reason": "原始CSV不全"}

    if phase == "topics":
        topic = step("research_topics", "research_topics.py", ["--dir", project], allow_codes=(2,))
        output = project / "reports" / "研究模型_输出.json"
        if output.is_file():
            result = json.loads(output.read_text(encoding="utf-8"))
            report["research_status"] = result.get("status")
            report["human_review"] = "NOT_ASSESSED"
            if result.get("status") == "INVALID":
                failures.append("research_topics_invalid")
            if not (input_dir / "研究模型.json").exists() and result.get("status") != "INCOMPLETE":
                failures.append("missing_model_not_incomplete")
        else:
            failures.append("research_topics_output_missing")

    if phase == "valuation":
        if not has_builder_data:
            report["valuation_status"] = "SKIP"
            report["skip_reason"] = "建模所需原始CSV不全"
            report["status"] = "INCOMPLETE"
        else:
            result = step("build_penetration_input", "build_penetration_input.py", [
                "--data", data, "--out", input_dir, "--company", company, "--code", code, "--overwrite"])
            if result.get("status") == "PASS" and result.get("exit_code") == 0:
                try:
                    report["valuation_audit"] = _valuation_audit(project)
                    report["valuation_status"] = "PASS"
                except Exception as exc:
                    report["valuation_status"] = "FAIL"
                    report["valuation_error"] = str(exc)
                    failures.append("valuation_audit")
            else:
                report["valuation_status"] = "INCOMPLETE" if result.get("expected_outcome") == "INPUT_INCOMPLETE" else result.get("status", "FAIL")
                if report["valuation_status"] == "INCOMPLETE":
                    report["status"] = "INCOMPLETE"

    if phase == "runtime":
        if not has_builder_data:
            report["status"] = "INCOMPLETE"
        try:
            report["cache_reuse"] = _cache_reuse_check(project, code)
            if report["cache_reuse"]["status"] != "PASS":
                report["status"] = "INCOMPLETE"
        except Exception as exc:
            failures.append("cache_reuse")
            report["cache_reuse"] = {"status": "FAIL", "error": str(exc)}
        # Two offline cycles; only growth between completed cycles is a regression.
        cycle_file_sets = []
        for cycle in (1, 2):
            if has_builder_data:
                built = step(f"builder_cycle_{cycle}", "build_penetration_input.py", [
                    "--data", data, "--out", input_dir, "--company", company, "--code", code, "--overwrite"])
                if built.get("expected_outcome") == "INPUT_INCOMPLETE":
                    report["status"] = "INCOMPLETE"
            step(f"topics_cycle_{cycle}", "research_topics.py", ["--dir", project], allow_codes=(2,))
            step(f"verification_cycle_{cycle}", "verification.py", ["--dir", project, "--code", code, "--offline"], allow_codes=(2,))
            cycle_file_sets.append(set(_tree_files(project)))
        added = sorted(cycle_file_sets[1] - cycle_file_sets[0])
        report["runtime_files_after_cycle_1"] = sorted(cycle_file_sets[0])
        report["runtime_files_after_cycle_2"] = sorted(cycle_file_sets[1])
        report["runtime_added_files"] = added
        report["runtime_status"] = "PASS" if not added else "FAIL"
        if added:
            failures.append("runtime_file_growth")
        audit_path = project / "data" / "验证快照.json"
        if audit_path.exists():
            report["verification_status"] = json.loads(audit_path.read_text(encoding="utf-8")).get("status")
            if report["verification_status"] != "OK":
                report["status"] = "INCOMPLETE"
        topic_path = project / "reports" / "研究模型_输出.json"
        if topic_path.is_file():
            result = json.loads(topic_path.read_text(encoding="utf-8"))
            report["research_status"] = result.get("status")
            report["human_review"] = "NOT_ASSESSED"
            if result.get("status") == "INVALID":
                failures.append("research_topics_invalid")
        else:
            failures.append("research_topics_output_missing")

    report["status"] = "FAIL" if failures else report.get("status", "PASS")
    report["failures"] = failures
    return report


def _run_case(batch: Path, code: str, phase: str, timeout: float):
    company = batch.parent.name
    source_hashes = {str(src.relative_to(batch)).replace("\\", "/"): _sha(src)
                     for src, _ in _selected_files(batch)}
    with tempfile.TemporaryDirectory(prefix=f"v3_{code}_") as temp_name:
        temp = Path(temp_name)
        copied_hashes = _copy_case(batch, temp)
        if not copied_hashes:
            return {"code": code, "company": company, "batch": str(batch), "status": "SKIP",
                    "reason": "无可复放的data/input文件", "source_hashes_before": source_hashes,
                    "source_hashes_after": source_hashes}
        command = [sys.executable, "-B", "-X", "utf8", "-u", str(Path(__file__).resolve()),
                   "--worker", "--project", str(temp), "--code", code, "--company", company,
                   "--phase", phase, "--worker-timeout", str(max(1, timeout - 2))]
        outcome = run_process(command, cwd=temp, timeout=timeout, heartbeat=min(10, max(1, timeout / 4)),
                              label=f"{code} {phase} worker", echo=False)
        payload_path = temp / "worker-result.json"
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {"status": outcome.get("status", "FAIL"), "error": "worker结果缺失或损坏"}
        after_hashes = {str(src.relative_to(batch)).replace("\\", "/"): _sha(src)
                        for src, _ in _selected_files(batch)}
        payload.update({"batch": str(batch), "worker_elapsed_seconds": outcome.get("elapsed_seconds"),
                        "source_hashes_before": source_hashes, "source_hashes_after": after_hashes,
                        "source_unchanged": source_hashes == after_hashes,
                        "temporary_copy_hashes": copied_hashes})
        if outcome.get("status") != "PASS":
            payload["status"] = outcome.get("status")
            payload["worker_tail"] = outcome.get("output", "")[-4000:]
        if not payload["source_unchanged"]:
            payload["status"] = "FAIL"
            payload["error"] = "回放期间历史源文件发生变化"
        return payload


def _phase_status(cases):
    statuses = [case.get("status", "FAIL") for case in cases]
    if "FAIL" in statuses or "TIMEOUT" in statuses:
        return "FAIL"
    if not statuses or "SKIP" in statuses or "INCOMPLETE" in statuses or "NETWORK_UNAVAILABLE" in statuses:
        return "INCOMPLETE"
    return "PASS"


def _online_case(code, timeout=23):
    """Optional bounded smoke; a network outage is distinct from a local script error."""
    with tempfile.TemporaryDirectory(prefix=f"v3_net_{code}_") as temp_name:
        temp = Path(temp_name)
        result = run_process([sys.executable, "-B", "-X", "utf8", "-u",
                              str(SKILL / "scripts" / "fetch_with_fallback.py"), code,
                              "--out", str(temp), "--items", "profile", "--timeout", "5",
                              "--retries", "1", "--fetch-budget", "15", "--success-ttl", "0"],
                             cwd=temp, timeout=timeout, heartbeat=5, label=f"{code} online profile", echo=False)
        path = temp / "拉取清单.json"
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"code": code, "status": result["status"] if result["status"] == "TIMEOUT" else "FAIL",
                    "elapsed_seconds": result["elapsed_seconds"], "tail": result.get("output", "")[-3000:],
                    "reason": "拉取清单缺失，不能归类为网络不可用"}
        items = manifest.get("datasets", [])
        okay = bool(items) and all(item.get("status") == "success" for item in items)
        status = "PASS" if okay and result.get("exit_code") == 0 else "NETWORK_UNAVAILABLE" if items else "FAIL"
        return {"code": code, "status": status, "elapsed_seconds": result["elapsed_seconds"],
                "datasets": items, "file_count": len(_tree_files(temp)),
                "tail": result.get("output", "")[-3000:]}


def run_suite(root, stocks=DEFAULT_STOCKS, phase="all", output=None, *, case_timeout=300,
              build_stage_timeout=300, build_total_timeout=1200, online_smoke=False):
    root = Path(root).resolve()
    stocks = tuple(dict.fromkeys(str(s).strip() for s in stocks if str(s).strip()))
    if not stocks or any(not re.fullmatch(r"\d{6}", s) for s in stocks):
        raise ValueError("stocks必须是一个或多个六位代码")
    if phase not in VALID_PHASES:
        raise ValueError("phase只能是topics/valuation/runtime/build/all")
    if not 10 <= case_timeout <= 1800:
        raise ValueError("case-timeout须在10到1800秒之间")
    for name, value in (("build-stage-timeout", build_stage_timeout), ("build-total-timeout", build_total_timeout)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name}必须是有限正数")
    if build_stage_timeout > build_total_timeout:
        raise ValueError("build-stage-timeout不能大于build-total-timeout")
    if build_total_timeout > 3600:
        raise ValueError("build-total-timeout不能大于3600秒")
    batches = discover_batches(root, stocks)
    phases = ("topics", "valuation", "runtime") if phase == "all" else (phase,)
    invocation = {"started_at": now(), "requested_phases": list(phases), "stocks": list(stocks), "status": "RUNNING"}
    output_path = Path(output).resolve() if output else root / "v3_regression_summary.json"
    try:
        existing = json.loads(output_path.read_text(encoding="utf-8"))
        same_root = existing.get("root") == str(root)
        same_stocks = existing.get("stocks") == list(stocks)
        if not same_root or (not same_stocks and phase != "build"):
            existing = {}
    except (OSError, ValueError, AttributeError):
        existing = {}
    summary = existing or {"schema_version": 1, "root": str(root), "stocks": list(stocks), "phases": {}}
    summary["phases"] = summary.get("phases", {})
    script_hashes = {p.name: _sha(p) for p in sorted((SKILL / "scripts").glob("*.py"))}
    for current_phase in phases:
        phase_started = time.monotonic()
        phase_started_at = now()
        cases = []
        for code in stocks:
            batch = batches.get(code)
            if batch is None:
                cases.append({"code": code, "status": "SKIP", "reason": "没有包含data的日期批次"})
                continue
            try:
                if current_phase == "build":
                    case = _run_build_case(batch, code, stage_timeout=build_stage_timeout,
                                           total_timeout=build_total_timeout)
                else:
                    case = _run_case(batch, code, current_phase, case_timeout)
            except Exception as exc:
                case = {"code": code, "batch": str(batch), "status": "FAIL", "error": str(exc)}
            cases.append(case)
        retained_case_codes = []
        if current_phase == "build":
            # A selected-stock build rerun updates those stocks, retaining other completed evidence.
            prior = summary["phases"].get("build", {}).get("cases", [])
            retained = [c for c in prior if isinstance(c, dict) and c.get("code") not in stocks]
            retained_case_codes = [c.get("code") for c in retained]
            cases = [*retained, *cases]
        status = _phase_status(cases)
        phase_stocks = list(dict.fromkeys(c.get("code") for c in cases if c.get("code"))) if current_phase == "build" else list(stocks)
        phase_record = {"started_at": phase_started_at, "finished_at": now(), "status": status, "coverage": sum(c.get("status") not in ("SKIP",) for c in cases),
                        "requested": len(phase_stocks), "elapsed_seconds": round(time.monotonic() - phase_started, 3),
                        "stocks": phase_stocks, "script_hashes": script_hashes, "cases": cases}
        if current_phase == "build":
            phase_record.update(invocation_stocks=list(stocks), retained_case_codes=retained_case_codes)
        # A phase rerun replaces just its own record; other phase records are retained.
        summary["phases"][current_phase] = phase_record
        invocation["status"] = status
        invocation["finished_phase"] = current_phase
        invocation["finished_at"] = now()
        summary["last_invocation"] = dict(invocation)
        atomic_json(output_path, summary)
    if online_smoke:
        cases = [_online_case(code) for code in stocks]
        summary["online_smoke"] = {"status": _phase_status(cases), "cases": cases, "finished_at": now()}
    invocation["status"] = _phase_status([summary["phases"][p] for p in phases])
    invocation["finished_at"] = now()
    summary["last_invocation"] = dict(invocation)
    atomic_json(output_path, summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--phase", choices=sorted(VALID_PHASES), default="all")
    parser.add_argument("--output")
    parser.add_argument("--stocks", default=",".join(DEFAULT_STOCKS))
    parser.add_argument("--case-timeout", type=float, default=300)
    parser.add_argument("--build-stage-timeout", type=float, default=300)
    parser.add_argument("--build-total-timeout", type=float, default=1200)
    parser.add_argument("--online-smoke", action="store_true", help="可选三股profile联网冒烟，每股15秒网络预算")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--project")
    parser.add_argument("--code")
    parser.add_argument("--company")
    parser.add_argument("--worker-timeout", type=float, default=240)
    args = parser.parse_args(argv)
    if args.worker:
        if args.phase == "build":
            parser.error("build由父进程运行；worker模式不支持build")
        result = _worker(Path(args.project), args.code, args.company, args.phase, args.worker_timeout)
        atomic_json(Path(args.project) / "worker-result.json", result)
        return 0 if result.get("status") in ("PASS", "INCOMPLETE") else 1
    try:
        result = run_suite(Path(args.root), tuple(args.stocks.split(",")), args.phase,
                           args.output, case_timeout=args.case_timeout,
                           build_stage_timeout=args.build_stage_timeout,
                           build_total_timeout=args.build_total_timeout,
                           online_smoke=args.online_smoke)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps({"status": result["phases"][args.phase]["status"] if args.phase != "all" else result["last_invocation"]["status"],
                      "output": str(Path(args.output).resolve() if args.output else Path(args.root).resolve() / "v3_regression_summary.json")},
                     ensure_ascii=False))
    return 0 if result["last_invocation"]["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
