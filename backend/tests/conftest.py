"""Shared test fixtures.

We set env vars *before* any application module gets imported; the env file
in the repo is therefore irrelevant to tests. Each test gets its own
in-memory SQLite database (shared across connections via StaticPool).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

# Must run before `app` is ever imported.
os.environ.setdefault("SNOKE_JWT_SECRET", "test-secret")
os.environ.setdefault("SNOKE_JWT_ALG", "HS256")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def client() -> Iterator[TestClient]:
    # Unique in-memory DB per test, shared across connections via StaticPool.
    db_url = f"sqlite+pysqlite:///file:mem_{uuid.uuid4().hex}?mode=memory&cache=shared&uri=true"
    os.environ["SNOKE_DATABASE_URL"] = db_url

    # Force a fresh settings object and engine on each test run.
    from app.core import config as config_module
    config_module.settings = config_module.Settings()

    from app.db import session as session_module
    session_module.engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False, "uri": True},
        poolclass=StaticPool,
        future=True,
    )
    session_module.SessionLocal.configure(bind=session_module.engine)

    # Create the schema now so the app lifespan is not required.
    import app.models  # noqa: F401  ensure models are registered
    session_module.Base.metadata.create_all(bind=session_module.engine)

    from app.main import app

    with TestClient(app) as c:
        yield c
