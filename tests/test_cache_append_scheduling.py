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
