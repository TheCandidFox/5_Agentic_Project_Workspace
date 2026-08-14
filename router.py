from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Route:
    provider: str
    tier: str
    model: str


def initial_tier(importance_band: int, workload: str) -> str:
    if importance_band >= 2:
        return "mid"
    if workload in {"coding", "automation", "research", "structured-data"}:
        return "mid"
    return "economy"


def route_for_provider(
    *,
    provider: str,
    importance_band: int,
    workload: str,
    economy_model: str,
    mid_model: str,
) -> Route:
    tier = initial_tier(importance_band, workload)
    return Route(
        provider=provider,
        tier=tier,
        model=economy_model if tier == "economy" else mid_model,
    )


def should_escalate(*, verifier_passed: bool, paid_attempt_number: int) -> bool:
    """
    v0.2.x permits one escalation only: attempt 1 may escalate to attempt 2.
    """
    return (not verifier_passed) and paid_attempt_number == 1
