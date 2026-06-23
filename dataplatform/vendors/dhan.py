"""DhanHQ historical-data vendor (free REST: daily + intraday OHLCV).

    POST https://api.dhan.co/v2/charts/historical   (daily, back to inception)
    POST https://api.dhan.co/v2/charts/intraday      (1/5/15/30/60-min, last 5y)

Auth is the `access-token` header (a JWT from the Dhan developer portal). The
response is COLUMNAR — {open[], high[], low[], close[], volume[], open_interest[],
timestamp[]} (epoch) — which we transpose to the platform's candle rows. Dhan keys
data by `securityId`, so `parse_scrip_master` maps a tradingsymbol to its id.

Credentials come from the environment ONLY (DHAN_ACCESS_TOKEN / DHAN_CLIENT_ID) —
never hardcode the token. The pure transforms here are unit-tested; the HTTP calls
run on the server (the SDK-free `requests` transport).
"""
from __future__ import annotations

import csv
import io
import os
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
_BASE = "https://api.dhan.co/v2"

# system interval tag -> Dhan intraday `interval` value ("day" uses the daily endpoint)
DHAN_INTERVAL = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "60m": "60"}


def dhan_to_candle_rows(resp: dict, token: int, interval: str, tz=IST) -> list[tuple]:
    """Columnar Dhan response -> candle rows (ts, token, interval, open, high, low,
    close, volume, oi). Skips bars with no close/timestamp; volume/oi default 0. Pure."""
    if not resp:
        return []
    o, h, l = resp.get("open") or [], resp.get("high") or [], resp.get("low") or []
    c, v = resp.get("close") or [], resp.get("volume") or []
    oi, ts = resp.get("open_interest") or [], resp.get("timestamp") or []
    n = min(len(o), len(h), len(l), len(c), len(ts))
    rows = []
    for i in range(n):
        if c[i] is None or ts[i] is None:
            continue
        dt = datetime.fromtimestamp(int(ts[i]), tz)
        rows.append((dt, int(token), interval, float(o[i]), float(h[i]), float(l[i]),
                     float(c[i]),
                     int(v[i]) if i < len(v) and v[i] is not None else 0,
                     int(oi[i]) if i < len(oi) and oi[i] is not None else 0))
    return rows


def parse_scrip_master(csv_text: str) -> dict:
    """Parse a Dhan scrip-master CSV -> {(EXCH, TRADINGSYMBOL): {security_id, segment,
    instrument}}. Columns are matched fuzzily so it survives header-name variants. Pure."""
    out: dict = {}
    reader = csv.DictReader(io.StringIO(csv_text))
    cols = reader.fieldnames or []
    if not cols:
        return out

    def find(*needles):
        for col in cols:
            cl = col.lower()
            if all(nd in cl for nd in needles):
                return col
        return None

    c_id = find("security", "id") or find("securityid")
    c_sym = find("trading", "symbol") or find("symbol")
    c_exch, c_seg, c_inst = find("exch"), find("segment"), find("instrument")
    if not (c_id and c_sym):
        return out
    for r in reader:
        sym = (r.get(c_sym) or "").strip().upper()
        sid = (r.get(c_id) or "").strip()
        if not sym or not sid:
            continue
        out[((r.get(c_exch) or "").strip().upper() if c_exch else "", sym)] = {
            "security_id": sid,
            "segment": (r.get(c_seg) or "").strip() if c_seg else "",
            "instrument": (r.get(c_inst) or "").strip() if c_inst else "",
        }
    return out


class DhanHistorical:
    """DhanHQ historical REST client (daily + intraday). Creds from env; lazy requests."""

    def __init__(self, access_token: str | None = None, client_id: str | None = None) -> None:
        self.access_token = access_token or os.environ.get("DHAN_ACCESS_TOKEN", "")
        self.client_id = client_id or os.environ.get("DHAN_CLIENT_ID", "")

    def available(self) -> bool:
        return bool(self.access_token)

    def _post(self, path: str, body: dict) -> dict:
        import requests
        headers = {"Accept": "application/json", "Content-Type": "application/json",
                   "access-token": self.access_token}
        if self.client_id:
            headers["client-id"] = self.client_id
        resp = requests.post(f"{_BASE}{path}", json=body, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def daily(self, security_id, exchange_segment: str, instrument: str,
              from_date: str, to_date: str, oi: bool = False) -> dict:
        return self._post("/charts/historical", {
            "securityId": str(security_id), "exchangeSegment": exchange_segment,
            "instrument": instrument, "expiryCode": 0,
            "oi": "true" if oi else "false", "fromDate": from_date, "toDate": to_date})

    def intraday(self, security_id, exchange_segment: str, instrument: str, interval: str,
                 from_date: str, to_date: str, oi: bool = False) -> dict:
        return self._post("/charts/intraday", {
            "securityId": str(security_id), "exchangeSegment": exchange_segment,
            "instrument": instrument, "interval": str(interval),
            "oi": "true" if oi else "false", "fromDate": from_date, "toDate": to_date})
