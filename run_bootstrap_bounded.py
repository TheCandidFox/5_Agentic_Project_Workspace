from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Mapping, Sequence

from ledger import Ledger
from repair_loop import RepairPolicy
from run_bootstrap_transactional import (
    TransactionalBootstrapReport,
    run_bootstrap_transactional,
)


REQUIRED_REPAIR_TABLES = frozenset({"repair_runs", "repair_attempts"})


@dataclass(frozen=True)
class BoundedBootstrapReport:
    transactional: TransactionalBootstrapReport
    integrity: str
    migrations: tuple[str, ...]
    newly_applied_migrations: tuple[str, ...]
    repair_tables_ready: bool
    safeguards_ready: bool
    status_only: bool

    @property
    def passed(self) -> bool:
        return (
            self.transactional.passed
            and self.integrity == "ok"
            and "0003_bounded_autonomy" in self.migrations
            and self.repair_tables_ready
            and self.safeguards_ready
        )


def run_bootstrap_bounded(
    *,
    project_root: str | Path,
    ledger_path: str | Path,
    status_only: bool = False,
    git_executable: str | Path | None = None,
    python_executable: str | Path | None = None,
    pytest_environment: Mapping[str, str] | None = None,
) -> BoundedBootstrapReport:
    transactional = run_bootstrap_transactional(
        project_root=project_root,
        ledger_path=ledger_path,
        status_only=status_only,
        git_executable=git_executable,
        python_executable=python_executable,
        pytest_environment=pytest_environment,
    )
    ledger = Ledger(ledger_path, project_root=project_root)
    with ledger.connect() as con:
        tables = {
            str(row["name"])
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        run_columns = {
            str(row["name"])
            for row in con.execute("PRAGMA table_info(repair_runs)").fetchall()
        }
        attempt_columns = {
            str(row["name"])
            for row in con.execute("PRAGMA table_info(repair_attempts)").fetchall()
        }
    tables_ready = REQUIRED_REPAIR_TABLES.issubset(tables)
    safeguards_ready = (
        {
            "deadline_at",
            "attempt_count",
            "cost_usd",
            "identical_failure_count",
            "no_progress_count",
            "stop_reason",
        }.issubset(run_columns)
        and {
            "proposal_sha256",
            "patch_id",
            "validation_after_sha256",
            "checkpoint_id",
        }.issubset(attempt_columns)
        and RepairPolicy().max_attempts > 0
    )
    return BoundedBootstrapReport(
        transactional=transactional,
        integrity=ledger.integrity_check(),
        migrations=ledger.schema_migration_ids(),
        newly_applied_migrations=transactional.newly_applied_migrations,
        repair_tables_ready=tables_ready,
        safeguards_ready=safeguards_ready,
        status_only=status_only,
    )


def print_report(report: BoundedBootstrapReport) -> None:
    mode = "status" if report.status_only else "verification"
    print(f"Bounded autonomy bootstrap offline {mode} (no provider calls)")
    print(
        f"[{'PASS' if report.integrity == 'ok' else 'FAIL'}] "
        f"SQLite integrity: {report.integrity}"
    )
    print(
        f"[{'PASS' if report.transactional.passed else 'FAIL'}] "
        "transactional validation/patch/checkpoint foundation"
    )
    migrations = ", ".join(report.migrations) or "none"
    newly = ", ".join(report.newly_applied_migrations) or "none"
    migration_ok = "0003_bounded_autonomy" in report.migrations
    print(
        f"[{'PASS' if migration_ok else 'FAIL'}] "
        f"schema migrations: {migrations}; newly_applied={newly}"
    )
    print(
        f"[{'PASS' if report.repair_tables_ready else 'FAIL'}] "
        "repair tables: repair_runs, repair_attempts"
    )
    print(
        f"[{'PASS' if report.safeguards_ready else 'FAIL'}] "
        "hard bounds: attempts, cost, time, repeated failure/patch, no progress"
    )
    git_status = report.transactional.git_status
    print(
        f"[{'PASS' if not git_status.conflicts else 'FAIL'}] "
        f"Git repository: branch={git_status.branch or 'detached'}; "
        f"head={(git_status.head or 'none')[:12]}; "
        f"changed_paths={len(git_status.changes)}; "
        f"conflicts={len(git_status.conflicts)}"
    )
    label = "status" if report.status_only else "result"
    print(f"Bounded autonomy {label}: {'PASS' if report.passed else 'FAIL'}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the offline bounded-autonomy bootstrap."
    )
    parser.add_argument("--status-only", action="store_true")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).parent)
    parser.add_argument("--ledger", type=Path, default=Path("ledger.db"))
    parser.add_argument("--git-executable", type=Path)
    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    ledger_path = args.ledger
    if not ledger_path.is_absolute():
        ledger_path = root / ledger_path
    environment = {}
    if os.environ.get("PYTHONPATH"):
        environment["PYTHONPATH"] = os.environ["PYTHONPATH"]
    try:
        report = run_bootstrap_bounded(
            project_root=root,
            ledger_path=ledger_path,
            status_only=args.status_only,
            git_executable=args.git_executable,
            python_executable=sys.executable,
            pytest_environment=environment,
        )
        print_report(report)
        return 0 if report.passed else 1
    except Exception as exc:
        safe = f"{type(exc).__name__}: {exc}".replace(str(root), "<workspace>")
        print("Bounded autonomy bootstrap offline verification (no provider calls)")
        print(f"[FAIL] {safe[:4_000]}")
        print("Bounded autonomy result: FAIL")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

