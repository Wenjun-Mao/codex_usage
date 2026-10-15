"""Small public convenience API layered over the incremental parser."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from codex_usage.models import UsageRecord
from codex_usage.session_project_lineage import finalize_session_records
from codex_usage.session_history import HistorySource


def parse_session_files(paths: Iterable[Path]) -> list[UsageRecord]:
    paths = tuple(paths)
    sources = []
    for path in paths:
        stat = path.stat()
        sources.append(HistorySource(path, stat.st_size, stat.st_dev, stat.st_ino))
    return finalize_session_records([
        parse_session_file(path, history_sources=tuple(sources)) for path in paths])


def parse_session_file(path: Path, *, history_sources: tuple[HistorySource, ...] = ()) -> list[UsageRecord]:
    from codex_usage.parser import parse_session_generation

    return list(parse_session_generation(path, history_sources=history_sources).records)
