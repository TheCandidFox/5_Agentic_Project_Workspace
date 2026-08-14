from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from budget_guard import BudgetDenied, BudgetGuard
from classification import assert_v0_2_allowed, classify
from ledger import Ledger
from project_paths import portable_project_path
from retrieval_local import find_symbol
from router import should_escalate
from run_loop_v0_2 import parse_args
from task_contract import TaskContract


def make_contract(**kwargs):
    base = dict(
        objective="Test objective",
        acceptance_criteria=["must pass"],
        data_classification="internal-non-sensitive",
        budget_ceiling_usd=10,
    )
    base.update(kwargs)
    return TaskContract(**base)


def test_task_contract_persists(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db")
    c = make_contract()
    ledger.upsert_task(c)
    row = ledger.get_task(c.task_id)
    assert row is not None
    assert row["objective"] == "Test objective"
    assert row["data_classification"] == "internal-non-sensitive"


def test_zero_budget_blocks_dispatch(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db")
    c = make_contract(budget_ceiling_usd=0)
    ledger.upsert_task(c)
    guard = BudgetGuard(ledger, daily_limit_usd=0, monthly_limit_usd=0)
    with pytest.raises(BudgetDenied):
        guard.reserve(
            task_id=c.task_id,
            step_id="s1",
            amount_usd=0.01,
            task_limit_usd=0,
        )


def test_one_step_escalation_only():
    assert should_escalate(verifier_passed=False, paid_attempt_number=1) is True
    assert should_escalate(verifier_passed=False, paid_attempt_number=2) is False
    assert should_escalate(verifier_passed=True, paid_attempt_number=1) is False


def test_sensitive_blocked_in_v0_2():
    assert classify() == "internal-non-sensitive"
    with pytest.raises(PermissionError):
        assert_v0_2_allowed("sensitive")


def test_completed_step_is_idempotent(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db", project_root=tmp_path)
    c = make_contract()
    ledger.upsert_task(c)
    artifact = tmp_path / "done.md"
    artifact.write_text("done", encoding="utf-8")

    assert ledger.start_step(
        step_id="step-1",
        task_id=c.task_id,
        stage="draft",
        provider="anthropic",
        model="test",
        idempotency_key=f"{c.task_id}:draft:v1",
        prompt_hash="abc",
    ) is True
    ledger.complete_step(f"{c.task_id}:draft:v1", str(artifact))

    assert ledger.start_step(
        step_id="step-2",
        task_id=c.task_id,
        stage="draft",
        provider="anthropic",
        model="test",
        idempotency_key=f"{c.task_id}:draft:v1",
        prompt_hash="abc",
    ) is False
    stored = ledger.completed_artifact(f"{c.task_id}:draft:v1")
    assert stored == "done.md"
    assert ledger.resolve_artifact_path(stored) == artifact


def test_legacy_windows_artifact_path_is_migrated(tmp_path):
    ledger_path = tmp_path / "ledger.db"
    ledger = Ledger(ledger_path, project_root=tmp_path)
    c = make_contract(task_id="legacy-task")
    ledger.upsert_task(c)
    ledger.start_step(
        step_id="legacy-step",
        task_id=c.task_id,
        stage="draft",
        provider="anthropic",
        model="test",
        idempotency_key="legacy-task:draft:v1",
        prompt_hash="abc",
    )
    with ledger.connect() as connection:
        connection.execute(
            """
            UPDATE steps
            SET status='completed', artifact_path=?
            WHERE idempotency_key=?
            """,
            (
                r"C:\Users\old-user\Downloads\ai_loop\outputs\draft.md",
                "legacy-task:draft:v1",
            ),
        )

    migrated = Ledger(ledger_path, project_root=tmp_path)
    assert migrated.migrated_artifact_paths == 1
    assert migrated.completed_artifact("legacy-task:draft:v1") == "outputs/draft.md"
    assert migrated.resolve_artifact_path("outputs/draft.md") == tmp_path / "outputs" / "draft.md"


def test_preflight_flag_is_explicit():
    assert parse_args(["--preflight-only"]).preflight_only is True
    assert parse_args([]).preflight_only is False


def test_artifact_survives_project_relocation(tmp_path):
    original = tmp_path / "original"
    relocated = tmp_path / "relocated"
    original.mkdir()
    (original / "outputs").mkdir()
    artifact = original / "outputs" / "done.md"
    artifact.write_text("portable", encoding="utf-8")

    ledger = Ledger(original / "ledger.db", project_root=original)
    c = make_contract(task_id="portable-task")
    ledger.upsert_task(c)
    ledger.start_step(
        step_id="portable-step",
        task_id=c.task_id,
        stage="draft",
        provider="anthropic",
        model="test",
        idempotency_key="portable-task:draft:v1",
        prompt_hash="abc",
    )
    ledger.complete_step("portable-task:draft:v1", str(artifact))

    shutil.copytree(original, relocated)
    moved_ledger = Ledger(relocated / "ledger.db", project_root=relocated)
    stored = moved_ledger.completed_artifact("portable-task:draft:v1")
    assert stored == "outputs/done.md"
    assert moved_ledger.resolve_artifact_path(stored).read_text(encoding="utf-8") == "portable"


def test_artifact_path_rejects_project_escape(tmp_path):
    with pytest.raises(ValueError):
        portable_project_path("../outside.md", tmp_path)


def test_missing_artifact_can_be_marked_for_safe_rerun(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db", project_root=tmp_path)
    c = make_contract(task_id="missing-task")
    ledger.upsert_task(c)
    ledger.start_step(
        step_id="missing-step",
        task_id=c.task_id,
        stage="draft",
        provider="anthropic",
        model="test",
        idempotency_key="missing-task:draft:v1",
        prompt_hash="abc",
    )
    missing = tmp_path / "outputs" / "missing.md"
    ledger.complete_step("missing-task:draft:v1", str(missing))
    ledger.mark_artifact_missing("missing-task:draft:v1", "outputs/missing.md")

    with ledger.connect() as connection:
        status = connection.execute(
            "SELECT status FROM steps WHERE idempotency_key=?",
            ("missing-task:draft:v1",),
        ).fetchone()["status"]
    assert status == "artifact_missing"
    assert ledger.completed_artifact("missing-task:draft:v1") is None


def test_python_symbol_retrieval(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text(
        "def target_function(x):\n    return x + 1\n", encoding="utf-8"
    )
    hits = find_symbol(repo, "target_function")
    assert hits
    assert Path(hits[0].path).name == "sample.py"
    assert hits[0].line == 1
