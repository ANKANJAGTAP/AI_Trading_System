"""Diagnose the Kite automated-login flow step by step.

Prints only SAFE diagnostics — never the password, TOTP, or the actual
request_token (only status codes, JSON status/message fields, redirect hosts, and
booleans). Use to pinpoint where auto-login breaks.

Run: docker compose run --rm --entrypoint python \
       -v "$PWD/scripts:/app/scripts" engine scripts/diag_kite_login.py
"""
from __future__ import annotations

from urllib.parse import parse_qs, urljoin, urlparse

import pyotp
import requests
from kiteconnect import KiteConnect

from config.settings import get_settings

s = get_settings()

print("=== credentials present? ===")
print(
    "api_key:", bool(s.kite_api_key),
    "| api_secret:", bool(s.kite_api_secret),
    "| user_id:", bool(s.kite_user_id),
    "| password:", bool(s.kite_password),
    "| totp_secret:", bool(s.kite_totp_secret),
)

sess = requests.Session()

print("\n=== step 1: POST /api/login (user_id + password) ===")
r1 = sess.post(
    "https://kite.zerodha.com/api/login",
    data={"user_id": s.kite_user_id, "password": s.kite_password},
    timeout=15,
)
print("http status:", r1.status_code)
request_id = None
try:
    j1 = r1.json()
    request_id = (j1.get("data") or {}).get("request_id")
    print("json status:", j1.get("status"), "| has request_id:", bool(request_id),
          "| message:", j1.get("message"), "| error_type:", j1.get("error_type"))
except Exception:
    print("response not JSON; len:", len(r1.text))
if not request_id:
    print("\n>>> STOP: no request_id — user_id/password step failed.")
    raise SystemExit(1)

print("\n=== step 2: POST /api/twofa (TOTP) ===")
totp = pyotp.TOTP(s.kite_totp_secret).now()
print("generated TOTP digits:", len(totp))
r2 = sess.post(
    "https://kite.zerodha.com/api/twofa",
    data={
        "user_id": s.kite_user_id,
        "request_id": request_id,
        "twofa_value": totp,
        "twofa_type": "totp",
    },
    timeout=15,
)
print("http status:", r2.status_code)
try:
    j2 = r2.json()
    print("json status:", j2.get("status"), "| message:", j2.get("message"),
          "| error_type:", j2.get("error_type"))
except Exception:
    print("response not JSON; len:", len(r2.text))

print("\n=== step 3: GET connect/login, follow redirects manually ===")
import re

kite = KiteConnect(api_key=s.kite_api_key)
print("login_url:", kite.login_url())
url = kite.login_url()
captured = False
for hop in range(8):
    r = sess.get(url, allow_redirects=False, timeout=15)
    loc = r.headers.get("Location", "")
    p = urlparse(loc)
    qkeys = sorted(parse_qs(p.query).keys())  # key NAMES only, never values
    print(f"hop{hop}: status={r.status_code} path={p.path or '(none)'} "
          f"host={p.netloc or '(same-host)'} query_keys={qkeys}")
    if "request_token=" in loc:
        captured = True
        break
    if not loc:
        body = r.text
        low = body.lower()
        m = re.search(r"<title>(.*?)</title>", body, re.I | re.S)
        print("  final requested url path:", urlparse(r.url).path)
        print("  page title:", (m.group(1).strip()[:120] if m else "(none)"))
        hits = [kw for kw in (
            "subscription", "inactive", "expired", "invalid", "error",
            "approve", "authorize", "consent", "redirect", "not found",
            "blocked", "disabled", "trial", "billing", "renew",
        ) if kw in low]
        print("  keywords present:", hits or "(none)")
        break
    url = urljoin(url, loc)

print("\n=== RESULT ===")
print("request_token captured:", "YES" if captured else "NO")
