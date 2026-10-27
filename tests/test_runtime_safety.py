"""Runtime failures must finish, retain bounded evidence, and leave no duplicate files."""
import math
import sys
import time

import pytest

from run_support import atomic_json, run_process


def test_timeout_includes_pipe_inherited_by_orphan_child(tmp_path):
    marker = tmp_path / "late_write.txt"
    child = f"import time; from pathlib import Path; time.sleep(4); Path({str(marker)!r}).write_text('orphan')"
    parent = "import subprocess, sys; subprocess.Popen([sys.executable, '-c', " + repr(child) + "]); print('parent exited')"
    started = time.monotonic()
    result = run_process([sys.executable, "-c", parent], timeout=.8, heartbeat=.3, echo=False)
    assert result["status"] == "TIMEOUT"
    assert time.monotonic() - started < 5
    time.sleep(4.2)
    assert not marker.exists(), "descendant survived its bounded job"


def test_large_output_is_bounded_and_long_unterminated_line_does_not_hang():
    result = run_process([sys.executable, "-c", "import sys; sys.stdout.write('x'*3000000); sys.stdout.flush()"],
                         timeout=8, heartbeat=2, echo=False)
    assert result["status"] == "PASS"
    assert len(result["output"]) <= 12000
    assert result["output"].endswith("x" * 100)


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), -1, 0, True])
def test_non_finite_timeouts_are_rejected(timeout):
    with pytest.raises(ValueError):
        run_process([sys.executable, "-c", "pass"], timeout=timeout)


def test_atomic_json_reuses_identical_content_without_side_files(tmp_path):
    target = tmp_path / "状态.json"
    assert atomic_json(target, {"value": 0})
    previous = target.stat().st_mtime_ns
    assert atomic_json(target, {"value": 0}) is False
    assert target.stat().st_mtime_ns == previous
    assert list(tmp_path.iterdir()) == [target]
    with pytest.raises(ValueError):
        atomic_json(target, {"value": math.nan})
    assert target.stat().st_mtime_ns == previous
