"""Script-disabled cross-browser composition acceptance and measured warm work."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from codex_usage.agent_reports import render_ledger_report
from codex_usage.ledger_schema import open_ledger, increment_ledger_revision
from usage_breakdown_fixture import AT, breakdown_home


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/playwright/usage-breakdown"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    evidence = {"synthetic_only": True, "views": [], "performance": {}}
    with TemporaryDirectory(prefix="breakdown-ui-") as raw:
        home = Path(raw)
        started = perf_counter()
        ledger = breakdown_home(home)
        evidence["performance"]["fixture_preparation_seconds"] = perf_counter() - started
        def render(action=None, theme="day", projects=None, now=AT):
            return render_ledger_report(home, range_name="all", project_keys=projects or [],
                theme=theme, timezone_name="UTC", now=now,
                breakdown_action=json.dumps(action) if action else None)
        started = perf_counter()
        first = render()
        evidence["performance"]["cold_report_seconds"] = perf_counter() - started
        def forbidden(*args, **kwargs):
            raise AssertionError("warm navigation did historical work")
        reports = [("hour-cost-model", first)]
        current = first
        with patch("codex_usage.breakdown_reports.prepare", forbidden), patch("codex_usage.allowance_index._decode_cached_report", forbidden), patch("codex_usage.breakdown_reports.query_ledger_records", forbidden), patch("codex_usage.agent_reports.materialize_ledger", forbidden):
            started = perf_counter()
            assert render().html == first.html
            evidence["performance"]["warm_report_seconds"] = perf_counter() - started
            times = []
            for label, changes in (
                ("hour-tokens-model", {"metric": "tokens"}),
                ("hour-tokens-project", {"group": "project"}),
                ("hour-cost-project", {"metric": "cost"}),
                ("project-cost", {"view": "project"}),
                ("project-tokens", {"metric": "tokens"}),
                ("other", {"detail": "other"}),
                ("previous", {"view": "hour", "detail": "", "day": "2026-10-08"}),
                ("selected", {"basis": "selected", "day": "2026-10-09", "detail": ""}),
            ):
                desired = {**current.breakdown_navigation["state"], **changes}
                # View and day are independent visible commands, never hidden
                # API shortcuts. Exercise each issued state transition.
                for key in changes:
                    target = {**current.breakdown_navigation["state"], key: desired[key]}
                    action = next((a for a in current.breakdown_navigation["actions"] if a["state"] == target), None)
                    if action is None and key == "basis":
                        action = next(a for a in current.breakdown_navigation["actions"]
                            if a["state"][key] == desired[key] and all(a["state"][k] == current.breakdown_navigation["state"][k] for k in ("view", "metric", "group")))
                    if action:
                        started = perf_counter()
                        current = render(action)
                        times.append(perf_counter() - started)
                if label == "other":
                    action = next(a for a in current.breakdown_navigation["actions"] if a["state"]["detail"] == "other")
                    current = render(action)
                reports.append((label, current))
                assert all(current.breakdown_navigation["state"][key] == value for key, value in changes.items()), (label, current.breakdown_navigation["state"])
            action = next(a for a in current.breakdown_navigation["actions"] if a["state"]["detail"].startswith("project:"))
            current = render(action)
            reports.append(("project-drill", current))
            action = next(a for a in current.breakdown_navigation["actions"] if a["state"]["detail"].startswith("hour:"))
            reports.append(("hour-drill", render(action)))
            evidence["performance"]["warm_navigation_seconds"] = times
            evidence["performance"]["warm_history_materializations_fits_reprices"] = 0
        reports.append(("empty-filter", render(projects=["nonexistent-synthetic"])))
        from datetime import timedelta
        reports.append(("expired-anchor", render(now=AT + timedelta(hours=2))))
        with open_ledger(ledger) as connection:
            connection.execute("update ledger_sources set is_stale=1")
            increment_ledger_revision(connection)
            connection.commit()
        reports.append(("partial-coverage", render()))
        for label, now, timezone, days, duration, day in (
            ("thirty-days", AT, "UTC", 30, 10080, None),
            ("chatham-partial", AT, "Pacific/Chatham", 30, 10080, "2026-09-27"),
            ("toronto-repeated", AT.replace(month=11, day=2), "America/Toronto", 4, 10080, "2026-11-01"),
            ("five-hour-only", AT, "UTC", 4, 300, None),
            ("missing-duration", AT, "UTC", 4, None, None),
            ("multi-weekly", AT, "UTC", 4, 10080, None),
        ):
            edge_home = home / label
            breakdown_home(edge_home, now=now, days=days, duration=duration)
            if label == "multi-weekly":
                from codex_usage.allowance_models import QuotaObservation
                from codex_usage.allowance_probe import QuotaRead
                from codex_usage.allowance_store import store_read
                with open_ledger(edge_home / ".codex-usage/usage-ledger.sqlite3") as connection:
                    point = QuotaObservation(now.isoformat(), "another-limit", "primary", "plus", 40,
                        10080, int((now+timedelta(days=4)).timestamp()))
                    store_read(connection, QuotaRead(now.isoformat(), "plus", (point,)), None)
                    increment_ledger_revision(connection)
                    connection.commit()
            def edge_render(action=None):
                return render_ledger_report(edge_home, range_name="all", project_keys=[], theme="day",
                    timezone_name=timezone, now=now, breakdown_action=json.dumps(action) if action else None)
            edge = edge_render()
            selected = next(a for a in edge.breakdown_navigation["actions"] if a["state"]["basis"] == "selected")
            edge = edge_render(selected)
            if day:
                edge = edge_render(next(a for a in edge.breakdown_navigation["actions"] if a["state"]["day"] == day))
            reports.append((label, edge))
        with sync_playwright() as playwright:
            for engine in ("chromium", "webkit", "firefox"):
                browser = getattr(playwright, engine).launch()
                context = browser.new_context(java_script_enabled=False)
                try:
                    page = context.new_page()
                    for label, report in reports:
                        for theme in ("day", "night"):
                            document = args.output / f"{label}-{theme}.html"
                            contents = report.html.replace('data-codex-theme="day"', f'data-codex-theme="{theme}"')
                            document.write_text(contents)
                            for width in (1440, 760, 360):
                                page.set_viewport_size({"width": width, "height": 900})
                                page.goto(document.resolve().as_uri())
                                section = page.locator(".usage-breakdown")
                                assert section.count() == 1 and page.locator("script").count() == 0
                                assert section.evaluate("e => e.scrollWidth <= e.clientWidth + 1"), (engine, label, width, section.evaluate("e => [...e.children].map(c => [c.tagName,c.className,c.clientWidth,c.scrollWidth])"))
                                for axis in section.locator(".ub-axis").all():
                                    assert axis.is_visible()
                                    assert axis.evaluate("e => getComputedStyle(e).fontSize") == "12px"
                                axes = section.locator(".ub-time-axis")
                                for marker in section.locator("svg rect, svg circle, svg path").all():
                                    assert "2026-" in marker.locator("title").text_content(), (label, marker.inner_html())
                                for link in section.locator("svg a").all():
                                    assert "2026-" in link.get_attribute("aria-label")
                                if label == "multi-weekly":
                                    assert "another-limit · weekly · plus" in section.locator(".ub-meter-legend").inner_text()
                                    assert "codex · weekly · pro" in section.locator(".ub-meter-legend").inner_text()
                                if report.breakdown_navigation["state"]["view"] == "hour":
                                    assert axes.count() == 3, (label, axes.count())
                                    assert axes.nth(1).get_attribute("data-start") == axes.nth(2).get_attribute("data-start")
                                    assert axes.nth(1).get_attribute("data-end") == axes.nth(2).get_attribute("data-end")
                                else:
                                    assert axes.count() == 0
                                for axis in axes.all():
                                    assert axis.evaluate("e => getComputedStyle(e).fontSize") == "12px"
                                    assert axis.evaluate("e => {const r=e.getBoundingClientRect();const t=[...e.querySelectorAll('.ub-tick')].filter(x=>getComputedStyle(x).display!=='none');return t.every((x,i)=>{const b=x.querySelector('span').getBoundingClientRect();return b.left>=r.left-1 && b.right<=r.right+1 && (!i || t[i-1].querySelector('span').getBoundingClientRect().right<=b.left+1)})}"), (engine, label, width)
                                    assert axis.evaluate("e => { const start=+e.dataset.start,end=+e.dataset.end,w=e.clientWidth,left=e.getBoundingClientRect().left; return [...e.querySelectorAll('.ub-tick')].filter(t=>getComputedStyle(t).display!=='none').every(t=>Math.abs(t.getBoundingClientRect().left-left-(+t.dataset.at-start)/Math.max(.000001,end-start)*w)<2) }")
                                for group in section.locator(".ub-controls").all():
                                    assert group.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
                                summary = section.locator("details > summary").last
                                before = section.locator("details").last.get_attribute("open")
                                summary.focus()
                                summary.press("Enter")
                                assert section.locator("details").last.get_attribute("open") != before, (engine, label, width)
                                summary.press("Enter")
                                if engine == "chromium" and width in (1440, 360) and theme == "day":
                                    section.screenshot(path=str(args.output / f"{label}-{width}.png"))
                                evidence["views"].append({"engine": engine, "scenario": label, "theme": theme,
                                    "width": width, "state": report.breakdown_navigation["state"], "script_disabled": True,
                                    "exact_table_keyboard": True, "fixed_axes": True, "aligned_collision_free_time_ticks": True})
                finally:
                    context.close()
                    browser.close()
    (args.output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"views": len(evidence["views"]), "performance": evidence["performance"]}))


if __name__ == "__main__":
    main()
