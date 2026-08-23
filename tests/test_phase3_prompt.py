"""Tests for Phase 3 prompt files — features #53-#60, optimizations A/B/C.

Validates that prompt files reference correct data sources after
v1.0 migration (Tushare-sourced sections replace stale P-items).
"""

import pathlib
import re
import pytest

PROMPTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "prompts"
PHASE3 = PROMPTS_DIR / "phase3_分析与报告.md"
FACTOR1 = PROMPTS_DIR / "references" / "factor1_资产质量与商业模式.md"
FACTOR2 = PROMPTS_DIR / "references" / "factor2_穿透回报率粗算.md"
FACTOR3 = PROMPTS_DIR / "references" / "factor3_穿透回报率精算.md"
FACTOR4 = PROMPTS_DIR / "references" / "factor4_估值与安全边际.md"
COORDINATOR = PROMPTS_DIR / "coordinator.md"


@pytest.fixture(scope="module")
def phase3_text():
    return PHASE3.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def factor1_text():
    return FACTOR1.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def factor2_text():
    return FACTOR2.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def factor3_text():
    return FACTOR3.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def factor4_text():
    return FACTOR4.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def coordinator_text():
    return COORDINATOR.read_text(encoding="utf-8")


# ── Feature #53: Phase 3 unified units ──────────────────────────────


class TestFeature53UnifiedUnits:
    """Phase 3 prompt uses unified units (百万元) and Tushare Pro."""

    def test_phase3_units_millions(self, phase3_text):
        assert "百万元" in phase3_text

    def test_phase3_tushare_pro_mention(self, phase3_text):
        assert "Tushare Pro" in phase3_text

    def test_phase3_payout_primary_source(self, phase3_text):
        """Payout ratio primary source should be §6 + §3, not P11."""
        assert "§6" in phase3_text
        assert "§3" in phase3_text

    def test_phase3_available_fields_mention(self, phase3_text):
        """Step 1 should mention available_fields.json for extra data."""
        assert "available_fields.json" in phase3_text


# ── Feature #54: Factor 1 parent company data §3P/§4P ──────────────


class TestFeature54ParentCompanyData:
    """Factor 1 module 9 uses §3P/§4P from Tushare, not P1."""

    def test_factor1_module9_uses_section_4P(self, factor1_text):
        """Module 9 SOTP should reference §4P for parent company data."""
        assert "§4P" in factor1_text

    def test_factor1_module9_degradation_not_P1_primary(self, factor1_text):
        """Degradation block should use 合并口径 as fallback, not P1 as primary."""
        # P1 should not appear as primary source in module 9
        # The degradation path should reference 合并口径 (consolidated)
        assert "合并口径" in factor1_text

    def test_factor1_no_P1_reference(self, factor1_text):
        """P1 references should be removed from factor1."""
        # Use regex to avoid matching P13 etc.
        assert not re.search(r"data_pack_report\s+P1(?!\d)", factor1_text)


# ── Feature #55: Factor 2 payout ratio from Tushare ────────────────


class TestFeature55PayoutRatio:
    """Factor 2 uses §6 + §3 for payout ratio, not P11."""

    def test_factor2_step5_uses_tushare_sections(self, factor2_text):
        """Step 5 payout source should reference §6 + §3."""
        assert "§6" in factor2_text
        assert "§3" in factor2_text

    def test_factor2_step8_uses_tushare_sections(self, factor2_text):
        """Step 8 payout ratio calculation should reference §6 + §3."""
        # Step 8 previously referenced P11
        assert "data_pack_report P11" not in factor2_text


# ── Feature #56: Factor 3 contract liability from §4 ──────────────


class TestFeature56ContractLiability:
    """Factor 3 step 1 annotates data source for 预收款/合同负债."""

    def test_factor3_step1_section4_annotation(self, factor3_text):
        """Step 1 should have §4 source annotation for contract liability."""
        assert "§4" in factor3_text


# ── Feature #57: Cross-validate with §12 pre-computed ratios ───────


class TestFeature57CrossValidateSection12:
    """Factor 1 module 0(2) cross-validates with §12."""

    def test_factor1_module0_references_section12(self, factor1_text):
        """Module 0(2) should reference §12 for cross-validation."""
        assert "§12" in factor1_text

    def test_factor1_module0_cross_validate_note(self, factor1_text):
        """Should contain cross-validation instruction with §12."""
        # Check both §12 and some form of cross-validate/校验
        assert "§12" in factor1_text
        # Should mention cross-validation concept
        has_cross_validate = "交叉校验" in factor1_text or "交叉验证" in factor1_text
        assert has_cross_validate, "Should mention cross-validation with §12"


# ── Feature #58: Remove all stale P-item references ────────────────


class TestFeature58StaleReferences:
    """No stale P-item references remain in any factor file."""

    def test_factor1_no_P11_reference(self, factor1_text):
        """Factor1 should not reference P11 (now §6 + §3)."""
        assert "P11" not in factor1_text

    def test_factor1_no_P9_reference(self, factor1_text):
        """Factor1 should not reference P9 (now §10)."""
        assert "data_pack_report.md P9" not in factor1_text
        assert "data_pack_report P9" not in factor1_text

    def test_factor3_no_P5_reference(self, factor3_text):
        """Factor3 should not reference P5 (now §5)."""
        assert "data_pack_report P5" not in factor3_text

    def test_factor3_no_P8_reference(self, factor3_text):
        """Factor3 should not reference P8 (merged into P6)."""
        assert "P6/P8" not in factor3_text
        assert "P8" not in factor3_text

    def test_factor3_no_P11_reference(self, factor3_text):
        """Factor3 should not reference P11 (now §6 + §3)."""
        assert "P11" not in factor3_text

    @pytest.mark.parametrize("stale_p", ["P1", "P5", "P7", "P8", "P9",
                                          "P10", "P11", "P12", "P14",
                                          "P15", "P16", "P17", "P18"])
    def test_no_stale_p_items_in_factor1(self, factor1_text, stale_p):
        """Factor1 should have no stale P-item references."""
        # Use word-boundary regex to avoid P1 matching P13, etc.
        pattern = rf"data_pack_report\s+{stale_p}(?!\d)"
        assert not re.search(pattern, factor1_text), \
            f"Stale reference 'data_pack_report {stale_p}' found in factor1"

    @pytest.mark.parametrize("stale_p", ["P1", "P5", "P7", "P8", "P9",
                                          "P10", "P11", "P12", "P14",
                                          "P15", "P16", "P17", "P18"])
    def test_no_stale_p_items_in_factor2(self, factor2_text, stale_p):
        """Factor2 should have no stale P-item references."""
        pattern = rf"data_pack_report\s+{stale_p}(?!\d)"
        assert not re.search(pattern, factor2_text), \
            f"Stale reference 'data_pack_report {stale_p}' found in factor2"

    @pytest.mark.parametrize("stale_p", ["P1", "P5", "P7", "P8", "P9",
                                          "P10", "P11", "P12", "P14",
                                          "P15", "P16", "P17", "P18"])
    def test_no_stale_p_items_in_factor3(self, factor3_text, stale_p):
        """Factor3 should have no stale P-item references."""
        pattern = rf"data_pack_report\s+{stale_p}(?!\d)"
        assert not re.search(pattern, factor3_text), \
            f"Stale reference 'data_pack_report {stale_p}' found in factor3"


# ── Feature #59: Checkpoint mechanism ──────────────────────────────


class TestFeature59Checkpoint:
    """Phase 3 has checkpoint output path in output/ directory."""

    def test_phase3_checkpoint_output_path(self, phase3_text):
        """Step 1 should specify checkpoint output path."""
        assert "output/" in phase3_text

    def test_phase3_checkpoint_report_filename(self, phase3_text):
        """Checkpoint output should reference report filename pattern."""
        assert "分析报告" in phase3_text


# ── Feature #60: Warnings consumption ──────────────────────────────


class TestFeature60Warnings:
    """Phase 3 distinguishes §13.1 (typed) and §13.2 (free-form)."""

    def test_phase3_section13_1_typed(self, phase3_text):
        """Should mention §13.1 as auto-detect/typed warnings."""
        assert "§13.1" in phase3_text

    def test_phase3_section13_2_freeform(self, phase3_text):
        """Should mention §13.2 as agent/free-form warnings."""
        assert "§13.2" in phase3_text

    def test_phase3_warnings_distinction(self, phase3_text):
        """Should distinguish typed vs free-form warnings."""
        # Should mention both auto-detect and agent concepts
        has_auto = "自动检测" in phase3_text or "auto" in phase3_text.lower()
        has_agent = "Agent" in phase3_text or "agent" in phase3_text
        assert has_auto or has_agent, "Should distinguish warning sources"


# ── Optimization A: Module 0 simplified ──────────────────────────────


class TestOptimizationAModule0Simplified:
    """Module 0 should be simplified to 3 items: anomaly scan, profit
    calibration, cash calibration. No data copying from reports."""

    def test_module0_title_updated(self, factor1_text):
        """Module 0 title should be '数据校验与口径锚定'."""
        assert "数据校验与口径锚定" in factor1_text

    def test_module0_no_parameter_preextract(self, factor1_text):
        """Module 0 should not have (8) parameter pre-extraction section."""
        assert "因子2/3/4计算参数预提取" not in factor1_text

    def test_module0_no_income_data_copy(self, factor1_text):
        """Module 0 should not copy income statement data."""
        assert "利润表核心数据" not in factor1_text

    def test_module0_no_bs_data_copy(self, factor1_text):
        """Module 0 should not copy balance sheet data."""
        assert "资产负债表核心数据" not in factor1_text

    def test_module0_no_cf_data_copy(self, factor1_text):
        """Module 0 should not copy cashflow data."""
        assert "现金流量表核心数据" not in factor1_text

    def test_module0_has_anomaly_scan(self, factor1_text):
        """Module 0 should have anomaly scan (异常扫描)."""
        assert "异常扫描" in factor1_text

    def test_module0_has_profit_calibration(self, factor1_text):
        """Module 0 should have profit calibration (利润口径锚定)."""
        assert "利润口径锚定" in factor1_text

    def test_module0_has_cash_calibration(self, factor1_text):
        """Module 0 should have cash calibration (现金口径决策)."""
        assert "现金口径决策" in factor1_text

    def test_no_module0_8_references(self, factor1_text):
        """No references to 模块〇(8) should remain."""
        assert "模块〇(8)" not in factor1_text

    def test_no_module0_8_refs_in_factor2(self, factor2_text):
        """Factor 2 should not reference 模块〇(8)."""
        assert "模块〇(8)" not in factor2_text

    def test_no_module0_8_refs_in_factor3(self, factor3_text):
        """Factor 3 should not reference 模块〇(8)."""
        assert "模块〇(8)" not in factor3_text

    def test_factor2_reads_from_data_pack(self, factor2_text):
        """Factor 2 should read directly from data_pack sections."""
        assert "§3" in factor2_text
        assert "§5" in factor2_text

    def test_factor3_reads_from_data_pack(self, factor3_text):
        """Factor 3 step 8 should read from §4 directly."""
        assert "data_pack §4" in factor3_text

    def test_factor4_rf_from_section14(self, factor4_text):
        """Factor 4 Rf should reference §14."""
        assert "§14" in factor4_text

    def test_factor1_output_no_quantitative_params(self, factor1_text):
        """Factor 1B output should not list quantitative params from 模块〇(8)."""
        assert "模块〇(8)A" not in factor1_text
        assert "模块〇(8)B" not in factor1_text
        assert "模块〇(8)C" not in factor1_text

    def test_factor1_output_has_calibration_reference(self, factor1_text):
        """Factor 1B output should reference calibration decisions."""
        assert "口径决策" in factor1_text

    def test_phase3_no_module0_8_ref(self, phase3_text):
        """Phase 3 executor should not reference 模块〇(8)."""
        assert "模块〇(8)" not in phase3_text

    def test_phase3_module0_simplified_mention(self, phase3_text):
        """Phase 3 should mention simplified Module 0."""
        assert "模块〇精简版" in phase3_text or "数据校验与口径锚定" in phase3_text


# ── Optimization B: Factor 2 streamlined to 4 steps ─────────────────


class TestOptimizationBFactor2Streamlined:
    """Factor 2 should have 4 steps instead of 8."""

    def test_factor2_has_step1(self, factor2_text):
        """Factor 2 should have step 1 (参数读取与 OE 粗算)."""
        assert "步骤1" in factor2_text
        assert "OE 粗算" in factor2_text or "Owner Earnings" in factor2_text

    def test_factor2_has_step2(self, factor2_text):
        """Factor 2 should have step 2 (分配能力验证)."""
        assert "步骤2" in factor2_text
        assert "分配能力验证" in factor2_text

    def test_factor2_has_step3(self, factor2_text):
        """Factor 2 should have step 3 (粗算穿透回报率)."""
        assert "步骤3" in factor2_text
        assert "粗算穿透回报率" in factor2_text

    def test_factor2_has_step4(self, factor2_text):
        """Factor 2 should have step 4 (否决门判断)."""
        assert "步骤4" in factor2_text
        assert "否决门" in factor2_text

    def test_factor2_no_step5(self, factor2_text):
        """Factor 2 should NOT have step 5 (分配意愿 moved to F3)."""
        # Steps should end at 4; no "## 步骤5" heading
        assert not re.search(r"^## 步骤5", factor2_text, re.MULTILINE)

    def test_factor2_no_step6(self, factor2_text):
        """Factor 2 should NOT have step 6 (可预测性 moved to F3)."""
        assert not re.search(r"^## 步骤6", factor2_text, re.MULTILINE)

    def test_factor2_no_step7(self, factor2_text):
        """Factor 2 should NOT have step 7 or 8 as separate sections."""
        assert not re.search(r"^## 步骤7", factor2_text, re.MULTILINE)
        assert not re.search(r"^## 步骤8", factor2_text, re.MULTILINE)

    def test_factor2_output_no_willingness(self, factor2_text):
        """Factor 2 output should not include 分配意愿 line."""
        # The output block should not have 分配意愿 as an output field
        output_section = factor2_text.split("## 因子2输出")[-1]
        assert "分配意愿：[强" not in output_section

    def test_factor2_output_no_predictability(self, factor2_text):
        """Factor 2 output should not include 可预测性 line."""
        output_section = factor2_text.split("## 因子2输出")[-1]
        assert "可预测性：[高" not in output_section

    def test_factor2_references_shared_tables(self, factor2_text):
        """Factor 2 should reference shared_tables.md for tax rates (v1.1: centralized)."""
        assert "shared_tables.md" in factor2_text

    def test_factor2_preserves_veto(self, factor2_text):
        """Factor 2 should preserve the veto gate rules."""
        assert "一票否决" in factor2_text

    def test_phase3_factor2_step_count(self, phase3_text):
        """Phase 3 executor should reference 步骤1-4 for factor 2."""
        assert "步骤1-4" in phase3_text

    def test_phase3_factor2_step2_veto(self, phase3_text):
        """Phase 3 executor should say step 2 is the veto."""
        assert "步骤2分配能力验证" in phase3_text

    def test_factor3_has_willingness(self, factor3_text):
        """Factor 3 should now contain 分配意愿评估."""
        assert "分配意愿评估" in factor3_text

    def test_factor3_has_predictability(self, factor3_text):
        """Factor 3 should now contain 可预测性评级."""
        assert "可预测性评级" in factor3_text

    def test_factor3_output_has_willingness(self, factor3_text):
        """Factor 3 output section should include 分配意愿."""
        output_section = factor3_text.split("## 因子3输出")[-1]
        assert "分配意愿" in output_section

    def test_factor3_output_has_predictability(self, factor3_text):
        """Factor 3 output section should include 可预测性."""
        output_section = factor3_text.split("## 因子3输出")[-1]
        assert "可预测性" in output_section

    def test_factor4_willingness_source_updated(self, factor4_text):
        """Factor 4 value trap check should reference 因子3分配意愿."""
        assert "因子3分配意愿" in factor4_text
        assert "因子2分配意愿" not in factor4_text


# ── Optimization C: Phase 1B early start ─────────────────────────────


class TestOptimizationCPhase1BEarlyStart:
    """Phase 1B should start immediately after Phase 1A, not wait for 2A."""

    def test_coordinator_no_wait_both(self, coordinator_text):
        """Coordinator should NOT say 'wait for 1A + 2A both complete'."""
        assert "等待 Phase 1A + Phase 2A 都完成后再启动" not in coordinator_text

    def test_coordinator_1b_after_1a(self, coordinator_text):
        """Coordinator should say Phase 1B starts after Phase 1A."""
        assert "Phase 1A 完成后立即启动" in coordinator_text

    def test_coordinator_section10_check(self, coordinator_text):
        """Coordinator should mention §10 checks for pdf_sections.json."""
        assert "§10" in coordinator_text
        assert "pdf_sections.json" in coordinator_text

    def test_coordinator_section7_8_independent(self, coordinator_text):
        """Coordinator should note §7/§8/§9B don't depend on pdf_sections."""
        has_independent = ("不依赖" in coordinator_text and
                          "pdf_sections" in coordinator_text)
        assert has_independent


# ===== Feature #93: §17 pre-computed metrics prompt references =====


class TestSection17PromptReferences:
    """Test that Phase 3 prompts reference §17 pre-computed metrics."""

    def test_phase3_step1_mentions_section17(self, phase3_text):
        """Phase 3 Step 1 should mention checking §17."""
        assert "§17" in phase3_text

    def test_factor2_references_section172(self, factor2_text):
        """Factor 2 should reference §17.2 for pre-computed inputs."""
        assert "§17.2" in factor2_text
        assert "预计算" in factor2_text

    def test_factor3_references_section173(self, factor3_text):
        """Factor 3 step 1 should reference §17.3 for true cash revenue."""
        assert "§17.3" in factor3_text

    def test_factor3_references_section174(self, factor3_text):
        """Factor 3 step 4 should reference §17.4 for operating outflows."""
        assert "§17.4" in factor3_text

    def test_factor3_references_section175(self, factor3_text):
        """Factor 3 step 7 should reference §17.5 for base surplus."""
        assert "§17.5" in factor3_text

    def test_factor4_references_section176(self, factor4_text):
        """Factor 4 should reference §17.6 for price percentiles."""
        assert "§17.6" in factor4_text

    def test_all_references_have_fallback(self, factor2_text, factor3_text, factor4_text):
        """All §17 references should include fallback instruction."""
        for text in [factor2_text, factor3_text, factor4_text]:
            assert "缺失" in text  # fallback when §17.X is missing


# ── Feature #95: Factor 4 §17.8 prompt updates ──────────────────────


class TestFeature95Factor4Step5:
    """Factor 4 prompt should include Step 5 for absolute valuation + baseline."""

    def test_factor4_step5_exists(self, factor4_text):
        """步骤5 and 绝对估值 should be in factor4."""
        assert "步骤5" in factor4_text
        assert "绝对估值" in factor4_text

    def test_factor4_references_section178(self, factor4_text):
        """Factor 4 should reference §17.8 for EV baseline."""
        assert "§17.8" in factor4_text

    def test_factor4_baseline_in_output(self, factor4_text):
        """Factor 4 output template should include 基准价."""
        assert "基准价" in factor4_text

    def test_factor4_178_fallback(self, factor4_text):
        """§17.8 reference should have fallback instruction."""
        assert "缺失" in factor4_text
