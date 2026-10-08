"""Cross-browser script-free speed chart and work-counter acceptance on synthetic data."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from codex_usage.agent_reports import render_ledger_report
from observed_speed_fixture import AT, chart_home


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/playwright/observed-speed"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    evidence = {"synthetic_only": True, "browser_views": [], "performance": {}}
    with TemporaryDirectory(prefix="speed-ui-") as raw:
        home = Path(raw)
        started = perf_counter()
        chart_home(home)
        evidence["performance"]["initial_materialization_seconds"] = perf_counter() - started
        def render(theme="day", granularity="daily"):
            return render_ledger_report(home, range_name="all", project_keys=[], theme=theme,
                timezone_name="UTC", now=AT, speed_granularity=granularity)
        started = perf_counter()
        first = render()
        evidence["performance"]["cold_html_seconds"] = perf_counter() - started
        def forbidden(*args, **kwargs):
            raise AssertionError("warm/navigation performed historical monetary work")
        with patch("codex_usage.agent_reports.materialize_ledger", forbidden), patch("codex_usage.agent_reports.indexed_allowance_report", forbidden):
            started = perf_counter()
            warm = render()
            evidence["performance"]["warm_html_seconds"] = perf_counter() - started
            assert warm.cache_hit and warm.html == first.html
            started = perf_counter()
            render(granularity="hourly")
            evidence["performance"]["window_change_seconds"] = perf_counter() - started
        evidence["performance"]["warm_monetary_materializations"] = 0
        with sync_playwright() as playwright:
            for engine in ("chromium", "webkit", "firefox"):
                browser = getattr(playwright, engine).launch()
                context = browser.new_context(java_script_enabled=False)
                try:
                    page = context.new_page()
                    for theme in ("day", "night"):
                        for granularity in ("daily", "hourly"):
                            report = render(theme, granularity)
                            document = args.output / f"{theme}-{granularity}.html"
                            document.write_text(report.html)
                            for width in (1440, 760, 360):
                                page.set_viewport_size({"width": width, "height": 900})
                                page.goto(document.resolve().as_uri())
                                assert page.locator("script").count() == 0
                                heading = page.get_by_role("heading", name="Observed Output Speed", exact=True)
                                heading.scroll_into_view_if_needed()
                                section = page.locator(".observed-speed")
                                assert section.locator(".speed-legend span").count() == 3
                                box = section.bounding_box()
                                assert box and box["x"] >= 0 and box["x"] + box["width"] <= width + 1
                                points = section.locator("svg a")
                                assert points.count() > 0
                                first_point = points.first
                                first_point.focus()
                                assert "middle 50%" in first_point.get_attribute("aria-label")
                                first_point.press("Enter")
                                target = first_point.get_attribute("href")
                                assert page.locator(target).is_visible(), "keyboard point detail stayed hidden"
                                summary = section.locator("details > summary")
                                if section.locator("details").get_attribute("open") is not None:
                                    summary.press("Enter")
                                summary.focus()
                                summary.press("Enter")
                                assert section.locator("details").get_attribute("open") is not None
                                summary.press("Enter")
                                if engine == "chromium" and granularity == "daily":
                                    section.screenshot(path=str(args.output / f"{theme}-{width}.png"))
                                evidence["browser_views"].append({"engine": engine, "theme": theme,
                                    "granularity": granularity, "width": width, "points": points.count(),
                                    "javascript_disabled": True, "keyboard_detail": True})
                finally:
                    context.close()
                    browser.close()
    (args.output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"browser_views": len(evidence["browser_views"]), "performance": evidence["performance"]}))


if __name__ == "__main__":
    main()
