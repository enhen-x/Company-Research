"""Evaluate research inputs and their explicit bindings to existing report sections.

The only output is reports/研究模型_输出.json. A resolved reference is not proof
of the cited claim. Human research judgement always remains NOT_ASSESSED here.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path

from research_topics import evaluate_topics, read_input, read_json_bounded, validate_json_depth
from run_support import atomic_json


SECTION_MODULES = {"industry": ("2.2", "2.4", "6.1", "6.2", "6.4"),
                   "guidance": ("3.4", "3.5", "5.2", "8.2"),
                   "orders": ("3.2", "4.2", "4.3", "5.1", "8.2"),
                   "forecast": ("5.1", "5.2", "5.3", "5.4"),
                   "theses": ("9.1", "9.2", "9.3"), "decision": ("6.4", "7.1", "7.2", "7.3")}
MAX_OUTPUT_BYTES = 50_000_000
MAX_OUTPUT_DEPTH = 256


def validate_output(result):
    """A generated result must fit the same finite contract as check-only reads."""
    validate_json_depth(result, max_depth=MAX_OUTPUT_DEPTH, label="研究模型输出")
    encoded = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(encoded) > MAX_OUTPUT_BYTES:
        raise ValueError(f"研究模型输出超过{MAX_OUTPUT_BYTES / 1_000_000:g}MB；请精简重复引用内容")


def read_output(path):
    return read_json_bounded(path, max_bytes=MAX_OUTPUT_BYTES, max_depth=MAX_OUTPUT_DEPTH, label="研究模型输出")


def code_fingerprint():
    root = Path(__file__).resolve().parent
    return {name: hashlib.sha256((root/name).read_bytes()).hexdigest()
            for name in ("research_topics.py", "research_models.py", "capital_metrics.py", "research_topic_qc.py")}


def evaluate_report(project, config, result, report):
    findings = []
    if report is None:
        return {"status": "NOT_ASSESSED", "findings": ["没有指定主报告"], "bindings": []}
    raw_report = Path(report).read_bytes()
    text = raw_report.decode("utf-8-sig")
    report_hash = hashlib.sha256(raw_report).hexdigest()
    headings = {m.group(1) for m in re.finditer(r"^###\s+§?(\d+\.\d+(?:\.\d+)?)\s+", text, re.M)}
    known = {r["id"] for r in result.get("registry", {}).get("records", []) if isinstance(r, dict) and "id" in r}
    bindings = config.get("report_bindings")
    if not isinstance(bindings, list) or not bindings:
        return {"status": "NOT_ASSESSED", "findings": ["缺少report_bindings，尚未核对专题与原章节关联"],
                "bindings": [], "report_sha256": report_hash}
    checked = []
    for item in bindings:
        if not isinstance(item, dict):
            findings.append("report_bindings记录必须为对象")
            continue
        module, section, refs = item.get("module"), item.get("section"), item.get("refs")
        if not isinstance(module, str) or not isinstance(section, str):
            findings.append("report_bindings.module和section必须为字符串")
            continue
        if module not in SECTION_MODULES or section not in SECTION_MODULES.get(module, ()):
            findings.append(f"专题与原章节不匹配: {module}/{section}")
        if section not in headings:
            findings.append(f"报告未找到原小节: {section}")
        if not isinstance(refs, list) or not refs or any(not isinstance(r, str) or r not in known for r in refs):
            findings.append(f"{module}/{section} 存在未解析事实/假设引用")
        checked.append({"module": module, "section": section, "refs": refs})
    if "研究模型_输出.json" not in text:
        findings.append("主报告未引用研究模型_输出.json")
    missing = [name for name, module in result.get("modules", {}).items()
               if module.get("status") == "OK" and name not in {x["module"] for x in checked}]
    if missing:
        findings.append("可用专题尚未绑定原章节: " + ",".join(missing))
    return {"status": "INVALID" if findings else "STRUCTURE_CHECKED", "findings": findings,
            "bindings": checked, "report_sha256": report_hash,
            "limitation": "仅验证章节存在和引用关系；不以关键词匹配证明文本支持结论"}


def run(project, report=None, *, check_only=False, require_complete=False):
    project = Path(project).resolve()
    source, output = project/"input/研究模型.json", project/"reports/研究模型_输出.json"
    if not source.is_file():
        missing = {"status": "INCOMPLETE", "human_review": "NOT_ASSESSED", "reason": "无研究模型输入"}
        if check_only:
            return dict(missing, check_error="模型输入不存在，无法核验已保存输出"), 1
        return missing, 2 if require_complete else 0
    try:
        raw_source, config = read_input(source)
        result = evaluate_topics(config)
        result["input_source_sha256"] = hashlib.sha256(raw_source).hexdigest()
        result["code_fingerprint"] = code_fingerprint()
        result["report_check"] = evaluate_report(project, config, result, report) if isinstance(config, dict) else {"status":"INVALID"}
        result["quality"] = {"calculation":result["status"], "evidence":result.get("registry", {}).get("status", "INCOMPLETE"),
                             "report_link":result["report_check"]["status"], "human_review":"NOT_ASSESSED"}
        result["human_review"] = "NOT_ASSESSED"
        validate_output(result)
        if check_only:
            _, saved = read_output(output)
            if saved != result:
                return dict(result, check_error="模型输入/代码/正文已变化，输出须重算"), 1
        else:
            atomic_json(output, result)
        invalid = result["status"] == "INVALID" or result["report_check"]["status"] == "INVALID"
        incomplete = result["status"] != "OK" or result["report_check"]["status"] != "STRUCTURE_CHECKED"
        return result, 1 if invalid or (require_complete and incomplete) else 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as exc:
        result = {"schema_version":1, "status":"INVALID", "error":str(exc)[:4096], "human_review":"NOT_ASSESSED"}
        if not check_only:
            try:
                validate_output(result)
                atomic_json(output, result)
            except (OSError, ValueError) as write_error:
                result["output_error"] = str(write_error)[:4096]
        return result, 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True)
    parser.add_argument("--report")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)
    report = Path(args.dir)/args.report if args.report else None
    result, code = run(args.dir, report, check_only=args.check_only, require_complete=args.require_complete)
    print(json.dumps({"status":result.get("status"), "quality":result.get("quality"), "error":result.get("error") or result.get("check_error"),
                      "report_findings":result.get("report_check", {}).get("findings", []),
                      "findings_count":len(result.get("findings", []))}, ensure_ascii=False), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
