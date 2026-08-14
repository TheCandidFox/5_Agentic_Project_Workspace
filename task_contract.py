from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import List


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskContract:
    objective: str
    acceptance_criteria: List[str]
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    contract_version: int = 1
    goal_version: int = 1
    scope_boundaries: List[str] = field(default_factory=list)
    importance_band: int = 1
    effect_class_ceiling: str = "informational"
    data_classification: str = "internal-non-sensitive"
    budget_ceiling_usd: float = 10.0
    approval_state: str = "approved"
    evidence_required: bool = False
    created_at: str = field(default_factory=utc_now)

    def validate(self) -> None:
        if not self.objective.strip():
            raise ValueError("objective is required")
        if not self.acceptance_criteria:
            raise ValueError("at least one acceptance criterion is required")
        if self.importance_band not in (0, 1, 2, 3):
            raise ValueError("importance_band must be 0..3")
        if self.data_classification not in (
            "public", "internal-non-sensitive", "sensitive"
        ):
            raise ValueError("invalid data_classification")
        if self.budget_ceiling_usd < 0:
            raise ValueError("budget_ceiling_usd must be >= 0")

    def to_record(self) -> dict:
        self.validate()
        d = asdict(self)
        d["scope_boundaries"] = json.dumps(self.scope_boundaries)
        d["acceptance_criteria"] = json.dumps(self.acceptance_criteria)
        d["evidence_required"] = int(self.evidence_required)
        return d
