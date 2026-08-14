from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ledger import Ledger
from offline_checklist_profile import (
    OfflineChecklistExecutor,
    OfflineChecklistPlanner,
)
from orchestration_kernel import (
    ArtifactConflict,
    DeclaredArtifactWriter,
    KernelPolicy,
    OrchestrationKernel,
    ProjectIdempotencyConflict,
    ProjectRunStatus,
    TaskExecutionContext,
    TaskExecutionResult,
)
from project_contract import AuthorityLevel, parse_project_contract
from task_graph import TaskSpec, validate_task_graph
from workspace_guard import WorkspaceGuard

VALID_CONTRACT = (
    Path(__file__).resolve().parents[1] / "project" / "phase7_sample_goal.md"
).read_text(encoding="utf-8")


def make_runtime(tmp_path: Path, markdown: str = VALID_CONTRACT):
    root = tmp_path / "candidate"
    root.mkdir()
    (root / "project").mkdir()
    contract_path = root / "project" / "goal.md"
    contract_path.write_text(markdown, encoding="utf-8")
    contract = parse_project_contract(markdown, source_path="project/goal.md")
    ledger = Ledger(root / "ledger.db", project_root=root)
    guard = WorkspaceGuard(root)
    return root, contract, ledger, guard


def test_offline_project_runs_to_acceptance_and_replays_without_dispatch(tmp_path):
    root, contract, ledger, guard = make_runtime(tmp_path)
    first_executor = OfflineChecklistExecutor()
    first = OrchestrationKernel(
        ledger=ledger,
        guard=guard,
        planner=OfflineChecklistPlanner(),
        executor=first_executor,
    ).run(contract)
    artifact = root / contract.deliverables[0].path
    first_mtime = artifact.stat().st_mtime_ns
    first_content = artifact.read_text(encoding="utf-8")

    second_executor = OfflineChecklistExecutor()
    second = OrchestrationKernel(
        ledger=Ledger(root / "ledger.db", project_root=root),
        guard=WorkspaceGuard(root),
        planner=OfflineChecklistPlanner(),
        executor=second_executor,
    ).run(contract)

    assert first.completed is True
    assert first.status == ProjectRunStatus.COMPLETED
    assert first.outcome.value == "PASS"
    assert first.completed_tasks == first.task_count == 2
    assert first.iteration_count == 2
    assert first.cost_usd == 0
    assert first_executor.dispatched_task_keys == [
        "compose-checklist",
        "validate-checklist",
    ]
    assert second.completed is True
    assert second.replayed is True
    assert second_executor.call_count == 0
    assert artifact.stat().st_mtime_ns == first_mtime
    assert artifact.read_text(encoding="utf-8") == first_content
    assert all(f"## {section}" in first_content for section in contract.required_content)
    with ledger.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM project_runs").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM task_dispatches").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM project_artifacts").fetchone()[0] == 1
        acceptance = con.execute(
            "SELECT outcome FROM acceptance_runs WHERE task_id=?", (first.run_id,)
        ).fetchone()
    assert acceptance["outcome"] == "PASS"


def test_running_project_resumes_only_incomplete_task(tmp_path):
    root, contract, ledger, guard = make_runtime(tmp_path)
    planner = OfflineChecklistPlanner()
    graph = validate_task_graph(
        tuple(planner.build(contract)),
        max_tasks=contract.policy.max_tasks,
        supported_kinds=planner.supported_kinds,
    )
    kernel = OrchestrationKernel(
        ledger=ledger,
        guard=guard,
        planner=planner,
        executor=OfflineChecklistExecutor(),
    )
    run_id = "phase7-resume-test"
    idempotency_key = "phase7:resume-test:v1"
    request_sha = kernel._request_sha(run_id, idempotency_key, contract, graph)
    kernel.store.claim_run(
        run_id=run_id,
        idempotency_key=idempotency_key,
        contract=contract,
        graph=graph,
        request_sha256=request_sha,
    )
    first_task = graph.tasks[0]
    attempt, dispatch_id = kernel.store.claim_dispatch(
        run_id=run_id,
        task=first_task,
        contract_sha256=contract.contract_sha256,
    )
    first_executor = OfflineChecklistExecutor()
    first_result = first_executor.execute(
        TaskExecutionContext(
            run_id=run_id,
            attempt_number=attempt,
            contract=contract,
            task=first_task,
            artifact_writer=DeclaredArtifactWriter(guard, contract),
        )
    )
    kernel.store.complete_dispatch(
        run_id=run_id,
        task=first_task,
        dispatch_id=dispatch_id,
        result=first_result,
    )

    resumed_executor = OfflineChecklistExecutor()
    resumed = OrchestrationKernel(
        ledger=Ledger(root / "ledger.db", project_root=root),
        guard=WorkspaceGuard(root),
        planner=planner,
        executor=resumed_executor,
    ).run(contract, run_id=run_id, idempotency_key=idempotency_key)

    assert resumed.completed is True
    assert resumed_executor.dispatched_task_keys == ["validate-checklist"]


class OneTaskPlanner:
    profile = "offline-checklist-v1"
    supported_kinds = frozenset({"controlled-task"})

    def __init__(self, task: TaskSpec) -> None:
        self.task = task

    def build(self, _contract):
        return (self.task,)


class CountingExecutor:
    def __init__(self, result: TaskExecutionResult | None = None, error: Exception | None = None):
        self.result = result or TaskExecutionResult(success=True, summary="Completed.")
        self.error = error
        self.call_count = 0

    def execute(self, _context):
        self.call_count += 1
        if self.error:
            raise self.error
        return self.result


def controlled_task(*, authority=AuthorityLevel.READ_ONLY, cost=0.0, attempts=1):
    return TaskSpec(
        task_key="controlled-task",
        title="Controlled task",
        description="Exercise a kernel policy gate.",
        kind="controlled-task",
        authority=authority,
        estimated_cost_usd=cost,
        max_attempts=attempts,
    )


def test_authority_and_positive_cost_are_denied_before_dispatch(tmp_path):
    _root, contract, ledger, guard = make_runtime(tmp_path)
    authority_executor = CountingExecutor()
    authority = OrchestrationKernel(
        ledger=ledger,
        guard=guard,
        planner=OneTaskPlanner(controlled_task(authority=AuthorityLevel.LOCAL_COMMAND)),
        executor=authority_executor,
    ).run(contract, run_id="authority-run", idempotency_key="authority-key")

    paid_markdown = VALID_CONTRACT.replace("Budget USD: `0`", "Budget USD: `10`")
    paid_contract = parse_project_contract(paid_markdown, source_path="project/paid.md")
    paid_executor = CountingExecutor()
    paid = OrchestrationKernel(
        ledger=ledger,
        guard=guard,
        planner=OneTaskPlanner(controlled_task(cost=1.0)),
        executor=paid_executor,
        policy=KernelPolicy(allow_positive_cost=False),
    ).run(paid_contract, run_id="paid-run", idempotency_key="paid-key")

    assert authority.status == ProjectRunStatus.BLOCKED
    assert authority.stop_reason == "authority-disabled:local-command"
    assert authority_executor.call_count == 0
    assert paid.status == ProjectRunStatus.BLOCKED
    assert paid.stop_reason == "positive-cost-disabled"
    assert paid_executor.call_count == 0


def test_executor_exception_is_recovery_required_and_never_redispatched(tmp_path):
    root, contract, ledger, guard = make_runtime(tmp_path)
    failing = CountingExecutor(error=RuntimeError(f"ambiguous failure at {root}"))
    first = OrchestrationKernel(
        ledger=ledger,
        guard=guard,
        planner=OneTaskPlanner(controlled_task()),
        executor=failing,
    ).run(contract, run_id="ambiguous-run", idempotency_key="ambiguous-key")

    replay_executor = CountingExecutor()
    second = OrchestrationKernel(
        ledger=Ledger(root / "ledger.db", project_root=root),
        guard=WorkspaceGuard(root),
        planner=OneTaskPlanner(controlled_task()),
        executor=replay_executor,
    ).run(contract, run_id="ambiguous-run", idempotency_key="ambiguous-key")

    assert first.status == ProjectRunStatus.RECOVERY_REQUIRED
    assert first.stop_reason == "ambiguous-dispatch"
    assert failing.call_count == 1
    assert second.status == ProjectRunStatus.RECOVERY_REQUIRED
    assert second.replayed is True
    assert replay_executor.call_count == 0
    with ledger.connect() as con:
        error = con.execute(
            "SELECT error FROM project_runs WHERE run_id='ambiguous-run'"
        ).fetchone()[0]
    assert str(root) not in error
    assert "<workspace>" in error


def test_retryable_failures_stop_at_no_progress_limit(tmp_path):
    _root, contract, ledger, guard = make_runtime(tmp_path)
    executor = CountingExecutor(
        result=TaskExecutionResult(
            success=False,
            summary="Known deterministic failure.",
            retryable=True,
        )
    )
    result = OrchestrationKernel(
        ledger=ledger,
        guard=guard,
        planner=OneTaskPlanner(controlled_task(attempts=3)),
        executor=executor,
    ).run(contract, run_id="no-progress-run", idempotency_key="no-progress-key")

    assert result.status == ProjectRunStatus.FAILED
    assert result.stop_reason == "no-progress-limit"
    assert executor.call_count == 2


def test_changed_contract_conflicts_under_same_idempotency_key(tmp_path):
    _root, contract, ledger, guard = make_runtime(tmp_path)
    planner = OneTaskPlanner(controlled_task())
    first = OrchestrationKernel(
        ledger=ledger,
        guard=guard,
        planner=planner,
        executor=CountingExecutor(),
    )
    first.run(contract, run_id="stable-run", idempotency_key="stable-key")
    changed = parse_project_contract(
        VALID_CONTRACT.replace("concise Markdown", "detailed Markdown"),
        source_path="project/goal.md",
    )

    with pytest.raises(ProjectIdempotencyConflict):
        OrchestrationKernel(
            ledger=ledger,
            guard=guard,
            planner=planner,
            executor=CountingExecutor(),
        ).run(changed, run_id="stable-run", idempotency_key="stable-key")


def test_artifact_writer_rejects_undeclared_and_conflicting_content(tmp_path):
    root, contract, _ledger, guard = make_runtime(tmp_path)
    writer = DeclaredArtifactWriter(guard, contract)
    with pytest.raises(PermissionError, match="not declared"):
        writer.write_text("outputs/not-declared.md", "blocked")

    path = contract.deliverables[0].path
    first = writer.write_text(path, "stable content")
    same = writer.write_text(path, "stable content")
    assert same == first
    assert first.content_sha256 == hashlib.sha256(b"stable content").hexdigest()
    with pytest.raises(ArtifactConflict, match="different content"):
        writer.write_text(path, "changed content")
    assert (root / path).read_text(encoding="utf-8") == "stable content"
