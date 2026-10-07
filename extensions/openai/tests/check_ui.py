"""Exercise the local SDK harness; never claim this as actual-host acceptance."""

from pathlib import Path
import sys

from playwright.sync_api import expect, sync_playwright

OUTPUT = Path(__file__).resolve().parents[3] / "output" / "playwright" / "openai-probe"


def check_controls(page):
    ui = page.frame_locator("#probe")
    expect(ui.locator("#connection")).to_have_text("Connected")
    expect(ui.locator("#cost")).to_have_text("US$120.40")
    expect(ui.locator("#tokens")).to_have_text("133,000,000")
    expect(ui.get_by_role("meter")).to_have_attribute("aria-valuetext", "83% remaining")
    assert ui.get_by_role("meter").evaluate("el => el.value") == 83
    assert ui.locator("button svg").count() == 3
    page.evaluate("window.probeHost.sendResult('yesterday', 'demo-b')")
    expect(ui.locator("#cost")).to_have_text("US$3.84")
    expect(ui.locator("#period")).to_have_value("yesterday")
    expect(ui.locator("#project")).to_have_value("demo-b")
    ui.get_by_role("combobox", name="Period", exact=True).select_option("today")
    ui.get_by_role("combobox", name="Project", exact=True).select_option("all")
    expect(ui.locator("#cost")).to_have_text("US$17.20")
    ui.get_by_role("combobox", name="Project", exact=True).select_option("demo-b")
    expect(ui.locator("#cost")).to_have_text("US$4.80")
    expect(ui.locator(".project-row")).to_have_count(1)
    page.evaluate("window.probeHost.sendResult('7d', 'all')")
    page.wait_for_timeout(50)
    expect(ui.locator("#period")).to_have_value("today")
    expect(ui.locator("#project")).to_have_value("demo-b")
    expect(ui.locator("#cost")).to_have_text("US$4.80")
    ui.get_by_role("radio", name="Tokens", exact=True).check()
    expect(ui.locator(".value")).to_have_text("8,000,000")
    ui.get_by_role("button", name="Ask about this selection").click()
    page.wait_for_function("window.probeHost.state.messages.length === 1")
    context = page.evaluate("window.probeHost.state.contexts[0]")
    assert context["structuredContent"] == {
        "source": "synthetic",
        "scope": {"period": "today", "project": "demo-b", "timezone": "America/Toronto"},
    }
    ui.get_by_role("button", name="Fullscreen").click()
    page.wait_for_function("window.probeHost.state.modes[0] === 'fullscreen'")

    page.evaluate("window.probeHost.state.fail = true")
    ui.get_by_role("button", name="Reload", exact=True).click()
    expect(ui.locator("#connection")).to_have_text("Unavailable")
    expect(ui.get_by_role("alert")).to_be_visible()
    page.evaluate("window.probeHost.state.fail = false")
    ui.get_by_role("button", name="Reload", exact=True).click()
    expect(ui.locator("#connection")).to_have_text("Connected")
    expect(ui.get_by_role("alert")).to_be_hidden()

    page.evaluate("window.probeHost.state.delay = true")
    ui.get_by_role("combobox", name="Period", exact=True).select_option("yesterday")
    expect(ui.locator("#cost")).to_have_text("US$3.84")
    ui.get_by_role("combobox", name="Period", exact=True).select_option("today")
    ui.get_by_role("combobox", name="Period", exact=True).select_option("30d")
    expect(ui.locator("#cost")).to_have_text("US$144.00")
    page.wait_for_timeout(200)
    expect(ui.locator("#period")).to_have_value("30d")
    expect(ui.locator("#cost")).to_have_text("US$144.00")
    page.evaluate("window.probeHost.state.delay = false")
    return ui


def check_layout(page, ui, browser_name):
    ui.get_by_role("combobox", name="Project", exact=True).select_option("all")
    expect(ui.locator("#cost")).to_have_text("US$516.00")
    page.locator("body").evaluate("el => el.style.background = '#0d0d0d'")
    ui.locator("body").evaluate(
        "el => el.style.setProperty('background', 'transparent', 'important')"
    )
    for theme in ("day", "night"):
        ui.get_by_role("combobox", name="Theme", exact=True).select_option(theme)
        assert ui.locator("main").evaluate("el => getComputedStyle(el).backgroundColor") == (
            "rgb(255, 255, 255)" if theme == "day" else "rgb(16, 21, 24)"
        )
        for width in (1440, 390, 360):
            page.set_viewport_size({"width": width, "height": 950})
            assert ui.locator("html").evaluate("el => el.scrollWidth <= el.clientWidth")
            assert ui.locator(".totals strong").evaluate_all(
                "els => els.every(el => el.scrollWidth <= el.clientWidth)"
            )
            assert ui.locator(".project-row span.value").evaluate_all(
                "els => els.every(el => el.scrollWidth <= el.clientWidth)"
            )
            expect(ui.locator("#cost")).to_be_visible()
            page.screenshot(path=str(OUTPUT / f"{browser_name}-{theme}-{width}.png"))
    ui.get_by_role("combobox", name="Theme", exact=True).select_option("auto")
    page.evaluate("window.probeHost.bridge.setHostContext({theme:'dark'})")
    expect(ui.locator("html")).to_have_attribute("data-theme", "night")
    ui.get_by_role("button", name="Reload", exact=True).focus()
    ui.get_by_role("button", name="Reload", exact=True).press("Enter")
    expect(ui.locator("#connection")).to_have_text("Connected")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        for name in ("chromium", "webkit", "firefox"):
            browser = getattr(playwright, name).launch()
            page = browser.new_page(viewport={"width": 1440, "height": 950})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(sys.argv[1])
            ui = check_controls(page)
            check_layout(page, ui, name)
            assert not errors, errors
            browser.close()
            print(f"{name}: bridge, controls, races, errors, themes, and 3 widths passed")


if __name__ == "__main__":
    main()
