"""Deny live-source/database access and external networking in source benchmarks."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname


def database_path(value):
    raw = os.fsdecode(value)
    if raw.startswith("file:"):
        uri = urlsplit(raw)
        if uri.netloc not in {"", "localhost"}:
            raise PermissionError("benchmark attempted remote database access")
        return Path(url2pathname(uri.path)).resolve()
    return Path(raw).resolve()


def audit_guard(root, *, report):
    root = root.resolve()

    def check(event, values):
        if event == "open" and isinstance(values[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(values[0])).resolve()
            if (path.suffix.lower() in {".jsonl", ".png", ".jpg", ".webp"}
                    or ".codex" in path.parts) and not path.is_relative_to(root):
                raise PermissionError("benchmark attempted original source access")
        if event == "sqlite3.connect" and values[0] != ":memory:":
            if not database_path(values[0]).is_relative_to(root):
                raise PermissionError("benchmark attempted external database access")
        if event in {"socket.connect", "socket.getaddrinfo"}:
            raise PermissionError("benchmark attempted network access")
        if report and event == "subprocess.Popen":
            raise PermissionError("report benchmark attempted process execution")

    return check
