import { AppBridge, PostMessageTransport } from "@modelcontextprotocol/ext-apps/app-bridge";
import fixtures from "./dist/companion-fixtures.json";
const state = { requests: [], fail: false, delay: false, skew: false, contexts: [], messages: [], modes: [], jobState: "queued" };
const bridge = new AppBridge(null, { name: "Disposable companion test host", version: "0.0.1" }, {
  serverTools: {}, updateModelContext: {}, message: { text: {} },
}, { hostContext: { theme: "light", displayMode: "inline", availableDisplayModes: ["inline", "fullscreen"] } });
const reply = (result) => ({ content: [{ type: "text", text: "Synthetic bridge fixture" }], structuredContent: { schema_version: 1, state: "ok", result, error_code: null } });
bridge.oncalltool = async ({ name, arguments: args }) => {
  state.requests.push({ name, args });
  if (state.delay) await new Promise((resolve) => setTimeout(resolve, args.period === "today" ? 140 : 10));
  if (state.fail) return { content: [], structuredContent: { schema_version: 1, state: "offline", result: {}, error_code: "collector_unavailable" } };
  const data = fixtures.scopes[`${args.period || "30d"}:${args.project_ids?.[0] || "all"}`];
  if (name === "list_projects") return reply(fixtures.projects);
  if (name === "usage_summary") return reply(data.summary);
  if (name === "allowance_status") return reply(fixtures.allowance);
  if (name === "usage_breakdown") {
    const result = structuredClone(data.breakdowns[args.dimension]);
    if (state.skew) result.status.ledger_revision++;
    return reply(result);
  }
  if (name === "compare_usage") return reply(fixtures.comparison);
  if (name === "storage_inventory") return reply(fixtures.storage);
  if (name === "capture_usage") return reply({ schema_version: 1, data: { outcome: "success", run_id: 2 } });
  if (name === "analyze_storage_tree") { state.jobState = "queued"; return reply({ schema_version: 1, data: { job_id: "test-job", state: "queued", progress: {}, result: null } }); }
  if (name === "cancel_storage_analysis") state.jobState = "cancelled";
  if (["storage_job", "cancel_storage_analysis"].includes(name)) return reply({ schema_version: 1, data: { job_id: "test-job", state: state.jobState, progress: { completed_files: 0, total_files: 1 }, result: null } });
  throw new Error("Unexpected synthetic test tool");
};
bridge.onupdatemodelcontext = async (params) => { state.contexts.push(params); return {}; };
bridge.onmessage = async (params) => { state.messages.push(params); return {}; };
bridge.onrequestdisplaymode = async ({ mode }) => { state.modes.push(mode); bridge.setHostContext({ displayMode: mode }); return { mode }; };
window.companionHost = { state, bridge, fixtures, sendResult: (period, project = "all") => bridge.sendToolResult(reply({ ...fixtures.scopes[`${period}:${project}`].summary, view: "usage" })) };
async function initialize() {
  const frame = document.getElementById("companion");
  await bridge.connect(new PostMessageTransport(frame.contentWindow, frame.contentWindow));
  frame.src = "companion.html";
}
initialize();
