"""Canonical rollout filenames distinguish logical threads from storage IDs."""
from dataclasses import dataclass
from pathlib import Path
import re

_UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
_NAME = re.compile(rf"^rollout-\d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}-\d{{2}}-\d{{2}}-"
                   rf"(?P<thread>{_UUID})(?:_(?P<rollout>{_UUID}))?\.jsonl$")


@dataclass(frozen=True, slots=True)
class RolloutIdentity:
    thread_id: str
    rollout_id: str


def rollout_identity(path: Path) -> RolloutIdentity | None:
    match = _NAME.fullmatch(path.name)
    if match is None:
        return None
    thread = match["thread"].lower()
    return RolloutIdentity(thread, (match["rollout"] or thread).lower())
