"""Retained Git authority survives missing Actions history and refuses replay."""
from copy import deepcopy
import json

import pytest

from journal_fixture import GitWriteError, JournalFixture, model, policy
from release_tooling_support import load_tool


def test_pinned_origin_and_reachable_intent_precede_any_upload_authority():
    f = JournalFixture()
    assert f.journal.read() == {"head": f.root, "records": []}
    event = f.event()
    candidate = f.journal.candidate(event)
    with pytest.raises(ValueError, match="not anchored"):
        f.journal.witness(candidate["commit"], event["intent"])
    ack = f.journal.anchor(candidate)
    assert ack["commit"] == f.api.heads[f.selected["ref"]]
    assert ack["intent_sha256"] == policy.fingerprint(event["intent"])


def test_concurrent_identical_semantic_attempts_get_distinct_commits_and_one_winner():
    f = JournalFixture()
    snapshot = f.journal.read()
    a, b = [f.journal.candidate(f.event(), snapshot) for _ in range(2)]
    assert a["commit"] != b["commit"]
    f.journal.anchor(a)
    with pytest.raises(ValueError, match="advanced"):
        f.journal.anchor(b)
    with pytest.raises(GitWriteError):
        f.api.write("PATCH", "git/refs/"+f.selected["ref"].removeprefix("refs/"), {"sha": b["commit"], "force": False})
    with pytest.raises(ValueError, match="advanced"):
        f.journal.anchor(a)
    with pytest.raises(ValueError, match="retained possible upload"):
        f.journal.candidate(f.event())


def test_lost_append_response_keeps_uncertainty_after_all_actions_evidence_disappears():
    f = JournalFixture()
    original = f.api.write

    def lost(method, endpoint, payload):
        result = original(method, endpoint, payload)
        if method == "PATCH":
            raise GitWriteError("unknown", "Response lost after accepted append")
        return result

    f.api.write = lost
    with pytest.raises(GitWriteError):
        f.journal.anchor(f.journal.candidate(f.event()))
    f.api.run = lambda *args: pytest.fail("Retained history must not query deleted Actions runs")
    snapshot = f.journal.read()
    assert model.prior_targets(snapshot["records"], f.qualified()) == {"darwin-arm64": True}
    changed = f.qualified()
    changed["source"]["sha"] = "e"*40
    with pytest.raises(ValueError, match="conflicts"):
        model.prior_targets(snapshot["records"], changed)


@pytest.mark.parametrize("fault", ["missing-ref", "wrong-genesis", "merge", "sequence", "previous", "schema", "namespace", "extra-file", "symlink", "truncated", "blob", "noncanonical"])
def test_missing_malformed_or_foreign_journal_never_recreates_history(fault):
    f = JournalFixture()
    candidate = f.journal.candidate(f.event())
    f.journal.anchor(candidate)
    commit = f.api.commits[candidate["commit"]]
    tree = f.api.trees[commit["tree"]["sha"]]
    if fault == "missing-ref":
        f.api.heads.clear()
    elif fault == "wrong-genesis":
        f.journal.config["genesis"] = "0"*40
    elif fault == "merge":
        commit["parents"].append({"sha": f.root})
    elif fault in ("sequence", "previous", "schema", "namespace", "noncanonical"):
        record = deepcopy(candidate["record"])
        if fault == "sequence":
            record["sequence"] = True
        elif fault == "previous":
            record["previous"] = "e"*40
        elif fault == "schema":
            record["schema"] = True
        elif fault == "namespace":
            record["event"]["domain"] = "pilot"
        data = json.dumps(record, indent=2).encode() if fault == "noncanonical" else policy.canonical(record)
        f.api.heads[f.selected["ref"]] = f.commit(data, [f.root])
    elif fault == "extra-file":
        tree["tree"].append({"path": "unexpected", "type": "blob"})
    elif fault == "symlink":
        tree["tree"][0]["mode"] = "120000"
    elif fault == "truncated":
        tree["truncated"] = True
    else:
        f.api.blobs[tree["tree"][0]["sha"]]["content"] = "Zm9yZ2Vk"
    count = len(f.api.writes)
    with pytest.raises((ValueError, KeyError)):
        f.journal.read()
    assert len(f.api.writes) == count


@pytest.mark.parametrize("fault", ["workflow", "repository", "source", "publisher", "attempt", "package", "cutover", "pilot"])
def test_event_identity_and_trusted_cutover_are_mandatory(fault):
    f = JournalFixture()
    event = f.event()
    if fault == "workflow":
        event["workflow_id"] = 20
    elif fault == "repository":
        event["intent"]["source"]["repository_id"] = 42
    elif fault == "source":
        event["intent"]["source"]["sha"] = "not-a-source"
    elif fault == "publisher":
        event["intent"]["publisher_sha"] = "not-a-publisher"
    elif fault == "attempt":
        event["intent"]["origin"]["attempt"] = True
    elif fault == "package":
        event["intent"]["package"]["target"] = "win32-x64"
    elif fault == "cutover":
        event["intent"]["source"]["version"] = "2.12.2"
        event["intent"]["tag"] = "v2.12.2"
    else:
        event = JournalFixture("pilot").event()
    with pytest.raises(ValueError):
        f.journal.candidate(event)
    assert not f.api.writes


def test_pilot_journal_is_a_separate_valid_namespace():
    f = JournalFixture("pilot")
    ack = f.journal.anchor(f.journal.candidate(f.event()))
    assert ack["domain"] == "pilot"
    assert ack["ref"] == "refs/heads/codex/publication-journal-pilot"
    assert f.api.heads.keys() == {ack["ref"]}


def test_caller_snapshot_cannot_erase_existing_intents_or_break_sequence():
    f = JournalFixture()
    f.journal.anchor(f.journal.candidate(f.event()))
    snapshot = f.journal.read()
    snapshot["records"] = []
    count = len(f.api.writes)
    with pytest.raises(ValueError, match="not verified"):
        f.journal.candidate(f.event("win32-x64"), snapshot)
    assert len(f.api.writes) == count


def test_cross_target_source_conflict_fails_at_journal_boundary():
    f = JournalFixture()
    first = f.journal.anchor(f.journal.candidate(f.event()))
    event = f.event("win32-x64")
    event["intent"]["source"]["sha"] = "e"*40
    count = len(f.api.writes)
    with pytest.raises(ValueError, match="same-version"):
        f.journal.candidate(event)
    assert len(f.api.writes) == count
    record = {"schema": 1, "kind": "journal-entry", "genesis": f.root, "previous": first["commit"],
        "sequence": 2, "invocation": "2d130d47-58b5-4aa1-801c-a1f8350a2a1e", "event": event}
    bad = f.commit(policy.canonical(record), [first["commit"]])
    f.api.heads[f.selected["ref"]] = bad
    with pytest.raises(ValueError, match="same-version"):
        f.journal.read()


@pytest.mark.parametrize("method,endpoint,payload", [("DELETE", "git/refs/heads/codex/publication-receipts", {}),
    ("PATCH", "git/refs/heads/main", {"force": False}),
    ("PATCH", "git/refs/heads/codex/publication-receipts", {"force": True}),
    ("POST", "git/refs", {"ref": "refs/heads/codex/publication-receipts"}),
    ("PATCH", "actions/runs/77", {})])
def test_normal_journal_adapter_cannot_delete_force_or_mutate_other_refs(method, endpoint, payload):
    f = JournalFixture()
    api = load_tool("release.journal_api").JournalAPI("production", f.config)
    with pytest.raises(ValueError, match="Forbidden"):
        api.write(method, endpoint, payload)
