"""On-disk JSONL buffer for events that could not be uploaded yet."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


class EventBuffer:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        items: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    logger.warning("dropping malformed buffer line: %s", exc)
        return items

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def replace_with(self, events: Iterable[dict[str, Any]]) -> None:
        """Atomic rewrite of the buffer with the given remaining events."""
        tmp_fd, tmp_name = tempfile.mkstemp(dir=str(self.path.parent), prefix=".buf-")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                for e in events:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
            os.replace(tmp_name, self.path)
        except Exception:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise
