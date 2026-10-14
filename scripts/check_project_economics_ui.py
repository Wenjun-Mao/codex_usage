"""Synthetic cross-browser checks for within-project model comparisons."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright

from codex_usage.aggregation import UsageSummary, ValuedUsageRecord
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.pricing import CostBreakdown, CreditBreakdown
from codex_usage.project_economics import build_project_economics
from codex_usage.report_project_economics import (
    project_economics_css,
    render_project_economics_section,
)
from codex_usage.report_theme import report_css


SCENARIO = "within-project-model-comparison"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/playwright/project-economics"),
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    screenshot_dir = args.output / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    report = render_project_economics_section(build_project_economics(_records()))
    screenshot_paths: list[str] = []
    evidence: dict[str, object] = {
        "synthetic_only": True,
        "live_access": "none",
        "scenario": SCENARIO,
        "cases": [],
        "screenshots": screenshot_paths,
    }

    with TemporaryDirectory(prefix="project-economics-ui-") as raw:
        documents = Path(raw)
        with sync_playwright() as playwright:
            for engine in ("chromium", "webkit", "firefox"):
                browser = getattr(playwright, engine).launch()
                context = None
                try:
                    context = browser.new_context(java_script_enabled=False)
                    page = context.new_page()
                    probe = documents / "javascript-disabled.html"
                    probe.write_text(
                        '<!doctype html><html><head><script>'
                        'document.documentElement.dataset.scriptRan="true"'
                        '</script></head><body></body></html>',
                        encoding="utf-8",
                    )
                    page.goto(probe.resolve().as_uri())
                    assert page.context == context
                    assert page.locator("html").get_attribute("data-script-ran") is None

                    for theme in ("day", "night"):
                        path = documents / f"{theme}.html"
                        path.write_text(_document(theme, report), encoding="utf-8")
                        for width in (1440, 760, 360):
                            page.set_viewport_size({"width": width, "height": 900})
                            page.goto(path.resolve().as_uri())
                            assert page.locator("script").count() == 0
                            assert page.locator("html").get_attribute("data-codex-theme") == theme
                            assert page.locator("h2#project-economics-heading").is_visible()
                            project = page.locator(".project-economics-project")
                            project_summary = project.locator(":scope > summary")
                            project_summary.focus()
                            project_summary.press("Enter")
                            assert project.get_attribute("open") is not None

                            primary = project.locator(".project-economics-models")
                            for header in (
                                "Model",
                                "Average API-equivalent cost / response",
                                "Responses / turn",
                                "Tokens / turn",
                                "Measured turns",
                            ):
                                assert header in primary.inner_text(), (engine, theme, width, header)
                            primary_text = primary.inner_text()
                            for value in (
                                "gpt-6.1-sol",
                                "gpt-6-astra",
                                "gpt-6-luna",
                                "$0.00001234",
                                "$0.00001235",
                                "$0.0000",
                                "2.4K",
                                "Unavailable",
                            ):
                                assert value in primary_text, (engine, theme, width, value)

                            secondary = project.locator(".project-economics-secondary")
                            secondary_summary = secondary.locator(":scope > summary")
                            secondary_summary.focus()
                            secondary_summary.press("Enter")
                            assert secondary.get_attribute("open") is not None
                            detail_text = secondary.inner_text()
                            for value in (
                                "Total tokens",
                                "Token share",
                                "Cost share",
                                "Average cost / turn",
                                "Response coverage",
                                "Token coverage",
                                "Priceability",
                                "Exact: $0.00001234",
                                "0 / 1 responses",
                                "missing turn IDs",
                            ):
                                assert value in detail_text, (engine, theme, width, value)

                            layout = page.evaluate(
                                """() => ({
                                    pageFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1
                                        && document.body.scrollWidth <= document.documentElement.clientWidth + 1,
                                    tableScrolls: [...document.querySelectorAll('.project-economics-table-wrap')]
                                        .map(e => e.scrollWidth > e.clientWidth + 1),
                                    cellsFit: [...document.querySelectorAll('.project-economics-table-wrap th, .project-economics-table-wrap td')]
                                        .every(e => e.scrollWidth <= e.clientWidth + 1),
                                    textColor: getComputedStyle(document.body).color,
                                    background: getComputedStyle(document.body).backgroundColor
                                })"""
                            )
                            assert layout["pageFits"], (engine, theme, width, layout)
                            assert len(layout["tableScrolls"]) == 2
                            assert layout["cellsFit"], (engine, theme, width, layout)
                            if width <= 760:
                                assert any(layout["tableScrolls"]), (engine, theme, width, layout)
                            if width == 360:
                                assert all(layout["tableScrolls"]), (engine, theme, width, layout)
                                assert page.locator(".project-economics-table-wrap").first.evaluate(
                                    "e => { e.scrollLeft = 100; return e.scrollLeft > 0; }"
                                )
                            assert layout["textColor"] != layout["background"]
                            if engine == "chromium" and width in (1440, 360):
                                page.locator(".project-economics-table-wrap").first.evaluate(
                                    "e => { e.scrollLeft = 0; }"
                                )
                                screenshot = screenshot_dir / f"{theme}-{width}.png"
                                page.screenshot(path=str(screenshot), full_page=True)
                                screenshot_paths.append(str(screenshot))
                                if width == 360:
                                    primary_wrap = page.locator(
                                        ".project-economics-table-wrap"
                                    ).first
                                    primary_wrap.evaluate("e => { e.scrollLeft = 150; }")
                                    scrolled = screenshot_dir / f"{theme}-{width}-table-scrolled.png"
                                    page.screenshot(path=str(scrolled), full_page=True)
                                    screenshot_paths.append(str(scrolled))
                                    primary_wrap.evaluate("e => { e.scrollLeft = 0; }")
                            evidence["cases"].append(
                                {
                                    "engine": engine,
                                    "scenario": SCENARIO,
                                    "theme": theme,
                                    "width": width,
                                    "java_script_enabled": False,
                                    "inline_script_blocked": True,
                                    "keyboard_disclosures": True,
                                    "table_local_scroll": all(layout["tableScrolls"]),
                                    "page_overflow": False,
                                    "synthetic_only": True,
                                }
                            )
                finally:
                    if context is not None:
                        context.close()
                    browser.close()

    evidence_path = args.output / "evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "scenario": SCENARIO,
                "passed_cases": len(evidence["cases"]),
                "screenshots": screenshot_paths,
                "live_access": "none",
            }
        )
    )


def _document(theme: str, report: str) -> str:
    return (
        '<!doctype html><html lang="en" data-codex-theme="'
        + theme
        + '"><head><meta charset="utf-8"><meta name="viewport" '
        'content="width=device-width, initial-scale=1"><title>Project Economics</title>'
        f"<style>{report_css()}{project_economics_css()}</style></head>"
        f"<body><main>{report}</main></body></html>"
    )


def _records() -> tuple[ValuedUsageRecord, ...]:
    return (
        _valued("turn-a", "gpt-6.1-sol", 1_200, 0.00001234),
        _valued("turn-a", "gpt-6.1-sol", 1_200, 0.00001234),
        _valued("turn-a", "gpt-6-astra", 500, 0.00001235),
        _valued("turn-b", "gpt-6-astra", 500, 0.00001235),
        _valued("turn-c", "gpt-6-astra", 500, 0.00001235),
        _valued("turn-d", "gpt-6-luna", 100, 0.0),
        _valued("turn-unpriced", "unknown-model-no-price", 80, 0.0, unpriced=80),
        _valued("", "unknown-model-no-turn", 40, 0.0, unpriced=40),
    )


def _valued(
    turn_id: str,
    model: str,
    tokens: int,
    cost_usd: float,
    *,
    unpriced: int = 0,
) -> ValuedUsageRecord:
    usage = TokenUsage(input_tokens=tokens, total_tokens=tokens)
    return ValuedUsageRecord(
        record=UsageRecord(
            timestamp=datetime(2026, 10, 13, tzinfo=UTC),
            usage=usage,
            session_id="synthetic-project-session",
            file_path=Path("synthetic.jsonl"),
            usage_role="root",
            model=model,
            turn_id=turn_id,
            project_key="synthetic-project",
            project_label="Synthetic Project",
        ),
        summary=UsageSummary(
            usage=usage,
            cost=CostBreakdown(total_usd=cost_usd, unpriced_tokens=unpriced),
            credits=CreditBreakdown(unpriced_tokens=unpriced),
            record_count=1,
        ),
    )


if __name__ == "__main__":
    main()
