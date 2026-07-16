from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGED_SYNC_SMOKE = ROOT / "scripts" / "smoke-test-packaged-sync.py"
PACKAGED_SYNC_VALIDATION = ROOT / "scripts" / "packaged_sync_smoke_validation.py"


def load_packaged_sync_smoke() -> ModuleType:
    scripts_dir = str(PACKAGED_SYNC_SMOKE.parent)
    spec = importlib.util.spec_from_file_location("packaged_sync_smoke", PACKAGED_SYNC_SMOKE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load smoke module from {PACKAGED_SYNC_SMOKE}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, scripts_dir)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(scripts_dir)
    return module


def inventory_payload(
    availability: str,
    *,
    thread_id: str = "thread-1",
    estimated_sync_bytes: int = 498,
    candidate_roots: list[str] | None = None,
) -> dict[str, object]:
    state, action = {
        "local": ("local_only", "push"),
        "remote": ("remote_only", "pull"),
        "both": ("synced", "none"),
    }[availability]
    return {
        "inventory_version": 2,
        "projects": [
            {
                "project_key": "https://github.com/example/packaged-sync-smoke",
                "project_label": "packaged-sync-smoke",
                "identity_kind": "git",
                "candidate_roots": candidate_roots or [],
                "tasks": [
                    {
                        "thread_id": thread_id,
                        "title": "Packaged sync smoke",
                        "updated_at": "2026-04-29T10:00:02Z",
                        "estimated_sync_bytes": estimated_sync_bytes,
                        "availability": availability,
                        "state": state,
                        "action": action,
                    }
                ],
            }
        ],
        "issues": [],
    }


def sha256_bytes(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def sync_result(
    direction: str,
    local_jsonl: Path,
    remote_jsonl: Path,
    source_bytes: bytes,
) -> dict[str, object]:
    pushing = direction == "push"
    return {
        "outcome": "completed",
        "counts": {
            "discovered": 1 if pushing else 0,
            "selected": 1,
            "remote": 0 if pushing else 1,
            "pulled": 0 if pushing else 1,
            "pushed": 1 if pushing else 0,
            "unchanged": 0,
            "conflicts": 0,
            "issues": 0,
        },
        "timings_ms": {
            "discovery": 1,
            "planning": 2,
            "pull": 3 if not pushing else 0,
            "push": 3 if pushing else 0,
            "index": 1,
            "total": 7,
        },
        "threads": [
            {
                "thread_id": "thread-1",
                "state": "local_only" if pushing else "remote_only",
                "action": direction,
                "reason": (
                    "local conversation is not in the sync folder"
                    if pushing
                    else "sync folder task is not local"
                ),
                "local_path": str(
                    local_jsonl if pushing else local_jsonl.resolve(strict=False)
                ),
                "remote_path": str(remote_jsonl),
                "local_sha256": sha256_bytes(source_bytes) if pushing else "",
                "remote_sha256": "" if pushing else sha256_bytes(source_bytes),
                "base_sha256": "",
                "updated_at": "2026-04-29T10:00:02Z",
                "source_relative_path": "2026/04/29/thread-1.jsonl",
                "project_key": "https://github.com/example/packaged-sync-smoke",
                "project_label": "packaged-sync-smoke",
                "memory_database_rows": 0,
            }
        ],
        "pulled": [] if pushing else ["thread-1"],
        "pushed": ["thread-1"] if pushing else [],
        "issues": [],
    }


def matching_metadata(row: dict[str, object], project_key: str) -> bool:
    payload = row.get("payload")
    git = payload.get("git") if isinstance(payload, dict) else None
    repository_url = str(git.get("repository_url") or "") if isinstance(git, dict) else ""
    return repository_url.removesuffix(".git") == project_key


def _write_baseline(
    smoke: ModuleType,
    codex_home: Path,
    local_bytes: bytes,
    remote_bytes: bytes,
) -> None:
    baseline = (
        codex_home
        / ".codex-sync-state"
        / "fingerprint"
        / "threads"
        / f"{smoke.THREAD_ID}.json"
    )
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_text(
        json.dumps(
            {
                "sync_version": 2,
                "thread_id": smoke.THREAD_ID,
                "sync_dir_fingerprint": "fingerprint",
                "base_sha256": sha256_bytes(local_bytes),
                "base_size_bytes": len(local_bytes),
                "base_updated_at": smoke.TASK_UPDATED_AT,
                "last_remote_sha256": sha256_bytes(remote_bytes),
                "last_local_sha256": sha256_bytes(local_bytes),
                "source_relative_path": smoke.SESSION_RELATIVE_PATH.as_posix(),
                "project_key": smoke.PROJECT_KEY,
                "project_label": smoke.PROJECT_LABEL,
                "synced_at": "2026-07-16T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )


class PackagedCommandDouble:
    def __init__(self, smoke: ModuleType, *, mutate_stage: str | None = None) -> None:
        self.smoke = smoke
        self.mutate_stage = mutate_stage
        self.calls: list[tuple[Path, tuple[str, ...], dict[str, str]]] = []

    def run(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        codex_home = Path(environment["CODEX_HOME"])
        command_args = tuple(command[1:])
        self.calls.append((codex_home, command_args, environment))
        sync_dir = Path(command_args[3])
        source_home = self.calls[0][0]
        source_jsonl = source_home / "sessions" / self.smoke.SESSION_RELATIVE_PATH
        remote_jsonl = sync_dir / "tasks" / f"{self.smoke.THREAD_ID}.jsonl"

        if len(self.calls) == 1:
            payload = inventory_payload(
                "local",
                estimated_sync_bytes=source_jsonl.stat().st_size + 4096,
            )
        elif len(self.calls) == 2:
            source_bytes = source_jsonl.read_bytes()
            remote_jsonl.parent.mkdir(parents=True, exist_ok=True)
            remote_jsonl.write_bytes(source_bytes)
            self._write_remote_index(sync_dir, source_bytes)
            _write_baseline(self.smoke, source_home, source_bytes, source_bytes)
            payload = sync_result("push", source_jsonl, remote_jsonl, source_bytes)
        elif len(self.calls) == 3:
            candidate_root = self._candidate_root(command_args)
            payload = inventory_payload(
                "remote",
                estimated_sync_bytes=source_jsonl.stat().st_size,
                candidate_roots=[candidate_root],
            )
            self._mutate_destination("inventory", codex_home)
        elif len(self.calls) == 4:
            candidate_root = self._candidate_root(command_args)
            imported_jsonl = codex_home / "sessions" / self.smoke.SESSION_RELATIVE_PATH
            rows = [json.loads(line) for line in remote_jsonl.read_bytes().splitlines()]
            for row in rows:
                if matching_metadata(row, self.smoke.PROJECT_KEY):
                    row["payload"]["cwd"] = candidate_root
            self.smoke._write_jsonl(imported_jsonl, rows)
            (codex_home / "session_index.jsonl").write_bytes(
                (source_home / "session_index.jsonl").read_bytes()
            )
            _write_baseline(
                self.smoke,
                codex_home,
                imported_jsonl.read_bytes(),
                remote_jsonl.read_bytes(),
            )
            payload = sync_result(
                "pull",
                imported_jsonl,
                remote_jsonl,
                remote_jsonl.read_bytes(),
            )
            self._mutate_destination("pull", codex_home)
        elif len(self.calls) == 5:
            imported_jsonl = codex_home / "sessions" / self.smoke.SESSION_RELATIVE_PATH
            payload = self._status_payload(imported_jsonl, remote_jsonl)
            self._mutate_destination("status", codex_home)
        else:
            raise AssertionError(f"Unexpected packaged command: {command!r}")
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    def _candidate_root(self, command_args: tuple[str, ...]) -> str:
        index = command_args.index("--candidate-project-root")
        return command_args[index + 1]

    def _mutate_destination(self, stage: str, codex_home: Path) -> None:
        if self.mutate_stage != stage:
            return
        filename = {
            "inventory": ".codex-global-state.json",
            "pull": "state_5.sqlite",
            "status": "unexpected-private-state.json",
        }[stage]
        (codex_home / filename).write_text("forbidden\n", encoding="utf-8")

    def _write_remote_index(self, sync_dir: Path, source_bytes: bytes) -> None:
        (sync_dir / "sync-index.json").write_text(
            json.dumps(
                {
                    "format_version": 3,
                    "updated_at": "2026-07-16T12:00:00Z",
                    "threads": {
                        self.smoke.THREAD_ID: {
                            "file": f"tasks/{self.smoke.THREAD_ID}.jsonl",
                            "source_relative_path": self.smoke.SESSION_RELATIVE_PATH.as_posix(),
                            "index_entry": {
                                "id": self.smoke.THREAD_ID,
                                "thread_name": self.smoke.TASK_TITLE,
                                "updated_at": self.smoke.TASK_UPDATED_AT,
                            },
                            "project_key": self.smoke.PROJECT_KEY,
                            "project_label": self.smoke.PROJECT_LABEL,
                            "project_aliases": [],
                            "sha256": sha256_bytes(source_bytes),
                            "size_bytes": len(source_bytes),
                            "session_updated_at": self.smoke.TASK_UPDATED_AT,
                            "exported_at": "2026-07-16T12:00:00Z",
                            "source_machine_id": "packaged-smoke",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    def _status_payload(self, imported_jsonl: Path, remote_jsonl: Path) -> dict[str, object]:
        local_bytes = imported_jsonl.read_bytes()
        remote_bytes = remote_jsonl.read_bytes()
        return {
            "threads": [
                {
                    "thread_id": self.smoke.THREAD_ID,
                    "state": "synced",
                    "action": "none",
                    "reason": "local and remote match their last synchronized versions",
                    "local_path": str(imported_jsonl),
                    "remote_path": str(remote_jsonl),
                    "local_sha256": sha256_bytes(local_bytes),
                    "remote_sha256": sha256_bytes(remote_bytes),
                    "base_sha256": sha256_bytes(local_bytes),
                    "updated_at": self.smoke.TASK_UPDATED_AT,
                    "source_relative_path": self.smoke.SESSION_RELATIVE_PATH.as_posix(),
                    "project_key": self.smoke.PROJECT_KEY,
                    "project_label": self.smoke.PROJECT_LABEL,
                    "memory_database_rows": 0,
                }
            ],
            "issues": [],
        }


def run_main(
    smoke: ModuleType,
    command_double: PackagedCommandDouble,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> int:
    executable = tmp_path / "codex-usage-double"
    executable.write_text("controlled executable double\n", encoding="utf-8")
    monkeypatch.setattr(smoke, "subprocess", SimpleNamespace(run=command_double.run))
    monkeypatch.setattr(
        sys,
        "argv",
        [str(PACKAGED_SYNC_SMOKE), "--executable", str(executable)],
    )
    return smoke.main()


def multi_record_rows(smoke: ModuleType, source_root: Path) -> list[dict[str, object]]:
    return [
        {
            "timestamp": "2026-04-29T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": smoke.THREAD_ID,
                "cwd": str(source_root),
                "git": {"repository_url": f"{smoke.PROJECT_KEY}.git"},
            },
        },
        {"timestamp": "2026-04-29T10:00:01Z", "type": "turn_context", "payload": {"turn_id": "one"}},
        {
            "timestamp": "2026-04-29T10:00:02Z",
            "type": "session_meta",
            "payload": {
                "id": smoke.THREAD_ID,
                "cwd": str(source_root),
                "git": {"repository_url": smoke.PROJECT_KEY},
            },
        },
        {
            "timestamp": "2026-04-29T10:00:03Z",
            "type": "session_meta",
            "payload": {
                "id": "unrelated",
                "cwd": "/unrelated/source",
                "git": {"repository_url": "https://github.com/example/unrelated.git"},
            },
        },
        {"timestamp": "2026-04-29T10:00:04Z", "type": "event_msg", "payload": {"type": "task_started"}},
    ]


def encode_rows(rows: list[dict[str, object]]) -> bytes:
    return "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows).encode()


def copied_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return copy.deepcopy(rows)
