from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient


def _register(client: TestClient) -> str:
    r = client.post(
        "/users/register",
        json={
            "device_id": "device-abc-123",
            "baseline_cigarettes_per_day": 15,
            "weaning_rate_pct": 5,
            "weight_kg": 82.0,
            "height_cm": 181.0,
            "body_fat": 0.19,
            "age_years": 34,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_register_and_batch(client: TestClient) -> None:
    token = _register(client)
    headers = {"Authorization": f"Bearer {token}"}

    now = datetime.now(UTC).isoformat()
    payload = {
        "events": [
            {
                "client_uuid": "cig-00000001",
                "kind": "cigarette",
                "occurred_at": now,
                "payload": {"trigger": "coffee"},
            },
            {
                "client_uuid": "crv-00000001",
                "kind": "craving",
                "occurred_at": now,
                "payload": {"intensity": 7, "resisted": True},
            },
        ]
    }
    r = client.post("/events/batch", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"accepted": 2, "duplicates": 0}

    # Duplicate upload is idempotent.
    r = client.post("/events/batch", json=payload, headers=headers)
    assert r.json() == {"accepted": 0, "duplicates": 2}

    r = client.get("/me/summary", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["today"]["cigarettes"] == 1
    assert body["today"]["cravings"] == 1
    assert body["today"]["cravings_resisted"] == 1
    assert len(body["last_7_days"]) == 7


def test_requires_auth(client: TestClient) -> None:
    r = client.post("/events/batch", json={"events": []})
    # HTTPBearer auto-error returns 403 by default; FastAPI may also surface
    # 401 depending on version. Either is acceptable as "rejected".
    assert r.status_code in (401, 403)
