"""D4 is one exact, bounded candidate contract, never an environment bypass."""
from copy import deepcopy

import pytest

from journal_fixture import JournalFixture, model
from latency_binding_fixture import anchor, binding, latency, source, successor


def test_explicit_binding_is_anchored_after_source_freeze_not_inside_its_own_sha():
    f = JournalFixture()
    value = binding(f)
    candidate = f.journal.candidate(latency.binding_event(value, f.selected))
    with pytest.raises(ValueError, match="current anchored"):
        f.journal.binding_witness(candidate["commit"], value)
    ack = f.journal.anchor(candidate)
    assert ack["commit"] != value["source"]["sha"]
    assert f.journal.current_binding(source(value)) == {"reference": ack, "binding": value}
    assert f.journal.current_binding(source(value, probe=True))["reference"] == ack
    assert f.journal.read()["records"][0]["event"]["kind"] == latency.KIND
    assert model.prior_targets(f.journal.read()["records"], f.qualified()) == {}


def test_disabled_c_and_enabled_e_sources_have_distinct_retained_bindings():
    f = JournalFixture()
    first = binding(f)
    previous = anchor(f, first)
    enabled = successor(first, previous, sha="b"*40, release=True)
    enabled["source"]["contract"] = "c"*64
    current = anchor(f, enabled)
    with pytest.raises(ValueError, match="current anchored"):
        f.journal.binding_witness(previous["commit"], first)
    with pytest.raises(ValueError, match="another source"):
        f.journal.current_binding(source(first))
    assert f.journal.current_binding(source(enabled), publication=True)["reference"] == current
    assert len(f.journal.read()["records"]) == 2


@pytest.mark.parametrize("fault", ["repository", "repository-id", "workflow", "sha", "contract", "version", "probe", "extra"])
def test_binding_cannot_authorize_a_foreign_candidate(fault):
    f = JournalFixture()
    value = binding(f)
    anchor(f, value)
    actual = source(value)
    mutations = {"repository": ("repository", "another/repo"), "repository-id": ("repository_id", True),
        "workflow": ("workflow", ".github/workflows/promote-vsix.yml"), "sha": ("sha", "e"*40),
        "contract": ("contract", "d"*64), "version": ("version", "2.12.3"),
        "probe": ("probe", 1), "extra": ("untrusted", True)}
    key, replacement = mutations[fault]
    actual[key] = replacement
    with pytest.raises(ValueError, match="another source"):
        f.journal.current_binding(actual)


@pytest.mark.parametrize("purpose,probe", [("nonpublishing", False), ("nonpublishing", True), ("release", True)])
def test_only_release_binding_and_nonprobe_proof_can_reach_publication(purpose, probe):
    f = JournalFixture()
    value = binding(f, purpose=purpose, source_version="2.12.3")
    anchor(f, value)
    with pytest.raises(ValueError, match="cannot authorize publication"):
        f.journal.current_binding(source(value, probe=probe), publication=True)


@pytest.mark.parametrize("fault", ["version", "max", "scope", "boolean-revision", "revision", "approval", "source-sha", "source-version", "purpose", "extra"])
def test_malformed_or_broadened_binding_cannot_write_git_objects(fault):
    f = JournalFixture()
    value = binding(f)
    if fault == "version":
        value["slot"]["release_version"] = "2.12.2"
    elif fault == "max":
        value["slot"]["max_bindings"] = True
    elif fault == "scope":
        value["slot"]["scope"]["engine"] = "chromium"
    elif fault == "boolean-revision":
        value["revision"] = True
    elif fault == "revision":
        value["revision"] = 5
    elif fault == "approval":
        value["approval"] = "  "
    elif fault == "source-sha":
        value["source"]["sha"] = "not-frozen"
    elif fault == "source-version":
        value["source"]["version"] = "2.12.4"
    elif fault == "purpose":
        value["purpose"] = "approved"
    else:
        value["environment_override"] = True
    with pytest.raises(ValueError):
        anchor(f, value)
    assert not f.api.writes


@pytest.mark.parametrize("fault", ["initial", "predecessor", "revision", "slot", "regress", "noop"])
def test_supersession_is_explicit_current_bounded_and_monotonic(fault):
    f = JournalFixture()
    first = binding(f, purpose="release", source_version="2.12.3")
    previous = anchor(f, first)
    value = successor(first, previous, sha="b"*40)
    if fault == "initial":
        value = deepcopy(first)
    elif fault == "predecessor":
        value["supersedes"] = f.root
    elif fault == "revision":
        value["revision"] = 3
    elif fault == "slot":
        value["slot"]["release_version"] = "2.12.4"
    elif fault == "regress":
        value["purpose"] = "nonpublishing"
    else:
        value["source"] = deepcopy(first["source"])
    writes = len(f.api.writes)
    with pytest.raises(ValueError):
        anchor(f, value)
    assert len(f.api.writes) == writes


def test_four_bindings_are_the_maximum_not_an_unbounded_retry_allowlist():
    f = JournalFixture()
    value = binding(f)
    ack = anchor(f, value)
    for letter in ("b", "c", "d"):
        value = successor(value, ack, sha=letter*40)
        ack = anchor(f, value)
    assert len(f.journal.read()["records"]) == 4
    with pytest.raises(ValueError, match="approved bound"):
        anchor(f, successor(value, ack, sha="e"*40))


def test_pilot_history_cannot_supply_production_deferral_authority():
    f = JournalFixture("pilot")
    with pytest.raises(ValueError, match="Foreign D4 binding"):
        anchor(f, binding(f))
    assert not f.api.writes


def test_missing_ref_or_current_binding_never_means_no_exception_required():
    f = JournalFixture()
    with pytest.raises(ValueError, match="Missing current"):
        f.journal.current_binding(source(binding(f)))
    f.api.heads.clear()
    with pytest.raises(ValueError, match="Missing retained"):
        f.journal.current_binding(source(binding(f)))


def test_raw_approval_size_includes_trailing_whitespace():
    f = JournalFixture()
    value = binding(f)
    value["approval"] = "Owner approved" + " " * 2000
    with pytest.raises(ValueError, match="explicit approval"):
        anchor(f, value)
    assert not f.api.writes
    assert f.journal.read() == {"head": f.root, "records": []}
