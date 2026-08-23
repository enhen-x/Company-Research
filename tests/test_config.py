"""Tests for scripts/config.py — token, stock codes, PDF utilities."""

import os

import pytest

from config import get_token, validate_stock_code, check_local_pdf, validate_pdf


# --- get_token() ---

class TestGetToken:
    def test_returns_token_when_set(self, monkeypatch):
        monkeypatch.setenv("TUSHARE_TOKEN", "abc123")
        assert get_token() == "abc123"

    def test_raises_when_not_set(self, monkeypatch):
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
        with pytest.raises(RuntimeError, match="TUSHARE_TOKEN"):
            get_token()

    def test_raises_when_empty(self, monkeypatch):
        monkeypatch.setenv("TUSHARE_TOKEN", "")
        with pytest.raises(RuntimeError, match="TUSHARE_TOKEN"):
            get_token()

    def test_loads_from_env_file(self, monkeypatch, tmp_path):
        """get_token() reads from .env file when env var not set."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        env_file = tmp_path / ".env"
        env_file.write_text("TUSHARE_TOKEN=from_env_file\n")
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
        import config as config_mod
        monkeypatch.setattr(config_mod, "__file__", str(scripts_dir / "config.py"))
        token = get_token()
        assert token == "from_env_file"
        # Clean up so other tests aren't affected
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

    def test_env_var_overrides_env_file(self, monkeypatch, tmp_path):
        """Environment variable takes precedence over .env file."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        env_file = tmp_path / ".env"
        env_file.write_text("TUSHARE_TOKEN=from_file\n")
        monkeypatch.setenv("TUSHARE_TOKEN", "from_env")
        import config as config_mod
        monkeypatch.setattr(config_mod, "__file__", str(scripts_dir / "config.py"))
        assert get_token() == "from_env"

    def test_env_file_skips_comments(self, monkeypatch, tmp_path):
        """Comments and blank lines in .env are skipped."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        env_file = tmp_path / ".env"
        env_file.write_text("# This is a comment\n\nTUSHARE_TOKEN=valid_token\n")
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
        import config as config_mod
        monkeypatch.setattr(config_mod, "__file__", str(scripts_dir / "config.py"))
        assert get_token() == "valid_token"
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)


# --- validate_stock_code() ---

class TestValidateStockCode:
    # A-share with suffix
    def test_sh_code(self):
        assert validate_stock_code("600887.SH") == "600887.SH"

    def test_sz_code(self):
        assert validate_stock_code("000858.SZ") == "000858.SZ"

    def test_sz_gem_code(self):
        assert validate_stock_code("300750.SZ") == "300750.SZ"

    # HK with suffix
    def test_hk_code(self):
        assert validate_stock_code("00700.HK") == "00700.HK"

    # Plain digit codes
    def test_plain_sh(self):
        assert validate_stock_code("600887") == "600887.SH"

    def test_plain_sz(self):
        assert validate_stock_code("000858") == "000858.SZ"

    def test_plain_gem(self):
        assert validate_stock_code("300750") == "300750.SZ"

    def test_plain_hk(self):
        assert validate_stock_code("00700") == "00700.HK"

    # Case insensitive
    def test_lowercase(self):
        assert validate_stock_code("600887.sh") == "600887.SH"

    # Whitespace
    def test_whitespace(self):
        assert validate_stock_code("  600887.SH  ") == "600887.SH"

    # Invalid codes
    def test_invalid_prefix(self):
        with pytest.raises(ValueError, match="Unrecognized"):
            validate_stock_code("900123")

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="Unrecognized"):
            validate_stock_code("AAPL123")

    def test_empty(self):
        with pytest.raises(ValueError, match="Unrecognized"):
            validate_stock_code("")

    # Variable-length HK codes (1-5 digits with suffix, zero-padded)
    def test_hk_4digit_suffix(self):
        assert validate_stock_code("0696.HK") == "00696.HK"

    def test_hk_4digit_suffix_no_leading_zero(self):
        assert validate_stock_code("9988.HK") == "09988.HK"

    def test_hk_1digit_suffix(self):
        assert validate_stock_code("5.HK") == "00005.HK"

    # Variable-length HK codes (plain digits, zero-padded)
    def test_plain_hk_3digit(self):
        assert validate_stock_code("696") == "00696.HK"

    def test_plain_hk_4digit(self):
        assert validate_stock_code("9988") == "09988.HK"

    def test_plain_hk_1digit(self):
        assert validate_stock_code("5") == "00005.HK"

    # US stock codes
    def test_us_with_suffix(self):
        assert validate_stock_code("AAPL.US") == "AAPL.US"

    def test_us_plain_ticker(self):
        assert validate_stock_code("AAPL") == "AAPL.US"

    def test_us_lowercase(self):
        assert validate_stock_code("aapl.us") == "AAPL.US"

    def test_us_5letter_ticker(self):
        assert validate_stock_code("GOOGL") == "GOOGL.US"

    def test_us_plain_lowercase(self):
        assert validate_stock_code("nvda") == "NVDA.US"


# --- check_local_pdf() ---

class TestCheckLocalPdf:
    def test_finds_matching_pdf(self, tmp_path):
        pdf = tmp_path / "600887_2023_annual.pdf"
        pdf.write_text("fake")
        result = check_local_pdf("600887.SH", 2023, str(tmp_path))
        assert result is not None
        assert "600887" in result

    def test_finds_chinese_pattern(self, tmp_path):
        pdf = tmp_path / "伊利600887_2023年报.pdf"
        pdf.write_text("fake")
        result = check_local_pdf("600887", 2023, str(tmp_path))
        assert result is not None

    def test_returns_none_when_no_match(self, tmp_path):
        result = check_local_pdf("600887.SH", 2023, str(tmp_path))
        assert result is None

    def test_returns_none_wrong_year(self, tmp_path):
        pdf = tmp_path / "600887_2022_annual.pdf"
        pdf.write_text("fake")
        result = check_local_pdf("600887.SH", 2023, str(tmp_path))
        assert result is None

    def test_strips_suffix(self, tmp_path):
        pdf = tmp_path / "600887_2023_report.pdf"
        pdf.write_text("fake")
        result = check_local_pdf("600887.SH", 2023, str(tmp_path))
        assert result is not None

    def test_finds_interim_report(self, tmp_path):
        """check_local_pdf finds interim report when report_type='中报'."""
        pdf = tmp_path / "600887_2025_中报.pdf"
        pdf.write_text("fake")
        result = check_local_pdf("600887.SH", 2025, str(tmp_path), report_type="中报")
        assert result is not None
        assert "中报" in result

    def test_interim_does_not_match_annual(self, tmp_path):
        """check_local_pdf with report_type='中报' does not match annual reports."""
        pdf = tmp_path / "600887_2025_年报.pdf"
        pdf.write_text("fake")
        result = check_local_pdf("600887.SH", 2025, str(tmp_path), report_type="中报")
        assert result is None

    def test_finds_interim_h1_pattern(self, tmp_path):
        """check_local_pdf finds H1-named interim reports."""
        pdf = tmp_path / "600887_2025_H1.pdf"
        pdf.write_text("fake")
        result = check_local_pdf("600887.SH", 2025, str(tmp_path), report_type="中报")
        assert result is not None


# --- validate_pdf() ---

class TestValidatePdf:
    def test_valid_pdf(self, tmp_path):
        pdf = tmp_path / "report.pdf"
        # Write PDF magic bytes + enough content to exceed 100KB
        with open(pdf, "wb") as f:
            f.write(b"%PDF-1.4 ")
            f.write(b"\x00" * (101 * 1024))
        is_valid, reason = validate_pdf(str(pdf))
        assert is_valid is True
        assert "Valid" in reason

    def test_file_not_found(self):
        is_valid, reason = validate_pdf("/nonexistent/file.pdf")
        assert is_valid is False
        assert "not found" in reason

    def test_file_too_small(self, tmp_path):
        pdf = tmp_path / "tiny.pdf"
        pdf.write_bytes(b"%PDF-1.4 tiny content")
        is_valid, reason = validate_pdf(str(pdf))
        assert is_valid is False
        assert "too small" in reason.lower()

    def test_wrong_magic_bytes(self, tmp_path):
        pdf = tmp_path / "fake.pdf"
        with open(pdf, "wb") as f:
            f.write(b"NOT A PDF FILE")
            f.write(b"\x00" * (101 * 1024))
        is_valid, reason = validate_pdf(str(pdf))
        assert is_valid is False
        assert "magic" in reason.lower() or "%PDF" in reason
