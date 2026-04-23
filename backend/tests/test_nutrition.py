from __future__ import annotations

from datetime import UTC, datetime

from app.models import Event, User
from app.nutrition.service import (
    NUTRITION_ACTIVITY_KIND,
    NUTRITION_CUSTOM_MEAL_KIND,
    NUTRITION_ENTRY_KIND,
    WEIGHT_ENTRY_KIND,
    daily_calorie_target_kcal,
    macro_range_status,
    merged_meal_catalog,
    nutrition_dashboard_metrics,
    recommend_meals_for_targets,
    who_fat_loss_macro_targets,
)


def test_daily_target_is_reasonable_range() -> None:
    user = User(
        id="u-1",
        baseline_cigarettes_per_day=10,
        weaning_rate_pct=5,
        weight_kg=82.0,
        height_cm=180.0,
        body_fat=0.20,
        age_years=33,
    )
    target = daily_calorie_target_kcal(user)
    assert 1200 <= target <= 4000
    macros = who_fat_loss_macro_targets(user, target)
    assert macros["protein"].target_g >= macros["protein"].min_g
    assert macros["fat"].max_g >= macros["fat"].min_g
    assert macros["carb"].min_g >= 130.0
    assert macro_range_status(macros["protein"].target_g, macros["protein"]) == "im_bereich"


def test_nutrition_metrics_aggregate_entries(client) -> None:
    client.post(
        "/onboarding",
        data={"baseline_cigarettes_per_day": 10, "weaning_rate_pct": 5},
    )
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        user = db.query(User).first()
        assert user is not None
        now = datetime.now(UTC)
        db.add(
            Event(
                user_id=user.id,
                client_uuid="nut-00000001",
                kind=NUTRITION_ENTRY_KIND,
                occurred_at=now,
                payload={
                    "meal_name": "Test",
                    "kcal": 500,
                    "portion": 1.0,
                    "protein_g": 30.0,
                    "fat_g": 14.0,
                    "carb_g": 52.0,
                },
            )
        )
        db.add(
            Event(
                user_id=user.id,
                client_uuid="wgt-00000001",
                kind=WEIGHT_ENTRY_KIND,
                occurred_at=now,
                payload={"weight_kg": 79.2},
            )
        )
        db.add(
            Event(
                user_id=user.id,
                client_uuid="act-00000001",
                kind=NUTRITION_ACTIVITY_KIND,
                occurred_at=now,
                payload={"sport_type": "joggen", "minutes": 30, "kcal_burned": 280},
            )
        )
        db.add(
            Event(
                user_id=user.id,
                client_uuid="meal-00000001",
                kind=NUTRITION_CUSTOM_MEAL_KIND,
                occurred_at=now,
                payload={"name": "Custom Bowl", "kcal_per_portion": 640, "portion_label": "1 Bowl"},
            )
        )
        db.commit()

        metrics = nutrition_dashboard_metrics(db, user, day=now.date())
        assert metrics["consumed_kcal"] >= 500
        assert metrics["activity_kcal_burned"] >= 280
        assert metrics["target_kcal"] >= metrics["base_target_kcal"]
        assert metrics["consumed_protein_g"] >= 30.0
        assert metrics["consumed_fat_g"] >= 14.0
        assert metrics["consumed_carb_g"] >= 52.0
        assert "protein" in metrics["macro_targets"]
        assert metrics["latest_weight_kg"] == 79.2

        catalog = merged_meal_catalog(db, user)
        assert any(m.name == "Custom Bowl" for m in catalog)
        assert any(m.name == "Skyr mit Haferflocken und Beeren" for m in catalog)

        recs = recommend_meals_for_targets(
            meals=catalog,
            consumed_kcal=metrics["consumed_kcal"],
            target_kcal=metrics["target_kcal"],
            consumed_protein_g=metrics["consumed_protein_g"],
            consumed_fat_g=metrics["consumed_fat_g"],
            consumed_carb_g=metrics["consumed_carb_g"],
            macro_targets=metrics["macro_targets"],
            limit=3,
        )
        assert len(recs) == 3
        assert recs[0].meal_name

