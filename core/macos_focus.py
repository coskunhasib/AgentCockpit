"""Read live keyboard focus without NSWorkspace's event-loop-dependent cache."""

import ctypes
from functools import lru_cache


@lru_cache(maxsize=1)
def _frameworks():
    carbon = ctypes.CDLL('/System/Library/Frameworks/Carbon.framework/Carbon')
    carbon.GetFrontProcess.argtypes = [ctypes.POINTER(ctypes.c_uint32 * 2)]
    carbon.GetFrontProcess.restype = ctypes.c_int16
    carbon.GetProcessPID.argtypes = [ctypes.POINTER(ctypes.c_uint32 * 2), ctypes.POINTER(ctypes.c_int)]
    carbon.GetProcessPID.restype = ctypes.c_int16
    return carbon


def focused_pid():
    # These legacy APIs remain available on macOS 27 and do not need AX trust.
    # Fail closed if a future macOS version removes them.
    carbon = _frameworks()
    serial = (ctypes.c_uint32 * 2)()
    pid = ctypes.c_int()
    if carbon.GetFrontProcess(ctypes.byref(serial)) != 0:
        return 0
    if carbon.GetProcessPID(ctypes.byref(serial), ctypes.byref(pid)) != 0:
        return 0
    return pid.value
