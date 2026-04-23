from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # device UUID
    baseline_cigarettes_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weaning_rate_pct: Mapped[int] = mapped_column(Integer, default=5)
    weight_kg: Mapped[float] = mapped_column(Float, default=75.0)
    height_cm: Mapped[float] = mapped_column(Float, default=175.0)
    body_fat: Mapped[float] = mapped_column(Float, default=0.20)
    age_years: Mapped[int] = mapped_column(Integer, default=30)
    weekly_weight_loss_kg: Mapped[float] = mapped_column(Float, default=0.40)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    events: Mapped[list["Event"]] = relationship(  # noqa: F821  forward ref
        "Event", back_populates="user", cascade="all, delete-orphan"
    )
