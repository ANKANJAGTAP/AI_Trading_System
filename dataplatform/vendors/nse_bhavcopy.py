"""
NSE F&O EOD bhavcopy adapter (free) — NIFTY & FINNIFTY index derivatives.

Supports BOTH formats:
  * UDiFF "common bhavcopy" (NSE switched to this in mid-2024)
  * legacy `fo<DDMONYYYY>bhav.csv.zip`

The download URLs and the requirement for browser-like headers/cookies change
periodically; the parsing functions are kept PURE (str -> DataFrame) so they can
be unit-tested offline and reused regardless of how the bytes were obtained.

NOTE: exchange data is licensed. Use within NSE's terms; keep raw files private.
"""
from __future__ import annotations

import datetime as dt
import io
import zipfile

import pandas as pd

from .base import VendorAdapter, validate_canonical

_PHASE_A_NSE = {"NIFTY", "FINNIFTY", "BANKNIFTY"}

# Browser-like headers NSE expects. A real run should first GET https://www.nseindia.com
# to obtain cookies, then reuse the session for the archive request.
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def udiff_url(d: dt.date) -> str:
    return (f"https://nsearchives.nseindia.com/content/fo/"
            f"BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip")


def legacy_url(d: dt.date) -> str:
    mon = _MONTHS[d.month - 1]
    return (f"https://archives.nseindia.com/content/historical/DERIVATIVES/"
            f"{d.year}/{mon}/fo{d.day:02d}{mon}{d.year}bhav.csv.zip")


def _parse_date_any(s: str) -> dt.date:
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y", "%Y%m%d"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # UDiFF sometimes uses e.g. "2024-07-25" or with time; take first 10 chars
    return dt.datetime.strptime(s[:10], "%Y-%m-%d").date()


def coalesce_untraded_ohlc(out: pd.DataFrame) -> pd.DataFrame:
    """Make EOD option-chain bars internally consistent for the lake. Pure.

    NSE bhavcopy reports UNTRADED contracts (volume 0) with degenerate OHLC
    (zeros) but a real settlement mark — so `close`/`settle` sit outside the
    [low,high]=[0,0] band and a naive quality check rejects the whole day. We:
      1. mark each untraded bar at its settlement price (fallback close), so an
         illiquid strike still carries a sane EOD price (its OI is preserved), and
      2. guarantee `high >= max(o,c)` and `low <= min(o,c)` on every row, so
         open/close always lie within [low,high].
    Traded bars keep their real open/close; only the high/low envelope is widened
    if a vendor quirk left it inconsistent.
    """
    price = ["open", "high", "low", "close"]
    out[price] = out[price].astype("float64")          # avoid int64/float dtype clash on assign
    untraded = out["volume"].fillna(0) <= 0
    if untraded.any():
        mark = out["settle"].where(out["settle"] > 0, out["close"]).astype("float64")
        for c in price:
            out.loc[untraded, c] = mark[untraded]
    out["high"] = out[price].max(axis=1)
    out["low"] = out[price].min(axis=1)
    return out


# --------------------------------------------------------------------------- #
# PURE parsers (testable with CSV fixtures, no network)
# --------------------------------------------------------------------------- #
def parse_udiff_csv(text: str) -> pd.DataFrame:
    """Parse NSE UDiFF common-bhavcopy CSV text into the canonical schema."""
    raw = pd.read_csv(io.StringIO(text))
    raw.columns = [c.strip() for c in raw.columns]
    # FinInstrmTp: IDF=index fut, IDO=index opt, STF/STO=stock (skipped)
    keep = raw[raw["FinInstrmTp"].isin(["IDF", "IDO"])].copy()
    keep = keep[keep["TckrSymb"].isin(_PHASE_A_NSE)]

    out = pd.DataFrame()
    out["trade_date"] = keep["TradDt"].map(_parse_date_any)
    out["underlying"] = keep["TckrSymb"]
    out["exchange"] = "NSE"
    out["instrument"] = keep["FinInstrmTp"].map({"IDF": "FUT", "IDO": "OPT"})
    out["opt_type"] = keep.get("OptnTp", "").fillna("").replace({"XX": ""})
    out["expiry"] = keep["XpryDt"].map(_parse_date_any)
    out["strike"] = pd.to_numeric(keep.get("StrkPric", 0), errors="coerce").fillna(0.0)
    out["open"] = pd.to_numeric(keep["OpnPric"], errors="coerce")
    out["high"] = pd.to_numeric(keep["HghPric"], errors="coerce")
    out["low"] = pd.to_numeric(keep["LwPric"], errors="coerce")
    out["close"] = pd.to_numeric(keep["ClsPric"], errors="coerce")
    out["settle"] = pd.to_numeric(keep["SttlmPric"], errors="coerce")
    out["volume"] = pd.to_numeric(keep["TtlTradgVol"], errors="coerce").fillna(0).astype("int64")
    out["oi"] = pd.to_numeric(keep["OpnIntrst"], errors="coerce").fillna(0).astype("int64")
    out["oi_change"] = pd.to_numeric(keep["ChngInOpnIntrst"], errors="coerce").fillna(0).astype("int64")
    out["source"] = "nse_bhavcopy_udiff"
    return validate_canonical(coalesce_untraded_ohlc(out))


def parse_legacy_csv(text: str) -> pd.DataFrame:
    """Parse legacy NSE F&O bhavcopy CSV text into the canonical schema."""
    raw = pd.read_csv(io.StringIO(text))
    raw.columns = [c.strip() for c in raw.columns]
    raw = raw.loc[:, ~raw.columns.str.startswith("Unnamed")]
    keep = raw[raw["INSTRUMENT"].isin(["FUTIDX", "OPTIDX"])].copy()
    keep = keep[keep["SYMBOL"].isin(_PHASE_A_NSE)]

    out = pd.DataFrame()
    out["trade_date"] = keep["TIMESTAMP"].map(_parse_date_any)
    out["underlying"] = keep["SYMBOL"]
    out["exchange"] = "NSE"
    out["instrument"] = keep["INSTRUMENT"].map({"FUTIDX": "FUT", "OPTIDX": "OPT"})
    out["opt_type"] = keep["OPTION_TYP"].replace({"XX": ""}).fillna("")
    out["expiry"] = keep["EXPIRY_DT"].map(_parse_date_any)
    out["strike"] = pd.to_numeric(keep["STRIKE_PR"], errors="coerce").fillna(0.0)
    out["open"] = pd.to_numeric(keep["OPEN"], errors="coerce")
    out["high"] = pd.to_numeric(keep["HIGH"], errors="coerce")
    out["low"] = pd.to_numeric(keep["LOW"], errors="coerce")
    out["close"] = pd.to_numeric(keep["CLOSE"], errors="coerce")
    out["settle"] = pd.to_numeric(keep["SETTLE_PR"], errors="coerce")
    out["volume"] = pd.to_numeric(keep["CONTRACTS"], errors="coerce").fillna(0).astype("int64")
    out["oi"] = pd.to_numeric(keep["OPEN_INT"], errors="coerce").fillna(0).astype("int64")
    out["oi_change"] = pd.to_numeric(keep["CHG_IN_OI"], errors="coerce").fillna(0).astype("int64")
    out["source"] = "nse_bhavcopy_legacy"
    return validate_canonical(coalesce_untraded_ohlc(out))


def _unzip_first_csv(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        return z.read(name).decode("utf-8", errors="replace")


class NSEBhavcopyAdapter(VendorAdapter):
    id = "nse_bhavcopy"

    def __init__(self, prefer: str = "udiff"):
        self.prefer = prefer  # 'udiff' or 'legacy'

    def _download(self, url: str) -> bytes:
        # urllib keeps this dependency-free; a production run should use a
        # requests.Session that first warms cookies on https://www.nseindia.com
        import urllib.request
        req = urllib.request.Request(url, headers=NSE_HEADERS)
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()

    def fetch_eod_fno(self, trade_date: dt.date) -> pd.DataFrame:
        order = ([udiff_url, parse_udiff_csv], [legacy_url, parse_legacy_csv])
        if self.prefer == "legacy":
            order = order[::-1]
        last_err = None
        for url_fn, parse_fn in order:
            try:
                blob = self._download(url_fn(trade_date))
                return parse_fn(_unzip_first_csv(blob))
            except Exception as e:  # noqa: BLE001 — try the other format
                last_err = e
        raise RuntimeError(
            f"NSE bhavcopy fetch failed for {trade_date}: {last_err}. "
            f"If running locally, ensure network access and that NSE cookies "
            f"are warmed (GET https://www.nseindia.com first)."
        )
