from __future__ import annotations

import os
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from bootstrap_acceptance import FINAL_BOOTSTRAP_GATES
from ledger import Ledger
from orchestration_kernel import KernelPolicy, OrchestrationKernel, ProjectRunStatus
from project_contract import AuthorityLevel, load_project_contract
from provider_fixtures import ScriptedProviderClient, recovering_phase9_replies
from provider_gateway import GovernedProviderGateway, ProviderExecutionMode, ProviderRoute
from recovery_live_profile import RecoveryLiveExecutor, RecoveryLivePlanner
from run_phase9 import Phase9Mode, Phase9Routes, run_phase9
from workspace_guard import WorkspaceGuard


GIT = os.environ.get("AI_LOOP_GIT_EXECUTABLE") or shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="Git is not installed")


def make_candidate(tmp_path: Path) -> Path:
    root = tmp_path / "candidate"
    root.mkdir()
    (root / ".gitignore").write_text(
        "ledger.db\nledger.db-shm\nledger.db-wal\noutputs/\nlogs/\n.pytest_tmp/\n",
        encoding="utf-8",
    )
    subprocess.run(
        [GIT, "init", "--initial-branch", "main"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    project = root / "project"
    project.mkdir()
    source_project = Path(__file__).resolve().parents[1] / "project"
    for name in (
        "phase7_sample_goal.md",
        "phase8_mock_goal.md",
        "phase8_live_canary_goal.md",
        "phase9_recovery_canary_goal.md",
    ):
        (project / name).write_text(
            (source_project / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    functions_by_path: dict[str, set[str]] = {}
    for gate in FINAL_BOOTSTRAP_GATES:
        for node in gate.evidence_nodes:
            path, function_name = node.split("::", 1)
            functions_by_path.setdefault(path, set()).add(function_name)
    for path, function_names in functions_by_path.items():
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            "\n\n".join(
                f"def {function_name}():\n    assert True"
                for function_name in sorted(function_names)
            )
            + "\n",
            encoding="utf-8",
        )
    return root


def routes() -> Phase9Routes:
    return Phase9Routes(
        composer=ProviderRoute("openai", "fixture-openai", 4_000, 2.5, 15),
        reviewer=ProviderRoute("anthropic", "fixture-anthropic", 5_000, 2, 10),
    )


def test_offline_recovery_retries_only_reviewer_and_replays(tmp_path):
    root = make_candidate(tmp_path)
    selected = routes()
    first = run_phase9(
        project_root=root,
        ledger_path=root / "ledger.db",
        contract_path="project/phase9_recovery_canary_goal.md",
        routes=selected,
        mode=Phase9Mode.RECOVERY_CANARY,
        git_executable=GIT,
    )
    artifact = root / "outputs" / "phase9_recovery_canary_runbook.md"
    mtime = artifact.stat().st_mtime_ns
    second = run_phase9(
        project_root=root,
        ledger_path=root / "ledger.db",
        contract_path="project/phase9_recovery_canary_goal.md",
        routes=selected,
        mode=Phase9Mode.RECOVERY_CANARY,
        git_executable=GIT,
    )

    assert first.passed and second.passed
    assert first.first_provider_calls == 3
    assert first.composer_calls == 1 and first.reviewer_calls == 2
    assert first.known_truncations == 1
    assert second.first_provider_calls == 0
    assert artifact.stat().st_mtime_ns == mtime
    assert first.diagnostic_path and (root / first.diagnostic_path).is_file()
    diagnostic = json.loads((root / first.diagnostic_path).read_text(encoding="utf-8"))
    assert len(diagnostic["segments"]) == 5
    assert all(segment["status"] == "complete" for segment in diagnostic["segments"])
    assert "preserve the accepted artifact" in diagnostic["recommended_actions"][0]
    assert all("response_json" not in call for call in diagnostic["provider_calls"])
    assert all("prompt" not in call for call in diagnostic["provider_calls"])
    with Ledger(root / "ledger.db", project_root=root).connect() as connection:
        calls = connection.execute(
            """
            SELECT task_key,attempt_number,status,failure_kind,response_excerpt
            FROM provider_calls
            WHERE run_id=? ORDER BY started_at
            """,
            (first.first_result.run_id,),
        ).fetchall()
        dispatches = connection.execute(
            """
            SELECT task_key,attempt_number,status,error FROM task_dispatches
            WHERE run_id=? ORDER BY started_at
            """,
            (first.first_result.run_id,),
        ).fetchall()
    assert [row["status"] for row in calls] == ["completed", "failed", "completed"]
    assert calls[1]["failure_kind"] == "response-truncated"
    assert calls[1]["response_excerpt"]
    assert [row["status"] for row in dispatches] == ["succeeded", "failed", "succeeded"]
    assert "response-truncated" in dispatches[1]["error"]
    assert all(row["status"] != "dispatching" for row in dispatches)


def test_live_accounting_includes_failed_billable_reviewer_attempt(tmp_path):
    root = make_candidate(tmp_path)
    selected = routes()
    prepared = run_phase9(
        project_root=root,
        ledger_path=root / "ledger.db",
        contract_path="project/phase9_recovery_canary_goal.md",
        routes=selected,
        mode=Phase9Mode.PREPARE_LIVE,
        git_executable=GIT,
    )
    client = ScriptedProviderClient(
        recovering_phase9_replies(
            prepared.contract,
            composer_provider=selected.composer.provider,
            composer_model=selected.composer.model,
            reviewer_provider=selected.reviewer.provider,
            reviewer_model=selected.reviewer.model,
            reviewer_max_output_tokens=selected.reviewer.max_output_tokens,
        )
    )
    client.offline_fixture = False
    report = run_phase9(
        project_root=root,
        ledger_path=root / "ledger.db",
        contract_path="project/phase9_recovery_canary_goal.md",
        routes=selected,
        mode=Phase9Mode.LIVE,
        approval=prepared.approval_token,
        git_executable=GIT,
        provider_client_factory=lambda: client,
    )

    assert report.passed and report.first_result is not None
    assert 0 < report.provider_cost_usd < report.contract.policy.budget_usd
    assert report.first_result.cost_usd == pytest.approx(report.provider_cost_usd)
    with Ledger(root / "ledger.db", project_root=root).connect() as connection:
        failed_cost = connection.execute(
            """
            SELECT estimated_cost_usd FROM provider_calls
            WHERE run_id=? AND failure_kind='response-truncated'
            """,
            (report.first_result.run_id,),
        ).fetchone()[0]
        telemetry_cost = connection.execute(
            "SELECT COALESCE(SUM(estimated_cost_usd),0) FROM telemetry WHERE task_id=?",
            (report.first_result.run_id,),
        ).fetchone()[0]
    assert float(failed_cost) > 0
    assert float(telemetry_cost) == pytest.approx(report.provider_cost_usd)


def test_controlled_pause_resumes_in_new_kernel_without_composer_redispatch(tmp_path):
    root = make_candidate(tmp_path)
    selected = routes()
    guard = WorkspaceGuard(root)
    contract = load_project_contract(guard, "project/phase9_recovery_canary_goal.md")
    ledger = Ledger(root / "ledger.db", project_root=root)
    planner = RecoveryLivePlanner(
        composer_route=selected.composer,
        reviewer_route=selected.reviewer,
    )
    replies = recovering_phase9_replies(
        contract,
        composer_provider=selected.composer.provider,
        composer_model=selected.composer.model,
        reviewer_provider=selected.reviewer.provider,
        reviewer_model=selected.reviewer.model,
        reviewer_max_output_tokens=selected.reviewer.max_output_tokens,
    )
    first_client = ScriptedProviderClient(replies[:2])
    first_gateway = GovernedProviderGateway(
        ledger=ledger,
        client=first_client,
        execution_mode=ProviderExecutionMode.OFFLINE_SIMULATION,
        approved_routes=selected.all,
        daily_limit_usd=5,
        monthly_limit_usd=150,
    )
    first_kernel = OrchestrationKernel(
        ledger=ledger,
        guard=guard,
        planner=planner,
        executor=RecoveryLiveExecutor(
            gateway=first_gateway,
            composer_route=selected.composer,
            reviewer_route=selected.reviewer,
        ),
        policy=KernelPolicy(
            allowed_authorities=frozenset(
                {
                    AuthorityLevel.READ_ONLY,
                    AuthorityLevel.WORKSPACE_WRITE,
                    AuthorityLevel.LIVE_NETWORK,
                }
            ),
            allow_positive_cost=True,
            pause_after_retryable_failure=True,
        ),
    )
    run_id = "phase9-controlled-resume"
    key = "phase9-controlled-resume-key"
    paused = first_kernel.run(contract, run_id=run_id, idempotency_key=key)
    artifact = root / contract.deliverables[0].path
    artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()

    assert paused.status == ProjectRunStatus.PAUSED
    assert paused.stop_reason == "retryable-failure-paused"
    assert paused.completed_tasks == 1 and first_client.call_count == 2

    second_client = ScriptedProviderClient((replies[2],))
    second_gateway = GovernedProviderGateway(
        ledger=ledger,
        client=second_client,
        execution_mode=ProviderExecutionMode.OFFLINE_SIMULATION,
        approved_routes=selected.all,
        daily_limit_usd=5,
        monthly_limit_usd=150,
    )
    second_kernel = OrchestrationKernel(
        ledger=ledger,
        guard=guard,
        planner=planner,
        executor=RecoveryLiveExecutor(
            gateway=second_gateway,
            composer_route=selected.composer,
            reviewer_route=selected.reviewer,
        ),
        policy=KernelPolicy(
            allowed_authorities=frozenset(
                {
                    AuthorityLevel.READ_ONLY,
                    AuthorityLevel.WORKSPACE_WRITE,
                    AuthorityLevel.LIVE_NETWORK,
                }
            ),
            allow_positive_cost=True,
        ),
    )
    resumed = second_kernel.run(
        contract,
        run_id=run_id,
        idempotency_key=key,
        resume_paused=True,
    )
    replay = second_kernel.run(contract, run_id=run_id, idempotency_key=key)

    assert resumed.completed and second_client.call_count == 1
    assert replay.completed and replay.replayed and second_client.call_count == 1
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == artifact_hash
    with ledger.connect() as connection:
        calls = connection.execute(
            "SELECT task_key,attempt_number FROM provider_calls WHERE run_id=?",
            (run_id,),
        ).fetchall()
        resumed_events = connection.execute(
            "SELECT COUNT(*) FROM events WHERE task_id=? AND event_type='project_run_resumed'",
            (run_id,),
        ).fetchone()[0]
    assert [(row["task_key"], row["attempt_number"]) for row in calls] == [
        ("compose-markdown", 1),
        ("review-markdown", 1),
        ("review-markdown", 2),
    ]
    assert resumed_events == 1
