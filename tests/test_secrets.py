"""#21 — log redaction + token encryption-at-rest policy (pure)."""
from common.secrets import redact_event, token_security_ok


def test_redact_scrubs_secret_keys_only():
    ed = {"event": "login", "api_key": "AKIAabc", "password": "p",
          "Authorization": "Bearer x", "access_token": "t",
          "user": "alice", "count": 3}
    out = redact_event(dict(ed))
    assert out["api_key"] == "***redacted***"
    assert out["password"] == "***redacted***"
    assert out["Authorization"] == "***redacted***"   # case-insensitive
    assert out["access_token"] == "***redacted***"
    # non-sensitive fields untouched
    assert out["user"] == "alice"
    assert out["count"] == 3
    assert out["event"] == "login"


def test_token_security_policy():
    assert token_security_ok("dev", False)[0] is True
    assert token_security_ok("test", False)[0] is True
    assert token_security_ok("local", False)[0] is True
    assert token_security_ok("prod", False)[0] is False     # fail-closed
    assert token_security_ok("prod", True)[0] is True
    assert token_security_ok("staging", False)[0] is False
    assert token_security_ok(None, False)[0] is True        # defaults to dev
