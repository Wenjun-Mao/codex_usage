import { AppBridge, PostMessageTransport } from "@modelcontextprotocol/ext-apps/app-bridge";
import fixtures from "./dist/fixtures.json";

async function initialize() {
  const state = { fail: false, delay: false, requests: [], contexts: [], messages: [], modes: [] };
  const bridge = new AppBridge(null, { name: "Local test harness", version: "0.0.1" }, {
    serverTools: {}, updateModelContext: {}, message: { text: {} },
  }, { hostContext: { theme: "light", displayMode: "inline", availableDisplayModes: ["inline", "fullscreen"] } });
  window.probeHost = {
    state, bridge,
    sendResult: (period, project) => bridge.sendToolResult({
      content: [{ type: "text", text: "Synthetic initial tool result" }],
      structuredContent: fixtures[`${period}:${project}`],
    }),
  };
  bridge.oncalltool = async ({ name, arguments: args }) => {
    state.requests.push({ name, args });
    if (state.delay) await new Promise((resolve) => setTimeout(resolve, args.period === "today" ? 150 : 10));
    if (state.fail) return { isError: true, content: [{ type: "text", text: "Synthetic test failure" }] };
    if (name !== "probe_usage") throw new Error("Unexpected test tool");
    const result = fixtures[`${args.period}:${args.project}`];
    if (!result) throw new Error("Unexpected test scope");
    return { content: [{ type: "text", text: "Synthetic usage" }], structuredContent: result };
  };
  bridge.onupdatemodelcontext = async (params) => { state.contexts.push(params); return {}; };
  bridge.onmessage = async (params) => { state.messages.push(params); return {}; };
  bridge.onrequestdisplaymode = async ({ mode }) => {
    state.modes.push(mode);
    bridge.setHostContext({ displayMode: mode });
    return { mode };
  };
  const frame = document.getElementById("probe");
  await bridge.connect(new PostMessageTransport(frame.contentWindow, frame.contentWindow));
  frame.src = "probe.html";
}

initialize();
