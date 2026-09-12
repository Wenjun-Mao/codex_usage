"""Small public convenience API layered over the incremental parser."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from codex_usage.models import UsageRecord
from codex_usage.session_project_lineage import finalize_session_records


def parse_session_files(paths: Iterable[Path]) -> list[UsageRecord]:
    return finalize_session_records([parse_session_file(path) for path in paths])


def parse_session_file(path: Path) -> list[UsageRecord]:
    from codex_usage.parser import parse_session_generation

    return list(parse_session_generation(path).records)
