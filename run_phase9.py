from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Sequence

from ledger import Ledger
from orchestration_kernel import KernelPolicy, OrchestrationKernel, ProjectRunResult
from project_contract import AuthorityLevel, ProjectContract, load_project_contract
from provider_fixtures import ScriptedProviderClient, recovering_phase9_replies
from provider_gateway import ProviderClient, ProviderExecutionMode, ProviderRoute
from recovery_live_profile import RecoveryLiveExecutor, RecoveryLivePlanner
from run_diagnostics import build_diagnostic_bundle, write_diagnostic_bundle
from run_phase8 import Phase8Mode, Phase8Report, Phase8Routes, run_phase8
from task_graph import TaskGraph, validate_task_graph
from workspace_guard import WorkspaceGuard


class Phase9Mode(str, Enum):
    STATUS = "status"
    RECOVERY_CANARY = "recovery-canary"
    PREPARE_LIVE = "prepare-live"
    LIVE = "live"


@dataclass(frozen=True)
class Phase9Routes:
    composer: ProviderRoute
    reviewer: ProviderRoute

    @property
    def all(self) -> tuple[ProviderRoute, ProviderRoute]:
        return self.composer, self.reviewer


@dataclass(frozen=True)
class Phase9Report:
    phase8: Phase8Report
    integrity: str
    migrations: tuple[str, ...]
    newly_applied_migrations: tuple[str, ...]
    provider_schema_ready: bool
    contract: ProjectContract
    graph: TaskGraph
    routes: Phase9Routes
    mode: Phase9Mode
    policy_ready: bool
    approval_token: str
    first_result: ProjectRunResult | None = None
    replay_result: ProjectRunResult | None = None
    first_provider_calls: int = 0
    replay_provider_calls: int = 0
    composer_calls: int = 0
    reviewer_calls: int = 0
    known_truncations: int = 0
    provider_cost_usd: float = 0.0
    diagnostic_path: str | None = None
    diagnostic_sha256: str | None = None

    @property
    def schema_ready(self) -> bool:
        return (
            "0008_recovery_observability" in self.migrations
            and self.provider_schema_ready
        )

    @property
    def passed(self) -> bool:
        base = (
            self.phase8.passed
            and self.integrity == "ok"
            and self.schema_ready
            and self.policy_ready
            and len(self.graph.tasks) == 2
            and self.graph.by_key["review-markdown"].max_attempts == 2
        )
        if self.mode in {Phase9Mode.STATUS, Phase9Mode.PREPARE_LIVE}:
            return base and self.first_provider_calls == 0
        execution = (
            self.first_result is not None
            and self.first_result.completed
            and (
                (not self.first_result.replayed and self.first_provider_calls in {2, 3})
                or (self.first_result.replayed and self.first_provider_calls == 0)
            )
            and self.replay_result is not None
            and self.replay_result.completed
            and self.replay_result.replayed
            and self.replay_provider_calls == 0
            and self.composer_calls == 1
            and self.reviewer_calls in {1, 2}
            and self.diagnostic_path is not None
            and self.diagnostic_sha256 is not None
        )
        if self.mode == Phase9Mode.RECOVERY_CANARY:
            execution = (
                execution
                and (
                    (not self.first_result.replayed and self.first_provider_calls == 3)
                    or (self.first_result.replayed and self.first_provider_calls == 0)
                )
                and self.reviewer_calls == 2
                and self.known_truncations == 1
                and self.provider_cost_usd == 0
            )
        return base and execution


def approval_token(
    *,
    contract: ProjectContract,
    graph: TaskGraph,
    routes: Phase9Routes,
    daily_limit_usd: float,
    monthly_limit_usd: float,
) -> str:
    payload = {
        "schema_version": 2,
        "contract_sha256": contract.contract_sha256,
        "graph_sha256": graph.graph_sha256,
        "profile": contract.policy.profile,
        "project_budget_usd": contract.policy.budget_usd,
        "daily_limit_usd": float(daily_limit_usd),
        "monthly_limit_usd": float(monthly_limit_usd),
        "routes": [
            {
                "role": role,
                "provider": route.provider,
                "model": route.model,
                "max_output_tokens": route.max_output_tokens,
                "input_per_mtok": route.input_per_mtok,
                "output_per_mtok": route.output_per_mtok,
            }
            for role, route in (
                ("composer", routes.composer),
                ("reviewer", routes.reviewer),
            )
        ],
        "prompt_templates": ["phase9-compose-v2", "phase9-review-v2"],
        "recovery": {
            "reviewer_max_attempts": 2,
            "retryable_failure_kinds": ["response-truncated"],
        },
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return "phase9-live-" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:20]


def _progress(event, context, result) -> None:
    segment = 3 if context.task.task_key == "compose-markdown" else 4
    name = "Compose" if segment == 3 else "Verify"
    if event == "started":
        print(
            f"[ACTIVE] {segment}/5 {name}: task={context.task.task_key}; "
            f"attempt={context.attempt_number}/{context.task.max_attempts}"
        )
        return
    assert result is not None
    status = "PASS" if result.success else "RETRY" if result.retryable else "FAIL"
    print(
        f"[{status}] {segment}/5 {name}: task={context.task.task_key}; "
        f"attempt={context.attempt_number}; cost=${result.actual_cost_usd:.6f}"
    )


def run_phase9(
    *,
    project_root: str | Path,
    ledger_path: str | Path,
    contract_path: str | Path,
    routes: Phase9Routes,
    mode: Phase9Mode = Phase9Mode.STATUS,
    approval: str | None = None,
    run_id: str | None = None,
    daily_limit_usd: float = 5.0,
    monthly_limit_usd: float = 150.0,
    git_executable: str | Path | None = None,
    provider_client_factory: Callable[[], ProviderClient] | None = None,
    emit_progress: bool = False,
) -> Phase9Report:
    if not isinstance(mode, Phase9Mode):
        raise TypeError("mode must be a Phase9Mode")
    root = Path(project_root).resolve()
    guard = WorkspaceGuard(root)
    contract = load_project_contract(guard, contract_path)
    planner = RecoveryLivePlanner(
        composer_route=routes.composer,
        reviewer_route=routes.reviewer,
    )
    graph = validate_task_graph(
        tuple(planner.build(contract)),
        max_tasks=contract.policy.max_tasks,
        supported_kinds=planner.supported_kinds,
    )
    phase8 = run_phase8(
        project_root=root,
        ledger_path=ledger_path,
        contract_path="project/phase8_live_canary_goal.md",
        routes=Phase8Routes(routes.composer, routes.reviewer),
        mode=Phase8Mode.STATUS,
        git_executable=git_executable or shutil.which("git"),
    )
    ledger = Ledger(ledger_path, project_root=root)
    with ledger.connect() as connection:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(provider_calls)").fetchall()
        }
    provider_schema_ready = {
        "failure_kind",
        "response_excerpt",
        "response_excerpt_sha256",
    }.issubset(columns)
    token = approval_token(
        contract=contract,
        graph=graph,
        routes=routes,
        daily_limit_usd=daily_limit_usd,
        monthly_limit_usd=monthly_limit_usd,
    )
    kernel_policy = KernelPolicy(
        allowed_authorities=frozenset(
            {
                AuthorityLevel.READ_ONLY,
                AuthorityLevel.WORKSPACE_WRITE,
                AuthorityLevel.LIVE_NETWORK,
            }
        ),
        allow_positive_cost=True,
    )
    policy_ready = (
        contract.policy.profile == planner.profile
        and contract.policy.authority_ceiling == AuthorityLevel.LIVE_NETWORK
        and 0 < contract.policy.budget_usd <= 5
        and contract.policy.max_no_progress >= 2
        and graph.by_key["compose-markdown"].max_attempts == 1
        and graph.by_key["review-markdown"].max_attempts == 2
        and abs(
            sum(task.estimated_cost_usd for task in graph.tasks)
            - contract.policy.budget_usd
        )
        <= 1e-9
        and AuthorityLevel.EXTERNAL_SIDE_EFFECT not in kernel_policy.allowed_authorities
    )

    first_result = None
    replay_result = None
    first_calls = 0
    replay_calls = 0
    selected_run_id: str | None = None
    diagnostic_path = None
    diagnostic_sha = None
    if mode in {Phase9Mode.RECOVERY_CANARY, Phase9Mode.LIVE}:
        if not phase8.passed or ledger.integrity_check() != "ok":
            raise RuntimeError("Phase 8 foundation is not ready")
        if not provider_schema_ready or not policy_ready:
            raise RuntimeError("Phase 9 schema or policy gate is not ready")
        if mode == Phase9Mode.LIVE and approval != token:
            raise PermissionError(
                "live approval fingerprint does not match the prepared Phase 9 configuration"
            )
        if mode == Phase9Mode.RECOVERY_CANARY:
            client = (
                provider_client_factory()
                if provider_client_factory is not None
                else ScriptedProviderClient(
                    recovering_phase9_replies(
                        contract,
                        composer_provider=routes.composer.provider,
                        composer_model=routes.composer.model,
                        reviewer_provider=routes.reviewer.provider,
                        reviewer_model=routes.reviewer.model,
                        reviewer_max_output_tokens=routes.reviewer.max_output_tokens,
                    )
                )
            )
            execution_mode = ProviderExecutionMode.OFFLINE_SIMULATION
            selected_run_id = run_id or f"phase9-recovery-{contract.contract_sha256[:20]}"
        else:
            if provider_client_factory is None:
                from dotenv import load_dotenv
                from provider_adapter import ProviderAdapter

                load_dotenv(root / ".env", override=False)
                client = ProviderAdapter()
            else:
                client = provider_client_factory()
            execution_mode = ProviderExecutionMode.LIVE
            selected_run_id = run_id or f"phase9-live-{contract.contract_sha256[:20]}"

        from provider_gateway import GovernedProviderGateway

        gateway = GovernedProviderGateway(
            ledger=ledger,
            client=client,
            execution_mode=execution_mode,
            approved_routes=routes.all,
            daily_limit_usd=daily_limit_usd,
            monthly_limit_usd=monthly_limit_usd,
            live_authorized=(mode == Phase9Mode.LIVE and approval == token),
        )
        executor = RecoveryLiveExecutor(
            gateway=gateway,
            composer_route=routes.composer,
            reviewer_route=routes.reviewer,
            progress_callback=_progress if emit_progress else None,
        )
        kernel = OrchestrationKernel(
            ledger=ledger,
            guard=guard,
            planner=planner,
            executor=executor,
            policy=kernel_policy,
        )
        key = (
            f"phase9:{execution_mode.value}:{contract.contract_sha256}:"
            f"run:{selected_run_id}:v2"
        )
        first_result = kernel.run(contract, run_id=selected_run_id, idempotency_key=key)
        first_calls = gateway.call_count
        before_replay = gateway.call_count
        replay_result = kernel.run(
            contract, run_id=selected_run_id, idempotency_key=key
        )
        replay_calls = gateway.call_count - before_replay
        bundle = build_diagnostic_bundle(
            ledger, project_root=root, run_id=selected_run_id
        )
        diagnostic_path, diagnostic_sha = write_diagnostic_bundle(
            guard,
            bundle,
            output_path=f"logs/diagnostics/{selected_run_id}.json",
        )

    composer_calls = reviewer_calls = truncations = 0
    provider_cost = 0.0
    if selected_run_id is not None:
        with ledger.connect() as connection:
            rows = connection.execute(
                """
                SELECT task_key,failure_kind,estimated_cost_usd
                FROM provider_calls WHERE run_id=?
                """,
                (selected_run_id,),
            ).fetchall()
        composer_calls = sum(row["task_key"] == "compose-markdown" for row in rows)
        reviewer_calls = sum(row["task_key"] == "review-markdown" for row in rows)
        truncations = sum(row["failure_kind"] == "response-truncated" for row in rows)
        provider_cost = sum(float(row["estimated_cost_usd"] or 0) for row in rows)

    return Phase9Report(
        phase8=phase8,
        integrity=ledger.integrity_check(),
        migrations=ledger.schema_migration_ids(),
        newly_applied_migrations=phase8.newly_applied_migrations,
        provider_schema_ready=provider_schema_ready,
        contract=contract,
        graph=graph,
        routes=routes,
        mode=mode,
        policy_ready=policy_ready,
        approval_token=token,
        first_result=first_result,
        replay_result=replay_result,
        first_provider_calls=first_calls,
        replay_provider_calls=replay_calls,
        composer_calls=composer_calls,
        reviewer_calls=reviewer_calls,
        known_truncations=truncations,
        provider_cost_usd=provider_cost,
        diagnostic_path=diagnostic_path,
        diagnostic_sha256=diagnostic_sha,
    )


def print_report(report: Phase9Report) -> None:
    label = {
        Phase9Mode.STATUS: "status",
        Phase9Mode.RECOVERY_CANARY: "offline recovery canary",
        Phase9Mode.PREPARE_LIVE: "live preparation",
        Phase9Mode.LIVE: "live canary",
    }[report.mode]
    print(f"Phase 9 recovery and observability {label}")
    print(f"Overall goal: {report.contract.goal}")
    print(f"[{'PASS' if report.phase8.passed else 'FAIL'}] 1/5 Govern: Phase 1-8 foundation")
    print(
        f"[{'PASS' if report.schema_ready and report.policy_ready else 'FAIL'}] "
        f"2/5 Plan: profile={report.contract.policy.profile}; tasks=2; "
        "reviewer attempts=2"
    )
    print(f"[{'PASS' if report.integrity == 'ok' else 'FAIL'}] SQLite integrity: {report.integrity}")
    print(
        f"[{'PASS' if report.schema_ready else 'FAIL'}] recovery schema: "
        f"{', '.join(report.migrations)}; newly_applied="
        f"{','.join(report.newly_applied_migrations) or 'none'}"
    )
    print(
        f"[PASS] routes: composer={report.routes.composer.provider}/"
        f"{report.routes.composer.model}; reviewer={report.routes.reviewer.provider}/"
        f"{report.routes.reviewer.model}"
    )
    if report.mode == Phase9Mode.STATUS:
        print("[INFO] status-only made no provider call and wrote no artifact")
    elif report.mode == Phase9Mode.PREPARE_LIVE:
        print("[PASS] prepared approval fingerprint: " + report.approval_token)
        print("[INFO] preparation made no provider call and wrote no artifact")
    elif report.first_result is not None and report.replay_result is not None:
        print(
            f"[{'PASS' if report.first_result.completed else 'FAIL'}] execution: "
            f"status={report.first_result.status.value}; "
            f"outcome={report.first_result.outcome.value if report.first_result.outcome else 'none'}; "
            f"tasks={report.first_result.completed_tasks}/{report.first_result.task_count}; "
            f"calls={report.first_provider_calls}; cost=${report.provider_cost_usd:.6f}"
        )
        print(
            f"[{'PASS' if report.composer_calls == 1 else 'FAIL'}] 3/5 Compose: "
            f"calls={report.composer_calls}; preserved across reviewer recovery"
        )
        print(
            f"[{'PASS' if report.reviewer_calls in {1, 2} else 'FAIL'}] 4/5 Verify: "
            f"calls={report.reviewer_calls}; known_truncations={report.known_truncations}"
        )
        print(
            f"[{'PASS' if report.replay_result.replayed and report.replay_provider_calls == 0 else 'FAIL'}] "
            f"5/5 Handoff: replayed={report.replay_result.replayed}; "
            f"new_provider_calls={report.replay_provider_calls}"
        )
        if report.first_result.artifacts:
            artifact = report.first_result.artifacts[0]
            print(
                f"[PASS] artifact: {artifact.path}; bytes={artifact.content_bytes}; "
                f"sha256={artifact.content_sha256[:12]}"
            )
        print(
            f"[PASS] diagnostic bundle: {report.diagnostic_path}; "
            f"sha256={report.diagnostic_sha256[:12]}"
        )
        print(
            "Current step: preserve the accepted artifact and use the diagnostic "
            "bundle as the continuation reference."
        )
    print("Phase 9 result:", "PASS" if report.passed else "FAIL")


def _provider_defaults(provider: str) -> tuple[str, float, float]:
    if provider == "openai":
        return (
            os.getenv("OPENAI_MID_MODEL", "gpt-5.6-terra"),
            float(os.getenv("OPENAI_INPUT_PER_MTOK", "2.50")),
            float(os.getenv("OPENAI_OUTPUT_PER_MTOK", "15.00")),
        )
    if provider == "anthropic":
        return (
            os.getenv("ANTHROPIC_MID_MODEL", "claude-sonnet-5"),
            float(os.getenv("ANTHROPIC_INPUT_PER_MTOK", "2.00")),
            float(os.getenv("ANTHROPIC_OUTPUT_PER_MTOK", "10.00")),
        )
    raise ValueError(f"unsupported provider: {provider}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 9 recovery and observability")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--status-only", action="store_true")
    modes.add_argument("--recovery-canary", action="store_true")
    modes.add_argument("--prepare-live", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--contract", default="project/phase9_recovery_canary_goal.md")
    parser.add_argument("--approval")
    parser.add_argument("--run-id")
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--ledger", default="ledger.db")
    parser.add_argument("--composer-provider", choices=("openai", "anthropic"), default="openai")
    parser.add_argument("--composer-model")
    parser.add_argument("--reviewer-provider", choices=("openai", "anthropic"), default="anthropic")
    parser.add_argument("--reviewer-model")
    parser.add_argument("--composer-max-output-tokens", type=int, default=4000)
    parser.add_argument("--reviewer-max-output-tokens", type=int, default=5000)
    parser.add_argument("--daily-limit-usd", type=float, default=5.0)
    parser.add_argument("--monthly-limit-usd", type=float, default=150.0)
    parser.add_argument("--git-executable")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    mode = (
        Phase9Mode.RECOVERY_CANARY
        if args.recovery_canary
        else Phase9Mode.PREPARE_LIVE
        if args.prepare_live
        else Phase9Mode.LIVE
        if args.live
        else Phase9Mode.STATUS
    )
    root = Path(args.project_root).resolve()
    ledger_path = Path(args.ledger)
    if not ledger_path.is_absolute():
        ledger_path = root / ledger_path
    try:
        composer_model, composer_input, composer_output = _provider_defaults(
            args.composer_provider
        )
        reviewer_model, reviewer_input, reviewer_output = _provider_defaults(
            args.reviewer_provider
        )
        routes = Phase9Routes(
            composer=ProviderRoute(
                args.composer_provider,
                args.composer_model or composer_model,
                args.composer_max_output_tokens,
                composer_input,
                composer_output,
            ),
            reviewer=ProviderRoute(
                args.reviewer_provider,
                args.reviewer_model or reviewer_model,
                args.reviewer_max_output_tokens,
                reviewer_input,
                reviewer_output,
            ),
        )
        report = run_phase9(
            project_root=root,
            ledger_path=ledger_path,
            contract_path=args.contract,
            routes=routes,
            mode=mode,
            approval=args.approval,
            run_id=args.run_id,
            daily_limit_usd=args.daily_limit_usd,
            monthly_limit_usd=args.monthly_limit_usd,
            git_executable=args.git_executable or shutil.which("git"),
            emit_progress=mode in {Phase9Mode.RECOVERY_CANARY, Phase9Mode.LIVE},
        )
        print_report(report)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}".replace(str(root), "<workspace>")
        print(f"Phase 9 stopped safely: {message}", file=sys.stderr)
        return 1
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
