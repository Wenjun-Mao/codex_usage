from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable, cast

from codex_usage.agent_capture import session_dirs_for_home
from codex_usage.agent_jobs import HeavyIOLane, JobPriority
from codex_usage.agent_operations import OperationRegistry
from codex_usage.agent_paths import ledger_database_path, storage_database_path
from codex_usage.agent_reports import RenderedLedgerReport, render_ledger_report
from codex_usage.agent_service import background_agent_status
from codex_usage.agent_settings import AgentSettings
from codex_usage.agent_transfer import (
    TransferOperation,
    execute_task_transfer,
    task_transfer_inventory,
)
from codex_usage.ledger_migration import (
    discover_legacy_caches,
    migrate_legacy_caches,
    plan_legacy_migration,
)
from codex_usage.ledger_queries import (
    load_ledger_transitions,
    load_projects,
    load_tasks,
)
from codex_usage.storage_analysis import analyze_storage_tree
from codex_usage.storage_cli_reporting import storage_snapshot_payload
from codex_usage.storage_context import load_storage_context


class AgentFeatures:
    """Product operations that share the agent's single heavy-I/O lane."""

    def __init__(
        self,
        codex_home: Path,
        lane: HeavyIOLane,
        operations: OperationRegistry,
        *,
        settings: Callable[[], AgentSettings],
        on_import: Callable[[], None],
    ) -> None:
        self._codex_home = codex_home
        self._ledger_path = ledger_database_path(codex_home)
        self._lane = lane
        self._operations = operations
        self._settings = settings
        self._on_import = on_import

    def report(
        self,
        *,
        range_name: str,
        project_keys: list[str],
        theme: str,
    ) -> RenderedLedgerReport:
        settings = self._settings()
        return render_ledger_report(
            self._codex_home,
            range_name=range_name,
            project_keys=project_keys,
            theme=theme,
            timezone_name=settings.timezone,
            auto_transitions=settings.auto_project_transitions,
        )

    def projects(self) -> list[dict[str, object]]:
        return load_projects(self._ledger_path)

    def tasks(self, project_key: str | None = None) -> list[dict[str, object]]:
        return load_tasks(self._ledger_path, project_key=project_key)

    def transitions(self) -> list[dict[str, object]]:
        return [item.to_dict() for item in load_ledger_transitions(self._ledger_path)]

    def storage_snapshot(self, project_keys: list[str]) -> dict[str, object]:
        context = load_storage_context(
            session_dirs=session_dirs_for_home(self._codex_home),
            cache_database_path=storage_database_path(self._codex_home),
        )
        return storage_snapshot_payload(context.insights.filter_projects(project_keys))

    def start_storage_analysis(self, tree_id: str) -> dict[str, object]:
        return self._operations.start(
            kind="storage-analysis",
            priority=JobPriority.STORAGE_ANALYSIS,
            operation=lambda progress, cancelled: analyze_storage_tree(
                tree_id,
                session_dirs=session_dirs_for_home(self._codex_home),
                cache_database_path=storage_database_path(self._codex_home),
                progress=progress,
                cancelled=cancelled,
            ).to_dict(),
        )

    def operation_status(self, operation_id: str) -> dict[str, object]:
        return self._operations.get(operation_id)

    def cancel_operation(self, operation_id: str) -> dict[str, object]:
        return self._operations.cancel(operation_id)

    def transfer_inventory(self, payload: dict[str, object]) -> dict[str, object]:
        sync_dir = _required_directory(payload, "sync_dir")
        roots = _directory_list(payload.get("candidate_roots", []))
        future = self._lane.submit(
            _payload_job_key("task-transfer-inventory", payload),
            JobPriority.TASK_TRANSFER,
            lambda: task_transfer_inventory(
                self._codex_home,
                sync_dir,
                candidate_roots=roots,
            ),
        )
        return future.result()

    def execute_transfer(self, payload: dict[str, object]) -> dict[str, object]:
        operation = str(payload.get("operation", "")).strip()
        if operation not in {"import", "export", "status"}:
            raise ValueError("operation must be import, export, or status")
        future = self._lane.submit(
            _payload_job_key("task-transfer", payload),
            JobPriority.TASK_TRANSFER,
            lambda: execute_task_transfer(
                self._codex_home,
                cast(TransferOperation, operation),
                payload,
            ),
        )
        result = future.result()
        if operation == "import":
            self._on_import()
        return result

    def service_status(self) -> dict[str, object]:
        return background_agent_status().to_dict()

    def migration_plan(self) -> dict[str, object]:
        candidates = discover_legacy_caches(self._codex_home)
        return plan_legacy_migration(self._ledger_path, candidates).to_dict()

    def migrate_legacy(self, precedence: dict[str, str]) -> dict[str, object]:
        candidates = discover_legacy_caches(self._codex_home)
        future = self._lane.submit(
            "legacy-migration",
            JobPriority.BASELINE_REBUILD,
            lambda: migrate_legacy_caches(
                self._ledger_path,
                candidates,
                precedence=precedence,
            ),
        )
        return future.result()


def _required_directory(payload: dict[str, object], key: str) -> Path:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"{key} is not an available folder: {path}")
    return path


def _directory_list(value: object) -> list[Path]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("candidate_roots must be an array of strings")
    return [Path(item).expanduser().resolve() for item in value]


def _payload_job_key(prefix: str, payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"{prefix}:{hashlib.sha256(encoded).hexdigest()}"
