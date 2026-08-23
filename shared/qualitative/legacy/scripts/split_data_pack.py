#!/usr/bin/env python3
"""Split data_pack_market.md into dimension-specific subsets for agent team.

Usage:
    python3 scripts/split_data_pack.py \
        --input output/002078_太阳纸业/data_pack_market.md \
        --output-dir output/002078_太阳纸业/data_splits/

Outputs:
    d1d2_business_moat.md  — §1, §2, §3, §4, §5, §8, §9, §12, §17 (business model + moat)
    d3d4d5_env_mgmt_mda.md — §1, §3(header only), §7, §8, §10, §12, §14, §15, §16, §13 (env + mgmt + MD&A)
    d6_holding.md          — §1, §9, §4P (holding structure, conditional)
    d6_trigger.json        — {"triggered": true/false, "reason": "..."}
"""

import argparse
import json
import re
import sys
from pathlib import Path


def parse_sections(md_text: str) -> dict[str, str]:
    """Split markdown into sections keyed by section header."""
    sections = {}
    current_key = "_preamble"
    current_lines = []

    for line in md_text.splitlines(keepends=True):
        m = re.match(r"^## (.+?)$", line)
        if m:
            # Save previous section
            sections[current_key] = "".join(current_lines)
            current_key = m.group(1).strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    sections[current_key] = "".join(current_lines)
    return sections


def find_section(sections: dict, prefix: str) -> str:
    """Find a section by prefix match (e.g., '1.' matches '1. 基本信息')."""
    for key, val in sections.items():
        if key.startswith(prefix):
            return val
    return ""


def build_subset(sections: dict, prefixes: list[str], title: str) -> str:
    """Build a markdown subset from selected sections."""
    parts = [f"# 数据子集 — {title}\n\n"]
    for prefix in prefixes:
        content = find_section(sections, prefix)
        if content:
            parts.append(content)
            parts.append("\n")
    return "".join(parts)


def check_d6_trigger(sections: dict) -> dict:
    """Check if D6 holding structure analysis should be triggered."""
    s1 = find_section(sections, "1.")
    s9 = find_section(sections, "9.")
    s4p = find_section(sections, "4P.")

    reasons = []

    # Check if company describes itself as investment holding
    if any(kw in s1 for kw in ["投资控股", "控股公司", "多元化集团"]):
        reasons.append("公司描述含'投资控股/控股公司/多元化集团'")

    # Check if parent company has large long-term equity investments
    ltei_match = re.search(r"长期股权投资\s*\|\s*([\d,.]+)", s4p)
    total_match = re.search(r"总资产\s*\|\s*([\d,.]+)", s4p)
    if ltei_match and total_match:
        ltei = float(ltei_match.group(1).replace(",", ""))
        total = float(total_match.group(1).replace(",", ""))
        if total > 0 and ltei / total > 0.5:
            reasons.append(f"母公司长期股权投资占总资产{ltei/total:.0%}")

    # Check for listed subsidiaries in §9
    if "上市子公司" in s9 or "§9B" in s9:
        reasons.append("§9中提及上市子公司")

    triggered = len(reasons) > 0
    return {
        "triggered": triggered,
        "reasons": reasons,
        "note": "D6控股结构分析触发" if triggered else "D6不适用（非控股结构）",
    }


def main():
    parser = argparse.ArgumentParser(description="Split data pack for agent team")
    parser.add_argument("--input", required=True, help="Path to data_pack_market.md")
    parser.add_argument("--output-dir", required=True, help="Output directory for splits")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)

    if not input_path.exists():
        print(f"Error: {input_path} not found", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    md_text = input_path.read_text(encoding="utf-8")
    sections = parse_sections(md_text)

    # --- Agent A: D1 (business model) + D2 (moat) ---
    d1d2 = build_subset(sections, [
        "1.", "2.", "3.", "3P.", "4.", "5.",  # financials
        "8.", "9.",                            # industry + segments
        "12.", "17.",                          # indicators + derived
    ], "D1商业模式 + D2护城河")
    (output_dir / "d1d2_business_moat.md").write_text(d1d2, encoding="utf-8")

    # --- Agent B: D3 (environment) + D4 (management) + D5 (MD&A) ---
    d3d4d5 = build_subset(sections, [
        "1.",                                 # basic info (needed for context)
        "3.",                                 # P&L (for cyclicality check)
        "7.", "8.", "10.",                    # governance, industry, MD&A
        "12.", "14.", "15.", "16.",           # indicators, rf rate, buyback, pledge
        "6.",                                 # dividends (for mgmt capital allocation)
        "13.",                                # warnings
    ], "D3外部环境 + D4管理层 + D5 MD&A")
    (output_dir / "d3d4d5_env_mgmt_mda.md").write_text(d3d4d5, encoding="utf-8")

    # --- D6 trigger check ---
    trigger = check_d6_trigger(sections)
    (output_dir / "d6_trigger.json").write_text(
        json.dumps(trigger, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- Agent C: D6 (holding structure, only if triggered) ---
    if trigger["triggered"]:
        d6 = build_subset(sections, [
            "1.", "9.", "4P.", "4.",
        ], "D6控股结构")
        (output_dir / "d6_holding.md").write_text(d6, encoding="utf-8")

    # --- Print summary ---
    d1d2_size = len(d1d2)
    d3d4d5_size = len(d3d4d5)
    total_size = len(md_text)
    print(f"Data pack split complete: {input_path}")
    print(f"  Total: {total_size:,} chars")
    print(f"  Agent A (D1+D2): {d1d2_size:,} chars ({d1d2_size/total_size:.0%})")
    print(f"  Agent B (D3+D4+D5): {d3d4d5_size:,} chars ({d3d4d5_size/total_size:.0%})")
    print(f"  D6 triggered: {trigger['triggered']}")
    if trigger["reasons"]:
        for r in trigger["reasons"]:
            print(f"    - {r}")


if __name__ == "__main__":
    main()
