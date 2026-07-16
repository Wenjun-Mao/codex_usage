from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import codex_usage.sync.planner as sync_planner
from codex_usage.sync.io import snapshot_file
from codex_usage.sync.models import SyncFileSnapshot
from codex_usage.sync.planner import classify_snapshots


def _snapshot_bytes(
    tmp_path: Path,
    name: str,
    value: bytes | None,
) -> SyncFileSnapshot:
    path = tmp_path / name
    if value is None:
        return SyncFileSnapshot(path=path, exists=False)
    path.write_bytes(value)
    return snapshot_file(path)


@pytest.mark.parametrize(
    ("local", "remote", "base", "expected_state", "expected_action"),
    [
        (b"same", b"same", b"same", "synced", "none"),
        (b"base+local", b"base", b"base", "local_ahead", "push"),
        (b"base", b"base+remote", b"base", "remote_ahead", "pull"),
        (b"base+local", b"base", None, "fast_forward_push", "push"),
        (b"base", b"base+remote", None, "fast_forward_pull", "pull"),
        (b"left", b"right", b"base", "conflict", "conflict"),
        (b"left", b"righty", None, "conflict", "conflict"),
        (b"local", None, None, "local_only", "push"),
        (None, b"remote", None, "remote_only", "pull"),
        (None, None, None, "missing", "skip"),
    ],
)
def test_planner_classifies_three_way_state(
    tmp_path: Path,
    local: bytes | None,
    remote: bytes | None,
    base: bytes | None,
    expected_state: str,
    expected_action: str,
) -> None:
    local_snapshot = _snapshot_bytes(tmp_path, "local.jsonl", local)
    remote_snapshot = _snapshot_bytes(tmp_path, "remote.jsonl", remote)
    base_sha256 = hashlib.sha256(base).hexdigest() if base is not None else ""

    state, action, _reason = classify_snapshots(
        local_snapshot,
        remote_snapshot,
        base_sha256,
    )

    assert state == expected_state
    assert action == expected_action


def test_planner_treats_distinct_materialized_local_and_remote_baselines_as_synced(
    tmp_path: Path,
) -> None:
    local = _snapshot_bytes(tmp_path, "local.jsonl", b"local-cwd\nhistory")
    remote = _snapshot_bytes(tmp_path, "remote.jsonl", b"remote-cwd\nhistory")

    state, action, reason = classify_snapshots(
        local,
        remote,
        base_sha256=local.sha256,
        last_local_sha256=local.sha256,
        last_remote_sha256=remote.sha256,
    )

    assert (state, action) == ("synced", "none")
    assert reason == "local and remote match their last synchronized versions"


def test_planner_detects_real_local_change_from_distinct_materialized_baselines(
    tmp_path: Path,
) -> None:
    previous_local = _snapshot_bytes(
        tmp_path,
        "previous-local.jsonl",
        b"local-cwd\nhistory",
    )
    local = _snapshot_bytes(
        tmp_path,
        "local.jsonl",
        b"local-cwd\nhistory\nnew turn",
    )
    remote = _snapshot_bytes(tmp_path, "remote.jsonl", b"remote-cwd\nhistory")

    state, action, _reason = classify_snapshots(
        local,
        remote,
        base_sha256=previous_local.sha256,
        last_local_sha256=previous_local.sha256,
        last_remote_sha256=remote.sha256,
    )

    assert (state, action) == ("local_ahead", "push")


def test_equal_hashes_do_not_require_prefix_file_reads(tmp_path: Path) -> None:
    local = _snapshot_bytes(tmp_path, "local.jsonl", b"same")
    remote = _snapshot_bytes(tmp_path, "remote.jsonl", b"same")
    assert local.path is not None
    assert remote.path is not None
    local.path.unlink()
    remote.path.unlink()

    assert classify_snapshots(local, remote, "")[:2] == ("synced", "none")


def test_equal_size_different_hashes_do_not_require_prefix_file_reads(
    tmp_path: Path,
) -> None:
    local = _snapshot_bytes(tmp_path, "local.jsonl", b"left")
    remote = _snapshot_bytes(tmp_path, "remote.jsonl", b"rght")
    assert local.path is not None
    assert remote.path is not None
    local.path.unlink()
    remote.path.unlink()

    assert classify_snapshots(local, remote, "")[:2] == ("conflict", "conflict")


def test_different_sizes_check_only_possible_prefix_direction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = _snapshot_bytes(tmp_path, "local.jsonl", b"longer")
    remote = _snapshot_bytes(tmp_path, "remote.jsonl", b"short")
    calls: list[tuple[SyncFileSnapshot, SyncFileSnapshot]] = []

    def not_a_prefix(prefix: SyncFileSnapshot, full: SyncFileSnapshot) -> bool:
        calls.append((prefix, full))
        return False

    monkeypatch.setattr(sync_planner, "is_byte_prefix", not_a_prefix)

    assert classify_snapshots(local, remote, "")[:2] == ("conflict", "conflict")
    assert calls == [(remote, local)]
