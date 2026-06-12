"""WebSocket push relay (Phase 6). Subscribes to the engine's Redis pub/sub event
channel and forwards every event to the connected browser client. The frontend's
real-time layer consumes these (price/pnl/position/signal/order/health/alert/mode).
"""
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from common.events import EVENTS_CHANNEL
from common.logging import get_logger
from common.redis_client import get_redis
from config.settings import get_settings

log = get_logger("api_ws")
router = APIRouter()


@router.websocket("/ws")
async def ws_events(websocket: WebSocket) -> None:
    # Auth: when API_AUTH_TOKEN is set, require it as ?token= or a Bearer header.
    token = get_settings().api_auth_token
    if token:
        supplied = websocket.query_params.get("token")
        if not supplied:
            auth = websocket.headers.get("authorization", "")
            supplied = auth[7:] if auth.startswith("Bearer ") else None
        if supplied != token:
            await websocket.close(code=1008)
            return
    await websocket.accept()
    r = await get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(EVENTS_CHANNEL)
    try:
        await websocket.send_json({"type": "connected", "payload": {"channel": EVENTS_CHANNEL}})
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg.get("type") == "message":
                await websocket.send_text(msg["data"])  # already a JSON string (decode_responses=True)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.info("ws_closed", error=str(exc))
    finally:
        try:
            await pubsub.unsubscribe(EVENTS_CHANNEL)
            await pubsub.aclose()
        except Exception:
            pass
