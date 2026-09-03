from __future__ import annotations

import ctypes
import os
import threading
from collections.abc import Callable


def process_is_alive(process_id: int) -> bool:
    if process_id <= 0:
        return False
    if os.name == "nt":
        return _windows_process_is_alive(process_id)
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def start_parent_monitor(
    process_id: int,
    request_shutdown: Callable[[], None],
    *,
    stop_event: threading.Event,
    poll_seconds: float = 1.0,
    probe: Callable[[int], bool] = process_is_alive,
) -> threading.Thread:
    if process_id <= 0:
        raise ValueError("parent process ID must be greater than zero")
    thread = threading.Thread(
        target=_monitor_parent,
        args=(process_id, request_shutdown, stop_event, poll_seconds, probe),
        name="codex-usage-parent-monitor",
        daemon=True,
    )
    thread.start()
    return thread


def _monitor_parent(
    process_id: int,
    request_shutdown: Callable[[], None],
    stop_event: threading.Event,
    poll_seconds: float,
    probe: Callable[[int], bool],
) -> None:
    while not stop_event.is_set():
        if not probe(process_id):
            request_shutdown()
            return
        stop_event.wait(poll_seconds)


def _windows_process_is_alive(process_id: int) -> bool:
    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(
        process_query_limited_information,
        False,
        process_id,
    )
    if not handle:
        return ctypes.get_last_error() == 5
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)
