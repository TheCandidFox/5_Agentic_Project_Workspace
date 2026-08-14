from __future__ import annotations

import json
from pathlib import Path

from governed_live_profile import GovernedLiveExecutor, GovernedLivePlanner
from ledger import Ledger
from orchestration_kernel import KernelPolicy, OrchestrationKernel, ProjectRunStatus
from project_contract import AuthorityLevel, parse_project_contract
from provider_fixtures import FixtureReply, ScriptedProviderClient, passing_phase8_replies
from provider_gateway import GovernedProviderGateway, ProviderExecutionMode, ProviderRoute
from workspace_guard import WorkspaceGuard


MOCK_CONTRACT = (
    Path(__file__).resolve().parents[1] / "project" / "phase8_mock_goal.md"
).read_text(encoding="utf-8")


def routes():
    return (
        ProviderRoute("openai", "compose-model", 1500, 2.5, 15),
        ProviderRoute("anthropic", "review-model", 1200, 2, 10),
    )


def run_with_replies(tmp_path: Path, replies):
    root = tmp_path / "candidate"
    root.mkdir()
    contract = parse_project_contract(MOCK_CONTRACT, source_path="project/mock.md")
    ledger = Ledger(root / "ledger.db", project_root=root)
    composer, reviewer = routes()
    client = ScriptedProviderClient(replies)
    gateway = GovernedProviderGateway(
        ledger=ledger,
        client=client,
        execution_mode=ProviderExecutionMode.OFFLINE_SIMULATION,
        approved_routes=(composer, reviewer),
        daily_limit_usd=5,
        monthly_limit_usd=150,
    )
    planner = GovernedLivePlanner(
        composer_route=composer,
        reviewer_route=reviewer,
    )
    executor = GovernedLiveExecutor(
        gateway=gateway,
        composer_route=composer,
        reviewer_route=reviewer,
    )
    kernel = OrchestrationKernel(
        ledger=ledger,
        guard=WorkspaceGuard(root),
        planner=planner,
        executor=executor,
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
    result = kernel.run(
        contract,
        run_id="phase8-profile-test",
        idempotency_key="phase8-profile-test-key",
    )
    return root, ledger, contract, client, gateway, kernel, result


def test_passing_simulation_records_artifact_acceptance_and_replay(tmp_path):
    contract = parse_project_contract(MOCK_CONTRACT, source_path="project/mock.md")
    composer, reviewer = routes()
    replies = passing_phase8_replies(
        contract,
        composer_provider=composer.provider,
        composer_model=composer.model,
        reviewer_provider=reviewer.provider,
        reviewer_model=reviewer.model,
    )
    root, ledger, contract, client, gateway, kernel, result = run_with_replies(
        tmp_path, replies
    )
    artifact = root / contract.deliverables[0].path
    mtime = artifact.stat().st_mtime_ns
    replay = kernel.run(
        contract,
        run_id="phase8-profile-test",
        idempotency_key="phase8-profile-test-key",
    )

    assert result.completed is True and result.outcome.value == "PASS"
    assert result.completed_tasks == 2 and result.cost_usd == 0
    assert client.call_count == gateway.call_count == 2
    assert replay.completed and replay.replayed
    assert gateway.call_count == 2
    assert artifact.stat().st_mtime_ns == mtime
    with ledger.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM provider_calls").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM acceptance_runs").fetchone()[0] == 1


def test_semantic_failure_becomes_repair_without_artifact_mutation(tmp_path):
    contract = parse_project_contract(MOCK_CONTRACT, source_path="project/mock.md")
    composer, reviewer = routes()
    compose, review = passing_phase8_replies(
        contract,
        composer_provider=composer.provider,
        composer_model=composer.model,
        reviewer_provider=reviewer.provider,
        reviewer_model=reviewer.model,
    )
    payload = json.loads(review.text)
    payload["criteria"][2]["verdict"] = "FAIL"
    payload["criteria"][2]["rationale"] = "The sequence is not sufficiently actionable."
    failed_review = FixtureReply(
        provider=review.provider,
        model=review.model,
        text=json.dumps(payload, separators=(",", ":")),
        input_tokens=review.input_tokens,
        output_tokens=review.output_tokens,
    )
    root, _ledger, contract, client, _gateway, _kernel, result = run_with_replies(
        tmp_path, (compose, failed_review)
    )

    assert result.status == ProjectRunStatus.FAILED
    assert result.outcome.value == "REPAIR"
    assert result.stop_reason == "acceptance-repair"
    assert client.call_count == 2
    assert (root / contract.deliverables[0].path).is_file()


def test_malformed_composer_response_requires_recovery_and_writes_nothing(tmp_path):
    composer, _reviewer = routes()
    malformed = FixtureReply(
        provider=composer.provider,
        model=composer.model,
        text='{"artifact_markdown":"# Incomplete"}',
        input_tokens=100,
        output_tokens=20,
    )
    root, ledger, contract, client, _gateway, _kernel, result = run_with_replies(
        tmp_path, (malformed,)
    )

    assert result.status == ProjectRunStatus.RECOVERY_REQUIRED
    assert result.stop_reason == "ambiguous-dispatch"
    assert client.call_count == 1
    assert not (root / contract.deliverables[0].path).exists()
    with ledger.connect() as con:
        call = con.execute("SELECT status FROM provider_calls").fetchone()
    assert call["status"] == "failed"
