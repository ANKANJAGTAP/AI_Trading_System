"""
Seed effective-dated contract specs for NIFTY / FINNIFTY / SENSEX.

NSE values below are VERIFIED against public circulars/reporting (verify=False):
  * Nifty lot: 25 -> 75 effective 2024-11-20 (SEBI Rs15-20L min contract value;
    existing contracts rolled by 2024-12-26), then 75 -> 65 effective 2024-12-31
    (the final 75-lot contract expired 2024-12-30).  [NSE circular, Nov 2024 /
    NSE lot revision Oct-Dec 2025]
  * FinNifty lot: 40 (weekly era) -> 65 (2024-11-20) -> 60 (2025-12-31).
  * FinNifty WEEKLY options DISCONTINUED: last weekly expiry 2024-11-19
    (SEBI single-weekly-per-exchange; NSE kept only Nifty 50 weekly).

SENSEX (BSE) lot values remain verify=True — confirm against BSE circulars.
Sources: groww.in / 5paisa / zerodha bulletins (Nov 2024); lemonn / stocko
(Oct-Dec 2025 lot revision); business-standard / newsonair (expiry swap 2025).
"""
from __future__ import annotations

import datetime as dt

from .models import SpecRecord


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


SEED_SPECS: list[SpecRecord] = [
    # ----------------------- NIFTY (NSE) — VERIFIED -----------------------
    SpecRecord("NIFTY", "lot_size", "25", _d("2015-11-01"), _d("2024-11-19"),
               source="nse_circular_nov2024", verify=False),
    SpecRecord("NIFTY", "lot_size", "75", _d("2024-11-20"), _d("2025-12-30"),
               source="nse_circular_nov2024", verify=False),
    SpecRecord("NIFTY", "lot_size", "65", _d("2025-12-31"), None,
               source="nse_lot_revision_dec2025", verify=False),
    SpecRecord("NIFTY", "tick_size", "0.05", _d("2001-06-01"), None, verify=False),
    SpecRecord("NIFTY", "weekly_available", "true", _d("2019-02-11"), None,
               source="nse_weekly_launch_2019", verify=False),

    # ----------------------- FINNIFTY (NSE) — VERIFIED -----------------------
    SpecRecord("FINNIFTY", "lot_size", "40", _d("2021-01-11"), _d("2024-11-19"),
               source="nse", verify=False),
    SpecRecord("FINNIFTY", "lot_size", "65", _d("2024-11-20"), _d("2025-12-30"),
               source="nse_circular_nov2024", verify=False),
    SpecRecord("FINNIFTY", "lot_size", "60", _d("2025-12-31"), None,
               source="nse_lot_revision_dec2025", verify=False),
    SpecRecord("FINNIFTY", "tick_size", "0.05", _d("2021-01-11"), None, verify=False),
    # weekly discontinued: last weekly expiry 2024-11-19
    SpecRecord("FINNIFTY", "weekly_available", "true", _d("2021-01-11"), _d("2024-11-19"),
               source="nse_weekly_discontinuation_nov2024", verify=False),
    SpecRecord("FINNIFTY", "weekly_available", "false", _d("2024-11-20"), None,
               source="nse_weekly_discontinuation_nov2024", verify=False),

    # ----------------------- SENSEX (BSE) — VERIFY -----------------------
    # BSE relaunched Sensex weekly options May 2023. Lot sizes here are best
    # estimates; CONFIRM against BSE circulars (verify=True).
    SpecRecord("SENSEX", "lot_size", "10", _d("2023-05-15"), _d("2024-11-19"),
               source="seed", verify=True),
    SpecRecord("SENSEX", "lot_size", "20", _d("2024-11-20"), None,
               source="seed", verify=True),
    SpecRecord("SENSEX", "tick_size", "0.05", _d("2023-05-15"), None, verify=False),
    SpecRecord("SENSEX", "weekly_available", "true", _d("2023-05-15"), None,
               source="bse_sensex_weekly_launch_2023", verify=False),
]
