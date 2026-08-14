from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from budget_guard import BudgetDenied, BudgetGuard
from git_checkpoint import (
    CheckpointRequest,
    GitCheckpointConflict,
    GitCheckpointError,
    GitCheckpointManager,
    GitCheckpointRecoveryRequired,
)
from ledger import Ledger
from patch_manager import (
    FilePatch,
    PatchError,
    PatchManager,
    PatchRecoveryRequired,
    PatchRequest,
)
from test_runner import (
    AnyValidationCheck,
    TestRunner,
    ValidationOutcome,
    ValidationSuiteResult,
    validation_spec_sha256,
)


class RepairIdempotencyConflict(RuntimeError):
    """Raised when a durable repair key is reused for another request."""


@dataclass(frozen=True)
class RepairPolicy:
    max_attempts: int = 3
    max_cost_usd: float = 1.0
    max_wall_seconds: float = 900.0
    max_identical_failures: int = 3
    max_identical_patches: int = 1
    max_no_progress_attempts: int = 2

    def __post_init__(self) -> None:
        integer_limits = (
            self.max_attempts,
            self.max_identical_failures,
            self.max_identical_patches,
            self.max_no_progress_attempts,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in integer_limits
        ):
            raise ValueError("repair count limits must be positive integers")
        for name in ("max_cost_usd", "max_wall_seconds"):
            value = getattr(self, name)
            if (
                not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                raise ValueError(f"{name} must be finite and non-negative")
        if self.max_wall_seconds <= 0:
            raise ValueError("max_wall_seconds must be positive")


@dataclass(frozen=True)
class RepairContext:
    run_id: str
    task_id: str
    objective: str
    attempt_number: int
    failure: Mapping[str, Any]
    remaining_cost_usd: float
    remaining_wall_seconds: float
    prior_attempts: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class RepairProposal:
    hypothesis: str
    files: tuple[FilePatch, ...]
    actual_cost_usd: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.hypothesis, str) or not self.hypothesis.strip():
            raise ValueError("repair hypothesis must be a non-empty string")
        if not self.files or not all(isinstance(item, FilePatch) for item in self.files):
            raise ValueError("repair proposal requires FilePatch entries")
        if (
            not isinstance(self.actual_cost_usd, (int, float))
            or not math.isfinite(float(self.actual_cost_usd))
            or float(self.actual_cost_usd) < 0
        ):
            raise ValueError("actual repair cost must be finite and non-negative")


class RepairAgent(Protocol):
    label: str

    def estimate_cost(self, context: RepairContext) -> float: ...

    def propose(self, context: RepairContext) -> RepairProposal: ...


@dataclass(frozen=True)
class RepairRequest:
    run_id: str
    idempotency_key: str
    task_id: str
    actor: str
    objective: str
    checks: tuple[AnyValidationCheck, ...]
    policy: RepairPolicy = RepairPolicy()

    def __post_init__(self) -> None:
        for name in ("run_id", "idempotency_key", "task_id", "actor", "objective"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                raise ValueError(f"{name} must be a non-empty safe string")
        if not self.checks:
            raise ValueError("repair request requires at least one validation check")


@dataclass(frozen=True)
class RepairResult:
    run_id: str
    status: str
    stop_reason: str | None
    attempts: int
    cost_usd: float
    checkpoint_id: str | None
    replayed: bool = False


class BoundedRepairLoop:
    """Durable validate/repair/checkpoint loop with hard stop conditions.

    A repair agent is injected rather than selected internally. This keeps
    provider dispatch, pricing, and credentials outside the safety mechanism
    and makes the complete state machine testable without provider calls.
    """

    _CONTEXT_LIMIT = 40_000

    def __init__(
        self,
        *,
        ledger: Ledger,
        test_runner: TestRunner,
        patch_manager: PatchManager,
        checkpoint_manager: GitCheckpointManager,
        repair_agent: RepairAgent,
        budget_guard: BudgetGuard | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if test_runner.store is not ledger:
            raise ValueError("bounded repair requires the durable ledger validation store")
        self.ledger = ledger
        self.test_runner = test_runner
        self.patch_manager = patch_manager
        self.checkpoint_manager = checkpoint_manager
        self.repair_agent = repair_agent
        self.budget_guard = budget_guard
        self.now = now or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _canonical_sha(value: Any) -> str:
        serialized = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _request_sha(self, request: RepairRequest) -> str:
        return self._canonical_sha(
            {
                "run_id": request.run_id,
                "task_id": request.task_id,
                "actor": request.actor,
                "objective": request.objective,
                "policy": asdict(request.policy),
                "checks": [validation_spec_sha256(check) for check in request.checks],
            }
        )

    @staticmethod
    def _parse_time(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

    def _portable_value(self, value: Any) -> Any:
        root = str(self.patch_manager.guard.root)
        if isinstance(value, Mapping):
            return {
                str(key): self._portable_value(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self._portable_value(item) for item in value]
        if isinstance(value, Path):
            value = str(value)
        if isinstance(value, str):
            return value.replace(root, "<workspace>")[:8_000]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value).replace(root, "<workspace>")[:8_000]

    def _validation_context(self, suite: ValidationSuiteResult) -> dict[str, Any]:
        results = [
            {
                "check_id": result.check_id,
                "kind": result.kind.value,
                "outcome": result.outcome.value,
                "summary": result.summary,
                "details": self._portable_value(result.details),
            }
            for result in suite.results
        ]
        pass_count = sum(
            result.outcome in {ValidationOutcome.PASS, ValidationOutcome.NOT_APPLICABLE}
            for result in suite.results
        )
        outcome_rank = {
            ValidationOutcome.ERROR: 0,
            ValidationOutcome.TIMEOUT: 1,
            ValidationOutcome.FAIL: 2,
            ValidationOutcome.NOT_APPLICABLE: 3,
            ValidationOutcome.PASS: 4,
        }[suite.outcome]
        context: dict[str, Any] = {
            "outcome": suite.outcome.value,
            "results": results,
            "progress_score": [pass_count, outcome_rank],
        }
        serialized = json.dumps(context, sort_keys=True, ensure_ascii=True)
        if len(serialized) > self._CONTEXT_LIMIT:
            context = {
                "outcome": suite.outcome.value,
                "results": [
                    {
                        "check_id": item["check_id"],
                        "kind": item["kind"],
                        "outcome": item["outcome"],
                        "summary": item["summary"][:1_000],
                    }
                    for item in results
                ],
                "progress_score": [pass_count, outcome_rank],
                "details_truncated": True,
            }
        return context

    def _suite_sha(self, context: Mapping[str, Any]) -> str:
        evidence = {
            "outcome": context["outcome"],
            "results": context["results"],
        }
        return self._canonical_sha(evidence)

    def _run_checks(
        self,
        request: RepairRequest,
        *,
        sequence: str,
    ) -> tuple[ValidationSuiteResult, dict[str, Any], str]:
        checks = tuple(
            replace(
                check,
                task_id=request.task_id,
                action_id=f"repair-validation-{sequence}",
                idempotency_key=(
                    f"{request.idempotency_key}:validation:{sequence}:{index}"
                ),
            )
            for index, check in enumerate(request.checks, start=1)
        )
        suite = self.test_runner.run_suite(checks)
        context = self._validation_context(suite)
        return suite, context, self._suite_sha(context)

    @staticmethod
    def _proposal_record(proposal: RepairProposal) -> dict[str, Any]:
        return {
            "files": [
                {
                    "path": Path(change.path).as_posix(),
                    "new_content": change.new_content,
                    "expected_sha256": change.expected_sha256,
                }
                for change in proposal.files
            ]
        }

    @staticmethod
    def _proposal_from_record(
        record: Mapping[str, Any],
        *,
        hypothesis: str,
        actual_cost_usd: float,
    ) -> RepairProposal:
        return RepairProposal(
            hypothesis=hypothesis,
            files=tuple(
                FilePatch(
                    item["path"],
                    item["new_content"],
                    expected_sha256=item.get("expected_sha256"),
                )
                for item in record["files"]
            ),
            actual_cost_usd=actual_cost_usd,
        )

    def _proposal_sha(self, proposal: RepairProposal) -> str:
        return self._canonical_sha(self._proposal_record(proposal))

    @staticmethod
    def _result(record: Mapping[str, Any], *, replayed: bool) -> RepairResult:
        return RepairResult(
            run_id=str(record["run_id"]),
            status=str(record["status"]),
            stop_reason=record.get("stop_reason"),
            attempts=int(record["attempt_count"]),
            cost_usd=float(record["cost_usd"]),
            checkpoint_id=record.get("checkpoint_id"),
            replayed=replayed,
        )

    def _finish(
        self,
        run_id: str,
        *,
        status: str,
        reason: str,
        error: str | None = None,
    ) -> RepairResult:
        record = self.ledger.finish_repair_run(
            run_id,
            status=status,
            stop_reason=reason,
            error=error,
        )
        return self._result(record, replayed=False)

    def _portable_error(self, exc: BaseException) -> str:
        root = str(self.patch_manager.guard.root)
        return f"{type(exc).__name__}: {exc}".replace(root, "<workspace>")[:4_000]

    def _deadline_remaining(self, record: Mapping[str, Any]) -> float:
        return max(
            0.0,
            (self._parse_time(str(record["deadline_at"])) - self.now()).total_seconds(),
        )

    def _update_no_progress(
        self,
        record: Mapping[str, Any],
        *,
        failure_sha: str,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        previous_context = record.get("failure_context") or {}
        previous_score = tuple(previous_context.get("progress_score", (0, 0)))
        new_score = tuple(context.get("progress_score", (0, 0)))
        identical = (
            int(record["identical_failure_count"]) + 1
            if record.get("last_failure_sha256") == failure_sha
            else 1
        )
        no_progress = (
            int(record["no_progress_count"]) + 1
            if new_score <= previous_score
            else 0
        )
        return self.ledger.record_repair_progress(
            str(record["run_id"]),
            last_failure_sha256=failure_sha,
            failure_context=context,
            identical_failure_count=identical,
            no_progress_count=no_progress,
        )

    def _rollback_or_recovery(
        self,
        request: RepairRequest,
        attempt: Mapping[str, Any],
        *,
        blocked_reason: str | None = None,
        error: str | None = None,
    ) -> RepairResult | None:
        try:
            self.patch_manager.rollback(str(attempt["patch_id"]))
            self.ledger.complete_repair_attempt_rollback(str(attempt["attempt_id"]))
        except Exception as exc:
            return self._finish(
                request.run_id,
                status="recovery_required",
                reason="rollback_recovery_required",
                error=self._portable_error(exc),
            )
        if blocked_reason is not None:
            return self._finish(
                request.run_id,
                status="blocked",
                reason=blocked_reason,
                error=error,
            )
        return None

    def _resume_attempt(
        self,
        request: RepairRequest,
        run: Mapping[str, Any],
        attempt: Mapping[str, Any],
    ) -> RepairResult | None:
        status = str(attempt["status"])
        if status == "proposing":
            return self._finish(
                request.run_id,
                status="recovery_required",
                reason="proposal_dispatch_unknown",
                error="A repair dispatch was claimed without a durable proposal result.",
            )
        if status == "proposal_received" and self._deadline_remaining(run) <= 0:
            return self._finish(
                request.run_id,
                status="blocked",
                reason="wall_clock_limit",
            )

        proposal = None
        if attempt.get("proposal") is not None:
            proposal = self._proposal_from_record(
                attempt["proposal"],
                hypothesis=str(attempt["hypothesis"]),
                actual_cost_usd=float(attempt["actual_cost_usd"] or 0.0),
            )

        if status == "proposal_received":
            assert proposal is not None
            patch_request = PatchRequest(
                patch_id=f"{request.run_id}:attempt:{attempt['attempt_number']}:patch",
                idempotency_key=(
                    f"{request.idempotency_key}:attempt:{attempt['attempt_number']}:patch"
                ),
                actor=request.actor,
                reason=proposal.hypothesis,
                files=proposal.files,
                task_id=request.task_id,
            )
            try:
                patch = self.patch_manager.apply(patch_request)
                attempt = self.ledger.mark_repair_patch_applied(
                    str(attempt["attempt_id"]), patch.patch_id
                )
                status = "patch_applied"
            except PatchRecoveryRequired as exc:
                return self._finish(
                    request.run_id,
                    status="recovery_required",
                    reason="patch_recovery_required",
                    error=self._portable_error(exc),
                )
            except PatchError as exc:
                self.ledger.fail_repair_attempt(
                    str(attempt["attempt_id"]), self._portable_error(exc)
                )
                run = self.ledger.get_repair_run(run_id=request.run_id)
                assert run is not None
                same_context = run.get("failure_context") or {}
                run = self.ledger.record_repair_progress(
                    request.run_id,
                    last_failure_sha256=str(run["last_failure_sha256"]),
                    failure_context=same_context,
                    identical_failure_count=int(run["identical_failure_count"]),
                    no_progress_count=int(run["no_progress_count"]) + 1,
                )
                if int(run["no_progress_count"]) >= request.policy.max_no_progress_attempts:
                    return self._finish(
                        request.run_id,
                        status="blocked",
                        reason="no_progress_limit",
                        error=self._portable_error(exc),
                    )
                return None
            except Exception as exc:
                return self._finish(
                    request.run_id,
                    status="recovery_required",
                    reason="patch_state_unknown",
                    error=self._portable_error(exc),
                )

        if status == "patch_applied":
            suite, context, failure_sha = self._run_checks(
                request,
                sequence=f"attempt-{attempt['attempt_number']}",
            )
            attempt = self.ledger.record_repair_validation(
                str(attempt["attempt_id"]),
                failure_sha256=failure_sha,
                outcome=suite.outcome.value,
            )
            status = str(attempt["status"])

        if status == "validation_passed":
            assert proposal is not None
            if self._deadline_remaining(run) <= 0:
                return self._rollback_or_recovery(
                    request,
                    attempt,
                    blocked_reason="wall_clock_limit",
                )
            paths = tuple(Path(change.path).as_posix() for change in proposal.files)
            checkpoint_id = (
                f"{request.run_id}:attempt:{attempt['attempt_number']}:checkpoint"
            )
            try:
                checkpoint = self.checkpoint_manager.create_checkpoint(
                    CheckpointRequest(
                        checkpoint_id=checkpoint_id,
                        idempotency_key=(
                            f"{request.idempotency_key}:attempt:"
                            f"{attempt['attempt_number']}:checkpoint"
                        ),
                        actor=request.actor,
                        reason=f"repair {request.objective}"[:2_000],
                        paths=paths,
                        patch_id=str(attempt["patch_id"]),
                        task_id=request.task_id,
                    )
                )
            except GitCheckpointRecoveryRequired as exc:
                return self._finish(
                    request.run_id,
                    status="recovery_required",
                    reason="checkpoint_recovery_required",
                    error=self._portable_error(exc),
                )
            except (GitCheckpointConflict, GitCheckpointError) as exc:
                return self._rollback_or_recovery(
                    request,
                    attempt,
                    blocked_reason="checkpoint_failed",
                    error=self._portable_error(exc),
                )
            stored = self.ledger.complete_repair_success(
                request.run_id,
                str(attempt["attempt_id"]),
                checkpoint.checkpoint_id,
            )
            return self._result(stored, replayed=False)

        if status == "validation_failed":
            result = self._rollback_or_recovery(request, attempt)
            if result is not None:
                return result
            run = self.ledger.get_repair_run(run_id=request.run_id)
            assert run is not None
            # Recreate the complete suite context from the deterministic replay;
            # this supports multi-check suites rather than relying on one row.
            _, context, failure_sha = self._run_checks(
                request,
                sequence=f"attempt-{attempt['attempt_number']}",
            )
            run = self._update_no_progress(
                run,
                failure_sha=failure_sha,
                context=context,
            )
            if (
                int(run["identical_failure_count"])
                >= request.policy.max_identical_failures
            ):
                return self._finish(
                    request.run_id,
                    status="blocked",
                    reason="repeated_identical_failure",
                )
            if int(run["no_progress_count"]) >= request.policy.max_no_progress_attempts:
                return self._finish(
                    request.run_id,
                    status="blocked",
                    reason="no_progress_limit",
                )
        return None

    def run(self, request: RepairRequest) -> RepairResult:
        request_sha = self._request_sha(request)
        deadline = self.now() + timedelta(seconds=request.policy.max_wall_seconds)
        claimed, run = self.ledger.claim_repair_run(
            run_id=request.run_id,
            task_id=request.task_id,
            actor=request.actor,
            objective=request.objective,
            idempotency_key=request.idempotency_key,
            request_sha256=request_sha,
            policy=asdict(request.policy),
            deadline_at=deadline.isoformat(),
        )
        if run["request_sha256"] != request_sha:
            raise RepairIdempotencyConflict(
                "repair idempotency key belongs to a different request"
            )
        if run["status"] != "running":
            return self._result(run, replayed=True)

        if not claimed and run["attempts"]:
            latest = run["attempts"][-1]
            if latest["status"] not in {"rolled_back", "rejected", "failed"}:
                resumed = self._resume_attempt(request, run, latest)
                if resumed is not None:
                    return resumed
                run = self.ledger.get_repair_run(run_id=request.run_id)
                assert run is not None

        if run["initial_failure_sha256"] is None:
            suite, context, failure_sha = self._run_checks(request, sequence="initial")
            if suite.outcome == ValidationOutcome.PASS:
                return self._finish(
                    request.run_id,
                    status="passed",
                    reason="already_valid",
                )
            run = self.ledger.record_repair_initial_failure(
                request.run_id,
                failure_sha,
                context,
            )

        while True:
            run = self.ledger.get_repair_run(run_id=request.run_id)
            assert run is not None
            if self._deadline_remaining(run) <= 0:
                return self._finish(
                    request.run_id,
                    status="blocked",
                    reason="wall_clock_limit",
                )
            if int(run["attempt_count"]) >= request.policy.max_attempts:
                return self._finish(
                    request.run_id,
                    status="blocked",
                    reason="attempt_limit",
                )

            attempt_number = int(run["attempt_count"]) + 1
            prior_attempts = tuple(
                {
                    "attempt_number": item["attempt_number"],
                    "status": item["status"],
                    "proposal_sha256": item.get("proposal_sha256"),
                    "validation_outcome": item.get("validation_outcome"),
                }
                for item in run["attempts"]
            )
            context = RepairContext(
                run_id=request.run_id,
                task_id=request.task_id,
                objective=request.objective,
                attempt_number=attempt_number,
                failure=run.get("failure_context") or {},
                remaining_cost_usd=max(
                    0.0, request.policy.max_cost_usd - float(run["cost_usd"])
                ),
                remaining_wall_seconds=self._deadline_remaining(run),
                prior_attempts=prior_attempts,
            )
            try:
                estimated = float(self.repair_agent.estimate_cost(context))
            except Exception as exc:
                return self._finish(
                    request.run_id,
                    status="blocked",
                    reason="cost_estimate_failed",
                    error=self._portable_error(exc),
                )
            if not math.isfinite(estimated) or estimated < 0:
                return self._finish(
                    request.run_id,
                    status="blocked",
                    reason="invalid_cost_estimate",
                )
            if self._deadline_remaining(run) <= 0:
                return self._finish(
                    request.run_id,
                    status="blocked",
                    reason="wall_clock_limit",
                )
            if float(run["cost_usd"]) + estimated > request.policy.max_cost_usd + 1e-12:
                return self._finish(
                    request.run_id,
                    status="blocked",
                    reason="repair_cost_limit",
                )
            if estimated > 0 and self.budget_guard is None:
                return self._finish(
                    request.run_id,
                    status="blocked",
                    reason="budget_guard_required",
                )

            reservation_id = None
            if self.budget_guard is not None:
                try:
                    reservation_id = self.budget_guard.reserve(
                        task_id=request.task_id,
                        step_id=f"{request.run_id}:attempt:{attempt_number}",
                        amount_usd=estimated,
                        task_limit_usd=request.policy.max_cost_usd,
                        idempotency_key=(
                            f"{request.idempotency_key}:attempt:{attempt_number}"
                        ),
                    )
                except BudgetDenied as exc:
                    return self._finish(
                        request.run_id,
                        status="blocked",
                        reason="budget_denied",
                        error=self._portable_error(exc),
                    )
                except Exception as exc:
                    return self._finish(
                        request.run_id,
                        status="recovery_required",
                        reason="budget_reservation_unknown",
                        error=self._portable_error(exc),
                    )
            if self._deadline_remaining(run) <= 0:
                if reservation_id is not None:
                    self.budget_guard.settle(reservation_id, 0.0)
                return self._finish(
                    request.run_id,
                    status="blocked",
                    reason="wall_clock_limit",
                )

            attempt_id = f"{request.run_id}:attempt:{attempt_number}"
            _, attempt = self.ledger.claim_repair_attempt(
                attempt_id=attempt_id,
                run_id=request.run_id,
                attempt_number=attempt_number,
                agent_label=str(self.repair_agent.label),
                failure_before_sha256=str(run["last_failure_sha256"]),
                estimated_cost_usd=estimated,
            )
            try:
                proposal = self.repair_agent.propose(context)
            except Exception as exc:
                return self._finish(
                    request.run_id,
                    status="recovery_required",
                    reason="proposal_dispatch_unknown",
                    error=self._portable_error(exc),
                )
            if not isinstance(proposal, RepairProposal):
                return self._finish(
                    request.run_id,
                    status="recovery_required",
                    reason="invalid_agent_response",
                    error="Repair agent returned an unsupported response type.",
                )

            proposal_sha = self._proposal_sha(proposal)
            previous_occurrences = sum(
                item.get("proposal_sha256") == proposal_sha for item in run["attempts"]
            )
            if previous_occurrences >= request.policy.max_identical_patches:
                self.ledger.reject_repair_proposal(
                    attempt_id,
                    proposal_sha256=proposal_sha,
                    actual_cost_usd=float(proposal.actual_cost_usd),
                    error="repeated identical repair proposal",
                )
                if reservation_id is not None:
                    self.budget_guard.settle(
                        reservation_id, float(proposal.actual_cost_usd)
                    )
                return self._finish(
                    request.run_id,
                    status="blocked",
                    reason="repeated_identical_patch",
                )

            if float(proposal.actual_cost_usd) > estimated + 1e-12:
                self.ledger.reject_repair_proposal(
                    attempt_id,
                    proposal_sha256=proposal_sha,
                    actual_cost_usd=float(proposal.actual_cost_usd),
                    error="actual repair cost exceeded its reservation",
                )
                if reservation_id is not None:
                    self.budget_guard.settle(
                        reservation_id, float(proposal.actual_cost_usd)
                    )
                return self._finish(
                    request.run_id,
                    status="blocked",
                    reason="cost_reservation_exceeded",
                )

            patch_request = PatchRequest(
                patch_id=f"{request.run_id}:attempt:{attempt_number}:patch",
                idempotency_key=(
                    f"{request.idempotency_key}:attempt:{attempt_number}:patch"
                ),
                actor=request.actor,
                reason=proposal.hypothesis,
                files=proposal.files,
                task_id=request.task_id,
            )
            try:
                self.patch_manager.validate_request(patch_request)
            except Exception as exc:
                self.ledger.reject_repair_proposal(
                    attempt_id,
                    proposal_sha256=proposal_sha,
                    actual_cost_usd=float(proposal.actual_cost_usd),
                    error=self._portable_error(exc),
                )
                if reservation_id is not None:
                    self.budget_guard.settle(
                        reservation_id, float(proposal.actual_cost_usd)
                    )
                run = self.ledger.get_repair_run(run_id=request.run_id)
                assert run is not None
                run = self.ledger.record_repair_progress(
                    request.run_id,
                    last_failure_sha256=str(run["last_failure_sha256"]),
                    failure_context=run.get("failure_context") or {},
                    identical_failure_count=int(run["identical_failure_count"]),
                    no_progress_count=int(run["no_progress_count"]) + 1,
                )
                if int(run["no_progress_count"]) >= request.policy.max_no_progress_attempts:
                    return self._finish(
                        request.run_id,
                        status="blocked",
                        reason="no_progress_limit",
                    )
                continue

            try:
                self.ledger.record_repair_proposal(
                    attempt_id,
                    proposal_sha256=proposal_sha,
                    proposal=self._proposal_record(proposal),
                    hypothesis=proposal.hypothesis,
                    actual_cost_usd=float(proposal.actual_cost_usd),
                )
                if reservation_id is not None:
                    self.budget_guard.settle(
                        reservation_id, float(proposal.actual_cost_usd)
                    )
            except Exception as exc:
                return self._finish(
                    request.run_id,
                    status="recovery_required",
                    reason="proposal_persistence_unknown",
                    error=self._portable_error(exc),
                )
            run = self.ledger.get_repair_run(run_id=request.run_id)
            assert run is not None
            if self._deadline_remaining(run) <= 0:
                return self._finish(
                    request.run_id,
                    status="blocked",
                    reason="wall_clock_limit",
                )
            attempt = run["attempts"][-1]
            completed = self._resume_attempt(request, run, attempt)
            if completed is not None:
                return completed
