from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("user_id", "client_uuid", name="uq_event_client_uuid"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    client_uuid: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # cigarette|craving|context|nudge
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    user: Mapped["User"] = relationship("User", back_populates="events")  # noqa: F821


@event.listens_for(Event, "load")
def _coerce_event_timestamps(target: Event, _context) -> None:
    """SQLite strips tzinfo on persist; reattach UTC on load so callers can
    freely compare `event.occurred_at` with `datetime.now(UTC)`."""
    if target.occurred_at is not None and target.occurred_at.tzinfo is None:
        target.occurred_at = target.occurred_at.replace(tzinfo=UTC)
    if target.received_at is not None and target.received_at.tzinfo is None:
        target.received_at = target.received_at.replace(tzinfo=UTC)
