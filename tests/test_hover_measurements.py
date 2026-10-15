"""Passing case counts cannot substitute for all raw real-input observations."""
from copy import deepcopy
import json

import pytest

from hover_measurement_fixture import PROCESS, hosted_measurements, measure, measurements
from qualification_fixture import policy, producer, visual_evidence


def files(evidence):
    return {"hover/verification.json": policy.canonical(evidence),
        "hover/process.json": policy.canonical(PROCESS)}


def producer_case():
    data, journal = hosted_measurements()
    return (visual_evidence("hover", hover=data), journal, {"source": data["timing_context"]["source"]},
        {"run": 77, "attempt": 1, "job_key": "visual"})


def test_every_case_target_and_phase_has_an_actual_strict_measurement():
    evidence = measurements()
    summary = measure.validate_measurements(evidence)
    assert summary == evidence["observation_summary"]
    assert summary["observations"] == 648
    assert all(phases == dict.fromkeys(measure.PHASES, .01) for phases in summary["maximum_seconds"].values())
    assert measure.validate_summary(summary) == summary


@pytest.mark.parametrize("value", [True, False, None, "0.1", -.001, .25, .3,
    float("nan"), float("inf"), float("-inf"), 10**1000])
def test_untyped_nonfinite_or_late_measurements_cannot_qualify(value):
    evidence = measurements()
    evidence["observations"][0]["seconds"] = value
    with pytest.raises(ValueError, match="budget"):
        measure.validate_measurements(evidence)


@pytest.mark.parametrize("fault", ["contract", "missing", "duplicate", "target", "boolean-target",
    "phase", "extra-field", "extra-case", "case", "order", "baseline", "continuity",
    "visible", "hover", "keyboard", "hidden", "untyped-state"])
def test_inventory_sequence_baseline_and_modality_are_all_required(fault):
    evidence = measurements()
    rows = evidence["observations"]
    if fault == "contract":
        evidence["observation_contract"] = True
    elif fault == "missing":
        rows.pop()
    elif fault == "duplicate":
        rows[-1] = deepcopy(rows[0])
    elif fault in ("target", "boolean-target"):
        rows[0]["target"] = 3 if fault == "target" else True
    elif fault == "phase":
        rows[0]["phase"] = "eventually visible"
    elif fault == "extra-field":
        rows[0]["eventually_passed"] = True
    elif fault == "extra-case":
        rows[0]["case"]["diagnostic"] = True
    elif fault == "case":
        rows[0]["case"]["engine"] = "native"
    elif fault == "order":
        rows[0], rows[1] = rows[1], rows[0]
    elif fault == "baseline":
        rows[0]["baseline"] = deepcopy(measure.MATCHED["hover"])
    elif fault == "continuity":
        rows[1]["baseline"] = deepcopy(measure.HIDDEN)
    elif fault == "keyboard":
        rows[2]["matched"]["hover"] = True
    elif fault == "hidden":
        rows[1]["matched"]["active"] = True
    else:
        rows[0]["matched"]["visible" if fault in ("visible", "untyped-state") else "hover"] = (
            1 if fault == "untyped-state" else False)
    with pytest.raises(ValueError):
        measure.validate_measurements(evidence)


def test_hide_baseline_is_the_actual_preceding_hover_without_an_extra_style_read():
    log = measure.HoverMeasurements()
    record = log.recorder({"engine": "webkit", "scenario": "tokens", "theme": "day", "width": 360}, 0)
    with pytest.raises(ValueError, match="no preceding"):
        record({"phase": "hide", "seconds": .01, "baseline": None, "matched": measure.HIDDEN})
    value = {"phase": "hover", "seconds": .01, "baseline": measure.HIDDEN,
        "matched": deepcopy(measure.MATCHED["hover"])}
    record(value)
    record({"phase": "hide", "seconds": .01, "baseline": None, "matched": measure.HIDDEN})
    value["matched"]["hover"] = False
    assert log.rows[1]["baseline"] == measure.MATCHED["hover"]
    assert log.rows[0]["matched"] == measure.MATCHED["hover"]


@pytest.mark.parametrize("fault", ["count", "boolean-count", "status", "digest", "phase", "late", "boolean-schema"])
def test_untrusted_summary_is_not_raw_measurement_proof(fault):
    summary = measurements()["observation_summary"]
    if fault == "count":
        summary["observations"] = 647
    elif fault == "boolean-count":
        summary["observations"] = True
    elif fault == "status":
        summary["status"] = "deferred-known-latency"
    elif fault == "digest":
        summary["sha256"] = "not a digest"
    elif fault == "phase":
        summary["maximum_seconds"]["chromium"].pop("hide")
    elif fault == "late":
        summary["maximum_seconds"]["chromium"]["keyboard"] = .25
    else:
        summary["schema"] = True
    with pytest.raises(ValueError):
        measure.validate_summary(summary)


@pytest.mark.parametrize("fault", ["missing", "incomplete", "late", "forged-summary"])
def test_producer_requires_raw_measurements_even_for_a_complete_case_inventory(fault):
    evidence, journal, metadata, origin = producer_case()
    if fault == "missing":
        evidence.pop("observations")
    elif fault == "incomplete":
        evidence["observations"].pop()
    elif fault == "late":
        evidence["observations"][0]["seconds"] = .3
    else:
        evidence["observations"][0]["seconds"] = .02
    with pytest.raises(ValueError):
        producer.validate_payload(metadata, files(evidence), "visual-hover", origin=origin, journal=journal)


def test_producer_keeps_a_compact_digest_summary_not_a_second_raw_copy():
    evidence, journal, metadata, origin = producer_case()
    result = producer.validate_payload(metadata, files(evidence), "visual-hover", origin=origin, journal=journal)
    actual = result["visual"]["hover"]
    assert actual["observation_summary"] == evidence["observation_summary"]
    assert "observations" not in actual
    assert len(json.dumps(actual)) < len(json.dumps(evidence)) / 5
