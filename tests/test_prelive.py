"""P0#2 — pre-live check framework: aggregation, coercion, fail-closed, and the
gate it provides to the mode transition. DB-free (mocked checks / state)."""
import asyncio

import pytest

from common.prelive import FAIL, PASS, WARN, CheckResult, PreLiveCheckService


def _run(c):
    return asyncio.run(c)


async def _ok():
    return True


async def _bad():
    return False


async def _warn():
    return (WARN, "soft")


async def _tuple_ev():
    return (PASS, "fine", {"x": 1})


async def _cr():
    return CheckResult("ignored", PASS, "via CheckResult")


async def _boom():
    raise RuntimeError("nope")


def test_all_pass_overall_pass():
    run = _run(PreLiveCheckService([("a", _ok), ("b", _tuple_ev), ("c", _cr)]).run_all())
    assert run["overall"] == PASS and run["failed"] == []
    assert {c["name"] for c in run["checks"]} == {"a", "b", "c"}


def test_one_fail_overall_fail():
    run = _run(PreLiveCheckService([("a", _ok), ("b", _bad)]).run_all())
    assert run["overall"] == FAIL and run["failed"] == ["b"]


def test_warn_does_not_block():
    run = _run(PreLiveCheckService([("a", _ok), ("w", _warn)]).run_all())
    assert run["overall"] == PASS and run["warned"] == ["w"]


def test_probe_exception_is_fail():
    run = _run(PreLiveCheckService([("boom", _boom)]).run_all())
    assert run["overall"] == FAIL and "boom" in run["failed"]
    assert "probe error" in run["checks"][0]["detail"]


def test_evidence_preserved():
    run = _run(PreLiveCheckService([("b", _tuple_ev)]).run_all())
    assert run["checks"][0]["evidence"] == {"x": 1}


def test_persister_receives_run():
    captured = {}

    async def _persist(run):
        captured["run"] = run

    _run(PreLiveCheckService([("a", _ok)], persister=_persist).run_all("alice"))
    assert captured["run"]["operator"] == "alice" and captured["run"]["overall"] == PASS


def test_failing_prelive_blocks_live_transition(monkeypatch):
    import common.mode_transition as mt
    import common.runtime_mode as rm
    from common.errors import ModeTransitionRejected

    store = {}

    async def _gs(k, d=None):
        return store.get(k, d)

    async def _ss(k, v, by="system"):
        store[k] = v

    monkeypatch.setattr(rm, "get_state", _gs)
    monkeypatch.setattr(rm, "set_state", _ss)

    svc = PreLiveCheckService([("a", _ok), ("b", _bad)])

    async def _ks_off():
        return False

    with pytest.raises(ModeTransitionRejected):
        _run(mt.request_transition("live", "op", confirm_token="LIVE",
                                   prelive_runner=svc.run_all, kill_switch_active=_ks_off))


def test_passing_prelive_allows_live_transition(monkeypatch):
    import common.mode_transition as mt
    import common.runtime_mode as rm

    store = {}

    async def _gs(k, d=None):
        return store.get(k, d)

    async def _ss(k, v, by="system"):
        store[k] = v

    monkeypatch.setattr(rm, "get_state", _gs)
    monkeypatch.setattr(rm, "set_state", _ss)

    svc = PreLiveCheckService([("a", _ok), ("w", _warn)])   # warn allowed

    async def _ks_off():
        return False

    new = _run(mt.request_transition("live", "op", confirm_token="LIVE",
                                     prelive_runner=svc.run_all, kill_switch_active=_ks_off))
    assert new.is_live
