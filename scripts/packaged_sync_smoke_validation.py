from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


THREAD_ID = "thread-1"
SESSION_RELATIVE_PATH = Path("2026") / "04" / "29" / f"{THREAD_ID}.jsonl"
TASK_TITLE = "Packaged sync smoke"
TASK_UPDATED_AT = "2026-04-29T10:00:02Z"
PROJECT_KEY = "https://github.com/example/packaged-sync-smoke"
PROJECT_LABEL = "packaged-sync-smoke"
UNRELATED_PROJECT_KEY = "https://github.com/example/packaged-sync-unrelated"
INVENTORY_VERSION = 2
REMOTE_TRANSFER_FORMAT_VERSION = 3
LOCAL_BASELINE_VERSION = 2
TASKS_DIRNAME = "tasks"
LOCAL_METADATA_ESTIMATE_BYTES = 4096
MAX_SAFE_INTEGER = 2**53 - 1

FORBIDDEN_DESTINATION_STATE_FILENAMES = frozenset(
    {
        ".codex-global-state.json",
        "state_5.sqlite",
        "state_5.sqlite-wal",
        "state_5.sqlite-shm",
    }
)
RESULT_FIELDS = {
    "outcome",
    "counts",
    "timings_ms",
    "threads",
    "pulled",
    "pushed",
    "issues",
}
COUNT_FIELDS = {
    "discovered",
    "selected",
    "remote",
    "pulled",
    "pushed",
    "unchanged",
    "conflicts",
    "issues",
}
TIMING_FIELDS = {"discovery", "planning", "pull", "push", "index", "total"}
PLAN_ITEM_FIELDS = {
    "thread_id",
    "state",
    "action",
    "reason",
    "local_path",
    "remote_path",
    "local_sha256",
    "remote_sha256",
    "base_sha256",
    "updated_at",
    "source_relative_path",
    "project_key",
    "project_label",
    "memory_database_rows",
}


def _require_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise RuntimeError(
            f"Packaged sync validation failed for {label}: "
            f"expected {expected!r}, got {actual!r}"
        )


def _require_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise RuntimeError(
            f"Packaged sync validation failed for {label}: expected an object, got {value!r}"
        )
    return value


def _require_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise RuntimeError(
            f"Packaged sync validation failed for {label}: expected a list, got {value!r}"
        )
    return value


def _require_exact_fields(
    value: dict[str, object],
    required: set[str],
    label: str,
    *,
    optional: set[str] | None = None,
) -> None:
    optional_fields = optional or set()
    keys = set(value)
    if not required.issubset(keys) or not keys.issubset(required | optional_fields):
        raise RuntimeError(
            f"Packaged sync validation failed for {label} fields: "
            f"expected required {sorted(required)!r} and optional "
            f"{sorted(optional_fields)!r}, got {sorted(keys)!r}"
        )


def _require_values(
    value: dict[str, object], expected: dict[str, object], label: str
) -> None:
    field_labels = {
        "thread_id": "thread id",
        "pulled": "pulled thread ids",
        "pushed": "pushed thread ids",
    }
    for field, expected_value in expected.items():
        display = field_labels.get(field, field)
        _require_equal(value.get(field), expected_value, f"{label} {display}")


def _require_nonnegative_integer(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_SAFE_INTEGER:
        raise RuntimeError(
            f"Packaged sync validation failed for {label}: "
            f"expected a safe nonnegative integer, got {value!r}"
        )
    return value


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(
            f"Packaged sync validation failed for {label}: expected a string, got {value!r}"
        )
    return value


def _read_required_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise RuntimeError(
            f"Packaged sync validation could not read {label} at {path}: {error}"
        ) from error


def _read_json_object(path: Path, label: str) -> dict[str, object]:
    contents = _read_required_bytes(path, label)
    try:
        value = json.loads(contents)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeError(
            f"Packaged sync validation found invalid JSON in {label} at {path}"
        ) from error
    return _require_object(value, label)


def _sha256(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _validate_inventory(
    result: dict[str, object],
    availability: str,
    estimated_sync_bytes: int,
    *,
    candidate_project_root: Path | None = None,
) -> None:
    _require_exact_fields(result, {"inventory_version", "projects", "issues"}, "inventory")
    _require_equal(result.get("inventory_version"), INVENTORY_VERSION, "inventory_version")
    _require_equal(result.get("issues"), [], f"{availability} inventory issues")
    projects = _require_list(result.get("projects"), f"{availability} inventory projects")
    _require_equal(len(projects), 1, f"{availability} inventory project count")
    project = _require_object(projects[0], f"{availability} inventory project")
    project_fields = {
        "project_key",
        "project_label",
        "identity_kind",
        "candidate_roots",
        "tasks",
    }
    _require_exact_fields(project, project_fields, "inventory project")
    expected_roots = [str(candidate_project_root)] if candidate_project_root else []
    _require_values(
        project,
        {
            "project_key": PROJECT_KEY,
            "project_label": PROJECT_LABEL,
            "identity_kind": "git",
            "candidate_roots": expected_roots,
        },
        f"{availability} inventory project",
    )
    tasks = _require_list(project.get("tasks"), f"{availability} inventory tasks")
    _require_equal(len(tasks), 1, f"{availability} inventory task count")
    task = _require_object(tasks[0], f"{availability} inventory task")
    task_fields = {
        "thread_id",
        "title",
        "updated_at",
        "estimated_sync_bytes",
        "availability",
        "state",
        "action",
    }
    _require_exact_fields(task, task_fields, "inventory task")
    expected_state, expected_action = {
        "local": ("local_only", "push"),
        "remote": ("remote_only", "pull"),
    }[availability]
    _require_values(
        task,
        {
            "thread_id": THREAD_ID,
            "title": TASK_TITLE,
            "updated_at": TASK_UPDATED_AT,
            "estimated_sync_bytes": estimated_sync_bytes,
            "availability": availability,
            "state": expected_state,
            "action": expected_action,
        },
        f"{availability} inventory task",
    )


def _validate_sync_result(
    result: dict[str, object],
    direction: str,
    *,
    local_jsonl: Path,
    remote_jsonl: Path,
    source_bytes: bytes,
) -> None:
    if direction not in {"push", "pull"}:
        raise ValueError(f"Unsupported packaged sync direction: {direction!r}")
    pushing = direction == "push"
    _require_exact_fields(result, RESULT_FIELDS, "result")
    _require_equal(result.get("outcome"), "completed", f"{direction} outcome")

    counts = _require_object(result.get("counts"), f"{direction} counts")
    _require_exact_fields(counts, COUNT_FIELDS, "counts")
    for field in COUNT_FIELDS:
        _require_nonnegative_integer(counts.get(field), f"counts.{field}")
    expected_counts = {
        "discovered": 1 if pushing else 0,
        "selected": 1,
        "remote": 0 if pushing else 1,
        "pulled": 0 if pushing else 1,
        "pushed": 1 if pushing else 0,
        "unchanged": 0,
        "conflicts": 0,
        "issues": 0,
    }
    _require_equal(counts, expected_counts, f"{direction} counts")

    timings = _require_object(result.get("timings_ms"), "timings_ms")
    _require_exact_fields(timings, TIMING_FIELDS, "timings")
    for field in TIMING_FIELDS:
        _require_nonnegative_integer(timings.get(field), f"timings_ms.{field}")

    threads = _require_list(result.get("threads"), "threads")
    _require_equal(len(threads), 1, f"{direction} selected plan item count")
    item = _require_object(threads[0], f"{direction} plan item")
    _require_exact_fields(item, PLAN_ITEM_FIELDS, "plan item", optional={"memory_note"})
    for field in PLAN_ITEM_FIELDS - {"memory_database_rows"}:
        _require_string(item.get(field), f"plan item {field}")
    _require_nonnegative_integer(
        item.get("memory_database_rows"), "plan item memory_database_rows"
    )
    if "memory_note" in item:
        _require_string(item.get("memory_note"), "plan item memory_note")
    expected_item: dict[str, object] = {
        "thread_id": THREAD_ID,
        "state": "local_only" if pushing else "remote_only",
        "action": direction,
        "reason": (
            "local conversation is not in the sync folder"
            if pushing
            else "sync folder task is not local"
        ),
        "updated_at": TASK_UPDATED_AT,
        "source_relative_path": SESSION_RELATIVE_PATH.as_posix(),
        "project_key": PROJECT_KEY,
        "project_label": PROJECT_LABEL,
        "memory_database_rows": 0,
        "base_sha256": "",
        "local_path": str(
            local_jsonl if pushing else local_jsonl.resolve(strict=False)
        ),
        "remote_path": str(remote_jsonl),
        "local_sha256": _sha256(source_bytes) if pushing else "",
        "remote_sha256": "" if pushing else _sha256(source_bytes),
    }
    _require_values(item, expected_item, f"{direction} plan item")
    for field in ("pulled", "pushed", "issues"):
        _require_list(result.get(field), f"{direction} {field}")
    _require_values(
        result,
        {
            "pulled": [] if pushing else [THREAD_ID],
            "pushed": [THREAD_ID] if pushing else [],
            "issues": [],
        },
        direction,
    )


def _validate_remote_layout(sync_dir: Path, source_bytes: bytes) -> None:
    tasks_dir = sync_dir / TASKS_DIRNAME
    try:
        task_files = sorted(path.name for path in tasks_dir.iterdir())
    except OSError as error:
        raise RuntimeError(
            f"Packaged sync validation could not inspect version-3 tasks at {tasks_dir}: {error}"
        ) from error
    _require_equal(task_files, [f"{THREAD_ID}.jsonl"], "version-3 task files")
    remote_jsonl = tasks_dir / f"{THREAD_ID}.jsonl"
    _require_equal(
        _read_required_bytes(remote_jsonl, "remote task JSONL"),
        source_bytes,
        "pushed task JSONL bytes",
    )
    sync_index = _read_json_object(sync_dir / "sync-index.json", "sync index")
    _require_equal(
        sync_index.get("format_version"),
        REMOTE_TRANSFER_FORMAT_VERSION,
        "index format",
    )
    indexed_threads = _require_object(sync_index.get("threads"), "sync index threads")
    _require_equal(set(indexed_threads), {THREAD_ID}, "sync index thread ids")
    entry = _require_object(indexed_threads[THREAD_ID], "sync index task entry")
    _require_values(
        entry,
        {
            "file": f"{TASKS_DIRNAME}/{THREAD_ID}.jsonl",
            "sha256": _sha256(source_bytes),
            "size_bytes": len(source_bytes),
            "source_relative_path": SESSION_RELATIVE_PATH.as_posix(),
            "project_key": PROJECT_KEY,
        },
        "sync index task",
    )
    for legacy_dir in ("conversations", "threads"):
        if sync_dir.joinpath(legacy_dir).exists():
            raise RuntimeError(
                f"Packaged sync validation found obsolete {legacy_dir!r} directory"
            )


def _validate_baseline(codex_home: Path, local_bytes: bytes, remote_bytes: bytes) -> None:
    baseline_files = sorted((codex_home / ".codex-sync-state").glob("*/threads/*.json"))
    _require_equal(len(baseline_files), 1, f"{codex_home.name} baseline file count")
    baseline = _read_json_object(baseline_files[0], f"{codex_home.name} baseline")
    _require_values(
        baseline,
        {
            "sync_version": LOCAL_BASELINE_VERSION,
            "thread_id": THREAD_ID,
            "base_sha256": _sha256(local_bytes),
            "base_size_bytes": len(local_bytes),
            "last_remote_sha256": _sha256(remote_bytes),
            "last_local_sha256": _sha256(local_bytes),
            "source_relative_path": SESSION_RELATIVE_PATH.as_posix(),
            "project_key": PROJECT_KEY,
            "project_label": PROJECT_LABEL,
        },
        f"{codex_home.name} baseline",
    )
    if not baseline.get("sync_dir_fingerprint") or not baseline.get("synced_at"):
        raise RuntimeError(f"Incomplete baseline metadata in {baseline_files[0]}")


def _normalized_repository_url(value: object) -> str:
    text = str(value or "").strip().rstrip("/")
    return text[:-4] if text.casefold().endswith(".git") else text


def _metadata_matches_project(row: dict[str, object]) -> bool:
    payload = row.get("payload")
    git = payload.get("git") if isinstance(payload, dict) else None
    repository_url = git.get("repository_url") if isinstance(git, dict) else ""
    return _normalized_repository_url(repository_url) == PROJECT_KEY


def _parse_json_line(line: bytes, label: str) -> dict[str, object]:
    try:
        return _require_object(json.loads(line), label)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeError(f"Packaged sync validation found invalid {label}") from error


def _validate_imported_task(
    imported_jsonl: Path,
    source_bytes: bytes,
    project_root: Path,
) -> bytes:
    imported_bytes = _read_required_bytes(imported_jsonl, "imported task JSONL")
    source_lines = source_bytes.splitlines(keepends=True)
    imported_lines = imported_bytes.splitlines(keepends=True)
    _require_equal(len(imported_lines), len(source_lines), "imported task line count")
    matching_count = unrelated_count = non_metadata_count = 0
    for index, (source_line, imported_line) in enumerate(
        zip(source_lines, imported_lines, strict=True)
    ):
        source_row = _parse_json_line(source_line, f"source task line {index}")
        imported_row = _parse_json_line(imported_line, f"imported task line {index}")
        if source_row.get("type") == "session_meta" and _metadata_matches_project(source_row):
            matching_count += 1
            expected_row = copy.deepcopy(source_row)
            payload = _require_object(expected_row.get("payload"), "matching metadata")
            payload["cwd"] = str(project_root)
            _require_equal(imported_row, expected_row, f"imported task matching metadata {index}")
            continue
        if source_row.get("type") == "session_meta":
            unrelated_count += 1
        else:
            non_metadata_count += 1
        _require_equal(imported_line, source_line, f"imported task unchanged line {index}")
    if matching_count < 2 or unrelated_count < 1 or non_metadata_count < 1:
        raise RuntimeError(
            "Packaged sync validation failed for imported task fixture coverage: "
            f"matching={matching_count}, unrelated={unrelated_count}, "
            f"non_metadata={non_metadata_count}"
        )
    return imported_bytes


def _validate_status(
    result: dict[str, object],
    imported_jsonl: Path,
    remote_jsonl: Path,
    imported_bytes: bytes,
    remote_bytes: bytes,
) -> None:
    _require_exact_fields(result, {"threads", "issues"}, "status")
    _require_equal(result.get("issues"), [], "status issues")
    threads = _require_list(result.get("threads"), "status threads")
    _require_equal(len(threads), 1, "status thread count")
    task = _require_object(threads[0], "status task")
    _require_values(
        task,
        {
            "thread_id": THREAD_ID,
            "state": "synced",
            "action": "none",
            "local_path": str(imported_jsonl),
            "remote_path": str(remote_jsonl),
            "local_sha256": _sha256(imported_bytes),
            "remote_sha256": _sha256(remote_bytes),
            "base_sha256": _sha256(imported_bytes),
        },
        "status",
    )


def _expected_target_tree(target_home: Path, imported_jsonl: Path) -> set[str]:
    baseline_files = sorted((target_home / ".codex-sync-state").glob("*/threads/*.json"))
    _require_equal(len(baseline_files), 1, "destination baseline file count")
    expected_files = {imported_jsonl, target_home / "session_index.jsonl", baseline_files[0]}
    expected: set[str] = set()
    for path in expected_files:
        current = path
        while current != target_home:
            expected.add(current.relative_to(target_home).as_posix())
            current = current.parent
    return expected


def _validate_destination_home(
    target_home: Path,
    stage: str,
    *,
    imported_jsonl: Path | None = None,
) -> None:
    actual = {path.relative_to(target_home).as_posix() for path in target_home.rglob("*")}
    expected = set() if imported_jsonl is None else _expected_target_tree(target_home, imported_jsonl)
    unexpected = sorted(actual - expected)
    missing = sorted(expected - actual)
    forbidden = sorted(
        path for path in actual if Path(path).name in FORBIDDEN_DESTINATION_STATE_FILENAMES
    )
    if unexpected or missing or forbidden:
        raise RuntimeError(
            f"Packaged sync validation failed: destination {stage} wrote unexpected "
            f"Codex-home paths {unexpected!r}; forbidden={forbidden!r}; missing={missing!r}"
        )
