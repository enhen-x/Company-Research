"""Integration tests — require live Tushare API and/or real PDF files.

All tests are marked with @pytest.mark.integration and skip automatically
when TUSHARE_TOKEN is not set or required files are not available.

Run with: python -m pytest tests/test_integration.py -v -m integration
"""

import glob
import os

import pytest

# Skip entire module if no TUSHARE_TOKEN
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN")
pytestmark = pytest.mark.integration

SKIP_NO_TOKEN = pytest.mark.skipif(
    not TUSHARE_TOKEN,
    reason="TUSHARE_TOKEN not set — skipping live API tests",
)


# --- Feature #74: Live tushare_collector.py on 600887 ---

@SKIP_NO_TOKEN
class TestFullCollection600887:
    """End-to-end test: collect all data for Yili (600887.SH) via live Tushare API."""

    def test_full_collection_600887(self, tmp_path):
        """Run assemble_data_pack on 600887.SH and verify output quality."""
        from tushare_collector import TushareClient

        client = TushareClient(TUSHARE_TOKEN)
        result = client.assemble_data_pack("600887.SH")

        # Output should be substantial (>5KB)
        assert len(result) > 5000, f"Output too small: {len(result)} bytes"

        # Should contain 5-year income data
        assert "合并利润表" in result
        assert "revenue" in result.lower() or "营业收入" in result or "revenue" in result

        # Should contain balance sheet fields
        assert "资产负债表" in result

        # Should contain basic info
        assert "600887" in result
        assert "基本信息" in result

        # Write to file for manual inspection
        output_file = tmp_path / "data_pack_market.md"
        output_file.write_text(result, encoding="utf-8")
        assert output_file.stat().st_size > 5000


# --- Feature #75: Live pdf_preprocessor.py with real PDF ---

@SKIP_NO_TOKEN
class TestFullPdfExtraction:
    """End-to-end test: extract sections from a real annual report PDF."""

    def _find_test_pdf(self):
        """Look for a test PDF in output/ directory."""
        patterns = [
            "output/*/600887*.pdf",
            "output/*/*.pdf",
            "tests/fixtures/*.pdf",
        ]
        for pattern in patterns:
            matches = glob.glob(pattern)
            if matches:
                return matches[0]
        return None

    def test_full_extraction_600887_report(self, tmp_path):
        """Extract sections from a real PDF and verify output."""
        pdf_path = self._find_test_pdf()
        if not pdf_path:
            pytest.skip("No test PDF found in output/ or tests/fixtures/")

        from pdf_preprocessor import run_pipeline

        output_path = str(tmp_path / "pdf_sections.json")
        result = run_pipeline(pdf_path, output_path)

        # Should extract at least 4 of 7 sections
        import json
        with open(output_path) as f:
            data = json.load(f)

        sections = ["P2", "P3", "P4", "P6", "P13", "MDA", "SUB"]
        found = sum(1 for s in sections if data.get(s) is not None)
        assert found >= 4, f"Only {found}/7 sections found, expected ≥4"

        # Extracted text should contain Chinese characters
        for key in sections:
            val = data.get(key)
            if val:
                has_chinese = any('\u4e00' <= c <= '\u9fff' for c in val)
                assert has_chinese, f"Section {key} has no Chinese text"


# --- Feature #76: Full pipeline end-to-end ---

@SKIP_NO_TOKEN
class TestFullPipeline:
    """End-to-end test: run Phase 1A + Phase 2A sequentially."""

    def test_phase1a_and_phase2a_pipeline(self, tmp_path):
        """Run tushare_collector then pdf_preprocessor and verify outputs."""
        from tushare_collector import TushareClient

        # Phase 1A: Tushare collection
        client = TushareClient(TUSHARE_TOKEN)
        data_pack = client.assemble_data_pack("600887.SH")

        market_file = tmp_path / "data_pack_market.md"
        market_file.write_text(data_pack, encoding="utf-8")
        assert market_file.exists()
        assert market_file.stat().st_size > 5000

        # Phase 2A: PDF extraction (only if a PDF is available)
        pdf_candidates = glob.glob("output/*/600887*.pdf") + glob.glob("tests/fixtures/*.pdf")
        if not pdf_candidates:
            pytest.skip("No PDF available for Phase 2A test")

        from pdf_preprocessor import run_pipeline

        pdf_output = str(tmp_path / "pdf_sections.json")
        run_pipeline(pdf_candidates[0], pdf_output)

        assert os.path.exists(pdf_output)
        import json
        with open(pdf_output) as f:
            sections = json.load(f)
        assert "metadata" in sections
        assert sections["metadata"]["sections_total"] == 7
