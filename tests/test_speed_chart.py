from datetime import UTC, datetime
from copy import deepcopy
import re
from xml.etree import ElementTree

import pytest

from codex_usage.report_speed import render_speed, speed_css
from codex_usage.report_speed_chart import nice_scale, render_plot, selection_band, tick_indices, x_position
from codex_usage.report_speed_marks import MARKERS, bucket_label, series_labels, short_model_label
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
    assert 'Typical range (middle 50%): 40.0-46.0 tokens/s&#10;8 responses across 2 tasks' in rendered
    assert len(rows) == 1 and '<td>40.0-46.0</td>' in rows[0]


def test_last_measured_label_survives_trailing_gaps_without_connecting_them():
    rendered, _ = render_plot([point('2026-10-07')], ['2026-10-07', '2026-10-08'],
                             ['gpt-6.1-sol'], {'gpt-6.1-sol': 6}, detail)
    assert '<small>43.0 tok/s</small>' in rendered
    root = ElementTree.fromstring(rendered)
    label = root.find(".//span[@class='speed-series-label']")
    assert label.get('title') is None and label.get('data-speed-tip') == 'series-0'
    tooltip = root.find(".//span[@data-speed-tip-for='series-0']")
    assert [line.text for line in tooltip] == ['Sol 6.1', 'Oct 7, 2026', 'Median speed: 43.0 tokens/s']
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


@pytest.mark.parametrize('bucket,label', [
    ('2026-10-17', 'Oct 17, 2026'),
    ('2026-10-17T20:00:00-04:00', 'Oct 17, 2026 at 20:00 (UTC-04:00)'),
    ('2026-11-01T01:00:00-04:00', 'Nov 1, 2026 at 01:00 (UTC-04:00)'),
    ('2026-11-01T01:00:00-05:00', 'Nov 1, 2026 at 01:00 (UTC-05:00)'),
    ('2026-10-17T20:00:00+05:45', 'Oct 17, 2026 at 20:00 (UTC+05:45)'),
    ('2026-10-17T20:00:00+10:30', 'Oct 17, 2026 at 20:00 (UTC+10:30)'),
    ('2026-10-17T00:00:00+00:00', 'Oct 17, 2026 at 00:00 (UTC+00:00)'),
])
def test_tooltip_dates_are_readable_without_losing_bucket_offsets(bucket, label):
    assert bucket_label(bucket) == label


def test_point_tooltip_has_labeled_lines_and_preserves_exact_detail_rows():
    bucket = '2026-10-17T20:00:00-04:00'
    stats = {**point(bucket, value=57.6, n=11), 'p25': 54.7, 'p75': 60.2, 'tasks': 3, 'sources': 3}
    before = deepcopy(stats)
    rendered, rows = render_plot([stats], [bucket], ['gpt-6.1-sol'], {'gpt-6.1-sol': 6}, detail)
    root = ElementTree.fromstring(rendered)
    target = root.find('.//a')
    expected = ['Sol 6.1', 'Oct 17, 2026 at 20:00 (UTC-04:00)',
        'Median speed: 57.6 tokens/s', 'Typical range (middle 50%): 54.7-60.2 tokens/s',
        '11 responses across 3 tasks', 'Small sample (fewer than 20 responses)']
    tooltip = root.find(".//span[@data-speed-tip-for='point-0']")
    assert [line.text for line in tooltip] == expected
    assert target.get('aria-label').splitlines() == expected
    assert target.find('title') is None
    assert 'sources' not in ''.join(tooltip.itertext())
    assert root.find('.//time').get('datetime') == bucket
    row = ElementTree.fromstring(rows[0])
    assert row.find('th').text == 'gpt-6.1-sol'
    assert [cell.text for cell in row.findall('td')] == [bucket, '57.6', '54.7-60.2', '11', '3', '3']
    assert stats == before


def test_tooltip_counts_use_grouping_pluralization_and_conditional_sample_note():
    label = detail({**point('2026-10-17', n=1200), 'tasks': 1})
    assert label.splitlines()[-1] == '1,200 responses across 1 task'
    assert 'Small sample' not in label
    assert detail({'median': None, 'n': 4}).splitlines() == [
        'Not enough data', '4 eligible responses (at least 5 needed)']
    assert '1 eligible response (at least 5 needed)' in detail({'median': None, 'n': 1})


def test_unknown_model_names_are_escaped_in_readable_tooltips():
    model = 'custom-<unsafe>"&'
    bucket = '2026-10-17'
    rendered, _ = render_plot([point(bucket, model=model)], [bucket], [model], {model: 1}, detail)
    root = ElementTree.fromstring(rendered)
    assert root.find('.//a').get('aria-label').startswith(model + '\nOct 17, 2026\n')
    assert root.find(".//span[@data-speed-tip-for='point-0']/strong").text == model
    assert root.findall('.//unsafe') == []


def test_speed_tooltips_are_script_free_without_native_point_popup_or_delay():
    bucket = '2026-10-17'
    rendered, _ = render_plot([point(bucket)], [bucket], ['gpt-6.1-sol'], {'gpt-6.1-sol': 6}, detail)
    root = ElementTree.fromstring(rendered)
    assert root.findall('.//svg//title') == []
    assert root.findall('.//script') == []
    tip = root.find(".//span[@data-speed-tip-for='point-0']")
    assert tip.get('role') == 'tooltip' and tip.get('aria-hidden') == 'true'
    rules = ''.join(style.text for style in root.findall('.//style'))
    assert ':hover)' in rules and ':focus-visible)' in rules
    assert ':not(:has([data-speed-tip]:hover))' in rules
    assert 'transition:none' in speed_css()
    overview, _ = render_plot([point(bucket)], [bucket], ['gpt-6.1-sol'], {'gpt-6.1-sol': 6}, detail, overview=True)
    root = ElementTree.fromstring(overview)
    assert root.findall('.//title') == [] and root.findall('.//a') == []
    assert root.find('.//g[@data-speed-tip="overview-0"]').find('.//circle') is not None
    assert root.find(".//span[@data-speed-tip-for='overview-0']") is not None
