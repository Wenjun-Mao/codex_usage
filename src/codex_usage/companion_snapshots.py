"""Bounded immutable query pages. Cursors never select a newer revision."""
from collections import OrderedDict
from dataclasses import dataclass
import json
import secrets
from time import monotonic

from codex_usage.companion_contract import CompanionError


@dataclass(frozen=True)
class Snapshot:
    expires: float
    envelope: dict
    data: dict
    size: int


class SnapshotStore:
    def __init__(self, *, clock=monotonic, ttl=600, max_bytes=32 * 1024 * 1024):
        self.clock, self.ttl, self.max_bytes = clock, ttl, max_bytes
        self.items: OrderedDict[str, Snapshot] = OrderedDict()
        self.cursors: dict[str, tuple[str, str, str, int, int]] = {}

    def put(self, envelope: dict, data: dict) -> str:
        self.prune()
        size = len(json.dumps(data, allow_nan=False))
        if size > self.max_bytes:
            raise CompanionError("scope_too_large")
        while self.items and (len(self.items) >= 8 or self.bytes_used + size > self.max_bytes):
            self.items.popitem(last=False)
        token = secrets.token_urlsafe(24)
        self.items[token] = Snapshot(self.clock() + self.ttl, envelope, data, size)
        self.prune()
        return token

    @property
    def bytes_used(self):
        return sum(item.size for item in self.items.values())

    def get(self, token: str) -> Snapshot:
        self.prune()
        result = self.items.get(token)
        if result is None:
            raise CompanionError("snapshot_expired")
        return result

    def prune(self):
        now = self.clock()
        for token in list(self.items):
            if self.items[token].expires <= now:
                del self.items[token]
        self.cursors = {k: v for k, v in self.cursors.items() if v[0] in self.items}

    def page(self, token: str, kind: str, dimension: str, offset: int, limit: int) -> dict:
        snapshot = self.get(token)
        rows = snapshot.data["dimensions"][dimension]
        next_cursor = None
        if offset + limit < len(rows):
            next_cursor = secrets.token_urlsafe(24)
            if len(self.cursors) >= 1000:
                self.cursors.pop(next(iter(self.cursors)))
            self.cursors[next_cursor] = (token, kind, dimension, offset + limit, limit)
        return {**snapshot.envelope, "snapshot_id": token,
                "data": {"dimension": dimension, "rows": rows[offset:offset + limit],
                         "total_rows": len(rows), "next_cursor": next_cursor,
                         "truncated": offset + limit < len(rows)}}

    def next_page(self, cursor: str, kind: str) -> dict:
        self.prune()
        value = self.cursors.get(cursor)
        if value is None:
            raise CompanionError("snapshot_expired")
        token, expected_kind, dimension, offset, limit = value
        if kind != expected_kind:
            raise CompanionError()
        return self.page(token, kind, dimension, offset, limit)
