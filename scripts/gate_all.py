#!/usr/bin/env python3
"""One report-build entry: preflight -> actual build -> unchanged full quality gates.
Every run replaces its machine ledger before any check. Check-only never attests a build.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import uuid
from pathlib import Path

from run_support import BatchLock, atomic_json, fingerprints, now, run_process


def _capex_enabled(project: Path) -> bool:
    plan_path = project / "input" / "capex_dividend_plan.json"
    if not plan_path.is_file():
        return False
    try:
        data = json.loads(plan_path.read_text(encoding="utf-8-sig"))
        return isinstance(data, dict) and data.get("enabled") is not False
    except Exception:
        return True


def check_sotp(project, report):
    try:
        trigger = json.loads((project / "input" / "sotp_触发.json").read_text(encoding="utf-8-sig"))
        if not isinstance(trigger, dict) or type(trigger.get("enabled")) is not bool:
            raise ValueError("enabled 必须为 true/false")
    except (OSError, ValueError) as exc:
        raise ValueError(f"SOTP 触发状态缺失或无效: {exc}；先运行 sotp_valuation.py --dir . --detect-only")
    if not trigger["enabled"]:
        return "SKIP", "明确声明非平台型公司，SOTP可选"
    if not (project / "reports" / "sotp_输出.json").is_file():
        raise ValueError("平台型触发但缺少 reports/sotp_输出.json")
    text = report.read_text(encoding="utf-8-sig")
    if "图18" not in text or "sotp_输出.json" not in text:
        raise ValueError("平台型触发但报告未引用图18及sotp_输出.json")
    return "PASS", "SOTP输出存在且已引用"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True)
    parser.add_argument("--report", default="")
    parser.add_argument("--legacy", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--stage-timeout", type=float, default=300, help="每阶段硬超时秒数")
    parser.add_argument("--heartbeat", type=float, default=10, help="阶段心跳间隔秒数")
    parser.add_argument("--total-timeout", type=float, default=1200, help="整次成稿硬预算秒数")
    parser.add_argument("--incremental", action="store_true", help="仅指纹完全一致时复用已通过的图表/HTML，质量门仍重跑")
    parser.add_argument("--require-research", action="store_true", help="要求结构化研究模型及原章节引用完整")
    parser.add_argument("--_gate-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--_gate-token", default="", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if any(not math.isfinite(v) or v <= 0 for v in (args.stage_timeout, args.heartbeat, args.total_timeout)):
        parser.error("stage-timeout/heartbeat/total-timeout 必须为有限正数")
    project = Path(args.dir).resolve()
    if not args._gate_worker:
        token = str(uuid.uuid4())
        result = run_process([sys.executable, "-u", str(Path(__file__).resolve()),
                              *sys.argv[1:], "--_gate-worker", "--_gate-token", token],
                             timeout=args.total_timeout, heartbeat=args.heartbeat, label="成稿总预算")
        if result["status"] == "TIMEOUT":
            path = project/"reports/流水线执行状态.json"
            try:
                ledger = json.loads(path.read_text(encoding="utf-8-sig"))
                if ledger.get("run_id") == token:
                    ledger.update(status="TIMEOUT", technical_pass=False, build_completed=False,
                                  fully_rebuilt=False, delivery_ready=False, finished_at=now(),
                                  error="整次成稿硬超时，进程树已终止", elapsed_seconds=result["elapsed_seconds"])
                    for entry in ledger.get("stages", []):
                        if entry.get("status") == "RUNNING":
                            entry.update(status="TIMEOUT", finished_at=now())
                        elif entry.get("status") == "PENDING":
                            entry.update(status="BLOCKED", reason="整次成稿硬超时")
                    atomic_json(path, ledger)
            except (OSError, ValueError, AttributeError):
                pass
        return 0 if result["status"] == "PASS" else 1
    try:
        with BatchLock(project/"reports/.gate.lock"):
            return run_locked(args, project)
    except RuntimeError as exc:
        print(f"[FAIL] {exc}", flush=True)
        return 1


def run_locked(args, project):
    reports, scripts = project/"reports", project/"scripts"
    ledger_path = reports/"流水线执行状态.json"
    try:
        previous = json.loads(ledger_path.read_text(encoding="utf-8-sig"))
        if not isinstance(previous, dict):
            previous = {}
    except (OSError, ValueError):
        previous = {}
    ledger = {"run_id": args._gate_token or str(uuid.uuid4()), "started_at": now(), "status":"RUNNING", "technical_pass":False,
              "build_completed":False, "mode":"CHECK_ONLY" if args.check_only else "BUILD",
              "legacy":args.legacy, "research_quality":"NOT_ASSESSED", "stages":[],
              "incremental_requested":args.incremental, "fully_rebuilt":False, "delivery_ready":False}
    atomic_json(ledger_path, ledger)  # invalidate any previous success immediately
    started = time.monotonic()
    def fail(message):
        ledger.update(status="FAIL", finished_at=now(), error=str(message), elapsed_seconds=round(time.monotonic()-started,3))
        atomic_json(ledger_path, ledger)
        print(f"[FAIL] {message}", flush=True)
        return 1
    try:
        candidates = sorted(reports.glob("*_分析报告.md"))
        if not args.report and len(candidates) != 1:
            return fail("必须有唯一主报告；多个或缺失时请用 --report 指定")
        report = project/args.report if args.report else candidates[0]
        if not report.is_file():
            return fail(f"报告不存在: {report}")
        if not (project/"input/图表豁免.json").is_file():
            return fail("缺少图表豁免配置")
        from chart_qc import _chart_exemptions
        _chart_exemptions(project)
        check_sotp(project, report)  # cheap trigger validation, before expensive plots
        inputs = fingerprints(project, ["data", "input", "scripts", report.relative_to(project)])
        ledger.update(report=str(report), input_fingerprint=inputs)
        reuse = False
        if args.incremental and not args.check_only and not args.legacy and previous.get("delivery_ready", previous.get("build_completed")) and previous.get("status") == "PASS" and previous.get("input_fingerprint") == inputs:
            expected = previous.get("artifacts", {}).get("files", {})
            reuse = bool(expected) and all((project/name).is_file() and __import__("hashlib").sha256((project/name).read_bytes()).hexdigest() == digest for name,digest in expected.items())
        if reuse:
            ledger["reused_from_run_id"] = previous.get("run_id")
        stem = report.stem.removesuffix("_分析报告")
        if "_" not in stem:
            return fail("报告文件名应为 <公司>_<代码>_分析报告.md")
        name, code = stem.rsplit("_", 1)
        stages = [("期间输入预检", "chart_period_qc.py", ["--dir",str(project),"--inputs-only"])]
        if not args.legacy:
            stages.append(("报告模板门", "report_template_qc.py", ["--report",str(report)]))
            if (project/"input/研究模型.json").exists() or args.require_research:
                stages.append(("研究专题计算与引用检查", "research_topic_qc.py", ["--dir",str(project),"--report",str(report)]
                               + (["--check-only"] if args.check_only else [])
                               + (["--require-complete"] if args.require_research else [])))
        if not args.check_only:
            stages.append(("固定图表构建", "analyze_charts.py", ["--dir",str(project),"--code",code,"--name",name]))
            if _capex_enabled(project):
                stages.append(("Capex与分红跃迁图表与测算", "capex_dividend_engine.py", ["--dir", str(project)]))
        if not args.legacy:
            stages.extend([
                ("主报告 HTML 渲染与一致性", "md_to_html.py", ["--input",str(report)]+(["--check"] if args.check_only else [])),
                ("G22 本期财报体检门", "financial_health_qc.py", ["--dir",str(project),"--report",str(report)])])
        stages.extend([
            ("G8-PERIOD 最新实际期覆盖门", "chart_period_qc.py", ["--dir",str(project)]),
            ("G8 图表质量门（完整性+契约+渲染）", "chart_qc.py", ["--dir",str(project),"--report",str(report)]),
            ("G9 格式质量门", "format_qc.py", ["--dir",str(project),"--report",str(report)]),
            ("SOTP 分部估值门（平台型强制）", None, [])])
        ledger["stages"] = [{"name":label,"status":"PENDING"} for label,_,_ in stages]
        atomic_json(ledger_path, ledger)
        print(f"批次: {project} ｜ {ledger['mode']} ｜ run_id={ledger['run_id']}", flush=True)
        blocked = False
        for entry, (label, filename, command) in zip(ledger["stages"], stages):
            if blocked:
                entry.update(status="BLOCKED", reason="前置阶段失败，修复后完整重跑")
                continue
            entry.update(status="RUNNING", started_at=now())
            atomic_json(ledger_path, ledger)
            print(f"\n▶ {label}", flush=True)
            remaining = args.total_timeout - (time.monotonic()-started)
            if remaining <= 0:
                entry.update(status="TIMEOUT", error="整次成稿预算耗尽", elapsed_seconds=0, finished_at=now())
            elif reuse and label in ("固定图表构建", "Capex与分红跃迁图表与测算", "主报告 HTML 渲染与一致性"):
                entry.update(status="REUSED", elapsed_seconds=0, finished_at=now(), reused_from_run_id=previous.get("run_id"),
                             reason="同一输入/代码/正文及全部产物哈希匹配")
            elif filename is None:
                status, detail = check_sotp(project, report)
                entry.update(status=status, detail=detail, elapsed_seconds=0, finished_at=now())
            elif not (scripts/filename).is_file():
                entry.update(status="FAIL", error=f"缺少脚本 {filename}", elapsed_seconds=0, finished_at=now())
            else:
                entry.update(run_process([sys.executable,"-u",str(scripts/filename),*command], cwd=project,
                                         timeout=min(args.stage_timeout, remaining), heartbeat=args.heartbeat, label=label))
                entry.pop("output", None)  # live output remains in caller's log, ledger retains concise evidence
            print(f"[{label}] {entry['status']} ｜ {entry['elapsed_seconds']:.2f}s", flush=True)
            blocked = entry["status"] not in ("PASS","SKIP","REUSED")
            if label == "研究专题计算与引用检查" and entry["status"] == "PASS":
                research = json.loads((reports/"研究模型_输出.json").read_text(encoding="utf-8-sig"))
                ledger["research_checks"] = research.get("quality", {"calculation":research.get("status")})
                ledger["research_quality"] = "STRUCTURE_CHECKED" if research.get("status") == "OK" and research.get("report_check",{}).get("status") == "STRUCTURE_CHECKED" else "LIMITED"
                ledger["human_research_review"] = "NOT_ASSESSED"
            atomic_json(ledger_path, ledger)
        if blocked:
            return fail("存在失败阶段；未执行阶段已标记BLOCKED，不能以旧产物认定完成")
        after = fingerprints(project, ["data", "input", "scripts", report.relative_to(project)])
        if after != inputs:
            return fail("运行中原始数据/输入/模板/正文发生变化；须按同一版本完整重跑")
        artifacts = fingerprints(project, ["reports/图表", "reports/图表期间覆盖.json", "reports/图表最新期数据.json",
                                            report.with_suffix(".html").relative_to(project), "reports/研究模型_输出.json"])
        for p in sorted(reports.glob("*_图表.html")):
            artifacts["files"].update(fingerprints(project,[p.relative_to(project)])["files"])
        # Evidence includes all output hashes and a run-scoped completion flag.
        artifacts["sha256"] = __import__("hashlib").sha256(json.dumps(artifacts["files"],sort_keys=True).encode()).hexdigest()
        ledger.update(status="PASS", technical_pass=True, build_completed=not args.check_only and not args.legacy and not reuse,
                      fully_rebuilt=not args.check_only and not args.legacy and not reuse,
                      delivery_ready=not args.check_only and not args.legacy,
                      artifacts=artifacts, elapsed_seconds=round(time.monotonic()-started,3), finished_at=now())
        atomic_json(ledger_path, ledger)
        print(f"\n汇总: PASS，{ledger['elapsed_seconds']:.2f}s；{'已复用验证匹配的构建产物' if reuse else '本次模式='+ledger['mode']}；研究状态={ledger['research_quality']}，人工研究判断不由技术门背书。", flush=True)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return fail(exc)
    except KeyboardInterrupt:
        return fail("用户中断，执行未完成")


if __name__ == "__main__":
    raise SystemExit(main())
