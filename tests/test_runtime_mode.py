"""P0#1 — atomic execution mode: RuntimeModeState + validated transitions.

DB-free: the config_state layer is monkeypatched with an in-memory dict, and the
async functions are driven via asyncio.run, so these run without Postgres.
"""
import asyncio

import pytest

import common.runtime_mode as rm
import common.mode_transition as mt
from common.errors import ModeTransitionRejected


class FakeStore:
    def __init__(self):
        self.d = {}

    async def get_state(self, key, default=None):
        return self.d.get(key, default)

    async def set_state(self, key, value, updated_by="system"):
        self.d[key] = value


@pytest.fixture
def store(monkeypatch):
    s = FakeStore()
    monkeypatch.setattr(rm, "get_state", s.get_state)
    monkeypatch.setattr(rm, "set_state", s.set_state)
    return s


def _run(coro):
    return asyncio.run(coro)


async def _all_pass():
    return {"token": True, "broker": True}


async def _one_fail():
    return {"token": True, "broker": False}


async def _ks_off():
    return False


async def _ks_on():
    return True


# ---- RuntimeModeState ---------------------------------------------------- #
def test_default_is_paper(store):
    st = _run(rm.load_runtime_mode())
    assert st.mode == "simulated_fill"
    assert st.capital_source == "paper_static"
    assert st.risk_profile == "paper"
    assert not st.is_live and not st.use_broker_capital


def test_legacy_execution_mode_fallback(store):
    store.d["execution_mode"] = "live"
    st = _run(rm.load_runtime_mode())
    assert st.is_live and st.use_broker_capital and st.position_namespace == "live"


def test_derive_fail_closed_to_paper():
    paper = rm.derive_for_mode("not_a_mode")
    assert paper.mode == "simulated_fill" and paper.capital_source == "paper_static"


def test_no_state_combo_is_live_with_paper_capital():
    for m in ("simulated_fill", "live", "garbage"):
        st = rm.derive_for_mode(m)
        assert not (st.is_live and st.capital_source == "paper_static")


def test_write_bumps_version_and_mirrors_legacy(store):
    _run(rm.write_runtime_mode(rm.derive_for_mode("live"), "op"))
    assert store.d["execution_mode"] == "live"          # legacy mirror
    st = _run(rm.load_runtime_mode())
    assert st.is_live and st.version == 1
    _run(rm.write_runtime_mode(rm.derive_for_mode("simulated_fill"), "op"))
    st2 = _run(rm.load_runtime_mode())
    assert st2.mode == "simulated_fill" and st2.version == 2


# ---- transition validation ---------------------------------------------- #
def test_live_requires_confirm_token(store):
    with pytest.raises(ModeTransitionRejected):
        _run(mt.request_transition("live", "op", confirm_token=None,
                                   prelive_runner=_all_pass, kill_switch_active=_ks_off))


def test_live_blocked_by_failing_check(store):
    with pytest.raises(ModeTransitionRejected) as e:
        _run(mt.request_transition("live", "op", confirm_token="LIVE",
                                   prelive_runner=_one_fail, kill_switch_active=_ks_off))
    assert "broker" in str(e.value)


def test_live_blocked_by_killswitch(store):
    with pytest.raises(ModeTransitionRejected):
        _run(mt.request_transition("live", "op", confirm_token="LIVE",
                                   prelive_runner=_all_pass, kill_switch_active=_ks_on))


def test_live_requires_prelive_runner_fail_closed(store):
    with pytest.raises(ModeTransitionRejected):
        _run(mt.request_transition("live", "op", confirm_token="LIVE"))


def test_to_live_success_writes_state(store):
    new = _run(mt.request_transition("live", "op", confirm_token="LIVE",
                                     prelive_runner=_all_pass, kill_switch_active=_ks_off))
    assert new.is_live and new.use_broker_capital
    assert store.d["execution_mode"] == "live"


def test_live_to_paper_blocked_with_open_positions(store):
    _run(rm.write_runtime_mode(rm.derive_for_mode("live"), "op"))

    async def _open():
        return 2

    with pytest.raises(ModeTransitionRejected):
        _run(mt.request_transition("simulated_fill", "op", open_live_positions=_open))


def test_live_to_paper_allowed_with_override(store):
    _run(rm.write_runtime_mode(rm.derive_for_mode("live"), "op"))

    async def _open():
        return 2

    new = _run(mt.request_transition("simulated_fill", "op", open_live_positions=_open,
                                     allow_unflattened_downgrade=True))
    assert new.mode == "simulated_fill"


def test_transition_idempotent_when_already_in_target(store):
    cur = _run(mt.request_transition("simulated_fill", "op"))
    assert cur.mode == "simulated_fill"
