"""Diagnostics are explicit, bounded, read-only and absent from dashboard work."""
from contextlib import ExitStack
from copy import deepcopy
from hashlib import sha256
import json
from unittest.mock import patch

from release_tooling_support import load_tool
from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_reports import render_ledger_report
from codex_usage.allowance_diagnostics import allowance_diagnostics, MAX_DIAGNOSTICS_BYTES
from codex_usage.ledger_schema import open_ledger
from codex_usage.report_allowance import render_allowance_section

fixtures = load_tool("allowance_period_fixture")


def seeded(home):
    home.mkdir(exist_ok=True)
    report = fixtures.reset_economics_fixture(home)
    now = fixtures.install_history_cache(home, report)
    return report, now


def forbidden(*_args, **_kwargs):
    raise AssertionError("Diagnostics performed historical work")


def test_copy_reads_only_selected_cached_aggregate_fields_and_preserves_ledger(tmp_path):
    _, now = seeded(tmp_path)
    path = ledger_database_path(tmp_path)
    with open_ledger(path) as connection:
        key, payload = connection.execute("select pricing_revision,report_json from allowance_report_cache where pricing_revision not like '%:pace-state'").fetchone()
        data = json.loads(payload)
        data["private_path"] = "PRIVATE_TASK_CONTENT /private/path auth-token"
        data["report"]["paces"][0][0]["private_path"] = data["private_path"]
        connection.execute("update allowance_report_cache set report_json=? where pricing_revision=?", (json.dumps(data), key))
        connection.commit()
    before = sha256(path.read_bytes()).hexdigest()
    with ExitStack() as stack:
        for target in ("codex_usage.allowance_queries.load_quota_evidence",
            "codex_usage.allowance_index.indexed_allowance_report", "codex_usage.allowance_pace.fit_paces",
            "codex_usage.allowance_index._price_missing_events", "codex_usage.allowance_capture.probe_allowance",
            "codex_usage.agent_capture.capture_once", "codex_usage.allowance_report_codec.decode_report"):
            stack.enter_context(patch(target, forbidden))
        result = allowance_diagnostics(tmp_path, now=now)
    assert result["schema_version"] == 1
    assert "PRIVATE_TASK_CONTENT" not in result["text"] and "private_path" not in result["text"]
    data = json.loads(result["text"])
    assert data["evidence"]["state"] == "cached"
    assert data["evidence"]["paces"] and data["evidence"]["headline_estimate"]["value"] > 0
    assert len(result["text"].encode()) <= MAX_DIAGNOSTICS_BYTES
    assert sha256(path.read_bytes()).hexdigest() == before


def test_cold_or_outdated_cache_does_not_build_a_report(tmp_path):
    _, now = seeded(tmp_path)
    with open_ledger(ledger_database_path(tmp_path)) as connection:
        connection.execute("update allowance_report_cache set ledger_revision=ledger_revision-1")
        connection.commit()
    with patch("codex_usage.allowance_queries._build_from_costs", forbidden):
        data = json.loads(allowance_diagnostics(tmp_path, now=now)["text"])
    assert data["evidence"] == {"state": "not_generated", "paces": []}


def test_large_pace_collection_is_bounded_and_omissions_are_explicit(tmp_path):
    _, now = seeded(tmp_path)
    with open_ledger(ledger_database_path(tmp_path)) as connection:
        key, payload = connection.execute("select pricing_revision,report_json from allowance_report_cache where pricing_revision not like '%:pace-state'").fetchone()
        data = json.loads(payload)
        data["report"]["paces"] *= 100
        connection.execute("update allowance_report_cache set report_json=? where pricing_revision=?", (json.dumps(data), key))
        connection.commit()
    result = allowance_diagnostics(tmp_path, now=now)
    evidence = json.loads(result["text"])["evidence"]
    assert len(evidence["paces"]) <= 24 and evidence["omitted_paces"] >= 276
    assert len(result["text"].encode()) <= MAX_DIAGNOSTICS_BYTES


def test_normal_render_never_builds_diagnostic_text_and_shows_only_relevant_warnings(tmp_path):
    report, now = seeded(tmp_path)
    original = deepcopy(report)
    with patch("codex_usage.allowance_diagnostics.allowance_diagnostics", forbidden), \
         patch("codex_usage.report_allowance_pace.pace_details", forbidden), \
         patch("codex_usage.report_allowance.evidence_line", forbidden):
        html = render_allowance_section(report, now=now)
    assert "<summary>Diagnostics</summary>" not in html
    assert "Account lifetime tokens" not in html and "Latest window fit:" not in html
    assert "Estimate uses incomplete history" not in html
    report["status"]["probe_status"] = "stale"
    report["headline"]["coverage_complete"] = False
    html = render_allowance_section(report, now=now)
    assert "Reading outdated." in html and "command:codexUsage.captureNow" in html
    assert "Estimate uses incomplete history." in html
    report["status"]["probe_status"] = original["status"]["probe_status"]
    report["headline"]["coverage_complete"] = original["headline"]["coverage_complete"]
    assert report == original


def test_upgrade_invalidates_diagnostic_panel_in_warm_revision_42_html(tmp_path, monkeypatch):
    import codex_usage.agent_reports as reports
    _, now = seeded(tmp_path)
    args = dict(range_name="all", project_keys=[], theme="night", timezone_name="UTC", now=now)
    original = reports.render_html_report
    def legacy(*args, **kwargs):
        path = original(*args, **kwargs)
        path.write_text(path.read_text().replace("</body>", "<details><summary>Diagnostics</summary>Old diagnostics</details></body>"))
        return path
    with monkeypatch.context() as old:
        old.setattr(reports, "REPORT_RENDER_REVISION", 42)
        old.setattr(reports, "render_html_report", legacy)
        previous = render_ledger_report(tmp_path, **args)
        assert "<summary>Diagnostics</summary>" in previous.html
        assert render_ledger_report(tmp_path, **args).cache_hit
    upgraded = render_ledger_report(tmp_path, **args)
    assert not upgraded.cache_hit and upgraded.ledger_revision == previous.ledger_revision
    assert "<summary>Diagnostics</summary>" not in upgraded.html
    assert render_ledger_report(tmp_path, **args).cache_hit
