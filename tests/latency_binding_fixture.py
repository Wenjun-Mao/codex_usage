"""Explicit fake approvals use only the in-memory Git Data transport."""
from copy import deepcopy

from journal_fixture import model
from release_tooling_support import load_tool

latency = load_tool("release.latency_bindings")


def binding(fixture, *, purpose="nonpublishing", source_version="2.12.2", sha="a"*40):
    source = fixture.event()["intent"]["source"]
    source = {key: source[key] for key in latency.SOURCE_FIELDS}
    source.update(version=source_version, sha=sha)
    return {"slot": {"id": latency.EXCEPTION_ID, "release_version": "2.12.3",
        "max_bindings": 4, "scope": deepcopy(latency.SCOPE)},
        "revision": 1, "supersedes": None, "purpose": purpose, "source": source,
        "approval": "Synthetic explicit fixture approval; never runtime authority"}


def anchor(fixture, value):
    return fixture.journal.anchor(fixture.journal.candidate(latency.binding_event(value, fixture.selected)))


def successor(value, ack, *, sha, release=False):
    result = deepcopy(value)
    result.update(revision=value["revision"]+1, supersedes=ack["commit"])
    result["source"]["sha"] = sha
    if release:
        result["purpose"] = "release"
        result["source"]["version"] = result["slot"]["release_version"]
    return result


def source(value, *, probe=False):
    return {**deepcopy(value["source"]), "probe": probe}


def intent(fixture, value, ack, target="darwin-arm64"):
    event = fixture.event(target)
    event["intent"]["source"] = source(value)
    event["intent"]["latency_binding"] = deepcopy(ack)
    return model.validate_event(event, fixture.selected)
