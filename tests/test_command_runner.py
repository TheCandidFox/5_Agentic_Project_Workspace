from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from command_runner import (
    CommandDenied,
    CommandOutcome,
    CommandPolicy,
    CommandRequest,
    CommandRunner,
    ExecutableRule,
    JsonlCommandEventSink,
    SecretRedactor,
)
from workspace_guard import WorkspaceGuard, WorkspaceViolation


def python_rule(**kwargs) -> ExecutableRule:
    return ExecutableRule(alias="python", executable=Path(sys.executable), **kwargs)


def make_runner(
    root: Path,
    *,
    max_timeout: float = 60,
    max_output: int = 100_000,
    allowed_environment_keys=frozenset(),
    redactor: SecretRedactor | None = None,
    event_sink=None,
) -> CommandRunner:
    guard = WorkspaceGuard(root)
    policy = CommandPolicy(
        rules=(python_rule(allow_any_arguments=True),),
        allowed_environment_keys=frozenset(allowed_environment_keys),
        max_timeout_seconds=max_timeout,
        max_output_bytes=max_output,
    )
    return CommandRunner(
        guard,
        policy,
        redactor=redactor,
        event_sink=event_sink,
    )


def test_captures_success_stdout_and_metadata(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    runner = make_runner(root)

    result = runner.run(
        CommandRequest(
            argv=("python", "-c", "print('hello')"),
            task_id="task-1",
            action_id="action-1",
            idempotency_key="task-1:action-1:v1",
        )
    )

    assert result.outcome == CommandOutcome.PASS
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"
    assert result.stderr == ""
    assert result.cwd == "."
    assert result.argv[0] == "python"
    assert result.task_id == "task-1"
    assert result.duration_ms >= 0


def test_captures_nonzero_exit_and_stderr(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    runner = make_runner(root)

    result = runner.run(
        CommandRequest(
            argv=(
                "python",
                "-c",
                "import sys; sys.stderr.write('broken\\n'); raise SystemExit(7)",
            )
        )
    )

    assert result.outcome == CommandOutcome.FAIL
    assert result.exit_code == 7
    assert result.stderr.splitlines() == ["broken"]


def test_timeout_kills_direct_child_and_returns_timeout(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    runner = make_runner(root, max_timeout=2)

    result = runner.run(
        CommandRequest(
            argv=("python", "-c", "import time; time.sleep(10)"),
            timeout_seconds=0.1,
        )
    )

    assert result.outcome == CommandOutcome.TIMEOUT
    assert result.duration_ms < 5_000


def test_large_output_is_drained_and_bounded_per_stream(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    runner = make_runner(root, max_output=128)

    result = runner.run(
        CommandRequest(
            argv=(
                "python",
                "-c",
                "import sys; print('x'*5000); sys.stderr.write('y'*5000)",
            )
        )
    )

    assert result.outcome == CommandOutcome.PASS
    assert len(result.stdout.encode("utf-8")) <= 128
    assert len(result.stderr.encode("utf-8")) <= 128
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True


def test_redacts_explicit_and_pattern_secrets_from_output_and_argv(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    explicit = "private-value-12345"
    # Assemble the provider-shaped fixture at runtime so static secret scanners
    # do not mistake test data for a credential.
    provider_key = "sk-" + "ant-" + "exampleSecret123456789"
    runner = make_runner(root, redactor=SecretRedactor((explicit,)))
    code = (
        f"import sys; print('{explicit}'); "
        f"sys.stderr.write('ANTHROPIC_API_KEY={provider_key}\\n')"
    )

    result = runner.run(CommandRequest(argv=("python", "-c", code)))
    combined = "\n".join((" ".join(result.argv), result.stdout, result.stderr))

    assert explicit not in combined
    assert provider_key not in combined
    assert "[REDACTED]" in combined


def test_does_not_inherit_api_keys(tmp_path, monkeypatch):
    root = tmp_path / "candidate"
    root.mkdir()
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-child")
    runner = make_runner(root)

    result = runner.run(
        CommandRequest(
            argv=(
                "python",
                "-c",
                "import os; print(os.getenv('OPENAI_API_KEY', 'not-present'))",
            )
        )
    )

    assert result.stdout.strip() == "not-present"


def test_allows_only_explicit_environment_keys(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    runner = make_runner(root, allowed_environment_keys={"PHASE1_TEST"})

    result = runner.run(
        CommandRequest(
            argv=(
                "python",
                "-c",
                "import os; print(os.environ['PHASE1_TEST'])",
            ),
            environment={"PHASE1_TEST": "allowed"},
        )
    )
    assert result.stdout.strip() == "allowed"

    with pytest.raises(CommandDenied, match="not allowlisted"):
        runner.run(
            CommandRequest(
                argv=("python", "-c", "print('never runs')"),
                environment={"OPENAI_API_KEY": "denied"},
            )
        )


def test_redacts_allowlisted_sensitive_environment_values(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    secret = "generic-service-secret-value"
    runner = make_runner(root, allowed_environment_keys={"SERVICE_TOKEN"})

    result = runner.run(
        CommandRequest(
            argv=(
                "python",
                "-c",
                "import os; print(os.environ['SERVICE_TOKEN'])",
            ),
            environment={"SERVICE_TOKEN": secret},
        )
    )

    assert secret not in result.stdout
    assert result.stdout.strip() == "[REDACTED]"


def test_rejects_unlisted_executable_and_string_command(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    runner = make_runner(root)

    with pytest.raises(CommandDenied, match="not allowlisted"):
        runner.run(CommandRequest(argv=("not-allowed", "--version")))
    with pytest.raises(CommandDenied, match="separate arguments"):
        runner.run(CommandRequest(argv="python -c print('unsafe')"))
    with pytest.raises(CommandDenied, match="separate arguments"):
        runner.run(CommandRequest(argv=(value for value in ("python", "--version"))))


def test_rejects_working_directory_outside_workspace(tmp_path):
    root = tmp_path / "candidate"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    runner = make_runner(root)

    with pytest.raises(CommandDenied, match="outside workspace"):
        runner.run(
            CommandRequest(
                argv=("python", "-c", "print('never runs')"),
                cwd=outside,
            )
        )


def test_argument_prefix_policy_blocks_unapproved_invocation(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    guard = WorkspaceGuard(root)
    policy = CommandPolicy(
        rules=(
            python_rule(allowed_argument_prefixes=(("-m", "pytest"),)),
        )
    )
    runner = CommandRunner(guard, policy)

    with pytest.raises(CommandDenied, match="arguments are not allowed"):
        runner.run(CommandRequest(argv=("python", "-c", "print('blocked')")))


def test_argument_prefix_policy_allows_approved_invocation(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    guard = WorkspaceGuard(root)
    policy = CommandPolicy(
        rules=(python_rule(allowed_argument_prefixes=(("-c",),)),),
    )
    runner = CommandRunner(guard, policy)

    result = runner.run(CommandRequest(argv=("python", "-c", "print('allowed')")))
    assert result.outcome == CommandOutcome.PASS
    assert result.stdout.strip() == "allowed"


def test_empty_argument_prefix_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="must not be empty"):
        python_rule(allowed_argument_prefixes=((),))


def test_timeout_and_output_requests_cannot_exceed_policy(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    runner = make_runner(root, max_timeout=1, max_output=100)

    with pytest.raises(CommandDenied, match="timeout exceeds"):
        runner.run(
            CommandRequest(
                argv=("python", "-c", "print('blocked')"),
                timeout_seconds=2,
            )
        )

    with pytest.raises(CommandDenied, match="finite number"):
        runner.run(
            CommandRequest(
                argv=("python", "-c", "print('blocked')"),
                timeout_seconds=float("nan"),
            )
        )
    with pytest.raises(CommandDenied, match="outside policy bounds"):
        runner.run(
            CommandRequest(
                argv=("python", "-c", "print('blocked')"),
                max_output_bytes=0,
                timeout_seconds=1,
            )
        )
    with pytest.raises(CommandDenied, match="outside policy bounds"):
        runner.run(
            CommandRequest(
                argv=("python", "-c", "print('blocked')"),
                max_output_bytes=101,
                timeout_seconds=1,
            )
        )


def test_rejects_unknown_output_encoding_before_dispatch(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    runner = make_runner(root)

    with pytest.raises(CommandDenied, match="unknown output encoding"):
        runner.run(
            CommandRequest(
                argv=("python", "-c", "print('never runs')"),
                encoding="not-a-real-codec",
            )
        )


def test_absolute_allowlisted_executable_path_is_accepted(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    runner = make_runner(root)

    result = runner.run(
        CommandRequest(argv=(str(Path(sys.executable)), "-c", "print('absolute')"))
    )
    assert result.outcome == CommandOutcome.PASS
    assert result.stdout.strip() == "absolute"


def test_spawn_failure_returns_structured_error(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    copied_python = tmp_path / Path(sys.executable).name
    shutil.copy2(sys.executable, copied_python)
    guard = WorkspaceGuard(root)
    rule = ExecutableRule(alias="temporary-python", executable=copied_python)
    policy = CommandPolicy(rules=(rule,))
    runner = CommandRunner(guard, policy)
    copied_python.unlink()

    result = runner.run(CommandRequest(argv=("temporary-python",)))
    assert result.outcome == CommandOutcome.ERROR
    assert result.exit_code is None
    assert result.error


def test_shell_executable_requires_explicit_policy_opt_in(tmp_path):
    shell = Path(os.environ.get("COMSPEC", ""))
    if not shell.is_file():
        pytest.skip("Windows command shell is unavailable")

    with pytest.raises(ValueError, match="explicit opt-in"):
        CommandPolicy(
            rules=(
                ExecutableRule(
                    alias="cmd",
                    executable=shell,
                    allow_any_arguments=True,
                ),
            )
        )


def test_sensitive_ambient_environment_requires_explicit_policy_opt_in(tmp_path):
    with pytest.raises(ValueError, match="sensitive inherited environment key"):
        CommandPolicy(
            rules=(python_rule(allow_any_arguments=True),),
            inherited_environment_keys=("OPENAI_API_KEY",),
        )


def test_policy_rejects_invalid_rule_and_environment_key_types(tmp_path):
    with pytest.raises(TypeError, match="ExecutableRule"):
        CommandPolicy(rules=(object(),))

    with pytest.raises(ValueError, match="allowed environment keys"):
        CommandPolicy(
            rules=(python_rule(allow_any_arguments=True),),
            allowed_environment_keys=frozenset({"INVALID=NAME"}),
        )


def test_event_sink_rejects_protected_destination_before_dispatch(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()

    with pytest.raises(WorkspaceViolation, match="protected"):
        JsonlCommandEventSink(WorkspaceGuard(root), path=".env")


def test_writes_redacted_durable_jsonl_event(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    guard = WorkspaceGuard(root)
    sink = JsonlCommandEventSink(guard)
    secret = "event-secret-12345"
    runner = make_runner(
        root,
        redactor=SecretRedactor((secret,)),
        event_sink=sink,
    )

    result = runner.run(
        CommandRequest(
            argv=("python", "-c", f"print('{secret}')"),
            task_id="task-event",
            action_id="action-event",
        )
    )

    event_path = root / "logs" / "command_events.jsonl"
    lines = event_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    serialized = json.dumps(event)
    assert secret not in serialized
    assert "[REDACTED]" in serialized
    assert event["outcome"] == "PASS"
    assert event["task_id"] == "task-event"
    assert event["cwd"] == "."
    assert result.stdout.strip() == "[REDACTED]"
