"""Synthetic all-target input histories, with no real browser or network access."""
from copy import deepcopy

from release_tooling_support import load_tool

measure = load_tool("verification.hover_measurements")
cases = load_tool("verification.visual_cases")
PROCESS = {"schema": 1, "status": "completed", "seconds": 100.,
    "limit_seconds": 600, "ownership": "owned-process-tree"}


def measurements():
    log = measure.HoverMeasurements()
    for case in cases.expected_cases("hover"):
        for target in range(3):
            record = log.recorder(case, target)
            for phase in measure.PHASES:
                record({"phase": phase, "seconds": .01,
                    "baseline": deepcopy(measure.HIDDEN) if phase != "hide" else None,
                    "matched": deepcopy(measure.MATCHED[phase])})
    result = {"observation_contract": measure.SCHEMA, "observations": log.rows}
    result["observation_summary"] = measure.validate_measurements(result)
    return result
