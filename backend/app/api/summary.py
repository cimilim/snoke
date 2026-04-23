from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db.session import get_db
from app.models import Event, User
from app.schemas import DailySummary, SummaryOut

router = APIRouter(tags=["summary"])


def _aggregate(events: list[Event], day: date) -> DailySummary:
    cigs = sum(1 for e in events if e.kind == "cigarette")
    cravings = [e for e in events if e.kind == "craving"]
    resisted = sum(1 for e in cravings if bool(e.payload.get("resisted")))
    return DailySummary(
        day=day, cigarettes=cigs, cravings=len(cravings), cravings_resisted=resisted
    )


@router.get("/me/summary", response_model=SummaryOut)
def me_summary(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> SummaryOut:
    today = datetime.now(UTC).date()
    start = today - timedelta(days=6)
    window_start = datetime.combine(start, datetime.min.time(), tzinfo=UTC)

    rows = db.execute(
        select(Event).where(
            Event.user_id == user.id,
            Event.occurred_at >= window_start,
            Event.kind.in_(("cigarette", "craving")),
        )
    ).scalars().all()

    by_day: dict[date, list[Event]] = {start + timedelta(days=i): [] for i in range(7)}
    for ev in rows:
        d = ev.occurred_at.astimezone(UTC).date()
        if d in by_day:
            by_day[d].append(ev)

    days = [_aggregate(by_day[d], d) for d in sorted(by_day)]
    today_summary = next((d for d in days if d.day == today), _aggregate([], today))
    past_six = [d for d in days if d.day != today]
    rolling = sum(d.cigarettes for d in past_six) / max(1, len(past_six))
    return SummaryOut(today=today_summary, last_7_days=days, rolling_avg_7d=round(rolling, 2))
