"""P1#13 — engine liveness classifier (ok | degraded | down). Pure."""
from common.heartbeat import DEGRADED, DOWN, OK, heartbeat_status


def test_fresh_all_ok():
    assert heartbeat_status({"db_ok": True, "redis_ok": True}, age_s=5) == OK


def test_no_doc_is_down():
    assert heartbeat_status(None, age_s=5) == DOWN


def test_stale_is_down():
    assert heartbeat_status({"db_ok": True, "redis_ok": True}, age_s=200, max_age_s=90) == DOWN


def test_one_dep_down_is_degraded():
    assert heartbeat_status({"db_ok": False, "redis_ok": True}, age_s=5) == DEGRADED
    assert heartbeat_status({"db_ok": True, "redis_ok": False}, age_s=5) == DEGRADED


def test_both_deps_down_is_down():
    assert heartbeat_status({"db_ok": False, "redis_ok": False}, age_s=5) == DOWN


def test_broker_down_in_live_is_degraded_but_ignored_in_paper():
    doc = {"db_ok": True, "redis_ok": True, "broker_ok": False}
    assert heartbeat_status(doc, age_s=5, live=True) == DEGRADED
    assert heartbeat_status(doc, age_s=5, live=False) == OK
