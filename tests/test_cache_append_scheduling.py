from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

from parallel_cache_test_support import SerialUsageTestMapper, write_valid_usage_set

import codex_usage.session_cache_refresh as refresh_module
from codex_usage.parallel.usage import UsageParseRequest, UsageParseResult
from codex_usage.session_cache import load_cached_session_data


class ObservingUsageMapper(SerialUsageTestMapper):
    orders: ClassVar[list[tuple[tuple[Path, int], ...]]] = []

    def map_batch(
        self,
        requests: Sequence[UsageParseRequest],
    ) -> list[UsageParseResult]:
        self.orders.append(
            tuple((request.path, request.estimated_bytes) for request in requests)
        )
        return super().map_batch(requests)


def test_groups_schedule_largest_unread_work_first(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sessions, paths = write_valid_usage_set(tmp_path / "codex", count=3)
    for index, path in enumerate(paths):
        _append_irrelevant_bytes(path, index * 10_000)
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(refresh_module, "OrderedProcessMapper", ObservingUsageMapper)
    ObservingUsageMapper.orders.clear()

    load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )

    cold_order = ObservingUsageMapper.orders[-1]
    assert [path for path, _bytes in cold_order] == [paths[2], paths[1], paths[0]]
    assert [size for _path, size in cold_order] == sorted(
        (path.stat().st_size for path in paths),
        reverse=True,
    )

    ObservingUsageMapper.orders.clear()
    for index, path in enumerate(paths):
        _append_irrelevant_bytes(path, (2 - index) * 5_000)
    load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )

    append_order = ObservingUsageMapper.orders[-1]
    assert [path for path, _bytes in append_order] == [paths[0], paths[1], paths[2]]
    assert [size for _path, size in append_order] == sorted(
        (size for _path, size in append_order),
        reverse=True,
    )


def test_total_parse_budget_is_shared_fairly_across_sources(tmp_path: Path) -> None:
    quantum = 16 * 1024 * 1024
    plans = [
        (
            (1, 2, "", size, ordinal),
            UsageParseRequest(
                ordinal=ordinal,
                file_key=f"task-{ordinal}",
                path=tmp_path / f"task-{ordinal}.jsonl",
                size_bytes=size,
                mtime_ns=ordinal,
            ),
        )
        for ordinal, size in enumerate([32 * 1024 * 1024] * 5)
    ]

    selected = refresh_module._apply_total_parse_budget(
        plans,
        max_total_parse_bytes=64 * 1024 * 1024,
        max_parse_bytes=quantum,
    )

    assert len(selected) == 4
    assert [request.max_bytes for request in selected] == [quantum] * 4


def test_dirty_source_is_selected_before_older_baseline_work(tmp_path: Path) -> None:
    ordinary = UsageParseRequest(
        ordinal=0,
        file_key="ordinary",
        path=tmp_path / "ordinary.jsonl",
        size_bytes=32,
        mtime_ns=1,
    )
    dirty = UsageParseRequest(
        ordinal=1,
        file_key="dirty",
        path=tmp_path / "dirty.jsonl",
        size_bytes=32,
        mtime_ns=2,
    )
    plans = [
        ((1, 2, "", 32, 0), ordinary),
        ((0, 2, "", 32, 1), dirty),
    ]

    selected = refresh_module._apply_total_parse_budget(
        plans,
        max_total_parse_bytes=16,
        max_parse_bytes=16,
    )

    assert [request.file_key for request in selected] == ["dirty"]
    assert selected[0].max_bytes == 16


def _append_irrelevant_bytes(path: Path, count: int) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {"type": "message", "text": "x" * count},
                }
            )
            + "\n"
        )
