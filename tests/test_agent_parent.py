from __future__ import annotations

import os
import threading

from codex_usage.agent_parent import process_is_alive, start_parent_monitor


def test_parent_monitor_requests_shutdown_when_parent_exits() -> None:
    stop = threading.Event()
    shutdown = threading.Event()
    observations = iter((True, False))
    thread = start_parent_monitor(
        123,
        shutdown.set,
        stop_event=stop,
        poll_seconds=0.001,
        probe=lambda _process_id: next(observations),
    )

    thread.join(timeout=1)

    assert not thread.is_alive()
    assert shutdown.is_set()


def test_process_probe_recognizes_current_process_and_invalid_ids() -> None:
    assert process_is_alive(os.getpid())
    assert not process_is_alive(0)
