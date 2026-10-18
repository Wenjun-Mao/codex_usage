"""Script-disabled, dense captured-point readability checks; synthetic only."""
import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright

from codex_usage.agent_reports import render_ledger_report
from codex_usage.report_usage_breakdown_chart import css, plot
from usage_breakdown_fixture import AT, breakdown_home
from verification.visual_cases import identity
from verification.visual_evidence import VisualEvidence


START = datetime(2026, 10, 4, tzinfo=UTC)


def dense_points():
    points = []
    for begin, length, used, increase in ((0, 3, 10, 40), (3, 2.3, 0, 100), (5.35, .15, 0, 8)):
        for i in range(4080):
            at = START + timedelta(days=begin + length * i / 4080)
            points.append({"timestamp": at.isoformat(), "limit_id": "codex", "plan": "pro",
                "slot": "primary", "duration_minutes": 10080, "resets_at": int(at.timestamp()) + 604800,
                "used_percent": used + increase * i / 4079, "provenance": "synthetic dense capture",
                "reset_credits": None, "_boundary": True})
    return points


def section(points, kind):
    intervals = [((START + timedelta(days=i)).timestamp(), (START + timedelta(days=i+1)).timestamp()) for i in range(7)]
    bars = [{"gpt-6.1-sol": v, "gpt-6-astra": max(0, v-250)} for v in (80, 120, 185, 270, 550, 320, 0)]
    chart = plot(bars, metric="cost", labels=["gpt-6.1-sol", "gpt-6-astra"],
        intervals=intervals, title="Daily selected range", timezone=UTC, daily=True,
        bucket_labels=[(START + timedelta(days=i)).date().isoformat() for i in range(7)],
        account_points=points, account_overlay=kind)
    return (css() + '<section class="section usage-breakdown"><h2>Usage &amp; Allowance Breakdown</h2>'
        + chart + '</section>')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/playwright/allowance-clarity"))
    parser.add_argument("--frozen-html", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="overlay-ui-") as raw:
        home = Path(raw)
        breakdown_home(home)
        report = render_ledger_report(home, range_name="all", project_keys=[], theme="day", timezone_name="UTC", now=AT)
    opening = report.html.index('<section class="section usage-breakdown"')
    closing = report.html.index('</section>', opening) + len('</section>')
    points = dense_points()
    additional = [{**p, "limit_id": "secondary", "plan": "plus", "used_percent": 30}
        for p in (points[0], points[2000], points[4000])]
    balance = [{"timestamp": p["timestamp"], "balance": str(62000-i*100), "plan": "pro",
        "unlimited": False, "diagnostic": "", "change": None} for i, p in enumerate(points[::1000])]
    endpoint = {**points[0], "timestamp": (START + timedelta(hours=1)).isoformat()}
    cases = [("dense-weekly", points, "weekly"), ("multi-weekly", points + additional, "weekly"),
        ("credit-balance", balance, "balance"),
        ("weekly-full", [{**endpoint, "used_percent": 0}], "weekly"),
        ("weekly-empty", [{**endpoint, "used_percent": 100}], "weekly")]
    evidence = {"synthetic_only": args.frozen_html is None, "live_access": "none", "views": []}
    with VisualEvidence(args.output, "overlay", synthetic_only=args.frozen_html is None) as audit, sync_playwright() as playwright:
        for engine in ("chromium", "webkit", "firefox"):
            browser = getattr(playwright, engine).launch()
            try:
                context = browser.new_context(java_script_enabled=False)
                page = context.new_page()
                for label, readings, kind in cases:
                    document = report.html[:opening] + section(readings, kind) + report.html[closing:]
                    for theme in ("day", "night"):
                        path = args.output / f"{label}-{theme}.html"
                        contents = document.replace('data-codex-theme="day"', f'data-codex-theme="{theme}"')
                        path.write_text(contents)
                        audit.document(f"{label}-{theme}", contents)
                        for width in (1440, 760, 360):
                            with audit.case(page, identity(engine, label, theme, width)):
                                page.set_viewport_size({"width": width, "height": 900})
                                page.goto(path.resolve().as_uri())
                                chart = page.locator(".usage-breakdown")
                                assert page.locator("script").count() == 0
                                assert chart.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
                                assert chart.locator(".ub-axis").count() == 2
                                assert chart.locator("svg").evaluate("""e => {
                                    const bounds = e.parentElement.getBoundingClientRect(), transform = e.getScreenCTM();
                                    const left = new DOMPoint(0, 0).matrixTransform(transform).x;
                                    const right = new DOMPoint(720, 0).matrixTransform(transform).x;
                                    return Math.abs(left - bounds.left) < .1 && Math.abs(right - bounds.right) < .1;
                                }"""), (engine, label, width, "time alignment")
                                assert "right axis" in chart.locator(".ub-account-title").get_attribute("title")
                                assert chart.locator(".ub-meter-legend").is_visible()
                                assert chart.locator(".ub-overlay-evidence,.ub-resolution-evidence").count() == 0
                                assert "Dense boundary evidence" not in chart.inner_text()
                                marks = chart.locator(".ub-account-point")
                                assert marks.count() == len(readings), (engine, label, marks.count())
                                assert marks.evaluate_all("es => es.every(e => e.tagName === 'circle' && e.getAttribute('aria-label').includes('right axis'))")
                                last = chart.locator('.ub-account-point[data-latest="true"][fill="var(--text)"]').first
                                tooltip = last.get_attribute('aria-label')
                                assert tooltip == last.locator('title').text_content()
                                assert tooltip.endswith('Account-wide · right axis')
                                assert len(tooltip.splitlines()) == 4 and ' at ' in tooltip
                                assert 'T00:' not in tooltip and ' | ' not in tooltip
                                point_color = last.evaluate("e => getComputedStyle(e).fill")
                                text_color = chart.locator(".ub-account-title").evaluate("e => getComputedStyle(e).color")
                                assert point_color == text_color, (engine, label, point_color, text_color)
                                last.hover()
                                assert last.evaluate("e => getComputedStyle(e).r") == "3px", (engine, label)
                                page.mouse.move(0, 0)
                                account_key = chart.locator(".ub-meter-legend span").first
                                account_key.focus()
                                assert account_key.evaluate("e => e === document.activeElement && e.matches(':focus-visible')")
                                assert account_key.get_attribute("aria-label") == account_key.get_attribute("title")
                                chart.locator("h2").click()
                                if engine == "chromium" and width in (1440, 360):
                                    chart.screenshot(path=str(args.output / f"{label}-{theme}-{width}.png"))
                                evidence["views"].append({"engine": engine, "case": label, "theme": theme,
                                    "width": width, "script_disabled": True, "captured_points": marks.count(),
                                    "synthetic_only": True, "separate_account_key": True, "hover": True, "keyboard_account_key": True})
                if args.frozen_html:
                    for theme in ("day", "night"):
                        for width in (1440, 760, 360):
                            page.set_viewport_size({"width": width, "height": 1000})
                            page.goto(args.frozen_html.resolve().as_uri())
                            page.locator("html").evaluate("(e, theme) => e.dataset.codexTheme = theme", theme)
                            chart = page.locator(".usage-breakdown")
                            assert chart.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
                            assert chart.locator(".ub-axis").count() == 2
                            assert chart.locator(".ub-meter-legend").is_visible()
                            assert "right axis" in chart.locator(".ub-account-title").get_attribute("title")
                            assert chart.locator('[data-boundary="true"]').count() > 12000
                            assert chart.locator(".ub-account-point").count() == chart.locator("circle.ub-account-point").count()
                            assert "Dense boundary evidence" not in chart.inner_text()
                            if engine == "chromium" and width in (1440, 360):
                                chart.screenshot(path=str(args.output / f"frozen-{theme}-{width}.png"))
                            evidence["views"].append({"engine": engine, "case": "retained-frozen-preview",
                                "theme": theme, "width": width, "script_disabled": True,
                                "synthetic_only": False, "captured_points": chart.locator(".ub-account-point").count(),
                                "boundary_points": chart.locator('[data-boundary="true"]').count(),
                                "separate_account_key": True, "fixed_axes": True})
            finally:
                browser.close()
    (args.output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"passed_views": len(evidence["views"]), "synthetic_only": evidence["synthetic_only"], "live_access": "none"}))


if __name__ == "__main__":
    main()
