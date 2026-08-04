from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection
from pathlib import Path

import codex_usage.project_transition_evidence as evidence_module
import codex_usage.project_transition_state as state_module
import codex_usage.project_transitions as transitions_module
from codex_usage.parser import parse_timestamp
from codex_usage.project_transition_evidence import RepoPathObservation
from codex_usage.project_transitions import ProjectTransition
from codex_usage.session_cache_queries import (
    load_all_raw_candidates,
    load_raw_candidates_for_task_ids,
    load_records_for_task_ids,
)


def refresh_dirty_task_transitions(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    *,
    auto_transitions: bool,
) -> list[ProjectTransition]:
    dirty_task_ids = load_dirty_task_ids(connection)
    if dirty_task_ids and auto_transitions:
        replace_dirty_task_transitions(connection, session_dirs, dirty_task_ids)
    return load_transitions(connection) if auto_transitions else []


def load_cached_transition_observations(
    session_dirs: list[Path],
    *,
    cache_dir: Path | None = None,
) -> list[RepoPathObservation]:
    from codex_usage.session_cache import CACHE_DB_NAME, resolve_cache_dir

    database_path = resolve_cache_dir(session_dirs, cache_dir) / CACHE_DB_NAME
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        verification_cache: evidence_module.VerificationCache = {}
        observations = evidence_module.verify_repo_path_candidates(
            load_all_raw_candidates(connection),
            verification_cache=verification_cache,
        )
        observations.extend(
            state_module.collect_state_repo_path_observations(
                _state_session_dirs(session_dirs),
                verification_cache=verification_cache,
            )
        )
        return evidence_module._dedupe_observations(observations)
    finally:
        connection.close()


def load_dirty_task_ids(connection: sqlite3.Connection) -> tuple[str, ...]:
    return tuple(
        str(row["thread_id"])
        for row in connection.execute(
            "select thread_id from dirty_transition_tasks order by thread_id"
        )
        if row["thread_id"]
    )


def replace_dirty_task_transitions(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    dirty_task_ids: Collection[str],
) -> None:
    ordered_task_ids = tuple(sorted({task_id for task_id in dirty_task_ids if task_id}))
    verification_cache: evidence_module.VerificationCache = {}
    observations = evidence_module.verify_repo_path_candidates(
        load_raw_candidates_for_task_ids(connection, ordered_task_ids),
        verification_cache=verification_cache,
    )
    observations.extend(
        observation
        for observation in state_module.collect_state_repo_path_observations(
            _state_session_dirs(session_dirs),
            verification_cache=verification_cache,
        )
        if observation.thread_id in ordered_task_ids
    )
    transitions = transitions_module.infer_project_transitions(
        load_records_for_task_ids(connection, ordered_task_ids),
        evidence_module._dedupe_observations(observations),
    )
    _replace_dirty_task_transitions(connection, ordered_task_ids, transitions)


def load_transitions(connection: sqlite3.Connection) -> list[ProjectTransition]:
    transitions: list[ProjectTransition] = []
    for row in connection.execute(
        "select * from project_transitions order by effective_from, source_key, target_key"
    ):
        timestamp = parse_timestamp(row["effective_from"])
        if timestamp is None:
            continue
        transitions.append(
            ProjectTransition(
                source_key=row["source_key"],
                source_label=row["source_label"],
                target_key=row["target_key"],
                target_label=row["target_label"],
                effective_from=timestamp,
                confidence=int(row["confidence"]),
                evidence=tuple(json.loads(row["evidence_json"] or "[]")),
                thread_ids=tuple(json.loads(row["thread_ids_json"] or "[]")),
            )
        )
    return transitions


def _replace_dirty_task_transitions(
    connection: sqlite3.Connection,
    dirty_task_ids: tuple[str, ...],
    transitions: list[ProjectTransition],
) -> None:
    owned_transitions = [
        (_transition_owner(transition), transition) for transition in transitions
    ]
    connection.execute("begin immediate")
    try:
        for task_id in dirty_task_ids:
            connection.execute(
                "delete from project_transitions where owner_thread_id = ?",
                (task_id,),
            )
        _delete_legacy_global_transitions(connection, dirty_task_ids)
        for owner_thread_id, transition in owned_transitions:
            connection.execute(
                """
                insert into project_transitions (
                    owner_thread_id, source_key, source_label, target_key, target_label,
                    effective_from, confidence, evidence_json, thread_ids_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner_thread_id,
                    transition.source_key,
                    transition.source_label,
                    transition.target_key,
                    transition.target_label,
                    transition.effective_from.isoformat(),
                    transition.confidence,
                    json.dumps(list(transition.evidence)),
                    json.dumps(list(transition.thread_ids)),
                ),
            )
        connection.executemany(
            "delete from dirty_transition_tasks where thread_id = ?",
            [(task_id,) for task_id in dirty_task_ids],
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _transition_owner(transition: ProjectTransition) -> str:
    owners = tuple(
        sorted({thread_id for thread_id in transition.thread_ids if thread_id})
    )
    if len(owners) != 1:
        raise ValueError(
            "incremental project transitions require exactly one owner task"
        )
    return owners[0]


def _delete_legacy_global_transitions(
    connection: sqlite3.Connection,
    dirty_task_ids: tuple[str, ...],
) -> None:
    if dirty_task_ids:
        connection.execute("delete from project_transitions where owner_thread_id = ''")


def _state_session_dirs(session_dirs: list[Path]) -> list[Path]:
    seen_homes: set[Path] = set()
    selected: list[Path] = []
    for session_dir in session_dirs:
        codex_home = session_dir.parent
        if codex_home in seen_homes:
            continue
        seen_homes.add(codex_home)
        selected.append(session_dir)
    return selected
