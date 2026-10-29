"""Selective native DOM reads keep representative report observation bounded."""
import json
from time import perf_counter

from speed_native_target import NativeSpeedTarget, attributes, nodes


class ThemeTarget(NativeSpeedTarget):
    cached_root = None

    async def send(self, method, params=None):
        started = perf_counter()
        result = await super().send(method, params)
        if not hasattr(self, 'observations'):
            self.observations = []
        self.observations.append({'method': method, 'seconds': perf_counter()-started})
        return result

    def begin_snapshot(self):
        self.cached_root = None

    async def content_root(self):
        if self.cached_root is not None:
            return self.cached_root
        root = (await self.send('DOM.getDocument', {'depth': 4, 'pierce': True}))['root']
        self.shallow_document = root
        documents = [n['contentDocument'] for n in nodes(root) if n.get('contentDocument')]
        assert documents, 'Native report iframe absent'
        self.cached_root = documents[-1]['nodeId']
        return self.cached_root

    async def select(self, selector):
        root = await self.content_root()
        identity = (await self.send('DOM.querySelector', {'nodeId': root, 'selector': selector}))['nodeId']
        return identity

    async def describe(self, selector, depth=0):
        identity = await self.select(selector)
        assert identity, f'Native rendered selector absent: {selector}'
        return (await self.send('DOM.describeNode', {'nodeId': identity, 'depth': depth}))['node']

    async def state(self, _decode):
        try:
            chart = await self.describe('.usage-breakdown')
            return {'scope': attributes(chart)['data-scope'], 'state': json.loads(attributes(chart)['data-state'])}
        except (RuntimeError, AssertionError, KeyError):
            self.cached_root = None
            # A real webview document replacement can invalidate node IDs between
            # CDP replies. Initial attachment keeps polling until the report exists.
            return None

    async def visible(self, selector):
        identity = await self.select(selector)
        assert identity, selector
        style = {s['name']: s['value'] for s in (await self.send('CSS.getComputedStyleForNode',
            {'nodeId': identity}))['computedStyle']}
        assert style['display'] != 'none' and style['visibility'] == 'visible' and style['opacity'] != '0', selector
        box = (await self.send('DOM.getBoxModel', {'nodeId': identity}))['model']
        assert box['width'] > 0 and box['height'] > 0, selector
        return style
