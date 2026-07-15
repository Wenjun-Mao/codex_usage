from __future__ import annotations

import json
from pathlib import Path

import pytest

from codex_usage.project_identity import normalize_project_key
from codex_usage.sync import session_materialization
from codex_usage.sync.errors import ConcurrentRemoteChangeError
from codex_usage.sync.io import snapshot_file
from codex_usage.sync.session_materialization import materialize_session_cwd


def test_materialize_session_cwd_changes_only_session_metadata_line(
    tmp_path: Path,
) -> None:
    source = tmp_path / "remote.jsonl"
    target = tmp_path / "local.jsonl"
    metadata = {
        "timestamp": "2026-07-14T12:00:00Z",
        "type": "session_meta",
        "payload": {
            "id": "thread-1",
            "cwd": r"D:\Projects\persona_generators",
            "nested": {"preserved": True},
        },
    }
    history = b'{"type":"event_msg","payload":{"text":"unchanged"}}\n\xff\x00tail'
    source.write_bytes(json.dumps(metadata).encode("utf-8") + b"\n" + history)

    written = materialize_session_cwd(
        source,
        target,
        local_cwd=tmp_path / "persona_generators",
        project_identities=frozenset({"d:/projects/persona_generators"}),
        expected_target=snapshot_file(target),
    )

    first_line, preserved_history = target.read_bytes().split(b"\n", 1)
    materialized = json.loads(first_line)
    assert materialized["payload"] == {
        "id": "thread-1",
        "cwd": str(tmp_path / "persona_generators"),
        "nested": {"preserved": True},
    }
    assert preserved_history == history
    assert written == snapshot_file(target)


def test_materialize_rewrites_every_metadata_record_for_the_bound_project(
    tmp_path: Path,
) -> None:
    source = tmp_path / "remote.jsonl"
    target = tmp_path / "local.jsonl"
    local_cwd = tmp_path / "persona_generators"
    records = [
        {
            "type": "session_meta",
            "payload": {
                "id": "task-1",
                "cwd": r"D:\Projects\persona_generators",
            },
        },
        {"type": "event_msg", "payload": {"text": "preserve me"}},
        {
            "type": "session_meta",
            "payload": {
                "id": "task-ancestor",
                "cwd": r"D:\Projects\persona_generators",
                "git": {
                    "repository_url": "https://github.com/example/persona_generators.git"
                },
            },
        },
        {
            "type": "session_meta",
            "payload": {
                "id": "unrelated-task",
                "cwd": r"D:\Projects\other",
                "git": {"repository_url": "https://github.com/example/other.git"},
            },
        },
    ]
    original_lines = [
        json.dumps(record, separators=(",", ":")).encode("utf-8") + b"\n"
        for record in records
    ]
    source.write_bytes(b"".join(original_lines))

    materialize_session_cwd(
        source,
        target,
        local_cwd=local_cwd,
        project_identities=frozenset(
            {
                "https://github.com/example/persona_generators",
                "d:/projects/persona_generators",
            }
        ),
        expected_target=snapshot_file(target),
        expected_source=snapshot_file(source),
    )

    output_lines = target.read_bytes().splitlines(keepends=True)
    assert json.loads(output_lines[0])["payload"]["cwd"] == str(local_cwd)
    assert output_lines[1] == original_lines[1]
    assert json.loads(output_lines[2])["payload"]["cwd"] == str(local_cwd)
    assert output_lines[3] == original_lines[3]


def test_materialize_session_cwd_keeps_exact_bytes_when_cwd_already_matches(
    tmp_path: Path,
) -> None:
    source = tmp_path / "remote.jsonl"
    target = tmp_path / "local.jsonl"
    cwd = tmp_path / "project"
    contents = (
        json.dumps(
            {
                "type": "session_meta",
                "payload": {"id": "thread-1", "cwd": str(cwd)},
            },
            indent=2,
        ).replace("\n", " ")
        + "\n"
        + '{"type":"event_msg"}'
    ).encode("utf-8")
    source.write_bytes(contents)

    materialize_session_cwd(
        source,
        target,
        local_cwd=cwd,
        project_identities=frozenset({normalize_project_key(str(cwd))}),
        expected_target=snapshot_file(target),
    )

    assert target.read_bytes() == contents


def test_exact_materialization_rejects_a_source_change_before_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "remote.jsonl"
    target = tmp_path / "local.jsonl"
    cwd = tmp_path / "project"
    source.write_text(
        json.dumps({"type": "session_meta", "payload": {"cwd": str(cwd)}}) + "\n",
        encoding="utf-8",
    )
    expected_source = snapshot_file(source)
    original_writer = session_materialization._write_materialized_session

    def write_then_change_source(*args, **kwargs):
        written = original_writer(*args, **kwargs)
        source.write_bytes(source.read_bytes() + b'{"type":"event_msg"}\n')
        return written

    monkeypatch.setattr(
        session_materialization,
        "_write_materialized_session",
        write_then_change_source,
    )

    with pytest.raises(ConcurrentRemoteChangeError):
        materialize_session_cwd(
            source,
            target,
            local_cwd=cwd,
            project_identities=frozenset({normalize_project_key(str(cwd))}),
            expected_target=snapshot_file(target),
            expected_source=expected_source,
        )

    assert not target.exists()
