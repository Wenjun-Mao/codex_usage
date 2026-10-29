"""Explicit deferred-history input in the existing exact-package native journey."""
import asyncio
from hashlib import sha256
import json
import time

from speed_native_target import attributes, node_text, nodes


def current_content(document):
    classes = {'allowance-economic', 'allowance-bucket', 'allowance-credit-balance'}
    return sha256(json.dumps([node_text(n) for n in nodes(document)
        if classes.intersection(attributes(n).get('class', '').split())]).encode()).hexdigest()


def allowance_links(document, decode):
    return [(n, decode(attributes(n)['href'])) for n in nodes(document)
        if attributes(n).get('href', '').startswith('command:codexUsage.navigateAllowanceHistory?')]


def history_rows(panel):
    return [n for n in nodes(panel) if {'allowance-history-item', 'allowance-reset-row'}.intersection(
        attributes(n).get('class', '').split())]


async def deferred_history_journey(target, root, output):
    from theme_native_journey import click_node, decode_action
    before = json.loads((root/'last-report.json').read_text())['allowance']
    assert before['deferred'] is True and len(before['actions']) == 1
    requests = json.loads((root/'report-requests.json').read_text())
    assert len(requests) >= 22 and all(r['history_mode'] == 'deferred' and not r['allowance_action']
                                     and r['deferred'] is True for r in requests)
    updates = []
    for serial, theme in enumerate(('night', 'day'), 1):
        (root/'theme-request.json').write_text(json.dumps(dict(serial=serial, theme=theme, phase='unrequested')))
        while time.monotonic() < target.deadline:
            assigned_path = root/'theme-assigned.json'
            if assigned_path.exists():
                assigned = json.loads(assigned_path.read_text())
                if assigned.get('phase') == 'unrequested' and assigned['serial'] == serial:
                    break
            await asyncio.sleep(.01)
        else:
            raise TimeoutError('Unrequested history theme update did not settle')
        while time.monotonic() < target.deadline:
            accepted = json.loads((root/'last-report.json').read_text())['allowance']
            document = await target.document()
            html = next(n for n in nodes(document) if 'data-codex-theme' in attributes(n))
            links = allowance_links(document, decode_action)
            if (attributes(html)['data-codex-theme'] == theme and accepted == before
                    and len(links) == 1 and node_text(links[0][0]) == 'Load allowance history'):
                break
            await asyncio.sleep(.02)
        else:
            raise TimeoutError('Unclicked history changed through theme refresh')
        screenshot = f'native-history-unrequested-{serial}.png'
        await target.page.screenshot(path=str(output/screenshot))
        updates.append(dict(theme=theme, serial=serial, deferred=True, scope=accepted['scope'], screenshot=screenshot))
    document = await target.document()
    current = current_content(document)
    links = allowance_links(document, decode_action)
    link, action = links[0]
    assert action in before['actions'] and node_text(link) == 'Load allowance history'
    started = time.monotonic()
    await click_node(target, link)
    while time.monotonic() < target.deadline:
        accepted = json.loads((root/'last-report.json').read_text())['allowance']
        document = await target.document()
        links = allowance_links(document, decode_action)
        panel = next(n for n in nodes(document) if 'allowance-history-panel' in attributes(n).get('class', '').split())
        items = history_rows(panel)
        scopes = {a['scope'] for _, a in links}
        if (not accepted.get('deferred') and accepted['state'] == action['state']
                and scopes == {accepted['scope']} and accepted['scope'] != action['scope']
                and items and 'open' in attributes(panel)
                and not any(node_text(n) == 'Load allowance history' for n, _ in links)):
            box = (await target.send('DOM.getBoxModel', {'nodeId': items[0]['nodeId']}))['model']
            assert box['width'] > 0 and box['height'] > 0
            assert current_content(document) == current, 'History load changed current allowance figures'
            requests = json.loads((root/'report-requests.json').read_text())
            assert requests[-1]['history_mode'] == 'requested' and requests[-1]['allowance_action'] == action
            screenshot = 'native-history-loaded.png'
            await target.page.screenshot(path=str(output/screenshot))
            return dict(unrequested_reports=len(requests)-1, unrequested_scope=before['scope'], updates=updates,
                requested=action, response_scope=accepted['scope'], rendered_scope=next(iter(scopes)),
                rendered_state=accepted['state'], current_before=current, current_after=current_content(document),
                history_visible=True, issued_origin_verified=True, seconds=time.monotonic()-started, screenshot=screenshot)
        await asyncio.sleep(.02)
    raise TimeoutError('Explicit issued history load never rendered')
