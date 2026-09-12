from __future__ import annotations

import argparse
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import Page, sync_playwright

from codex_usage.marketplace_screenshot_validation import validate_screenshot

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DESKTOP_ROOT = REPOSITORY_ROOT / "apps" / "desktop"
USAGE_SCREENSHOT_PATH = (
    REPOSITORY_ROOT / "docs" / "marketplace" / "native-usage-synthetic.png"
)
USAGE_SCREENSHOT_PATHS = {
    ("day", "wide"): REPOSITORY_ROOT
    / "docs"
    / "marketplace"
    / "native-usage-day-wide-synthetic.png",
    ("night", "wide"): USAGE_SCREENSHOT_PATH,
    ("day", "narrow"): REPOSITORY_ROOT
    / "docs"
    / "marketplace"
    / "native-usage-day-narrow-synthetic.png",
    ("night", "narrow"): REPOSITORY_ROOT
    / "docs"
    / "marketplace"
    / "native-usage-night-narrow-synthetic.png",
}
STORAGE_SCREENSHOT_PATH = (
    REPOSITORY_ROOT / "docs" / "marketplace" / "native-storage-synthetic.png"
)
VIEWPORT = {"width": 1440, "height": 900}
NARROW_VIEWPORT = {"width": 760, "height": 900}
PRIVATE_MARKERS = ("/Users/wjmao", "C:\\Users\\wjmao", "OneDrive-Personal")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture deterministic Marketplace images from the native app."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Capture and validate temporary images without changing tracked files.",
    )
    args = parser.parse_args(argv)

    if args.check:
        with TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            _render_capture_and_validate(
                {
                    key: temporary / path.name
                    for key, path in USAGE_SCREENSHOT_PATHS.items()
                },
                temporary / "native-storage.png",
            )
        return 0

    _render_capture_and_validate(USAGE_SCREENSHOT_PATHS, STORAGE_SCREENSHOT_PATH)
    return 0


def _render_capture_and_validate(
    usage_paths: dict[tuple[str, str], Path],
    storage_path: Path,
) -> None:
    _build_frontend()
    with _preview_server() as url:
        capture_marketplace_screenshots(url, usage_paths, storage_path)
    for (_theme, size), path in usage_paths.items():
        validate_screenshot(path, NARROW_VIEWPORT if size == "narrow" else VIEWPORT)
    validate_screenshot(storage_path, VIEWPORT)


def _build_frontend() -> None:
    subprocess.run(
        ["npm", "run", "build"],
        cwd=DESKTOP_ROOT,
        check=True,
    )


@contextmanager
def _preview_server() -> Iterator[str]:
    port = _unused_loopback_port()
    url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [
            "npm",
            "exec",
            "vite",
            "preview",
            "--",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--strictPort",
        ],
        cwd=DESKTOP_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    "native frontend preview exited before becoming ready"
                )
            try:
                with urlopen(url, timeout=0.5) as response:  # noqa: S310
                    if response.status == 200:
                        break
            except (URLError, OSError):
                time.sleep(0.1)
        else:
            raise RuntimeError("native frontend preview did not become ready")
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _unused_loopback_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def capture_marketplace_screenshots(
    url: str,
    usage_paths: dict[tuple[str, str], Path],
    storage_path: Path,
) -> None:
    for usage_path in usage_paths.values():
        usage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(
                viewport=VIEWPORT,
                locale="en-US",
                timezone_id="UTC",
                color_scheme="dark",
            )
            page.goto(url, wait_until="networkidle")
            _wait_for_usage(page)
            page.locator("#usage-range").select_option("all")
            page.wait_for_timeout(150)
            _reject_private_fixture_data(page)
            _exercise_theme_modes(page, view="usage")
            _exercise_usage_chart_controls(page)
            page.frame_locator("#usage-report").locator(".image-activity").evaluate(
                "element => element.scrollIntoView({block: 'start'})"
            )
            page.wait_for_timeout(100)
            for theme in ("day", "night"):
                page.evaluate(
                    "theme => { document.documentElement.dataset.theme = theme; }",
                    theme,
                )
                page.frame_locator("#usage-report").locator("html").evaluate(
                    "(element, theme) => { element.dataset.codexTheme = theme; }",
                    theme,
                )
                for size, viewport in (("wide", VIEWPORT), ("narrow", NARROW_VIEWPORT)):
                    _set_viewport(page, viewport)
                    _validate_layout(page, view="usage", viewport=viewport)
                    page.frame_locator("#usage-report").locator(
                        ".image-activity"
                    ).evaluate("element => element.scrollIntoView({block: 'start'})")
                    page.wait_for_timeout(100)
                    page.screenshot(
                        path=str(usage_paths[(theme, size)]),
                        full_page=False,
                    )

            _set_viewport(page, VIEWPORT)

            page.get_by_role("button", name="Task Storage", exact=True).click()
            _wait_for_storage(page)
            _reject_private_fixture_data(page)
            _exercise_theme_modes(page, view="storage")
            page.screenshot(path=str(storage_path), full_page=False)
        finally:
            browser.close()


def _wait_for_usage(page: Page) -> None:
    page.get_by_role("heading", name="Token Usage", exact=True).wait_for()
    page.get_by_text("Collector active", exact=True).wait_for()
    page.get_by_role("button", name="Capture Usage", exact=True).wait_for()
    page.frame_locator("#usage-report").locator(
        'section[aria-label="Usage summary"]'
    ).wait_for()
    page.get_by_text("Loaded in", exact=False).wait_for()


def _wait_for_storage(page: Page) -> None:
    page.get_by_role("heading", name="Task Storage", exact=True).wait_for()
    page.get_by_role("heading", name="Largest Task Trees", exact=True).wait_for()
    page.get_by_text("Ship native persistent collector", exact=True).wait_for()
    page.get_by_role(
        "button", name="Analyze Ship native persistent collector"
    ).wait_for()


def _set_viewport(page: Page, viewport: dict[str, int]) -> None:
    page.set_viewport_size(viewport)
    page.wait_for_function(
        "width => window.innerWidth === width", arg=viewport["width"]
    )
    page.evaluate(
        "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
    )


def _exercise_theme_modes(page: Page, *, view: str) -> None:
    colors: dict[str, str] = {}
    for theme in ("day", "night"):
        page.evaluate(
            "theme => { document.documentElement.dataset.theme = theme; }",
            theme,
        )
        if view == "usage":
            page.frame_locator("#usage-report").locator("html").evaluate(
                "(element, theme) => { element.dataset.codexTheme = theme; }",
                theme,
            )
        _set_viewport(page, VIEWPORT)
        _validate_layout(page, view=view, viewport=VIEWPORT)
        _set_viewport(page, NARROW_VIEWPORT)
        _validate_layout(page, view=view, viewport=NARROW_VIEWPORT)
        colors[theme] = page.locator("body").evaluate(
            "element => getComputedStyle(element).backgroundColor"
        )
    if colors["day"] == colors["night"]:
        raise RuntimeError(f"{view} day and night themes render the same background")
    _set_viewport(page, VIEWPORT)


def _exercise_usage_chart_controls(page: Page) -> None:
    frame = page.frame_locator("#usage-report")
    role_fill = frame.locator(
        '.role-fill[data-project-key="persona_generators"][data-role="subagent"]'
    )
    model_fill = frame.locator(".mix-fill.luna")
    token_control = frame.locator("#compare-scale-tokens")
    cost_control = frame.locator("#compare-scale-cost")
    week_control = frame.locator("#cost-trend-week")
    month_control = frame.locator("#cost-trend-month")
    project_economics = frame.locator(".project-economics-project").first
    token_accounting = frame.locator(".token-accounting").first
    image_activity = frame.locator(".image-activity")

    if not image_activity.is_visible():
        raise RuntimeError("usage fixture is missing Image Generation reporting")
    image_activity.get_by_role(
        "heading", name="Image Generation", exact=True
    ).wait_for()
    if "Separate accounting" not in image_activity.inner_text():
        raise RuntimeError(
            "image reporting fixture lost its separate-accounting disclosure"
        )

    for theme in ("day", "night"):
        page.evaluate(
            "theme => { document.documentElement.dataset.theme = theme; }",
            theme,
        )
        frame.locator("html").evaluate(
            "(element, theme) => { element.dataset.codexTheme = theme; }",
            theme,
        )
        for viewport in (VIEWPORT, NARROW_VIEWPORT):
            _set_viewport(page, viewport)
            _exercise_disclosure(
                project_economics,
                "Project Economics details",
            )
            _exercise_disclosure(
                token_accounting,
                "Token Accounting",
            )
            if not week_control.is_checked():
                raise RuntimeError("all-history cost trend did not default to Week")
            if not frame.locator(".cost-week-panel").is_visible():
                raise RuntimeError("weekly cost panel is not visible by default")
            week_control.focus()
            week_control.press("ArrowRight")
            if (
                not month_control.is_checked()
                or not frame.locator(".cost-month-panel").is_visible()
            ):
                raise RuntimeError("cost trend keyboard did not select Month")
            month_control.focus()
            month_control.press("ArrowLeft")
            if not week_control.is_checked():
                raise RuntimeError("cost trend keyboard did not restore Week")

            for selector in (
                ".cost-week-panel .trend-bar:first-child",
                ".cost-week-panel .trend-bar:last-child",
            ):
                bar = frame.locator(selector)
                bar.focus()
                tooltip_box = bar.locator(".trend-tooltip").bounding_box()
                frame_box = page.locator("#usage-report").bounding_box()
                if tooltip_box is None or frame_box is None:
                    raise RuntimeError(
                        "cost trend tooltip containment probe is missing"
                    )
                if (
                    tooltip_box["x"] < frame_box["x"] - 1
                    or tooltip_box["x"] + tooltip_box["width"]
                    > frame_box["x"] + frame_box["width"] + 1
                ):
                    raise RuntimeError(
                        "cost trend edge tooltip escapes the report viewport: "
                        f"tooltip={tooltip_box}, frame={frame_box}, selector={selector}, "
                        f"viewport={viewport}"
                    )

            if not token_control.is_checked():
                raise RuntimeError("usage fixture did not start from the token scale")
            token_box = role_fill.bounding_box()
            model_token_box = model_fill.bounding_box()
            if token_box is None:
                raise RuntimeError(
                    "usage fixture is missing the project role scale probe"
                )
            if model_token_box is None:
                raise RuntimeError("usage fixture is missing the Model Mix scale probe")

            token_control.focus()
            token_control.press("ArrowRight")
            if not cost_control.is_checked():
                raise RuntimeError("usage fixture keyboard did not select API cost")
            cost_box = role_fill.bounding_box()
            if cost_box is None or abs(token_box["width"] - cost_box["width"]) < 4:
                raise RuntimeError(
                    "usage fixture API cost scale did not change bar geometry"
                )
            model_cost_box = model_fill.bounding_box()
            if (
                model_cost_box is None
                or abs(model_token_box["width"] - model_cost_box["width"]) < 4
            ):
                raise RuntimeError(
                    "usage fixture API cost scale did not change Model Mix geometry"
                )

            tracks = frame.locator(".mix-track")
            track_boxes = [
                tracks.nth(index).bounding_box() for index in range(tracks.count())
            ]
            if not track_boxes or any(box is None for box in track_boxes):
                raise RuntimeError("usage fixture is missing Model Mix tracks")
            first = track_boxes[0]
            assert first is not None
            if any(
                abs(box["x"] - first["x"]) > 1 or abs(box["width"] - first["width"]) > 1
                for box in track_boxes[1:]
                if box is not None
            ):
                raise RuntimeError(
                    "usage fixture Model Mix tracks do not share equal bounds"
                )

            cost_control.focus()
            cost_control.press("ArrowLeft")
            if not token_control.is_checked():
                raise RuntimeError("usage fixture keyboard did not restore Tokens")

    _set_viewport(page, VIEWPORT)


def _exercise_disclosure(disclosure, label: str) -> None:
    disclosure.evaluate("element => { element.open = false; }")
    summary = disclosure.locator("summary")
    summary.focus()
    summary.press("Enter")
    if not disclosure.evaluate("element => element.open"):
        raise RuntimeError(f"usage fixture keyboard did not expand {label}")


def _reject_private_fixture_data(page: Page) -> None:
    text = page.locator("body").inner_text()
    for marker in PRIVATE_MARKERS:
        if marker.casefold() in text.casefold():
            raise RuntimeError(f"native fixture leaked a private marker: {marker}")


def _validate_layout(page: Page, *, view: str, viewport: dict[str, int]) -> None:
    metrics = page.evaluate(
        """
        () => {
          const selectors = ['html', 'body', '#app', '.app-shell', '.main-shell', '.topbar', '.view-heading', '.view-filters'];
          return selectors.map(selector => {
            const element = document.querySelector(selector);
            if (!element) throw new Error(`Missing ${selector}`);
            const rect = element.getBoundingClientRect();
            return {selector, clientWidth: element.clientWidth, scrollWidth: element.scrollWidth,
                    left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom};
          });
        }
        """
    )
    for metric in metrics:
        if metric["scrollWidth"] > metric["clientWidth"] + 1:
            raise RuntimeError(
                f"{view} overflows horizontally at {viewport['width']}px: "
                f"{metric['selector']} {metric['scrollWidth']} > {metric['clientWidth']}"
            )
        if metric["left"] < -1 or metric["right"] > viewport["width"] + 1:
            raise RuntimeError(
                f"{view} escapes the viewport at {viewport['width']}px: "
                f"{metric['selector']}"
            )

    _assert_no_overlap(page, ".capture-summary", ".button-capture", view, viewport)
    contextual_controls = (
        ("#usage-project-filter", "#usage-reload")
        if view == "usage"
        else ("#storage-project-filter", "#storage-refresh")
    )
    for selector in contextual_controls:
        _assert_within_viewport(page, selector, view, viewport)
    if view == "usage":
        frame = page.frame_locator("#usage-report")
        report_metrics = frame.locator("html").evaluate(
            "element => ({clientWidth: element.clientWidth, scrollWidth: element.scrollWidth})"
        )
        if report_metrics["scrollWidth"] > report_metrics["clientWidth"] + 1:
            raise RuntimeError(
                f"usage report overflows at {viewport['width']}px: "
                f"{report_metrics['scrollWidth']} > {report_metrics['clientWidth']}"
            )


def _assert_within_viewport(
    page: Page,
    selector: str,
    view: str,
    viewport: dict[str, int],
) -> None:
    box = page.locator(selector).bounding_box()
    if box is None:
        raise RuntimeError(f"{view} is missing required control {selector}")
    if (
        box["x"] < -1
        or box["x"] + box["width"] > viewport["width"] + 1
        or box["y"] < -1
        or box["y"] + box["height"] > viewport["height"] + 1
    ):
        raise RuntimeError(
            f"{view} control {selector} escapes the {viewport['width']}px viewport"
        )


def _assert_no_overlap(
    page: Page,
    first_selector: str,
    second_selector: str,
    view: str,
    viewport: dict[str, int],
) -> None:
    first = page.locator(first_selector).bounding_box()
    second = page.locator(second_selector).bounding_box()
    if first is None or second is None:
        raise RuntimeError(f"{view} is missing a required top-bar control")
    separated = (
        first["x"] + first["width"] <= second["x"]
        or second["x"] + second["width"] <= first["x"]
        or first["y"] + first["height"] <= second["y"]
        or second["y"] + second["height"] <= first["y"]
    )
    if not separated:
        raise RuntimeError(f"{view} top-bar controls overlap at {viewport['width']}px")


if __name__ == "__main__":
    raise SystemExit(main())
