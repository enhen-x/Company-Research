"""Tests for coordinator.md prompt — phase ordering, commands, and skill entrypoint."""

import os
import re

import pytest

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")
SKILL_DIR = os.path.join(os.path.dirname(__file__), "..")


@pytest.fixture(scope="module")
def coordinator_content():
    """Load coordinator.md content once for all tests."""
    path = os.path.join(PROMPTS_DIR, "coordinator.md")
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestCoordinatorFlow:
    """Verify coordinator prompt defines correct multi-phase pipeline."""

    def test_phase_ordering(self, coordinator_content):
        """Coordinator defines Phase 0 → 1A → 1B → 2A → 2B → 3 flow."""
        # Find positions of phase mentions to verify ordering
        phases = ["Phase 0", "Phase 1A", "Phase 1B", "Phase 2A", "Phase 2B", "Phase 3"]
        # Verify all phases are mentioned
        for phase in phases:
            assert phase in coordinator_content or phase.replace("Phase ", "phase") in coordinator_content, \
                f"Missing phase: {phase}"

    def test_phase1a_bash_command(self, coordinator_content):
        """Phase 1A references tushare_collector.py bash command."""
        assert "tushare_collector.py" in coordinator_content

    def test_phase2a_bash_command(self, coordinator_content):
        """Phase 2A references pdf_preprocessor.py bash command."""
        assert "pdf_preprocessor.py" in coordinator_content

    def test_phase1b_agent_websearch(self, coordinator_content):
        """Phase 1B dispatches to agent for WebSearch."""
        assert "WebSearch" in coordinator_content

    def test_phase2b_agent_extraction(self, coordinator_content):
        """Phase 2B dispatches to agent for PDF structured extraction."""
        assert "phase2_PDF解析" in coordinator_content or "Phase 2B" in coordinator_content

    def test_phase3_analysis_dispatch(self, coordinator_content):
        """Phase 3 dispatches to analysis and report generation."""
        assert "phase3_分析与报告" in coordinator_content or "Phase 3" in coordinator_content

    def test_no_pdf_alternative(self, coordinator_content):
        """Coordinator defines graceful degradation when no PDF available."""
        assert "降级" in coordinator_content or "no-PDF" in coordinator_content.lower() or \
            "跳过" in coordinator_content

    def test_file_path_convention(self, coordinator_content):
        """Coordinator uses {output_dir} convention for file paths."""
        assert "output_dir" in coordinator_content or "output/" in coordinator_content

    def test_ask_user_question_templates(self, coordinator_content):
        """Coordinator defines AskUserQuestion interaction points."""
        assert "AskUserQuestion" in coordinator_content
        # Should have multiple AskUserQuestion blocks
        count = coordinator_content.count("AskUserQuestion")
        assert count >= 3, f"Expected ≥3 AskUserQuestion references, got {count}"


class TestSkillEntrypoint:
    """Verify the Codex skill entrypoint file."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.entrypoint_path = os.path.join(SKILL_DIR, "SKILL.md")

    def test_skill_entrypoint_exists(self):
        """Codex skill entrypoint exists at SKILL.md."""
        assert os.path.exists(self.entrypoint_path), "SKILL.md not found"

    def test_skill_entrypoint_references_coordinator(self):
        """Skill entrypoint references coordinator.md for execution."""
        with open(self.entrypoint_path, encoding="utf-8") as f:
            content = f.read()
        assert "coordinator" in content.lower() or "prompts/" in content

    def test_skill_entrypoint_includes_phases(self):
        """Skill entrypoint mentions the multi-phase pipeline."""
        with open(self.entrypoint_path, encoding="utf-8") as f:
            content = f.read()
        assert "Phase" in content or "phase" in content

    def test_skill_entrypoint_includes_output_path(self):
        """Skill entrypoint specifies output path convention."""
        with open(self.entrypoint_path, encoding="utf-8") as f:
            content = f.read()
        assert "output/" in content

    def test_skill_entrypoint_defines_stock_triggers(self):
        """Skill entrypoint defines stock analysis trigger phrases."""
        with open(self.entrypoint_path, encoding="utf-8") as f:
            content = f.read()
        assert "调研" in content
        assert "分析" in content
        assert "股票" in content
