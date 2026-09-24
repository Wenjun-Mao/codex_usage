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
from codex_usage.report_theme import report_css


def main():
    count = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            for state in ("qualified", "stale", "unavailable", "partial", "multi-bucket", "insufficient"):
                report = deepcopy(allowance_fixture())
                if state in {"stale", "unavailable", "partial"}:
                    report["status"]["probe_status"] = state
                if state == "unavailable":
                    report["status"]["active_buckets"] = []
                if state == "insufficient":
                    report["qualified"] = []
                    report["windows"] = []
                    report["headline"] = None
                for theme in ("day", "night"):
                    for width in (1440, 760, 360):
                        page.set_viewport_size({"width": width, "height": 900})
                        page.set_content(f'<!doctype html><html data-codex-theme="{theme}"><style>{report_css()}{allowance_css()}</style>'
                                         f'<body>{render_allowance_section(report, timezone=ZoneInfo("America/Toronto"))}</body></html>')
                        assert page.locator("script").count() == 0
                        assert page.get_by_role("heading", name="Plan Allowance", exact=True).is_visible()
                        headline = "Latest window" if state == "insufficient" else "Current · provisional"
                        assert page.get_by_role("heading", name=headline, exact=True).is_visible()
                        assert page.locator(".allowance-value").count() == 1
                        assert not page.get_by_text("Last checked:").is_visible()
                        assert not page.get_by_text("Latest window fit:").is_visible()
                        assert page.locator(".allowance-economic").count() == 1
                        assert page.locator(".allowance-economic").first.evaluate(
                            "e => getComputedStyle(e).borderTopStyle === 'none'"
                        )
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
            print(f"Allowance UI: {count} state/theme/viewport cases passed")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
