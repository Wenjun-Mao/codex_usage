from __future__ import annotations

import errno


_TRANSIENT_ERRNOS = frozenset(
    {
        errno.EAGAIN,
        errno.EBUSY,
        errno.EINTR,
        errno.ETIMEDOUT,
        *(
            value
            for name in ("ESTALE", "ETXTBSY")
            if (value := getattr(errno, name, None)) is not None
        ),
    }
)
_TRANSIENT_WINERRORS = frozenset(
    {
        32,  # ERROR_SHARING_VIOLATION
        33,  # ERROR_LOCK_VIOLATION
        54,  # ERROR_NETWORK_BUSY
        121,  # ERROR_SEM_TIMEOUT
        170,  # ERROR_BUSY
        1237,  # ERROR_RETRY
    }
)
_PERMANENT_ERRORS = (
    FileNotFoundError,
    PermissionError,
    NotADirectoryError,
    IsADirectoryError,
)


def is_transient_filesystem_error(error: BaseException) -> bool:
    if not isinstance(error, OSError) or isinstance(error, FileNotFoundError):
        return False
    winerror = getattr(error, "winerror", None)
    if winerror is not None:
        return winerror in _TRANSIENT_WINERRORS
    if isinstance(error, _PERMANENT_ERRORS):
        return False
    return error.errno in _TRANSIENT_ERRNOS
