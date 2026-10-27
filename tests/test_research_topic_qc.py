"""Report links validate structure and provenance freshness, never truth of a claim."""
import copy
import json
from pathlib import Path

import pytest

import research_topic_qc as qc


@pytest.fixture
def project(tmp_path):
    (tmp_path / "input").mkdir()
    (tmp_path / "reports").mkdir()
    config = {"schema_version": 1, "as_of": "2026-10-28",
              "facts": {"entity": {"id": "TEST", "name": "测试公司"}, "records": [
                  {"id": "fact1", "value": 1, "unit": "CNY", "period": "2025",
                   "source": {"title": "年报", "locator": "第1页"}}]},
              "report_bindings": [{"module": "guidance", "section": "3.4", "refs": ["fact1"]}]}
    (tmp_path / "input" / "研究模型.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "reports" / "主报告.md").write_text(
        "### 3.4 管理层、治理与资本配置\n尚未做研究判断。\n研究模型_输出.json\n", encoding="utf-8")
    return tmp_path


def _output(project):
    return project / "reports" / "研究模型_输出.json"


def _run(project, **kwargs):
    return qc.run(project, project / "reports" / "主报告.md", **kwargs)


@pytest.mark.parametrize("module,section,refs", [
    ([], "3.4", ["fact1"]), ({}, "3.4", ["fact1"]),
    ("guidance", [], ["fact1"]), ("guidance", {}, ["fact1"]),
    ("guidance", "3.4", {}), ("guidance", "3.4", "fact1"),
    ("guidance", "3.4", [["fact1"]]), ("guidance", "3.4", [{"id": "fact1"}]),
    ("guidance", "3.4", []), (None, None, None),
])
def test_bad_binding_types_are_structured_invalid_not_uncaught(project, module, section, refs):
    source = project / "input" / "研究模型.json"
    config = json.loads(source.read_text(encoding="utf-8"))
    config["report_bindings"] = [{"module": module, "section": section, "refs": refs}]
    source.write_text(json.dumps(config), encoding="utf-8")

    result, code = _run(project)
    assert code != 0
    assert result["report_check"]["status"] == "INVALID"
    assert result["report_check"]["findings"]
    assert "error" not in result


def test_same_inputs_keep_output_mtime_and_check_only_writes_nothing(project):
    first, code = _run(project)
    assert code == 0
    output = _output(project)
    before = {p.relative_to(project).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
              for p in project.rglob("*") if p.is_file()}

    again, code = _run(project)
    assert code == 0
    assert again == first
    assert output.stat().st_mtime_ns == before[output.relative_to(project).as_posix()][1]
    checked, code = _run(project, check_only=True)
    assert code == 0
    assert checked == first
    after = {p.relative_to(project).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
             for p in project.rglob("*") if p.is_file()}
    assert after == before


@pytest.mark.parametrize("changed", ["input", "report", "code"])
def test_check_only_rejects_changed_input_code_or_report_and_preserves_saved_output(project, monkeypatch, changed):
    _run(project)
    saved = _output(project).read_bytes()
    saved_mtime = _output(project).stat().st_mtime_ns
    if changed == "input":
        # Even raw text changes must be observable when semantic JSON is identical.
        source = project / "input" / "研究模型.json"
        source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    elif changed == "report":
        report = project / "reports" / "主报告.md"
        report.write_text(report.read_text(encoding="utf-8") + "正文增加一句。\n", encoding="utf-8")
    else:
        fingerprints = qc.code_fingerprint()
        monkeypatch.setattr(qc, "code_fingerprint", lambda: {**fingerprints, "research_topics.py": "changed"})

    result, code = _run(project, check_only=True)
    assert code != 0
    assert result["check_error"]
    assert _output(project).read_bytes() == saved
    assert _output(project).stat().st_mtime_ns == saved_mtime


def test_changed_report_is_detected_even_without_bindings(project):
    source = project / "input" / "研究模型.json"
    config = json.loads(source.read_text(encoding="utf-8"))
    config.pop("report_bindings")
    source.write_text(json.dumps(config), encoding="utf-8")
    first, _ = _run(project)
    assert first["report_check"]["status"] == "NOT_ASSESSED"
    report = project / "reports" / "主报告.md"
    report.write_text("正文全部替换", encoding="utf-8")

    result, code = _run(project, check_only=True)
    assert code != 0
    assert result["check_error"]


def test_missing_or_removed_input_is_not_complete_and_check_only_creates_no_files(tmp_path):
    result, code = qc.run(tmp_path, require_complete=True)
    assert code != 0
    assert result["status"] == "INCOMPLETE"
    assert not list(tmp_path.iterdir())
    result, code = qc.run(tmp_path, check_only=True)
    assert code != 0
    assert result["check_error"]
    assert not list(tmp_path.iterdir())


def test_missing_saved_output_is_not_rebuilt_in_check_only(project):
    result, code = _run(project, check_only=True)
    assert code != 0
    assert result["status"] == "INVALID"
    assert not _output(project).exists()


def test_require_complete_rejects_partial_research_despite_valid_report_links(project):
    result, code = _run(project, require_complete=True)
    assert code != 0
    assert result["status"] == "INCOMPLETE"
    assert result["report_check"]["status"] == "STRUCTURE_CHECKED"
    assert result["quality"]["human_review"] == "NOT_ASSESSED"
    assert result["human_review"] == "NOT_ASSESSED"


def test_report_structure_does_not_endorse_false_or_unrelated_prose(project):
    report = project / "reports" / "主报告.md"
    report.write_text("### 3.4 管理层、治理与资本配置\n完全没有支持任何指引结论的内容。\n研究模型_输出.json\n", encoding="utf-8")
    result, _ = _run(project)

    assert result["report_check"]["status"] == "STRUCTURE_CHECKED"
    assert result["quality"]["human_review"] == "NOT_ASSESSED"
    assert "仅验证章节存在和引用关系" in result["report_check"]["limitation"]


def test_binding_reference_must_exist_in_registry(project):
    source = project / "input" / "研究模型.json"
    config = json.loads(source.read_text(encoding="utf-8"))
    config["report_bindings"][0]["refs"] = ["made_up"]
    source.write_text(json.dumps(config), encoding="utf-8")
    result, code = _run(project)
    assert code != 0
    assert result["report_check"]["status"] == "INVALID"
    assert any("未解析" in finding for finding in result["report_check"]["findings"])


@pytest.mark.parametrize("payload", [b'\xff', b'{', b'{"a":' + b'[' * 150 + b'0' + b']' * 150 + b'}'])
@pytest.mark.parametrize("check_only", [False, True])
def test_input_boundary_is_shared_and_check_only_never_overwrites(project, payload, check_only):
    _run(project)
    saved = _output(project).read_bytes()
    (project / "input" / "研究模型.json").write_bytes(payload)
    result, code = _run(project, check_only=check_only)
    assert code != 0
    assert result["status"] == "INVALID"
    assert result["error"]
    if check_only:
        assert _output(project).read_bytes() == saved


def test_saved_output_boundary_is_checked_without_replacing_it(project):
    _run(project)
    depth = qc.MAX_OUTPUT_DEPTH + 2
    saved = b'[' * depth + b'0' + b']' * depth
    _output(project).write_bytes(saved)
    result, code = _run(project, check_only=True)
    assert code != 0
    assert result["status"] == "INVALID"
    assert _output(project).read_bytes() == saved


def test_capital_implementation_is_part_of_check_only_fingerprint(project, monkeypatch):
    first, _ = _run(project)
    assert "capital_metrics.py" in first["code_fingerprint"]
    original_fingerprint = qc.code_fingerprint

    def revised_fingerprint():
        result = original_fingerprint()
        result["capital_metrics.py"] = "revised-capital-implementation"
        return result

    saved = _output(project).read_bytes()
    monkeypatch.setattr(qc, "code_fingerprint", revised_fingerprint)
    result, code = _run(project, check_only=True)
    assert code != 0
    assert result["check_error"]
    assert _output(project).read_bytes() == saved


def test_oversized_model_is_rejected_before_unbounded_read(project, monkeypatch):
    import research_topics
    monkeypatch.setattr(research_topics, "MAX_INPUT_BYTES", 10)
    source = project / "input" / "研究模型.json"
    original_read = Path.read_bytes

    def refuse_input_read(path):
        if path == source:
            raise AssertionError("unbounded source read")
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", refuse_input_read)
    result, code = _run(project, check_only=True)
    assert code != 0
    assert "研究模型输入超过" in result["error"]
    assert not _output(project).exists()


def test_output_larger_than_input_budget_can_be_verified_without_rewrite(tmp_path):
    from tests.test_research_topics import _base
    config = _base()
    config["assumptions"][0]["reason"] = "x" * 5_100_000
    source = tmp_path / "input" / "研究模型.json"
    source.parent.mkdir()
    source.write_text(json.dumps(config), encoding="utf-8")
    assert source.stat().st_size < 10_000_000
    result, code = qc.run(tmp_path)
    assert code == 0 and result["status"] == "OK"
    output = _output(tmp_path)
    assert 10_000_000 < output.stat().st_size <= qc.MAX_OUTPUT_BYTES
    before = (output.read_bytes(), output.stat().st_mtime_ns)
    verified, code = qc.run(tmp_path, check_only=True)
    assert code == 0 and verified == result
    assert (output.read_bytes(), output.stat().st_mtime_ns) == before


def test_generated_output_must_fit_its_own_read_contract(project, monkeypatch):
    monkeypatch.setattr(qc, "MAX_OUTPUT_BYTES", 2000)
    result, code = _run(project)
    assert code == 1 and result["status"] == "INVALID"
    assert "研究模型输出超过" in result["error"]
    output = _output(project)
    assert output.stat().st_size <= qc.MAX_OUTPUT_BYTES
    assert qc.read_output(output)[1] == result
    before = (output.read_bytes(), output.stat().st_mtime_ns)
    checked, code = _run(project, check_only=True)
    assert code == 1 and checked["status"] == "INVALID"
    assert (output.read_bytes(), output.stat().st_mtime_ns) == before


def test_output_depth_budget_is_separate_from_input_and_validated_before_write(tmp_path):
    import research_topics
    value = 0
    for _ in range(research_topics.MAX_INPUT_DEPTH + 3):
        value = [value]
    output = tmp_path / "saved.json"
    output.write_text(json.dumps(value), encoding="utf-8")
    qc.validate_output(value)
    assert qc.read_output(output)[1] == value
    with pytest.raises(ValueError, match="嵌套"):
        research_topics.read_input(output)
    for _ in range(qc.MAX_OUTPUT_DEPTH):
        value = [value]
    with pytest.raises(ValueError, match="研究模型输出嵌套"):
        qc.validate_output(value)


@pytest.mark.parametrize("after_stat", [False, True])
def test_saved_output_read_has_stat_and_read_growth_limits(monkeypatch, after_stat):
    import io
    from types import SimpleNamespace
    monkeypatch.setattr(qc, "MAX_OUTPUT_BYTES", 100)
    observed = []

    class BoundedStream(io.BytesIO):
        def read(self, size=-1):
            observed.append(size)
            return super().read(size)

    class SavedPath:
        def stat(self):
            return SimpleNamespace(st_size=99 if after_stat else 101)

        def open(self, mode):
            assert after_stat, "oversized saved output must be rejected before opening"
            return BoundedStream(b" " * 101)

    with pytest.raises(ValueError, match="研究模型输出超过"):
        qc.read_output(SavedPath())
    assert observed == ([101] if after_stat else [])
