from __future__ import annotations

import argparse
import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from budget_guard import BudgetGuard
from classification import assert_v0_2_allowed, classify
from config import SETTINGS
from ledger import Ledger
from project_paths import portable_project_path
from router import route_for_provider
from task_contract import TaskContract
from telemetry import estimate_cost, record_call


def rough_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def reservation_estimate(provider: str, prompt: str, max_output_tokens: int) -> float:
    input_tokens = rough_tokens(prompt)
    if provider == "openai":
        return (
            input_tokens / 1_000_000 * SETTINGS.openai_input_per_mtok
            + max_output_tokens / 1_000_000 * SETTINGS.openai_output_per_mtok
        )
    return (
        input_tokens / 1_000_000 * SETTINGS.anthropic_input_per_mtok
        + max_output_tokens / 1_000_000 * SETTINGS.anthropic_output_per_mtok
    )


def actual_cost(provider: str, usage) -> float:
    return estimate_cost(
        provider,
        usage,
        openai_input_per_mtok=SETTINGS.openai_input_per_mtok,
        openai_output_per_mtok=SETTINGS.openai_output_per_mtok,
        anthropic_input_per_mtok=SETTINGS.anthropic_input_per_mtok,
        anthropic_output_per_mtok=SETTINGS.anthropic_output_per_mtok,
    )


def _read_completed_artifact(ledger: Ledger, idempotency_key: str, stage: str) -> str | None:
    stored_path = ledger.completed_artifact(idempotency_key)
    if not stored_path:
        return None

    try:
        artifact_path = ledger.resolve_artifact_path(stored_path)
    except ValueError:
        ledger.mark_artifact_missing(idempotency_key, stored_path)
        return None

    if artifact_path.is_file():
        print(f"  resume: {stage} already complete")
        return artifact_path.read_text(encoding="utf-8")

    ledger.mark_artifact_missing(idempotency_key, stored_path)
    return None


def execute_step(
    *,
    ledger: Ledger,
    adapter,
    guard: BudgetGuard,
    contract: TaskContract,
    stage: str,
    provider: str,
    model: str,
    prompt: str,
    output_name: str,
    max_output_tokens: int,
) -> str:
    SETTINGS.outputs_dir.mkdir(parents=True, exist_ok=True)
    idempotency_key = f"{contract.task_id}:{stage}:v1"
    existing_text = _read_completed_artifact(ledger, idempotency_key, stage)
    if existing_text is not None:
        return existing_text

    step_id = str(uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key))
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    reserve_usd = reservation_estimate(provider, prompt, max_output_tokens)

    reservation_id = guard.reserve(
        task_id=contract.task_id,
        step_id=step_id,
        amount_usd=reserve_usd,
        task_limit_usd=contract.budget_ceiling_usd,
    )

    should_dispatch = ledger.start_step(
        step_id=step_id,
        task_id=contract.task_id,
        stage=stage,
        provider=provider,
        model=model,
        idempotency_key=idempotency_key,
        prompt_hash=prompt_hash,
    )
    if not should_dispatch:
        guard.settle(reservation_id, 0.0)
        existing_text = _read_completed_artifact(ledger, idempotency_key, stage)
        if existing_text is not None:
            return existing_text
        raise FileNotFoundError(
            f"completed step {idempotency_key!r} has no readable artifact"
        )

    try:
        result = adapter.call(
            provider=provider,
            model=model,
            prompt=prompt,
            max_output_tokens=max_output_tokens,
        )
        cost = actual_cost(provider, result.usage)
        record_call(
            ledger,
            task_id=contract.task_id,
            step_id=step_id,
            provider=provider,
            model=model,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            estimated_cost_usd=cost,
            latency_ms=result.latency_ms,
            stop_reason=result.stop_reason,
            error=None,
        )
        guard.settle(reservation_id, cost)

        output_path = SETTINGS.outputs_dir / output_name
        output_path.write_text(result.text.strip() + "\n", encoding="utf-8")
        ledger.complete_step(idempotency_key, str(output_path))
        return result.text
    except Exception as exc:
        guard.settle(reservation_id, 0.0)
        ledger.fail_step(idempotency_key, repr(exc))
        ledger.event("provider_error", {"stage": stage, "error": repr(exc)}, contract.task_id)
        raise


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: str
    detail: str


def offline_preflight() -> tuple[bool, list[PreflightCheck]]:
    """Validate the local runtime without constructing clients or calling providers."""

    checks: list[PreflightCheck] = []

    if SETTINGS.project_goal_path.is_file():
        goal = SETTINGS.project_goal_path.read_text(encoding="utf-8").strip()
        checks.append(
            PreflightCheck(
                "project goal",
                "PASS" if goal else "FAIL",
                str(SETTINGS.project_goal_path),
            )
        )
    else:
        checks.append(
            PreflightCheck("project goal", "FAIL", f"missing: {SETTINGS.project_goal_path}")
        )

    try:
        ledger = Ledger(SETTINGS.ledger_path, project_root=SETTINGS.project_root)
        integrity = ledger.integrity_check()
        checks.append(
            PreflightCheck(
                "SQLite ledger",
                "PASS" if integrity == "ok" else "FAIL",
                f"integrity={integrity}; migrated_paths={ledger.migrated_artifact_paths}",
            )
        )

        missing: list[str] = []
        invalid: list[str] = []
        for row in ledger.completed_artifacts():
            stored_path = row["artifact_path"]
            try:
                resolved = ledger.resolve_artifact_path(stored_path)
            except ValueError:
                invalid.append(stored_path)
                continue
            if not resolved.is_file():
                missing.append(stored_path)
        detail = (
            f"{len(missing)} missing, {len(invalid)} invalid "
            f"of {len(ledger.completed_artifacts())} completed artifacts"
        )
        checks.append(
            PreflightCheck(
                "completed artifacts",
                "WARN" if missing or invalid else "PASS",
                detail,
            )
        )
    except Exception as exc:
        checks.append(PreflightCheck("SQLite ledger", "FAIL", repr(exc)))

    missing_keys = [
        name
        for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")
        if not os.getenv(name)
    ]
    checks.append(
        PreflightCheck(
            "API key presence",
            "FAIL" if missing_keys else "PASS",
            "missing: " + ", ".join(missing_keys) if missing_keys else "both configured",
        )
    )

    try:
        portable_output = portable_project_path(
            SETTINGS.outputs_dir,
            SETTINGS.project_root,
        )
        checks.append(
            PreflightCheck(
                "output directory",
                "PASS",
                portable_output,
            )
        )
    except ValueError as exc:
        checks.append(PreflightCheck("output directory", "FAIL", str(exc)))
    return not any(check.status == "FAIL" for check in checks), checks


def print_preflight() -> bool:
    ok, checks = offline_preflight()
    print("Offline preflight (no provider calls)")
    for check in checks:
        print(f"[{check.status}] {check.name}: {check.detail}")
    print("Preflight result:", "PASS" if ok else "FAIL")
    return ok


def run_workflow() -> None:
    from provider_adapter import ProviderAdapter

    goal = SETTINGS.project_goal_path.read_text(encoding="utf-8")
    ledger = Ledger(SETTINGS.ledger_path, project_root=SETTINGS.project_root)
    adapter = ProviderAdapter()
    guard = BudgetGuard(
        ledger,
        daily_limit_usd=SETTINGS.daily_budget_usd,
        monthly_limit_usd=SETTINGS.monthly_budget_usd,
    )

    data_class = classify()
    assert_v0_2_allowed(data_class)

    # Stable task identity is what makes restart/resume work. Re-running the same
    # goal reuses completed step idempotency keys instead of silently creating a new task.
    # Set TASK_ID explicitly when you intentionally want a new run for the same goal.
    task_id = os.getenv("TASK_ID") or (
        "goal-" + hashlib.sha256(goal.strip().encode("utf-8")).hexdigest()[:20]
    )

    contract = TaskContract(
        task_id=task_id,
        objective=goal.strip(),
        acceptance_criteria=[
            "produce a concise execution brief",
            "produce an executor draft",
            "audit material defects",
            "produce a revised final deliverable",
        ],
        scope_boundaries=["Do not change the primary goal."],
        importance_band=1,
        effect_class_ceiling="informational",
        data_classification=data_class,
        budget_ceiling_usd=SETTINGS.default_task_budget_usd,
        approval_state="approved",
        evidence_required=False,
    )
    ledger.upsert_task(contract)
    ledger.set_task_state(contract.task_id, "in_progress", "brief")

    openai_route = route_for_provider(
        provider="openai",
        importance_band=contract.importance_band,
        workload="general",
        economy_model=SETTINGS.openai_economy_model,
        mid_model=SETTINGS.openai_mid_model,
    )
    anthropic_route = route_for_provider(
        provider="anthropic",
        importance_band=contract.importance_band,
        workload="general",
        economy_model=SETTINGS.anthropic_economy_model,
        mid_model=SETTINGS.anthropic_mid_model,
    )

    try:
        print(f"Task: {contract.task_id}")
        print("1/4 OpenAI architect...")
        brief = execute_step(
            ledger=ledger, adapter=adapter, guard=guard, contract=contract,
            stage="gpt_brief", provider="openai", model=openai_route.model,
            max_output_tokens=SETTINGS.openai_max_output_tokens,
            output_name="01_gpt_brief.md",
            prompt=f"""You are the ARCHITECT in a two-model workflow.

Turn the following goal into a precise execution brief for another AI.
Include objective, required deliverable, acceptance criteria, likely edge cases,
and explicit executor instructions. Keep it concise and do not solve the task.

GOAL:
{goal}
""",
        )

        ledger.set_task_state(contract.task_id, "in_progress", "draft")
        print("2/4 Anthropic executor...")
        draft = execute_step(
            ledger=ledger, adapter=adapter, guard=guard, contract=contract,
            stage="claude_draft", provider="anthropic", model=anthropic_route.model,
            max_output_tokens=SETTINGS.anthropic_max_output_tokens,
            output_name="02_claude_draft.md",
            prompt=f"""You are the EXECUTOR.

Complete the work described in this project brief.
Return the finished deliverable, followed by 'Assumptions and Uncertainties'.

PROJECT BRIEF:
{brief}
""",
        )

        ledger.set_task_state(contract.task_id, "in_progress", "audit")
        print("3/4 OpenAI auditor...")
        audit = execute_step(
            ledger=ledger, adapter=adapter, guard=guard, contract=contract,
            stage="gpt_audit", provider="openai", model=openai_route.model,
            max_output_tokens=SETTINGS.openai_max_output_tokens,
            output_name="03_gpt_audit.md",
            prompt=f"""You are an INDEPENDENT AUDITOR.

Compare the project brief against the deliverable.
Identify only material omissions, unsupported assumptions, contradictions,
or acceptance-criteria failures.

Return PASS ITEMS, REQUIRED CORRECTIONS, and OPTIONAL IMPROVEMENTS.

PROJECT BRIEF:
{brief}

DELIVERABLE:
{draft}
""",
        )

        ledger.set_task_state(contract.task_id, "in_progress", "revision")
        print("4/4 Anthropic revision...")
        final = execute_step(
            ledger=ledger, adapter=adapter, guard=guard, contract=contract,
            stage="claude_final", provider="anthropic", model=anthropic_route.model,
            max_output_tokens=SETTINGS.anthropic_max_output_tokens,
            output_name="04_claude_final.md",
            prompt=f"""You are the EXECUTOR performing the revision pass.

Revise the prior deliverable using the auditor's feedback.
Apply valid REQUIRED CORRECTIONS. Use OPTIONAL IMPROVEMENTS only when material.
Do not accept criticism that conflicts with the project brief.

PROJECT BRIEF:
{brief}

PRIOR DELIVERABLE:
{draft}

AUDIT:
{audit}

Return only the revised final deliverable plus a short Revision Notes section.
""",
        )

        ledger.set_task_state(contract.task_id, "completed", "finished")
        ledger.event("task_completed", {"final_output": "04_claude_final.md"}, contract.task_id)
        print("\nLocal v0.2 loop complete.")
        print(f"Final: {SETTINGS.outputs_dir / '04_claude_final.md'}")
        print(f"Ledger: {SETTINGS.ledger_path}")
    except Exception as exc:
        ledger.set_task_state(contract.task_id, "failed", "interrupted")
        ledger.event("task_failed", {"error": repr(exc)}, contract.task_id)
        print(f"\nStopped safely: {exc}")
        print("Durable state remains in ledger.db.")
        raise


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the durable local v0.2 AI loop.")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="run offline configuration and persistence checks; make no provider calls",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.preflight_only:
        return 0 if print_preflight() else 1
    run_workflow()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
