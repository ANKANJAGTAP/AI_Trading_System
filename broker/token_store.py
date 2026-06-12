"""Secure daily access-token storage.

Kite access tokens expire daily. We persist the token + the IST trading-day it was
issued to a 0600 file. If a Fernet key is configured the payload is encrypted at
rest; otherwise it is stored plaintext (DEV ONLY — a loud warning is logged). In
production prefer OS keyring / a cloud secret manager (swap this class out).

Validity is keyed to the IST date (the market day), not the container's UTC date,
so a token issued before 05:30 IST isn't mistaken for the previous day's.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet

from common.logging import get_logger
from common.market_time import now_ist

log = get_logger("token_store")


def _today_ist() -> str:
    return now_ist().date().isoformat()


class TokenStore:
    def __init__(self, path: str, encryption_key: str = "") -> None:
        self.path = Path(path)
        self._fernet = Fernet(encryption_key.encode()) if encryption_key else None

    def save(self, access_token: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"access_token": access_token, "date": _today_ist()})
        data = (
            self._fernet.encrypt(payload.encode())
            if self._fernet
            else payload.encode()
        )
        with open(self.path, "wb") as fh:
            fh.write(data)
        os.chmod(self.path, 0o600)
        if not self._fernet:
            log.warning("token_stored_plaintext_dev_only", path=str(self.path))

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        raw = self.path.read_bytes()
        try:
            payload = self._fernet.decrypt(raw).decode() if self._fernet else raw.decode()
            return json.loads(payload)
        except Exception as exc:
            log.error("token_load_failed", error=str(exc))
            return None

    def valid_token_for_today(self) -> str | None:
        data = self.load()
        if data and data.get("date") == _today_ist() and data.get("access_token"):
            return data["access_token"]
        return None
