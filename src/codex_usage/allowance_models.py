"""Allowlisted, content-free quota metadata shared by RPC and rollout parsing."""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class QuotaObservation:
    timestamp: str
    limit_id: str
    slot: str
    plan: str
    used_percent: float
    duration_minutes: int | None
    resets_at: int | None
    reset_credits: int | None = None

    def to_dict(self):
        return asdict(self)


def identifier(value: object) -> str:
    return value if isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", value) else ""


def number(value: object, *, minimum=0, maximum=float("inf")) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        parsed = float(value)
    except OverflowError:
        return None
    return parsed if math.isfinite(parsed) and minimum <= parsed <= maximum else None


def integer(value: object) -> int | None:
    parsed = number(value)
    return int(parsed) if parsed is not None and parsed.is_integer() else None


def quota_observations(value: object, timestamp: str, *, plan: str = "") -> tuple[QuotaObservation, ...]:
    if not isinstance(value, dict):
        return ()
    try:
        stamp = datetime.fromisoformat(timestamp)
        if stamp.tzinfo is None:
            return ()
        timestamp = stamp.astimezone(UTC).isoformat()
    except (ValueError, TypeError, OverflowError):
        return ()
    credits = value.get("rateLimitResetCredits")
    count = integer(credits.get("availableCount")) if isinstance(credits, dict) else None
    buckets = value.get("rateLimitsByLimitId")
    if not isinstance(buckets, dict):
        single = value.get("rateLimits", value)
        buckets = {"codex": single}
    observations = []
    for key, bucket in list(buckets.items())[:64]:
        if not isinstance(bucket, dict):
            continue
        limit_id = identifier(bucket.get("limitId", bucket.get("limit_id"))) or identifier(key)
        if not limit_id:
            continue
        bucket_plan = identifier(bucket.get("planType", bucket.get("plan_type"))) or identifier(plan)
        for slot in ("primary", "secondary"):
            window = bucket.get(slot)
            if not isinstance(window, dict):
                continue
            used = number(window.get("usedPercent", window.get("used_percent")), maximum=100)
            if used is None:
                continue
            duration = integer(window.get("windowDurationMins", window.get("window_minutes")))
            observations.append(QuotaObservation(
                timestamp, limit_id, slot, bucket_plan, used, duration or None,
                reset_timestamp(window.get("resetsAt", window.get("resets_at"))), count,
            ))
    return tuple(observations)


def rollout_observations(event: object) -> tuple[QuotaObservation, ...]:
    if not isinstance(event, dict) or event.get("type") != "event_msg":
        return ()
    payload = event.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return ()
    return quota_observations(payload.get("rate_limits"), event.get("timestamp"))


def reset_timestamp(value):
    parsed = integer(value)
    return parsed if parsed is not None and parsed <= 253402300799 else None
