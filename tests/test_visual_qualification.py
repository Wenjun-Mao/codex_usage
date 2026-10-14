"""Coverage identities and failing journals, independent of browser transport."""
from copy import deepcopy
import json

import pytest

from release_tooling_support import load_tool

cases = load_tool("verification.visual_cases")
ASSERTIONS, case_key = cases.ASSERTIONS, cases.case_key
expected_cases, validate_inventory = cases.expected_cases, cases.validate_inventory
VisualEvidence = load_tool("verification.visual_evidence").VisualEvidence


def evidence(suite):
    return {"schema": 1, "suite": suite, "status": "passed", "synthetic_only": True,
        "assertions": list(ASSERTIONS[suite]), "completed": expected_cases(suite)}


@pytest.mark.parametrize("suite,count", [("breakdown", 720), ("speed", 162),
    ("overlay", 90), ("hover", 72), ("allowance", 216), ("screenshots", 15), ("economics", 18)])
def test_independent_complete_tuple_inventory(suite, count):
    sample = evidence(suite)
    assert len(sample["completed"]) == count
    validate_inventory(sample, suite)
    assert len({case_key(case) for case in sample["completed"]}) == count


@pytest.mark.parametrize("change", ["missing", "duplicate", "wrong-width", "assertions",
    "failed", "incomplete", "private", "schema"])
def test_same_count_or_partial_evidence_cannot_qualify(change):
    sample = evidence("hover")
    if change == "missing":
        sample["completed"].pop()
    elif change == "duplicate":
        sample["completed"][-1] = deepcopy(sample["completed"][0])
    elif change == "wrong-width":
        sample["completed"][0]["width"] = 361
    elif change == "assertions":
        sample["assertions"].pop()
    elif change in ("failed", "incomplete"):
        sample["status"] = change
    elif change == "private":
        sample["synthetic_only"] = False
    else:
        sample["schema"] = 2
    with pytest.raises(ValueError):
        validate_inventory(sample, "hover")


def test_failure_keeps_original_exception_current_and_completed_cases(tmp_path):
    first, second = expected_cases("hover")[:2]
    original = AssertionError("original assertion")
    class BrokenPage:
        def evaluate(self, source):
            raise RuntimeError("diagnostics unavailable")
    with pytest.raises(AssertionError) as raised:
        with VisualEvidence(tmp_path, "hover") as audit:
            with audit.case(None, first):
                pass
            with audit.case(BrokenPage(), second):
                raise original
    assert raised.value is original
    saved = json.loads((tmp_path / "verification.json").read_text())
    assert saved["completed"] == [first] and saved["current"] == second
    assert saved["status"] == "failed" and saved["failure"]["type"] == "AssertionError"
    assert "diagnostics unavailable" in saved["failure"]["diagnostic_error"]


def test_controlled_fault_injection_is_explicit_and_cannot_pass(tmp_path, monkeypatch):
    case = expected_cases("hover")[0]
    monkeypatch.setenv("CODEX_VISUAL_FAIL_CASE", case_key(case))
    with pytest.raises(AssertionError, match="Requested synthetic"):
        with VisualEvidence(tmp_path, "hover") as audit:
            with audit.case(None, case):
                pytest.fail("body must not run")
    assert json.loads((tmp_path / "verification.json").read_text())["status"] == "failed"


def test_missing_body_cases_fail_at_finish_and_private_is_not_receipt(tmp_path):
    with pytest.raises(ValueError, match="case mismatch"):
        with VisualEvidence(tmp_path / "missing", "hover"):
            pass
    with VisualEvidence(tmp_path / "private", "overlay", synthetic_only=False):
        pass
    private = json.loads((tmp_path / "private/verification.json").read_text())
    assert private["status"] == "diagnostic-only"
    with pytest.raises(ValueError):
        validate_inventory(private, "overlay")


def test_complete_journal_preserves_document_hash_and_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    with VisualEvidence(tmp_path, "hover") as audit:
        audit.document("fixture", "unchanged production HTML")
        for case in expected_cases("hover"):
            with audit.case(None, case):
                pass
    saved = json.loads((tmp_path / "verification.json").read_text())
    validate_inventory(saved, "hover")
    assert len(saved["documents"]["fixture"]) == 64
    assert saved["origin"]["GITHUB_RUN_ATTEMPT"] == "2" and saved["current"] is None
