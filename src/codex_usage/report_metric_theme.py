from __future__ import annotations


def report_metric_strip_css() -> str:
    return """
    .kpis { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); margin: 20px 0 18px; border-block: 1px solid var(--border); }
    .kpi { min-width: 0; padding: 13px 12px; border-right: 1px solid var(--border); }
    .kpi:last-child { border-right: 0; }
    .kpi-label { color: var(--muted); font-size: 11px; text-transform: uppercase; }
    .kpi-value { display: block; margin-top: 5px; font-size: 21px; font-weight: 700; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
    .kpi-detail { color: var(--muted); font-size: 11px; margin-top: 3px; }
    @media (max-width: 720px) {
      .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .kpi { border-bottom: 1px solid var(--border); }
      .kpi:nth-child(2n) { border-right: 0; }
      .kpi:last-child { grid-column: 1 / -1; border-bottom: 0; }
      .kpi-value { font-size: 20px; }
    }
    @media (max-width: 430px) {
      .kpis { grid-template-columns: minmax(0, 1fr); }
      .kpi { border-right: 0; }
      .kpi:last-child { grid-column: auto; }
    }
"""
