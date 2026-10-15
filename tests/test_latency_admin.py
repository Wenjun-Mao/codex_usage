"""Manual preparation is not a write; append requires unchanged pushed source/head."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from journal_fixture import JournalFixture, policy
from latency_binding_fixture import binding, latency, source
from release_tooling_support import load_tool

admin = load_tool("release.latency_admin")


def fixture(monkeypatch):
    f = JournalFixture()
    actual = binding(f)["source"]
    monkeypatch.setattr(admin, "frozen_source", lambda *a: deepcopy(actual))
    return f, actual


def test_prepare_writes_no_git_objects_then_append_is_verified_and_not_replayable(monkeypatch):
    f, actual = fixture(monkeypatch)
    prepared = admin.prepare("2.12.3", "nonpublishing", "Explicit synthetic approval", journal=f.journal)
    assert not f.api.writes
    assert prepared["binding"]["source"] == actual
    receipt = admin.append(prepared, journal=f.journal)
    assert f.journal.current_binding(source(prepared["binding"]))["reference"] == receipt
    writes = len(f.api.writes)
    with pytest.raises(ValueError, match="advanced"):
        admin.append(prepared, journal=f.journal)
    assert len(f.api.writes) == writes


@pytest.mark.parametrize("fault", ["source", "head", "digest", "schema", "extra", "purpose"])
def test_changed_source_head_or_preparation_never_writes(fault, monkeypatch):
    f, actual = fixture(monkeypatch)
    prepared = admin.prepare("2.12.3", "nonpublishing", "Explicit synthetic approval", journal=f.journal)
    if fault == "source":
        actual["sha"] = "e"*40
    elif fault == "head":
        initial = binding(f)
        f.journal.anchor(f.journal.candidate(latency.binding_event(initial, f.selected)))
    elif fault == "digest":
        prepared["binding"]["source"]["contract"] = "e"*64
    elif fault == "schema":
        prepared["schema"] = True
    elif fault == "purpose":
        prepared["binding"]["purpose"] = "release"
        prepared["binding"]["source"]["version"] = "2.12.3"
    else:
        prepared["force"] = True
    writes = len(f.api.writes)
    with pytest.raises(ValueError):
        admin.append(prepared, journal=f.journal)
    assert len(f.api.writes) == writes


def test_release_purpose_cannot_override_disabled_policy(monkeypatch):
    f, actual = fixture(monkeypatch)
    monkeypatch.setattr(admin, "PROMOTION_ENABLED", False)
    actual["version"] = "2.12.3"
    with pytest.raises(ValueError, match="enabled policy"):
        admin.prepare("2.12.3", "release", "Explicit synthetic approval", journal=f.journal)
    assert not f.api.writes


def test_enabled_release_binding_requires_the_exact_reserved_version(monkeypatch):
    f, actual = fixture(monkeypatch)
    monkeypatch.setattr(admin, "PROMOTION_ENABLED", True)
    actual["version"] = "2.12.3"
    prepared = admin.prepare("2.12.3", "release", "Explicit synthetic approval", journal=f.journal)
    receipt = admin.append(prepared, journal=f.journal)
    assert f.journal.current_binding(dict(actual, probe=False), publication=True)["reference"] == receipt


def test_lost_append_acknowledgement_cannot_be_retried_with_the_same_preparation(monkeypatch):
    from journal_fixture import GitWriteError
    f, actual = fixture(monkeypatch)
    prepared = admin.prepare("2.12.3", "nonpublishing", "Explicit synthetic approval", journal=f.journal)
    write = f.api.write
    def lost(method, endpoint, payload):
        result = write(method, endpoint, payload)
        if method == "PATCH":
            raise GitWriteError("unknown", "Accepted append, lost acknowledgement")
        return result
    monkeypatch.setattr(f.api, "write", lost)
    with pytest.raises(GitWriteError):
        admin.append(prepared, journal=f.journal)
    writes = len(f.api.writes)
    with pytest.raises(ValueError, match="advanced"):
        admin.append(prepared, journal=f.journal)
    assert len(f.api.writes) == writes
    assert f.journal.current_binding(dict(actual, probe=False))["binding"] == prepared["binding"]


@pytest.mark.parametrize("fault", [None, "dirty", "branch", "head", "cached-main", "repository", "tree"])
def test_source_is_clean_pushed_main_and_one_immutable_byte_map(monkeypatch, tmp_path, fault):
    f = JournalFixture()
    contents = {"extensions/vscode/package.json": json.dumps({"version": "2.12.2"}).encode(),
        "harness.py": b"unchanged\n"}
    for name, data in contents.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.replace(b"\n", b"\r\n"))
    monkeypatch.setattr(admin, "contract_files", lambda root: list(contents))
    def run(command, **kwargs):
        if "diff" in command and fault == "dirty":
            raise admin.subprocess.CalledProcessError(1, command)
        return SimpleNamespace(stdout=("branch" if fault == "branch" else "main") if "symbolic-ref" in command else "a"*40)
    monkeypatch.setattr(admin.subprocess, "run", run)
    def get(endpoint):
        if endpoint == f.api.prefix:
            return {"id": 1 if fault == "repository" else f.selected["repository_id"], "full_name": policy.REPOSITORY}
        return {"ref": "refs/heads/main", "object": {"type": "commit", "sha": ("e" if fault == "head" else "a")*40,
            "url": "public API metadata, not source identity"}}
    monkeypatch.setattr(f.api, "json", get)
    def fresh(endpoint):
        value = get(endpoint)
        if fault == "cached-main":
            value["object"]["sha"] = "e"*40
        return policy.canonical(value)
    monkeypatch.setattr(f.api, "raw", fresh)
    f.api.contract_tree = lambda sha: {name: "0"*40 if fault == "tree" else admin.blob_sha(data)
        for name, data in contents.items()}
    if fault:
        with pytest.raises((ValueError, admin.subprocess.CalledProcessError)):
            admin.frozen_source(tmp_path, f.journal)
    else:
        actual = admin.frozen_source(tmp_path, f.journal)
        assert actual["sha"] == "a"*40 and actual["version"] == "2.12.2"
        assert actual["contract"] == policy.fingerprint({name: admin.sha256(data).hexdigest() for name, data in contents.items()})
    assert not f.api.writes
