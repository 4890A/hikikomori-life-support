"""Where the mouse and windows are on the desktop, so her eyes can follow them.

A web page can't see the mouse outside itself, or where a shared window is. This reads both from
Windows and streams them to her page. Everything is in physical pixels, which stay correct across
display scaling and several monitors. It stays on this PC and never goes to the LLM.
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import sys
from collections.abc import AsyncIterator, Callable
from ctypes import wintypes

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

AVAILABLE = sys.platform == "win32"
POLL_SECONDS = 1 / 30
# How often to look for her page's window again, and to show the connection is alive when nothing moves.
FIND_PAGE_SECONDS = 1.0
KEEP_ALIVE_SECONDS = 15.0
# Browsers whose tab title becomes the window title.
BROWSER_CLASSES = ("Chrome_WidgetWin", "MozillaWindowClass")
DWMWA_EXTENDED_FRAME_BOUNDS = 9
PER_MONITOR_AWARE_V2 = -4

router = APIRouter()

if AVAILABLE:
    _user32 = ctypes.WinDLL("user32")
    _dwmapi = ctypes.WinDLL("dwmapi")
    _EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _user32.EnumWindows.argtypes = [_EnumWindowsProc, wintypes.LPARAM]
    for _name in ("IsWindow", "IsWindowVisible", "IsIconic"):
        getattr(_user32, _name).argtypes = [wintypes.HWND]
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.InternalGetWindowText.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    _dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    # Otherwise Windows reports scaled positions that don't match across monitors.
    _user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(PER_MONITOR_AWARE_V2))


def cursor() -> list[int]:
    point = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(point))
    return [point.x, point.y]


def window_rect(handle: int) -> dict | None:
    """The visible edges of a window, or None if it's closed, hidden or minimized."""
    if not handle or not _user32.IsWindow(handle) or not _user32.IsWindowVisible(handle) or _user32.IsIconic(handle):
        return None
    rect = wintypes.RECT()
    # Unlike GetWindowRect, this leaves out the invisible resize border.
    if _dwmapi.DwmGetWindowAttribute(handle, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
        return None
    return {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom}


def _title(handle: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    # GetWindowText can wait on a frozen app, and this doesn't.
    _user32.InternalGetWindowText(handle, buffer, len(buffer))
    return buffer.value


def _is_browser(handle: int) -> bool:
    buffer = ctypes.create_unicode_buffer(64)
    _user32.GetClassNameW(handle, buffer, len(buffer))
    return buffer.value.startswith(BROWSER_CLASSES)


def find_browser_window(title: str) -> int:
    """The browser window showing a tab with this title, or 0."""
    found = 0

    def check(handle: int, _: int) -> bool:
        nonlocal found
        if _user32.IsWindowVisible(handle) and _title(handle).startswith(title) and _is_browser(handle):
            found = handle
            return False
        return True

    _user32.EnumWindows(_EnumWindowsProc(check), 0)
    return found


class DesktopReader:
    def __init__(self, page_title: str, target: int) -> None:
        self.page_title = page_title
        self.target = target
        self.page_window = 0
        self.until_search = 0.0

    def read(self) -> dict:
        self.until_search -= POLL_SECONDS
        if self.until_search <= 0:
            self.until_search = FIND_PAGE_SECONDS
            self.page_window = find_browser_window(self.page_title)
        return {
            "cursor": cursor(),
            "page": window_rect(self.page_window),
            "target": window_rect(self.target),
        }


async def updates(read: Callable[[], dict]) -> AsyncIterator[str]:
    """Server-sent events, sent only when something has moved."""
    last = None
    quiet = 0.0
    while True:
        state = read()
        if state != last:
            last = state
            quiet = 0.0
            yield f"data: {json.dumps(state)}\n\n"
        elif quiet >= KEEP_ALIVE_SECONDS:
            quiet = 0.0
            yield ": alive\n\n"
        await asyncio.sleep(POLL_SECONDS)
        quiet += POLL_SECONDS


@router.get("/desktop/stream")
async def stream(page: str, window: int = 0) -> StreamingResponse:
    if not AVAILABLE:
        raise HTTPException(status_code=404, detail="Only available on Windows")
    return StreamingResponse(updates(DesktopReader(page, window).read), media_type="text/event-stream")
