"""Exercise allowance states through the real shared, script-free renderer."""
from copy import deepcopy

from playwright.sync_api import sync_playwright

from allowance_fixture import allowance_fixture
from codex_usage.report_allowance import allowance_css, render_allowance_section
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
                    report["latest_completed"] = None
                for theme in ("day", "night"):
                    for width in (1440, 760, 360):
                        page.set_viewport_size({"width": width, "height": 900})
                        page.set_content(f'<!doctype html><html data-codex-theme="{theme}"><style>{report_css()}{allowance_css()}</style>'
                                         f'<body>{render_allowance_section(report)}</body></html>')
                        assert page.locator("script").count() == 0
                        assert page.get_by_role("heading", name="Plan Allowance", exact=True).is_visible()
                        headline = "Latest window" if state == "insufficient" else "Current · provisional"
                        assert page.get_by_role("heading", name=headline, exact=True).is_visible()
                        assert page.get_by_role("heading", name="Latest completed · qualified").is_visible()
                        assert not page.get_by_text("Last checked:").is_visible()
                        if state == "insufficient":
                            assert page.get_by_text("Insufficient data").count() == 2
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
