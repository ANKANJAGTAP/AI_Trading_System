"""Automated Kite Connect login via TOTP.

Kite access tokens expire daily. This performs the headless login flow:
  1. POST credentials  -> request_id
  2. POST TOTP (2FA)    -> session established
  3. GET connect login  -> redirect carries ?request_token=...
  4. exchange request_token + api_secret -> access_token

The request_token is captured from the redirect chain (or, if the broker
redirects to a custom scheme the HTTP client cannot follow, from the raised
error / response body). Returns the access_token string.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlparse

import time

import pyotp
import requests
from kiteconnect import KiteConnect

from common.errors import BrokerUnavailable
from common.logging import get_logger

log = get_logger("kite_auth")

LOGIN_URL = "https://kite.zerodha.com/api/login"
TWOFA_URL = "https://kite.zerodha.com/api/twofa"
_TOKEN_RE = re.compile(r"request_token=([A-Za-z0-9]+)")


def _extract_request_token(urls: list[str], body: str = "") -> str | None:
    for url in urls:
        params = parse_qs(urlparse(url).query)
        if "request_token" in params:
            return params["request_token"][0]
    match = _TOKEN_RE.search(body or "")
    return match.group(1) if match else None


def kite_auto_login(
    api_key: str,
    api_secret: str,
    user_id: str,
    password: str,
    totp_secret: str,
) -> str:
    if not all([api_key, api_secret, user_id, password, totp_secret]):
        raise ValueError("Missing Kite credentials for automated login")

    session = requests.Session()

    # Step 1 — credentials
    resp = session.post(
        LOGIN_URL, data={"user_id": user_id, "password": password}, timeout=15
    )
    resp.raise_for_status()
    request_id = resp.json()["data"]["request_id"]

    # Step 2 — TOTP 2FA. If the current code is about to roll over, wait for the next
    # window so the code we submit is still valid when it reaches Kite.
    totp = pyotp.TOTP(totp_secret)
    remaining = totp.interval - (int(time.time()) % totp.interval)
    if remaining <= 2:
        time.sleep(remaining + 0.5)
    twofa = totp.now()
    resp = session.post(
        TWOFA_URL,
        data={
            "user_id": user_id,
            "request_id": request_id,
            "twofa_value": twofa,
            "twofa_type": "totp",
            "skip_session": "",
        },
        timeout=15,
    )
    resp.raise_for_status()

    # Step 3 — connect/login server-side redirects to the registered redirect URL
    # carrying ?request_token=... . Follow redirects MANUALLY and read the token
    # straight from the Location header, so we never try to fetch the (usually
    # unreachable) redirect URL itself, e.g. https://127.0.0.1.
    kite = KiteConnect(api_key=api_key)
    url = kite.login_url()
    request_token: str | None = None
    for _ in range(10):
        resp = session.get(url, allow_redirects=False, timeout=15)
        location = resp.headers.get("Location", "")
        if "request_token=" in location:
            request_token = _extract_request_token([location])
            break
        if not location:
            # Terminal page, no redirect: token was not issued. Most common cause
            # on a new app is that it has not been authorised once in a browser.
            request_token = _extract_request_token([resp.url], resp.text)
            break
        url = urljoin(url, location)

    if not request_token:
        # #47: a broker-login runtime failure is a TradingError, so callers can
        # guard the live path with a single `except TradingError`.
        raise BrokerUnavailable(
            "Failed to obtain request_token from Kite login flow. For a new Kite "
            "Connect app, authorise it once in a browser (open the login URL, log "
            "in, approve access), then retry."
        )

    # Step 4 — exchange for access token
    data = kite.generate_session(request_token, api_secret=api_secret)
    access_token = data["access_token"]
    log.info("kite_login_success", user_id=user_id)
    return access_token
