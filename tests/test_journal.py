from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from research import journal


def test_daily_journal_builds_review_record(monkeypatch):
    async def fake_fetch(query, *args):
        if "FROM positions WHERE status='open'" in query:
            return [{"tradingsymbol": "NIFTY26JUL24400CE", "side": "SELL", "quantity": 75, "up": -1200}]
        if "FROM positions p WHERE p.status='closed'" in query:
            return [{
                "id": 42,
                "legs": 4,
                "inst": "iron_condor",
                "sleeve": "fno",
                "pnl": -28000,
                "rr": 20000,
                "max_loss": 20306,
                "reasons": "guard_stop",
                "closed": "14:58",
            }]
        if "FROM signals" in query and "decision='REJECT'" in query:
            return [{"sleeve": "fno", "reason": "iv_spike", "c": 7}]
        raise AssertionError(query)

    async def fake_fetchval(query, *args):
        if "SELECT $1::numeric" in query:
            return args[0] - 16800
        if "COALESCE(SUM(realized_pnl),0)" in query:
            return -39645
        if "decision='PASS'" in query:
            return 3
        if "SELECT count(*) FROM" in query:
            return 36
        raise AssertionError(query)

    async def fake_fetchrow(query, *args):
        if "FROM daily_pnl" in query:
            return {"kill_switch_tripped": True, "max_loss_limit": 25000}
        if "FROM config_state" in query:
            values = {
                "period_brake_active": "false",
                "trade_budget_exhausted": "true",
                "dd_circuit_active": "false",
                "sleeve_fno_review_required": "true",
            }
            return {"value": values.get(args[0], "false")}
        if "FROM meta_models" in query:
            return {"name": "meta-v2", "metrics": '{"lift": 0.08}', "active": True}
        raise AssertionError(query)

    monkeypatch.setattr(journal, "fetch", fake_fetch)
    monkeypatch.setattr(journal, "fetchval", fake_fetchval)
    monkeypatch.setattr(journal, "fetchrow", fake_fetchrow)
    monkeypatch.setattr(
        journal,
        "get_config",
        lambda: SimpleNamespace(risk=SimpleNamespace(paper_capital=1_000_000)),
    )
    monkeypatch.setattr(
        journal,
        "now_ist",
        lambda: datetime(2026, 6, 12, 17, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
    )

    content = asyncio.run(journal.build_daily_journal())

    assert "Running balance: Rs 983,200.00" in content
    assert "#42 iron_condor [fno] legs=4 pnl Rs -28,000" in content
    assert "STOP-OVERRUN" in content
    assert "BEYOND-MAX-LOSS" in content
    assert "KILL-SWITCH TRIPPED" in content
    assert "limit Rs 25,000" in content
    assert "TRADE BUDGET active: True" in content
    assert "KILL CRITERIA: sleeve fno disabled pending human review" in content
    assert "Decision funnel — PASS 3" in content
    assert "Latest model: meta-v2 active=True metrics={'lift': 0.08}" in content
