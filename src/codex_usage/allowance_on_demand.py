"""Companion-only history presentation, isolated from eager report consumers."""
import json

from codex_usage.allowance_history_navigation import DEFAULT_STATE, digest, issued_receipt
from codex_usage.allowance_report_codec import REPORT_FORMAT, decode_report, encode_report

DEFERRED_SUFFIX = ':deferred-history-1'
DEFERRED_FORMAT = 'allowance-deferred-history-1'


def current_projection(report):
    """Keep every current calculation; remove only detailed capture membership."""
    windows = [dict(window, points=[]) for window in report['windows']]
    positions = {id(window): index for index, window in enumerate(report['windows'])}
    result = {key: value for key, value in report.items()
              if key not in {'display_history', 'reset_history'}}
    result['windows'] = windows
    for key in ('qualified', 'history'):
        result[key] = [windows[positions[id(window)]] for window in report[key]]
    result['headline'] = None if report['headline'] is None else windows[positions[id(report['headline'])]]
    result['history_deferred'] = True
    return result


def encode_deferred(report):
    return json.dumps(dict(format=DEFERRED_FORMAT, payload=json.loads(encode_report(report))), allow_nan=False)


def decode_deferred(payload):
    data = json.loads(payload)
    if not isinstance(data, dict) or set(data) != {'format', 'payload'} or data['format'] != DEFERRED_FORMAT:
        raise ValueError('Invalid deferred allowance format')
    if not isinstance(data['payload'], dict) or data['payload'].get('format') != REPORT_FORMAT:
        raise ValueError('Invalid deferred allowance payload')
    try:
        report = decode_report(json.dumps(data['payload'], allow_nan=False))
    except (AttributeError, TypeError, KeyError, IndexError) as error:
        raise ValueError('Invalid deferred allowance shape') from error
    required = {'status', 'credits', 'paces', 'windows', 'qualified', 'headline',
                'headline_previous', 'history', 'history_deferred'}
    if (not isinstance(report, dict) or set(report) != required
            or any(not isinstance(report[key], list) for key in ('paces','windows','qualified','history'))
            or not isinstance(report['credits'], dict) or type(report['headline_previous']) is not bool):
        raise ValueError('Incomplete deferred allowance contents')
    if (report.get('history_deferred') is not True or 'display_history' in report
            or 'reset_history' in report or any(window['points'] for window in report['windows'])):
        raise ValueError('Invalid deferred allowance contents')
    return report


def selection_context(status, kwargs, path):
    """Same account/evidence can retain its issued selection through UI filters."""
    from codex_usage.agent_reports import PRICING_REVISION, REPORT_RENDER_REVISION
    from codex_usage.allowance_index import _revisions
    return digest([str(path.resolve()), status.revision, _revisions(PRICING_REVISION), REPORT_RENDER_REVISION,
                   status.coverage.complete, status.plan_allowance['active_buckets'],
                   status.plan_allowance['probe_status'], kwargs['timezone_name'],
                   kwargs.get('auto_transitions', True)])


def invitation(base_html, context, writes, *, selection_identity):
    """Issue one explicit load without enumerating or preparing any history."""
    from codex_usage.allowance_history_navigation import RECEIPT_PREFIX
    from codex_usage.report_allowance_history import _link
    import re
    scope = digest([context, 'deferred-history-1'])
    state = dict(DEFAULT_STATE)
    nav = dict(scope=scope, state=state, actions=[dict(scope=scope, state=dict(state))], deferred=True)
    writes[RECEIPT_PREFIX+scope] = dict(issued_receipt(nav, context), selection_context=selection_identity)
    markup = ('<p class="allowance-history-load">'
              + _link(nav, state, 'Load allowance history') + '</p>')
    rendered = re.sub(r'<!-- allowance-history:start -->.*?<!-- allowance-history:end -->',
        lambda _: '<!-- allowance-history:start -->'+markup+'<!-- allowance-history:end -->',
        base_html, count=1, flags=re.DOTALL)
    rendered = rendered.replace('<details class="allowance-history-panel">',
                                '<details class="allowance-history-panel" open>', 1)
    return rendered, nav, True
