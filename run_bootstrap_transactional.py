from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from git_checkpoint import GitCheckpointManager, RepositoryStatus
from ledger import Ledger
from run_bootstrap_phase2 import BootstrapPhase2Report, run_bootstrap_phase2
from workspace_guard import WorkspaceGuard


TRANSACTION_TABLES = frozenset(
    {"patch_transactions", "patch_files", "git_checkpoints"}
)


@dataclass(frozen=True)
class TransactionalBootstrapReport:
    integrity: str
    migration_ids: tuple[str, ...]
    newly_applied_migrations: tuple[str, ...]
    transaction_tables_ready: bool
    git_status: RepositoryStatus
    phase2: BootstrapPhase2Report | None

    @property
    def passed(self) -> bool:
        return (
            self.integrity == "ok"
            and self.transaction_tables_ready
            and not self.git_status.conflicts
            and (self.phase2 is None or self.phase2.passed)
        )


def run_bootstrap_transactional(
    *,
    project_root: str | Path,
    ledger_path: str | Path,
    status_only: bool = False,
    rerun: bool = False,
    python_executable: str | Path | None = None,
    pytest_environment: Mapping[str, str] | None = None,
    git_executable: str | Path | None = None,
) -> TransactionalBootstrapReport:
    guard = WorkspaceGuard(project_root)
    ledger = Ledger(ledger_path, project_root=guard.root)
    integrity = ledger.integrity_check()
    with ledger.connect() as con:
        tables = {
            str(row["name"])
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    tables_ready = TRANSACTION_TABLES <= tables
    effective_git = git_executable or shutil.which("git")
    if effective_git is None:
        raise FileNotFoundError("Git executable was not found")
    git_manager = GitCheckpointManager(
        guard,
        ledger,
        git_executable=effective_git,
    )
    git_status = git_manager.status()
    phase2 = None
    if not status_only and integrity == "ok" and tables_ready:
        environment = dict(pytest_environment or {})
        environment["AI_LOOP_GIT_EXECUTABLE"] = str(effective_git)
        phase2 = run_bootstrap_phase2(
            project_root=guard.root,
            ledger_path=ledger_path,
            rerun=rerun,
            python_executable=python_executable,
            pytest_environment=environment,
        )
    return TransactionalBootstrapReport(
        integrity=integrity,
        migration_ids=ledger.schema_migration_ids(),
        newly_applied_migrations=ledger.applied_schema_migrations,
        transaction_tables_ready=tables_ready,
        git_status=git_status,
        phase2=phase2,
    )


def print_report(report: TransactionalBootstrapReport) -> None:
    print("Transactional bootstrap offline verification (no provider calls)")
    print(
        f"[{'PASS' if report.integrity == 'ok' else 'FAIL'}] "
        f"SQLite integrity: {report.integrity}"
    )
    migrations = ", ".join(report.migration_ids) or "none"
    applied = ", ".join(report.newly_applied_migrations) or "none"
    print(f"[PASS] schema migrations: {migrations}; newly_applied={applied}")
    print(
        f"[{'PASS' if report.transaction_tables_ready else 'FAIL'}] "
        "transaction tables: patch_transactions, patch_files, git_checkpoints"
    )
    status = report.git_status
    head = status.head[:12] if status.head else "unborn"
    branch = status.branch or "detached"
    print(
        f"[{'PASS' if not status.conflicts else 'FAIL'}] Git repository: "
        f"branch={branch}; head={head}; changed_paths={len(status.changes)}; "
        f"conflicts={len(status.conflicts)}"
    )
    if status.changes:
        print("[WARN] worktree changes are expected before the update is committed")
    if report.phase2 is not None and report.phase2.suite is not None:
        for result in report.phase2.suite.results:
            replayed = "; replayed" if result.replayed else ""
            print(
                f"[{result.outcome.value}] {result.check_id}: "
                f"{result.summary}{replayed}"
            )
    label = "Transactional result" if report.phase2 is not None else "Transactional status"
    print(f"{label}:", "PASS" if report.passed else "FAIL")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the offline transactional patch/checkpoint bootstrap."
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="check migrations, SQLite integrity, and Git state without pytest",
    )
    parser.add_argument(
        "--rerun",
        action="store_true",
        help="force new Phase 2 validation evidence for unchanged Python source",
    )
    args = parser.parse_args(argv)

    from config import SETTINGS

    try:
        report = run_bootstrap_transactional(
            project_root=SETTINGS.project_root,
            ledger_path=SETTINGS.ledger_path,
            status_only=args.status_only,
            rerun=args.rerun,
            git_executable=shutil.which("git"),
            python_executable=sys.executable,
        )
    except Exception as exc:
        print(f"Transactional bootstrap ERROR: {type(exc).__name__}: {exc}")
        return 2
    print_report(report)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
