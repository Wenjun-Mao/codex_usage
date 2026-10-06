from concurrent.futures import ThreadPoolExecutor
import json
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace

import pytest

from codex_usage.agent_jobs import HeavyIOLane, JobPriority
from codex_usage.agent_operations import OperationRegistry
from codex_usage.companion_contract import CompanionError
from codex_usage.companion_service import CompanionService
from codex_usage.companion_storage import CompanionStorage


@pytest.fixture
def storage(tmp_path):
    home = tmp_path / "codex"
    sessions = home / "sessions"
    sessions.mkdir(parents=True)
    for task, project, padding in (("SECRET_ROOT", "alpha", 500), ("SECRET_OTHER", "beta", 5000)):
        rows = [{"type": "session_meta", "payload": {"id": task, "cwd": f"/SECRET_HOME/{project}", "title": "SECRET_TITLE"}},
                {"type": "compacted", "payload": {"message": "x" * padding}}]
        (sessions / f"{task}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    lane = HeavyIOLane()
    ops = OperationRegistry(lane)
    service = CompanionService(home, lambda: SimpleNamespace(timezone="UTC", auto_project_transitions=True),
                               storage=CompanionStorage(home, lane, ops))
    yield service, lane, ops
    ops.cancel_all()
    lane.close()


def terminal(service, job_id):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        result = service.query({"kind": "storage_job", "job_id": job_id})
        if result["data"]["state"] in {"completed", "failed", "cancelled"}:
            return result
        sleep(0.01)
    pytest.fail("storage job did not settle")


def test_storage_projection_selected_scope_frozen_result_and_foreign_job(storage):
    service, _, ops = storage
    full = service.query({"kind": "storage"})
    tree = full["data"]["rows"][-1]
    selected = service.query({"kind": "storage", "project_ids": [tree["project_id"]]})
    assert selected["data"]["rows"][0]["share"] == 1
    started = service.query({"kind": "storage_start", "snapshot_id": selected["snapshot_id"], "tree_id": tree["id"]})
    finished = terminal(service, started["data"]["job_id"])
    assert finished["data"]["state"] == "completed"
    result = finished["data"]["result"]
    assert result["counts"]["files_total"] == 1
    assert result["tree"]["share"] == 1
    # A later whole-inventory refresh does not reconstruct the completed result.
    (service.home / "sessions" / "SECRET_ROOT.jsonl").unlink()
    service.query({"kind": "storage"})
    assert service.query({"kind": "storage_job", "job_id": started["data"]["job_id"]}) == finished
    encoded = json.dumps([full, selected, started, finished])
    assert "SECRET" not in encoded and str(service.home) not in encoded and '"path"' not in encoded
    foreign = ops.start(kind="foreign", priority=JobPriority.STORAGE_ANALYSIS, operation=lambda p, c: {})
    with pytest.raises(CompanionError, match="job_unknown"):
        service.query({"kind": "storage_cancel", "job_id": foreign["operation_id"]})


def test_membership_change_rejects_before_content_scan(storage, monkeypatch):
    service, _, _ = storage
    snapshot = service.query({"kind": "storage"})
    tree = snapshot["data"]["rows"][-1]
    child = service.home / "sessions" / "child.jsonl"
    child.write_text(json.dumps({"type": "session_meta", "payload": {
        "id": "child", "cwd": "/SECRET_HOME/alpha", "source": {"subagent": {"thread_spawn": {"parent_thread_id": "SECRET_ROOT"}}},
    }}) + "\n")
    def fail(*a, **kw):
        pytest.fail("changed membership scanned content")
    monkeypatch.setattr("codex_usage.storage_analysis._run_analysis", fail)
    job = service.query({"kind": "storage_start", "snapshot_id": snapshot["snapshot_id"], "tree_id": tree["id"]})
    completed = terminal(service, job["data"]["job_id"])
    assert completed["data"]["state"] == "failed"
    assert completed["data"]["error_code"] == "selection_changed"


def test_waiting_inventory_does_not_block_cancellation_or_polling(storage):
    service, lane, ops = storage
    entered, release = Event(), Event()
    def running(progress, cancelled):
        entered.set()
        release.wait(5)
        return {}
    job = ops.start(kind="companion-storage-analysis", priority=JobPriority.STORAGE_ANALYSIS, operation=running)
    service.storage.jobs[job["operation_id"]] = {"snapshot_id": "test", "tree_id": "test", "expires": 1000000000}
    assert entered.wait(1)
    with ThreadPoolExecutor(max_workers=3) as pool:
        inventory = pool.submit(service.query, {"kind": "storage"})
        deadline = monotonic() + 1
        while "companion-storage-inventory" not in lane._futures and monotonic() < deadline:
            sleep(0.01)
        try:
            poll = pool.submit(service.query, {"kind": "storage_job", "job_id": job["operation_id"]})
            assert poll.result(timeout=1)["data"]["state"] == "running"
            cancel = pool.submit(service.query, {"kind": "storage_cancel", "job_id": job["operation_id"]})
            assert cancel.result(timeout=1)["cancellation_requested"] is True
            assert not inventory.done()
        finally:
            release.set()
        inventory.result(timeout=2)
    assert terminal(service, job["operation_id"])["data"]["state"] == "cancelled"
