from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db.session import get_db
from app.models import User
from app.schemas import RegisterIn, TokenOut

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/register", response_model=TokenOut)
def register(payload: RegisterIn, db: Annotated[Session, Depends(get_db)]) -> TokenOut:
    user = db.get(User, payload.device_id)
    if user is None:
        user = User(
            id=payload.device_id,
            baseline_cigarettes_per_day=payload.baseline_cigarettes_per_day,
            weaning_rate_pct=payload.weaning_rate_pct,
            weight_kg=payload.weight_kg,
            height_cm=payload.height_cm,
            body_fat=payload.body_fat,
            age_years=payload.age_years,
            weekly_weight_loss_kg=payload.weekly_weight_loss_kg,
        )
        db.add(user)
    else:
        if payload.baseline_cigarettes_per_day is not None:
            user.baseline_cigarettes_per_day = payload.baseline_cigarettes_per_day
        user.weaning_rate_pct = payload.weaning_rate_pct
        user.weight_kg = payload.weight_kg
        user.height_cm = payload.height_cm
        user.body_fat = payload.body_fat
        user.age_years = payload.age_years
        user.weekly_weight_loss_kg = payload.weekly_weight_loss_kg
    db.commit()
    token = create_access_token(subject=user.id)
    return TokenOut(access_token=token)
