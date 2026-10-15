"""Enabled CLI authorization keeps real proof, dispatch, binding and byte guards."""
import json

import pytest

from latency_binding_fixture import latency, successor
from publication_fixture import PublicationFixture, policy
from release_tooling_support import load_tool

qualification = load_tool("qualification")


def assert_not_authorized(directory):
    path = directory / "qualified.json"
    assert not path.exists() or json.loads(path.read_text())["status"] != "validated-for-publication"


def test_enabled_publication_validation_and_package_check_accept_exact_synthetic_proof(tmp_path, monkeypatch):
    api = PublicationFixture()
    api.install(monkeypatch, qualification)
    result = api.validate(qualification, tmp_path)
    assert result["status"] == "validated-for-publication"
    assert result["latency_binding"] == api.hover["timing_context"]["binding"]
    assert result["promotion"]["publisher_sha"] == api.publisher_sha
    qualification.main(["check-files", "--directory", str(tmp_path)])
    assert len(api.journal.read()["records"]) == 1


@pytest.mark.parametrize("fault", ["nonpublishing", "superseded", "probe", "dispatch-sha", "dispatch-event",
    "dispatch-ref", "dispatch-attempt", "environment", "tag-source", "main-ancestry"])
def test_enabled_publication_validation_refuses_ineligible_context(tmp_path, monkeypatch, fault):
    api = PublicationFixture(purpose="nonpublishing" if fault == "nonpublishing" else "release", probe=fault == "probe")
    api.install(monkeypatch, qualification)
    if fault == "superseded":
        row = api.journal.read()["records"][-1]
        value = successor(row["event"]["binding"], api.hover["timing_context"]["binding"], sha="e"*40)
        api.journal.anchor(api.journal.candidate(latency.binding_event(value, api.journal.config)))
    elif fault.startswith("dispatch-"):
        key, value = {"dispatch-sha": ("head_sha", "c"*40), "dispatch-event": ("event", "push"),
            "dispatch-ref": ("head_branch", "main"), "dispatch-attempt": ("run_attempt", 2)}[fault]
        api.publication[key] = value
    elif fault == "environment":
        monkeypatch.setenv("GITHUB_SHA", "c"*40)
    elif fault in ("tag-source", "main-ancestry"):
        original = api.raw

        def drift(endpoint):
            if fault == "tag-source" and "/git/ref/tags/" in endpoint:
                return policy.canonical({"object": {"type": "commit", "sha": "c"*40}})
            if fault == "main-ancestry" and "/compare/" in endpoint:
                return policy.canonical({"merge_base_commit": {"sha": "c"*40}, "status": "diverged"})
            return original(endpoint)

        api.raw = drift
    with pytest.raises(ValueError):
        api.validate(qualification, tmp_path)
    assert_not_authorized(tmp_path)
    assert all(row["event"]["kind"] == latency.KIND for row in api.journal.read()["records"])


@pytest.mark.parametrize("fault", ["status", "manifest", "source", "contract", "binding", "missing-binding",
    "disposition", "publisher", *policy.TARGETS])
def test_enabled_package_check_rejects_authority_or_either_target_drift(tmp_path, monkeypatch, fault):
    api = PublicationFixture()
    api.install(monkeypatch, qualification)
    result = api.validate(qualification, tmp_path)
    if fault in policy.TARGETS:
        path = tmp_path / f"codex-usage-companion-{fault}.vsix"
        path.write_bytes(path.read_bytes() + b"changed upload bytes")
    else:
        if fault == "status":
            result["status"] = "qualified-not-published"
        elif fault == "manifest":
            result["manifest_sha256"] = "e"*64
        elif fault == "source":
            result["source"]["sha"] = "e"*40
        elif fault == "contract":
            result["source"]["contract"] = result["manifest"]["source"]["contract"] = "e"*64
            result["manifest_sha256"] = policy.fingerprint(result["manifest"])
        elif fault == "binding":
            result["latency_binding"]["commit"] = "e"*40
        elif fault == "missing-binding":
            result.pop("latency_binding")
        elif fault == "disposition":
            result["timing_disposition"] = result["manifest"]["timing_disposition"] = "passed"
            result["manifest_sha256"] = policy.fingerprint(result["manifest"])
        else:
            result["promotion"]["publisher_sha"] = "e"*40
        (tmp_path / "qualified.json").write_bytes(policy.canonical(result))
    with pytest.raises(ValueError):
        qualification.main(["check-files", "--directory", str(tmp_path)])


@pytest.mark.parametrize("fault", [None, "closure", "checkout-marker"])
def test_enabled_nonhosted_validation_checks_original_publisher_closure(tmp_path, monkeypatch, fault):
    api = PublicationFixture()
    api.install(monkeypatch, qualification)
    monkeypatch.delenv("GITHUB_ACTIONS")
    if fault == "closure":
        api.publisher_tree[policy.PROMOTION_WORKFLOW] = "e"*40
    elif fault == "checkout-marker":
        original = api.logs
        api.logs = lambda job_id: "missing checkout marker" if job_id == 5000 else original(job_id)
    if fault:
        with pytest.raises(ValueError):
            api.validate(qualification, tmp_path)
        assert_not_authorized(tmp_path)
    else:
        assert api.validate(qualification, tmp_path)["promotion"]["publisher_sha"] == api.publisher_sha
