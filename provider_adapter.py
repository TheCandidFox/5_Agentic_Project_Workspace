from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from anthropic import Anthropic
from openai import OpenAI

from telemetry import Usage


@dataclass
class ProviderResponse:
    provider: str
    model: str
    text: str
    usage: Usage
    latency_ms: int
    stop_reason: str | None = None
    request_id: str | None = None


class ProviderAdapter:
    def __init__(self, openai_client: OpenAI | None = None, anthropic_client: Anthropic | None = None):
        self.openai = openai_client or OpenAI()
        self.anthropic = anthropic_client or Anthropic()

    def call(
        self,
        *,
        provider: str,
        model: str,
        prompt: str,
        max_output_tokens: int,
    ) -> ProviderResponse:
        started = time.perf_counter()

        if provider == "openai":
            r = self.openai.responses.create(
                model=model,
                input=prompt,
                max_output_tokens=max_output_tokens,
            )
            usage_obj = getattr(r, "usage", None)
            input_tokens = int(getattr(usage_obj, "input_tokens", 0) or 0)
            output_tokens = int(getattr(usage_obj, "output_tokens", 0) or 0)
            return ProviderResponse(
                provider=provider,
                model=model,
                text=r.output_text,
                usage=Usage(input_tokens, output_tokens),
                latency_ms=int((time.perf_counter() - started) * 1000),
                stop_reason=getattr(r, "status", None),
                request_id=getattr(r, "id", None),
            )

        if provider == "anthropic":
            r = self.anthropic.messages.create(
                model=model,
                max_tokens=max_output_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            parts = []
            for block in r.content:
                if getattr(block, "type", None) == "text":
                    parts.append(block.text)
            usage_obj = getattr(r, "usage", None)
            input_tokens = int(getattr(usage_obj, "input_tokens", 0) or 0)
            output_tokens = int(getattr(usage_obj, "output_tokens", 0) or 0)
            return ProviderResponse(
                provider=provider,
                model=model,
                text="\n".join(parts),
                usage=Usage(input_tokens, output_tokens),
                latency_ms=int((time.perf_counter() - started) * 1000),
                stop_reason=getattr(r, "stop_reason", None),
                request_id=getattr(r, "id", None),
            )

        raise ValueError(f"unsupported provider: {provider}")
