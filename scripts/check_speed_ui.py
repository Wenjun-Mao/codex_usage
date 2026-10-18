"""Cross-browser script-free speed chart and work-counter acceptance on synthetic data."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from codex_usage.agent_reports import render_ledger_report
from observed_speed_fixture import AT, chart_home, converging_chart
from verification.visual_cases import identity
from verification.visual_evidence import VisualEvidence
from verification.speed_tooltips import check_point
from verification.hover_measurements import STRICT
from release.latency_context import runtime_context, validate_context


def assert_chart_layout(section, *, tooltip_screenshot=None, tooltip_limit=.25):
    chart = section.locator(".speed-chart")
    if not chart.count():
        assert section.locator(".speed-empty").is_visible()
        assert section.locator('a[href^="#speed-detail-"]').count() == 0
        return {"empty": True}
    assert chart.evaluate("e => e.scrollWidth <= e.clientWidth + 1"), "chart overflow"
    plot = chart.locator(".speed-plot")
    bounds = plot.bounding_box()
    assert plot.evaluate("e => e.scrollWidth <= e.clientWidth + 1"), "plot overflow"
    assert chart.locator(".speed-unit").is_visible()
    assert chart.locator(".speed-y-axis").is_visible()
    assert plot.locator("svg").evaluate("e => getComputedStyle(e).overflow") == "visible"
    assert plot.locator('.speed-marker').count() == plot.locator('svg a').count()
    assert plot.locator('.speed-interval').evaluate_all(
        "es => es.every(e => getComputedStyle(e).visibility === 'hidden')")
    series = chart.locator('.speed-series-label')
    boxes = sorted((series.nth(index).bounding_box() for index in range(series.count())), key=lambda box: box['y'])
    assert all(left['y'] + left['height'] <= right['y'] + 1
               for left, right in zip(boxes, boxes[1:])), 'series labels overlap'
    assert all(box['x'] >= 0 and box['x'] + box['width'] <= section.bounding_box()['x'] + section.bounding_box()['width'] + 1
               for box in boxes), 'series labels overflow'
    labels = []
    ticks = plot.locator(".speed-tick")
    for index in range(ticks.count()):
        tick = ticks.nth(index)
        if not tick.is_visible():
            continue
        box = tick.bounding_box()
        assert tick.evaluate("e => getComputedStyle(e).fontSize") == "12px"
        assert box["x"] >= bounds["x"] - 1
        assert box["x"] + box["width"] <= bounds["x"] + bounds["width"] + 1
        labels.append(box)
    labels.sort(key=lambda box: box["x"])
    assert labels
    assert all(left["x"] + left["width"] + 4 <= right["x"]
               for left, right in zip(labels, labels[1:])), "date labels overlap"
    for point in (plot.locator("svg a").first, plot.locator("svg a").last):
        point.focus()
        mark = point.locator(".speed-marker").bounding_box()
        stroke = float(point.locator(".speed-marker").evaluate("e => getComputedStyle(e).strokeWidth").removesuffix("px")) / 2
        assert mark["x"] - stroke >= bounds["x"]
        assert mark["x"] + mark["width"] + stroke <= bounds["x"] + bounds["width"]
        label = point.get_attribute("aria-label")
        assert "Median speed:" in label and "Typical range (middle 50%):" in label
        assert "tokens/s\n" in label and " responses across " in label
        assert "T00:00:" not in label and ";" not in label
        assert point.locator("title").count() == 0
        assert point.locator('.speed-interval').evaluate("e => getComputedStyle(e).visibility") == 'visible'
        assert point.evaluate("e => getComputedStyle(e).outlineStyle") == 'none'
        point.press("Enter")
        target = section.locator(point.get_attribute("href"))
        assert target.count() == 1 and target.is_visible(), "point detail stayed hidden"
    points = plot.locator('svg a')
    times = [check_point(section.page, chart.locator('.speed-chart-grid'), point,
                        screenshot=tooltip_screenshot if index == 0 else None, limit=tooltip_limit)
             for index, point in enumerate((points.first, points.last))]
    hover_point = points.first
    hover_point.locator('.speed-marker').hover()
    assert hover_point.locator('.speed-interval').evaluate("e => getComputedStyle(e).visibility") == 'visible'
    section.locator('.speed-unit').hover()
    assert section.locator(".speed-overview a").count() == 0
    summary = section.locator("details > summary")
    if section.locator("details").get_attribute("open") is not None:
        summary.press("Enter")
    summary.focus()
    summary.press("Enter")
    assert section.locator("details").get_attribute("open") is not None
    summary.press("Enter")
    return {"empty": False, "visible_ticks": len(labels), "plot_width": bounds["width"],
            "points": points.count(), "keyboard_detail": True, "tooltip_seconds": times}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/playwright/observed-speed"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    timing = runtime_context()
    origin = {**timing['origin'], 'job_key': 'visual'} if timing['execution'] == 'hosted' else None
    policy = validate_context(timing, source=timing['source'], origin=origin)
    evidence = {"synthetic_only": True, "browser_views": [], "performance": {},
                "timing_context": timing, "timing_policy": policy}
    with VisualEvidence(args.output, "speed") as audit, TemporaryDirectory(prefix="speed-ui-") as raw:
        home = Path(raw)
        started = perf_counter()
        chart_home(home)
        evidence["performance"]["initial_materialization_seconds"] = perf_counter() - started
        def render(theme="day", granularity="daily", range_name="30d", window_start=None):
            return render_ledger_report(home, range_name=range_name, project_keys=[], theme=theme,
                timezone_name="UTC", now=AT, speed_granularity=granularity,
                speed_window_start=window_start)
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
                limit = 2.0 if engine == 'webkit' and policy != STRICT else .25
                browser = getattr(playwright, engine).launch()
                context = browser.new_context(java_script_enabled=False)
                try:
                    page = context.new_page()
                    for theme in ("day", "night"):
                        for width in (1440, 760, 360):
                            with audit.case(page, identity(engine, "converging", theme, width)):
                                document = args.output / f'{theme}-converging-{width}.html'
                                contents = converging_chart(theme)
                                document.write_text(contents)
                                audit.document(f"{theme}-converging", contents)
                                page.set_viewport_size({'width': width, 'height': 900})
                                page.goto(document.resolve().as_uri())
                                section = page.locator('.observed-speed')
                                layout = assert_chart_layout(section, tooltip_limit=limit)
                                assert page.locator("script").count() == 0
                                assert section.locator('.speed-series-label').count() == 3
                                if engine == 'chromium':
                                    section.screenshot(path=str(args.output / f'{theme}-converging-{width}.png'))
                                evidence['browser_views'].append({'engine': engine, 'theme': theme,
                                    'scenario': 'converging', 'width': width,
                                    'javascript_disabled': True, **layout})
                        for name, granularity, range_name, window in (
                            ("daily", "daily", "30d", None),
                            ("daily-all", "daily", "all", None),
                            ("hourly", "hourly", "30d", None),
                            ("empty-week", "hourly", "30d", "2026-09-18"),
                            ("single-day", "hourly", "today", None),
                            ("daily-single", "daily", "today", None),
                        ):
                            report = render(theme, granularity, range_name, window)
                            for width, embedded in ((1440, False), (760, False), (360, False),
                                                    (1440, True)):
                                with audit.case(page, identity(engine, name, theme, width, embedded=embedded)):
                                    suffix = "embedded" if embedded else str(width)
                                    document = args.output / f"{theme}-{name}-{suffix}.html"
                                    contents = report.html
                                    if embedded:
                                        contents = contents.replace("</style>",
                                            ".observed-speed { width:320px; max-width:100%; }</style>")
                                    document.write_text(contents)
                                    audit.document(f"{theme}-{name}-{suffix}", contents)
                                    page.set_viewport_size({"width": width, "height": 900})
                                    page.goto(document.resolve().as_uri())
                                    assert page.locator("script").count() == 0
                                    heading = page.get_by_role("heading", name="Observed Output Speed", exact=True)
                                    heading.scroll_into_view_if_needed()
                                    section = page.locator(".observed-speed")
                                    assert section.locator(".speed-legend span").count() == 3
                                    box = section.bounding_box()
                                    assert box and box["x"] >= 0 and box["x"] + box["width"] <= width + 1
                                    tooltip_shot = (args.output / f'{theme}-{name}-{suffix}-tooltip.png'
                                        if engine == 'chromium' and theme == 'night' and name == 'hourly' else None)
                                    layout = assert_chart_layout(section, tooltip_screenshot=tooltip_shot, tooltip_limit=limit)
                                    if name == "empty-week":
                                        assert layout["empty"]
                                        assert section.locator(".speed-overview circle").count() > 0
                                        assert section.get_by_role("link", name="Latest week", exact=True).count() == 1
                                    if name == "hourly":
                                        assert "7 of 30 days" in section.locator(".speed-window").inner_text()
                                    if engine == "chromium":
                                        section.screenshot(path=str(args.output / f"{theme}-{name}-{suffix}.png"))
                                    evidence["browser_views"].append({"engine": engine, "theme": theme,
                                        "granularity": granularity, "width": width, "embedded": embedded,
                                        "scenario": name, "javascript_disabled": True, **layout})
                finally:
                    context.close()
                    browser.close()
    evidence['tooltip_observations'] = {}
    for engine in ('chromium', 'webkit', 'firefox'):
        values = [value for view in evidence['browser_views'] if view['engine'] == engine
                  for sample in view.get('tooltip_seconds', []) for value in sample.values()]
        evidence['tooltip_observations'][engine] = {
            'count': len(values), 'max_seconds': max(values),
            'at_or_above_250ms': sum(value >= .25 for value in values)}
    (args.output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"browser_views": len(evidence["browser_views"]), "performance": evidence["performance"]}))


if __name__ == "__main__":
    main()
