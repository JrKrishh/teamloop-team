"""The person sees which window an agent is using, and can stop it: four thin brick-red edges around the window, a
caption above it ("Agent S is using Notepad · Ctrl+Alt+Esc stops it"), and a global Ctrl+Alt+Esc. The edges and the
caption are topmost, never take focus, and let clicks through. Windows only, on its own thread and message loop; it
hides itself 4 seconds after the agent's last step."""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

WS_POPUP, WS_CHILD, WS_VISIBLE = 0x80000000, 0x40000000, 0x10000000
WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x8, 0x80, 0x08000000, 0x80000, 0x20
SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x10, 0x40
WM_HOTKEY, WM_TIMER, WM_CTLCOLORSTATIC, WM_APP = 0x312, 0x113, 0x138, 0x8000
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, VK_ESCAPE = 0x1, 0x2, 0x4000, 0x1B
SS_CENTER, SS_CENTERIMAGE, LWA_ALPHA, EDGE, CAPTION_H = 0x1, 0x200, 0x2, 3, 26
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


def _api():
    u, g, k = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("gdi32"), ctypes.WinDLL("kernel32")
    u.CreateWindowExW.restype = wintypes.HWND
    u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    u.DefWindowProcW.restype = LRESULT
    u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    u.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_ubyte, wintypes.DWORD]
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
    u.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    u.SetTimer.restype = ctypes.c_size_t
    u.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID]
    u.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
    g.CreateSolidBrush.restype = wintypes.HBRUSH
    g.SetTextColor.argtypes = [wintypes.HDC, wintypes.DWORD]
    g.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
    k.GetModuleHandleW.restype = wintypes.HMODULE
    return u, g, k


class Overlay:
    def __init__(self, on_stop, rgb=(194, 85, 76)):
        self.on_stop, self.rgb = on_stop, rgb
        self.pending, self.error, self.tid, self.timer = None, None, 0, 0
        self.ready = threading.Event()
        threading.Thread(target=self._run, name="agent-overlay", daemon=True).start()
        if not self.ready.wait(5):
            raise RuntimeError("The window frame didn't start")
        if self.error:
            raise self.error

    def show(self, left: int, top: int, right: int, bottom: int, label: str) -> None:
        self.pending = (int(left), int(top), int(right), int(bottom), label)
        self.u.PostThreadMessageW(self.tid, WM_APP + 1, 0, 0)

    def hide(self) -> None:
        self.u.PostThreadMessageW(self.tid, WM_APP + 2, 0, 0)

    def _proc(self, hwnd, msg, wp, lp):
        if msg == WM_CTLCOLORSTATIC:  # the caption's text: white on the frame's red
            self.g.SetTextColor(wp, 0xFFFFFF)
            self.g.SetBkMode(wp, 1)
            return self.brush
        return self.u.DefWindowProcW(hwnd, msg, wp, lp)

    def _run(self) -> None:
        try:
            u, g, k = self.u, self.g, self.k = _api()
            self.tid = k.GetCurrentThreadId()
            inst = k.GetModuleHandleW(None)
            r, gr, b = self.rgb
            self.brush = g.CreateSolidBrush(r | gr << 8 | b << 16)
            self._wndproc = WNDPROC(self._proc)  # kept: the window class holds only a pointer to it
            u.RegisterClassW(ctypes.byref(WNDCLASSW(lpfnWndProc=self._wndproc, hInstance=inst, hbrBackground=self.brush,
                                                    lpszClassName="SuperAgentsFrame")))
            through = WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED | WS_EX_TRANSPARENT
            self.edges = [u.CreateWindowExW(through, "SuperAgentsFrame", None, WS_POPUP, 0, 0, 1, 1, None, None, inst, None) for _ in range(4)]
            for e in self.edges:
                u.SetLayeredWindowAttributes(e, 0, 235, LWA_ALPHA)
            self.cap = u.CreateWindowExW(through, "SuperAgentsFrame", None, WS_POPUP, 0, 0, 1, 1, None, None, inst, None)
            u.SetLayeredWindowAttributes(self.cap, 0, 245, LWA_ALPHA)
            self.text = u.CreateWindowExW(0, "STATIC", "", WS_CHILD | WS_VISIBLE | SS_CENTER | SS_CENTERIMAGE, 0, 0, 1, 1, self.cap,
                                          None, inst, None)
            if not all(self.edges) or not self.cap or not self.text:
                raise OSError(ctypes.get_last_error(), "CreateWindowEx failed")
            self.hotkey = bool(u.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_ESCAPE))
        except Exception as e:  # noqa: BLE001 - reported to the caller, which works on without a frame
            self.error = e
            self.ready.set()
            return
        self.ready.set()
        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self._hide()
                self.on_stop()
            elif msg.message == WM_APP + 1:
                self._show()
            elif msg.message == WM_APP + 2 or (msg.message == WM_TIMER and not msg.hWnd):
                self._hide()
            else:
                u.TranslateMessage(ctypes.byref(msg))
                u.DispatchMessageW(ctypes.byref(msg))

    def _show(self) -> None:
        if not self.pending:
            return
        left, top, right, bottom, label = self.pending
        w, h, top_most = right - left, bottom - top, wintypes.HWND(-1)
        flags = SWP_NOACTIVATE | SWP_SHOWWINDOW
        for e, (x, y, cx, cy) in zip(self.edges, [(left - EDGE, top - EDGE, w + 2 * EDGE, EDGE), (left - EDGE, bottom, w + 2 * EDGE, EDGE),
                                                  (left - EDGE, top, EDGE, h), (right, top, EDGE, h)]):
            self.u.SetWindowPos(e, top_most, x, y, cx, cy, flags)
        cw = min(max(w, 240), 9 * len(label) + 28)
        cy = top - EDGE - CAPTION_H if top - EDGE - CAPTION_H >= 0 else top + EDGE
        self.u.SetWindowTextW(self.text, label)
        self.u.SetWindowPos(self.cap, top_most, left - EDGE, cy, cw, CAPTION_H, flags)
        self.u.SetWindowPos(self.text, None, 0, 0, cw, CAPTION_H, SWP_NOACTIVATE | SWP_SHOWWINDOW)
        if self.timer:
            self.u.KillTimer(None, self.timer)
        self.timer = self.u.SetTimer(None, 0, 4000, None)

    def _hide(self) -> None:
        for e in [*self.edges, self.cap]:
            self.u.ShowWindow(e, 0)
        if self.timer:
            self.u.KillTimer(None, self.timer)
            self.timer = 0
