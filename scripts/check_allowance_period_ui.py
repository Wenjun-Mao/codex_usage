"""Mandatory period-history cases within the allowance visual qualification."""
from pathlib import Path
from tempfile import TemporaryDirectory

from allowance_period_fixture import allowance_period_fixture, dense_period_fixture
from verification.visual_cases import PERIOD_HISTORY_STATES, THEMES, WIDTHS, identity


def check_period_matrix(page, engine, audit, document):
    count = 0
    screenshots = audit.output / "period-history"
    screenshots.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="allowance-period-ui-") as directory:
        for scenario in PERIOD_HISTORY_STATES:
            report = (allowance_period_fixture if scenario == "period-history" else dense_period_fixture)(Path(directory))
            for theme in THEMES:
                contents = document(report, theme)
                audit.document(f"{scenario}-{theme}", contents)
                for width in WIDTHS:
                    case = identity(engine, scenario, theme, width)
                    with audit.case(page, case):
                        _check_period_view(page, contents, scenario, width, screenshots,
                                           f"{engine}-{scenario}-{theme}-{width}")
                    count += 1
    return count


def _check_period_view(page, contents, scenario, width, screenshots, key):
    page.set_viewport_size({"width": width, "height": 900})
    page.set_content(contents)
    assert page.locator("script").count() == 0
    diagnostics = page.get_by_text("Probe, coverage, and allowance history", exact=True)
    diagnostics.focus()
    diagnostics.press("Enter")
    periods = page.get_by_role("list", name="Allowance period history")
    dense = scenario == "period-history-dense"
    assert periods.locator(":scope > li").count() == (12 if dense else 2)
    uncertain = page.locator(".allowance-uncertain")
    assert not uncertain.evaluate("e => e.open")
    assert uncertain.locator(":scope > summary").inner_text() == (
        "Uncertain readings (79)" if dense else "Uncertain readings (4)")
    assert not page.locator(".allowance-observations").first.is_visible()
    periods.scroll_into_view_if_needed()
    page.screenshot(path=str(screenshots / f"{key}-compact.png"))
    uncertain.locator(":scope > summary").focus()
    uncertain.locator(":scope > summary").press("Enter")
    assert uncertain.locator(":scope > ol > li").count() == (12 if dense else 2)
    if dense:
        assert "41 observed periods; newest 12 shown" in page.locator(".allowance-history-count").inner_text()
    else:
        assert "Observed 2026-10-31 to 2026-11-01" in periods.inner_text()
        assert "Coverage ended" in periods.inner_text() and "Current" in periods.inner_text()
        cross = page.get_by_text("Uncertain / cross-boundary fits (1)", exact=True)
        cross.focus()
        cross.press("Enter")
        assert cross.evaluate("e => e.parentElement.open")
    for summary in page.locator("summary").all():
        if summary.is_visible() and "Capture details" in summary.inner_text():
            summary.focus()
            summary.press("Enter")
    tables = page.locator(".allowance-observations")
    assert tables.count() == (24 if dense else 4)
    if not dense:
        assert page.locator(".allowance-observations tbody tr").count() == 105
        rows = tables.all_text_contents()
        assert any("EDT" in row for row in rows) and any("EST" in row for row in rows)
        assert tables.first.get_by_role("columnheader", name="Reset credits", exact=True).count() == 1
        assert "Most recent 100 of 125" in page.locator(".plan-allowance").inner_text()
        fit_summaries = page.locator(".allowance-fit > summary")
        assert fit_summaries.count() == 2
        for summary in fit_summaries.all():
            assert summary.is_visible()
            summary.focus()
            summary.press("Enter")
            assert summary.evaluate("e => e.parentElement.open")
    assert page.locator(".allowance-history-item").evaluate_all(
        "es => es.every(e => e.scrollWidth <= e.clientWidth + 1)")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if width == 360:
        table = tables.first
        region = table.locator("xpath=..")
        assert region.evaluate("e => e.scrollWidth > e.clientWidth && getComputedStyle(e).overflowX === 'auto'")
        region.focus()
        region.evaluate("e => e.scrollLeft = e.scrollWidth")
        assert region.evaluate("e => e.scrollLeft > 0")
    periods.scroll_into_view_if_needed()
    page.screenshot(path=str(screenshots / f"{key}-detail.png"))
