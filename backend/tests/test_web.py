from __future__ import annotations

from fastapi.testclient import TestClient


def test_root_redirects_to_onboarding_when_no_session(client: TestClient) -> None:
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/onboarding"


def test_onboarding_creates_user_and_sets_cookie(client: TestClient) -> None:
    r = client.post(
        "/onboarding",
        data={"baseline_cigarettes_per_day": 15, "weaning_rate_pct": 5},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert "snoke_device" in r.cookies


def test_dashboard_renders_after_onboarding(client: TestClient) -> None:
    client.post(
        "/onboarding",
        data={"baseline_cigarettes_per_day": 10, "weaning_rate_pct": 5},
    )
    r = client.get("/")
    assert r.status_code == 200
    assert "Aktuelles Verlangen" in r.text
    assert "Tagesbudget" in r.text
    assert "Coach-Plan Kalender-basiert" in r.text
    assert "Termin einstellen" in r.text


def test_log_cigarette_updates_dashboard(client: TestClient) -> None:
    client.post(
        "/onboarding",
        data={"baseline_cigarettes_per_day": 10, "weaning_rate_pct": 5},
    )
    r = client.post("/web/log/cigarette", data={"trigger": "coffee"})
    assert r.status_code == 200
    # count increment visible in the returned fragment
    assert "Tagesbudget" in r.text


def test_settings_shows_token(client: TestClient) -> None:
    client.post(
        "/onboarding",
        data={"baseline_cigarettes_per_day": 10, "weaning_rate_pct": 5},
    )
    r = client.get("/settings")
    assert r.status_code == 200
    # a JWT has at least two dots
    assert r.text.count(".") >= 2
    assert "Tracker-Token" in r.text


def test_settings_can_store_planner_reactivity(client: TestClient) -> None:
    client.post(
        "/onboarding",
        data={"baseline_cigarettes_per_day": 10, "weaning_rate_pct": 5},
    )
    r = client.post(
        "/settings",
        data={
            "baseline_cigarettes_per_day": 13,
            "weaning_rate_pct": 5,
            "rolling_weight_pct": 25,
            "weight_kg": 75,
            "height_cm": 175,
            "body_fat": 0.20,
            "age_years": 30,
            "weekly_weight_loss_kg": 0.4,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/settings"

    import re
    settings_page = client.get("/settings")
    m = re.search(r"(eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)", settings_page.text)
    assert m is not None
    token = m.group(1)
    cfg = client.get("/me/model-config", headers={"Authorization": f"Bearer {token}"})
    assert cfg.status_code == 200
    body = cfg.json()
    assert body["planner"]["rolling_weight"] == 0.25
    assert body["planner"]["baseline_weight"] == 0.75


def test_settings_hard_reset_requires_confirmation_and_resets_data(client: TestClient) -> None:
    client.post(
        "/onboarding",
        data={"baseline_cigarettes_per_day": 13, "weaning_rate_pct": 5},
    )
    # Add user history that should be deleted by hard reset.
    client.post("/web/log/cigarette", data={"trigger": "coffee"})
    client.post(
        "/calendar/appointments/add",
        data={
            "selected_day": "2026-04-21",
            "title": "Reset Termin",
            "date": "2026-04-21",
            "start_time": "10:00",
            "end_time": "11:00",
        },
        follow_redirects=False,
    )
    client.post(
        "/settings",
        data={
            "baseline_cigarettes_per_day": 13,
            "weaning_rate_pct": 5,
            "rolling_weight_pct": 80,
            "weight_kg": 85,
            "height_cm": 180,
            "body_fat": 0.25,
            "age_years": 35,
            "weekly_weight_loss_kg": 0.8,
        },
        follow_redirects=False,
    )

    bad = client.post("/settings/hard-reset", data={"confirmation_text": "reset"})
    assert bad.status_code == 400

    ok = client.post(
        "/settings/hard-reset",
        data={"confirmation_text": "RESET"},
        follow_redirects=False,
    )
    assert ok.status_code == 303
    assert ok.headers["location"] == "/settings"

    # Defaults visible again.
    settings_page = client.get("/settings")
    assert settings_page.status_code == 200
    assert "value=\"15\"" in settings_page.text
    assert "value=\"5\"" in settings_page.text

    # History was deleted (calendar appointment gone).
    cal = client.get("/calendar?day=2026-04-21")
    assert cal.status_code == 200
    assert "Reset Termin" not in cal.text

    # Model config reset via event deletion fallback to defaults.
    import re
    m = re.search(r"(eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)", settings_page.text)
    assert m is not None
    token = m.group(1)
    cfg = client.get("/me/model-config", headers={"Authorization": f"Bearer {token}"})
    assert cfg.status_code == 200
    cfg_body = cfg.json()
    assert cfg_body["planner"]["rolling_weight"] == 0.3
    assert cfg_body["planner"]["baseline_weight"] == 0.7


def test_how_it_works_page_renders_after_onboarding(client: TestClient) -> None:
    client.post(
        "/onboarding",
        data={"baseline_cigarettes_per_day": 10, "weaning_rate_pct": 5},
    )
    r = client.get("/how-it-works")
    assert r.status_code == 200
    assert "Wie Snoke im Hintergrund rechnet" in r.text
    assert "Halbwertszeiten" in r.text
    assert "Validierung, Baselines und Ablationen" in r.text
    assert "Wissenschaftliche Quellen (DOI)" in r.text
    assert "Aktive Runtime-Parameter" in r.text


def test_calendar_page_renders_and_saves(client: TestClient) -> None:
    client.post(
        "/onboarding",
        data={"baseline_cigarettes_per_day": 10, "weaning_rate_pct": 5},
    )
    r = client.get("/calendar")
    assert r.status_code == 200
    assert "Kalender, Termine und freie Rauch-Slots" in r.text

    r = client.post(
        "/calendar",
        data={
            "monday_enabled": "on",
            "monday_start": "10:00",
            "monday_end": "18:00",
            "tuesday_start": "09:00",
            "tuesday_end": "17:00",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/calendar"


def test_calendar_appointment_add_and_delete(client: TestClient) -> None:
    client.post(
        "/onboarding",
        data={"baseline_cigarettes_per_day": 10, "weaning_rate_pct": 5},
    )
    r = client.post(
        "/calendar/appointments/add",
        data={
            "selected_day": "2026-04-21",
            "title": "Arbeit Meeting",
            "date": "2026-04-21",
            "start_time": "10:00",
            "end_time": "11:00",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/calendar")

    page = client.get("/calendar?day=2026-04-21")
    assert page.status_code == 200
    assert "Arbeit Meeting" in page.text
    assert "10:00–11:00" in page.text


def test_calendar_day_toggle_marks_done(client: TestClient) -> None:
    client.post(
        "/onboarding",
        data={"baseline_cigarettes_per_day": 10, "weaning_rate_pct": 5},
    )
    r = client.post(
        "/calendar/day-toggle",
        data={"selected_day": "2026-04-21", "done": "1"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/calendar?day=2026-04-21")

    page = client.get("/calendar?day=2026-04-21")
    assert page.status_code == 200
    assert "erledigt" in page.text


def test_probability_endpoint_with_bearer(client: TestClient) -> None:
    client.post(
        "/onboarding",
        data={"baseline_cigarettes_per_day": 10, "weaning_rate_pct": 5},
    )
    page = client.get("/settings")
    # JWTs always start with `eyJ` (base64 of `{"`).
    import re
    m = re.search(r"(eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)", page.text)
    assert m is not None
    token = m.group(1)
    r = client.get("/me/probability", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert 0.0 <= body["p_now"] <= 1.0
    assert 0.0 <= body["p_low"] <= 1.0
    assert 0.0 <= body["p_high"] <= 1.0
    assert body["confidence_level"] in {"hoch", "mittel", "niedrig"}
    assert 0.0 <= body["p_next_hour"] <= 1.0


def test_nutrition_page_and_flows(client: TestClient) -> None:
    client.post(
        "/onboarding",
        data={"baseline_cigarettes_per_day": 10, "weaning_rate_pct": 5},
    )
    page = client.get("/nutrition")
    assert page.status_code == 200
    assert "Ernährung & Abnehmen" in page.text
    assert "Kalorien heute" in page.text
    assert "Makro-Ziele heute" in page.text
    assert "Skyr mit Haferflocken und Beeren" in page.text
    assert "Empfohlene nächste Gerichte" in page.text
    assert "Sport eintragen" in page.text

    r = client.post(
        "/nutrition/custom-meal/add",
        data={
            "selected_day": "2026-04-21",
            "name": "Wrap Chicken",
            "kcal_per_portion": "540",
            "portion_label": "1 Wrap",
            "category": "Custom",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/nutrition")

    r = client.post(
        "/nutrition/entry/add",
        data={
            "selected_day": "2026-04-21",
            "meal_name": "Manuell",
            "kcal": "550",
            "portion": "1.0",
            "protein_g": "35",
            "fat_g": "12",
            "carb_g": "60",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/nutrition")

    r = client.post(
        "/nutrition/activity/add",
        data={"selected_day": "2026-04-21", "sport_type": "joggen", "minutes": "35"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/nutrition")

    r = client.post(
        "/nutrition/weight/add",
        data={"selected_day": "2026-04-21", "weight_kg": "78.4"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/nutrition")

    page = client.get("/nutrition?day=2026-04-21")
    assert page.status_code == 200
    assert "Manuell" in page.text
    assert "550 kcal" in page.text
    assert "P 35.0g" in page.text
    assert "joggen" in page.text

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "Letzte Sport-Intervention" in dashboard.text
