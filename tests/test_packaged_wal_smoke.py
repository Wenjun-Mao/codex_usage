"""The same normal-agent proof used for frozen package acceptance."""
import sys

from release_tooling_support import load_tool


def test_real_source_agent_replays_the_packaged_wal_contract():
    smoke = load_tool('packaged_wal_smoke')
    evidence = smoke.run_acceptance([sys.executable, '-m', 'codex_usage.agent_main'])
    assert evidence['contract'] == 'collector-wal-http-v1'
    assert evidence['restarted']['outcome'] == 'partial'
    assert evidence['completed']['outcome'] == 'reclaimed'
    assert evidence['records_equal'] and evidence['source_unchanged']
