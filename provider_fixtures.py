from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from typing import Deque, Iterable

from project_contract import ProjectContract
from provider_adapter import ProviderResponse
from telemetry import Usage


@dataclass(frozen=True)
class FixtureReply:
    provider: str
    model: str
    text: str
    input_tokens: int
    output_tokens: int
    stop_reason: str = "fixture-complete"
    latency_ms: int = 7


class ScriptedProviderClient:
    """Explicit offline fixture; it never constructs an SDK or opens a network."""

    offline_fixture = True

    def __init__(self, replies: Iterable[FixtureReply]) -> None:
        self._replies: Deque[FixtureReply] = deque(replies)
        self.call_count = 0

    def call(
        self,
        *,
        provider: str,
        model: str,
        prompt: str,
        max_output_tokens: int,
    ) -> ProviderResponse:
        del prompt
        if not self._replies:
            raise RuntimeError("offline provider fixture has no remaining response")
        reply = self._replies.popleft()
        if (provider, model) != (reply.provider, reply.model):
            raise RuntimeError("offline provider fixture route mismatch")
        if reply.output_tokens > max_output_tokens:
            raise RuntimeError("offline provider fixture exceeds output-token limit")
        self.call_count += 1
        return ProviderResponse(
            provider=provider,
            model=model,
            text=reply.text,
            usage=Usage(reply.input_tokens, reply.output_tokens),
            latency_ms=reply.latency_ms,
            stop_reason=reply.stop_reason,
            request_id=f"fixture-request-{self.call_count}",
        )


def passing_phase8_replies(
    contract: ProjectContract,
    *,
    composer_provider: str,
    composer_model: str,
    reviewer_provider: str,
    reviewer_model: str,
) -> tuple[FixtureReply, FixtureReply]:
    lines = [
        f"# {contract.title}",
        "",
        "This bounded operating brief records a repeatable review sequence.",
        "",
    ]
    for heading in contract.required_content:
        lines.extend(
            [
                f"## {heading}",
                "",
                "- [ ] Record the observation and measurement.",
                "- [ ] Attach or reference the supporting evidence.",
                "- [ ] Note any exception and required follow-up.",
                "",
            ]
        )
    lines.extend(
        [
            "## Assumptions",
            "",
            "- This is a fictional offline fixture with no real sample facts.",
            "- Measurements and approval authority must be supplied by a human.",
            "",
        ]
    )
    artifact = "\n".join(lines)
    compose = {
        "artifact_markdown": artifact,
        "assumptions": [
            "The fixture contains no current external facts.",
            "A human supplies measurements and final approval.",
        ],
        "criterion_notes": {
            item.criterion_key: "The fixture artifact addresses this criterion."
            for item in contract.acceptance_criteria
        },
    }
    review = {
        "criteria": [
            {
                "criterion_key": item.criterion_key,
                "verdict": "PASS",
                "rationale": (
                    "The fixture artifact visibly satisfies the stated criterion."
                ),
            }
            for item in contract.acceptance_criteria
        ],
        "constraints": [
            {
                "constraint_key": item.constraint_key,
                "violated": False,
                "rationale": "The offline governed fixture preserved this control.",
            }
            for item in contract.constraints
        ],
        "overall_notes": (
            "The fixture artifact is complete enough for the bounded mock canary."
        ),
    }
    return (
        FixtureReply(
            provider=composer_provider,
            model=composer_model,
            text=json.dumps(compose, separators=(",", ":"), ensure_ascii=True),
            input_tokens=320,
            output_tokens=520,
        ),
        FixtureReply(
            provider=reviewer_provider,
            model=reviewer_model,
            text=json.dumps(review, separators=(",", ":"), ensure_ascii=True),
            input_tokens=620,
            output_tokens=310,
        ),
    )


def recovering_phase9_replies(
    contract: ProjectContract,
    *,
    composer_provider: str,
    composer_model: str,
    reviewer_provider: str,
    reviewer_model: str,
    reviewer_max_output_tokens: int,
) -> tuple[FixtureReply, FixtureReply, FixtureReply]:
    """Reproduce the Phase 8 max-token failure, then return a valid review."""

    compose, review = passing_phase8_replies(
        contract,
        composer_provider=composer_provider,
        composer_model=composer_model,
        reviewer_provider=reviewer_provider,
        reviewer_model=reviewer_model,
    )
    truncated = FixtureReply(
        provider=reviewer_provider,
        model=reviewer_model,
        text=(
            '{"criteria":[{"criterion_key":"deliverable-exists",'
            '"verdict":"PASS","rationale":"The artifact exists"}'
        ),
        input_tokens=6_759,
        # Preserve the observed Phase 8 failure (3,000 billed output tokens)
        # even though Phase 9 authorizes a larger 5,000-token retry window.
        output_tokens=min(3_000, reviewer_max_output_tokens),
        stop_reason="max_tokens",
        latency_ms=30_050,
    )
    return compose, truncated, review
