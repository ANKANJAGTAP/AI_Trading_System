"""
Kite daily access-token helper.

Kite's access token expires every trading day, so it must be regenerated each
morning from your API key/secret + login + TOTP. This module:

  * runs that login flow (`generate_access_token`) — best-effort, version-
    dependent on Zerodha's endpoints; verify against your account,
  * stores the token Fernet-ENCRYPTED at TOKEN_STORE_PATH (`save_token`),
  * loads it back, rejecting a stale (not-today) token (`load_token`),
  * `refresh_from_env()` + a CLI tie it together.

Run it on YOUR machine — it reads credentials from your environment and they
never leave it. (Set TOKEN_ENCRYPTION_KEY to a Fernet key; leave empty for
plaintext storage in DEV only.)
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path


# --------------------------------------------------------------------------- #
# encryption
# --------------------------------------------------------------------------- #
def _encrypt(data: bytes, key: str | None) -> bytes:
    if not key:
        return data
    from cryptography.fernet import Fernet
    return Fernet(key.encode() if isinstance(key, str) else key).encrypt(data)


def _decrypt(data: bytes, key: str | None) -> bytes:
    if not key:
        return data
    from cryptography.fernet import Fernet
    return Fernet(key.encode() if isinstance(key, str) else key).decrypt(data)


# --------------------------------------------------------------------------- #
# token store
# --------------------------------------------------------------------------- #
def save_token(access_token: str, path, key: str | None = None) -> Path:
    payload = json.dumps({"access_token": access_token,
                          "date": str(dt.date.today())}).encode()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(_encrypt(payload, key))
    try:
        p.chmod(0o600)            # owner-only
    except OSError:
        pass
    return p


def load_token(path, key: str | None = None, require_today: bool = True) -> str | None:
    """Return the stored access token, or None if missing or (by default) stale."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        obj = json.loads(_decrypt(p.read_bytes(), key))
    except Exception:
        return None
    if require_today and obj.get("date") != str(dt.date.today()):
        return None
    return obj.get("access_token")


# --------------------------------------------------------------------------- #
# login flow (transport — runs in your environment with your creds)
# --------------------------------------------------------------------------- #
def generate_access_token(api_key, api_secret, user_id, password, totp_secret,
                          redirect_url=None, timeout: int = 15) -> str:
    """Automated Kite login (userid+password -> TOTP -> request_token -> session).

    ⚠️ Uses Zerodha's web-login endpoints, which can change — verify against your
    account and the current kiteconnect docs.
    """
    import requests
    import pyotp
    from urllib.parse import urlparse, parse_qs
    from kiteconnect import KiteConnect

    s = requests.Session()
    r = s.post("https://kite.zerodha.com/api/login",
               data={"user_id": user_id, "password": password}, timeout=timeout)
    r.raise_for_status()
    request_id = r.json()["data"]["request_id"]

    s.post("https://kite.zerodha.com/api/twofa",
           data={"user_id": user_id, "request_id": request_id,
                 "twofa_value": pyotp.TOTP(totp_secret).now(), "twofa_type": "totp"},
           timeout=timeout).raise_for_status()

    kite = KiteConnect(api_key=api_key)
    try:                                   # final redirect carries ?request_token=...
        final_url = s.get(kite.login_url(), allow_redirects=True, timeout=timeout).url
    except requests.exceptions.ConnectionError as e:   # redirect to 127.0.0.1 refuses
        final_url = e.request.url if e.request is not None else ""
    token = parse_qs(urlparse(final_url).query).get("request_token", [None])[0]
    if not token:
        raise RuntimeError("request_token not found in redirect; check KITE_REDIRECT_URL.")
    return kite.generate_session(token, api_secret=api_secret)["access_token"]


def refresh_from_env() -> Path:
    """Read creds from env, mint today's token, store it encrypted. Returns path."""
    token = generate_access_token(
        os.environ["KITE_API_KEY"], os.environ["KITE_API_SECRET"],
        os.environ["KITE_USER_ID"], os.environ["KITE_PASSWORD"],
        os.environ["KITE_TOTP_SECRET"], os.environ.get("KITE_REDIRECT_URL"),
    )
    path = os.environ.get("TOKEN_STORE_PATH", ".secrets/kite_token.json")
    save_token(token, path, os.environ.get("TOKEN_ENCRYPTION_KEY") or None)
    return Path(path)


def manual_refresh_from_env() -> Path:
    """Reliable fallback: you log in via the browser; paste back the request_token.

    No password/TOTP is handled here — you authenticate on Zerodha's own page.
    """
    from urllib.parse import urlparse, parse_qs
    from kiteconnect import KiteConnect

    kite = KiteConnect(api_key=os.environ["KITE_API_KEY"])
    print("\n1) Open this URL in your browser and log in (Zerodha's own page):\n")
    print("   " + kite.login_url() + "\n")
    print("2) After login it redirects to your redirect URL (e.g. 127.0.0.1). The")
    print("   page won't load — that's expected. Copy the FULL address from the")
    print("   browser bar (it contains '...?request_token=XXXX&action=login...').\n")
    raw = input("3) Paste the request_token (or the whole redirected URL) here: ").strip()
    token = raw
    if "request_token=" in raw:
        token = parse_qs(urlparse(raw).query).get("request_token", [raw])[0]

    data = kite.generate_session(token, api_secret=os.environ["KITE_API_SECRET"])
    path = os.environ.get("TOKEN_STORE_PATH", ".secrets/kite_token.json")
    save_token(data["access_token"], path, os.environ.get("TOKEN_ENCRYPTION_KEY") or None)
    return Path(path)


if __name__ == "__main__":
    import sys
    fn = manual_refresh_from_env if "--manual" in sys.argv else refresh_from_env
    p = fn()
    print(f"\nAccess token stored at {p}")
