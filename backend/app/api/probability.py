from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db.session import get_db
from app.model import (
    CravingEngine,
    WeaningPlanner,
    get_user_model_config,
    get_user_runtime_parameters,
)
from app.model.nudges import choose_nudge, get_nudge
from app.models import Event, User
from app.schemas import (
    NudgeOut,
    ProbabilityOut,
    RecommendationOut,
    TriggerOut,
    WeaningOut,
)

router = APIRouter(tags=["probability"])

_engine = CravingEngine()


def _rolling_avg_7d(db: Session, user: User, now: datetime) -> tuple[float, int]:
    start = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    rows: list[Event] = list(
        db.execute(
            select(Event).where(
                Event.user_id == user.id,
                Event.kind == "cigarette",
                Event.occurred_at >= start,
            )
        ).scalars()
    )
    by_day: dict[date, int] = {}
    smoked_today = 0
    for ev in rows:
        d = ev.occurred_at.astimezone(UTC).date()
        by_day[d] = by_day.get(d, 0) + 1
        if ev.occurred_at >= today_start:
            smoked_today += 1
    past = [by_day.get((today_start.date() - timedelta(days=i)), 0) for i in range(1, 8)]
    avg = sum(past) / max(1, len(past))
    return avg, smoked_today


@router.get("/me/probability", response_model=ProbabilityOut)
def me_probability(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> ProbabilityOut:
    params = get_user_runtime_parameters(db, user)
    result = _engine.compute_with_parameters(db, user, model_parameters=params)
    return ProbabilityOut(
        as_of=result.now,
        p_now=result.p_now,
        p_low=result.p_low,
        p_high=result.p_high,
        uncertainty_width=result.uncertainty_width,
        confidence_level=result.confidence_level,
        p_next_hour=result.p_next_hour,
        next_peak_at=result.next_peak_at,
        bucket_key=result.bucket_key,
        dopamine=result.dopamine,
        withdrawal=result.withdrawal,
        habit=result.habit,
        rule_reasons=result.rule_reasons,
        top_triggers=[
            TriggerOut(label=t.label, bucket_key=t.bucket_key,
                       mean=t.mean, samples=t.samples)
            for t in result.top_triggers
        ],
    )


@router.get("/me/recommendation", response_model=RecommendationOut)
def me_recommendation(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> RecommendationOut:
    now = datetime.now(UTC)
    params = get_user_runtime_parameters(db, user)
    cfg = get_user_model_config(db, user)
    planner = WeaningPlanner(
        baseline_weight=float(cfg.planner.baseline_weight),
        rolling_weight=float(cfg.planner.rolling_weight),
    )
    result = _engine.compute_with_parameters(db, user, model_parameters=params, now=now)
    avg, smoked_today = _rolling_avg_7d(db, user, now)
    status = planner.status(
        rolling_avg_7d=avg,
        smoked_today=smoked_today,
        weaning_rate_pct=user.weaning_rate_pct,
        baseline=user.baseline_cigarettes_per_day,
    )
    nudge = choose_nudge(result, status)
    return RecommendationOut(
        as_of=now,
        probability=ProbabilityOut(
            as_of=result.now,
            p_now=result.p_now,
            p_low=result.p_low,
            p_high=result.p_high,
            uncertainty_width=result.uncertainty_width,
            confidence_level=result.confidence_level,
            p_next_hour=result.p_next_hour,
            next_peak_at=result.next_peak_at,
            bucket_key=result.bucket_key,
            dopamine=result.dopamine,
            withdrawal=result.withdrawal,
            habit=result.habit,
            rule_reasons=result.rule_reasons,
            top_triggers=[
                TriggerOut(label=t.label, bucket_key=t.bucket_key,
                           mean=t.mean, samples=t.samples)
                for t in result.top_triggers
            ],
        ),
        weaning=WeaningOut(
            target_today=status.target_today,
            smoked_today=status.smoked_today,
            remaining=status.remaining,
            rolling_avg_7d=status.rolling_avg_7d,
            state=status.state.value,
            streak_days_on_target=status.streak_days_on_target,
        ),
        nudge=NudgeOut(
            id=nudge.id,
            title=nudge.title,
            body=nudge.body,
            duration_seconds=nudge.duration_seconds,
            kind=nudge.kind,
        ) if nudge else None,
    )


@router.get("/nudges/{nudge_id}", response_model=NudgeOut)
def get_single_nudge(nudge_id: str) -> NudgeOut:
    n = get_nudge(nudge_id)
    if n is None:
        raise HTTPException(404, "unknown nudge")
    return NudgeOut(id=n.id, title=n.title, body=n.body,
                    duration_seconds=n.duration_seconds, kind=n.kind)
