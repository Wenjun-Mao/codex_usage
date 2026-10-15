"""One strict real-input-to-style observation budget, without selector adoption."""
from time import perf_counter


def prepare_pointer(page, hit, tooltip):
    hit.hover(position={"x": 2, "y": 2}, timeout=1000, trial=True)
    # The pinned driver's trial hover moves the pointer and can prime CSS hover.
    page.mouse.move(0, 0)
    page.evaluate("document.activeElement.blur()")
    require_hidden(tooltip)
    box = hit.bounding_box()
    assert box is not None and box["width"] > 2 and box["height"] > 2
    point = {"x": box["x"] + 2, "y": box["y"] + 2}
    assert hit.evaluate("(e,p)=>e.contains(document.elementFromPoint(p.x,p.y))", point)
    return point


def tooltip_state(tooltip):
    return tooltip.evaluate("""tip => {
        const target = tip.previousElementSibling;
        const style = getComputedStyle(tip);
        const rect = tip.getBoundingClientRect();
        return {visible: style.visibility === 'visible' && style.opacity === '1'
                && rect.width > 0 && rect.height > 0,
            hidden: style.visibility === 'hidden' && style.opacity === '0',
            active: target === document.activeElement,
            focusVisible: target.matches(':focus-visible'), hover: target.matches(':hover')};
    }""")


def require_hidden(tooltip):
    state = tooltip_state(tooltip)
    assert state["hidden"] and not state["active"] and not state["hover"], {
        "phase": "input baseline", "state": state}
    return state


def observe_keyboard(page, tooltip, targets, index, *, record=None):
    origin = page.locator('.ub-meter-legend span[tabindex="0"]') if index == 0 else targets.nth(index-1)
    assert origin.count() == 1
    origin.focus()
    assert origin.evaluate("e=>e===document.activeElement")
    return observe_input(page, tooltip, lambda: page.keyboard.press("Tab"),
        visible=True, keyboard=True, phase="keyboard", record=record)


def observe_input(page, tooltip, action, *, visible, keyboard=False, phase, record=None):
    baseline = require_hidden(tooltip) if visible else None
    started = perf_counter()
    action()
    state = None
    while True:
        elapsed = perf_counter() - started
        assert elapsed < .25, {"phase": phase, "seconds": elapsed, "state": state}
        state = tooltip_state(tooltip)
        elapsed = perf_counter() - started
        assert elapsed < .25, {"phase": phase, "seconds": elapsed, "state": state}
        if visible:
            matched = state["visible"] and (not keyboard or
                (state["active"] and state["focusVisible"] and not state["hover"]))
        else:
            matched = state["hidden"] and not state["active"] and not state["hover"]
        if matched:
            if record is not None:
                record({"phase": phase, "seconds": elapsed, "baseline": baseline, "matched": state})
            return elapsed
        page.wait_for_timeout(10)
