"""Runtime boundaries and owned-artifact cleanup for template regression."""
import math
from pathlib import Path
import subprocess
import sys
import time

import pytest

import template_regression as regression


def fake_worker(result, seen):
    def run(command, **kwargs):
        seen.update(command=command, options=kwargs)
        project = Path(command[command.index("--out") + 1])
        scratch = Path(command[command.index("--_scratch") + 1])
        seen.update(project=project, scratch=scratch)
        (project / "reports").mkdir(parents=True, exist_ok=True)
        (project / "reports" / "fixture.txt").write_text("generated", encoding="utf-8")
        (scratch / "negative-template.txt").write_text("generated", encoding="utf-8")
        return dict(result, output="fixture output")
    return run


@pytest.mark.parametrize("status,exit_code,expected", [("PASS", 0, 0), ("FAIL", 1, 1), ("TIMEOUT", -1, 2)])
@pytest.mark.parametrize("selfcheck", [False, True])
def test_parent_cleans_owned_output_and_negative_templates_for_all_exits(tmp_path, monkeypatch, status, exit_code, expected, selfcheck):
    seen = {}
    monkeypatch.setattr(regression, "run_process", fake_worker({"status": status, "exit_code": exit_code}, seen))
    project = tmp_path / "owned-output"
    args = ["--out", str(project)] + (["--selfcheck"] if selfcheck else [])
    assert regression.main(args) == expected
    assert not project.exists()
    assert not seen["scratch"].exists()
    assert seen["options"]["timeout"] == 1200
    assert seen["options"]["heartbeat"] == 10
    assert "--stage-timeout" in seen["command"]
    assert seen["command"][seen["command"].index("--stage-timeout") + 1] == "300.0"


def test_default_project_stays_in_parent_temp_and_does_not_touch_cwd(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(regression, "run_process", fake_worker({"status": "PASS", "exit_code": 0}, seen))
    assert regression.main([]) == 0
    assert not seen["project"].exists()
    assert list(tmp_path.iterdir()) == []


def test_keep_preserves_partial_output_but_still_cleans_temporary_templates(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(regression, "run_process", fake_worker({"status": "TIMEOUT", "exit_code": -1}, seen))
    project = tmp_path / "kept-output"
    assert regression.main(["--out", str(project), "--keep", "--selfcheck"]) == 2
    assert (project / "reports" / "fixture.txt").read_text(encoding="utf-8") == "generated"
    assert not seen["scratch"].exists()


def test_existing_user_directory_is_not_overwritten_or_deleted(tmp_path, monkeypatch):
    project = tmp_path / "existing"
    project.mkdir()
    (project / "owned.txt").write_text("original", encoding="utf-8")
    monkeypatch.setattr(regression, "run_process", lambda *a, **k: pytest.fail("worker must not run"))
    assert regression.main(["--out", str(project)]) == 2
    assert (project / "owned.txt").read_text(encoding="utf-8") == "original"


def test_stage_timeout_is_explicit_and_cannot_count_as_negative_qc(monkeypatch):
    seen = {}
    def timeout(command, **kwargs):
        seen.update(kwargs)
        return {"status": "TIMEOUT", "exit_code": 1, "output": "[FAIL] G8-RENDER: 图04 数据标注互相重叠"}
    monkeypatch.setattr(regression, "run_process", timeout)
    with pytest.raises(TimeoutError):
        regression.run([sys.executable, "fixture.py"], timeout=.5, heartbeat=.1)
    assert seen["timeout"] == .5
    assert seen["heartbeat"] == .1


def test_real_parent_overall_timeout_removes_partial_output(tmp_path):
    project = tmp_path / "timeout-output"
    started = time.monotonic()
    result = subprocess.run([sys.executable, str(Path(regression.__file__)), "--out", str(project),
                             "--total-timeout", ".2", "--heartbeat", ".1"],
                            capture_output=True, encoding="utf-8", errors="replace", timeout=15)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "TIMEOUT" in result.stdout
    assert not project.exists()
    assert time.monotonic() - started < 15


@pytest.mark.parametrize("option,value", [("--total-timeout", "nan"), ("--stage-timeout", "0"), ("--heartbeat", "-1")])
def test_invalid_budgets_fail_before_creating_output(tmp_path, option, value):
    project = tmp_path / "invalid-output"
    with pytest.raises(SystemExit) as error:
        regression.main(["--out", str(project), option, value])
    assert error.value.code == 2
    assert not project.exists()
