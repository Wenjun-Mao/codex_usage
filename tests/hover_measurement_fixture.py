"""Synthetic all-target input histories, with no real browser or network access."""
from copy import deepcopy

from release_tooling_support import load_tool

measure = load_tool("verification.hover_measurements")
cases = load_tool("verification.visual_cases")
PROCESS = {"schema": 1, "status": "completed", "seconds": 100.,
    "limit_seconds": 600, "ownership": "owned-process-tree"}


def measurements(*, deferred=False, context=None):
    log = measure.HoverMeasurements(deferred=deferred)
    for case in cases.expected_cases("hover"):
        for target in range(3):
            record = log.recorder(case, target)
            for phase in measure.PHASES:
                record({"phase": phase, "seconds": .01,
                    "baseline": deepcopy(measure.HIDDEN) if phase != "hide" else None,
                    "matched": deepcopy(measure.MATCHED[phase])})
    result = {"observation_contract": measure.SCHEMA, "observations": log.rows,
        "timing_context": context or {"execution": "local", "source": None, "origin": None, "binding": None}}
    result["observation_summary"] = measure.validate_measurements(result, deferred=deferred)
    return result


def hosted_measurements(source=None, *, attempt=1):
    from journal_fixture import JournalFixture
    from latency_binding_fixture import anchor, binding
    fixture = JournalFixture(repository_id=123 if source is None else source["repository_id"])
    value = binding(fixture)
    if source is not None:
        value["source"] = {key: source[key] for key in value["source"]}
    else:
        source = dict(value["source"], probe=False)
    ack = anchor(fixture, value)
    context = {"execution": "hosted", "source": deepcopy(source),
        "origin": {"run": 77, "attempt": attempt, "job": "visual"}, "binding": ack}
    return measurements(deferred=True, context=context), fixture.journal
