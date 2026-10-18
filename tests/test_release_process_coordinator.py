"""Interruption exercises the real coordinator with synthetic external boundaries."""
import pytest

from release_tooling_support import load_tool
from release_process_fixture import CANDIDATE, Transport

co = load_tool("release.process_coordinator")
state = load_tool("release.process_state")
policy = load_tool("release.policy")


@pytest.fixture
def flow(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "ROOT", tmp_path)
    monkeypatch.setattr(co, "unchanged", lambda *a: None)
    monkeypatch.setattr(co, "preflight", lambda *a, **k: {"reused": False, "suites": list(policy.VISUALS)})
    monkeypatch.setattr(co, "ensure_tag", lambda *a, **k: "v2.12.6")
    monkeypatch.setattr(co, "write_receipt", lambda *a, **k: "synthetic-receipt.md")
    progress = state.Progress(tmp_path / "output/process", CANDIDATE)
    with progress.locked():
        api = Transport()
        yield co.Coordinator(progress, api=api, run_command=api.command), api, progress


def dispatches(api):
    return [call for call in api.calls if call[:3] == ["gh", "workflow", "run"]]


def test_prepare_and_explicit_promotion_preserve_all_boundaries(flow):
    coordinator, api, progress = flow
    result = coordinator.prepare("v2.12.5")
    assert result["id"] == 100 and len(dispatches(api)) == 1
    assert coordinator.promote(100, 1) == "synthetic-receipt.md"
    assert len(dispatches(api)) == 3 and progress.data["status"] == "publicly-verified"
    assert not any("package:vsix" in arg for args in api.calls for arg in args)
    assert set(progress.data["workflows"]) == {"qualification", "dry-run", "promotion"}
    assert (progress.directory / "timings.json").exists()


def test_observation_resume_does_not_cross_new_publication_boundary(flow):
    coordinator, api, progress = flow
    with pytest.raises(state.Pending):
        coordinator.resume(None)
    assert api.calls == []
    coordinator.prepare("v2.12.5")
    coordinator.resume(None)
    assert len(dispatches(api)) == 1
    coordinator.dry_run(100, 1, allow=True)
    with pytest.raises(state.Pending, match="explicit promote"):
        coordinator.resume(None)
    assert len(dispatches(api)) == 2


def test_lost_qualification_reply_resumes_the_accepted_run_without_dispatch(flow):
    coordinator, api, progress = flow
    api.lose = policy.WORKFLOW
    with pytest.raises(state.Pending, match="unknown"):
        coordinator.prepare("v2.12.5")
    assert len(dispatches(api)) == 1
    assert coordinator.resume(None)["id"] == 100
    assert len(dispatches(api)) == 1


def test_lost_promotion_reply_resumes_only_its_original_public_verification(flow):
    coordinator, api, progress = flow
    coordinator.prepare("v2.12.5")
    coordinator.dry_run(100, 1, allow=True)
    api.lose = policy.PROMOTION_WORKFLOW
    with pytest.raises(state.Pending, match="unknown"):
        coordinator.promote(100, 1)
    assert len(dispatches(api)) == 3
    assert coordinator.resume(None) == "synthetic-receipt.md"
    assert len(dispatches(api)) == 3


@pytest.mark.parametrize("fault", ["inspection", "dry-artifact", "source", "attempt", "qualification-failed"])
def test_failed_or_changed_proof_never_dispatches_a_publisher(flow, fault):
    coordinator, api, progress = flow
    coordinator.prepare("v2.12.5")
    if fault == "inspection":
        api.bad_inspection = True
    elif fault == "dry-artifact":
        api.artifact_mismatch = True
    else:
        key, value = {"source": ("head_sha", "c" * 40), "attempt": ("run_attempt", 2),
            "qualification-failed": ("conclusion", "failure")}[fault]
        api.runs[100][key] = value
        # The existing proof reader must observe this actual run afresh before promotion.
        def inspect(*args):
            co.finish(progress, api, "qualification", seconds=1)
        coordinator.inspect = inspect
    with pytest.raises((ValueError, KeyError)):
        coordinator.promote(100, 1)
    assert all("dry_run=false" not in call for call in dispatches(api))


def test_failed_partial_publisher_never_retries_or_generates_receipt(flow):
    coordinator, api, progress = flow
    coordinator.prepare("v2.12.5")
    coordinator.dry_run(100, 1, allow=True)
    api.lose = policy.PROMOTION_WORKFLOW
    with pytest.raises(state.Pending):
        coordinator.promote(100, 1)
    api.runs[102]["conclusion"] = "failure"
    with pytest.raises(ValueError, match="ended failure"):
        coordinator.resume(None)
    assert len(dispatches(api)) == 3 and not (progress.directory / "public").exists()


def test_verifier_timeout_retains_truthful_uploaded_pending_status(flow):
    coordinator, api, progress = flow
    coordinator.prepare("v2.12.5")
    coordinator.dry_run(100, 1, allow=True)
    original = api.command
    def timeout(args, **kwargs):
        if "scripts/verify_marketplace_release.cjs" in args:
            raise TimeoutError()
        return original(args, **kwargs)
    coordinator.command = timeout
    with pytest.raises(TimeoutError):
        coordinator.promote(100, 1)
    assert progress.data["status"] == "uploaded-public-verification-pending"
    assert len(dispatches(api)) == 3


def test_failed_preflight_prevents_even_nonpublishing_dispatch(flow, monkeypatch):
    coordinator, api, progress = flow
    def failed(*args, **kwargs):
        raise AssertionError("stale date assertion")
    monkeypatch.setattr(co, "preflight", failed)
    with pytest.raises(AssertionError):
        coordinator.prepare("v2.12.5")
    assert api.calls == [] and progress.data["operations"] == {}
