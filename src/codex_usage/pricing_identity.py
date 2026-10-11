"""Pricing identity follows accounting contracts, not presentation releases."""
from dataclasses import asdict
from datetime import datetime
import hashlib
import json

from codex_usage.image_pricing import IMAGE_PRICING_REVISION
from codex_usage.pricing import API_PRICING_USD_SCHEDULE, CODEX_CREDIT_RATE_SCHEDULE, PRICING_AS_OF
from codex_usage.subscription_usage import AUTO_REVIEW_FREE_FROM, AUTO_REVIEW_MODEL


LANGUAGE_ACCOUNTING_REVISION = 1


def pricing_revision():
    payload = {
        "accounting": LANGUAGE_ACCOUNTING_REVISION,
        "api": [asdict(entry) for entry in API_PRICING_USD_SCHEDULE],
        "credits": [asdict(entry) for entry in CODEX_CREDIT_RATE_SCHEDULE],
        "included": [AUTO_REVIEW_MODEL, AUTO_REVIEW_FREE_FROM],
        "images": IMAGE_PRICING_REVISION,
    }
    def timestamp(value):
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError(f"Unsupported pricing identity value: {type(value).__name__}")
    identity = hashlib.sha256(json.dumps(payload, sort_keys=True,
        separators=(",", ":"), default=timestamp).encode()).hexdigest()
    return f"{PRICING_AS_OF}:accounting:{identity}"
