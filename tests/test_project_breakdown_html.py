from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re

from codex_usage.aggregation import summarize_records
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.report_breakdown import OTHER_MODEL_KEY, build_report_breakdown
from codex_usage.reporting import render_html_report


def test_project_breakdown_renders_nested_roles_models_and_shared_legend(
    tmp_path: Path,
) -> None:
    html = _render_report(
        tmp_path,
        [
            _record("root", "gpt-5.6-sol", 600),
            _record("root", "gpt-5.6-terra", 400),
            _record("subagent", "gpt-5.6-terra", 75),
            _record("subagent", "gpt-5.6-luna", 25),
        ],
    )

    for section_id in (
        "daily-cost",
        "hourly-heatmap",
        "project-breakdown",
        "project-details",
        "model-mix",
        "model-details",
    ):
        assert f'data-report-section="{section_id}"' in html
    assert 'class="project-breakdown-chart" role="group"' in html
    assert 'class="project-breakdown-matrix" role="table"' in html
    assert 'class="project-breakdown-header" role="row"' in html
    assert html.count('<span class="role-column-heading" role="columnheader">Root tasks</span>') == 1
    assert html.count('<span class="role-column-heading" role="columnheader">Subagents</span>') == 1
    assert 'class="project-role-cell project-role-cell-root"' in html
    assert 'class="project-role-cell project-role-cell-subagent"' in html
    assert 'role="group" aria-label="demo Root tasks' in html
    assert 'tabindex="0"' in html
    assert "demo, Root tasks, gpt-5.6-sol" in html
    assert "tokens, 54.5% of project" in html
    assert 'class="model-color-slot-1"' in html
    assert 'class="model-color-slot-2"' in html
    assert 'class="model-color-slot-3"' in html
    assert 'class="model-segment model-color-slot-1"' in html
    assert 'class="model-segment model-color-slot-2"' in html
    assert 'class="project-role-metric-cost">$' in html
    assert 'id="project-scale-tokens" value="tokens" checked' in html
    assert 'id="project-scale-cost" value="cost"' in html
    assert '<label for="project-scale-tokens">Tokens</label>' in html
    assert '<label for="project-scale-cost">API cost</label>' in html

    legend_html = html.split('<div class="model-legend" aria-label="Model colors">', 1)[
        1
    ].split("</div>", 1)[0]
    for model in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
        assert legend_html.count(f">{model}</span>") == 1
    assert "model-mix-fill model-color-slot-1" in html
    assert "model-mix-fill model-color-slot-2" in html
    assert "model-mix-fill model-color-slot-3" in html


def test_project_breakdown_role_edges_keep_tiny_positive_shares_accessible(
    tmp_path: Path,
) -> None:
    root_only_html = _render_report(tmp_path, [_record("root", "gpt-5.6-sol", 10)])
    subagent_only_html = _render_report(
        tmp_path, [_record("subagent", "gpt-5.6-terra", 10)]
    )
    tiny_share_html = _render_report(
        tmp_path,
        [
            _record("root", "gpt-5.6-sol", 9_999),
            _record("subagent", "gpt-5.6-terra", 1),
        ],
    )

    assert (
        'class="project-role-fill" style="--token-width:100.0000%;--cost-width:100.0000%"'
        in root_only_html
    )
    assert 'aria-label="demo Subagents, no usage"' in root_only_html
    assert 'aria-label="demo Root tasks, no usage"' in subagent_only_html
    assert (
        'class="project-role-fill" style="--token-width:100.0000%;--cost-width:100.0000%"'
        in subagent_only_html
    )
    assert tiny_share_html.count("--token-width:100.0000%;--cost-width:100.0000%") >= 2
    assert (
        "demo, Subagents, gpt-5.6-terra, 1 tokens, 0.0% of project" in tiny_share_html
    )
    assert "--token-width:1.0000%" not in tiny_share_html


def test_project_breakdown_scales_each_role_column_independently(
    tmp_path: Path,
) -> None:
    html = _render_report(
        tmp_path,
        [
            _record("root", "gpt-5.6-sol", 1_000, project="alpha"),
            _record("subagent", "gpt-5.6-terra", 10, project="alpha"),
            _record("root", "gpt-5.6-sol", 500, project="beta"),
            _record("subagent", "gpt-5.6-terra", 20, project="beta"),
        ],
    )

    alpha = html.split('data-project-key="alpha"', 1)[1].split(
        '<div class="project-breakdown-row"', 1
    )[0]
    beta = html.split('data-project-key="beta"', 1)[1].split(
        '<div class="model-legend"', 1
    )[0]

    assert 'style="--token-width:100.0000%;--cost-width:100.0000%"' in alpha
    assert re.search(
        r'style="--token-width:50\.0000%;--cost-width:[\d.]+%"', alpha
    )
    assert re.search(
        r'style="--token-width:50\.0000%;--cost-width:[\d.]+%"', beta
    )
    assert 'style="--token-width:100.0000%;--cost-width:100.0000%"' in beta


def test_project_breakdown_exposes_distinct_token_and_cost_scales(tmp_path: Path) -> None:
    html = _render_report(
        tmp_path,
        [
            _record("root", "gpt-5.6-sol", 1_000, project="sol-project"),
            _record("root", "gpt-5.6-luna", 1_000, project="luna-project"),
        ],
    )

    luna = html.split('data-project-key="luna-project"', 1)[1].split(
        '<div class="model-legend"', 1
    )[0]
    outer_fill = re.search(
        r'class="project-role-fill" style="--token-width:(?P<tokens>[\d.]+)%;'
        r'--cost-width:(?P<cost>[\d.]+)%"',
        luna,
    )

    assert outer_fill is not None
    assert float(outer_fill.group("tokens")) == 100.0
    assert 0 < float(outer_fill.group("cost")) < 100.0
    assert (
        "#project-scale-cost:checked ~ .project-breakdown-matrix .project-role-fill"
        in html
    )
    assert (
        "#project-scale-cost:checked ~ .project-breakdown-matrix .project-role-cost-share"
        in html
    )


def test_project_details_and_exact_model_details_keep_complete_disclosures(
    tmp_path: Path,
) -> None:
    records = [
        _record("root", "gpt-5.6-sol", 100),
        _record("subagent", "unknown-model", 5),
        *[_record("root", f"model-{index}", 20 - index) for index in range(8)],
    ]
    html = _render_report(tmp_path, records)

    assert 'data-report-section="project-details"' in html
    assert 'data-report-section="model-details"' in html
    assert '<th class="num">Root Tokens</th>' in html
    assert '<th class="num">Subagent Tokens</th>' in html
    assert '<td class="num">100</td>' in html
    assert '<td class="num">5</td>' in html
    assert "unknown-model" in html
    assert "API-excluded" in html
    assert "without credit rates" in html
    assert OTHER_MODEL_KEY not in html
    assert ">Other</span>" in html
    for index in range(8):
        assert f">model-{index}</td>" in html
    assert "model-color-slot-7" in html


def test_project_breakdown_empty_state_and_styles_are_self_contained(
    tmp_path: Path,
) -> None:
    html = _render_report(tmp_path, [])

    assert html.count("<svg") == 4
    assert "No usage found for this range." in html
    assert "--model-0: #087f8c;" in html
    assert "--model-1: #c47f00;" in html
    assert "--model-2: #2e8b57;" in html
    assert "--model-7: #8b949f;" in html
    assert "body.vscode-high-contrast" in html
    assert ".model-segment:focus-visible" in html
    assert 'grid-template-areas: "project total" "root root" "subagent subagent";' in html
    assert "<script" not in html
    assert " src=" not in html
    assert 'href="#report-view-usage"' in html
    assert 'href="#report-view-task-storage"' in html
    assert 'href="http://' not in html and 'href="https://' not in html


def test_breakdown_css_keeps_high_contrast_focus_and_boundaries_distinct(
    tmp_path: Path,
) -> None:
    html = _render_report(tmp_path, [])

    assert "--model-0: var(--text);" in html
    assert "--model-separator: var(--bg);" in html
    assert "--model-focus-inner: var(--bg);" in html
    assert "--model-focus-outer: var(--accent);" in html
    assert (
        "box-shadow: inset 0 0 0 2px var(--model-focus-inner), 0 0 0 2px var(--model-focus-outer);"
        in html
    )
    assert "box-shadow: inset 2px 0 0 var(--model-separator);" in html


def test_breakdown_css_uses_non_layout_segment_and_model_mix_boundaries(
    tmp_path: Path,
) -> None:
    html = _render_report(tmp_path, [])

    segment_css = html.split(".model-segment {", 1)[1].split("}", 1)[0]
    model_mix_css = html.split(".model-mix-fill {", 1)[1].split("}", 1)[0]

    assert "border:" not in segment_css
    assert "min-width:" not in segment_css
    assert "border:" not in model_mix_css
    assert "min-width:" not in model_mix_css
    assert "box-shadow: inset 1px 0 0 var(--model-separator);" in html
    assert "box-shadow: inset 0 0 0 1px var(--model-separator);" in html


def test_project_role_fill_boundary_keeps_tooltips_outside_its_clip(tmp_path: Path) -> None:
    html = _render_report(tmp_path, [])

    role_group_css = html.split(".project-role-group {", 1)[1].split("}", 1)[0]

    assert "overflow: visible;" in role_group_css
    assert ".model-segment:first-child { border-radius: 3px 0 0 3px; }" in html
    assert ".model-segment:last-child { border-radius: 0 3px 3px 0; }" in html
    assert ".model-segment:only-child { border-radius: 3px; }" in html
    assert ".project-role-cell-root .model-segment:first-child .chart-tooltip" in html
    assert ".project-role-cell-subagent .model-segment:last-child .chart-tooltip" in html


def test_project_role_cells_reserve_space_for_metrics_and_tracks(tmp_path: Path) -> None:
    html = _render_report(tmp_path, [])

    assert ".project-role-metric {" in html
    assert ".project-role-track { min-width: 0; height: 30px;" in html
    assert (
        ".project-role-fill { min-width: 0; width: var(--token-width, 0%); height: 100%; }"
        in html
    )


def test_project_rows_share_role_columns_and_headings_render_once(
    tmp_path: Path,
) -> None:
    html = _render_report(
        tmp_path,
        [
            _record("root", "gpt-5.6-sol", 9_999),
            _record("subagent", "gpt-5.6-terra", 1),
        ],
    )

    assert ".project-breakdown-header, .project-breakdown-row { display: contents; }" in html
    assert "grid-column: 1 / -1;" in html
    assert (
        "grid-template-columns: minmax(120px, 190px) minmax(190px, 1fr) "
        "minmax(190px, 1fr) max-content;" in html
    )
    header = html.split('<div class="project-breakdown-header" role="row">', 1)[1].split(
        "</div>", 1
    )[0]
    assert header.count('role="columnheader"') == 4
    assert header.count("Root tasks") == 1
    assert header.count("Subagents") == 1


def test_model_mix_rows_share_one_track_grid(tmp_path: Path) -> None:
    html = _render_report(tmp_path, [])

    assert ".model-mix-row { display: contents; }" in html
    assert (
        "grid-template-columns: minmax(120px, 200px) minmax(220px, 1fr) max-content;"
        in html
    )


def test_model_details_keeps_all_exact_models_beyond_two_hundred_rows(
    tmp_path: Path,
) -> None:
    html = _render_report(
        tmp_path,
        [_record("root", f"model-{index:03d}", 1) for index in range(201)],
    )

    model_details = html.split(
        '<section class="report-table-section" data-report-section="model-details">', 1
    )[1].split("</section>", 1)[0]
    assert model_details.count("<tr>") == 202
    assert ">model-000</td>" in model_details
    assert ">model-200</td>" in model_details


def _render_report(tmp_path: Path, records: list[UsageRecord]) -> str:
    output = tmp_path / "report.html"
    total = summarize_records(records)
    render_html_report(
        output_path=output,
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        range_name="all",
        total=total,
        daily_rows=[],
        hourly_rows=[],
        breakdown=build_report_breakdown(records),
        sessions_dirs=[Path("sessions")],
        files_scanned=len(records),
    )
    return output.read_text(encoding="utf-8")


def _record(
    role: str, model: str, total: int, *, project: str = "demo"
) -> UsageRecord:
    return UsageRecord(
        timestamp=datetime(2026, 8, 1, tzinfo=UTC),
        usage=TokenUsage(
            input_tokens=total,
            cached_input_tokens=total // 4,
            cache_write_input_tokens=total // 10,
            output_tokens=total // 10,
            total_tokens=total,
        ),
        session_id=f"{project}-{role}-{model}",
        file_path=Path("/tmp/session.jsonl"),
        usage_role=role,  # type: ignore[arg-type]
        model=model,
        project_key=project,
        project_label=project,
    )
