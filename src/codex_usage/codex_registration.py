from __future__ import annotations

import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TextIO

from codex_usage import __version__


@dataclass(frozen=True, slots=True)
class RegistrationFailure:
    task_id: str
    message: str


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    attempted_task_ids: tuple[str, ...]
    registered_task_ids: tuple[str, ...]
    failures: tuple[RegistrationFailure, ...]
    executable: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "attempted_task_ids": list(self.attempted_task_ids),
            "registered_task_ids": list(self.registered_task_ids),
            "failures": [asdict(failure) for failure in self.failures],
            "executable": self.executable,
        }


def discover_codex_executables() -> tuple[str, ...]:
    candidates: list[str] = []
    override = os.environ.get("CODEX_CLI_PATH", "").strip()
    if override:
        candidates.append(override)
    if sys.platform == "darwin":
        candidates.extend(
            (
                "/Applications/ChatGPT.app/Contents/Resources/codex",
                str(
                    Path.home()
                    / "Applications/ChatGPT.app/Contents/Resources/codex"
                ),
            )
        )
    elif os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        if str(local):
            roots = (
                local / "OpenAI/Codex/bin",
                local
                / "Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/OpenAI/Codex/bin",
            )
            for root in roots:
                candidates.append(str(root / "codex.exe"))
                if root.is_dir():
                    candidates.extend(str(path / "codex.exe") for path in root.iterdir())
    discovered = shutil.which("codex")
    if discovered:
        candidates.append(discovered)
    candidates.append("codex.exe" if os.name == "nt" else "codex")
    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))


def register_codex_tasks(
    task_ids: list[str] | tuple[str, ...],
    *,
    codex_home: Path | None = None,
    candidates: tuple[str, ...] | None = None,
    startup_timeout: float = 5.0,
    request_timeout: float = 5.0,
    batch_timeout: float = 10.0,
) -> RegistrationResult:
    selected, invalid = _classify_task_ids(task_ids)
    if not selected:
        return RegistrationResult(selected, (), invalid)
    last_failure = "No Codex executable candidate was available"
    for executable in candidates or discover_codex_executables():
        try:
            session = _AppServerSession(
                executable,
                selected,
                codex_home=codex_home,
                startup_timeout=startup_timeout,
                request_timeout=request_timeout,
                batch_timeout=batch_timeout,
            )
            registered, failures = session.run()
        except _PreDispatchFailure as exc:
            last_failure = str(exc)
            continue
        return RegistrationResult(
            selected,
            tuple(task_id for task_id in selected if task_id in registered),
            (*invalid, *failures),
            executable,
        )
    return RegistrationResult(
        selected,
        (),
        (
            *invalid,
            *(RegistrationFailure(task_id, last_failure) for task_id in selected),
        ),
    )


class _PreDispatchFailure(RuntimeError):
    pass


class _AppServerSession:
    def __init__(
        self,
        executable: str,
        task_ids: tuple[str, ...],
        *,
        codex_home: Path | None,
        startup_timeout: float,
        request_timeout: float,
        batch_timeout: float,
    ) -> None:
        self.executable = executable
        self.task_ids = task_ids
        self.codex_home = codex_home
        self.startup_timeout = startup_timeout
        self.request_timeout = request_timeout
        self.batch_timeout = batch_timeout

    def run(self) -> tuple[set[str], tuple[RegistrationFailure, ...]]:
        try:
            process = subprocess.Popen(
                [self.executable, "app-server", "--stdio"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                start_new_session=os.name != "nt",
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                ),
                env=_registration_environment(self.codex_home),
            )
        except (OSError, ValueError) as exc:
            raise _PreDispatchFailure(
                f"Could not start Codex app-server: {exc}"
            ) from exc
        lines: queue.Queue[str | BaseException | None] = queue.Queue()
        assert process.stdout is not None
        assert process.stderr is not None
        reader = threading.Thread(
            target=_read_lines,
            args=(process.stdout, lines),
            daemon=True,
        )
        reader.start()
        threading.Thread(
            target=_drain_stream,
            args=(process.stderr,),
            daemon=True,
        ).start()
        dispatched = False
        try:
            self._write(
                process,
                {
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {"name": "codex-usage", "version": __version__},
                        "capabilities": {},
                    },
                },
            )
            initialized = self._response(lines, 1, self.startup_timeout)
            if "error" in initialized or "result" not in initialized:
                raise _PreDispatchFailure("Codex app-server initialization failed")
            self._write(process, {"method": "initialized", "params": {}})
            pending = {
                request_id: task_id
                for request_id, task_id in enumerate(self.task_ids, start=2)
            }
            for request_id, task_id in pending.items():
                self._write(
                    process,
                    {
                        "id": request_id,
                        "method": "thread/read",
                        "params": {"threadId": task_id, "includeTurns": False},
                    },
                )
            dispatched = True
            return self._collect(lines, pending)
        except _PreDispatchFailure:
            raise
        except BaseException as exc:
            if not dispatched:
                raise _PreDispatchFailure(str(exc)) from exc
            return set(), tuple(
                RegistrationFailure(task_id, str(exc)) for task_id in self.task_ids
            )
        finally:
            _stop_process_tree(process)

    def _collect(
        self,
        lines: queue.Queue[str | BaseException | None],
        pending: dict[int, str],
    ) -> tuple[set[str], tuple[RegistrationFailure, ...]]:
        registered: set[str] = set()
        failures: list[RegistrationFailure] = []
        deadline = time.monotonic() + self.batch_timeout
        request_deadlines = {
            request_id: time.monotonic() + self.request_timeout for request_id in pending
        }
        while pending and time.monotonic() < deadline:
            now = time.monotonic()
            expired = [key for key, value in request_deadlines.items() if value <= now]
            for request_id in expired:
                failures.append(
                    RegistrationFailure(pending.pop(request_id), "thread/read timed out")
                )
                request_deadlines.pop(request_id, None)
            if not pending:
                break
            message = _next_message(lines, min(0.1, max(0.01, deadline - now)))
            if message is None or not isinstance(message.get("id"), int):
                continue
            request_id = int(message["id"])
            task_id = pending.pop(request_id, None)
            request_deadlines.pop(request_id, None)
            if task_id is None:
                continue
            if "error" in message:
                failures.append(RegistrationFailure(task_id, "thread/read failed"))
                continue
            returned = _returned_task_id(message.get("result"))
            if returned == task_id:
                registered.add(task_id)
            else:
                failures.append(
                    RegistrationFailure(task_id, "thread/read returned another task")
                )
        failures.extend(
            RegistrationFailure(task_id, "Codex app-server batch timed out")
            for task_id in pending.values()
        )
        return registered, tuple(failures)

    @staticmethod
    def _response(
        lines: queue.Queue[str | BaseException | None],
        request_id: int,
        timeout: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = _next_message(lines, max(0.01, deadline - time.monotonic()))
            if message is not None and message.get("id") == request_id:
                return message
        raise _PreDispatchFailure("Codex app-server initialization timed out")

    @staticmethod
    def _write(process: subprocess.Popen[str], payload: dict[str, Any]) -> None:
        if process.stdin is None:
            raise RuntimeError("Codex app-server stdin is unavailable")
        process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        process.stdin.flush()


def _read_lines(stream: TextIO, lines: queue.Queue[str | BaseException | None]) -> None:
    try:
        for line in stream:
            if len(line.encode()) > 65_536:
                raise ValueError("Codex app-server frame exceeded 65536 bytes")
            lines.put(line)
    except BaseException as exc:
        lines.put(exc)
    finally:
        lines.put(None)


def _drain_stream(stream: TextIO) -> None:
    try:
        while stream.read(8192):
            pass
    except (OSError, ValueError):
        pass


def _next_message(
    lines: queue.Queue[str | BaseException | None], timeout: float
) -> dict[str, Any] | None:
    try:
        item = lines.get(timeout=timeout)
    except queue.Empty:
        return None
    if isinstance(item, BaseException):
        raise item
    if item is None:
        raise RuntimeError("Codex app-server exited early")
    payload = json.loads(item)
    if not isinstance(payload, dict):
        raise ValueError("Codex app-server emitted a non-object message")
    if "id" not in payload and isinstance(payload.get("method"), str):
        return None
    return payload


def _returned_task_id(result: object) -> str | None:
    if not isinstance(result, dict):
        return None
    thread = result.get("thread")
    if isinstance(thread, dict) and isinstance(thread.get("id"), str):
        return str(thread["id"])
    return str(result["threadId"]) if isinstance(result.get("threadId"), str) else None


def _classify_task_ids(
    values: list[str] | tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[RegistrationFailure, ...]]:
    selected: list[str] = []
    failures: list[RegistrationFailure] = []
    for value in dict.fromkeys(values):
        if value and value == value.strip():
            selected.append(value)
        else:
            failures.append(RegistrationFailure(value, "Invalid task ID"))
    return tuple(selected), tuple(failures)


def _registration_environment(codex_home: Path | None) -> dict[str, str]:
    environment = dict(os.environ)
    if codex_home is not None:
        environment["CODEX_HOME"] = str(codex_home.expanduser().resolve())
    return environment


def _stop_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                check=False,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
    except (OSError, ProcessLookupError, subprocess.SubprocessError):
        process.kill()
