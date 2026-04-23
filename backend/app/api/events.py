from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db.session import get_db
from app.models import Event, User
from app.schemas import EventBatchIn, EventBatchOut

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/batch", response_model=EventBatchOut)
def upload_batch(
    batch: EventBatchIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> EventBatchOut:
    if not batch.events:
        return EventBatchOut(accepted=0, duplicates=0)

    uuids = [e.client_uuid for e in batch.events]
    existing = set(
        db.execute(
            select(Event.client_uuid).where(
                Event.user_id == user.id, Event.client_uuid.in_(uuids)
            )
        ).scalars()
    )

    accepted = 0
    for item in batch.events:
        if item.client_uuid in existing:
            continue
        db.add(
            Event(
                user_id=user.id,
                client_uuid=item.client_uuid,
                kind=item.kind.value,
                occurred_at=item.occurred_at,
                payload=item.payload,
            )
        )
        existing.add(item.client_uuid)
        accepted += 1

    db.commit()
    return EventBatchOut(accepted=accepted, duplicates=len(batch.events) - accepted)
