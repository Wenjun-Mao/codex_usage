"""Exercise allowance states through the real shared, script-free renderer."""
from copy import deepcopy
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

from allowance_fixture import allowance_fixture
from codex_usage.report_allowance import (
    allowance_css,
    duration_label,
    render_allowance_section,
)
from codex_usage.allowance_queries import allowance_history
from codex_usage.report_theme import report_css


def main():
    count = 0
    history_colors = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            for state in ("qualified", "previous-window", "stale", "unavailable", "partial", "multi-bucket", "insufficient"):
                report = deepcopy(allowance_fixture())
                if state == "previous-window":
                    latest = report["windows"][-1]
                    latest["estimate"].update(confidence="insufficient", value=None, span=9, bins=5)
                    for point, used in zip(latest["points"], (0, 2, 5, 7, 9), strict=True):
                        point["used_percent"] = used
                    report["status"]["active_buckets"][0]["used_percent"] = 9
                    report["headline"] = report["windows"][-2]
                    report["headline_previous"] = True
                    report["history"] = allowance_history(report["windows"])
                if state in {"stale", "unavailable", "partial"}:
                    report["status"]["probe_status"] = state
                if state == "unavailable":
                    report["status"]["active_buckets"] = []
                if state == "insufficient":
                    report["qualified"] = []
                    report["windows"] = []
                    report["headline"] = None
                    report["headline_previous"] = False
                    report["history"] = []
                for theme in ("day", "night"):
                    for width in (1440, 760, 360):
                        page.set_viewport_size({"width": width, "height": 900})
                        page.set_content(f'<!doctype html><html data-codex-theme="{theme}"><style>{report_css()}{allowance_css()}</style>'
                                         f'<body>{render_allowance_section(report, timezone=ZoneInfo("America/Toronto"))}</body></html>')
                        assert page.locator("script").count() == 0
                        assert page.get_by_role("heading", name="Plan Allowance", exact=True).is_visible()
                        headline = ("Latest window" if state == "insufficient" else
                                    "Previous window" if state == "previous-window" else
                                    "Current · provisional")
                        assert page.get_by_role("heading", name=headline, exact=True).is_visible()
                        assert page.locator(".allowance-value").count() == 1
                        assert not page.get_by_text("Last checked:").is_visible()
                        assert not page.get_by_text("Latest window fit:").is_visible()
                        assert page.locator(".allowance-economic").count() == 1
                        assert page.locator(".allowance-economic").first.evaluate(
                            "e => getComputedStyle(e).borderTopStyle === 'none'"
                        )
                        if state == "previous-window":
                            summary_text = page.locator(".allowance-economic").inner_text()
                            assert "Observed 2026-08-22–2026-08-28" in summary_text
                            assert "$1,260.00" in summary_text
                            assert "2026-08-29" not in summary_text
                        assert page.get_by_role("meter").count() == len(report["status"]["active_buckets"])
                        for bucket in report["status"]["active_buckets"]:
                            identity = f'{bucket["limit_id"]} · {duration_label(bucket["duration_minutes"])}'
                            assert page.get_by_role("meter", name=f"{identity} percentage used").count() == 1
                        assert page.locator(".allowance-bucket-summary").evaluate_all(
                            "elements => elements.every(element => { const rects = Array.from(element.children, child => child.getBoundingClientRect()); "
                            "if (element.scrollWidth > element.clientWidth + 1) return false; "
                            "return rects.every((left, index) => rects.slice(index + 1).every(right => "
                            "left.right <= right.left + 1 || right.right <= left.left + 1 || "
                            "left.bottom <= right.top + 1 || right.bottom <= left.top + 1)); })"
                        )
                        if report["status"]["active_buckets"]:
                            assert "EDT (UTC−04:00)" in page.locator(".allowance-bucket-reset").first.inner_text()
                        diagnostics = page.locator("details").filter(
                            has_text="Probe, coverage, and allowance history"
                        )
                        assert diagnostics.count() == 1
                        diagnostics_summary = diagnostics.locator("summary")
                        diagnostics_summary.focus()
                        diagnostics_summary.press("Enter")
                        assert diagnostics.evaluate("e => e.open")
                        assert diagnostics.locator("details").count() == 0
                        if report["history"]:
                            history = diagnostics.locator(".allowance-history")
                            assert history.count() == 1
                            assert history.locator("li").count() == min(12, len(report["history"]))
                            assert history.locator("li").first.inner_text().startswith("codex · pro · 7 days")
                            assert history.evaluate("e => e.scrollWidth <= e.clientWidth")
                            if state == "previous-window":
                                assert history.locator("li").first.inner_text().find("2026-08-29") == -1
                                assert diagnostics.get_by_text("Previous window fit:").is_visible()
                            history_colors[theme] = diagnostics.locator(
                                ".allowance-history-meta"
                            ).first.evaluate("e => getComputedStyle(e).color")
                        else:
                            assert diagnostics.get_by_text(
                                "No valid priced window estimate yet."
                            ).is_visible()
                        if state == "insufficient":
                            assert page.get_by_text("Insufficient data").count() == 1
                        summary = page.locator("summary", has_text="Reset windows and capture details")
                        summary.focus()
                        summary.press("Enter")
                        assert summary.evaluate("e => e.parentElement.open")
                        if report["windows"]:
                            window = page.locator(".allowance-window summary").first
                            window.focus()
                            window.press("Enter")
                            capture = page.locator(".allowance-window").first.locator("details summary")
                            capture.focus()
                            capture.press("Enter")
                            assert capture.evaluate("e => e.parentElement.open")
                        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                        count += 1
            assert history_colors["day"] != history_colors["night"]
            print(f"Allowance UI: {count} state/theme/viewport cases passed")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
