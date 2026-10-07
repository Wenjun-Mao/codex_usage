"""Disposable bridge checks; not actual ChatGPT/Codex host acceptance."""
from pathlib import Path
import sys

from playwright.sync_api import expect, sync_playwright

OUTPUT = Path(__file__).resolve().parents[3] / "output" / "playwright" / "openai-companion"


def check(page):
    ui = page.frame_locator("#companion")
    expect(ui.locator("#connection")).to_have_text("Connected")
    expect(ui.locator("#categories table")).to_be_visible()
    expect(ui.locator("#buckets meter")).to_have_attribute("aria-valuetext", "80% remaining")
    assert ui.locator("#buckets meter").evaluate("e => e.value") == 80
    expect(ui.locator("#breakdown > .table-scroll > table")).to_be_visible()
    assert page.evaluate("window.companionHost.state.requests.every(r => !['capture_usage','analyze_storage_tree'].includes(r.name))")
    page.evaluate("window.companionHost.sendResult('yesterday')")
    expect(ui.locator("#period")).to_have_value("yesterday")
    expect(ui.locator("#daily")).to_be_hidden()
    ui.locator("#period").select_option("today")
    expect(ui.locator("#connection")).to_have_text("Connected")
    expect(ui.locator("#daily")).to_be_hidden()
    ui.locator("#dimension").select_option("model")
    expect(ui.locator("#breakdown")).to_contain_text("gpt-6-sol")
    ui.get_by_role("radio", name="Tokens", exact=True).check()
    expect(ui.locator("#connection")).to_have_text("Connected")
    ui.locator("#ask").click()
    page.wait_for_function("window.companionHost.state.contexts.length === 1")
    context = page.evaluate("window.companionHost.state.contexts[0]")
    assert set(context["structuredContent"]) == {"scope", "view"}
    ui.locator("#expand").click()
    page.wait_for_function("window.companionHost.state.modes[0] === 'fullscreen'")
    ui.locator("#capture").click()
    expect(ui.locator("dialog")).to_be_visible()
    ui.get_by_role("button", name="Cancel", exact=True).click()
    assert page.evaluate("window.companionHost.state.requests.filter(r => r.name === 'capture_usage').length") == 0
    ui.locator("#capture").click()
    ui.get_by_role("button", name="Confirm", exact=True).click()
    page.wait_for_function("window.companionHost.state.requests.some(r => r.name === 'capture_usage')")
    expect(ui.locator("#connection")).to_have_text("Connected")
    ui.locator("#storage-tab").click()
    expect(ui.locator("#trees table")).to_be_visible()
    ui.get_by_role("button", name="Analyze", exact=True).first.click()
    ui.get_by_role("button", name="Confirm", exact=True).click()
    expect(ui.locator("#job-state")).to_have_text("queued")
    ui.locator("#cancel").click()
    expect(ui.locator("#job-state")).to_contain_text("cancelled")
    ui.locator("#usage-tab").click()
    expect(ui.locator("#connection")).to_have_text("Connected")
    page.evaluate("window.companionHost.state.fail = true")
    ui.locator("#reload").click()
    expect(ui.locator("#connection")).to_have_text("Unavailable")
    expect(ui.locator("#ask")).to_be_disabled()
    page.evaluate("window.companionHost.state.fail = false; window.companionHost.state.skew = true")
    ui.locator("#reload").click()
    expect(ui.locator("#error")).to_contain_text("consistent revision")
    page.evaluate("window.companionHost.state.skew = false; window.companionHost.state.delay = true")
    ui.locator("#period").select_option("today")
    ui.locator("#period").select_option("30d")
    expect(ui.locator("#connection")).to_have_text("Connected")
    page.wait_for_timeout(200)
    expect(ui.locator("#period")).to_have_value("30d")
    expect(ui.locator("#daily")).to_be_visible()
    page.evaluate("window.companionHost.state.delay = false")
    return ui


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        for name in ("chromium", "webkit", "firefox"):
            browser = getattr(p, name).launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1400})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(sys.argv[1])
            ui = check(page)
            page.locator("body").evaluate("e => e.style.background = '#0d0d0d'")
            ui.locator("body").evaluate(
                "e => e.style.setProperty('background', 'transparent', 'important')"
            )
            for theme in ("day", "night"):
                ui.locator("#theme").select_option(theme)
                assert ui.locator("main").evaluate("e => getComputedStyle(e).backgroundColor") == (
                    "rgb(255, 255, 255)" if theme == "day" else "rgb(16, 21, 24)"
                )
                for width in (1440, 390, 360):
                    page.set_viewport_size({"width": width, "height": 1400})
                    assert ui.locator("html").evaluate("e => e.scrollWidth <= e.clientWidth")
                    assert ui.locator(".summary-grid strong").evaluate_all("els => els.every(e => e.scrollWidth <= e.clientWidth)")
                    page.screenshot(path=str(OUTPUT / f"{name}-{theme}-{width}.png"))
            assert not errors, errors
            browser.close()
            print(f"{name}: views, scopes, actions, context, races, snapshot consistency, errors and 6 layouts passed")


if __name__ == "__main__":
    main()
