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
from verification.breakdown_layout import SNAPSHOT, assert_layout
from verification.visual_cases import identity
from verification.visual_evidence import VisualEvidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/playwright/usage-breakdown"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    evidence = {"synthetic_only": True, "views": [], "performance": {}}
    with VisualEvidence(args.output, "breakdown") as audit, TemporaryDirectory(prefix="breakdown-ui-") as raw:
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
        reports = [("daily-cost-model", first)]
        current = first
        with patch("codex_usage.breakdown_reports.prepare", forbidden), patch("codex_usage.allowance_index._decode_cached_report", forbidden), patch("codex_usage.breakdown_reports.query_ledger_records", forbidden), patch("codex_usage.agent_reports.materialize_ledger", forbidden), patch("codex_usage.breakdown_evidence.prepare_balances", forbidden), patch("codex_usage.breakdown_reports.value_records", forbidden):
            started = perf_counter()
            assert render().html == first.html
            evidence["performance"]["warm_report_seconds"] = perf_counter() - started
            times = []
            for key, value in (("metric", "tokens"), ("group", "project"), ("metric", "credits"),
                ("overlay", "balance"), ("overlay", "none"), ("grain", "hourly"),
                ("overlay", "weekly"), ("metric", "cost"), ("group", "model"),
                ("view", "project"), ("metric", "tokens"), ("metric", "credits"),
                ("view", "time"), ("grain", "daily")):
                desired = {**current.breakdown_navigation["state"], key: value}
                if key == "grain":
                    desired["detail"] = ""
                action = next(a for a in current.breakdown_navigation["actions"] if a["state"] == desired)
                started = perf_counter()
                current = render(action)
                times.append(perf_counter()-started)
                reports.append((f"control-{key}-{value}-{len(reports)}", current))
            day = next(a for a in current.breakdown_navigation["actions"] if a["state"]["detail"] == "day:2026-10-08")
            current = render(day)
            reports.append(("daily-drill", current))
            for label, predicate in (
                ("previous", lambda s: s["day"] < current.breakdown_navigation["state"]["day"] and not s["detail"]),
                ("hour-drill", lambda s: s["detail"].startswith("hour:")),
                ("project-drill", lambda s: bool(s["project"])),
                ("return-daily", lambda s: s == {**current.breakdown_navigation["state"], "grain": "daily", "detail": ""})):
                current = render(next(a for a in current.breakdown_navigation["actions"] if predicate(a["state"])))
                reports.append((label, current))
            evidence["performance"]["warm_navigation_seconds"] = times
            evidence["performance"]["warm_history_materializations_fits_reprices"] = 0
        reports.append(("empty-filter", render(projects=["nonexistent-synthetic"])))
        for label, projects in (("month-selected", []), ("month-empty-filter", ["nonexistent-synthetic"])):
            month = render(projects=projects, range_name="month")
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
            ("lord-howe-partial", AT.replace(day=5), "Australia/Lord_Howe", 30, 10080, "2026-10-04"),
            ("dense-history", AT, "UTC", 180, 10080, None),
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
            if day:
                edge = edge_render(next(a for a in edge.breakdown_navigation["actions"] if a["state"]["detail"] == "day:" + day))
            if label == "large-token-scale":
                edge = edge_render(next(a for a in edge.breakdown_navigation["actions"] if a["state"]["metric"] == "tokens"))
            if "balance" in label or label == "signed-credit-changes":
                edge = edge_render(next(a for a in edge.breakdown_navigation["actions"] if a["state"]["overlay"] == "balance"))
            if "balance" in label or label in {"unknown-balances", "unlimited-balances", "missing-duration", "five-hour-only", "multi-weekly"}:
                edge = edge_render(next(a for a in edge.breakdown_navigation["actions"] if a["state"]["detail"] == "readings:" + edge.breakdown_navigation["state"]["day"]))
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
                            audit.document(f"{label}-{theme}", contents)
                            evidence["performance"].setdefault("html_bytes", {})[label] = len(contents.encode())
                            for width in (1440, 760, 360):
                                with audit.case(page, identity(engine, label, theme, width)):
                                    page.set_viewport_size({"width": width, "height": 900})
                                    page.goto(document.resolve().as_uri())
                                    assert_layout(page.evaluate(SNAPSHOT), label, report.breakdown_navigation["state"])
                                    section = page.locator(".usage-breakdown")
                                    summary = section.locator("details > summary").last
                                    details = section.locator("details").last
                                    before = details.get_attribute("open")
                                    summary.focus()
                                    summary.press("Enter")
                                    assert details.get_attribute("open") != before, (engine, label, width)
                                    summary.press("Enter")
                                    assert details.get_attribute("open") == before, (engine, label, width)
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
