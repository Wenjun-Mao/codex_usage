from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exercise Task Storage backup through a packaged codex-usage executable."
    )
    parser.add_argument("--executable", type=Path, required=True)
    args = parser.parse_args(argv)

    executable = args.executable.expanduser().resolve()
    if not executable.is_file():
        raise RuntimeError(f"packaged executable is unavailable: {executable}")

    with TemporaryDirectory(prefix="codex-usage-backup-smoke-") as temporary:
        root = Path(temporary)
        codex_home = root / ".codex"
        sessions = codex_home / "sessions"
        archived = codex_home / "archived_sessions"
        sessions.mkdir(parents=True)
        archived.mkdir(parents=True)
        _write_task(sessions / "root.jsonl", "root", body="root side chat")
        _write_task(
            sessions / "child.jsonl",
            "child",
            parent_task_id="root",
            body="structured descendant",
        )
        _write_task(archived / "root-copy.jsonl", "root", body="archived root")
        (codex_home / "session_index.jsonl").write_text(
            json.dumps({"id": "root", "thread_name": "Packaged backup smoke"})
            + "\n"
            + json.dumps({"id": "child", "thread_name": "Internal child"})
            + "\n",
            encoding="utf-8",
        )

        environment = {
            **os.environ,
            "CODEX_HOME": str(codex_home),
            "CODEX_USAGE_CACHE_DIR": str(root / "cache"),
        }
        snapshot = _run_json(executable, ["storage", "snapshot", "--json"], environment)
        trees = snapshot.get("task_trees")
        if not isinstance(trees, list) or len(trees) != 1:
            raise RuntimeError(f"packaged storage inventory was incomplete: {snapshot}")
        tree = trees[0]
        if not isinstance(tree, dict) or tree.get("physical_file_count") != 3:
            raise RuntimeError(f"packaged storage tree omitted physical files: {tree}")

        archive = root / "smoke.codex-task-backup"
        created = _run_json(
            executable,
            [
                "storage",
                "backup",
                "--tree-id",
                "root",
                "--output",
                str(archive),
                "--compression",
                "balanced",
                "--json",
            ],
            environment,
        )
        verified = _run_json(
            executable,
            ["storage", "verify", str(archive), "--json"],
            environment,
        )
        if created.get("archive_sha256") != verified.get("archive_sha256"):
            raise RuntimeError("packaged backup verification changed the archive digest")
        if created.get("file_count") != 3 or created.get("recovery_ready") is not True:
            raise RuntimeError(f"packaged backup result was incomplete: {created}")

        damaged = root / "damaged.codex-task-backup"
        contents = archive.read_bytes()
        damaged.write_bytes(contents[: max(1, len(contents) // 2)])
        rejected = subprocess.run(
            [str(executable), "storage", "verify", str(damaged), "--json"],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if rejected.returncode == 0:
            raise RuntimeError("packaged verifier accepted a truncated backup")
    return 0


def _run_json(
    executable: Path,
    arguments: list[str],
    environment: dict[str, str],
) -> dict[str, object]:
    completed = subprocess.run(
        [str(executable), *arguments],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"packaged command failed ({completed.returncode}): "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"packaged command returned invalid JSON: {completed.stdout}") from error
    if not isinstance(payload, dict):
        raise RuntimeError("packaged command returned a non-object JSON value")
    return payload


def _write_task(
    path: Path,
    task_id: str,
    *,
    parent_task_id: str = "",
    body: str,
) -> None:
    metadata: dict[str, object] = {
        "id": task_id,
        "cwd": "/projects/packaged-backup-smoke",
        "timestamp": "2026-08-07T00:00:00Z",
    }
    if parent_task_id:
        metadata["source"] = {
            "subagent": {"thread_spawn": {"parent_thread_id": parent_task_id}}
        }
    path.write_text(
        json.dumps({"type": "session_meta", "payload": metadata})
        + "\n"
        + json.dumps({"type": "response_item", "payload": {"text": body}})
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
