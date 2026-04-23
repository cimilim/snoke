"""Server-rendered Web-UI (Jinja + HTMX).

Authentication for the web layer is a cookie-based session keyed to the
anonymous device id. A visitor without a session is redirected to
/onboarding on first hit.
"""

from __future__ import annotations

import calendar
import math
import json
import secrets
import uuid
from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.probability import _rolling_avg_7d
from app.core.security import create_access_token
from app.db.session import get_db
from app.model import (
    CravingEngine,
    WeaningPlanner,
    build_validation_report,
    set_user_model_config,
    get_user_model_config,
    get_user_runtime_parameters,
)
from app.model.state_space import (
    CravingModel,
    CravingModelParameters,
    dopamine_sensitivity,
    estimate_half_life,
)
from app.model.nudges import choose_nudge
from app.nutrition import (
    NUTRITION_ACTIVITY_KIND,
    NUTRITION_CUSTOM_MEAL_KIND,
    NUTRITION_ENTRY_KIND,
    SPORT_MET,
    WEIGHT_ENTRY_KIND,
    activity_kcal_burned,
    estimate_macros_from_kcal,
    merged_meal_catalog,
    nutrition_dashboard_metrics,
    recommend_meals_for_targets,
)
from app.models import Event, User

_BASE = Path(__file__).parent
templates = Jinja2Templates(directory=_BASE / "templates")

router = APIRouter(tags=["web"], include_in_schema=False)

SESSION_COOKIE = "snoke_device"
_engine = CravingEngine()
_CALENDAR_BLOCK_KIND = "calendar_block"
_CALENDAR_DAY_DONE_KIND = "calendar_day_done"
_SCIENTIFIC_REFERENCES = [
    {
        "title": "Neurobiology of addiction: a neurocircuitry analysis",
        "authors": "Koob GF, Volkow ND (2016)",
        "doi": "10.1016/S2215-0366(16)00104-8",
        "scope": "Drei-Phasen-Architektur (Intoxikation, Withdrawal/Negative Affect, Anticipation/Craving).",
    },
    {
        "title": "The incentive sensitization theory of addiction: some current issues",
        "authors": "Robinson TE, Berridge KC (2008)",
        "doi": "10.1098/rstb.2008.0093",
        "scope": "Cue-getriebene 'Wanting'-Komponente und Incentive Salience.",
    },
    {
        "title": "Addiction motivation reformulated: an affective processing model of negative reinforcement",
        "authors": "Baker TB et al. (2004)",
        "doi": "10.1037/0033-295X.111.1.33",
        "scope": "Negative Reinforcement / Entzugsdruck als Treiber von Rückfall.",
    },
    {
        "title": "Clinical pharmacology of nicotine",
        "authors": "Benowitz NL (2008)",
        "doi": "10.1038/clpt.2008.3",
        "scope": "Pharmakokinetik-Zeitskalen und Halbwertszeitannahmen für Nikotin.",
    },
]


def get_session_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> User | None:
    device_id = request.cookies.get(SESSION_COOKIE)
    if not device_id:
        return None
    return db.get(User, device_id)


def set_session_cookie(response: Response, device_id: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=device_id,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 365,
    )


# ---------- templates / helpers ----------

def _p_color(p: float) -> str:
    if p >= 0.55:
        return "crave-high"
    if p >= 0.35:
        return "crave-mid"
    if p >= 0.2:
        return "crave-low"
    return "crave-none"


def _fmt_time(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.astimezone().strftime("%H:%M")


_WEEKDAY_NAMES = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

_WEEKDAY_LABELS_DE = {
    "monday": "Montag",
    "tuesday": "Dienstag",
    "wednesday": "Mittwoch",
    "thursday": "Donnerstag",
    "friday": "Freitag",
    "saturday": "Samstag",
    "sunday": "Sonntag",
}


def _parse_hhmm(value: str) -> tuple[int, int] | None:
    try:
        hh_s, mm_s = value.strip().split(":")
        hh, mm = int(hh_s), int(mm_s)
    except Exception:
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return hh, mm


def _day_bounds_local(day: date, tzinfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0, 0), tzinfo=tzinfo)
    end = start + timedelta(days=1)
    return start, end


def _calendar_windows_for_day(
    *,
    config: Any,
    day: date,
    tzinfo,
) -> list[tuple[datetime, datetime]]:
    day_name = _WEEKDAY_NAMES[day.weekday()]
    day_cfg = getattr(config.smoking_calendar, day_name)
    if not day_cfg.enabled:
        return []
    start = _parse_hhmm(day_cfg.start)
    end = _parse_hhmm(day_cfg.end)
    if start is None or end is None:
        return []
    s = datetime.combine(day, time(start[0], start[1]), tzinfo=tzinfo)
    e = datetime.combine(day, time(end[0], end[1]), tzinfo=tzinfo)
    if e <= s:
        return []
    return [(s, e)]


def _merge_intervals(
    intervals: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    if not intervals:
        return []
    sorted_int = sorted(intervals, key=lambda it: it[0])
    merged: list[tuple[datetime, datetime]] = [sorted_int[0]]
    for s, e in sorted_int[1:]:
        ms, me = merged[-1]
        if s <= me:
            merged[-1] = (ms, max(me, e))
        else:
            merged.append((s, e))
    return merged


def _subtract_intervals(
    windows: list[tuple[datetime, datetime]],
    blocked: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    if not windows:
        return []
    blocked_m = _merge_intervals(blocked)
    result: list[tuple[datetime, datetime]] = []
    for ws, we in windows:
        cursor = ws
        for bs, be in blocked_m:
            if be <= cursor or bs >= we:
                continue
            if bs > cursor:
                result.append((cursor, min(bs, we)))
            cursor = max(cursor, be)
            if cursor >= we:
                break
        if cursor < we:
            result.append((cursor, we))
    # filter tiny segments
    return [(s, e) for s, e in result if (e - s).total_seconds() >= 60]


def _smoke_windows(
    windows: list[tuple[datetime, datetime]],
    *,
    min_minutes: int = 9,
) -> list[tuple[datetime, datetime]]:
    min_seconds = max(60, int(min_minutes) * 60)
    return [(s, e) for s, e in windows if (e - s).total_seconds() > min_seconds]


def _get_calendar_blocks(
    db: Session,
    user: User,
    *,
    start_utc: datetime,
    end_utc: datetime,
    tzinfo,
) -> list[dict[str, Any]]:
    rows = list(
        db.execute(
            select(Event).where(
                Event.user_id == user.id,
                Event.kind == _CALENDAR_BLOCK_KIND,
                Event.occurred_at < end_utc,
                Event.occurred_at >= start_utc - timedelta(days=2),
            )
        ).scalars()
    )
    blocks: list[dict[str, Any]] = []
    for ev in rows:
        start = ev.occurred_at
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        start_local = start.astimezone(tzinfo)
        payload = ev.payload if isinstance(ev.payload, dict) else {}
        title = str(payload.get("title", "Termin"))
        end_raw = payload.get("end_at")
        end_local = start_local + timedelta(hours=1)
        if isinstance(end_raw, str):
            try:
                parsed = datetime.fromisoformat(end_raw)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                end_local = parsed.astimezone(tzinfo)
            except ValueError:
                pass
        if end_local <= start_local:
            end_local = start_local + timedelta(minutes=30)
        # Overlap filter with requested window in local timeline
        window_start_local = start_utc.astimezone(tzinfo)
        window_end_local = end_utc.astimezone(tzinfo)
        if end_local <= window_start_local or start_local >= window_end_local:
            continue
        blocks.append(
            {
                "id": ev.id,
                "title": title,
                "start": start_local,
                "end": end_local,
            }
        )
    return sorted(blocks, key=lambda b: b["start"])


def _get_done_day_map(
    db: Session,
    user: User,
    *,
    start_utc: datetime,
    end_utc: datetime,
    tzinfo,
) -> dict[date, bool]:
    """Return latest completion state per local day in the interval."""
    rows = list(
        db.execute(
            select(Event).where(
                Event.user_id == user.id,
                Event.kind == _CALENDAR_DAY_DONE_KIND,
                Event.occurred_at >= start_utc - timedelta(days=2),
                Event.occurred_at < end_utc + timedelta(days=2),
            )
        ).scalars()
    )
    latest: dict[date, tuple[datetime, bool]] = {}
    for ev in rows:
        payload = ev.payload if isinstance(ev.payload, dict) else {}
        day_raw = payload.get("day")
        done = bool(payload.get("done", True))
        if not isinstance(day_raw, str):
            continue
        try:
            d = date.fromisoformat(day_raw)
        except ValueError:
            continue
        ts = ev.occurred_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        local_ts = ts.astimezone(tzinfo)
        prev = latest.get(d)
        if prev is None or local_ts > prev[0]:
            latest[d] = (local_ts, done)
    return {d: done for d, (_ts, done) in latest.items()}


def _calendar_windows_for_today(
    *,
    config: Any,
    now: datetime,
) -> list[tuple[datetime, datetime]]:
    """Return allowed smoking windows for today's weekday in local time."""
    local_now = now.astimezone()
    return _calendar_windows_for_day(config=config, day=local_now.date(), tzinfo=local_now.tzinfo)


def _distribute_slots_over_windows(
    *,
    windows: list[tuple[datetime, datetime]],
    slot_count: int,
) -> list[datetime]:
    """Distribute slots evenly over concatenated allowed windows."""
    if slot_count <= 0 or not windows:
        return []
    durations = [max(0.0, (e - s).total_seconds()) for s, e in windows]
    total = sum(durations)
    if total <= 0:
        return []

    slots: list[datetime] = []
    for i in range(slot_count):
        # center points in equal segments over total allowed duration
        target_offset = total * ((i + 0.5) / slot_count)
        acc = 0.0
        for (s, e), dur in zip(windows, durations):
            if target_offset <= acc + dur:
                offset_in_window = target_offset - acc
                slots.append(s + timedelta(seconds=offset_in_window))
                break
            acc += dur
        else:
            slots.append(windows[-1][1])
    return slots


def _calendar_hint_for_today(
    config: Any,
    now: datetime,
    *,
    day: date,
    blocked_count: int,
    free_windows: list[tuple[datetime, datetime]],
) -> str:
    day_name = _WEEKDAY_NAMES[day.weekday()]
    day_cfg = getattr(config.smoking_calendar, day_name)
    if not day_cfg.enabled:
        return f"Plan-Tag ({_WEEKDAY_LABELS_DE[day_name]}) hat keine freigegebenen Rauchfenster."
    if not free_windows:
        return (
            f"Plan-Tag erlaubt: {day_cfg.start}–{day_cfg.end} "
            f"({_WEEKDAY_LABELS_DE[day_name]}), aber keine freie Lücke > 9 Minuten."
        )
    return (
        f"Plan-Tag erlaubt: {day_cfg.start}–{day_cfg.end} "
        f"({_WEEKDAY_LABELS_DE[day_name]}), Termine: {blocked_count}."
    )


def _build_smoking_coach_plan(
    *,
    now: datetime,
    plan_day: date,
    target_today: int,
    smoked_today: int,
    p_now: float,
    allowed_windows: list[tuple[datetime, datetime]],
) -> dict[str, Any]:
    """Return a simple mathematically spaced smoking-reduction plan.

    Idea:
    - define a daily planning window (08:00-22:00 local time),
    - distribute `target_today` slots evenly,
    - suggest "jetzt" only when the next slot is due and budget remains.
    """
    local_now = now.astimezone()
    planning_for_future_day = plan_day > local_now.date()

    if target_today <= 0:
        return {
            "slot_count": 0,
            "remaining": 0,
            "next_slot_at": None,
            "allow_now": False,
            "message": "Heute ist rauchfrei geplant.",
            "slot_times": [],
            "current_window_remaining_min": 0,
        }
    if not allowed_windows:
        return {
            "slot_count": target_today,
            "remaining": max(0, target_today - smoked_today),
            "next_slot_at": None,
            "allow_now": False,
            "message": "Kalender blockiert den Plan-Tag (kein freigegebenes Fenster).",
            "slot_times": [],
            "current_window_remaining_min": 0,
        }

    eligible_windows = _smoke_windows(allowed_windows, min_minutes=9)
    remaining = target_today if planning_for_future_day else max(0, target_today - smoked_today)
    if planning_for_future_day:
        planning_windows = eligible_windows
        slot_count_for_distribution = target_today
    else:
        planning_windows = []
        for ws, we in eligible_windows:
            if we <= local_now:
                continue
            s = max(ws, local_now)
            if (we - s).total_seconds() > 9 * 60:
                planning_windows.append((s, we))
        slot_count_for_distribution = remaining

    slots = _distribute_slots_over_windows(
        windows=planning_windows,
        slot_count=slot_count_for_distribution,
    )
    slot_times = [s.strftime("%H:%M") for s in slots]
    next_slot_at = slots[0] if slots else None

    current_window_remaining = 0
    for ws, we in eligible_windows:
        if ws <= local_now <= we:
            current_window_remaining = int((we - local_now).total_seconds() // 60)
            break

    if planning_for_future_day:
        allow_now = False
        if next_slot_at is None:
            message = "Für morgen sind keine freien Rauch-Slots verfügbar."
        else:
            message = "Plan für morgen erstellt. Halte dich an diese Uhrzeiten."
    elif remaining <= 0:
        allow_now = False
        message = "Tagesbudget erreicht. Wenn möglich jetzt keine weitere Zigarette."
    elif not slots:
        allow_now = False
        message = (
            "Heute sind keine weiteren freien Rauch-Slots > 9 Minuten verfügbar. "
            "Wenn möglich bis morgen warten."
        )
    elif current_window_remaining >= 9:
        allow_now = True
        message = (
            "Freies Zeitfenster >= 9 Minuten. Wenn du willst, kannst du jetzt eine rauchen."
        )
    else:
        allow_now = False
        if next_slot_at is None:
            message = (
                "Heute kein weiteres geplantes Fenster. "
                "Wenn möglich bis morgen warten."
            )
        else:
            wait_mins = max(1, int((next_slot_at - local_now).total_seconds() // 60))
            message = f"Noch warten: nächstes geplantes Fenster in ca. {wait_mins} Minuten."

    return {
        "slot_count": target_today,
        "remaining": remaining,
        "next_slot_at": next_slot_at,
        "allow_now": allow_now,
        "message": message,
        "slot_times": slot_times,
        "current_window_remaining_min": max(0, current_window_remaining),
    }


def _half_life_hours(rate: float) -> float | None:
    """Return half-life in hours for first-order decay x*exp(-rate*t)."""
    if rate <= 0:
        return None
    return math.log(2.0) / rate


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _sigmoid_float(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-float(x)))


def _planner_from_config(cfg: Any) -> WeaningPlanner:
    return WeaningPlanner(
        baseline_weight=float(cfg.planner.baseline_weight),
        rolling_weight=float(cfg.planner.rolling_weight),
    )


def _build_dashboard_ctx(db: Session, user: User) -> dict[str, Any]:
    now = datetime.now(UTC)
    local_now = now.astimezone()
    planning_day = local_now.date()
    params = get_user_runtime_parameters(db, user)
    cfg = get_user_model_config(db, user)
    result = _engine.compute_with_parameters(db, user, model_parameters=params, now=now)
    avg, smoked_today = _rolling_avg_7d(db, user, now)
    status = _planner_from_config(cfg).status(
        rolling_avg_7d=avg,
        smoked_today=smoked_today,
        weaning_rate_pct=user.weaning_rate_pct,
        baseline=user.baseline_cigarettes_per_day,
    )
    plan_start_local, plan_end_local = _day_bounds_local(planning_day, local_now.tzinfo)
    blocks_plan_day = _get_calendar_blocks(
        db,
        user,
        start_utc=plan_start_local.astimezone(UTC),
        end_utc=plan_end_local.astimezone(UTC),
        tzinfo=local_now.tzinfo,
    )
    blocked_intervals = [(b["start"], b["end"]) for b in blocks_plan_day]
    allowed_windows = _calendar_windows_for_day(
        config=cfg,
        day=planning_day,
        tzinfo=local_now.tzinfo,
    )
    free_windows = _subtract_intervals(allowed_windows, blocked_intervals)
    smoke_free_windows = _smoke_windows(free_windows, min_minutes=9)

    coach_plan = _build_smoking_coach_plan(
        now=now,
        plan_day=planning_day,
        target_today=status.target_today,
        smoked_today=status.smoked_today,
        p_now=result.p_now,
        allowed_windows=smoke_free_windows,
    )
    nudge = choose_nudge(result, status)
    last_activity = db.execute(
        select(Event)
        .where(Event.user_id == user.id, Event.kind == "nutrition_activity")
        .order_by(Event.occurred_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    activity_hint: dict[str, Any] | None = None
    if last_activity is not None and isinstance(last_activity.payload, dict):
        payload = last_activity.payload
        sport = str(payload.get("sport_type", "sport")).strip() or "sport"
        try:
            minutes = int(payload.get("minutes", 0))
        except Exception:
            minutes = 0
        try:
            burned = int(payload.get("kcal_burned", 0))
        except Exception:
            burned = 0
        action = _engine._event_action(last_activity) or {"dopamine_boost": 0.0, "withdrawal_relief": 0.0}
        activity_hint = {
            "sport": sport,
            "minutes": minutes,
            "kcal_burned": burned,
            "dopamine_boost": round(float(action.get("dopamine_boost", 0.0)), 3),
            "withdrawal_relief": round(float(action.get("withdrawal_relief", 0.0)), 3),
            "at": last_activity.occurred_at,
        }
    recent = list(
        db.execute(
            select(Event)
            .where(Event.user_id == user.id, Event.kind.in_(("cigarette", "craving")))
            .order_by(Event.occurred_at.desc())
            .limit(8)
        ).scalars()
    )
    return {
        "user": user,
        "today_iso": local_now.date().isoformat(),
        "planning_day_iso": planning_day.isoformat(),
        "p_now": result.p_now,
        "p_low": result.p_low,
        "p_high": result.p_high,
        "confidence_level": result.confidence_level,
        "p_next_hour": result.p_next_hour,
        "p_color": _p_color(result.p_now),
        "next_peak": _fmt_time(result.next_peak_at),
        "bucket_key": result.bucket_key,
        "rule_reasons": result.rule_reasons,
        "top_triggers": result.top_triggers,
        "status": status,
        "coach_plan": coach_plan,
        "coach_plan_day_label": planning_day.strftime("%A, %d.%m."),
        "calendar_hint": _calendar_hint_for_today(
            cfg,
            now,
            day=planning_day,
            blocked_count=len(blocks_plan_day),
            free_windows=smoke_free_windows,
        ),
        "nudge": nudge,
        "activity_hint": activity_hint,
        "recent": recent,
        "fmt_time": _fmt_time,
    }


def _build_nutrition_ctx(db: Session, user: User, day: date) -> dict[str, Any]:
    meals = merged_meal_catalog(db, user)
    metrics = nutrition_dashboard_metrics(db, user, day=day)
    healthy_meals = [m for m in meals if m.is_healthy_alternative][:12]
    meal_recommendations = recommend_meals_for_targets(
        meals=meals,
        consumed_kcal=metrics["consumed_kcal"],
        target_kcal=metrics["target_kcal"],
        consumed_protein_g=metrics["consumed_protein_g"],
        consumed_fat_g=metrics["consumed_fat_g"],
        consumed_carb_g=metrics["consumed_carb_g"],
        macro_targets=metrics["macro_targets"],
        limit=3,
    )
    weight_series = [
        {"at": w.occurred_at.astimezone().strftime("%d.%m."), "weight": round(w.weight_kg, 1)}
        for w in metrics["weight_entries"]
    ]
    return {
        "user": user,
        "selected_day": day.isoformat(),
        "meal_catalog": meals,
        "entries": metrics["entries"],
        "consumed_kcal": metrics["consumed_kcal"],
        "target_kcal": metrics["target_kcal"],
        "base_target_kcal": metrics["base_target_kcal"],
        "activity_kcal_burned": metrics["activity_kcal_burned"],
        "remaining_kcal": metrics["remaining_kcal"],
        "consumed_protein_g": metrics["consumed_protein_g"],
        "consumed_fat_g": metrics["consumed_fat_g"],
        "consumed_carb_g": metrics["consumed_carb_g"],
        "macro_targets": metrics["macro_targets"],
        "macro_status": metrics["macro_status"],
        "latest_weight_kg": metrics["latest_weight_kg"],
        "weight_delta_kg": metrics["weight_delta_kg"],
        "avg_kcal_7d": metrics["avg_kcal_7d"],
        "activity_entries": metrics["activity_entries"],
        "sport_types": sorted(SPORT_MET.keys()),
        "healthy_meals": healthy_meals,
        "meal_recommendations": meal_recommendations,
        "weight_series_json": json.dumps(weight_series, ensure_ascii=False),
    }


# ---------- pages ----------

@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
) -> HTMLResponse:
    if user is None:
        return RedirectResponse("/onboarding", status_code=303)
    ctx = _build_dashboard_ctx(db, user)
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@router.get("/onboarding", response_class=HTMLResponse)
def onboarding(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "onboarding.html", {})


@router.post("/onboarding")
def onboarding_submit(
    db: Annotated[Session, Depends(get_db)],
    baseline_cigarettes_per_day: Annotated[int, Form(ge=0, le=80)],
    weaning_rate_pct: Annotated[int, Form(ge=0, le=50)] = 5,
    weight_kg: Annotated[float, Form(ge=35.0, le=250.0)] = 75.0,
    height_cm: Annotated[float, Form(ge=120.0, le=230.0)] = 175.0,
    body_fat: Annotated[float, Form(ge=0.05, le=0.60)] = 0.20,
    age_years: Annotated[int, Form(ge=14, le=110)] = 30,
    weekly_weight_loss_kg: Annotated[float, Form(ge=0.0, le=2.0)] = 0.40,
) -> Response:
    device_id = f"dev-{uuid.uuid4().hex[:16]}"
    user = User(
        id=device_id,
        baseline_cigarettes_per_day=baseline_cigarettes_per_day,
        weaning_rate_pct=weaning_rate_pct,
        weight_kg=weight_kg,
        height_cm=height_cm,
        body_fat=body_fat,
        age_years=age_years,
        weekly_weight_loss_kg=weekly_weight_loss_kg,
    )
    db.add(user)
    db.commit()

    response = RedirectResponse("/", status_code=303)
    set_session_cookie(response, device_id)
    return response


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
) -> HTMLResponse:
    if user is None:
        return RedirectResponse("/onboarding", status_code=303)
    token = create_access_token(subject=user.id)
    cfg = get_user_model_config(db, user)
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "api_token": token,
            "rolling_weight_pct": int(round(float(cfg.planner.rolling_weight) * 100.0)),
        },
    )


@router.get("/nutrition", response_class=HTMLResponse)
def nutrition_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
) -> HTMLResponse:
    if user is None:
        return RedirectResponse("/onboarding", status_code=303)
    day_raw = request.query_params.get("day", "")
    local_today = datetime.now().astimezone().date()
    selected_day = local_today
    if day_raw:
        try:
            selected_day = date.fromisoformat(day_raw)
        except ValueError:
            selected_day = local_today
    ctx = _build_nutrition_ctx(db, user, selected_day)
    return templates.TemplateResponse(request, "nutrition.html", ctx)


@router.post("/nutrition/entry/add")
async def nutrition_entry_add(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
) -> Response:
    if user is None:
        raise HTTPException(401)
    form = await request.form()
    selected_day_raw = str(form.get("selected_day", "")).strip()
    meal_id = str(form.get("meal_id", "")).strip()
    meal_name_manual = str(form.get("meal_name", "")).strip()
    try:
        portion = float(str(form.get("portion", "1.0")))
    except Exception:
        portion = 1.0
    portion = max(0.1, min(5.0, portion))

    local_today = datetime.now().astimezone().date()
    try:
        selected_day = date.fromisoformat(selected_day_raw) if selected_day_raw else local_today
    except ValueError:
        selected_day = local_today

    catalog = merged_meal_catalog(db, user)
    meal = next((m for m in catalog if m.id == meal_id), None)
    if meal is None:
        try:
            kcal_manual = int(round(float(str(form.get("kcal", "0")).strip())))
        except Exception:
            kcal_manual = 0
        if kcal_manual <= 0:
            raise HTTPException(400, "Gericht oder kcal erforderlich")
        meal_name = meal_name_manual or "Manuelle Mahlzeit"
        base_kcal = kcal_manual
        source = "manual"
        try:
            base_protein = float(str(form.get("protein_g", "")).strip() or "0")
        except Exception:
            base_protein = 0.0
        try:
            base_fat = float(str(form.get("fat_g", "")).strip() or "0")
        except Exception:
            base_fat = 0.0
        try:
            base_carb = float(str(form.get("carb_g", "")).strip() or "0")
        except Exception:
            base_carb = 0.0
        if base_protein <= 0.0 and base_fat <= 0.0 and base_carb <= 0.0:
            base_protein, base_fat, base_carb = estimate_macros_from_kcal(base_kcal)
    else:
        meal_name = meal.name
        base_kcal = int(meal.kcal_per_portion)
        source = meal.source
        base_protein = float(meal.protein_g)
        base_fat = float(meal.fat_g)
        base_carb = float(meal.carb_g)

    local_tz = datetime.now().astimezone().tzinfo
    occur_local = datetime.combine(selected_day, time(12, 0), tzinfo=local_tz)
    if selected_day == local_today:
        occur_local = datetime.now().astimezone()
    total_kcal = max(1, int(round(base_kcal * portion)))
    total_protein = round(max(0.0, base_protein * portion), 1)
    total_fat = round(max(0.0, base_fat * portion), 1)
    total_carb = round(max(0.0, base_carb * portion), 1)

    db.add(
        Event(
            user_id=user.id,
            client_uuid=f"nut-{uuid.uuid4().hex[:16]}",
            kind=NUTRITION_ENTRY_KIND,
            occurred_at=occur_local.astimezone(UTC),
            payload={
                "meal_name": meal_name,
                "portion": portion,
                "kcal": total_kcal,
                "base_kcal": base_kcal,
                "protein_g": total_protein,
                "fat_g": total_fat,
                "carb_g": total_carb,
                "source": source,
                "meal_id": meal_id,
            },
        )
    )
    db.commit()
    return RedirectResponse(f"/nutrition?day={selected_day.isoformat()}", status_code=303)


@router.post("/nutrition/entry/delete")
async def nutrition_entry_delete(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
) -> Response:
    if user is None:
        raise HTTPException(401)
    form = await request.form()
    selected_day = str(form.get("selected_day", "")).strip()
    try:
        event_id = int(str(form.get("event_id", "")).strip())
    except ValueError:
        raise HTTPException(400, "Ungültige Eintrag-ID")
    ev = db.get(Event, event_id)
    if ev is None or ev.user_id != user.id or ev.kind != NUTRITION_ENTRY_KIND:
        raise HTTPException(404, "Eintrag nicht gefunden")
    db.delete(ev)
    db.commit()
    if selected_day:
        return RedirectResponse(f"/nutrition?day={selected_day}", status_code=303)
    return RedirectResponse("/nutrition", status_code=303)


@router.post("/nutrition/weight/add")
async def nutrition_weight_add(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
) -> Response:
    if user is None:
        raise HTTPException(401)
    form = await request.form()
    selected_day_raw = str(form.get("selected_day", "")).strip()
    try:
        weight_kg = float(str(form.get("weight_kg", "")).strip())
    except Exception:
        raise HTTPException(400, "Ungültiges Gewicht")
    if not (30.0 <= weight_kg <= 300.0):
        raise HTTPException(400, "Gewicht außerhalb Bereich")

    local_today = datetime.now().astimezone().date()
    try:
        selected_day = date.fromisoformat(selected_day_raw) if selected_day_raw else local_today
    except ValueError:
        selected_day = local_today
    local_tz = datetime.now().astimezone().tzinfo
    occur_local = datetime.combine(selected_day, time(8, 0), tzinfo=local_tz)
    if selected_day == local_today:
        occur_local = datetime.now().astimezone()

    db.add(
        Event(
            user_id=user.id,
            client_uuid=f"wgt-{uuid.uuid4().hex[:16]}",
            kind=WEIGHT_ENTRY_KIND,
            occurred_at=occur_local.astimezone(UTC),
            payload={"weight_kg": round(weight_kg, 2)},
        )
    )
    db.commit()
    return RedirectResponse(f"/nutrition?day={selected_day.isoformat()}", status_code=303)


@router.post("/nutrition/activity/add")
async def nutrition_activity_add(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
) -> Response:
    if user is None:
        raise HTTPException(401)
    form = await request.form()
    selected_day_raw = str(form.get("selected_day", "")).strip()
    sport_type = str(form.get("sport_type", "gehen")).strip().lower()
    if sport_type not in SPORT_MET:
        sport_type = "gehen"
    try:
        minutes = int(str(form.get("minutes", "0")).strip())
    except Exception:
        raise HTTPException(400, "Ungültige Minuten")
    if minutes <= 0 or minutes > 600:
        raise HTTPException(400, "Minuten außerhalb Bereich")

    local_today = datetime.now().astimezone().date()
    try:
        selected_day = date.fromisoformat(selected_day_raw) if selected_day_raw else local_today
    except ValueError:
        selected_day = local_today

    local_tz = datetime.now().astimezone().tzinfo
    occur_local = datetime.combine(selected_day, time(18, 0), tzinfo=local_tz)
    if selected_day == local_today:
        occur_local = datetime.now().astimezone()

    burned = activity_kcal_burned(user.weight_kg, sport_type=sport_type, minutes=minutes)
    db.add(
        Event(
            user_id=user.id,
            client_uuid=f"act-{uuid.uuid4().hex[:16]}",
            kind=NUTRITION_ACTIVITY_KIND,
            occurred_at=occur_local.astimezone(UTC),
            payload={
                "sport_type": sport_type,
                "minutes": minutes,
                "kcal_burned": burned,
            },
        )
    )
    db.commit()
    return RedirectResponse(f"/nutrition?day={selected_day.isoformat()}", status_code=303)


@router.post("/nutrition/custom-meal/add")
async def nutrition_custom_meal_add(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
) -> Response:
    if user is None:
        raise HTTPException(401)
    form = await request.form()
    selected_day = str(form.get("selected_day", "")).strip()
    name = str(form.get("name", "")).strip()
    portion_label = str(form.get("portion_label", "1 Portion")).strip() or "1 Portion"
    category = str(form.get("category", "Custom")).strip() or "Custom"
    healthy_raw = str(form.get("is_healthy_alternative", "")).strip().lower()
    is_healthy = healthy_raw in {"1", "on", "true", "yes"}
    try:
        kcal_per_portion = int(round(float(str(form.get("kcal_per_portion", "")).strip())))
    except Exception:
        raise HTTPException(400, "Ungültige kcal")
    try:
        protein_g = float(str(form.get("protein_g", "")).strip() or "0")
    except Exception:
        protein_g = 0.0
    try:
        fat_g = float(str(form.get("fat_g", "")).strip() or "0")
    except Exception:
        fat_g = 0.0
    try:
        carb_g = float(str(form.get("carb_g", "")).strip() or "0")
    except Exception:
        carb_g = 0.0
    if not name or kcal_per_portion <= 0:
        raise HTTPException(400, "Name und kcal erforderlich")
    if protein_g <= 0.0 and fat_g <= 0.0 and carb_g <= 0.0:
        protein_g, fat_g, carb_g = estimate_macros_from_kcal(kcal_per_portion)

    db.add(
        Event(
            user_id=user.id,
            client_uuid=f"meal-{uuid.uuid4().hex[:16]}",
            kind=NUTRITION_CUSTOM_MEAL_KIND,
            occurred_at=datetime.now(UTC),
            payload={
                "name": name,
                "kcal_per_portion": kcal_per_portion,
                "portion_label": portion_label,
                "category": category,
                "protein_g": round(max(0.0, protein_g), 1),
                "fat_g": round(max(0.0, fat_g), 1),
                "carb_g": round(max(0.0, carb_g), 1),
                "is_healthy_alternative": is_healthy,
            },
        )
    )
    db.commit()
    if selected_day:
        return RedirectResponse(f"/nutrition?day={selected_day}", status_code=303)
    return RedirectResponse("/nutrition", status_code=303)


@router.get("/calendar", response_class=HTMLResponse)
def calendar_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
) -> HTMLResponse:
    if user is None:
        return RedirectResponse("/onboarding", status_code=303)
    now = datetime.now(UTC)
    local_now = now.astimezone()
    cfg = get_user_model_config(db, user)
    days: list[dict[str, str | bool]] = []
    for name in _WEEKDAY_NAMES:
        d = getattr(cfg.smoking_calendar, name)
        days.append(
            {
                "name": name,
                "label": _WEEKDAY_LABELS_DE[name],
                "enabled": bool(d.enabled),
                "start": str(d.start),
                "end": str(d.end),
            }
        )

    # Month-view event buckets
    month_start_local = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    _, days_in_month = calendar.monthrange(month_start_local.year, month_start_local.month)
    month_end_local = month_start_local + timedelta(days=days_in_month)
    month_blocks = _get_calendar_blocks(
        db,
        user,
        start_utc=month_start_local.astimezone(UTC),
        end_utc=month_end_local.astimezone(UTC),
        tzinfo=local_now.tzinfo,
    )
    done_day_map = _get_done_day_map(
        db,
        user,
        start_utc=month_start_local.astimezone(UTC),
        end_utc=month_end_local.astimezone(UTC),
        tzinfo=local_now.tzinfo,
    )
    day_to_blocks: dict[date, list[dict[str, Any]]] = {}
    for b in month_blocks:
        d = b["start"].date()
        day_to_blocks.setdefault(d, []).append(b)

    selected_day_raw = request.query_params.get("day")
    selected_day = local_now.date()
    if selected_day_raw:
        try:
            selected_day = date.fromisoformat(selected_day_raw)
        except ValueError:
            selected_day = local_now.date()
    selected_start_local, selected_end_local = _day_bounds_local(selected_day, local_now.tzinfo)
    selected_blocks = _get_calendar_blocks(
        db,
        user,
        start_utc=selected_start_local.astimezone(UTC),
        end_utc=selected_end_local.astimezone(UTC),
        tzinfo=local_now.tzinfo,
    )
    selected_allowed = _calendar_windows_for_day(
        config=cfg, day=selected_day, tzinfo=local_now.tzinfo
    )
    selected_free = _subtract_intervals(
        selected_allowed, [(b["start"], b["end"]) for b in selected_blocks]
    )
    selected_free = _smoke_windows(selected_free, min_minutes=9)

    # Build month grid (Monday-first).
    week_rows: list[list[dict[str, Any]]] = []
    first_weekday = month_start_local.weekday()  # Monday=0
    cursor_day = month_start_local.date() - timedelta(days=first_weekday)
    while True:
        row: list[dict[str, Any]] = []
        for _ in range(7):
            in_month = cursor_day.month == month_start_local.month
            blocks_count = len(day_to_blocks.get(cursor_day, []))
            row.append(
                {
                    "date": cursor_day.isoformat(),
                    "day": cursor_day.day,
                    "in_month": in_month,
                    "is_today": cursor_day == local_now.date(),
                    "is_selected": cursor_day == selected_day,
                    "blocks_count": blocks_count,
                    "is_done": bool(done_day_map.get(cursor_day, False)),
                }
            )
            cursor_day += timedelta(days=1)
        week_rows.append(row)
        if cursor_day.month != month_start_local.month and cursor_day.weekday() == 0:
            break

    return templates.TemplateResponse(
        request,
        "calendar.html",
        {
            "user": user,
            "days": days,
            "month_label": month_start_local.strftime("%B %Y"),
            "week_rows": week_rows,
            "selected_day": selected_day.isoformat(),
            "selected_day_done": bool(done_day_map.get(selected_day, False)),
            "selected_blocks": selected_blocks,
            "selected_free_windows": selected_free,
        },
    )


@router.post("/calendar")
async def calendar_save(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
) -> Response:
    if user is None:
        raise HTTPException(401)
    cfg = get_user_model_config(db, user)
    form = await request.form()
    for name in _WEEKDAY_NAMES:
        day = getattr(cfg.smoking_calendar, name)
        day.enabled = f"{name}_enabled" in form
        start = str(form.get(f"{name}_start", day.start))
        end = str(form.get(f"{name}_end", day.end))
        if _parse_hhmm(start) is not None and _parse_hhmm(end) is not None:
            day.start = start
            day.end = end
    set_user_model_config(db, user, cfg)
    return RedirectResponse("/calendar", status_code=303)


@router.post("/calendar/appointments/add")
async def calendar_appointment_add(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
) -> Response:
    if user is None:
        raise HTTPException(401)
    form = await request.form()
    date_raw = str(form.get("date", "")).strip()
    start_time_raw = str(form.get("start_time", "")).strip()
    end_time_raw = str(form.get("end_time", "")).strip()
    # Backward compatibility: keep old datetime-local names if present.
    start_raw = str(form.get("start_at", "")).strip()
    end_raw = str(form.get("end_at", "")).strip()
    title = str(form.get("title", "Termin")).strip() or "Termin"
    selected_day = str(form.get("selected_day", "")).strip()
    return_to = str(form.get("return_to", "")).strip()

    local_tz = datetime.now().astimezone().tzinfo

    if date_raw and start_time_raw and end_time_raw:
        try:
            d = date.fromisoformat(date_raw)
            st = _parse_hhmm(start_time_raw)
            et = _parse_hhmm(end_time_raw)
            if st is None or et is None:
                raise ValueError("invalid time")
            start_local = datetime.combine(d, time(st[0], st[1]), tzinfo=local_tz)
            end_local = datetime.combine(d, time(et[0], et[1]), tzinfo=local_tz)
        except Exception:
            raise HTTPException(400, "Ungültiges Datum/Uhrzeit")
    else:
        # Fallback path for old datetime-local payloads.
        try:
            start_local = datetime.fromisoformat(start_raw).replace(tzinfo=local_tz)
            end_local = datetime.fromisoformat(end_raw).replace(tzinfo=local_tz)
        except Exception:
            raise HTTPException(400, "Ungültiges Datum/Uhrzeit")
    if end_local <= start_local:
        raise HTTPException(400, "Ende muss nach Start liegen")

    db.add(
        Event(
            user_id=user.id,
            client_uuid=f"cal-{uuid.uuid4().hex[:16]}",
            kind=_CALENDAR_BLOCK_KIND,
            occurred_at=start_local.astimezone(UTC),
            payload={"title": title, "end_at": end_local.astimezone(UTC).isoformat()},
        )
    )
    db.commit()
    if return_to in {"/", "/calendar"}:
        redirect = return_to
        if redirect == "/calendar" and selected_day:
            redirect += f"?day={selected_day}"
    else:
        redirect = "/calendar"
        if selected_day:
            redirect += f"?day={selected_day}"
    return RedirectResponse(redirect, status_code=303)


@router.post("/calendar/appointments/delete")
async def calendar_appointment_delete(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
) -> Response:
    if user is None:
        raise HTTPException(401)
    form = await request.form()
    selected_day = str(form.get("selected_day", "")).strip()
    try:
        event_id = int(str(form.get("event_id", "")))
    except ValueError:
        raise HTTPException(400, "Ungültige Termin-ID")
    ev = db.get(Event, event_id)
    if ev is None or ev.user_id != user.id or ev.kind != _CALENDAR_BLOCK_KIND:
        raise HTTPException(404, "Termin nicht gefunden")
    db.delete(ev)
    db.commit()
    redirect = "/calendar"
    if selected_day:
        redirect += f"?day={selected_day}"
    return RedirectResponse(redirect, status_code=303)


@router.post("/calendar/day-toggle")
async def calendar_day_toggle(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
) -> Response:
    if user is None:
        raise HTTPException(401)
    form = await request.form()
    selected_day = str(form.get("selected_day", "")).strip()
    done_value = str(form.get("done", "")).strip()
    try:
        d = date.fromisoformat(selected_day)
    except ValueError:
        raise HTTPException(400, "Ungültiger Tag")
    done = done_value in {"1", "true", "on", "yes"}
    local_tz = datetime.now().astimezone().tzinfo
    mark_time_local = datetime.combine(d, time(12, 0), tzinfo=local_tz)
    db.add(
        Event(
            user_id=user.id,
            client_uuid=f"done-{uuid.uuid4().hex[:16]}",
            kind=_CALENDAR_DAY_DONE_KIND,
            occurred_at=mark_time_local.astimezone(UTC),
            payload={"day": d.isoformat(), "done": done},
        )
    )
    db.commit()
    return RedirectResponse(f"/calendar?day={d.isoformat()}", status_code=303)


@router.post("/settings")
def settings_save(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
    baseline_cigarettes_per_day: Annotated[int, Form(ge=0, le=80)],
    weaning_rate_pct: Annotated[int, Form(ge=0, le=50)],
    rolling_weight_pct: Annotated[float, Form(ge=0.0, le=100.0)],
    weight_kg: Annotated[float, Form(ge=35.0, le=250.0)],
    height_cm: Annotated[float, Form(ge=120.0, le=230.0)],
    body_fat: Annotated[float, Form(ge=0.05, le=0.60)],
    age_years: Annotated[int, Form(ge=14, le=110)],
    weekly_weight_loss_kg: Annotated[float, Form(ge=0.0, le=2.0)],
) -> Response:
    if user is None:
        raise HTTPException(401)
    user.baseline_cigarettes_per_day = baseline_cigarettes_per_day
    user.weaning_rate_pct = weaning_rate_pct
    user.weight_kg = weight_kg
    user.height_cm = height_cm
    user.body_fat = body_fat
    user.age_years = age_years
    user.weekly_weight_loss_kg = weekly_weight_loss_kg
    cfg = get_user_model_config(db, user)
    rolling = max(0.0, min(1.0, float(rolling_weight_pct) / 100.0))
    cfg.planner.rolling_weight = rolling
    cfg.planner.baseline_weight = 1.0 - rolling
    set_user_model_config(db, user, cfg)
    db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/hard-reset")
async def settings_hard_reset(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
) -> Response:
    if user is None:
        raise HTTPException(401)
    form = await request.form()
    confirmation_text = str(form.get("confirmation_text", "")).strip()
    if confirmation_text != "RESET":
        raise HTTPException(400, "Bitte zur Bestätigung exakt RESET eingeben.")

    db.execute(delete(Event).where(Event.user_id == user.id))
    user.baseline_cigarettes_per_day = 15
    user.weaning_rate_pct = 5
    user.weight_kg = 75.0
    user.height_cm = 175.0
    user.body_fat = 0.20
    user.age_years = 30
    user.weekly_weight_loss_kg = 0.40
    db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.get("/progress", response_class=HTMLResponse)
def progress_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
) -> HTMLResponse:
    if user is None:
        return RedirectResponse("/onboarding", status_code=303)
    now = datetime.now(UTC)
    start = (now - timedelta(days=13)).date()
    window_start = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
    events = list(
        db.execute(
            select(Event).where(
                Event.user_id == user.id,
                Event.occurred_at >= window_start,
                Event.kind.in_(("cigarette", "craving")),
            )
        ).scalars()
    )
    by_day: dict[date, dict[str, int]] = {}
    for i in range(14):
        d = start + timedelta(days=i)
        by_day[d] = {"cigarettes": 0, "cravings": 0, "resisted": 0}
    for ev in events:
        d = ev.occurred_at.astimezone(UTC).date()
        if d not in by_day:
            continue
        if ev.kind == "cigarette":
            by_day[d]["cigarettes"] += 1
        elif ev.kind == "craving":
            by_day[d]["cravings"] += 1
            if isinstance(ev.payload, dict) and ev.payload.get("resisted"):
                by_day[d]["resisted"] += 1
    days = [{"day": d, **v} for d, v in sorted(by_day.items())]
    max_cigs = max((d["cigarettes"] for d in days), default=1) or 1

    params = get_user_runtime_parameters(db, user)
    result = _engine.compute_with_parameters(db, user, model_parameters=params, now=now)
    state_trace = _state_trace_for_plot(
        db, user, now=now, lookback_days=1, model_parameters=params
    )
    return templates.TemplateResponse(
        request,
        "progress.html",
        {
            "user": user,
            "days": days,
            "max_cigs": max_cigs,
            "top_triggers": result.top_triggers,
            "state_trace_json": json.dumps(state_trace, ensure_ascii=False),
        },
    )


@router.get("/how-it-works", response_class=HTMLResponse)
def how_it_works_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
) -> HTMLResponse:
    if user is None:
        return RedirectResponse("/onboarding", status_code=303)
    now = datetime.now(UTC)
    params = get_user_runtime_parameters(db, user)
    result = _engine.compute_with_parameters(db, user, model_parameters=params, now=now)
    cfg = get_user_model_config(db, user)
    params_dict = asdict(params)
    events = _engine._load_events(db, user, now)  # noqa: SLF001 - explainability view
    latest_context = _engine._latest_context(events, now)  # noqa: SLF001 - explainability view
    stress_proxy, cue_proxy = _engine._context_proxies(latest_context)  # noqa: SLF001
    d_now = float(result.dopamine)
    w_now = float(result.withdrawal)
    h_now = float(result.habit)
    z_terms = {
        "dopamine": -float(params.w_D) * d_now,
        "withdrawal": float(params.w_W) * w_now,
        "habit": float(params.w_H) * h_now,
        "stress": float(params.w_stress) * stress_proxy,
        "cue": float(params.w_cue) * cue_proxy,
        "bias": float(params.bias),
    }
    z_now = sum(z_terms.values())
    p_model_now = _sigmoid_float(z_now)
    rule_factor = (float(result.p_now) / p_model_now) if p_model_now > 1e-6 else None
    dt_seconds = max(10, int(cfg.simulation.dt_seconds))
    dt_hours = dt_seconds / 3600.0
    decay_factors = {
        "nicotine": math.exp(-float(params.lambda_nicotine) * dt_hours),
        "dopamine_fast": math.exp(-float(params.k_dopamine_fast) * dt_hours),
        "dopamine_slow": math.exp(-float(params.k_dopamine_slow) * dt_hours),
        "withdrawal": math.exp(-float(params.decay_withdrawal) * dt_hours),
        "habit": math.exp(-float(params.k_habit_decay) * dt_hours),
    }
    weight_kg = max(35.0, float(params.weight_kg))
    body_fat = _clamp01(float(params.body_fat))
    age_years = max(14, int(params.age_years))
    estimated_t_half_h = estimate_half_life(weight_kg=weight_kg, body_fat=body_fat)
    sens = dopamine_sensitivity(body_fat=body_fat, age_years=age_years)
    nicotine_conc = float(params.cigarette_dose_mg) / (2.5 * weight_kg)
    nicotine_receptor = nicotine_conc / (nicotine_conc + float(params.nicotine_kd))
    nicotine_effect_dt = nicotine_receptor * decay_factors["nicotine"]
    personalized = {
        "alpha_nic_fast": float(params.alpha_nicotine_fast) * sens,
        "alpha_nic_slow": float(params.alpha_nicotine_slow) * sens,
        "k_withdrawal": float(params.k_withdrawal) * (weight_kg / 70.0) * (1.0 + body_fat),
        "habit_learning": float(params.habit_learning) * (1.0 + 0.2 * body_fat),
    }
    half_lives = {
        "nicotine_h": _half_life_hours(params.lambda_nicotine),
        "dopamine_fast_h": _half_life_hours(params.k_dopamine_fast),
        "dopamine_slow_h": _half_life_hours(params.k_dopamine_slow),
        "withdrawal_h": _half_life_hours(params.decay_withdrawal),
        "habit_h": _half_life_hours(params.k_habit_decay),
    }
    validation_report = build_validation_report(
        db,
        user,
        _engine,
        params,
        now=now,
        max_samples=60,
    )
    validation_dict: dict[str, Any] | None = None
    if validation_report is not None:
        validation_dict = {
            "model": asdict(validation_report.model),
            "baselines": {k: asdict(v) for k, v in validation_report.baselines.items()},
            "ablations": {k: asdict(v) for k, v in validation_report.ablations.items()},
        }
    return templates.TemplateResponse(
        request,
        "how_it_works.html",
        {
            "user": user,
            "container_class": "max-w-[1400px]",
            "as_of": now,
            "result": result,
            "params": params,
            "params_dict_json": json.dumps(params_dict, ensure_ascii=False, indent=2),
            "config_json": json.dumps(cfg.model_dump(mode="json"), ensure_ascii=False, indent=2),
            "half_lives": half_lives,
            "dt_seconds": dt_seconds,
            "dt_hours": dt_hours,
            "decay_factors": decay_factors,
            "stress_proxy": stress_proxy,
            "cue_proxy": cue_proxy,
            "readout_terms": z_terms,
            "z_now": z_now,
            "p_model_now": p_model_now,
            "rule_factor_now": rule_factor,
            "validation_report": validation_dict,
            "scientific_refs": _SCIENTIFIC_REFERENCES,
            "personalized_values": {
                "weight_kg": weight_kg,
                "body_fat": body_fat,
                "age_years": age_years,
                "estimated_t_half_h": estimated_t_half_h,
                "sensitivity": sens,
                "nicotine_conc": nicotine_conc,
                "nicotine_receptor": nicotine_receptor,
                "nicotine_effect_dt": nicotine_effect_dt,
                **personalized,
            },
        },
    )


# ---------- HTMX fragments (actions) ----------

@router.post("/web/log/cigarette", response_class=HTMLResponse)
def log_cigarette(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
    trigger: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    if user is None:
        raise HTTPException(401)
    payload: dict[str, Any] = {}
    if trigger:
        payload["trigger"] = trigger
    db.add(Event(
        user_id=user.id,
        client_uuid=f"web-{secrets.token_hex(6)}",
        kind="cigarette",
        occurred_at=datetime.now(UTC),
        payload=payload,
    ))
    db.commit()
    ctx = _build_dashboard_ctx(db, user)
    return templates.TemplateResponse(request, "_dashboard_main.html", ctx)


@router.post("/web/log/craving", response_class=HTMLResponse)
def log_craving(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
    intensity: Annotated[int, Form(ge=1, le=10)] = 5,
    resisted: Annotated[str | None, Form()] = "yes",
    trigger: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    if user is None:
        raise HTTPException(401)
    payload: dict[str, Any] = {
        "intensity": intensity,
        "resisted": resisted != "no",
    }
    if trigger:
        payload["trigger"] = trigger
    db.add(Event(
        user_id=user.id,
        client_uuid=f"web-{secrets.token_hex(6)}",
        kind="craving",
        occurred_at=datetime.now(UTC),
        payload=payload,
    ))
    db.commit()
    ctx = _build_dashboard_ctx(db, user)
    return templates.TemplateResponse(request, "_dashboard_main.html", ctx)


@router.get("/web/dashboard", response_class=HTMLResponse)
def dashboard_fragment(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
) -> HTMLResponse:
    """HTMX-poll endpoint: refresh the whole dashboard panel every 30 s."""
    if user is None:
        raise HTTPException(401)
    ctx = _build_dashboard_ctx(db, user)
    return templates.TemplateResponse(request, "_dashboard_main.html", ctx)


@router.post("/web/nudge/accept", response_class=HTMLResponse)
def accept_nudge(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(get_session_user)],
    nudge_id: Annotated[str, Form()],
    accepted: Annotated[str, Form()] = "yes",
) -> HTMLResponse:
    if user is None:
        raise HTTPException(401)
    db.add(Event(
        user_id=user.id,
        client_uuid=f"web-{secrets.token_hex(6)}",
        kind="nudge",
        occurred_at=datetime.now(UTC),
        payload={"type": nudge_id, "accepted": accepted == "yes"},
    ))
    db.commit()
    ctx = _build_dashboard_ctx(db, user)
    return templates.TemplateResponse(request, "_dashboard_main.html", ctx)


def mount_static(app) -> None:
    app.mount("/static", StaticFiles(directory=_BASE / "static"), name="static")


def _state_trace_for_plot(
    db: Session,
    user: User,
    now: datetime,
    lookback_days: int = 1,
    model_parameters: CravingModelParameters | None = None,
) -> dict[str, list]:
    """Create time series for 3D plot: time × dopamine × craving probability.

    We preserve the existing engine internals by reusing the same input-mapping
    helpers that feed the dynamic latent-state model in regular predictions.

    Important: simulation is performed on a fixed discrete grid of 60-second
    steps (dt = 1/60 hours), independent of raw event spacing.
    """
    start = now - timedelta(days=lookback_days)
    events = list(
        db.execute(
            select(Event)
            .where(Event.user_id == user.id, Event.occurred_at >= start)
            .order_by(Event.occurred_at.asc())
        ).scalars()
    )
    for ev in events:
        if ev.occurred_at.tzinfo is None:
            ev.occurred_at = ev.occurred_at.replace(tzinfo=UTC)

    model = _engine.dynamic_model.clone() if model_parameters is None else CravingModel(model_parameters)
    model.reset()
    context: dict[str, Any] = {}

    times: list[str] = []
    dopamine: list[float] = []
    craving: list[float] = []

    def append_point(ts: datetime) -> None:
        state = model.get_state()
        times.append(ts.astimezone(UTC).isoformat())
        dopamine.append(round(float(state["dopamine"]), 4))
        craving.append(round(float(state["craving_probability"]), 4))

    # Fixed-step simulation at dt=60 seconds over exactly one day.
    dt_h = 1.0 / 60.0
    cursor = start
    end = now
    ev_idx = 0
    n_events = len(events)

    while cursor < end:
        step_end = min(cursor + timedelta(seconds=60), end)

        # Aggregate all events in this 60s bin into one model update.
        nicotine = 0.0
        reward = 0.0
        stress, cue = _engine._context_proxies(context)
        observed_vals: list[float] = []
        action: dict[str, float] | None = None

        while ev_idx < n_events and events[ev_idx].occurred_at < step_end:
            ev = events[ev_idx]
            if ev.kind == "context" and isinstance(ev.payload, dict):
                context = dict(ev.payload)
                stress, cue = _engine._context_proxies(context)
            ev_nic, ev_rew, ev_stress, ev_cue = _engine._inputs_for_step(ev, context)
            nicotine = max(nicotine, ev_nic)
            reward = max(reward, ev_rew)
            stress = max(stress, ev_stress)
            cue = max(cue, ev_cue)

            obs = _engine._event_observed_craving(ev)
            if obs is not None:
                observed_vals.append(float(obs))

            ev_action = _engine._event_action(ev)
            if ev_action is not None:
                if action is None:
                    action = {"dopamine_boost": 0.0, "withdrawal_relief": 0.0}
                action["dopamine_boost"] = max(
                    action["dopamine_boost"], float(ev_action.get("dopamine_boost", 0.0))
                )
                action["withdrawal_relief"] = max(
                    action["withdrawal_relief"], float(ev_action.get("withdrawal_relief", 0.0))
                )
            ev_idx += 1

        observed = sum(observed_vals) / len(observed_vals) if observed_vals else None
        model.update(
            dt=dt_h,
            nicotine=nicotine,
            reward=reward,
            stress=stress,
            cue=cue,
            action=action,
            observed_craving=observed,
        )
        append_point(step_end)
        cursor = step_end

    return {"time": times, "dopamine": dopamine, "craving": craving}
