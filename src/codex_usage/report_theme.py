from __future__ import annotations

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
      --day-bg: #f7f8fa;
      --day-bg-strong: #eef0f3;
      --day-surface: #ffffff;
      --day-surface-strong: #ffffff;
      --day-surface-soft: #f4f6f8;
      --day-surface-muted: #eef1f5;
      --day-text: #0a0b0d;
      --day-muted: #5b616e;
      --day-muted-soft: #7c828a;
      --day-accent: #0052ff;
      --day-accent-strong: #003ecc;
      --day-accent-soft: rgba(0, 82, 255, 0.08);
      --day-highlight: #f4b000;
      --day-success: #05b169;
      --day-danger: #cf202f;
      --day-border: #dee1e6;
      --day-border-soft: #eef0f3;
      --day-shadow-soft: 0 1px 2px rgba(10, 11, 13, 0.06);

      --night-bg: #0d0f12;
      --night-bg-strong: #14171c;
      --night-surface: #161a20;
      --night-surface-strong: #1d222a;
      --night-surface-soft: #202631;
      --night-surface-muted: #2a313b;
      --night-text: #eef2f6;
      --night-muted: #a7b0bc;
      --night-muted-soft: #7f8996;
      --night-accent: #4f83ff;
      --night-accent-strong: #7da3ff;
      --night-accent-soft: rgba(79, 131, 255, 0.16);
      --night-highlight: #d8a72f;
      --night-success: #31c98a;
      --night-danger: #ff6b78;
      --night-border: #303844;
      --night-border-soft: #252c35;
      --night-shadow-soft: 0 1px 2px rgba(0, 0, 0, 0.22);

      --bg: #f7f8fa;
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
      --notice-bg: #fff7ed;
      --warn-bg: #fef3f2;
      --heat-0: #eef1f5;
      --heat-1: #dbeafe;
      --heat-2: #93c5fd;
      --heat-3: #3b82f6;
      --heat-4: #1d4ed8;
      --heat-5: #f4b000;
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
      --notice-bg: rgba(216, 167, 47, 0.14);
      --warn-bg: rgba(255, 107, 120, 0.14);
      --heat-0: #202631;
      --heat-1: #1e3a5f;
      --heat-2: #2f5fbe;
      --heat-3: #4f83ff;
      --heat-4: #7da3ff;
      --heat-5: #d8a72f;
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
        --notice-bg: rgba(216, 167, 47, 0.14);
        --warn-bg: rgba(255, 107, 120, 0.14);
        --heat-0: #202631;
        --heat-1: #1e3a5f;
        --heat-2: #2f5fbe;
        --heat-3: #4f83ff;
        --heat-4: #7da3ff;
        --heat-5: #d8a72f;
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
      --notice-bg: rgba(216, 167, 47, 0.14);
      --warn-bg: rgba(255, 107, 120, 0.14);
      --heat-0: #202631;
      --heat-1: #1e3a5f;
      --heat-2: #2f5fbe;
      --heat-3: #4f83ff;
      --heat-4: #7da3ff;
      --heat-5: #d8a72f;
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
    .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; margin: 20px 0 18px; }
    .kpi { border: 1px solid var(--border); border-radius: 8px; background: var(--surface); box-shadow: var(--shadow-soft); padding: 12px; min-height: 92px; }
    .kpi-label { color: var(--muted); font-size: 12px; text-transform: uppercase; }
    .kpi-value { display: block; font-size: 23px; font-weight: 700; margin-top: 6px; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
    .kpi-detail { color: var(--muted); font-size: 12px; margin-top: 4px; }
    .notice { border-left: 4px solid var(--highlight); background: var(--notice-bg); padding: 9px 12px; margin: 10px 0; }
    .notice.warn { border-left-color: var(--danger); background: var(--warn-bg); }
    .dashboard-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 24px; margin-top: 18px; }
    .section { border-top: 1px solid var(--border); padding-top: 18px; }
    .chart-scroll { overflow-x: auto; padding-bottom: 4px; }
    .chart-svg { display: block; width: 100%; height: auto; min-width: 680px; }
    .axis-line { stroke: var(--border); stroke-width: 1; }
    .axis-label { fill: var(--muted); font-size: 11px; }
    .bar-label { fill: var(--text); font-size: 12px; }
    .value-label { fill: var(--muted); font-size: 12px; }
    .cost-bar { fill: var(--accent); }
    .cost-bar:hover, .breakdown-bar:hover { fill: var(--accent-strong); }
    .breakdown-bar { fill: var(--highlight); }
    .heatmap-grid {
      --heatmap-cell-size: 20px;
      display: grid;
      grid-template-columns: max-content repeat(24, var(--heatmap-cell-size));
      gap: 4px;
      align-items: center;
      width: max-content;
      min-width: 680px;
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
    .heatmap-legend { margin: 8px 0 0 82px; }
    .heat-cell { stroke: var(--heat-stroke); stroke-width: 1; }
    .heat-0 { fill: var(--heat-0); background: var(--heat-0); }
    .heat-1 { fill: var(--heat-1); background: var(--heat-1); }
    .heat-2 { fill: var(--heat-2); background: var(--heat-2); }
    .heat-3 { fill: var(--heat-3); background: var(--heat-3); }
    .heat-4 { fill: var(--heat-4); background: var(--heat-4); }
    .heat-5 { fill: var(--heat-5); background: var(--heat-5); }
    .empty-chart { fill: var(--muted); font-size: 14px; }
    .table-wrap { overflow-x: auto; }
    @media (max-width: 720px) {
      main { padding: 16px; }
      .kpi-value { font-size: 20px; }
      th, td { padding: 6px; }
    }
"""
