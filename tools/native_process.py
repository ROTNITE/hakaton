"""Read-only lifetime handle for a native process owned by the product launcher."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os


class AttachedNative:
    def __init__(self,pid):
        if os.name!='nt':raise RuntimeError('Native product attachment requires Windows')
        self.pid=pid;self.returncode=None
        self.api=ctypes.WinDLL('kernel32',use_last_error=True)
        self.api.OpenProcess.argtypes=(wintypes.DWORD,wintypes.BOOL,wintypes.DWORD)
        self.api.OpenProcess.restype=wintypes.HANDLE
        self.api.GetExitCodeProcess.argtypes=(wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD))
        self.api.GetExitCodeProcess.restype=wintypes.BOOL
        self.api.CloseHandle.argtypes=(wintypes.HANDLE,)
        self.api.CloseHandle.restype=wintypes.BOOL
        self.handle=self.api.OpenProcess(0x1000,False,pid) # PROCESS_QUERY_LIMITED_INFORMATION
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())

    def poll(self):
        code=wintypes.DWORD()
        if not self.api.GetExitCodeProcess(self.handle,ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.returncode=None if code.value==259 else code.value # STILL_ACTIVE
        return self.returncode

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle);self.handle=None
