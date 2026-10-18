"""Local reuse is content-bound and can never stand in for hosted case proof."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from release_tooling_support import load_tool
from qualification_fixture import visual_evidence

pre = load_tool("release.process_preflight")
candidate = load_tool("release.process_candidate")


@pytest.mark.parametrize("name", ["unknown", "scripts/release/new.py", ".github/workflows/package-vsix.yml",
    "src/codex_usage/reporting.py", "uv.lock", "scripts/usage_breakdown_fixture.py", "tests/new.py"])
def test_unknown_and_shared_changes_select_every_suite(name):
    assert pre.selection([name])[0] == list(pre.VISUALS)


def test_mapping_reports_each_path_and_preserves_deleted_old_names():
    chosen, reasons = pre.selection(["src/codex_usage/report_speed_old.py", "src/codex_usage/report_speed_new.py", "docs/note.md"])
    assert chosen == ["screenshots-allowance", "speed"]
    assert reasons["docs/note.md"] == [] and len(reasons) == 3


def test_actual_tracked_input_bytes_and_deletions_affect_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(candidate, "git", lambda *a, **k: "new.py\0old.py\0" if "-z" in a else "")
    (tmp_path / "new.py").write_text("new")
    (tmp_path / "old.py").write_text("old")
    before = candidate.inputs(tmp_path)
    (tmp_path / "new.py").write_text("changed")
    (tmp_path / "old.py").unlink()
    after = candidate.inputs(tmp_path)
    assert before["new.py"] != after["new.py"] and after["old.py"] is None


def expected():
    return {"schema": 1, "base": "a" * 40, "inputs": "b" * 64, "environment": {"browser": "1"},
        "suites": ["speed"], "reasons": {"report_speed.py": ["speed"]}}


def test_complete_pass_reused_only_with_matching_inputs_and_raw_inventory(tmp_path, monkeypatch):
    monkeypatch.setattr(pre, "ROOT", tmp_path)
    monkeypatch.setattr(pre, "identity", lambda *a, **k: expected())
    directory = tmp_path / "output/run"
    directory.mkdir(parents=True)
    calls = []

    def run(args):
        calls.append(args)
        if "scripts/run_visual_suite.py" in args:
            output = Path(args[-1]) / "speed"
            output.mkdir(parents=True)
            (output / "verification.json").write_text(json.dumps(visual_evidence("speed")))

    assert pre.preflight("v2.12.5", directory, run_command=run, environment_reader=lambda: {})["reused"] is False
    assert len(calls) == 2
    assert pre.preflight("v2.12.5", directory, run_command=run, environment_reader=lambda: {})["reused"] is True
    assert len(calls) == 2
    data = json.loads((directory / "preflight.json").read_text())
    raw = Path(data["evidence"]["speed"]) / "speed/verification.json"
    evidence = json.loads(raw.read_text())
    evidence["completed"].pop()
    raw.write_text(json.dumps(evidence))
    assert pre.preflight("v2.12.5", directory, run_command=run, environment_reader=lambda: {})["reused"] is False
    assert len(calls) == 4


@pytest.mark.parametrize("field", ["inputs", "environment", "base", "suites"])
def test_stale_local_identity_rejected(field):
    actual = deepcopy(expected())
    actual[field] = "changed"
    with pytest.raises(ValueError, match="differ"):
        pre.validate_pass({"status": "local-preflight-only", "identity": actual}, expected())


def test_fast_contract_failure_never_yields_a_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(pre, "ROOT", tmp_path)
    monkeypatch.setattr(pre, "identity", lambda *a, **k: expected())
    def fail(args):
        raise AssertionError("readable clock disagrees with exact instant")
    with pytest.raises(AssertionError, match="readable clock"):
        pre.preflight("v2.12.5", tmp_path / "output/run", run_command=fail, environment_reader=lambda: {})
    assert not (tmp_path / "output/run/preflight.json").exists()


def test_unstaged_new_code_cannot_hide_from_input_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr(candidate, "git", lambda *a, **k: "scripts/new.py")
    with pytest.raises(ValueError, match="Stage new"):
        candidate.inputs(tmp_path)


@pytest.mark.parametrize("dirty,allowed", [("docs/release.md", True), ("scripts/qualification.py", False)])
def test_resume_allows_only_receipt_guide_edits(tmp_path, monkeypatch, dirty, allowed):
    def git(*args, **kwargs):
        if args[0] == "branch":
            return "main"
        if args[0] == "diff":
            return dirty
        if args[0] == "remote":
            return "https://github.com/Wenjun-Mao/codex_usage.git"
        if args[0] == "ls-files":
            return "apps/owner-untracked.txt\ndocs/research/original-report.md"
        return "a" * 40
    monkeypatch.setattr(candidate, "git", git)
    monkeypatch.setattr(candidate, "package_version", lambda root: "2.12.6")
    monkeypatch.setattr(candidate, "contract_identity", lambda root: "b" * 64)
    if allowed:
        assert candidate.candidate(root=tmp_path, allow_receipt_edits=True)["sha"] == "a" * 40
    else:
        with pytest.raises(ValueError, match="Commit tracked"):
            candidate.candidate(root=tmp_path, allow_receipt_edits=True)
