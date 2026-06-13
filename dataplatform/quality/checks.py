"""
Data-quality checks for canonical EOD F&O frames.

Philosophy: quarantine, don't silently drop. Each check appends structured
issues; the pipeline decides what blocks promotion. Severities: 'error' (likely
corrupt — investigate), 'warn' (suspicious — keep but flag).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..vendors.base import CANONICAL_EOD_COLUMNS


@dataclass
class Issue:
    check: str
    severity: str        # 'error' | 'warn'
    count: int
    detail: str = ""


@dataclass
class QualityReport:
    rows: int
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(i.count for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> int:
        return sum(i.count for i in self.issues if i.severity == "warn")

    @property
    def ok(self) -> bool:
        """Pass if there are no error-severity issues."""
        return not any(i.severity == "error" for i in self.issues)

    def summary(self) -> str:
        head = f"rows={self.rows} errors={self.errors} warnings={self.warnings} ok={self.ok}"
        lines = [f"  [{i.severity}] {i.check}: {i.count} {i.detail}".rstrip()
                 for i in self.issues]
        return "\n".join([head, *lines])


def run_quality_checks(df: pd.DataFrame) -> QualityReport:
    rep = QualityReport(rows=len(df))

    missing = set(CANONICAL_EOD_COLUMNS) - set(df.columns)
    if missing:
        rep.issues.append(Issue("schema", "error", len(missing),
                                f"missing columns {sorted(missing)}"))
        return rep  # can't run row checks without schema
    if df.empty:
        rep.issues.append(Issue("empty", "warn", 0, "no rows for this date"))
        return rep

    price_cols = ["open", "high", "low", "close"]

    # null OHLC
    n_null = int(df[price_cols].isna().any(axis=1).sum())
    if n_null:
        rep.issues.append(Issue("null_ohlc", "error", n_null, "NaN in OHLC"))

    # crossed bars: high < low
    n_cross = int((df["high"] < df["low"]).sum())
    if n_cross:
        rep.issues.append(Issue("crossed_high_low", "error", n_cross, "high < low"))

    # close/open outside [low, high] (tolerant of tiny float noise)
    tol = 1e-6
    oob = (
        (df["close"] > df["high"] + tol) | (df["close"] < df["low"] - tol)
        | (df["open"] > df["high"] + tol) | (df["open"] < df["low"] - tol)
    )
    n_oob = int(oob.sum())
    if n_oob:
        rep.issues.append(Issue("ohlc_out_of_range", "error", n_oob,
                                "open/close outside [low,high]"))

    # negative prices
    n_neg = int((df[price_cols] < 0).any(axis=1).sum())
    if n_neg:
        rep.issues.append(Issue("negative_price", "error", n_neg, ""))

    # negative OI
    n_oi = int((df["oi"] < 0).sum())
    if n_oi:
        rep.issues.append(Issue("negative_oi", "error", n_oi, ""))

    # options with non-positive strike
    opt = df[df["instrument"] == "OPT"]
    n_strike = int((opt["strike"] <= 0).sum())
    if n_strike:
        rep.issues.append(Issue("bad_option_strike", "error", n_strike,
                                "OPT strike <= 0"))

    # expiry before trade date (already-expired contract trading)
    exp = pd.to_datetime(df["expiry"], errors="coerce")
    td = pd.to_datetime(df["trade_date"], errors="coerce")
    n_exp = int((exp < td).sum())
    if n_exp:
        rep.issues.append(Issue("expiry_before_trade_date", "error", n_exp, ""))

    # duplicate natural keys
    key = ["trade_date", "underlying", "instrument", "opt_type", "expiry", "strike"]
    n_dup = int(df.duplicated(subset=key).sum())
    if n_dup:
        rep.issues.append(Issue("duplicate_keys", "error", n_dup, ""))

    # zero-volume AND zero-OI rows (illiquid / placeholder) — warn only
    n_dead = int(((df["volume"] == 0) & (df["oi"] == 0)).sum())
    if n_dead:
        rep.issues.append(Issue("zero_vol_and_oi", "warn", n_dead,
                                "illiquid/placeholder rows"))

    return rep
