export const usageReportHtml = `<!doctype html>
<html lang="en" data-codex-theme="night">
<head>
<meta charset="utf-8">
<style>
:root {
  color-scheme: light;
  --bg: #f5f7f9;
  --surface: #ffffff;
  --soft: #edf1f4;
  --text: #172027;
  --muted: #64717b;
  --line: #d5dce1;
  --astra: #087f8c;
  --sol: #c47f00;
  --terra: #2e8b57;
  --luna: #7656c7;
}
html[data-codex-theme="night"] {
  color-scheme: dark;
  --bg: #101316;
  --surface: #15191d;
  --soft: #1e242a;
  --text: #edf2f5;
  --muted: #9ba7b1;
  --line: #303840;
  --astra: #45c5d6;
  --sol: #f2b84b;
  --terra: #5fc98a;
  --luna: #b59af1;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 20px 24px 46px;
  background: var(--bg);
  color: var(--text);
  font: 14px system-ui, -apple-system, Segoe UI, sans-serif;
  line-height: 1.4;
}
.muted { color: var(--muted); font-size: 12px; }
.metric-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  margin: 18px 0 24px;
  border-block: 1px solid var(--line);
}
.metric-strip > div { min-width: 0; padding: 12px; border-right: 1px solid var(--line); }
.metric-strip > div:last-child { border-right: 0; }
.metric-strip span { display: block; color: var(--muted); font-size: 10px; text-transform: uppercase; }
.metric-strip strong { display: block; margin-top: 4px; font-size: 20px; overflow-wrap: anywhere; }
.metric-strip small { display: block; margin-top: 2px; color: var(--muted); font-size: 10px; }
.cost-input { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.cost-toolbar { display: flex; align-items: center; justify-content: flex-end; gap: 7px; margin: -31px 0 10px; color: var(--muted); font-size: 10px; font-weight: 700; }
.cost-options { display: inline-flex; overflow: hidden; border: 1px solid var(--line); border-radius: 4px; background: var(--surface); }
.cost-options label { min-width: 62px; padding: 4px 8px; cursor: pointer; text-align: center; }
.cost-options label + label { border-left: 1px solid var(--line); }
#cost-trend-week:checked ~ .cost-toolbar label[for="cost-trend-week"],
#cost-trend-month:checked ~ .cost-toolbar label[for="cost-trend-month"] { background: var(--soft); color: var(--text); }
#cost-trend-week:focus-visible ~ .cost-toolbar label[for="cost-trend-week"],
#cost-trend-month:focus-visible ~ .cost-toolbar label[for="cost-trend-month"] { outline: 2px solid var(--astra); outline-offset: -2px; }
.cost-month-panel { display: none; }
#cost-trend-month:checked ~ .cost-panels .cost-week-panel { display: none; }
#cost-trend-month:checked ~ .cost-panels .cost-month-panel { display: block; }
.cost-panels { padding-bottom: 20px; }
.trend-bars { display: grid; grid-template-columns: repeat(var(--count), minmax(1px, 1fr)); gap: 5px; width: 100%; height: 132px; padding: 0 12px; align-items: end; border-bottom: 1px solid var(--line); }
.trend-bar { position: relative; display: block; height: var(--height); min-height: 3px; border-radius: 3px 3px 0 0; background: var(--astra); outline: none; }
.trend-bar::after { position: absolute; left: 50%; top: calc(100% + 6px); color: var(--muted); content: attr(data-label); font-size: 9px; white-space: nowrap; transform: translateX(-50%); }
.trend-tooltip { position: absolute; left: 50%; bottom: calc(100% + 7px); width: max-content; max-width: min(220px, calc(100vw - 48px)); padding: 5px 7px; border-radius: 4px; background: var(--text); color: var(--bg); font-size: 10px; opacity: 0; pointer-events: none; transform: translateX(-50%); }
.trend-bar:hover .trend-tooltip, .trend-bar:focus-visible .trend-tooltip { opacity: 1; }
.trend-bar:first-child .trend-tooltip { left: 0; transform: none; }
.trend-bar:last-child .trend-tooltip { right: 0; left: auto; transform: none; }
.section { margin-top: 22px; padding-top: 18px; border-top: 1px solid var(--line); }
h2 { margin: 0 0 4px; font-size: 17px; }
.help { margin: 0 0 12px; color: var(--muted); font-size: 12px; }
.image-activity-heading { display: flex; justify-content: space-between; gap: 12px; }
.image-activity-source { display: inline-block; border: 1px solid var(--line); border-radius: 999px; color: var(--muted); font-size: 10px; font-weight: 700; line-height: 1.2; padding: 3px 7px; white-space: nowrap; }
.image-activity-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 12px 0; }.image-activity-metrics > div { padding: 10px; border: 1px solid var(--line); border-radius: 7px; background: var(--soft); }.image-activity-metrics dt, .image-activity-metrics small { color: var(--muted); font-size: 10px; }.image-activity-metrics dd { margin: 2px 0 0; font-size: 14px; font-weight: 700; }.image-activity-metrics small { display: block; margin-top: 3px; }
.project-economics-heading { display: flex; justify-content: space-between; gap: 12px; }
.project-economics-heading p { max-width: 760px; }
.economics-source, .sample-badge { display: inline-block; border: 1px solid var(--line); border-radius: 999px; color: var(--muted); font-size: 10px; font-weight: 700; line-height: 1.2; padding: 3px 7px; white-space: nowrap; }
.sample-badge { border-color: var(--sol); color: var(--sol); margin-left: 7px; }
.economics-benchmark { margin-top: 12px; padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--soft); }
.economics-benchmark-heading { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; }
.economics-benchmark-heading > span { color: var(--muted); }
.economics-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 10px 0 0; }
.economics-metrics > div { min-width: 0; }
.economics-metrics dt, .economics-metrics span { color: var(--muted); font-size: 10px; }
.economics-metrics dd { margin: 2px 0; font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums; }
.economics-metrics span { display: block; line-height: 1.3; }
.project-economics-project { margin-top: 6px; padding: 0 10px; border: 1px solid var(--line); border-radius: 7px; background: var(--surface); }
.project-economics-project[open] { padding-bottom: 10px; }
.project-economics-project summary, .token-accounting summary { cursor: pointer; color: var(--text); font-weight: 700; }
.project-economics-project summary { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; min-height: 42px; }
.project-economics-summary { color: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; text-align: right; }
.economics-models { margin-top: 12px; }
.token-accounting { margin-top: 12px; }
.token-accounting p { margin: 8px 0 0; }
.project-scroll { overflow-x: auto; }
.scale-input { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.scale-toolbar { display: flex; align-items: center; justify-content: flex-end; gap: 7px; margin-bottom: 9px; color: var(--muted); font-size: 10px; font-weight: 700; }
.scale-options { display: inline-flex; overflow: hidden; border: 1px solid var(--line); border-radius: 4px; background: var(--surface); }
.scale-options label { min-width: 58px; padding: 4px 8px; cursor: pointer; text-align: center; }
.scale-options label + label { border-left: 1px solid var(--line); }
#compare-scale-tokens:checked ~ .scale-toolbar label[for="compare-scale-tokens"],
#compare-scale-cost:checked ~ .scale-toolbar label[for="compare-scale-cost"] { background: var(--soft); color: var(--text); }
#compare-scale-tokens:focus-visible ~ .scale-toolbar label[for="compare-scale-tokens"],
#compare-scale-cost:focus-visible ~ .scale-toolbar label[for="compare-scale-cost"] { outline: 2px solid var(--astra); outline-offset: -2px; }
.project-grid { display: grid; grid-template-columns: 145px minmax(210px, 1fr) minmax(170px, .65fr) 185px; gap: 8px 16px; align-items: center; }
.column { color: var(--muted); font-size: 10px; font-weight: 700; text-transform: uppercase; }
.project { text-align: right; }
.role-metric { font-size: 11px; font-weight: 650; font-variant-numeric: tabular-nums; }
.track { height: 30px; overflow: hidden; border-radius: 4px; background: var(--soft); }
.role-fill { display: flex; width: var(--token-width); height: 100%; overflow: hidden; border-radius: 4px; }
.segment { display: block; flex: 0 0 auto; width: var(--token-width); height: 100%; }
.cost-share { display: none; }
#compare-scale-cost:checked ~ .comparison-charts .role-fill,
#compare-scale-cost:checked ~ .comparison-charts .segment,
#compare-scale-cost:checked ~ .comparison-charts .mix-fill { width: var(--cost-width); }
#compare-scale-cost:checked ~ .comparison-charts .token-share { display: none; }
#compare-scale-cost:checked ~ .comparison-charts .cost-share { display: inline; }
.astra { background: var(--astra); }
.sol { background: var(--sol); }
.terra { background: var(--terra); }
.luna { background: var(--luna); }
.total, .mix-value { color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
.legend { display: flex; gap: 18px; margin: 17px 0 0 161px; color: var(--muted); font-size: 11px; }
.swatch { display: inline-block; width: 10px; height: 10px; margin-right: 6px; border: 1px solid var(--line); border-radius: 2px; vertical-align: -1px; }
.model-mix { display: grid; grid-template-columns: 145px minmax(260px, 1fr) max-content; gap: 10px 12px; align-items: center; max-width: 930px; }
.model-row { display: contents; }
.model-name { text-align: right; font-size: 12px; }
.mix-track { height: 24px; border-radius: 4px; background: var(--soft); }
.mix-fill { display: block; width: var(--token-width); height: 100%; border-radius: 4px; }
.comparison-charts { display: grid; min-width: 0; gap: 24px; }
.comparison-charts > .section { min-width: 0; }
.table-wrap { overflow-x: auto; }
table { width: 100%; min-width: 760px; border-collapse: collapse; font-size: 11px; }
th, td { padding: 7px 8px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }
th { color: var(--muted); font-size: 10px; text-transform: uppercase; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
@media (max-width: 720px) {
  body { padding: 16px; }
  .metric-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .metric-strip > div { border-bottom: 1px solid var(--line); }
  .metric-strip > div:nth-child(2n) { border-right: 0; }
  .metric-strip > div:last-child { grid-column: 1 / -1; border-bottom: 0; }
  .project-grid { min-width: 690px; grid-template-columns: 90px minmax(210px, 1fr) minmax(180px, .75fr) 165px; }
  .legend { min-width: 690px; margin-left: 106px; }
  .model-mix { min-width: 600px; grid-template-columns: 96px minmax(260px, 1fr) max-content; }
  .cost-toolbar { margin-top: 0; justify-content: flex-start; }
  .project-economics-heading, .project-economics-project summary { align-items: flex-start; flex-direction: column; gap: 4px; }
  .project-economics-summary { text-align: left; }
  .economics-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
</head>
<body>
<div class="muted">Usage range: All time · Pricing table as of 2026-09-04</div>
<div class="muted">Pricing uses rates effective at each usage event.</div>
<section class="metric-strip" aria-label="Usage summary">
  <div><span>Total tokens</span><strong>903.9M</strong><small>6,418 usage events</small></div>
  <div><span>API-equivalent cost</span><strong>$437.45</strong><small>100% priced</small></div>
  <div><span>Codex credits</span><strong>13,837</strong><small>100% credit-priced</small></div>
  <div><span>Cache hit share</span><strong>97.8%</strong><small>881.7M cached input</small></div>
  <div><span>API-excluded tokens</span><strong>0</strong><small>All models have rates</small></div>
</section>
<section class="section project-economics" data-report-section="project-economics" aria-labelledby="project-economics-heading">
  <div class="project-economics-heading"><div><h2 id="project-economics-heading">Project Economics</h2><p class="help">Turn measures use selected ledger responses with a non-empty turn ID. The benchmark is weighted across those responses, not averaged from projects.</p></div><span class="economics-source">Ledger only</span></div>
  <section class="economics-benchmark" aria-label="Weighted all-project benchmark"><div class="economics-benchmark-heading"><strong>Weighted all-project benchmark</strong><span>4,981 measured turns</span></div><dl class="economics-metrics"><div><dt>Average cost / turn</dt><dd>$0.09</dd><span>4,981 of 4,981 turns priceable</span></div><div><dt>Median cost / turn</dt><dd>$0.07</dd><span>Priceable turns only</span></div><div><dt>Tokens / turn</dt><dd>181.5K</dd><span>6,418 responses across 4,981 turns</span></div><div><dt>Turn coverage</dt><dd>94% responses</dd><span>6,012 of 6,418 responses · 97% of tokens</span></div></dl></section>
  <details class="project-economics-project"><summary><span>codex_usage<span class="sample-badge">Small sample</span></span><span class="project-economics-summary">201.6M tokens · $0.08 / turn · 3 turns</span></summary><div><dl class="economics-metrics"><div><dt>Average cost / response</dt><dd>$0.05</dd><span>5 of 5 responses priceable</span></div><div><dt>Responses / turn</dt><dd>1.7</dd><span>5 responses across 3 turns</span></div><div><dt>Tokens / turn</dt><dd>67.2M</dd><span>100% of tokens covered</span></div><div><dt>Turn coverage</dt><dd>100% responses</dd><span>5 of 5 responses · 100% of tokens</span></div></dl><div class="table-wrap"><table class="economics-models"><thead><tr><th>Model</th><th class="num">Tokens</th><th class="num">Token share</th><th class="num">Cost share</th><th class="num">Turns</th><th class="num">Average cost / turn</th></tr></thead><tbody><tr><td>gpt-5.6-sol</td><td class="num">164.2M</td><td class="num">81.4%</td><td class="num">87.7%</td><td class="num">3</td><td class="num">$0.09</td></tr><tr><td>gpt-5.6-terra</td><td class="num">37.4M</td><td class="num">18.6%</td><td class="num">12.3%</td><td class="num">2</td><td class="num">$0.03</td></tr></tbody></table></div></div></details>
  <details class="token-accounting"><summary>Token Accounting</summary><p class="muted">Cache Write (reported) is taken from the selected ledger exactly as Codex reported it; it is never inferred from cache reads or reconstructed during report rendering.</p><div class="table-wrap"><table><thead><tr><th>Project</th><th class="num">Input</th><th class="num">Cache Read</th><th class="num">Cache Write (reported)</th><th class="num">Output</th></tr></thead><tbody><tr><td>codex_usage</td><td class="num">2.1M</td><td class="num">194.8M</td><td class="num">0.3M</td><td class="num">3.1M</td></tr></tbody></table></div></details>
</section>
<section class="section cost-trend" data-report-section="daily-cost">
  <h2>Cost Trend</h2>
  <div class="cost-trend-interaction" role="radiogroup" aria-label="Cost trend period">
  <input class="cost-input" type="radio" name="cost-trend-granularity" id="cost-trend-week" value="week" aria-label="Group cost trend by week" checked>
  <input class="cost-input" type="radio" name="cost-trend-granularity" id="cost-trend-month" value="month" aria-label="Group cost trend by month">
  <div class="cost-toolbar"><span>Group by</span><span class="cost-options"><label for="cost-trend-week">Week</label><label for="cost-trend-month">Month</label></span></div>
  <div class="cost-panels project-scroll">
    <div class="cost-week-panel"><div class="trend-bars" style="--count:8">
      <span class="trend-bar" tabindex="0" data-label="Jul 13" style="--height:35%"><span class="trend-tooltip">Jul 13–19, 2026 · $29.18 · 62.1M tokens</span></span>
      <span class="trend-bar" tabindex="0" data-label="Jul 20" style="--height:48%"><span class="trend-tooltip">Jul 20–26, 2026 · $40.04 · 84.3M tokens</span></span>
      <span class="trend-bar" tabindex="0" data-label="Jul 27" style="--height:64%"><span class="trend-tooltip">Jul 27–Aug 2, 2026 · $53.37 · 110.8M tokens</span></span>
      <span class="trend-bar" tabindex="0" data-label="Aug 3" style="--height:55%"><span class="trend-tooltip">Aug 3–9, 2026 · $45.86 · 98.4M tokens</span></span>
      <span class="trend-bar" tabindex="0" data-label="Aug 10" style="--height:76%"><span class="trend-tooltip">Aug 10–16, 2026 · $63.38 · 132.5M tokens</span></span>
      <span class="trend-bar" tabindex="0" data-label="Aug 17" style="--height:90%"><span class="trend-tooltip">Aug 17–23, 2026 · $75.06 · 154.7M tokens</span></span>
      <span class="trend-bar" tabindex="0" data-label="Aug 24" style="--height:68%"><span class="trend-tooltip">Aug 24–30, 2026 · $56.71 · 121.4M tokens</span></span>
      <span class="trend-bar" tabindex="0" data-label="Aug 31" style="--height:100%"><span class="trend-tooltip">Aug 31–Sep 6, 2026 · $83.40 · 139.7M tokens</span></span>
    </div></div>
    <div class="cost-month-panel"><div class="trend-bars" style="--count:5">
      <span class="trend-bar" tabindex="0" data-label="May 2026" style="--height:42%"><span class="trend-tooltip">May 1–31, 2026 · $88.10 · 181.6M tokens</span></span>
      <span class="trend-bar" tabindex="0" data-label="Jun 2026" style="--height:58%"><span class="trend-tooltip">Jun 1–30, 2026 · $121.77 · 249.4M tokens</span></span>
      <span class="trend-bar" tabindex="0" data-label="Jul 2026" style="--height:73%"><span class="trend-tooltip">Jul 1–31, 2026 · $153.30 · 318.9M tokens</span></span>
      <span class="trend-bar" tabindex="0" data-label="Aug 2026" style="--height:100%"><span class="trend-tooltip">Aug 1–31, 2026 · $210.01 · 438.2M tokens</span></span>
      <span class="trend-bar" tabindex="0" data-label="Sep 2026" style="--height:31%"><span class="trend-tooltip">Sep 1–30, 2026 · $64.27 · 132.8M tokens</span></span>
    </div></div>
  </div></div>
</section>
<section class="section image-activity" data-report-section="image-activity" aria-labelledby="image-activity-heading">
  <div class="image-activity-heading"><div><h2 id="image-activity-heading">Image Generation</h2><p class="help">Ledger-only image operations. Image values are separate from language tokens, costs, and Project Economics; prompts and image contents are never retained.</p></div><span class="image-activity-source">Separate accounting</span></div>
  <dl class="image-activity-metrics"><div><dt>Operations</dt><dd>19</dd></div><div><dt>Outputs</dt><dd>31</dd></div><div><dt>Succeeded</dt><dd>17</dd><small>2 failed</small></div><div><dt>API equivalent</dt><dd>exact $0.4350</dd><small>3 unpriced</small></div></dl>
  <div class="table-wrap"><table><thead><tr><th>Model evidence</th><th class="num">Operations</th><th class="num">Outputs</th><th class="num">API equivalent</th><th class="num">Codex credits</th></tr></thead><tbody><tr><th>GPT Image 2</th><td class="num">12</td><td class="num">22</td><td class="num">exact $0.4350</td><td class="num">exact credits 10.8750</td></tr><tr><th>GPT Image 2.5 Sunburst</th><td class="num">7</td><td class="num">9</td><td class="num">3 unpriced</td><td class="num">3 unpriced</td></tr></tbody></table></div>
</section>
<section class="section agent-activity">
  <h2>Agent Activity</h2>
  <p class="help">Activity is calculated only from the selected ledger records. Root task resolution follows the saved task graph.</p>
  <h3>Daily Summary</h3>
  <div class="table-wrap"><table><thead><tr><th>Date</th><th class="num">Total</th><th class="num">Input</th><th class="num">Cached Input</th><th class="num">Output</th><th class="num">Reasoning</th><th class="num">Responses</th><th class="num">Root Tasks</th><th class="num">Subagents</th></tr></thead><tbody>
    <tr><td>Sep 6, 2026</td><td class="num">139.7M</td><td class="num">1.4M</td><td class="num">136.1M</td><td class="num">1.8M</td><td class="num">0.4M</td><td class="num">1,142</td><td class="num">18</td><td class="num">42</td></tr>
  </tbody></table></div>
  <h3>Agents</h3>
  <details class="agent-activity-agents"><summary>Show 3 of 3 agents by total tokens.</summary>
  <p class="help">Export Agent Activity CSV includes every selected agent-day row.</p>
  <div class="table-wrap"><table><thead><tr><th>Agent</th><th>Role</th><th>Root Task</th><th>Projects</th><th class="num">Days</th><th class="num">Input</th><th class="num">Cached Input</th><th class="num">Output</th><th class="num">Reasoning</th><th class="num">Total</th><th class="num">Responses</th></tr></thead><tbody>
    <tr><td>Ship native persistent collector</td><td>Root</td><td><code>019f…0001</code></td><td>codex_usage</td><td class="num">18</td><td class="num">2.3M</td><td class="num">194.8M</td><td class="num">3.1M</td><td class="num">0.7M</td><td class="num">200.9M</td><td class="num">1,202</td></tr>
    <tr><td>Evaluate report visuals</td><td>Subagent</td><td><code>019f…0001</code></td><td>codex_usage</td><td class="num">6</td><td class="num">0.4M</td><td class="num">35.9M</td><td class="num">0.5M</td><td class="num">0.1M</td><td class="num">36.9M</td><td class="num">221</td></tr>
    <tr><td>Research product metrics</td><td>Subagent</td><td><code>019f…0001</code></td><td>persona_generators</td><td class="num">4</td><td class="num">0.3M</td><td class="num">28.1M</td><td class="num">0.4M</td><td class="num">0.1M</td><td class="num">28.9M</td><td class="num">184</td></tr>
  </tbody></table></div></details>
</section>
<section class="section usage-comparison">
  <input class="scale-input" type="radio" name="usage-chart-scale" id="compare-scale-tokens" value="tokens" checked>
  <input class="scale-input" type="radio" name="usage-chart-scale" id="compare-scale-cost" value="cost">
  <div class="scale-toolbar"><span>Compare by</span><span class="scale-options" role="group" aria-label="Compare chart bars by"><label for="compare-scale-tokens">Tokens</label><label for="compare-scale-cost">API cost</label></span></div>
  <div class="comparison-charts">
<section class="section">
  <h2>Project Breakdown</h2>
  <p class="help">Root task token usage includes side chats stored in the parent task.</p>
  <div class="project-scroll">
    <div class="project-grid">
      <span class="column project">Project</span><span class="column">Root tasks</span><span class="column">Subagents</span><span class="column">Total</span>
      <strong class="project">uk_dev</strong>
      <div><div class="role-metric">371.3M · $190.40 · <span class="token-share">70.0%</span><span class="cost-share">73.7%</span></div><div class="track"><div class="role-fill" data-project-key="uk_dev" data-role="root" style="--token-width:100%;--cost-width:100%"><span class="segment astra" style="--token-width:4%;--cost-width:10%"></span><span class="segment sol" style="--token-width:72%;--cost-width:75%"></span><span class="segment terra" style="--token-width:24%;--cost-width:15%"></span></div></div></div>
      <div><div class="role-metric">159.1M · $67.89 · <span class="token-share">30.0%</span><span class="cost-share">26.3%</span></div><div class="track"><div class="role-fill" data-project-key="uk_dev" data-role="subagent" style="--token-width:100%;--cost-width:100%"><span class="segment terra" style="--token-width:82%;--cost-width:95%"></span><span class="segment luna" style="--token-width:18%;--cost-width:5%"></span></div></div></div>
      <span class="total">530.4M · $258.29 · 8,181 cr</span>
      <strong class="project">codex_usage</strong>
      <div><div class="role-metric">164.2M · $85.22 · <span class="token-share">81.4%</span><span class="cost-share">87.7%</span></div><div class="track"><div class="role-fill" data-project-key="codex_usage" data-role="root" style="--token-width:44.22%;--cost-width:44.76%"><span class="segment astra" style="--token-width:3%;--cost-width:8%"></span><span class="segment sol" style="--token-width:59%;--cost-width:75%"></span><span class="segment terra" style="--token-width:38%;--cost-width:17%"></span></div></div></div>
      <div><div class="role-metric">37.4M · $11.90 · <span class="token-share">18.6%</span><span class="cost-share">12.3%</span></div><div class="track"><div class="role-fill" data-project-key="codex_usage" data-role="subagent" style="--token-width:23.51%;--cost-width:17.53%"><span class="segment terra" style="--token-width:100%;--cost-width:100%"></span></div></div></div>
      <span class="total">201.6M · $97.12 · 3,044 cr</span>
      <strong class="project">persona_generators</strong>
      <div><div class="role-metric">107.5M · $79.02 · <span class="token-share">62.5%</span><span class="cost-share">96.3%</span></div><div class="track"><div class="role-fill" data-project-key="persona_generators" data-role="root" style="--token-width:28.95%;--cost-width:41.50%"><span class="segment sol" style="--token-width:100%;--cost-width:100%"></span></div></div></div>
      <div><div class="role-metric">64.4M · $3.02 · <span class="token-share">37.5%</span><span class="cost-share">3.7%</span></div><div class="track"><div class="role-fill" data-project-key="persona_generators" data-role="subagent" style="--token-width:40.48%;--cost-width:4.45%"><span class="segment luna" style="--token-width:100%;--cost-width:100%"></span></div></div></div>
      <span class="total">171.9M · $82.04 · 2,611 cr</span>
    </div>
    <div class="legend">
      <span><i class="swatch astra"></i>gpt-6-astra</span>
      <span><i class="swatch sol"></i>gpt-5.6-sol</span>
      <span><i class="swatch terra"></i>gpt-5.6-terra</span>
      <span><i class="swatch luna"></i>gpt-5.6-luna</span>
    </div>
  </div>
</section>
<section class="section">
  <h2>Model Mix</h2>
  <div class="model-mix">
    <div class="model-row"><strong class="model-name">gpt-6-astra</strong><div class="mix-track"><span class="mix-fill astra" style="--token-width:3.4%;--cost-width:10.3%"></span></div><span class="mix-value">20.0M · $31.00 · 775 cr</span></div>
    <div class="model-row"><strong class="model-name">gpt-5.6-sol</strong><div class="mix-track"><span class="mix-fill sol" style="--token-width:100%;--cost-width:100%"></span></div><span class="mix-value">588.2M · $300.00 · 9,029 cr</span></div>
    <div class="model-row"><strong class="model-name">gpt-5.6-terra</strong><div class="mix-track"><span class="mix-fill terra" style="--token-width:39.3%;--cost-width:33.3%"></span></div><span class="mix-value">231.3M · $100.00 · 3,507 cr</span></div>
    <div class="model-row"><strong class="model-name">gpt-5.6-luna</strong><div class="mix-track"><span class="mix-fill luna" style="--token-width:10.9%;--cost-width:2.2%"></span></div><span class="mix-value">64.4M · $6.45 · 526 cr</span></div>
  </div>
</section>
</div>
</section>
</body>
</html>`;
