"""End-to-end decision-pipeline tests."""
from fno_signals.pipeline import decide, DecisionConfig
from fno_signals.sizing import SizingConfig
from fno_signals.risk import RiskState


def _cfg(capital=1_000_000):
    return DecisionConfig(sizing=SizingConfig(capital=capital, per_trade_risk_pct=1.0))


def test_accepts_bullish_low_iv(ctx_bull_lowiv):
    d = decide(ctx_bull_lowiv, _cfg(), RiskState(capital=1_000_000))
    assert d.accepted, d.reject_reason
    assert d.family == "bull_call_debit"
    assert d.lots >= 1
    assert d.qty == ctx_bull_lowiv.lot_size * d.lots
    assert d.max_loss > 0
    assert len(d.structure.legs) == 2
    assert d.gate_trail                       # audit trail present


def test_meta_veto_blocks(ctx_bull_lowiv):
    d = decide(ctx_bull_lowiv, _cfg(), RiskState(capital=1_000_000),
               meta_confidence=0.2)           # below veto threshold
    assert not d.accepted and "meta-veto" in d.reject_reason


def test_kill_switch_blocks(ctx_bull_lowiv):
    rs = RiskState(capital=1_000_000, day_pnl=-50_000, daily_max_loss_pct=3.0)
    d = decide(ctx_bull_lowiv, _cfg(), rs)
    assert not d.accepted and "kill-switch" in d.reject_reason


def test_tiny_capital_sizes_to_zero(ctx_bull_lowiv):
    d = decide(ctx_bull_lowiv, _cfg(capital=1_000), RiskState(capital=1_000))
    assert not d.accepted and "lot" in d.reject_reason


def test_illiquid_rejected_at_gate(ctx_illiquid):
    d = decide(ctx_illiquid, _cfg(), RiskState(capital=1_000_000))
    assert not d.accepted and "liquidity" in d.reject_reason


def test_neutral_high_iv_routes_to_condor(ctx_neutral_highiv):
    d = decide(ctx_neutral_highiv, _cfg(), RiskState(capital=1_000_000))
    # neutral + high IV -> iron condor (accepted or sized-out, but family must route)
    assert d.family == "iron_condor"
