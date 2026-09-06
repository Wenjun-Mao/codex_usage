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
