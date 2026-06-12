"""Dashboard REST API (Phase 6 / frontend Appendix B). Reads are pure DB/Redis;
control actions write operator state (config_state) or enqueue one-shot engine
commands (flatten/close/modify). Every action is audited and guarded.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api import analytics as analytics_svc
from api import backtest as backtest_svc
from api import marketdata, research as research_svc, services
from common.audit import audit
from common.commands import enqueue_command
from common.events import publish_event
from common.logging import get_logger
from common.state import set_state

log = get_logger("api_routes")
router = APIRouter(prefix="/api")


# ---------------------------------------------------------------- reads
@router.get("/account")
async def get_account():
    return await services.account()


@router.get("/pnl/today")
async def get_pnl_today():
    return await services.pnl_today()


@router.get("/positions")
async def get_positions():
    return await services.positions()


@router.get("/sleeves")
async def get_sleeves():
    return await services.sleeves()


@router.get("/risk")
async def get_risk():
    return await services.risk()


@router.get("/signals")
async def get_signals(limit: int = Query(50, le=500), filter: str | None = None):
    return await services.signals(limit=limit, flt=filter)


@router.get("/audit")
async def get_audit(limit: int = Query(100, le=1000), offset: int = 0,
                    correlation_id: str | None = None, event_type: str | None = None):
    return await services.audit(limit=limit, offset=offset, correlation_id=correlation_id, event_type=event_type)


@router.get("/audit/{correlation_id}")
async def get_reconstruction(correlation_id: str):
    return await services.reconstruct(correlation_id)


@router.get("/config")
async def get_config_view():
    return await services.config_view()


@router.get("/health")
async def get_health():
    return await services.health()


@router.get("/prelive-checklist")
async def get_prelive():
    return await services.prelive_checklist()


@router.get("/market")
async def get_market():
    return await marketdata.market()


@router.get("/breadth")
async def get_breadth():
    return await marketdata.breadth()


@router.get("/chart/{instrument}")
async def get_chart(instrument: str, interval: str = "5m", limit: int = Query(200, le=1000)):
    return await marketdata.chart(instrument, interval, limit)


@router.get("/optionchain/{underlying}")
async def get_optionchain(underlying: str, expiry: str | None = None):
    return await marketdata.optionchain(underlying, expiry)


@router.get("/analytics")
async def get_analytics(period: str = "all"):
    return await analytics_svc.analytics(period)


class BacktestBody(BaseModel):
    symbols: list[str]
    from_date: str
    to_date: str
    sleeve: str = "intraday_stocks"
    starting_capital: float = 1_000_000.0
    per_trade_pct: float = 1.0


@router.post("/backtest")
async def post_backtest(b: BacktestBody):
    res = await backtest_svc.start_run(b.sleeve, b.symbols, b.from_date, b.to_date,
                                       b.starting_capital, b.per_trade_pct)
    if res.get("error"):
        raise HTTPException(400, res["error"])
    await audit("backtest_started", "api", f"{b.sleeve} {b.from_date}..{b.to_date}",
                payload={"symbols": b.symbols, "sleeve": b.sleeve})
    return res


@router.get("/backtests")
async def get_backtests(limit: int = Query(50, le=200)):
    return await backtest_svc.list_runs(limit)


@router.get("/backtest/{run_id}")
async def get_backtest_run(run_id: int):
    return await backtest_svc.get_run(run_id)


# ---------------------------------------------------------------- research (Phase 4)
class TrainBody(BaseModel):
    name: str | None = None
    min_samples: int = 30


@router.get("/research")
async def get_research():
    return await research_svc.status()


@router.get("/research/dataset")
async def get_research_dataset():
    return await research_svc.dataset_stats()


@router.get("/research/discrimination")
async def get_research_discrimination():
    return await research_svc.discrimination()


@router.post("/research/train")
async def post_research_train(b: TrainBody):
    res = await research_svc.train_and_register(b.name, b.min_samples)
    if res.get("error"):
        raise HTTPException(400, res["error"])
    await audit("meta_trained", "api", res.get("name", ""), payload=res.get("metrics"))
    return res


@router.post("/research/activate/{model_id}")
async def post_research_activate(model_id: int):
    return await research_svc.activate_model(model_id)


@router.get("/signals/rejections")
async def get_rejections(window_hours: int = Query(24, le=720)):
    return await analytics_svc.rejections(window_hours)


class LayoutBody(BaseModel):
    name: str
    layout: dict


@router.get("/layouts")
async def get_layouts():
    return await services.layouts_get()


@router.put("/layouts")
async def put_layouts(b: LayoutBody):
    return await services.layouts_put(b.name, b.layout)


# ---------------------------------------------------------------- controls
class PauseBody(BaseModel):
    paused: bool


class ConfirmBody(BaseModel):
    confirm: bool = False


class SleeveBody(BaseModel):
    enabled: bool


class ModeBody(BaseModel):
    mode: str
    confirm_token: str | None = None


class ModifyBody(BaseModel):
    stop: float | None = None
    target: float | None = None


class ConfigEditBody(BaseModel):
    path: str
    value: float


@router.post("/controls/pause")
async def control_pause(b: PauseBody):
    await set_state("engine_paused", b.paused, "operator")
    await audit("control_pause", "api", f"paused={b.paused}", payload={"paused": b.paused})
    await publish_event("health_update", await services.health())
    return {"ok": True, "paused": b.paused}


@router.post("/controls/flatten")
async def control_flatten(b: ConfirmBody):
    if not b.confirm:
        raise HTTPException(400, "flatten requires confirm=true")
    await enqueue_command({"type": "flatten", "reason": "operator flatten-all"})
    await audit("control_flatten", "api", "operator flatten-all requested")
    return {"ok": True, "queued": True}


@router.post("/controls/sleeve/{sleeve}")
async def control_sleeve(sleeve: str, b: SleeveBody):
    await set_state(f"sleeve_{sleeve}_enabled", b.enabled, "operator")
    await audit("control_sleeve", "api", f"{sleeve} enabled={b.enabled}",
                payload={"sleeve": sleeve, "enabled": b.enabled})
    return {"ok": True, "sleeve": sleeve, "enabled": b.enabled}


@router.post("/controls/mode")
async def control_mode(b: ModeBody):
    if b.mode not in ("simulated_fill", "live"):
        raise HTTPException(400, "mode must be simulated_fill or live")
    if b.mode == "live":
        if b.confirm_token != "LIVE":
            raise HTTPException(400, "going LIVE requires confirm_token='LIVE'")
        # Enforce the pre-live checklist SERVER-SIDE (the UI gate is not trusted).
        checklist = await services.prelive_checklist()
        missing = [k for k, v in checklist.items() if not v]
        if missing:
            raise HTTPException(400, f"pre-live checklist incomplete: {', '.join(missing)}")
    await set_state("execution_mode", b.mode, "operator")
    await audit("control_mode", "api", f"mode -> {b.mode}", payload={"mode": b.mode})
    await publish_event("mode_changed", {"mode": b.mode})
    return {"ok": True, "mode": b.mode}


@router.post("/controls/killswitch/reset")
async def control_ks_reset(b: ConfirmBody):
    if not b.confirm:
        raise HTTPException(400, "reset requires confirm=true")
    await set_state("kill_switch_active", False, "operator")
    await set_state("engine_halted", False, "operator")
    await set_state("engine_paused", False, "operator")
    await set_state("dd_circuit_active", False, "operator")   # clear Phase 3.2 drawdown circuit
    await audit("control_ks_reset", "api", "kill-switch + circuits reset by operator")
    return {"ok": True}


@router.post("/positions/{position_id}/close")
async def close_position(position_id: str, b: ConfirmBody):
    if not b.confirm:
        raise HTTPException(400, "close requires confirm=true")
    await enqueue_command({"type": "close", "id": position_id})
    await audit("control_close", "api", f"close {position_id}", payload={"id": position_id})
    return {"ok": True, "queued": True}


@router.post("/positions/{position_id}/modify")
async def modify_position(position_id: str, b: ModifyBody):
    await enqueue_command({"type": "modify", "id": position_id, "stop": b.stop, "target": b.target})
    await audit("control_modify", "api", f"modify {position_id}", payload=b.model_dump())
    return {"ok": True, "queued": True}


_EDITABLE = {"risk.paper_per_trade_pct": (0.25, 2.0), "risk.paper_daily_max_loss_pct": (1.0, 6.0)}


@router.put("/config")
async def edit_config(b: ConfigEditBody):
    bounds = _EDITABLE.get(b.path)
    if bounds is None:
        raise HTTPException(400, f"path not editable: {b.path}")
    lo, hi = bounds
    if not (lo <= b.value <= hi):
        raise HTTPException(400, f"value {b.value} out of bounds [{lo}, {hi}]")
    await set_state(f"config_override:{b.path}", b.value, "operator")
    await audit("config_edit", "api", f"{b.path}={b.value}", payload=b.model_dump())
    return {"ok": True, "path": b.path, "value": b.value, "applied": False,
            "note": "recorded + audited; applies on engine reload"}
