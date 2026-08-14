from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from acceptance_truth import (
    AcceptanceEngine,
    AcceptanceOutcome,
    AcceptanceRequest,
    ClaimAssessment,
    ConstraintFinding,
    CriterionAssessment,
    CriterionVerdict,
    EvidenceDisposition,
    EvidenceKind,
    EvidenceRef,
    TruthLabel,
)
from ledger import Ledger, utc_now
from project_contract import AuthorityLevel, ProjectContract
from task_graph import TaskGraph, TaskSpec, validate_task_graph
from workspace_guard import WorkspaceGuard


class ProjectOrchestrationError(RuntimeError):
    """Base error for the durable Phase 7 orchestration layer."""


class ProjectIdempotencyConflict(ProjectOrchestrationError):
    """A durable project key was reused with changed semantics."""


class AmbiguousTaskDispatch(ProjectOrchestrationError):
    """A task has a dispatch claim without a terminal durable result."""


class ArtifactConflict(ProjectOrchestrationError):
    """A declared artifact already exists with unexpected content."""


class ProjectRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    PAUSED = "paused"
    RECOVERY_REQUIRED = "recovery_required"


TERMINAL_PROJECT_STATES = frozenset(
    {
        ProjectRunStatus.COMPLETED.value,
        ProjectRunStatus.FAILED.value,
        ProjectRunStatus.BLOCKED.value,
        ProjectRunStatus.PAUSED.value,
        ProjectRunStatus.RECOVERY_REQUIRED.value,
    }
)


@dataclass(frozen=True)
class ArtifactRecord:
    path: str
    content_sha256: str
    content_bytes: int
    media_type: str = "text/markdown"

    def __post_init__(self) -> None:
        if not self.path or "\x00" in self.path or Path(self.path).is_absolute():
            raise ValueError("artifact path must be project-relative")
        digest = self.content_sha256.casefold()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("artifact content_sha256 must be a SHA-256 digest")
        object.__setattr__(self, "content_sha256", digest)
        if not isinstance(self.content_bytes, int) or not 0 <= self.content_bytes <= 1_000_000:
            raise ValueError("artifact content_bytes is outside the supported bound")
        if not self.media_type or len(self.media_type) > 200 or "\x00" in self.media_type:
            raise ValueError("artifact media_type is invalid")


@dataclass(frozen=True)
class TaskEvidence:
    evidence_key: str
    kind: EvidenceKind
    disposition: EvidenceDisposition
    summary: str
    reference: str

    def __post_init__(self) -> None:
        for name, value, maximum in (
            ("evidence_key", self.evidence_key, 120),
            ("summary", self.summary, 2_000),
            ("reference", self.reference, 1_000),
        ):
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                raise ValueError(f"{name} must be non-empty safe text")
            if len(value) > maximum:
                raise ValueError(f"{name} exceeds {maximum} characters")
        if not isinstance(self.kind, EvidenceKind):
            raise TypeError("task evidence kind must be an EvidenceKind")
        if not isinstance(self.disposition, EvidenceDisposition):
            raise TypeError("task evidence disposition must be an EvidenceDisposition")


@dataclass(frozen=True)
class CriterionResult:
    criterion_key: str
    verdict: CriterionVerdict
    evidence_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.criterion_key or "\x00" in self.criterion_key:
            raise ValueError("criterion result key is required")
        if not isinstance(self.verdict, CriterionVerdict):
            raise TypeError("criterion result verdict must be a CriterionVerdict")
        if not isinstance(self.evidence_keys, tuple):
            raise TypeError("criterion result evidence_keys must be a tuple")
        if len(self.evidence_keys) != len(set(self.evidence_keys)):
            raise ValueError("criterion result evidence_keys must be unique")


@dataclass(frozen=True)
class ConstraintResult:
    constraint_key: str
    violated: bool
    evidence_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.constraint_key or "\x00" in self.constraint_key:
            raise ValueError("constraint result key is required")
        if not isinstance(self.violated, bool):
            raise TypeError("constraint result violated must be boolean")
        if not isinstance(self.evidence_keys, tuple):
            raise TypeError("constraint result evidence_keys must be a tuple")


@dataclass(frozen=True)
class TaskExecutionResult:
    success: bool
    summary: str
    evidence: tuple[TaskEvidence, ...] = ()
    criteria: tuple[CriterionResult, ...] = ()
    constraints: tuple[ConstraintResult, ...] = ()
    artifacts: tuple[ArtifactRecord, ...] = ()
    actual_cost_usd: float = 0.0
    retryable: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool) or not isinstance(self.retryable, bool):
            raise TypeError("task success and retryable flags must be boolean")
        if not isinstance(self.summary, str) or not self.summary.strip() or "\x00" in self.summary:
            raise ValueError("task result summary is required")
        if len(self.summary) > 4_000:
            raise ValueError("task result summary exceeds 4000 characters")
        for name, values, expected in (
            ("evidence", self.evidence, TaskEvidence),
            ("criteria", self.criteria, CriterionResult),
            ("constraints", self.constraints, ConstraintResult),
            ("artifacts", self.artifacts, ArtifactRecord),
        ):
            if not isinstance(values, tuple) or not all(
                isinstance(item, expected) for item in values
            ):
                raise TypeError(f"{name} must be a tuple of {expected.__name__} values")
        if len({item.evidence_key for item in self.evidence}) != len(self.evidence):
            raise ValueError("task result evidence keys must be unique")
        if len({item.criterion_key for item in self.criteria}) != len(self.criteria):
            raise ValueError("task result criterion keys must be unique")
        if len({item.constraint_key for item in self.constraints}) != len(self.constraints):
            raise ValueError("task result constraint keys must be unique")
        if len({item.path.casefold() for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("task result artifact paths must be unique")
        known_evidence = {item.evidence_key for item in self.evidence}
        for item in (*self.criteria, *self.constraints):
            if not set(item.evidence_keys).issubset(known_evidence):
                raise ValueError("task result references unknown evidence")
        cost = float(self.actual_cost_usd)
        if not math.isfinite(cost) or cost < 0 or cost > 10_000:
            raise ValueError("task actual cost must be finite and between 0 and 10000")
        object.__setattr__(self, "actual_cost_usd", cost)

    def payload(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "summary": self.summary,
            "evidence": [
                {
                    **asdict(item),
                    "kind": item.kind.value,
                    "disposition": item.disposition.value,
                }
                for item in self.evidence
            ],
            "criteria": [
                {
                    **asdict(item),
                    "verdict": item.verdict.value,
                    "evidence_keys": list(item.evidence_keys),
                }
                for item in self.criteria
            ],
            "constraints": [
                {**asdict(item), "evidence_keys": list(item.evidence_keys)}
                for item in self.constraints
            ],
            "artifacts": [asdict(item) for item in self.artifacts],
            "actual_cost_usd": self.actual_cost_usd,
            "retryable": self.retryable,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> TaskExecutionResult:
        return cls(
            success=bool(payload["success"]),
            summary=str(payload["summary"]),
            evidence=tuple(
                TaskEvidence(
                    evidence_key=str(item["evidence_key"]),
                    kind=EvidenceKind(str(item["kind"])),
                    disposition=EvidenceDisposition(str(item["disposition"])),
                    summary=str(item["summary"]),
                    reference=str(item["reference"]),
                )
                for item in payload.get("evidence", [])
            ),
            criteria=tuple(
                CriterionResult(
                    criterion_key=str(item["criterion_key"]),
                    verdict=CriterionVerdict(str(item["verdict"])),
                    evidence_keys=tuple(str(key) for key in item.get("evidence_keys", [])),
                )
                for item in payload.get("criteria", [])
            ),
            constraints=tuple(
                ConstraintResult(
                    constraint_key=str(item["constraint_key"]),
                    violated=bool(item["violated"]),
                    evidence_keys=tuple(str(key) for key in item.get("evidence_keys", [])),
                )
                for item in payload.get("constraints", [])
            ),
            artifacts=tuple(
                ArtifactRecord(
                    path=str(item["path"]),
                    content_sha256=str(item["content_sha256"]),
                    content_bytes=int(item["content_bytes"]),
                    media_type=str(item["media_type"]),
                )
                for item in payload.get("artifacts", [])
            ),
            actual_cost_usd=float(payload.get("actual_cost_usd", 0)),
            retryable=bool(payload.get("retryable", False)),
        )


class ProjectPlanner(Protocol):
    profile: str
    supported_kinds: frozenset[str]

    def build(self, contract: ProjectContract) -> Sequence[TaskSpec]: ...


class TaskExecutor(Protocol):
    def execute(self, context: TaskExecutionContext) -> TaskExecutionResult: ...


@dataclass(frozen=True)
class TaskExecutionContext:
    run_id: str
    attempt_number: int
    contract: ProjectContract
    task: TaskSpec
    artifact_writer: DeclaredArtifactWriter


@dataclass(frozen=True)
class KernelPolicy:
    allowed_authorities: frozenset[AuthorityLevel] = field(
        default_factory=lambda: frozenset(
            {AuthorityLevel.READ_ONLY, AuthorityLevel.WORKSPACE_WRITE}
        )
    )
    allow_positive_cost: bool = False


@dataclass(frozen=True)
class ProjectRunResult:
    run_id: str
    contract_id: str
    status: ProjectRunStatus
    outcome: AcceptanceOutcome | None
    stop_reason: str | None
    completed_tasks: int
    task_count: int
    iteration_count: int
    cost_usd: float
    artifacts: tuple[ArtifactRecord, ...]
    acceptance_evaluation_id: str | None
    replayed: bool = False

    @property
    def completed(self) -> bool:
        return self.status == ProjectRunStatus.COMPLETED and self.outcome == AcceptanceOutcome.PASS


class DeclaredArtifactWriter:
    def __init__(
        self,
        guard: WorkspaceGuard,
        contract: ProjectContract,
        *,
        max_bytes: int = 131_072,
    ) -> None:
        self.guard = guard
        self.allowed_paths = frozenset(item.path for item in contract.deliverables)
        self.max_bytes = max_bytes

    def write_text(self, path: str, content: str) -> ArtifactRecord:
        if path not in self.allowed_paths:
            raise PermissionError(f"artifact path was not declared by the contract: {path}")
        if not isinstance(content, str) or "\x00" in content:
            raise ValueError("artifact content must be NUL-free text")
        data = content.encode("utf-8")
        if not data or len(data) > self.max_bytes:
            raise ValueError(f"artifact must contain 1 to {self.max_bytes} bytes")
        authorized = self.guard.authorize_write(path, expect_directory=False)
        authorized.path.parent.mkdir(parents=True, exist_ok=True)
        authorized = self.guard.authorize_write(path, expect_directory=False)
        digest = hashlib.sha256(data).hexdigest()
        if authorized.path.exists():
            if not authorized.path.is_file():
                raise ArtifactConflict(f"artifact target is not a file: {path}")
            existing = authorized.path.read_bytes()
            if hashlib.sha256(existing).hexdigest() != digest:
                raise ArtifactConflict(f"artifact target already has different content: {path}")
            return ArtifactRecord(path, digest, len(data))

        handle = tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".phase7-artifact-",
            dir=authorized.path.parent,
            delete=False,
        )
        temporary = Path(handle.name)
        try:
            with handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, authorized.path)
        finally:
            temporary.unlink(missing_ok=True)
        return ArtifactRecord(path, digest, len(data))

    def read_text(self, path: str) -> str:
        if path not in self.allowed_paths:
            raise PermissionError(f"artifact path was not declared by the contract: {path}")
        authorized = self.guard.authorize_read(path, expect_directory=False)
        raw = authorized.path.read_bytes()
        if len(raw) > self.max_bytes:
            raise ValueError(f"artifact exceeds {self.max_bytes} bytes")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("artifact must be valid UTF-8") from exc


def _json(payload: Any) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    if len(serialized.encode("utf-8")) > 131_072:
        raise ValueError("durable orchestration payload exceeds 131072 bytes")
    return serialized


def _sha(payload: Any) -> str:
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _safe_error(exc: BaseException, root: Path) -> str:
    message = f"{type(exc).__name__}: {exc}".replace(str(root), "<workspace>")
    return message[:4_000]


class OrchestrationStore:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    @staticmethod
    def _task_record_id(run_id: str, task_key: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"phase7-task:{run_id}:{task_key}"))

    @staticmethod
    def _artifact_id(run_id: str, path: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"phase7-artifact:{run_id}:{path}"))

    def claim_run(
        self,
        *,
        run_id: str,
        idempotency_key: str,
        contract: ProjectContract,
        graph: TaskGraph,
        request_sha256: str,
    ) -> tuple[bool, dict[str, Any]]:
        now = utc_now()
        deadline = (
            datetime.now(timezone.utc)
            + timedelta(seconds=contract.policy.max_runtime_seconds)
        ).isoformat()
        policy_payload = {
            **asdict(contract.policy),
            "authority_ceiling": contract.policy.authority_ceiling.value,
        }
        with self.ledger.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute(
                "SELECT * FROM project_runs WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                record = dict(existing)
                if record["request_sha256"] != request_sha256:
                    raise ProjectIdempotencyConflict(
                        "project idempotency key belongs to a different contract or plan"
                    )
                return False, record
            same_run = con.execute(
                "SELECT request_sha256 FROM project_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if same_run is not None:
                raise ProjectIdempotencyConflict("project run_id is already in use")
            con.execute(
                """
                INSERT INTO project_runs(
                    run_id, contract_id, contract_path, contract_sha256,
                    idempotency_key, request_sha256, graph_sha256, profile,
                    policy_json, status, task_count, started_at, deadline_at,
                    updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,'running',?,?,?,?)
                """,
                (
                    run_id,
                    contract.contract_id,
                    contract.source_path,
                    contract.contract_sha256,
                    idempotency_key,
                    request_sha256,
                    graph.graph_sha256,
                    contract.policy.profile,
                    _json(policy_payload),
                    len(graph.tasks),
                    now,
                    deadline,
                    now,
                ),
            )
            for ordinal, task in enumerate(graph.tasks, start=1):
                con.execute(
                    """
                    INSERT INTO backlog_tasks(
                        task_record_id, run_id, task_key, ordinal, title,
                        description, kind, authority, estimated_cost_usd,
                        max_attempts, inputs_json, status, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,'pending',?)
                    """,
                    (
                        self._task_record_id(run_id, task.task_key),
                        run_id,
                        task.task_key,
                        ordinal,
                        task.title,
                        task.description,
                        task.kind,
                        task.authority.value,
                        task.estimated_cost_usd,
                        task.max_attempts,
                        _json(task.inputs),
                        now,
                    ),
                )
            for task in graph.tasks:
                for dependency in task.dependencies:
                    con.execute(
                        """
                        INSERT INTO backlog_dependencies(
                            run_id, task_key, depends_on_task_key
                        ) VALUES(?,?,?)
                        """,
                        (run_id, task.task_key, dependency),
                    )
        self.ledger.event(
            "project_run_started",
            {
                "run_id": run_id,
                "contract_id": contract.contract_id,
                "graph_sha256": graph.graph_sha256,
                "task_count": len(graph.tasks),
                "profile": contract.policy.profile,
            },
            run_id,
        )
        return True, self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self.ledger.connect() as con:
            row = con.execute("SELECT * FROM project_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown project run: {run_id}")
        record = dict(row)
        record["policy"] = json.loads(record.pop("policy_json"))
        return record

    def task_records(self, run_id: str) -> list[dict[str, Any]]:
        with self.ledger.connect() as con:
            rows = con.execute(
                "SELECT * FROM backlog_tasks WHERE run_id=? ORDER BY ordinal",
                (run_id,),
            ).fetchall()
            dependencies = con.execute(
                """
                SELECT task_key, depends_on_task_key
                FROM backlog_dependencies WHERE run_id=?
                ORDER BY task_key, depends_on_task_key
                """,
                (run_id,),
            ).fetchall()
        dependency_map: dict[str, list[str]] = {}
        for item in dependencies:
            dependency_map.setdefault(str(item["task_key"]), []).append(
                str(item["depends_on_task_key"])
            )
        records: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            record["inputs"] = json.loads(record.pop("inputs_json"))
            result_json = record.pop("result_json")
            record["result"] = json.loads(result_json) if result_json else None
            record["dependencies"] = tuple(dependency_map.get(record["task_key"], []))
            records.append(record)
        return records

    def ambiguous_dispatches(self, run_id: str) -> tuple[str, ...]:
        with self.ledger.connect() as con:
            rows = con.execute(
                """
                SELECT task_key FROM task_dispatches
                WHERE run_id=? AND status='dispatching'
                ORDER BY task_key
                """,
                (run_id,),
            ).fetchall()
        return tuple(str(row["task_key"]) for row in rows)

    def claim_dispatch(
        self,
        *,
        run_id: str,
        task: TaskSpec,
        contract_sha256: str,
    ) -> tuple[int, str]:
        now = utc_now()
        with self.ledger.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT * FROM backlog_tasks WHERE run_id=? AND task_key=?",
                (run_id, task.task_key),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown backlog task: {task.task_key}")
            if row["status"] == "running":
                raise AmbiguousTaskDispatch(
                    f"task already has a non-terminal dispatch: {task.task_key}"
                )
            if row["status"] != "pending":
                raise ProjectOrchestrationError(
                    f"task cannot dispatch from state {row['status']}: {task.task_key}"
                )
            attempt = int(row["attempt_count"]) + 1
            if attempt > int(row["max_attempts"]):
                raise ProjectOrchestrationError(
                    f"task attempt limit is exhausted: {task.task_key}"
                )
            idempotency_key = f"phase7:{run_id}:{task.task_key}:attempt:{attempt}"
            request_sha256 = _sha(
                {
                    "contract_sha256": contract_sha256,
                    "run_id": run_id,
                    "attempt": attempt,
                    "task": task.payload(int(row["ordinal"])),
                }
            )
            dispatch_id = str(uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key))
            existing = con.execute(
                "SELECT * FROM task_dispatches WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if existing["request_sha256"] != request_sha256:
                    raise ProjectIdempotencyConflict(
                        "task dispatch key belongs to changed semantics"
                    )
                raise AmbiguousTaskDispatch(
                    f"task dispatch already exists without reusable completion: {task.task_key}"
                )
            con.execute(
                """
                INSERT INTO task_dispatches(
                    dispatch_id, run_id, task_key, attempt_number,
                    idempotency_key, request_sha256, status, started_at,
                    updated_at
                ) VALUES(?,?,?,?,?,?,'dispatching',?,?)
                """,
                (
                    dispatch_id,
                    run_id,
                    task.task_key,
                    attempt,
                    idempotency_key,
                    request_sha256,
                    now,
                    now,
                ),
            )
            con.execute(
                """
                UPDATE backlog_tasks
                SET status='running', attempt_count=?, started_at=COALESCE(started_at,?),
                    updated_at=?
                WHERE run_id=? AND task_key=?
                """,
                (attempt, now, now, run_id, task.task_key),
            )
        return attempt, dispatch_id

    def complete_dispatch(
        self,
        *,
        run_id: str,
        task: TaskSpec,
        dispatch_id: str,
        result: TaskExecutionResult,
    ) -> None:
        now = utc_now()
        payload = result.payload()
        with self.ledger.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            dispatch = con.execute(
                "SELECT * FROM task_dispatches WHERE dispatch_id=?", (dispatch_id,)
            ).fetchone()
            if dispatch is None or dispatch["status"] != "dispatching":
                raise AmbiguousTaskDispatch("task dispatch is not durably dispatching")
            task_row = con.execute(
                "SELECT * FROM backlog_tasks WHERE run_id=? AND task_key=?",
                (run_id, task.task_key),
            ).fetchone()
            if task_row is None or task_row["status"] != "running":
                raise AmbiguousTaskDispatch("backlog task is not durably running")
            attempt_count = int(task_row["attempt_count"])
            if result.success:
                next_status = "completed"
            elif result.retryable and attempt_count < int(task_row["max_attempts"]):
                next_status = "pending"
            else:
                next_status = "failed"

            con.execute(
                """
                UPDATE task_dispatches
                SET status=?, result_json=?, actual_cost_usd=?, completed_at=?,
                    updated_at=?
                WHERE dispatch_id=?
                """,
                (
                    "succeeded" if result.success else "failed",
                    _json(payload),
                    result.actual_cost_usd,
                    now,
                    now,
                    dispatch_id,
                ),
            )
            con.execute(
                """
                UPDATE backlog_tasks
                SET status=?, result_json=?, actual_cost_usd=actual_cost_usd+?,
                    error=?, completed_at=?, updated_at=?
                WHERE run_id=? AND task_key=?
                """,
                (
                    next_status,
                    _json(payload),
                    result.actual_cost_usd,
                    None if result.success else result.summary[:4_000],
                    now if next_status in {"completed", "failed"} else None,
                    now,
                    run_id,
                    task.task_key,
                ),
            )
            for artifact in result.artifacts:
                con.execute(
                    """
                    INSERT INTO project_artifacts(
                        artifact_id, run_id, task_key, path, content_sha256,
                        content_bytes, media_type, created_at
                    ) VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(run_id, path) DO UPDATE SET
                        content_sha256=excluded.content_sha256,
                        content_bytes=excluded.content_bytes,
                        media_type=excluded.media_type
                    """,
                    (
                        self._artifact_id(run_id, artifact.path),
                        run_id,
                        task.task_key,
                        artifact.path,
                        artifact.content_sha256,
                        artifact.content_bytes,
                        artifact.media_type,
                        now,
                    ),
                )
            completed_count = int(
                con.execute(
                    """
                    SELECT COUNT(*) FROM backlog_tasks
                    WHERE run_id=? AND status='completed'
                    """,
                    (run_id,),
                ).fetchone()[0]
            )
            project_state = con.execute(
                "SELECT no_progress_count FROM project_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if project_state is None:
                raise KeyError(f"unknown project run: {run_id}")
            con.execute(
                """
                UPDATE project_runs
                SET completed_task_count=?, iteration_count=iteration_count+1,
                    no_progress_count=?, cost_usd=cost_usd+?, updated_at=?
                WHERE run_id=?
                """,
                (
                    completed_count,
                    0 if result.success else int(project_state["no_progress_count"]) + 1,
                    result.actual_cost_usd,
                    now,
                    run_id,
                ),
            )
        self.ledger.event(
            "project_task_completed" if result.success else "project_task_failed",
            {
                "run_id": run_id,
                "task_key": task.task_key,
                "dispatch_id": dispatch_id,
                "cost_usd": result.actual_cost_usd,
                "artifact_count": len(result.artifacts),
            },
            run_id,
        )

    def mark_task_blocked(self, run_id: str, task_key: str, reason: str) -> None:
        now = utc_now()
        with self.ledger.connect() as con:
            con.execute(
                """
                UPDATE backlog_tasks SET status='blocked', error=?, completed_at=?,
                    updated_at=? WHERE run_id=? AND task_key=?
                """,
                (reason[:4_000], now, now, run_id, task_key),
            )

    def finish_run(
        self,
        run_id: str,
        *,
        status: ProjectRunStatus,
        outcome: AcceptanceOutcome | None,
        stop_reason: str,
        acceptance_evaluation_id: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.ledger.connect() as con:
            con.execute(
                """
                UPDATE project_runs
                SET status=?, outcome=?, acceptance_evaluation_id=?, stop_reason=?,
                    error=?, completed_at=?, updated_at=?
                WHERE run_id=?
                """,
                (
                    status.value,
                    outcome.value if outcome else None,
                    acceptance_evaluation_id,
                    stop_reason[:1_000],
                    error[:4_000] if error else None,
                    now,
                    now,
                    run_id,
                ),
            )
        self.ledger.event(
            "project_run_finished",
            {
                "run_id": run_id,
                "status": status.value,
                "outcome": outcome.value if outcome else None,
                "stop_reason": stop_reason[:1_000],
            },
            run_id,
        )
        return self.get_run(run_id)

    def artifacts(self, run_id: str) -> tuple[ArtifactRecord, ...]:
        with self.ledger.connect() as con:
            rows = con.execute(
                """
                SELECT path, content_sha256, content_bytes, media_type
                FROM project_artifacts WHERE run_id=? ORDER BY path
                """,
                (run_id,),
            ).fetchall()
        return tuple(
            ArtifactRecord(
                path=str(row["path"]),
                content_sha256=str(row["content_sha256"]),
                content_bytes=int(row["content_bytes"]),
                media_type=str(row["media_type"]),
            )
            for row in rows
        )

    def result(self, run_id: str, *, replayed: bool) -> ProjectRunResult:
        record = self.get_run(run_id)
        outcome = (
            AcceptanceOutcome(str(record["outcome"])) if record["outcome"] else None
        )
        return ProjectRunResult(
            run_id=run_id,
            contract_id=str(record["contract_id"]),
            status=ProjectRunStatus(str(record["status"])),
            outcome=outcome,
            stop_reason=record["stop_reason"],
            completed_tasks=int(record["completed_task_count"]),
            task_count=int(record["task_count"]),
            iteration_count=int(record["iteration_count"]),
            cost_usd=float(record["cost_usd"]),
            artifacts=self.artifacts(run_id),
            acceptance_evaluation_id=record["acceptance_evaluation_id"],
            replayed=replayed,
        )


class OrchestrationKernel:
    def __init__(
        self,
        *,
        ledger: Ledger,
        guard: WorkspaceGuard,
        planner: ProjectPlanner,
        executor: TaskExecutor,
        policy: KernelPolicy | None = None,
    ) -> None:
        self.ledger = ledger
        self.guard = guard
        self.planner = planner
        self.executor = executor
        self.policy = policy or KernelPolicy()
        self.store = OrchestrationStore(ledger)

    @staticmethod
    def _request_sha(
        run_id: str,
        idempotency_key: str,
        contract: ProjectContract,
        graph: TaskGraph,
    ) -> str:
        return _sha(
            {
                "schema_version": 1,
                "run_id": run_id,
                "idempotency_key": idempotency_key,
                "contract_sha256": contract.contract_sha256,
                "graph_sha256": graph.graph_sha256,
                "profile": contract.policy.profile,
                "policy": {
                    **asdict(contract.policy),
                    "authority_ceiling": contract.policy.authority_ceiling.value,
                },
            }
        )

    def _deny_reason(
        self,
        task: TaskSpec,
        contract: ProjectContract,
        current_cost: float,
    ) -> str | None:
        if task.authority not in self.policy.allowed_authorities:
            return f"authority-disabled:{task.authority.value}"
        if not contract.policy.authority_ceiling.permits(task.authority):
            return f"authority-ceiling:{task.authority.value}"
        if task.estimated_cost_usd > 0 and not self.policy.allow_positive_cost:
            return "positive-cost-disabled"
        if current_cost + task.estimated_cost_usd > contract.policy.budget_usd + 1e-12:
            return "project-budget-exceeded"
        return None

    def _accept(
        self,
        run_id: str,
        contract: ProjectContract,
        records: Sequence[Mapping[str, Any]],
    ) -> ProjectRunResult:
        task_results = [
            TaskExecutionResult.from_payload(record["result"])
            for record in records
            if record["result"] is not None
        ]
        evidence_by_key: dict[str, TaskEvidence] = {}
        criterion_results: dict[str, CriterionResult] = {}
        constraint_results: dict[str, ConstraintResult] = {}
        for result in task_results:
            for evidence in result.evidence:
                existing = evidence_by_key.get(evidence.evidence_key)
                if existing is not None and existing != evidence:
                    raise ProjectOrchestrationError(
                        f"conflicting task evidence: {evidence.evidence_key}"
                    )
                evidence_by_key[evidence.evidence_key] = evidence
            for criterion in result.criteria:
                existing = criterion_results.get(criterion.criterion_key)
                if existing is not None and existing != criterion:
                    raise ProjectOrchestrationError(
                        f"conflicting criterion result: {criterion.criterion_key}"
                    )
                criterion_results[criterion.criterion_key] = criterion
            for constraint in result.constraints:
                existing = constraint_results.get(constraint.constraint_key)
                if existing is not None and existing != constraint:
                    raise ProjectOrchestrationError(
                        f"conflicting constraint result: {constraint.constraint_key}"
                    )
                constraint_results[constraint.constraint_key] = constraint

        expected_criteria = {item.criterion_key for item in contract.acceptance_criteria}
        expected_constraints = {item.constraint_key for item in contract.constraints}
        if set(criterion_results) != expected_criteria:
            missing = sorted(expected_criteria.difference(criterion_results))
            extra = sorted(set(criterion_results).difference(expected_criteria))
            raise ProjectOrchestrationError(
                f"criterion evidence coverage mismatch; missing={missing}; extra={extra}"
            )
        if set(constraint_results) != expected_constraints:
            missing = sorted(expected_constraints.difference(constraint_results))
            extra = sorted(set(constraint_results).difference(expected_constraints))
            raise ProjectOrchestrationError(
                f"constraint evidence coverage mismatch; missing={missing}; extra={extra}"
            )

        evidence = tuple(
            EvidenceRef(
                evidence_key=item.evidence_key,
                kind=item.kind,
                disposition=item.disposition,
                summary=item.summary,
                reference=item.reference,
            )
            for item in evidence_by_key.values()
        )
        criteria = tuple(
            CriterionAssessment(
                criterion_key=item.criterion_key,
                description=item.description,
                required=True,
                verdict=criterion_results[item.criterion_key].verdict,
                evidence_keys=criterion_results[item.criterion_key].evidence_keys,
                unresolved_action=AcceptanceOutcome.DEFER,
            )
            for item in contract.acceptance_criteria
        )
        constraints = tuple(
            ConstraintFinding(
                constraint_key=item.constraint_key,
                description=item.description,
                violated=constraint_results[item.constraint_key].violated,
                evidence_keys=constraint_results[item.constraint_key].evidence_keys,
            )
            for item in contract.constraints
        )
        supportive = tuple(
            item.evidence_key
            for item in evidence
            if item.disposition == EvidenceDisposition.SUPPORTS
            and item.kind in {EvidenceKind.DETERMINISTIC_VALIDATION, EvidenceKind.OBSERVATION}
        )
        claims: tuple[ClaimAssessment, ...] = ()
        if supportive:
            claims = (
                ClaimAssessment(
                    claim_key="project-evidence-recorded",
                    statement="The project run produced governed deterministic evidence.",
                    truth_label=TruthLabel.VERIFIED,
                    evidence_keys=supportive,
                ),
            )
        acceptance_id = f"phase7-acceptance-{hashlib.sha256(run_id.encode()).hexdigest()[:20]}"
        acceptance = AcceptanceEngine(self.ledger).evaluate(
            AcceptanceRequest(
                evaluation_id=acceptance_id,
                task_id=run_id,
                objective=contract.goal,
                idempotency_key=f"phase7:{run_id}:acceptance:v1",
                evidence=evidence,
                claims=claims,
                criteria=criteria,
                constraints=constraints,
            )
        )
        status_by_outcome = {
            AcceptanceOutcome.PASS: ProjectRunStatus.COMPLETED,
            AcceptanceOutcome.REPAIR: ProjectRunStatus.FAILED,
            AcceptanceOutcome.BLOCK: ProjectRunStatus.BLOCKED,
            AcceptanceOutcome.HUMAN_DECISION: ProjectRunStatus.PAUSED,
            AcceptanceOutcome.DEFER: ProjectRunStatus.PAUSED,
        }
        self.store.finish_run(
            run_id,
            status=status_by_outcome[acceptance.outcome],
            outcome=acceptance.outcome,
            stop_reason=f"acceptance-{acceptance.outcome.value.casefold()}",
            acceptance_evaluation_id=acceptance.evaluation_id,
        )
        return self.store.result(run_id, replayed=False)

    def run(
        self,
        contract: ProjectContract,
        *,
        run_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ProjectRunResult:
        if contract.policy.profile != self.planner.profile:
            raise ProjectOrchestrationError(
                f"planner profile does not match contract: {contract.policy.profile}"
            )
        tasks = tuple(self.planner.build(contract))
        graph = validate_task_graph(
            tasks,
            max_tasks=contract.policy.max_tasks,
            supported_kinds=self.planner.supported_kinds,
        )
        selected_run_id = run_id or f"phase7-{contract.contract_sha256[:20]}"
        selected_key = idempotency_key or (
            f"phase7:{contract.contract_sha256}:run:{selected_run_id}:v1"
        )
        request_sha256 = self._request_sha(
            selected_run_id, selected_key, contract, graph
        )
        claimed, record = self.store.claim_run(
            run_id=selected_run_id,
            idempotency_key=selected_key,
            contract=contract,
            graph=graph,
            request_sha256=request_sha256,
        )
        if not claimed and record["status"] in TERMINAL_PROJECT_STATES:
            return self.store.result(selected_run_id, replayed=True)

        ambiguous = self.store.ambiguous_dispatches(selected_run_id)
        if ambiguous:
            self.store.finish_run(
                selected_run_id,
                status=ProjectRunStatus.RECOVERY_REQUIRED,
                outcome=None,
                stop_reason="ambiguous-dispatch",
                error=f"non-terminal dispatches: {', '.join(ambiguous)}",
            )
            return self.store.result(selected_run_id, replayed=False)

        writer = DeclaredArtifactWriter(self.guard, contract)
        by_key = graph.by_key
        while True:
            run_record = self.store.get_run(selected_run_id)
            task_records = self.store.task_records(selected_run_id)
            running_without_reusable_result = [
                str(item["task_key"])
                for item in task_records
                if item["status"] == "running"
            ]
            if running_without_reusable_result:
                self.store.finish_run(
                    selected_run_id,
                    status=ProjectRunStatus.RECOVERY_REQUIRED,
                    outcome=None,
                    stop_reason="ambiguous-task-state",
                    error=(
                        "running tasks lack a terminal reusable result: "
                        + ", ".join(running_without_reusable_result)
                    ),
                )
                return self.store.result(selected_run_id, replayed=False)
            completed = {
                str(item["task_key"])
                for item in task_records
                if item["status"] == "completed"
            }
            if len(completed) == len(graph.tasks):
                try:
                    return self._accept(selected_run_id, contract, task_records)
                except Exception as exc:
                    self.store.finish_run(
                        selected_run_id,
                        status=ProjectRunStatus.BLOCKED,
                        outcome=None,
                        stop_reason="acceptance-evidence-invalid",
                        error=_safe_error(exc, self.guard.root),
                    )
                    return self.store.result(selected_run_id, replayed=False)

            failed = [item for item in task_records if item["status"] == "failed"]
            blocked = [item for item in task_records if item["status"] == "blocked"]
            if failed or blocked:
                state = ProjectRunStatus.BLOCKED if blocked else ProjectRunStatus.FAILED
                reason = "task-blocked" if blocked else "task-failed"
                self.store.finish_run(
                    selected_run_id,
                    status=state,
                    outcome=None,
                    stop_reason=reason,
                )
                return self.store.result(selected_run_id, replayed=False)

            deadline = datetime.fromisoformat(str(run_record["deadline_at"]))
            if datetime.now(timezone.utc) >= deadline:
                self.store.finish_run(
                    selected_run_id,
                    status=ProjectRunStatus.FAILED,
                    outcome=None,
                    stop_reason="runtime-limit",
                )
                return self.store.result(selected_run_id, replayed=False)
            if int(run_record["iteration_count"]) >= contract.policy.max_iterations:
                self.store.finish_run(
                    selected_run_id,
                    status=ProjectRunStatus.FAILED,
                    outcome=None,
                    stop_reason="iteration-limit",
                )
                return self.store.result(selected_run_id, replayed=False)
            if int(run_record["no_progress_count"]) >= contract.policy.max_no_progress:
                self.store.finish_run(
                    selected_run_id,
                    status=ProjectRunStatus.FAILED,
                    outcome=None,
                    stop_reason="no-progress-limit",
                )
                return self.store.result(selected_run_id, replayed=False)

            terminal = {
                str(item["task_key"])
                for item in task_records
                if item["status"] in {"failed", "blocked"}
            }
            ready = graph.ready_tasks(completed=completed, terminal=terminal)
            ready = tuple(
                task
                for task in ready
                if next(
                    item for item in task_records if item["task_key"] == task.task_key
                )["status"]
                == "pending"
            )
            if not ready:
                self.store.finish_run(
                    selected_run_id,
                    status=ProjectRunStatus.BLOCKED,
                    outcome=None,
                    stop_reason="dependency-deadlock",
                )
                return self.store.result(selected_run_id, replayed=False)
            task = ready[0]
            deny_reason = self._deny_reason(
                task,
                contract,
                float(run_record["cost_usd"]),
            )
            if deny_reason:
                self.store.mark_task_blocked(selected_run_id, task.task_key, deny_reason)
                self.store.finish_run(
                    selected_run_id,
                    status=ProjectRunStatus.BLOCKED,
                    outcome=None,
                    stop_reason=deny_reason,
                )
                return self.store.result(selected_run_id, replayed=False)

            try:
                attempt, dispatch_id = self.store.claim_dispatch(
                    run_id=selected_run_id,
                    task=by_key[task.task_key],
                    contract_sha256=contract.contract_sha256,
                )
                result = self.executor.execute(
                    TaskExecutionContext(
                        run_id=selected_run_id,
                        attempt_number=attempt,
                        contract=contract,
                        task=task,
                        artifact_writer=writer,
                    )
                )
                if not isinstance(result, TaskExecutionResult):
                    raise TypeError("task executor must return TaskExecutionResult")
                if result.actual_cost_usd > task.estimated_cost_usd + 1e-12:
                    raise ProjectOrchestrationError(
                        f"task actual cost exceeds its estimate: {task.task_key}"
                    )
                declared = {item.path for item in contract.deliverables}
                if any(artifact.path not in declared for artifact in result.artifacts):
                    raise ProjectOrchestrationError("task returned an undeclared artifact")
                for artifact in result.artifacts:
                    authorized = self.guard.authorize_read(
                        artifact.path, expect_directory=False
                    )
                    actual = authorized.path.read_bytes()
                    if len(actual) != artifact.content_bytes or hashlib.sha256(
                        actual
                    ).hexdigest() != artifact.content_sha256:
                        raise ProjectOrchestrationError(
                            f"task returned mismatched artifact evidence: {artifact.path}"
                        )
                self.store.complete_dispatch(
                    run_id=selected_run_id,
                    task=task,
                    dispatch_id=dispatch_id,
                    result=result,
                )
            except Exception as exc:
                self.store.finish_run(
                    selected_run_id,
                    status=ProjectRunStatus.RECOVERY_REQUIRED,
                    outcome=None,
                    stop_reason="ambiguous-dispatch",
                    error=_safe_error(exc, self.guard.root),
                )
                return self.store.result(selected_run_id, replayed=False)
