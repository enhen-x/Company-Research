#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一主报告模板门控。

检查报告是否遵循 references/report-template.md v3：固定十部分、固定财务子节、
每节结论、关键内容、元信息和占位符清理。它不判断投资观点是否正确，数字一致性
由 financial_health_qc.py、chart_qc.py 和其他门控负责。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from chart_numbers import report_amount_unit_violations


SECTIONS = [
    ("1", "投资摘要"),
    ("2", "宏观与行业分析"),
    ("3", "公司分析"),
    ("4", "财务分析"),
    ("5", "盈利预测"),
    ("6", "估值分析"),
    ("7", "投资建议与目标价"),
    ("8", "催化剂与跟踪"),
    ("9", "风险与反证条件"),
    ("10", "附录"),
]

FIXED_FINANCE = [
    ("§4.1", "盈利与资产负债表"),
    ("§4.2", "现金流与盈利质量"),
    ("§4.3", "本期财报体检"),
    ("§4.4", "同行业比较"),
]

CONTENT_RULES = {
    "1": ("最终结论", "12个月目标价", "龟龟", "最大优势", "最大风险"),
    "2": ("宏观", "生命周期", "需求", "供给", "政策"),
    "3": ("商业模式", "分部", "护城河", "管理层", "治理"),
    "4": ("盈利与资产负债表", "现金流与盈利质量", "本期财报体检", "同行业比较"),
    "5": ("假设", "悲观", "基准", "乐观", "概率", "敏感性", "跟踪指标"),
    "6": ("SOTP", "龟龟穿透回报率", "R_eff", "II", "KK", "目标买入价"),
    "7": ("市场/券商轨", "龟龟轨", "概率加权", "仓位", "门槛价格"),
    "8": ("催化剂", "跟踪验证台账", "验证", "触发"),
    "9": ("风险矩阵", "概率及方法", "尾部", "反证", "待验证"),
    "10": ("数据来源", "方法", "图表清单", "复验", "免责声明"),
}

# The template deliberately uses braces for every replaceable field. Keep the
# check broad so newly added fields (for example {评级}) cannot silently pass.
PLACEHOLDER_RE = re.compile(
    r"【[^】]*】|\b(?:TODO|TBD)\b|\{[^{}\r\n]*\}"
)


def _mask_fenced(text: str) -> str:
    """Mask fenced code blocks but preserve newlines for line-based parsing."""
    def repl(match: re.Match[str]) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))

    return re.sub(r"```.*?```|~~~.*?~~~", repl, text, flags=re.S)


def _section_spans(text: str) -> list[tuple[str, str, int, int]]:
    masked = _mask_fenced(text)
    matches = list(re.finditer(r"^##\s+([^\n]+?)\s*$", masked, flags=re.M))
    return [(m.group(1).strip(), text[m.start():m.end()], m.start(),
             matches[i + 1].start() if i + 1 < len(matches) else len(text))
            for i, m in enumerate(matches)]


def _line_no(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def check_report(text: str) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    masked = _mask_fenced(text)
    spans = _section_spans(text)
    for match in report_amount_unit_violations(masked):
        failures.append(f'金额/股数单位不符合报告口径（L{match["line"]}）：请同时换算数值为亿/万，不得只改单位')

    title = re.search(r"^#\s+.+分析报告\s*$", masked, flags=re.M)
    if not title:
        failures.append("缺少标准报告标题（应为 '# 公司（代码.市场）分析报告'）")

    section_positions: dict[str, int] = {}
    for number, title_text in SECTIONS:
        expected = f"{number}. {title_text}"
        found = [s for s in spans if s[0] == expected]
        if not found:
            failures.append(f"缺少固定章节「## {expected}」")
        elif len(found) > 1:
            failures.append(f"固定章节「## {expected}」重复 {len(found)} 次")
        else:
            section_positions[number] = found[0][2]

    if section_positions:
        ordered = [section_positions[n] for n, _ in SECTIONS if n in section_positions]
        if ordered != sorted(ordered):
            failures.append("十个固定章节顺序错误")

    allowed = {f"{n}. {t}" for n, t in SECTIONS}
    for heading, _, pos, _ in spans:
        if heading not in allowed:
            failures.append(f"存在未纳入模板的二级章节「{heading}」（L{_line_no(text, pos)}）")

    metadata_start = 0
    first_section = section_positions.get("1", len(text))
    metadata = text[metadata_start:first_section]
    for token in ("报告元信息", "分析日期", "当前价", "总市值", "最新财报", "Rf", "数据审计状态"):
        if token not in metadata:
            failures.append(f"元信息缺少「{token}」")

    for number, _ in SECTIONS:
        match = next((s for s in spans if s[0] == f"{number}. {dict(SECTIONS)[number]}"), None)
        if not match:
            continue
        body = text[match[2]:match[3]]
        for token in CONTENT_RULES[number]:
            if token not in body:
                failures.append(f"第 {number} 章缺少必写内容「{token}」")
        if "**本节结论**：" not in body and "**本节结论**:" not in body:
            failures.append(f"第 {number} 章缺少「本节结论」")
        if "数据依据：" not in body and "数据依据:" not in body:
            failures.append(f"第 {number} 章缺少「数据依据」")

    finance_match = next((s for s in spans if s[0] == "4. 财务分析"), None)
    if finance_match:
        finance_body = text[finance_match[2]:finance_match[3]]
        positions = []
        for code, title_text in FIXED_FINANCE:
            matches = list(re.finditer(rf"^###\s+{re.escape(code)}\s+{re.escape(title_text)}\s*$", finance_body, flags=re.M))
            if not matches:
                failures.append(f"第 4 章缺少固定子节「{code} {title_text}」")
            elif len(matches) > 1:
                failures.append(f"固定子节「{code} {title_text}」重复 {len(matches)} 次")
            else:
                positions.append(matches[0].start())
                start = matches[0].start()
                end = next((p for p in [m.start() for m in re.finditer(r"^###\s+", finance_body, flags=re.M)] if p > start), len(finance_body))
                sub_body = finance_body[start:end]
                if "**小节结论**：" not in sub_body and "**小节结论**:" not in sub_body:
                    failures.append(f"固定子节「{code}」缺少「小节结论」")
                if "数据依据：" not in sub_body and "数据依据:" not in sub_body:
                    failures.append(f"固定子节「{code}」缺少「数据依据」")
        if positions != sorted(positions):
            failures.append("第 4 章固定子节顺序错误")

        health = finance_body[finance_body.find("### §4.3"):] if "### §4.3" in finance_body else ""
        for token in ("4.3.1", "4.3.2", "4.3.3", "4.3.4", "4.3.5", "4.3.6", "4.3.7", "4.3.8", "4.3.9", "本期财报体检.json"):
            if token not in health:
                failures.append(f"§4.3 缺少必写项「{token}」")

    placeholders = PLACEHOLDER_RE.findall(masked)
    if placeholders:
        failures.append(f"仍有 {len(placeholders)} 个模板占位符（首个：{placeholders[0]}）")

    return failures, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="统一证券调研主报告模板门控")
    parser.add_argument("--report", required=True, help="主报告 Markdown 路径")
    args = parser.parse_args(argv)
    report = Path(args.report)
    if not report.is_file():
        print(f"[FAIL] 报告不存在: {report}")
        return 2
    text = report.read_text(encoding="utf-8-sig")
    failures, warnings = check_report(text)
    for issue in failures:
        print(f"[FAIL] {issue}")
    for issue in warnings:
        print(f"[WARN] {issue}")
    print(f"== {report.name}: FAIL {len(failures)} | WARN {len(warnings)} ==")
    if failures:
        print("❌ 报告模板门未通过：请按 references/report-template.md v3 补齐后重跑")
        return 1
    print("✅ 报告模板门通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
