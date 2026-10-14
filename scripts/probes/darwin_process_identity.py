"""Historical private libproc ABI; live sampler attachment is held pending replacement."""
import ctypes


class BSDInfo(ctypes.Structure):
    _fields_ = [("fields", ctypes.c_uint32 * 12), ("comm", ctypes.c_char * 16),
        ("name", ctypes.c_char * 32), ("counts", ctypes.c_uint32 * 5),
        ("nice", ctypes.c_int32), ("start_seconds", ctypes.c_uint64),
        ("start_microseconds", ctypes.c_uint64)]


def process_identity(pid):
    library = ctypes.CDLL("/usr/lib/libproc.dylib")
    library.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    library.proc_pidinfo.restype = ctypes.c_int
    library.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    library.proc_pidpath.restype = ctypes.c_int
    info, path = BSDInfo(), ctypes.create_string_buffer(4096)
    # PROC_PIDTBSDINFO=3; reject incomplete responses instead of using PID alone.
    if library.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info)) != ctypes.sizeof(info):
        return None
    if library.proc_pidpath(pid, path, len(path)) <= 0:
        return None
    return {"pid": info.fields[3], "parent": info.fields[4],
        "start_seconds": info.start_seconds, "start_microseconds": info.start_microseconds,
        "executable": path.value.decode()}
