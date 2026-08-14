from __future__ import annotations

from dataclasses import dataclass

from ledger import Ledger


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


def estimate_cost(
    provider: str,
    usage: Usage,
    *,
    openai_input_per_mtok: float,
    openai_output_per_mtok: float,
    anthropic_input_per_mtok: float,
    anthropic_output_per_mtok: float,
) -> float:
    if provider == "openai":
        return (
            usage.input_tokens / 1_000_000 * openai_input_per_mtok
            + usage.output_tokens / 1_000_000 * openai_output_per_mtok
        )
    if provider == "anthropic":
        return (
            usage.input_tokens / 1_000_000 * anthropic_input_per_mtok
            + usage.output_tokens / 1_000_000 * anthropic_output_per_mtok
        )
    raise ValueError(f"unsupported provider: {provider}")


def record_call(ledger: Ledger, **kwargs) -> None:
    ledger.add_telemetry(**kwargs)
