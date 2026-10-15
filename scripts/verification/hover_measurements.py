"""Complete real-input observations, separate from case-count assertions."""
from copy import deepcopy
from hashlib import sha256
import json
from math import isfinite

from .visual_cases import case_key, expected_cases

SCHEMA = 1
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


def finite_seconds(value):
    require(type(value) in (int, float) and 0 <= value < .25 and isfinite(value),
        "Tooltip observation exceeds the strict real-input budget")
    return value


class HoverMeasurements:
    def __init__(self):
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
            row.update(case=deepcopy(case), target=target)
            self.rows.append(row)
            self.previous[key] = row

        return record


def validate_measurements(evidence):
    require(type(evidence.get("observation_contract")) is int
        and evidence["observation_contract"] == SCHEMA, "Missing tooltip observation contract")
    rows = evidence.get("observations")
    require(isinstance(rows, list), "Missing raw tooltip observations")
    cases = {case_key(case) for case in expected_cases("hover")}
    expected = {(case, target, phase) for case in cases for target in range(3) for phase in PHASES}
    require(len(rows) == len(expected), "Incomplete tooltip observation inventory")
    seen, previous, maxima = set(), {}, {phase: 0.0 for phase in PHASES}
    for row in rows:
        require(isinstance(row, dict) and set(row) == {
            "case", "target", "phase", "seconds", "baseline", "matched"}, "Foreign tooltip observation")
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
        maxima[phase] = max(maxima[phase], finite_seconds(row["seconds"]))
        chain.append(row)
    require(seen == expected, "Incomplete tooltip observation inventory")
    data = (json.dumps(rows, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return {"schema": SCHEMA, "status": "passed", "observations": len(rows),
        "sha256": sha256(data).hexdigest(), "maximum_seconds": maxima}


def validate_summary(summary):
    require(isinstance(summary, dict) and set(summary) == {
        "schema", "status", "observations", "sha256", "maximum_seconds"}
        and type(summary["schema"]) is int and summary["schema"] == SCHEMA
        and summary["status"] == "passed" and type(summary["observations"]) is int
        and summary["observations"] == len(expected_cases("hover"))*3*len(PHASES),
        "Incomplete tooltip observation summary")
    digest = summary["sha256"]
    require(isinstance(digest, str) and len(digest) == 64
        and all(c in "0123456789abcdef" for c in digest), "Invalid tooltip observation digest")
    maxima = summary["maximum_seconds"]
    require(isinstance(maxima, dict) and set(maxima) == set(PHASES), "Missing tooltip phase maxima")
    for value in maxima.values():
        finite_seconds(value)
    return summary
