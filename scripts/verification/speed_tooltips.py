"""Strict real-input checks for script-free speed tooltip response."""
from time import perf_counter


def state(tooltip):
    return tooltip.evaluate("""e => {
        const s = getComputedStyle(e), r = e.getBoundingClientRect();
        return {visible:s.visibility==='visible' && s.opacity==='1' && r.width>0 && r.height>0,
                hidden:s.visibility==='hidden' && s.opacity==='0'};
    }""")


def observe(tooltip, action, *, visible, limit=.25):
    assert type(limit) in (int, float) and limit in (.25, 2.0), 'Invalid finite observation policy'
    assert state(tooltip)['hidden' if visible else 'visible'], 'tooltip baseline mismatch'
    started = perf_counter()
    action()
    input_returned = perf_counter()
    matched = state(tooltip)
    seconds = perf_counter() - started
    assert seconds < limit, {'phase': 'show' if visible else 'hide', 'seconds': seconds,
        'input_seconds': input_returned-started, 'style_seconds': seconds-(input_returned-started),
        'state': matched}
    assert matched['visible' if visible else 'hidden'], matched
    return seconds


def check_point(page, scope, point, *, screenshot=None, limit=.25):
    key = point.get_attribute('data-speed-tip')
    tooltip = scope.locator(f'.speed-tooltip[data-speed-tip-for="{key}"]').element_handle()
    assert tooltip is not None
    try:
        return _check_point(page, scope, point, tooltip, screenshot=screenshot, limit=limit)
    finally:
        tooltip.dispose()


def _check_point(page, scope, point, tooltip, *, screenshot, limit):
    key = point.get_attribute('data-speed-tip')
    assert point.locator('title').count() == 0
    page.mouse.move(0, 0)
    page.evaluate('document.activeElement.blur()')
    point.scroll_into_view_if_needed()
    box = point.locator('.speed-marker').bounding_box()
    center = {'x': box['x'] + box['width']/2, 'y': box['y'] + box['height']/2}
    assert point.evaluate('(e,p)=>e.contains(document.elementFromPoint(p.x,p.y))', center)
    times = {'hover': observe(tooltip, lambda: page.mouse.move(center['x'], center['y']), visible=True, limit=limit)}
    assert tooltip.inner_text() == point.get_attribute('aria-label')
    assert tooltip.evaluate("""e => {
        const b=e.getBoundingClientRect(), p=e.closest('.speed-hover-scope').getBoundingClientRect();
        return b.left>=p.left-1 && b.right<=p.right+1 && e.scrollWidth<=e.clientWidth+1;
    }"""), 'tooltip overflow'
    if screenshot:
        scope.screenshot(path=str(screenshot))
    times['hide'] = observe(tooltip, lambda: page.mouse.move(0, 0), visible=False, limit=limit)
    point.focus()
    page.keyboard.press('Shift+Tab')
    times['keyboard'] = observe(tooltip, lambda: page.keyboard.press('Tab'), visible=True, limit=limit)
    assert point.evaluate('e=>e===document.activeElement && e.matches(":focus-visible")')
    other = scope.locator(f'.speed-point:not([data-speed-tip="{key}"])').first
    if other.count():
        box = other.locator('.speed-marker').bounding_box()
        times['hover_over_focus'] = observe(tooltip,
            lambda: page.mouse.move(box['x']+box['width']/2, box['y']+box['height']/2),
            visible=False, limit=limit)
        other_tip = scope.locator(f'.speed-tooltip[data-speed-tip-for="{other.get_attribute("data-speed-tip")}"]')
        assert state(other_tip)['visible'], 'hovered point did not take priority over focus'
        times['restore_focus'] = observe(tooltip, lambda: page.mouse.move(0, 0), visible=True, limit=limit)
    page.keyboard.press('Tab')
    assert state(tooltip)['hidden'], 'tooltip stayed visible after leaving the point'
    return times
