"""Content-free primitives for observed output-phase speed, independent of pricing."""
from dataclasses import asdict, dataclass
from datetime import datetime
import math

METRIC_VERSION = 1
MIN_ITEM_MS = 10
MIN_OUTPUT_TOKENS = 500
TOKEN_FIELDS = (
    "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
    "output_tokens", "reasoning_output_tokens", "total_tokens",
)


def counts(value: object) -> tuple[int, ...] | None:
    if not isinstance(value, dict):
        return None
    result = tuple(value.get(key, 0) for key in TOKEN_FIELDS)
    return result if all(type(v) is int and v >= 0 for v in result) else None


def milliseconds(value: object) -> float | None:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.timestamp() * 1000 if parsed.tzinfo else None
        except ValueError:
            return None
    if type(value) in (int, float) and math.isfinite(value):
        return float(value)
    return None


@dataclass(frozen=True, slots=True)
class SpeedFact:
    record_index: int
    response_id: str
    timestamp: str
    task_id: str
    turn_id: str
    model: str
    effort: str
    cli_version: str
    usage: tuple[int, ...]
    start_ms: float
    end_ms: float
    min_item_ms: float
    item_count: int
    reason: str
    metric_version: int = METRIC_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def eligible(self) -> bool:
        return not self.reason and self.usage[3] >= MIN_OUTPUT_TOKENS
