"""Concrete pre-live probes (P0#2).

The real verifications, wired to the read-only adapter / rate governor / Redis /
DB / trading calendar. Assembled into a PreLiveCheckService consumed by the
mode-transition gate (P0#1) and surfaced by GET /prelive-checklist.

Every probe is read-only (no orders are ever placed; order_margins is a margin
*quote*, not an order) and fails closed — an exception becomes a FAIL upstream.
"""
from __future__ import annotations

import datetime as dt

from common.logging import get_logger
from common.prelive import FAIL, PASS, WARN, PreLiveCheckService, persist_run

log = get_logger("prelive_checks")


async def _broker_token():
    from api.services import read_adapter
    return (PASS, "token present") if read_adapter() is not None else (FAIL, "no valid Kite token for today")


async def _broker_reachable():
    from api.services import governor, read_adapter
    a = read_adapter()
    if a is None:
        return (FAIL, "no adapter/token")
    m = await governor().call("other", a.margins, "equity")
    net = (m or {}).get("net") if isinstance(m, dict) else None
    return (PASS, "margins reachable", {"equity_net": net})


async def _market_data_feed():
    from common.market_time import is_within, now_ist
    from common.redis_client import get_redis
    from config.loader import get_config
    last = await (await get_redis()).get("aegis:feed:last_tick")
    market = (get_config().data.feed or {}).get("market_window", ["09:15", "15:30"])
    in_session = is_within(market[0], market[1])
    if not last:
        return (FAIL if in_session else WARN, "no feed tick recorded")
    age = (now_ist() - dt.datetime.fromisoformat(last)).total_seconds()
    if not in_session:
        return (WARN, f"market closed; last tick age {int(age)}s", {"age_s": int(age)})
    return (PASS if age < 30 else FAIL, f"feed age {int(age)}s", {"age_s": int(age)})


async def _order_dry_run():
    from api.services import governor, read_adapter
    a = read_adapter()
    if a is None:
        return (FAIL, "no adapter")
    order = {"exchange": "NSE", "tradingsymbol": "INFY", "transaction_type": "BUY",
             "variety": "regular", "product": "MIS", "order_type": "MARKET", "quantity": 1, "price": 0}
    res = await governor().call("other", a.order_margins, [order])
    total = float(res[0].get("total")) if res else 0.0
    return (PASS if total > 0 else WARN, "order_margins responded", {"sample_total": total})


async def _positions_reconcile():
    from api.services import governor, read_adapter
    from common.db import fetchval
    db_n = int(await fetchval("SELECT COUNT(*) FROM positions WHERE status='open' AND mode='live'") or 0)
    a = read_adapter()
    if a is None:
        return (FAIL, "no adapter to reconcile")
    bp = await governor().call("other", a.positions)
    net = bp.get("net", []) if isinstance(bp, dict) else []
    broker_n = sum(1 for p in net if int(p.get("quantity") or 0) != 0)
    ok = broker_n == db_n
    return (PASS if ok else FAIL, f"broker={broker_n} db={db_n}", {"broker": broker_n, "db": db_n})


async def _no_stale_live_positions():
    from common.db import fetchval
    n = int(await fetchval("SELECT COUNT(*) FROM positions WHERE status='open' AND mode='live'") or 0)
    return (PASS if n == 0 else WARN, f"{n} open live position(s)", {"open_live": n})


async def _alerts_configured():
    from config.settings import get_settings
    s = get_settings()
    host = getattr(s, "smtp_host", None) or getattr(s, "smtp_server", None)
    # Verify config presence only (we don't spam a real email on every poll; a live
    # transition can run an explicit send-test).
    return (PASS, "SMTP configured") if host else (WARN, "SMTP not configured")


async def _redis_healthy():
    from common.redis_client import get_redis
    return (PASS, "redis ping ok") if await (await get_redis()).ping() else (FAIL, "redis ping failed")


async def _db_migrations():
    from common.db import fetchval
    n = int(await fetchval("SELECT COUNT(*) FROM schema_migrations") or 0)
    return (PASS if n > 0 else FAIL, f"{n} migrations applied", {"applied": n})


async def _risk_caps_loaded():
    from config.loader import get_config
    cfg = get_config()
    dml = cfg.risk.daily_max_loss_pct.default
    prl = cfg.risk.portfolio_risk_limit_pct.default
    ok = dml > 0 and prl > 0
    return (PASS if ok else FAIL, f"daily_max_loss={dml}% portfolio_limit={prl}%",
            {"daily_max_loss_pct": dml, "portfolio_risk_limit_pct": prl})


async def _kill_switch_ready():
    from common.state import get_state
    active = bool(await get_state("kill_switch_active", False))
    return (PASS, "kill-switch clear") if not active else (FAIL, "kill-switch is ACTIVE")


async def _clock():
    from common.market_time import now_ist
    # Records the clock for evidence. Broker-server skew comparison is P1 work; the
    # local clock being readable + IST-aligned is the minimum bar here.
    return (PASS, "system clock readable", {"now_ist": now_ist().isoformat()})


async def _holiday_calendar():
    from common.market_time import now_ist
    from dataplatform.marketcalendar import TradingCalendar
    cal = TradingCalendar.from_seed()
    today = now_ist().date()
    return (PASS, "calendar loaded", {"today": str(today), "is_trading_day": cal.is_trading_day(today)})


async def _dependency_versions():
    import importlib.metadata as md
    vers = {}
    for pkg in ("kiteconnect", "asyncpg", "redis", "fastapi", "pandas", "numpy", "duckdb", "pyarrow"):
        try:
            vers[pkg] = md.version(pkg)
        except Exception:
            vers[pkg] = "missing"
    missing = [k for k, v in vers.items() if v == "missing"]
    return (PASS if not missing else WARN, f"{len(vers) - len(missing)}/{len(vers)} present", vers)


async def _sebi_compliance():
    from common.compliance import compliance_gaps
    from config.loader import get_config
    gaps = compliance_gaps(get_config())
    if gaps:
        return (FAIL, "; ".join(gaps), {"gaps": gaps})
    return (PASS, "order tag + static IP + market protection + OPS<=10 configured")


async def _token_security():
    """#21: token encryption-at-rest policy + broker-token freshness (read-only).
    Fails closed in live only when a non-dev env has no encryption key — paper is
    unaffected (this probe gates arming live, never startup)."""
    from broker.token_store import TokenStore
    from common.secrets import token_security_ok
    from config.settings import get_settings
    s = get_settings()
    ok, msg = token_security_ok(s.env, bool(s.token_encryption_key))
    if not ok:
        return (FAIL, msg, {"env": s.env})
    age = TokenStore(s.token_store_path, s.token_encryption_key).age_seconds()
    if age is None:
        return (WARN, f"{msg}; no token file yet", {"age_s": None})
    stale = age > 86400  # Kite tokens are daily; >1 day is stale.
    return (WARN if stale else PASS, f"{msg}; token age {int(age)}s",
            {"age_s": int(age), "stale": stale})


_CHECKS = [
    ("broker_token", _broker_token),
    ("token_security", _token_security),
    ("broker_reachable", _broker_reachable),
    ("market_data_feed", _market_data_feed),
    ("order_dry_run", _order_dry_run),
    ("positions_reconcile", _positions_reconcile),
    ("no_stale_live_positions", _no_stale_live_positions),
    ("alerts_configured", _alerts_configured),
    ("redis_healthy", _redis_healthy),
    ("db_migrations", _db_migrations),
    ("risk_caps_loaded", _risk_caps_loaded),
    ("kill_switch_ready", _kill_switch_ready),
    ("clock", _clock),
    ("holiday_calendar", _holiday_calendar),
    ("dependency_versions", _dependency_versions),
    ("sebi_compliance", _sebi_compliance),
]


def build_prelive_service(persist: bool = True) -> PreLiveCheckService:
    return PreLiveCheckService(_CHECKS, persister=(persist_run if persist else None))
