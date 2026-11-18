"""Windows-only helpers for the physical grave/yo key used by native QA."""
import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
user32.keybd_event.argtypes = [ctypes.c_ubyte,ctypes.c_ubyte,ctypes.c_ulong,ctypes.c_size_t]
user32.GetForegroundWindow.restype = ctypes.c_void_p

def press_reveal():
    # VK_OEM_3 / physical scan code 0x29, independent of RU/EN character text.
    user32.keybd_event(0xC0,0x29,0,0)
    time.sleep(.03)
    user32.keybd_event(0xC0,0x29,2,0)

def focus_process(pid):
    """Focus only the isolated QA receiver, verifying the actual foreground."""
    user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes=[wintypes.HWND]
    user32.SetForegroundWindow.argtypes=[wintypes.HWND]
    user32.ShowWindow.argtypes=[wintypes.HWND,ctypes.c_int]
    found=[]
    callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    def visit(hwnd,_):
        process=wintypes.DWORD();user32.GetWindowThreadProcessId(hwnd,ctypes.byref(process))
        if process.value==pid and user32.IsWindowVisible(hwnd):found.append(hwnd)
        return True
    user32.EnumWindows(callback(visit),0)
    assert found,'QA receiver has no visible window'
    target=found[0];user32.ShowWindow(target,9)
    thread=user32.GetWindowThreadProcessId(user32.GetForegroundWindow(),None)
    current=ctypes.windll.kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(current,thread,True)
    try:
        if not user32.SetForegroundWindow(target):
            user32.keybd_event(0x12,0x38,0,0)
            user32.SetForegroundWindow(target)
            user32.keybd_event(0x12,0x38,2,0)
    finally:user32.AttachThreadInput(current,thread,False)
    assert user32.GetForegroundWindow()==target,'Windows denied focus to the QA receiver'
