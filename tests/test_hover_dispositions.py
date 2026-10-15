"""Only authorized hosted WebKit timing is deferred; functionality stays strict."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from hover_measurement_fixture import hosted_measurements, measure, measurements
from release_tooling_support import load_tool


def webkit_rows(evidence):
    return [row for row in evidence["observations"] if row["case"]["engine"] == "webkit"]


def test_even_fast_hosted_webkit_samples_are_deferred_not_silently_passed():
    evidence, _ = hosted_measurements()
    rows = webkit_rows(evidence)
    assert len(rows) == 216
    assert all(row["disposition"] == measure.DEFERRED for row in rows)
    summary = measure.validate_measurements(evidence, deferred=True)
    assert summary["status"] == measure.DEFERRED and summary["deferred_observations"] == 216
    assert measure.validate_summary(summary, deferred=True) == summary
    with pytest.raises(ValueError):
        measure.validate_measurements(evidence)


@pytest.mark.parametrize("seconds,passes", [(.3, True), (1.999, True), (2., False), (float("inf"), False)])
def test_functional_observation_bound_is_finite_and_still_includes_transport(seconds, passes):
    evidence, _ = hosted_measurements()
    for row in webkit_rows(evidence):
        row["seconds"] = seconds
    if passes:
        summary = measure.validate_measurements(evidence, deferred=True)
        assert summary["maximum_seconds"]["webkit"] == dict.fromkeys(measure.PHASES, seconds)
    else:
        with pytest.raises(ValueError, match="budget"):
            measure.validate_measurements(evidence, deferred=True)


@pytest.mark.parametrize("fault", ["false-pass", "hidden", "baseline", "keyboard", "missing", "duplicate", "strict-engine"])
def test_deferral_does_not_cover_other_failures_or_engines(fault):
    evidence, _ = hosted_measurements()
    rows = webkit_rows(evidence)
    if fault == "false-pass":
        rows[0]["disposition"] = "passed"
    elif fault == "hidden":
        rows[1]["matched"]["active"] = True
    elif fault == "baseline":
        rows[0]["baseline"] = deepcopy(measure.MATCHED["hover"])
    elif fault == "keyboard":
        rows[2]["matched"]["hover"] = True
    elif fault == "missing":
        evidence["observations"].remove(rows[0])
    elif fault == "duplicate":
        evidence["observations"][-1] = deepcopy(rows[0])
    else:
        evidence["observations"][0]["seconds"] = .3
    with pytest.raises(ValueError):
        measure.validate_measurements(evidence, deferred=True)


def test_local_evidence_stays_strict_and_policy_bounds_match_the_binding():
    evidence = measurements()
    for row in webkit_rows(evidence):
        row["seconds"] = .6
    with pytest.raises(ValueError, match="budget"):
        measure.validate_measurements(evidence)
    assert load_tool("release.latency_bindings").SCOPE["functional_seconds"] == measure.FUNCTIONAL_SECONDS
    assert load_tool("release.latency_bindings").SCOPE["strict_seconds"] == measure.STRICT_SECONDS
    assert load_tool("release.latency_bindings").SCOPE["process_seconds"] == load_tool("verification.hover_process").SECONDS


@pytest.mark.parametrize("seconds,passes", [(.6, True), (1.999, True), (2., False)])
def test_finite_functional_clock_starts_before_input_and_finishes_after_style(monkeypatch, seconds, passes):
    observer = load_tool("verification.hover_observation")
    now = [0.]
    monkeypatch.setattr(observer, "perf_counter", lambda: now[0])
    count = [0]
    def sample(_):
        count[0] += 1
        if count[0] == 1:
            return measure.HIDDEN
        now[0] += seconds / 2
        return measure.MATCHED["hover"]
    def action():
        now[0] += seconds / 2
    records = []
    def run():
        return observer.observe_input(None, SimpleNamespace(evaluate=sample), action,
            visible=True, phase="hover", record=records.append, limit=2.0)
    if passes:
        assert run() == pytest.approx(seconds)
        assert records[0]["seconds"] == pytest.approx(seconds)
    else:
        with pytest.raises(AssertionError):
            run()
        assert not records
