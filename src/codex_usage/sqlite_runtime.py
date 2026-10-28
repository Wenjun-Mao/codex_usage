"""Identify the actual linked SQLite engine, not an unrelated CLI binary."""
from contextlib import closing
import sqlite3
import hashlib
from pathlib import Path
import ssl
import sys

import _sqlite3


RELEASE_VERSION = "3.54.1"
RELEASE_SOURCE_ID = "2026-10-16 14:45:20 555e07ef33f69a0957d24d8e555b702464a131d6f1607f4c3c1e4551e8e6ca76"


def identity():
    with closing(sqlite3.connect(":memory:")) as connection:
        result = {
            "version": sqlite3.sqlite_version,
            "source_id": connection.execute("select sqlite_source_id()").fetchone()[0],
            "compile_options": sorted(row[0] for row in connection.execute("pragma compile_options")),
            "python": sys.version,
            "openssl": ssl.OPENSSL_VERSION,
            "binding": str(Path(_sqlite3.__file__).resolve()),
        }
    if sys.platform == "win32":
        result.update(_windows_library())
    return result


def _windows_library():
    import ctypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    kernel.GetModuleHandleW.restype = ctypes.c_void_p
    kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
    kernel.GetModuleFileNameW.restype = ctypes.c_uint
    handle = kernel.GetModuleHandleW('sqlite3.dll')
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel.GetModuleFileNameW(handle, buffer, len(buffer)) if handle else 0
    if not 0 < length < len(buffer):
        raise RuntimeError('Cannot identify the loaded private SQLite DLL')
    library = Path(buffer.value).resolve()
    root = Path(getattr(sys, '_MEIPASS', sys.base_prefix)).resolve()
    if not all(path.is_relative_to(root) for path in (library, Path(_sqlite3.__file__).resolve())):
        raise RuntimeError('SQLite binding/DLL escaped the private runtime or frozen package')
    return {'library': str(library), 'library_sha256': hashlib.sha256(library.read_bytes()).hexdigest(),
            'package_root': str(root)}


def require_release_runtime():
    result = identity()
    if result["version"] != RELEASE_VERSION or result["source_id"] != RELEASE_SOURCE_ID:
        raise RuntimeError(
            f"This candidate requires official SQLite {RELEASE_VERSION}; Python loaded "
            f"{result['version']} ({result['source_id']}). Updating the sqlite3 CLI does not "
            "update Python's linked engine. See scripts/build_sqlite_runtime.py."
        )
    if "THREADSAFE=0" in result["compile_options"]:
        raise RuntimeError("The SQLite runtime must support independent concurrent connections")
    if "ENABLE_DBSTAT_VTAB" not in result["compile_options"]:
        raise RuntimeError("The SQLite runtime must provide dbstat allocation accounting")
    return result


def wal_reset_fixed():
    version = sqlite3.sqlite_version_info
    return version >= (3, 51, 3) or (3, 50, 7) <= version < (3, 51) or (3, 44, 6) <= version < (3, 45)
