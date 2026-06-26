"""
BSE F&O EOD bhavcopy adapter (free) — SENSEX index derivatives.

BSE publishes a UDiFF-style common bhavcopy. As with NSE, the exact download URL
changes periodically, so the parser is a PURE function and the URL is
configurable. Verify the current URL from BSE before a production run.

NOTE: exchange data is licensed; keep raw files private.
"""
from __future__ import annotations

import datetime as dt
import io
import zipfile

import pandas as pd

from .base import VendorAdapter, validate_canonical
from .nse_bhavcopy import _parse_date_any, coalesce_untraded_ohlc  # robust dates + untraded-OHLC fix

_PHASE_A_BSE = {"SENSEX"}


def bse_udiff_url(d: dt.date) -> str:
    # Verify against BSE; pattern mirrors the exchange-common UDiFF naming.
    # BSE serves the UDiFF derivatives bhavcopy as a plain .CSV (uppercase ext).
    return (f"https://www.bseindia.com/download/Bhavcopy/Derivative/"
            f"BhavCopy_BSE_FO_0_0_0_{d:%Y%m%d}_F_0000.CSV")


def _bse_bytes_to_csv(blob: bytes) -> str:
    """BSE bhavcopy is usually a plain CSV but is sometimes zipped — handle both."""
    if blob[:2] == b"PK":                       # zip magic number
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            return z.read(name).decode("utf-8", errors="replace")
    return blob.decode("utf-8", errors="replace")


def parse_bse_udiff_csv(text: str) -> pd.DataFrame:
    """Parse BSE UDiFF derivatives bhavcopy CSV text into the canonical schema."""
    raw = pd.read_csv(io.StringIO(text))
    raw.columns = [c.strip() for c in raw.columns]
    keep = raw[raw["FinInstrmTp"].isin(["IDF", "IDO"])].copy()
    keep = keep[keep["TckrSymb"].isin(_PHASE_A_BSE)]

    out = pd.DataFrame()
    out["trade_date"] = keep["TradDt"].map(_parse_date_any)
    out["underlying"] = keep["TckrSymb"]
    out["exchange"] = "BSE"
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
    out["source"] = "bse_bhavcopy_udiff"
    return validate_canonical(coalesce_untraded_ohlc(out))


class BSEBhavcopyAdapter(VendorAdapter):
    id = "bse_bhavcopy"

    def _download(self, url: str) -> bytes:
        import urllib.request
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "*/*"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()

    def fetch_eod_fno(self, trade_date: dt.date) -> pd.DataFrame:
        try:
            blob = self._download(bse_udiff_url(trade_date))
            return parse_bse_udiff_csv(_bse_bytes_to_csv(blob))
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"BSE bhavcopy fetch failed for {trade_date}: {e}. "
                f"Verify the current BSE derivatives bhavcopy URL."
            )
