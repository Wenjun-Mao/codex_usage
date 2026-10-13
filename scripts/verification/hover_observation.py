"""One strict real-input-to-style observation budget, without selector adoption."""
from time import perf_counter


def observe_keyboard(page, tooltip, targets, index):
    origin = page.locator('.ub-meter-legend span[tabindex="0"]') if index == 0 else targets.nth(index-1)
    assert origin.count() == 1
    origin.focus()
    assert origin.evaluate("e=>e===document.activeElement")
    return observe_input(page, tooltip, lambda: page.keyboard.press("Tab"),
        visible=True, keyboard=True, phase="keyboard")


def observe_input(page, tooltip, action, *, visible, keyboard=False, phase):
    started = perf_counter()
    action()
    state = None
    while True:
        elapsed = perf_counter() - started
        assert elapsed < .25, {"phase": phase, "seconds": elapsed, "state": state}
        state = tooltip.evaluate("""tip => {
            const target = tip.previousElementSibling;
            const style = getComputedStyle(tip);
            const rect = tip.getBoundingClientRect();
            return {visible: style.visibility === 'visible' && style.opacity === '1'
                    && rect.width > 0 && rect.height > 0,
                hidden: style.visibility === 'hidden' && style.opacity === '0',
                active: target === document.activeElement,
                focusVisible: target.matches(':focus-visible'), hover: target.matches(':hover')};
        }""")
        elapsed = perf_counter() - started
        assert elapsed < .25, {"phase": phase, "seconds": elapsed, "state": state}
        if visible:
            matched = state["visible"] and (not keyboard or
                (state["active"] and state["focusVisible"] and not state["hover"]))
        else:
            matched = state["hidden"] and not state["active"] and not state["hover"]
        if matched:
            return elapsed
        page.wait_for_timeout(10)
