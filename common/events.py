"""Cross-process event bus (engine -> API WebSocket) over Redis pub/sub.

The engine publishes typed events (signal_evaluated, pnl_update, order_event,
alert, health_update, mode_changed, position_update); the API's /ws endpoint
subscribes and relays them to browser clients. Fire-and-forget — a publish failure
must never disrupt trading.
"""
from __future__ import annotations

import json

from common.logging import get_logger
from common.market_time import now_ist
from common.redis_client import get_redis

log = get_logger("events")

EVENTS_CHANNEL = "aegis:events"


async def publish_event(event_type: str, payload: dict) -> None:
    try:
        r = await get_redis()
        await r.publish(EVENTS_CHANNEL, json.dumps(
            {"type": event_type, "payload": payload, "ts": now_ist().isoformat()}, default=str))
    except Exception as exc:
        log.warning("publish_event_failed", type=event_type, error=str(exc))
