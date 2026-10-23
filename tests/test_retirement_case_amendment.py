"""A reviewed retirement cannot silently discard unrelated required coverage."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _case_digest(cases):
    encoded = sorted(json.dumps(case, ensure_ascii=False, separators=(",", ":")) for case in cases)
    return hashlib.sha256("\n".join(encoded).encode()).hexdigest()


def test_retirement_amendments_preserve_every_unrelated_required_case():
    manifest = json.loads((ROOT / "scripts/verification/task-transfer-retirement.json").read_text())
    assert manifest["decision"] == "0076-retire-task-transfer"
    for kind, name in (("python", "python-case-baseline.json"), ("extension", "extension-case-baseline.json")):
        baseline = json.loads((ROOT / "scripts/verification" / name).read_text())
        change = manifest[kind]
        current = {json.dumps(case, ensure_ascii=False, separators=(",", ":")) for case in baseline["required"]}
        added = {json.dumps(case, ensure_ascii=False, separators=(",", ":")) for case in change["added"]}
        removed = {json.dumps(case, ensure_ascii=False, separators=(",", ":")) for case in change["removed"]}
        assert added <= current and not removed.intersection(current)
        inherited = current - added
        assert len(inherited) == change["preserved_count"]
        assert _case_digest(json.loads(case) for case in inherited) == change["preserved_sha256"]
        original = inherited | removed
        assert len(original) == change["original_count"]
        assert _case_digest(json.loads(case) for case in original) == change["original_sha256"]
        assert len(current) == len(baseline["required"])
    assert ["tests.test_agent_operations", "test_lane_can_promote_a_coalesced_capture_ahead_of_lower_priority_work"] not in manifest["python"]["removed"]
