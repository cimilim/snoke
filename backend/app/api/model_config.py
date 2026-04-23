from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db.session import get_db
from app.model import (
    CravingModelConfig,
    get_user_model_config,
    reset_user_model_config,
    set_user_model_config,
)
from app.models import User

router = APIRouter(tags=["model-config"])


@router.get("/me/model-config", response_model=CravingModelConfig)
def me_model_config(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> CravingModelConfig:
    return get_user_model_config(db, user)


@router.put("/me/model-config", response_model=CravingModelConfig)
def update_model_config(
    payload: CravingModelConfig,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> CravingModelConfig:
    return set_user_model_config(db, user, payload)


@router.post("/me/model-config/reset", response_model=CravingModelConfig)
def reset_model_config(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> CravingModelConfig:
    return reset_user_model_config(db, user)
