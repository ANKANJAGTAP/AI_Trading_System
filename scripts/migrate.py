"""CLI entrypoint: apply database migrations.

Usage: python scripts/migrate.py
"""
from __future__ import annotations

import asyncio

from migrations.runner import run_migrations

if __name__ == "__main__":
    asyncio.run(run_migrations())
