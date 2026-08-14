from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from ledger import Ledger


def make_ledger(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    return root, Ledger(root / "ledger.db", project_root=root)


def command_request_record():
    return {
        "argv": ["python", "-m", "pytest", "-q"],
        "executable_alias": "python",
        "cwd": ".",
        "timeout_seconds": 60.0,
        "max_output_bytes": 100_000,
        "encoding": "utf-8",
        "environment_keys": [],
    }


def test_additive_migration_applies_once_and_preserves_existing_events(tmp_path):
    root, first = make_ledger(tmp_path)
    first.event("legacy_event", {"preserved": True})

    assert first.applied_schema_migrations == (
        "0001_bootstrap_commands_validations",
        "0002_transactional_changes",
        "0003_bounded_autonomy",
        "0004_research_provenance",
        "0005_acceptance_truth",
        "0006_project_orchestration",
        "0007_governed_provider_calls",
        "0008_recovery_observability",
    )
    assert first.schema_migration_ids() == first.applied_schema_migrations

    reopened = Ledger(root / "ledger.db", project_root=root)

    assert reopened.applied_schema_migrations == ()
    assert reopened.schema_migration_ids() == (
        "0001_bootstrap_commands_validations",
        "0002_transactional_changes",
        "0003_bounded_autonomy",
        "0004_research_provenance",
        "0005_acceptance_truth",
        "0006_project_orchestration",
        "0007_governed_provider_calls",
        "0008_recovery_observability",
    )
    assert reopened.integrity_check() == "ok"
    with reopened.connect() as con:
        tables = {
            row["name"]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        preserved = con.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='legacy_event'"
        ).fetchone()[0]
    assert {
        "tasks",
        "steps",
        "commands",
        "validation_runs",
        "patch_transactions",
        "patch_files",
        "git_checkpoints",
        "research_runs",
        "research_sources",
        "research_claims",
        "research_citations",
        "acceptance_runs",
        "acceptance_evidence",
        "acceptance_claims",
        "acceptance_criteria",
        "acceptance_constraints",
        "project_runs",
        "backlog_tasks",
        "backlog_dependencies",
        "task_dispatches",
        "project_artifacts",
        "provider_calls",
    } <= tables
    assert preserved == 1


def test_migration_checksum_tampering_is_rejected(tmp_path):
    root, ledger = make_ledger(tmp_path)
    with ledger.connect() as con:
        con.execute(
            """
            UPDATE schema_migrations SET checksum_sha256='bad'
            WHERE migration_id='0001_bootstrap_commands_validations'
            """
        )

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        Ledger(root / "ledger.db", project_root=root)


def test_concurrent_ledger_initialization_records_migration_once(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    database = root / "ledger.db"
    barrier = threading.Barrier(2)

    def initialize(_number):
        barrier.wait(timeout=5)
        ledger = Ledger(database, project_root=root)
        return ledger.applied_schema_migrations, ledger.schema_migration_ids()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(initialize, (1, 2)))

    applied_counts = [len(applied) for applied, _ in results]
    assert sorted(applied_counts) == [0, 8]
    assert all(
        migration_ids
        == (
            "0001_bootstrap_commands_validations",
            "0002_transactional_changes",
            "0003_bounded_autonomy",
            "0004_research_provenance",
            "0005_acceptance_truth",
            "0006_project_orchestration",
            "0007_governed_provider_calls",
            "0008_recovery_observability",
        )
        for _, migration_ids in results
    )


def test_command_claim_is_atomic_and_keeps_only_portable_request_paths(tmp_path):
    root, ledger = make_ledger(tmp_path)
    request = command_request_record()
    fingerprint = "a" * 64

    claimed, first = ledger.claim_command(
        command_id="command-1",
        task_id="task-1",
        action_id="action-1",
        idempotency_key="task-1:action-1:v1",
        request_sha256=fingerprint,
        request=request,
    )
    claimed_again, second = ledger.claim_command(
        command_id="command-2",
        task_id="task-1",
        action_id="action-1",
        idempotency_key="task-1:action-1:v1",
        request_sha256=fingerprint,
        request=request,
    )

    assert claimed is True
    assert claimed_again is False
    assert first["command_id"] == second["command_id"] == "command-1"
    assert first["status"] == "dispatching"
    serialized = json.dumps(first)
    assert str(root) not in serialized
    assert first["request"]["cwd"] == "."
    with ledger.connect() as con:
        count = con.execute("SELECT COUNT(*) FROM commands").fetchone()[0]
    assert count == 1


def test_concurrent_command_claim_has_exactly_one_winner(tmp_path):
    _, ledger = make_ledger(tmp_path)
    barrier = threading.Barrier(2)

    def claim(number):
        barrier.wait(timeout=5)
        claimed, record = ledger.claim_command(
            command_id=f"command-{number}",
            task_id=None,
            action_id="concurrent",
            idempotency_key="concurrent-key",
            request_sha256="e" * 64,
            request=command_request_record(),
        )
        return claimed, record["command_id"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, (1, 2)))

    assert sorted(claimed for claimed, _ in results) == [False, True]
    assert len({command_id for _, command_id in results}) == 1
    with ledger.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 1


def test_command_completion_records_hashes_and_compact_event(tmp_path):
    _, ledger = make_ledger(tmp_path)
    ledger.claim_command(
        command_id="command-1",
        task_id="task-1",
        action_id="action-1",
        idempotency_key="command-key",
        request_sha256="b" * 64,
        request=command_request_record(),
    )

    completed = ledger.complete_command(
        "command-1",
        {
            "outcome": "PASS",
            "exit_code": 0,
            "stdout": "passed\n",
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "duration_ms": 12,
            "started_at": "2026-08-10T00:00:00+00:00",
            "completed_at": "2026-08-10T00:00:01+00:00",
            "error": None,
        },
    )

    assert completed["status"] == "completed"
    assert completed["stdout_sha256"] == hashlib.sha256(b"passed\n").hexdigest()
    assert ledger.get_command("command-key")["outcome"] == "PASS"
    with ledger.connect() as con:
        event = con.execute(
            """
            SELECT payload_json FROM events
            WHERE event_type='command_completed'
            """
        ).fetchone()
    payload = json.loads(event["payload_json"])
    assert payload["command_id"] == "command-1"
    assert "stdout" not in payload


def test_validation_records_are_insert_once_for_an_idempotency_key(tmp_path):
    _, ledger = make_ledger(tmp_path)
    record = {
        "validation_id": "validation-1",
        "task_id": "task-1",
        "action_id": "validate-1",
        "command_id": None,
        "check_id": "syntax",
        "kind": "PYTHON_SYNTAX",
        "idempotency_key": "validation-key",
        "spec_sha256": "c" * 64,
        "outcome": "PASS",
        "summary": "passed",
        "details": {"files_checked": 3},
        "started_at": "2026-08-10T00:00:00+00:00",
        "completed_at": "2026-08-10T00:00:01+00:00",
        "duration_ms": 10,
    }

    first = ledger.record_validation(record)
    changed = dict(record, validation_id="validation-2", summary="changed")
    second = ledger.record_validation(changed)

    assert first["validation_id"] == second["validation_id"] == "validation-1"
    assert second["summary"] == "passed"
    assert ledger.get_validation("validation-key")["details"] == {
        "files_checked": 3
    }
    with ledger.connect() as con:
        count = con.execute("SELECT COUNT(*) FROM validation_runs").fetchone()[0]
    assert count == 1


def test_command_claim_rejects_absolute_or_traversing_durable_cwd(tmp_path):
    root, ledger = make_ledger(tmp_path)
    for cwd in (str(root), "../outside"):
        request = command_request_record()
        request["cwd"] = cwd
        with pytest.raises(ValueError, match="project-relative"):
            ledger.claim_command(
                command_id=f"command-{len(cwd)}",
                task_id=None,
                action_id=None,
                idempotency_key=f"key-{len(cwd)}",
                request_sha256="d" * 64,
                request=request,
            )
