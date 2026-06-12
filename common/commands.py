"""Cross-process command queue (API -> engine) over a Redis list.

State-style controls (pause, mode, sleeve toggles, kill-switch reset) go through
`config_state` (the engine reads them in its loops). One-shot ACTIONS that must run
inside the engine's executor — flatten-all, close, modify — are enqueued here and
drained by the engine's command loop (~1s latency, works even if the feed is down).
"""
from __future__ import annotations

import json

from common.logging import get_logger
from common.redis_client import get_redis

log = get_logger("commands")

COMMANDS_KEY = "aegis:engine:commands"


async def enqueue_command(command: dict) -> None:
    r = await get_redis()
    await r.rpush(COMMANDS_KEY, json.dumps(command, default=str))
    log.info("command_enqueued", command=command.get("type"))


async def dequeue_commands(max_n: int = 50) -> list[dict]:
    r = await get_redis()
    out: list[dict] = []
    for _ in range(max_n):
        item = await r.lpop(COMMANDS_KEY)
        if item is None:
            break
        try:
            out.append(json.loads(item))
        except Exception:
            pass
    return out
