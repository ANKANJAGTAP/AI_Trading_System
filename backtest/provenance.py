"""Backtest ↔ live parameter alignment (#24) — pure, no I/O.

A backtest is only trustworthy if it ran with the SAME knobs you trade live. This
fingerprints the result-affecting config into a stable hash, so every run can be
stamped and a backtest can be diffed against the live config before you believe it.
"""
from __future__ import annotations

import hashlib
import json

# Config sections whose values actually change decisions / sizing / costs.
FINGERPRINT_SECTIONS = ("risk", "execution", "strategy")


def _canonical(obj):
    """Deterministic, JSON-able projection: sorted keys, stable float rounding."""
    if isinstance(obj, dict):
        return {k: _canonical(obj[k]) for k in sorted(obj)}
    if isinstance(obj, (list, tuple)):
        return [_canonical(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 10)
    return obj


def config_fingerprint(cfg: dict, sections=FINGERPRINT_SECTIONS) -> str:
    """Stable 16-hex SHA-256 over the result-affecting config sections. Same knobs ->
    same fingerprint, regardless of key ordering."""
    projected = {s: _canonical((cfg or {}).get(s, {})) for s in sections}
    blob = json.dumps(projected, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def params_match(fp_a: str, fp_b: str) -> bool:
    return fp_a == fp_b


def _flat_diff(a, b, prefix: str = "") -> list[dict]:
    out: list[dict] = []
    if isinstance(a, dict) or isinstance(b, dict):
        a = a if isinstance(a, dict) else {}
        b = b if isinstance(b, dict) else {}
        for k in sorted(set(a) | set(b)):
            out += _flat_diff(a.get(k), b.get(k), f"{prefix}.{k}" if prefix else k)
    elif a != b:
        out.append({"path": prefix, "backtest": a, "live": b})
    return out


def diff_configs(cfg_backtest: dict, cfg_live: dict, sections=FINGERPRINT_SECTIONS) -> dict:
    """Per-section list of dotted paths whose values differ. {match: bool, differences}."""
    diffs: dict = {}
    for s in sections:
        d = _flat_diff(_canonical((cfg_backtest or {}).get(s, {})),
                       _canonical((cfg_live or {}).get(s, {})), s)
        if d:
            diffs[s] = d
    return {"match": not diffs, "differences": diffs}
