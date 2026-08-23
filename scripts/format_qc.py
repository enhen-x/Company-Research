#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markdown 报告格式质量门（格式门控，并入 G8 门控流程 / 新增 F 系列）

背景：2026-08-16 药明康德批次暴露"---## 写在一行"类格式事故——报告由多段拼接时
分隔线与标题粘连、或分隔线后缺空行，导致部分渲染器把 --- 并入标题/误判 setext 标题。
本脚本把格式检查固化为门控，成稿前必须运行，无 FAIL 才可交付。

用法：
    python format_qc.py --dir 项目目录 [--report reports/<报告>.md] [--strict-warn]

检查项（F 系列）：
  F1  分隔线与标题同行粘连（---## / ***# / ___#）         FAIL
  F2  分隔线后无空行紧跟标题（--- 下一行即 ##）            FAIL
  F3  标题行后紧接分隔线（setext 标题歧义，# xxx 下一行 ---）FAIL
  F4  表格列数不一致（表头/分隔行/数据行）                 FAIL
  F5  连续空行 >=3                                       WARN
  F6  行尾空白（除表格/代码块外）                         WARN
  F7  粗体/斜体标记未闭合（** 或 * 计数为奇数）            WARN
  F8  图片引用文件不存在（相对 reports/）                  FAIL
  F9  图片重复引用（每图只嵌入一次）                       FAIL
  F10 换行符混用（CRLF/LF）                              WARN
  F11 文件以 UTF-8 BOM 开头                              WARN
  F12 表格分隔行缺失/格式错误（表头后无合法分隔行，或首行即分隔行）FAIL
  F13 表格后未空行，与正文粘连（后续普通文本被并入表格）     FAIL
  F14 表格行缺少结尾 |（首尾 | 未闭合）                   WARN
  F15 单列表格（疑似漏 | 分隔，仅 1 列）                   WARN
  F16 表格前未空行（建议与上文空行分隔）                  WARN

退出码：0 = 通过（可含 WARN）；1 = 存在 FAIL（修复后重跑）。
WARN 项必须逐条写入 交付清单.md 第三节说明，未说明不得宣称门控通过。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def p(msg: str) -> None:
    print(msg, flush=True)


_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


def _is_sep_line(line: str) -> bool:
    """是否为合法表格分隔行（含 |，仅由 - : 空格 | 组成，且含至少一个 -）。"""
    s = line.strip()
    if not s or "|" not in s:
        return False
    if not _SEP_RE.match(s):
        return False
    return "-" in s


def _split_cells(line: str) -> list[str]:
    """按 | 拆列，跳过反斜杠转义的管道符（GFM 合法转义）。"""
    parts, buf, esc = [], [], False
    for ch in line.strip().strip("|"):
        if ch == "\\" and not esc:
            esc = True
            continue
        if ch == "|" and not esc:
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
        esc = False
    if buf:
        parts.append("".join(buf).strip())
    return parts


def _is_block_start(line: str) -> bool:
    """是否为块级元素起始行（标题/列表/引用/代码围栏/分隔线/HTML），
    用于判断表格与上下文粘连是否影响渲染。"""
    s = line.strip()
    if not s:
        return True
    if re.match(r"^#{1,6}\s", s):
        return True
    if re.match(r"^([-*+]|\d+\.)\s", s):
        return True
    if s.startswith(">"):
        return True
    if s.startswith("```") or s.startswith("~~~"):
        return True
    if re.match(r"^(-{3,}|\*{3,}|_{3,})\s*$", s):
        return True
    if s.startswith("<"):
        return True
    return False


def check_tables(lines: list[str]) -> list[str]:
    """表格格式检查（F4/F12-F16，2026-08-18 固化）：逐块解析连续 | 行，
    校验分隔行存在且格式合法、全表列数一致、首尾 | 闭合、前后空行、
    单列表格，杜绝「口径注混入表格行 / 分隔线错位 / 表格与正文粘连」。
    """
    issues: list[str] = []
    n = len(lines)
    i = 0
    while i < n:
        if not lines[i].strip().startswith("|"):
            i += 1
            continue
        # 收集连续表格块
        block: list[tuple[int, str]] = []
        j = i
        while j < n and lines[j].strip().startswith("|"):
            block.append((j + 1, lines[j]))
            j += 1
        first_ln, first = block[0]
        if _is_sep_line(first):
            issues.append(f"F12 L{first_ln}: 表格首行即分隔行（缺表头，分隔线错位）")
        # 表头与分隔行
        if len(block) >= 2 and _is_sep_line(block[1][1]):
            header_cells = _split_cells(first)
            sep_ln, sep = block[1]
            sep_cells = _split_cells(sep)
            if len(header_cells) != len(sep_cells):
                issues.append(f"F4 L{first_ln}: 表头 {len(header_cells)} 列 vs 分隔行 {len(sep_cells)} 列")
            if len(header_cells) <= 1:
                issues.append(f"F15 L{first_ln}: 表格仅 {len(header_cells)} 列（疑似漏 | 分隔）")
            for (dln, dline) in block[2:]:
                if _is_sep_line(dline):
                    issues.append(f"F12 L{dln}: 表格块内出现多余分隔行（表头重复/数据区含分隔线）")
                    continue
                dcells = _split_cells(dline)
                if len(dcells) != len(header_cells):
                    issues.append(f"F4 L{dln}: 数据行 {len(dcells)} 列 vs 表头 {len(header_cells)} 列（检查是否混入口径注/漏 |）")
                if not dline.strip().endswith("|"):
                    issues.append(f"F14 L{dln}: 表格行缺少结尾 |（首尾未闭合）")
        else:
            # 无合法分隔行
            if len(block) >= 2:
                issues.append(f"F12 L{first_ln}: 表格分隔行缺失/格式错误（表头后第 {len(block)-1} 行非合法分隔行，如 {block[1][1].strip()[:40]!r}）")
            else:
                issues.append(f"F12 L{first_ln}: 表格仅一行且无分隔行（可能不是表格或格式错误）")
        # 表格后空行/粘连
        if j < n:
            nxt = lines[j]
            if nxt.strip() and not _is_block_start(nxt):
                issues.append(f"F13 L{j+1}: 表格后未空行，与正文粘连（该行会被并入表格）: {nxt.strip()[:40]!r}")
        # 表格前空行
        if i > 0:
            prev = lines[i - 1]
            if prev.strip() and not _is_block_start(prev):
                issues.append(f"F16 L{i}: 表格前未空行（建议与上文空行分隔）")
        i = j
    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description="Markdown 报告格式质量门")
    ap.add_argument("--dir", required=True, help="批次目录（含 reports/）")
    ap.add_argument("--report", default="", help="报告相对路径，如 reports/药明康德_603259_分析报告.md")
    ap.add_argument("--strict-warn", action="store_true", help="WARN 也按 FAIL 处理（严格模式）")
    args = ap.parse_args()

    root = Path(args.dir)
    reports_dir = root / "reports"
    if args.report and Path(args.report).is_absolute():
        reports_dir = Path(args.report).parent
    if not reports_dir.exists():
        p(f"[FAIL] 目录下无 reports/：{root}")
        return 1
    if args.report:
        rp = Path(args.report)
        md = rp if rp.is_absolute() else root / args.report
        targets = [md]
    else:
        targets = sorted(reports_dir.glob("*.md"))
    targets = [t for t in targets if t.exists()]
    if not targets:
        p("[FAIL] 未找到任何 .md 报告（--report 可指定）")
        return 1

    total_fail, total_warn = 0, 0
    for md in targets:
        raw = md.read_bytes()
        # F11 BOM
        if raw.startswith(b"\xef\xbb\xbf"):
            p(f"  [WARN] F11 {md.name}: 文件以 UTF-8 BOM 开头")
            total_warn += 1
        text = raw.decode("utf-8-sig", errors="replace")
        if "\r\n" in text and "\n" in text and "\r\n" not in text.replace("\r\n", ""):
            # 同时存在 CRLF 与裸 LF
            has_lf_only = "\n" in text.replace("\r\n", "")
            if has_lf_only:
                p(f"  [WARN] F10 {md.name}: CRLF 与 LF 混用")
                total_warn += 1
        lines = text.splitlines()
        fails, warns = [], []

        # F1/F2/F3 分隔线与标题
        for i, ln in enumerate(lines):
            if re.match(r"^-{3,}\s*#", ln) or re.match(r"^\*{3,}\s*#", ln) or re.match(r"^_{3,}\s*#", ln):
                fails.append(f"F1 L{i+1}: 分隔线与标题同行粘连: {ln.strip()[:50]}")
            if re.match(r"^-{3,}\s*$", ln) and i + 1 < len(lines) and re.match(r"^#{1,6}\s", lines[i + 1]):
                fails.append(f"F2 L{i+1}: 分隔线后无空行紧跟标题: {lines[i+1].strip()[:50]}")
            if re.match(r"^#{1,6}\s", ln) and i + 1 < len(lines) and re.match(r"^-{3,}\s*$", lines[i + 1]):
                fails.append(f"F3 L{i+1}: 标题后紧接分隔线（setext 歧义）: {ln.strip()[:50]}")

        # F5 连续空行 / F6 行尾空白
        for i, ln in enumerate(lines):
            if ln.strip() == "" and i + 2 < len(lines) and lines[i + 1].strip() == "" and lines[i + 2].strip() == "":
                warns.append(f"F5 L{i+1}: 连续 3+ 空行（建议折叠为 1 个空行）")
            if re.search(r"[ \t]+$", ln) and ln.strip() != "":
                warns.append(f"F6 L{i+1}: 行尾空白")

        # F4/F12-F16 表格（2026-08-18 全面固化）
        fails.extend(check_tables(lines))

        # F7 标记闭合
        b = len(re.findall(r"\*\*", text))
        if b % 2 != 0:
            warns.append(f"F7: 粗体标记 ** 数量为奇数（{b}）")
        i1 = len(re.findall(r"(?<!\*)\*(?!\*)", text))
        if i1 % 2 != 0:
            warns.append(f"F7: 斜体标记 * 数量为奇数（{i1}）")

        # F8/F9 图片
        cnt: dict[str, int] = {}
        for alt, rel in re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", text):
            rel2 = rel.replace("/", "\\")
            pp = (md.parent / rel2) if not rel2.startswith(("reports", "图表")) else (reports_dir / rel2.removeprefix("reports\\"))
            # 统一相对 reports/ 解析
            if rel2.startswith("图表\\"):
                pp = reports_dir / rel2
            if not pp.exists():
                fails.append(f"F8: 图片文件不存在: {rel}")
            cnt[rel] = cnt.get(rel, 0) + 1
        for rel, n in cnt.items():
            if n > 1:
                fails.append(f"F9: 图片重复引用 {n} 次: {rel}")

        for s in fails:
            p(f"  [FAIL] {s}")
        for s in warns:
            p(f"  [WARN] {s}")
        p(f"== {md.name}: FAIL {len(fails)} ｜ WARN {len(warns)} ==")
        total_fail += len(fails)
        total_warn += len(warns)

    if total_fail:
        p(f"❌ 格式门未通过：{total_fail} 项 FAIL（修复后重跑）")
        return 1
    p(f"✅ 格式门通过：FAIL 0 ｜ WARN {total_warn}（WARN 需在交付清单说明）")
    return 0


if __name__ == "__main__":
    sys.exit(main())