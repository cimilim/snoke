"""Main loop of the Snoke desktop tracker."""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from snoke_tracker.buffer import EventBuffer
from snoke_tracker.collectors import DesktopSampler
from snoke_tracker.config import Config, parse_config
from snoke_tracker.notifier import DesktopNotifier
from snoke_tracker.poster import BackendClient

logger = logging.getLogger(__name__)

_RUNNING = True


def _stop(*_args: Any) -> None:
    global _RUNNING
    _RUNNING = False
    logger.info("received signal, shutting down")


def _make_event(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "client_uuid": f"ctx-{uuid.uuid4().hex[:16]}",
        "kind": "context",
        "occurred_at": datetime.now(UTC).isoformat(),
        "payload": payload,
    }


def _flush(client: BackendClient, buffer: EventBuffer) -> None:
    pending = buffer.read_all()
    if not pending:
        return
    ok, resp = client.post_events(pending)
    if ok:
        logger.info("uploaded %d events (accepted=%s duplicates=%s)",
                    len(pending), resp.get("accepted"), resp.get("duplicates"))
        buffer.clear()
    else:
        logger.info("%d events remain buffered", len(pending))


def _maybe_nudge(client: BackendClient, notifier: DesktopNotifier,
                 last_notified_id: str | None) -> str | None:
    reco = client.fetch_recommendation()
    if not reco:
        return last_notified_id
    nudge = reco.get("nudge")
    if not nudge:
        return last_notified_id
    nid = nudge.get("id")
    if nid == last_notified_id:
        return last_notified_id
    p_pct = int(round(reco.get("probability", {}).get("p_now", 0.0) * 100))
    notifier.notify(
        title=f"Snoke · {p_pct}% Verlangen",
        body=f"{nudge.get('title')} — {nudge.get('body')}",
        urgency="critical" if p_pct >= 55 else "normal",
    )
    return nid


def run(config: Config) -> int:
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not config.token:
        logger.error("no API token set. Get one at %s/settings and pass --token.",
                     config.backend)
        return 2

    buffer = EventBuffer(config.buffer_path)
    client = BackendClient(config.backend, config.token)
    notifier = DesktopNotifier(enabled=config.notify)
    sampler = DesktopSampler()

    if not client.ping():
        logger.warning("backend not reachable at %s — events will be buffered",
                       config.backend)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    last_nudge_id: str | None = None
    logger.info("snoke-tracker started. Posting every %s s to %s",
                config.interval_seconds, config.backend)

    while _RUNNING:
        t0 = time.monotonic()
        try:
            payload = sampler.snapshot()
            buffer.append(_make_event(payload))
            _flush(client, buffer)
            last_nudge_id = _maybe_nudge(client, notifier, last_nudge_id)
        except Exception as exc:  # never die in the main loop
            logger.exception("tick failed: %s", exc)

        elapsed = time.monotonic() - t0
        sleep_for = max(1.0, config.interval_seconds - elapsed)
        # Use short sleeps so ctrl-C is responsive.
        while _RUNNING and sleep_for > 0:
            step = min(1.0, sleep_for)
            time.sleep(step)
            sleep_for -= step

    client.close()
    logger.info("snoke-tracker stopped cleanly")
    return 0


def _register(argv: list[str]) -> int:
    """One-shot: register a new anonymous user and print/save a token.

    Usage:
        snoke-tracker register [--backend URL] [--baseline N] [--rate PCT] [--save PATH]
    """
    import argparse

    parser = argparse.ArgumentParser(prog="snoke-tracker register")
    parser.add_argument("--backend", default=os.environ.get("SNOKE_BACKEND",
                                                            "http://127.0.0.1:8000"))
    parser.add_argument("--baseline", type=int, default=15)
    parser.add_argument("--rate", type=int, default=5)
    parser.add_argument(
        "--save",
        default=str(Path.home() / ".config" / "snoke" / "tracker.env"),
        help="Where to store SNOKE_BACKEND and SNOKE_TOKEN",
    )
    args = parser.parse_args(argv)

    device_id = f"dev-{uuid.uuid4().hex[:16]}"
    body = {
        "device_id": device_id,
        "baseline_cigarettes_per_day": args.baseline,
        "weaning_rate_pct": args.rate,
    }
    r = httpx.post(f"{args.backend.rstrip('/')}/users/register", json=body, timeout=10)
    r.raise_for_status()
    token = r.json()["access_token"]

    out = Path(args.save)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"SNOKE_BACKEND={args.backend}\nSNOKE_TOKEN={token}\n",
        encoding="utf-8",
    )
    os.chmod(out, 0o600)
    print(f"registered device {device_id}")
    print(f"credentials written to {out}")
    print("start the tracker with: snoke-tracker")
    return 0


def main() -> None:
    # tiny dispatcher for subcommands
    if len(sys.argv) >= 2 and sys.argv[1] == "register":
        raise SystemExit(_register(sys.argv[2:]))
    raise SystemExit(run(parse_config()))


if __name__ == "__main__":
    main()
