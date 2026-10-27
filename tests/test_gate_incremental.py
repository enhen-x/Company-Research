"""Bounded, isolated regressions for gate reuse, lock ownership and total budgets."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from run_support import BatchLock, run_process


def _batch(tmp_path, *, build_delay=0):
    project = tmp_path / "synthetic_batch"
    for folder in ("input", "reports", "scripts", "data"):
        (project / folder).mkdir(parents=True)
    (project / "input/图表豁免.json").write_text('{"豁免":[]}', encoding="utf-8")
    (project / "input/sotp_触发.json").write_text('{"enabled":false}', encoding="utf-8")
    (project / "reports/测试_000001_分析报告.md").write_text("# synthetic report\n", encoding="utf-8")
    for filename in ("chart_qc.py", "chart_period_qc.py", "report_template_qc.py", "financial_health_qc.py"):
        (project / "scripts" / filename).write_text("pass\n", encoding="utf-8")
    (project / "scripts/format_qc.py").write_text(
        "from pathlib import Path\n"
        "p=Path('reports/quality_count.txt')\n"
        "p.write_text(str(int(p.read_text())+1) if p.exists() else '1')\n", encoding="utf-8")
    (project / "scripts/analyze_charts.py").write_text(
        "from pathlib import Path\nimport time\n"
        "p=Path('reports/build_count.txt')\n"
        "p.write_text(str(int(p.read_text())+1) if p.exists() else '1')\n"
        "Path('reports/builder_ready.txt').write_text('started')\n"
        f"time.sleep({build_delay!r})\n"
        "Path('reports/图表').mkdir(exist_ok=True)\n"
        "Path('reports/图表/图01.png').write_bytes(b'isolated synthetic artifact')\n", encoding="utf-8")
    (project / "scripts/md_to_html.py").write_text(
        "from pathlib import Path\nimport sys\n"
        "p=Path('reports/render_count.txt')\n"
        "p.write_text(str(int(p.read_text())+1) if p.exists() else '1')\n"
        "Path(sys.argv[sys.argv.index('--input')+1]).with_suffix('.html').write_text('<p>synthetic</p>')\n",
        encoding="utf-8")
    return project


def _gate(project, *extra, outer_timeout=20):
    return run_process(
        [sys.executable, "-B", "-X", "utf8", str(SCRIPTS / "gate_all.py"),
         "--dir", str(project), "--heartbeat", "0.2", *extra],
        timeout=outer_timeout, heartbeat=5, label="isolated gate regression", echo=False)


def _state(project):
    return json.loads((project / "reports/流水线执行状态.json").read_text(encoding="utf-8-sig"))


def _count(project, name):
    return int((project / "reports" / f"{name}_count.txt").read_text())


def _assert_pass(result):
    assert result["status"] == "PASS", result.get("output", result)


def test_batch_lock_is_nonblocking_and_releases_after_exception(tmp_path):
    path = tmp_path / ".gate.lock"
    with pytest.raises(ValueError, match="synthetic owner failure"):
        with BatchLock(path):
            started = time.monotonic()
            with pytest.raises(RuntimeError, match="同一批次正在运行"):
                with BatchLock(path):
                    pytest.fail("a second owner acquired the lock")
            assert time.monotonic() - started < 2
            raise ValueError("synthetic owner failure")
    with BatchLock(path):
        pass


def test_incremental_reuses_artifacts_but_reruns_quality_gates(tmp_path):
    project = _batch(tmp_path)
    _assert_pass(_gate(project))
    first = _state(project)
    chart = project / "reports/图表/图01.png"
    html = project / "reports/测试_000001_分析报告.html"
    original_mtimes = (chart.stat().st_mtime_ns, html.stat().st_mtime_ns)
    _assert_pass(_gate(project, "--incremental"))
    reused = _state(project)
    assert reused["run_id"] != first["run_id"]
    assert reused["reused_from_run_id"] == first["run_id"]
    assert reused["delivery_ready"] is True
    assert reused["build_completed"] is False and reused["fully_rebuilt"] is False
    assert [s["name"] for s in reused["stages"] if s["status"] == "REUSED"] == [
        "固定图表构建", "主报告 HTML 渲染与一致性"]
    assert _count(project, "build") == 1 and _count(project, "render") == 1
    assert _count(project, "quality") == 2
    assert (chart.stat().st_mtime_ns, html.stat().st_mtime_ns) == original_mtimes
    assert reused["artifacts"] == first["artifacts"]
    # Reuse remains valid for the next invocation; it does not require the
    # immediately preceding invocation to claim a fresh build.
    _assert_pass(_gate(project, "--incremental"))
    assert _state(project)["reused_from_run_id"] == reused["run_id"]
    assert _count(project, "build") == 1 and _count(project, "quality") == 3


@pytest.mark.parametrize("mutation", ["chart_bytes", "html_bytes", "missing_chart"])
def test_artifact_tampering_or_removal_forces_full_rebuild(tmp_path, mutation):
    project = _batch(tmp_path)
    _assert_pass(_gate(project))
    chart = project / "reports/图表/图01.png"
    if mutation == "missing_chart":
        chart.unlink()
    elif mutation == "chart_bytes":
        chart.write_bytes(b"changed synthetic chart")
    else:
        (project / "reports/测试_000001_分析报告.html").write_text("changed html", encoding="utf-8")
    _assert_pass(_gate(project, "--incremental"))
    state = _state(project)
    assert "reused_from_run_id" not in state
    assert state["fully_rebuilt"] is True and state["build_completed"] is True
    assert not any(s["status"] == "REUSED" for s in state["stages"])
    assert _count(project, "build") == 2 and _count(project, "render") == 2
    assert chart.read_bytes() == b"isolated synthetic artifact"


def test_code_change_forces_full_rebuild(tmp_path):
    project = _batch(tmp_path)
    _assert_pass(_gate(project))
    first = _state(project)
    (project / "scripts/chart_qc.py").write_text("pass\n# synthetic code version 2\n", encoding="utf-8")
    _assert_pass(_gate(project, "--incremental"))
    state = _state(project)
    assert state["input_fingerprint"] != first["input_fingerprint"]
    assert state["fully_rebuilt"] is True
    assert _count(project, "build") == 2 and _count(project, "render") == 2


def test_total_budget_leaves_timeout_ledger_and_terminates_worker(tmp_path):
    project = _batch(tmp_path, build_delay=20)
    started = time.monotonic()
    result = _gate(project, "--stage-timeout", "30", "--total-timeout", "2", outer_timeout=12)
    assert result["status"] == "FAIL", result
    assert time.monotonic() - started < 10
    state = _state(project)
    assert state["status"] == "TIMEOUT"
    assert all(state[key] is False for key in ("technical_pass", "delivery_ready", "build_completed", "fully_rebuilt"))
    assert any(s["status"] == "TIMEOUT" for s in state["stages"])
    assert not any(s["status"] in ("PENDING", "RUNNING") for s in state["stages"])
    assert not (project / "reports/图表/图01.png").exists()
    with BatchLock(project / "reports/.gate.lock"):
        pass


def test_concurrent_invocation_cannot_replace_running_run_id(tmp_path):
    project = _batch(tmp_path, build_delay=4)
    ready = project / "reports/builder_ready.txt"
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(_gate, project)
        deadline = time.monotonic() + 10
        while not ready.exists() and not running.done() and time.monotonic() < deadline:
            time.sleep(.02)
        assert ready.exists(), running.result(timeout=15)
        owner = _state(project)
        assert owner["status"] == "RUNNING"
        rejected = _gate(project)
        assert rejected["status"] == "FAIL"
        assert "同一批次正在运行" in rejected["output"]
        assert _state(project)["run_id"] == owner["run_id"]
        _assert_pass(running.result(timeout=15))
    assert _state(project)["run_id"] == owner["run_id"]
    assert _state(project)["status"] == "PASS"


def test_total_timeout_before_lock_does_not_overwrite_other_owner_ledger(tmp_path):
    project = _batch(tmp_path)
    path = project / "reports/流水线执行状态.json"
    original = '{"run_id":"existing-owner","status":"RUNNING","stages":[]}'
    path.write_text(original, encoding="utf-8")
    with BatchLock(project / "reports/.gate.lock"):
        result = _gate(project, "--total-timeout", "0.001", outer_timeout=8)
    assert result["status"] == "FAIL", result
    assert path.read_text(encoding="utf-8") == original
