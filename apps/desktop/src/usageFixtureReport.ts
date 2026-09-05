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
.section { margin-top: 22px; padding-top: 18px; border-top: 1px solid var(--line); }
h2 { margin: 0 0 4px; font-size: 17px; }
.help { margin: 0 0 12px; color: var(--muted); font-size: 12px; }
.project-scroll { overflow-x: auto; }
.scale-input { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.scale-toolbar { display: flex; align-items: center; justify-content: flex-end; gap: 7px; margin-bottom: 9px; color: var(--muted); font-size: 10px; font-weight: 700; }
.scale-options { display: inline-flex; overflow: hidden; border: 1px solid var(--line); border-radius: 4px; background: var(--surface); }
.scale-options label { min-width: 58px; padding: 4px 8px; cursor: pointer; text-align: center; }
.scale-options label + label { border-left: 1px solid var(--line); }
#project-scale-tokens:checked ~ .scale-toolbar label[for="project-scale-tokens"],
#project-scale-cost:checked ~ .scale-toolbar label[for="project-scale-cost"] { background: var(--soft); color: var(--text); }
#project-scale-tokens:focus-visible ~ .scale-toolbar label[for="project-scale-tokens"],
#project-scale-cost:focus-visible ~ .scale-toolbar label[for="project-scale-cost"] { outline: 2px solid var(--astra); outline-offset: -2px; }
.project-grid { display: grid; grid-template-columns: 145px minmax(210px, 1fr) minmax(170px, .65fr) 185px; gap: 8px 16px; align-items: center; }
.column { color: var(--muted); font-size: 10px; font-weight: 700; text-transform: uppercase; }
.project { text-align: right; }
.role-metric { font-size: 11px; font-weight: 650; font-variant-numeric: tabular-nums; }
.track { height: 30px; overflow: hidden; border-radius: 4px; background: var(--soft); }
.role-fill { display: flex; width: var(--token-width); height: 100%; overflow: hidden; border-radius: 4px; }
.segment { display: block; flex: 0 0 auto; width: var(--token-width); height: 100%; }
.cost-share { display: none; }
#project-scale-cost:checked ~ .project-grid .role-fill,
#project-scale-cost:checked ~ .project-grid .segment { width: var(--cost-width); }
#project-scale-cost:checked ~ .project-grid .token-share { display: none; }
#project-scale-cost:checked ~ .project-grid .cost-share { display: inline; }
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
.mix-fill { display: block; height: 100%; border-radius: 4px; }
@media (max-width: 720px) {
  body { padding: 16px; }
  .metric-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .metric-strip > div { border-bottom: 1px solid var(--line); }
  .metric-strip > div:nth-child(2n) { border-right: 0; }
  .metric-strip > div:last-child { grid-column: 1 / -1; border-bottom: 0; }
  .project-grid { min-width: 690px; grid-template-columns: 90px minmax(210px, 1fr) minmax(180px, .75fr) 165px; }
  .legend { min-width: 690px; margin-left: 106px; }
  .model-mix { min-width: 600px; grid-template-columns: 96px minmax(260px, 1fr) max-content; }
}
</style>
</head>
<body>
<div class="muted">Usage range: 7 days · Pricing table as of 2026-09-04</div>
<div class="muted">Pricing uses rates effective at each usage event.</div>
<section class="metric-strip" aria-label="Usage summary">
  <div><span>Total tokens</span><strong>903.9M</strong><small>6,418 usage events</small></div>
  <div><span>API-equivalent cost</span><strong>$437.45</strong><small>100% priced</small></div>
  <div><span>Codex credits</span><strong>13,837</strong><small>100% credit-priced</small></div>
  <div><span>Cache hit share</span><strong>97.8%</strong><small>881.7M cached input</small></div>
  <div><span>API-excluded tokens</span><strong>0</strong><small>All models have rates</small></div>
</section>
<section class="section">
  <h2>Project Breakdown</h2>
  <p class="help">Root task token usage includes side chats stored in the parent task.</p>
  <div class="project-scroll">
    <input class="scale-input" type="radio" name="project-scale" id="project-scale-tokens" value="tokens" checked>
    <input class="scale-input" type="radio" name="project-scale" id="project-scale-cost" value="cost">
    <div class="scale-toolbar"><span>Scale bars by</span><span class="scale-options" role="group" aria-label="Project bar scale"><label for="project-scale-tokens">Tokens</label><label for="project-scale-cost">API cost</label></span></div>
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
    <div class="model-row"><strong class="model-name">gpt-6-astra</strong><div class="mix-track"><span class="mix-fill astra" style="width:3.4%"></span></div><span class="mix-value">20.0M · $31.00 · 775 cr</span></div>
    <div class="model-row"><strong class="model-name">gpt-5.6-sol</strong><div class="mix-track"><span class="mix-fill sol" style="width:100%"></span></div><span class="mix-value">588.2M · $300.00 · 9,029 cr</span></div>
    <div class="model-row"><strong class="model-name">gpt-5.6-terra</strong><div class="mix-track"><span class="mix-fill terra" style="width:39.3%"></span></div><span class="mix-value">231.3M · $100.00 · 3,507 cr</span></div>
    <div class="model-row"><strong class="model-name">gpt-5.6-luna</strong><div class="mix-track"><span class="mix-fill luna" style="width:10.9%"></span></div><span class="mix-value">64.4M · $6.45 · 526 cr</span></div>
  </div>
</section>
</body>
</html>`;
