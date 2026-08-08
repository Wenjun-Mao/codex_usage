from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from codex_usage.aggregation import UsageSummary
from codex_usage.models import TokenUsage
from codex_usage.pricing import CostBreakdown, CreditBreakdown
from codex_usage.report_breakdown import ReportBreakdown
from codex_usage.reporting import render_html_report
from codex_usage.storage_insights import TaskStorageInsights, TaskStorageTree


def test_task_storage_section_is_full_width_and_discloses_side_chats(tmp_path: Path) -> None:
    output = tmp_path / "storage.html"
    long_title = "A very long task title that is still readable in the details table " * 2
    snapshot = TaskStorageInsights(
        task_trees=(
            TaskStorageTree(
                root_task_id="root-small-123456",
                title="Small task",
                project_key="repo",
                project_label="Repo",
                project_aliases=(),
                root_bytes=0,
                descendant_bytes=30,
                descendant_count=1,
                total_bytes=30,
                share=0.0001,
                active_file_count=2,
                archived_file_count=0,
                active_bytes=30,
                archived_bytes=0,
                physical_file_count=2,
                has_missing_root=False,
                has_relationship_cycle=True,
                duplicate_file_count=0,
                metadata_diagnostics=(),
                is_large_root=False,
                is_large_tree=False,
            ),
            TaskStorageTree(
                root_task_id="root-large-123456",
                title=long_title,
                project_key="repo",
                project_label="Repo",
                project_aliases=("repo-alias",),
                root_bytes=2 * 1024**3,
                descendant_bytes=11 * 1024**3,
                descendant_count=32,
                total_bytes=13 * 1024**3,
                share=0.9999,
                active_file_count=30,
                archived_file_count=3,
                active_bytes=10 * 1024**3,
                archived_bytes=3 * 1024**3,
                physical_file_count=33,
                has_missing_root=False,
                has_relationship_cycle=False,
                duplicate_file_count=2,
                is_large_root=True,
                is_large_tree=True,
                metadata_diagnostics=("duplicate physical file retained",),
            ),
        ),
        corpus_bytes=13 * 1024**3 + 30,
        root_bytes=2 * 1024**3,
        descendant_bytes=11 * 1024**3 + 30,
        active_bytes=10 * 1024**3 + 30,
        archived_bytes=3 * 1024**3,
        physical_file_count=35,
        task_tree_count=2,
        diagnostics=("physical inventory contains a duplicate task id",),
    )

    _render(output, snapshot)
    html = output.read_text(encoding="utf-8")

    assert 'data-report-section="task-storage"' in html
    assert html.index('id="report-usage"') < html.index('id="report-task-storage"')
    assert html.index('class="dashboard-grid"') < html.index('id="report-task-storage"')
    assert html.index('id="report-task-storage"') < html.index(
        'data-report-section="task-storage"'
    )
    assert "Current local storage. Date range does not affect storage; selected project filters do." in html
    assert "Root task token usage includes side chats stored in the parent task." in html
    assert 'data-report-section="project-breakdown"' in html
    assert html.count("Root task token usage includes side chats stored in the parent task.") == 2
    assert 'role="group" aria-label="Largest task storage trees"' in html
    assert "storage-has-boundary" in html
    assert "storage-descendant-only" in html
    assert "Root task JSONL" in html
    assert "Structured subagents" in html
    assert "Task Storage Details" in html
    assert 'data-storage-tree-id="root-large-123456"' in html
    assert "Root</th>" in html
    assert "Descendants</th>" in html
    assert "High inherited root" in html
    assert "Large task tree" in html
    assert "2 duplicate files" in html
    assert "Relationship cycle" in html
    assert "Snapshot diagnostics: physical inventory contains a duplicate task id" in html
    assert "13.00 GiB" in html
    assert html.index(long_title) < html.index("Small task")
    assert "storage-chart {" in html
    assert "min-width: 560px;" in html
    assert "overflow-wrap: anywhere" in html
    assert "<script" not in html
    assert " src=" not in html
    assert 'href="#report-view-usage"' in html
    assert 'href="#report-view-task-storage"' in html
    assert 'href="http://' not in html and 'href="https://' not in html


def test_task_storage_empty_state_does_not_replace_usage_empty_state(tmp_path: Path) -> None:
    output = tmp_path / "empty-storage.html"
    _render(
        output,
        TaskStorageInsights(0, 0, 0, 0, 0, 0, 0, ()),
        total_tokens=25,
    )

    html = output.read_text(encoding="utf-8")

    assert "No task storage was found for the selected projects." in html
    assert "No Codex usage was found for this report range." not in html
    assert "No daily usage found for this range." in html


def _render(
    output: Path, snapshot: TaskStorageInsights, *, total_tokens: int = 0
) -> None:
    total = UsageSummary(
        usage=TokenUsage(input_tokens=total_tokens, total_tokens=total_tokens),
        cost=CostBreakdown(),
        credits=CreditBreakdown(),
        record_count=0,
    )
    render_html_report(
        output_path=output,
        generated_at=datetime(2026, 8, 7, tzinfo=UTC),
        range_name="today",
        total=total,
        daily_rows=[],
        hourly_rows=[],
        breakdown=ReportBreakdown((), (), (), ()),
        sessions_dirs=[Path("sessions")],
        files_scanned=0,
        project_keys=["repo"],
        storage_snapshot=snapshot,
    )
