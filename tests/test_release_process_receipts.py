"""Truthful official-byte receipts and deterministic, manual-edit-safe documents."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from release_tooling_support import load_tool
from release_process_fixture import CANDIDATE, write_public

receipts = load_tool("release.process_receipts")
timings = load_tool("release.process_timings")


def test_receipt_requires_both_official_bytes_and_retained_publisher(tmp_path):
    public, q = write_public(tmp_path)
    assert receipts.checked_public(tmp_path, CANDIDATE) == (public, q)
    (tmp_path / "official-win32-x64.vsix").write_bytes(b"other")
    with pytest.raises(ValueError, match="bytes differ"):
        receipts.checked_public(tmp_path, CANDIDATE)


@pytest.mark.parametrize("fault", ["pending", "one-target", "duplicate", "source", "attempt", "intent", "manifest"])
def test_unverified_or_foreign_facts_cannot_produce_a_published_receipt(tmp_path, fault):
    public, q = write_public(tmp_path)
    publisher = json.loads((tmp_path / "publisher-proof.json").read_text())
    if fault == "pending":
        q["status"] = "uploaded-awaiting-public-validation"
    elif fault == "one-target":
        public["targets"].pop()
    elif fault == "duplicate":
        public["targets"][1] = deepcopy(public["targets"][0])
    elif fault == "source":
        public["commit"] = "c" * 40
    elif fault == "attempt":
        public["promotionAttempt"] = 2
    elif fault == "intent":
        publisher["prior_intents"].pop("win32-x64")
    else:
        q["manifest"]["source"]["sha"] = "c" * 40
    for name, data in {"verification.json": public, "qualified.json": q, "publisher-proof.json": publisher}.items():
        (tmp_path / name).write_text(json.dumps(data))
    with pytest.raises(ValueError):
        receipts.checked_public(tmp_path, CANDIDATE)


@pytest.mark.parametrize("instant,day,clock", [("2026-10-18T01:33:18Z", "2026-10-17", "21:33:18 EDT"),
    ("2026-11-01T05:30:00Z", "2026-11-01", "01:30:00 EDT"),
    ("2026-11-01T06:30:00Z", "2026-11-01", "01:30:00 EST")])
def test_receipt_clock_preserves_toronto_date_and_repeated_hour(tmp_path, instant, day, clock):
    public, q = write_public(tmp_path)
    public["verifiedAt"] = instant
    observed_day, text = receipts.receipt_text(public, q, {"id": 101, "run_attempt": 1})
    assert observed_day == day and clock in text and "Native Windows UI" in text
    assert "no delay" not in text and "not a claim" in text


def test_reverification_keeps_original_timestamp_across_toronto_midnight(tmp_path):
    public, q = write_public(tmp_path)
    public["verifiedAt"] = "2026-10-18T03:59:59Z"
    progress = SimpleNamespace(intents={}, save=lambda: None)
    original = receipts.pinned_verification(progress, public, q)
    again = receipts.pinned_verification(progress, {**public, "verifiedAt": "2026-10-18T04:00:01Z"}, q)
    assert again == original
    assert receipts.receipt_text(again, q, {"id": 101, "run_attempt": 1}) == receipts.receipt_text(original, q, {"id": 101, "run_attempt": 1})
    with pytest.raises(ValueError, match="facts differ"):
        receipts.pinned_verification(progress, {**public, "promotionRun": 999}, q)


def guides():
    return {"docs/release.md": "# VSIX Releases\n\nCodex Usage 2.12.5 ships only two packages.\n\n## Historical receipt\nKeep unchanged.\n",
        "docs/release/qualified-promotion.md": "# Qualified VSIX Promotion\n\nStatus: 2.12.5 is published. The\n[latest receipt](old.md) binds proof.\n\n## Safety\nKeep unchanged.\n"}


def test_receipt_writes_are_idempotent_and_preserve_manual_changes(tmp_path, monkeypatch):
    public, q = write_public(tmp_path / "evidence")
    original = guides()
    for name, text in original.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    monkeypatch.setattr(receipts, "git", lambda *args, **kwargs: original[args[1].split(":", 1)[1]])
    progress = SimpleNamespace(candidate=CANDIDATE, directory=tmp_path)
    dry = {"id": 101, "run_attempt": 1}
    name = receipts.write_receipt(progress, public, q, dry, root=tmp_path)
    after = {p: (tmp_path / p).read_text() for p in (*original, name)}
    assert receipts.write_receipt(progress, public, q, dry, root=tmp_path) == name
    assert after == {p: (tmp_path / p).read_text() for p in after}
    assert after["docs/release.md"].endswith("## Historical receipt\nKeep unchanged.\n")
    (tmp_path / "docs/release.md").write_text(after["docs/release.md"] + "Human change\n")
    with pytest.raises(ValueError, match="manual"):
        receipts.write_receipt(progress, public, q, dry, root=tmp_path)
    assert (tmp_path / "docs/release.md").read_text().endswith("Human change\n")


def test_overlapping_job_times_are_not_added_as_release_elapsed_time():
    run = {"id": 1, "run_attempt": 1, "created_at": "2026-10-17T00:00:00Z", "updated_at": "2026-10-17T00:00:30Z"}
    job = {"name": "x", "status": "completed", "conclusion": "success", "created_at": run["created_at"],
        "started_at": "2026-10-17T00:00:05Z", "completed_at": "2026-10-17T00:00:25Z", "steps": []}
    result = timings.workflow_timing(run, [job, {**job, "name": "y"}])
    assert result["wall_seconds"] == 30 and result["concurrent_runner_seconds"] == 40
