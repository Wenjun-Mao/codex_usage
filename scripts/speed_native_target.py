"""CDP DOM/input acceptance for VS Code's separately targeted webview iframe.

Chromium can expose an OOPIF target that Playwright's page frame inventory has
not adopted. Attach that target explicitly; use rendered DOM and real input,
not host command execution or injected webview scripts.
"""
import json
import time
import asyncio

from native_cdp import NativeCDP


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


class NativeSpeedTarget(NativeCDP):
    chart_class = "observed-speed"
    def __init__(self, browser, session, session_id, deadline):
        super().__init__(session, session_id, deadline)
        self.browser = browser
        self.page = browser.contexts[0].pages[0]

    @classmethod
    async def attach(cls, browser, target_id, deadline):
        async with asyncio.timeout(max(0, min(5, deadline - time.monotonic()))):
            session = await browser.new_browser_cdp_session()
            try:
                result = await session.send("Target.attachToTarget", {"targetId": target_id, "flatten": False})
            except BaseException:
                async with asyncio.timeout(5):
                    await session.detach()
                raise
        return cls(browser, session, result["sessionId"], deadline)

    async def document(self):
        return (await self.send("DOM.getDocument", {"depth": -1, "pierce": True}))["root"]

    async def chart(self):
        return next((n for n in nodes(await self.document())
                     if self.chart_class in attributes(n).get("class", "").split()), None)

    async def state(self, decode_navigation):
        chart = await self.chart()
        if chart is None:
            return None
        selected = next(n for n in nodes(chart) if attributes(n).get("aria-current") == "true")
        args = decode_navigation(attributes(selected)["href"])
        window = next((n for n in nodes(chart) if "speed-window" in attributes(n).get("class", "").split()), None)
        label = next((n for n in nodes(window) if n.get("nodeName") == "STRONG"), None) if window else None
        return {"granularity": args["granularity"], "scope": args["scope"],
                "window_start": args["windowStart"], "window_label": node_text(label) if label else None}

    async def click(self, label, decode_navigation):
        document = await self.document()
        chart = next(n for n in nodes(document)
                     if self.chart_class in attributes(n).get("class", "").split())
        link = next(n for n in nodes(chart) if n.get("nodeName") == "A" and node_text(n) == label)
        args = decode_navigation(attributes(link)["href"])
        await self.send("DOM.scrollIntoViewIfNeeded", {"nodeId": link["nodeId"]})
        quad = (await self.send("DOM.getContentQuads", {"nodeId": link["nodeId"]}))["quads"][0]
        x, y = sum(quad[::2]) / 4, sum(quad[1::2]) / 4
        toolbar = next(n for n in nodes(document)
                       if "companion-actions" in attributes(n).get("class", "").split())
        toolbar_quad = (await self.send("DOM.getContentQuads", {"nodeId": toolbar["nodeId"]}))["quads"][0]
        bottom = max(toolbar_quad[1::2])
        if y <= bottom + 12:
            # scrollIntoView does not account for the variable-height sticky
            # toolbar. Real wheel input clears it before hit-testing the link.
            await self.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x,
                      "y": bottom + 20, "deltaX": 0, "deltaY": y - bottom - 12})
            await self.page.wait_for_timeout(100)
            quad = (await self.send("DOM.getContentQuads", {"nodeId": link["nodeId"]}))["quads"][0]
            x, y = sum(quad[::2]) / 4, sum(quad[1::2]) / 4
        hit = await self.send("DOM.getNodeForLocation", {"x": round(x), "y": round(y)})
        assert hit["backendNodeId"] in {n.get("backendNodeId") for n in nodes(link)}, f"Occluded native link: {label}"
        await self.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        for event in ("mousePressed", "mouseReleased"):
            await self.send("Input.dispatchMouseEvent", {
                "type": event, "x": x, "y": y, "button": "left", "clickCount": 1,
            })
        return args

    async def screenshot(self, path):
        await self.send("DOM.scrollIntoViewIfNeeded", {"nodeId": (await self.chart())["nodeId"]})
        await self.page.screenshot(path=str(path), timeout=5000)


async def attach_speed_target(browser, deadline, decode_navigation, diagnostics, diagnostics_path, target_type=NativeSpeedTarget):
    session = await browser.new_browser_cdp_session()
    try:
        while time.monotonic() < deadline:
            targets = (await session.send("Target.getTargets"))["targetInfos"]
            diagnostics["targets"] = [{"type": t["type"], "url": t["url"]} for t in targets]
            diagnostics_path.write_text(json.dumps(diagnostics, indent=2) + "\n")
            for info in targets:
                if (info["type"] != "iframe" or not info["url"].startswith("vscode-webview://")
                    or "extensionId=wenjun-mao.codex-usage-dashboard" not in info["url"]):
                    continue
                target = await target_type.attach(browser, info["targetId"], deadline)
                state = await target.state(decode_navigation)
                if state is not None:
                    return target, state
                await target.close()
            await browser.contexts[0].pages[0].wait_for_timeout(100)
    finally:
        await session.detach()
    raise TimeoutError("VS Code iframe target did not render Observed Output Speed")


async def wait_native_state(target, expected, decode_navigation, matches):
    while time.monotonic() < target.deadline:
        state = await target.state(decode_navigation)
        if state is not None and matches(state, expected):
            return state
        await target.page.wait_for_timeout(100)
    raise TimeoutError(f"Native rendered navigation did not settle to {expected}")
