"""Windows: Super Agents draws its own title bar, like Claude's and Codex's apps. Windows' own bar can't be restyled:
Windows 10 paints it in the accent colour when that's switched on. The native frame stays (resize edges, snap, the
shadow, the minimise and maximise animations); only its caption goes, through WM_NCCALCSIZE in a window subclass.
The page's bar becomes the caption: with its non-client region support on, WebView2 treats `app-region: drag` areas
as the title bar (drag, snap, double-click to maximise, the window menu on right-click)."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Callable

_keep: list = []  # the subclass procedure has to outlive the window


def install(window, on_ready: Callable[[bool], None]) -> None:
    """From the window's before_show event, so the caption is gone before the window first shows. If WebView2 can't do
    drag regions, Windows' title bar comes back, so the window can always be moved."""
    if sys.platform != "win32":
        on_ready(False)
        return
    user32, comctl32 = ctypes.windll.user32, ctypes.windll.comctl32
    proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                   ctypes.c_size_t, ctypes.c_size_t)
    comctl32.SetWindowSubclass.argtypes = [wintypes.HWND, proc_type, ctypes.c_size_t, ctypes.c_size_t]
    comctl32.RemoveWindowSubclass.argtypes = [wintypes.HWND, proc_type, ctypes.c_size_t]
    comctl32.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    comctl32.DefSubclassProc.restype = ctypes.c_ssize_t

    class Sizes(ctypes.Structure):  # NCCALCSIZE_PARAMS
        _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]

    @proc_type
    def proc(hwnd, msg, wp, lp, _id, _data):
        if msg == 0x0083 and wp:  # WM_NCCALCSIZE: the client area takes the caption and the 1 px border
            r = ctypes.cast(lp, ctypes.POINTER(Sizes)).contents.rgrc[0]
            top, left = r.top, r.left
            result = comctl32.DefSubclassProc(hwnd, msg, wp, lp)
            if user32.IsZoomed(hwnd):  # maximised, the frame hangs off the screen: keep its inset at the top too
                r.top = top + (r.left - left)
            else:
                r.top, r.left, r.right, r.bottom = top, r.left - 1, r.right + 1, r.bottom + 1
            return result
        return comctl32.DefSubclassProc(hwnd, msg, wp, lp)

    form = window.native
    hwnd = form.Handle.ToInt64()

    def frame_changed():
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)  # NOSIZE NOMOVE NOZORDER FRAMECHANGED

    def ready(sender, _args):  # after pywebview's own setup, before the first page loads
        try:
            sender.CoreWebView2.Settings.IsNonClientRegionSupportEnabled = True
            on_ready(True)
        except Exception:  # noqa: BLE001 - WebView2 failed to start, or is too old for drag regions
            comctl32.RemoveWindowSubclass(hwnd, proc, 1)
            frame_changed()
            on_ready(False)

    form.webview.CoreWebView2InitializationCompleted += ready
    _keep.append(proc)
    comctl32.SetWindowSubclass(hwnd, proc, 1, 0)
    frame_changed()
