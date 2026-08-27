"""Exercise retained Task Storage commands through a packaged executable."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exercise Task Storage snapshot and analysis in a packaged executable."
    )
    parser.add_argument("--executable", type=Path, required=True)
    args = parser.parse_args(argv)

    executable = args.executable.expanduser().resolve()
    if not executable.is_file():
        raise RuntimeError(f"packaged executable is unavailable: {executable}")

    with TemporaryDirectory(prefix="codex-usage-storage-analysis-smoke-") as temporary:
        root = Path(temporary)
        codex_home = root / ".codex"
        sessions = codex_home / "sessions"
        archived = codex_home / "archived_sessions"
        sessions.mkdir(parents=True)
        archived.mkdir(parents=True)
        _write_task(sessions / "root.jsonl", "root", body="root side chat", compacted=True)
        _write_task(
            sessions / "child.jsonl",
            "child",
            parent_task_id="root",
            body="structured descendant",
        )
        _write_task(archived / "root-copy.jsonl", "root", body="archived root")

        environment = {
            **os.environ,
            "CODEX_HOME": str(codex_home),
            "CODEX_USAGE_CACHE_DIR": str(root / "cache"),
        }
        snapshot = _run_json(executable, ["storage", "snapshot", "--json"], environment)
        if snapshot.get("schema_version") != 4:
            raise RuntimeError(f"packaged storage schema was not version 4: {snapshot}")
        trees = snapshot.get("task_trees")
        if not isinstance(trees, list) or len(trees) != 1:
            raise RuntimeError(f"packaged storage inventory was incomplete: {snapshot}")
        tree = trees[0]
        if not isinstance(tree, dict) or tree.get("physical_file_count") != 3:
            raise RuntimeError(f"packaged storage tree omitted physical files: {tree}")
        retired = {"recovery_ready", "analysis_complete", "can_prepare_rollover"}
        if retired.intersection(tree):
            raise RuntimeError(f"packaged storage tree retained lifecycle fields: {tree}")

        analysis = _run_json(
            executable,
            ["storage", "analyze", "--tree-id", "root", "--json"],
            environment,
        )
        analyzed_tree = analysis.get("task_tree")
        if (
            not isinstance(analyzed_tree, dict)
            or analyzed_tree.get("analysis_status") != "complete"
            or analyzed_tree.get("compacted_record_count") != 1
            or analyzed_tree.get("embedded_media_occurrence_count") != 1
        ):
            raise RuntimeError(
                f"packaged storage analysis omitted content evidence: {analysis}"
            )
        warm_analysis = _run_json(
            executable,
            ["storage", "analyze", "--tree-id", "root", "--json"],
            environment,
        )
        warm_summary = warm_analysis.get("analysis")
        if (
            not isinstance(warm_summary, dict)
            or warm_summary.get("source_bytes_read") != 0
            or warm_summary.get("files_unchanged") != 3
        ):
            raise RuntimeError(
                f"packaged storage analysis missed warm reuse: {warm_analysis}"
            )

        for removed in ("backup", "verify", "rollover"):
            completed = subprocess.run(
                [str(executable), "storage", removed],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode == 0:
                raise RuntimeError(f"packaged executable retained storage {removed}")
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
        raise RuntimeError(
            f"packaged command returned invalid JSON: {completed.stdout}"
        ) from error
    if not isinstance(payload, dict):
        raise RuntimeError("packaged command returned a non-object JSON value")
    return payload


def _write_task(
    path: Path,
    task_id: str,
    *,
    parent_task_id: str = "",
    body: str,
    compacted: bool = False,
) -> None:
    metadata: dict[str, object] = {
        "id": task_id,
        "cwd": "/projects/packaged-storage-analysis-smoke",
        "timestamp": "2026-08-27T00:00:00Z",
    }
    if parent_task_id:
        metadata["source"] = {
            "subagent": {"thread_spawn": {"parent_thread_id": parent_task_id}}
        }
    rows = [
        {"type": "session_meta", "payload": metadata},
        {"type": "response_item", "payload": {"text": body}},
    ]
    if compacted:
        rows.append(
            {
                "type": "compacted",
                "payload": {
                    "history": body,
                    "image_url": "data:image/png;base64,c21va2U=",
                },
            }
        )
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
