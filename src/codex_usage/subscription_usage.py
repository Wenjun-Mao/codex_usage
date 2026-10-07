"""Known included subscription activity, distinct from public API pricing."""
from datetime import UTC, datetime


AUTO_REVIEW_MODEL = "codex-auto-review"
# The original announcement was displayed at 03:13 EDT. The next full minute
# is a conservative evidence boundary, not a claimed backend rollout instant.
AUTO_REVIEW_FREE_FROM = datetime(2026, 10, 6, 7, 14, tzinfo=UTC)


def is_included_subscription_usage(model: str, at: datetime | None) -> bool:
    if model.strip().casefold() != AUTO_REVIEW_MODEL:
        return False
    if at is None:
        return True
    effective_at = at.replace(tzinfo=UTC) if at.tzinfo is None else at.astimezone(UTC)
    return effective_at >= AUTO_REVIEW_FREE_FROM
