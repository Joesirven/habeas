"""FastAPI admin control plane."""

from fastapi import FastAPI
from sse_starlette.sse import EventSourceResponse

from habeas_privacy_core.health import health_payload

app = FastAPI(title="Habeas Privacy Admin API", version="0.1.0")


@app.get("/healthz")
async def healthz():
    return health_payload()


@app.get("/live/events")
async def live_events():
    """Server-Sent Events stream — Postgres LISTEN bridge wired in a follow-up change."""

    async def event_generator():
        yield {"event": "ready", "data": "connected"}

    return EventSourceResponse(event_generator())
