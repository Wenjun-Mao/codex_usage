"""Offline theme performance adapter: real authenticated API/reports, no scheduler or RPC."""
import argparse
from contextlib import ExitStack
from datetime import datetime
import json
import os
import secrets
from pathlib import Path
import time
from unittest.mock import patch

from codex_usage.agent_api import AgentHttpServer
from codex_usage.agent_paths import agent_descriptor_path, ledger_database_path
from codex_usage.agent_protocol import AgentDescriptor, write_agent_descriptor
from codex_usage.agent_reports import render_ledger_report
from codex_usage.agent_settings import AgentSettings
from codex_usage.agent_status import runtime_status_payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--now', required=True)
    args = parser.parse_args()
    root, now = args.root, datetime.fromisoformat(args.now)
    home = root / 'codex'
    counts, calls, reports_seen = {}, [], []
    import codex_usage.agent_reports as reports
    import codex_usage.breakdown_reports as breakdown
    import codex_usage.ledger_materialization as materialization
    import codex_usage.allowance_index as allowance
    import codex_usage.agent_capture as capture
    import codex_usage.allowance_queries as quota
    import resource
    class Offline:
        settings = AgentSettings(str(home), capture_interval_minutes=None, timezone='America/Toronto')
        def status_payload(self):
            return runtime_status_payload(home, descriptor, capture_running=False, next_capture_seconds=None, dirty_paths=0)
        def report(self, **kwargs):
            counts.clear()
            started = time.perf_counter()
            report = render_ledger_report(home, timezone_name='America/Toronto', now=now, **kwargs)
            reports_seen.append(report)
            calls.append({'query': kwargs, 'seconds': time.perf_counter()-started,
                'work': dict(counts), 'cache_hit': report.cache_hit, 'html_bytes': len(report.html.encode()),
                'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
            return report
    token = secrets.token_urlsafe(32)
    server = AgentHttpServer(Offline(), token=token)
    descriptor = AgentDescriptor(os.getpid(), 1, server.port, token, now.isoformat(), str(home), 'background')
    def track(stack, module, name, label):
        fn = getattr(module, name)
        def observed(*a, **kw):
            counts[label] = counts.get(label, 0)+1
            return fn(*a, **kw)
        stack.enter_context(patch.object(module, name, observed))
    with ExitStack() as stack:
        for module, name, label in [(reports, 'materialize_ledger', 'materialization'),
            (materialization, 'value_records', 'repricing'), (breakdown, 'prepare_evidence', 'history_preparation'),
            (allowance, 'indexed_allowance_report', 'quota_preparation'), (reports, 'indexed_allowance_report', 'quota_preparation'),
            (breakdown, 'indexed_allowance_report', 'quota_preparation'),
            (breakdown, 'prepare_account', 'account_preparation'),
            (allowance, '_price_missing_events', 'monetary_index_scan'),
            (quota, 'load_quota_evidence', 'quota_decode'),
            (capture, 'capture_once', 'capture')]:
            track(stack, module, name, label)
        assert ledger_database_path(home).exists()
        write_agent_descriptor(agent_descriptor_path(home), descriptor)
        server.start()
        (root / 'server-ready').write_text('ready')
        try:
            while not (root / 'stop-server').exists():
                if (root / 'flush-reports').exists() and not (root / 'reports-flushed').exists():
                    for index, report in enumerate(reports_seen):
                        (root / f'report-{index}.html').write_text(report.html)
                        metadata = report.to_dict()
                        del metadata['html']
                        (root / f'report-{index}.json').write_text(json.dumps(metadata, default=str))
                    (root / 'collector.json').write_text(json.dumps(calls, default=str))
                    (root / 'reports-flushed').touch()
                time.sleep(.01)
        finally:
            (root / 'collector.json').write_text(json.dumps(calls, default=str))
            server.stop()


if __name__ == '__main__':
    main()
