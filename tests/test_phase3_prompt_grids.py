"""Tests for Phase 3 prompt wiring of §17.10-§17.13 pre-computation grids.

Substring assertions on strategies/turtle/ prompt files verifying:
- "你不做数学计算" discipline constraint
- §17.10-§17.13 table-lookup references
- "降级路径" fallback blocks preserving manual formulas
- M 来源 / GG 来源 provenance fields
- target_buy_price wired into valuation step 4-1 + factor_interface schema
"""

import pathlib

import pytest

TURTLE_DIR = pathlib.Path(__file__).resolve().parent.parent / "strategies" / "turtle"
QUANT = TURTLE_DIR / "phase3_quantitative.md"
VALUATION = TURTLE_DIR / "phase3_valuation.md"
FACTOR_INTERFACE = TURTLE_DIR / "references" / "factor_interface.md"


@pytest.fixture(scope="module")
def quant_text():
    return QUANT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def valuation_text():
    return VALUATION.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def factor_interface_text():
    return FACTOR_INTERFACE.read_text(encoding="utf-8")


class TestQuantPrompt:
    def test_no_manual_math_constraint(self, quant_text):
        assert "你不做数学计算" in quant_text

    def test_references_all_four_sections(self, quant_text):
        for tag in ["§17.10", "§17.11", "§17.12", "§17.13"]:
            assert tag in quant_text

    def test_degradation_paths_preserved(self, quant_text):
        # Manual formulas retained under 降级路径 sub-blocks
        assert "降级路径（§17.12 缺失时）" in quant_text
        assert "降级路径（§17.10 缺失时）" in quant_text
        assert "降级路径（§17.11 缺失时）" in quant_text
        assert "降级路径（§17.13 缺失时）" in quant_text
        # Original manual formula still present
        assert "Owner Earnings I = C + D − H" in quant_text
        assert "GG = [AA × M × (1−Q%) + O] / 市值" in quant_text

    def test_provenance_fields_in_summary(self, quant_text):
        assert "M 来源" in quant_text
        assert "GG 来源" in quant_text


class TestValuationPrompt:
    def test_step_4_1_references_17_11(self, valuation_text):
        assert "§17.11" in valuation_text
        assert "target_buy_price" in valuation_text
        assert "目标买入价" in valuation_text


class TestFactorInterface:
    def test_target_buy_price_row(self, factor_interface_text):
        assert "target_buy_price" in factor_interface_text

    def test_m_source_row(self, factor_interface_text):
        assert "M_source" in factor_interface_text

    def test_gg_source_row(self, factor_interface_text):
        assert "GG_source" in factor_interface_text
