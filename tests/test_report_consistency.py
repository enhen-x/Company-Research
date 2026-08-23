"""Tests for scripts/report_consistency.py — 杠杆6 cross-passage audit + 杠杆7 gates."""

import os

import pytest

import report_consistency as rc
from report_consistency import extract, find_conflicts, check_gates, main

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                       "sample_report_with_conflicts.md")


@pytest.fixture(scope="module")
def report_text():
    with open(FIXTURE, "r", encoding="utf-8") as f:
        return f.read()


# ── extraction & masking ────────────────────────────────────────────

class TestExtraction:
    def test_src_number_skipped(self, report_text):
        """The 999.99 亿 inside [src: ...] must never be extracted."""
        clusters = extract(report_text)
        vals = [o.value for obs in clusters.values() for o in obs]
        assert 999.99 not in vals

    def test_bare_year_not_a_metric(self, report_text):
        """A bare '2024' (no unit) must not be extracted as a value."""
        clusters = extract(report_text)
        vals = [o.value for obs in clusters.values() for o in obs]
        assert 2024 not in vals and 2024.0 not in vals

    def test_revenue_cluster_built(self, report_text):
        clusters = extract(report_text)
        assert ("营业收入", "2024") in clusters
        vals = sorted({round(o.value, 2) for o in clusters[("营业收入", "2024")]})
        assert 500.0 in vals and 560.0 in vals

    def test_margin_cluster_built(self, report_text):
        clusters = extract(report_text)
        assert ("毛利率", "2024") in clusters
        vals = sorted({round(o.value, 2) for o in clusters[("毛利率", "2024")]})
        assert 47.6 in vals and 49.2 in vals

    def test_nearest_keyword_classification(self):
        """营业利润 next to the number wins over a farther 归母 keyword."""
        txt = "2024 年营业利润 122.51 亿，归母 89.54 亿。"
        clusters = extract(txt)
        assert ("营业利润", "2024") in clusters
        assert ("归母净利润", "2024") in clusters
        prof = [round(o.value, 2) for o in clusters[("营业利润", "2024")]]
        assert prof == [122.51]


# ── conflict detection ──────────────────────────────────────────────

class TestConflicts:
    def test_default_tolerance_flags_revenue(self, report_text):
        conflicts = find_conflicts(extract(report_text), 0.05)
        cats = {(c["category"], c["year"]) for c in conflicts}
        assert ("营业收入", "2024") in cats            # 500 vs 560 = 10.7% > 5%
        assert ("毛利率", "2024") not in cats          # 3.3% < 5% → within tol

    def test_tight_tolerance_flags_margin(self, report_text):
        conflicts = find_conflicts(extract(report_text), 0.02)
        cats = {(c["category"], c["year"]) for c in conflicts}
        assert ("营业收入", "2024") in cats
        assert ("毛利率", "2024") in cats              # 3.3% > 2%

    def test_identical_values_deduped(self):
        """Same value repeated is not a conflict."""
        txt = "2024 年营业收入 500.00 亿。后文重申 2024 年营业收入 500.00 亿。"
        conflicts = find_conflicts(extract(txt), 0.05)
        assert conflicts == []


# ── hard gates (杠杆7) ───────────────────────────────────────────────

class TestGates:
    def test_short_dimensions_fail(self, report_text):
        failures = check_gates(report_text)
        assert any("维度一" in f for f in failures)
        assert any("维度二" in f for f in failures)

    def test_conditional_dim6_skipped_when_degraded(self, report_text):
        failures = check_gates(report_text)
        assert not any("维度六" in f for f in failures)   # 不适用 → skipped

    def test_required_sections_present(self, report_text):
        failures = check_gates(report_text)
        assert not any("数字溯源汇总" in f for f in failures)
        assert not any("结构化参数" in f for f in failures)

    def test_missing_required_section_flagged(self):
        txt = "## 维度一：商业模式\n" + ("字" * 700) + "\n## 维度二：护城河\n" + ("字" * 900)
        failures = check_gates(txt)
        assert any("数字溯源汇总" in f for f in failures)
        assert any("结构化参数" in f for f in failures)


# ── CLI ─────────────────────────────────────────────────────────────

class TestCLI:
    def test_main_conflicts_exit_1(self, tmp_path):
        out = tmp_path / "cons.md"
        rc_code = main(["--report", FIXTURE, "--output", str(out)])
        assert rc_code == 1
        assert out.exists()

    def test_main_missing_file_exit_2(self, tmp_path):
        rc_code = main(["--report", str(tmp_path / "nope.md")])
        assert rc_code == 2

    def test_main_clean_report_exit_0(self, tmp_path):
        clean = tmp_path / "clean.md"
        clean.write_text("# 报告\n\n## 维度一\n2024 年营业收入 500.00 亿，稳健增长。\n",
                         encoding="utf-8")
        rc_code = main(["--report", str(clean)])
        assert rc_code == 0

    def test_main_gates_exit_1(self, tmp_path):
        out = tmp_path / "g.md"
        rc_code = main(["--report", FIXTURE, "--output", str(out), "--gates"])
        assert rc_code == 1
        assert "硬门槛" in out.read_text(encoding="utf-8")
