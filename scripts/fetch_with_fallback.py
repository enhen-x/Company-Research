"""Unified bounded data fetch entry point, also called directly by research_pipeline.
Each candidate attempt is retained. Existing CSVs survive failure and are marked stale.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import time
import uuid
from pathlib import Path

from bounded_fetch import FetchError, fetch_job
from fetch_sources import dataset_specs
from run_support import atomic_json, now


def fetch_datasets(code, market, out_dir, *, items=None, timeout=30, retries=2,
                   failure_ttl=900, force=False, report_date=None, total_budget=180, success_ttl=0):
    for name, value in (("total_budget", total_budget), ("success_ttl", success_ttl)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} 必须为有限非负数")
    if total_budget == 0:
        raise ValueError("total_budget 必须大于0")
    deadline = time.monotonic() + total_budget
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "拉取清单.json"
    try:
        previous = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        previous = {}
    if not isinstance(previous, dict):
        previous = {}
    previous_stock = previous.get("stock", {})
    if not isinstance(previous_stock, dict):
        previous_stock = {}
    older_runs = previous.get("older_runs_not_retained", 0)
    if type(older_runs) is not int or older_runs < 0:
        older_runs = 0
    runs = previous.get("runs", []) if isinstance(previous, dict) else []
    if not isinstance(runs, list):
        runs = []
    if not runs and previous:
        runs = [{"run_id": "legacy", "manifest": previous}]
    results = []
    run = {"run_id": str(uuid.uuid4()), "started_at": now(), "status": "RUNNING", "datasets": results}
    runs.append(run)
    trimmed = max(0, len(runs)-20)
    runs = runs[-20:]
    try:
        version = importlib.metadata.version("akshare")
    except importlib.metadata.PackageNotFoundError:
        version = "missing"
    manifest = {"stock": {"code": code, "symbol": market+"."+code}, "akshare_version": version,
                "run_id": run["run_id"], "started_at": run["started_at"], "datasets": results, "runs": runs,
                "older_runs_not_retained": older_runs+trimmed,
                "total_budget_seconds": total_budget}
    atomic_json(target, manifest)
    for name, filename, candidates in dataset_specs(code, market, items or {"daily","sheets","indicators","dividends","profile"}, report_date):
        output = out_dir / filename
        result = {"name": name, "file": filename, "status": "failed", "attempts": [],
                  "old_file_preserved": output.exists()}
        previous_items = previous.get("datasets", []) if isinstance(previous.get("datasets", []), list) else []
        cached = next((x for x in previous_items if isinstance(x, dict) and x.get("file") == filename), {})
        identity_matches = previous_stock.get("symbol") == market+"."+code
        source_matches = any(cached.get("source") == c["module"]+"."+c["function"] for c in candidates)
        stamp = cached.get("fetched_epoch", 0)
        fresh = (not isinstance(stamp, bool) and isinstance(stamp, (int, float))
                 and math.isfinite(stamp) and 0 <= time.time()-stamp < success_ttl)
        if (not force and success_ttl and identity_matches and source_matches and fresh and output.exists()
                and cached.get("status") in ("success", "cached")
                and hashlib.sha256(output.read_bytes()).hexdigest() == cached.get("sha256")
                and cached.get("report_date") == report_date):
            result.update(cached, status="cached", attempts=[], reused_from_run_id=previous.get("run_id"), old_file_preserved=False)
            results.append(result)
            atomic_json(target, manifest)
            print(f"[拉取] {name}：复用TTL内已验证文件（未重新联网）", flush=True)
            continue
        if not candidates:
            result["error"] = "必须提供 --report-date 并核对响应的股东报告期，禁止API默认旧日期"
        for candidate in candidates:
            if time.monotonic() >= deadline:
                result["error"] = "总拉取预算已耗尽；未尝试剩余源"
                result["budget_exhausted"] = True
                break
            try:
                frame, attempts = fetch_job(candidate, cache_dir=out_dir/".fetch_failures", timeout=timeout,
                                            retries=retries, failure_ttl=failure_ttl, force=force, deadline=deadline)
                result["attempts"].extend(attempts)
                tmp = output.with_suffix(".csv.tmp")
                frame.to_csv(tmp, index=False, encoding="utf-8-sig")
                tmp.replace(output)
                result.pop("error", None)
                result.update(status="success", source=candidate["module"]+"."+candidate["function"],
                              rows=len(frame), columns=len(frame.columns), old_file_preserved=False,
                              sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                              fetched_epoch=time.time(), report_date=report_date)
                print(f"[拉取] {name}：{len(frame)}行 -> {filename}", flush=True)
                break
            except FetchError as exc:
                result["attempts"].extend(exc.attempts)
                result["error"] = str(exc)
        if result["status"] == "failed":
            print(f"[拉取] {name} FAIL：{result.get('error')}；保留旧文件={result['old_file_preserved']}", flush=True)
        results.append(result)
        atomic_json(target, manifest)
    run.update(status="WARN" if any(r["status"]=="failed" for r in results) else "PASS", finished_at=now())
    manifest.update(status=run["status"], finished_at=run["finished_at"])
    atomic_json(target, manifest)
    return manifest


def add_fetch_options(parser):
    parser.add_argument("--timeout", type=float, default=30, help="每次候选调用的硬超时秒数（含模块导入）")
    parser.add_argument("--retries", type=int, choices=range(1,4), default=2, help="每候选最多尝试1~3次")
    parser.add_argument("--failure-ttl", type=float, default=900, help="失败缓存秒数；0禁用")
    parser.add_argument("--force-refresh", action="store_true", help="忽略失败缓存重新请求")
    parser.add_argument("--fetch-budget", type=float, default=180, help="整批网络拉取硬预算秒数")
    parser.add_argument("--success-ttl", type=float, default=3600, help="成功数据复用秒数；0每次拉取；会核对股票/指纹/报告期")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("code")
    parser.add_argument("--out", required=True)
    parser.add_argument("--items", default="daily,sheets,indicators,dividends,top10,profile")
    parser.add_argument("--report-date", help="股东数据的明确报告期，例如2026-06-30")
    add_fetch_options(parser)
    args = parser.parse_args()
    code = args.code.split(".")[0] if "." in args.code else args.code
    market = "SH" if code.startswith(("6","9")) else "BJ" if code.startswith(("4","8","92")) else "SZ"
    manifest = fetch_datasets(code, market, args.out, items=set(args.items.split(",")), timeout=args.timeout,
                              retries=args.retries, failure_ttl=args.failure_ttl, force=args.force_refresh, report_date=args.report_date,
                              total_budget=args.fetch_budget, success_ttl=args.success_ttl)
    return int(manifest["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
