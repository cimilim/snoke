"""Collect desktop activity signals in a privacy-preserving way.

Guarantees:
* never record the content of any keystroke;
* never capture clipboard or screenshots;
* truncate window titles heavily and strip URL-looking substrings before
  emitting them.
"""

from __future__ import annotations

import logging
import re
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://\S+")
_MAX_TITLE_LEN = 80


def _sanitise_title(title: str | None) -> str | None:
    if not title:
        return None
    cleaned = _URL_RE.sub("[url]", title)
    cleaned = cleaned.strip()
    if len(cleaned) > _MAX_TITLE_LEN:
        cleaned = cleaned[: _MAX_TITLE_LEN - 1] + "…"
    return cleaned


# --- Active window via python-xlib (Linux / X11) ---------------------------

class _XlibActiveWindow:
    """Query the EWMH active-window + idle time from X11. Linux-only."""

    def __init__(self) -> None:
        from Xlib import X, display  # type: ignore[import-untyped]
        from Xlib.ext import screensaver  # type: ignore[import-untyped]

        self._display = display.Display()
        self._root = self._display.screen().root
        self._X = X
        self._screensaver = screensaver
        self._NET_ACTIVE = self._display.intern_atom("_NET_ACTIVE_WINDOW")
        self._NET_NAME = self._display.intern_atom("_NET_WM_NAME")
        self._WM_CLASS = self._display.intern_atom("WM_CLASS")
        self._UTF8 = self._display.intern_atom("UTF8_STRING")

    def active(self) -> tuple[str | None, str | None]:
        try:
            prop = self._root.get_full_property(self._NET_ACTIVE, self._X.AnyPropertyType)
            if prop is None or not prop.value:
                return None, None
            win_id = int(prop.value[0])
            if win_id == 0:
                return None, None
            win = self._display.create_resource_object("window", win_id)
            title = None
            name_prop = win.get_full_property(self._NET_NAME, self._UTF8)
            if name_prop is not None:
                raw = name_prop.value
                if isinstance(raw, bytes):
                    title = raw.decode("utf-8", errors="replace")
                else:
                    title = str(raw)
            cls_prop = win.get_full_property(self._WM_CLASS, self._X.AnyPropertyType)
            cls_name = None
            if cls_prop is not None and cls_prop.value:
                raw = cls_prop.value
                if isinstance(raw, bytes):
                    parts = raw.split(b"\x00")
                    if parts:
                        cls_name = parts[-2 if len(parts) > 1 else 0].decode(
                            "utf-8", errors="replace"
                        ) or None
            return cls_name, title
        except Exception as exc:  # pragma: no cover - X errors
            logger.debug("xlib active_window failed: %s", exc)
            return None, None

    def idle_seconds(self) -> int | None:
        try:
            info = self._screensaver.query_info(self._root)
            return int(info.idle / 1000)
        except Exception as exc:  # pragma: no cover
            logger.debug("xlib idle failed: %s", exc)
            return None


def _make_active_window() -> _XlibActiveWindow | None:
    try:
        import os

        if not os.environ.get("DISPLAY"):
            return None
        return _XlibActiveWindow()
    except Exception as exc:
        logger.info("X11 active-window not available (%s); continuing without it", exc)
        return None


# --- Input rate via pynput -------------------------------------------------

@dataclass(slots=True)
class _Counters:
    kbd: int = 0
    mouse: int = 0
    last_event_at: float = field(default_factory=time.monotonic)


class InputRateCollector:
    """Count keyboard/mouse events per window, never their content."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._c = _Counters()
        self._listeners: list[Any] = []

    def start(self) -> None:
        try:
            from pynput import keyboard, mouse  # type: ignore[import-untyped]
        except Exception as exc:
            logger.warning("pynput unavailable: %s (input counts disabled)", exc)
            return

        def on_key(_key: Any) -> None:
            with self._lock:
                self._c.kbd += 1
                self._c.last_event_at = time.monotonic()

        def on_click(*_a: Any, **_kw: Any) -> None:
            with self._lock:
                self._c.mouse += 1
                self._c.last_event_at = time.monotonic()

        def on_move(*_a: Any, **_kw: Any) -> None:
            with self._lock:
                self._c.mouse += 1
                self._c.last_event_at = time.monotonic()

        kb_listener = keyboard.Listener(on_press=on_key, suppress=False)
        ms_listener = mouse.Listener(on_click=on_click, on_scroll=on_click,
                                     on_move=on_move, suppress=False)
        kb_listener.daemon = True
        ms_listener.daemon = True
        kb_listener.start()
        ms_listener.start()
        self._listeners = [kb_listener, ms_listener]

    def snapshot_and_reset(self, interval_s: float) -> tuple[int, int, float]:
        with self._lock:
            kbd, mouse_c = self._c.kbd, self._c.mouse
            last = self._c.last_event_at
            self._c.kbd = 0
            self._c.mouse = 0
        factor = 60.0 / max(1.0, interval_s)
        return int(kbd * factor), int(mouse_c * factor), last


# --- Top-level snapshot ----------------------------------------------------

class DesktopSampler:
    def __init__(self) -> None:
        self.input = InputRateCollector()
        self.input.start()
        self.window = _make_active_window()
        self._hostname = socket.gethostname()
        self._last_tick = time.monotonic()

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        interval = now - self._last_tick
        self._last_tick = now

        kbd_pm, mouse_pm, last_event_at = self.input.snapshot_and_reset(interval)
        idle_seconds: int | None = None
        active_app: str | None = None
        active_title: str | None = None
        if self.window is not None:
            active_app, active_title = self.window.active()
            idle_seconds = self.window.idle_seconds()
        if idle_seconds is None:
            # fallback via pynput last-event timestamp
            idle_seconds = max(0, int(now - last_event_at))

        return {
            "active_app": active_app,
            "active_title": _sanitise_title(active_title),
            "idle_seconds": idle_seconds,
            "kbd_per_min": kbd_pm,
            "mouse_per_min": mouse_pm,
            "hostname": self._hostname,
        }
