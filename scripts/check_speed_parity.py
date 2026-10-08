"""Compare frozen synthetic monetary evidence with a read-only baseline Git archive."""
import argparse
from dataclasses import asdict
from datetime import UTC, timedelta
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from unittest.mock import patch

from observed_speed_fixture import AT, append_rows, response, write_source


def snapshot(home):
    from codex_usage.agent_capture import capture_once
    from codex_usage.agent_paths import ledger_database_path
    from codex_usage.aggregation import resolve_report_range, summarize_valued_records
    from codex_usage.allowance_index import indexed_allowance_report
    from codex_usage.allowance_models import QuotaObservation
    from codex_usage.allowance_queries import build_allowance_report
    from codex_usage.allowance_store import store_observations
    from codex_usage.ledger_materialization import materialize_ledger
    from codex_usage.ledger_queries import query_ledger_records, query_ledger_status
    from codex_usage.ledger_schema import increment_ledger_revision, ledger_revision, open_ledger
    with patch("codex_usage.agent_capture.capture_quota_read", lambda *args: None):
        result = capture_once(home, request_kind="manual", max_workers=1)
    assert result.outcome == "success", result.error
    db = ledger_database_path(home)
    with open_ledger(db) as connection:
        observations = [QuotaObservation((AT + timedelta(minutes=i * 5)).isoformat(),
            "codex", "primary", "pro", 10 + i * 5, 300, int(AT.timestamp()) + 18000) for i in range(12)]
        store_observations(connection, observations, source_key="synthetic-frozen", provenance="live")
        increment_ledger_revision(connection)
        connection.commit()
    with open_ledger(db, read_only=True) as connection:
        connection.execute("begin")
        status = query_ledger_status(connection)
        records = [record.to_dict() for record in query_ledger_records(connection)]
        for record in records:
            record.pop("file_path", None)
        monetary = {}
        keys = [r[0] for r in connection.execute("select project_key from ledger_projects order by project_key")]
        for range_name in ("all", "today", "7d"):
            for selection in ([], keys[:1], keys[-1:]):
                report_range = resolve_report_range(range_name, UTC, now=AT)
                materialized = materialize_ledger(connection, report_range, selection, UTC, status, auto_transitions=True)
                key = json.dumps([range_name, selection])
                monetary[key] = {"language": summarize_valued_records(materialized.valued).to_dict(),
                                 "images": asdict(materialized.images)}
        full = build_allowance_report(connection)
        indexed = indexed_allowance_report(connection, db, revision=ledger_revision(connection),
                                           pricing_revision="frozen-synthetic", coverage_complete=True)
        for report in (full, indexed):
            report["status"].pop("probe_age_seconds", None)
        assert indexed == full, "indexed/full monetary parity failed"
    return {"records": records, "monetary": monetary, "allowance": full}


def frozen_sources(home):
    for task, model in (("astra", "gpt-6-astra"), ("sol", "gpt-6.1-sol"), ("luna", "gpt-6-luna")):
        source = write_source(home, task=task, count=0, cwd=f"/synthetic/{task}")
        for index in range(20):
            append_rows(source, response(index, model=model, response_id=f"{task}-{index}"))
    image = write_source(home, task="image", count=0, cwd="/synthetic/image")
    stamp = AT.isoformat()
    append_rows(image, [
        {"type": "turn_context", "timestamp": stamp, "payload": {"turn_id": "image-turn", "model": "gpt-5.6-terra"}},
        {"type": "event_msg", "timestamp": stamp, "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 100, "total_tokens": 100}}}},
        {"timestamp": stamp, "type": "response_item", "payload": {"type": "function_call", "name": "image_gen", "call_id": "synthetic-image", "arguments": json.dumps({"model": "gpt-image-2", "size": "1024x1024", "quality": "high", "prompt": "SYNTHETIC ONLY"})}},
        {"timestamp": stamp, "type": "response_item", "payload": {"type": "function_call_output", "call_id": "synthetic-image", "output": json.dumps({"model": "gpt-image-2", "data": [{}], "usage": {"text_input_tokens": 10, "cached_text_input_tokens": 0, "image_input_tokens": 0, "cached_image_input_tokens": 0, "image_output_tokens": 20, "total_tokens": 30}})}},
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default="b276f87deadec90137549bcaf6bd6f9e33a9ad15")
    parser.add_argument("--output", type=Path, default=Path("output/playwright/observed-speed/monetary-parity.json"))
    parser.add_argument("--worker-home", type=Path)
    args = parser.parse_args()
    if args.worker_home:
        print(json.dumps(snapshot(args.worker_home), sort_keys=True, default=str))
        return
    repo = Path(__file__).resolve().parents[1]
    with TemporaryDirectory(prefix="speed-parity-") as raw:
        root = Path(raw)
        archive = subprocess.run(["git", "archive", "--format=tar", args.baseline_ref, "src"], cwd=repo, check=True, capture_output=True).stdout
        baseline = root / "baseline"
        baseline.mkdir()
        with tarfile.open(fileobj=BytesIO(archive)) as bundle:
            bundle.extractall(baseline, filter="data")
        frozen_sources(root / "before")
        shutil.copytree(root / "before", root / "after")
        results = []
        for label, source in (("before", baseline / "src"), ("after", repo / "src")):
            environment = dict(os.environ, PYTHONPATH=str(source), CODEX_HOME=str(root / label),
                               CODEX_USAGE_DATA_DIR=str(root / "settings"))
            completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker-home", str(root / label)],
                env=environment, capture_output=True, text=True, check=True)
            results.append(json.loads(completed.stdout))
        if results[0] != results[1]:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            for label, result in zip(("expected", "candidate"), results):
                args.output.with_suffix(f".{label}.json").write_text(json.dumps(result, indent=2, sort_keys=True))
            raise AssertionError("candidate changed frozen evidence; inspect synthetic expected/candidate snapshots")
        evidence = {"synthetic_only": True, "baseline": args.baseline_ref, "exact_parity": True,
            "language_records": len(results[0]["records"]), "range_project_cases": len(results[0]["monetary"]),
            "indexed_full_allowance_equal": True,
            "snapshot_sha256": hashlib.sha256(json.dumps(results[0], sort_keys=True).encode()).hexdigest()}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(evidence))


if __name__ == "__main__":
    main()
