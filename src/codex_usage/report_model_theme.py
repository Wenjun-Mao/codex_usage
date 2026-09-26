from __future__ import annotations


def report_model_css() -> str:
    return """
    .model-details-help { max-width: 850px; }
    .model-details-table { min-width: 620px; }
    .model-summary-row th { font-weight: 650; }
    .model-breakdown-row > td { padding: 0 8px 9px; }
    .model-breakdown { margin-left: 8px; }
    .model-breakdown > summary { cursor: pointer; color: var(--highlight); padding: 5px 0; }
    .model-breakdown > summary:focus-visible { outline: 2px solid var(--highlight); outline-offset: 2px; }
    .model-breakdown .table-wrap { margin: 2px 0 0 10px; }
    .model-breakdown table { min-width: 460px; margin-top: 0; }
    .model-breakdown table th, .model-breakdown table td { padding: 5px 8px; }
    .model-breakdown p { max-width: 800px; margin: 8px 0 0 10px; }
    .model-partial { color: var(--muted); font-size: 11px; }
    @media (max-width: 720px) {
      .model-details-table { min-width: 560px; }
      .model-breakdown { margin-left: 0; }
      .model-breakdown .table-wrap, .model-breakdown p { margin-left: 0; }
    }
"""
