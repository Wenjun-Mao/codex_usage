"""Record isolated synthetic migration/recovery/append/quota work, without timing gates."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from observed_speed_fixture import AT, append_rows, legacy_speed_home, response

from codex_usage.agent_capture import capture_once
from codex_usage.agent_reports import render_ledger_report
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_store import store_observations
from codex_usage.ledger_schema import increment_ledger_revision, ledger_revision, open_ledger
from codex_usage.speed_recovery import run_speed_recovery_slice


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/playwright/observed-speed/work.json"))
    args = parser.parse_args()
    evidence = {"synthetic_only": True}
    with TemporaryDirectory(prefix="speed-work-") as raw:
        home = Path(raw)
        db, baseline = legacy_speed_home(home)
        started = perf_counter()
        with open_ledger(db) as connection:
            before = ledger_revision(connection)
        evidence["additive_migration_seconds"] = perf_counter() - started
        started = perf_counter()
        recovered = run_speed_recovery_slice(db)
        evidence["speed_only_recovery"] = {"seconds": perf_counter() - started, **asdict(recovered)}
        assert recovered.sources <= 1 and recovered.source_opens <= 4
        assert recovered.source_bytes <= 16 * 1024 * 1024 + 640 * 1024 + 1
        with open_ledger(db) as connection:
            assert ledger_revision(connection) == before
            assert tuple(connection.execute("select count(*),sum(total_tokens),sum(output_tokens) from ledger_usage_events").fetchone()) == baseline
        evidence["speed_only_monetary_revision_change"] = 0
        assert run_speed_recovery_slice(db).source_opens == 0
        evidence["unchanged_recovery_source_opens"] = 0
        source = next((home / "sessions").glob("*timed.jsonl"))
        append_rows(source, response(20))
        with patch("codex_usage.agent_capture.capture_quota_read", lambda *args: None):
            started = perf_counter()
            captured = capture_once(home, request_kind="manual", max_workers=1)
        assert captured.outcome == "success", captured.error
        evidence["append_capture"] = {"seconds": perf_counter() - started,
            "normal_source_bytes": captured.stats.source_bytes_read,
            "historical_speed": asdict(captured.speed_recovery)}
        def render():
            return render_ledger_report(home, range_name="all", project_keys=[], theme="day", timezone_name="UTC", now=AT)
        with open_ledger(db) as connection:
            store_observations(connection, [QuotaObservation(AT.isoformat(), "codex", "primary", "pro", 5, 300, int(AT.timestamp()) + 18000)], source_key="synthetic-initial-quota", provenance="live")
            increment_ledger_revision(connection)
            connection.commit()
        render()
        with patch("codex_usage.allowance_index.estimate_cost", side_effect=AssertionError("quota-only update repriced a language event")):
            started = perf_counter()
            with open_ledger(db) as connection:
                store_observations(connection, [QuotaObservation(AT.isoformat(), "codex", "primary", "pro", 10, 300, int(AT.timestamp()) + 18000)], source_key="synthetic-quota", provenance="live")
                increment_ledger_revision(connection)
                connection.commit()
            render()
            evidence["quota_only_update_and_report_seconds"] = perf_counter() - started
        evidence["quota_only_language_reprices"] = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
