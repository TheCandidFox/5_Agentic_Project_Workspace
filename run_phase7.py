from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ledger import Ledger
from offline_checklist_profile import (
    OfflineChecklistExecutor,
    OfflineChecklistPlanner,
)
from orchestration_kernel import (
    KernelPolicy,
    OrchestrationKernel,
    ProjectRunResult,
)
from project_contract import (
    AuthorityLevel,
    ProjectContract,
    load_project_contract,
)
from run_bootstrap_phase6 import Phase6BootstrapReport, run_bootstrap_phase6
from task_graph import TaskGraph, validate_task_graph
from workspace_guard import WorkspaceGuard


ORCHESTRATION_TABLES = frozenset(
    {
        "project_runs",
        "backlog_tasks",
        "backlog_dependencies",
        "task_dispatches",
        "project_artifacts",
    }
)


@dataclass(frozen=True)
class Phase7Report:
    phase6: Phase6BootstrapReport
    integrity: str
    migrations: tuple[str, ...]
    newly_applied_migrations: tuple[str, ...]
    orchestration_tables_ready: bool
    contract: ProjectContract
    graph: TaskGraph
    policy_ready: bool
    status_only: bool
    first_result: ProjectRunResult | None = None
    replay_result: ProjectRunResult | None = None
    first_dispatch_calls: int = 0
    replay_dispatch_calls: int = 0

    @property
    def schema_ready(self) -> bool:
        return (
            "0006_project_orchestration" in self.migrations
            and self.orchestration_tables_ready
        )

    @property
    def passed(self) -> bool:
        base = (
            self.phase6.passed
            and self.integrity == "ok"
            and self.schema_ready
            and self.policy_ready
            and len(self.graph.tasks) > 0
        )
        if self.status_only:
            return base
        return (
            base
            and self.first_result is not None
            and self.first_result.completed
            and self.replay_result is not None
            and self.replay_result.completed
            and self.replay_result.replayed
            and self.replay_dispatch_calls == 0
        )


def run_phase7(
    *,
    project_root: str | Path,
    ledger_path: str | Path,
    contract_path: str | Path = "project/phase7_sample_goal.md",
    status_only: bool = False,
    run_id: str | None = None,
    git_executable: str | Path | None = None,
) -> Phase7Report:
    root = Path(project_root).resolve()
    guard = WorkspaceGuard(root)
    contract = load_project_contract(guard, contract_path)
    planner = OfflineChecklistPlanner()
    graph = validate_task_graph(
        tuple(planner.build(contract)),
        max_tasks=contract.policy.max_tasks,
        supported_kinds=planner.supported_kinds,
    )
    phase6 = run_bootstrap_phase6(
        project_root=root,
        ledger_path=ledger_path,
        status_only=True,
        git_executable=git_executable or shutil.which("git"),
    )
    ledger = Ledger(ledger_path, project_root=root)
    with ledger.connect() as con:
        tables = {
            str(row["name"])
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        run_columns = {
            str(row["name"])
            for row in con.execute("PRAGMA table_info(project_runs)").fetchall()
        }
        task_columns = {
            str(row["name"])
            for row in con.execute("PRAGMA table_info(backlog_tasks)").fetchall()
        }
    tables_ready = ORCHESTRATION_TABLES.issubset(tables) and {
        "contract_sha256",
        "graph_sha256",
        "deadline_at",
        "acceptance_evaluation_id",
    }.issubset(run_columns) and {
        "authority",
        "attempt_count",
        "result_json",
    }.issubset(task_columns)
    kernel_policy = KernelPolicy()
    policy_ready = (
        contract.policy.profile == planner.profile
        and contract.policy.authority_ceiling == AuthorityLevel.WORKSPACE_WRITE
        and contract.policy.budget_usd == 0
        and kernel_policy.allowed_authorities
        == frozenset({AuthorityLevel.READ_ONLY, AuthorityLevel.WORKSPACE_WRITE})
        and not kernel_policy.allow_positive_cost
        and all(task.estimated_cost_usd == 0 for task in graph.tasks)
        and all(task.authority in kernel_policy.allowed_authorities for task in graph.tasks)
    )

    first_result = None
    replay_result = None
    first_calls = 0
    replay_calls = 0
    if (
        not status_only
        and phase6.passed
        and ledger.integrity_check() == "ok"
        and tables_ready
        and policy_ready
    ):
        executor = OfflineChecklistExecutor()
        kernel = OrchestrationKernel(
            ledger=ledger,
            guard=guard,
            planner=planner,
            executor=executor,
            policy=kernel_policy,
        )
        first_result = kernel.run(contract, run_id=run_id)
        first_calls = executor.call_count
        calls_before_replay = executor.call_count
        replay_result = kernel.run(contract, run_id=run_id)
        replay_calls = executor.call_count - calls_before_replay

    return Phase7Report(
        phase6=phase6,
        integrity=ledger.integrity_check(),
        migrations=ledger.schema_migration_ids(),
        newly_applied_migrations=phase6.newly_applied_migrations,
        orchestration_tables_ready=tables_ready,
        contract=contract,
        graph=graph,
        policy_ready=policy_ready,
        status_only=status_only,
        first_result=first_result,
        replay_result=replay_result,
        first_dispatch_calls=first_calls,
        replay_dispatch_calls=replay_calls,
    )


def print_report(report: Phase7Report) -> None:
    mode = "status" if report.status_only else "sample run"
    print(f"Phase 7 Markdown project orchestration {mode} (offline, zero cost)")
    print(
        f"[{'PASS' if report.phase6.passed else 'FAIL'}] "
        "Phase 1-6 execution/research/acceptance foundation"
    )
    print(
        f"[{'PASS' if report.integrity == 'ok' else 'FAIL'}] "
        f"SQLite integrity: {report.integrity}"
    )
    migrations = ", ".join(report.migrations) or "none"
    newly = ", ".join(report.newly_applied_migrations) or "none"
    print(
        f"[{'PASS' if report.schema_ready else 'FAIL'}] "
        f"orchestration schema: {migrations}; newly_applied={newly}"
    )
    print(
        "[PASS] Markdown contract: "
        f"{report.contract.source_path}; id={report.contract.contract_id}; "
        f"criteria={len(report.contract.acceptance_criteria)}; "
        f"deliverables={len(report.contract.deliverables)}"
    )
    print(
        f"[{'PASS' if report.policy_ready else 'FAIL'}] "
        f"profile={report.contract.policy.profile}; "
        f"authority={report.contract.policy.authority_ceiling.value}; "
        f"budget=${report.contract.policy.budget_usd:.2f}"
    )
    print(
        f"[PASS] durable backlog DAG: tasks={len(report.graph.tasks)}; "
        f"order={','.join(report.graph.topological_order)}"
    )
    if report.first_result is not None:
        first = report.first_result
        print(
            f"[{'PASS' if first.completed else 'FAIL'}] first execution: "
            f"status={first.status.value}; outcome="
            f"{first.outcome.value if first.outcome else 'none'}; "
            f"tasks={first.completed_tasks}/{first.task_count}; "
            f"dispatch_calls={report.first_dispatch_calls}; cost=${first.cost_usd:.2f}"
        )
        for artifact in first.artifacts:
            print(
                f"[PASS] artifact: {artifact.path}; bytes={artifact.content_bytes}; "
                f"sha256={artifact.content_sha256[:12]}"
            )
    if report.replay_result is not None:
        replay = report.replay_result
        print(
            f"[{'PASS' if replay.completed and replay.replayed and report.replay_dispatch_calls == 0 else 'FAIL'}] "
            f"completed replay: replayed={replay.replayed}; "
            f"new_dispatch_calls={report.replay_dispatch_calls}"
        )
    else:
        print("[INFO] status-only mode did not dispatch tasks or write artifacts")
    label = "status" if report.status_only else "result"
    print(f"Phase 7 {label}: {'PASS' if report.passed else 'FAIL'}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Phase 7 deterministic Markdown project profile."
    )
    parser.add_argument("--status-only", action="store_true")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).parent)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("project/phase7_sample_goal.md"),
    )
    parser.add_argument("--ledger", type=Path, default=Path("ledger.db"))
    parser.add_argument("--run-id")
    parser.add_argument("--git-executable", type=Path)
    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    ledger_path = args.ledger
    if not ledger_path.is_absolute():
        ledger_path = root / ledger_path
    contract_path = args.contract
    if contract_path.is_absolute():
        try:
            contract_path = contract_path.resolve().relative_to(root)
        except ValueError as exc:
            parser.error(f"contract path must be inside project root: {exc}")
    try:
        report = run_phase7(
            project_root=root,
            ledger_path=ledger_path,
            contract_path=contract_path,
            status_only=args.status_only,
            run_id=args.run_id,
            git_executable=args.git_executable or shutil.which("git"),
        )
        print_report(report)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}".replace(str(root), "<workspace>")
        print(f"Phase 7 stopped safely: {message}", file=sys.stderr)
        return 1
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
