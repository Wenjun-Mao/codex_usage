"""Preview the selected layout from a retained ledger; never capture or report on live state."""
import argparse
from datetime import datetime
import html
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_reports import render_ledger_report
from codex_usage.ledger_schema import open_ledger
from codex_usage.report_theme import report_css
from codex_usage.report_usage_breakdown_chart import css, plot


LAYOUTS = (("axis-linked", "Axis-Linked"),)
METRICS = (("tokens", "Tokens"), ("cost", "API cost"), ("credits", "Estimated credits"))
GRAINS = (("daily", "Daily"), ("hourly", "Hourly"))
THEMES = (("night", "Night"), ("day", "Day"))


def chart_inputs(ledger, range_name, now, timezone):
    captured = []

    def capture(bars, **kwargs):
        captured.append((bars, kwargs))
        return plot(bars, **kwargs)

    with TemporaryDirectory(prefix="breakdown-layout-preview-") as raw:
        home = Path(raw)
        target = ledger_database_path(home)
        target.parent.mkdir(parents=True, mode=0o700)
        with sqlite3.connect(ledger.resolve().as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(target) as copy:
            source.backup(copy)
        target.chmod(0o600)
        with open_ledger(target) as connection:
            connection.execute("delete from rendered_reports")
            connection.commit()

        def render(action=None):
            captured.clear()
            with patch("codex_usage.report_breakdown_time.plot", capture):
                report = render_ledger_report(home, range_name=range_name, project_keys=[],
                    theme="night", timezone_name=timezone, now=now,
                    breakdown_action=json.dumps(action) if action else None)
            if len(captured) != 1:
                raise AssertionError("Expected one source-backed timeline")
            return report, captured[0]

        report, _ = render()
        candidates = {}
        for grain, _ in GRAINS:
            desired = {**report.breakdown_navigation["state"], "grain": grain, "detail": ""}
            action = next(a for a in report.breakdown_navigation["actions"] if a["state"] == desired)
            report, _ = render(action)
            for metric, _ in METRICS:
                changes = {**report.breakdown_navigation["state"], "metric": metric}
                action = next(a for a in report.breakdown_navigation["actions"] if a["state"] == changes)
                report, inputs = render(action)
                # Native command receipts belong to the disposable home. Static
                # previews retain mark titles, not nonfunctional command links.
                candidates[grain, metric] = (inputs[0], {**inputs[1], "links": None})
        return candidates, report.ledger_revision


def filename(layout, metric, grain, theme):
    return f"{layout}-{metric}-{grain}-{theme}.html"


def controls(layout, metric, grain, theme):
    current = {"layout": layout, "metric": metric, "grain": grain, "theme": theme}
    groups = []
    for dimension, choices in (("metric", METRICS), ("grain", GRAINS), ("theme", THEMES)):
        links = []
        for value, label in choices:
            target = {**current, dimension: value}
            active = ' aria-current="true"' if value == current[dimension] else ""
            links.append(f'<a href="{filename(**target)}"{active}>{label}</a>')
        groups.append('<span class="ub-segment">' + ''.join(links) + '</span>')
    return '<nav class="ub-controls" aria-label="Preview selections">' + ''.join(groups) + '</nav>'


def document(body, theme):
    return (f'<!doctype html><html lang="en" data-codex-theme="{theme}"><head>'
        '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data:">'
        '<title>Codex Usage · Layout Comparison</title><style>' + report_css() + """
        body {margin:0;padding:24px;background:var(--bg);color:var(--text);font-family:system-ui,sans-serif}
        main {max-width:1200px;margin:0 auto}
        .preview-label {font-size:12px;color:var(--muted);margin:0 0 6px}
        .preview-title {font-size:20px;margin:0 0 12px}
        .preview-candidate {font-size:16px!important;margin:0 0 12px}
        .preview-range {margin:14px 0;font-size:12px;color:var(--muted)}
        @media(max-width:560px) {body {padding:16px}}
        </style>""" + css() + '</head><body><main>' + body + '</main></body></html>')


def build(candidates, output, revision):
    views = []
    for layout, label in LAYOUTS:
        for metric, _ in METRICS:
            for grain, _ in GRAINS:
                bars, kwargs = candidates[grain, metric]
                chart = plot(bars, **kwargs)
                intervals, timezone = kwargs["intervals"], kwargs["timezone"]
                first = datetime.fromtimestamp(intervals[0][0], timezone).strftime("%b %d, %Y %H:%M")
                last = datetime.fromtimestamp(intervals[-1][1], timezone).strftime("%b %d, %Y %H:%M")
                scope = (f'<p class="preview-range">{first} – {last} · {html.escape(str(timezone))}'
                    f' · retained snapshot · ledger {revision}</p>')
                for theme, _ in THEMES:
                    body = ('<p class="preview-label">Codex Usage · Local Preview</p>'
                        '<h1 class="preview-title">Usage &amp; Allowance Breakdown</h1>'
                        + controls(layout, metric, grain, theme) + scope
                        + f'<section class="section usage-breakdown"><h2 class="preview-candidate">{label}</h2>'
                        + chart + '</section>')
                    path = output / filename(layout, metric, grain, theme)
                    path.write_text(document(body, theme))
                    path.chmod(0o600)
                    views.append({"layout": layout, "metric": metric, "grain": grain,
                        "theme": theme, "filename": path.name})
    index = output / "index.html"
    default = output / filename("axis-linked", "cost", "daily", "night")
    index.write_text(default.read_text())
    index.chmod(0o600)
    return views


def verify(output, views):
    evidence = []
    with sync_playwright() as playwright:
        for engine in ("chromium", "webkit", "firefox"):
            browser = getattr(playwright, engine).launch()
            try:
                page = browser.new_page(java_script_enabled=False)
                selected = [v for v in views if v["metric"] == "cost" and v["grain"] == "daily"]
                if engine == "chromium":
                    selected += [v for v in views if v["theme"] == "night" and
                        (v["grain"] == "hourly" or v["metric"] != "cost")]
                for view in selected:
                    widths = (1440, 760, 360) if view["metric"] == "cost" else (360,)
                    for width in widths:
                        page.set_viewport_size({"width": width, "height": 1000})
                        page.goto((output / view["filename"]).resolve().as_uri())
                        chart = page.locator(".usage-breakdown")
                        assert chart.evaluate("e => e.scrollWidth <= e.clientWidth + 1"), (engine, view, width)
                        assert chart.locator(".ub-time-axis").count() == 1
                        assert chart.locator("svg").count() == 1
                        assert chart.locator(".ub-meter-legend").count() == 1
                        header = chart.locator(".ub-account-heading")
                        assert header.is_visible()
                        assert header.inner_text().splitlines()[0] == "Allowance Remaining"
                        metadata = header.locator(".ub-meter-legend span").get_attribute("title")
                        assert "account-wide" in metadata and "Latest captured in selected range" in metadata
                        axes = chart.locator(".ub-axis").all()
                        assert len(axes) == 2
                        for axis in axes:
                            assert axis.evaluate("e => e.getBoundingClientRect().left >= 0 && e.getBoundingClientRect().right <= innerWidth")
                        assert chart.locator(".ub-right-axis").count() == 1
                        assert chart.locator("svg circle:not(.ub-account-point)").count() == 0
                        assert chart.locator(".ub-account-point").count() > 0
                        assert not chart.locator(".ub-overlay-evidence").get_attribute("open")
                        page.locator('.ub-controls a[aria-current="true"]').first.focus()
                        latest = chart.locator('.ub-account-point[data-latest="true"]').first
                        latest.hover()
                        assert latest.evaluate("e => getComputedStyle(e).r") == "3px"
                        page.mouse.move(0, 0)
                        if engine == "chromium" and view["metric"] == "cost" and view["grain"] == "daily" and width in (1440, 360):
                            chart.screenshot(path=str(output / f'{view["layout"]}-{view["theme"]}-{width}.png'))
                        evidence.append({**view, "engine": engine, "width": width,
                            "captured_points": chart.locator(".ub-account-point").count(),
                            "boundary_points": chart.locator('[data-boundary="true"]').count()})
                if engine == "chromium":
                    page.goto((output / "index.html").resolve().as_uri())
                    assert page.locator('.ub-axis-linked[data-layout="axis-linked"]').count() == 1
                    page.get_by_role("link", name="Hourly", exact=True).click()
                    assert "hourly" in page.url
                    page.get_by_role("link", name="Tokens", exact=True).click()
                    assert "tokens-hourly" in page.url
                    page.get_by_role("link", name="Day", exact=True).click()
                    assert page.locator("html").get_attribute("data-codex-theme") == "day"
            finally:
                browser.close()
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True, help="Retained frozen snapshot, never the live ledger")
    parser.add_argument("--now", required=True)
    parser.add_argument("--range", choices=("7d", "30d", "all"), default="7d")
    parser.add_argument("--timezone", default="America/Toronto")
    parser.add_argument("--output", type=Path, default=Path("output/playwright/axis-layout-comparison"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    candidates, revision = chart_inputs(args.ledger, args.range, datetime.fromisoformat(args.now), args.timezone)
    views = build(candidates, args.output, revision)
    evidence = {"live_access": "none; supplied retained snapshot only", "ledger_revision": revision,
        "range": args.range, "timezone": args.timezone, "installed_extension_changed": False,
        "rendered_views": views, "checked_views": verify(args.output, views) if args.check else []}
    (args.output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"rendered_views": len(views), "checked_views": len(evidence["checked_views"]),
        "live_access": "none", "index": str((args.output / "index.html").resolve())}))


if __name__ == "__main__":
    main()
