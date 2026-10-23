from __future__ import annotations

from pathlib import Path
from typing import Callable

from codex_usage.agent_capture import session_dirs_for_home
from codex_usage.agent_jobs import HeavyIOLane, JobPriority
from codex_usage.agent_operations import OperationRegistry
from codex_usage.agent_paths import ledger_database_path, storage_database_path
from codex_usage.agent_reports import (
    AgentActivityExport,
    RenderedLedgerReport,
    export_agent_activity_csv,
    render_ledger_report,
)
from codex_usage.agent_service import background_agent_status
from codex_usage.agent_settings import AgentSettings
from codex_usage.companion_service import CompanionService
from codex_usage.companion_storage import CompanionStorage
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
    ) -> None:
        self._codex_home = codex_home
        self._ledger_path = ledger_database_path(codex_home)
        self._lane = lane
        self._operations = operations
        self._settings = settings
        self.companion = CompanionService(codex_home, settings,
            storage=CompanionStorage(codex_home, lane, operations))

    def report(
        self,
        *,
        range_name: str,
        project_keys: list[str],
        theme: str,
        start_date: str | None = None,
        end_date: str | None = None,
        speed_granularity: str | None = None,
        speed_window_start: str | None = None,
        speed_window_scope: str | None = None,
        breakdown_action: str | None = None,
        allowance_action: str | None = None,
    ) -> RenderedLedgerReport:
        settings = self._settings()
        return render_ledger_report(
            self._codex_home,
            range_name=range_name,
            start_date=start_date,
            end_date=end_date,
            project_keys=project_keys,
            theme=theme,
            timezone_name=settings.timezone,
            auto_transitions=settings.auto_project_transitions,
            speed_granularity=speed_granularity,
            speed_window_start=speed_window_start,
            speed_window_scope=speed_window_scope,
            breakdown_action=breakdown_action,
            allowance_action=allowance_action,
        )

    def export_agent_activity(
        self,
        *,
        range_name: str,
        start_date: str | None,
        end_date: str | None,
        project_keys: list[str],
    ) -> AgentActivityExport:
        settings = self._settings()
        return export_agent_activity_csv(
            self._codex_home,
            range_name=range_name,
            start_date=start_date,
            end_date=end_date,
            project_keys=project_keys,
            timezone_name=settings.timezone,
            auto_transitions=settings.auto_project_transitions,
        )

    def projects(self) -> list[dict[str, object]]:
        return load_projects(self._ledger_path)

    def allowance_diagnostics(self) -> dict[str, object]:
        from codex_usage.allowance_diagnostics import allowance_diagnostics
        return allowance_diagnostics(self._codex_home)

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
