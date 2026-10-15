"""Enabled intent CLI cannot issue usable authority without retained acknowledgement."""
import json
import sys
from types import SimpleNamespace

import pytest

from latency_binding_fixture import latency, successor
from publication_fixture import PublicationFixture, policy
from release_tooling_support import load_tool

qualification = load_tool("qualification")
tool = load_tool("publication_intent")


def writer(monkeypatch, directory, command, target="darwin-arm64"):
    arguments = ["publication_intent.py", command, "--directory", str(directory), "--target", target]
    if command == "stamp":
        arguments += ["--artifact-id", "123", "--artifact-digest", "b"*64]
    monkeypatch.setattr(sys, "argv", arguments)
    tool.main()


def fixture(tmp_path, monkeypatch):
    api = PublicationFixture()
    api.install(monkeypatch, qualification)
    qualified = api.validate(qualification, tmp_path)
    api.install_writer(monkeypatch, tool)
    return api, qualified


def assert_no_authority(directory, target="darwin-arm64"):
    assert not (directory / f"intent-{target}-ack.json").exists()
    assert not (directory / f"intent-{target}-authority.json").exists()


def test_enabled_intent_prepare_and_stamp_bind_both_targets_to_retained_history(tmp_path, monkeypatch, capsys):
    api, qualified = fixture(tmp_path, monkeypatch)
    for target in policy.TARGETS:
        writer(monkeypatch, tmp_path, "prepare", target)
        assert_no_authority(tmp_path, target)
        writer(monkeypatch, tmp_path, "stamp", target)
        ack = json.loads((tmp_path / f"intent-{target}-ack.json").read_text())
        authority = json.loads((tmp_path / f"intent-{target}-authority.json").read_text())
        body = json.loads((tmp_path / f"intent-{target}/intent.json").read_text())
        assert body["latency_binding"] == authority["latency_binding"] == qualified["latency_binding"]
        assert body["source"] == authority["source"] == qualified["source"]
        assert ack["journal"] == authority["journal"] == api.journal.witness(ack["journal"]["commit"], body)
        assert authority["package_sha256"] == qualified["manifest"]["packages"][target]["sha256"]
    assert len(api.journal.read()["records"]) == 3
    assert capsys.readouterr().out.count("CODEX_PUBLICATION_INTENT ") == 2


def test_disabled_intent_writer_refuses_before_context_or_transport(monkeypatch):
    monkeypatch.setattr(tool, "PROMOTION_ENABLED", False)
    api = SimpleNamespace(run=lambda *args: pytest.fail("Disabled writer must not read transport"))
    with pytest.raises(ValueError, match="independently retained"):
        tool.writer_context(api, {})


@pytest.mark.parametrize("fault", ["actions", "job", "workflow-id", "workflow", "repository", "fork",
    "source", "tag", "attempt", "event", "closure", "checkout-marker"])
def test_enabled_intent_writer_rejects_foreign_execution_before_git_writes(tmp_path, monkeypatch, fault):
    api, _ = fixture(tmp_path, monkeypatch)
    if fault in ("actions", "job"):
        monkeypatch.setenv("GITHUB_ACTIONS" if fault == "actions" else "GITHUB_JOB", "foreign")
    elif fault == "closure":
        api.publisher_tree[policy.PROMOTION_WORKFLOW] = "e"*40
    elif fault == "checkout-marker":
        original = api.logs
        api.logs = lambda job_id: "missing checkout marker" if job_id == 5000 else original(job_id)
    elif fault in ("repository", "fork"):
        api.publication["repository" if fault == "repository" else "head_repository"]["id"] = 456
    else:
        key, value = {"workflow-id": ("workflow_id", 456), "workflow": ("path", "foreign.yml"),
            "source": ("head_sha", "e"*40), "tag": ("head_branch", "main"),
            "attempt": ("run_attempt", 2), "event": ("event", "push")}[fault]
        api.publication[key] = value
    before = len(api.journal.api.writes)
    with pytest.raises(ValueError):
        writer(monkeypatch, tmp_path, "prepare")
    assert len(api.journal.api.writes) == before
    assert_no_authority(tmp_path)
    assert not (tmp_path / "intent-darwin-arm64-journal.json").exists()


def test_enabled_intent_writer_refuses_a_superseded_qualified_binding(tmp_path, monkeypatch):
    api, qualified = fixture(tmp_path, monkeypatch)
    current = api.journal.read()["records"][-1]
    replacement = successor(current["event"]["binding"], qualified["latency_binding"], sha="e"*40)
    api.journal.anchor(api.journal.candidate(latency.binding_event(replacement, api.journal.config)))
    before = len(api.journal.api.writes)
    with pytest.raises(ValueError, match="another source"):
        writer(monkeypatch, tmp_path, "prepare")
    assert len(api.journal.api.writes) == before
    assert_no_authority(tmp_path)


def test_lost_git_acknowledgement_retains_possible_upload_but_emits_no_authority(tmp_path, monkeypatch):
    api, _ = fixture(tmp_path, monkeypatch)
    write = api.journal.api.write

    def lost_ack(method, endpoint, payload):
        result = write(method, endpoint, payload)
        if method == "PATCH":
            raise OSError("synthetic lost acknowledgement after accepted Git update")
        return result

    monkeypatch.setattr(api.journal.api, "write", lost_ack)
    with pytest.raises(OSError, match="lost acknowledgement"):
        writer(monkeypatch, tmp_path, "prepare")
    records = api.journal.read()["records"]
    assert len(records) == 2 and records[-1]["event"]["kind"] == "publication-start"
    assert_no_authority(tmp_path)
    assert not (tmp_path / "intent-darwin-arm64-journal.json").exists()


@pytest.mark.parametrize("fault", ["body", "journal", "digest", "writer"])
def test_stamp_refuses_persisted_context_or_acknowledgement_drift(tmp_path, monkeypatch, fault):
    api, _ = fixture(tmp_path, monkeypatch)
    writer(monkeypatch, tmp_path, "prepare")
    if fault == "writer":
        monkeypatch.setenv("GITHUB_JOB", "foreign")
    else:
        path = tmp_path / ("intent-darwin-arm64/intent.json" if fault == "body" else "intent-darwin-arm64-journal.json")
        data = json.loads(path.read_text())
        if fault == "body":
            data["qualification_attempt"] += 1
        else:
            data["commit" if fault == "journal" else "intent_sha256"] = "e"*(40 if fault == "journal" else 64)
        path.write_bytes(policy.canonical(data))
    writes = len(api.journal.api.writes)
    with pytest.raises(ValueError):
        writer(monkeypatch, tmp_path, "stamp")
    assert len(api.journal.api.writes) == writes
    assert_no_authority(tmp_path)
