"""Real HTTP parameter/response boundary, including issued cold-load bootstrap."""
import json
from urllib.parse import urlencode

from codex_usage.agent_api import AgentHttpServer
from codex_usage.agent_reports import render_ledger_report
from test_agent_api import _StubAgent, _request
from test_allowance_window_cache import AT, breakdown_home


def test_api_defaults_eager_and_transports_deferred_and_issued_load(tmp_path):
    breakdown_home(tmp_path, extended=True)
    class Agent(_StubAgent):
        def report(self, **kwargs):
            return render_ledger_report(tmp_path, timezone_name='UTC', now=AT, **kwargs)
    server = AgentHttpServer(Agent(), token='x'*40)
    server.start()
    def get(**kwargs):
        status, body = _request(server.port, headers={'Authorization':'Bearer '+'x'*40},
                                path='/v1/report?'+urlencode(dict(range='today', theme='auto', **kwargs)))
        return status, json.loads(body)
    try:
        code, eager = get()
        assert code == 200 and 'Load allowance history' not in eager['html']
        code, initial = get(allowance_history='deferred')
        assert code == 200 and initial['allowance_navigation']['deferred'] is True
        action = initial['allowance_navigation']['actions'][0]
        code, loaded = get(allowance_history='requested', allowance_action=json.dumps(action))
        assert code == 200 and 'Load allowance history' not in loaded['html']
        assert loaded['allowance_navigation'] == eager['allowance_navigation']
        assert loaded['allowance_navigation']['scope'] != action['scope']
        assert get(allowance_history='unknown')[0] == 400
        assert get(allowance_history='')[0] == 400
        assert get(allowance_history='requested', allowance_action=json.dumps(dict(action, scope='f'*64)))[0] == 400
    finally:
        server.stop()
