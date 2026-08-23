"""Tests for scripts/format_utils.py — markdown formatting helpers."""

import math

from format_utils import format_number, format_table, format_header


class TestFormatNumber:
    def test_yili_revenue_2020(self):
        """96886000000 yuan -> 96,886.00 million."""
        assert format_number(96886000000) == "96,886.00"

    def test_small_number(self):
        assert format_number(1000000) == "1.00"

    def test_zero(self):
        assert format_number(0) == "0.00"

    def test_negative(self):
        assert format_number(-5000000000) == "-5,000.00"

    def test_none_returns_dash(self):
        assert format_number(None) == "—"

    def test_nan_returns_dash(self):
        assert format_number(float("nan")) == "—"

    def test_custom_divider(self):
        """No division when divider=1."""
        assert format_number(12345.678, divider=1, decimals=1) == "12,345.7"

    def test_custom_decimals(self):
        assert format_number(1500000000, decimals=0) == "1,500"

    def test_string_number(self):
        assert format_number("96886000000") == "96,886.00"

    def test_non_numeric_returns_dash(self):
        assert format_number("N/A") == "—"


class TestFormatTable:
    def test_basic_table(self):
        result = format_table(
            ["Name", "Value"],
            [["Revenue", "96,886.00"], ["Net Income", "7,030.00"]],
        )
        lines = result.split("\n")
        assert len(lines) == 4  # header + separator + 2 rows
        assert "| Name | Value |" in lines[0]
        assert "| Revenue | 96,886.00 |" in lines[2]

    def test_right_alignment(self):
        result = format_table(
            ["Item", "Amount"],
            [["A", "100"]],
            alignments=["l", "r"],
        )
        assert "---:" in result

    def test_center_alignment(self):
        result = format_table(
            ["Item", "Amount"],
            [["A", "100"]],
            alignments=["c", "c"],
        )
        assert ":---:" in result

    def test_empty_headers(self):
        assert format_table([], []) == ""

    def test_short_row_padded(self):
        result = format_table(["A", "B", "C"], [["x"]])
        # Row should still have 3 columns
        data_line = result.split("\n")[2]
        assert data_line.count("|") == 4  # 3 columns + outer pipes

    def test_multiple_rows(self):
        result = format_table(
            ["Year", "Revenue"],
            [["2020", "96,886"], ["2021", "110,600"], ["2022", "123,186"]],
        )
        lines = result.split("\n")
        assert len(lines) == 5  # header + sep + 3 rows


class TestFormatHeader:
    def test_h1(self):
        assert format_header(1, "Title") == "# Title"

    def test_h2(self):
        assert format_header(2, "Section") == "## Section"

    def test_h3(self):
        assert format_header(3, "Subsection") == "### Subsection"

    def test_clamp_high(self):
        assert format_header(10, "Deep") == "###### Deep"

    def test_clamp_low(self):
        assert format_header(0, "Top") == "# Top"
