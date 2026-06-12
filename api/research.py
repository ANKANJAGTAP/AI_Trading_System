"""Research API (Phase 4): meta-label dataset stats, training, and model registry."""
from __future__ import annotations

from common.logging import get_logger
from research import registry
from research.dataset import build_dataset, feature_names, to_matrix
from research.discrimination import discriminate
from research.meta_label import evaluate, feature_importance, train

log = get_logger("api_research")


async def status() -> dict:
    models = await registry.list_models()
    active = await registry.get_active()
    active_view = None
    if active:
        active_view = {"id": active["id"], "name": active["name"], "metrics": active["metrics"],
                       "importance": feature_importance(active["params"], active["features"])[:10]}
    return {"models": models, "active": active_view}


async def dataset_stats() -> dict:
    samples = await build_dataset()
    wins = sum(s["label"] for s in samples)
    return {"n_samples": len(samples), "wins": wins, "losses": len(samples) - wins,
            "base_rate": round(wins / len(samples), 3) if samples else 0.0,
            "features": feature_names(samples)}


async def discrimination() -> dict:
    """Does any feature actually separate winners from losers? (edge diagnostic)"""
    return discriminate(await build_dataset())


def _recency_weights(n: int, half_life: int) -> list[float] | None:
    """Exponential recency decay: a trade `half_life` trades ago counts half as much.
    Markets drift — yesterday's regime teaches more than last quarter's."""
    if half_life <= 0 or n <= 1:
        return None
    import math
    return [math.pow(0.5, (n - 1 - i) / float(half_life)) for i in range(n)]


def _select_features(samples: list[dict], all_feats: list[str], max_features: int) -> list[str]:
    """Leak-free feature pruning: rank by discrimination |lift| computed on the
    OLDEST 80% only (never on data any CV fold will test on), keep the top-K.
    Fewer, proven features beat many noisy ones at this sample size."""
    if max_features <= 0 or len(all_feats) <= max_features:
        return all_feats
    cut = max(1, int(len(samples) * 0.8))
    disc = discriminate(samples[:cut])
    ranked = [f["feature"] for f in (disc.get("features") or [])
              if f.get("win_rate_high") is not None and f["feature"] in set(all_feats)]
    keep = ranked[:max_features]
    return keep or all_feats


async def train_and_register(name: str | None = None, min_samples: int = 80,
                             meta_cfg: dict | None = None) -> dict:
    """Train/validate with PURGED EXPANDING-WINDOW CV (López de Prado): the series is
    chunked sequentially; each fold trains on everything BEFORE the test chunk minus
    an embargo sample, so no future information leaks and the verdict rests on
    multiple independent out-of-sample windows, not one lucky split. The production
    model then refits on all data with recency + class weights. Registered ACTIVE
    only if the CV gate passes — a model worse than no model never trades."""
    cfg = meta_cfg or {}
    min_samples = int(cfg.get("min_samples", min_samples) or min_samples)
    min_test = int(cfg.get("min_test", 15) or 15)
    min_lift = float(cfg.get("min_lift", 0.05) or 0.05)
    min_class = int(cfg.get("min_class_samples", 15) or 15)
    folds = int(cfg.get("cv_folds", 4) or 4)
    min_test_fold = int(cfg.get("min_test_per_fold", 8) or 8)
    half_life = int(cfg.get("recency_half_life_trades", 60) or 0)
    max_features = int(cfg.get("max_features", 12) or 0)
    embargo = 1

    samples = await build_dataset()   # ordered by signal id == time
    if len(samples) < min_samples:
        return {"error": f"not enough labeled trades to train ({len(samples)} < {min_samples})"}
    wins = sum(s["label"] for s in samples)
    if wins < min_class or (len(samples) - wins) < min_class:
        return {"error": f"class imbalance: {wins} wins / {len(samples) - wins} losses "
                         f"(need >= {min_class} of each)"}

    feats = _select_features(samples, feature_names(samples), max_features)

    # ---- purged expanding-window CV (fall back to one temporal split when small) --
    seg = len(samples) // (folds + 1)
    fold_metrics: list[dict] = []
    if seg >= min_test_fold:
        for k in range(1, folds + 1):
            tr = samples[: max(1, k * seg - embargo)]
            te = samples[k * seg: (k + 1) * seg if k < folds else len(samples)]
            tw = sum(s["label"] for s in tr)
            if len(te) < min_test_fold or tw == 0 or tw == len(tr):
                continue
            p = train(*to_matrix(tr, feats), class_weight=True)
            fold_metrics.append(evaluate(p, *to_matrix(te, feats)))
        split_desc = f"purged_expanding_{folds}fold_embargo{embargo}"
    else:
        cut = max(1, int(len(samples) * 0.8))
        tr, te = samples[:cut], samples[cut:]
        if len(te) < min_test:
            return {"error": f"test window too small ({len(te)} < {min_test})"}
        p = train(*to_matrix(tr, feats), class_weight=True)
        fold_metrics.append(evaluate(p, *to_matrix(te, feats)))
        split_desc = "temporal_80_20"

    if not fold_metrics:
        return {"error": "no evaluable CV folds (degenerate class distribution)"}

    import math
    import statistics as st
    mean_acc = st.mean(m["accuracy"] for m in fold_metrics)
    mean_lift = st.mean(m["lift"] for m in fold_metrics)
    mean_base = st.mean(m["base_rate"] for m in fold_metrics)
    pos_folds = sum(1 for m in fold_metrics if m["lift"] > 0)
    majority = max(mean_base, 1.0 - mean_base)
    # Gate: beat majority-guess on accuracy, clear the lift bar ON AVERAGE, and be
    # right in most folds — one golden window must not carry the verdict.
    validated = (mean_acc >= majority + min_lift / 2
                 and mean_lift >= min_lift
                 and pos_folds >= math.ceil(0.75 * len(fold_metrics)))

    final = train(*to_matrix(samples, feats),
                  sample_weight=_recency_weights(len(samples), half_life),
                  class_weight=True)
    final["deploy"] = {  # the filter thresholds ship inside the model
        "veto_below": float(cfg.get("veto_below", 0.40) or 0.40),
        "neutral_above": float(cfg.get("neutral_above", 0.55) or 0.55),
        "soft_floor": float(cfg.get("soft_floor", 0.6) or 0.6),
    }
    metrics = {"accuracy": round(mean_acc, 3), "base_rate": round(mean_base, 3),
               "lift": round(mean_lift, 3),
               "precision_1": round(st.mean(m["precision_1"] for m in fold_metrics), 3),
               "recall_1": round(st.mean(m["recall_1"] for m in fold_metrics), 3),
               "folds_evaluated": len(fold_metrics), "positive_folds": pos_folds,
               "n_samples": len(samples), "n_features": len(feats),
               "validated": validated, "split": split_desc}
    name = name or f"meta-{len(samples)}"
    mid = await registry.save_model(name, feats, final, metrics, activate=validated)
    log.info("meta_model_trained", id=mid, activated=validated, **{
        k: v for k, v in metrics.items() if k != "split"})
    return {"id": mid, "name": name, "metrics": metrics, "validated": validated,
            "importance": feature_importance(final, feats)[:10]}


async def activate_model(model_id: int) -> dict:
    await registry.activate(model_id)
    return {"ok": True, "active": model_id}
