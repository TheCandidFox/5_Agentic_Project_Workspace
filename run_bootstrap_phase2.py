from __future__ import annotations

import argparse
import hashlib
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from command_runner import CommandPolicy, CommandRunner, ExecutableRule
from durable_execution import IdempotentCommandRunner
from ledger import Ledger
from test_runner import (
    PytestCheck,
    PythonSyntaxCheck,
    TestRunner,
    ValidationOutcome,
    ValidationSuiteResult,
    discover_python_files,
)
from workspace_guard import WorkspaceGuard


@dataclass(frozen=True)
class BootstrapPhase2Report:
    integrity: str
    migration_ids: tuple[str, ...]
    newly_applied_migrations: tuple[str, ...]
    source_snapshot_sha256: str | None
    suite: ValidationSuiteResult | None

    @property
    def passed(self) -> bool:
        if self.integrity != "ok":
            return False
        return self.suite is None or self.suite.outcome == ValidationOutcome.PASS


def source_snapshot_sha256(guard: WorkspaceGuard) -> str:
    """Hash authorized Python source names and contents, excluding runtime state."""

    digest = hashlib.sha256()
    files = discover_python_files(guard)
    for relative_path, path in sorted(files.items()):
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\x00")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\x00")
    return digest.hexdigest()


def run_bootstrap_phase2(
    *,
    project_root: str | Path,
    ledger_path: str | Path,
    status_only: bool = False,
    rerun: bool = False,
    python_executable: str | Path | None = None,
    pytest_arguments: Sequence[str] = (
        "-q",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        ".pytest_tmp",
    ),
    pytest_environment: Mapping[str, str] | None = None,
) -> BootstrapPhase2Report:
    guard = WorkspaceGuard(project_root)
    ledger = Ledger(ledger_path, project_root=guard.root)
    integrity = ledger.integrity_check()
    if status_only or integrity != "ok":
        return BootstrapPhase2Report(
            integrity=integrity,
            migration_ids=ledger.schema_migration_ids(),
            newly_applied_migrations=ledger.applied_schema_migrations,
            source_snapshot_sha256=None,
            suite=None,
        )

    environment = dict(pytest_environment or {})
    executable = Path(python_executable or sys.executable)
    runtime_temp = guard.authorize_write(".pytest_tmp", expect_directory=True)
    runtime_temp.path.mkdir(parents=True, exist_ok=True)
    policy = CommandPolicy(
        rules=(
            ExecutableRule(
                alias="python",
                executable=executable,
                allowed_argument_prefixes=(("-m", "pytest"),),
            ),
        ),
        allowed_environment_keys=frozenset(environment),
        max_timeout_seconds=600,
        max_output_bytes=1_000_000,
    )
    command_runner = CommandRunner(guard, policy)
    durable_runner = IdempotentCommandRunner(command_runner, ledger)
    test_runner = TestRunner(
        guard,
        command_runner=durable_runner,
        store=ledger,
    )
    snapshot = source_snapshot_sha256(guard)
    run_identity = str(uuid.uuid4()) if rerun else snapshot
    suite = test_runner.run_suite(
        (
            PythonSyntaxCheck(
                check_id="phase2-python-syntax",
                paths=(".",),
                action_id="bootstrap-phase2-syntax",
                idempotency_key=f"bootstrap:phase2:syntax:{run_identity}",
            ),
            PytestCheck(
                check_id="phase2-pytest",
                arguments=tuple(pytest_arguments),
                timeout_seconds=600,
                max_output_bytes=1_000_000,
                environment=environment,
                action_id="bootstrap-phase2-pytest",
                idempotency_key=f"bootstrap:phase2:pytest:{run_identity}",
            ),
        ),
        stop_on_failure=True,
    )
    return BootstrapPhase2Report(
        integrity=integrity,
        migration_ids=ledger.schema_migration_ids(),
        newly_applied_migrations=ledger.applied_schema_migrations,
        source_snapshot_sha256=snapshot,
        suite=suite,
    )


def print_report(report: BootstrapPhase2Report) -> None:
    print("Bootstrap Phase 2 offline verification (no provider calls)")
    print(
        f"[{'PASS' if report.integrity == 'ok' else 'FAIL'}] "
        f"SQLite integrity: {report.integrity}"
    )
    migrations = ", ".join(report.migration_ids) or "none"
    newly_applied = ", ".join(report.newly_applied_migrations) or "none"
    print(f"[PASS] schema migrations: {migrations}; newly_applied={newly_applied}")
    if report.suite is not None:
        for result in report.suite.results:
            replayed = "; replayed" if result.replayed else ""
            print(
                f"[{result.outcome.value}] {result.check_id}: "
                f"{result.summary}{replayed}"
            )
            if result.outcome not in {
                ValidationOutcome.PASS,
                ValidationOutcome.NOT_APPLICABLE,
            }:
                failure_tail = (
                    result.details.get("stderr_tail")
                    or result.details.get("stdout_tail")
                )
                if failure_tail:
                    print("  Last captured output:")
                    for line in str(failure_tail).splitlines()[-12:]:
                        print(f"    {line}")
        print("Phase 2 result:", "PASS" if report.passed else "FAIL")
    else:
        print("Phase 2 status:", "PASS" if report.passed else "FAIL")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the offline v0.3 Bootstrap Phase 2 validation layer."
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="check ledger integrity and migration status without running tests",
    )
    parser.add_argument(
        "--rerun",
        action="store_true",
        help="force a new validation record even when source files are unchanged",
    )
    args = parser.parse_args(argv)

    from config import SETTINGS

    try:
        report = run_bootstrap_phase2(
            project_root=SETTINGS.project_root,
            ledger_path=SETTINGS.ledger_path,
            status_only=args.status_only,
            rerun=args.rerun,
        )
    except Exception as exc:
        print(f"Bootstrap Phase 2 ERROR: {type(exc).__name__}: {exc}")
        return 2
    print_report(report)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
