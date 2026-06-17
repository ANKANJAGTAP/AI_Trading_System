"""API auth: scoped bearer tokens (#19), WS token extraction (#20), and a tiny
in-process rate limiter for sensitive endpoints.

Backward-compatible by design:
- If only API_AUTH_TOKEN is set it grants ADMIN (every scope), so the existing
  single-token dashboard keeps working unchanged.
- Scoped tokens (API_TOKEN_READONLY/OPERATOR/TRADER/ADMIN) are opt-in.
- When NO token is configured the control plane is OPEN (dev only) — unchanged.
"""
from __future__ import annotations

import time

from fastapi import Header, HTTPException

from config.settings import get_settings

# Scope levels — higher includes lower (a TRADER token can also read).
READ, OPERATOR, TRADER, ADMIN = 1, 2, 3, 4
LEVEL_NAME = {READ: "read", OPERATOR: "operator", TRADER: "trader", ADMIN: "admin"}


def configured_tokens(settings=None) -> dict[str, int]:
    """Map each configured token string -> the level it grants. The legacy single
    API_AUTH_TOKEN maps to ADMIN so nothing breaks when scopes aren't used."""
    s = settings or get_settings()
    m: dict[str, int] = {}
    if getattr(s, "api_token_readonly", ""):
        m[s.api_token_readonly] = READ
    if getattr(s, "api_token_operator", ""):
        m[s.api_token_operator] = OPERATOR
    if getattr(s, "api_token_trader", ""):
        m[s.api_token_trader] = TRADER
    if getattr(s, "api_token_admin", ""):
        m[s.api_token_admin] = ADMIN
    if getattr(s, "api_auth_token", ""):
        m[s.api_auth_token] = ADMIN
    return m


def auth_enabled(settings=None) -> bool:
    return bool(configured_tokens(settings))


def bearer(authorization: str | None) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return None


def level_for(token: str | None, tokens: dict[str, int]) -> int:
    """Granted level for a token; 0 if missing/unknown."""
    if not token:
        return 0
    return tokens.get(token, 0)


def require_scope(min_level: int):
    """Dependency factory — gate a route at >= min_level. No-op when auth is off."""
    async def _dep(authorization: str | None = Header(default=None)) -> None:
        tokens = configured_tokens()
        if not tokens:
            return  # OPEN control plane (dev only)
        lvl = level_for(bearer(authorization), tokens)
        if lvl <= 0:
            raise HTTPException(status_code=401, detail="unauthorized")
        if lvl < min_level:
            raise HTTPException(
                status_code=403,
                detail=f"requires {LEVEL_NAME.get(min_level, min_level)} scope",
            )
    return _dep


def ws_token_from(headers: dict, query: dict) -> tuple[str | None, str]:
    """Extract a WS token, preferring the Authorization header or the
    Sec-WebSocket-Protocol subprotocol ("bearer,<token>") over the DEPRECATED
    query string (which leaks via logs/proxies/history). Returns (token, source)."""
    tok = bearer(headers.get("authorization"))
    if tok:
        return tok, "header"
    protos = [p.strip() for p in (headers.get("sec-websocket-protocol") or "").split(",") if p.strip()]
    if len(protos) >= 2 and protos[0] == "bearer":
        return protos[1], "subprotocol"
    q = query.get("token")
    if q:
        return q, "query"
    return None, "none"


# --- tiny in-process sliding-window rate limiter (sensitive endpoints) ---
_BUCKETS: dict[str, list[float]] = {}


def rate_ok(key: str, max_calls: int, per_seconds: float, *, now: float | None = None) -> bool:
    """True if the call is within the limit for `key`; records the call when allowed."""
    t = time.monotonic() if now is None else now
    q = _BUCKETS.setdefault(key, [])
    cutoff = t - per_seconds
    while q and q[0] < cutoff:
        q.pop(0)
    if len(q) >= max_calls:
        return False
    q.append(t)
    return True


def rate_limit(name: str, max_calls: int = 20, per_seconds: float = 60.0):
    """Dependency — limit a sensitive endpoint per process. 429 when exceeded."""
    async def _dep() -> None:
        if not rate_ok(f"ep:{name}", max_calls, per_seconds):
            raise HTTPException(status_code=429, detail="rate limit exceeded")
    return _dep
