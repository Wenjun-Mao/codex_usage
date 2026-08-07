from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image
from playwright.sync_api import Locator, Page, sync_playwright

from codex_usage.aggregation import aggregate_records, summarize_records
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
VIEWPORT = {"width": 1440, "height": 900}
NARROW_VIEWPORT = {"width": 720, "height": 900}
FIXED_GENERATED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
SYNTHETIC_SESSIONS_DIR = Path("/synthetic/codex/sessions")

_SCREENSHOT_CSS = """
  [data-report-section="daily-cost"],
  [data-report-section="hourly-heatmap"],
  [data-report-section="project-details"],
  [data-report-section="model-details"],
  [data-report-section="task-storage-details"],
  .summary-line { display: none !important; }
  main {
    width: 100% !important;
    max-width: none !important;
    margin: 0 !important;
    padding: 24px !important;
  }
  .dashboard-grid { gap: 16px !important; margin-top: 16px !important; }
  .task-storage-section { padding-bottom: 14px !important; }
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
        ),
        _synthetic_storage_tree(
            task_id="storage-translation",
            title="Batch translation pipeline",
            project="Translation Tools",
            root_bytes=1 * gib + 205 * mib,
            descendant_bytes=6 * gib + 820 * mib,
            descendant_count=19,
            active_files=20,
        ),
        _synthetic_storage_tree(
            task_id="storage-glossary",
            title="Glossary cleanup",
            project="Translation Tools",
            root_bytes=320 * mib,
            descendant_bytes=680 * mib,
            descendant_count=4,
            active_files=5,
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


def capture_marketplace_screenshot(report_path: Path, output_path: Path) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport=VIEWPORT)
            page.goto(report_path.resolve().as_uri(), wait_until="load")
            page.add_style_tag(content=_SCREENSHOT_CSS)
            page.set_viewport_size(VIEWPORT)
            _wait_for_landmarks(page)
            _validate_browser_layout(page, VIEWPORT["width"])
            page.set_viewport_size(NARROW_VIEWPORT)
            _validate_browser_layout(page, NARROW_VIEWPORT["width"])
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
                temporary_path / "dashboard.html", temporary_path / "dashboard.png"
            )
        return 0

    with TemporaryDirectory() as temporary_directory:
        report_path = Path(temporary_directory) / "dashboard.html"
        _render_capture_and_validate(report_path, SCREENSHOT_PATH)
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
    )


def _render_capture_and_validate(report_path: Path, screenshot_path: Path) -> None:
    render_synthetic_report(report_path)
    capture_marketplace_screenshot(report_path, screenshot_path)
    validate_screenshot(screenshot_path)


def _wait_for_landmarks(page: Page) -> None:
    page.get_by_role("heading", name="Task Storage", exact=True).wait_for()
    page.get_by_text("Root task JSONL", exact=True).wait_for()
    page.get_by_text("Structured subagents", exact=True).wait_for()
    page.get_by_role("heading", name="Project Breakdown", exact=True).wait_for()
    page.get_by_text("Root tasks", exact=True).first.wait_for()
    page.get_by_text("Subagents", exact=True).first.wait_for()
    page.get_by_role("heading", name="Model Mix", exact=True).wait_for()
    page.get_by_text("Other", exact=True).last.wait_for(state="attached")
    page.locator(".model-legend-item").filter(has_text="Other").last.wait_for()


def _validate_browser_layout(page: Page, viewport_width: int) -> None:
    _validate_focused_tooltips(page, viewport_width)
    _validate_storage_tooltips(page, viewport_width)
    _validate_role_group_geometry(page)
    _validate_scroll_containers(page)


def _validate_focused_tooltips(page: Page, viewport_width: int) -> None:
    segments = page.locator(".model-segment")
    segment_count = segments.count()
    if segment_count < 2:
        raise RuntimeError("expected at least two model segments")
    for index in (0, segment_count - 1):
        segment = segments.nth(index)
        segment.hover()
        _validate_visible_tooltip(segment, viewport_width, interaction="hovered")
        segment.focus()
        page.wait_for_timeout(50)
        _validate_visible_tooltip(segment, viewport_width, interaction="focused")


def _validate_storage_tooltips(page: Page, viewport_width: int) -> None:
    stacks = page.locator(".storage-stack")
    stack_count = stacks.count()
    if stack_count < 2:
        raise RuntimeError("expected at least two task storage bars")
    for index in (0, stack_count - 1):
        stack = stacks.nth(index)
        stack.hover()
        _validate_visible_tooltip(stack, viewport_width, interaction="hovered storage")
        stack.focus()
        page.wait_for_timeout(50)
        _validate_visible_tooltip(stack, viewport_width, interaction="focused storage")


def _validate_visible_tooltip(
    segment: Locator, viewport_width: int, *, interaction: str
) -> None:
    diagnostics = segment.locator(".chart-tooltip").evaluate(
        """
        tooltip => {
          const rect = tooltip.getBoundingClientRect();
          const clippingAncestors = [];
          for (let ancestor = tooltip.parentElement; ancestor; ancestor = ancestor.parentElement) {
            const style = getComputedStyle(ancestor);
            const ancestorRect = ancestor.getBoundingClientRect();
            const clipsX = style.overflowX !== "visible";
            const clipsY = style.overflowY !== "visible";
            const clippedX = clipsX && (rect.left < ancestorRect.left || rect.right > ancestorRect.right);
            const clippedY = clipsY && (rect.top < ancestorRect.top || rect.bottom > ancestorRect.bottom);
            if (clippedX || clippedY) {
              clippingAncestors.push(ancestor.className || ancestor.tagName);
            }
          }
          const originalPointerEvents = tooltip.style.pointerEvents;
          tooltip.style.pointerEvents = "auto";
          const hit = document.elementFromPoint(
            rect.left + Math.min(rect.width / 2, Math.max(1, rect.width - 1)),
            rect.top + Math.min(rect.height / 2, Math.max(1, rect.height - 1)),
          );
          tooltip.style.pointerEvents = originalPointerEvents;
          return {
            x: rect.x,
            y: rect.y,
            width: rect.width,
            height: rect.height,
            clipping_ancestors: clippingAncestors,
            hit_inside: Boolean(hit && tooltip.contains(hit)),
          };
        }
        """
    )
    if not isinstance(diagnostics, dict):
        raise RuntimeError(f"{interaction} model tooltip is missing diagnostics")
    if error := _tooltip_visibility_error(diagnostics, viewport_width=viewport_width):
        raise RuntimeError(f"{interaction} model tooltip {error}")


def _tooltip_visibility_error(
    tooltip: dict[str, object], *, viewport_width: int
) -> str | None:
    tooltip_x = float(tooltip["x"])
    tooltip_y = float(tooltip["y"])
    tooltip_width = float(tooltip["width"])
    tooltip_height = float(tooltip["height"])
    clipping_ancestors = tooltip["clipping_ancestors"]
    if not isinstance(clipping_ancestors, list):
        return "has invalid ancestor clipping diagnostics"
    if clipping_ancestors:
        ancestors = ", ".join(str(ancestor) for ancestor in clipping_ancestors)
        return f"is clipped by ancestor overflow: {ancestors}"
    if not tooltip.get("hit_inside"):
        return "is not reachable by tooltip hit-testing"
    if (
        tooltip_y < 0
        or tooltip_x < 0
        or tooltip_x + tooltip_width > viewport_width
        or tooltip_height <= 0
    ):
        return "escapes its visible chart area"
    return None


def _clear_tooltip_interaction(page: Page) -> None:
    page.mouse.move(0, 0)
    page.evaluate("document.activeElement?.blur()")
    page.wait_for_timeout(100)


def _validate_role_group_geometry(page: Page) -> None:
    groups = page.locator(".project-role-group")
    if groups.count() == 0:
        raise RuntimeError("expected project role groups")
    for index in range(groups.count()):
        group = groups.nth(index)
        group_box = group.bounding_box()
        stack_box = _ancestor(group, "project-role-stack").bounding_box()
        if group_box is None or stack_box is None:
            raise RuntimeError("project role group is missing geometry")
        group_x, group_y, group_width, group_height = _box_values(group_box)
        stack_x, stack_y, stack_width, stack_height = _box_values(stack_box)
        if (
            group_width <= 0
            or group_height <= 0
            or group_x < stack_x
            or group_y < stack_y
            or group_x + group_width > stack_x + stack_width
            or group_y + group_height > stack_y + stack_height
        ):
            raise RuntimeError("project role group escapes its project role stack")


def _validate_scroll_containers(page: Page) -> None:
    metrics = page.locator(".tooltip-chart-scroll").evaluate_all(
        "elements => elements.map(({clientWidth, scrollWidth}) => ({clientWidth, scrollWidth}))"
    )
    visible_metrics = _visible_scroll_metrics(metrics)
    if len(visible_metrics) != 2 or any(
        item["scrollWidth"] < item["clientWidth"] for item in visible_metrics
    ):
        raise RuntimeError("chart tooltip scroll containers have invalid geometry")
    storage_metrics = page.locator(".storage-chart-scroll").evaluate_all(
        "elements => elements.map(({clientWidth, scrollWidth}) => ({clientWidth, scrollWidth}))"
    )
    visible_storage_metrics = _visible_scroll_metrics(storage_metrics)
    if len(visible_storage_metrics) != 1 or any(
        item["scrollWidth"] < item["clientWidth"] for item in visible_storage_metrics
    ):
        raise RuntimeError("task storage scroll container has invalid geometry")


def _ancestor(locator: Locator, class_name: str) -> Locator:
    return locator.locator(
        f"xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' {class_name} ')]"
    ).first


def _box_values(box: dict[str, float]) -> tuple[float, float, float, float]:
    return box["x"], box["y"], box["width"], box["height"]


def _visible_scroll_metrics(metrics: list[dict[str, int]]) -> list[dict[str, int]]:
    return [item for item in metrics if item["clientWidth"] > 0]


if __name__ == "__main__":
    raise SystemExit(main())
