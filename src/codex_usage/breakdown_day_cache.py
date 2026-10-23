"""Reuse exact day reductions without decoding unchanged raw day payloads."""
import hashlib
import json
from datetime import datetime, timedelta

from codex_usage.breakdown_readings import display_day
from codex_usage.history_preparation_cache import encode


def reused_display_day(name, timezone, read_encoded, cache):
    prefix, day = name.split("-display:", 1)
    raw = ("meter:" if prefix == "meter" else "balance-points:") + day
    context = prefix + "-context:" + day
    inputs = {key: read_encoded(key) or "[]" for key in (raw, context)}
    signature = hashlib.sha256()
    for payload in inputs.values():
        value = payload.encode()
        signature.update(len(value).to_bytes(8, "big"))
        signature.update(value)
    fingerprint = signature.hexdigest()
    local = datetime.fromisoformat(day).replace(tzinfo=timezone)
    slot = "display-day-2:" + encode([str(timezone), name, local.timestamp(), (local + timedelta(days=1)).timestamp()])
    cached = cache.read(slot)
    if (isinstance(cached, dict) and cached.get("fingerprint") == fingerprint
            and isinstance(cached.get("result"), dict) and type(cached["result"].get("count")) is int
            and isinstance(cached["result"].get("points"), list)):
        return cached["result"]
    result = display_day(name, timezone, lambda key: json.loads(inputs[key]))
    cache.stage(slot, {"fingerprint": fingerprint, "result": result})
    return result
