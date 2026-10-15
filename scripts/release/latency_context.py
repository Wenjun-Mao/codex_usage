"""Fresh journal resolution, never a caller flag, selects the one-release scope."""
import os

from .git_journal import Journal
from .github import GitHub
from .policy import ROOT, canonical, positive, require

LOCAL = {"execution": "local", "source": None, "origin": None, "binding": None}


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
    reference = (journal or Journal(GitHub())).current_binding(source)["reference"]
    return {"execution": "hosted", "source": source, "origin": origin, "binding": reference}


def validate_context(value, *, source=None, origin=None, journal=None):
    require(isinstance(value, dict) and set(value) == {"execution", "source", "origin", "binding"},
        "Foreign D4 runtime context")
    if value["execution"] == "local":
        require(source is None and origin is None and canonical(value) == canonical(LOCAL),
            "Local timing evidence cannot qualify a hosted producer")
        return False
    require(value["execution"] == "hosted" and source is not None and origin is not None
        and canonical(value["source"]) == canonical(source), "D4 source/context differs")
    expected = {"run": positive(origin["run"]), "attempt": positive(origin["attempt"]), "job": "visual"}
    require(origin["job_key"] == "visual" and canonical(value["origin"]) == canonical(expected),
        "D4 observation is not from its original producer execution")
    current_binding(source, value["binding"], journal or Journal(GitHub()))
    return True
