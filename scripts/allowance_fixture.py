"""Fixed synthetic quota observations for extension and report visual checks."""
from datetime import UTC, datetime, timedelta

from codex_usage.allowance_estimation import estimate_window
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_pace import fit_paces
from codex_usage.allowance_queries import allowance_highlights, allowance_history
from codex_usage.allowance_windows import AllowanceWindow


def allowance_fixture() -> dict:
    windows = []
    for index, value in enumerate((1180, 1240, 1220, 1260, 1250)):
        start = datetime(2026, 8, 1, tzinfo=UTC) + timedelta(days=index * 7)
        points = [
            QuotaObservation(
                (start + timedelta(hours=offset * 12)).isoformat(),
                "codex", "primary", "pro", offset * 5, 10080,
                int((start + timedelta(days=7)).timestamp()),
            )
            for offset in range(13 if index < 4 else 5)
        ]
        window = AllowanceWindow(points, "scheduled-compatible" if index < 4 else "ongoing")
        estimate = estimate_window(
            window, [point.used_percent * value / 100 for point in points],
            fully_priced=True,
        )
        windows.append({
            "limit_id": "codex", "plan": "pro", "duration_minutes": 10080,
            "start": points[0].timestamp, "end": points[-1].timestamp,
            "completed": window.completed, "closure": window.closure,
            "corrections": 0, "estimate": estimate.to_dict(),
            "fully_priced": True, "coverage_complete": True,
            "points": [dict(point.to_dict(), provenance=(
                "Recovered task snapshot" if index < 4 else
                "Live probe" if offset % 2 else "Task snapshot"
            )) for offset, point in enumerate(points)],
        })
    active = dict(windows[-1]["points"][-1], timestamp="2026-09-02T16:00:00+00:00")
    anchor = QuotaObservation(**{key: active[key] for key in QuotaObservation.__dataclass_fields__})
    observed = datetime.fromisoformat(anchor.timestamp)
    pace_points = [QuotaObservation((observed - timedelta(hours=h)).isoformat(),
                   anchor.limit_id, anchor.slot, anchor.plan, 18, anchor.duration_minutes,
                   anchor.resets_at) for h in range(24, 0, -2)]
    pace_points += [QuotaObservation((observed - timedelta(minutes=m)).isoformat(),
                    anchor.limit_id, anchor.slot, anchor.plan, used, anchor.duration_minutes,
                    anchor.resets_at) for m, used in ((60, 18), (30, 18), (15, 19))]
    pace_points.append(anchor)
    paces = fit_paces(pace_points, anchor, {anchor})
    extra = dict(active, limit_id="extra-model", used_percent=8, duration_minutes=300)
    extra_anchor = QuotaObservation(**{key: extra[key] for key in QuotaObservation.__dataclass_fields__})
    qualified, headline = allowance_highlights(windows)
    return {
        "status": {
            "plan": "pro",
            "active_buckets": [
                active,
                extra,
            ],
            "probe_status": "fresh", "last_probe_at": active["timestamp"],
            "lifetime_tokens": 900000000,
            "recovery": {"total": 80, "complete": 72, "pending": 8, "unavailable": 0},
        },
        "paces": [paces, fit_paces([extra_anchor], extra_anchor, {extra_anchor})],
        "windows": windows, "qualified": qualified, "headline": headline,
        "headline_previous": False, "history": allowance_history(windows),
    }
