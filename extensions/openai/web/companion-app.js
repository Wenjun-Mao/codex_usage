import { App } from "@modelcontextprotocol/ext-apps";
import { createIcons, RefreshCw, Maximize2, MessageSquare, ScanLine, Square } from "lucide";
import { byId, el, money, number, bytes, localTime, table, chart, usageRows, renderSummary, renderAllowance } from "./companion-render.js";

const app = new App({ name: "Codex Usage private companion", version: "0.0.1" }, { availableDisplayModes: ["inline", "fullscreen"] });
const state = { connected: false, selected: false, revision: 0, view: "usage", pages: {}, job: null, timer: null, scope: null };
createIcons({ icons: { RefreshCw, Maximize2, MessageSquare, ScanLine, Square }, attrs: { "aria-hidden": "true" } });
const messages = {
  sharing_not_enabled: "Private sharing is not enabled.", collector_update_required: "A compatible VS Code collector is required.",
  collector_unavailable: "The VS Code collector is unavailable. Open VS Code, then reload.",
  action_completion_unknown: "Action completion is unknown. Check current data or job status before trying again.",
  snapshot_expired: "Snapshot expired. Reload to refresh the selection.", selection_expired: "Selection expired. Reload and select again.",
  invalid_request: "The selected range or request is invalid.", selection_changed: "Tree membership changed. Reload and select again.",
};
function error(message) { byId("error").textContent = message; byId("error").hidden = false; }
function scope() {
  return { period: byId("period").value, project_ids: byId("project").value === "all" ? [] : [byId("project").value],
    start_date: byId("period").value === "custom" ? byId("start").value : null,
    end_date: byId("period").value === "custom" ? byId("end").value : null };
}
const metric = () => document.querySelector('input[name="metric"]:checked').value;
async function query(name, args = {}) {
  let response;
  try { response = await app.callServerTool({ name, arguments: args }); }
  catch { throw new Error("The private connection was interrupted. Reload to retry reads; check action status before retrying actions."); }
  const reply = response.structuredContent;
  if (response.isError || !reply || reply.schema_version !== 1 || reply.state !== "ok") throw new Error(messages[reply?.error_code] || "The private query failed. Reload to retry.");
  return reply.result;
}
async function projects(revision) {
  const selected = state.initialProject || byId("project").value; const rows = []; let cursor;
  do {
    const r = await query("list_projects", cursor ? { cursor } : { limit: 100 });
    rows.push(...r.data.rows); cursor = r.data.next_cursor;
    if (revision !== state.revision) return;
    if (rows.length >= 1000 && cursor) throw new Error("More than 1,000 projects. Use conversational pagination.");
  } while (cursor);
  byId("project").replaceChildren(...[{ id: "all", label: "All projects" }, ...rows].map((r) => { const o = el("option", r.label); o.value = r.id; return o; }));
  if ([...byId("project").options].some((o) => o.value === selected)) byId("project").value = selected;
  else if (selected !== "all") throw new Error("Project selection expired. Select a project again.");
  state.initialProject = null;
}
function changeView(view) {
  state.view = view; byId("usage-view").hidden = view !== "usage"; byId("storage-view").hidden = view !== "storage";
  byId("usage-tab").setAttribute("aria-pressed", String(view === "usage")); byId("storage-tab").setAttribute("aria-pressed", String(view === "storage"));
  byId("period").disabled = view === "storage"; byId("custom").hidden = view === "storage" || byId("period").value !== "custom";
}
function freshness(reply) {
  state.scope = reply.scope; byId("ask").disabled = false;
  byId("freshness").textContent = reply.status ? `Captured ${localTime(reply.status.last_capture_at, reply.timezone)} · Revision ${reply.status.ledger_revision} · ${reply.status.coverage.complete ? "Complete local coverage" : "Partial local coverage"} · Shared aggregates` : `Storage observed ${localTime(reply.observed_at, reply.timezone)} · Shared aggregates`;
}
async function reload({ initial = false } = {}) {
  if (!state.connected) return;
  if (!initial) state.selected = true;
  const revision = ++state.revision; byId("error").hidden = true; byId("connection").textContent = "Loading"; byId("ask").disabled = true;
  try {
    await projects(revision); if (revision !== state.revision) return;
    const selected = scope();
    if (state.view === "storage") {
      const r = await query("storage_inventory", { project_ids: selected.project_ids, limit: 25 });
      if (revision !== state.revision) return;
      freshness(r); showTrees(r); byId("connection").textContent = "Connected"; return;
    }
    if (selected.period === "custom" && (!selected.start_date || !selected.end_date)) throw new Error("Choose both custom dates.");
    const summary = await query("usage_summary", selected); const allowance = await query("allowance_status");
    const pages = [];
    for (const dimension of ["day", "hour", byId("dimension").value]) {
      pages.push([dimension, await query("usage_breakdown", { ...selected, dimension, metric: metric(), limit: dimension === "day" ? 31 : 25 })]);
      if (revision !== state.revision) return;
    }
    if ([allowance, ...pages.map((p) => p[1])].some((r) => r.status.ledger_revision !== summary.status.ledger_revision || r.timezone !== summary.timezone)) throw new Error("Captured data changed during loading. Reload to get one consistent revision.");
    freshness(summary); renderSummary(summary); renderAllowance(allowance);
    byId("daily").hidden = ["today", "yesterday"].includes(selected.period);
    for (const [dimension, r] of pages) showPage(r, dimension);
    byId("connection").textContent = "Connected";
  } catch (e) { if (revision === state.revision) { byId("connection").textContent = "Unavailable"; error(e.message); } }
}
function showPage(reply, dimension, append = false) {
  const rows = append ? [...state.pages[dimension].rows, ...reply.data.rows] : reply.data.rows;
  state.pages[dimension] = { rows, cursor: reply.data.next_cursor };
  const prefix = dimension === "day" ? "daily" : dimension === "hour" ? "hour" : "breakdown";
  byId(`${prefix}-more`).hidden = !reply.data.next_cursor;
  if (["day", "hour"].includes(dimension)) {
    byId(`${prefix}-chart`).replaceChildren(chart(rows, dimension === "day" ? "api_cost" : metric()), el("small", `${number(rows.length)} of ${number(reply.data.total_rows)} ${dimension === "day" ? "days" : "hours"}`));
    byId(`${prefix}-table`).replaceChildren(usageRows(rows, dimension));
  } else byId("breakdown").replaceChildren(chart(rows, metric()), el("small", `${number(rows.length)} of ${number(reply.data.total_rows)} rows`), usageRows(rows, dimension));
}
async function more(dimension) {
  const revision = state.revision;
  try { const r = await query("usage_breakdown", { cursor: state.pages[dimension].cursor }); if (revision === state.revision) showPage(r, dimension, true); }
  catch (e) { error(e.message); }
}
function showTrees(reply, append = false) {
  const rows = append ? [...state.pages.tree.rows, ...reply.data.rows] : reply.data.rows;
  state.pages.tree = { rows, cursor: reply.data.next_cursor, snapshot_id: reply.snapshot_id };
  const t = reply.totals;
  byId("storage-totals").replaceChildren(el("p", `${bytes(t.corpus_bytes)} · ${number(t.physical_file_count)} files · ${number(t.task_tree_count)} trees`), el("small", `${number(rows.length)} of ${number(reply.data.total_rows)} trees`));
  byId("storage-more").hidden = !reply.data.next_cursor;
  byId("trees").replaceChildren(table(["Tree", "Total", "Root", "Descendants", "Evidence", ""], rows.map((r) => {
    const b = el("button", "Analyze", "command"); b.onclick = () => analyze(r.id, reply.snapshot_id);
    return [r.label, bytes(r.total_bytes), bytes(r.root_bytes), `${number(r.descendant_count)} · ${bytes(r.descendant_bytes)}`,
      [r.has_missing_root ? "Root missing" : "", r.has_history_amplification ? "History amplification" : "", r.has_media_amplification ? "Inline media" : "", r.analysis_status].filter(Boolean).join(" · "), b];
  })));
}
async function confirm(title, message) {
  byId("confirm-title").textContent = title; byId("confirm-text").textContent = message;
  const dialog = byId("confirm"); dialog.returnValue = "cancel"; dialog.showModal();
  return new Promise((resolve) => dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true }));
}
async function analyze(tree_id, snapshot_id) {
  if (!await confirm("Analyze selected tree?", "Read this tree's files and update its local diagnostics.")) return;
  try { const r = await query("analyze_storage_tree", { tree_id, snapshot_id }); state.job = r.data.job_id; showJob(r); schedulePoll(); }
  catch (e) { error(e.message); }
}
function showJob(r) {
  const j = r.data; byId("job").hidden = false;
  byId("job-state").textContent = `${j.state}${j.progress.total_files != null ? ` · ${number(j.progress.completed_files)} / ${number(j.progress.total_files)} files` : ""}${j.error_code ? ` · ${messages[j.error_code] || "Analysis failed"}` : ""}`;
  const terminal = ["completed", "failed", "cancelled"].includes(j.state); byId("cancel").hidden = terminal;
  if (terminal) { state.job = null; clearTimeout(state.timer); }
  byId("job-result").replaceChildren(...(j.result ? [table(["Measured bytes", "Coverage", "Compacted bytes", "Inline-media occurrences"], [[number(j.result.tree.analyzed_bytes), `${number(j.result.tree.analysis_coverage * 100)}%`, number(j.result.tree.compacted_bytes), number(j.result.tree.embedded_media_occurrence_count)]])] : []));
}
function schedulePoll() {
  clearTimeout(state.timer); if (!state.job || document.hidden) return;
  state.timer = setTimeout(async () => { try { showJob(await query("storage_job", { job_id: state.job })); schedulePoll(); } catch (e) { error(e.message); } }, 2000);
}

byId("usage-tab").onclick = () => { changeView("usage"); reload(); };
byId("storage-tab").onclick = () => { changeView("storage"); reload(); };
byId("filters").onsubmit = (e) => e.preventDefault();
byId("period").onchange = () => { byId("custom").hidden = byId("period").value !== "custom"; reload(); };
for (const id of ["project", "start", "end", "dimension"]) byId(id).onchange = reload;
byId("reload").onclick = () => { reload(); if (state.job) schedulePoll(); };
for (const input of document.querySelectorAll('input[name="metric"]')) input.onchange = reload;
byId("daily-more").onclick = () => more("day"); byId("hour-more").onclick = () => more("hour");
byId("breakdown-more").onclick = () => more(byId("dimension").value);
byId("storage-more").onclick = async () => { const revision = state.revision; try { const r = await query("storage_inventory", { cursor: state.pages.tree.cursor }); if (revision === state.revision) showTrees(r, true); } catch (e) { error(e.message); } };
byId("capture").onclick = async () => {
  if (!await confirm("Capture Usage?", "Update captured usage through the existing VS Code collector.")) return;
  byId("capture").disabled = true;
  try { const r = await query("capture_usage"); if (r.data.outcome !== "success") throw new Error("Capture failed. Existing captured data is retained."); await reload(); }
  catch (e) { error(e.message); } finally { byId("capture").disabled = false; }
};
byId("cancel").onclick = async () => { try { showJob(await query("cancel_storage_analysis", { job_id: state.job })); if (state.job) byId("job-state").textContent = "Cancellation requested"; } catch (e) { error(e.message); } };
byId("comparison").onsubmit = async (e) => {
  e.preventDefault(); const revision = state.revision;
  try {
    const selected = scope(); const r = await query("compare_usage", { left: { ...selected, period: byId("baseline").value, start_date: null, end_date: null }, right: selected });
    if (revision !== state.revision) return;
    byId("comparison-result").replaceChildren(table(["Metric", "Baseline", "Selected", "Change"], Object.entries(r.data.changes).map(([name, v]) => { const f = name === "api_cost_usd" ? money : number; return [name.replaceAll("_", " "), f(v.left), f(v.right), `${f(v.delta)}${v.percent_change != null ? ` · ${number(v.percent_change)}%` : ""}`]; })));
  } catch (e) { error(e.message); }
};
byId("theme").onchange = () => { const v = byId("theme").value; document.documentElement.dataset.theme = v === "auto" ? (app.getHostContext()?.theme === "dark" ? "night" : "day") : v; };
byId("expand").onclick = async () => { try { await app.requestDisplayMode({ mode: "fullscreen" }); } catch { error("Fullscreen is unavailable in this host."); } };
byId("ask").onclick = async () => {
  try { await app.updateModelContext({ structuredContent: { scope: state.scope, view: state.view } }); await app.sendMessage({ role: "user", content: [{ type: "text", text: `Analyze this Codex Usage ${state.view} selection using captured aggregates and their coverage.` }] }); }
  catch { error("Conversation context is unavailable in this host."); }
};
app.onhostcontextchanged = ({ theme }) => { if (byId("theme").value === "auto" && theme) byId("theme").dispatchEvent(new Event("change")); };
app.ontoolresult = (r) => {
  if (state.selected || r.structuredContent?.state !== "ok") return;
  const incoming = r.structuredContent.result;
  if (incoming.view) changeView(incoming.view);
  if (incoming.scope?.period && [...byId("period").options].some((o) => o.value === incoming.scope.period)) byId("period").value = incoming.scope.period;
  if (incoming.scope?.start_date) byId("start").value = incoming.scope.start_date;
  if (incoming.scope?.end_date) byId("end").value = incoming.scope.end_date;
  if (incoming.scope?.project_ids?.length) state.initialProject = incoming.scope.project_ids[0];
  if (state.connected) reload({ initial: true });
};
document.addEventListener("visibilitychange", schedulePoll);
async function initialize() {
  try {
    await app.connect(); state.connected = true;
    const context = app.getHostContext(); const caps = app.getHostCapabilities();
    byId("expand").hidden = !context?.availableDisplayModes?.includes("fullscreen");
    byId("ask").hidden = !(caps?.updateModelContext && caps?.message?.text);
    byId("theme").dispatchEvent(new Event("change")); await reload({ initial: true });
  } catch (e) { byId("connection").textContent = "Unavailable"; error(e.message || "A connected MCP host is required."); }
}
initialize();
