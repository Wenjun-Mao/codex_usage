from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image
from playwright.sync_api import Page, sync_playwright

from codex_usage.aggregation import aggregate_records, summarize_records
from codex_usage.marketplace_screenshot_validation import (
    _clear_tooltip_interaction,
    _validate_browser_layout,
)
from codex_usage.models import (
    ROOT_USAGE_ROLE,
    SUBAGENT_USAGE_ROLE,
    TokenUsage,
    UsageRecord,
    UsageRole,
)
from codex_usage.report_breakdown import build_report_breakdown
from codex_usage.reporting import render_html_report
from codex_usage.storage_insights import TaskStorageInsights, TaskStorageTree

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCREENSHOT_PATH = REPOSITORY_ROOT / "docs" / "marketplace" / "dashboard-synthetic.png"
STORAGE_SCREENSHOT_PATH = (
    REPOSITORY_ROOT / "docs" / "marketplace" / "task-storage-synthetic.png"
)
VIEWPORT = {"width": 1440, "height": 900}
NARROW_VIEWPORT = {"width": 720, "height": 900}
FIXED_GENERATED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
SYNTHETIC_SESSIONS_DIR = Path("/synthetic/codex/sessions")

_SCREENSHOT_CSS = """
  [data-report-section="daily-cost"],
  [data-report-section="hourly-heatmap"],
  [data-report-section="project-details"],
  [data-report-section="model-details"],
  .summary-line { display: none !important; }
  main {
    width: 100% !important;
    max-width: none !important;
    margin: 0 !important;
    padding: 24px !important;
  }
  .dashboard-grid { gap: 16px !important; margin-top: 16px !important; }
  .task-storage-section { padding-bottom: 14px !important; }
  [data-report-section="task-storage-details"] tbody tr:nth-child(n+3) {
    display: none !important;
  }
  .screenshot-storage-action {
    display: inline-flex;
    align-items: center;
    min-height: 24px;
    padding: 2px 8px;
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--accent);
    font-size: 12px;
    white-space: nowrap;
  }
"""

_SYNTHETIC_RECORDS: tuple[tuple[str, str, UsageRole, str, int], ...] = (
    ("codex-usage", "Codex Usage", ROOT_USAGE_ROLE, "gpt-5.6-sol", 400_000),
    ("codex-usage", "Codex Usage", ROOT_USAGE_ROLE, "gpt-5.6-terra", 250_000),
    ("codex-usage", "Codex Usage", ROOT_USAGE_ROLE, "gpt-5.5", 90_000),
    ("codex-usage", "Codex Usage", ROOT_USAGE_ROLE, "gpt-5.3-codex", 50_000),
    ("codex-usage", "Codex Usage", SUBAGENT_USAGE_ROLE, "gpt-5.6-luna", 220_000),
    ("codex-usage", "Codex Usage", SUBAGENT_USAGE_ROLE, "gpt-5.4-mini", 80_000),
    ("codex-usage", "Codex Usage", SUBAGENT_USAGE_ROLE, "synthetic-unpriced-model", 10_000),
    ("translation-tools", "Translation Tools", ROOT_USAGE_ROLE, "gpt-5.6-sol", 350_000),
    ("translation-tools", "Translation Tools", ROOT_USAGE_ROLE, "gpt-5.6-luna", 190_000),
    ("translation-tools", "Translation Tools", ROOT_USAGE_ROLE, "gpt-5.4", 100_000),
    ("translation-tools", "Translation Tools", SUBAGENT_USAGE_ROLE, "gpt-5.6-terra", 300_000),
    ("translation-tools", "Translation Tools", SUBAGENT_USAGE_ROLE, "gpt-5.5", 70_000),
    ("translation-tools", "Translation Tools", SUBAGENT_USAGE_ROLE, "gpt-5.4-mini", 60_000),
    ("translation-tools", "Translation Tools", SUBAGENT_USAGE_ROLE, "gpt-5.3-codex", 45_000),
    ("translation-tools", "Translation Tools", SUBAGENT_USAGE_ROLE, "synthetic-unpriced-model", 8_000),
)


def build_synthetic_records() -> list[UsageRecord]:
    records = []
    for index, (project, label, role, model, total_tokens) in enumerate(_SYNTHETIC_RECORDS):
        timestamp = FIXED_GENERATED_AT + timedelta(minutes=index)
        records.append(
            UsageRecord(
                timestamp=timestamp,
                usage=_usage(total_tokens),
                session_id=f"synthetic-{index:02d}",
                file_path=SYNTHETIC_SESSIONS_DIR / f"session-{index:02d}.jsonl",
                usage_role=role,
                model=model,
                project_key=f"https://github.com/example/{project}",
                project_label=label,
            )
        )
    return records


def build_synthetic_storage_snapshot() -> TaskStorageInsights:
    gib = 1024**3
    mib = 1024**2
    trees = (
        _synthetic_storage_tree(
            task_id="storage-codex-main",
            title="Codex Usage main",
            project="Codex Usage",
            root_bytes=5 * gib + 410 * mib,
            descendant_bytes=38 * gib + 630 * mib,
            descendant_count=112,
            active_files=113,
            analysis_status="complete",
            compacted_bytes=35 * gib + 120 * mib,
            embedded_media_occurrence_count=48,
            active_root_compacted_bytes=4 * gib + 900 * mib,
            has_history_amplification=True,
            has_media_amplification=True,
            has_active_root_history_risk=True,
        ),
        _synthetic_storage_tree(
            task_id="storage-transfer",
            title="Cross-platform Task Transfer",
            project="Codex Usage",
            root_bytes=780 * mib,
            descendant_bytes=12 * gib + 240 * mib,
            descendant_count=37,
            active_files=36,
            archived_files=2,
            analysis_status="not_analyzed",
        ),
        _synthetic_storage_tree(
            task_id="storage-translation",
            title="Batch translation pipeline",
            project="Translation Tools",
            root_bytes=1 * gib + 205 * mib,
            descendant_bytes=6 * gib + 820 * mib,
            descendant_count=19,
            active_files=20,
            analysis_status="complete",
            compacted_bytes=820 * mib,
        ),
        _synthetic_storage_tree(
            task_id="storage-glossary",
            title="Glossary cleanup",
            project="Translation Tools",
            root_bytes=320 * mib,
            descendant_bytes=680 * mib,
            descendant_count=4,
            active_files=5,
            analysis_status="partial",
            compacted_bytes=210 * mib,
        ),
    )
    corpus_bytes = sum(tree.total_bytes for tree in trees)
    trees = tuple(
        replace(tree, share=tree.total_bytes / corpus_bytes) for tree in trees
    )
    return TaskStorageInsights(
        corpus_bytes=corpus_bytes,
        root_bytes=sum(tree.root_bytes for tree in trees),
        descendant_bytes=sum(tree.descendant_bytes for tree in trees),
        active_bytes=sum(tree.active_bytes for tree in trees),
        archived_bytes=sum(tree.archived_bytes for tree in trees),
        physical_file_count=sum(tree.physical_file_count for tree in trees),
        task_tree_count=len(trees),
        task_trees=trees,
    )


def render_synthetic_report(destination: Path) -> Path:
    records = build_synthetic_records()
    breakdown = build_report_breakdown(records)
    return render_html_report(
        output_path=destination,
        generated_at=FIXED_GENERATED_AT,
        range_name="30d",
        total=summarize_records(records),
        daily_rows=aggregate_records(records, "day", UTC),
        hourly_rows=aggregate_records(records, "hour", UTC),
        breakdown=breakdown,
        storage_snapshot=build_synthetic_storage_snapshot(),
        sessions_dirs=[SYNTHETIC_SESSIONS_DIR],
        files_scanned=len({record.file_path for record in records}),
        theme="night",
    )


def capture_marketplace_screenshot(
    report_path: Path, output_path: Path, *, view: str
) -> None:
    if view not in {"usage", "task-storage"}:
        raise ValueError(f"unknown screenshot view: {view}")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport=VIEWPORT)
            page.goto(report_path.resolve().as_uri(), wait_until="load")
            _inject_backup_actions(page)
            page.add_style_tag(content=_SCREENSHOT_CSS)
            page.get_by_role(
                "link", name="Usage" if view == "usage" else "Task Storage", exact=True
            ).click()
            page.set_viewport_size(VIEWPORT)
            _wait_for_landmarks(page, view)
            _validate_browser_layout(page, VIEWPORT["width"], view)
            page.set_viewport_size(NARROW_VIEWPORT)
            _validate_browser_layout(page, NARROW_VIEWPORT["width"], view)
            page.set_viewport_size(VIEWPORT)
            _clear_tooltip_interaction(page)
            page.screenshot(path=str(output_path), full_page=False)
        finally:
            browser.close()


def validate_screenshot(path: Path) -> None:
    with Image.open(path) as image:
        if image.size != (1440, 900):
            raise RuntimeError(f"unexpected screenshot dimensions for {path}: {image.size}")
        rgb = image.convert("RGB")
        extrema = rgb.getextrema()
        if not all(high > low for low, high in extrema):
            raise RuntimeError(f"screenshot has a flat color channel: {path}")
        colors = rgb.resize((180, 112)).getcolors(maxcolors=180 * 112)
        if colors is None or len(colors) < 32:
            raise RuntimeError(f"screenshot lacks meaningful visual variation: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the Marketplace dashboard screenshot.")
    parser.add_argument("--check", action="store_true", help="Validate a temporary screenshot.")
    args = parser.parse_args(argv)
    if args.check:
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            _render_capture_and_validate(
                temporary_path / "dashboard.html",
                temporary_path / "dashboard.png",
                temporary_path / "task-storage.png",
            )
        return 0

    with TemporaryDirectory() as temporary_directory:
        report_path = Path(temporary_directory) / "dashboard.html"
        _render_capture_and_validate(
            report_path, SCREENSHOT_PATH, STORAGE_SCREENSHOT_PATH
        )
    return 0


def _usage(total_tokens: int) -> TokenUsage:
    input_tokens = total_tokens * 3 // 4
    cached_input_tokens = input_tokens // 3
    cache_write_input_tokens = input_tokens // 12
    return TokenUsage(
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_write_input_tokens=cache_write_input_tokens,
        output_tokens=total_tokens - input_tokens,
        reasoning_output_tokens=total_tokens // 20,
        total_tokens=total_tokens,
    )


def _synthetic_storage_tree(
    *,
    task_id: str,
    title: str,
    project: str,
    root_bytes: int,
    descendant_bytes: int,
    descendant_count: int,
    active_files: int,
    archived_files: int = 0,
    analysis_status: str = "not_analyzed",
    compacted_bytes: int = 0,
    embedded_media_occurrence_count: int = 0,
    active_root_compacted_bytes: int = 0,
    has_history_amplification: bool = False,
    has_media_amplification: bool = False,
    has_active_root_history_risk: bool = False,
) -> TaskStorageTree:
    total_bytes = root_bytes + descendant_bytes
    archived_bytes = total_bytes // 12 if archived_files else 0
    return TaskStorageTree(
        root_task_id=task_id,
        title=title,
        project_key=project.casefold().replace(" ", "-"),
        project_label=project,
        project_aliases=(),
        root_bytes=root_bytes,
        descendant_bytes=descendant_bytes,
        descendant_count=descendant_count,
        active_file_count=active_files,
        archived_file_count=archived_files,
        active_bytes=total_bytes - archived_bytes,
        archived_bytes=archived_bytes,
        physical_file_count=active_files + archived_files,
        total_bytes=total_bytes,
        share=0.0,
        has_missing_root=False,
        has_relationship_cycle=False,
        duplicate_file_count=0,
        metadata_diagnostics=(),
        is_large_root=root_bytes >= 1024**3,
        is_large_tree=total_bytes >= 10 * 1024**3,
        analysis_status=analysis_status,
        analyzed_bytes=total_bytes if analysis_status == "complete" else compacted_bytes,
        analysis_coverage=(
            1.0
            if analysis_status == "complete"
            else compacted_bytes / total_bytes if total_bytes else 0.0
        ),
        compacted_record_count=14 if compacted_bytes else 0,
        compacted_bytes=compacted_bytes,
        compacted_share=compacted_bytes / total_bytes if total_bytes else 0.0,
        largest_compacted_record_bytes=compacted_bytes // 3,
        media_compacted_record_count=6 if embedded_media_occurrence_count else 0,
        embedded_media_occurrence_count=embedded_media_occurrence_count,
        active_root_compacted_bytes=active_root_compacted_bytes,
        has_history_amplification=has_history_amplification,
        has_media_amplification=has_media_amplification,
        has_active_root_history_risk=has_active_root_history_risk,
    )


def _render_capture_and_validate(
    report_path: Path, usage_screenshot_path: Path, storage_screenshot_path: Path
) -> None:
    render_synthetic_report(report_path)
    capture_marketplace_screenshot(
        report_path, usage_screenshot_path, view="usage"
    )
    capture_marketplace_screenshot(
        report_path, storage_screenshot_path, view="task-storage"
    )
    validate_screenshot(usage_screenshot_path)
    validate_screenshot(storage_screenshot_path)


def _wait_for_landmarks(page: Page, view: str) -> None:
    page.get_by_role("navigation", name="Report views").wait_for()
    if view == "task-storage":
        page.get_by_role("heading", name="Task Storage", exact=True).wait_for()
        page.get_by_text("Root task JSONL", exact=True).wait_for()
        page.get_by_text("Structured subagents", exact=True).wait_for()
        page.get_by_text("Back Up", exact=True).first.wait_for()
        page.get_by_text("Analyze", exact=True).first.wait_for()
        page.get_by_text("Prepare Rollover", exact=True).first.wait_for()
        return
    page.get_by_role("heading", name="Project Breakdown", exact=True).wait_for()
    page.get_by_text("Root tasks", exact=True).first.wait_for()
    page.get_by_text("Subagents", exact=True).first.wait_for()
    page.get_by_role("heading", name="Model Mix", exact=True).wait_for()
    page.get_by_text("Other", exact=True).last.wait_for(state="attached")
    page.locator(".model-legend-item").filter(has_text="Other").last.wait_for()


def _inject_backup_actions(page: Page) -> None:
    page.locator('[data-report-section="task-storage-details"]').evaluate(
        """
        section => {
          const header = section.querySelector('thead tr');
          if (!header) throw new Error('Task Storage details header is missing');
          const heading = document.createElement('th');
          heading.textContent = 'Actions';
          header.appendChild(heading);
          for (const row of section.querySelectorAll('tbody tr[data-storage-tree-id]')) {
            const cell = document.createElement('td');
            cell.className = 'storage-actions';
            const labels = ['Back Up'];
            if (row.dataset.storageAnalysisStatus !== 'complete') labels.push('Analyze');
            if (row.dataset.storageCanRollover === 'true' && row.dataset.storageRecoveryReady === 'true') {
              labels.push('Prepare Rollover');
            }
            labels.forEach((label, index) => {
              if (index) cell.append(' · ');
              const action = document.createElement('span');
              action.className = 'screenshot-storage-action';
              action.textContent = label;
              cell.appendChild(action);
            });
            row.appendChild(cell);
          }
        }
        """
    )


if __name__ == "__main__":
    raise SystemExit(main())
