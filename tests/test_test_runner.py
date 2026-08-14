from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

from command_runner import (
    CommandPolicy,
    CommandRequest,
    CommandRunner,
    ExecutableRule,
)
from durable_execution import IdempotentCommandRunner
from ledger import Ledger
from test_runner import (
    CommandCheck,
    FileCheck,
    JsonCheck,
    PytestCheck,
    PythonSyntaxCheck,
    TestRunner,
    ValidationIdempotencyConflict,
    ValidationOutcome,
)
from workspace_guard import WorkspaceGuard


def make_root(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    return root


def make_command_runner(root, *, max_timeout=180):
    guard = WorkspaceGuard(root)
    policy = CommandPolicy(
        rules=(
            ExecutableRule(
                alias="python",
                executable=Path(sys.executable),
                allow_any_arguments=True,
            ),
        ),
        allowed_environment_keys=frozenset({"PYTHONPATH"}),
        max_timeout_seconds=max_timeout,
        max_output_bytes=200_000,
    )
    return guard, CommandRunner(guard, policy)


def test_python_syntax_check_reports_relative_failures_then_passes(tmp_path):
    root = make_root(tmp_path)
    (root / "good.py").write_text("value = 1\n", encoding="utf-8")
    broken = root / "nested" / "broken.py"
    broken.parent.mkdir()
    broken.write_text("def broken(:\n", encoding="utf-8")
    runner = TestRunner(WorkspaceGuard(root))

    failed = runner.run(PythonSyntaxCheck(check_id="syntax", paths=(".",)))
    broken.write_text("def fixed():\n    return True\n", encoding="utf-8")
    passed = runner.run(PythonSyntaxCheck(check_id="syntax-fixed", paths=(".",)))

    assert failed.outcome == ValidationOutcome.FAIL
    assert failed.details["failures"][0]["path"] == "nested/broken.py"
    assert str(root) not in str(failed.details)
    assert passed.outcome == ValidationOutcome.PASS
    assert passed.details["files_checked"] == 2


def test_python_syntax_check_is_not_applicable_without_python_files(tmp_path):
    root = make_root(tmp_path)
    (root / "README.md").write_text("docs", encoding="utf-8")

    result = TestRunner(WorkspaceGuard(root)).run(
        PythonSyntaxCheck(check_id="syntax")
    )

    assert result.outcome == ValidationOutcome.NOT_APPLICABLE
    assert result.details["files_checked"] == 0


def test_protected_syntax_input_returns_portable_error(tmp_path):
    root = make_root(tmp_path)
    (root / ".env").write_text("PRIVATE=value", encoding="utf-8")

    result = TestRunner(WorkspaceGuard(root)).run(
        PythonSyntaxCheck(check_id="protected", paths=(".env",))
    )

    assert result.outcome == ValidationOutcome.ERROR
    assert result.details == {"error_type": "WorkspaceViolation"}
    assert str(root) not in str(result.to_record())


def test_file_check_supports_presence_size_hash_and_optional_absence(tmp_path):
    root = make_root(tmp_path)
    artifact = root / "artifact.txt"
    artifact.write_text("verified", encoding="utf-8")
    digest = hashlib.sha256(b"verified").hexdigest()
    runner = TestRunner(WorkspaceGuard(root))

    passed = runner.run(
        FileCheck(
            check_id="artifact",
            path="artifact.txt",
            min_size_bytes=8,
            expected_sha256=digest,
        )
    )
    wrong_hash = runner.run(
        FileCheck(
            check_id="artifact-wrong",
            path="artifact.txt",
            expected_sha256="0" * 64,
        )
    )
    optional = runner.run(
        FileCheck(
            check_id="optional",
            path="not-created.txt",
            must_exist=False,
        )
    )

    assert passed.outcome == ValidationOutcome.PASS
    assert passed.details["path"] == "artifact.txt"
    assert wrong_hash.outcome == ValidationOutcome.FAIL
    assert optional.outcome == ValidationOutcome.PASS


def test_file_check_rejects_incoherent_directory_assertions():
    with pytest.raises(ValueError, match="directory checks"):
        FileCheck(
            check_id="invalid",
            path="docs",
            expect_directory=True,
            min_size_bytes=1,
        )


def test_json_check_validates_shape_keys_values_and_parse_errors(tmp_path):
    root = make_root(tmp_path)
    (root / "valid.json").write_text(
        '{"status":"ready","items":3}',
        encoding="utf-8",
    )
    (root / "invalid.json").write_text("{broken", encoding="utf-8")
    runner = TestRunner(WorkspaceGuard(root))

    passed = runner.run(
        JsonCheck(
            check_id="json-pass",
            path="valid.json",
            required_keys=("status", "items"),
            expected_values={"status": "ready"},
        )
    )
    failed = runner.run(
        JsonCheck(
            check_id="json-fail",
            path="valid.json",
            expected_values={"status": "blocked"},
        )
    )
    invalid = runner.run(
        JsonCheck(check_id="json-invalid", path="invalid.json")
    )

    assert passed.outcome == ValidationOutcome.PASS
    assert failed.outcome == ValidationOutcome.FAIL
    assert invalid.outcome == ValidationOutcome.FAIL
    assert invalid.details["path"] == "invalid.json"


def test_command_check_normalizes_failure_and_timeout(tmp_path):
    root = make_root(tmp_path)
    guard, command_runner = make_command_runner(root, max_timeout=2)
    runner = TestRunner(guard, command_runner=command_runner)

    failed = runner.run(
        CommandCheck(
            check_id="exit-seven",
                request=CommandRequest(
                    argv=("python", "-c", "raise SystemExit(7)"),
                    timeout_seconds=1,
                ),
        )
    )
    timed_out = runner.run(
        CommandCheck(
            check_id="timeout",
            request=CommandRequest(
                argv=("python", "-c", "import time; time.sleep(5)"),
                timeout_seconds=0.1,
            ),
        )
    )

    assert failed.outcome == ValidationOutcome.FAIL
    assert failed.details["exit_code"] == 7
    assert "stdout_tail" in failed.details
    assert "stderr_tail" in failed.details
    assert timed_out.outcome == ValidationOutcome.TIMEOUT


def test_command_check_without_executor_returns_normalized_error(tmp_path):
    root = make_root(tmp_path)

    result = TestRunner(WorkspaceGuard(root)).run(
        CommandCheck(
            check_id="no-executor",
            request=CommandRequest(argv=("python", "--version")),
        )
    )

    assert result.outcome == ValidationOutcome.ERROR
    assert result.summary == "no command runner is configured"


def test_pytest_check_runs_through_the_guarded_command_runner(tmp_path):
    root = make_root(tmp_path)
    (root / "test_sample.py").write_text(
        "def test_sample():\n    assert 2 + 2 == 4\n",
        encoding="utf-8",
    )
    guard, command_runner = make_command_runner(root)
    environment = {}
    if os.environ.get("PYTHONPATH"):
        environment["PYTHONPATH"] = os.environ["PYTHONPATH"]
    runner = TestRunner(guard, command_runner=command_runner)

    result = runner.run(
        PytestCheck(
            check_id="pytest",
            arguments=("-q", "test_sample.py", "-p", "no:cacheprovider"),
            environment=environment,
        )
    )

    assert result.outcome == ValidationOutcome.PASS
    assert "1 passed" in result.details["stdout_preview"]


def test_validation_store_replays_result_and_detects_spec_conflict(tmp_path):
    root = make_root(tmp_path)
    artifact = root / "artifact.txt"
    artifact.write_text("first", encoding="utf-8")
    ledger = Ledger(root / "ledger.db", project_root=root)
    runner = TestRunner(WorkspaceGuard(root), store=ledger)
    check = FileCheck(
        check_id="artifact",
        path="artifact.txt",
        expected_sha256=hashlib.sha256(b"first").hexdigest(),
        idempotency_key="artifact-validation:v1",
    )

    first = runner.run(check)
    artifact.write_text("changed", encoding="utf-8")
    replayed = runner.run(check)

    assert first.outcome == ValidationOutcome.PASS
    assert replayed.outcome == ValidationOutcome.PASS
    assert replayed.replayed is True
    assert first.validation_id == replayed.validation_id

    with pytest.raises(ValidationIdempotencyConflict):
        runner.run(
            FileCheck(
                check_id="artifact",
                path="artifact.txt",
                expected_sha256=hashlib.sha256(b"changed").hexdigest(),
                idempotency_key="artifact-validation:v1",
            )
        )


def test_durable_command_and_validation_records_are_linked(tmp_path):
    root = make_root(tmp_path)
    guard, command_runner = make_command_runner(root)
    ledger = Ledger(root / "ledger.db", project_root=root)
    durable = IdempotentCommandRunner(command_runner, ledger)
    runner = TestRunner(guard, command_runner=durable, store=ledger)
    code = "from pathlib import Path; Path('evidence.txt').write_text('created')"
    check = CommandCheck(
        check_id="create-evidence",
        idempotency_key="validation:create-evidence:v1",
        request=CommandRequest(argv=("python", "-c", code)),
    )

    first = runner.run(check)
    replayed = runner.run(check)

    assert first.outcome == ValidationOutcome.PASS
    assert first.command_id is not None
    assert replayed.replayed is True
    assert replayed.command_id == first.command_id
    assert (root / "evidence.txt").read_text(encoding="utf-8") == "created"
    stored = ledger.get_validation("validation:create-evidence:v1")
    assert stored["command_id"] == first.command_id
    command = ledger.get_command("validation:create-evidence:v1:command")
    assert command["status"] == "completed"


def test_suite_aggregation_can_stop_after_first_failure(tmp_path):
    root = make_root(tmp_path)
    (root / "present.txt").write_text("present", encoding="utf-8")
    runner = TestRunner(WorkspaceGuard(root))

    suite = runner.run_suite(
        (
            FileCheck(check_id="pass", path="present.txt"),
            FileCheck(check_id="fail", path="missing.txt"),
            FileCheck(check_id="not-run", path="present.txt"),
        ),
        stop_on_failure=True,
    )
    empty = runner.run_suite(())

    assert suite.outcome == ValidationOutcome.FAIL
    assert len(suite.results) == 2
    assert empty.outcome == ValidationOutcome.NOT_APPLICABLE
