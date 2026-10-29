"""Observe actual current markup and reset rows, independent of old list layouts."""
from copy import deepcopy
from datetime import UTC, datetime
from html.parser import HTMLParser

from codex_usage.report_allowance import render_allowance_section
from release_tooling_support import load_tool

native = load_tool('allowance_native_journey')
fixtures = load_tool('allowance_fixture')
periods = load_tool('allowance_period_fixture')


class DOM(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.root = dict(nodeType=1, nodeName='ROOT', children=[])
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = dict(nodeType=1, nodeName=tag.upper(), attributes=[v or '' for pair in attrs for v in pair], children=[])
        self.stack[-1]['children'].append(node)
        if tag not in {'meta','br','hr','input','img','link'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack)-1, 0, -1):
            if self.stack[index]['nodeName'] == tag.upper():
                self.stack = self.stack[:index]
                break

    def handle_data(self, data):
        self.stack[-1]['children'].append(dict(nodeType=3, nodeValue=data))


def signature(report):
    return native.current_content(DOM(render_allowance_section(report,
        now=datetime(2026,9,2,16,tzinfo=UTC))).root)


def test_current_observation_covers_real_headline_pace_and_balance_but_not_history():
    original = fixtures.allowance_fixture()
    before = signature(original)
    for change in ('headline','pace','balance'):
        report = deepcopy(original)
        if change == 'headline':
            report['headline']['estimate']['value'] += 123
        elif change == 'pace':
            report['paces'][0] = []
        else:
            report['status']['credits']['balance'] = '123'
        assert signature(report) != before, change
    report = deepcopy(original)
    report['windows'][0]['estimate']['value'] += 123
    assert signature(report) == before


def test_native_history_observation_selects_current_reset_table_rows(tmp_path):
    report = periods.reset_economics_fixture(tmp_path)
    document = DOM(render_allowance_section(report)).root
    rows = native.history_rows(document)
    assert rows
    assert any('allowance-reset-row' in node['attributes'] for node in rows)
