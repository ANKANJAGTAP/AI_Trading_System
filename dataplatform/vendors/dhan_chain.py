"""
DhanHQ option-chain vendor — real Greeks / IV / OI / volume / best bid-ask.

Replaces the old TrueData EOD-chain adapter. Dhan's option chain is a **live
snapshot** (paid Data API), not historical EOD: `POST /v2/optionchain` returns,
per strike, both CE and PE legs carrying `greeks{delta,theta,gamma,vega}`,
`implied_volatility`, `last_price`, `oi`, `previous_oi`, `volume` and the top
`bid/ask`; `POST /v2/optionchain/expirylist` returns the active expiries.

  - pure ``parse_expiry_list(resp)``                 -> [date, ...]
  - pure ``parse_option_chain(resp, expiry, asof)``  -> rich per-leg row dicts
  - ``DhanChainAdapter(BarVendorAdapter)``           -> live fetch via env creds;
        ``fetch_eod_fno()`` returns the canonical EOD frame for the backtest lake
        (snapshot LTP as OHLC) and ``fetch_chain_rows()`` returns the full
        greeks/IV/bid-ask rows for the F&O sleeve + Structure Lab.

Credentials are env-only (DHAN_ACCESS_TOKEN = JWT, DHAN_CLIENT_ID) — never from
chat or the repo, same as ``dataplatform.vendors`` historical Dhan path.

Rate limit: Dhan enforces **one option-chain request every 3 seconds** — the
snapshot script throttles accordingly.

⚠️ Underlying security ids/segments below come from Dhan's annexure and are the
common index values; verify against your plan's instrument list / annexure and
override via ``scrip_map=`` if any differ.
"""
from __future__ import annotations

import datetime as dt
import os

from .bar_vendor import BarVendorAdapter
from .fieldmap import FieldMap

_BASE = "https://api.dhan.co/v2"

# Dhan annexure — index underlyings (IDX_I segment). VERIFY against your plan.
DHAN_UNDERLYING: dict[str, tuple[int, str]] = {
    "NIFTY": (13, "IDX_I"),
    "BANKNIFTY": (25, "IDX_I"),
    "FINNIFTY": (27, "IDX_I"),
    "SENSEX": (51, "IDX_I"),
    "BANKEX": (69, "IDX_I"),
}

# Snapshot LTP fills OHLC (a chain snapshot has no intrabar OHLC); source for lineage.
DHAN_CHAIN_FIELDMAP = FieldMap(
    open="open", high="high", low="low", close="close", volume="volume",
    strike="strike", opt_type="opt_type", expiry="expiry", oi="oi",
    source="dhan",
)

_GREEK_KEYS = ("delta", "theta", "gamma", "vega")


def _num(v):
    """Coerce to float, or None (Dhan sometimes sends 0/"" for empty legs)."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _leg_row(leg, strike: float, opt_type: str, expiry, asof, underlying, spot):
    """One CE/PE leg dict -> a rich canonical+greeks row, or None if not a dict."""
    if not isinstance(leg, dict):
        return None
    g = leg.get("greeks") or {}
    ltp = _num(leg.get("last_price"))
    return {
        "trade_date": asof, "asof": asof, "expiry": expiry,
        "underlying": underlying, "underlying_ltp": spot,
        "strike": float(strike), "opt_type": opt_type,
        # OHLC: a snapshot has only LTP — stamp it across so the canonical lake is valid
        "open": ltp, "high": ltp, "low": ltp, "close": ltp, "ltp": ltp,
        "volume": int(_num(leg.get("volume")) or 0),
        "oi": int(_num(leg.get("oi")) or 0),
        "previous_oi": int(_num(leg.get("previous_oi")) or 0),
        "iv": _num(leg.get("implied_volatility")),
        "delta": _num(g.get("delta")), "theta": _num(g.get("theta")),
        "gamma": _num(g.get("gamma")), "vega": _num(g.get("vega")),
        "bid": _num(leg.get("top_bid_price")), "ask": _num(leg.get("top_ask_price")),
        "bid_qty": int(_num(leg.get("top_bid_quantity")) or 0),
        "ask_qty": int(_num(leg.get("top_ask_quantity")) or 0),
    }


def parse_option_chain(resp, *, expiry, asof=None, underlying=None) -> list[dict]:
    """Dhan ``/optionchain`` JSON -> list of per-leg row dicts (CE + PE per strike).

    Pure. Tolerates the payload at the top level or under ``data``. ``expiry`` and
    ``asof`` (dates or ISO strings) are stamped on every row. Empty legs — no LTP
    *and* no OI — are skipped so the chain isn't padded with dead strikes.
    """
    if not resp:
        return []
    data = resp.get("data", resp) if isinstance(resp, dict) else {}
    oc = (data or {}).get("oc") or {}
    spot = _num((data or {}).get("last_price"))
    rows: list[dict] = []
    for strike_key, legs in oc.items():
        try:
            strike = float(strike_key)
        except (TypeError, ValueError):
            continue
        if not isinstance(legs, dict):
            continue
        for opt_type, key in (("CE", "ce"), ("PE", "pe")):
            row = _leg_row(legs.get(key), strike, opt_type, expiry, asof, underlying, spot)
            if row is None:
                continue
            if not row["close"] and not row["oi"]:      # dead strike
                continue
            rows.append(row)
    rows.sort(key=lambda r: (r["strike"], r["opt_type"]))
    return rows


def parse_expiry_list(resp) -> list[dt.date]:
    """Dhan ``/optionchain/expirylist`` JSON -> sorted [date, ...] (ISO strings tolerated)."""
    if not resp:
        return []
    data = resp.get("data", resp) if isinstance(resp, dict) else resp
    out: list[dt.date] = []
    for d in data or []:
        if isinstance(d, dt.date):
            out.append(d)
        elif isinstance(d, str):
            try:
                out.append(dt.date.fromisoformat(d[:10]))
            except ValueError:
                continue
    return sorted(set(out))


class DhanChainAdapter(BarVendorAdapter):
    """Live Dhan option chain (real greeks/IV/OI/bid-ask).

    A *snapshot* vendor: it records the chain as-of now, so it forward-fills the
    options lake rather than backfilling history. Plugs into the same
    ``fetch_eod_fno`` / ``run_backfill`` pipeline as the bhavcopy + GDFL adapters.
    """

    id = "dhan_chain"
    fieldmap = DHAN_CHAIN_FIELDMAP
    required_env = ("DHAN_ACCESS_TOKEN", "DHAN_CLIENT_ID")

    def __init__(self, underlyings=("NIFTY", "FINNIFTY", "SENSEX"),
                 scrip_map: dict | None = None, n_expiries: int = 2, timeout: int = 30):
        super().__init__(underlyings)
        self.scrip_map = dict(DHAN_UNDERLYING)
        if scrip_map:
            self.scrip_map.update(scrip_map)
        self.n_expiries = n_expiries          # front weekly + next, by default
        self.timeout = timeout

    # -- transport (single REST touch-point) ----------------------------
    def _headers(self) -> dict:
        c = self._creds()
        return {"access-token": c["DHAN_ACCESS_TOKEN"], "client-id": c["DHAN_CLIENT_ID"],
                "Content-Type": "application/json"}

    def _post(self, path: str, body: dict) -> dict:
        import requests          # lazy import; only needed with live creds
        r = requests.post(f"{_BASE}{path}", json=body, headers=self._headers(),
                          timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"Dhan {path} HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    def _scrip(self, underlying: str) -> tuple[int, str]:
        if underlying not in self.scrip_map:
            raise KeyError(f"no Dhan scrip id for {underlying!r} (pass scrip_map=...)")
        return self.scrip_map[underlying]

    # -- public fetches -------------------------------------------------
    def expiry_list(self, underlying: str) -> list[dt.date]:
        sid, seg = self._scrip(underlying)
        return parse_expiry_list(self._post(
            "/optionchain/expirylist", {"UnderlyingScrip": sid, "UnderlyingSeg": seg}))

    def chain_snapshot(self, underlying: str, expiry) -> dict:
        """Raw ``/optionchain`` JSON for one underlying + expiry (date or ISO str)."""
        sid, seg = self._scrip(underlying)
        exp = expiry.isoformat() if hasattr(expiry, "isoformat") else str(expiry)
        return self._post("/optionchain",
                          {"UnderlyingScrip": sid, "UnderlyingSeg": seg, "Expiry": exp})

    def fetch_chain_rows(self, underlying: str, expiry=None, asof=None) -> list[dict]:
        """Rich per-leg rows (greeks/IV/OI/bid-ask) for one expiry (default: nearest)."""
        if expiry is None:
            exps = self.expiry_list(underlying)
            if not exps:
                return []
            expiry = exps[0]
        resp = self.chain_snapshot(underlying, expiry)
        return parse_option_chain(resp, expiry=expiry,
                                  asof=asof or dt.date.today(), underlying=underlying)

    # -- canonical EOD path (BarVendorAdapter.fetch_eod_fno) ------------
    def _fetch_raw_chain(self, underlying: str, trade_date: dt.date):
        import pandas as pd
        rows: list[dict] = []
        for expiry in self.expiry_list(underlying)[: self.n_expiries]:
            rows.extend(self.fetch_chain_rows(underlying, expiry, asof=trade_date))
        return pd.DataFrame(rows)


def chain_rows_to_records(rows: list[dict]) -> list[dict]:
    """Trim the rich rows to a stable, storage-friendly record set (greeks kept).

    Useful for persisting a snapshot to a Parquet/CSV lake or an option-chain table
    without dragging adapter-internal scratch columns along. Pure.
    """
    keep = ("asof", "expiry", "underlying", "underlying_ltp", "strike", "opt_type",
            "ltp", "volume", "oi", "previous_oi", "iv",
            "delta", "theta", "gamma", "vega", "bid", "ask", "bid_qty", "ask_qty")
    out = []
    for r in rows:
        rec = {k: r.get(k) for k in keep}
        for d in ("asof", "expiry"):
            v = rec.get(d)
            if hasattr(v, "isoformat"):
                rec[d] = v.isoformat()
        out.append(rec)
    return out
