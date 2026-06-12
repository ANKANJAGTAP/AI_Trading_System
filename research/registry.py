"""Model registry: persist + activate trained meta-models (Phase 4)."""
from __future__ import annotations

import json

from common.db import execute, fetch, fetchrow
from research.meta_label import MetaLabeler


async def save_model(name: str, features: list[str], params: dict, metrics: dict,
                     activate: bool = True) -> int:
    row = await fetchrow(
        "INSERT INTO meta_models (name, features, params, metrics, active) "
        "VALUES ($1,$2,$3::jsonb,$4::jsonb,$5) RETURNING id",
        name, features, json.dumps(params), json.dumps(metrics), activate)
    if activate:
        await execute("UPDATE meta_models SET active=false WHERE id<>$1", row["id"])
    return row["id"]


async def get_active() -> dict | None:
    row = await fetchrow("SELECT * FROM meta_models WHERE active=true ORDER BY created_at DESC LIMIT 1")
    if not row:
        return None
    return _row_to_dict(row)


async def list_models(limit: int = 20) -> list[dict]:
    rows = await fetch("SELECT id, created_at, name, features, metrics, active FROM meta_models "
                       "ORDER BY created_at DESC LIMIT $1", int(limit))
    out = []
    for r in rows:
        m = r["metrics"]
        if isinstance(m, str):
            m = json.loads(m)
        out.append({"id": r["id"], "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "name": r["name"], "n_features": len(list(r["features"] or [])),
                    "metrics": m or {}, "active": r["active"]})
    return out


async def activate(model_id: int) -> None:
    await execute("UPDATE meta_models SET active=(id=$1)", model_id)


def _row_to_dict(row) -> dict:
    params = row["params"]
    if isinstance(params, str):
        params = json.loads(params)
    metrics = row["metrics"]
    if isinstance(metrics, str):
        metrics = json.loads(metrics)
    return {"id": row["id"], "name": row["name"], "features": list(row["features"] or []),
            "params": params, "metrics": metrics or {}}


async def load_labeler() -> MetaLabeler | None:
    """Construct a MetaLabeler from the active model, or None if there isn't one."""
    active = await get_active()
    if not active or not active.get("params") or not active.get("features"):
        return None
    return MetaLabeler(active["features"], active["params"])
