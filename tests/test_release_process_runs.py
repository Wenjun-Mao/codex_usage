"""Dispatch response loss never becomes permission to submit another workflow."""
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from release_tooling_support import load_tool

runs = load_tool("release.process_runs")
policy = load_tool("release.policy")
Pending = load_tool("release.process_state").Pending
CANDIDATE = {"repository": policy.REPOSITORY, "sha": "a" * 40, "version": "2.12.6", "contract": "b" * 64}


def operation():
    return {"workflow": policy.WORKFLOW, "ref": "main", "fields": {},
        "request_id": str(uuid4()), "created_at": "2026-10-17T20:00:00+00:00"}


def row(op):
    return {"id": 77, "repository": {"id": 123, "full_name": policy.REPOSITORY},
        "head_repository": {"id": 123}, "head_sha": CANDIDATE["sha"], "head_branch": op["ref"],
        "path": op["workflow"], "event": "workflow_dispatch", "run_attempt": 1,
        "status": "completed", "conclusion": "success",
        "display_title": f"Qualify Codex Usage VSIX ref=main probe=false request={op['request_id']}"}


class API:
    prefix = "repos/" + policy.REPOSITORY

    def __init__(self, rows):
        self.rows = rows

    def raw(self, endpoint):
        if "/actions/runs?" in endpoint:
            return json.dumps({"total_count": len(self.rows), "workflow_runs": self.rows})
        return json.dumps(self.rows[0])

    def pages(self, endpoint, field):
        return self.rows


@pytest.mark.parametrize("value", ["bad", "",
    pytest.param("01234567-89AB-4CDE-8FAB-0123456789AB", id="uppercase-uuid"),
    "0" * 32, None, True])
def test_correlation_rejects_noncanonical_values(value):
    with pytest.raises((ValueError, AttributeError, TypeError)):
        runs.request_id(value)
    assert runs.request_id("", optional=True) == ""


def test_lost_dispatch_reply_is_durable_before_call_and_not_redelivered():
    writes, calls = [], []
    progress = SimpleNamespace(data={"operations": {}}, candidate=CANDIDATE)
    progress.save = lambda: writes.append(json.loads(json.dumps(progress.data)))

    def lost(args, **kwargs):
        assert len(writes) == 1 and "qualification" in writes[0]["operations"]
        calls.append(args)
        raise TimeoutError()

    with pytest.raises(Pending):
        runs.dispatch(progress, API([]), "qualification", workflow=policy.WORKFLOW, ref="main", allow=True, run_command=lost)
    result = runs.dispatch(progress, API([]), "qualification", workflow=policy.WORKFLOW, ref="main", allow=True, run_command=lost)
    assert result == writes[0]["operations"]["qualification"] and len(calls) == 1


@pytest.mark.parametrize("field,value", [("head_sha", "c" * 40), ("head_branch", "other"),
    ("event", "push"), ("run_attempt", 2), ("run_attempt", True), ("path", "other"),
    ("display_title", "not the correlated workflow"), ("head_repository", {"id": 999})])
def test_correlated_foreign_execution_is_never_adopted(field, value):
    op = operation()
    run = {**row(op), field: value}
    if field == "display_title":
        assert runs.discover(API([run]), op, CANDIDATE) is None
        with pytest.raises(ValueError):
            runs.validate_run(run, op, CANDIDATE)
        return
    with pytest.raises(ValueError):
        runs.discover(API([run]), op, CANDIDATE)


def test_duplicate_uuid_matches_are_not_latest_run_selection():
    op = operation()
    with pytest.raises(ValueError, match="Multiple"):
        runs.discover(API([row(op), {**row(op), "id": 88}]), op, CANDIDATE)


def test_missing_dispatch_stays_pending_at_finite_deadline():
    op = operation()
    clock = iter([0, 0, 1, 2])
    with pytest.raises(Pending):
        runs.observe(API([]), op, CANDIDATE, seconds=1, clock=lambda: next(clock), wait=lambda _: None)
    assert "run" not in op


def test_observer_records_identity_and_rejects_failed_workflow():
    op = operation()
    run = row(op)
    assert runs.observe(API([run]), op, CANDIDATE)["id"] == 77 and op["run"] == 77
    run["conclusion"] = "failure"
    with pytest.raises(ValueError, match="ended failure"):
        runs.observe(API([run]), op, CANDIDATE)


def test_read_only_resume_cannot_dispatch_or_accept_changed_fields():
    progress = SimpleNamespace(data={"operations": {}}, candidate=CANDIDATE, save=lambda: None)
    with pytest.raises(Pending):
        runs.dispatch(progress, API([]), "qualification", workflow=policy.WORKFLOW, ref="main")
    progress.data["operations"]["qualification"] = operation()
    with pytest.raises(ValueError, match="differs"):
        runs.dispatch(progress, API([]), "qualification", workflow=policy.WORKFLOW, ref="other", allow=True)


def test_deleted_local_publication_hint_cannot_duplicate_known_remote_dispatch():
    progress = SimpleNamespace(data={"operations": {}}, candidate=CANDIDATE, save=lambda: None)
    prior = {"path": policy.PROMOTION_WORKFLOW, "display_title": "Promote qualified run=77 attempt=1 dry-run=false request=old"}
    with pytest.raises(ValueError, match="already exists"):
        runs.dispatch(progress, API([prior]), "promotion", workflow=policy.PROMOTION_WORKFLOW,
            ref="v2.12.6", fields={"dry_run": "false"}, allow=True,
            run_command=lambda *a, **k: pytest.fail("must not dispatch again"))
