"""CDP DOM/input acceptance for VS Code's separately targeted webview iframe.

Chromium can expose an OOPIF target that Playwright's page frame inventory has
not adopted. Attach that target explicitly; use rendered DOM and real input,
not host command execution or injected webview scripts.
"""
import json
import time


def attributes(node):
    values = node.get("attributes", [])
    return dict(zip(values[::2], values[1::2]))


def nodes(root):
    yield root
    for child in root.get("children", []) + root.get("shadowRoots", []):
        yield from nodes(child)
    if root.get("contentDocument"):
        yield from nodes(root["contentDocument"])


def node_text(node):
    return "".join(n.get("nodeValue", "") for n in nodes(node) if n.get("nodeType") == 3).strip()


class NativeSpeedTarget:
    def __init__(self, browser, target_id, deadline):
        self.browser = browser
        self.page = browser.contexts[0].pages[0]
        self.session = browser.new_browser_cdp_session()
        self.session_id = self.session.send("Target.attachToTarget", {
            "targetId": target_id, "flatten": False,
        })["sessionId"]
        self.responses = {}
        self.sequence = 0
        self.deadline = deadline
        self.session.on("Target.receivedMessageFromTarget", self._received)

    def _received(self, event):
        if event.get("sessionId") == self.session_id:
            message = json.loads(event["message"])
            if "id" in message:
                self.responses[message["id"]] = message

    def send(self, method, params=None):
        self.sequence += 1
        identity = self.sequence
        self.session.send("Target.sendMessageToTarget", {
            "sessionId": self.session_id,
            "message": json.dumps({"id": identity, "method": method, "params": params or {}}),
        })
        stop = min(self.deadline, time.monotonic() + 5)
        while identity not in self.responses and time.monotonic() < stop:
            self.page.wait_for_timeout(10)
        if identity not in self.responses:
            raise TimeoutError(f"Native iframe CDP {method} did not respond")
        result = self.responses.pop(identity)
        if "error" in result:
            raise RuntimeError(f"Native iframe CDP {method}: {result['error']}")
        return result.get("result", {})

    def document(self):
        return self.send("DOM.getDocument", {"depth": -1, "pierce": True})["root"]

    def chart(self):
        return next((n for n in nodes(self.document())
                     if "observed-speed" in attributes(n).get("class", "").split()), None)

    def state(self, decode_navigation):
        chart = self.chart()
        if chart is None:
            return None
        selected = next(n for n in nodes(chart) if attributes(n).get("aria-current") == "true")
        args = decode_navigation(attributes(selected)["href"])
        window = next((n for n in nodes(chart) if "speed-window" in attributes(n).get("class", "").split()), None)
        label = next((n for n in nodes(window) if n.get("nodeName") == "STRONG"), None) if window else None
        return {"granularity": args["granularity"], "scope": args["scope"],
                "window_start": args["windowStart"], "window_label": node_text(label) if label else None}

    def click(self, label, decode_navigation):
        document = self.document()
        chart = next(n for n in nodes(document)
                     if "observed-speed" in attributes(n).get("class", "").split())
        link = next(n for n in nodes(chart) if n.get("nodeName") == "A" and node_text(n) == label)
        args = decode_navigation(attributes(link)["href"])
        self.send("DOM.scrollIntoViewIfNeeded", {"nodeId": link["nodeId"]})
        quad = self.send("DOM.getContentQuads", {"nodeId": link["nodeId"]})["quads"][0]
        x, y = sum(quad[::2]) / 4, sum(quad[1::2]) / 4
        toolbar = next(n for n in nodes(document)
                       if "companion-actions" in attributes(n).get("class", "").split())
        toolbar_quad = self.send("DOM.getContentQuads", {"nodeId": toolbar["nodeId"]})["quads"][0]
        bottom = max(toolbar_quad[1::2])
        if y <= bottom + 12:
            # scrollIntoView does not account for the variable-height sticky
            # toolbar. Real wheel input clears it before hit-testing the link.
            self.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x,
                      "y": bottom + 20, "deltaX": 0, "deltaY": y - bottom - 12})
            self.page.wait_for_timeout(100)
            quad = self.send("DOM.getContentQuads", {"nodeId": link["nodeId"]})["quads"][0]
            x, y = sum(quad[::2]) / 4, sum(quad[1::2]) / 4
        hit = self.send("DOM.getNodeForLocation", {"x": round(x), "y": round(y)})
        assert hit["backendNodeId"] in {n.get("backendNodeId") for n in nodes(link)}, f"Occluded native link: {label}"
        self.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        for event in ("mousePressed", "mouseReleased"):
            self.send("Input.dispatchMouseEvent", {
                "type": event, "x": x, "y": y, "button": "left", "clickCount": 1,
            })
        return args

    def screenshot(self, path):
        self.send("DOM.scrollIntoViewIfNeeded", {"nodeId": self.chart()["nodeId"]})
        self.page.screenshot(path=str(path), timeout=5000)

    def close(self):
        self.session.send("Target.detachFromTarget", {"sessionId": self.session_id})
        self.session.detach()


def attach_speed_target(browser, deadline, decode_navigation, diagnostics, diagnostics_path):
    session = browser.new_browser_cdp_session()
    try:
        while time.monotonic() < deadline:
            targets = session.send("Target.getTargets")["targetInfos"]
            diagnostics["targets"] = [{"type": t["type"], "url": t["url"]} for t in targets]
            diagnostics_path.write_text(json.dumps(diagnostics, indent=2) + "\n")
            for info in targets:
                if (info["type"] != "iframe" or not info["url"].startswith("vscode-webview://")
                    or "extensionId=wenjun-mao.codex-usage-dashboard" not in info["url"]):
                    continue
                target = NativeSpeedTarget(browser, info["targetId"], deadline)
                state = target.state(decode_navigation)
                if state is not None:
                    return target, state
                target.close()
            browser.contexts[0].pages[0].wait_for_timeout(100)
    finally:
        session.detach()
    raise TimeoutError("VS Code iframe target did not render Observed Output Speed")


def wait_native_state(target, expected, decode_navigation, matches):
    while time.monotonic() < target.deadline:
        state = target.state(decode_navigation)
        if state is not None and matches(state, expected):
            return state
        target.page.wait_for_timeout(100)
    raise TimeoutError(f"Native rendered navigation did not settle to {expected}")
