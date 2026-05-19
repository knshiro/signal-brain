"""Anthropic SDK wrapper with retry and JSON parsing."""
from __future__ import annotations
import json
import os
import re
import time
from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int


class LLMClient:
    def __init__(self, api_client=None, default_model: str = "claude-sonnet-4-6",
                 max_retries: int = 3):
        if api_client is None:
            from anthropic import Anthropic
            api_client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self._client = api_client
        self.default_model = default_model
        self.max_retries = max_retries

    def complete(self, system: str, user: str, *, model: str | None = None,
                 max_tokens: int = 4096) -> LLMResponse:
        last_err = None
        for attempt in range(self.max_retries):
            try:
                r = self._client.messages.create(
                    model=model or self.default_model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                text = "".join(b.text for b in r.content if hasattr(b, "text"))
                return LLMResponse(text=text,
                                   input_tokens=r.usage.input_tokens,
                                   output_tokens=r.usage.output_tokens)
            except Exception as e:
                last_err = e
                time.sleep(2 ** attempt)
        raise last_err

    def complete_json(self, system: str, user: str, **kw) -> dict | list:
        resp = self.complete(system, user, **kw)
        text = resp.text.strip()
        m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if m:
            text = m.group(1).strip()
        return json.loads(text)
