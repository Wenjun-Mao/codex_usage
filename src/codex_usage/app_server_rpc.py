"""Short-lived, bounded stdio RPC sessions; never start a model turn."""
from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import threading
import time
from pathlib import Path

from codex_usage import __version__
from codex_usage.codex_registration import _stop_process_tree
from codex_usage.windows_job import WindowsJob


def windows_runtime():
    return os.name == "nt"


class RpcError(RuntimeError):
    """A deliberately content-free transport/protocol diagnostic."""


class AppServerRpc:
    def __init__(self, executable: str, codex_home: Path, *, timeout: float = 8):
        self.executable = executable
        self.codex_home = codex_home
        self.timeout = timeout
        self.process = None
        self.job = None
        self.messages: queue.Queue = queue.Queue(maxsize=128)
        self.stopping = threading.Event()
        self.threads: list[threading.Thread] = []
        self.next_id = 0

    def __enter__(self):
        self.deadline = time.monotonic() + self.timeout
        environment = dict(os.environ, CODEX_HOME=str(self.codex_home.expanduser().resolve()))
        try:
            self.process = subprocess.Popen(
                [self.executable, "app-server", "--stdio"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=environment, start_new_session=not windows_runtime(),
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 512) if windows_runtime() else 0,
            )
            if windows_runtime():
                self.job = WindowsJob()
                self.job.assign(self.process.pid)
            reader = threading.Thread(target=self._read, daemon=True)
            self.threads.append(reader)
            reader.start()
            self.call("initialize", {
                "clientInfo": {"name": "codex-usage", "version": __version__},
                "capabilities": {},
            })
            self._write({"method": "initialized", "params": {}})
            return self
        except Exception:
            self.close()
            raise RpcError("startup_failed") from None

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.stopping.set()
        if self.process is not None:
            if not windows_runtime():
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif self.job is not None:
                self.job.close()
                self.job = None
            else:
                _stop_process_tree(self.process)
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
            for stream in (self.process.stdin, self.process.stdout):
                if stream is not None:
                    stream.close()
        for thread in self.threads:
            thread.join(timeout=1)

    def _enqueue(self, value):
        while not self.stopping.is_set():
            try:
                self.messages.put(value, timeout=.05)
                return
            except queue.Full:
                continue

    def _read(self):
        try:
            while not self.stopping.is_set():
                line = self.process.stdout.readline(262145)
                if not line:
                    raise RpcError("process_exited")
                if len(line) > 262144:
                    raise RpcError("oversized_frame")
                try:
                    message = json.loads(line)
                except (ValueError, RecursionError):
                    raise RpcError("malformed_frame") from None
                if not isinstance(message, dict):
                    raise RpcError("malformed_frame")
                self._enqueue(message)
        except (OSError, ValueError, RpcError) as exc:
            self._enqueue(exc if isinstance(exc, RpcError) else RpcError("read_failed"))

    def _write(self, message):
        try:
            self.process.stdin.write((json.dumps(message) + "\n").encode())
            self.process.stdin.flush()
        except (OSError, ValueError):
            raise RpcError("write_failed") from None

    def call(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        request_id = self.next_id
        self._write({"id": request_id, "method": method, "params": params or {}})
        while True:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise RpcError("timeout")
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty:
                raise RpcError("timeout") from None
            if isinstance(message, Exception):
                raise message
            if "method" in message:
                if "id" in message:
                    self._write({"id": message["id"], "error": {
                        "code": -32601, "message": "Unsupported client request",
                    }})
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RpcError("method_failed")
            if not isinstance(message.get("result"), dict):
                raise RpcError("malformed_result")
            return message["result"]
