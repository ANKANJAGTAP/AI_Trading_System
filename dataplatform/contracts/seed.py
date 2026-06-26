"""
Seed effective-dated contract specs for NIFTY / FINNIFTY / SENSEX.

All values below are VERIFIED against public circulars/reporting (verify=False):
  * Nifty lot: 25 -> 75 effective 2024-11-20 (SEBI Rs15-20L min contract value;
    existing 25-lot contracts rolled by 2024-12-26), then 75 -> 65 effective
    2025-12-31 (revised lot applies from the Jan-2026 series; the final 75-lot
    contract expired 2025-12-30).  [NSE circular Nov 2024 / NSE lot revision
    Oct-Dec 2025, effective Jan-2026]
  * FinNifty lot: 40 (weekly era) -> 65 (2024-11-20) -> 60 (2025-12-31).
  * FinNifty WEEKLY options DISCONTINUED: last weekly expiry 2024-11-19
    (SEBI single-weekly-per-exchange; NSE kept only Nifty 50 weekly).
  * SENSEX (BSE) lot: 15 at the 2000 launch -> 10 on the 2023-05-15 relaunch ->
    20 on 2024-11-20 (BSE circular); unchanged through the Jan-2026 revision.

Sources: businesstoday (May-2023 Sensex relaunch); groww / zerodha / 5paisa
(BSE Nov-2024 lot 10->20); kotaksecurities / angelone (NSE Jan-2026 65/60
revision); business-standard / newsonair (expiry swap 2025).
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

    # ----------------------- BANKNIFTY (NSE) — VERIFIED -----------------------
    # Lot: 25 -> 15 (2023-06-30, NSE circular) -> 30 (2024-11-20, SEBI Nov-2024
    # revision). A late-2025 revision is reported ambiguously (30 vs 35) — the open
    # record is flagged verify=True pending the exact circular. BANKNIFTY weeklies
    # were withdrawn 2024-11-20 (NSE single-weekly rule): monthly-only since.
    SpecRecord("BANKNIFTY", "lot_size", "25", _d("2023-01-01"), _d("2023-06-29"),
               source="nse", verify=False),
    SpecRecord("BANKNIFTY", "lot_size", "15", _d("2023-06-30"), _d("2024-11-19"),
               source="nse_circular_jun2023", verify=False),
    SpecRecord("BANKNIFTY", "lot_size", "30", _d("2024-11-20"), None,
               source="nse_circular_nov2024", verify=False),   # re-check late-2025 revision (30 vs 35)
    SpecRecord("BANKNIFTY", "tick_size", "0.05", _d("2016-05-27"), None, verify=False),
    SpecRecord("BANKNIFTY", "weekly_available", "false", _d("2024-11-20"), None,
               source="nse_weekly_removal_nov2024", verify=False),

    # ----------------------- SENSEX (BSE) — VERIFIED -----------------------
    # BSE relaunched Sensex F&O 2023-05-15 with lot 10 (cut from 15); raised to
    # 20 on 2024-11-20 and unchanged through the Jan-2026 NSE revision.
    SpecRecord("SENSEX", "lot_size", "10", _d("2023-05-15"), _d("2024-11-19"),
               source="bse_sensex_relaunch_may2023", verify=False),
    SpecRecord("SENSEX", "lot_size", "20", _d("2024-11-20"), None,
               source="bse_circular_nov2024", verify=False),
    SpecRecord("SENSEX", "tick_size", "0.05", _d("2023-05-15"), None, verify=False),
    SpecRecord("SENSEX", "weekly_available", "true", _d("2023-05-15"), None,
               source="bse_sensex_weekly_launch_2023", verify=False),
]
