"""LLM Context & News layer (spec §6, Appendix B).

A single LLM call (slow loop only — NEVER on the tick path) that ingests news/events
for an already-approved trade and returns a structured risk signal:
{sentiment, event_risk, veto, downsize, reason}. It can ONLY veto or downsize — never
originate or upsize. On any failure/timeout it FAILS NEUTRAL (no veto, no downsize)
and logs it. The provider (Gemini for dev/paper, Anthropic for prod) is selected by
config; this layer owns the schema, prompt, hard timeout, and fail-neutral contract.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

from common.logging import get_logger
from common.market_time import now_ist
from llm.providers import make_provider

log = get_logger("llm_context")

NEUTRAL = {
    "sentiment": "neutral", "event_risk": "unknown", "veto": False, "downsize": 1.0,
    "reason": "LLM unavailable — fail neutral (no veto, no boost)",
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
        "event_risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "veto": {"type": "boolean", "description": "block the trade entirely"},
        "downsize": {"type": "number", "description": "size multiplier 0..1 (1 = no change)"},
        "reason": {"type": "string"},
    },
    "required": ["sentiment", "event_risk", "veto", "downsize", "reason"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a pre-trade risk sanity check for an algorithmic trading system in Indian markets. "
    "A deterministic pipeline and risk engine have ALREADY APPROVED this trade and sized it. "
    "Your ONLY power is to VETO (block) it or DOWNSIZE it based on news/event risk — you can NEVER "
    "originate or upsize a trade. Veto only for clear, material, adverse, time-sensitive risk "
    "(regulatory action, fraud, an imminent adverse event/earnings shock for the holding window). "
    "Be conservative: when in doubt, do not veto and do not downsize."
)


class LLMContextLayer:
    def __init__(self, config, settings, news_provider=None) -> None:
        llm = config.system.llm or {}
        self.timeout = float(llm.get("timeout_seconds", 20))
        self.max_news = int(llm.get("max_news_items", 25))
        self.news = news_provider
        self.provider = make_provider(config, settings)

    def _prompt(self, instrument: dict, setup: dict, news: list[dict]) -> str:
        lines = [
            f"Instrument: {instrument.get('tradingsymbol')} ({instrument.get('exchange')})",
            f"Proposed (already-approved) trade: side={setup.get('side')} "
            f"setup={setup.get('setup')} sleeve={setup.get('sleeve')}",
            "Recent news/events:",
        ]
        if news:
            lines += [f"- [{n.get('ts')}] {n.get('headline')}" for n in news[: self.max_news]]
        else:
            lines.append("- (no news available)")
        lines.append("Assess event risk; veto or downsize only if clearly warranted.")
        return "\n".join(lines)

    async def assess(self, instrument: dict, setup: dict, news: list[dict] | None = None) -> dict:
        if self.provider is None:
            log.info("llm_skipped_no_provider_fail_neutral")
            return dict(NEUTRAL)
        try:
            if news is None and self.news is not None:
                try:
                    news = await self.news.get_news(
                        instrument.get("tradingsymbol") or "", now_ist() - timedelta(days=2))
                except Exception:
                    news = []
            data = await asyncio.wait_for(
                self.provider.assess(_SYSTEM, self._prompt(instrument, setup, news or []), _SCHEMA),
                timeout=self.timeout + 2,
            )
            if not data:
                return dict(NEUTRAL)
            data["veto"] = bool(data.get("veto", False))
            data["downsize"] = max(0.0, min(1.0, float(data.get("downsize", 1.0))))
            log.info("llm_assessed", provider=self.provider.name, symbol=instrument.get("tradingsymbol"),
                     veto=data["veto"], downsize=data["downsize"], event_risk=data.get("event_risk"))
            return data
        except Exception as exc:
            log.warning("llm_assess_failed_fail_neutral", error=str(exc))
            return dict(NEUTRAL)


class StubLLMContextLayer:
    """Deterministic LLM stub for tests / no-LLM fallback: returns a fixed verdict."""

    def __init__(self, verdict: dict | None = None) -> None:
        self.verdict = verdict or dict(NEUTRAL)

    async def assess(self, instrument: dict, setup: dict, news: list[dict] | None = None) -> dict:
        return dict(self.verdict)
