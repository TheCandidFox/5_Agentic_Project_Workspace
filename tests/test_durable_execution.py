from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from command_runner import (
    CommandPolicy,
    CommandRequest,
    CommandRunner,
    ExecutableRule,
    JsonlCommandEventSink,
)
from durable_execution import (
    CommandDispatchInProgress,
    CommandDispatchPreviouslyFailed,
    CommandIdempotencyConflict,
    CommandIdempotencyRequired,
    IdempotentCommandRunner,
    command_request_sha256,
)
from ledger import Ledger
from workspace_guard import WorkspaceGuard


def make_components(tmp_path, *, event_sink=False, allowed_environment_keys=()):
    root = tmp_path / "candidate"
    root.mkdir()
    guard = WorkspaceGuard(root)
    policy = CommandPolicy(
        rules=(
            ExecutableRule(
                alias="python",
                executable=Path(sys.executable),
                allow_any_arguments=True,
            ),
        ),
        allowed_environment_keys=frozenset(allowed_environment_keys),
        max_timeout_seconds=120,
        max_output_bytes=100_000,
    )
    sink = JsonlCommandEventSink(guard) if event_sink else None
    runner = CommandRunner(guard, policy, event_sink=sink)
    ledger = Ledger(root / "ledger.db", project_root=root)
    return root, runner, ledger, IdempotentCommandRunner(runner, ledger)


def increment_request(key="increment:v1"):
    code = (
        "from pathlib import Path; p=Path('counter.txt'); "
        "n=int(p.read_text()) if p.exists() else 0; p.write_text(str(n+1))"
    )
    return CommandRequest(
        argv=("python", "-c", code),
        idempotency_key=key,
        task_id="task-1",
        action_id="increment",
    )


def test_durable_dispatch_requires_an_idempotency_key(tmp_path):
    _, _, _, durable = make_components(tmp_path)

    with pytest.raises(CommandIdempotencyRequired):
        durable.run(CommandRequest(argv=("python", "-c", "print('no key')")))


def test_completed_command_is_replayed_without_executing_twice(tmp_path):
    root, _, ledger, durable = make_components(tmp_path)
    request = increment_request()

    first = durable.run(request)
    second = durable.run(request)

    assert (root / "counter.txt").read_text(encoding="utf-8") == "1"
    assert first.replayed is False
    assert second.replayed is True
    assert first.command_id == second.command_id
    assert second.outcome == first.outcome
    assert ledger.get_command("increment:v1")["status"] == "completed"


def test_same_command_key_with_changed_request_is_rejected(tmp_path):
    _, _, _, durable = make_components(tmp_path)
    durable.run(
        CommandRequest(
            argv=("python", "-c", "print('first')"),
            idempotency_key="shared-key",
        )
    )

    with pytest.raises(CommandIdempotencyConflict):
        durable.run(
            CommandRequest(
                argv=("python", "-c", "print('different')"),
                idempotency_key="shared-key",
            )
        )


def test_redacted_argument_changes_still_change_the_private_fingerprint(tmp_path):
    _, _, ledger, durable = make_components(tmp_path)
    first_value = "sk-" + "ant-" + "fixtureValue111111"
    second_value = "sk-" + "ant-" + "fixtureValue222222"
    first = CommandRequest(
        argv=("python", "-c", f"print('{first_value}')"),
        idempotency_key="redacted-argument-key",
    )
    second = CommandRequest(
        argv=("python", "-c", f"print('{second_value}')"),
        idempotency_key="redacted-argument-key",
    )

    result = durable.run(first)
    with pytest.raises(CommandIdempotencyConflict):
        durable.run(second)

    persisted = json.dumps(ledger.get_command("redacted-argument-key"))
    assert result.stdout.strip() == "[REDACTED]"
    assert first_value not in persisted
    assert second_value not in persisted


def test_unfinished_claim_blocks_duplicate_dispatch(tmp_path):
    _, runner, ledger, durable = make_components(tmp_path)
    request = increment_request("in-progress-key")
    description = runner.describe_request(request)
    fingerprint = command_request_sha256(request, description)
    ledger.claim_command(
        command_id="claimed-command",
        task_id=request.task_id,
        action_id=request.action_id,
        idempotency_key=request.idempotency_key,
        request_sha256=fingerprint,
        request={
            "argv": list(description["argv"]),
            "executable_alias": description["executable_alias"],
            "cwd": description["cwd"],
            "timeout_seconds": description["timeout_seconds"],
            "max_output_bytes": description["max_output_bytes"],
            "encoding": description["encoding"],
            "environment_keys": description["environment_keys"],
        },
    )

    with pytest.raises(CommandDispatchInProgress):
        durable.run(request)


def test_dispatch_exception_is_recorded_and_not_retried_implicitly(tmp_path, monkeypatch):
    _, runner, ledger, durable = make_components(tmp_path)
    request = increment_request("dispatch-error-key")

    def fail_after_claim(_request, *, command_id=None):
        raise RuntimeError("simulated dispatch failure")

    monkeypatch.setattr(runner, "run", fail_after_claim)
    with pytest.raises(RuntimeError, match="simulated"):
        durable.run(request)

    record = ledger.get_command("dispatch-error-key")
    assert record["status"] == "dispatch_error"
    assert record["outcome"] == "ERROR"
    with pytest.raises(CommandDispatchPreviouslyFailed, match="simulated"):
        durable.run(request)


def test_jsonl_and_sqlite_events_use_portable_executable_identity(tmp_path):
    root, _, ledger, durable = make_components(tmp_path, event_sink=True)

    result = durable.run(
        CommandRequest(
            argv=("python", "-c", "print('portable')"),
            idempotency_key="portable-event-key",
        )
    )

    event = json.loads(
        (root / "logs" / "command_events.jsonl").read_text(encoding="utf-8")
    )
    serialized = json.dumps(event)
    assert event["executable_alias"] == "python"
    assert event["command_id"] == result.command_id
    assert str(Path(sys.executable)) not in serialized
    with ledger.connect() as con:
        payloads = "\n".join(
            row["payload_json"]
            for row in con.execute(
                "SELECT payload_json FROM events ORDER BY id"
            ).fetchall()
        )
    assert str(Path(sys.executable)) not in payloads


def test_sensitive_environment_value_is_hashed_but_never_persisted(tmp_path):
    root, _, ledger, durable = make_components(
        tmp_path,
        allowed_environment_keys={"SERVICE_TOKEN"},
    )
    secret = "durable-fixture-private-value"

    result = durable.run(
        CommandRequest(
            argv=(
                "python",
                "-c",
                "import os; print(os.environ['SERVICE_TOKEN'])",
            ),
            environment={"SERVICE_TOKEN": secret},
            idempotency_key="secret-env-key",
        )
    )

    assert result.stdout.strip() == "[REDACTED]"
    with ledger.connect() as con:
        command_values = con.execute("SELECT * FROM commands").fetchone()
        event_values = con.execute(
            "SELECT GROUP_CONCAT(payload_json, '') AS payloads FROM events"
        ).fetchone()["payloads"]
    serialized = json.dumps(dict(command_values)) + (event_values or "")
    assert secret not in serialized
    assert "SERVICE_TOKEN" in serialized
    assert (root / "ledger.db").is_file()
