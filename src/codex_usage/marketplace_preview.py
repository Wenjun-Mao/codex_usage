"""Lifecycle of the local built-frontend screenshot preview."""
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.error import URLError
from urllib.request import urlopen


@contextmanager
def preview_server(desktop_root: Path) -> Iterator[str]:
    port = _unused_loopback_port()
    url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [
            "npm",
            "exec",
            "vite",
            "preview",
            "--",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--strictPort",
        ],
        cwd=desktop_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    "native frontend preview exited before becoming ready"
                )
            try:
                with urlopen(url, timeout=0.5) as response:  # noqa: S310
                    if response.status == 200:
                        break
            except (URLError, OSError):
                time.sleep(0.1)
        else:
            raise RuntimeError("native frontend preview did not become ready")
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _unused_loopback_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


