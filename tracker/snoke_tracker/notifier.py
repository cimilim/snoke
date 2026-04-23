"""Desktop notifications via `notify-send`; falls back to stdout."""

from __future__ import annotations

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)


class DesktopNotifier:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._notify_send = shutil.which("notify-send") if enabled else None

    def notify(self, title: str, body: str, urgency: str = "normal") -> None:
        if not self.enabled:
            return
        if self._notify_send:
            try:
                subprocess.run(
                    [
                        self._notify_send,
                        "-a", "Snoke",
                        "-u", urgency,
                        "-t", "10000",
                        title,
                        body,
                    ],
                    check=False,
                    timeout=5,
                )
                return
            except Exception as exc:
                logger.debug("notify-send failed: %s", exc)
        # Fallback: just log to stdout so the user still sees it in the terminal.
        print(f"\n[Snoke] {title}\n        {body}\n", flush=True)
