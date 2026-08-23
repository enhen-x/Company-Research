"""Configuration and utility functions for Turtle Investment Framework."""

from __future__ import annotations

import os
import re
import glob
from typing import Optional


def _load_env_file() -> None:
    """Load .env file from project root if it exists."""
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    env_path = os.path.normpath(env_path)
    if not os.path.isfile(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = value


def get_token() -> str:
    """Get Tushare Pro API token from environment or .env file.

    Returns:
        str: The Tushare API token.

    Raises:
        RuntimeError: If TUSHARE_TOKEN is not set.
    """
    _load_env_file()
    token = os.environ.get("TUSHARE_TOKEN", "")
    if not token:
        raise RuntimeError(
            "TUSHARE_TOKEN is not set.\n"
            "Option 1: Copy .env.sample to .env and fill in your token\n"
            "Option 2: export TUSHARE_TOKEN='your_token_here'\n"
            "Get a token at: https://tushare.pro/register"
        )
    return token


def get_api_url() -> Optional[str]:
    """Return custom Tushare API URL if TUSHARE_API_URL is set.

    When a broker API URL is configured, TushareClient will route all calls
    through it and auto-upgrade to VIP endpoints for better rate limits.
    """
    _load_env_file()
    return os.environ.get("TUSHARE_API_URL") or None


def validate_stock_code(code: str) -> str:
    """Validate and normalize a stock code to Tushare format.

    Supports:
        - A-share: 600887.SH, 000858.SZ, 300750.SZ
        - HK: 00700.HK, 09988.HK (1-5 digits, zero-padded to 5)
        - Plain codes: 600887 -> 600887.SH, 000858 -> 000858.SZ
        - Plain 1-5 digit codes -> HK (e.g., 696 -> 00696.HK)

    Args:
        code: Stock code string.

    Returns:
        str: Normalized Tushare-format code (e.g., '600887.SH').

    Raises:
        ValueError: If the code format is not recognized.
    """
    code = code.strip().upper()

    # Already in Tushare format
    if re.match(r"^\d{6}\.(SH|SZ)$", code):
        return code
    m = re.match(r"^(\d{1,5})\.HK$", code)
    if m:
        return f"{m.group(1).zfill(5)}.HK"

    # Plain 6-digit A-share code
    if re.match(r"^\d{6}$", code):
        if code.startswith("6"):
            return f"{code}.SH"
        elif code.startswith(("0", "3")):
            return f"{code}.SZ"
        else:
            raise ValueError(
                f"Unrecognized A-share code prefix: {code}. "
                "Expected 6xxxxx (SH), 0xxxxx or 3xxxxx (SZ)."
            )

    # Plain 1-5 digit HK code
    if re.match(r"^\d{1,5}$", code):
        return f"{code.zfill(5)}.HK"

    # Already in US format: AAPL.US
    if re.match(r"^[A-Z]{1,5}\.US$", code):
        return code

    # Plain alphabetic ticker → US stock
    if re.match(r"^[A-Z]{1,5}$", code):
        return f"{code}.US"

    raise ValueError(
        f"Unrecognized stock code format: '{code}'. "
        "Expected: 600887.SH, 000858.SZ, 00700.HK, AAPL.US, or plain digits."
    )


def check_local_pdf(stock_code: str, year: int, search_dir: str = ".",
                    report_type: str = "年报") -> Optional[str]:
    """Check if a report PDF exists locally.

    Args:
        stock_code: Stock code (e.g., '600887' or '600887.SH').
        year: Fiscal year to look for.
        search_dir: Directory to search in.
        report_type: Type of report to search for ('年报' or '中报').

    Returns:
        Path to the PDF if found, None otherwise.
    """
    # Extract numeric part of code
    numeric_code = stock_code.split(".")[0]

    if report_type == "中报":
        patterns = [
            f"*{numeric_code}*{year}*中报*.pdf",
            f"*{numeric_code}*{year}*半年*.pdf",
            f"*{numeric_code}*{year}*interim*.pdf",
            f"*{numeric_code}*{year}*H1*.pdf",
            f"{numeric_code}_{year}_中报.pdf",
        ]
    else:
        patterns = [
            f"*{numeric_code}*{year}*.pdf",
            f"*{numeric_code}*{year}*年报*.pdf",
            f"{numeric_code}_{year}_*.pdf",
        ]

    for pattern in patterns:
        matches = glob.glob(os.path.join(search_dir, pattern))
        if matches:
            return matches[0]

    return None


def validate_pdf(filepath: str) -> "tuple[bool, str]":
    """Validate that a file is a real PDF.

    Args:
        filepath: Path to the file.

    Returns:
        Tuple of (is_valid, reason).
    """
    if not os.path.exists(filepath):
        return False, f"File not found: {filepath}"

    size = os.path.getsize(filepath)
    if size < 100 * 1024:  # 100KB minimum
        return False, f"File too small ({size} bytes), likely not a real annual report"

    with open(filepath, "rb") as f:
        magic = f.read(20)
        if b"%PDF-" not in magic:
            return False, "File does not start with %PDF- magic bytes"

    return True, "Valid PDF"
