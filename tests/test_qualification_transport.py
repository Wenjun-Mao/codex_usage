"""Source claims and partial REST lists are not qualification authority."""
import json
from types import SimpleNamespace
import subprocess

import pytest

from qualification_fixture import GitHub, policy, producer
from release_tooling_support import load_tool


@pytest.mark.parametrize("fault", [None, "checkout", "workflow-sha", "dirty"])
def test_producer_source_requires_actual_checkout_and_unchanged_tracked_inputs(monkeypatch, tmp_path, fault):
    env = {"GITHUB_REPOSITORY": policy.REPOSITORY, "GITHUB_REPOSITORY_ID": "123", "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_SHA": "a" * 40,
        "QUALIFICATION_WORKFLOW_SHA": "a" * 40, "QUALIFICATION_PROBE": "false"}
    if fault == "workflow-sha":
        env["QUALIFICATION_WORKFLOW_SHA"] = "c" * 40
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[1] == "rev-parse":
            return SimpleNamespace(stdout=("c" if fault == "checkout" else "a") * 40)
        if command[1] == "diff" and fault == "dirty":
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(producer.subprocess, "run", run)
    monkeypatch.setattr(producer, "contract_files", lambda _: ["trusted.py"])
    monkeypatch.setattr(producer, "contract_identity", lambda _: "b" * 64)
    monkeypatch.setattr(producer, "package_version", lambda _: "2.12.2")
    if fault:
        with pytest.raises((ValueError, subprocess.CalledProcessError)):
            producer.source_context(tmp_path, env)
    else:
        assert producer.source_context(tmp_path, env)["sha"] == "a" * 40
        assert [command[1] for command in calls] == ["rev-parse", "ls-files", "diff"]


@pytest.mark.parametrize("fault", ["incomplete", "duplicate", "total-type"])
def test_rest_inventory_is_complete_unique_and_typed(fault):
    api = GitHub()
    response = {"total_count": 2, "rows": [{"id": 1}, {"id": 2}]}
    if fault == "incomplete":
        response["rows"].pop()
    elif fault == "duplicate":
        response["rows"][1]["id"] = 1
    else:
        response["total_count"] = True
    api.raw = lambda endpoint: json.dumps(response).encode()
    with pytest.raises(ValueError):
        api.pages("synthetic", "rows")


def test_production_promotion_is_blocked_before_network_or_credentials(tmp_path, monkeypatch):
    qualification = load_tool("qualification")
    monkeypatch.setattr(qualification, "proof_reader", lambda *args, **kwargs: pytest.fail("Blocked promotion must not download proof"))
    with pytest.raises(ValueError, match="independently retained"):
        qualification.main(["validate-publication", "--run", "77", "--attempt", "1", "--ref", "refs/tags/v2.12.2",
            "--promotion-run", "99", "--promotion-attempt", "1", "--output", str(tmp_path)])
