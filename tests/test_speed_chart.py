from datetime import UTC, datetime
import re

from codex_usage.report_speed import render_speed, speed_css
from codex_usage.report_speed_chart import nice_scale, render_plot, selection_band, tick_indices, x_position
from codex_usage.report_speed_marks import MARKERS, series_labels, short_model_label
from codex_usage.model_presentation import assign_model_color_slots
from codex_usage.report_speed import detail
from codex_usage.speed_queries import calendar_buckets


def navigation(granularity="daily", start="2026-10-02", end="2026-10-08"):
    return {"scope": "a" * 64, "granularity": granularity,
            "min_date": "2026-09-09", "max_date": "2026-10-08",
            "window_start": start, "window_end": end,
            "previous": "2026-09-25", "next": None}


def point(bucket, model="gpt-6.1-sol", value=43, n=20):
    return {"model": model, "bucket": bucket, "median": value, "p25": value - 3,
            "p75": value + 3, "n": n, "tasks": 2, "sources": 2, "small": n < 20}


def aggregates(daily=(), hourly=()):
    return {"summaries": {"gpt-6.1-sol": {"n": 20}}, "daily": list(daily),
            "hourly": list(hourly), "reasons": {}}


def test_daily_ticks_preserve_endpoints_without_crowding():
    nav = navigation()
    buckets = calendar_buckets(nav, UTC)
    for budget in (220, 350, 550):
        indices = tick_indices(buckets, "daily", budget)
        assert indices[0] == 0 and indices[-1] == len(buckets) - 1
        assert all((right - left) * budget / (len(buckets) - 1) >= 72
                   for left, right in zip(indices, indices[1:]))
        assert not {len(buckets) - 2, len(buckets) - 1}.issubset(indices)


def test_singleton_and_hourly_ticks():
    assert tick_indices(["2026-10-08"], "daily", 220) == [0]
    assert x_position(0, 1) == 50
    nav = navigation("hourly")
    buckets = calendar_buckets(nav, UTC)
    for budget in (220, 350, 550):
        indices = tick_indices(buckets, "hourly", budget)
        assert indices[0] == 0 and indices[-1] == 167
        assert all((right - left) * budget / 167 >= 72
                   for left, right in zip(indices, indices[1:]))


def test_nice_numeric_scale_is_above_interval_and_uses_readable_ticks():
    ceiling, ticks = nice_scale([point("2026-10-08", value=55.5)])
    assert ceiling > 58.5
    assert ticks[0] == 0 and ticks[-1] == ceiling
    assert ticks == [0, 20, 40, 60, 80]


def test_daily_fits_container_with_full_scope_and_global_backfill_label():
    rendered = render_speed(aggregates([point("2026-10-07"), point("2026-10-08")]),
                            navigation(), {"complete": 4, "unmeasurable": 2, "pending": 120}, UTC)
    assert '<svg width="100%" height="224" role="group"' in rendered
    assert 'class="speed-y-axis"' in rendered and 'class="speed-x-axis"' in rendered
    assert "Sep 9 - Oct 8, 2026" in rendered and "30 days" in rendered
    assert "Account-wide timing history: 6 sources checked &middot; 120 pending" in rendered
    assert 'id="speed-detail-0"' in rendered and 'id="speed-detail-1"' in rendered
    assert "speed-scroll" not in rendered


def test_empty_hourly_window_preserves_populated_full_range_overview_and_latest_jump():
    nav = navigation("hourly", "2026-09-18", "2026-09-24")
    nav.update(previous="2026-09-11", next="2026-09-25")
    rendered = render_speed(aggregates([point("2026-10-07"), point("2026-10-08")]), nav, {}, UTC)
    assert "Daily overview" in rendered and "Sep 9 - Oct 8, 2026" in rendered
    assert "Hourly detail &middot; 7 of 30 days" in rendered
    assert "No measurable speed in this window." in rendered
    assert "Latest week</a>" in rendered and "%222026-10-02%22" in rendered
    assert 'class="speed-selection"' in rendered
    assert 'class="speed-chart"' not in rendered
    assert 'href="#speed-detail-' not in rendered


def test_hourly_single_day_has_no_redundant_overview():
    nav = navigation("hourly", "2026-10-08", "2026-10-08")
    nav.update(min_date="2026-10-08", previous=None)
    bucket = datetime(2026, 10, 8, 12, tzinfo=UTC).isoformat()
    rendered = render_speed(aggregates(hourly=[point(bucket)]), nav, {}, UTC)
    assert "Hourly detail &middot; 1 of 1 day" in rendered
    assert 'class="speed-overview"' not in rendered
    assert 'href="#speed-detail-0"' in rendered


def test_selection_band_uses_local_dates_not_hour_counts():
    buckets = [f"2026-11-{day:02d}" for day in range(1, 11)]
    band = selection_band(buckets, "2026-11-01", "2026-11-07")
    assert 'x="0.0000%"' in band and 'width="71.3333%"' in band
    assert 'width="100.0000%"' in selection_band(["2026-11-01"], "2026-11-01", "2026-11-01")


def test_current_models_have_distinct_fixed_size_markers_and_matching_legend():
    models = ('gpt-6.1-sol', 'gpt-6-astra', 'gpt-6-luna')
    slots = assign_model_color_slots(models)
    assert len({MARKERS[slots[model]] for model in models}) == 3
    data = aggregates([point('2026-10-08', model=model) for model in models])
    data['summaries'] = {model: {'n': 20} for model in models}
    rendered = render_speed(data, navigation(), {}, UTC)
    for model in models:
        assert f'data-model-slot="{slots[model]}"' in rendered
        assert f'<strong>{short_model_label(model)}</strong>' in rendered
    assert rendered.count('class="speed-marker"') == 3
    assert rendered.count('class="speed-series-label"') == 3


def test_spread_and_small_samples_have_separate_point_semantics():
    rendered, rows = render_plot([point('2026-10-08', n=8)], ['2026-10-08'],
                                ['gpt-6.1-sol'], {'gpt-6.1-sol': 6}, detail)
    assert 'class="speed-point speed-point-small"' in rendered
    assert 'class="speed-interval"' in rendered
    assert 'stroke-dasharray' not in rendered
    assert 'middle 50% 40.0-46.0; 8 responses' in rendered
    assert len(rows) == 1 and '<td>40.0-46.0</td>' in rows[0]


def test_last_measured_label_survives_trailing_gaps_without_connecting_them():
    rendered, _ = render_plot([point('2026-10-07')], ['2026-10-07', '2026-10-08'],
                             ['gpt-6.1-sol'], {'gpt-6.1-sol': 6}, detail)
    assert '<small>43.0 tok/s</small>' in rendered
    assert 'title="gpt-6.1-sol; 2026-10-07"' in rendered
    assert 'stroke-width="2"' not in rendered


def test_series_label_collisions_are_resolved_inside_plot_bounds():
    models = ('gpt-6.1-sol', 'gpt-6-astra', 'gpt-6-luna')
    endpoints = [{'model': model, 'median': 80, 'y': 100, 'bucket': '2026-10-08'} for model in models]
    rendered = series_labels(endpoints, assign_model_color_slots(models), top=10, span=200)
    positions = [float(value) for value in re.findall(r'top:([\d.]+)px', rendered)]
    assert positions[0] >= 10 and positions[-1] + 28 <= 210
    assert all(right - left >= 28 for left, right in zip(positions, positions[1:]))


def test_many_or_long_model_labels_use_a_flowing_list_and_escape_content():
    models = [f'model-{index}-long-<name>' for index in range(8)]
    endpoints = [{'model': model, 'median': 80, 'y': 100, 'bucket': '2026-10-08'} for model in models]
    rendered = series_labels(endpoints, {model: index % 7 for index, model in enumerate(models)}, top=10, span=200)
    assert 'speed-series-labels speed-series-list' in rendered
    assert '<name>' not in rendered and '&lt;name&gt;' in rendered
    assert rendered.count('class="speed-series-label"') == 8


def test_decorative_segments_cannot_intercept_marker_hover():
    rendered, _ = render_plot([point('2026-10-07'), point('2026-10-08')],
                             ['2026-10-07', '2026-10-08'], ['gpt-6.1-sol'],
                             {'gpt-6.1-sol': 6}, detail)
    assert rendered.count('class="speed-trend"') == 1
    assert '.speed-grid,.speed-trend { pointer-events:none; }' in speed_css()
