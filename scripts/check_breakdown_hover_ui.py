"""Script-disabled immediate hover/focus and compact time-axis acceptance."""
import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

from codex_usage.report_usage_breakdown_chart import plot
from preview_breakdown_layouts import document


def chart(zone_name, *, days=1, metric="cost", dst=False):
    zone = ZoneInfo(zone_name)
    start = datetime(2026, 11, 1, tzinfo=zone) if dst else datetime(2026, 10, 10, tzinfo=zone)
    end = start + timedelta(days=days)
    span = (end.timestamp()-start.timestamp()) / 3
    intervals = [(start.timestamp()+i*span, start.timestamp()+(i+1)*span) for i in range(3)]
    values = [{"gpt-6-astra": 74.19778399999994, "gpt-6.1-sol": 17.814169600000003,
        "gpt-6-luna": .000001} for _ in intervals]
    if metric == "tokens":
        values = [{"gpt-6-astra": 139030000, "gpt-6.1-sol": 278050000,
            "gpt-6-luna": 1} for _ in intervals]
    point = {"timestamp": start.isoformat(), "plan": "pro", "limit_id": "codex",
        "slot": "primary", "duration_minutes": 10080, "used_percent": 10,
        "resets_at": int((start+timedelta(days=7)).timestamp()), "reset_credits": None,
        "provenance": "synthetic", "_boundary": True}
    return plot(values, metric=metric, labels=list(values[0]),
        links=["command:codexUsage.navigateBreakdown?issued=" + str(i) for i in range(3)],
        intervals=intervals, timezone=zone, bucket_labels=[
            datetime.fromtimestamp(a, zone).strftime("%Y-%m-%d %H:%M %z") for a, _ in intervals],
        account_points=[point, {**point, "timestamp": datetime.fromtimestamp(
            start.timestamp()+span/2, zone).isoformat()}], account_overlay="weekly")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/playwright/breakdown-hover"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    evidence = {"synthetic_only": True, "script_disabled": True, "views": []}
    with sync_playwright() as playwright:
        for engine in ("chromium", "webkit", "firefox"):
            browser = getattr(playwright, engine).launch()
            context = browser.new_context(java_script_enabled=False)
            page = context.new_page()
            try:
                for scenario, kwargs in (("single-day", {}), ("multi-day", {"days": 7}),
                    ("dst", {"dst": True}), ("tokens", {"metric": "tokens"})):
                    for theme in ("night", "day"):
                        path = args.output / f"{scenario}-{theme}.html"
                        path.write_text(document(chart("America/Toronto", **kwargs), theme))
                        for width in (1440, 760, 360):
                            page.set_viewport_size({"width": width, "height": 900})
                            page.goto(path.resolve().as_uri())
                            assert page.locator("script").count() == 0
                            assert page.locator("svg rect title").count() == 0
                            assert page.locator(".ub-time-axis .ub-tick br").count() <= 5
                            durations = []
                            targets = page.locator(".ub-hover-target")
                            for index in range(3):
                                page.evaluate("document.activeElement.blur()")
                                target = targets.nth(index)
                                hit = target.locator(".ub-hover-hit")
                                assert hit.get_attribute("title") == ""
                                tooltip = page.locator(".ub-hover-bucket").nth(index).locator(".ub-hover-tooltip")
                                started = perf_counter()
                                hit.hover(position={"x": 2, "y": 2}, timeout=1000)
                                tooltip.wait_for(state="visible", timeout=250)
                                durations.append(perf_counter()-started)
                                text = tooltip.inner_text()
                                assert "74.197783" not in text and "e+" not in text
                                assert "$74.20" in text if scenario != "tokens" else "139.03 M tokens" in text
                                assert target.get_attribute("href").endswith("issued=" + str(index))
                                assert tooltip.evaluate("e=>{const b=e.getBoundingClientRect(),p=e.closest('.ub-scroll').getBoundingClientRect();return b.left>=p.left-1&&b.right<=p.right+1&&e.scrollWidth<=e.clientWidth+1}"), (engine, scenario, width, text)
                                page.mouse.move(0, 0)
                                tooltip.wait_for(state="hidden", timeout=250)
                                page.keyboard.press("Tab")
                                target.focus()
                                tooltip.wait_for(state="visible", timeout=250)
                                if index < 2:
                                    page.keyboard.press("Tab")
                                    assert targets.nth(index+1).evaluate("e=>e===document.activeElement")
                            # Account marks keep native hit testing above the usage plot.
                            for point in page.locator(".ub-account-point").all():
                                assert point.evaluate("e=>{const r=e.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===e}")
                            axis = page.locator(".ub-time-axis")
                            assert axis.evaluate("e=>[...e.querySelectorAll('.ub-tick>span')].every(t=>t.querySelectorAll('br').length<=1)")
                            assert page.locator(".ub-time-context").inner_text().count("America/Toronto") == 1
                            if engine == "chromium" and width in (1440, 360):
                                page.locator("main").screenshot(path=str(args.output / f"{scenario}-{theme}-{width}.png"))
                            evidence["views"].append({"engine": engine, "scenario": scenario,
                                "theme": theme, "width": width, "hover_seconds": durations,
                                "hover_focus_within_250ms": True, "tooltip_contained": True,
                                "account_hit_preserved": True})
            finally:
                context.close()
                browser.close()
    (args.output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"views": len(evidence["views"]), "script_disabled": True}))


if __name__ == "__main__":
    main()
