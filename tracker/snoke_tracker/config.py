from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path


def _load_env_file(path: Path) -> None:
    """Best-effort load of KEY=VALUE lines into os.environ (non-destructive)."""
    if not path.exists():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
    except OSError:
        pass


_DEFAULT_ENV_FILE = Path.home() / ".config" / "snoke" / "tracker.env"
_load_env_file(_DEFAULT_ENV_FILE)


@dataclass(slots=True)
class Config:
    backend: str
    token: str | None
    interval_seconds: int
    buffer_path: Path
    notify: bool
    log_level: str

    @property
    def headers(self) -> dict[str, str]:
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def parse_config(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(
        prog="snoke-tracker",
        description="Local desktop activity tracker for Snoke",
    )
    parser.add_argument(
        "--backend",
        default=_env("SNOKE_BACKEND", "http://127.0.0.1:8000"),
        help="Base URL of the Snoke backend",
    )
    parser.add_argument(
        "--token",
        default=_env("SNOKE_TOKEN"),
        help="API token issued at /settings in the web UI",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(_env("SNOKE_INTERVAL", "60") or "60"),
        help="Seconds between context snapshots",
    )
    parser.add_argument(
        "--buffer",
        default=_env(
            "SNOKE_BUFFER",
            str(Path.home() / ".local" / "share" / "snoke" / "buffer.jsonl"),
        ),
        help="Path to local JSONL buffer for offline events",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Disable desktop notifications for nudges",
    )
    parser.add_argument(
        "--log-level",
        default=_env("SNOKE_LOG_LEVEL", "INFO"),
        help="Python logging level (DEBUG, INFO, WARNING, …)",
    )
    args = parser.parse_args(argv)
    return Config(
        backend=args.backend.rstrip("/"),
        token=args.token,
        interval_seconds=max(10, args.interval),
        buffer_path=Path(args.buffer),
        notify=not args.no_notify,
        log_level=args.log_level.upper(),
    )
