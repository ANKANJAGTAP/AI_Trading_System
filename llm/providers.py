"""LLM provider abstraction for the veto layer (Phase 5/6).

One interface, swappable backends selected by `config.system.llm.provider`:
  - gemini    : Google Gemini Flash (free dev/paper) — async JSON output
  - anthropic : Claude (production) — forced tool-use structured output
  - none / no key : returns None -> the context layer fails neutral (no veto)

Each provider returns the parsed dict (or None on any failure); the LLMContextLayer
wraps the call in a hard timeout and normalizes / fail-neutrals.
"""
from __future__ import annotations

import json

from common.logging import get_logger

log = get_logger("llm_provider")


class LLMProvider:
    name = "none"

    async def assess(self, system: str, prompt: str, schema: dict) -> dict | None:
        return None


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        self.api_key = api_key
        self.model = model

    async def assess(self, system: str, prompt: str, schema: dict) -> dict | None:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)
        contents = (f"{system}\n\n{prompt}\n\nRespond ONLY with a JSON object matching this schema "
                    f"(no markdown):\n{json.dumps(schema)}")
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json", temperature=0, max_output_tokens=1024)
        # 2.5-* are thinking models; the veto is a simple classification — disable
        # thinking so the token budget produces the JSON (not consumed by reasoning).
        try:
            cfg.thinking_config = types.ThinkingConfig(thinking_budget=0)
        except Exception:
            pass
        resp = await client.aio.models.generate_content(model=self.model, contents=contents, config=cfg)
        text = (resp.text or "").strip()
        return json.loads(text) if text else None


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6", timeout: float = 20) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def assess(self, system: str, prompt: str, schema: dict) -> dict | None:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=self.api_key, timeout=self.timeout, max_retries=1)
        resp = await client.messages.create(
            model=self.model, max_tokens=512, system=system,
            messages=[{"role": "user", "content": prompt}],
            tools=[{"name": "submit_assessment",
                    "description": "Submit the pre-trade veto/sentiment assessment.",
                    "input_schema": schema}],
            tool_choice={"type": "tool", "name": "submit_assessment"},
        )
        block = next((b for b in resp.content if getattr(b, "type", None) == "tool_use"), None)
        return dict(block.input) if block else None


def make_provider(config, settings) -> LLMProvider | None:
    """Select the provider from config + available keys. Returns None when no usable
    provider is configured (the context layer then fails neutral)."""
    llm = config.system.llm or {}
    provider = (llm.get("provider") or "auto").lower()
    timeout = float(llm.get("timeout_seconds", 20))
    if provider == "auto":
        provider = "gemini" if settings.gemini_api_key else ("anthropic" if settings.anthropic_api_key else "none")
    if provider == "gemini" and settings.gemini_api_key:
        log.info("llm_provider", provider="gemini", model=llm.get("gemini_model", "gemini-2.5-flash"))
        return GeminiProvider(settings.gemini_api_key, llm.get("gemini_model", "gemini-2.5-flash"))
    if provider == "anthropic" and settings.anthropic_api_key:
        model = (llm.get("models") or {}).get("news_synthesis", "claude-sonnet-4-6")
        log.info("llm_provider", provider="anthropic", model=model)
        return AnthropicProvider(settings.anthropic_api_key, model, timeout)
    log.warning("llm_provider_none", requested=provider)
    return None
