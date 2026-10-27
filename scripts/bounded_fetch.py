"""JSON-described fetch jobs in killable processes; finite retries and negative TTL cache.
Only failed requests are cached: a cached failure never supplies old data as a success.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

from run_support import atomic_json, now, run_process


class FetchError(RuntimeError):
    def __init__(self, message, attempts):
        super().__init__(message)
        self.attempts = attempts


def job(module, function, **kwargs):
    return {"module": module, "function": function, "kwargs": kwargs}


def cache_key(spec):
    try:
        version = importlib.metadata.version("akshare")
    except importlib.metadata.PackageNotFoundError:
        version = "missing"
    identity = {"job": spec, "akshare": version, "python": sys.version,
                "worker": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    local = Path(__file__).with_name(spec["module"] + ".py")
    if local.is_file():
        identity["adapter"] = hashlib.sha256(local.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def fetch_job(spec, *, cache_dir, timeout=30, retries=2, delay=.5, failure_ttl=900, force=False, deadline=None):
    if (type(retries) is not int or not 1 <= retries <= 3 or
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                for v in (timeout, failure_ttl, delay)) or timeout <= 0 or failure_ttl < 0 or delay < 0):
        raise ValueError("retries 必须为1~3，timeout>0，delay/failure_ttl>=0")
    cache = Path(cache_dir) / (cache_key(spec) + ".failure.json")
    attempts = []
    if not force and failure_ttl:
        try:
            saved = json.loads(cache.read_text(encoding="utf-8"))
            if 0 <= time.time() - saved["failed_at"] < failure_ttl:
                entry = dict(spec, status="FAILURE_CACHED", error=saved["error"],
                             started_at=now(), elapsed_seconds=0, expires_at=saved["failed_at"]+failure_ttl)
                print(f"[拉取] {spec['function']}：命中失败缓存，跳至候选源", flush=True)
                raise FetchError(saved["error"], [entry])
        except (OSError, ValueError, KeyError, TypeError):
            pass
    with tempfile.TemporaryDirectory(prefix="research_fetch_") as temp:
        request = Path(temp) / "request.json"
        output = Path(temp) / "result.pkl"
        meta = Path(temp) / "result.json"
        atomic_json(request, spec)
        for number in range(1, retries + 1):
            remaining = deadline - time.monotonic() if deadline is not None else timeout
            if remaining <= 0:
                attempts.append(dict(spec, status="BUDGET_EXHAUSTED", error="总拉取预算已耗尽", elapsed_seconds=0))
                raise FetchError("总拉取预算已耗尽", attempts)
            attempt_timeout = min(timeout, remaining)
            output.unlink(missing_ok=True)
            meta.unlink(missing_ok=True)
            print(f"[拉取] {spec['function']} {number}/{retries}，硬超时 {attempt_timeout:g}s", flush=True)
            result = run_process([sys.executable, "-u", str(Path(__file__).resolve()), "--worker", str(request),
                                  "--output", str(output), "--meta", str(meta)],
                                 timeout=attempt_timeout, heartbeat=min(10, attempt_timeout), label=spec["function"], echo=False)
            try:
                detail = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
            except (OSError, ValueError):
                detail = {"error": "子进程元数据损坏", "retryable": False}
            entry = dict(spec, attempt=number, status=result["status"], exit_code=result["exit_code"],
                         started_at=result["started_at"], elapsed_seconds=result["elapsed_seconds"])
            if result["status"] == "PASS" and output.exists():
                import pandas as pd
                frame = pd.read_pickle(output)  # produced by this local worker, never by a network response
                entry["rows"] = len(frame)
                attempts.append(entry)
                cache.unlink(missing_ok=True)
                return frame, attempts
            error = detail.get("error") or ("硬超时" if result["status"] == "TIMEOUT" else result["output"][-2000:] or "无有效结果")
            entry["error"] = error
            attempts.append(entry)
            print(f"[拉取] {spec['function']} {entry['status']}：{error}", flush=True)
            if detail.get("retryable") is False:
                break
            if number < retries:
                time.sleep(min(delay, max(0, deadline-time.monotonic())) if deadline is not None else delay)
    if failure_ttl:
        atomic_json(cache, {"job": spec, "failed_at": time.time(), "error": attempts[-1]["error"]})
    raise FetchError(attempts[-1]["error"], attempts)


def worker(request, output, meta):
    try:
        spec = json.loads(Path(request).read_text(encoding="utf-8"))
        module = importlib.import_module(spec["module"])
        frame = getattr(module, spec["function"])(**spec.get("kwargs", {}))
        import pandas as pd
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise ValueError("接口返回空数据或非DataFrame")
        frame.to_pickle(output)
        atomic_json(meta, {"status": "PASS", "rows": len(frame)})
        return 0
    except Exception as exc:
        atomic_json(meta, {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}",
                           "retryable": not isinstance(exc, (AttributeError, ImportError, TypeError))})
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--meta", required=True)
    args = parser.parse_args()
    raise SystemExit(worker(args.worker, args.output, args.meta))
