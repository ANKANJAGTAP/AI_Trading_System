"""Pure secret-handling helpers (#21): log redaction + token-encryption policy.

No I/O — safe to import anywhere (logging config, pre-live checks, tests).
"""
from __future__ import annotations

# Substrings that mark a log field as sensitive (matched case-insensitively).
SENSITIVE_HINTS = (
    "token", "password", "secret", "authorization", "access_token",
    "api_key", "apikey", "totp", "fernet", "credential",
)


def redact_event(event_dict: dict) -> dict:
    """Scrub values of keys that look secret. Mutates and returns the dict so a
    token/password/api-key can never reach the logs even if passed by mistake."""
    for k in list(event_dict.keys()):
        try:
            lk = str(k).lower()
        except Exception:
            continue
        if any(h in lk for h in SENSITIVE_HINTS):
            event_dict[k] = "***redacted***"
    return event_dict


def token_security_ok(env: str | None, has_encryption_key: bool) -> tuple[bool, str]:
    """Encryption-at-rest policy for the stored broker token. Dev/local/test may
    keep plaintext; any other environment MUST configure an encryption key. This
    is fail-closed for live (surfaced as a pre-live FAIL), never a startup crash —
    paper/sim is unaffected."""
    e = (env or "dev").strip().lower()
    if e in ("dev", "local", "test"):
        return True, f"{e}: plaintext token permitted"
    if not has_encryption_key:
        return False, "token encryption key required outside dev"
    return True, "token encryption configured"
