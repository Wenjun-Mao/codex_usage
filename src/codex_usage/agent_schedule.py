from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CaptureSchedule:
    interval_minutes: int | None
    next_due_monotonic: float | None = None

    def start(self, now: float) -> None:
        self.next_due_monotonic = now

    def update_interval(self, interval_minutes: int | None, now: float) -> None:
        self.interval_minutes = interval_minutes
        self.next_due_monotonic = (
            None if interval_minutes is None else now + interval_minutes * 60
        )

    def mark_success(self, now: float) -> None:
        self.next_due_monotonic = (
            None
            if self.interval_minutes is None
            else now + self.interval_minutes * 60
        )

    def request_catch_up(self, now: float) -> None:
        if self.interval_minutes is not None:
            self.next_due_monotonic = now

    def is_due(self, now: float) -> bool:
        return (
            self.interval_minutes is not None
            and self.next_due_monotonic is not None
            and now >= self.next_due_monotonic
        )

    def seconds_until_due(self, now: float) -> float | None:
        if self.interval_minutes is None or self.next_due_monotonic is None:
            return None
        return max(0.0, self.next_due_monotonic - now)
