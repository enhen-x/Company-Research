"""Markdown output formatting utilities for Turtle Investment Framework.

All financial amounts are in millions RMB (raw yuan / 1e6).
"""

from __future__ import annotations

from typing import List, Optional


def format_number(value, divider: float = 1e6, decimals: int = 2) -> str:
    """Format a number: divide by divider, then comma-separate with decimals.

    Args:
        value: Raw number (e.g., 96886000000 yuan).
        divider: Divisor (default 1e6 to convert to millions).
        decimals: Decimal places (default 2).

    Returns:
        Formatted string, e.g., '96,886.00'.
        Returns '—' for None/NaN values.
    """
    if value is None:
        return "—"
    try:
        num = float(value) / divider
    except (TypeError, ValueError):
        return "—"
    # Check for NaN
    if num != num:
        return "—"
    return f"{num:,.{decimals}f}"


def format_table(headers: List[str], rows: List[List[str]],
                 alignments: Optional[List[str]] = None) -> str:
    """Generate a markdown table string.

    Args:
        headers: Column header strings.
        rows: List of rows, each a list of cell strings.
        alignments: Per-column alignment ('l', 'r', 'c'). Defaults to left.

    Returns:
        Markdown table string.
    """
    if not headers:
        return ""

    n_cols = len(headers)
    if alignments is None:
        alignments = ["l"] * n_cols

    # Build separator row
    sep_parts = []
    for a in alignments:
        if a == "r":
            sep_parts.append("---:")
        elif a == "c":
            sep_parts.append(":---:")
        else:
            sep_parts.append("---")

    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(sep_parts) + " |")
    for row in rows:
        # Pad row to match header length
        padded = list(row) + [""] * (n_cols - len(row))
        lines.append("| " + " | ".join(str(c) if c is not None else "—" for c in padded[:n_cols]) + " |")

    return "\n".join(lines)


def format_header(level: int, text: str) -> str:
    """Generate a markdown header.

    Args:
        level: Header level (1-6).
        text: Header text.

    Returns:
        Markdown header string, e.g., '## Section Title'.
    """
    level = max(1, min(6, level))
    return "#" * level + " " + text
