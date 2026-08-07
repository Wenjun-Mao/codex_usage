from __future__ import annotations

import json
import os
import pickle
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Never, Self

import project_transition_serial_oracle as serial_oracle
import pytest
from parallel_transition_test_support import (
    ShuffledTransitionResultMapper,
    write_transition_corpus,
)

import codex_usage.project_transition_candidates as candidate_module
import codex_usage.project_transition_collection as collection_module
import codex_usage.project_transition_evidence as evidence_module
import codex_usage.project_transition_state as state_module
from codex_usage.parallel.execution import OrderedProcessMapper
from codex_usage.parallel.transitions import (
    TransitionScanRequest,
    scan_transition_request,
)
from codex_usage.project_transition_candidates import (
    PartialTransitionReadError,
    RawRepoPathCandidate,
    read_jsonl_repo_path_candidates_once,
)
from codex_usage.project_transition_collection import (
    collect_repo_path_observations_with_report,
)
from codex_usage.project_transition_evidence import (
    RepoPathObservation,
    VerificationCache,
)
from codex_usage.session_cache import load_cached_session_data
from codex_usage.session_cache_transitions import load_cached_transition_observations


@pytest.fixture(autouse=True)
def reset_transition_mapper_double() -> Iterator[None]:
    ShuffledTransitionResultMapper.seed = 0
    ShuffledTransitionResultMapper.observed_orders.clear()
    yield
    ShuffledTransitionResultMapper.seed = 0
    ShuffledTransitionResultMapper.observed_orders.clear()


def test_frozen_serial_oracle_passes_one_cache_through_jsonl_and_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_caches: list[object] = []

    def track_jsonl(_session_files: list[Path], cache: object) -> list[RepoPathObservation]:
        seen_caches.append(cache)
        return []

    def track_state(_session_dirs: list[Path], cache: object) -> list[RepoPathObservation]:
        seen_caches.append(cache)
        return []

    monkeypatch.setattr(serial_oracle, "_collect_jsonl_observations", track_jsonl)
    monkeypatch.setattr(serial_oracle, "_collect_state_sqlite_observations", track_state)

    assert serial_oracle.collect_repo_path_observations([], []) == []
    assert len(seen_caches) == 2
    assert seen_caches[0] is seen_caches[1]


def test_parallel_collection_equals_frozen_serial_oracle(tmp_path: Path) -> None:
    corpus = write_transition_corpus(tmp_path)
    session_dirs = list(corpus.session_dirs)
    session_files = list(corpus.session_files)
    expected = serial_oracle.collect_repo_path_observations(session_dirs, session_files)
    actual, report = collect_repo_path_observations_with_report(
        session_dirs,
        session_files,
        max_workers=2,
    )
    assert actual == expected
    assert report.resolved_worker_count == 2
    assert report.worker_pids
    assert os.getpid() not in report.worker_pids
    assert report.used_serial_fallback is False


def test_cached_observations_equal_frozen_serial_oracle_without_jsonl_rescan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = write_transition_corpus(tmp_path)
    session_dirs = list(corpus.session_dirs)
    session_files = list(corpus.session_files)
    expected = serial_oracle.collect_repo_path_observations(session_dirs, session_files)
    cache_dir = tmp_path / "cache"
    load_cached_session_data(
        session_dirs,
        cache_dir=cache_dir,
        auto_transitions=False,
        max_workers=1,
    )

    original_open = Path.open

    def fail_source_rescan(path: Path, *args: object, **kwargs: object):
        if path.suffix == ".jsonl":
            raise AssertionError("cached transition observations must not read source JSONLs")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_source_rescan)
    actual = load_cached_transition_observations(session_dirs, cache_dir=cache_dir)

    assert actual == expected


def test_parent_uses_one_cache_across_jsonl_files_and_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = write_transition_corpus(tmp_path, repeat_same_path=True)
    session_dirs = list(corpus.session_dirs)
    session_files = list(corpus.session_files)
    seen_cache_ids: list[int] = []
    resolutions: list[str] = []
    original_verify = evidence_module.verify_repo_path_candidates
    original_state = state_module.collect_state_repo_path_observations
    original_resolve = evidence_module.verified_repo_observation_from_path

    def track_verify(
        candidates: Sequence[RawRepoPathCandidate],
        *,
        verification_cache: VerificationCache,
    ) -> list[RepoPathObservation]:
        seen_cache_ids.append(id(verification_cache))
        return original_verify(candidates, verification_cache=verification_cache)

    def track_state(
        session_dirs: list[Path],
        *,
        verification_cache: VerificationCache,
    ) -> list[RepoPathObservation]:
        seen_cache_ids.append(id(verification_cache))
        return original_state(session_dirs, verification_cache=verification_cache)

    def track_resolution(
        raw_path: str | Path,
        timestamp: datetime,
        thread_id: str,
        source: str,
    ) -> RepoPathObservation | None:
        resolutions.append(str(raw_path))
        return original_resolve(raw_path, timestamp, thread_id, source)

    monkeypatch.setattr(evidence_module, "verify_repo_path_candidates", track_verify)
    monkeypatch.setattr(state_module, "collect_state_repo_path_observations", track_state)
    monkeypatch.setattr(
        evidence_module, "verified_repo_observation_from_path", track_resolution
    )
    _observations, report = collect_repo_path_observations_with_report(
        session_dirs, session_files, max_workers=1
    )
    assert len(seen_cache_ids) == len(session_files) + 1
    assert len(set(seen_cache_ids)) == 1
    assert resolutions.count(str(corpus.repeated_repo)) == 1
    assert report.resolved_worker_count == 1
    assert report.worker_pids == (os.getpid(),)
    assert report.used_serial_fallback is False


def test_transition_request_result_pickle_and_varied_order_match_oracle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = write_transition_corpus(tmp_path)
    requests = tuple(
        TransitionScanRequest(ordinal, path)
        for ordinal, path in enumerate(corpus.session_files)
    )
    assert pickle.loads(pickle.dumps(requests)) == requests
    direct = scan_transition_request(requests[0])
    assert pickle.loads(pickle.dumps(direct)) == direct

    expected = serial_oracle.collect_repo_path_observations(
        list(corpus.session_dirs), list(corpus.session_files)
    )
    monkeypatch.setattr(
        collection_module, "OrderedProcessMapper", ShuffledTransitionResultMapper
    )
    observed_orders: set[tuple[int, ...]] = set()
    for seed in range(16):
        ShuffledTransitionResultMapper.seed = seed
        ShuffledTransitionResultMapper.observed_orders.clear()
        actual, report = collect_repo_path_observations_with_report(
            list(corpus.session_dirs), list(corpus.session_files), max_workers=2
        )
        observed_orders.update(ShuffledTransitionResultMapper.observed_orders)
        assert actual == expected
        assert report.used_serial_fallback is False
        assert report.file_error_count == 0
    assert len(observed_orders) == 2


@pytest.mark.parametrize(
    "failure",
    [
        OSError("transition read unavailable"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
    ],
    ids=["oserror", "unicode"],
)
def test_transition_read_exhaustion_is_three_attempt_error_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: OSError | UnicodeDecodeError,
) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    prefix = RawRepoPathCandidate(
        raw_path="/repo/already-read",
        timestamp=datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
        thread_id="thread-prefix",
        source="function_call",
    )
    calls = 0

    def fail_once(_path: Path) -> list[RawRepoPathCandidate]:
        nonlocal calls
        calls += 1
        raise PartialTransitionReadError((prefix,), failure)

    monkeypatch.setattr(
        candidate_module, "read_jsonl_repo_path_candidates_once", fail_once
    )
    request = TransitionScanRequest(0, path)
    with OrderedProcessMapper(
        scan_transition_request, task_count=1, max_workers=1
    ) as mapper:
        result = mapper.map_batch([request])[0]
    assert calls == 3
    assert result.request == request
    assert result.candidates == (prefix,)
    assert result.error == f"{type(failure).__name__}: {failure}"
    assert result.span.pid == os.getpid()
    assert mapper.worker_count == 1
    assert mapper.used_serial_fallback is False
    assert mapper.infrastructure_error == ""


def test_once_reader_wraps_a_late_read_error_with_the_valid_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "session.jsonl"
    valid_lines = (
        json.dumps(
            {
                "timestamp": "2026-07-31T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": "thread-prefix"},
            }
        )
        + "\n",
        json.dumps(
            {
                "timestamp": "2026-07-31T12:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "arguments": json.dumps(
                        {"workdir": "/repo/already-read", "command": "Get-Location"}
                    ),
                },
            }
        )
        + "\n",
    )

    path.write_bytes("".join(valid_lines).encode() + b"x")
    original_open = Path.open

    class LateFailingHandle:
        def __init__(self, handle: object) -> None:
            self._handle = handle
            self._read_count = 0

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> object:
            return self._handle.__exit__(*args)  # type: ignore[attr-defined]

        def __getattr__(self, name: str) -> object:
            return getattr(self._handle, name)

        def readline(self, size: int = -1) -> bytes:
            if self._read_count == len(valid_lines):
                raise OSError("late transition read failure")
            self._read_count += 1
            return self._handle.readline(size)  # type: ignore[attr-defined,no-any-return]

    def late_failing_open(candidate: Path, *args: object, **kwargs: object):
        handle = original_open(candidate, *args, **kwargs)
        return LateFailingHandle(handle) if candidate == path else handle

    monkeypatch.setattr(Path, "open", late_failing_open)
    with pytest.raises(PartialTransitionReadError) as caught:
        read_jsonl_repo_path_candidates_once(path)
    assert len(caught.value.candidates) == 1
    assert caught.value.candidates[0].thread_id == "thread-prefix"
    assert isinstance(caught.value.cause, OSError)
    assert str(caught.value.cause) == "late transition read failure"


def test_once_reader_wraps_an_open_error_with_an_empty_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "session.jsonl"

    def fail_open(*_args: object, **_kwargs: object) -> Never:
        raise OSError("transition open failure")

    monkeypatch.setattr(Path, "open", fail_open)
    with pytest.raises(PartialTransitionReadError) as caught:
        read_jsonl_repo_path_candidates_once(path)
    assert caught.value.candidates == ()
    assert isinstance(caught.value.cause, OSError)
    assert str(caught.value.cause) == "transition open failure"


def test_transition_non_io_error_propagates_without_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text("{}\n", encoding="utf-8")

    def fail_once(_path: Path) -> list[RawRepoPathCandidate]:
        raise ValueError("candidate contract violated")

    monkeypatch.setattr(
        candidate_module, "read_jsonl_repo_path_candidates_once", fail_once
    )
    with OrderedProcessMapper(
        scan_transition_request, task_count=1, max_workers=1
    ) as mapper, pytest.raises(ValueError, match="candidate contract violated"):
        mapper.map_batch([TransitionScanRequest(0, path)])
    assert mapper.worker_count == 1
    assert mapper.used_serial_fallback is False
    assert mapper.infrastructure_error == ""
