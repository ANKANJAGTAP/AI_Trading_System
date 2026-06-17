"""#19/#20 — scoped tokens, bearer parsing, WS token source preference, rate limiter.
All pure; settings is faked with SimpleNamespace (configured_tokens uses getattr)."""
from types import SimpleNamespace

from api.auth import (ADMIN, OPERATOR, READ, TRADER, bearer, configured_tokens,
                      level_for, rate_ok, ws_token_from)


def _settings(**kw):
    base = dict(api_auth_token="", api_token_readonly="", api_token_operator="",
                api_token_trader="", api_token_admin="")
    base.update(kw)
    return SimpleNamespace(**base)


def test_legacy_single_token_is_admin_backward_compatible():
    t = configured_tokens(_settings(api_auth_token="legacy"))
    assert t == {"legacy": ADMIN}
    assert level_for("legacy", t) == ADMIN
    assert level_for("nope", t) == 0
    assert level_for(None, t) == 0


def test_no_tokens_means_open_control_plane():
    assert configured_tokens(_settings()) == {}


def test_scoped_tokens_map_to_levels():
    t = configured_tokens(_settings(api_token_readonly="r", api_token_operator="o",
                                    api_token_trader="t", api_token_admin="a"))
    assert level_for("r", t) == READ
    assert level_for("o", t) == OPERATOR
    assert level_for("t", t) == TRADER
    assert level_for("a", t) == ADMIN
    assert READ < OPERATOR < TRADER < ADMIN


def test_bearer_parsing():
    assert bearer("Bearer abc") == "abc"
    assert bearer("Basic abc") is None
    assert bearer(None) is None


def test_ws_token_prefers_header_then_subprotocol_then_query():
    assert ws_token_from({"authorization": "Bearer H"}, {"token": "Q"}) == ("H", "header")
    assert ws_token_from({"sec-websocket-protocol": "bearer, S"}, {"token": "Q"}) == ("S", "subprotocol")
    assert ws_token_from({}, {"token": "Q"}) == ("Q", "query")
    assert ws_token_from({}, {}) == (None, "none")


def test_rate_ok_allows_then_blocks_then_slides():
    key = "ut:rate"
    assert all(rate_ok(key, 3, 60, now=100.0 + i) for i in range(3))  # 3 allowed
    assert rate_ok(key, 3, 60, now=104.0) is False                    # 4th blocked
    assert rate_ok(key, 3, 60, now=200.0) is True                     # window slid past
