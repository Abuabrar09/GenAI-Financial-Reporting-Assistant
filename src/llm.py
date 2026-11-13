"""Thin provider-agnostic LLM client (Anthropic Claude, OpenAI, or offline)."""
from __future__ import annotations

import json
import re

from src import config


class LLMUnavailable(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings: dict | None = None):
        self.settings = settings or config.llm_settings()
        self.provider = self.settings["provider"]
        self._client = None
        if self.provider == "anthropic" and not self.settings.get("anthropic_key"):
            self.provider = "offline"
        if self.provider == "openai" and not self.settings.get("openai_key"):
            self.provider = "offline"

    @property
    def available(self) -> bool:
        return self.provider in ("anthropic", "openai")

    @property
    def label(self) -> str:
        if self.provider == "anthropic":
            return f"Claude ({self.settings['anthropic_model']})"
        if self.provider == "openai":
            return f"OpenAI ({self.settings['openai_model']})"
        return "Offline mode (rule-based, no API key)"

    def complete(self, system: str, user: str, max_tokens: int = 1200, temperature: float = 0.2) -> str:
        if self.provider == "anthropic":
            import anthropic

            if self._client is None:
                self._client = anthropic.Anthropic(api_key=self.settings["anthropic_key"])
            msg = self._client.messages.create(
                model=self.settings["anthropic_model"],
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()

        if self.provider == "openai":
            from openai import OpenAI

            if self._client is None:
                self._client = OpenAI(api_key=self.settings["openai_key"])
            resp = self._client.chat.completions.create(
                model=self.settings["openai_model"],
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
            return (resp.choices[0].message.content or "").strip()

        raise LLMUnavailable("No LLM API key configured.")

    def complete_json(self, system: str, user: str, max_tokens: int = 800) -> dict:
        text = self.complete(system, user, max_tokens=max_tokens, temperature=0.0)
        return extract_json(text)


def extract_json(text: str) -> dict:
    """Parse the first JSON object in a model response (tolerates ```json fences)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(candidate)
