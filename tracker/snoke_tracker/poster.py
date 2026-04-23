"""HTTP client talking to the Snoke backend."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class BackendClient:
    def __init__(self, base_url: str, token: str | None, timeout: float = 10.0) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers=({"Authorization": f"Bearer {token}"} if token else {}),
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def ping(self) -> bool:
        try:
            r = self._client.get("/healthz")
            return r.status_code == 200
        except Exception as exc:
            logger.debug("ping failed: %s", exc)
            return False

    def post_events(self, events: list[dict[str, Any]]) -> tuple[bool, dict]:
        try:
            r = self._client.post("/events/batch", json={"events": events})
        except Exception as exc:
            logger.info("network error uploading %d events: %s", len(events), exc)
            return False, {}
        if r.status_code == 401:
            logger.error("backend rejected token (401). Please regenerate via /settings.")
            return False, {}
        if r.status_code >= 500:
            logger.info("backend error %s, will retry", r.status_code)
            return False, {}
        if r.status_code >= 400:
            logger.error("backend returned %s: %s", r.status_code, r.text[:200])
            return False, {}
        return True, r.json()

    def fetch_recommendation(self) -> dict | None:
        try:
            r = self._client.get("/me/recommendation")
        except Exception as exc:
            logger.debug("recommendation fetch failed: %s", exc)
            return None
        if r.status_code != 200:
            return None
        return r.json()
