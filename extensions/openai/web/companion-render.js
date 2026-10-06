export const el = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
};
export const money = (n) => n == null ? "--" : new Intl.NumberFormat("en-CA", { style: "currency", currency: "USD" }).format(n);
export const number = (n) => n == null ? "--" : new Intl.NumberFormat("en-CA", { maximumFractionDigits: 2 }).format(n);
export const byId = (id) => document.getElementById(id);
export const localTime = (stamp, timezone) => !stamp ? "--" : new Intl.DateTimeFormat("en-CA", {
  timeZone: timezone, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short",
}).format(new Date(typeof stamp === "number" ? stamp * 1000 : stamp));
export const span = (seconds) => {
  const minutes = Math.max(0, Math.round(seconds / 60));
  const hours = Math.floor(minutes / 60);
  if (hours >= 24) return `${Math.floor(hours / 24)}d ${hours % 24}h`;
  return hours ? `${hours}h${minutes % 60 ? ` ${minutes % 60}m` : ""}` : `${minutes}m`;
};
export const bytes = (value) => {
  if (value < 1024) return `${number(value)} B`;
  const units = ["KiB", "MiB", "GiB", "TiB"];
  const scale = Math.min(4, Math.floor(Math.log(value) / Math.log(1024)));
  return `${number(value / (1024 ** scale))} ${units[scale - 1]}`;
};
export const duration = (minutes) => minutes % 1440 === 0 ? `${minutes / 1440} days` : minutes % 60 === 0 ? `${minutes / 60} hours` : `${minutes} minutes`;

export function table(headers, rows) {
  const wrapper = el("div", undefined, "table-scroll");
  const t = el("table");
  const head = el("thead"); const tr = el("tr");
  headers.forEach((h) => { const th = el("th", h); th.scope = "col"; tr.append(th); });
  head.append(tr); t.append(head);
  const body = el("tbody");
  rows.forEach((values) => { const row = el("tr"); values.forEach((v) => {
    const td = el("td"); td.append(v instanceof Node ? v : el("span", v)); row.append(td);
  }); body.append(row); });
  t.append(body); wrapper.append(t); return wrapper;
}

export function categories(rows) {
  return table(["Category", "Tokens", "API cost", "Est. credits", "API unpriced", "No credit rate"],
    rows.map((r) => [r.category, number(r.tokens), money(r.api_cost_usd), number(r.estimated_standard_credits), number(r.api_unpriced_tokens), number(r.credit_unpriced_tokens)]));
}

export function usageRows(rows, dimension) {
  const label = { agent: "Agent", model: "Model", project: "Project", day: "Day", hour: "Hour" }[dimension];
  return table([label, "Tokens", "API cost", "Est. credits", "Categories"], rows.map((r) => {
    const disclosure = el("details"); disclosure.append(el("summary", "Breakdown"), categories(r.categories));
    if (r.economics) {
      const { metrics: m, coverage: c } = r.economics;
      disclosure.append(table(["Measured turns", "Avg / turn", "Median / turn", "Missing turn IDs"], [[
        number(m.turn_count), money(m.average_cost_per_turn), money(m.median_cost_per_turn), number(c.total_responses - c.measured_responses),
      ]]));
    }
    return [r.role ? `${r.label} · ${r.role}` : r.label, number(r.usage.total_tokens), money(r.api_cost.total_usd), number(r.estimated_standard_credits.total_credits), disclosure];
  }));
}

export function chart(rows, metric) {
  const container = el("div", undefined, "chart");
  const max = Math.max(1e-9, ...rows.map((r) => metric === "tokens" ? r.usage.total_tokens : r.api_cost.total_usd));
  rows.forEach((r) => {
    const v = metric === "tokens" ? r.usage.total_tokens : r.api_cost.total_usd;
    const row = el("div", undefined, "chart-row"); const bar = el("div", undefined, "bar");
    bar.title = `${r.label}: ${number(r.usage.total_tokens)} tokens, ${money(r.api_cost.total_usd)}`;
    bar.tabIndex = 0; bar.setAttribute("role", "img"); bar.setAttribute("aria-label", bar.title);
    const fill = el("span"); fill.style.width = `${100 * v / max}%`; bar.append(fill);
    row.append(el("span", r.label), bar, el("span", metric === "tokens" ? number(v) : money(v))); container.append(row);
  });
  if (!rows.length) container.append(el("p", "No captured activity", "muted"));
  return container;
}

export function renderSummary(reply) {
  const s = reply.data; const language = s.language;
  byId("totals").replaceChildren(...[
    ["API-equivalent cost", money(language.api_cost.total_usd)],
    ["Tokens", number(language.usage.total_tokens)],
    ["Est. Standard credits", number(language.estimated_standard_credits.total_credits)],
  ].map(([label, value]) => { const div = el("div"); div.append(el("span", label), el("strong", value)); return div; }));
  byId("categories").replaceChildren(categories(s.categories));
  const e = s.economics;
  byId("economics").replaceChildren(table(["Measured turns", "Measured responses", "Avg / turn", "Median / turn", "Missing turn IDs"], [[
    number(e.metrics.turn_count), number(e.metrics.response_count), money(e.metrics.average_cost_per_turn), money(e.metrics.median_cost_per_turn),
    number(e.coverage.total_responses - e.coverage.measured_responses),
  ]]));
  const i = s.images; const api = i.api_usd;
  byId("images").replaceChildren(table(["Operations", "Outputs", "Exact API cost", "Estimated range", "Unpriced operations"], [[
    number(i.operation_count), number(i.output_count), money(api.exact_amount), api.estimated_operation_count ? `${money(api.estimated_low)} - ${money(api.estimated_high)}` : "--", number(api.unpriced_operation_count),
  ]]), el("p", s.image_coverage.complete ? "Image coverage complete" : "Image coverage partial", "muted"));
  for (const model of s.image_groups.models) byId("images").append(el("p", `${model.label} · ${number(model.summary.operation_count)} operations`));
  if (s.image_groups.models_truncated || s.image_groups.projects_truncated) byId("images").append(el("small", "First 25 image groups"));
}

export function renderAllowance(reply) {
  const a = reply.data; const zone = reply.timezone;
  const children = a.buckets.map((b) => {
    const container = el("div", undefined, "bucket"); const row = el("p");
    row.append(el("strong", `${b.limit_id} · ${duration(b.duration_minutes)}`),
      el("span", `${number(b.used_percent)}% used · ${number(100 - b.used_percent)}% remaining`),
      el("span", `Reset: ${localTime(b.resets_at, zone)}`, "muted"));
    const meter = el("meter"); meter.min = 0; meter.max = 100; meter.value = 100 - b.used_percent;
    meter.setAttribute("aria-label", `${b.limit_id} remaining allowance`); meter.setAttribute("aria-valuetext", `${number(100 - b.used_percent)}% remaining`);
    container.append(row, meter);
    a.paces.filter((p) => p.limit_id === b.limit_id && p.duration_minutes === b.duration_minutes).forEach((p) => {
      const outcome = p.state !== "ready" ? (p.state === "reported full" ? "Allowance exhausted" : "Awaiting measurable current data") :
        p.exhaustion && p.exhaustion <= p.reset ? `Runs out ${localTime(p.exhaustion, zone)} · ${span(p.reset - p.exhaustion)} before reset` :
          `${number(Math.max(0, p.reset_balance))}% left at reset`;
      container.append(el("p", `${p.name === "Cycle" ? "Since reset" : p.name} · ${span(p.span_seconds)}: ${outcome}`, "pace"));
    });
    return container;
  });
  if (!children.length) children.push(el("p", "No captured allowance reading", "muted"));
  const freshness = { fresh: "Current", partial: "Partially refreshed", stale: "Last known", unavailable: "No captured" }[a.probe_status] || "Last known";
  const credits = a.credits.unlimited ? " · Credits unlimited" : a.credits.balance != null ? ` · Credits ${number(Number(a.credits.balance))}${a.credits.freshness !== "fresh" ? " (last known)" : ""}` : "";
  if (a.last_observed_at || credits) children.push(el("p", `${freshness} reading · ${localTime(a.last_observed_at, zone)}${credits}`, "muted"));
  byId("buckets").replaceChildren(...children);
  const headline = a.headline;
  byId("estimate").replaceChildren(el("p", "Observed API-equivalent value per 100% allowance", "muted"),
    el("strong", headline ? money(headline.estimate.value) : "--"),
    el("p", headline ? `${a.headline_previous ? "Previous window" : "Current"} · ${localTime(headline.start, zone)} - ${localTime(headline.end, zone)}` : "No priced reference", "muted"));
  byId("allowance-details").replaceChildren(table(["Observed", "Value", "Evidence"], a.history.map((w) => [
    `${localTime(w.start, zone)} - ${localTime(w.end, zone)}`, money(w.estimate.value), w.estimate.confidence,
  ])), el("small", "Workload-specific local estimates, not cash or contractual allowance."));
  if (a.history_truncated) byId("allowance-details").append(el("small", "First 50 valid estimates"));
}
