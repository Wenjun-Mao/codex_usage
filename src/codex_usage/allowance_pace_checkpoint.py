"""Resume causal pace state only after a complete unchanged-prefix certificate."""
from dataclasses import asdict

from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_pace_evidence import Continuity, Cursor
from codex_usage.history_preparation_cache import encode


def _pack(values):
    positions, unique, refs = {}, [], []
    for value in values:
        if value not in positions:
            positions[value] = len(unique)
            unique.append(value)
        refs.append(positions[value])
    return unique, refs


def _unpack(packed, count, width):
    values, refs = packed
    if len(refs) != count or any(not isinstance(value, list) or len(value) != width for value in values):
        raise ValueError("Invalid pace checkpoint shape")
    if any(type(index) is not int or not 0 <= index < len(values) for index in refs):
        raise ValueError("Invalid pace checkpoint reference")
    values = list(map(tuple, values))
    return [values[index] for index in refs]


class PaceCheckpoint:
    def __init__(self, cache, groups, first_known):
        self.cache, self.groups, self.first_known = cache, groups, first_known
        point = groups[0].point
        self.slot = "pace-1:" + encode([point.limit_id, point.duration_minutes])

    def restore(self):
        saved = self.cache.read(self.slot)
        if not isinstance(saved, dict) or type(saved.get("count")) is not int:
            return None
        count = saved["count"]
        if (not 0 < count <= len(self.groups) or saved.get("end") != self.groups[count - 1].time
                or saved.get("first_known") != self.first_known
                or not self.cache.prefix_unchanged(saved.get("dependency"), saved["end"])):
            return None
        try:
            raw = dict(saved["cursor"])
            continuity = dict(raw["continuity"])
            if continuity["previous"] is not None:
                continuity["previous"] = QuotaObservation(**continuity["previous"])
            raw["continuity"] = Continuity(**continuity)
            return (count, Cursor(**raw), _unpack(saved["checkpoints"], count, 3),
                    _unpack(saved["cycle_stats"], count, 4))
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    def stage(self, cursor, checkpoints, cycle_stats):
        self.cache.stage(self.slot, {"dependency": self.cache.dependency, "count": len(self.groups),
            "end": self.groups[-1].time, "first_known": self.first_known, "cursor": asdict(cursor),
            "checkpoints": _pack(checkpoints), "cycle_stats": _pack(cycle_stats)})
