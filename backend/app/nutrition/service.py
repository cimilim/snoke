from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, User
from app.nutrition.catalog import DEFAULT_MEALS, MealItem, estimate_macros_from_kcal

NUTRITION_ENTRY_KIND = "nutrition_entry"
WEIGHT_ENTRY_KIND = "weight_entry"
NUTRITION_CUSTOM_MEAL_KIND = "nutrition_custom_meal"
NUTRITION_ACTIVITY_KIND = "nutrition_activity"

SPORT_MET: dict[str, float] = {
    "gehen": 3.3,
    "joggen": 7.0,
    "laufen": 10.0,
    "radfahren": 7.5,
    "schwimmen": 8.0,
    "krafttraining": 6.0,
    "yoga": 3.0,
    "fussball": 8.0,
    "tennis": 7.3,
    "wandern": 6.0,
}


@dataclass(slots=True)
class NutritionEntry:
    id: int
    occurred_at: datetime
    meal_name: str
    kcal: int
    portion: float
    protein_g: float
    fat_g: float
    carb_g: float


@dataclass(slots=True)
class WeightEntry:
    id: int
    occurred_at: datetime
    weight_kg: float


@dataclass(slots=True)
class ActivityEntry:
    id: int
    occurred_at: datetime
    sport_type: str
    minutes: int
    kcal_burned: int


@dataclass(slots=True)
class MacroRange:
    min_g: float
    target_g: float
    max_g: float


@dataclass(slots=True)
class MealRecommendation:
    meal_id: str
    meal_name: str
    kcal: int
    protein_g: float
    fat_g: float
    carb_g: float
    score: float
    reason: str


def _utc_day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return start, start + timedelta(days=1)


def bmr_katch_mcardle(weight_kg: float, body_fat: float) -> float:
    lean_mass = max(30.0, weight_kg * (1.0 - body_fat))
    return 370.0 + (21.6 * lean_mass)


def daily_calorie_target_kcal(
    user: User,
    *,
    activity_factor: float = 1.4,
    deficit_kcal: int | None = None,
) -> int:
    weekly_goal = max(0.0, min(2.0, float(getattr(user, "weekly_weight_loss_kg", 0.4) or 0.4)))
    if deficit_kcal is None:
        deficit_kcal = int(round((weekly_goal * 7700.0) / 7.0))
    deficit_kcal = max(0, min(1300, int(deficit_kcal)))
    tdee = bmr_katch_mcardle(user.weight_kg, user.body_fat) * activity_factor
    target = int(round(tdee - deficit_kcal))
    return max(1200, min(4000, target))


def activity_kcal_burned(weight_kg: float, sport_type: str, minutes: int) -> int:
    met = SPORT_MET.get(sport_type.strip().lower(), 5.0)
    kcal = met * max(35.0, weight_kg) * (max(1, minutes) / 60.0)
    return max(1, int(round(kcal)))


def who_fat_loss_macro_targets(user: User, target_kcal: int) -> dict[str, MacroRange]:
    """WHO-informed daily macro ranges for fat-loss context.

    Uses:
    - protein safeguard by body weight for satiety/muscle retention in deficit
    - fat range aligned to WHO-inspired energy-share corridor
    - carbs as remaining energy with practical lower bound
    """
    kcal = max(1200, float(target_kcal))
    weight = max(35.0, float(user.weight_kg))

    # Protein: practical fat-loss safeguard.
    p_min = max(1.2 * weight, (0.15 * kcal) / 4.0)
    p_target = max(1.6 * weight, (0.22 * kcal) / 4.0)
    p_max = max(p_target, min(2.2 * weight, (0.35 * kcal) / 4.0))

    # Fat: WHO-inspired safe corridor.
    f_min = (0.20 * kcal) / 9.0
    f_target = (0.25 * kcal) / 9.0
    f_max = (0.30 * kcal) / 9.0

    # Carbs: remainder with practical floor (not extreme-low by default).
    c_target_kcal = max(0.0, kcal - (p_target * 4.0) - (f_target * 9.0))
    c_min = max(130.0, (0.35 * kcal) / 4.0)
    c_target = max(c_min, c_target_kcal / 4.0)
    c_max = max(c_target, (0.60 * kcal) / 4.0)

    return {
        "protein": MacroRange(round(p_min, 1), round(p_target, 1), round(p_max, 1)),
        "fat": MacroRange(round(f_min, 1), round(f_target, 1), round(f_max, 1)),
        "carb": MacroRange(round(c_min, 1), round(c_target, 1), round(c_max, 1)),
    }


def macro_range_status(consumed: float, target: MacroRange) -> str:
    if consumed < target.min_g:
        return "unter"
    if consumed > target.max_g:
        return "ueber"
    return "im_bereich"


def recommend_meals_for_targets(
    *,
    meals: list[MealItem],
    consumed_kcal: int,
    target_kcal: int,
    consumed_protein_g: float,
    consumed_fat_g: float,
    consumed_carb_g: float,
    macro_targets: dict[str, MacroRange],
    limit: int = 3,
) -> list[MealRecommendation]:
    remaining_kcal = max(0.0, float(target_kcal - consumed_kcal))
    p_need = max(0.0, macro_targets["protein"].target_g - consumed_protein_g)
    f_need = max(0.0, macro_targets["fat"].target_g - consumed_fat_g)
    c_need = max(0.0, macro_targets["carb"].target_g - consumed_carb_g)

    recs: list[MealRecommendation] = []
    for m in meals:
        if m.kcal_per_portion <= 0:
            continue
        p_gain = min(m.protein_g, p_need) / max(1.0, p_need)
        f_gain = min(m.fat_g, f_need) / max(1.0, f_need)
        c_gain = min(m.carb_g, c_need) / max(1.0, c_need)
        benefit = (1.3 * p_gain) + (0.7 * f_gain) + (0.9 * c_gain)

        p_over = max(0.0, (consumed_protein_g + m.protein_g) - macro_targets["protein"].max_g)
        f_over = max(0.0, (consumed_fat_g + m.fat_g) - macro_targets["fat"].max_g)
        c_over = max(0.0, (consumed_carb_g + m.carb_g) - macro_targets["carb"].max_g)
        overflow_penalty = (
            (p_over / max(1.0, macro_targets["protein"].max_g))
            + (f_over / max(1.0, macro_targets["fat"].max_g))
            + (c_over / max(1.0, macro_targets["carb"].max_g))
        )

        if remaining_kcal <= 0:
            kcal_penalty = 1.0 + (m.kcal_per_portion / 500.0)
        else:
            kcal_penalty = max(0.0, (m.kcal_per_portion - remaining_kcal) / max(120.0, remaining_kcal))
        healthy_bonus = 0.15 if m.is_healthy_alternative else 0.0
        score = benefit + healthy_bonus - overflow_penalty - (0.6 * kcal_penalty)

        strongest = max(
            [("Protein", p_gain), ("Fett", f_gain), ("Kohlenhydrate", c_gain)],
            key=lambda x: x[1],
        )[0]
        reason = f"Hilft v. a. bei {strongest}"
        if m.is_healthy_alternative:
            reason += " (gesund)"

        recs.append(
            MealRecommendation(
                meal_id=m.id,
                meal_name=m.name,
                kcal=int(m.kcal_per_portion),
                protein_g=round(float(m.protein_g), 1),
                fat_g=round(float(m.fat_g), 1),
                carb_g=round(float(m.carb_g), 1),
                score=round(float(score), 3),
                reason=reason,
            )
        )

    recs.sort(key=lambda r: r.score, reverse=True)
    return recs[: max(1, limit)]


def load_custom_meals(db: Session, user: User) -> list[MealItem]:
    rows = list(
        db.execute(
            select(Event)
            .where(Event.user_id == user.id, Event.kind == NUTRITION_CUSTOM_MEAL_KIND)
            .order_by(Event.occurred_at.asc(), Event.id.asc())
        ).scalars()
    )
    custom: list[MealItem] = []
    for ev in rows:
        payload = ev.payload if isinstance(ev.payload, dict) else {}
        name = str(payload.get("name", "")).strip()
        portion_label = str(payload.get("portion_label", "1 Portion")).strip() or "1 Portion"
        category = str(payload.get("category", "Custom")).strip() or "Custom"
        try:
            kcal = int(round(float(payload.get("kcal_per_portion", 0))))
        except Exception:
            kcal = 0
        try:
            protein_g = float(payload.get("protein_g", 0))
        except Exception:
            protein_g = 0.0
        try:
            fat_g = float(payload.get("fat_g", 0))
        except Exception:
            fat_g = 0.0
        try:
            carb_g = float(payload.get("carb_g", 0))
        except Exception:
            carb_g = 0.0
        if not name or kcal <= 0:
            continue
        if protein_g <= 0.0 and fat_g <= 0.0 and carb_g <= 0.0:
            protein_g, fat_g, carb_g = estimate_macros_from_kcal(kcal)
        custom.append(
            MealItem(
                id=f"custom-{ev.id}",
                name=name,
                kcal_per_portion=kcal,
                portion_label=portion_label,
                category=category,
                protein_g=round(protein_g, 1),
                fat_g=round(fat_g, 1),
                carb_g=round(carb_g, 1),
                is_healthy_alternative=bool(payload.get("is_healthy_alternative", False)),
                source="custom",
            )
        )
    return custom


def merged_meal_catalog(db: Session, user: User) -> list[MealItem]:
    custom = load_custom_meals(db, user)
    out: list[MealItem] = []
    seen: set[tuple[str, str]] = set()
    for meal in [*custom, *DEFAULT_MEALS]:
        key = (meal.name.strip().lower(), meal.portion_label.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(meal)
    return out


def load_day_entries(db: Session, user: User, day: date) -> list[NutritionEntry]:
    start, end = _utc_day_bounds(day)
    rows = list(
        db.execute(
            select(Event)
            .where(
                Event.user_id == user.id,
                Event.kind == NUTRITION_ENTRY_KIND,
                Event.occurred_at >= start,
                Event.occurred_at < end,
            )
            .order_by(Event.occurred_at.desc(), Event.id.desc())
        ).scalars()
    )
    out: list[NutritionEntry] = []
    for ev in rows:
        payload = ev.payload if isinstance(ev.payload, dict) else {}
        meal_name = str(payload.get("meal_name", "Mahlzeit")).strip() or "Mahlzeit"
        try:
            kcal = int(round(float(payload.get("kcal", 0))))
        except Exception:
            kcal = 0
        try:
            portion = float(payload.get("portion", 1.0))
        except Exception:
            portion = 1.0
        try:
            protein_g = float(payload.get("protein_g", 0.0))
        except Exception:
            protein_g = 0.0
        try:
            fat_g = float(payload.get("fat_g", 0.0))
        except Exception:
            fat_g = 0.0
        try:
            carb_g = float(payload.get("carb_g", 0.0))
        except Exception:
            carb_g = 0.0
        if ev.occurred_at.tzinfo is None:
            ev.occurred_at = ev.occurred_at.replace(tzinfo=UTC)
        out.append(
            NutritionEntry(
                id=ev.id,
                occurred_at=ev.occurred_at,
                meal_name=meal_name,
                kcal=max(0, kcal),
                portion=max(0.1, portion),
                protein_g=max(0.0, protein_g),
                fat_g=max(0.0, fat_g),
                carb_g=max(0.0, carb_g),
            )
        )
    return out


def load_weight_entries(db: Session, user: User, *, days: int = 14) -> list[WeightEntry]:
    now = datetime.now(UTC)
    start = now - timedelta(days=days)
    rows = list(
        db.execute(
            select(Event)
            .where(
                Event.user_id == user.id,
                Event.kind == WEIGHT_ENTRY_KIND,
                Event.occurred_at >= start,
            )
            .order_by(Event.occurred_at.asc(), Event.id.asc())
        ).scalars()
    )
    out: list[WeightEntry] = []
    for ev in rows:
        payload = ev.payload if isinstance(ev.payload, dict) else {}
        try:
            weight_kg = float(payload.get("weight_kg", 0.0))
        except Exception:
            weight_kg = 0.0
        if weight_kg <= 0:
            continue
        if ev.occurred_at.tzinfo is None:
            ev.occurred_at = ev.occurred_at.replace(tzinfo=UTC)
        out.append(WeightEntry(id=ev.id, occurred_at=ev.occurred_at, weight_kg=weight_kg))
    return out


def load_day_activity_entries(db: Session, user: User, day: date) -> list[ActivityEntry]:
    start, end = _utc_day_bounds(day)
    rows = list(
        db.execute(
            select(Event)
            .where(
                Event.user_id == user.id,
                Event.kind == NUTRITION_ACTIVITY_KIND,
                Event.occurred_at >= start,
                Event.occurred_at < end,
            )
            .order_by(Event.occurred_at.desc(), Event.id.desc())
        ).scalars()
    )
    out: list[ActivityEntry] = []
    for ev in rows:
        payload = ev.payload if isinstance(ev.payload, dict) else {}
        sport_type = str(payload.get("sport_type", "sport")).strip() or "sport"
        try:
            minutes = int(payload.get("minutes", 0))
        except Exception:
            minutes = 0
        try:
            kcal_burned = int(payload.get("kcal_burned", 0))
        except Exception:
            kcal_burned = 0
        if minutes <= 0:
            continue
        if ev.occurred_at.tzinfo is None:
            ev.occurred_at = ev.occurred_at.replace(tzinfo=UTC)
        out.append(
            ActivityEntry(
                id=ev.id,
                occurred_at=ev.occurred_at,
                sport_type=sport_type,
                minutes=minutes,
                kcal_burned=max(0, kcal_burned),
            )
        )
    return out


def nutrition_dashboard_metrics(
    db: Session,
    user: User,
    *,
    day: date,
) -> dict[str, Any]:
    entries = load_day_entries(db, user, day)
    activities = load_day_activity_entries(db, user, day)
    consumed = sum(e.kcal for e in entries)
    protein_sum = round(sum(e.protein_g for e in entries), 1)
    fat_sum = round(sum(e.fat_g for e in entries), 1)
    carb_sum = round(sum(e.carb_g for e in entries), 1)
    base_target = daily_calorie_target_kcal(user)
    activity_burned = sum(a.kcal_burned for a in activities)
    target = base_target + activity_burned
    remaining = target - consumed
    macro_targets = who_fat_loss_macro_targets(user, target)
    macro_status = {
        "protein": macro_range_status(protein_sum, macro_targets["protein"]),
        "fat": macro_range_status(fat_sum, macro_targets["fat"]),
        "carb": macro_range_status(carb_sum, macro_targets["carb"]),
    }

    weight_entries = load_weight_entries(db, user, days=21)
    latest_weight = weight_entries[-1].weight_kg if weight_entries else user.weight_kg
    if len(weight_entries) >= 2:
        delta = weight_entries[-1].weight_kg - weight_entries[0].weight_kg
    else:
        delta = 0.0

    now = datetime.now(UTC)
    week_start = now - timedelta(days=7)
    week_rows = list(
        db.execute(
            select(Event)
            .where(
                Event.user_id == user.id,
                Event.kind == NUTRITION_ENTRY_KIND,
                Event.occurred_at >= week_start,
            )
        ).scalars()
    )
    by_day: dict[date, int] = {}
    for ev in week_rows:
        if ev.occurred_at.tzinfo is None:
            ev.occurred_at = ev.occurred_at.replace(tzinfo=UTC)
        d = ev.occurred_at.date()
        payload = ev.payload if isinstance(ev.payload, dict) else {}
        try:
            kcal = int(round(float(payload.get("kcal", 0))))
        except Exception:
            kcal = 0
        by_day[d] = by_day.get(d, 0) + max(0, kcal)
    avg_week = round(sum(by_day.values()) / max(1, len(by_day)))

    return {
        "entries": entries,
        "consumed_kcal": consumed,
        "target_kcal": target,
        "base_target_kcal": base_target,
        "activity_kcal_burned": int(activity_burned),
        "remaining_kcal": remaining,
        "consumed_protein_g": protein_sum,
        "consumed_fat_g": fat_sum,
        "consumed_carb_g": carb_sum,
        "macro_targets": macro_targets,
        "macro_status": macro_status,
        "latest_weight_kg": round(float(latest_weight), 1),
        "weight_delta_kg": round(float(delta), 2),
        "avg_kcal_7d": int(avg_week),
        "weight_entries": weight_entries,
        "activity_entries": activities,
    }

