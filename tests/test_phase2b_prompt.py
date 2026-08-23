"""Tests for Phase 2B prompt content — validate prompt structure and extraction templates.

Features #48-#52: Verify phase2_PDF解析.md has correct scope, output format, and templates.
"""

import os
import re
import pytest

PROMPT_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")


@pytest.fixture(scope="module")
def prompt_text():
    """Load the Phase 2B prompt file."""
    path = os.path.join(PROMPT_DIR, "phase2_PDF解析.md")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _get_section(prompt_text, section_key):
    """Extract text belonging to a specific section (e.g. 'P2', 'P6')."""
    pattern = rf"### {section_key}[：:].*?\n(.*?)(?=### [A-Z]|\Z)"
    m = re.search(pattern, prompt_text, re.DOTALL)
    if m:
        return m.group(1)
    # Fallback: look for ## P2. style in output template
    pattern2 = rf"## {section_key}\..*?\n(.*?)(?=## [A-Z]|\Z)"
    m2 = re.search(pattern2, prompt_text, re.DOTALL)
    return m2.group(1) if m2 else ""


# --- Feature #48: Prompt scope ---

class TestFeature48PromptScope:
    def test_role_is_extraction_specialist(self, prompt_text):
        """Agent role must be 数据提取专员."""
        assert "数据提取专员" in prompt_text

    def test_input_is_pdf_sections_json(self, prompt_text):
        """Input must be pdf_sections.json."""
        assert "pdf_sections.json" in prompt_text

    def test_five_target_sections(self, prompt_text):
        """Prompt must reference all 5+1 extraction targets."""
        for key in ["P2", "P3", "P4", "P6", "P13"]:
            assert f'"{key}"' in prompt_text or f"### {key}" in prompt_text, (
                f"Missing extraction target: {key}"
            )

    def test_no_old_items(self, prompt_text):
        """Prompt should not have P1, P5, P7-P12, P14-P18 as extraction targets."""
        # These old items should not appear as ### section headers
        old_items = ["P1", "P5", "P7", "P8", "P9", "P10", "P11", "P12",
                     "P14", "P15", "P16", "P17", "P18"]
        for item in old_items:
            pattern = rf"### {item}[：:]"
            assert not re.search(pattern, prompt_text), (
                f"Old extraction target found: {item}"
            )


# --- Feature #49: Output format ---

class TestFeature49OutputFormat:
    def test_output_file_is_data_pack_report(self, prompt_text):
        """Output file must be data_pack_report.md."""
        assert "data_pack_report.md" in prompt_text

    def test_has_section_headers(self, prompt_text):
        """Output template must have section headers for all 5 items."""
        for key in ["P2", "P3", "P4", "P6", "P13"]:
            pattern = rf"## {key}\."
            assert re.search(pattern, prompt_text), (
                f"Missing output section header: ## {key}."
            )

    def test_has_unit_annotation(self, prompt_text):
        """Prompt must specify 百万元 as unit."""
        assert "百万元" in prompt_text

    def test_null_handling(self, prompt_text):
        """Prompt must have null handling with ⚠️ marker."""
        assert "⚠️" in prompt_text
        assert "null" in prompt_text.lower()


# --- Feature #50: P2 restricted cash template ---

class TestFeature50P2Template:
    def test_p2_has_restricted_cash_table(self, prompt_text):
        """P2 template must have restricted cash categories."""
        p2 = _get_section(prompt_text, "P2")
        assert "受限" in p2 or "受限现金" in prompt_text
        # Table should have category columns
        assert "金额" in p2

    def test_p2_has_total(self, prompt_text):
        """P2 template must have a total row."""
        p2 = _get_section(prompt_text, "P2")
        assert "合计" in p2

    def test_p2_has_cash_percentage(self, prompt_text):
        """P2 template must include percentage of total cash."""
        p2 = _get_section(prompt_text, "P2")
        assert "占货币资金总额比例" in p2 or "占总现金" in p2


# --- Feature #51: P3 AR aging template ---

class TestFeature51P3Template:
    def test_p3_has_aging_table(self, prompt_text):
        """P3 template must have aging buckets."""
        p3 = _get_section(prompt_text, "P3")
        assert "账龄" in p3
        for bucket in ["1年以内", "1-2年", "2-3年", "3年以上"]:
            assert bucket in p3, f"Missing aging bucket: {bucket}"

    def test_p3_has_bad_debt_provision(self, prompt_text):
        """P3 template must mention bad debt provision."""
        p3 = _get_section(prompt_text, "P3")
        assert "坏账准备" in p3 or "坏账计提" in p3

    def test_p3_has_related_party_ar(self, prompt_text):
        """P3 template must mention related party receivables."""
        p3 = _get_section(prompt_text, "P3")
        assert "关联方应收" in p3


# --- Feature #52: P4/P6/P13 templates ---

class TestFeature52P4P6P13Templates:
    def test_p4_has_top5_table(self, prompt_text):
        """P4 template must have related party transaction table."""
        p4 = _get_section(prompt_text, "P4")
        assert ("前5大" in p4 or "关联方名称" in p4)
        assert "金额" in p4

    def test_p6_has_guarantees(self, prompt_text):
        """P6 template must mention guarantees."""
        p6 = _get_section(prompt_text, "P6")
        assert "担保" in p6

    def test_p6_has_litigation(self, prompt_text):
        """P6 template must mention litigation or arbitration."""
        p6 = _get_section(prompt_text, "P6")
        assert "诉讼" in p6 or "仲裁" in p6

    def test_p6_has_commitments(self, prompt_text):
        """P6 template must mention commitments."""
        p6 = _get_section(prompt_text, "P6")
        assert "承诺" in p6

    def test_p13_has_category_table(self, prompt_text):
        """P13 template must have non-recurring items by category."""
        p13 = _get_section(prompt_text, "P13")
        assert "非经常性损益" in prompt_text
        assert "政府补贴" in p13 or "政府补助" in p13
        assert "资产处置" in p13
