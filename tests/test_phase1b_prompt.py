"""Tests for Phase 1B prompt content — validate prompt structure and instructions.

Features #31-#36: Verify phase1_数据采集.md has correct role, scope, and section specs.
"""

import os
import pytest

PROMPT_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")


@pytest.fixture(scope="module")
def prompt_text():
    """Load the Phase 1B prompt file."""
    path = os.path.join(PROMPT_DIR, "phase1_数据采集.md")
    with open(path, encoding="utf-8") as f:
        return f.read()


# --- Feature #31: Role and scope ---

class TestFeature31RoleAndScope:
    def test_role_is_data_collector(self, prompt_text):
        """Agent role must be data collector (财经调查记者 v2.0 or 数据采集专员 v1.x)."""
        assert "财经调查记者" in prompt_text or "数据采集专员" in prompt_text

    def test_agent_tasks_listed(self, prompt_text):
        """Prompt must list §7, §8, §10, §13 as agent tasks."""
        for section in ["§7", "§8", "§10", "§13"]:
            assert section in prompt_text

    def test_tushare_sections_referenced(self, prompt_text):
        """Prompt must reference §1-§6 as tushare-generated."""
        assert "§1-§6" in prompt_text

    def test_forbids_analysis(self, prompt_text):
        """Prompt must forbid analysis and valuation."""
        assert "不做分析判断" in prompt_text or "不做任何分析判断" in prompt_text
        assert "不做估值计算" in prompt_text


# --- Feature #32: Risk-free rate handled by tushare ---

class TestFeature32RiskFreeRate:
    def test_no_rf_websearch_instruction(self, prompt_text):
        """Agent should NOT have WebSearch instructions for Rf/国债收益率.

        §14 risk-free rate is now collected by tushare_collector.py,
        so the prompt should not ask the agent to search for it.
        """
        # The prompt should mention §14 as tushare-generated, not as an agent task
        assert "§14" in prompt_text
        # §14 should appear in the tushare-generated listing, not in the agent search section
        # Check that §14 is NOT listed as a WebSearch task heading
        lines = prompt_text.split("\n")
        for line in lines:
            if "§14" in line and "WebSearch" in line and "搜索" in line:
                pytest.fail("Prompt should not instruct agent to WebSearch for §14 (Rf rate)")


# --- Feature #33: §7 management and governance ---

class TestFeature33Section7:
    def test_has_8_search_items(self, prompt_text):
        """§7 search table should have 8 items."""
        # Find §7 section and count table rows with numbered items
        in_s7 = False
        item_count = 0
        for line in prompt_text.split("\n"):
            if "§7" in line and "管理层" in line:
                in_s7 = True
            elif in_s7 and line.startswith("### §"):
                break
            elif in_s7 and line.startswith("| "):
                parts = [p.strip() for p in line.split("|")]
                if len(parts) > 1 and parts[1].isdigit():
                    item_count += 1
        assert item_count == 8, f"Expected 8 search items in §7, found {item_count}"

    def test_notes_tushare_data(self, prompt_text):
        """§7 should note that items 1/4/7/8 have tushare data."""
        assert "已有 tushare 结构化数据" in prompt_text
        # Check specific items mentioned
        assert "控股股东持股比例" in prompt_text
        assert "审计师" in prompt_text or "审计意见" in prompt_text

    def test_has_search_templates(self, prompt_text):
        """§7 should have search keyword templates with {公司名}."""
        assert "{公司名}" in prompt_text


# --- Feature #34: §8 industry and competition ---

class TestFeature34Section8:
    def test_has_competitor_query(self, prompt_text):
        """§8 should have competitor search."""
        assert "竞争对手" in prompt_text

    def test_has_regulation_query(self, prompt_text):
        """§8 should have regulation search."""
        assert "监管" in prompt_text

    def test_has_cycle_query(self, prompt_text):
        """§8 should have industry cycle search."""
        assert "周期" in prompt_text

    def test_has_trigger_condition(self, prompt_text):
        """§8.4 should have trigger condition for raw material prices."""
        assert "触发条件" in prompt_text
        assert "原材料" in prompt_text or "原奶" in prompt_text


# --- Feature #35: §10 MD&A ---

class TestFeature35Section10:
    def test_has_4_subsections(self, prompt_text):
        """§10 should have 4 subsections: 经营回顾/前瞻指引/资本配置/风险因素."""
        for sub in ["经营回顾", "前瞻指引", "资本配置", "风险因素"]:
            assert sub in prompt_text, f"§10 missing subsection: {sub}"

    def test_has_bilingual_queries(self, prompt_text):
        """§10 should have both Chinese and English search keywords."""
        assert "MD&A" in prompt_text
        # Check for English search template
        assert "annual report" in prompt_text or "management discussion" in prompt_text

    def test_pdf_first_instruction(self, prompt_text):
        """§10 should mention PDF-first sourcing via pdf_sections.json."""
        assert "pdf_sections.json" in prompt_text
        assert "PDF 优先" in prompt_text or "优先方式" in prompt_text

    def test_websearch_fallback(self, prompt_text):
        """§10 should still have WebSearch as fallback."""
        assert "备选" in prompt_text or "WebSearch" in prompt_text
        # Bilingual search keywords should still be present
        assert "管理层讨论" in prompt_text


# --- Feature #36: §13 Warnings ---

class TestFeature36Section13:
    def test_has_merge_instruction(self, prompt_text):
        """§13 should instruct agent to merge, not overwrite."""
        assert "合并" in prompt_text
        assert "不要覆盖" in prompt_text or "不覆盖" in prompt_text

    def test_references_section_13_1(self, prompt_text):
        """§13 should reference §13.1 auto-warnings (not 附录A)."""
        assert "§13.1" in prompt_text

    def test_no_appendix_a_for_warnings(self, prompt_text):
        """Warnings should not reference 附录A — that's §11 weekly prices."""
        # Find lines mentioning 附录A and check they don't refer to warnings
        for line in prompt_text.split("\n"):
            if "附录A" in line and ("Warnings" in line or "警示" in line or "异常" in line):
                pytest.fail(f"Line incorrectly references 附录A for warnings: {line.strip()}")


# --- Feature #89: §9B subsidiary identification ---

class TestSection9BSubsidiaries:
    """§9B: listed subsidiary identification for Module 9."""

    def test_has_section_9b(self, prompt_text):
        assert "§9B" in prompt_text

    def test_9b_has_trigger_condition(self, prompt_text):
        assert "触发条件" in prompt_text
        assert "控股" in prompt_text

    def test_9b_has_output_table_columns(self, prompt_text):
        for col in ["股票代码", "持股比例", "主营业务"]:
            assert col in prompt_text

    def test_9b_listed_in_task_scope(self, prompt_text):
        """§9B should appear in the task scope listing at the top."""
        assert "§9B" in prompt_text
