# AI Algorithmic Trading Platform — Backend

Real-money-capable algorithmic trading backend for Indian markets (NSE/BSE
equities + F&O, MCX commodities) via **Zerodha Kite Connect**. Built strictly to
[`backend_v2.md`](backend_v2.md).

**Core non-negotiables:** think in R (not lots); a deterministic gate pipeline
decides every trade (the LLM can only veto); the Risk Engine is an unbypassable
upstream gate; capital is read live every session; **fail safe, not fail open**;
everything is logged. Default mode is `simulated_fill` — real signals, real
prices, no real orders — flipped to `live` only manually by the operator.

---

## Build status

| Phase | Scope | Status |
|---|---|---|
| **0** | Foundations: skeleton, config, infra, DB schema, Kite auth | ✅ implemented |
| 1 | Market data layer (feed, candles, indicators) | pending |
| 2 | Risk & Capital Engine | pending |
| 3 | Execution & order management | pending |
| 4 | Strategy pipelines | pending |
| 5 | Orchestrator + confidence + LLM context | pending |
| 6 | Monitoring, dashboard, alerts, audit | pending |
| 7 | Go-live & operations | pending |

## Repository layout

```
engine/      asyncio engine process (fast + slow loops; Phase 0: bootstrap)
api/         FastAPI control plane (Phase 0: /health)
strategies/  the four gate pipelines (Phase 4)
risk/        Risk & Capital Engine (Phase 2)
execution/   execution layer + broker order management (Phase 3)
data/        market-data layer: feed, candles, governor (Phase 1)
broker/      BrokerAdapter interface + KiteAdapter, TOTP auth, token store
llm/         LLM context & news layer (Phase 5)
common/      shared infra: logging, db pool, redis, alerts, enums, time
config/      typed config loader + *.yaml tunables + env settings
migrations/  SQL migrations + runner (TimescaleDB hypertables)
dashboard/   React operator console (Phase 6)
ops/         entrypoint, systemd unit, runbook
scripts/     migrate, verify_phase0
```

## Phase 0 — what's implemented

- **Repo skeleton** mirroring the spec layout.
- **Typed config**: `config/*.yaml` (risk, sleeves, execution, data, system,
  strategy params) validated by pydantic models; secrets via `.env`
  (`config/settings.py`). Every spec parameter is present and tunable.
- **Infra**: Docker + docker-compose (app, TimescaleDB, Redis), `systemd` unit,
  restart-on-failure.
- **DB schema + migrations**: `instruments`, `ticks` (hypertable),
  `candles` (hypertable), `orders`, `fills`, `positions`, `signals`,
  `gate_results`, `audit_log` (hypertable, immutable), `daily_pnl`,
  `config_state`.
- **Broker**: `BrokerAdapter` interface + `KiteAdapter` skeleton with
  **automated daily TOTP login + token refresh**, encrypted token storage, and
  an email alert on auth failure.

## Quick start

```bash
# 1. configure
cp .env.example .env          # fill in Kite + (optional) SMTP creds
#    optionally generate a token encryption key:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 2. bring up the stack (Postgres+TimescaleDB, Redis, api, engine)
make up                       # == docker compose up -d --build

# 3. migrations run automatically on container start; or run manually:
make migrate

# 4. check health
curl -s localhost:8000/health   # -> {"status":"ok","mode":"simulated_fill",...}
```

### Running locally (without Docker)

```bash
pip install -r requirements.txt
export PYTHONPATH=$(pwd)
# point .env at a local Postgres+TimescaleDB and Redis
python scripts/migrate.py
uvicorn api.app:app --reload     # API
python -m engine.main            # engine
```

## Phase 0 acceptance

> *Containers come up; Kite auth succeeds and refreshes automatically; a live
> `margins()` and `instruments()` call returns real data and persists.*

```bash
make verify            # or: python scripts/verify_phase0.py
```

The verifier checks: all required tables + hypertables exist; automated Kite
login (or cached token) succeeds; `margins()` returns live data; `instruments()`
returns real data and persists to the `instruments` table. Prints `PASS`/`FAIL`
per criterion and exits non-zero on failure. (Kite checks require real
credentials in `.env`.)

## Notes

- `simulated_fill` is the default mode and **never sends a real order**. Going
  live is a deliberate manual flip (Phase 6 dashboard control / `config_state`).
- The `audit_log` table is immutable (a trigger blocks UPDATE/DELETE).
- Production token storage should use OS keyring / a cloud secret manager —
  swap out `broker/token_store.py`.
