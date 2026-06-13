"""Unit tests for the individual pipeline components."""
from fno_signals.gates import run_hard_gates
from fno_signals.regime import iv_regime, route
from fno_signals.structures import select_structure, one_lot_max_loss
from fno_signals.sizing import SizingConfig, effective_R, size_lots
from fno_signals.risk import RiskState
from fno_signals.signal import generate_signal


# ---- signal ----
def test_signal_bullish(ctx_bull_lowiv):
    s = generate_signal(ctx_bull_lowiv)
    assert s.direction == "bullish" and 0 < s.view_strength <= 1


def test_signal_neutral(ctx_neutral_highiv):
    assert generate_signal(ctx_neutral_highiv).direction == "neutral"


# ---- gates ----
def test_gates_pass_when_liquid(ctx_bull_lowiv):
    assert run_hard_gates(ctx_bull_lowiv).passed


def test_gates_fail_when_illiquid(ctx_illiquid):
    gr = run_hard_gates(ctx_illiquid)
    assert not gr.passed and "liquidity" in gr.reject_reason


# ---- regime ----
def test_iv_regime_buckets():
    assert iv_regime(20) == "low" and iv_regime(50) == "mid" and iv_regime(70) == "high"


def test_route_table_and_credit_block():
    assert route("bullish", "low") == "bull_call_debit"
    assert route("neutral", "high") == "iron_condor"
    assert route("bearish", "high") == "bear_call_credit"
    assert route("bearish", "high", iv_spiking=True) is None   # credit blocked


# ---- structures ----
def test_debit_structure_is_debit(ctx_bull_lowiv):
    s = select_structure("bull_call_debit", ctx_bull_lowiv.chain, ctx_bull_lowiv.spot, 65)
    assert s is not None and len(s.legs) == 2
    assert s.net_premium() > 0                       # debit paid
    assert one_lot_max_loss(s, ctx_bull_lowiv.spot) > 0


def test_credit_structure_is_credit(ctx_neutral_highiv):
    s = select_structure("bull_put_credit", ctx_neutral_highiv.chain,
                         ctx_neutral_highiv.spot, 65)
    assert s is not None and len(s.legs) == 2
    assert s.net_premium() < 0                       # credit received


def test_iron_condor_four_legs(ctx_neutral_highiv):
    s = select_structure("iron_condor", ctx_neutral_highiv.chain,
                         ctx_neutral_highiv.spot, 65)
    assert s is not None and len(s.legs) == 4
    assert one_lot_max_loss(s, ctx_neutral_highiv.spot) > 0


# ---- sizing ----
def test_effective_r_clamps_confidence():
    cfg = SizingConfig(capital=1_000_000, per_trade_risk_pct=1.0)
    assert effective_R(cfg, 1.0) == 10_000
    assert effective_R(cfg, 0.5) == 5_000
    assert effective_R(cfg, 2.0) == 10_000           # clamp at 1.0


def test_size_lots_caps():
    cfg = SizingConfig(capital=1_000_000, per_trade_risk_pct=1.0, max_lots_per_structure=4)
    assert size_lots(10_000, 2_000, cfg) == 4                       # capped at max
    assert size_lots(10_000, 2_000, cfg, portfolio_remaining_R=4_000) == 2
    assert size_lots(10_000, 0, cfg) == 0                           # no finite risk


# ---- risk ----
def test_kill_switch_and_budget():
    rs = RiskState(capital=1_000_000, day_pnl=-40_000, daily_max_loss_pct=3.0)
    assert rs.kill_switch_tripped()
    rs2 = RiskState(capital=1_000_000, day_pnl=-10_000, open_R=20_000,
                    portfolio_risk_limit_pct=5.0)
    assert not rs2.kill_switch_tripped()
    assert rs2.portfolio_remaining_R() == 30_000
    assert rs2.can_add_position()
