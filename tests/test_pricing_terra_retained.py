"""A fresh normal report reprices retained Terra rows without source replay."""
import ast
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import codex_usage
from codex_usage.ledger_schema import open_ledger
from test_allowance_window_cache import breakdown_home

NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)
MODEL = 'gpt-6.1-terra'
PROGRAM = '''
import hashlib, json, pathlib, sys
from datetime import datetime
import codex_usage
from codex_usage.agent_reports import render_ledger_report, PRICING_REVISION
from codex_usage.aggregation import aggregate_records
from codex_usage.ledger_queries import query_ledger_records
from codex_usage.ledger_schema import open_ledger, ledger_revision
core, home, stamp = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]
assert pathlib.Path(codex_usage.__file__).is_relative_to(core)
assert not (home/'sessions').exists()
assert not (core/'codex_usage/read_model').exists()
path = home/'.codex-usage/usage-ledger.sqlite3'
with open_ledger(path, read_only=True) as db:
    raw = [tuple(row) for row in db.execute('SELECT * FROM ledger_usage_events ORDER BY event_id')]
    revision = ledger_revision(db)
    rows = aggregate_records(query_ledger_records(db), 'model', __import__('datetime').UTC)
row = next(row for row in rows if row.key == 'gpt-6.1-terra')
options = dict(range_name='30d', project_keys=[], theme='day', timezone_name='UTC', now=datetime.fromisoformat(stamp))
report = render_ledger_report(home, **options)
warm = render_ledger_report(home, **options)
assert report.html == warm.html and warm.cache_hit
print(json.dumps(dict(pricing=PRICING_REVISION, revision=revision,
    raw=hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest(),
    responses=row.record_count, tokens=row.usage.total_tokens, unpriced=row.cost.unpriced_tokens,
    dollars=row.cost.total_usd, credits=row.credits.total_credits,
    html=hashlib.sha256(report.html.encode()).hexdigest(), cache_hit=report.cache_hit)))
'''


def test_normal_pricing_identity_replaces_unpriced_cached_terra_in_a_fresh_process(tmp_path):
    home, core = tmp_path/'home', tmp_path/'runtime'
    path = breakdown_home(home, now=NOW, projects=1, days=2, extended=True)
    with open_ledger(path) as db:
        assert db.execute('UPDATE ledger_models SET model_key=? WHERE model_key=?',
            (MODEL, 'unknown-synthetic')).rowcount == 1
        db.commit()
    shutil.rmtree(home/'sessions')
    shutil.copytree(Path(codex_usage.__file__).parent, core/'codex_usage',
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    source = core/'codex_usage/pricing.py'
    published = source.read_text()
    class BeforeTerra(ast.NodeTransformer):
        removed = 0
        def visit_Call(self, node):
            if (isinstance(node.func, ast.Name) and node.func.id == '_effective_rate' and node.args
                    and isinstance(node.args[0], ast.Constant) and node.args[0].value == MODEL):
                self.removed += 1
                return None
            return self.generic_visit(node)
    previous = BeforeTerra()
    tree = previous.visit(ast.parse(published))
    assert previous.removed == 2
    source.write_text(ast.unparse(tree))
    environment = dict(os.environ, PYTHONPATH=str(core), PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
    def render():
        result = subprocess.run([sys.executable, '-B', '-c', PROGRAM, str(core), str(home), NOW.isoformat()],
            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout+result.stderr
        return json.loads(result.stdout)
    old = render()
    source.write_text(published)
    new = render()
    assert old['pricing'] != new['pricing'] and old['html'] != new['html']
    assert old['raw'] == new['raw'] and old['revision'] == new['revision']
    assert old['responses'] == new['responses'] == 6
    assert old['tokens'] == new['tokens'] == old['unpriced'] == 4800
    assert old['dollars'] == old['credits'] == 0 and new['unpriced'] == 0
    assert new['dollars'] == pytest.approx(.01326)
    assert new['credits'] == pytest.approx(.3315)
    assert not old['cache_hit'] and not new['cache_hit']
