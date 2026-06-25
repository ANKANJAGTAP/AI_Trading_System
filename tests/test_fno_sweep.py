"""fno_sweep pure helpers (no lake/engine — heavy imports live inside _run)."""
import importlib.util
import os
from dataclasses import dataclass, field

import pytest

_PATH = os.path.join(os.path.dirname(__file__), "..", "scripts", "fno_sweep.py")
_spec = importlib.util.spec_from_file_location("fno_sweep", _PATH)
fs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fs)


@dataclass
class _Gate:
    max_dte: int = 45
    min_atm_oi: int = 5000


@dataclass
class _Cfg:
    width_steps: int = 2
    gate: _Gate = field(default_factory=_Gate)


def test_coerce_value_types():
    assert fs.coerce_value("30") == 30 and isinstance(fs.coerce_value("30"), int)
    assert fs.coerce_value("0.5") == 0.5
    assert fs.coerce_value("true") is True
    assert fs.coerce_value("wide") == "wide"


def test_build_grid():
    grid = fs.build_grid("gate.max_dte", ["7", "30", ""])
    assert grid == [
        {"label": "max_dte=7", "path": "gate.max_dte", "value": 7},
        {"label": "max_dte=30", "path": "gate.max_dte", "value": 30},
    ]  # blank skipped


def test_set_decision_param_nested_and_immutable_source():
    base = _Cfg()
    out = fs.set_decision_param(base, "gate.max_dte", 7)
    assert out.gate.max_dte == 7
    assert base.gate.max_dte == 45        # original untouched (deep-copied)
    top = fs.set_decision_param(base, "width_steps", 3)
    assert top.width_steps == 3 and base.width_steps == 2


def test_set_decision_param_bad_path_raises():
    with pytest.raises(AttributeError):
        fs.set_decision_param(_Cfg(), "gate.nope", 1)


def test_trades_to_returns_rows():
    recs = [{"entry_date": "2024-07-25 00:00:00", "net": 1200.0, "name": "bull_put"},
            {"entry_date": "2024-08-01", "net": -300.0}]
    rows = fs.trades_to_returns_rows(recs)
    assert rows == [{"ts": "2024-07-25", "pnl": 1200.0}, {"ts": "2024-08-01", "pnl": -300.0}]
    assert fs.trades_to_returns_rows([]) == []
