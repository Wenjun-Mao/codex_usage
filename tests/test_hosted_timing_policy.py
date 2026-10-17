"""Measured hosted WebKit latency is not a renewable publication exception."""
from copy import deepcopy
import json
import sys

import pytest

from hover_measurement_fixture import hosted_measurements, measure
from journal_fixture import JournalFixture
from latency_binding_fixture import anchor, binding, intent
from publication_fixture import PublicationFixture
from qualification_fixture import FixtureAPI, policy, producer
from release_tooling_support import load_tool

context = load_tool("release.latency_context")
qualification = load_tool("qualification")
writer = load_tool("publication_intent")
ORIGIN = {"run": 77, "attempt": 1, "job_key": "visual"}


def observed():
    return hosted_measurements({"repository": policy.REPOSITORY, "repository_id": 123,
        "sha": "a"*40, "version": "2.12.4", "contract": "b"*64, "workflow": policy.WORKFLOW, "probe": False})[0]


def test_future_hosted_policy_needs_no_exception_or_journal_read(monkeypatch):
    evidence = observed()
    source = evidence["timing_context"]["source"]
    monkeypatch.setattr(context, "Journal", lambda *_: pytest.fail("Normal timing must not resolve an exception"))
    monkeypatch.setattr(producer, "source_context", lambda *_: source)
    env = {"GITHUB_ACTIONS": "true", "GITHUB_JOB": "visual", "GITHUB_RUN_ID": "77", "GITHUB_RUN_ATTEMPT": "1"}
    assert context.runtime_context(env) == evidence["timing_context"]
    assert context.validate_context(evidence["timing_context"], source=source, origin=ORIGIN) == measure.OBSERVED
    assert context.timing_fields(source, publication=True) == {"timing_disposition": measure.OBSERVED}
    for version in ("2.12.4", "2.12.5", "2.13.0", "3.0.0"):
        assert context.hosted_policy({**source, "version": version}) == measure.OBSERVED


@pytest.mark.parametrize("seconds,passes", [(0., True), (.249, True), (.25, True), (.6, True),
    (1.999, True), (2., False), (True, False), (-.1, False), (".3", False), (float("nan"), False), (float("inf"), False)])
def test_record_only_threshold_preserves_a_finite_functional_limit(seconds, passes):
    evidence = observed()
    for row in evidence["observations"]:
        if row["case"]["engine"] == "webkit":
            row["seconds"] = seconds
    if not passes:
        with pytest.raises(ValueError):
            measure.validate_measurements(evidence, policy=measure.OBSERVED)
        return
    summary = measure.validate_measurements(evidence, policy=measure.OBSERVED)
    assert summary["status"] == measure.OBSERVED and summary["schema"] == 3
    assert summary["strict_exceedances"] == (216 if seconds >= .25 else 0)
    assert summary["report_only_observations"] == 216 and summary["deferred_observations"] == 0
    assert summary["maximum_seconds"]["webkit"] == dict.fromkeys(measure.PHASES, seconds)
    assert measure.validate_summary(summary, policy=measure.OBSERVED) == summary


@pytest.mark.parametrize("fault", ["chromium", "firefox", "missing", "baseline", "keyboard", "label", "legacy-schema"])
def test_normal_policy_does_not_relax_other_engines_or_functionality(fault):
    evidence = observed()
    rows = evidence["observations"]
    if fault in ("chromium", "firefox"):
        next(row for row in rows if row["case"]["engine"] == fault)["seconds"] = .25
    elif fault == "missing":
        rows.pop()
    elif fault == "legacy-schema":
        evidence["observation_contract"] = 2
    else:
        row = next(row for row in rows if row["case"]["engine"] == "webkit" and row["phase"] == "keyboard")
        if fault == "label":
            row["disposition"] = "passed"
        else:
            row["baseline" if fault == "baseline" else "matched"]["hover"] = True
    with pytest.raises(ValueError):
        measure.validate_measurements(evidence, policy=measure.OBSERVED)


@pytest.mark.parametrize("fault", ["exceedances", "count", "bool", "max", "status"])
def test_summary_cannot_hide_observations_or_claim_a_strict_pass(fault):
    summary = observed()["observation_summary"]
    if fault == "exceedances":
        summary["strict_exceedances"] = 1
    elif fault == "count":
        summary["report_only_observations"] = 215
    elif fault == "bool":
        summary["strict_exceedances"] = False
    elif fault == "max":
        summary["maximum_seconds"]["webkit"]["hover"] = 2.
    else:
        summary["status"] = "passed"
    with pytest.raises(ValueError):
        measure.validate_summary(summary, policy=measure.OBSERVED)


@pytest.mark.parametrize("late_phases,count", [(3, 1), (1, 73), (1, 216)])
def test_summary_exceedances_must_fit_the_per_phase_inventory(late_phases, count):
    summary = observed()["observation_summary"]
    for phase in measure.PHASES[:late_phases]:
        summary["maximum_seconds"]["webkit"][phase] = .6
    summary["strict_exceedances"] = count
    with pytest.raises(ValueError, match="count"):
        measure.validate_summary(summary, policy=measure.OBSERVED)


@pytest.mark.parametrize("fault", ["origin", "local", "source", "binding", "missing-binding"])
def test_normal_context_cannot_be_forged_or_borrow_a_legacy_binding(fault):
    value = observed()["timing_context"]
    source = deepcopy(value["source"])
    if fault == "origin":
        value["origin"]["attempt"] = 2
    elif fault == "local":
        value = dict(context.LOCAL)
    elif fault == "source":
        value["source"]["version"] = "2.12.3"
    elif fault == "binding":
        value["binding"] = {"commit": "e"*40}
    else:
        value.pop("binding")
    with pytest.raises(ValueError):
        context.validate_context(value, source=source, origin=ORIGIN)


def test_freeze_inspection_and_raw_payload_preserve_observed_policy():
    api = FixtureAPI(version="2.12.4", webkit_seconds=.6)
    manifest = api.reader().freeze()
    assert manifest["timing_disposition"] == measure.OBSERVED and "latency_binding" not in manifest
    api.add_gate("hosted", {"hosted.json": policy.canonical(manifest)})
    assert api.reader().hosted()[1] == manifest
    assert api.journal.read()["records"] == []


@pytest.mark.parametrize("fault", ["old-binding", "null-binding", "passed", "deferred", "missing"])
def test_frozen_manifest_cannot_change_the_source_policy(fault):
    api = FixtureAPI(version="2.12.4")
    manifest = api.reader().freeze()
    if fault.endswith("binding"):
        manifest["latency_binding"] = None if fault == "null-binding" else {"commit": "e"*40}
    elif fault == "missing":
        manifest.pop("timing_disposition")
    else:
        manifest["timing_disposition"] = "passed" if fault == "passed" else measure.DEFERRED
    api.add_gate("hosted", {"hosted.json": policy.canonical(manifest)})
    with pytest.raises(ValueError):
        api.reader().hosted()


def test_new_publication_keeps_old_receipts_and_duplicate_upload_fencing(tmp_path, monkeypatch):
    api = PublicationFixture(version="2.12.4")
    old = JournalFixture(repository_id=123)
    value = binding(old, purpose="release", source_version="2.12.3")
    ack = anchor(old, value)
    for target in policy.TARGETS:
        old.journal.anchor(old.journal.candidate(intent(old, value, ack, target)))
    before = deepcopy(old.journal.read()["records"])
    api.journal = old.journal
    api.install(monkeypatch, qualification)
    result = api.validate(qualification, tmp_path)
    assert result["timing_disposition"] == measure.OBSERVED and "latency_binding" not in result
    qualification.main(["check-files", "--directory", str(tmp_path)])
    api.install_writer(monkeypatch, writer)
    for target in policy.TARGETS:
        monkeypatch.setattr(sys, "argv", ["publication_intent.py", "prepare", "--directory", str(tmp_path), "--target", target])
        writer.main()
        body = json.loads((tmp_path / f"intent-{target}/intent.json").read_text())
        assert "latency_binding" not in body and body["source"] == api.source
        with pytest.raises(ValueError, match="already has a retained"):
            writer.main()
    after = old.journal.read()["records"]
    assert after[:len(before)] == before and len(after) == len(before) + 2


@pytest.mark.parametrize("fault", ["probe", "dispatch-sha", "dispatch-ref", "dispatch-attempt", "dispatch-event",
    "tag-source", "closure", "checkout-marker", "native-job"])
def test_modern_publication_still_requires_the_full_proof_and_dispatch(tmp_path, monkeypatch, fault):
    api = PublicationFixture(version="2.12.4", probe=fault == "probe")
    api.install(monkeypatch, qualification)
    if fault.startswith("dispatch-"):
        key, value = {"dispatch-sha": ("head_sha", "e"*40), "dispatch-ref": ("head_branch", "main"),
            "dispatch-attempt": ("run_attempt", 2), "dispatch-event": ("event", "push")}[fault]
        api.publication[key] = value
    elif fault == "tag-source":
        raw = api.raw
        api.raw = lambda endpoint: (policy.canonical({"object": {"type": "commit", "sha": "e"*40}})
            if "/git/ref/tags/" in endpoint else raw(endpoint))
    elif fault in ("closure", "checkout-marker"):
        monkeypatch.delenv("GITHUB_ACTIONS")
        if fault == "closure":
            api.publisher_tree[policy.PROMOTION_WORKFLOW] = "e"*40
        else:
            logs = api.logs
            api.logs = lambda job: "missing checkout marker" if job == 5000 else logs(job)
    elif fault == "native-job":
        api.job_rows["native"]["conclusion"] = "failure"
    with pytest.raises(ValueError):
        api.validate(qualification, tmp_path)
    path = tmp_path / "qualified.json"
    assert not path.exists() or json.loads(path.read_text())["status"] != "validated-for-publication"
    assert api.journal.read()["records"] == []


@pytest.mark.parametrize("fault", ["passed", "deferred", "null-binding", "manifest", "contract", "publisher", *policy.TARGETS])
def test_modern_preupload_check_refuses_policy_authority_or_byte_drift(tmp_path, monkeypatch, fault):
    api = PublicationFixture(version="2.12.4")
    api.install(monkeypatch, qualification)
    result = api.validate(qualification, tmp_path)
    if fault in policy.TARGETS:
        path = tmp_path / f"codex-usage-companion-{fault}.vsix"
        path.write_bytes(path.read_bytes() + b"different bytes")
    else:
        if fault in ("passed", "deferred"):
            result["timing_disposition"] = result["manifest"]["timing_disposition"] = (
                "passed" if fault == "passed" else measure.DEFERRED)
        elif fault == "null-binding":
            result["latency_binding"] = None
        elif fault == "manifest":
            result["manifest"]["run"] += 1
        elif fault == "contract":
            result["source"]["contract"] = result["manifest"]["source"]["contract"] = "e"*64
        else:
            result["promotion"]["publisher_sha"] = "e"*40
        if fault != "manifest":
            result["manifest_sha256"] = policy.fingerprint(result["manifest"])
        (tmp_path / "qualified.json").write_bytes(policy.canonical(result))
    with pytest.raises(ValueError):
        qualification.main(["check-files", "--directory", str(tmp_path)])
