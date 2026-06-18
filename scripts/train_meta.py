"""CLI: build the meta-label dataset from the audit trail, train a model, register it.

Usage:
    python scripts/train_meta.py
    python scripts/train_meta.py --name v1 --min-samples 50
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api import research as research_svc  # noqa: E402
from common.db import close_pool, init_pool  # noqa: E402
from common.logging import configure_logging  # noqa: E402


async def _main(args) -> None:
    configure_logging()
    await init_pool()
    try:
        from config.loader import get_config
        meta_cfg = dict(getattr(get_config().system, "meta_label", {}) or {})
        if args.min_samples:
            meta_cfg["min_samples"] = args.min_samples
        if args.labels == "triple_barrier":
            meta_cfg["triple_barrier"] = {"pt_pct": args.pt_pct, "sl_pct": args.sl_pct,
                                          "max_holding": args.max_holding}
            print(f"label mode: triple-barrier (pt={args.pt_pct:.1%} sl={args.sl_pct:.1%} "
                  f"hold={args.max_holding} bars) — labels built from forward price paths at train time")
        else:
            ds = await research_svc.dataset_stats()
            print(f"dataset: {ds['n_samples']} labelled trades · base win-rate {ds['base_rate']*100:.0f}%")
        res = await research_svc.train_and_register(args.name, meta_cfg=meta_cfg,
                                                    label_mode=args.labels)
        if res.get("error"):
            print("ERROR:", res["error"])
            return
        m = res["metrics"]
        print(f"\nmodel #{res['id']} ({res['name']})  VALIDATED={res['validated']}  [{m['split']}]")
        print(f"CV out-of-sample: acc {m['accuracy']*100:.0f}%  precision(let-through) "
              f"{m['precision_1']*100:.0f}%  lift {m['lift']*100:+.0f}pp  (base {m['base_rate']*100:.0f}%)")
        print(f"folds positive   : {m['positive_folds']}/{m['folds_evaluated']}  "
              f"(n {m['n_samples']}, features {m['n_features']})")
        if not res["validated"]:
            print("NOT activated — failed the CV validation gate (kept inactive for inspection).")
        print("top features      :")
        for f in res["importance"][:6]:
            print(f"    {f['feature']:<18} {f['weight']:+.2f}")
    finally:
        await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--name", default=None)
    p.add_argument("--min-samples", type=int, default=None,
                   help="override config system.meta_label.min_samples")
    p.add_argument("--labels", choices=["realized", "triple_barrier"], default="realized",
                   help="label source: realized trade P&L (default) or triple-barrier outcome")
    p.add_argument("--pt-pct", type=float, default=0.02,
                   help="triple-barrier profit target as a fraction (default 0.02 = 2%%)")
    p.add_argument("--sl-pct", type=float, default=0.01,
                   help="triple-barrier stop as a fraction (default 0.01 = 1%%); use ~= pt for balance")
    p.add_argument("--max-holding", type=int, default=24,
                   help="triple-barrier vertical/time barrier in bars (default 24)")
    asyncio.run(_main(p.parse_args()))
