from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

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
    def __init__(self, openai_client: Any | None = None, anthropic_client: Any | None = None):
        # Clients are deliberately lazy. Offline status, preparation, and test
        # paths can import this adapter without reading keys or constructing an
        # SDK client.
        self.openai = openai_client
        self.anthropic = anthropic_client
        self.offline_fixture = False

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
            if self.openai is None:
                from openai import OpenAI

                self.openai = OpenAI()
            client = self.openai
            r = client.responses.create(
                model=model,
                input=prompt,
                max_output_tokens=max_output_tokens,
            )
            usage_obj = getattr(r, "usage", None)
            input_tokens = int(getattr(usage_obj, "input_tokens", 0) or 0)
            output_tokens = int(getattr(usage_obj, "output_tokens", 0) or 0)
            status = getattr(r, "status", None)
            if status == "incomplete":
                details = getattr(r, "incomplete_details", None)
                status = getattr(details, "reason", None) or status
            return ProviderResponse(
                provider=provider,
                model=model,
                text=r.output_text,
                usage=Usage(input_tokens, output_tokens),
                latency_ms=int((time.perf_counter() - started) * 1000),
                stop_reason=status,
                request_id=getattr(r, "id", None),
            )

        if provider == "anthropic":
            if self.anthropic is None:
                from anthropic import Anthropic

                self.anthropic = Anthropic()
            client = self.anthropic
            r = client.messages.create(
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
