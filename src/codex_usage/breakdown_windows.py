"""Observed weekly portions from the shared causal continuity checkpoints."""
import hashlib
import json
from datetime import datetime


def observed_windows(prepared):
    windows = {}
    for (limit, duration), series in prepared.series.items():
        if duration != 10080:
            continue
        runs = []
        for index, group in enumerate(series.groups):
            start, boundary, _ = series.checkpoints[index]
            identity = (start, boundary, group.conflict)
            if not runs or runs[-1][0] != identity:
                runs.append((identity, []))
            runs[-1][1].append(index)
        for (origin, boundary, conflict), indices in runs:
            first, last = indices[0], indices[-1]
            # Conflicting captures are their own inspectable portion, not an
            # opening borrowed from the preceding compatible suffix.
            if conflict:
                origin, boundary = first, "observation conflict"
            else:
                origin = first
            plan = "" if conflict else series.cycle_stats[last][3]
            opening = series.groups[origin].point.timestamp
            ending = series.groups[last].point.timestamp
            key = "window:" + hashlib.sha256(json.dumps(
                [limit, duration, series.times[origin], boundary, plan], separators=(",", ":")
            ).encode()).hexdigest()
            windows[key] = {"start": opening, "end": ending, "limit_id": limit,
                "duration_minutes": duration, "plan": plan, "boundary": boundary,
                "ambiguous": conflict, "full_at": series.cycle_stats[last][2],
                "corrections": series.cycle_stats[last][1],
                "closure": "ongoing" if last == len(series.groups)-1 else
                    series.checkpoints[last+1][1], "partial": True}
    return dict(sorted(windows.items(), key=lambda item: (datetime.fromisoformat(item[1]["end"]), item[0]), reverse=True))
