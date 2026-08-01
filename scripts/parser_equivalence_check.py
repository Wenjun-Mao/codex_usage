#!/usr/bin/env python3
"""Capture bounded fixtures and compare parser results without exposing content."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import shutil
import sys
from pathlib import Path

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


_PATH_ERROR = "path must remain under evidence root"


def capture(
    source_root: Path,
    evidence_root: Path,
    *,
    limit: int,
    max_file_bytes: int,
) -> Path:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if max_file_bytes < 1:
        raise ValueError("max_file_bytes must be at least 1")
    if not source_root.is_dir():
        raise ValueError("source root must be a directory")

    candidates = _eligible_source_files(source_root, max_file_bytes)
    selected_count = min(limit, len(candidates))
    selected = [candidates[index] for index in _sample_indexes(len(candidates), selected_count)]

    evidence_root.mkdir(parents=True, exist_ok=True)
    if any(evidence_root.iterdir()):
        raise ValueError("evidence root must be empty")
    fixtures_root = evidence_root / "fixtures"
    fixtures_root.mkdir()

    fixtures: list[dict[str, object]] = []
    for index, (_, source_path) in enumerate(selected):
        relative_path = Path("fixtures") / f"{index:03d}.jsonl"
        copied_size = _copy_bounded(
            source_path,
            evidence_root / relative_path,
            max_file_bytes=max_file_bytes,
        )
        fixtures.append(
            {"fixture": relative_path.as_posix(), "size_bytes": copied_size}
        )

    manifest_path = evidence_root / "manifest.json"
    _write_json(manifest_path, {"version": 1, "fixtures": fixtures})
    return manifest_path


def digest(manifest_path: Path, package_root: Path, output_path: Path) -> Path:
    evidence_root = manifest_path.parent.resolve()
    resolved_output = _require_below(output_path, evidence_root)
    manifest = _read_payload(manifest_path, require_digest=False)
    parse_session_file = _load_parser(package_root)

    fixtures: list[dict[str, object]] = []
    for row in manifest["fixtures"]:
        fixture_path = _require_below(evidence_root / row["fixture"], evidence_root)
        if fixture_path.stat().st_size != row["size_bytes"]:
            raise ValueError("fixture size does not match manifest")
        parsed_digest = hashlib.sha256(
            repr(parse_session_file(fixture_path)).encode("utf-8")
        ).hexdigest()
        fixtures.append(
            {
                "fixture": row["fixture"],
                "size_bytes": row["size_bytes"],
                "digest": parsed_digest,
            }
        )

    _write_json(resolved_output, {"version": 1, "fixtures": fixtures})
    return output_path


def compare(oracle_path: Path, current_path: Path) -> int:
    evidence_root = oracle_path.parent.resolve()
    if current_path.parent.resolve() != evidence_root:
        raise ValueError(_PATH_ERROR)
    resolved_oracle = _require_below(oracle_path, evidence_root)
    resolved_current = _require_below(current_path, evidence_root)
    oracle = _read_payload(resolved_oracle, require_digest=True)
    current = _read_payload(resolved_current, require_digest=True)
    return 0 if oracle == current else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare bounded parser results without exposing fixture data."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("--source-root", type=Path, required=True)
    capture_parser.add_argument("--evidence-root", type=Path, required=True)
    capture_parser.add_argument("--limit", type=int, required=True)
    capture_parser.add_argument("--max-file-bytes", type=int, required=True)

    digest_parser = subparsers.add_parser("digest")
    digest_parser.add_argument("--manifest", type=Path, required=True)
    digest_parser.add_argument("--package-root", type=Path, required=True)
    digest_parser.add_argument("--output", type=Path, required=True)

    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--oracle", type=Path, required=True)
    compare_parser.add_argument("--current", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "capture":
            manifest_path = capture(
                args.source_root,
                args.evidence_root,
                limit=args.limit,
                max_file_bytes=args.max_file_bytes,
            )
            _print_summary(_read_payload(manifest_path, require_digest=False))
            return 0
        if args.command == "digest":
            output_path = digest(args.manifest, args.package_root, args.output)
            _print_summary(_read_payload(output_path, require_digest=True))
            return 0

        result = compare(args.oracle, args.current)
        payload = _read_payload(args.current, require_digest=True)
        _print_summary(payload, equivalent=result == 0)
        return result
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
        print(json.dumps({"error": True}, separators=(",", ":")), file=sys.stderr)
        return 2


@retry(
    retry=retry_if_exception_type(OSError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.2),
    reraise=True,
)
def _eligible_source_files(source_root: Path, max_file_bytes: int) -> list[tuple[int, Path]]:
    candidates: list[tuple[int, Path]] = []
    for path in source_root.rglob("*.jsonl"):
        if not path.is_file():
            continue
        size_bytes = path.stat().st_size
        if size_bytes <= max_file_bytes:
            candidates.append((size_bytes, path))
    return sorted(candidates, key=lambda item: (item[0], item[1].as_posix().casefold()))


def _sample_indexes(count: int, selected: int) -> tuple[int, ...]:
    if selected == 0:
        return ()
    if selected == 1:
        return (0,)
    return tuple(
        round(position * (count - 1) / (selected - 1))
        for position in range(selected)
    )


@retry(
    retry=retry_if_exception_type(OSError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.2),
    reraise=True,
)
def _copy_bounded(source: Path, target: Path, *, max_file_bytes: int) -> int:
    shutil.copyfile(source, target)
    copied_size = target.stat().st_size
    if copied_size > max_file_bytes:
        target.unlink(missing_ok=True)
        raise ValueError("source file exceeded capture byte limit")
    return copied_size


def _load_parser(package_root: Path):
    resolved_root = package_root.resolve()
    if not resolved_root.is_dir():
        raise ValueError("package root must be a directory")
    sys.path.insert(0, str(resolved_root))
    try:
        parser_module = importlib.import_module("codex_usage.parser")
    finally:
        sys.path.pop(0)
    module_path = Path(parser_module.__file__).resolve()
    if not module_path.is_relative_to(resolved_root):
        raise RuntimeError("requested package root was not used")
    return parser_module.parse_session_file


def _require_below(path: Path, evidence_root: Path) -> Path:
    resolved_path = path.resolve()
    if resolved_path == evidence_root or not resolved_path.is_relative_to(evidence_root):
        raise ValueError(_PATH_ERROR)
    return resolved_path


def _read_payload(path: Path, *, require_digest: bool) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected_payload_keys = {"version", "fixtures"}
    if not isinstance(payload, dict) or set(payload) != expected_payload_keys:
        raise ValueError("invalid evidence payload")
    if payload["version"] != 1 or not isinstance(payload["fixtures"], list):
        raise ValueError("invalid evidence payload")
    expected_row_keys = (
        {"fixture", "size_bytes", "digest"}
        if require_digest
        else {"fixture", "size_bytes"}
    )
    for row in payload["fixtures"]:
        if not isinstance(row, dict) or set(row) != expected_row_keys:
            raise ValueError("invalid evidence payload")
        if not isinstance(row["fixture"], str) or not isinstance(row["size_bytes"], int):
            raise ValueError("invalid evidence payload")
        if require_digest and not isinstance(row["digest"], str):
            raise ValueError("invalid evidence payload")
    return payload


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _print_summary(payload: dict[str, object], *, equivalent: bool | None = None) -> None:
    fixtures = payload["fixtures"]
    summary: dict[str, object] = {
        "fixture_count": len(fixtures),
        "byte_count": sum(row["size_bytes"] for row in fixtures),
    }
    if equivalent is not None:
        summary["equivalent"] = equivalent
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    raise SystemExit(main())
