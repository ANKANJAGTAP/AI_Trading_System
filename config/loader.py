"""Loads and validates the YAML tunables into a typed `AppConfig`."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from config.models import (
    AppConfig,
    DataConfig,
    ExecutionConfig,
    RiskConfig,
    SleevesConfig,
    StrategyParams,
    SystemConfig,
)
from config.settings import get_settings


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache
def get_config() -> AppConfig:
    cfg_dir = Path(get_settings().config_dir)
    return AppConfig(
        risk=RiskConfig(**_load_yaml(cfg_dir / "risk.yaml")),
        sleeves=SleevesConfig(**_load_yaml(cfg_dir / "sleeves.yaml")),
        execution=ExecutionConfig(**_load_yaml(cfg_dir / "execution.yaml")),
        data=DataConfig(**_load_yaml(cfg_dir / "data.yaml")),
        system=SystemConfig(**_load_yaml(cfg_dir / "system.yaml")),
        strategy=StrategyParams(**_load_yaml(cfg_dir / "strategy_params.yaml")),
    )


def reload_config() -> AppConfig:
    """Clear the cache and reload (used after an operator edits a YAML)."""
    get_config.cache_clear()
    return get_config()
