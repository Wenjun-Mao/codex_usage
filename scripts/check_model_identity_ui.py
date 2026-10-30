"""Computed model colors and geometry on public synthetic script-free reports.

Uses the existing report fixtures and Playwright layout contract. This focused
check supplements the speed/breakdown suites with cross-renderer identity.
"""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright

from codex_usage.model_presentation import model_color_slot
from model_identity_fixture import MODELS, prepare, render, move
from verification.breakdown_layout import SNAPSHOT, assert_layout


SNAPSHOT_IDENTITY = """() => {
    const all = s => [...document.querySelectorAll(s)];
    const shape = e => {const c = e.querySelector('rect,circle,path');
        return [c.tagName,...[...c.attributes].map(a=>[a.name,a.value]).sort()];};
    return {
      legends:all('.speed-legend>span').map(e=>({model:e.textContent,
        color:getComputedStyle(e.querySelector('svg')).color,shape:shape(e)})),
      marks:all('.speed-marker').map(e=>({slot:+e.dataset.modelSlot,
        color:getComputedStyle(e).color, shape:shape(e)})),
      bars:all('.ub-scroll svg rect').filter(e=>e.querySelector('desc')).map(e=>({
        model:e.querySelector('desc').textContent.split(' | ')[1].split(': ')[0],
        color:getComputedStyle(e).fill})),
      swatches:all('.ub-usage-heading .ub-legend>span,.usage-breakdown>.ub-legend>span')
        .map(e=>({model:e.textContent,color:getComputedStyle(e.querySelector('i')).backgroundColor})),
      tips:all('.ub-hover-row').map(e=>({model:e.children[1].textContent,
        color:getComputedStyle(e.querySelector('i')).backgroundColor})),
      stacks:all('.ub-stack>span').map(e=>({model:e.title.split(' | ')[1].split(': ')[0],
        color:getComputedStyle(e).backgroundColor})),
      comparison:all('.model-segment,.model-mix-fill').map(e=>({
        slot:+[...e.classList].find(c=>c.startsWith('model-color-slot-')).split('-').pop(),
        color:getComputedStyle(e).backgroundColor, label:e.getAttribute('aria-label')})),
      comparisonLegend:all('.model-legend-item').map(e=>({model:e.textContent.trim(),
        color:getComputedStyle(e.querySelector('.model-swatch>span')).backgroundColor})),
      small:all('.speed-point-small .speed-marker').map(e=>({
        fill:getComputedStyle(e).fill,stroke:getComputedStyle(e).stroke,color:getComputedStyle(e).color})),
      unknown:all('.ub-scroll svg path').filter(e=>e.querySelector('desc')?.textContent.includes('Unknown'))
        .map(e=>({fill:getComputedStyle(e).fill,stroke:getComputedStyle(e).stroke})),
      overflow:document.documentElement.scrollWidth>innerWidth+1,
      scripts:document.querySelectorAll('script').length,
    };
}"""


def verify(page, *, forced=False):
    result = page.evaluate(SNAPSHOT_IDENTITY)
    assert result['scripts'] == 0 and not result['overflow']
    legends = {row['model']: row for row in result['legends']}
    assert legends and 'gpt-6.1-terra' in legends
    expected = {}
    for model, row in legends.items():
        slot = model_color_slot(model)
        expected[slot] = row
        for peer in legends.values():
            if model_color_slot(peer['model']) == slot:
                assert peer['color'] == row['color'] and peer['shape'] == row['shape']
    for row in result['marks']:
        assert row['shape'] == expected[row['slot']]['shape']
        assert row['color'] == expected[row['slot']]['color']
    comparisons = 0
    for category in ('bars', 'swatches', 'tips', 'stacks', 'comparisonLegend'):
        for row in result[category]:
            if row['model'] in legends:
                assert row['color'] == legends[row['model']]['color'], (category, row, legends[row['model']])
                comparisons += 1
    for row in result['comparison']:
        if row['slot'] != 7:
            assert row['color'] == expected[row['slot']]['color'], row
    for row in result['small']:
        assert row['fill'] != row['color'] and row['stroke'] == row['color'], row
    for row in result['unknown']:
        assert row['fill'] == 'none' and row['stroke'] != 'none'
    # SVG templates are the same in compact overview, detail, and point legend.
    assert len(result['marks']) > len(MODELS)
    if not forced:
        assert len({row['color'] for row in legends.values()}) == 8
    return {'color_comparisons': comparisons, 'model_points': len(result['marks']),
            'small_sample_points': len(result['small']), 'unknown_marks': len(result['unknown']),
            'identities': legends}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    evidence = {'synthetic_only': True, 'javascript_disabled': True, 'views': []}
    with TemporaryDirectory(prefix='model-identity-ui-') as raw:
        home = Path(raw)
        prepare(home)
        reports = {}
        for theme in ('day', 'night'):
            reports[theme, 'all-hourly'] = render(home, theme=theme, speed_granularity='hourly')
            for scenario, range_name, projects in (('all', 'all', ()), ('range', '7d', ()),
                                                  ('project-filter', 'all', ('/synthetic/project',))):
                report = render(home, theme=theme, range_name=range_name, projects=projects)
                options = dict(theme=theme, range_name=range_name, projects=projects)
                # Cost view retains unknown diamonds; tokens paint every model.
                reports[theme, scenario+'-cost'] = report
                tokens = move(home, report, metric='tokens', **options)
                reports[theme, scenario+'-tokens'] = tokens
                reports[theme, scenario+'-stacks'] = move(home, tokens, view='project', **options)
        with sync_playwright() as playwright:
            for engine in ('chromium', 'webkit', 'firefox'):
                browser = getattr(playwright, engine).launch()
                context = browser.new_context(java_script_enabled=False)
                try:
                    page = context.new_page()
                    for (theme, scenario), report in reports.items():
                        document = args.output / f'{theme}-{scenario}.html'
                        document.write_text(report.html)
                        for width in (1440, 360):
                            page.set_viewport_size({'width': width, 'height': 1000})
                            page.goto(document.resolve().as_uri())
                            result = verify(page)
                            if not scenario.endswith('stacks'):
                                assert_layout(page.evaluate(SNAPSHOT), scenario, report.breakdown_navigation['state'])
                            if engine == 'chromium' and scenario.startswith('all-'):
                                for selector, name in (('.usage-breakdown', 'usage'), ('.observed-speed', 'speed'),
                                                       ('.usage-comparison', 'comparison')):
                                    page.locator(selector).screenshot(path=str(args.output / f'{theme}-{scenario}-{width}-{name}.png'))
                            evidence['views'].append(dict(engine=engine, theme=theme, scenario=scenario,
                                                          width=width, **result))
                    if engine == 'chromium':
                        for theme in ('day', 'night'):
                            page.emulate_media(forced_colors='active')
                            page.goto((args.output / f'{theme}-all-tokens.html').resolve().as_uri())
                            evidence['views'].append(dict(engine=engine, theme=theme, scenario='forced-colors',
                                width=360, **verify(page, forced=True)))
                            page.locator('.usage-breakdown').screenshot(path=str(args.output / f'{theme}-forced-colors.png'))
                        page.emulate_media(forced_colors='none')
                finally:
                    context.close()
                    browser.close()
    (args.output / 'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
    print(json.dumps({'status': 'passed', 'views': len(evidence['views'])}))


if __name__ == '__main__':
    main()
