from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

_engine_kwargs: dict = {"future": True}
if settings.database_url.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(settings.database_url, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables. For dev/MVP only — production uses Alembic migrations."""
    from app import models  # noqa: F401  import side-effects register models

    Base.metadata.create_all(bind=engine)
    _ensure_user_profile_columns()


def _ensure_user_profile_columns() -> None:
    """Best-effort SQLite dev migration for newly added user profile fields."""
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(users)")).mappings().all()
        if not rows:
            return
        existing = {str(r["name"]) for r in rows}
        wanted = {
            "weight_kg": "ALTER TABLE users ADD COLUMN weight_kg FLOAT DEFAULT 75.0",
            "height_cm": "ALTER TABLE users ADD COLUMN height_cm FLOAT DEFAULT 175.0",
            "body_fat": "ALTER TABLE users ADD COLUMN body_fat FLOAT DEFAULT 0.20",
            "age_years": "ALTER TABLE users ADD COLUMN age_years INTEGER DEFAULT 30",
            "weekly_weight_loss_kg": "ALTER TABLE users ADD COLUMN weekly_weight_loss_kg FLOAT DEFAULT 0.40",
        }
        for name, ddl in wanted.items():
            if name not in existing:
                conn.execute(text(ddl))
