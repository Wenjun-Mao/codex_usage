"""Capture deterministic, synthetic VS Code Companion Marketplace images."""
from __future__ import annotations

import argparse
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import Page, sync_playwright

from codex_usage.aggregation import aggregate_records, summarize_records
from codex_usage.marketplace_screenshot_validation import validate_screenshot
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.report_breakdown import build_report_breakdown
from codex_usage.reporting import render_html_report

from allowance_fixture import allowance_fixture

ROOT = Path(__file__).resolve().parents[1]
EXTENSION_ROOT = ROOT / "extensions" / "vscode"
MARKETPLACE_ROOT = ROOT / "docs" / "marketplace"
USAGE_SCREENSHOT_PATH = MARKETPLACE_ROOT / "extension-usage-synthetic.png"
USAGE_SCREENSHOT_PATHS = {
    (theme, size): MARKETPLACE_ROOT / f"extension-usage-{theme}-{size}-synthetic.png"
    for theme in ("day", "night")
    for size in ("wide", "narrow")
}
STORAGE_SCREENSHOT_PATH = MARKETPLACE_ROOT / "extension-storage-synthetic.png"
VIEWPORT = {"width": 1440, "height": 900}
NARROW_VIEWPORT = {"width": 760, "height": 900}
PRIVATE_MARKERS = ("/Users/", "C:\\Users\\", "OneDrive-Personal", "session.jsonl")


def synthetic_records() -> list[UsageRecord]:
    """Fixed public sample names and values; never read a Codex home or ledger."""
    models = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5")
    projects = (("studio_atlas", "Studio Atlas"), ("northstar", "Northstar"), ("meridian", "Meridian"))
    origin = datetime(2026, 8, 17, 9, tzinfo=UTC)
    records = []
    for day in range(16):
        for project_index, (project_key, project_label) in enumerate(projects):
            for role_index, role in enumerate(("root", "subagent")):
                amount = (8_000 + (day * 1211 + project_index * 3547 + role_index * 1793) % 14_000) * (2 if role == "root" else 1)
                records.append(UsageRecord(
                    timestamp=origin + timedelta(days=day, hours=project_index * 2 + role_index),
                    usage=TokenUsage(
                        input_tokens=amount * 3 // 5,
                        cached_input_tokens=amount // 5,
                        cache_write_input_tokens=amount // 10,
                        output_tokens=amount // 5,
                        total_tokens=amount,
                    ),
                    session_id=f"sample-{day:02d}-{project_index}-{role_index}",
                    file_path=Path("sample-task.jsonl"),
                    usage_role=role,
                    model=models[(day + project_index + role_index) % len(models)],
                    project_key=project_key,
                    project_label=project_label,
                ))
    return records


def render_fixture(directory: Path) -> dict[tuple[str, str], Path]:
    records = synthetic_records()
    raw_usage = directory / "raw-usage.html"
    render_html_report(
        output_path=raw_usage,
        generated_at=datetime(2026, 9, 2, 16, tzinfo=UTC),
        range_name="all",
        total=summarize_records(records),
        daily_rows=aggregate_records(records, "day", UTC),
        hourly_rows=aggregate_records(records, "hour", UTC),
        breakdown=build_report_breakdown(records),
        sessions_dirs=[Path("sample-sessions")],
        files_scanned=len(records),
        theme="night",
        embedded_usage_only=True,
        allowance_report=allowance_fixture(),
    )
    subprocess.run(["npm", "run", "build"], cwd=EXTENSION_ROOT, check=True)
    subprocess.run(
        ["node", str(ROOT / "scripts" / "render_extension_marketplace.js"), str(raw_usage), str(directory)],
        check=True,
    )
    return {(theme, view): directory / f"{view}-{theme}.html" for theme in ("day", "night") for view in ("usage", "storage")}


def capture_marketplace_screenshots(
    documents: dict[tuple[str, str], Path],
    usage_paths: dict[tuple[str, str], Path],
    storage_path: Path,
) -> None:
    for output in (*usage_paths.values(), storage_path):
        output.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(locale="en-US", timezone_id="UTC")
            backgrounds: dict[tuple[str, str], str] = {}
            for theme in ("day", "night"):
                for size, viewport in (("wide", VIEWPORT), ("narrow", NARROW_VIEWPORT)):
                    _open_document(page, documents[(theme, "usage")], viewport)
                    _check_usage(page, theme)
                    _check_layout(page, viewport)
                    backgrounds[(theme, "usage")] = page.locator("body").evaluate(
                        "element => getComputedStyle(element).backgroundColor"
                    )
                    page.evaluate("() => { document.activeElement?.blur(); window.scrollTo(0, 0); }")
                    page.mouse.move(0, 0)
                    page.screenshot(path=str(usage_paths[(theme, size)]), full_page=False)
                for viewport in (VIEWPORT, NARROW_VIEWPORT):
                    _open_document(page, documents[(theme, "storage")], viewport)
                    _check_storage(page, theme)
                    _check_layout(page, viewport)
                    backgrounds[(theme, "storage")] = page.locator("body").evaluate(
                        "element => getComputedStyle(element).backgroundColor"
                    )
                    if theme == "night" and viewport == VIEWPORT:
                        page.screenshot(path=str(storage_path), full_page=False)
            for view in ("usage", "storage"):
                if backgrounds[("day", view)] == backgrounds[("night", view)]:
                    raise RuntimeError(f"{view} Day and Night themes render the same background")
        finally:
            browser.close()


def _open_document(page: Page, document: Path, viewport: dict[str, int]) -> None:
    page.set_viewport_size(viewport)
    page.goto(document.as_uri(), wait_until="load")
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    source = page.locator("body").inner_text()
    if any(marker.casefold() in source.casefold() for marker in PRIVATE_MARKERS):
        raise RuntimeError("synthetic extension fixture contains private data or a local path")
    if page.locator("script").count():
        raise RuntimeError("Marketplace HTML unexpectedly contains executable script")


def _check_usage(page: Page, theme: str) -> None:
    assert page.locator("html").get_attribute("data-codex-theme") == theme
    page.get_by_role("heading", name="Token Usage", exact=True).wait_for()
    page.get_by_role("heading", name="Plan Allowance", exact=True).wait_for()
    page.get_by_role("link", name="Capture Usage", exact=True).wait_for()
    page.get_by_role("link", name="Task Transfer", exact=True).wait_for()
    assert page.get_by_role("link", name="Open App", exact=True).count() == 0
    assert page.locator(".project-role-group").count() > 0
    assert page.locator(".model-segment").count() > 1
    token = page.locator("#compare-scale-tokens")
    cost = page.locator("#compare-scale-cost")
    token.focus()
    token.press("ArrowRight")
    assert cost.is_checked()
    cost.press("ArrowLeft")
    assert token.is_checked()
    disclosure = page.locator("details.token-accounting").first
    if disclosure.count():
        summary = disclosure.locator("summary")
        summary.focus()
        summary.press("Enter")
        assert disclosure.evaluate("element => element.open")
        summary.press("Enter")
        assert not disclosure.evaluate("element => element.open")
    for target in (page.locator(".model-segment").first, page.locator(".model-segment").last):
        target.focus()
        tooltip = target.locator(".chart-tooltip")
        if not tooltip.is_visible():
            raise RuntimeError("focused model segment has no visible tooltip")
        box = tooltip.bounding_box()
        if box is None or box["x"] < -1 or box["x"] + box["width"] > page.viewport_size["width"] + 1:
            raise RuntimeError(f"focused model tooltip is clipped: {box}")


def _check_storage(page: Page, theme: str) -> None:
    assert page.locator("html").get_attribute("data-codex-theme") == theme
    page.get_by_role("heading", name="Task Storage", exact=True).wait_for()
    page.get_by_role("heading", name="Largest Task Trees", exact=True).wait_for()
    page.get_by_text("Build onboarding flow", exact=True).wait_for()
    assert page.get_by_role("link", name="Analyze", exact=True).count() >= 1
    assert page.get_by_role("link", name="Task Transfer", exact=True).count() == 1


def _check_layout(page: Page, viewport: dict[str, int]) -> None:
    width = viewport["width"]
    metrics = page.evaluate("""() => ({
      document: document.documentElement.scrollWidth,
      body: document.body.scrollWidth,
      viewport: window.innerWidth,
      nav: (() => { const r = document.querySelector('.companion-actions').getBoundingClientRect(); return {left:r.left,right:r.right}; })(),
      header: (() => { const r = document.querySelector('.report-header').getBoundingClientRect(); return {left:r.left,right:r.right}; })()
    })""")
    if metrics["document"] > width + 1 or metrics["body"] > width + 1:
        raise RuntimeError(f"extension webview overflows at {width}px: {metrics}")
    for key in ("nav", "header"):
        if metrics[key]["left"] < -1 or metrics[key]["right"] > width + 1:
            raise RuntimeError(f"extension {key} escapes {width}px viewport: {metrics[key]}")


def _render_capture_and_validate(usage_paths: dict[tuple[str, str], Path], storage_path: Path) -> None:
    with TemporaryDirectory() as temporary_directory:
        documents = render_fixture(Path(temporary_directory))
        capture_marketplace_screenshots(documents, usage_paths, storage_path)
    for (_theme, size), path in usage_paths.items():
        validate_screenshot(path, NARROW_VIEWPORT if size == "narrow" else VIEWPORT)
    validate_screenshot(storage_path, VIEWPORT)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate temporary captures without changing tracked images")
    args = parser.parse_args(argv)
    if args.check:
        with TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            _render_capture_and_validate(
                {key: temporary / path.name for key, path in USAGE_SCREENSHOT_PATHS.items()},
                temporary / STORAGE_SCREENSHOT_PATH.name,
            )
    else:
        _render_capture_and_validate(USAGE_SCREENSHOT_PATHS, STORAGE_SCREENSHOT_PATH)
        # The main listing image is the Night wide capture.
        USAGE_SCREENSHOT_PATH.write_bytes(USAGE_SCREENSHOT_PATHS[("night", "wide")].read_bytes())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
