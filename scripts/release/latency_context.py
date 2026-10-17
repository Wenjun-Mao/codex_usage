"""Source-version timing policy; legacy exceptions still require fresh history."""
import os

from verification.hover_measurements import DEFERRED, OBSERVED, STRICT

from .git_journal import Journal
from .github import GitHub
from .latency_bindings import version
from .policy import ROOT, canonical, positive, require

LOCAL = {"execution": "local", "source": None, "origin": None, "binding": None}
OBSERVED_FROM = "2.12.4"


def hosted_policy(source):
    return OBSERVED if version(source["version"]) >= version(OBSERVED_FROM) else DEFERRED


def current_binding(source, reference, journal, *, publication=False):
    current = journal.current_binding(source, publication=publication)
    require(canonical(reference) == canonical(current["reference"]),
        "D4 proof does not bind the current retained candidate")
    return current["reference"]


def runtime_context(env=os.environ, *, journal=None):
    if env.get("GITHUB_ACTIONS") != "true":
        return dict(LOCAL)
    from .producer import source_context
    require(env.get("GITHUB_JOB") == "visual", "D4 runtime is not the hosted visual job")
    source = source_context(ROOT, env)
    origin = {"run": positive(env["GITHUB_RUN_ID"]), "attempt": positive(env["GITHUB_RUN_ATTEMPT"]), "job": "visual"}
    reference = ((journal or Journal(GitHub())).current_binding(source)["reference"]
        if hosted_policy(source) == DEFERRED else None)
    return {"execution": "hosted", "source": source, "origin": origin, "binding": reference}


def validate_context(value, *, source=None, origin=None, journal=None):
    require(isinstance(value, dict) and set(value) == {"execution", "source", "origin", "binding"},
        "Foreign D4 runtime context")
    if value["execution"] == "local":
        require(source is None and origin is None and canonical(value) == canonical(LOCAL),
            "Local timing evidence cannot qualify a hosted producer")
        return STRICT
    require(value["execution"] == "hosted" and source is not None and origin is not None
        and canonical(value["source"]) == canonical(source), "D4 source/context differs")
    expected = {"run": positive(origin["run"]), "attempt": positive(origin["attempt"]), "job": "visual"}
    require(origin["job_key"] == "visual" and canonical(value["origin"]) == canonical(expected),
        "D4 observation is not from its original producer execution")
    policy = hosted_policy(source)
    if policy == DEFERRED:
        current_binding(source, value["binding"], journal or Journal(GitHub()))
    else:
        require(value["binding"] is None, "Normal timing policy cannot reuse a legacy exception")
    return policy


def timing_fields(source, reference=None, *, journal=None, publication=False):
    policy = hosted_policy(source)
    result = {"timing_disposition": policy}
    if policy == DEFERRED:
        result["latency_binding"] = current_binding(source, reference, journal or Journal(GitHub()),
            publication=publication)
    else:
        require(reference is None, "Normal timing policy cannot reuse a legacy exception")
    return result


def validate_timing_fields(value, *, journal=None, publication=False):
    expected = timing_fields(value["source"], value.get("latency_binding"), journal=journal, publication=publication)
    actual = {key: value[key] for key in ("timing_disposition", "latency_binding") if key in value}
    require(canonical(actual) == canonical(expected), "Frozen timing policy or binding differs")
    return expected
