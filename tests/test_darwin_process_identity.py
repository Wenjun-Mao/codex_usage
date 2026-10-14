"""Kernel creation identity requires complete BSD/path responses, never PID alone."""
import ctypes
from types import SimpleNamespace

import pytest

from release_tooling_support import load_tool

identity = load_tool("probes.darwin_process_identity")


@pytest.mark.parametrize("fault", (None, "partial", "path"))
def test_kernel_identity_requires_complete_responses(monkeypatch, fault):
    assert ctypes.sizeof(identity.BSDInfo) == 136

    def info(pid, flavor, arg, pointer, size):
        assert (pid, flavor, arg, size) == (123, 3, 0, 136)
        data = ctypes.cast(pointer, ctypes.POINTER(identity.BSDInfo)).contents
        data.fields[3], data.fields[4] = 123, 122
        data.start_seconds, data.start_microseconds = 10, 20
        return 135 if fault == "partial" else 136

    def path(pid, buffer, size):
        assert pid == 123 and size == 4096
        buffer.value = b"/synthetic/WebContent"
        return 0 if fault == "path" else len(buffer.value)

    monkeypatch.setattr(identity.ctypes, "CDLL", lambda _: SimpleNamespace(proc_pidinfo=info, proc_pidpath=path))
    actual = identity.process_identity(123)
    if fault:
        assert actual is None
    else:
        assert actual == {"pid": 123, "parent": 122, "start_seconds": 10,
            "start_microseconds": 20, "executable": "/synthetic/WebContent"}
