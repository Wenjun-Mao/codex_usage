"""Neither environment flags nor stale witnesses grant a hosted deferral."""
from copy import deepcopy

import pytest

from hover_measurement_fixture import hosted_measurements
from latency_binding_fixture import latency, successor
from release_tooling_support import load_tool

context = load_tool("release.latency_context")
ORIGIN = {"run": 77, "attempt": 1, "job_key": "visual"}


def valid():
    data, journal = hosted_measurements()
    return data["timing_context"], journal


def test_local_context_is_strict_and_never_reads_the_journal():
    assert context.runtime_context({}) == context.LOCAL
    assert context.validate_context(dict(context.LOCAL)) is False
    value, journal = valid()
    with pytest.raises(ValueError, match="cannot qualify"):
        context.validate_context(dict(context.LOCAL), source=value["source"], origin=ORIGIN, journal=journal)


def test_hosted_runtime_resolves_fresh_candidate_after_actual_source_verification(monkeypatch):
    value, journal = valid()
    producer = load_tool("release.producer")
    seen = []
    def source(root, env):
        seen.append((root, env))
        return value["source"]
    monkeypatch.setattr(producer, "source_context", source)
    env = {"GITHUB_ACTIONS": "true", "GITHUB_JOB": "visual", "GITHUB_RUN_ID": "77", "GITHUB_RUN_ATTEMPT": "1"}
    assert context.runtime_context(env, journal=journal) == value
    assert len(seen) == 1
    assert context.validate_context(value, source=value["source"], origin=ORIGIN, journal=journal) is True


def test_environment_claim_alone_or_wrong_job_cannot_authorize_a_deferral(monkeypatch):
    monkeypatch.setattr(load_tool("release.producer"), "source_context", lambda *a: pytest.fail("Wrong job must stop first"))
    with pytest.raises(ValueError, match="visual job"):
        context.runtime_context({"GITHUB_ACTIONS": "true", "GITHUB_JOB": "native"})


@pytest.mark.parametrize("fault", ["missing", "execution", "extra", "source", "run", "attempt", "job", "ref", "digest", "commit"])
def test_producer_context_is_exact_and_tied_to_the_original_execution(fault):
    value, journal = valid()
    source = deepcopy(value["source"])
    if fault == "missing":
        value.pop("binding")
    elif fault == "execution":
        value["execution"] = "native"
    elif fault == "extra":
        value["approved"] = True
    elif fault == "source":
        value["source"]["sha"] = "e"*40
    elif fault in ("run", "attempt", "job"):
        value["origin"][fault] = "other" if fault == "job" else True
    else:
        key = {"ref": "ref", "digest": "binding_sha256", "commit": "commit"}[fault]
        value["binding"][key] = "e"*40 if fault == "commit" else "foreign"
    with pytest.raises(ValueError):
        context.validate_context(value, source=source, origin=ORIGIN, journal=journal)


def test_superseded_source_and_nonpublishing_purpose_cannot_grant_publication():
    value, journal = valid()
    with pytest.raises(ValueError, match="cannot authorize publication"):
        context.current_binding(value["source"], value["binding"], journal, publication=True)
    previous = journal.read()["records"][-1]
    replacement = successor(previous["event"]["binding"], value["binding"], sha="e"*40)
    journal.anchor(journal.candidate(latency.binding_event(replacement, journal.config)))
    with pytest.raises(ValueError, match="another source"):
        context.validate_context(value, source=value["source"], origin=ORIGIN, journal=journal)
