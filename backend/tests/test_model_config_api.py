from __future__ import annotations

from fastapi.testclient import TestClient


def _register(client: TestClient) -> str:
    r = client.post(
        "/users/register",
        json={
            "device_id": "model-cfg-device-1",
            "baseline_cigarettes_per_day": 12,
            "weaning_rate_pct": 5,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_model_config_get_put_reset(client: TestClient) -> None:
    token = _register(client)
    headers = {"Authorization": f"Bearer {token}"}

    # default config
    r = client.get("/me/model-config", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["schema_version"] == "1.0"
    assert body["simulation"]["dt_seconds"] == 60
    assert body["planner"]["baseline_weight"] == 0.7
    assert body["planner"]["rolling_weight"] == 0.3

    # update config
    body["dynamics"]["k_dopamine"] = 0.77
    body["readout"]["w_W"] = 3.2
    body["kalman"]["enabled"] = False
    r = client.put("/me/model-config", headers=headers, json=body)
    assert r.status_code == 200
    updated = r.json()
    assert updated["dynamics"]["k_dopamine"] == 0.77
    assert updated["readout"]["w_W"] == 3.2
    assert updated["kalman"]["enabled"] is False

    # persisted
    r = client.get("/me/model-config", headers=headers)
    assert r.status_code == 200
    persisted = r.json()
    assert persisted["dynamics"]["k_dopamine"] == 0.77
    assert persisted["readout"]["w_W"] == 3.2
    assert persisted["kalman"]["enabled"] is False

    # reset
    r = client.post("/me/model-config/reset", headers=headers)
    assert r.status_code == 200
    reset = r.json()
    assert reset["dynamics"]["k_dopamine"] == 0.35
    assert reset["dynamics"]["lambda_nicotine"] == 0.35
    assert reset["dynamics"]["k_dopamine_fast"] == 1.1
    assert reset["dynamics"]["k_dopamine_slow"] == 0.08
    assert reset["readout"]["w_W"] == 2.4
    assert reset["kalman"]["enabled"] is True
