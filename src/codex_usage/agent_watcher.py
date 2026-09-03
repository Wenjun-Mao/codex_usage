from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


class DirtyPathSet:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._paths: set[str] = set()

    def mark(self, path: str | Path) -> None:
        candidate = str(path)
        if not candidate.casefold().endswith(".jsonl"):
            return
        with self._lock:
            self._paths.add(candidate)

    def drain(self) -> tuple[str, ...]:
        with self._lock:
            paths = tuple(sorted(self._paths, key=str.casefold))
            self._paths.clear()
        return paths

    def snapshot(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._paths, key=str.casefold))


class _DirtyEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        dirty_paths: DirtyPathSet,
        on_overflow: Callable[[], None],
    ) -> None:
        super().__init__()
        self._dirty_paths = dirty_paths
        self._on_overflow = on_overflow

    def on_any_event(self, event: FileSystemEvent) -> None:
        event_type = str(getattr(event, "event_type", ""))
        if event_type in {"overflow", "queue_overflow"}:
            self._on_overflow()
            return
        self._dirty_paths.mark(event.src_path)
        destination = getattr(event, "dest_path", "")
        if destination:
            self._dirty_paths.mark(destination)


class SessionWatcher:
    def __init__(
        self,
        roots: list[Path],
        dirty_paths: DirtyPathSet,
        *,
        on_overflow: Callable[[], None],
    ) -> None:
        self._roots = tuple(root for root in roots if root.is_dir())
        self._handler = _DirtyEventHandler(dirty_paths, on_overflow)
        self._observer = self._new_observer()

    def start(self) -> None:
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        try:
            self._observer.join(timeout=5)
        except RuntimeError:
            # Startup can fail before watchdog starts its worker thread.
            pass

    def is_alive(self) -> bool:
        return self._observer.is_alive()

    def recover(self) -> bool:
        """Replace a failed watchdog thread; Observer instances cannot restart."""
        if self._observer.is_alive():
            return False
        try:
            self._observer.stop()
            self._observer.join(timeout=1)
        except RuntimeError:
            pass
        self._observer = self._new_observer()
        self._observer.start()
        return True

    def _new_observer(self) -> Observer:
        observer = Observer()
        for root in self._roots:
            observer.schedule(self._handler, str(root), recursive=True)
        return observer
