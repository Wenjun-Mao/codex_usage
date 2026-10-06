"""Observation-bound selected storage actions on the collector's existing lane."""
from datetime import UTC, datetime
from threading import RLock

from codex_usage.agent_capture import session_dirs_for_home
from codex_usage.agent_jobs import JobPriority
from codex_usage.agent_paths import storage_database_path
from codex_usage.companion_contract import CompanionError, SCHEMA_VERSION, check_fields, page_size
from codex_usage.companion_snapshots import SnapshotStore
from codex_usage.storage_analysis import analyze_storage_tree
from codex_usage.storage_context import load_storage_context
from codex_usage.storage_selection import tree_membership

TREE_FIELDS = (
    "root_bytes", "descendant_bytes", "descendant_count", "active_file_count", "archived_file_count",
    "active_bytes", "archived_bytes", "physical_file_count", "total_bytes", "share",
    "has_missing_root", "has_relationship_cycle", "duplicate_file_count", "is_large_root", "is_large_tree",
    "analysis_status", "analyzed_bytes", "analysis_coverage", "compacted_record_count", "compacted_bytes",
    "compacted_share", "largest_compacted_record_bytes", "media_compacted_record_count",
    "embedded_media_occurrence_count", "large_descendant_file_count", "large_descendant_bytes",
    "large_descendant_share", "has_history_amplification", "has_media_amplification", "has_active_root_history_risk",
)
DIAGNOSTICS = {"session_meta_unreadable", "session_meta_limit_exceeded", "session_meta_missing", "task_relationship_cycle"}


def tree_projection(tree, handle, handles):
    return {"id": handle, "label": "Tree " + handle[-6:],
            "project_id": handles.issue("project", tree.project_key),
            **{field: getattr(tree, field) for field in TREE_FIELDS},
            "diagnostics": sorted(DIAGNOSTICS.intersection(tree.diagnostics))}


class CompanionStorage:
    def __init__(self, home, lane, operations):
        self.home, self.lane, self.operations = home, lane, operations
        self.store = SnapshotStore()
        self.selections = {}
        self.jobs = {}
        self._lock = RLock()

    def query(self, payload, handles):
        if payload.get("kind") == "storage" and "cursor" not in payload:
            return self._inventory(payload, handles)
        with self._lock:
            return self._action(payload, handles)

    def _inventory(self, payload, handles):
        check_fields(payload, {"kind", "project_ids", "limit"})
        ids = payload.get("project_ids", [])
        if not isinstance(ids, list) or len(ids) > 100 or not all(isinstance(i, str) for i in ids):
            raise CompanionError()
        keys = [handles.resolve("project", i) for i in ids]
        limit = page_size(payload)
        context = self.lane.submit(
            "companion-storage-inventory", JobPriority.STORAGE_ANALYSIS,
            lambda: load_storage_context(session_dirs=session_dirs_for_home(self.home),
                cache_database_path=storage_database_path(self.home)),
        ).result()
        with self._lock:
            return self._inventory_result(context, ids, keys, limit, handles)

    def _inventory_result(self, context, ids, keys, limit, handles):
        insights = context.insights.filter_projects(keys)
        selected = sorted(insights.task_trees, key=lambda t: (-t.total_bytes, t.root_task_id))
        rows = []
        membership = {}
        for tree in selected:
            handle = handles.issue("tree", tree.root_task_id)
            rows.append(tree_projection(tree, handle, handles))
            membership[handle] = (tree.root_task_id, tree_membership(tree), keys)
        envelope = {"schema_version": SCHEMA_VERSION, "observed_at": datetime.now(UTC).isoformat(),
                    "scope": {"project_ids": ids}, "source": "bounded filesystem metadata",
                    "totals": {key: getattr(insights, key) for key in (
                        "corpus_bytes", "root_bytes", "descendant_bytes", "active_bytes",
                        "archived_bytes", "physical_file_count", "task_tree_count",
                    )},
                    "roots": [{key: getattr(root, key) for key in (
                        "storage_state", "exists", "jsonl_count", "total_bytes",
                    )} for root in insights.roots]}
        token = self.store.put(envelope, {"dimensions": {"tree": rows}})
        self.selections = {key: value for key, value in self.selections.items() if key in self.store.items}
        self.selections[token] = membership
        return self.store.page(token, "storage", "tree", 0, limit)

    def _action(self, payload, handles):
        kind = payload["kind"]
        if kind == "storage":
            check_fields(payload, {"kind", "cursor"})
            return self.store.next_page(payload["cursor"], kind)
        if kind == "storage_start":
            check_fields(payload, {"kind", "snapshot_id", "tree_id"})
            token, handle = payload.get("snapshot_id"), payload.get("tree_id")
            if not isinstance(token, str) or not isinstance(handle, str):
                raise CompanionError()
            self.store.get(token)
            selection = self.selections.get(token, {}).get(handle)
            if selection is None:
                raise CompanionError("selection_expired")
            self.jobs = {key: value for key, value in self.jobs.items()
                         if self.operations.get(key)["state"] not in {"completed", "failed", "cancelled"}
                         or value["expires"] > self.store.clock()}
            if len(self.jobs) >= 32:
                raise CompanionError("too_many_jobs")
            tree_id, membership, keys = selection
            def analyze(progress, cancelled):
                summary = analyze_storage_tree(tree_id,
                    session_dirs=session_dirs_for_home(self.home),
                    cache_database_path=storage_database_path(self.home),
                    progress=progress, cancelled=cancelled, expected_membership=membership,
                    analysis_project_keys=keys)
                return {"counts": {key: getattr(summary, key) for key in (
                    "files_total", "files_analyzed", "files_unchanged", "files_appended",
                    "full_scans", "append_fallbacks", "source_bytes_read",
                )}, "tree": tree_projection(summary.selected_tree, handle, handles)}
            job = self.operations.start(kind="companion-storage-analysis",
                priority=JobPriority.STORAGE_ANALYSIS, operation=analyze)
            self.jobs[job["operation_id"]] = {"snapshot_id": token, "tree_id": handle,
                                              "expires": self.store.clock() + 3600}
            return self._job(job)
        if kind not in {"storage_job", "storage_cancel"}:
            raise CompanionError()
        check_fields(payload, {"kind", "job_id"})
        job_id = payload.get("job_id")
        if not isinstance(job_id, str) or job_id not in self.jobs:
            raise CompanionError("job_unknown")
        job = (self.operations.cancel(job_id) if kind == "storage_cancel" else self.operations.get(job_id))
        return self._job(job) | {"cancellation_requested": kind == "storage_cancel"}

    def _job(self, job):
        progress = job["progress"]
        code = ("selection_changed" if str(job.get("error", "")).startswith("StorageSelectionChanged:")
                else "analysis_failed" if job["state"] == "failed" else None)
        return {"schema_version": SCHEMA_VERSION, "data": {
            "job_id": job["operation_id"], "state": job["state"], "error_code": code,
            "created_at": job["created_at"], "completed_at": job["completed_at"],
            **{key: self.jobs.get(job["operation_id"], {}).get(key) for key in ("snapshot_id", "tree_id")},
            "progress": {key: progress.get(key) for key in (
                "completed_files", "total_files", "completed_bytes", "total_bytes",
            )},
            "result": job["result"] if job["state"] == "completed" else None,
        }}
