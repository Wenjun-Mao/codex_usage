from __future__ import annotations

_MODEL_COLOR_CSS = """
    :root {
      --model-0: #8fb1f5;
      --model-1: #3978e6;
      --model-2: #315a9f;
      --model-3: #b59af1;
      --model-4: #7d4dde;
      --model-5: #dd6a9e;
      --model-6: #d9aa2b;
      --model-7: #8b949f;
    }
    html[data-codex-theme="night"] {
      --model-0: #a7c2fa;
      --model-1: #5b91f2;
      --model-2: #6188c8;
      --model-3: #c7b2f7;
      --model-4: #9b74e7;
      --model-5: #ee8bb8;
      --model-6: #e5be53;
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
      gap: 12px;
      min-width: 680px;
      max-width: 920px;
      width: 100%;
    }
    .project-breakdown-row, .model-mix-row {
      display: grid;
      grid-template-columns: minmax(120px, 200px) minmax(220px, 1fr) max-content;
      gap: 10px;
      align-items: center;
    }
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
    .project-track, .model-mix-track {
      min-width: 0;
      height: 58px;
      border-radius: 4px;
      background: var(--surface-soft);
    }
    .project-role-stack { min-width: 0; height: 100%; }
    .project-role-labels {
      display: grid;
      min-width: 0;
      height: 24px;
      margin-bottom: 4px;
    }
    .project-role-groups { display: grid; height: 34px; min-width: 0; }
    .project-role-groups.has-role-gap,
    .project-role-labels.has-role-gap { gap: 8px; }
    .project-role-heading { container-type: inline-size; overflow: hidden; min-width: 0; color: var(--muted); font-size: 11px; white-space: nowrap; }
    .project-role-heading-label { color: var(--text); font-weight: 650; }
    .project-role-heading-detail { margin-left: 4px; font-variant-numeric: tabular-nums; }
    .project-role-group { display: flex; overflow: hidden; min-width: 0; border: 1px solid var(--border); border-radius: 4px; }
    .model-segment { position: relative; display: block; flex: 0 0 auto; height: 100%; outline: none; }
    .model-segment:hover, .model-segment:focus-visible { filter: brightness(1.12); z-index: 3; }
    .model-segment:focus-visible { box-shadow: inset 0 0 0 2px var(--text); z-index: 3; }
    .model-segment + .model-segment { border-left: 1px solid var(--surface); }
    .model-legend { display: flex; flex-wrap: wrap; gap: 6px 12px; margin: 2px 0 0 210px; color: var(--muted); font-size: 12px; }
    .model-legend-item { display: inline-flex; align-items: center; gap: 5px; }
    .model-swatch { display: inline-block; width: 10px; height: 10px; border: 1px solid var(--border); border-radius: 2px; overflow: hidden; }
    .model-swatch > span { display: block; width: 100%; height: 100%; }
    .model-segment .chart-tooltip { left: 50%; }
    .model-segment:hover .chart-tooltip,
    .model-segment:focus-visible .chart-tooltip { opacity: 1; visibility: visible; transform: translate(-50%, 0); transition-delay: 0s; }
    @container (max-width: 120px) { .project-role-heading-detail { display: none; } }
    @media (max-width: 720px) {
      .project-breakdown-chart, .model-mix-chart { min-width: 560px; }
      .project-breakdown-row, .model-mix-row { grid-template-columns: 96px minmax(220px, 1fr) max-content; gap: 8px; }
      .breakdown-bar-label { text-align: left; }
      .model-legend { margin-left: 104px; }
    }
    body.vscode-high-contrast .project-role-group,
    body.vscode-high-contrast .model-segment { border-color: var(--border); }
    body.vscode-high-contrast {
      --model-0: var(--text);
      --model-1: var(--text);
      --model-2: var(--text);
      --model-3: var(--text);
      --model-4: var(--text);
      --model-5: var(--text);
      --model-6: var(--text);
      --model-7: var(--text);
    }
"""

_MODEL_MIX_CSS = """
    .model-mix-track { height: 24px; position: relative; }
    .model-mix-fill { position: relative; display: block; height: 100%; min-width: 0; border: 1px solid var(--border); border-radius: 4px; outline: none; }
    .model-mix-fill:hover, .model-mix-fill:focus-visible { filter: brightness(1.12); z-index: 3; }
    .model-mix-fill:focus-visible { box-shadow: inset 0 0 0 2px var(--text); }
    .model-mix-fill:hover .chart-tooltip,
    .model-mix-fill:focus-visible .chart-tooltip { opacity: 1; visibility: visible; transform: translate(-50%, 0); transition-delay: 0s; }
    body.vscode-high-contrast .model-mix-fill { border-color: var(--border); }
"""


def report_breakdown_css() -> str:
    return "\n".join(  # noqa: FLY002 - explicit chart CSS composition is the public contract.
        (_MODEL_COLOR_CSS, _PROJECT_BREAKDOWN_CSS, _MODEL_MIX_CSS)
    )
