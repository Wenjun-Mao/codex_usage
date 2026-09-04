from __future__ import annotations

from codex_usage.report_breakdown_theme import report_breakdown_css
from codex_usage.report_metric_theme import report_metric_strip_css
from codex_usage.report_views import report_views_css

REPORT_THEME_CHOICES = ("auto", "day", "night")


def normalize_report_theme(value: str | None) -> str:
    theme = (value or "auto").strip().lower()
    if theme not in REPORT_THEME_CHOICES:
        choices = ", ".join(REPORT_THEME_CHOICES)
        raise ValueError(f"unknown report theme {value!r}; expected one of: {choices}")
    return theme


def report_css() -> str:
    return """
    :root {
      color-scheme: light;
      --day-bg: #f5f7f9;
      --day-bg-strong: #edf1f4;
      --day-surface: #ffffff;
      --day-surface-strong: #ffffff;
      --day-surface-soft: #edf1f4;
      --day-surface-muted: #e5ebef;
      --day-text: #172027;
      --day-muted: #64717b;
      --day-muted-soft: #7b8791;
      --day-accent: #087ea4;
      --day-accent-strong: #05627f;
      --day-accent-soft: rgba(8, 126, 164, 0.10);
      --day-highlight: #9b6900;
      --day-success: #1c7a51;
      --day-danger: #bb3748;
      --day-border: #d5dce1;
      --day-border-soft: #e5eaed;
      --day-shadow-soft: 0 1px 2px rgba(23, 32, 39, 0.08);

      --night-bg: #101316;
      --night-bg-strong: #15191d;
      --night-surface: #15191d;
      --night-surface-strong: #1a1f24;
      --night-surface-soft: #1e242a;
      --night-surface-muted: #262d34;
      --night-text: #edf2f5;
      --night-muted: #9ba7b1;
      --night-muted-soft: #78858f;
      --night-accent: #43b4da;
      --night-accent-strong: #75cbe7;
      --night-accent-soft: rgba(67, 180, 218, 0.16);
      --night-highlight: #e0ab34;
      --night-success: #55c68f;
      --night-danger: #ff7485;
      --night-border: #303840;
      --night-border-soft: #252c32;
      --night-shadow-soft: 0 1px 2px rgba(0, 0, 0, 0.22);

      --bg: #f5f7f9;
      --bg-strong: var(--day-bg-strong);
      --surface: var(--day-surface);
      --surface-strong: var(--day-surface-strong);
      --surface-soft: var(--day-surface-soft);
      --surface-muted: var(--day-surface-muted);
      --text: var(--day-text);
      --muted: var(--day-muted);
      --muted-soft: var(--day-muted-soft);
      --accent: var(--day-accent);
      --accent-strong: var(--day-accent-strong);
      --accent-soft: var(--day-accent-soft);
      --highlight: var(--day-highlight);
      --success: var(--day-success);
      --danger: var(--day-danger);
      --border: var(--day-border);
      --border-soft: var(--day-border-soft);
      --shadow-soft: var(--day-shadow-soft);
      --notice-bg: #fff4d2;
      --warn-bg: #fee9ec;
      --heat-0: #eef1f5;
      --heat-1: #dbeafe;
      --heat-2: #93c5fd;
      --heat-3: #3b82f6;
      --heat-4: #1d4ed8;
      --heat-5: #05627f;
      --heat-stroke: var(--surface);
      --tooltip-bg: #111827;
      --tooltip-text: #f8fafc;
    }
    html[data-codex-theme="night"] {
      color-scheme: dark;
      --bg: var(--night-bg);
      --bg-strong: var(--night-bg-strong);
      --surface: var(--night-surface);
      --surface-strong: var(--night-surface-strong);
      --surface-soft: var(--night-surface-soft);
      --surface-muted: var(--night-surface-muted);
      --text: var(--night-text);
      --muted: var(--night-muted);
      --muted-soft: var(--night-muted-soft);
      --accent: var(--night-accent);
      --accent-strong: var(--night-accent-strong);
      --accent-soft: var(--night-accent-soft);
      --highlight: var(--night-highlight);
      --success: var(--night-success);
      --danger: var(--night-danger);
      --border: var(--night-border);
      --border-soft: var(--night-border-soft);
      --shadow-soft: var(--night-shadow-soft);
      --notice-bg: #3b311c;
      --warn-bg: #3d2228;
      --heat-0: #202631;
      --heat-1: #1e3a5f;
      --heat-2: #2f5fbe;
      --heat-3: #43b4da;
      --heat-4: #75cbe7;
      --heat-5: #b8ccff;
      --heat-stroke: var(--bg);
      --tooltip-bg: #f8fafc;
      --tooltip-text: #0d0f12;
    }
    @media (prefers-color-scheme: dark) {
      html[data-codex-theme="auto"] {
        color-scheme: dark;
        --bg: var(--night-bg);
        --bg-strong: var(--night-bg-strong);
        --surface: var(--night-surface);
        --surface-strong: var(--night-surface-strong);
        --surface-soft: var(--night-surface-soft);
        --surface-muted: var(--night-surface-muted);
        --text: var(--night-text);
        --muted: var(--night-muted);
        --muted-soft: var(--night-muted-soft);
        --accent: var(--night-accent);
        --accent-strong: var(--night-accent-strong);
        --accent-soft: var(--night-accent-soft);
        --highlight: var(--night-highlight);
        --success: var(--night-success);
        --danger: var(--night-danger);
        --border: var(--night-border);
        --border-soft: var(--night-border-soft);
        --shadow-soft: var(--night-shadow-soft);
        --notice-bg: #3b311c;
        --warn-bg: #3d2228;
        --heat-0: #202631;
        --heat-1: #1e3a5f;
        --heat-2: #2f5fbe;
        --heat-3: #43b4da;
        --heat-4: #75cbe7;
        --heat-5: #b8ccff;
        --heat-stroke: var(--bg);
        --tooltip-bg: #f8fafc;
        --tooltip-text: #0d0f12;
      }
    }
    html[data-codex-theme="auto"] body.vscode-dark {
      color-scheme: dark;
      --bg: var(--vscode-editor-background, var(--night-bg));
      --bg-strong: var(--night-bg-strong);
      --surface: var(--vscode-sideBar-background, var(--night-surface));
      --surface-strong: var(--night-surface-strong);
      --surface-soft: var(--night-surface-soft);
      --surface-muted: var(--night-surface-muted);
      --text: var(--vscode-editor-foreground, var(--night-text));
      --muted: var(--vscode-descriptionForeground, var(--night-muted));
      --muted-soft: var(--night-muted-soft);
      --accent: var(--vscode-textLink-foreground, var(--night-accent));
      --accent-strong: var(--night-accent-strong);
      --accent-soft: var(--night-accent-soft);
      --highlight: var(--night-highlight);
      --success: var(--night-success);
      --danger: var(--night-danger);
      --border: var(--vscode-panel-border, var(--night-border));
      --border-soft: var(--night-border-soft);
      --shadow-soft: var(--night-shadow-soft);
      --notice-bg: #3b311c;
      --warn-bg: #3d2228;
      --heat-0: #202631;
      --heat-1: #1e3a5f;
      --heat-2: #2f5fbe;
      --heat-3: #43b4da;
      --heat-4: #75cbe7;
      --heat-5: #b8ccff;
      --heat-stroke: var(--bg);
      --tooltip-bg: var(--vscode-editorWidget-background, #f8fafc);
      --tooltip-text: var(--vscode-editorWidget-foreground, #0d0f12);
    }
    body.vscode-high-contrast {
      --bg: var(--vscode-editor-background, #000000);
      --surface: var(--vscode-editor-background, #000000);
      --surface-strong: var(--vscode-editor-background, #000000);
      --surface-soft: var(--vscode-editor-background, #000000);
      --text: var(--vscode-editor-foreground, #ffffff);
      --muted: var(--vscode-editor-foreground, #ffffff);
      --accent: var(--vscode-textLink-foreground, #00ffff);
      --accent-strong: var(--vscode-textLink-activeForeground, #ffffff);
      --border: var(--vscode-contrastBorder, #ffffff);
      --border-soft: var(--vscode-contrastBorder, #ffffff);
      --notice-bg: transparent;
      --warn-bg: transparent;
      --heat-stroke: var(--border);
      --tooltip-bg: var(--vscode-editorWidget-background, #000000);
      --tooltip-text: var(--vscode-editorWidget-foreground, #ffffff);
    }
    * { box-sizing: border-box; }
    body {
      font-family: system-ui, -apple-system, Segoe UI, sans-serif;
      margin: 0;
      background: var(--bg);
      color: var(--text);
      line-height: 1.4;
    }
    main { max-width: 1180px; margin: 0 auto; padding: 24px; }
    h1 { font-size: 26px; margin: 0 0 4px; letter-spacing: 0; }
    h2 { font-size: 17px; margin: 0 0 10px; letter-spacing: 0; }
    h3 { font-size: 14px; margin: 18px 0 8px; letter-spacing: 0; }
    table { border-collapse: collapse; width: 100%; margin-top: 10px; background: var(--surface); }
    th, td { border-bottom: 1px solid var(--border); padding: 7px 8px; text-align: left; vertical-align: top; }
    th { font-weight: 650; background: var(--surface-soft); color: var(--muted); }
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    .muted { color: var(--muted); font-size: 13px; }
    .summary-line { margin-top: 4px; }
    .notice { border-left: 4px solid var(--highlight); background: var(--notice-bg); padding: 9px 12px; margin: 10px 0; }
    .notice.warn { border-left-color: var(--danger); background: var(--warn-bg); }
    .dashboard-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 24px; margin-top: 18px; }
    .section { border-top: 1px solid var(--border); padding-top: 18px; }
    .chart-scroll { overflow-x: auto; padding-bottom: 4px; }
    .tooltip-chart-scroll {
      /* Horizontal scroll containers clip vertical overflow, so reserve a full multiline tooltip lane. */
      --chart-tooltip-top-reserve: 80px;
      padding-top: var(--chart-tooltip-top-reserve);
      margin-top: calc(12px - var(--chart-tooltip-top-reserve));
    }
    .heatmap-chart-scroll {
      padding-top: 56px;
      margin-top: -44px;
    }
    .chart-svg { display: block; width: 100%; height: auto; min-width: 680px; }
    .axis-line { stroke: var(--border); stroke-width: 1; }
    .axis-label { fill: var(--muted); font-size: 11px; }
    .bar-label { fill: var(--text); font-size: 12px; }
    .value-label { fill: var(--muted); font-size: 12px; }
    .cost-bar { fill: var(--accent); }
    .cost-bar:hover { fill: var(--accent-strong); }
    .daily-bar-chart {
      min-width: 680px;
      max-width: 920px;
      width: 100%;
    }
    .chart-max-label {
      color: var(--muted);
      font-size: 11px;
      margin: 0 18px 5px 54px;
      font-variant-numeric: tabular-nums;
    }
    .daily-bars {
      display: grid;
      grid-template-columns: repeat(var(--bar-count), minmax(5px, 1fr));
      gap: 3px;
      min-height: 226px;
      padding: 0 18px 0 54px;
    }
    .daily-bar-slot {
      display: grid;
      grid-template-rows: 200px 22px;
      min-width: 0;
      align-items: end;
    }
    .chart-bar-hit {
      position: relative;
      display: block;
      outline: none;
    }
    .daily-bar-hit {
      align-self: end;
      height: 200px;
      border-bottom: 1px solid var(--border);
    }
    .daily-bar-fill {
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      display: block;
      min-height: 1px;
      border-radius: 2px 2px 0 0;
      background: var(--accent);
    }
    .daily-bar-label {
      color: var(--muted);
      font-size: 11px;
      min-height: 16px;
      margin-top: 6px;
      overflow: hidden;
      text-align: center;
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
    }
    .chart-bar-hit:hover .daily-bar-fill,
    .chart-bar-hit:focus-visible .daily-bar-fill {
      background: var(--accent-strong);
    }
    .chart-bar-hit:hover,
    .chart-bar-hit:focus-visible {
      z-index: 2;
    }
    .chart-tooltip {
      position: absolute;
      left: 50%;
      bottom: calc(100% + 8px);
      z-index: 4;
      width: max-content;
      max-width: 280px;
      padding: 6px 8px;
      border-radius: 6px;
      background: var(--tooltip-bg);
      color: var(--tooltip-text);
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.22);
      font-size: 12px;
      line-height: 1.3;
      pointer-events: none;
      transform: translate(-50%, 2px);
      opacity: 0;
      visibility: hidden;
      transition: opacity 0.06s linear, transform 0.06s linear, visibility 0s linear 0.06s;
      white-space: normal;
    }
    .chart-bar-hit:hover .chart-tooltip,
    .chart-bar-hit:focus-visible .chart-tooltip {
      opacity: 1;
      visibility: visible;
      transform: translate(-50%, 0);
      transition-delay: 0s;
    }
    .chart-tooltip-main,
    .chart-tooltip-detail {
      display: block;
    }
    .chart-tooltip-detail {
      margin-top: 2px;
      opacity: 0.86;
    }
    .heatmap-grid {
      --heatmap-cell-size: 20px;
      display: grid;
      grid-template-columns: max-content repeat(24, var(--heatmap-cell-size));
      gap: 4px;
      align-items: center;
      width: max-content;
      min-width: 680px;
      margin-inline: auto;
      padding: 4px 0;
    }
    .heatmap-corner { width: 72px; }
    .heatmap-hour, .heatmap-day {
      color: var(--muted);
      font-size: 11px;
      font-variant-numeric: tabular-nums;
    }
    .heatmap-hour { text-align: center; min-height: 16px; }
    .heatmap-day { width: 72px; text-align: right; padding-right: 4px; }
    .heatmap-cell {
      position: relative;
      display: block;
      width: var(--heatmap-cell-size);
      height: var(--heatmap-cell-size);
      border: 1px solid var(--heat-stroke);
      border-radius: 4px;
      outline: none;
    }
    .heatmap-cell:hover,
    .heatmap-cell:focus-visible {
      border-color: var(--accent-strong);
      box-shadow: 0 0 0 2px var(--accent-soft);
      z-index: 2;
    }
    .heatmap-tooltip {
      position: absolute;
      left: 50%;
      bottom: calc(100% + 8px);
      z-index: 4;
      width: max-content;
      max-width: 260px;
      padding: 6px 8px;
      border-radius: 6px;
      background: var(--tooltip-bg);
      color: var(--tooltip-text);
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.22);
      font-size: 12px;
      line-height: 1.3;
      pointer-events: none;
      transform: translate(-50%, 2px);
      opacity: 0;
      visibility: hidden;
      transition: opacity 0.06s linear, transform 0.06s linear, visibility 0s linear 0.06s;
      white-space: normal;
    }
    .heatmap-cell:hover .heatmap-tooltip,
    .heatmap-cell:focus-visible .heatmap-tooltip {
      opacity: 1;
      visibility: visible;
      transform: translate(-50%, 0);
      transition-delay: 0s;
    }
    .heatmap-tooltip-main,
    .heatmap-tooltip-detail {
      display: block;
    }
    .heatmap-tooltip-detail {
      margin-top: 2px;
      opacity: 0.86;
    }
    .heat-cell { stroke: var(--heat-stroke); stroke-width: 1; }
    .heat-0 { fill: var(--heat-0); background: var(--heat-0); }
    .heat-1 { fill: var(--heat-1); background: var(--heat-1); }
    .heat-2 { fill: var(--heat-2); background: var(--heat-2); }
    .heat-3 { fill: var(--heat-3); background: var(--heat-3); }
    .heat-4 { fill: var(--heat-4); background: var(--heat-4); }
    .heat-5 { fill: var(--heat-5); background: var(--heat-5); }
    .empty-chart { fill: var(--muted); font-size: 14px; }
    .table-wrap { overflow-x: auto; }
    .section-help { margin: -4px 0 10px; }
    .storage-intro { max-width: 840px; margin: -2px 0 8px; }
    .storage-summary { margin: 0 0 12px; font-variant-numeric: tabular-nums; }
    .storage-chart-scroll { overflow-x: auto; padding: 82px 0 4px; margin-top: -70px; }
    .storage-chart {
      display: grid;
      gap: 10px;
      min-width: 680px;
      max-width: 920px;
      width: 100%;
    }
    .storage-bar-row {
      display: grid;
      grid-template-columns: minmax(130px, 200px) minmax(240px, 1fr) max-content;
      gap: 10px;
      align-items: center;
    }
    .storage-bar-label {
      overflow: hidden;
      color: var(--text);
      font-size: 12px;
      text-align: right;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .storage-track { height: 26px; min-width: 0; background: var(--surface-soft); border-radius: 4px; }
    .storage-stack {
      position: relative;
      display: flex;
      min-width: 1px;
      height: 100%;
      border-radius: 4px;
      outline: none;
      overflow: visible;
    }
    .storage-stack:focus-visible { box-shadow: 0 0 0 2px var(--accent-strong); z-index: 3; }
    .storage-segment { display: block; flex: 0 0 auto; min-width: 0; height: 100%; }
    .storage-root-segment { background: var(--accent); border-radius: 4px 0 0 4px; }
    .storage-descendant-segment { background: var(--highlight); border-radius: 0 4px 4px 0; }
    .storage-root-only .storage-root-segment,
    .storage-descendant-only .storage-descendant-segment { border-radius: 4px; }
    .storage-has-boundary .storage-root-segment { box-shadow: inset -2px 0 0 var(--surface-strong); }
    .storage-stack:hover .storage-root-segment,
    .storage-stack:focus-visible .storage-root-segment { filter: brightness(1.12); }
    .storage-stack:hover .storage-descendant-segment,
    .storage-stack:focus-visible .storage-descendant-segment { filter: brightness(1.12); }
    .storage-stack .chart-tooltip { left: 0; transform: translate(0, 2px); }
    .storage-stack:hover .chart-tooltip,
    .storage-stack:focus-visible .chart-tooltip { opacity: 1; visibility: visible; transform: translate(0, 0); transition-delay: 0s; }
    .storage-bar-value { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .storage-legend { display: flex; flex-wrap: wrap; gap: 6px 12px; margin: 2px 0 0 210px; color: var(--muted); font-size: 12px; }
    .storage-legend > span { display: inline-flex; align-items: center; gap: 5px; }
    .storage-swatch { display: inline-block; width: 10px; height: 10px; border: 1px solid var(--border); border-radius: 2px; }
    .storage-root-swatch { background: var(--accent); }
    .storage-descendant-swatch { background: var(--highlight); }
    .storage-task-title { display: block; font-weight: 650; overflow-wrap: anywhere; }
    code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; color: var(--muted); }
    .storage-badge { display: inline-block; margin: 1px 3px 1px 0; padding: 1px 5px; border: 1px solid var(--border); border-radius: 3px; color: var(--muted); font-size: 11px; white-space: nowrap; }
    .storage-badge.warn { border-color: var(--highlight); color: var(--highlight); }
    .storage-badge.danger { border-color: var(--danger); color: var(--danger); }
    .storage-diagnostics { margin: 10px 0 0; overflow-wrap: anywhere; }
    @media (max-width: 720px) {
      main { padding: 16px; }
      th, td { padding: 6px; }
      .storage-chart { min-width: 560px; }
      .storage-bar-row { grid-template-columns: 96px minmax(220px, 1fr) max-content; gap: 8px; }
      .storage-bar-label { text-align: left; }
      .storage-legend { margin-left: 104px; }
    }
""" + report_metric_strip_css() + report_views_css() + report_breakdown_css()
