from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Protocol

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100


class WindowsJobError(RuntimeError):
    pass


class _JobApi(Protocol):
    def create_job(self) -> int: ...

    def set_kill_on_close(self, handle: int) -> None: ...

    def assign_process(self, handle: int, pid: int) -> None: ...

    def terminate_job(self, handle: int) -> None: ...

    def close_handle(self, handle: int) -> None: ...


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class WindowsJob:
    def __init__(self, *, api: _JobApi | None = None) -> None:
        self._api = api if api is not None else _CtypesJobApi()
        self._handle: int | None = self._api.create_job()
        try:
            self._api.set_kill_on_close(self._require_handle())
        except Exception:
            self.close()
            raise

    def assign(self, pid: int) -> None:
        self._api.assign_process(self._require_handle(), pid)

    def terminate(self) -> None:
        self._api.terminate_job(self._require_handle())

    def close(self) -> None:
        if self._handle is None:
            return
        handle = self._handle
        self._api.close_handle(handle)
        self._handle = None

    def _require_handle(self) -> int:
        if self._handle is None:
            raise WindowsJobError("Windows Job Object handle is closed")
        return self._handle


class _CtypesJobApi:
    def __init__(self) -> None:
        if os.name != "nt":
            raise WindowsJobError("Windows Job Objects require Windows")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32 = kernel32

    def create_job(self) -> int:
        handle = self._kernel32.CreateJobObjectW(None, None)
        if not handle:
            self._raise("Windows Job Object creation")
        return int(handle)

    def set_kill_on_close(self, handle: int) -> None:
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        succeeded = self._kernel32.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        )
        if not succeeded:
            self._raise("Windows Job Object limit configuration")

    def assign_process(self, handle: int, pid: int) -> None:
        process_handle = self._kernel32.OpenProcess(
            _PROCESS_TERMINATE | _PROCESS_SET_QUOTA,
            False,
            pid,
        )
        if not process_handle:
            self._raise("Windows controller process open")
        assigned = self._kernel32.AssignProcessToJobObject(handle, process_handle)
        assignment_error = ctypes.get_last_error() if not assigned else 0
        closed = self._kernel32.CloseHandle(process_handle)
        if not assigned:
            self._raise_with_code("Windows controller Job Object assignment", assignment_error)
        if not closed:
            self._raise("Windows controller process handle close")

    def terminate_job(self, handle: int) -> None:
        if not self._kernel32.TerminateJobObject(handle, 1):
            self._raise("Windows Job Object termination")

    def close_handle(self, handle: int) -> None:
        if not self._kernel32.CloseHandle(handle):
            self._raise("Windows Job Object handle close")

    def _raise(self, operation: str) -> None:
        self._raise_with_code(operation, ctypes.get_last_error())

    @staticmethod
    def _raise_with_code(operation: str, error_code: int) -> None:
        raise WindowsJobError(f"{operation} failed with Windows error {error_code}")
