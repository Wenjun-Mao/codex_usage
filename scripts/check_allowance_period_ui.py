"""Real private-host replay within mandatory allowance browser qualification."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote

from allowance_period_fixture import allowance_period_fixture, dense_period_fixture, install_history_cache, official_display_fixture
from codex_usage.agent_reports import render_ledger_report
from verification.visual_cases import PERIOD_HISTORY_STATES, THEMES, WIDTHS, identity


def check_period_matrix(page, engine, audit):
    count = 0
    screenshots = audit.output / "period-history"
    screenshots.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="allowance-period-ui-") as directory:
        variants = []
        for variant in ("official-conflicts", "uncertain-current", "lone-current"):
            home = Path(directory) / variant
            home.mkdir()
            variants.append((variant, home, install_history_cache(home, official_display_fixture(home, variant))))
        for scenario in PERIOD_HISTORY_STATES:
            home = Path(directory) / scenario
            home.mkdir()
            report = (allowance_period_fixture if scenario == "period-history" else dense_period_fixture)(home)
            now = install_history_cache(home, report)
            for theme in THEMES:
                def render(action=None):
                    return render_ledger_report(home, range_name="all", project_keys=[], theme=theme,
                        timezone_name="America/Toronto", now=now,
                        allowance_action=json.dumps(action) if action is not None else None)
                first = render()
                audit.document(f"{scenario}-{theme}", first.html)
                for width in WIDTHS:
                    with audit.case(page, identity(engine, scenario, theme, width)):
                        _check_period_view(page, first, render, scenario, width, screenshots,
                                           f"{engine}-{scenario}-{theme}-{width}")
                        if scenario == "period-history":
                            for variant, variant_home, variant_now in variants:
                                extra = render_ledger_report(variant_home, range_name="all", project_keys=[], theme=theme,
                                    timezone_name="America/Toronto", now=variant_now)
                                audit.document(f"{variant}-{theme}", extra.html)
                                _check_current(page, extra, variant, screenshots, f"{engine}-{variant}-{theme}-{width}")
                    count += 1
    return count


def _check_period_view(page, first, render, scenario, width, screenshots, key):
    current = first
    page.set_viewport_size({"width": width, "height": 900})
    page.set_content(current.html)
    assert page.locator("script").count() == 0

    def disclose():
        summary = page.get_by_text("Probe, coverage, and allowance history", exact=True)
        if not summary.evaluate("e => e.parentElement.open"):
            summary.focus()
            summary.press("Enter")

    def follow(predicate):
        nonlocal current
        for link in page.get_by_role("link").all():
            uri = link.get_attribute("href") or ""
            if uri.startswith("command:codexUsage.navigateAllowanceHistory?"):
                action = json.loads(unquote(uri.split("?", 1)[1]))[0]
                if predicate(action["state"]) and link.is_visible():
                    assert action in current.allowance_navigation["actions"]
                    link.focus()
                    assert link.evaluate("e => e === document.activeElement")
                    link.press("Enter")
                    current = render(action)
                    assert current.allowance_navigation["state"] == action["state"]
                    page.set_content(current.html)
                    disclose()
                    return
        raise AssertionError("Missing visible issued history action")

    def uncertain_open():
        summary = page.locator(".allowance-uncertain > summary")
        if not summary.evaluate("e => e.parentElement.open"):
            summary.focus()
            summary.press("Enter")

    disclose()
    periods = page.get_by_role("list", name="Allowance period history")
    dense = scenario == "period-history-dense"
    assert periods.locator(":scope > li").count() == (12 if dense else 2)
    assert not page.locator(".allowance-uncertain").evaluate("e => e.open")
    assert page.locator(".allowance-uncertain > summary").inner_text() == (
        "Uncertain readings (79)" if dense else "Uncertain readings (4)")
    assert page.locator(".allowance-observations").count() == 0
    periods.scroll_into_view_if_needed()
    page.screenshot(path=str(screenshots / f"{key}-compact.png"))
    if dense:
        for index in (1, 2, 3):
            follow(lambda s: s["period_page"] == index and s["kind"] == "")
        assert periods.locator(":scope > li").count() == 5
        follow(lambda s: s["kind"] == "periods" and s["index"] == 40)
        assert page.locator(".allowance-observations tbody tr").count() == 1
        for index in (1, 2, 3):
            uncertain_open()
            follow(lambda s: s["uncertain_page"] == index and s["kind"] == "")
        assert page.locator(".allowance-uncertain > ol > li").count() == 4
        follow(lambda s: s["kind"] == "uncertain" and s["index"] == 39)
    else:
        assert "Observed 2026-10-31 to 2026-11-01" in periods.inner_text()
        follow(lambda s: s["kind"] == "periods" and s["index"] == 1)
        assert page.locator(".allowance-observations tbody tr").count() == 100
        follow(lambda s: s["capture_page"] == 1)
        assert page.locator(".allowance-observations tbody tr").count() == 25
        follow(lambda s: s["capture_order"] == "oldest")
        times = page.locator(".allowance-observations tbody td:first-child").all_text_contents()
        assert "2026-10-31 23:30:00 EDT" in times[0]
        assert times == sorted(times)
        uncertain_open()
        follow(lambda s: s["kind"] == "cross")
        fit = page.locator(".allowance-fit > summary")
        assert fit.count() == 1
        fit.focus()
        fit.press("Enter")
        assert fit.evaluate("e => e.parentElement.open")
        follow(lambda s: s["kind"] == "periods" and s["index"] == 0)
        assert "EST" in page.locator(".allowance-observations").inner_text()
    tables = page.locator(".allowance-observations")
    assert tables.count() == 1
    assert tables.get_by_role("columnheader", name="Reset credits", exact=True).count() == 1
    assert "Live probe" in tables.inner_text() if not dense else "Task snapshot" in tables.inner_text()
    assert page.locator(".allowance-history-item").evaluate_all(
        "es => es.every(e => e.scrollWidth <= e.clientWidth + 1)")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if width == 360:
        region = tables.locator("xpath=..")
        assert region.evaluate("e => e.scrollWidth > e.clientWidth && getComputedStyle(e).overflowX === 'auto'")
        region.focus()
        region.evaluate("e => e.scrollLeft = e.scrollWidth")
        assert region.evaluate("e => e.scrollLeft > 0")
    page.locator(".allowance-history-inspection").scroll_into_view_if_needed()
    page.screenshot(path=str(screenshots / f"{key}-detail.png"))


def _check_current(page, report, variant, screenshots, key):
    page.set_content(report.html)
    summary = page.get_by_text("Probe, coverage, and allowance history", exact=True)
    summary.focus()
    summary.press("Enter")
    periods = page.get_by_role("list", name="Allowance period history")
    current = periods.locator("li").filter(has=page.locator("strong", has_text="Current"))
    assert current.count() == 1
    assert "Opening unobserved" in current.inner_text()
    if variant == "uncertain-current":
        assert "Current · uncertain boundary" in current.inner_text()
    else:
        assert current.locator("strong").inner_text() == "Current"
    if variant == "official-conflicts":
        assert periods.locator("li").count() == 1
        uncertain = page.locator(".allowance-uncertain")
        assert uncertain.locator(":scope > summary").inner_text() == "Uncertain readings (3)"
        uncertain.locator(":scope > summary").focus()
        uncertain.locator(":scope > summary").press("Enter")
        assert uncertain.locator(":scope > ol > li").count() >= 1
    if variant == "lone-current":
        assert "Capture details (1)" in current.inner_text()
        assert "Observed 2026-10-31 to 2026-11-01" not in current.inner_text()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    current.scroll_into_view_if_needed()
    page.screenshot(path=str(screenshots / f"{key}.png"))
