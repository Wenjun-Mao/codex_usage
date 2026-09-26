"""Exercise production report allowance and meter rendering across browsers."""
from copy import deepcopy
from io import BytesIO
import re
from zoneinfo import ZoneInfo

from PIL import Image
from playwright.sync_api import sync_playwright

from allowance_fixture import allowance_fixture
from codex_usage.allowance_queries import allowance_history
from codex_usage.report_allowance import (
    allowance_css,
    duration_label,
    render_allowance_section,
)
from codex_usage.report_theme import report_css


THEMES = {
    "day": ("day", "", ""),
    "night": ("night", "", ""),
    "vscode": (
        "auto",
        "vscode-dark",
        "--vscode-editor-background:#161b22;--vscode-sideBar-background:#202832;"
        "--vscode-editor-foreground:#f4f7fa;--vscode-descriptionForeground:#b8c0cc;"
        "--vscode-panel-border:#51606f;--vscode-textLink-foreground:#d28dff;",
    ),
}
BROWSERS = ("chromium", "webkit", "firefox")
VALUES = (0, 17, 83, 100)
def _document(report, theme_name):
    html_theme, body_class, body_style = THEMES[theme_name]
    return (
        f'<!doctype html><html data-codex-theme="{html_theme}"><style>'
        f'{report_css()}{allowance_css()}</style>'
        f'<body class="{body_class}" style="{body_style}">'
        f'{render_allowance_section(report, timezone=ZoneInfo("America/Toronto"))}'
        "</body></html>"
    )


def _report_for_state(state):
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
    return report


def _check_report_matrix(page, browser_name):
    count = 0
    history_colors = {}
    for state in (
        "qualified",
        "previous-window",
        "stale",
        "unavailable",
        "partial",
        "multi-bucket",
        "insufficient",
    ):
        report = _report_for_state(state)
        for theme in ("day", "night"):
            for width in (1440, 760, 360):
                page.set_viewport_size({"width": width, "height": 900})
                page.set_content(_document(report, theme))
                _check_report_content(page, report, state, theme, history_colors)
                count += 1
    assert history_colors["day"] != history_colors["night"]
    return count


def _check_report_content(page, report, state, theme, history_colors):
    assert page.locator("script").count() == 0
    assert page.get_by_role("heading", name="Plan Allowance", exact=True).is_visible()
    headline = (
        "Latest window"
        if state == "insufficient"
        else "Previous window"
        if state == "previous-window"
        else "Current · provisional"
    )
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
        meter = page.get_by_role("meter", name=f"{identity} percentage remaining")
        assert meter.count() == 1
        used = bucket["used_percent"]
        remaining = 100 - used
        assert meter.get_attribute("value") == f"{remaining:g}"
        assert meter.get_attribute("aria-valuetext") == f"{remaining:g}% remaining"
        assert page.locator(".allowance-bucket-usage").filter(
            has_text=f"{used:g}% used · {100 - used:g}% remaining"
        ).count() == 1
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
    page.keyboard.press("Tab")
    focus = diagnostics_summary.evaluate(
        "e => { const probe = document.createElement('span'); probe.style.color = 'var(--accent)'; e.append(probe); "
        "const accent = getComputedStyle(probe).color; probe.remove(); return {active: document.activeElement === e, "
        "visible: e.matches(':focus-visible'), outlineStyle: getComputedStyle(e).outlineStyle, "
        "outlineWidth: getComputedStyle(e).outlineWidth, outlineColor: getComputedStyle(e).outlineColor, accent}; }"
    )
    assert focus["active"] and focus["visible"]
    assert focus["outlineStyle"] == "solid" and focus["outlineWidth"] == "2px"
    assert focus["outlineColor"] == focus["accent"]
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
        assert diagnostics.get_by_text("No valid priced window estimate yet.").is_visible()
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


def _css_rgb(value):
    if re.fullmatch(r"#[\da-fA-F]{3}", value):
        return tuple(int(channel * 2, 16) for channel in value[1:])
    if re.fullmatch(r"#[\da-fA-F]{6}", value):
        return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))
    match = re.fullmatch(
        r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*[\d.]+)?\s*\)",
        value,
    )
    assert match, f"expected computed RGB color, got {value!r}"
    return tuple(int(channel) for channel in match.groups())


def _contrast_ratio(first, second):
    def luminance(color):
        linear = []
        for channel in color:
            srgb = channel / 255
            linear.append(srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4)
        return sum(weight * channel for weight, channel in zip((0.2126, 0.7152, 0.0722), linear, strict=True))

    bright, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (bright + 0.05) / (dark + 0.05)


def _check_meter_visuals(page, browser_name):
    for theme in THEMES:
        for used in VALUES:
            remaining = 100 - used
            report = deepcopy(allowance_fixture())
            report["status"]["active_buckets"] = [
                dict(report["status"]["active_buckets"][0], used_percent=used)
            ]
            page.set_viewport_size({"width": 360, "height": 240})
            page.set_content(_document(report, theme))
            meter = page.get_by_role(
                "meter", name="codex · 7 days percentage remaining"
            )
            assert meter.count() == 1
            assert meter.get_attribute("min") == "0"
            assert meter.get_attribute("max") == "100"
            assert meter.get_attribute("value") == str(remaining)
            assert meter.get_attribute("aria-valuetext") == f"{remaining}% remaining"
            assert page.locator(".allowance-bucket-usage").inner_text() == (
                f"{used}% used · {100 - used}% remaining"
            )
            styles = meter.evaluate(
                "e => ({"
                "native: e.localName === 'meter' && e.getAttribute('role') === null && e.tabIndex === -1, "
                "appearance: getComputedStyle(e).appearance, width: getComputedStyle(e).width, "
                "height: getComputedStyle(e).height, track: getComputedStyle(e).backgroundColor, "
                "accent: getComputedStyle(e).color, "
                "text: getComputedStyle(e.parentElement.querySelector('.allowance-bucket-usage')).color, "
                "page: getComputedStyle(document.body).backgroundColor})"
            )
            assert styles["native"]
            assert styles["appearance"] == "none"
            accent_rgb = _css_rgb(styles["accent"])
            track_rgb = _css_rgb(styles["track"])
            page_rgb = _css_rgb(styles["page"])
            assert _contrast_ratio(accent_rgb, track_rgb) >= 3
            assert _contrast_ratio(track_rgb, page_rgb) < _contrast_ratio(accent_rgb, page_rgb)
            assert _contrast_ratio(_css_rgb(styles["text"]), page_rgb) >= 4.5
            assert _contrast_ratio(accent_rgb, page_rgb) >= 3

            # Meter value pseudo styles are not reflected consistently by
            # getComputedStyle; sample the actual engine-painted pixels.
            image = Image.open(BytesIO(meter.screenshot())).convert("RGB")
            center_row = [image.getpixel((x, image.height // 2)) for x in range(image.width)]
            colored_fraction = sum(pixel == accent_rgb for pixel in center_row) / image.width
            assert abs(colored_fraction - remaining / 100) <= 0.04, (
                f"{browser_name}/{theme} meter at {used}% has {colored_fraction:.3f} "
                "accent fill across its center row; expected remaining allowance"
            )


def main():
    total = 0
    with sync_playwright() as playwright:
        for browser_name in BROWSERS:
            browser = getattr(playwright, browser_name).launch()
            try:
                page = browser.new_page()
                total += _check_report_matrix(page, browser_name)
                _check_meter_visuals(page, browser_name)
            finally:
                browser.close()
    print(
        f"Allowance UI: {total} state/theme/viewport cases and "
        f"{len(BROWSERS) * len(THEMES) * len(VALUES)} meter visual cases "
        f"passed across {', '.join(BROWSERS)}"
    )


if __name__ == "__main__":
    main()
