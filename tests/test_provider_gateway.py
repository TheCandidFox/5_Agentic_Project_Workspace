from __future__ import annotations

import json
from pathlib import Path

import pytest

from governed_live_profile import GovernedLivePlanner
from ledger import Ledger
from orchestration_kernel import OrchestrationKernel, OrchestrationStore
from project_contract import parse_project_contract
from provider_fixtures import FixtureReply, ScriptedProviderClient
from provider_gateway import (
    AmbiguousProviderCall,
    GovernedProviderGateway,
    ProviderCallFailed,
    ProviderAuthorizationError,
    ProviderExecutionMode,
    ProviderResponseError,
    ProviderRoute,
    strict_json_object,
)
from task_graph import validate_task_graph


MOCK_CONTRACT = (
    Path(__file__).resolve().parents[1] / "project" / "phase8_mock_goal.md"
).read_text(encoding="utf-8")


def route(provider="openai", model="fixture-model"):
    return ProviderRoute(
        provider=provider,
        model=model,
        max_output_tokens=1000,
        input_per_mtok=2.5,
        output_per_mtok=15,
    )


def claimed_task(tmp_path: Path):
    root = tmp_path / "candidate"
    root.mkdir()
    ledger = Ledger(root / "ledger.db", project_root=root)
    contract = parse_project_contract(MOCK_CONTRACT, source_path="project/mock.md")
    selected = route()
    planner = GovernedLivePlanner(
        composer_route=selected,
        reviewer_route=route("anthropic", "review-model"),
    )
    graph = validate_task_graph(
        tuple(planner.build(contract)),
        max_tasks=contract.policy.max_tasks,
        supported_kinds=planner.supported_kinds,
    )
    run_id = "gateway-test-run"
    key = "gateway-test-key"
    request_sha = OrchestrationKernel._request_sha(run_id, key, contract, graph)
    store = OrchestrationStore(ledger)
    store.claim_run(
        run_id=run_id,
        idempotency_key=key,
        contract=contract,
        graph=graph,
        request_sha256=request_sha,
    )
    task = graph.tasks[0]
    store.claim_dispatch(
        run_id=run_id,
        task=task,
        contract_sha256=contract.contract_sha256,
    )
    return ledger, contract, task, selected


def fixture_client(text: str):
    return ScriptedProviderClient(
        (
            FixtureReply(
                provider="openai",
                model="fixture-model",
                text=text,
                input_tokens=100,
                output_tokens=80,
            ),
        )
    )


def call_gateway(ledger, contract, task, selected, client, parser=lambda value: value):
    gateway = GovernedProviderGateway(
        ledger=ledger,
        client=client,
        execution_mode=ProviderExecutionMode.OFFLINE_SIMULATION,
        approved_routes=(selected,),
        daily_limit_usd=5,
        monthly_limit_usd=150,
    )
    result = gateway.call_json(
        run_id="gateway-test-run",
        task_key=task.task_key,
        attempt_number=1,
        route=selected,
        prompt="bounded prompt",
        prompt_template_version="phase8-test-v1",
        response_schema="phase8-test-v1",
        max_call_cost_usd=task.estimated_cost_usd,
        project_budget_usd=contract.policy.budget_usd,
        parser=parser,
    )
    return gateway, result


def test_strict_json_rejects_wrappers_fences_and_non_objects():
    assert strict_json_object(' {"ok":true}\n') == {"ok": True}
    with pytest.raises(ProviderResponseError, match="only one JSON object"):
        strict_json_object('result: {"ok":true}')
    with pytest.raises(ProviderResponseError, match="only one JSON object"):
        strict_json_object('```json\n{"ok":true}\n```')
    with pytest.raises(ProviderResponseError, match="root"):
        strict_json_object("[]")


def test_fixture_call_records_hashes_schema_usage_and_no_raw_prompt(tmp_path):
    ledger, contract, task, selected = claimed_task(tmp_path)
    client = fixture_client(json.dumps({"ok": True}))
    gateway, result = call_gateway(ledger, contract, task, selected, client)

    assert gateway.call_count == client.call_count == 1
    assert result.payload == {"ok": True}
    assert result.actual_cost_usd == 0
    with ledger.connect() as con:
        row = dict(con.execute("SELECT * FROM provider_calls").fetchone())
        reservation = dict(
            con.execute("SELECT * FROM budget_reservations").fetchone()
        )
        telemetry = dict(con.execute("SELECT * FROM telemetry").fetchone())
    assert row["status"] == "completed"
    assert row["execution_mode"] == "offline-simulation"
    assert row["prompt_sha256"] and "bounded prompt" not in json.dumps(row)
    assert json.loads(row["response_json"]) == {"ok": True}
    assert row["input_tokens"] == 100 and row["output_tokens"] == 80
    assert reservation["status"] == "settled" and reservation["actual_usd"] == 0
    assert telemetry["estimated_cost_usd"] == 0


def test_schema_failure_is_durable_and_never_silently_recalled(tmp_path):
    ledger, contract, task, selected = claimed_task(tmp_path)
    client = fixture_client('{"unexpected":true}')
    gateway = GovernedProviderGateway(
        ledger=ledger,
        client=client,
        execution_mode=ProviderExecutionMode.OFFLINE_SIMULATION,
        approved_routes=(selected,),
        daily_limit_usd=5,
        monthly_limit_usd=150,
    )
    kwargs = dict(
        run_id="gateway-test-run",
        task_key=task.task_key,
        attempt_number=1,
        route=selected,
        prompt="bounded prompt",
        prompt_template_version="phase8-test-v1",
        response_schema="phase8-test-v1",
        max_call_cost_usd=task.estimated_cost_usd,
        project_budget_usd=contract.policy.budget_usd,
        parser=lambda value: (
            value
            if set(value) == {"ok"}
            else (_ for _ in ()).throw(ValueError("schema mismatch"))
        ),
    )
    with pytest.raises(ProviderCallFailed, match="schema mismatch") as captured:
        gateway.call_json(**kwargs)
    assert captured.value.failure_kind == "response-schema"
    assert captured.value.retryable is False
    with pytest.raises(AmbiguousProviderCall, match="will not be repeated"):
        gateway.call_json(**kwargs)
    assert client.call_count == 1
    with ledger.connect() as con:
        row = con.execute(
            "SELECT status,error,failure_kind,response_excerpt FROM provider_calls"
        ).fetchone()
    assert row["status"] == "failed"
    assert "schema mismatch" in row["error"]
    assert row["failure_kind"] == "response-schema"
    assert row["response_excerpt"] == '{"unexpected":true}'


def test_max_token_response_is_retryable_and_excerpt_is_redacted(tmp_path):
    ledger, contract, task, selected = claimed_task(tmp_path)
    client = ScriptedProviderClient(
        (
            FixtureReply(
                provider=selected.provider,
                model=selected.model,
                text=(
                    '{"note":"api_key=sk-abcdefghijklmnopqrst",'
                    '"criteria":['
                ),
                input_tokens=250,
                output_tokens=selected.max_output_tokens,
                stop_reason="max_tokens",
            ),
        )
    )
    gateway = GovernedProviderGateway(
        ledger=ledger,
        client=client,
        execution_mode=ProviderExecutionMode.OFFLINE_SIMULATION,
        approved_routes=(selected,),
        daily_limit_usd=5,
        monthly_limit_usd=150,
    )

    with pytest.raises(ProviderCallFailed) as captured:
        gateway.call_json(
            run_id="gateway-test-run",
            task_key=task.task_key,
            attempt_number=1,
            route=selected,
            prompt="bounded prompt",
            prompt_template_version="phase9-test-v1",
            response_schema="phase9-test-v1",
            max_call_cost_usd=task.estimated_cost_usd,
            project_budget_usd=contract.policy.budget_usd,
            parser=lambda value: value,
        )

    assert captured.value.failure_kind == "response-truncated"
    assert captured.value.retryable is True
    with ledger.connect() as con:
        row = con.execute(
            """
            SELECT status,failure_kind,response_excerpt,response_excerpt_sha256,
                   output_tokens,stop_reason
            FROM provider_calls
            """
        ).fetchone()
    assert row["status"] == "failed"
    assert row["failure_kind"] == "response-truncated"
    assert row["output_tokens"] == selected.max_output_tokens
    assert row["stop_reason"] == "max_tokens"
    assert "sk-abcdefghijklmnopqrst" not in row["response_excerpt"]
    assert "[REDACTED]" in row["response_excerpt"]
    assert row["response_excerpt_sha256"]


def test_route_drift_and_budget_denial_happen_before_fixture_dispatch(tmp_path):
    ledger, contract, task, selected = claimed_task(tmp_path)
    client = fixture_client('{"ok":true}')
    gateway = GovernedProviderGateway(
        ledger=ledger,
        client=client,
        execution_mode=ProviderExecutionMode.OFFLINE_SIMULATION,
        approved_routes=(selected,),
        daily_limit_usd=0.000001,
        monthly_limit_usd=150,
    )
    with pytest.raises(ProviderAuthorizationError, match="allowlist"):
        gateway.call_json(
            run_id="gateway-test-run",
            task_key=task.task_key,
            attempt_number=1,
            route=route("openai", "drifted-model"),
            prompt="bounded prompt",
            prompt_template_version="phase8-test-v1",
            response_schema="phase8-test-v1",
            max_call_cost_usd=task.estimated_cost_usd,
            project_budget_usd=contract.policy.budget_usd,
            parser=lambda value: value,
        )
    from budget_guard import BudgetDenied

    with pytest.raises(BudgetDenied):
        gateway.call_json(
            run_id="gateway-test-run",
            task_key=task.task_key,
            attempt_number=1,
            route=selected,
            prompt="bounded prompt",
            prompt_template_version="phase8-test-v1",
            response_schema="phase8-test-v1",
            max_call_cost_usd=task.estimated_cost_usd,
            project_budget_usd=contract.policy.budget_usd,
            parser=lambda value: value,
        )
    assert client.call_count == 0
    with ledger.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM provider_calls").fetchone()[0] == 0


class NonFixtureClient:
    offline_fixture = False

    def call(self, **_kwargs):
        raise AssertionError("client should not be called")


def test_live_gateway_requires_explicit_authorization(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db", project_root=tmp_path)
    with pytest.raises(ProviderAuthorizationError, match="exact approval"):
        GovernedProviderGateway(
            ledger=ledger,
            client=NonFixtureClient(),
            execution_mode=ProviderExecutionMode.LIVE,
            approved_routes=(route(),),
            daily_limit_usd=5,
            monthly_limit_usd=150,
            live_authorized=False,
        )
