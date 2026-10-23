"""Stream event records with query-local reuse of normalized immutable metadata."""
from datetime import UTC, datetime
import json
from pathlib import Path

from codex_usage.models import TokenUsage, UsageRecord, parse_usage_role
from codex_usage.parser import parse_timestamp


def context_values(row):
    return dict(effort=str(row["effort"]), collaboration_mode=str(row["collaboration_mode"]),
        project_key=str(row["project_key"]), project_label=str(row["project_label"]),
        project_aliases=tuple(json.loads(row["project_aliases_json"] or "[]")),
        cwd=str(row["cwd"]), git_repository_url=str(row["repository_url"]),
        git_branch=str(row["git_branch"]))


class RecordMetadata:
    """One SQL result owns these dictionaries; no cross-snapshot invalidation."""

    def __init__(self):
        self.contexts = {}
        self.paths = {}

    def context(self, row):
        key = row["context_id"]
        if key not in self.contexts:
            self.contexts[key] = context_values(row)
        return self.contexts[key]

    def path(self, row):
        key = row["file_path"]
        if key not in self.paths:
            self.paths[key] = Path(key)
        return self.paths[key]


def row_to_usage_record(row, metadata=None):
    timestamp = parse_timestamp(row["timestamp"])
    return UsageRecord(
        timestamp=timestamp or datetime.fromtimestamp(0, tz=UTC),
        usage=TokenUsage(
            input_tokens=int(row["input_tokens"]),
            cached_input_tokens=int(row["cached_input_tokens"]),
            cache_write_input_tokens=int(row["cache_write_input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            reasoning_output_tokens=int(row["reasoning_output_tokens"]),
            total_tokens=int(row["total_tokens"]),
        ),
        session_id=str(row["task_id"]),
        file_path=metadata.path(row) if metadata is not None else Path(row["file_path"]),
        usage_role=parse_usage_role(row["usage_role"]),
        model=str(row["model_key"]),
        turn_id=str(row["turn_id"]),
        parent_thread_id=str(row["parent_task_id"]),
        **(metadata.context(row) if metadata is not None else context_values(row)),
    )
