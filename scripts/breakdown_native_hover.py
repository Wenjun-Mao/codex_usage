"""Native OOPIF hover and Tab inspection without injecting webview scripts."""
from time import perf_counter

from speed_native_target import attributes, node_text, nodes


def check_native_hover(target, screenshot):
    target.send("DOM.enable")
    target.send("CSS.enable")
    buckets = [n for n in nodes(target.chart())
        if "ub-hover-bucket" in attributes(n).get("class", "").split()]
    pairs = []
    for bucket in buckets:
        link = next(n for n in nodes(bucket)
            if "ub-hover-target" in attributes(n).get("class", "").split())
        tip = next(n for n in nodes(bucket)
            if "ub-hover-tooltip" in attributes(n).get("class", "").split())
        pairs.append((link, tip))
    assert len(pairs) >= 2

    def visible(node):
        style = {s["name"]: s["value"] for s in target.send(
            "CSS.getComputedStyleForNode", {"nodeId": node["nodeId"]})["computedStyle"]}
        return style["visibility"] == "visible" and style["opacity"] == "1"

    timings = []
    for link, tip in pairs[:2]:
        # VS Code fills missing anchor titles with command URIs. An explicit
        # empty hit-area title suppresses inherited native titles.
        area = next(n for n in nodes(link)
            if "ub-hover-hit" in attributes(n).get("class", "").split())
        assert attributes(area).get("title") == ""
        target.send("DOM.scrollIntoViewIfNeeded", {"nodeId": link["nodeId"]})
        quad = target.send("DOM.getContentQuads", {"nodeId": link["nodeId"]})["quads"][0]
        x, y = sum(quad[::2])/4, sum(quad[1::2])/4
        hit = target.send("DOM.getNodeForLocation", {"x": round(x), "y": round(y)})
        assert hit["backendNodeId"] in {n.get("backendNodeId") for n in nodes(link)}
        target.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 0, "y": 0})
        # Establish the style/transport baseline before measuring first input;
        # initial webview CSS-domain setup is not tooltip latency.
        assert not visible(tip)
        started = perf_counter()
        target.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        while not visible(tip) and perf_counter()-started < .25:
            target.page.wait_for_timeout(10)
        elapsed = perf_counter()-started
        is_visible = visible(tip)
        assert is_visible and elapsed < .25, {"visible": is_visible, "seconds": elapsed,
            "link": attributes(link), "tooltip": node_text(tip)}
        timings.append(elapsed)
        text = node_text(tip)
        assert "e+" not in text and "999999" not in text, text
        target.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 0, "y": 0})
        assert not visible(tip)

    target.send("DOM.focus", {"nodeId": pairs[0][0]["nodeId"]})
    for event in ("keyDown", "keyUp"):
        target.send("Input.dispatchKeyEvent", {"type": event, "key": "Tab", "code": "Tab",
            "windowsVirtualKeyCode": 9})
    assert visible(pairs[1][1]) and not visible(pairs[0][1])
    target.page.screenshot(path=str(screenshot), timeout=5000)
    return {"hover_seconds": timings, "hover_within_250ms": True,
        "tab_traversal": "CDP focus origin; real Tab reaches next usage bar",
        "script_disabled": True, "numeric_format_readable": True,
        "native_title_inheritance_suppressed": True}
