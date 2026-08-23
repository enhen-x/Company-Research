"""report_consistency.py — 杠杆6: cross-passage numeric consistency audit.

Scans a finished qualitative report (markdown) for the same metric being
written with different values in different passages (e.g. 毛利率 47.6% 前文 /
49.2% 后文) — the "叙述内部矛盾" class that quality_control.py (算式正确) does
not cover. Optionally (``--gates``) enforces deterministic hard gates (杠杆7):
per-dimension 字数下限 + presence of required sections.

Method (see plan §4.2):
  1. mask spans that must be skipped ([src:...] / §N / P.X / 8-digit dates)
  2. extract numbers carrying a money/percent unit only
  3. classify to one of ~14 metric categories by keyword in a ±30 char window
  4. normalize money→亿元 / ratio→% ; require a year in the window to cluster
  5. cluster by (category, year); flag clusters spanning > tolerance

Exit codes: 0 no conflicts (& gates pass) · 1 conflicts / gate failures · 2 file error.
The exit-1 conflict list is **advisory** — a downstream numeric_audit agent
adjudicates 真错误 vs 口径差异.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

WINDOW = 30

# (canonical, keywords, kind) — order matters: most-specific first.
CATEGORIES: List[Tuple[str, Tuple[str, ...], str]] = [
    ("扣非净利润", ("扣非净利润", "扣非归母", "扣非"), "money"),
    ("归母净利润", ("归母净利润", "归母"), "money"),
    ("营业利润", ("营业利润",), "money"),
    ("净利润", ("净利润",), "money"),
    ("营业收入", ("营业收入", "营收", "销售收入"), "money"),
    ("营业成本", ("营业成本",), "money"),
    ("总市值", ("总市值", "市值"), "money"),
    ("分红总额", ("总分红", "分红总额", "现金分红总额"), "money"),
    ("毛利率", ("毛利率",), "ratio"),
    ("净利率", ("净利率",), "ratio"),
    ("ROE", ("ROE", "净资产收益率", "加权roe"), "ratio"),
    ("资产负债率", ("资产负债率",), "ratio"),
    ("股息率", ("股息率",), "ratio"),
    ("分红率", ("分红支付率", "分红率", "支付率", "派息率"), "ratio"),
]

MONEY_UNITS = {"亿元": 1.0, "亿": 1.0, "百万元": 0.01, "百万": 0.01}
NUM_UNIT_RE = re.compile(
    r"(-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)\s*(亿元|亿|百万元|百万|%|％)"
)
YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_MASK_PATTERNS = [
    re.compile(r"\[src:[^\]]*\]"),
    re.compile(r"§\s*\d+(?:\.\d+)?"),
    re.compile(r"[Pp]\.?\s*\d+"),
    re.compile(r"\d{8}"),
    re.compile(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"),
]


# ─────────────────────────── extraction ───────────────────────────────

def _mask(text: str) -> str:
    """Blank out skip-spans, preserving character offsets."""
    out = list(text)
    for pat in _MASK_PATTERNS:
        for m in pat.finditer(text):
            for i in range(m.start(), m.end()):
                out[i] = " "
    return "".join(out)


def _classify(window: str, num_offset: int) -> Optional[Tuple[str, str]]:
    """Pick the category whose keyword occurrence is *nearest* to the number.

    Nearest-keyword (not list-order) avoids cross-contaminating adjacent
    metrics in the same sentence (e.g. 营业利润 122.51 亿, 归母 89.54 亿)."""
    low = window.lower()
    best = None  # (distance, canon, kind)
    for canon, kws, kind in CATEGORIES:
        for kw in kws:
            hay = low if kw.islower() else window
            start = 0
            while True:
                idx = hay.find(kw, start)
                if idx < 0:
                    break
                dist = abs(idx - num_offset)
                if best is None or dist < best[0]:
                    best = (dist, canon, kind)
                start = idx + 1
    if best is None:
        return None
    return best[1], best[2]


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


class Obs:
    __slots__ = ("value", "line", "snippet")

    def __init__(self, value: float, line: int, snippet: str):
        self.value = value
        self.line = line
        self.snippet = snippet


def extract(text: str) -> Dict[Tuple[str, str], List[Obs]]:
    """Return {(category, year): [Obs, ...]} of normalized values."""
    masked = _mask(text)
    clusters: Dict[Tuple[str, str], List[Obs]] = {}
    for m in NUM_UNIT_RE.finditer(masked):
        raw, unit = m.group(1), m.group(2)
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        w0, w1 = max(0, m.start() - WINDOW), min(len(masked), m.end() + WINDOW)
        window = masked[w0:w1]
        cls = _classify(window, m.start() - w0)
        if cls is None:
            continue
        canon, kind = cls
        if kind == "money":
            if unit not in MONEY_UNITS:
                continue
            norm = value * MONEY_UNITS[unit]
        else:  # ratio
            if unit not in ("%", "％"):
                continue
            norm = value
        ym = YEAR_RE.search(window)
        if not ym:
            continue  # no year in window → cannot cluster reliably (plan §4.2)
        year = ym.group(1)
        snippet = re.sub(r"\s+", " ", text[w0:w1]).strip()
        clusters.setdefault((canon, year), []).append(
            Obs(norm, _line_of(text, m.start()), snippet))
    return clusters


def _distinct_groups(values: List[float], tol: float) -> List[float]:
    """Greedy grouping: representatives that pairwise differ by > tol."""
    reps: List[float] = []
    for v in sorted(values):
        if not any(abs(v - r) / max(abs(v), abs(r), 1e-9) <= tol for r in reps):
            reps.append(v)
    return reps


def find_conflicts(clusters, tol: float) -> List[dict]:
    conflicts = []
    for (canon, year), obs in clusters.items():
        vals = [o.value for o in obs]
        reps = _distinct_groups(vals, tol)
        if len(reps) < 2:
            continue
        rng = max(vals) - min(vals)
        spread = rng / max(abs(max(vals)), abs(min(vals)), 1e-9)
        conflicts.append({
            "category": canon, "year": year, "spread": spread,
            "values": sorted(set(round(v, 4) for v in vals)),
            "locations": sorted({o.line for o in obs}),
            "obs": obs,
        })
    conflicts.sort(key=lambda c: (-c["spread"], c["category"]))
    return conflicts


# ─────────────────────────── hard gates (杠杆7) ────────────────────────

DIMENSION_MINS = [("维度一", 600), ("维度二", 800), ("维度六", 300)]
REQUIRED_SECTIONS = ["## 数字溯源汇总", "## 结构化参数"]
_DEGRADE_MARKERS = ("不适用", "未触发", "不属于控股结构", "不涉及控股")


def _section_body(text: str, name: str) -> Optional[str]:
    m = re.search(r"^##\s*[^\n]*" + re.escape(name) + r"[^\n]*$", text, re.M)
    if not m:
        return None
    start = m.end()
    nxt = re.search(r"^##\s", text[start:], re.M)
    return text[start:start + nxt.start()] if nxt else text[start:]


def _cjk_count(s: str) -> int:
    return sum(1 for ch in s if "一" <= ch <= "鿿")


def check_gates(text: str) -> List[str]:
    failures = []
    for name, minimum in DIMENSION_MINS:
        body = _section_body(text, name)
        if body is None:
            if name == "维度六":  # conditional — absence is allowed
                continue
            failures.append(f"缺少章节「{name}」")
            continue
        if name == "维度六" and any(mk in body for mk in _DEGRADE_MARKERS):
            continue  # not triggered
        n = _cjk_count(body)
        if n < minimum:
            failures.append(f"「{name}」正文 {n} 字 < 门槛 {minimum} 字")
    for header in REQUIRED_SECTIONS:
        if header not in text:
            failures.append(f"缺少必备章节标题「{header}」")
    return failures


# ─────────────────────────── report render ────────────────────────────

def render(conflicts: List[dict], gate_failures: Optional[List[str]], tol: float) -> str:
    out = ["# 一致性审计 — consistency_report.md\n",
           f"> 容差 {tol:.0%}；本表为 **advisory**，真错误 vs 口径差异由 numeric_audit 裁定。\n"]
    out.append("## 跨段数值冲突\n")
    if not conflicts:
        out.append("✅ 未发现跨段数值冲突。\n")
    else:
        out.append(f"发现 **{len(conflicts)}** 处潜在冲突：\n")
        out.append("| 指标 | 年份 | 冲突数值 | 相对差 | 出现行号 |")
        out.append("| --- | --- | --- | ---: | --- |")
        for c in conflicts:
            vals = " / ".join(f"{v:g}" for v in c["values"])
            locs = ", ".join(str(l) for l in c["locations"])
            out.append(f"| {c['category']} | {c['year']} | {vals} | {c['spread']:.1%} | {locs} |")
        out.append("")
    if gate_failures is not None:
        out.append("## 硬门槛检查（--gates）\n")
        if not gate_failures:
            out.append("✅ 全部硬门槛通过。\n")
        else:
            out.append(f"❌ **{len(gate_failures)}** 项门槛未达标：\n")
            for f in gate_failures:
                out.append(f"- {f}")
            out.append("")
    out.append("---\n*consistency_report.md · 由 scripts/report_consistency.py 生成 · 内部工件（非交付物）*")
    return "\n".join(out) + "\n"


# ─────────────────────────────── CLI ──────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="定性报告跨段一致性 + 硬门槛审计")
    ap.add_argument("--report", required=True, help="qualitative_report.md 路径")
    ap.add_argument("--output", help="consistency_report.md 输出路径（可选）")
    ap.add_argument("--tolerance", type=float, default=0.05, help="同类判定容差（默认 0.05）")
    ap.add_argument("--gates", action="store_true", help="附加执行硬门槛检查（杠杆7）")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.report):
        sys.stderr.write(f"[report_consistency] 文件不存在: {args.report}\n")
        return 2
    with open(args.report, "r", encoding="utf-8") as f:
        text = f.read()
    if not text.strip():
        sys.stderr.write("[report_consistency] 报告为空。\n")
        return 2

    conflicts = find_conflicts(extract(text), args.tolerance)
    gate_failures = check_gates(text) if args.gates else None

    report = render(conflicts, gate_failures, args.tolerance)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
    else:
        sys.stdout.write(report)

    n_gate = len(gate_failures) if gate_failures else 0
    sys.stderr.write(
        f"[report_consistency] 冲突 {len(conflicts)} 处 · 门槛失败 {n_gate} 项\n")
    return 1 if (conflicts or n_gate) else 0


if __name__ == "__main__":
    sys.exit(main())
