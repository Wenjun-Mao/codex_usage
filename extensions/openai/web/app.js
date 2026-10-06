import { App } from "@modelcontextprotocol/ext-apps";
import { createIcons, RefreshCw, Maximize2, MessageSquare } from "lucide";

const byId = (id) => document.getElementById(id);
const money = (value) => new Intl.NumberFormat("en-CA", { style: "currency", currency: "USD" }).format(value);
const integer = (value) => new Intl.NumberFormat("en-CA").format(value);
const app = new App({ name: "Codex Usage private test", version: "0.0.1" }, {
  availableDisplayModes: ["inline", "fullscreen"],
});
let payload;
let requestRevision = 0;
let connected = false;
let userSelected = false;

createIcons({ icons: { RefreshCw, Maximize2, MessageSquare }, attrs: { "aria-hidden": "true" } });

function render(result) {
  if (result?.source !== "synthetic" || result.live_data_supported !== false || !Array.isArray(result.projects)) {
    throw new Error("The connection test did not return its synthetic dataset.");
  }
  payload = result;
  byId("ask").disabled = false;
  byId("period").value = result.scope.period;
  byId("project").value = result.scope.project;
  byId("cost").textContent = money(result.api_cost_usd);
  byId("tokens").textContent = integer(result.tokens);
  byId("allowance-label").textContent = `${result.allowance.used_percent}% used · ${result.allowance.remaining_percent}% remaining`;
  byId("allowance").value = result.allowance.remaining_percent;
  byId("allowance").setAttribute("aria-valuetext", `${result.allowance.remaining_percent}% remaining`);
  renderRows();
}

function renderRows() {
  if (!payload) return;
  const metric = document.querySelector('input[name="metric"]:checked').value;
  const rows = [...payload.projects].sort((a, b) => b[metric] - a[metric] || a.id.localeCompare(b.id));
  const max = Math.max(1, ...rows.map((row) => row[metric]));
  byId("rows").replaceChildren(...rows.map((row) => {
    const container = document.createElement("div");
    container.className = "project-row";
    const label = document.createElement("span");
    label.textContent = row.label;
    const bar = document.createElement("div");
    bar.className = "bar";
    bar.setAttribute("aria-hidden", "true");
    const fill = document.createElement("span");
    fill.style.width = `${100 * row[metric] / max}%`;
    bar.append(fill);
    const value = document.createElement("span");
    value.className = "value";
    value.textContent = metric === "tokens" ? integer(row.tokens) : money(row.api_cost_usd);
    container.append(label, bar, value);
    return container;
  }));
}

function showError(message) {
  byId("error").textContent = message;
  byId("error").hidden = false;
}

async function reload(options = {}) {
  if (!connected) return;
  if (!options.initial) userSelected = true;
  const revision = ++requestRevision;
  byId("error").hidden = true;
  byId("connection").textContent = "Loading";
  try {
    const result = await app.callServerTool({ name: "probe_usage", arguments: { period: byId("period").value, project: byId("project").value } });
    if (revision !== requestRevision) return;
    if (result.isError) throw new Error("Synthetic query failed.");
    render(result.structuredContent);
    byId("connection").textContent = "Connected";
  } catch {
    if (revision !== requestRevision) return;
    byId("connection").textContent = "Unavailable";
    showError("The private test connection is unavailable. Reload to retry.");
  }
}

app.ontoolresult = (result) => {
  if (userSelected) return;
  ++requestRevision;
  try {
    render(result.structuredContent);
    byId("connection").textContent = "Connected";
  } catch { showError("Synthetic test data is unavailable."); }
};
app.onhostcontextchanged = ({ theme }) => {
  if (byId("theme").value === "auto" && theme) document.documentElement.dataset.theme = theme === "dark" ? "night" : "day";
};
byId("filters").onsubmit = (event) => event.preventDefault();
byId("period").onchange = reload;
byId("project").onchange = reload;
byId("reload").onclick = reload;
byId("theme").onchange = () => {
  const theme = byId("theme").value;
  const hostTheme = app.getHostContext()?.theme;
  document.documentElement.dataset.theme = theme === "auto" ? (hostTheme === "dark" ? "night" : hostTheme === "light" ? "day" : "auto") : theme;
};
document.querySelectorAll('input[name="metric"]').forEach((input) => input.onchange = renderRows);
byId("expand").onclick = async () => {
  try { await app.requestDisplayMode({ mode: "fullscreen" }); } catch { showError("Fullscreen is unavailable in this host."); }
};
byId("ask").onclick = async () => {
  try {
    await app.updateModelContext({ structuredContent: { source: "synthetic", scope: payload.scope } });
    await app.sendMessage({ role: "user", content: [{ type: "text", text: "Compare the projects in this synthetic Codex Usage selection. Do not treat it as my real usage." }] });
  } catch { showError("Conversation context is unavailable in this host."); }
};

async function initialize() {
  try {
    await app.connect();
    connected = true;
    const context = app.getHostContext();
    const capabilities = app.getHostCapabilities();
    byId("expand").hidden = !context?.availableDisplayModes?.includes("fullscreen");
    byId("ask").hidden = !(capabilities?.updateModelContext && capabilities?.message?.text);
    byId("theme").dispatchEvent(new Event("change"));
    await reload({ initial: true });
  } catch {
    byId("connection").textContent = "Host required";
    showError("The private test connection could not initialize.");
  }
}

initialize();
