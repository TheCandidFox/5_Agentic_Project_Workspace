from __future__ import annotations

import hashlib
import re
from typing import Sequence

from acceptance_truth import (
    CriterionVerdict,
    EvidenceDisposition,
    EvidenceKind,
)
from orchestration_kernel import (
    ArtifactRecord,
    ConstraintResult,
    CriterionResult,
    TaskEvidence,
    TaskExecutionContext,
    TaskExecutionResult,
)
from project_contract import AuthorityLevel, ProjectContract, ProjectContractError
from task_graph import TaskSpec


class OfflineChecklistPlanner:
    profile = "offline-checklist-v1"
    supported_kinds = frozenset({"compose-checklist", "validate-checklist"})
    supported_criteria = frozenset(
        {"deliverable-exists", "required-sections", "concise-length"}
    )
    supported_constraints = frozenset(
        {"offline-only", "no-provider-calls", "workspace-confined"}
    )

    def build(self, contract: ProjectContract) -> Sequence[TaskSpec]:
        if contract.policy.profile != self.profile:
            raise ProjectContractError(
                f"offline checklist planner cannot run profile {contract.policy.profile}"
            )
        if contract.policy.authority_ceiling != AuthorityLevel.WORKSPACE_WRITE:
            raise ProjectContractError(
                "offline-checklist-v1 requires the workspace-write authority ceiling"
            )
        if abs(contract.policy.budget_usd) > 1e-12:
            raise ProjectContractError("offline-checklist-v1 requires Budget USD 0")
        if len(contract.deliverables) != 1:
            raise ProjectContractError("offline-checklist-v1 requires exactly one deliverable")
        criterion_keys = {item.criterion_key for item in contract.acceptance_criteria}
        unsupported_criteria = sorted(criterion_keys.difference(self.supported_criteria))
        if unsupported_criteria:
            raise ProjectContractError(
                f"unsupported checklist criterion(s): {', '.join(unsupported_criteria)}"
            )
        constraint_keys = {item.constraint_key for item in contract.constraints}
        unsupported_constraints = sorted(
            constraint_keys.difference(self.supported_constraints)
        )
        if unsupported_constraints:
            raise ProjectContractError(
                f"unsupported checklist constraint(s): {', '.join(unsupported_constraints)}"
            )

        deliverable = contract.deliverables[0]
        common_inputs = {
            "deliverable_path": deliverable.path,
            "required_content": list(contract.required_content),
        }
        return (
            TaskSpec(
                task_key="compose-checklist",
                title="Compose the declared checklist",
                description="Create the deterministic Markdown checklist artifact.",
                kind="compose-checklist",
                authority=AuthorityLevel.WORKSPACE_WRITE,
                estimated_cost_usd=0,
                max_attempts=1,
                inputs=common_inputs,
            ),
            TaskSpec(
                task_key="validate-checklist",
                title="Validate the checklist",
                description=(
                    "Verify the declared artifact, required sections, length, and "
                    "offline policy constraints."
                ),
                kind="validate-checklist",
                authority=AuthorityLevel.READ_ONLY,
                dependencies=("compose-checklist",),
                estimated_cost_usd=0,
                max_attempts=1,
                inputs={
                    **common_inputs,
                    "criterion_keys": sorted(criterion_keys),
                    "constraint_keys": sorted(constraint_keys),
                    "max_words": 1_000,
                },
            ),
        )


class OfflineChecklistExecutor:
    """Deterministic Phase 7 fixture executor with no provider/network adapter."""

    def __init__(self) -> None:
        self.call_count = 0
        self.dispatched_task_keys: list[str] = []

    @staticmethod
    def _render(contract: ProjectContract) -> str:
        lines = [
            f"# {contract.title}",
            "",
            f"**Goal:** {contract.goal}",
            "",
            "## Evaluation Information",
            "",
            "- Supplier:",
            "- Reviewer:",
            "- Date:",
            "- Product or service:",
            "",
        ]
        for section in contract.required_content:
            lines.extend(
                [
                    f"## {section}",
                    "",
                    "- [ ] Record the relevant facts and supporting evidence.",
                    "- [ ] Note exceptions, assumptions, and follow-up questions.",
                    "- Rating (1–5):",
                    "- Evidence/notes:",
                    "",
                ]
            )
        lines.extend(
            [
                "## Decision Summary",
                "",
                "- [ ] Approve",
                "- [ ] Approve with conditions",
                "- [ ] Defer for more information",
                "- [ ] Reject",
                "- Decision rationale:",
                "- Required follow-up:",
                "",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _artifact_reference(artifact: ArtifactRecord) -> str:
        return f"artifact:{artifact.path}#sha256={artifact.content_sha256}"

    def execute(self, context: TaskExecutionContext) -> TaskExecutionResult:
        self.call_count += 1
        self.dispatched_task_keys.append(context.task.task_key)
        if context.task.kind == "compose-checklist":
            return self._compose(context)
        if context.task.kind == "validate-checklist":
            return self._validate(context)
        raise ValueError(f"unsupported offline checklist task: {context.task.kind}")

    def _compose(self, context: TaskExecutionContext) -> TaskExecutionResult:
        path = context.contract.deliverables[0].path
        artifact = context.artifact_writer.write_text(
            path,
            self._render(context.contract),
        )
        evidence = TaskEvidence(
            evidence_key="compose-artifact",
            kind=EvidenceKind.OBSERVATION,
            disposition=EvidenceDisposition.SUPPORTS,
            summary="The declared checklist artifact was written inside the workspace.",
            reference=self._artifact_reference(artifact),
        )
        return TaskExecutionResult(
            success=True,
            summary="Created the declared deterministic Markdown checklist.",
            evidence=(evidence,),
            artifacts=(artifact,),
        )

    def _validate(self, context: TaskExecutionContext) -> TaskExecutionResult:
        path = context.contract.deliverables[0].path
        content = context.artifact_writer.read_text(path)
        data = content.encode("utf-8")
        artifact = ArtifactRecord(
            path=path,
            content_sha256=hashlib.sha256(data).hexdigest(),
            content_bytes=len(data),
        )
        reference = self._artifact_reference(artifact)
        word_count = len(re.findall(r"\b\w[\w’'-]*\b", content, flags=re.UNICODE))
        checks = {
            "deliverable-exists": bool(content.strip()),
            "required-sections": all(
                f"## {section}" in content for section in context.contract.required_content
            ),
            "concise-length": word_count <= 1_000,
        }
        evidence: list[TaskEvidence] = []
        criteria: list[CriterionResult] = []
        for criterion in context.contract.acceptance_criteria:
            passed = checks[criterion.criterion_key]
            evidence_key = f"check-{criterion.criterion_key}"
            evidence.append(
                TaskEvidence(
                    evidence_key=evidence_key,
                    kind=EvidenceKind.DETERMINISTIC_VALIDATION,
                    disposition=(
                        EvidenceDisposition.SUPPORTS
                        if passed
                        else EvidenceDisposition.CONTRADICTS
                    ),
                    summary=(
                        f"Deterministic check {criterion.criterion_key} "
                        f"{'passed' if passed else 'failed'}."
                    ),
                    reference=reference,
                )
            )
            criteria.append(
                CriterionResult(
                    criterion_key=criterion.criterion_key,
                    verdict=CriterionVerdict.PASS if passed else CriterionVerdict.FAIL,
                    evidence_keys=(evidence_key,),
                )
            )

        constraint_evidence: dict[str, str] = {}
        for constraint in context.contract.constraints:
            evidence_key = f"constraint-{constraint.constraint_key}"
            constraint_evidence[constraint.constraint_key] = evidence_key
            evidence.append(
                TaskEvidence(
                    evidence_key=evidence_key,
                    kind=EvidenceKind.DETERMINISTIC_VALIDATION,
                    disposition=EvidenceDisposition.SUPPORTS,
                    summary=(
                        f"The offline fixture profile enforced {constraint.constraint_key}."
                    ),
                    reference=f"profile:{OfflineChecklistPlanner.profile}",
                )
            )
        constraints = tuple(
            ConstraintResult(
                constraint_key=item.constraint_key,
                violated=False,
                evidence_keys=(constraint_evidence[item.constraint_key],),
            )
            for item in context.contract.constraints
        )
        return TaskExecutionResult(
            success=True,
            summary=(
                f"Validated checklist existence, {len(context.contract.required_content)} "
                f"required sections, and {word_count}/1000 words."
            ),
            evidence=tuple(evidence),
            criteria=tuple(criteria),
            constraints=constraints,
            artifacts=(artifact,),
        )
