import importlib.util
from pathlib import Path

from speed_test_support import append_rows, response, write_source


def test_actual_ingestion_evidence_compares_raw_whole_full_append_and_recovery(tmp_path, monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("speed_ingestion_harness", scripts / "check_speed_ingestion.py")
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    path = write_source(tmp_path, count=0)
    for index in range(5):
        rows = response(index)
        rows[3]["payload"]["content"] = [{"text": "private" * 10000}]
        rows[3]["payload"]["internal_chat_message_metadata_passthrough"] = {"turn_id": f"turn-{index}"}
        append_rows(path, rows)
    results, maximum = harness.parse_paths(path)
    assert set(results) == {"whole_object", "full", "append", "recovery"}
    assert all(facts == results["whole_object"] for facts in results.values())
    assert maximum < 12000 and all(not fact.reason for fact in results["full"])
    summary = harness.summarize(results["full"])
    assert summary["sensitivity"]["10ms/500tokens"] == {
        "eligible": 5, "models_with_summary": 1, "model_daily_points": 1, "model_hourly_points": 1,
    }
