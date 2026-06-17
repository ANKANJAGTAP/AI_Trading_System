"""WebSocket push relay (Phase 6). Subscribes to the engine's Redis pub/sub event
channel and forwards every event to the connected browser client. The frontend's
real-time layer consumes these (price/pnl/position/signal/order/health/alert/mode).
"""
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.auth import READ, configured_tokens, level_for, ws_token_from
from common.events import EVENTS_CHANNEL
from common.logging import get_logger
from common.redis_client import get_redis

log = get_logger("api_ws")
router = APIRouter()


@router.websocket("/ws")
async def ws_events(websocket: WebSocket) -> None:
    # Auth (#20): prefer the Authorization header or the Sec-WebSocket-Protocol
    # subprotocol ("bearer,<token>"); the ?token= query param still works but is
    # deprecated (it leaks via logs/proxies/history) and its value is never logged.
    tokens = configured_tokens()
    subprotocol = None
    if tokens:
        supplied, source = ws_token_from(dict(websocket.headers), dict(websocket.query_params))
        if level_for(supplied, tokens) < READ:
            await websocket.close(code=1008)
            return
        if source == "subprotocol":
            subprotocol = "bearer"   # must echo the negotiated subprotocol back
        elif source == "query":
            log.warning("ws_token_in_query_deprecated", hint="use subprotocol/header")
    await websocket.accept(subprotocol=subprotocol)
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
