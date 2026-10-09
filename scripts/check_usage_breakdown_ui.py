"""Script-disabled cross-browser composition acceptance and measured warm work."""
import argparse
import json
from decimal import Decimal, localcontext
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
        ledger = breakdown_home(home, extended=True, days=12)
        evidence["performance"]["fixture_preparation_seconds"] = perf_counter() - started
        def render(action=None, theme="day", projects=None, now=AT, range_name="all"):
            return render_ledger_report(home, range_name=range_name, project_keys=projects or [],
                theme=theme, timezone_name="UTC", now=now,
                breakdown_action=json.dumps(action) if action else None)
        started = perf_counter()
        first = render()
        evidence["performance"]["cold_report_seconds"] = perf_counter() - started
        def forbidden(*args, **kwargs):
            raise AssertionError("warm navigation did historical work")
        reports = [("hour-cost-model", first)]
        current = first
        with patch("codex_usage.breakdown_reports.prepare", forbidden), patch("codex_usage.allowance_index._decode_cached_report", forbidden), patch("codex_usage.breakdown_reports.query_ledger_records", forbidden), patch("codex_usage.agent_reports.materialize_ledger", forbidden), patch("codex_usage.breakdown_evidence.prepare_balances", forbidden), patch("codex_usage.breakdown_reports.value_records", forbidden):
            started = perf_counter()
            assert render().html == first.html
            evidence["performance"]["warm_report_seconds"] = perf_counter() - started
            times = []
            for label, changes in (
                ("hour-tokens-model", {"metric": "tokens"}),
                ("hour-tokens-project", {"group": "project"}),
                ("hour-cost-project", {"metric": "cost"}),
                ("hour-credits-model", {"metric": "credits", "group": "model"}),
                ("hour-credits-project", {"group": "project"}),
                ("project-credits", {"view": "project"}),
                ("project-cost", {"metric": "cost"}),
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
            for index, action in enumerate(a for a in first.breakdown_navigation["actions"] if a["state"]["basis"].startswith("window:")):
                started = perf_counter()
                historical = render(action)
                times.append(perf_counter()-started)
                reports.append((f"dated-window-{index}", historical))
            evidence["performance"]["warm_navigation_seconds"] = times
            evidence["performance"]["warm_history_materializations_fits_reprices"] = 0
        reports.append(("empty-filter", render(projects=["nonexistent-synthetic"])))
        for label, projects in (("month-selected", []), ("month-empty-filter", ["nonexistent-synthetic"])):
            month = render(projects=projects, range_name="month")
            selected = next(a for a in month.breakdown_navigation["actions"] if a["state"]["basis"] == "selected")
            month = render(selected, projects=projects, range_name="month")
            assert month.breakdown_navigation["state"]["day"] == "2026-10-09"
            reports.append((label, month))
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
            ("large-balance-small-decrease", AT, "UTC", 12, 10080, None),
            ("extreme-balances", AT, "UTC", 12, 10080, None),
            ("tiny-balances", AT, "UTC", 12, 10080, None),
            ("signed-credit-changes", AT, "UTC", 12, 10080, None),
            ("large-token-scale", AT, "UTC", 12, 10080, None),
            ("unknown-balances", AT, "UTC", 4, 10080, None),
            ("unlimited-balances", AT, "UTC", 4, 10080, None),
        ):
            edge_home = home / label
            breakdown_home(edge_home, now=now, days=days, duration=duration,
                extended=label in {"large-balance-small-decrease", "extreme-balances", "tiny-balances", "signed-credit-changes"}, credit_base=62500,
                token_multiplier=1000 if label == "large-token-scale" else 1)
            if label in {"extreme-balances", "tiny-balances", "signed-credit-changes"}:
                with open_ledger(edge_home / ".codex-usage/usage-ledger.sqlite3") as connection, localcontext() as context:
                    context.prec = 40
                    reads = connection.execute("select read_id from credit_observations order by read_id").fetchall()
                    for index, row in enumerate(reads):
                        value = (Decimal("1e18") - index*Decimal("1e-18") if label == "extreme-balances" else
                            (len(reads)-index)*Decimal("1e-18") if label == "tiny-balances" else
                            Decimal("1e18") if index % 2 else Decimal(0))
                        connection.execute("update credit_observations set balance=? where read_id=?", (format(value, "f"), row[0]))
                    increment_ledger_revision(connection)
                    connection.commit()
            if label == "unlimited-balances":
                with open_ledger(edge_home / ".codex-usage/usage-ledger.sqlite3") as connection:
                    connection.execute("update credit_observations set unlimited=1, diagnostic=''")
                    increment_ledger_revision(connection)
                    connection.commit()
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
            if label == "large-token-scale":
                edge = edge_render(next(a for a in edge.breakdown_navigation["actions"] if a["state"]["metric"] == "tokens"))
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
                                for axis in section.locator(".ub-axis").all():
                                    # A span box fits even when its glyphs extend into the plot.
                                    boxes = axis.evaluate("e => {const gutter=e.getBoundingClientRect(),right=gutter.right-parseFloat(getComputedStyle(e).paddingRight);return [...e.children].filter(s=>s.textContent.trim()).map(s=>{const range=document.createRange();range.selectNodeContents(s);const text=range.getBoundingClientRect(),span=s.getBoundingClientRect();return {label:s.textContent,textLeft:text.left,textRight:text.right,spanLeft:span.left,spanRight:span.right,gutterLeft:gutter.left,gutterRight:right}})}")
                                    assert all(b["textLeft"] >= max(b["spanLeft"], b["gutterLeft"])-1 and b["textRight"] <= min(b["spanRight"], b["gutterRight"])+1 for b in boxes), (engine, label, width, boxes)
                                axes = section.locator(".ub-time-axis")
                                for marker in section.locator("svg rect, svg circle, svg path").all():
                                    assert "2026-" in marker.locator("title").text_content(), (label, marker.inner_html())
                                for link in section.locator("svg a").all():
                                    assert "2026-" in link.get_attribute("aria-label")
                                if label == "multi-weekly":
                                    assert "another-limit · weekly · plus" in section.locator(".ub-meter-legend").inner_text()
                                    assert "codex · weekly · pro" in section.locator(".ub-meter-legend").inner_text()
                                if label in ("unknown-balances", "unlimited-balances"):
                                    assert section.locator(".ub-balances .ub-axis").inner_text().strip() == "Unknown"
                                    assert section.locator(".ub-credit-changes .ub-axis").inner_text().strip() == "Unknown"
                                    assert "No finite valid balances among in-domain captures" in section.inner_text()
                                    assert "No in-domain balance captures" not in section.inner_text()
                                if label == "extreme-balances":
                                    assert "Axis offset:" in section.inner_text()
                                    tick_labels = section.locator(".ub-balances .ub-axis span").all_text_contents()
                                    assert len(set(tick_labels)) == 3, tick_labels
                                if report.breakdown_navigation["state"]["view"] == "hour":
                                    assert axes.count() == 5, (label, axes.count())
                                    for i in (2, 3, 4):
                                        assert axes.nth(1).get_attribute("data-start") == axes.nth(i).get_attribute("data-start")
                                        assert axes.nth(1).get_attribute("data-end") == axes.nth(i).get_attribute("data-end")
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
                                if engine == "chromium" and width in (1440, 360):
                                    section.screenshot(path=str(args.output / f"{label}-{theme}-{width}.png"))
                                evidence["views"].append({"engine": engine, "scenario": label, "theme": theme,
                                    "width": width, "state": report.breakdown_navigation["state"], "script_disabled": True,
                                    "exact_table_keyboard": True, "fixed_axes": True, "axis_text_contained": True, "aligned_collision_free_time_ticks": True})
                finally:
                    context.close()
                    browser.close()
    (args.output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"views": len(evidence["views"]), "performance": evidence["performance"]}))


if __name__ == "__main__":
    main()
