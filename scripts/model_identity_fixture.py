"""Public synthetic reports for cross-chart model identity regression checks."""
import json
from pathlib import Path
from runpy import run_path

from codex_usage.agent_reports import render_ledger_report

MODELS = ('gpt-6-astra', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna',
          'gpt-6-sol', 'gpt-6-luna', 'gpt-6.1-sol', 'gpt-6.1-terra',
          'custom-one', 'custom-two', 'custom-three')
SCRIPTS = Path(__file__).resolve().parent
SPEED = run_path(str(SCRIPTS / 'observed_speed_fixture.py'))
USAGE = run_path(str(SCRIPTS / 'usage_breakdown_fixture.py'))
AT = USAGE['AT']


def prepare(home):
    USAGE['breakdown_home'](home, projects=2, days=3, extended=True)
    return SPEED['chart_home'](home, models=tuple((m, 5+i) for i, m in enumerate(MODELS)))


def render(home, *, theme='day', range_name='all', projects=(), action=None, speed_granularity=None):
    return render_ledger_report(home, range_name=range_name, project_keys=list(projects),
        theme=theme, timezone_name='UTC', now=AT,
        breakdown_action=json.dumps(action) if action else None, speed_granularity=speed_granularity)


def move(home, report, *, theme='day', range_name='all', projects=(), **changes):
    desired = {**report.breakdown_navigation['state'], **changes}
    action = next(a for a in report.breakdown_navigation['actions'] if a['state'] == desired)
    return render(home, theme=theme, range_name=range_name, projects=projects, action=action)
