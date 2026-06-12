"""FastAPI control-plane + dashboard API (Phase 6).

Serves the Section 9 / frontend Appendix B surface: REST reads (account, pnl,
positions, sleeves, risk, signals, audit + reconstruction, config, health,
prelive-checklist), guarded control actions, and a WebSocket push relay off the
engine's Redis event channel.

Auth: when `API_AUTH_TOKEN` is set, every /api/* route and /ws require a
`Authorization: Bearer <token>` header (token also accepted as `?token=` on /ws).
When empty the control plane is OPEN (dev only) and a loud warning is logged.
"""
from __future__ import annotations

import json
import math
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import router as api_router
from api.ws import router as ws_router
from common.db import close_pool, get_pool, init_pool
from common.logging import configure_logging, get_logger
from common.redis_client import close_redis, get_redis
from config.loader import get_config
from config.settings import get_settings

log = get_logger("api")


def _sanitize(o):
    """Replace non-finite floats (NaN/Inf — common from thin-instrument indicators)
    with None so responses are always valid JSON."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _sanitize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_sanitize(v) for v in o]
    return o


class SafeJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(_sanitize(content), ensure_ascii=False, allow_nan=False,
                          separators=(",", ":"), default=str).encode("utf-8")


async def require_auth(authorization: str | None = Header(default=None)) -> None:
    """Bearer-token gate for /api/* routes. No-op when API_AUTH_TOKEN is unset."""
    token = get_settings().api_auth_token
    if not token:
        return
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="unauthorized")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await init_pool()
    await get_redis()
    if not get_settings().api_auth_token:
        log.warning("api_auth_disabled_open_control_plane",
                    hint="set API_AUTH_TOKEN and bind the port to localhost in production")
    log.info("api_startup", mode=get_config().execution.mode)
    yield
    await close_pool()
    await close_redis()
    log.info("api_shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AI Trading System — Aegis API", version="0.6.1-phase6b",
                  lifespan=lifespan, default_response_class=SafeJSONResponse)
    # CORS: locked to configured origins in prod; "*" only for local dev. Credentials
    # are only allowed when origins are explicitly listed (never with "*").
    raw = (settings.cors_allow_origins or "*").strip()
    origins = ["*"] if raw == "*" else [o.strip() for o in raw.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_credentials=(origins != ["*"]),
        allow_methods=["*"], allow_headers=["*"],
    )
    # All control/read routes are auth-gated (no-op when API_AUTH_TOKEN is unset).
    app.include_router(api_router, dependencies=[Depends(require_auth)])
    app.include_router(ws_router)

    @app.get("/health")
    async def health() -> dict:
        cfg = get_config()
        settings = get_settings()
        db_ok = redis_ok = True
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
        except Exception:
            db_ok = False
        try:
            client = await get_redis()
            await client.ping()
        except Exception:
            redis_ok = False
        return {
            "status": "ok" if (db_ok and redis_ok) else "degraded",
            "env": settings.env,
            "mode": cfg.execution.mode,
            "db": db_ok,
            "redis": redis_ok,
        }

    return app


app = create_app()
