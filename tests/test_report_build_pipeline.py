"""Observable contracts for the shared report build pipeline."""

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lXcAAAAASUVORK5CYII="
)


def test_renderer_keeps_previous_html_when_image_is_missing(tmp_path):
    report_dir = tmp_path / "reports"
    image_dir = report_dir / "图表"
    image_dir.mkdir(parents=True)
    (image_dir / "图01.png").write_bytes(PNG)
    source = report_dir / "测试_000001_分析报告.md"
    target = source.with_suffix(".html")
    source.write_text("# 测试报告\n\n## 一、摘要\n\n| 项目 | 值 |\n|---|---|\n| A | 1 |\n\n![图01](图表/图01.png)\n", encoding="utf-8")
    command = [sys.executable, str(SCRIPTS / "md_to_html.py"), "--input", str(source)]
    first = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    assert first.returncode == 0, first.stderr
    assert "data:image/png;base64" in target.read_text(encoding="utf-8")
    original = target.read_bytes()

    original_markdown = source.read_text(encoding="utf-8")
    source.write_text(original_markdown.replace("| A | 1 |", "| A | 2 |"), encoding="utf-8")
    stale = subprocess.run([*command, "--check"], capture_output=True, text=True, encoding="utf-8")
    assert stale.returncode != 0
    assert target.read_bytes() == original
    source.write_text(original_markdown, encoding="utf-8")

    (image_dir / "图01.png").unlink()
    second = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    assert second.returncode != 0
    assert target.read_bytes() == original


@pytest.mark.parametrize("trigger,expected", [(None, 1), ({"triggered": False}, 1), ({"enabled": False}, 0)])
def test_gate_requires_explicit_sotp_decision(tmp_path, trigger, expected):
    project = tmp_path / "batch"
    (project / "reports").mkdir(parents=True)
    (project / "input").mkdir()
    (project / "scripts").mkdir()
    (project / "input" / "图表豁免.json").write_text('{"豁免": []}', encoding="utf-8")
    (project / "reports" / "测试_000001_分析报告.md").write_text("# 测试\n", encoding="utf-8")
    if trigger is not None:
        (project / "input" / "sotp_触发.json").write_text(json.dumps(trigger), encoding="utf-8")
    for script in ("report_template_qc.py", "md_to_html.py", "financial_health_qc.py", "chart_period_qc.py", "chart_qc.py", "format_qc.py"):
        (project / "scripts" / script).write_text("pass\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "gate_all.py"), "--dir", str(project), "--check-only"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == expected, result.stdout + result.stderr


def test_renderer_rejects_legacy_amount_units_without_overwriting_previous_html(tmp_path):
    source=tmp_path/'测试_000001_分析报告.md'
    target=source.with_suffix('.html')
    source.write_text('# 分析报告\n\n市值1000百万元。\n',encoding='utf-8')
    target.write_text('previous valid artifact',encoding='utf-8')
    result=subprocess.run([sys.executable,str(SCRIPTS/'md_to_html.py'),'--input',str(source)],capture_output=True,text=True,encoding='utf-8')
    assert result.returncode != 0
    assert target.read_text(encoding='utf-8')=='previous valid artifact'
    source.write_text('# 分析报告\n\n市值10亿元。\n',encoding='utf-8')
    result=subprocess.run([sys.executable,str(SCRIPTS/'md_to_html.py'),'--input',str(source)],capture_output=True,text=True,encoding='utf-8')
    assert result.returncode==0,result.stderr
    assert '10亿元' in target.read_text(encoding='utf-8')
