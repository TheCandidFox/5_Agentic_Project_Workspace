from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class FutureInterfaceError(ValueError):
    pass


INTERFACE_FIELDS = {
    "CommandExecutionRequest.v1": frozenset({"schema_version", "command_alias", "arguments", "working_directory", "timeout_seconds", "idempotency_key", "authority_fingerprint"}),
    "CommandEvidence.v1": frozenset({"schema_version", "idempotency_key", "exit_code", "stdout_sha256", "stderr_sha256", "duration_ms", "outcome"}),
    "TrajectoryReview.v1": frozenset({"schema_version", "goal_sha256", "artifact_refs", "stability_verdict", "blocking_questions", "feature_recommendations"}),
    "FeatureRecommendation.v1": frozenset({"schema_version", "recommendation_id", "description", "reason", "blocking", "proposed_phase"}),
    "BlockingQuestion.v1": frozenset({"schema_version", "question_id", "question", "why_blocking", "bounded_options", "state_fingerprint"}),
    "HumanDecisionRequired.v1": frozenset({"schema_version", "gate_kind", "state_fingerprint", "artifact_fingerprint", "finding_fingerprint", "bounded_options", "expires_at"}),
}


def validate_future_interface(payload: Mapping[str, Any], *, expected_version: str) -> Mapping[str, Any]:
    """Validate dormant later-phase interfaces without activating their behavior."""
    expected = INTERFACE_FIELDS.get(expected_version)
    if expected is None:
        raise FutureInterfaceError("unknown interface version")
    if not isinstance(payload, Mapping) or payload.get("schema_version") != expected_version:
        raise FutureInterfaceError("interface version mismatch")
    if set(payload) != expected:
        raise FutureInterfaceError("interface fields do not match the strict schema")
    for name, value in payload.items():
        if name == "schema_version":
            continue
        if value is None or isinstance(value, str) and (not value.strip() or "\x00" in value):
            raise FutureInterfaceError(f"{name} is empty or unsafe")
    return payload
