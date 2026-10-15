"""Allowlisted lineage for physical pages of one logical Codex thread."""
from dataclasses import dataclass


class PaginatedHistoryError(ValueError):
    """An inherited counter cannot yet be attributed without guessing."""


@dataclass(frozen=True, slots=True)
class HistoryBoundary:
    thread_id: str
    end_ordinal_exclusive: int
    end_byte_offset: int

    @classmethod
    def from_mapping(cls, value):
        if value is None:
            return None
        if not isinstance(value, dict):
            raise PaginatedHistoryError("paginated_history_invalid_reference")
        thread = value.get("thread_id")
        ordinal = value.get("end_ordinal_exclusive")
        offset = value.get("end_byte_offset")
        if (not isinstance(thread, str) or not thread
                or type(ordinal) is not int or ordinal <= 0
                or type(offset) is not int or offset < 0):
            raise PaginatedHistoryError("paginated_history_invalid_reference")
        return cls(thread, ordinal, offset)

    @property
    def rollout_id(self):
        # The upstream field is historically called thread_id, but identifies
        # immutable physical storage, not SessionMeta.id or a logical parent.
        return self.thread_id

    def to_dict(self):
        return {"thread_id": self.thread_id,
                "end_ordinal_exclusive": self.end_ordinal_exclusive,
                "end_byte_offset": self.end_byte_offset}


def optional_ordinal(value):
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise PaginatedHistoryError("paginated_history_invalid_ordinal")
    return value
