"""Binding changes and possible publication serialize in the same Git parent."""
from copy import deepcopy

import pytest

from journal_fixture import GitWriteError, JournalFixture, model, policy
from latency_binding_fixture import anchor, binding, intent, latency, successor


def release(f):
    value = binding(f, purpose="release", source_version="2.12.3")
    return value, anchor(f, value)


@pytest.mark.parametrize("target", policy.TARGETS)
def test_either_target_permanently_freezes_candidate_supersession(target):
    f = JournalFixture()
    value, ack = release(f)
    f.journal.anchor(f.journal.candidate(intent(f, value, ack, target)))
    writes = len(f.api.writes)
    with pytest.raises(ValueError, match="permanently freezes"):
        anchor(f, successor(value, ack, sha="e"*40))
    assert len(f.api.writes) == writes
    assert f.journal.binding_witness(ack["commit"], value) == ack


def test_initial_exception_cannot_erase_an_earlier_possible_upload():
    f = JournalFixture()
    f.journal.anchor(f.journal.candidate(f.event()))
    with pytest.raises(ValueError, match="permanently freezes"):
        anchor(f, binding(f))


@pytest.mark.parametrize("winner", ["intent", "binding"])
def test_same_parent_race_has_one_winner_and_never_replays_the_loser(winner):
    f = JournalFixture()
    value, ack = release(f)
    state = f.journal.read()
    publish = intent(f, value, ack)
    replacement = successor(value, ack, sha="e"*40)
    candidates = {"intent": f.journal.candidate(publish, state),
        "binding": f.journal.candidate(latency.binding_event(replacement, f.selected), state)}
    loser = "binding" if winner == "intent" else "intent"
    f.journal.anchor(candidates[winner])
    writes = len(f.api.writes)
    with pytest.raises(ValueError, match="advanced"):
        f.journal.anchor(candidates[loser])
    assert len(f.api.writes) == writes
    with pytest.raises(ValueError):
        f.journal.candidate(latency.binding_event(replacement, f.selected) if loser == "binding" else publish)


@pytest.mark.parametrize("fault", ["missing", "superseded", "commit", "digest", "invocation", "sequence", "ref", "extra"])
def test_publication_intent_requires_the_exact_current_binding_reference(fault):
    f = JournalFixture()
    first, prior = release(f)
    value = successor(first, prior, sha="e"*40)
    current = anchor(f, value)
    event = intent(f, value, current)
    reference = event["intent"]["latency_binding"]
    if fault == "missing":
        event["intent"].pop("latency_binding")
    elif fault == "superseded":
        event["intent"]["latency_binding"] = prior
    else:
        key, replacement = {"commit": ("commit", f.root), "digest": ("binding_sha256", "f"*64),
            "invocation": ("invocation", "2d130d47-58b5-4aa1-801c-a1f8350a2a1e"),
            "sequence": ("sequence", True), "ref": ("ref", "refs/heads/main"), "extra": ("untrusted", True)}[fault]
        reference[key] = replacement
    writes = len(f.api.writes)
    with pytest.raises(ValueError):
        f.journal.candidate(event)
    assert len(f.api.writes) == writes


def test_nonpublishing_candidate_cannot_supply_an_upload_intent():
    f = JournalFixture()
    value = binding(f, source_version="2.12.3")
    ack = anchor(f, value)
    with pytest.raises(ValueError, match="cannot authorize publication"):
        f.journal.candidate(intent(f, value, ack))


def test_unknown_reference_is_not_an_independent_approval():
    f = JournalFixture()
    value, ack = release(f)
    other = JournalFixture()
    with pytest.raises(ValueError, match="unknown D4"):
        other.journal.candidate(intent(other, value, ack))


def test_bindings_are_not_upload_targets_and_legacy_upload_guards_still_apply():
    f = JournalFixture()
    value, ack = release(f)
    for target in policy.TARGETS:
        f.journal.anchor(f.journal.candidate(intent(f, value, ack, target)))
    qualified = f.qualified()
    assert model.prior_targets(f.journal.read()["records"], qualified) == dict.fromkeys(policy.TARGETS, True)
    with pytest.raises(ValueError, match="retained possible upload"):
        f.journal.candidate(intent(f, value, ack))
    forged = intent(f, value, ack, "win32-x64")
    forged["intent"]["source"]["sha"] = "e"*40
    with pytest.raises(ValueError, match="same-version"):
        f.journal.candidate(forged)


def test_lost_intent_acknowledgement_and_deleted_actions_do_not_unfreeze_d4():
    f = JournalFixture()
    value, ack = release(f)
    original = f.api.write

    def lost(method, endpoint, payload):
        result = original(method, endpoint, payload)
        if method == "PATCH":
            raise GitWriteError("unknown", "Lost accepted append response")
        return result

    f.api.write = lost
    with pytest.raises(GitWriteError):
        f.journal.anchor(f.journal.candidate(intent(f, value, ack)))
    f.api.write = original
    f.api.run = lambda *_: pytest.fail("Actions retention is not the publication authority")
    with pytest.raises(ValueError, match="permanently freezes"):
        anchor(f, successor(value, ack, sha="e"*40))


def test_lost_binding_append_is_observed_not_replayed():
    f = JournalFixture()
    value = binding(f)
    candidate = f.journal.candidate(latency.binding_event(value, f.selected))
    original = f.api.write

    def lost(method, endpoint, payload):
        result = original(method, endpoint, payload)
        if method == "PATCH":
            raise GitWriteError("unknown", "Lost accepted binding response")
        return result

    f.api.write = lost
    with pytest.raises(GitWriteError):
        f.journal.anchor(candidate)
    assert f.journal.binding_witness(candidate["commit"], value)["commit"] == candidate["commit"]
    with pytest.raises(ValueError, match="advanced"):
        f.journal.anchor(candidate)


def test_malformed_supersession_in_retained_history_is_rejected_without_mutation():
    f = JournalFixture()
    value, ack = release(f)
    replacement = successor(value, ack, sha="e"*40)
    replacement["supersedes"] = f.root
    record = deepcopy(f.journal.read()["records"][0])
    record.pop("commit")
    record.update(previous=ack["commit"], sequence=2, invocation="2d130d47-58b5-4aa1-801c-a1f8350a2a1e",
                  event=latency.binding_event(replacement, f.selected))
    f.api.heads[f.selected["ref"]] = f.commit(policy.canonical(record), [ack["commit"]])
    writes = len(f.api.writes)
    with pytest.raises(ValueError, match="current predecessor"):
        f.journal.read()
    assert len(f.api.writes) == writes
