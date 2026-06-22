"""§10 Phase 2 — model promotion ladder (pure next_stage)."""
from research.registry import STAGES, next_stage


def test_promotion_ladder():
    assert next_stage("dev") == "shadow"
    assert next_stage("shadow") == "paper"
    assert next_stage("paper") == "live"
    assert next_stage("live") == "live"        # caps at the top rung
    assert next_stage("garbage") == "dev"      # unknown stage resets to dev


def test_stages_order():
    assert STAGES == ("dev", "shadow", "paper", "live")
