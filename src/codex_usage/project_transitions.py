from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, replace
from datetime import datetime

from codex_usage.models import UsageRecord
from codex_usage.project_transition_evidence import (
    RepoPathObservation,
    collect_repo_path_observations,
)


@dataclass(frozen=True)
class ProjectTransition:
    source_key: str
    source_label: str
    target_key: str
    target_label: str
    effective_from: datetime
    confidence: int
    evidence: tuple[str, ...] = ()
    thread_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "source_key": self.source_key,
            "source_label": self.source_label,
            "target_key": self.target_key,
            "target_label": self.target_label,
            "effective_from": self.effective_from.isoformat(),
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "thread_ids": list(self.thread_ids),
        }


def infer_project_transitions(
    records: list[UsageRecord],
    observations: list[RepoPathObservation],
) -> list[ProjectTransition]:
    records_by_thread = _records_by_thread(records)
    transitions_by_key: dict[tuple[str, str, str], ProjectTransition] = {}

    for observation in sorted(observations, key=_observation_sort_key):
        if not observation.thread_id:
            continue

        thread_index = records_by_thread.get(observation.thread_id)
        if not thread_index:
            continue

        source_record = _latest_record_before(thread_index, observation.timestamp)
        if source_record is None or _record_matches_project(source_record, observation.project_key):
            continue

        key = (source_record.project_key, observation.thread_id, observation.project_key)
        if key in transitions_by_key:
            continue

        transitions_by_key[key] = ProjectTransition(
            source_key=source_record.project_key,
            source_label=source_record.project_label,
            target_key=observation.project_key,
            target_label=observation.project_label,
            effective_from=observation.timestamp,
            confidence=100,
            evidence=(observation.to_evidence_text(),),
            thread_ids=(observation.thread_id,),
        )

    return sorted(
        transitions_by_key.values(),
        key=lambda item: (item.effective_from, item.source_key, item.target_key, item.thread_ids),
    )


def apply_project_transitions(
    records: list[UsageRecord],
    transitions: list[ProjectTransition],
) -> list[UsageRecord]:
    if not transitions:
        return records

    ordered = sorted(transitions, key=lambda item: item.effective_from)
    rewritten: list[UsageRecord] = []
    for record in records:
        applied = None
        for transition in ordered:
            if (
                record.project_key == transition.source_key
                and record.timestamp >= transition.effective_from
                and (not transition.thread_ids or record.session_id in transition.thread_ids)
            ):
                applied = transition
        if applied is None:
            rewritten.append(record)
            continue
        aliases = _dedupe_aliases([record.project_key, *record.project_aliases], applied.target_key)
        rewritten.append(
            replace(
                record,
                project_key=applied.target_key,
                project_label=applied.target_label,
                project_aliases=aliases,
                project_previous_key=applied.source_key,
                project_previous_label=applied.source_label,
                project_transition_effective_from=applied.effective_from.isoformat(),
            )
        )
    return rewritten


_ThreadRecordIndex = tuple[list[datetime], list[UsageRecord]]


def _records_by_thread(records: list[UsageRecord]) -> dict[str, _ThreadRecordIndex]:
    grouped: dict[str, list[UsageRecord]] = {}
    for record in records:
        if not record.session_id:
            continue
        grouped.setdefault(record.session_id, []).append(record)

    indexed: dict[str, _ThreadRecordIndex] = {}
    for thread_id, thread_records in grouped.items():
        sorted_records = sorted(thread_records, key=_record_sort_key)
        indexed[thread_id] = ([record.timestamp for record in sorted_records], sorted_records)
    return indexed


def _latest_record_before(thread_index: _ThreadRecordIndex, timestamp: datetime) -> UsageRecord | None:
    timestamps, records = thread_index
    record_index = bisect_left(timestamps, timestamp) - 1
    if record_index < 0:
        return None
    return records[record_index]


def _record_matches_project(record: UsageRecord, project_key: str) -> bool:
    return project_key in {record.project_key, *record.project_aliases, record.project_previous_key}


def _record_sort_key(record: UsageRecord) -> tuple[datetime, str, str, str, str]:
    return (
        record.timestamp,
        str(record.file_path),
        record.turn_id,
        record.project_key,
        record.project_label,
    )


def _observation_sort_key(observation: RepoPathObservation) -> tuple[datetime, str, str, str, str, str]:
    return (
        observation.timestamp,
        observation.thread_id,
        observation.project_key,
        observation.resolved_path,
        observation.source,
        observation.raw_path,
    )


def _dedupe_aliases(values: list[str], primary_key: str) -> tuple[str, ...]:
    aliases: list[str] = []
    seen = {primary_key}
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        aliases.append(value)
    return tuple(aliases)
