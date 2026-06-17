"""P1#8 — mode+account scoping is pure and fail-closed; the SQL filter always
restricts by mode so paper and live rows never mix."""
import types

from risk.scope import position_scope, where_clause


def _state(ns="simulated_fill", acct=None):
    return types.SimpleNamespace(position_namespace=ns, broker_account_id=acct)


def test_paper_scope_defaults_account_paper():
    assert position_scope(_state("simulated_fill")) == {"mode": "simulated_fill", "account_id": "paper"}


def test_live_scope_carries_account():
    assert position_scope(_state("live", "ZA1234")) == {"mode": "live", "account_id": "ZA1234"}


def test_unreadable_state_fails_closed_to_paper():
    s = position_scope(object())   # no attributes at all
    assert s["mode"] == "simulated_fill" and s["account_id"] == "paper"


def test_where_clause_mode_only_for_paper():
    sql, args = where_clause({"mode": "simulated_fill", "account_id": "paper"})
    assert sql == "mode = $1" and args == ["simulated_fill"]


def test_where_clause_adds_account_for_live():
    sql, args = where_clause({"mode": "live", "account_id": "ZA1234"})
    assert sql == "mode = $1 AND account_id = $2" and args == ["live", "ZA1234"]


def test_where_clause_respects_start_index():
    sql, args = where_clause({"mode": "live", "account_id": "ZA1234"}, start_idx=3)
    assert "$3" in sql and "$4" in sql and args == ["live", "ZA1234"]
