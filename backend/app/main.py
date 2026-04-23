from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api import events, model_config, probability, summary, users
from app.core.config import settings
from app.db.session import init_db
from app.web import routes as web_routes


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=f"{settings.app_name} API",
    version=__version__,
    lifespan=lifespan,
)

app.include_router(users.router)
app.include_router(events.router)
app.include_router(summary.router)
app.include_router(probability.router)
app.include_router(model_config.router)
app.include_router(web_routes.router)
web_routes.mount_static(app)


@app.get("/healthz", tags=["health"])
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
