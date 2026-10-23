"""Exact-prefix reuse for one display-authority lane and limit.

Resolved identities and canonical positions are part of the prefix. A future
plan can therefore invalidate old unknown runs; a late insertion or changed
authority lane cannot reuse an index belonging to another capture.
"""
from dataclasses import asdict
import hashlib

from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_pace_evidence import Continuity
from codex_usage.history_preparation_cache import encode

def _extend(hasher, timeline, identities, positions, start, end):
    # Bounded batches keep fingerprinting from allocating a second full history.
    for offset in range(start, end, 4096):
        rows = [(time, identities[i], [positions[p] for p in points])
                for i in range(offset, min(offset + 4096, end)) for time, points in (timeline[i],)]
        if offset:
            hasher.update(b",")
        hasher.update(encode(rows)[1:-1].encode())


class SegmentCheckpoint:
    def __init__(self, cache, lane, limit, timeline, identities, positions):
        self.cache = cache
        self.slot = "segment-2:" + encode([lane, limit])
        self.timeline, self.identities, self.positions = timeline, identities, positions
        self.hasher = hashlib.sha256()
        self.count = 0
        self.saved = cache.read(self.slot)

    def restore(self):
        saved = self.saved
        if not isinstance(saved, dict) or type(saved.get("count")) is not int:
            return None
        count = saved["count"]
        if not 0 < count <= len(self.timeline):
            return None
        if not self.cache.prefix_unchanged(saved.get("dependency"), self.timeline[count - 1][0]):
            return None
        _extend(self.hasher, self.timeline, self.identities, self.positions, 0, count)
        self.count = count
        if self.hasher.hexdigest() != saved.get("fingerprint"):
            return None
        try:
            fragments = saved["fragments"]
            active = {}
            for duration, index, raw in saved["active"]:
                if type(index) is not int or not 0 <= index < len(fragments):
                    return None
                raw = dict(raw)
                if raw["previous"] is not None:
                    raw["previous"] = QuotaObservation(**raw["previous"])
                active[duration] = fragments[index], Continuity(**raw)
            previous = tuple(saved["previous_identity"]) if saved["previous_identity"] is not None else None
            return count, fragments, active, previous, saved["known_plan"], set(saved["tainted"])
        except (KeyError, TypeError, ValueError, IndexError):
            return None

    def stage(self, fragments, active, previous_identity, known_plan, tainted):
        _extend(self.hasher, self.timeline, self.identities, self.positions, self.count, len(self.timeline))
        indices = {id(fragment): index for index, fragment in enumerate(fragments)}
        self.cache.stage(self.slot, {"count": len(self.timeline), "fingerprint": self.hasher.hexdigest(),
            "dependency": self.cache.dependency,
            "fragments": fragments, "active": [(duration, indices[id(fragment)], asdict(continuity))
                for duration, (fragment, continuity) in active.items()],
            "previous_identity": previous_identity, "known_plan": known_plan, "tainted": sorted(tainted, key=str)})
