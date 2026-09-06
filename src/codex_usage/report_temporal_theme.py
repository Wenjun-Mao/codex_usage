from __future__ import annotations


def report_temporal_css() -> str:
    return """
    .cost-granularity-input {
      position: absolute;
      width: 1px;
      height: 1px;
      opacity: 0;
      pointer-events: none;
    }
    .cost-granularity-toolbar {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 7px;
      min-height: 28px;
      margin: -38px 0 10px;
    }
    .cost-granularity-label { color: var(--muted); font-size: 11px; font-weight: 650; }
    .cost-granularity-options {
      display: inline-flex;
      overflow: hidden;
      border: 1px solid var(--border);
      border-radius: 4px;
      background: var(--surface);
    }
    .cost-granularity-options label {
      min-width: 64px;
      padding: 4px 10px;
      color: var(--muted);
      cursor: pointer;
      font-size: 11px;
      font-weight: 650;
      text-align: center;
    }
    .cost-granularity-options label + label { border-left: 1px solid var(--border); }
    #cost-trend-week:checked ~ .cost-granularity-toolbar label[for="cost-trend-week"],
    #cost-trend-month:checked ~ .cost-granularity-toolbar label[for="cost-trend-month"] {
      background: var(--surface-soft);
      color: var(--text);
    }
    #cost-trend-week:focus-visible ~ .cost-granularity-toolbar label[for="cost-trend-week"],
    #cost-trend-month:focus-visible ~ .cost-granularity-toolbar label[for="cost-trend-month"] {
      outline: 2px solid var(--accent-strong);
      outline-offset: -2px;
    }
    .cost-trend-month-panel { display: none; }
    #cost-trend-month:checked ~ .cost-trend-panels .cost-trend-week-panel { display: none; }
    #cost-trend-month:checked ~ .cost-trend-panels .cost-trend-month-panel { display: block; }
    .daily-bar-chart.temporal-week,
    .daily-bar-chart.temporal-month {
      min-width: 0;
      width: 100%;
    }
    .temporal-week .daily-bars,
    .temporal-month .daily-bars {
      grid-template-columns: repeat(var(--bar-count), minmax(1px, 1fr));
      gap: clamp(1px, 0.3vw, 3px);
    }
    .daily-bar-label.tick-wide { visibility: visible; }
    @media (max-width: 820px) {
      .daily-bar-label { visibility: hidden; }
      .daily-bar-label.tick-medium { visibility: visible; }
      .cost-granularity-toolbar { margin-top: 0; justify-content: flex-start; }
    }
    @media (max-width: 520px) {
      .daily-bar-label { visibility: hidden; }
      .daily-bar-label.tick-narrow { visibility: visible; }
    }
    """
