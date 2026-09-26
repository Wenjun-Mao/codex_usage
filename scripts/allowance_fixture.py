"""Fixed synthetic quota observations for extension and report visual checks."""
from datetime import UTC, datetime, timedelta

from codex_usage.allowance_estimation import estimate_window
from codex_usage.allowance_models import QuotaObservation
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
            "points": [dict(point.to_dict(), provenance="Recovered") for point in points],
        })
    active = windows[-1]["points"][-1]
    qualified, headline = allowance_highlights(windows)
    return {
        "status": {
            "plan": "pro",
            "active_buckets": [
                active,
                dict(active, limit_id="extra-model", used_percent=8, duration_minutes=300),
            ],
            "probe_status": "fresh", "last_probe_at": active["timestamp"],
            "lifetime_tokens": 900000000,
            "recovery": {"total": 80, "complete": 72, "pending": 8, "unavailable": 0},
        },
        "windows": windows, "qualified": qualified, "headline": headline,
        "headline_previous": False, "history": allowance_history(windows),
    }
