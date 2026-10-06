"""Strict private query input and process-local opaque selection handles."""
from dataclasses import dataclass
import hashlib
import hmac
import re
import secrets
from threading import RLock

SCHEMA_VERSION = 1
MAX_PAGE_SIZE = 100


class CompanionError(ValueError):
    def __init__(self, code: str = "invalid_request") -> None:
        self.code = code
        super().__init__(code)


def check_fields(payload: dict, allowed: set[str]) -> None:
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise CompanionError()


def page_size(payload: dict) -> int:
    size = payload.get("limit", 25)
    if type(size) is not int or not 1 <= size <= MAX_PAGE_SIZE:
        raise CompanionError()
    return size


@dataclass(frozen=True, slots=True)
class QueryScope:
    period: str = "30d"
    start_date: str | None = None
    end_date: str | None = None
    project_ids: tuple[str, ...] = ()

    @classmethod
    def parse(cls, payload: object) -> "QueryScope":
        if not isinstance(payload, dict):
            raise CompanionError()
        check_fields(payload, {"period", "start_date", "end_date", "project_ids"})
        period = payload.get("period", "30d")
        if period not in {"today", "yesterday", "7d", "30d", "month", "all", "custom"}:
            raise CompanionError()
        ids = payload.get("project_ids", [])
        if not isinstance(ids, list) or len(ids) > 100 or not all(isinstance(i, str) for i in ids):
            raise CompanionError()
        start, end = payload.get("start_date"), payload.get("end_date")
        if any(value is not None and not isinstance(value, str) for value in (start, end)):
            raise CompanionError()
        return cls(period, start, end, tuple(sorted(set(ids))))

    def to_dict(self) -> dict:
        return {"period": self.period, "start_date": self.start_date,
                "end_date": self.end_date, "project_ids": list(self.project_ids)}


class SelectionHandles:
    """Handles are collector-instance-specific, never path or task IDs."""
    def __init__(self) -> None:
        self._secret = secrets.token_bytes(32)
        self._selections: dict[str, tuple[str, str]] = {}
        self._lock = RLock()

    def issue(self, kind: str, key: str) -> str:
        digest = hmac.new(self._secret, (kind + "\0" + key).encode(), hashlib.sha256).hexdigest()
        handle = kind + "_" + digest[:32]
        with self._lock:
            if len(self._selections) >= 100_000 and handle not in self._selections:
                raise CompanionError("scope_too_large")
            self._selections[handle] = (kind, key)
        return handle

    def resolve(self, kind: str, handle: str) -> str:
        with self._lock:
            selection = self._selections.get(handle)
        if selection is None or selection[0] != kind:
            raise CompanionError("selection_expired")
        return selection[1]


def model_label(value: str) -> str:
    # Unknown upstream model strings are data, not unrestricted display text.
    return value if re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", value) else "Unknown model"
