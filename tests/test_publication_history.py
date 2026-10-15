"""Failed publishers establish uncertainty, never authority to re-upload."""
import pytest

from qualification_fixture import FixtureAPI, policy
from release_tooling_support import load_tool

history = load_tool("release.publication_history")


class HistoryAPI(FixtureAPI):
    def __init__(self, *, attempted=True, recorded=True, bound_timing=False):
        self.publisher_sha = "d" * 40
        super().__init__(version="2.12.3" if bound_timing else "2.12.2",
            binding_purpose="release" if bound_timing else "nonpublishing")
        manifest = self.reader().freeze()
        self.qualified = {"schema": 1, "status": "validated-for-publication", "source": self.source,
            "tag": "v" + self.source["version"], "qualification_run": 77, "qualification_attempt": 1,
            "manifest_sha256": policy.fingerprint(manifest), "manifest": manifest}
        if bound_timing:
            self.qualified["latency_binding"] = manifest["latency_binding"]
        self.publication = {**self.run_data, "id": 88, "path": policy.PROMOTION_WORKFLOW,
            "head_branch": self.qualified["tag"], "conclusion": "failure", "run_number": 1}
        self.validation = {"id": 301, "name": "Validate qualification", "status": "completed", "conclusion": "success",
            "started_at": "2026-10-13T01:00:00Z", "completed_at": "2026-10-13T01:00:10Z"}
        self.publisher = {"id": 302, "name": "Publish qualified packages", "status": "completed", "conclusion": "failure",
            "started_at": "2026-10-13T01:00:20Z", "completed_at": "2026-10-13T01:01:00Z",
            "steps": [{"name": f"Publish {target}", "status": "completed", "conclusion":
                "failure" if attempted and target == "darwin-arm64" else "skipped"} for target in policy.TARGETS]}
        self.validation_log = history.CHECKOUT + self.publisher_sha + "\n"
        self.publisher_log = ""
        self.record = None
        if recorded:
            target = "darwin-arm64"
            data = {"schema": 1, "kind": "publication-intent", "source": self.source, "tag": self.qualified["tag"],
                "qualification_run": 77, "qualification_attempt": 1, "manifest_sha256": self.qualified["manifest_sha256"],
                "publisher_sha": self.publisher_sha, "target": target, "package": manifest["packages"][target],
                "origin": {"run": 88, "attempt": 1, "job": "publish"}}
            if bound_timing:
                data["latency_binding"] = manifest["latency_binding"]
            self.record = self.upload("intent-darwin-arm64-r88-a1", {"intent.json": policy.canonical(data)})
            self.record["workflow_run"]["id"] = 88
            self.publisher_log = history.PREFIX + policy.canonical({"target": target, "run": 88,
                "attempt": 1, "artifact_id": self.record["id"], "artifact_digest": self.record["digest"].removeprefix("sha256:")}).decode()

    def run(self, run_id):
        if run_id == 99:
            return {**self.publication, "id": 99, "run_number": self.publication["run_number"] + 1,
                "head_sha": self.source["sha"], "status": "in_progress", "conclusion": None}
        return self.publication if run_id == 88 else super().run(run_id)

    def pages(self, endpoint, field):
        return [self.publication] if "/workflows/promote-vsix.yml/runs" in endpoint else super().pages(endpoint, field)

    def jobs(self, run_id, attempt):
        return [self.validation, self.publisher] if run_id == 88 else super().jobs(run_id, attempt)

    def logs(self, job_id):
        if job_id == 301:
            return self.validation_log
        if job_id == 302:
            return self.publisher_log
        return super().logs(job_id)

    def contract_tree(self, source_sha):
        return self.blobs.copy() if source_sha == self.publisher_sha else super().contract_tree(source_sha)


def test_valid_intent_from_failed_publisher_means_possibly_uploaded():
    api = HistoryAPI()
    assert history.prior_intents(api, api.qualified, 99, 1, api.blobs) == {"darwin-arm64": True}


def test_not_attempted_target_is_distinct_from_missing_catalog_entry():
    api = HistoryAPI(attempted=False, recorded=False)
    assert history.prior_intents(api, api.qualified, 99, 1, api.blobs) == {}


@pytest.mark.parametrize("fault", ["missing-intent", "duplicate", "digest", "expired", "failed-validation",
    "missing-checkout", "wrong-closure", "running", "unknown-step-inventory"])
def test_missing_untrusted_or_ambiguous_history_blocks_automatic_retry(fault):
    api = HistoryAPI(recorded=fault != "missing-intent")
    if fault == "duplicate":
        api.publisher_log *= 2
    elif fault == "digest":
        api.record["digest"] = "sha256:" + "0"*64
    elif fault == "expired":
        api.record["expired"] = True
    elif fault == "failed-validation":
        api.validation["conclusion"] = "failure"
    elif fault == "missing-checkout":
        api.validation_log = "no trusted marker"
    elif fault == "wrong-closure":
        old = api.blobs.copy()
        api.blobs[policy.PROMOTION_WORKFLOW] = "e"*40
        with pytest.raises(ValueError):
            history.prior_intents(api, api.qualified, 99, 1, old)
        return
    elif fault == "running":
        api.publisher["status"] = "in_progress"
    elif fault == "unknown-step-inventory":
        api.publisher["steps"] = []
    with pytest.raises(ValueError):
        history.prior_intents(api, api.qualified, 99, 1, api.blobs)


def test_current_execution_is_excluded_but_previous_attempt_is_not():
    api = HistoryAPI()
    assert history.prior_intents(api, api.qualified, 88, 1, api.blobs) == {}
    api.publication["run_attempt"] = 2
    assert history.prior_intents(api, api.qualified, 88, 2, api.blobs) == {"darwin-arm64": True}


def test_previous_upload_cannot_disappear_after_release_tag_source_drift():
    api = HistoryAPI()
    api.publication["head_sha"] = "e" * 40
    with pytest.raises(ValueError, match="conflicting dispatch source"):
        history.prior_intents(api, api.qualified, 99, 1, api.blobs)


def test_copied_validation_rows_with_distinct_ids_use_original_only_logs():
    api = HistoryAPI()
    original_jobs = api.jobs
    copied = {**api.validation, "id": 401, "run_attempt": 2}
    api.jobs = lambda run_id, attempt: [copied, api.publisher] if run_id == 88 and attempt == 2 else original_jobs(run_id, attempt)
    assert history.original_successful_job(api, 88, 2, "Validate qualification")["id"] == 301
    api.publication["run_attempt"] = 3
    assert history.prior_intents(api, api.qualified, 99, 1, api.blobs) == {"darwin-arm64": True}


def test_reexecuted_validation_requires_its_own_original_marker():
    api = HistoryAPI()
    original_jobs = api.jobs
    rerun = {**api.validation, "id": 401, "started_at": "2026-10-13T01:02:00Z", "completed_at": "2026-10-13T01:02:10Z"}
    api.jobs = lambda run_id, attempt: [rerun, api.publisher] if run_id == 88 and attempt == 2 else original_jobs(run_id, attempt)
    original_logs = api.logs
    api.logs = lambda identifier: "no marker" if identifier == 401 else original_logs(identifier)
    with pytest.raises(ValueError, match="checkout marker"):
        history.publisher_revision(api, 88, 2, api.blobs)


def test_deleted_history_is_not_interpreted_as_no_previous_upload():
    api = HistoryAPI()
    api.publication["run_number"] = 3
    with pytest.raises(ValueError, match="Missing promotion history"):
        history.prior_intents(api, api.qualified, 99, 1, api.blobs)


def test_duplicate_run_numbers_are_not_a_complete_history():
    api = HistoryAPI()
    api.pages = lambda *args: [api.publication, api.publication]
    with pytest.raises(ValueError, match="Duplicate promotion run numbers"):
        history.prior_intents(api, api.qualified, 99, 1, api.blobs)


def completed_history(*, bound_timing=False):
    api = HistoryAPI(bound_timing=bound_timing)
    api.publication["conclusion"] = "success"
    api.publisher["conclusion"] = "success"
    api.publisher["steps"][0]["conclusion"] = "success"
    api.qualified["promotion"] = {"run": 88, "attempt": 1, "sha": api.source["sha"],
        "ref": "refs/tags/" + api.qualified["tag"], "publisher_sha": api.publisher_sha}
    expected = {"qualification_run": 77, "qualification_attempt": 1, "source": api.source,
        "packages": api.qualified["manifest"]["packages"]}
    if bound_timing:
        expected["latency_binding"] = api.qualified["latency_binding"]
    api.publisher_log += "CODEX_PROMOTION_COMPLETE " + policy.canonical(expected).decode()
    api.retained = lambda: {"records": [{"event": {"kind": "publication-start", "intent": {"source": api.source,
        "target": "darwin-arm64", "package": api.qualified["manifest"]["packages"]["darwin-arm64"]}}}]}
    if bound_timing:
        import json
        from qualification_fixture import archives
        model = load_tool("release.journal_model")
        files = archives.zip_files(api.bodies[f"{api.prefix}/actions/artifacts/{api.record['id']}/zip"])
        body = json.loads(files["intent.json"])
        api.journal.anchor(api.journal.candidate(model.event_for(body, api.journal.config)))
        api.retained = api.journal.read
    return api


def test_completed_promotion_uses_original_publisher_logs_across_copied_attempts():
    api = completed_history()
    api.publication["run_attempt"] = 3
    api.qualified["promotion"]["attempt"] = 3
    original = api.jobs
    api.jobs = lambda run_id, attempt: ([{**api.validation, "id": 401+attempt}, {**api.publisher, "id": 501+attempt}]
        if run_id == 88 and attempt > 1 else original(run_id, attempt))
    result = history.verify_complete(api, api.qualified, api.blobs, api.retained)
    assert result["publisher_job_id"] == 302
    assert result["prior_intents"] == {"darwin-arm64": True}


@pytest.mark.parametrize("fault", ["failed-run", "failed-job", "missing-completion", "duplicate", "wrong-package"])
def test_public_completion_cannot_borrow_or_fabricate_an_upload(fault):
    api = completed_history()
    if fault == "failed-run":
        api.publication["conclusion"] = "failure"
    elif fault == "failed-job":
        api.publisher["conclusion"] = "failure"
    elif fault == "missing-completion":
        api.publisher_log = api.publisher_log.split("CODEX_PROMOTION_COMPLETE")[0]
    elif fault == "duplicate":
        api.publisher_log *= 2
    else:
        api.qualified["manifest"]["packages"]["win32-x64"]["sha256"] = "e" * 64
    with pytest.raises(ValueError):
        history.verify_complete(api, api.qualified, api.blobs, api.retained)


def test_completed_promotion_preserves_exact_d4_reference_and_retained_intent():
    api = completed_history(bound_timing=True)
    result = history.verify_complete(api, api.qualified, api.blobs, api.retained)
    assert result["completed"]["latency_binding"] == api.qualified["latency_binding"]
    assert result["prior_intents"] == {"darwin-arm64": True}
    assert len(api.journal.read()["records"]) == 2


@pytest.mark.parametrize("fault", ["missing", "changed", "completion"])
def test_completed_promotion_refuses_d4_reference_drift(fault):
    import json
    api = completed_history(bound_timing=True)
    if fault == "missing":
        api.qualified.pop("latency_binding")
    elif fault == "changed":
        api.qualified["latency_binding"] = {**api.qualified["latency_binding"], "commit": "e"*40}
    else:
        prefix = "CODEX_PROMOTION_COMPLETE "
        body = json.loads(history.markers(api.publisher_log, prefix)[0])
        body["latency_binding"]["commit"] = "e"*40
        api.publisher_log = api.publisher_log.split(prefix)[0] + prefix + policy.canonical(body).decode()
    with pytest.raises(ValueError, match="completion"):
        history.verify_complete(api, api.qualified, api.blobs, api.retained)
