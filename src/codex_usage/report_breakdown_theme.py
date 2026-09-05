from __future__ import annotations

_MODEL_COLOR_CSS = """
    :root {
      --model-0: #087f8c;
      --model-1: #c47f00;
      --model-2: #2e8b57;
      --model-3: #7656c7;
      --model-4: #3568c8;
      --model-5: #bb477d;
      --model-6: #c74f37;
      --model-7: #8b949f;
      --model-separator: var(--surface);
      --model-focus-inner: var(--text);
      --model-focus-outer: var(--accent-strong);
    }
    html[data-codex-theme="night"] {
      --model-0: #45c5d6;
      --model-1: #f2b84b;
      --model-2: #5fc98a;
      --model-3: #b59af1;
      --model-4: #6f9cf4;
      --model-5: #ee7aaa;
      --model-6: #ef806b;
      --model-7: #a5adb8;
    }
    .model-color-slot-0 { background: var(--model-0); }
    .model-color-slot-1 { background: var(--model-1); }
    .model-color-slot-2 { background: var(--model-2); }
    .model-color-slot-3 { background: var(--model-3); }
    .model-color-slot-4 { background: var(--model-4); }
    .model-color-slot-5 { background: var(--model-5); }
    .model-color-slot-6 { background: var(--model-6); }
    .model-color-slot-7 { background: var(--model-7); }
"""

_PROJECT_BREAKDOWN_CSS = """
    .project-breakdown-chart, .model-mix-chart {
      display: grid;
      min-width: 680px;
      width: 100%;
    }
    .project-breakdown-chart {
      grid-template-columns: minmax(120px, 190px) minmax(190px, 1fr) minmax(190px, 1fr) max-content;
      gap: 12px 10px;
      align-items: center;
      max-width: 1180px;
    }
    .project-breakdown-matrix { display: contents; }
    .project-breakdown-header, .project-breakdown-row { display: contents; }
    .project-scale-input {
      position: absolute;
      width: 1px;
      height: 1px;
      opacity: 0;
      pointer-events: none;
    }
    .project-scale-toolbar {
      display: flex;
      grid-column: 1 / -1;
      align-items: center;
      justify-self: end;
      gap: 7px;
      min-height: 26px;
    }
    .project-scale-label { color: var(--muted); font-size: 11px; font-weight: 650; }
    .project-scale-options {
      display: inline-flex;
      overflow: hidden;
      border: 1px solid var(--border);
      border-radius: 4px;
      background: var(--surface);
    }
    .project-scale-options label {
      min-width: 58px;
      padding: 4px 8px;
      color: var(--muted);
      cursor: pointer;
      font-size: 11px;
      font-weight: 650;
      text-align: center;
    }
    .project-scale-options label + label { border-left: 1px solid var(--border); }
    #project-scale-tokens:checked ~ .project-scale-toolbar label[for="project-scale-tokens"],
    #project-scale-cost:checked ~ .project-scale-toolbar label[for="project-scale-cost"] {
      background: var(--surface-soft);
      color: var(--text);
    }
    #project-scale-tokens:focus-visible ~ .project-scale-toolbar label[for="project-scale-tokens"],
    #project-scale-cost:focus-visible ~ .project-scale-toolbar label[for="project-scale-cost"] {
      outline: 2px solid var(--accent-strong);
      outline-offset: -2px;
    }
    .project-column-heading, .role-column-heading, .project-total-heading {
      min-width: 0;
      color: var(--muted);
      font-size: 11px;
      font-weight: 650;
      white-space: nowrap;
    }
    .project-column-heading { text-align: right; }
    .model-mix-chart {
      grid-template-columns: minmax(120px, 200px) minmax(220px, 1fr) max-content;
      gap: 12px 10px;
      align-items: center;
      max-width: 920px;
    }
    .model-mix-row { display: contents; }
    .breakdown-bar-label {
      color: var(--text);
      font-size: 12px;
      overflow: hidden;
      text-align: right;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .breakdown-bar-value {
      color: var(--muted);
      font-size: 12px;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }
    .model-mix-track {
      min-width: 0;
      height: 58px;
      border-radius: 4px;
      background: var(--surface-soft);
    }
    .project-role-cell { min-width: 0; }
    .project-role-cell::before { display: none; content: attr(data-role-label); }
    .project-role-metric {
      display: flex;
      align-items: center;
      gap: 4px;
      height: 18px;
      margin-bottom: 5px;
      color: var(--muted);
      font-size: 11px;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }
    .project-role-metric-total { color: var(--text); font-weight: 650; }
    .project-role-cost-share { display: none; }
    .project-role-track { min-width: 0; height: 30px; border-radius: 4px; background: var(--surface-soft); }
    .project-role-fill { min-width: 0; width: var(--token-width, 0%); height: 100%; }
    #project-scale-cost:checked ~ .project-breakdown-matrix .project-role-fill,
    #project-scale-cost:checked ~ .project-breakdown-matrix .model-segment {
      width: var(--cost-width, 0%);
    }
    #project-scale-cost:checked ~ .project-breakdown-matrix .project-role-token-share { display: none; }
    #project-scale-cost:checked ~ .project-breakdown-matrix .project-role-cost-share { display: inline; }
    .project-role-group { position: relative; display: flex; overflow: visible; width: 100%; height: 100%; min-width: 0; border: 1px solid var(--border); border-radius: 4px; }
    .model-segment { position: relative; display: block; flex: 0 0 auto; width: var(--token-width, 0%); height: 100%; outline: none; }
    .model-segment:first-child { border-radius: 3px 0 0 3px; }
    .model-segment:last-child { border-radius: 0 3px 3px 0; }
    .model-segment:only-child { border-radius: 3px; }
    .model-segment:hover { filter: brightness(1.12); z-index: 3; }
    .model-segment + .model-segment { box-shadow: inset 1px 0 0 var(--model-separator); }
    .model-segment:focus-visible {
      box-shadow: inset 0 0 0 2px var(--model-focus-inner), 0 0 0 2px var(--model-focus-outer);
      filter: brightness(1.12);
      z-index: 3;
    }
    .model-legend { display: flex; flex-wrap: wrap; grid-column: 2 / 4; gap: 6px 12px; margin-top: 2px; color: var(--muted); font-size: 12px; }
    .model-legend-item { display: inline-flex; align-items: center; gap: 5px; }
    .model-swatch { display: inline-block; width: 10px; height: 10px; border: 1px solid var(--border); border-radius: 2px; overflow: hidden; }
    .model-swatch > span { display: block; width: 100%; height: 100%; }
    .model-segment .chart-tooltip { left: 50%; }
    .model-segment:hover .chart-tooltip,
    .model-segment:focus-visible .chart-tooltip { opacity: 1; visibility: visible; transform: translate(-50%, 0); transition-delay: 0s; }
    .project-role-cell-root .model-segment:first-child .chart-tooltip { left: 0; transform: translate(0, 2px); }
    .project-role-cell-subagent .model-segment:last-child .chart-tooltip { right: 0; left: auto; transform: translate(0, 2px); }
    .project-role-cell-root .model-segment:first-child:hover .chart-tooltip,
    .project-role-cell-root .model-segment:first-child:focus-visible .chart-tooltip,
    .project-role-cell-subagent .model-segment:last-child:hover .chart-tooltip,
    .project-role-cell-subagent .model-segment:last-child:focus-visible .chart-tooltip { transform: translate(0, 0); }
    @media (max-width: 720px) {
      .project-breakdown-chart { display: block; min-width: 0; }
      .project-scale-toolbar { justify-content: flex-end; margin-bottom: 10px; }
      .project-breakdown-matrix { display: block; }
      .project-breakdown-header { display: none; }
      .project-breakdown-row {
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(0, auto);
        grid-template-areas: "project total" "root root" "subagent subagent";
        gap: 8px 12px;
        padding: 10px 0;
        border-bottom: 1px solid var(--border-soft);
      }
      .project-breakdown-row .breakdown-bar-label { grid-area: project; align-self: center; }
      .project-breakdown-row .breakdown-bar-value { grid-area: total; max-width: 52vw; text-align: right; white-space: normal; overflow-wrap: anywhere; }
      .project-role-cell { display: grid; grid-template-columns: minmax(0, 1fr) auto; grid-template-areas: "role metric" "track track"; row-gap: 3px; }
      .project-role-cell-root { grid-area: root; }
      .project-role-cell-subagent { grid-area: subagent; }
      .project-role-cell::before { display: block; grid-area: role; color: var(--text); font-size: 11px; font-weight: 650; }
      .project-role-metric { grid-area: metric; height: auto; margin: 0; align-self: center; }
      .project-role-track { grid-area: track; }
      .model-legend { margin-top: 10px; }
      .model-mix-chart { min-width: 560px; grid-template-columns: 96px minmax(220px, 1fr) max-content; gap: 12px 8px; }
      .breakdown-bar-label { text-align: left; }
    }
    body.vscode-high-contrast {
      --model-0: var(--text);
      --model-1: var(--text);
      --model-2: var(--text);
      --model-3: var(--text);
      --model-4: var(--text);
      --model-5: var(--text);
      --model-6: var(--text);
      --model-7: var(--text);
      --model-separator: var(--bg);
      --model-focus-inner: var(--bg);
      --model-focus-outer: var(--accent);
    }
    body.vscode-high-contrast .model-segment + .model-segment {
      box-shadow: inset 2px 0 0 var(--model-separator);
    }
    body.vscode-high-contrast .model-segment:focus-visible {
      box-shadow: inset 0 0 0 2px var(--model-focus-inner), 0 0 0 2px var(--model-focus-outer);
    }
"""

_MODEL_MIX_CSS = """
    .model-mix-track { height: 24px; position: relative; }
    .model-mix-fill { position: relative; display: block; height: 100%; border-radius: 4px; box-shadow: inset 0 0 0 1px var(--model-separator); outline: none; }
    .model-mix-fill:hover, .model-mix-fill:focus-visible { filter: brightness(1.12); z-index: 3; }
    .model-mix-fill:focus-visible { box-shadow: inset 0 0 0 2px var(--model-focus-inner), 0 0 0 2px var(--model-focus-outer); }
    .model-mix-fill:hover .chart-tooltip,
    .model-mix-fill:focus-visible .chart-tooltip { opacity: 1; visibility: visible; transform: translate(-50%, 0); transition-delay: 0s; }
"""


def report_breakdown_css() -> str:
    return "\n".join(  # noqa: FLY002 - explicit chart CSS composition is the public contract.
        (_MODEL_COLOR_CSS, _PROJECT_BREAKDOWN_CSS, _MODEL_MIX_CSS)
    )
