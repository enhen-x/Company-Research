#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render a report Markdown file to a self-contained, Markdown-like HTML file.

This renderer is intentionally separate from report_to_html.py, which serves the
legacy qualitative-report dashboard. Main research reports are rendered with
Pandoc/GFM so headings, tables, lists, blockquotes, and relative report images
keep the same reading order as the source Markdown.

Usage:
    python scripts/md_to_html.py \
      --input reports/新和成_002001_分析报告.md \
      --output reports/新和成_002001_分析报告.html
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path


CSS = r"""
:root { color-scheme: light; }
html { background: #fff; }
body {
  max-width: 980px;
  margin: 0 auto;
  padding: 42px 54px 72px;
  color: #172033;
  background: #fff;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
  font-size: 15px;
  line-height: 1.72;
  overflow-wrap: break-word;
}
h1 { font-size: 30px; margin: 0 0 18px; color: #10203a; }
h2 { font-size: 22px; margin: 42px 0 14px; padding-bottom: 7px; border-bottom: 1px solid #dfe5ec; color: #12233e; }
h3 { font-size: 18px; margin: 28px 0 10px; color: #1b2b43; }
h4 { font-size: 16px; margin: 22px 0 8px; color: #24364f; }
p, ul, ol, blockquote, table, figure { margin: 12px 0; }
blockquote { padding: 9px 16px; border-left: 4px solid #9db7d7; background: #f3f6fa; color: #40536b; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { border: 1px solid #d9e0e8; padding: 8px 10px; vertical-align: top; }
th { background: #f1f4f7; color: #1b2b43; font-weight: 650; }
tr:nth-child(even) td { background: #fbfcfd; }
img { display: block; max-width: 100%; height: auto; margin: 18px auto; }
code { padding: 1px 4px; border-radius: 3px; background: #f1f3f5; color: #9b3d2f; }
pre { padding: 14px; overflow-x: auto; background: #f4f6f8; border: 1px solid #e0e5eb; }
a { color: #1c5b99; }
hr { border: 0; border-top: 1px solid #dfe5ec; margin: 28px 0; }
@media (max-width: 760px) {
  body { padding: 24px 18px 48px; font-size: 14px; }
  h1 { font-size: 25px; }
  h2 { font-size: 20px; }
  table { display: block; overflow-x: auto; white-space: normal; }
}
"""


def _pandoc_path() -> str:
    path = shutil.which("pandoc")
    if path:
        return path
    raise RuntimeError(
        "未找到 pandoc。请安装 Pandoc 3.x，并确保 pandoc 在 PATH 中。"
    )


class _Structure(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.headings: dict[str, list[str]] = {f"h{level}": [] for level in range(1, 5)}
        self.tables = 0
        self.images = 0
        self._heading: str | None = None
        self._heading_text: list[str] = []
        self._skip_heading = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.headings:
            self._heading = tag
            self._heading_text = []
            attributes = dict(attrs)
            self._skip_heading = (attributes.get("id") == "title-block-header"
                                  or "title" in (attributes.get("class") or "").split())
        elif tag == "table":
            self.tables += 1
        elif tag == "img":
            self.images += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == self._heading:
            if not self._skip_heading:
                self.headings[tag].append("".join(self._heading_text).strip())
            self._heading = None
            self._heading_text = []

    def handle_data(self, data: str) -> None:
        if self._heading:
            self._heading_text.append(data)


def _inline_text(nodes: list[dict]) -> str:
    parts = []
    for node in nodes:
        kind, content = node.get("t"), node.get("c")
        if kind in ("Str", "Code", "Math"):
            parts.append(content if kind == "Str" else content[-1])
        elif kind in ("Space", "SoftBreak", "LineBreak"):
            parts.append(" ")
        elif kind in ("Emph", "Strong", "Strikeout", "Superscript", "Subscript", "SmallCaps"):
            parts.append(_inline_text(content))
        elif kind in ("Link", "Image"):
            parts.append(_inline_text(content[1]))
        elif kind == "Span":
            parts.append(_inline_text(content[1]))
        elif kind == "Quoted":
            parts.append(_inline_text(content[1]))
    return "".join(parts).strip()


def _source_structure(ast: dict) -> tuple[dict[str, list[str]], int, int]:
    headings = {f"h{level}": [] for level in range(1, 5)}
    tables = images = 0

    def walk(value: object) -> None:
        nonlocal tables, images
        if isinstance(value, dict):
            kind, content = value.get("t"), value.get("c")
            if kind == "Header" and 1 <= content[0] <= 4:
                headings[f"h{content[0]}"].append(_inline_text(content[2]))
            elif kind == "Table":
                tables += 1
            elif kind == "Image":
                images += 1
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(ast.get("blocks", []))
    return headings, tables, images


def _validate(ast: dict, output: str) -> list[str]:
    failures: list[str] = []
    structure = _Structure()
    structure.feed(output)
    headings, source_tables, image_refs = _source_structure(ast)
    for level in range(1, 5):
        expected = headings[f"h{level}"]
        actual = structure.headings[f"h{level}"]
        normalized_expected = [" ".join(item.split()) for item in expected]
        normalized_actual = [" ".join(item.split()) for item in actual]
        if normalized_expected != normalized_actual:
            mismatch = next(((a, b) for a, b in zip(normalized_expected, normalized_actual) if a != b), None)
            failures.append(f"{level}级标题不一致：Markdown={len(expected)}，HTML={len(actual)}，首处={mismatch}")

    embedded_images = len(re.findall(r"data:image/[^;]+;base64,", output, flags=re.I))
    if structure.images != image_refs or embedded_images != image_refs:
        failures.append(f"图片未全部内嵌：Markdown={image_refs}，HTML={embedded_images}")
    if source_tables != structure.tables:
        failures.append(f"表格数量不一致：Markdown={source_tables}，HTML={structure.tables}")
    if not output.lstrip().lower().startswith("<!doctype html>"):
        failures.append("HTML 缺少标准 DOCTYPE")
    return failures


def render(input_path: Path, output_path: Path, check: bool = False) -> None:
    pandoc = _pandoc_path()
    input_path = input_path.resolve()
    output_path = output_path.resolve()
    markdown = input_path.read_text(encoding="utf-8-sig")
    from chart_numbers import report_amount_unit_violations
    unit_errors = report_amount_unit_violations(markdown)
    if unit_errors:
        raise RuntimeError(f'报告金额/股数必须换算为亿/万，发现旧单位：{unit_errors[:8]}')
    title_match = re.search(r"^#\s+(.+?)\s*$", markdown, flags=re.M)
    title = title_match.group(1).strip() if title_match else "证券分析报告"
    cmd = [
        pandoc,
        input_path.name,
        "--from=gfm",
        "--standalone",
        "--embed-resources",
        "--resource-path=.",
        "--metadata",
        f"title={title}",
    ]
    completed = subprocess.run(cmd, cwd=input_path.parent, text=True,
                               encoding="utf-8", capture_output=True)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "pandoc 渲染失败")
    if "Could not fetch resource" in completed.stderr:
        raise RuntimeError(completed.stderr.strip())

    rendered = completed.stdout
    if "</style>" in rendered:
        rendered = rendered.replace("</style>", f"{CSS}\n</style>", 1)
    else:
        rendered = rendered.replace("</head>", f"<style>{CSS}</style></head>", 1)

    parsed = subprocess.run([pandoc, input_path.name, "--from=gfm", "--to=json"],
                            cwd=input_path.parent, text=True, encoding="utf-8", capture_output=True)
    if parsed.returncode:
        raise RuntimeError(parsed.stderr.strip() or "pandoc 结构解析失败")
    failures = _validate(json.loads(parsed.stdout), rendered)
    if failures:
        raise RuntimeError("；".join(failures))
    if check:
        if not output_path.is_file() or output_path.read_text(encoding="utf-8") != rendered:
            raise RuntimeError("主报告 HTML 与当前 Markdown 不一致；请运行完整 gate_all.py 重新成稿")
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Markdown主报告 → 自包含HTML")
    parser.add_argument("--input", required=True, help="Markdown报告路径")
    parser.add_argument("--output", help="HTML输出路径；默认与输入同名")
    parser.add_argument("--check", action="store_true", help="只核对现有HTML是否与当前Markdown完全一致，不写入")
    args = parser.parse_args(argv)
    input_path = Path(args.input)
    if not input_path.is_file():
        parser.error(f"输入文件不存在：{input_path}")
    output_path = Path(args.output) if args.output else input_path.with_suffix(".html")
    try:
        render(input_path, output_path, check=args.check)
    except (OSError, RuntimeError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    print(f"[OK] HTML{'一致性已核对' if args.check else '已生成'}：{output_path}")
    print(f"[OK] 图片已内嵌，章节与Markdown结构已校验")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
