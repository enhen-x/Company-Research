#!/usr/bin/env python3
"""Turtle Investment Framework - PDF Preprocessor (Phase 2A).

Scans annual report PDFs for 7 target sections using keyword matching
and outputs structured JSON for Agent fine-extraction.

Target sections:
    P2: Restricted cash (受限资产)
    P3: AR aging (应收账款账龄)
    P4: Related party transactions (关联方交易)
    P6: Contingent liabilities (或有负债)
    P13: Non-recurring items (非经常性损益)
    MDA: Management Discussion & Analysis (管理层讨论与分析)
    SUB: Subsidiary holdings (主要控股参股公司)

Usage:
    python3 scripts/pdf_preprocessor.py --pdf report.pdf
    python3 scripts/pdf_preprocessor.py --pdf report.pdf --output output/sections.json
    python3 scripts/pdf_preprocessor.py --pdf report.pdf --verbose --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pdfplumber


# ---------------------------------------------------------------------------
# Feature #38: SECTION_KEYWORDS for 5 target sections
# Feature #43: Traditional Chinese keyword support
# ---------------------------------------------------------------------------

SECTION_KEYWORDS: Dict[str, List[str]] = {
    "P2": [
        # Simplified Chinese
        "所有权或使用权受限资产",
        "受限资产",
        "使用受限的资产",
        "所有权受限",
        "使用权受到限制",
        "受限的货币资金",
        "受到限制的资产",
        # Traditional Chinese (HK reports)
        "所有權或使用權受限資產",
        "受限資產",
        "使用受限的資產",
    ],
    "P3": [
        # Simplified Chinese
        "应收账款账龄",
        "应收账款的账龄",
        "账龄分析",
        "应收账款按账龄披露",
        "应收账款按账龄列示",
        "应收款项账龄",
        # Traditional Chinese
        "應收賬款賬齡",
        "應收賬款的賬齡",
        "賬齡分析",
    ],
    "P4": [
        # Simplified Chinese
        "关联方交易",
        "关联交易",
        "关联方及关联交易",
        "关联方关系及其交易",
        "重大关联交易",
        # Traditional Chinese
        "關聯方交易",
        "關聯交易",
        "關聯方及關聯交易",
    ],
    "P6": [
        # Simplified Chinese
        "或有负债",
        "或有事项",
        "未决诉讼",
        "重大诉讼",
        "对外担保",
        "承诺及或有事项",
        "承诺和或有负债",
        # Traditional Chinese
        "或有負債",
        "或有事項",
        "未決訴訟",
        "承諾及或有事項",
    ],
    "P13": [
        # Simplified Chinese - specific (prefer these for supplement zone)
        "非经常性损益项目及金额",
        "非经常性损益合计",
        # Simplified Chinese - general
        "非经常性损益",
        "非经常性损益明细",
        "非经常性损益项目",
        "扣除非经常性损益",
        "非经常性损益的项目和金额",
        # Traditional Chinese
        "非經常性損益",
        "非經常性損益明細",
        "非經常性損益項目及金額",
    ],
    "MDA": [
        # Simplified Chinese
        "管理层讨论与分析",
        "经营情况讨论与分析",
        "经营情况的讨论与分析",
        "管理层分析与讨论",
        "董事会报告",
        # Traditional Chinese
        "管理層討論與分析",
        "經營情況討論與分析",
        "董事會報告",
    ],
    "SUB": [
        # 高特异性 — 主匹配
        "主要控股参股公司分析",
        "主要子公司及对公司净利润的影响",
        "主要控股参股公司情况",
        "控股子公司情况",
        # 中特异性
        "在子公司中的权益",
        "在其他主体中的权益",
        "纳入合并范围的主体",
        "合并范围的变化",
        # 删除: "长期股权投资" (歧义太大，匹配到 Note #17)
        # 新增: 更具体的变体
        "长期股权投资——对子公司",
        "长期股权投资——联营企业",
        # 繁体
        "主要控股參股公司分析",
        "在子公司中的權益",
        "在其他主體中的權益",
        "長期股權投資——對子公司",
    ],
}

# Per-section extraction parameters (overrides defaults)
SECTION_EXTRACT_CONFIG: Dict[str, Dict[str, int]] = {
    "MDA": {"buffer_pages": 3, "max_chars": 8000},
    "SUB": {"buffer_pages": 2, "max_chars": 6000},
}
DEFAULT_BUFFER_PAGES = 1
DEFAULT_MAX_CHARS = 4000

# ---------------------------------------------------------------------------
# Zone detection markers for A-share annual reports (CSRC format)
# ---------------------------------------------------------------------------

ZONE_MARKERS: List[Tuple[str, str]] = [
    (r"第[一二三四五六七八九十百]+节\s*重要提示", "INTRO_ZONE"),
    (r"第[一二三四五六七八九十百]+节\s*公司简介", "INTRO_ZONE"),
    (r"第[一二三四五六七八九十百]+节\s*管理层讨论与分析", "MDA_ZONE"),
    (r"第[一二三四五六七八九十百]+节\s*经营情况讨论与分析", "MDA_ZONE"),
    (r"第[一二三四五六七八九十百]+节\s*公司治理", "GOVERNANCE_ZONE"),
    (r"第[一二三四五六七八九十百]+节\s*财务报告", "FIN_ZONE"),
    (r"第[一二三四五六七八九十百]+节\s*会计数据", "FIN_ZONE"),
    # Sub-zones within financial report
    (r"[四五六]\s*[、.．]\s*重要会计政策", "POLICY_ZONE"),
    (r"七\s*[、.．]\s*合并财务报表项目注释", "NOTES_ZONE"),
    (r"[一二三四五六七八九十]+[、.．]\s*补充资料", "SUPPLEMENT_ZONE"),
]

SECTION_ZONE_PREFERENCES: Dict[str, Dict[str, List[str]]] = {
    "P2":  {"prefer": ["NOTES_ZONE"], "avoid": ["POLICY_ZONE"]},
    "P3":  {"prefer": ["NOTES_ZONE"], "avoid": ["POLICY_ZONE"]},
    "P4":  {"prefer": ["NOTES_ZONE"], "avoid": ["POLICY_ZONE"]},
    "P6":  {"prefer": ["NOTES_ZONE"], "avoid": ["POLICY_ZONE"]},
    "P13": {"prefer": ["SUPPLEMENT_ZONE", "NOTES_ZONE"], "avoid": ["POLICY_ZONE"]},
    "MDA": {"prefer": ["MDA_ZONE"], "avoid": ["NOTES_ZONE", "FIN_ZONE", "POLICY_ZONE", "SUPPLEMENT_ZONE"]},
    "SUB": {"prefer": ["NOTES_ZONE"], "avoid": ["POLICY_ZONE"]},
}


# ---------------------------------------------------------------------------
# Feature #37: PDF text extraction with pdfplumber
# Feature #44: PyMuPDF fallback for garbled text
# Feature #45: Table-aware extraction
# ---------------------------------------------------------------------------

def is_garbled(text: str, threshold: float = 0.30) -> bool:
    """Detect garbled text: >threshold fraction of non-CJK/ASCII/common-punct chars."""
    if not text:
        return True
    # Characters we consider "normal" in a Chinese annual report
    normal = 0
    for ch in text:
        cp = ord(ch)
        if (
            0x20 <= cp <= 0x7E  # ASCII printable
            or 0x4E00 <= cp <= 0x9FFF  # CJK Unified Ideographs
            or 0x3400 <= cp <= 0x4DBF  # CJK Extension A
            or 0x3000 <= cp <= 0x303F  # CJK Punctuation
            or 0xFF00 <= cp <= 0xFFEF  # Fullwidth Forms
            or ch in "\n\r\t"
        ):
            normal += 1
    ratio = normal / len(text)
    return ratio < (1 - threshold)


def _tables_to_markdown(tables: list) -> str:
    """Convert pdfplumber tables to markdown format."""
    parts = []
    for table in tables:
        if not table or len(table) < 2:
            continue
        # Clean cells
        cleaned = []
        for row in table:
            cleaned.append([
                (cell or "").replace("\n", " ").strip()
                for cell in row
            ])
        # Build markdown table
        header = cleaned[0]
        md = "| " + " | ".join(header) + " |\n"
        md += "| " + " | ".join(["---"] * len(header)) + " |\n"
        for row in cleaned[1:]:
            # Pad row if shorter than header
            while len(row) < len(header):
                row.append("")
            md += "| " + " | ".join(row[:len(header)]) + " |\n"
        parts.append(md)
    return "\n".join(parts)


def extract_all_pages(pdf_path: str, verbose: bool = False) -> List[Tuple[int, str]]:
    """Extract text from all pages of a PDF using pdfplumber.

    Falls back to PyMuPDF if pdfplumber produces garbled text.

    Args:
        pdf_path: Path to the PDF file.
        verbose: Print progress messages.

    Returns:
        List of (page_number_1indexed, text) tuples.

    Raises:
        FileNotFoundError: If the PDF file doesn't exist.
        RuntimeError: If the PDF cannot be opened or is encrypted.
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    pages_text: List[Tuple[int, str]] = []
    garbled_count = 0

    try:
        with pdfplumber.open(pdf_path) as pdf:
            total = len(pdf.pages)
            if verbose:
                print(f"Extracting {total} pages with pdfplumber...")

            for i, page in enumerate(pdf.pages):
                page_num = i + 1
                text = page.extract_text() or ""

                # Feature #45: table-aware extraction
                tables = page.extract_tables()
                if tables:
                    table_md = _tables_to_markdown(tables)
                    if table_md:
                        text = text + "\n\n[TABLE]\n" + table_md

                if is_garbled(text) and len(text) > 50:
                    garbled_count += 1

                pages_text.append((page_num, text))

                if verbose and page_num % 50 == 0:
                    print(f"  ...page {page_num}/{total}")

    except Exception as e:
        err_msg = str(e).lower()
        if "encrypt" in err_msg or "password" in err_msg:
            raise RuntimeError(f"PDF is encrypted: {pdf_path}") from e
        raise RuntimeError(f"Cannot open PDF: {pdf_path}: {e}") from e

    # Feature #44: PyMuPDF fallback if >30% pages are garbled
    if total > 0 and garbled_count / total > 0.30:
        if verbose:
            print(f"Garbled text detected ({garbled_count}/{total} pages), trying PyMuPDF...")
        fallback = fallback_extract_pymupdf(pdf_path, verbose=verbose)
        if fallback:
            return fallback

    return pages_text


def fallback_extract_pymupdf(pdf_path: str, verbose: bool = False) -> Optional[List[Tuple[int, str]]]:
    """Fallback extraction using PyMuPDF (fitz).

    Returns None if PyMuPDF is not installed.
    """
    try:
        import fitz
    except ImportError:
        if verbose:
            print("PyMuPDF not installed, skipping fallback.")
        return None

    pages_text: List[Tuple[int, str]] = []
    try:
        doc = fitz.open(pdf_path)
        total = len(doc)
        if verbose:
            print(f"Extracting {total} pages with PyMuPDF...")
        for i in range(total):
            page = doc[i]
            text = page.get_text() if hasattr(page, 'get_text') else page.getText()
            pages_text.append((i + 1, text or ""))
        doc.close()
    except Exception as e:
        if verbose:
            print(f"PyMuPDF fallback failed: {e}")
        return None

    return pages_text


# ---------------------------------------------------------------------------
# Zone detection for A-share annual report structure
# ---------------------------------------------------------------------------

def detect_zones(pages_text: List[Tuple[int, str]]) -> Dict[int, str]:
    """Detect report structure zones by scanning for section markers.

    Returns:
        Dict mapping page_number -> zone_name. Pages without a detected
        zone inherit from the most recent zone marker before them.
        Returns empty dict if no zone markers are found.
    """
    zone_transitions: List[Tuple[int, str]] = []

    for page_num, text in pages_text:
        if not text:
            continue
        for pattern, zone_name in ZONE_MARKERS:
            if re.search(pattern, text):
                zone_transitions.append((page_num, zone_name))
                break  # first matching marker per page

    if not zone_transitions:
        return {}

    # Build page->zone mapping (each page inherits from last marker)
    zone_transitions.sort(key=lambda x: x[0])
    page_zones: Dict[int, str] = {}
    current_zone = None
    transition_idx = 0

    for page_num, _ in pages_text:
        while transition_idx < len(zone_transitions) and zone_transitions[transition_idx][0] <= page_num:
            current_zone = zone_transitions[transition_idx][1]
            transition_idx += 1
        if current_zone:
            page_zones[page_num] = current_zone

    return page_zones


# ---------------------------------------------------------------------------
# Feature #39: Keyword matching to locate sections
# Feature #46: Section priority scoring
# ---------------------------------------------------------------------------

def _score_match(
    page_num: int, total_pages: int, text: str, keyword: str,
    zone: Optional[str] = None, section_id: Optional[str] = None,
) -> float:
    """Score a keyword match: prefer correct report zone over TOC.

    Scoring:
        +1.0 base for a match
        +2.0 if page is in a preferred zone for this section
        -2.0 if page is in an avoided zone for this section
        +0.5 fallback position bonus if no zone info available
        -0.5 if page looks like TOC (contains "目录" or "目 录")
        +0.3 if keyword appears in a heading-like context (numbered section)
        -0.3 if keyword only appears as a cross-reference ("详见")
    """
    score = 1.0

    # Zone-aware scoring (replaces position bonus when zone info available)
    if zone and section_id and section_id in SECTION_ZONE_PREFERENCES:
        prefs = SECTION_ZONE_PREFERENCES[section_id]
        if zone in prefs.get("prefer", []):
            score += 2.0
        elif zone in prefs.get("avoid", []):
            score -= 2.0
    elif total_pages > 0:
        # Fallback: position-based scoring when no zone info
        if page_num / total_pages > 0.30:
            score += 0.5

    # Penalize TOC pages
    if "目录" in text or "目 录" in text:
        score -= 0.5

    # Penalize cross-references ("详见注释七'31、所有权或使用权受限资产'")
    kw_pos = text.find(keyword)
    if kw_pos > 0:
        before = text[max(0, kw_pos - 30):kw_pos]
        if "详见" in before or "参见" in before or "参照" in before:
            score -= 0.3

    # SUB context scoring: penalize accounting detail, reward subsidiary operating data
    if section_id == "SUB" and kw_pos >= 0:
        context_window = text[max(0, kw_pos - 200):min(len(text), kw_pos + 200)]
        # Penalize: accounting detail context
        acct = ["权益法", "账面余额", "减值准备", "成本法", "账面价值"]
        if sum(1 for a in acct if a in context_window) >= 2:
            score -= 1.5
        # Reward: subsidiary operating data context
        subs = ["主营业务", "营业收入", "净利润", "注册资本", "持股比例"]
        if sum(1 for s in subs if s in context_window) >= 2:
            score += 1.0

    # P3 context scoring: penalize non-AR aging (prepayments, other payables)
    if section_id == "P3" and kw_pos >= 0:
        context_window = text[max(0, kw_pos - 200):min(len(text), kw_pos + 200)]
        non_ar = ["预付款项", "预付账款", "预付", "应付账款", "应付票据", "其他应付"]
        if any(term in context_window for term in non_ar):
            score -= 2.0

    # Bonus: keyword appears near a numbered heading pattern
    # e.g., "31、所有权或使用权受限资产" or "十四、关联方及关联交易"
    heading_patterns = [
        r"\d+[、.．]\s*" + re.escape(keyword),
        r"[一二三四五六七八九十]+[、.．]\s*" + re.escape(keyword),
    ]
    for pat in heading_patterns:
        if re.search(pat, text):
            score += 0.3
            break

    return score


def find_section_pages(
    pages_text: List[Tuple[int, str]],
    section_keywords: Dict[str, List[str]] = None,
) -> Dict[str, List[int]]:
    """Locate sections by scanning all pages for keywords.

    Args:
        pages_text: List of (page_number, text) tuples.
        section_keywords: Keyword dict (default: SECTION_KEYWORDS).

    Returns:
        Dict mapping section_id -> [page_numbers] sorted by priority score (best first).
    """
    if section_keywords is None:
        section_keywords = SECTION_KEYWORDS

    total_pages = len(pages_text)
    results: Dict[str, List[int]] = {}

    # Detect zones for scoring
    page_zones = detect_zones(pages_text)

    for section_id, keywords in section_keywords.items():
        # Collect (score, page_num) for all matches
        scored_matches: List[Tuple[float, int]] = []

        for page_num, text in pages_text:
            if not text:
                continue
            for kw in keywords:
                if kw in text:
                    zone = page_zones.get(page_num)
                    score = _score_match(page_num, total_pages, text, kw,
                                         zone=zone, section_id=section_id)
                    scored_matches.append((score, page_num))
                    break  # one keyword per page is enough

        # Sort by score descending, then by page number ascending as tiebreak
        scored_matches.sort(key=lambda x: (-x[0], x[1]))

        # Deduplicate page numbers while preserving order
        seen = set()
        ordered_pages = []
        for _, pn in scored_matches:
            if pn not in seen:
                seen.add(pn)
                ordered_pages.append(pn)

        results[section_id] = ordered_pages

    return results


# ---------------------------------------------------------------------------
# Feature #40: Context extraction with page buffer
# ---------------------------------------------------------------------------

def extract_section_context(
    pages_text: List[Tuple[int, str]],
    section_pages: Dict[str, List[int]],
    section_keywords: Dict[str, List[str]] = None,
    buffer_pages: int = 1,
    max_chars: int = 4000,
) -> Dict[str, Optional[str]]:
    """Extract context text for each section using best-match page +/- buffer.

    Centers the extraction around the first keyword match position on the
    target page to maximize relevance.

    Args:
        pages_text: List of (page_number, text) tuples.
        section_pages: Output from find_section_pages.
        section_keywords: Keywords dict for locating match position.
        buffer_pages: Number of pages before/after to include.
        max_chars: Maximum characters per section.

    Returns:
        Dict mapping section_id -> extracted text or None if not found.
    """
    if section_keywords is None:
        section_keywords = SECTION_KEYWORDS

    # Build a lookup: page_num -> text
    page_lookup: Dict[int, str] = {pn: text for pn, text in pages_text}

    contexts: Dict[str, Optional[str]] = {}

    for section_id, matched_pages in section_pages.items():
        if not matched_pages:
            contexts[section_id] = None
            continue

        # Per-section config overrides function defaults
        cfg = SECTION_EXTRACT_CONFIG.get(section_id, {})
        sect_buffer = cfg.get("buffer_pages", buffer_pages)
        sect_max = cfg.get("max_chars", max_chars)

        # Use the best-scored page (first in list)
        best_page = matched_pages[0]

        # Collect text from (best - buffer) to (best + buffer)
        parts = []
        for offset in range(-sect_buffer, sect_buffer + 1):
            target = best_page + offset
            if target in page_lookup:
                text = page_lookup[target]
                if text:
                    parts.append(f"--- p.{target} ---\n{text}")

        combined = "\n\n".join(parts)

        # If too long, try to center around the keyword match
        if len(combined) > sect_max:
            keywords = section_keywords.get(section_id, [])
            combined = _center_truncate(combined, keywords, sect_max)

        contexts[section_id] = combined

    return contexts


def _center_truncate(text: str, keywords: list, max_chars: int) -> str:
    """Truncate text centered around the first keyword match."""
    # Find the first keyword position
    match_pos = len(text)
    for kw in keywords:
        pos = text.find(kw)
        if pos >= 0 and pos < match_pos:
            match_pos = pos

    if match_pos == len(text):
        # No keyword found, fall back to simple truncation
        return _truncate_at_boundary(text, max_chars)

    # Center the window around the match
    half = max_chars // 2
    start = max(0, match_pos - half // 2)  # More text after match than before
    end = min(len(text), start + max_chars)
    start = max(0, end - max_chars)

    result = text[start:end]

    # Clean up: try to start at a page boundary or line boundary
    if start > 0:
        newline_pos = result.find("\n")
        if newline_pos >= 0 and newline_pos < 200:
            result = result[newline_pos + 1:]

    return _truncate_at_boundary(result, max_chars)


def _truncate_at_boundary(text: str, max_chars: int) -> str:
    """Truncate text at the last sentence boundary before max_chars."""
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]

    # Try to find last Chinese period, question mark, or newline
    for sep in ["。", "\n", "；", ".", "!", "！"]:
        last_pos = truncated.rfind(sep)
        if last_pos > max_chars * 0.5:  # Don't cut too aggressively
            return truncated[:last_pos + 1]

    return truncated


# ---------------------------------------------------------------------------
# Feature #41: JSON output writer
# ---------------------------------------------------------------------------

def write_output(
    contexts: Dict[str, Optional[str]],
    pdf_path: str,
    total_pages: int,
    output_path: str,
) -> dict:
    """Write pdf_sections.json with 7 sections + metadata.

    Returns the output dict for inspection.
    """
    found_count = sum(1 for v in contexts.values() if v is not None)

    output = {
        "metadata": {
            "pdf_file": os.path.basename(pdf_path),
            "total_pages": total_pages,
            "extract_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sections_found": found_count,
            "sections_total": len(contexts),
        },
    }

    for section_id in ["P2", "P3", "P4", "P6", "P13", "MDA", "SUB"]:
        output[section_id] = contexts.get(section_id)

    # Ensure output directory exists
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return output


# ---------------------------------------------------------------------------
# Feature #42: Main pipeline
# ---------------------------------------------------------------------------

def parse_args(args=None):
    parser = argparse.ArgumentParser(
        description="Extract target sections from annual report PDFs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --pdf 伊利股份_2024_年报.pdf
  %(prog)s --pdf report.pdf --output output/pdf_sections.json --verbose
        """,
    )
    parser.add_argument(
        "--pdf",
        required=True,
        help="Path to the annual report PDF file",
    )
    parser.add_argument(
        "--output",
        default="output/pdf_sections.json",
        help="Output JSON file path (default: output/pdf_sections.json)",
    )
    parser.add_argument(
        "--hints",
        default=None,
        help="Path to toc_hints.json (optional, from Phase 2A.5 TOC analysis)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress messages during extraction",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print parsed arguments and exit without processing",
    )
    return parser.parse_args(args)


def _load_hints(hints_path: Optional[str]) -> Dict[str, dict]:
    """Load TOC hints from JSON file.

    Args:
        hints_path: Path to toc_hints.json or None.

    Returns:
        Dict mapping section_id -> {"page": int, "title": str} or empty dict.
    """
    if not hints_path or not os.path.exists(hints_path):
        return {}
    try:
        with open(hints_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Failed to load hints file '{hints_path}': {e}", file=sys.stderr)
        return {}


def run_pipeline(pdf_path: str, output_path: str, verbose: bool = False,
                 hints_path: Optional[str] = None) -> dict:
    """Run the full extraction pipeline.

    Args:
        pdf_path: Path to the PDF.
        output_path: Path for JSON output.
        verbose: Print progress.
        hints_path: Optional path to toc_hints.json for TOC-based page overrides.

    Returns:
        The output dict written to JSON.

    Raises:
        FileNotFoundError: If PDF not found.
        RuntimeError: If PDF cannot be opened or is too small.
    """
    try:
        from scripts.config import validate_pdf
    except ModuleNotFoundError:
        from config import validate_pdf

    # Validate PDF
    is_valid, reason = validate_pdf(pdf_path)
    if not is_valid:
        raise RuntimeError(f"Invalid PDF: {reason}")

    # Step 1: Extract all pages
    print(f"[1/4] Extracting pages from {pdf_path}...")
    pages_text = extract_all_pages(pdf_path, verbose=verbose)
    total_pages = len(pages_text)

    if total_pages == 0:
        raise RuntimeError("PDF has no extractable pages")

    print(f"  Extracted {total_pages} pages")

    # Load TOC hints (Phase 2A.5)
    hints = _load_hints(hints_path)
    if hints and verbose:
        print(f"  Loaded TOC hints for: {list(hints.keys())}")

    # Step 2: Find section pages via keyword matching
    print("[2/4] Scanning for target sections...")
    section_pages = find_section_pages(pages_text)

    # Apply hints: override keyword-matched pages with TOC hint pages
    for sid, hint in hints.items():
        if sid in section_pages and "page" in hint:
            hint_page = hint["page"]
            if 1 <= hint_page <= total_pages:
                section_pages[sid] = [hint_page]
                if verbose:
                    print(f"  {sid}: overridden by hint → page {hint_page}")

    if verbose:
        for sid, pages in section_pages.items():
            if pages:
                print(f"  {sid}: found on pages {pages[:5]}")
            else:
                print(f"  {sid}: not found")

    # Step 3: Extract context around best matches
    print("[3/4] Extracting section context...")
    contexts = extract_section_context(pages_text, section_pages)

    # Step 4: Write output
    print(f"[4/4] Writing output to {output_path}...")
    result = write_output(contexts, pdf_path, total_pages, output_path)

    found = result["metadata"]["sections_found"]
    total = result["metadata"]["sections_total"]
    print(f"Done: {found}/{total} sections found")

    return result


def main():
    args = parse_args()

    if args.dry_run:
        print("=== Dry Run ===")
        print(f"  PDF: {args.pdf}")
        print(f"  Output: {args.output}")
        print(f"  Hints: {args.hints}")
        print(f"  Verbose: {args.verbose}")
        return

    try:
        result = run_pipeline(args.pdf, args.output, verbose=args.verbose,
                              hints_path=args.hints)
        found = result["metadata"]["sections_found"]
        total = result["metadata"]["sections_total"]
        print(f"Extracted {found}/{total} sections -> {args.output}")
    except (FileNotFoundError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
