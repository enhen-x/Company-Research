"""Offline regressions for repeatable script sync and scaffold preservation."""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import research_pipeline as pipeline


@pytest.fixture
def script_sources(tmp_path, monkeypatch):
    local = tmp_path / "v3"
    legacy = tmp_path / "legacy"
    local.mkdir()
    legacy.mkdir()
    names = ["verification.py", "calc_penetration_return.py", "build_penetration_input.py"]
    for name in names:
        (local / name).write_text(f"# current v3 {name}\n", encoding="utf-8")
        (legacy / name).write_text(f"# legacy {name}\n", encoding="utf-8")
    monkeypatch.setattr(pipeline, "_skill_scripts_dir", lambda: local)
    monkeypatch.setattr(pipeline, "_guigui_scripts_dir", lambda: legacy)
    monkeypatch.setattr(pipeline, "TEMPLATE_SCRIPTS", names)
    monkeypatch.setattr(pipeline, "TODAY", datetime(2026, 10, 28, 12))
    return local, legacy


def snapshot(root):
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*") if path.is_file()
    }


def stamp_files(root):
    # A distinctive timestamp detects redundant copy2/write calls without sleeps.
    for path in root.rglob("*"):
        if path.is_file():
            os.utime(path, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))


def test_sync_prefers_current_v3_and_records_actual_source(script_sources, tmp_path):
    local, _ = script_sources
    batch = tmp_path / "batch"
    status = pipeline.copy_template_scripts(batch)
    manifest = json.loads((batch / "scripts" / "复制清单.json").read_text(encoding="utf-8"))
    assert all(value.startswith("✅") for value in status.values())
    assert manifest["status"] == status
    for name in pipeline.TEMPLATE_SCRIPTS:
        content = (local / name).read_bytes()
        assert (batch / "scripts" / name).read_bytes() == content
        assert manifest["files"][name] == {
            "source": str((local / name).resolve()),
            "sha256": hashlib.sha256(content).hexdigest(),
        }


def test_legacy_fallback_is_limited_to_guigui_scripts(script_sources, tmp_path):
    local, legacy = script_sources
    (local / "build_penetration_input.py").unlink()
    (local / "verification.py").unlink()
    batch = tmp_path / "batch"
    status = pipeline.copy_template_scripts(batch)
    assert status["build_penetration_input.py"].startswith("✅")
    assert status["verification.py"].startswith("⚠️")
    assert not (batch / "scripts" / "verification.py").exists()
    manifest = json.loads((batch / "scripts" / "复制清单.json").read_text(encoding="utf-8"))
    assert "verification.py" not in manifest["files"]
    assert manifest["files"]["build_penetration_input.py"]["source"] == str(
        (legacy / "build_penetration_input.py").resolve()
    )
    assert (batch / "scripts" / "build_penetration_input.py").read_bytes() == (
        legacy / "build_penetration_input.py"
    ).read_bytes()


@pytest.mark.parametrize("broken_manifest", ["{bad", "[]", "null", "42"])
def test_sync_recovers_damaged_or_nonobject_manifest(script_sources, tmp_path, broken_manifest):
    batch = tmp_path / "batch"
    destination = batch / "scripts"
    destination.mkdir(parents=True)
    (destination / "复制清单.json").write_text(broken_manifest, encoding="utf-8")
    status = pipeline.copy_template_scripts(batch)
    manifest = json.loads((destination / "复制清单.json").read_text(encoding="utf-8"))
    assert manifest["status"] == status
    assert set(manifest["files"]) == set(pipeline.TEMPLATE_SCRIPTS)
    assert manifest["copied_at"]
    assert not list(batch.rglob("*.tmp"))


def test_unchanged_sync_preserves_bytes_and_mtimes(script_sources, tmp_path):
    batch = tmp_path / "batch"
    first_status = pipeline.copy_template_scripts(batch)
    stamp_files(batch)
    before = snapshot(batch)
    assert pipeline.copy_template_scripts(batch) == first_status
    assert snapshot(batch) == before


def test_sync_updates_changed_script_and_manifest_only(script_sources, tmp_path):
    local, _ = script_sources
    batch = tmp_path / "batch"
    pipeline.copy_template_scripts(batch)
    stamp_files(batch)
    before = snapshot(batch)
    (local / "verification.py").write_text("# updated verifier\n", encoding="utf-8")
    pipeline.copy_template_scripts(batch)
    after = snapshot(batch)
    changed = {name for name in before if before[name] != after[name]}
    assert changed == {"scripts/verification.py", "scripts/复制清单.json"}
    assert (batch / "scripts" / "verification.py").read_bytes() == (local / "verification.py").read_bytes()
    manifest = json.loads((batch / "scripts" / "复制清单.json").read_text(encoding="utf-8"))
    assert manifest["files"]["verification.py"]["sha256"] == hashlib.sha256(
        (local / "verification.py").read_bytes()
    ).hexdigest()


def test_scaffold_creates_required_files_and_reuses_them(script_sources, tmp_path):
    project = tmp_path / "SYNTHETIC"
    batch = pipeline.scaffold(project, "SYNTHETIC", "000000", "合成测试", "待分析")
    assert batch == project / "2026_10_28"
    for directory in ["data", "input", "scripts", "reports/图表"]:
        assert (batch / directory).is_dir()
    required = [
        project / "财报更新验证.md", batch / "README.md", batch / "ROADMAP.md",
        batch / "交付清单.md", batch / "input" / "图表豁免.json",
        batch / "input" / "判断记录.md", batch / "input" / "本期财报体检配置.json",
    ]
    assert all(path.is_file() and path.read_bytes() for path in required)
    assert isinstance(json.loads(required[-1].read_text(encoding="utf-8")), dict)
    stamp_files(project)
    before = snapshot(project)
    assert pipeline.scaffold(project, "SYNTHETIC", "000000", "合成测试", "已更新") == batch
    assert snapshot(project) == before


def test_scaffold_preserves_custom_work_and_previous_batch(script_sources, tmp_path):
    local, _ = script_sources
    project = tmp_path / "SYNTHETIC"
    batch = project / "2026_10_28"
    custom_files = {
        "财报更新验证.md": "# custom cross-period record\n",
        "2026_10_28/README.md": "# custom README\n",
        "2026_10_28/ROADMAP.md": "# custom roadmap\n",
        "2026_10_28/交付清单.md": "# custom delivery\n",
        "2026_10_28/input/判断记录.md": "# custom judgments\n",
        "2026_10_28/input/图表豁免.json": '{"豁免": ["custom"]}\n',
        "2026_10_28/input/本期财报体检配置.json": '{"custom": true}\n',
        "2026_10_28/data/source.csv": "value\n12\n",
        "2026_10_28/reports/report.md": "# custom report\n",
        "2026_10_28/scripts/custom.py": "# user analysis\n",
        "2026_10_27/README.md": "# previous batch\n",
    }
    for relative, content in custom_files.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    stamp_files(project)
    custom_before = snapshot(project)
    pipeline.scaffold(project, "SYNTHETIC", "000000", "合成测试", "待分析")
    (local / "verification.py").write_text("# refreshed verifier\n", encoding="utf-8")
    pipeline.scaffold(project, "SYNTHETIC", "000000", "合成测试", "待分析")
    after = snapshot(project)
    for relative, value in custom_before.items():
        assert after[relative] == value
    assert (batch / "scripts" / "verification.py").read_bytes() == (local / "verification.py").read_bytes()
    assert not list(project.rglob("*.tmp"))
