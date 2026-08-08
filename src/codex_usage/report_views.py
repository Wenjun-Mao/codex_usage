from __future__ import annotations

import html

USAGE_REPORT_VIEW = "usage"
STORAGE_REPORT_VIEW = "task-storage"


def render_report_view_tabs() -> str:
    return (
        '<nav class="report-view-tabs" aria-label="Report views">'
        f'<a class="report-view-tab report-view-tab-usage" '
        f'data-report-view-link="{USAGE_REPORT_VIEW}" '
        f'href="#report-view-{USAGE_REPORT_VIEW}" '
        f'aria-controls="report-{USAGE_REPORT_VIEW}">Usage</a>'
        f'<a class="report-view-tab report-view-tab-storage" '
        f'data-report-view-link="{STORAGE_REPORT_VIEW}" '
        f'href="#report-view-{STORAGE_REPORT_VIEW}" '
        f'aria-controls="report-{STORAGE_REPORT_VIEW}">Task Storage</a>'
        "</nav>"
    )


def render_report_view_targets() -> str:
    return (
        f'<span id="report-view-{USAGE_REPORT_VIEW}" '
        f'class="report-view-target report-view-target-usage" aria-hidden="true"></span>'
        f'<span id="report-view-{STORAGE_REPORT_VIEW}" '
        f'class="report-view-target report-view-target-storage" aria-hidden="true"></span>'
    )


def render_report_view(view: str, body: str) -> str:
    if view not in {USAGE_REPORT_VIEW, STORAGE_REPORT_VIEW}:
        raise ValueError(f"unknown report view: {view}")
    label = "Usage" if view == USAGE_REPORT_VIEW else "Task Storage"
    return (
        f'<section id="report-{html.escape(view, quote=True)}" '
        f'class="report-view report-view-{html.escape(view, quote=True)}" '
        f'data-report-view="{html.escape(view, quote=True)}" '
        f'aria-label="{html.escape(label, quote=True)}">'
        f"{body}</section>"
    )


def report_views_css() -> str:
    return """
    .report-view-tabs {
      display: flex;
      gap: 22px;
      margin: 20px 0 0;
      overflow-x: auto;
      border-bottom: 1px solid var(--border);
    }
    .report-view-target {
      display: block;
      width: 0;
      height: 0;
      overflow: hidden;
    }
    .report-view-tab {
      display: inline-flex;
      flex: 0 0 auto;
      align-items: center;
      min-height: 38px;
      padding: 7px 2px 8px;
      border-bottom: 2px solid transparent;
      color: var(--muted);
      font-size: 14px;
      font-weight: 650;
      text-decoration: none;
      white-space: nowrap;
    }
    .report-view-tab:hover { color: var(--text); }
    .report-view-tab:focus-visible {
      border-radius: 3px;
      outline: 2px solid var(--accent-strong);
      outline-offset: 2px;
    }
    .report-view-tab-usage {
      border-bottom-color: var(--accent);
      color: var(--text);
    }
    .report-view {
      display: none;
      min-width: 0;
      padding-top: 18px;
    }
    .report-view-usage { display: block; }
    .report-view > .section:first-child {
      border-top: 0;
      padding-top: 0;
    }
    .usage-view-context { margin-bottom: 4px; }

    .report-shell:has(.report-view-target-storage:target) .report-view-usage {
      display: none;
    }
    .report-shell:has(.report-view-target-storage:target) .report-view-task-storage {
      display: block;
    }
    .report-shell:has(.report-view-target-storage:target) .report-view-tab-usage {
      border-bottom-color: transparent;
      color: var(--muted);
    }
    .report-shell:has(.report-view-target-storage:target) .report-view-tab-storage {
      border-bottom-color: var(--accent);
      color: var(--text);
    }

    .report-shell[data-active-report-view] .report-view { display: none; }
    .report-shell[data-active-report-view="usage"] .report-view-usage,
    .report-shell[data-active-report-view="task-storage"] .report-view-task-storage {
      display: block;
    }
    .report-shell[data-active-report-view] .report-view-tab {
      border-bottom-color: transparent;
      color: var(--muted);
    }
    .report-shell[data-active-report-view="usage"] .report-view-tab-usage,
    .report-shell[data-active-report-view="task-storage"] .report-view-tab-storage {
      border-bottom-color: var(--accent);
      color: var(--text);
    }
    @media (max-width: 720px) {
      .report-view-tabs { gap: 18px; margin-top: 16px; }
      .report-view { padding-top: 16px; }
    }
"""
