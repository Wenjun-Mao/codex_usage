"""Complete real-input observations, separate from case-count assertions."""
from copy import deepcopy
from hashlib import sha256
import json
from math import isfinite

from .visual_cases import case_key, expected_cases

SCHEMA = 2
STRICT_SECONDS = .25
FUNCTIONAL_SECONDS = 2.0
DEFERRED = "deferred-known-latency"
PHASES = ("hover", "hide", "keyboard")
HIDDEN = {"visible": False, "hidden": True, "active": False,
    "focusVisible": False, "hover": False}
MATCHED = {"hide": HIDDEN,
    "hover": {**HIDDEN, "visible": True, "hidden": False, "hover": True},
    "keyboard": {**HIDDEN, "visible": True, "hidden": False, "active": True, "focusVisible": True}}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def state(value):
    require(isinstance(value, dict) and set(value) == set(HIDDEN)
        and all(type(bit) is bool for bit in value.values()), "Untyped tooltip state")
    return value


def finite_seconds(value, *, deferred=False):
    limit = FUNCTIONAL_SECONDS if deferred else STRICT_SECONDS
    require(type(value) in (int, float) and 0 <= value < limit and isfinite(value),
        "Tooltip observation exceeds its real-input budget")
    return value


class HoverMeasurements:
    def __init__(self, *, deferred=False):
        require(type(deferred) is bool, "Untyped timing policy")
        self.deferred = deferred
        self.rows = []
        self.previous = {}

    def recorder(self, case, target):
        key = (case_key(case), target)

        def record(value):
            row = deepcopy(value)
            if row["phase"] == "hide":
                prior = self.previous.get(key)
                require(prior is not None and prior["phase"] == "hover",
                    "Hide has no preceding matched hover observation")
                # Reuse the actual preceding match, without another style read
                # or an unmeasured input between the two timed actions.
                row["baseline"] = deepcopy(prior["matched"])
            row.update(case=deepcopy(case), target=target,
                disposition=DEFERRED if self.deferred and case["engine"] == "webkit" else "passed")
            self.rows.append(row)
            self.previous[key] = row

        return record


def validate_measurements(evidence, *, deferred=False):
    require(type(deferred) is bool, "Untyped timing policy")
    require(type(evidence.get("observation_contract")) is int
        and evidence["observation_contract"] == SCHEMA, "Missing tooltip observation contract")
    rows = evidence.get("observations")
    require(isinstance(rows, list), "Missing raw tooltip observations")
    cases = {case_key(case) for case in expected_cases("hover")}
    expected = {(case, target, phase) for case in cases for target in range(3) for phase in PHASES}
    require(len(rows) == len(expected), "Incomplete tooltip observation inventory")
    seen, previous = set(), {}
    maxima = {engine: dict.fromkeys(PHASES, 0.0) for engine in ("chromium", "webkit", "firefox")}
    for row in rows:
        require(isinstance(row, dict) and set(row) == {
            "case", "target", "phase", "seconds", "baseline", "matched", "disposition"}, "Foreign tooltip observation")
        case = row["case"]
        require(isinstance(case, dict) and set(case) == {"engine", "scenario", "theme", "width"},
            "Foreign tooltip observation case")
        key = case_key(case)
        require(type(row["target"]) is int and 0 <= row["target"] < 3, "Invalid tooltip target")
        require(isinstance(row["phase"], str), "Untyped tooltip phase")
        identity = (key, row["target"], row["phase"])
        require(identity in expected and identity not in seen, "Duplicate or foreign tooltip observation")
        seen.add(identity)
        phase = row["phase"]
        chain = previous.setdefault((key, row["target"]), [])
        require(phase == PHASES[len(chain)], "Tooltip input sequence differs")
        baseline = state(row["baseline"])
        require(baseline == (chain[-1]["matched"] if phase == "hide" else HIDDEN),
            "Tooltip baseline was primed or continuity differs")
        require(state(row["matched"]) == MATCHED[phase], "Tooltip matched state or modality differs")
        waived = deferred and case["engine"] == "webkit"
        require(row["disposition"] == (DEFERRED if waived else "passed"), "False tooltip timing disposition")
        maxima[case["engine"]][phase] = max(maxima[case["engine"]][phase], finite_seconds(row["seconds"], deferred=waived))
        chain.append(row)
    require(seen == expected, "Incomplete tooltip observation inventory")
    data = (json.dumps(rows, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return {"schema": SCHEMA, "status": DEFERRED if deferred else "passed", "observations": len(rows),
        "deferred_observations": 216 if deferred else 0,
        "sha256": sha256(data).hexdigest(), "maximum_seconds": maxima}


def validate_summary(summary, *, deferred=False):
    require(type(deferred) is bool, "Untyped timing policy")
    require(isinstance(summary, dict) and set(summary) == {
        "schema", "status", "observations", "sha256", "maximum_seconds", "deferred_observations"}
        and type(summary["schema"]) is int and summary["schema"] == SCHEMA
        and summary["status"] == (DEFERRED if deferred else "passed") and type(summary["observations"]) is int
        and type(summary["deferred_observations"]) is int
        and summary["deferred_observations"] == (216 if deferred else 0)
        and summary["observations"] == len(expected_cases("hover"))*3*len(PHASES),
        "Incomplete tooltip observation summary")
    digest = summary["sha256"]
    require(isinstance(digest, str) and len(digest) == 64
        and all(c in "0123456789abcdef" for c in digest), "Invalid tooltip observation digest")
    maxima = summary["maximum_seconds"]
    require(isinstance(maxima, dict) and set(maxima) == {"chromium", "webkit", "firefox"}, "Missing tooltip engine maxima")
    for engine, phases in maxima.items():
        require(isinstance(phases, dict) and set(phases) == set(PHASES), "Missing tooltip phase maxima")
        for value in phases.values():
            finite_seconds(value, deferred=deferred and engine == "webkit")
    return summary
