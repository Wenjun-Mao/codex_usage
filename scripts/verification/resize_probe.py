"""Compare restored resize state with fresh navigation; not a qualifying UI gate."""
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from .breakdown_layout import SNAPSHOT, assert_layout
from .visual_cases import BREAKDOWN_SCENARIOS, ENGINES, THEMES, WIDTHS, identity

STATE = """() => ({focus: document.activeElement.tagName, scroll: [scrollX, scrollY],
    details: [...document.querySelectorAll('details')].map(e => e.getAttribute('open')),
    hovered: [...document.querySelectorAll(':hover')].map(e => [e.tagName, e.getAttribute('class')])})"""
RESET = """state => {
    document.activeElement?.blur();
    [...document.querySelectorAll('details')].forEach((e, i) => {
        if (state.details[i] === null) e.removeAttribute('open'); else e.setAttribute('open', state.details[i]);
    });
    window.scrollTo(...state.scroll);
}"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    views = json.loads((args.documents / "evidence.json").read_text())["views"]
    states = {view["scenario"]: view["state"] for view in views}
    result = {"synthetic_only": True, "status": "incomplete", "comparisons": [],
        "scope": "Fresh versus resize DOM/layout, focus, pointer, scroll and disclosure; not pixel or native proof"}
    try:
        with sync_playwright() as playwright:
            for engine in ENGINES:
                browser = getattr(playwright, engine).launch()
                context = browser.new_context(java_script_enabled=False)
                try:
                    reference, resized = context.new_page(), context.new_page()
                    for scenario in BREAKDOWN_SCENARIOS:
                        for theme in THEMES:
                            document = args.documents / f"{scenario}-{theme}.html"
                            for index, width in enumerate(WIDTHS):
                                result["current"] = identity(engine, scenario, theme, width)
                                for page in (reference, resized):
                                    page.set_viewport_size({"width": width, "height": 900})
                                reference.goto(document.resolve().as_uri())
                                reference.mouse.move(0, 0)
                                original = reference.evaluate(STATE)
                                if index == 0:
                                    resized.goto(document.resolve().as_uri())
                                resized.mouse.move(0, 0)
                                resized.evaluate(RESET, original)
                                snapshots = [page.evaluate(SNAPSHOT) for page in (reference, resized)]
                                for snapshot in snapshots:
                                    assert_layout(snapshot, scenario, states[scenario])
                                assert resized.evaluate(STATE) == original, "Restored interaction state differs"
                                assert snapshots[0] == snapshots[1], "Fresh and resized layout snapshots differ"
                                summary = resized.locator(".usage-breakdown details > summary").last
                                details = resized.locator(".usage-breakdown details").last
                                before = details.get_attribute("open")
                                summary.focus()
                                summary.press("Enter")
                                assert details.get_attribute("open") != before
                                summary.press("Enter")
                                assert details.get_attribute("open") == before
                                result["comparisons"].append(result["current"])
                finally:
                    context.close()
                    browser.close()
        result["status"] = "equivalent-under-probe"
        result["current"] = None
    except Exception as error:
        result["status"] = "not-demonstrated"
        result["failure"] = str(error)
        raise
    finally:
        args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
