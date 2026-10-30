"""Model identity survives chart membership; semantic indicators remain separate."""
from datetime import UTC
from pathlib import Path
from runpy import run_path
from unittest.mock import patch
import re
import pytest
from xml.etree import ElementTree as ET

from codex_usage.model_presentation import assign_model_color_slots
from codex_usage.report_speed import render_speed
from codex_usage.report_speed_marks import MARKERS
from codex_usage.report_usage_breakdown_chart import plot


MODELS = ('gpt-6-astra', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna',
          'gpt-6-sol', 'gpt-6-luna', 'gpt-6.1-sol', 'gpt-6.1-terra',
          'custom-one', 'custom-two', 'custom-three')


def test_identity_is_independent_of_membership_order_and_case():
    slots = assign_model_color_slots(MODELS)
    assert slots['gpt-6.1-terra'] == 8
    assert set(slots.values()) <= {0, 1, 2, 3, 4, 5, 6, 8}
    assert assign_model_color_slots(tuple(reversed(MODELS))) == slots
    for model, slot in slots.items():
        assert assign_model_color_slots((model,))[model] == slot
        assert assign_model_color_slots((model.upper(),))[model.upper()] == slot
        assert MARKERS[slot]


def speed_document(models, *, hourly=False):
    points = [dict(model=model, bucket='2026-10-08', median=20+i*3,
        p25=15+i*3, p75=25+i*3, n=8 if i == 0 else 20, tasks=2,
        sources=2, small=i == 0) for i, model in enumerate(models)]
    nav = dict(scope='a'*64, granularity='hourly' if hourly else 'daily',
        min_date='2026-10-01', max_date='2026-10-08', window_start='2026-10-02',
        window_end='2026-10-08', previous='2026-10-01', next=None)
    data = dict(summaries={m: {} for m in models}, daily=points,
        hourly=[{**p, 'bucket': p['bucket']+'T12:00:00+00:00'} for p in points], reasons={})
    return render_speed(data, nav, {}, UTC)


def test_usage_marks_legends_and_tooltips_share_speed_identity_with_overflow():
    slots = assign_model_color_slots(MODELS)
    for models in (MODELS, tuple(reversed(MODELS)), MODELS[6:]):
        usage = plot([{model: 10 for model in models}], metric='cost', labels=models,
                     incomplete=[True], color_domain='model')
        speed = speed_document(models)
        root = ET.fromstring(('<main>'+usage+speed+'</main>').replace('&middot;', '&#183;'))
        bars = root.findall('.//div[@class="ub-scroll"]/svg/rect')
        assert len(bars) == len(models)
        for model, bar in zip(models, bars):
            color = f'var(--model-{slots[model]})'
            assert bar.get('fill') == color
            assert f'background:{color}' in usage
            assert model in bar.find('desc').text
            legend = next(e for e in root.findall('.//div[@class="speed-legend"]/span')
                          if ''.join(e.itertext()) == model)
            assert legend.find('svg').get('style') == f'color:{color}'
            mark = root.find(f'.//g[@data-model-slot="{slots[model]}"]')
            assert ET.tostring(mark[0]) == ET.tostring(legend.find('svg')[0])
        assert 'Unknown or API-excluded cost; not zero' in usage
        assert 'fill="none" stroke="var(--text)"' in usage
        assert 'speed-point-small' in speed


def test_overview_points_use_the_same_model_shapes_as_detail_and_legend():
    root = ET.fromstring(speed_document(MODELS, hourly=True).replace('&middot;', '&#183;'))
    for model, slot in assign_model_color_slots(MODELS).items():
        overview = root.find(f'.//div[@class="speed-overview"]//g[@data-model-slot="{slot}"]')
        assert overview is not None, model
        primitive = overview.find('.//'+ET.fromstring(MARKERS[slot]).tag)
        assert primitive is not None


def test_project_color_domain_keeps_its_separate_palette():
    from codex_usage.report_usage_breakdown_chart import COLORS
    document = plot([{'project': 10}], metric='tokens', labels=['project'], color_domain='project')
    assert f'fill="{COLORS[0]}"' in document
    other = plot([{'__other_projects__': 10}], metric='tokens',
                 labels=['__other_projects__'], color_domain='project')
    assert 'fill="var(--model-7)"' in other


def report_fixture():
    return run_path(str(Path(__file__).resolve().parents[1] / 'scripts/model_identity_fixture.py'))


def test_full_reports_keep_model_identity_through_filters_and_project_stacks(tmp_path):
    fixture = report_fixture()
    fixture['prepare'](tmp_path)
    for theme in ('day', 'night'):
        for range_name, projects in (('all', ()), ('7d', ()), ('all', ('/synthetic/project',))):
            options = dict(theme=theme, range_name=range_name, projects=projects)
            report = fixture['render'](tmp_path, **options)
            assert 'gpt-6.1-terra' in report.html
            assert 'Unknown or API-excluded cost; not zero' in report.html
            report = fixture['move'](tmp_path, report, metric='tokens', **options)
            for view in ('time', 'project'):
                current = report if view == 'time' else fixture['move'](
                    tmp_path, report, view='project', **options)
                section = current.html.split('<section class="section usage-breakdown"', 1)[1]
                section = section.split('<section class="section observed-speed"', 1)[0]
                for model in MODELS:
                    slot = assign_model_color_slots((model,))[model]
                    assert f'background:var(--model-{slot})' in section
                    if view == 'time':
                        assert re.search(rf'fill="var\(--model-{slot}\)"><desc>[^<]*{re.escape(model)}:', section)
                    else:
                        assert re.search(rf'background:var\(--model-{slot}\)" title="[^"<>]* \| {re.escape(model)}:', section)
                    assert f'color:var(--model-{slot})' in current.html
                for slot, label in re.findall(
                    r'class="model-segment model-color-slot-(\d+)"[^>]*aria-label="([^"]+)"', current.html
                ):
                    if slot != '7':
                        model = label.split(', ')[2]
                        assert int(slot) == assign_model_color_slots((model,))[model]
            hourly = fixture['move'](tmp_path, report, grain='hourly', detail='', **options)
            assert 'background:var(--model-8)' in hourly.html


@pytest.mark.parametrize('revision,old_value', [
    ('codex_usage.agent_reports.REPORT_RENDER_REVISION', 45),
    ('codex_usage.speed_reports.SPEED_RENDER_REVISION', 2),
    ('codex_usage.breakdown_reports.BREAKDOWN_RENDER_REVISION', 1),
])
def test_presentation_revisions_invalidate_existing_html_without_changing_values(tmp_path, revision, old_value):
    fixture = report_fixture()
    path = fixture['prepare'](tmp_path)
    from codex_usage.ledger_schema import open_ledger
    with open_ledger(path, read_only=True) as connection:
        before = [tuple(row) for row in connection.execute('select * from ledger_usage_events')]
    # Populate precisely the old presentation namespaces, then read the same
    # ledger with current revisions. No source refresh or ledger reset is needed.
    with patch(revision, old_value):
        old = fixture['render'](tmp_path)
        assert fixture['render'](tmp_path).cache_hit
    current = fixture['render'](tmp_path)
    if 'BREAKDOWN_RENDER' not in revision:
        assert not current.cache_hit
    if 'SPEED_RENDER' not in revision:
        assert current.breakdown_navigation['scope'] != old.breakdown_navigation['scope']
    assert fixture['render'](tmp_path).cache_hit
    with open_ledger(path, read_only=True) as connection:
        assert [tuple(row) for row in connection.execute('select * from ledger_usage_events')] == before
