"""Persistence helpers for per-user model configuration.

To avoid schema migrations in the MVP, we store config snapshots as events of
kind `model_config` and always read the latest one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.model.model_config import CravingModelConfig, default_model_config, to_runtime_parameters
from app.model.state_space import CravingModelParameters
from app.models import Event, User

_CONFIG_EVENT_KIND = "model_config"


def get_user_model_config(db: Session, user: User) -> CravingModelConfig:
    row = db.execute(
        select(Event)
        .where(Event.user_id == user.id, Event.kind == _CONFIG_EVENT_KIND)
        .order_by(Event.occurred_at.desc(), Event.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None or not isinstance(row.payload, dict):
        return default_model_config()
    try:
        return CravingModelConfig.model_validate(row.payload)
    except Exception:
        return default_model_config()


def set_user_model_config(db: Session, user: User, config: CravingModelConfig) -> CravingModelConfig:
    db.add(
        Event(
            user_id=user.id,
            client_uuid=f"cfg-{uuid.uuid4().hex[:16]}",
            kind=_CONFIG_EVENT_KIND,
            occurred_at=datetime.now(UTC),
            payload=config.model_dump(mode="json"),
        )
    )
    db.commit()
    return config


def reset_user_model_config(db: Session, user: User) -> CravingModelConfig:
    return set_user_model_config(db, user, default_model_config())


def get_user_runtime_parameters(db: Session, user: User) -> CravingModelParameters:
    return to_runtime_parameters(
        get_user_model_config(db, user),
        weight_kg=user.weight_kg,
        height_cm=user.height_cm,
        body_fat=user.body_fat,
        age_years=user.age_years,
    )
