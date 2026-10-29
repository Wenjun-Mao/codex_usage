"""Clock/freshness exactness and real HTTP capture overlap at the changed builder."""
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import timedelta
import http.client
import json
import re
from threading import Event
from time import perf_counter

import pytest

from codex_usage.agent_api import AgentHttpServer
from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_reports import render_ledger_report
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_probe import QuotaRead
from test_agent_api import _StubAgent
from test_allowance_index import _session
from test_allowance_window_cache import AT, breakdown_home


def without_history(html):
    html = html.replace('<details class="allowance-history-panel" open>', '<details class="allowance-history-panel">')
    return re.sub(r'<!-- allowance-history:start -->.*?<!-- allowance-history:end -->', '', html, flags=re.S)


@pytest.mark.parametrize('offset', [-300, 0, 7200, 5*86400])
def test_deferred_current_html_and_status_match_full_through_clock_and_deadline_changes(tmp_path, offset):
    breakdown_home(tmp_path, extended=True)
    options = dict(range_name='today', project_keys=[], theme='auto', timezone_name='UTC', now=AT+timedelta(seconds=offset))
    full = render_ledger_report(tmp_path, **options)
    deferred = render_ledger_report(tmp_path, **options, allowance_history='deferred')
    assert json.dumps(deferred.status.to_dict()) == json.dumps(full.status.to_dict())
    assert without_history(deferred.html) == without_history(full.html)
    assert deferred.speed_navigation == full.speed_navigation
    assert deferred.breakdown_navigation == full.breakdown_navigation


@pytest.mark.parametrize('mode', ['eager', 'deferred'])
def test_normal_capture_completes_over_http_while_report_holds_allowance_snapshot(tmp_path, monkeypatch, mode):
    import codex_usage.allowance_index as index
    home = tmp_path/'codex'
    source = home/'sessions/owned.jsonl'
    source.parent.mkdir(parents=True)
    _session(source, [100])
    anchor = QuotaObservation(AT.isoformat(), 'codex','primary','pro',20,300,int((AT+timedelta(hours=1)).timestamp()))
    monkeypatch.setattr('codex_usage.allowance_capture.probe_allowance', lambda _:QuotaRead(AT.isoformat(),'pro',(anchor,)))
    assert capture_once(home, request_kind='manual', max_workers=1).outcome == 'success'
    entered, release = Event(), Event()
    original = index._build_from_costs
    def held(*args, **kwargs):
        if not entered.is_set():
            assert kwargs['include_history'] is (mode == 'eager')
            entered.set()
            assert release.wait(10), 'Capture did not complete under the report snapshot'
        return original(*args, **kwargs)
    monkeypatch.setattr(index, '_build_from_costs', held)
    class Agent(_StubAgent):
        def report(self, **kwargs):
            return render_ledger_report(home, timezone_name='UTC', now=AT+timedelta(minutes=1), **kwargs)

        def capture_now(self):
            result = Future()
            result.set_result(capture_once(home, request_kind='manual', max_workers=1))
            return result
    server = AgentHttpServer(Agent(), token='x'*40)
    def request(method, path):
        connection = http.client.HTTPConnection('127.0.0.1', server.port, timeout=15)
        try:
            connection.request(method,path,body='{}' if method=='POST' else None,
                headers={'Authorization':'Bearer '+'x'*40,'Content-Type':'application/json'})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()
    server.start()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(request,'GET',f'/v1/report?range=today&theme=auto&allowance_history={mode}')
            try:
                assert entered.wait(5)
                with source.open('a') as stream:
                    stream.write(json.dumps(dict(timestamp=(AT+timedelta(seconds=10)).isoformat(),type='event_msg',
                        payload=dict(type='token_count',info=dict(total_token_usage=dict(input_tokens=150,total_tokens=150)))))+'\n')
                started = perf_counter()
                code, capture = request('POST','/v1/capture')
                elapsed = perf_counter()-started
                assert code == 200 and capture['outcome'] == 'success'
                assert capture['stats']['files_appended'] == 1 and elapsed < 10
            finally:
                release.set()
            code, old = pending.result(timeout=15)
        assert code == 200 and old['ledger_revision'] < capture['status']['ledger_revision']
        code, fresh = request('GET',f'/v1/report?range=today&theme=auto&allowance_history={mode}')
        assert code == 200 and fresh['ledger_revision'] == capture['status']['ledger_revision']
        assert (fresh['allowance_navigation'].get('deferred') is True) is (mode == 'deferred')
        assert ledger_database_path(home).exists()
    finally:
        release.set()
        server.stop()
