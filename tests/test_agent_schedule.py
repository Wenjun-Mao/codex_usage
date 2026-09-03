from __future__ import annotations

from codex_usage.agent_schedule import CaptureSchedule


def test_schedule_counts_interval_from_success_and_manual_reset() -> None:
    schedule = CaptureSchedule(15)
    schedule.start(100.0)
    assert schedule.is_due(100.0)

    schedule.mark_success(140.0)
    assert schedule.seconds_until_due(140.0) == 900.0
    assert not schedule.is_due(1_039.0)
    assert schedule.is_due(1_040.0)

    schedule.mark_success(1_050.0)
    assert schedule.seconds_until_due(1_050.0) == 900.0


def test_manual_only_has_no_due_time_but_can_be_reenabled() -> None:
    schedule = CaptureSchedule(None)
    schedule.start(10.0)
    assert schedule.seconds_until_due(100.0) is None
    assert not schedule.is_due(100.0)

    schedule.update_interval(1, 100.0)
    assert schedule.is_due(160.0)
