from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from command_runner import CommandOutcome, CommandRequest, CommandResult, CommandRunner
from ledger import Ledger


class CommandIdempotencyRequired(ValueError):
    """Raised when durable dispatch is attempted without an idempotency key."""


class CommandIdempotencyConflict(RuntimeError):
    """Raised when a command key is reused for a different request."""


class CommandDispatchInProgress(RuntimeError):
    """Raised when a prior claimant may still own the command dispatch."""


class CommandDispatchPreviouslyFailed(RuntimeError):
    """Raised when the original dispatch failed before a result was recorded."""


def command_request_sha256(
    request: CommandRequest,
    portable_description: dict[str, object],
) -> str:
    """Fingerprint command semantics without persisting credential values."""

    payload = {
        "argv": [portable_description["executable_alias"], *tuple(request.argv)[1:]],
        "executable_alias": portable_description["executable_alias"],
        "cwd": portable_description["cwd"],
        "timeout_seconds": portable_description["timeout_seconds"],
        "max_output_bytes": portable_description["max_output_bytes"],
        "encoding": portable_description["encoding"],
        "environment": {
            key: request.environment[key]
            for key in sorted(request.environment, key=str.casefold)
        },
        "task_id": request.task_id,
        "action_id": request.action_id,
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class IdempotentCommandRunner:
    """Add durable at-most-once claims and terminal-result replay."""

    def __init__(self, runner: CommandRunner, ledger: Ledger) -> None:
        self.runner = runner
        self.ledger = ledger

    def run(self, request: CommandRequest) -> CommandResult:
        key = request.idempotency_key
        if not isinstance(key, str) or not key.strip() or "\x00" in key:
            raise CommandIdempotencyRequired(
                "durable command dispatch requires a non-empty idempotency key"
            )

        description = self.runner.describe_request(request)
        request_sha256 = command_request_sha256(request, description)
        command_id = str(uuid.uuid4())
        durable_request = {
            "argv": list(description["argv"]),
            "executable_alias": description["executable_alias"],
            "cwd": description["cwd"],
            "timeout_seconds": description["timeout_seconds"],
            "max_output_bytes": description["max_output_bytes"],
            "encoding": description["encoding"],
            "environment_keys": description["environment_keys"],
        }
        claimed, record = self.ledger.claim_command(
            command_id=command_id,
            task_id=request.task_id,
            action_id=request.action_id,
            idempotency_key=key,
            request_sha256=request_sha256,
            request=durable_request,
        )
        if not claimed:
            if record["request_sha256"] != request_sha256:
                raise CommandIdempotencyConflict(
                    "command idempotency key belongs to a different request"
                )
            if record["status"] == "completed":
                return self._replay(record, description)
            if record["status"] == "dispatching":
                raise CommandDispatchInProgress(
                    "command has a durable dispatch claim without a terminal result"
                )
            if record["status"] == "dispatch_error":
                raise CommandDispatchPreviouslyFailed(
                    record.get("error") or "the original command dispatch failed"
                )
            raise RuntimeError(f"unknown durable command status: {record['status']}")

        try:
            result = self.runner.run(request, command_id=command_id)
        except Exception as exc:
            portable_error = f"{type(exc).__name__}: {exc}"
            portable_error = portable_error.replace(
                str(self.runner.guard.root),
                "<workspace>",
            ).replace(
                str(description["launch_executable"]),
                f"<executable:{description['executable_alias']}>",
            ).replace(
                str(description["resolved_executable"]),
                f"<executable:{description['executable_alias']}>",
            )
            safe_error = self.runner.redactor.redact(portable_error)[:4_000]
            self.ledger.fail_command_dispatch(command_id, safe_error)
            raise

        stored = self.ledger.complete_command(
            command_id,
            {
                "outcome": result.outcome.value,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "stdout_truncated": result.stdout_truncated,
                "stderr_truncated": result.stderr_truncated,
                "duration_ms": result.duration_ms,
                "started_at": result.started_at,
                "completed_at": result.completed_at,
                "error": result.error,
            },
        )
        if stored["command_id"] != command_id:
            raise RuntimeError("durable command completion identity mismatch")
        return result

    @staticmethod
    def _replay(
        record: dict[str, Any],
        current_description: dict[str, object],
    ) -> CommandResult:
        request = record["request"]
        return CommandResult(
            outcome=CommandOutcome(record["outcome"]),
            argv=tuple(str(value) for value in request["argv"]),
            executable=str(current_description["launch_executable"]),
            cwd=str(record["cwd"]),
            exit_code=record["exit_code"],
            stdout=record["stdout"] or "",
            stderr=record["stderr"] or "",
            stdout_truncated=bool(record["stdout_truncated"]),
            stderr_truncated=bool(record["stderr_truncated"]),
            duration_ms=int(record["duration_ms"] or 0),
            started_at=str(record["started_at"]),
            completed_at=str(record["completed_at"]),
            task_id=record.get("task_id"),
            action_id=record.get("action_id"),
            idempotency_key=record["idempotency_key"],
            error=record.get("error"),
            command_id=record["command_id"],
            replayed=True,
        )
