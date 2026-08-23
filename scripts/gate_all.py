#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键图表质量门（G8 + G9 统一执行，2026-08-18 新增）

背景：图表问题（数据缺失/格式/标注/契约）曾依赖人工逐条跑 chart_qc + format_qc 并人工解读，
本脚本把「图表完整性（G8-完整）+ 运营数据契约（G8-OPS）+ 渲染质量（G8-RENDER）+ 格式（G9）」
收敛为单条命令：任一 FAIL → 退出码 1，杜绝静默通过。

用法：
    python scripts/gate_all.py --dir "G:\\理财\\个股分析\\SZ.002028 思源电气\\2026_08_18" [--report reports/思源电气_002028_分析报告.md]

输出：逐门结果 + 汇总 PASS/FAIL；退出码 0=全部通过，1=存在 FAIL。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="批次目录（含 reports/ 与 scripts/）")
    ap.add_argument("--report", default="", help="报告 MD 相对路径（默认自动查找 reports/*_分析报告.md）")
    args = ap.parse_args()

    proj = Path(args.dir).resolve()
    scripts = proj / "scripts"
    reports = proj / "reports"

    if args.report:
        report = proj / args.report
    else:
        cands = list(reports.glob("*_分析报告.md"))
        if not cands:
            print("[FAIL] 未找到 reports/*_分析报告.md，请用 --report 指定")
            return 1
        report = cands[0]
    if not report.exists():
        print(f"[FAIL] 报告不存在: {report}")
        return 1

    gates = [
        ("G8 图表质量门（完整性+契约+渲染）", scripts / "chart_qc.py", ["--dir", str(proj), "--report", str(report)]),
        ("G9 格式质量门", scripts / "format_qc.py", ["--dir", str(proj), "--report", str(report)]),
        ("SOTP 分部估值门（平台型强制）", None, []),
    ]

    overall_fail = 0
    print("=" * 68)
    print("一键图表质量门（G8 + G9）")
    print(f"批次: {proj} ｜ 报告: {report.name}")
    print("=" * 68)
    for name, script, cmd in gates:
        if name == "SOTP 分部估值门（平台型强制）":
            print(f"\n▶ {name}")
            # 平台型检测：sotp_触发.json enabled=true → 必须存在 reports/sotp_输出.json 且报告引用图18
            try:
                trig = json.loads((proj / "input" / "sotp_触发.json").read_text(encoding="utf-8"))
                enabled = bool(trig.get("enabled"))
            except Exception:
                enabled = False
            if not enabled:
                print("    [SKIP] 非平台型公司（sotp_触发.json 未启用），SOTP 可选")
                continue
            sotp_out = proj / "reports" / "sotp_输出.json"
            if not sotp_out.exists():
                print("    [FAIL] 平台型触发但缺少 reports/sotp_输出.json——请填写 input/sotp_输入.json 并运行 sotp_valuation.py")
                overall_fail = 1
                continue
            rpt_text = report.read_text(encoding="utf-8")
            if "图18" not in rpt_text or "sotp_输出.json" not in rpt_text:
                print("    [FAIL] 平台型触发但报告未引用 SOTP（需 §6 嵌入图18 并引用 sotp_输出.json 结论）")
                overall_fail = 1
                continue
            print("    [OK] SOTP 输出存在且报告已引用（图18 + sotp_输出.json）")
            continue
        if not script.exists():
            print(f"[SKIP] {name}: 脚本缺失 {script}")
            overall_fail = 1
            continue
        print(f"\n▶ {name}")
        r = subprocess.run([sys.executable, str(script), *cmd], cwd=proj)
        if r.returncode != 0:
            print(f"[{name}] ❌ FAIL（退出码 {r.returncode}）")
            overall_fail = 1
        else:
            print(f"[{name}] ✅ 通过")

    print("\n" + "=" * 68)
    if overall_fail:
        print("汇总: ❌ 存在 FAIL——请按上方 FAIL 项修复后重跑")
        return 1
    print("汇总: ✅ 全部门控通过（WARN 项需在交付清单说明）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
