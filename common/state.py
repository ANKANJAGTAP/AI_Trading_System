"""Runtime operator state in `config_state` (mode, pause, kill-switch, toggles).

JSONB values: asyncpg returns them as JSON text, so we json.loads on read and
cast $::jsonb on write.
"""
from __future__ import annotations

import json

from common.db import execute, fetchrow


async def get_state(key: str, default=None):
    row = await fetchrow("SELECT value FROM config_state WHERE key = $1", key)
    if not row:
        return default
    value = row["value"]
    return json.loads(value) if isinstance(value, str) else value


async def set_state(key: str, value, updated_by: str = "system") -> None:
    await execute(
        "INSERT INTO config_state (key, value, updated_by) VALUES ($1, $2::jsonb, $3) "
        "ON CONFLICT (key) DO UPDATE SET value = $2::jsonb, updated_at = now(), updated_by = $3",
        key, json.dumps(value), updated_by,
    )
