"""Tests for output format validation — data_pack_market.md, pdf_sections.json, data_pack_report.md."""

import json
import os
import re
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tushare_collector import TushareClient
from pdf_preprocessor import write_output


def _make_client():
    """Create a TushareClient with mocked tushare module."""
    with patch("tushare_collector.ts") as mock_ts:
        mock_ts.pro_api.return_value = MagicMock()
        client = TushareClient("test_token")
    return client


def _assemble_empty_data_pack(ts_code="600887.SH"):
    """Assemble a data pack with empty API responses for schema testing."""
    client = _make_client()

    def mock_safe_call(api_name, **kwargs):
        return pd.DataFrame()

    with patch.object(client, '_safe_call', side_effect=mock_safe_call):
        return client.assemble_data_pack(ts_code)


# --- Feature #71: data_pack_market.md schema validation ---

class TestDataPackMarketSchema:
    """Validate structure and content of data_pack_market.md output."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.result = _assemble_empty_data_pack("600887.SH")

    def test_has_top_level_header(self):
        """Output starts with H1 header containing stock code."""
        assert "# 数据包 — 600887.SH" in self.result

    def test_has_timestamp(self):
        """Output includes generation timestamp."""
        assert re.search(r"\*生成时间: \d{4}-\d{2}-\d{2}", self.result)

    def test_has_tushare_source(self):
        """Output cites Tushare Pro as data source."""
        assert "Tushare Pro" in self.result

    def test_has_unit_label(self):
        """Output includes currency unit (百万元 for A-shares)."""
        assert "百万元" in self.result

    def test_section_headers_present(self):
        """All expected section headers are present in the output."""
        expected_sections = [
            "1. 基本信息",
            "2. 市场行情",
            "3. 合并利润表",
            "3P. 母公司利润表",
            "4. 合并资产负债表",
            "4P. 母公司资产负债表",
            "5. 现金流量表",
            "6. 分红历史",
            "7. 股东与治理",
            "9. 主营业务构成",
            "11. 十年周线行情",
            "12. 关键财务指标",
            "13. 风险警示",
            "14. 无风险利率",
            "15. 股票回购",
            "16. 股权质押",
            "17. 衍生指标",
        ]
        for section in expected_sections:
            assert section in self.result, f"Missing section: {section}"

    def test_agent_placeholder_sections(self):
        """Agent-only sections (§8, §10) have placeholder markers."""
        assert "§8 待Agent WebSearch补充" in self.result
        assert "§10 待Agent WebSearch补充" in self.result

    def test_completion_summary(self):
        """Output ends with completion summary line."""
        assert re.search(r"\*共 \d+/\d+ 个数据板块成功获取\*", self.result)


# --- Feature #72: pdf_sections.json schema validation ---

class TestPdfSectionsJsonSchema:
    """Validate structure of pdf_sections.json output."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Generate a pdf_sections.json using write_output with mock data."""
        self.output_path = str(tmp_path / "pdf_sections.json")
        contexts = {
            "P2": "受限资产合计 1,234 百万元",
            "P3": "应收账款账龄分析...",
            "P4": None,
            "P6": "或有负债说明...",
            "P13": "非经常性损益明细...",
            "MDA": "管理层讨论与分析内容...",
            "SUB": None,
        }
        self.output_data = write_output(contexts, "test_report.pdf", 200, self.output_path)
        with open(self.output_path) as f:
            self.json_data = json.load(f)

    def test_required_section_keys_present(self):
        """Output JSON has all 7 section keys."""
        for key in ("P2", "P3", "P4", "P6", "P13", "MDA", "SUB"):
            assert key in self.json_data, f"Missing key: {key}"

    def test_metadata_present(self):
        """Output JSON has metadata with expected fields."""
        assert "metadata" in self.json_data
        meta = self.json_data["metadata"]
        assert "pdf_file" in meta
        assert "total_pages" in meta
        assert "extract_time" in meta
        assert "sections_found" in meta
        assert "sections_total" in meta

    def test_metadata_pdf_file(self):
        """Metadata pdf_file matches input filename."""
        assert self.json_data["metadata"]["pdf_file"] == "test_report.pdf"

    def test_metadata_total_pages(self):
        """Metadata total_pages matches input."""
        assert self.json_data["metadata"]["total_pages"] == 200

    def test_metadata_sections_found_count(self):
        """sections_found matches count of non-null section values."""
        non_null = sum(1 for k in ("P2", "P3", "P4", "P6", "P13", "MDA", "SUB")
                       if self.json_data[k] is not None)
        assert self.json_data["metadata"]["sections_found"] == non_null

    def test_metadata_sections_total(self):
        """sections_total is always 7."""
        assert self.json_data["metadata"]["sections_total"] == 7

    def test_section_values_are_str_or_none(self):
        """All section values must be str or None."""
        for key in ("P2", "P3", "P4", "P6", "P13", "MDA", "SUB"):
            val = self.json_data[key]
            assert val is None or isinstance(val, str), f"{key} has invalid type: {type(val)}"

    def test_extract_time_format(self):
        """extract_time follows YYYY-MM-DD HH:MM:SS format."""
        ts = self.json_data["metadata"]["extract_time"]
        assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", ts)


# --- Feature #73: data_pack_report.md validation ---

class TestDataPackReportSchema:
    """Validate Phase 2B output contract defined in prompts/phase2_PDF解析.md."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Read the Phase 2 prompt to validate against."""
        prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "phase2_PDF解析.md")
        with open(prompt_path, encoding="utf-8") as f:
            self.prompt_content = f.read()

    def test_prompt_defines_header_template(self):
        """Phase 2 prompt defines the output header template."""
        assert "年报附注数据包" in self.prompt_content

    def test_prompt_defines_pdf_source_metadata(self):
        """Phase 2 prompt specifies PDF source info in header."""
        assert "PDF来源" in self.prompt_content

    def test_prompt_defines_p_section_headers(self):
        """Phase 2 prompt defines all P-section headers."""
        for section in ("P2", "P3", "P4", "P6", "P13"):
            assert f"## {section}" in self.prompt_content or section in self.prompt_content, \
                f"Missing P-section definition: {section}"

    def test_prompt_defines_unit_convention(self):
        """Phase 2 prompt specifies 百万元 as unit convention."""
        assert "百万元" in self.prompt_content

    def test_prompt_defines_missing_section_warning(self):
        """Phase 2 prompt defines a warning marker for missing sections."""
        # The prompt uses ⚠️ or similar warning for sections not found in PDF
        assert "未找到" in self.prompt_content or "跳过" in self.prompt_content or "缺失" in self.prompt_content

    def test_prompt_defines_sub_section(self):
        """Phase 2 prompt includes SUB (subsidiary) conditional section."""
        assert "SUB" in self.prompt_content

    def test_prompt_defines_page_count_metadata(self):
        """Phase 2 prompt specifies page count in metadata block."""
        assert "总页数" in self.prompt_content or "total_pages" in self.prompt_content
