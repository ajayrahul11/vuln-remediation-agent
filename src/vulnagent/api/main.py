"""FastAPI app. Optional in this design -- ingestion is the poller, not a
request handler. Kept for health checks and the admin/runs surface, both
useful for an ops team even in a poll-based system.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from vulnagent.api.routes import health, runs
from vulnagent.config import get_settings
from vulnagent.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.env != "local")
    yield


app = FastAPI(title="vulnagent", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(runs.router)
