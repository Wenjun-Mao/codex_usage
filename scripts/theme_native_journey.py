"""Rendered theme and issued-action journey in the script-disabled native webview."""
import asyncio
from hashlib import sha256
import json
import time
from urllib.parse import unquote

from speed_native_target import NativeSpeedTarget, attributes, node_text, nodes, wait_native_state


def decode_action(uri):
    return json.loads(unquote(uri.split('?', 1)[1]))[0]


async def read_speed(target):
    target.chart_class = 'observed-speed'
    try:
        return await NativeSpeedTarget.state(target, decode_action)
    finally:
        target.chart_class = 'usage-breakdown'


async def speed_action(target, label):
    before = await read_speed(target)
    target.chart_class = 'observed-speed'
    try:
        requested = await NativeSpeedTarget.click(target, label, decode_action)
    finally:
        target.chart_class = 'usage-breakdown'
    assert requested['granularity'] != before['granularity'] or requested['windowStart'] != before['window_start']
    while time.monotonic() < target.deadline:
        rendered = await read_speed(target)
        if (rendered and rendered['granularity'] == requested['granularity']
                and rendered['window_start'] == requested['windowStart']):
            return {'requested': requested, 'rendered': rendered}
        await asyncio.sleep(.02)
    raise TimeoutError('Issued speed action never rendered')


async def click_node(target, node):
    await target.send('DOM.scrollIntoViewIfNeeded', {'nodeId': node['nodeId']})
    quad = (await target.send('DOM.getContentQuads', {'nodeId': node['nodeId']}))['quads'][0]
    x, y = sum(quad[::2])/4, sum(quad[1::2])/4
    hit = await target.send('DOM.getNodeForLocation', {'x': round(x), 'y': round(y)})
    assert hit['backendNodeId'] in {n.get('backendNodeId') for n in nodes(node)}, 'Occluded native theme journey input'
    for event in ('mousePressed', 'mouseReleased'):
        await target.send('Input.dispatchMouseEvent', {'type': event, 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})
    await asyncio.sleep(.05)


async def open_history(target):
    document = await target.document()
    detail = next(n for n in nodes(document) if 'allowance-history-panel' in attributes(n).get('class', '').split())
    if 'open' not in attributes(detail):
        summary = next(n for n in nodes(detail) if n.get('nodeName') == 'SUMMARY' and node_text(n) == 'Allowance history')
        await click_node(target, summary)


async def allowance_dom(target, root, expected):
    while time.monotonic() < target.deadline:
        accepted = json.loads((root / 'last-report.json').read_text())['allowance']
        document = await target.document()
        inspection = next((n for n in nodes(document) if 'allowance-history-inspection' in attributes(n).get('class', '').split()), None)
        scopes = {decode_action(attributes(n)['href'])['scope'] for n in nodes(document)
            if attributes(n).get('href', '').startswith('command:codexUsage.navigateAllowanceHistory?')}
        if accepted['state'] == expected and inspection and scopes == {accepted['scope']}:
            text = node_text(inspection)
            if 'Observed at' in text and any('allowance-observations' in attributes(n).get('class', '').split() for n in nodes(inspection)):
                await open_history(target)
                document = await target.document()
                inspection = next(n for n in nodes(document) if 'allowance-history-inspection' in attributes(n).get('class', '').split())
                box = (await target.send('DOM.getBoxModel', {'nodeId': inspection['nodeId']}))['model']
                assert box['width'] > 0 and box['height'] > 0
                return {'state': accepted['state'], 'scope': accepted['scope'], 'inspection_visible': True, 'has_observations': True,
                    'inspection_sha256': sha256(node_text(inspection).encode()).hexdigest()}
        await asyncio.sleep(.02)
    raise TimeoutError('Issued allowance inspection never rendered')


async def allowance_action(target, root, kind):
    await open_history(target)
    document = await target.document()
    links = [n for n in nodes(document) if attributes(n).get('href', '').startswith('command:codexUsage.navigateAllowanceHistory?')]
    before = json.loads((root / 'last-report.json').read_text())['allowance']['state']
    for candidate in links:
        requested = decode_action(attributes(candidate)['href'])
        if requested['state']['kind'] == kind and requested['state'] != before:
            if (await target.send('DOM.getContentQuads', {'nodeId': candidate['nodeId']}))['quads']:
                await click_node(target, candidate)
                rendered = await allowance_dom(target, root, requested['state'])
                return {'requested': requested, 'rendered': rendered}
    raise AssertionError('Visible noncurrent issued allowance action absent')


async def theme_snapshot(target, root, theme, expected_palette, allowance_state):
    await target.send('DOM.enable')
    await target.send('CSS.enable')
    document = await target.document()
    html = next(n for n in nodes(document) if 'data-codex-theme' in attributes(n))
    assert attributes(html)['data-codex-theme'] == theme
    text = node_text(html)
    assert 'Usage & Allowance Breakdown' in text and 'Observed Output Speed' in text
    assert f'Theme: {theme.title()}' in text and 'Loading usage' not in text
    body = next(n for n in nodes(html) if n.get('nodeName') == 'BODY')
    style = {s['name']: s['value'] for s in (await target.send(
        'CSS.getComputedStyleForNode', {'nodeId': body['nodeId']}))['computedStyle']}
    assert (style['background-color'], style['color']) == expected_palette
    return {'theme': theme, 'background': style['background-color'], 'color': style['color'],
        'breakdown': await target.state(None), 'speed': await read_speed(target),
        'allowance': await allowance_dom(target, root, allowance_state), 'complete_content': True}


async def theme_journey(target, root, output):
    from check_usage_breakdown_webview import decode
    await speed_action(target, 'Hourly')
    await speed_action(target, 'Previous')
    seeded = await allowance_action(target, root, 'periods')
    initial = await target.state(None)
    initial_speed = await read_speed(target)
    initial_allowance = seeded['rendered']
    records = []
    night = ('rgb(16, 19, 22)', 'rgb(237, 242, 245)')
    day = ('rgb(245, 247, 249)', 'rgb(23, 32, 39)')
    for serial, (theme, editor, palette) in enumerate([
        ('night', None, night), ('day', None, day),
        ('auto', 'Default Dark Modern', ('rgb(31, 31, 31)', 'rgb(204, 204, 204)')),
        ('auto', 'Default Light Modern', day), ('night', None, night)], 1):
        (root / 'theme-request.json').write_text(json.dumps({'serial': serial, 'theme': theme, 'editorTheme': editor}))
        while time.monotonic() < target.deadline:
            assigned_path = root / 'theme-assigned.json'
            if assigned_path.exists():
                assigned = json.loads(assigned_path.read_text())
                if assigned['serial'] == serial:
                    break
            await asyncio.sleep(.01)
        else:
            raise TimeoutError('Native theme configuration did not settle')
        while time.monotonic() < target.deadline:
            try:
                snapshot = await theme_snapshot(target, root, theme, palette, initial_allowance['state'])
                break
            except (AssertionError, StopIteration, RuntimeError):
                await asyncio.sleep(.01)
        else:
            raise TimeoutError('Native theme report never fully rendered in requested colors')
        assert snapshot['breakdown'] == initial, 'Theme lost selected chart/window/detail state'
        assert snapshot['speed'] == initial_speed, 'Theme lost speed granularity/window'
        assert snapshot['allowance'] == initial_allowance, 'Theme lost allowance inspection'
        await target.page.screenshot(path=str(output / f'native-theme-{serial}.png'))
        snapshot.update(editor_theme=editor, serial=serial, seconds=time.time()-assigned['started']/1000,
            screenshot=f'native-theme-{serial}.png', configuration_persisted=assigned['theme'] == theme)
        records.append(snapshot)
    before = await target.state(decode)
    requested = await target.click('API cost', decode)
    assert requested['state'] != before['state']
    rendered = await wait_native_state(target, requested, decode, lambda s, a: s['state'] == a['state'])
    assert json.loads((root / 'last-report.json').read_text())['breakdown']['state'] == requested['state']
    breakdown = {'before': before, 'requested': requested, 'rendered': rendered}
    speed = await speed_action(target, 'Daily')
    allowance = await allowance_action(target, root, 'periods')
    assert allowance['rendered']['inspection_sha256'] != initial_allowance['inspection_sha256']
    assert allowance['rendered']['state'] != initial_allowance['state']
    await target.page.screenshot(path=str(output / 'native-theme-actions.png'))
    return {'initial_state': initial, 'initial_speed': initial_speed, 'initial_allowance': initial_allowance,
        'updates': records, 'script_disabled': True, 'breakdown': breakdown, 'speed': speed,
        'allowance': allowance, 'action_screenshot': 'native-theme-actions.png'}
