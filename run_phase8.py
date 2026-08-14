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

from governed_live_profile import GovernedLiveExecutor, GovernedLivePlanner
from ledger import Ledger
from orchestration_kernel import KernelPolicy, OrchestrationKernel, ProjectRunResult
from project_contract import AuthorityLevel, ProjectContract, load_project_contract
from provider_fixtures import ScriptedProviderClient, passing_phase8_replies
from provider_gateway import (
    ProviderClient,
    ProviderExecutionMode,
    ProviderRoute,
)
from run_phase7 import Phase7Report, run_phase7
from task_graph import TaskGraph, validate_task_graph
from workspace_guard import WorkspaceGuard


PROVIDER_TABLES = frozenset({"provider_calls"})


class Phase8Mode(str, Enum):
    STATUS = "status"
    MOCK = "mock-canary"
    PREPARE_LIVE = "prepare-live"
    LIVE = "live"


@dataclass(frozen=True)
class Phase8Routes:
    composer: ProviderRoute
    reviewer: ProviderRoute

    @property
    def all(self) -> tuple[ProviderRoute, ProviderRoute]:
        return self.composer, self.reviewer


@dataclass(frozen=True)
class Phase8Report:
    phase7: Phase7Report
    integrity: str
    migrations: tuple[str, ...]
    newly_applied_migrations: tuple[str, ...]
    provider_schema_ready: bool
    contract: ProjectContract
    graph: TaskGraph
    routes: Phase8Routes
    mode: Phase8Mode
    policy_ready: bool
    approval_token: str
    first_result: ProjectRunResult | None = None
    replay_result: ProjectRunResult | None = None
    first_provider_calls: int = 0
    replay_provider_calls: int = 0
    durable_provider_calls: int = 0

    @property
    def schema_ready(self) -> bool:
        return (
            "0007_governed_provider_calls" in self.migrations
            and self.provider_schema_ready
        )

    @property
    def passed(self) -> bool:
        base = (
            self.phase7.passed
            and self.integrity == "ok"
            and self.schema_ready
            and self.policy_ready
            and len(self.graph.tasks) == 2
        )
        if self.mode in {Phase8Mode.STATUS, Phase8Mode.PREPARE_LIVE}:
            return base and self.durable_provider_calls == 0
        first_execution_valid = (
            self.first_result is not None
            and self.first_result.completed
            and (
                (not self.first_result.replayed and self.first_provider_calls == 2)
                or (self.first_result.replayed and self.first_provider_calls == 0)
            )
        )
        return (
            base
            and first_execution_valid
            and self.replay_result is not None
            and self.replay_result.completed
            and self.replay_result.replayed
            and self.replay_provider_calls == 0
        )


def approval_token(
    *,
    contract: ProjectContract,
    graph: TaskGraph,
    routes: Phase8Routes,
    daily_limit_usd: float,
    monthly_limit_usd: float,
) -> str:
    payload = {
        "schema_version": 1,
        "contract_sha256": contract.contract_sha256,
        "graph_sha256": graph.graph_sha256,
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
        "prompt_templates": ["phase8-compose-v1", "phase8-review-v1"],
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"phase8-live-{digest[:20]}"


def run_phase8(
    *,
    project_root: str | Path,
    ledger_path: str | Path,
    contract_path: str | Path,
    routes: Phase8Routes,
    mode: Phase8Mode = Phase8Mode.STATUS,
    approval: str | None = None,
    run_id: str | None = None,
    daily_limit_usd: float = 5.0,
    monthly_limit_usd: float = 150.0,
    git_executable: str | Path | None = None,
    provider_client_factory: Callable[[], ProviderClient] | None = None,
) -> Phase8Report:
    if not isinstance(mode, Phase8Mode):
        raise TypeError("mode must be a Phase8Mode")
    root = Path(project_root).resolve()
    guard = WorkspaceGuard(root)
    contract = load_project_contract(guard, contract_path)
    planner = GovernedLivePlanner(
        composer_route=routes.composer,
        reviewer_route=routes.reviewer,
    )
    graph = validate_task_graph(
        tuple(planner.build(contract)),
        max_tasks=contract.policy.max_tasks,
        supported_kinds=planner.supported_kinds,
    )
    phase7 = run_phase7(
        project_root=root,
        ledger_path=ledger_path,
        contract_path="project/phase7_sample_goal.md",
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
        provider_columns = {
            str(row["name"])
            for row in con.execute("PRAGMA table_info(provider_calls)").fetchall()
        }
        durable_calls_before = int(
            con.execute("SELECT COUNT(*) FROM provider_calls").fetchone()[0]
        )
    provider_schema_ready = PROVIDER_TABLES.issubset(tables) and {
        "request_sha256",
        "execution_mode",
        "prompt_sha256",
        "response_schema",
        "quoted_cost_usd",
        "response_sha256",
        "response_json",
        "input_tokens",
        "output_tokens",
        "estimated_cost_usd",
    }.issubset(provider_columns)
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
        and all(task.authority == AuthorityLevel.LIVE_NETWORK for task in graph.tasks)
        and abs(
            sum(task.estimated_cost_usd for task in graph.tasks)
            - contract.policy.budget_usd
        )
        <= 1e-9
        and kernel_policy.allow_positive_cost
        and AuthorityLevel.EXTERNAL_SIDE_EFFECT
        not in kernel_policy.allowed_authorities
    )

    first_result = None
    replay_result = None
    first_calls = 0
    replay_calls = 0
    if mode in {Phase8Mode.MOCK, Phase8Mode.LIVE}:
        if not phase7.passed or ledger.integrity_check() != "ok":
            raise RuntimeError("Phase 7 foundation is not ready")
        if not provider_schema_ready or not policy_ready:
            raise RuntimeError("Phase 8 schema or policy gate is not ready")
        if mode == Phase8Mode.LIVE and approval != token:
            raise PermissionError(
                "live approval fingerprint does not match the prepared configuration"
            )
        if mode == Phase8Mode.MOCK:
            if provider_client_factory is not None:
                client = provider_client_factory()
            else:
                client = ScriptedProviderClient(
                    passing_phase8_replies(
                        contract,
                        composer_provider=routes.composer.provider,
                        composer_model=routes.composer.model,
                        reviewer_provider=routes.reviewer.provider,
                        reviewer_model=routes.reviewer.model,
                    )
                )
            execution_mode = ProviderExecutionMode.OFFLINE_SIMULATION
            selected_run_id = run_id or f"phase8-mock-{contract.contract_sha256[:20]}"
        else:
            if provider_client_factory is None:
                # Credential loading and SDK construction occur only after all
                # contract, fingerprint, route, schema, and policy checks pass.
                from dotenv import load_dotenv
                from provider_adapter import ProviderAdapter

                load_dotenv(root / ".env", override=False)
                client = ProviderAdapter()
            else:
                client = provider_client_factory()
            execution_mode = ProviderExecutionMode.LIVE
            selected_run_id = run_id or f"phase8-live-{contract.contract_sha256[:20]}"

        from provider_gateway import GovernedProviderGateway

        gateway = GovernedProviderGateway(
            ledger=ledger,
            client=client,
            execution_mode=execution_mode,
            approved_routes=routes.all,
            daily_limit_usd=daily_limit_usd,
            monthly_limit_usd=monthly_limit_usd,
            live_authorized=(mode == Phase8Mode.LIVE and approval == token),
        )
        executor = GovernedLiveExecutor(
            gateway=gateway,
            composer_route=routes.composer,
            reviewer_route=routes.reviewer,
        )
        kernel = OrchestrationKernel(
            ledger=ledger,
            guard=guard,
            planner=planner,
            executor=executor,
            policy=kernel_policy,
        )
        idempotency_key = (
            f"phase8:{execution_mode.value}:{contract.contract_sha256}:"
            f"run:{selected_run_id}:v1"
        )
        first_result = kernel.run(
            contract,
            run_id=selected_run_id,
            idempotency_key=idempotency_key,
        )
        first_calls = gateway.call_count
        before_replay = gateway.call_count
        replay_result = kernel.run(
            contract,
            run_id=selected_run_id,
            idempotency_key=idempotency_key,
        )
        replay_calls = gateway.call_count - before_replay

    with ledger.connect() as con:
        durable_calls_after = int(
            con.execute("SELECT COUNT(*) FROM provider_calls").fetchone()[0]
        )
    return Phase8Report(
        phase7=phase7,
        integrity=ledger.integrity_check(),
        migrations=ledger.schema_migration_ids(),
        newly_applied_migrations=phase7.phase6.newly_applied_migrations,
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
        durable_provider_calls=durable_calls_after - durable_calls_before,
    )


def print_report(report: Phase8Report) -> None:
    external_cost = (
        0.0
        if report.mode == Phase8Mode.MOCK
        else (report.first_result.cost_usd if report.first_result else 0.0)
    )
    label = {
        Phase8Mode.STATUS: "status",
        Phase8Mode.MOCK: "simulated canary",
        Phase8Mode.PREPARE_LIVE: "live preparation",
        Phase8Mode.LIVE: "live canary",
    }[report.mode]
    print(f"Phase 8 governed provider orchestration {label}")
    print(
        f"[{'PASS' if report.phase7.passed else 'FAIL'}] "
        "Phase 1-7 deterministic orchestration foundation"
    )
    print(f"[{'PASS' if report.integrity == 'ok' else 'FAIL'}] SQLite integrity: {report.integrity}")
    print(
        f"[{'PASS' if report.schema_ready else 'FAIL'}] provider-call schema: "
        f"{', '.join(report.migrations)}; newly_applied="
        f"{','.join(report.newly_applied_migrations) or 'none'}"
    )
    print(
        f"[{'PASS' if report.policy_ready else 'FAIL'}] contract="
        f"{report.contract.source_path}; id={report.contract.contract_id}; "
        f"budget=${report.contract.policy.budget_usd:.2f}; tasks={len(report.graph.tasks)}"
    )
    print(
        f"[PASS] routes: composer={report.routes.composer.provider}/"
        f"{report.routes.composer.model}; reviewer={report.routes.reviewer.provider}/"
        f"{report.routes.reviewer.model}"
    )
    if report.mode == Phase8Mode.STATUS:
        print("[INFO] status-only made no provider call and wrote no artifact")
    elif report.mode == Phase8Mode.PREPARE_LIVE:
        print("[PASS] prepared approval fingerprint: " + report.approval_token)
        print("[INFO] preparation made no provider call and wrote no artifact")
    elif report.first_result is not None and report.replay_result is not None:
        print(
            f"[{'PASS' if report.first_result.completed else 'FAIL'}] first execution: "
            f"status={report.first_result.status.value}; "
            f"outcome={report.first_result.outcome.value if report.first_result.outcome else 'none'}; "
            f"tasks={report.first_result.completed_tasks}/{report.first_result.task_count}; "
            f"provider_calls={report.first_provider_calls}; cost=${external_cost:.6f}"
        )
        if report.first_result.artifacts:
            artifact = report.first_result.artifacts[0]
            print(
                f"[PASS] artifact: {artifact.path}; bytes={artifact.content_bytes}; "
                f"sha256={artifact.content_sha256[:12]}"
            )
        print(
            f"[{'PASS' if report.replay_result.replayed and report.replay_provider_calls == 0 else 'FAIL'}] "
            f"completed replay: replayed={report.replay_result.replayed}; "
            f"new_provider_calls={report.replay_provider_calls}"
        )
    print("Phase 8 result:", "PASS" if report.passed else "FAIL")


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
    parser = argparse.ArgumentParser(
        description="Phase 8 governed provider orchestration"
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--status-only", action="store_true")
    modes.add_argument("--mock-canary", action="store_true")
    modes.add_argument("--prepare-live", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--contract")
    parser.add_argument("--approval")
    parser.add_argument("--run-id")
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--ledger", default="ledger.db")
    parser.add_argument("--composer-provider", choices=("openai", "anthropic"), default="openai")
    parser.add_argument("--composer-model")
    parser.add_argument("--reviewer-provider", choices=("openai", "anthropic"), default="anthropic")
    parser.add_argument("--reviewer-model")
    parser.add_argument("--composer-max-output-tokens", type=int, default=2000)
    parser.add_argument("--reviewer-max-output-tokens", type=int, default=1600)
    parser.add_argument("--daily-limit-usd", type=float, default=5.0)
    parser.add_argument("--monthly-limit-usd", type=float, default=150.0)
    parser.add_argument("--git-executable")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    mode = (
        Phase8Mode.MOCK
        if args.mock_canary
        else Phase8Mode.PREPARE_LIVE
        if args.prepare_live
        else Phase8Mode.LIVE
        if args.live
        else Phase8Mode.STATUS
    )
    contract_path = args.contract or (
        "project/phase8_mock_goal.md"
        if mode == Phase8Mode.MOCK
        else "project/phase8_live_canary_goal.md"
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
        routes = Phase8Routes(
            composer=ProviderRoute(
                provider=args.composer_provider,
                model=args.composer_model or composer_model,
                max_output_tokens=args.composer_max_output_tokens,
                input_per_mtok=composer_input,
                output_per_mtok=composer_output,
            ),
            reviewer=ProviderRoute(
                provider=args.reviewer_provider,
                model=args.reviewer_model or reviewer_model,
                max_output_tokens=args.reviewer_max_output_tokens,
                input_per_mtok=reviewer_input,
                output_per_mtok=reviewer_output,
            ),
        )
        report = run_phase8(
            project_root=root,
            ledger_path=ledger_path,
            contract_path=contract_path,
            routes=routes,
            mode=mode,
            approval=args.approval,
            run_id=args.run_id,
            daily_limit_usd=args.daily_limit_usd,
            monthly_limit_usd=args.monthly_limit_usd,
            git_executable=args.git_executable or shutil.which("git"),
        )
        print_report(report)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}".replace(str(root), "<workspace>")
        print(f"Phase 8 stopped safely: {message}", file=sys.stderr)
        return 1
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
