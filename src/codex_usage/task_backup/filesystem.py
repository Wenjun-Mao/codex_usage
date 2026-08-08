from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from codex_usage.filesystem_retry import is_transient_filesystem_error


@retry(
    retry=retry_if_exception(is_transient_filesystem_error),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def open_binary_read(path: Path, *, buffering: int = 1024 * 1024) -> BinaryIO:
    return path.open("rb", buffering=buffering)


@retry(
    retry=retry_if_exception(is_transient_filesystem_error),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def stat_path(path: Path) -> os.stat_result:
    return path.stat()
