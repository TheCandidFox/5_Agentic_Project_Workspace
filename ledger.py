from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from project_paths import portable_project_path, resolve_project_path
from task_contract import TaskContract


SCHEMA_MIGRATIONS: tuple[tuple[str, str], ...] = (
    (
        "0001_bootstrap_commands_validations",
        """
        CREATE TABLE IF NOT EXISTS commands (
            command_id TEXT PRIMARY KEY,
            task_id TEXT,
            action_id TEXT,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_sha256 TEXT NOT NULL,
            request_json TEXT NOT NULL,
            executable_alias TEXT NOT NULL,
            cwd TEXT NOT NULL,
            status TEXT NOT NULL,
            outcome TEXT,
            exit_code INTEGER,
            stdout TEXT,
            stderr TEXT,
            stdout_sha256 TEXT,
            stderr_sha256 TEXT,
            stdout_truncated INTEGER NOT NULL DEFAULT 0,
            stderr_truncated INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_commands_task_created
        ON commands(task_id, created_at);

        CREATE TABLE IF NOT EXISTS validation_runs (
            validation_id TEXT PRIMARY KEY,
            task_id TEXT,
            action_id TEXT,
            command_id TEXT,
            check_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            idempotency_key TEXT UNIQUE,
            spec_sha256 TEXT NOT NULL,
            outcome TEXT NOT NULL,
            summary TEXT NOT NULL,
            details_json TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(command_id) REFERENCES commands(command_id)
        );

        CREATE INDEX IF NOT EXISTS idx_validation_runs_task_created
        ON validation_runs(task_id, created_at);
        """,
    ),
    (
        "0002_transactional_changes",
        """
        CREATE TABLE IF NOT EXISTS patch_transactions (
            patch_id TEXT PRIMARY KEY,
            task_id TEXT,
            actor TEXT NOT NULL,
            reason TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_sha256 TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT,
            created_at TEXT NOT NULL,
            applied_at TEXT,
            rolled_back_at TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS patch_files (
            patch_id TEXT NOT NULL,
            path TEXT NOT NULL,
            operation TEXT NOT NULL,
            pre_sha256 TEXT,
            post_sha256 TEXT NOT NULL,
            backup_blob BLOB,
            pre_mode INTEGER,
            size_before INTEGER,
            size_after INTEGER NOT NULL,
            PRIMARY KEY(patch_id, path),
            FOREIGN KEY(patch_id) REFERENCES patch_transactions(patch_id)
        );

        CREATE INDEX IF NOT EXISTS idx_patch_transactions_task_created
        ON patch_transactions(task_id, created_at);

        CREATE TABLE IF NOT EXISTS git_checkpoints (
            checkpoint_id TEXT PRIMARY KEY,
            patch_id TEXT,
            task_id TEXT,
            actor TEXT NOT NULL,
            reason TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_sha256 TEXT NOT NULL,
            status TEXT NOT NULL,
            base_commit TEXT,
            commit_hash TEXT,
            revert_commit_hash TEXT,
            paths_json TEXT NOT NULL,
            diff_sha256 TEXT NOT NULL,
            error TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            reverted_at TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(patch_id) REFERENCES patch_transactions(patch_id)
        );

        CREATE INDEX IF NOT EXISTS idx_git_checkpoints_task_created
        ON git_checkpoints(task_id, created_at);
        """,
    ),
    (
        "0003_bounded_autonomy",
        """
        CREATE TABLE IF NOT EXISTS repair_runs (
            run_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            actor TEXT NOT NULL,
            objective TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_sha256 TEXT NOT NULL,
            policy_json TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL NOT NULL DEFAULT 0,
            initial_failure_sha256 TEXT,
            last_failure_sha256 TEXT,
            identical_failure_count INTEGER NOT NULL DEFAULT 0,
            no_progress_count INTEGER NOT NULL DEFAULT 0,
            failure_context_json TEXT,
            stop_reason TEXT,
            checkpoint_id TEXT,
            error TEXT,
            started_at TEXT NOT NULL,
            deadline_at TEXT NOT NULL,
            completed_at TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(checkpoint_id) REFERENCES git_checkpoints(checkpoint_id)
        );

        CREATE INDEX IF NOT EXISTS idx_repair_runs_task_created
        ON repair_runs(task_id, started_at);

        CREATE TABLE IF NOT EXISTS repair_attempts (
            attempt_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            agent_label TEXT NOT NULL,
            status TEXT NOT NULL,
            failure_before_sha256 TEXT NOT NULL,
            estimated_cost_usd REAL NOT NULL,
            actual_cost_usd REAL,
            proposal_sha256 TEXT,
            proposal_json TEXT,
            hypothesis TEXT,
            patch_id TEXT,
            validation_after_sha256 TEXT,
            validation_outcome TEXT,
            checkpoint_id TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(run_id, attempt_number),
            FOREIGN KEY(run_id) REFERENCES repair_runs(run_id),
            FOREIGN KEY(patch_id) REFERENCES patch_transactions(patch_id),
            FOREIGN KEY(checkpoint_id) REFERENCES git_checkpoints(checkpoint_id)
        );

        CREATE INDEX IF NOT EXISTS idx_repair_attempts_run_number
        ON repair_attempts(run_id, attempt_number);
        """,
    ),
    (
        "0004_research_provenance",
        """
        CREATE TABLE IF NOT EXISTS research_runs (
            run_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            objective TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_sha256 TEXT NOT NULL,
            status TEXT NOT NULL,
            retrieval_mode TEXT NOT NULL,
            require_primary_source INTEGER NOT NULL,
            source_count INTEGER NOT NULL DEFAULT 0,
            claim_count INTEGER NOT NULL DEFAULT 0,
            request_count INTEGER NOT NULL DEFAULT 0,
            bytes_retrieved INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL NOT NULL DEFAULT 0,
            error TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_research_runs_task_started
        ON research_runs(task_id, started_at);

        CREATE TABLE IF NOT EXISTS research_sources (
            source_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            source_key TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            requested_url TEXT NOT NULL,
            canonical_url TEXT NOT NULL,
            title TEXT NOT NULL,
            source_type TEXT NOT NULL,
            is_primary INTEGER NOT NULL,
            capture_method TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            applicable_version TEXT,
            applicable_date TEXT,
            content_type TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            content_sha256 TEXT NOT NULL,
            content_text TEXT NOT NULL,
            content_bytes INTEGER NOT NULL,
            duration_ms INTEGER NOT NULL,
            UNIQUE(run_id, source_key),
            UNIQUE(run_id, ordinal),
            FOREIGN KEY(run_id) REFERENCES research_runs(run_id)
        );

        CREATE INDEX IF NOT EXISTS idx_research_sources_run_ordinal
        ON research_sources(run_id, ordinal);

        CREATE TABLE IF NOT EXISTS research_claims (
            claim_record_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            claim_key TEXT NOT NULL,
            statement TEXT NOT NULL,
            claim_type TEXT NOT NULL,
            rationale TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(run_id, claim_key),
            FOREIGN KEY(run_id) REFERENCES research_runs(run_id)
        );

        CREATE INDEX IF NOT EXISTS idx_research_claims_run
        ON research_claims(run_id);

        CREATE TABLE IF NOT EXISTS research_citations (
            claim_record_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            excerpt TEXT NOT NULL,
            excerpt_sha256 TEXT NOT NULL,
            PRIMARY KEY(claim_record_id, source_id, excerpt_sha256),
            FOREIGN KEY(claim_record_id)
                REFERENCES research_claims(claim_record_id),
            FOREIGN KEY(source_id) REFERENCES research_sources(source_id)
        );

        CREATE INDEX IF NOT EXISTS idx_research_citations_source
        ON research_citations(source_id);
        """,
    ),
    (
        "0005_acceptance_truth",
        """
        CREATE TABLE IF NOT EXISTS acceptance_runs (
            evaluation_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            objective TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_sha256 TEXT NOT NULL,
            status TEXT NOT NULL,
            outcome TEXT,
            summary TEXT,
            error TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_acceptance_runs_task_started
        ON acceptance_runs(task_id, started_at);

        CREATE TABLE IF NOT EXISTS acceptance_evidence (
            evidence_record_id TEXT PRIMARY KEY,
            evaluation_id TEXT NOT NULL,
            evidence_key TEXT NOT NULL,
            kind TEXT NOT NULL,
            disposition TEXT NOT NULL,
            summary TEXT NOT NULL,
            reference TEXT NOT NULL,
            observed_at TEXT,
            UNIQUE(evaluation_id, evidence_key),
            FOREIGN KEY(evaluation_id) REFERENCES acceptance_runs(evaluation_id)
        );

        CREATE INDEX IF NOT EXISTS idx_acceptance_evidence_evaluation
        ON acceptance_evidence(evaluation_id);

        CREATE TABLE IF NOT EXISTS acceptance_claims (
            claim_record_id TEXT PRIMARY KEY,
            evaluation_id TEXT NOT NULL,
            claim_key TEXT NOT NULL,
            statement TEXT NOT NULL,
            truth_label TEXT NOT NULL,
            rationale TEXT,
            evidence_keys_json TEXT NOT NULL,
            UNIQUE(evaluation_id, claim_key),
            FOREIGN KEY(evaluation_id) REFERENCES acceptance_runs(evaluation_id)
        );

        CREATE INDEX IF NOT EXISTS idx_acceptance_claims_evaluation
        ON acceptance_claims(evaluation_id);

        CREATE TABLE IF NOT EXISTS acceptance_criteria (
            criterion_record_id TEXT PRIMARY KEY,
            evaluation_id TEXT NOT NULL,
            criterion_key TEXT NOT NULL,
            description TEXT NOT NULL,
            required INTEGER NOT NULL,
            verdict TEXT NOT NULL,
            unresolved_action TEXT NOT NULL,
            evidence_keys_json TEXT NOT NULL,
            UNIQUE(evaluation_id, criterion_key),
            FOREIGN KEY(evaluation_id) REFERENCES acceptance_runs(evaluation_id)
        );

        CREATE INDEX IF NOT EXISTS idx_acceptance_criteria_evaluation
        ON acceptance_criteria(evaluation_id);

        CREATE TABLE IF NOT EXISTS acceptance_constraints (
            constraint_record_id TEXT PRIMARY KEY,
            evaluation_id TEXT NOT NULL,
            constraint_key TEXT NOT NULL,
            description TEXT NOT NULL,
            violated INTEGER NOT NULL,
            evidence_keys_json TEXT NOT NULL,
            UNIQUE(evaluation_id, constraint_key),
            FOREIGN KEY(evaluation_id) REFERENCES acceptance_runs(evaluation_id)
        );

        CREATE INDEX IF NOT EXISTS idx_acceptance_constraints_evaluation
        ON acceptance_constraints(evaluation_id);
        """,
    ),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_safe_text(name: str, value: Any, *, maximum: int = 1_000) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be a non-empty safe string")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    return value


def _require_sha256(name: str, value: Any) -> str:
    digest = _require_safe_text(name, value, maximum=64).casefold()
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return digest


def _require_git_hash(name: str, value: Any) -> str:
    digest = _require_safe_text(name, value, maximum=64).casefold()
    if len(digest) not in {40, 64} or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"{name} must be a Git object hash")
    return digest


def _require_portable_path(name: str, value: Any) -> str:
    path = _require_safe_text(name, value, maximum=1_000).replace("\\", "/")
    parsed = Path(path)
    if parsed.is_absolute() or ":" in path or ".." in parsed.parts:
        raise ValueError(f"{name} must be project-relative")
    normalized = parsed.as_posix()
    if normalized in {"", "."}:
        raise ValueError(f"{name} must identify a project file")
    return normalized


class Ledger:
    def __init__(self, path: str | Path, project_root: str | Path | None = None):
        self.path = Path(path)
        self.project_root = Path(project_root or self.path.parent).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.applied_schema_migrations = self._apply_schema_migrations()
        self.migrated_artifact_paths = self._migrate_artifact_paths()

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=30.0)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA busy_timeout=30000")
            for attempt in range(20):
                try:
                    con.execute("PRAGMA journal_mode=WAL")
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).casefold() or attempt == 19:
                        raise
                    time.sleep(0.05)
            con.execute("PRAGMA foreign_keys=ON")
            yield con
            con.commit()
        finally:
            con.close()

    def _init_db(self) -> None:
        with self.connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    contract_version INTEGER NOT NULL,
                    goal_version INTEGER NOT NULL,
                    objective TEXT NOT NULL,
                    scope_boundaries TEXT NOT NULL,
                    acceptance_criteria TEXT NOT NULL,
                    importance_band INTEGER NOT NULL,
                    effect_class_ceiling TEXT NOT NULL,
                    data_classification TEXT NOT NULL,
                    budget_ceiling_usd REAL NOT NULL,
                    approval_state TEXT NOT NULL,
                    evidence_required INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    current_stage TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS steps (
                    step_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    provider TEXT,
                    model TEXT,
                    status TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    prompt_hash TEXT,
                    artifact_path TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    error TEXT,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id)
                );

                CREATE TABLE IF NOT EXISTS telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    step_id TEXT,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    estimated_cost_usd REAL NOT NULL,
                    latency_ms INTEGER,
                    stop_reason TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS budget_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    step_id TEXT,
                    reserved_usd REAL NOT NULL,
                    actual_usd REAL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    settled_at TEXT
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def _apply_schema_migrations(self) -> tuple[str, ...]:
        """Apply additive, checksummed migrations exactly once."""

        applied_now: list[str] = []
        with self.connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    migration_id TEXT PRIMARY KEY,
                    checksum_sha256 TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
            con.execute("BEGIN IMMEDIATE")
            for migration_id, sql in SCHEMA_MIGRATIONS:
                checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
                existing = con.execute(
                    """
                    SELECT checksum_sha256 FROM schema_migrations
                    WHERE migration_id=?
                    """,
                    (migration_id,),
                ).fetchone()
                if existing is not None:
                    if existing["checksum_sha256"] != checksum:
                        raise RuntimeError(
                            f"schema migration checksum mismatch: {migration_id}"
                        )
                    continue
                for statement in sql.split(";"):
                    if statement.strip():
                        con.execute(statement)
                con.execute(
                    """
                    INSERT INTO schema_migrations(
                        migration_id, checksum_sha256, applied_at
                    ) VALUES(?,?,?)
                    """,
                    (migration_id, checksum, utc_now()),
                )
                applied_now.append(migration_id)
        return tuple(applied_now)

    def schema_migration_ids(self) -> tuple[str, ...]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT migration_id FROM schema_migrations
                ORDER BY migration_id
                """
            ).fetchall()
        return tuple(str(row["migration_id"]) for row in rows)

    def _migrate_artifact_paths(self) -> int:
        """Make legacy artifact paths portable without discarding task history."""

        migrated = 0
        with self.connect() as con:
            rows = con.execute(
                "SELECT step_id, artifact_path FROM steps WHERE artifact_path IS NOT NULL"
            ).fetchall()
            for row in rows:
                old_path = row["artifact_path"]
                try:
                    new_path = portable_project_path(
                        old_path,
                        self.project_root,
                        legacy_anchor="outputs",
                    )
                except ValueError:
                    continue
                if new_path == old_path:
                    continue
                con.execute(
                    "UPDATE steps SET artifact_path=? WHERE step_id=?",
                    (new_path, row["step_id"]),
                )
                migrated += 1

            if migrated:
                con.execute(
                    """
                    INSERT INTO events(task_id,event_type,payload_json,created_at)
                    VALUES(NULL,?,?,?)
                    """,
                    (
                        "artifact_paths_migrated",
                        json.dumps({"count": migrated, "format": "project-relative-posix"}),
                        utc_now(),
                    ),
                )
        return migrated

    def upsert_task(self, contract: TaskContract) -> None:
        r = contract.to_record()
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO tasks (
                    task_id, contract_version, goal_version, objective,
                    scope_boundaries, acceptance_criteria, importance_band,
                    effect_class_ceiling, data_classification, budget_ceiling_usd,
                    approval_state, evidence_required, status, current_stage,
                    created_at, updated_at
                ) VALUES (
                    :task_id, :contract_version, :goal_version, :objective,
                    :scope_boundaries, :acceptance_criteria, :importance_band,
                    :effect_class_ceiling, :data_classification, :budget_ceiling_usd,
                    :approval_state, :evidence_required, 'pending', NULL,
                    :created_at, :created_at
                )
                ON CONFLICT(task_id) DO UPDATE SET
                    objective=excluded.objective,
                    acceptance_criteria=excluded.acceptance_criteria,
                    updated_at=excluded.created_at
                """,
                r,
            )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        return dict(row) if row else None

    def set_task_state(self, task_id: str, status: str, stage: str | None = None) -> None:
        with self.connect() as con:
            con.execute(
                "UPDATE tasks SET status=?, current_stage=?, updated_at=? WHERE task_id=?",
                (status, stage, utc_now(), task_id),
            )

    def start_step(
        self,
        *,
        step_id: str,
        task_id: str,
        stage: str,
        provider: str,
        model: str,
        idempotency_key: str,
        prompt_hash: str,
    ) -> bool:
        """
        Returns False if the idempotency key already belongs to a completed step.
        """
        with self.connect() as con:
            existing = con.execute(
                "SELECT status FROM steps WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing and existing["status"] == "completed":
                return False
            con.execute(
                """
                INSERT INTO steps (
                    step_id, task_id, stage, provider, model, status,
                    idempotency_key, prompt_hash, started_at
                ) VALUES (?, ?, ?, ?, ?, 'dispatching', ?, ?, ?)
                ON CONFLICT(idempotency_key) DO UPDATE SET
                    provider=excluded.provider,
                    model=excluded.model,
                    status='dispatching',
                    prompt_hash=excluded.prompt_hash,
                    started_at=excluded.started_at,
                    error=NULL
                """,
                (
                    step_id, task_id, stage, provider, model,
                    idempotency_key, prompt_hash, utc_now()
                ),
            )
        return True

    def complete_step(self, idempotency_key: str, artifact_path: str) -> None:
        portable_path = portable_project_path(
            artifact_path,
            self.project_root,
            legacy_anchor="outputs",
        )
        with self.connect() as con:
            con.execute(
                """
                UPDATE steps
                SET status='completed', artifact_path=?, completed_at=?, error=NULL
                WHERE idempotency_key=?
                """,
                (portable_path, utc_now(), idempotency_key),
            )

    def mark_artifact_missing(self, idempotency_key: str, artifact_path: str) -> None:
        """Allow a paid step to rerun when its durable artifact was not transferred."""

        with self.connect() as con:
            con.execute(
                """
                UPDATE steps
                SET status='artifact_missing', error=?
                WHERE idempotency_key=? AND status='completed'
                """,
                (f"completed artifact is unavailable: {artifact_path}", idempotency_key),
            )
            con.execute(
                """
                INSERT INTO events(task_id,event_type,payload_json,created_at)
                SELECT task_id, 'completed_artifact_missing', ?, ?
                FROM steps WHERE idempotency_key=?
                """,
                (
                    json.dumps({"artifact_path": artifact_path}),
                    utc_now(),
                    idempotency_key,
                ),
            )

    def fail_step(self, idempotency_key: str, error: str) -> None:
        with self.connect() as con:
            con.execute(
                "UPDATE steps SET status='failed', error=? WHERE idempotency_key=?",
                (error, idempotency_key),
            )

    def completed_artifact(self, idempotency_key: str) -> str | None:
        with self.connect() as con:
            row = con.execute(
                """
                SELECT artifact_path FROM steps
                WHERE idempotency_key=? AND status='completed'
                """,
                (idempotency_key,),
            ).fetchone()
        return row["artifact_path"] if row else None

    def resolve_artifact_path(self, artifact_path: str | Path) -> Path:
        return resolve_project_path(
            artifact_path,
            self.project_root,
            legacy_anchor="outputs",
        )

    def completed_artifacts(self) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT task_id, stage, idempotency_key, artifact_path
                FROM steps
                WHERE status='completed' AND artifact_path IS NOT NULL
                ORDER BY task_id, stage
                """
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _decode_command_row(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        record["request"] = json.loads(record.pop("request_json"))
        record["stdout_truncated"] = bool(record["stdout_truncated"])
        record["stderr_truncated"] = bool(record["stderr_truncated"])
        return record

    @staticmethod
    def _decode_validation_row(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        record["details"] = json.loads(record.pop("details_json"))
        return record

    @staticmethod
    def _decode_checkpoint_row(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        record["paths"] = json.loads(record.pop("paths_json"))
        return record

    def _decode_patch_row(
        self,
        con: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        record = dict(row)
        files = con.execute(
            """
            SELECT path, operation, pre_sha256, post_sha256, backup_blob,
                   pre_mode, size_before, size_after
            FROM patch_files WHERE patch_id=? ORDER BY path
            """,
            (row["patch_id"],),
        ).fetchall()
        record["files"] = [dict(file_row) for file_row in files]
        return record

    def claim_command(
        self,
        *,
        command_id: str,
        task_id: str | None,
        action_id: str | None,
        idempotency_key: str,
        request_sha256: str,
        request: dict[str, Any],
    ) -> tuple[bool, dict[str, Any]]:
        """Atomically claim one durable command idempotency key.

        The returned boolean is true only for the caller that inserted the
        claim. Existing terminal and in-progress records are never overwritten.
        """

        for name, value in (
            ("command_id", command_id),
            ("idempotency_key", idempotency_key),
            ("request_sha256", request_sha256),
        ):
            if not isinstance(value, str) or not value or "\x00" in value:
                raise ValueError(f"{name} must be a non-empty safe string")
        if len(request_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in request_sha256.casefold()
        ):
            raise ValueError("request_sha256 must be a SHA-256 hex digest")
        executable_alias = request.get("executable_alias")
        cwd = request.get("cwd")
        if not isinstance(executable_alias, str) or not executable_alias:
            raise ValueError("durable command request requires executable_alias")
        if any(separator in executable_alias for separator in ("/", "\\", ":")):
            raise ValueError("durable command executable_alias must be a basename")
        if not isinstance(cwd, str) or not cwd:
            raise ValueError("durable command request requires a relative cwd")
        if (
            Path(cwd).is_absolute()
            or ":" in cwd
            or ".." in Path(cwd.replace("\\", "/")).parts
        ):
            raise ValueError("durable command cwd must be project-relative")
        request_json = json.dumps(
            request,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        now = utc_now()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute(
                "SELECT * FROM commands WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                return False, self._decode_command_row(existing)
            con.execute(
                """
                INSERT INTO commands (
                    command_id, task_id, action_id, idempotency_key,
                    request_sha256, request_json, executable_alias, cwd,
                    status, started_at, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?, 'dispatching', ?,?,?)
                """,
                (
                    command_id,
                    task_id,
                    action_id,
                    idempotency_key,
                    request_sha256.casefold(),
                    request_json,
                    executable_alias,
                    cwd,
                    now,
                    now,
                    now,
                ),
            )
            con.execute(
                """
                INSERT INTO events(task_id,event_type,payload_json,created_at)
                VALUES(?,?,?,?)
                """,
                (
                    task_id,
                    "command_claimed",
                    json.dumps(
                        {
                            "command_id": command_id,
                            "action_id": action_id,
                            "idempotency_key": idempotency_key,
                            "executable_alias": executable_alias,
                            "cwd": cwd,
                        },
                        sort_keys=True,
                    ),
                    now,
                ),
            )
            inserted = con.execute(
                "SELECT * FROM commands WHERE command_id=?",
                (command_id,),
            ).fetchone()
        assert inserted is not None
        return True, self._decode_command_row(inserted)

    def complete_command(
        self,
        command_id: str,
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        stdout = str(result.get("stdout", ""))
        stderr = str(result.get("stderr", ""))
        completed_at = str(result["completed_at"])
        with self.connect() as con:
            cursor = con.execute(
                """
                UPDATE commands SET
                    status='completed', outcome=?, exit_code=?, stdout=?, stderr=?,
                    stdout_sha256=?, stderr_sha256=?, stdout_truncated=?,
                    stderr_truncated=?, duration_ms=?, started_at=?, completed_at=?,
                    error=?, updated_at=?
                WHERE command_id=? AND status='dispatching'
                """,
                (
                    str(result["outcome"]),
                    result.get("exit_code"),
                    stdout,
                    stderr,
                    hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
                    hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
                    int(bool(result.get("stdout_truncated"))),
                    int(bool(result.get("stderr_truncated"))),
                    int(result["duration_ms"]),
                    str(result["started_at"]),
                    completed_at,
                    result.get("error"),
                    completed_at,
                    command_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("durable command is not in dispatching state")
            row = con.execute(
                "SELECT * FROM commands WHERE command_id=?",
                (command_id,),
            ).fetchone()
            assert row is not None
            con.execute(
                """
                INSERT INTO events(task_id,event_type,payload_json,created_at)
                VALUES(?,?,?,?)
                """,
                (
                    row["task_id"],
                    "command_completed",
                    json.dumps(
                        {
                            "command_id": command_id,
                            "action_id": row["action_id"],
                            "idempotency_key": row["idempotency_key"],
                            "outcome": result["outcome"],
                            "exit_code": result.get("exit_code"),
                            "duration_ms": int(result["duration_ms"]),
                        },
                        sort_keys=True,
                    ),
                    completed_at,
                ),
            )
        return self._decode_command_row(row)

    def fail_command_dispatch(self, command_id: str, error: str) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as con:
            cursor = con.execute(
                """
                UPDATE commands SET
                    status='dispatch_error', outcome='ERROR', error=?,
                    completed_at=?, updated_at=?
                WHERE command_id=? AND status='dispatching'
                """,
                (error, now, now, command_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("durable command is not in dispatching state")
            row = con.execute(
                "SELECT * FROM commands WHERE command_id=?",
                (command_id,),
            ).fetchone()
            assert row is not None
            con.execute(
                """
                INSERT INTO events(task_id,event_type,payload_json,created_at)
                VALUES(?,?,?,?)
                """,
                (
                    row["task_id"],
                    "command_dispatch_error",
                    json.dumps(
                        {
                            "command_id": command_id,
                            "action_id": row["action_id"],
                            "idempotency_key": row["idempotency_key"],
                            "error": error,
                        },
                        sort_keys=True,
                    ),
                    now,
                ),
            )
        return self._decode_command_row(row)

    def get_command(self, idempotency_key: str) -> dict[str, Any] | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT * FROM commands WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
        return self._decode_command_row(row) if row is not None else None

    def record_validation(
        self,
        record: Mapping[str, Any],
    ) -> dict[str, Any]:
        required = (
            "validation_id",
            "check_id",
            "kind",
            "spec_sha256",
            "outcome",
            "summary",
            "details",
            "started_at",
            "completed_at",
            "duration_ms",
        )
        missing = [name for name in required if name not in record]
        if missing:
            raise ValueError("validation record is missing: " + ", ".join(missing))
        idempotency_key = record.get("idempotency_key")
        if idempotency_key is not None and (
            not isinstance(idempotency_key, str)
            or not idempotency_key
            or "\x00" in idempotency_key
        ):
            raise ValueError("validation idempotency_key must be a non-empty safe string")
        spec_sha256 = str(record["spec_sha256"]).casefold()
        if len(spec_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in spec_sha256
        ):
            raise ValueError("validation spec_sha256 must be a SHA-256 hex digest")
        details_json = json.dumps(
            record["details"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        now = utc_now()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            if idempotency_key is not None:
                existing = con.execute(
                    "SELECT * FROM validation_runs WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    return self._decode_validation_row(existing)
            con.execute(
                """
                INSERT INTO validation_runs (
                    validation_id, task_id, action_id, command_id, check_id,
                    kind, idempotency_key, spec_sha256, outcome, summary,
                    details_json, started_at, completed_at, duration_ms, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    record["validation_id"],
                    record.get("task_id"),
                    record.get("action_id"),
                    record.get("command_id"),
                    record["check_id"],
                    record["kind"],
                    idempotency_key,
                    spec_sha256,
                    record["outcome"],
                    record["summary"],
                    details_json,
                    record["started_at"],
                    record["completed_at"],
                    int(record["duration_ms"]),
                    now,
                ),
            )
            row = con.execute(
                "SELECT * FROM validation_runs WHERE validation_id=?",
                (record["validation_id"],),
            ).fetchone()
            assert row is not None
            con.execute(
                """
                INSERT INTO events(task_id,event_type,payload_json,created_at)
                VALUES(?,?,?,?)
                """,
                (
                    record.get("task_id"),
                    "validation_recorded",
                    json.dumps(
                        {
                            "validation_id": record["validation_id"],
                            "check_id": record["check_id"],
                            "kind": record["kind"],
                            "outcome": record["outcome"],
                            "command_id": record.get("command_id"),
                        },
                        sort_keys=True,
                    ),
                    now,
                ),
            )
        return self._decode_validation_row(row)

    def get_validation(self, idempotency_key: str) -> dict[str, Any] | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT * FROM validation_runs WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
        return self._decode_validation_row(row) if row is not None else None

    def claim_patch(
        self,
        *,
        patch_id: str,
        task_id: str | None,
        actor: str,
        reason: str,
        idempotency_key: str,
        request_sha256: str,
        files: list[Mapping[str, Any]],
    ) -> tuple[bool, dict[str, Any]]:
        """Atomically claim a hash-locked patch and persist rollback bytes."""

        patch_id = _require_safe_text("patch_id", patch_id, maximum=200)
        actor = _require_safe_text("actor", actor, maximum=200)
        reason = _require_safe_text("reason", reason, maximum=2_000)
        idempotency_key = _require_safe_text(
            "idempotency_key", idempotency_key, maximum=500
        )
        request_sha256 = _require_sha256("request_sha256", request_sha256)
        if not files:
            raise ValueError("patch must contain at least one file")

        normalized_files: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        for file_record in files:
            path = _require_portable_path("patch path", file_record.get("path"))
            path_key = path.casefold()
            if path_key in seen_paths:
                raise ValueError(f"duplicate patch path: {path}")
            seen_paths.add(path_key)
            operation = file_record.get("operation")
            if operation not in {"create", "replace"}:
                raise ValueError("patch operation must be create or replace")
            post_sha256 = _require_sha256(
                "post_sha256", file_record.get("post_sha256")
            )
            backup = file_record.get("backup_blob")
            pre_sha256 = file_record.get("pre_sha256")
            size_before = file_record.get("size_before")
            pre_mode = file_record.get("pre_mode")
            if operation == "replace":
                pre_sha256 = _require_sha256("pre_sha256", pre_sha256)
                if not isinstance(backup, bytes):
                    raise ValueError("replace patch requires byte backup")
                if not isinstance(size_before, int) or size_before < 0:
                    raise ValueError("replace patch requires size_before")
                if len(backup) != size_before:
                    raise ValueError("patch backup size does not match size_before")
            else:
                if pre_sha256 is not None or backup is not None or size_before is not None:
                    raise ValueError("create patch must not contain pre-image data")
                pre_mode = None
            size_after = file_record.get("size_after")
            if not isinstance(size_after, int) or size_after < 0:
                raise ValueError("patch requires non-negative size_after")
            if pre_mode is not None and (
                not isinstance(pre_mode, int) or pre_mode < 0
            ):
                raise ValueError("pre_mode must be a non-negative integer")
            normalized_files.append(
                {
                    "path": path,
                    "operation": operation,
                    "pre_sha256": pre_sha256,
                    "post_sha256": post_sha256,
                    "backup_blob": backup,
                    "pre_mode": pre_mode,
                    "size_before": size_before,
                    "size_after": size_after,
                }
            )

        now = utc_now()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute(
                "SELECT * FROM patch_transactions WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                return False, self._decode_patch_row(con, existing)
            con.execute(
                """
                INSERT INTO patch_transactions(
                    patch_id, task_id, actor, reason, idempotency_key,
                    request_sha256, status, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,'prepared',?,?)
                """,
                (
                    patch_id,
                    task_id,
                    actor,
                    reason,
                    idempotency_key,
                    request_sha256,
                    now,
                    now,
                ),
            )
            for file_record in normalized_files:
                con.execute(
                    """
                    INSERT INTO patch_files(
                        patch_id, path, operation, pre_sha256, post_sha256,
                        backup_blob, pre_mode, size_before, size_after
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        patch_id,
                        file_record["path"],
                        file_record["operation"],
                        file_record["pre_sha256"],
                        file_record["post_sha256"],
                        file_record["backup_blob"],
                        file_record["pre_mode"],
                        file_record["size_before"],
                        file_record["size_after"],
                    ),
                )
            con.execute(
                """
                INSERT INTO events(task_id,event_type,payload_json,created_at)
                VALUES(?,?,?,?)
                """,
                (
                    task_id,
                    "patch_prepared",
                    json.dumps(
                        {
                            "patch_id": patch_id,
                            "idempotency_key": idempotency_key,
                            "paths": [item["path"] for item in normalized_files],
                        },
                        sort_keys=True,
                    ),
                    now,
                ),
            )
            inserted = con.execute(
                "SELECT * FROM patch_transactions WHERE patch_id=?",
                (patch_id,),
            ).fetchone()
            assert inserted is not None
            return True, self._decode_patch_row(con, inserted)

    def complete_patch(self, patch_id: str) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as con:
            cursor = con.execute(
                """
                UPDATE patch_transactions
                SET status='applied', applied_at=?, updated_at=?
                WHERE patch_id=? AND status='prepared'
                """,
                (now, now, patch_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("patch is not in prepared state")
            row = con.execute(
                "SELECT * FROM patch_transactions WHERE patch_id=?",
                (patch_id,),
            ).fetchone()
            assert row is not None
            con.execute(
                """
                INSERT INTO events(task_id,event_type,payload_json,created_at)
                VALUES(?,?,?,?)
                """,
                (
                    row["task_id"],
                    "patch_applied",
                    json.dumps({"patch_id": patch_id}, sort_keys=True),
                    now,
                ),
            )
            return self._decode_patch_row(con, row)

    def fail_patch(
        self,
        patch_id: str,
        error: str,
        *,
        recovery_required: bool,
    ) -> dict[str, Any]:
        now = utc_now()
        status = "recovery_required" if recovery_required else "failed_rolled_back"
        safe_error = _require_safe_text("patch error", error, maximum=4_000)
        with self.connect() as con:
            cursor = con.execute(
                """
                UPDATE patch_transactions
                SET status=?, error=?, rolled_back_at=?, updated_at=?
                WHERE patch_id=? AND status IN ('prepared','rolling_back')
                """,
                (
                    status,
                    safe_error,
                    None if recovery_required else now,
                    now,
                    patch_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("patch cannot transition to failure state")
            row = con.execute(
                "SELECT * FROM patch_transactions WHERE patch_id=?",
                (patch_id,),
            ).fetchone()
            assert row is not None
            con.execute(
                """
                INSERT INTO events(task_id,event_type,payload_json,created_at)
                VALUES(?,?,?,?)
                """,
                (
                    row["task_id"],
                    "patch_recovery_required" if recovery_required else "patch_failed_rolled_back",
                    json.dumps(
                        {"patch_id": patch_id, "error": safe_error},
                        sort_keys=True,
                    ),
                    now,
                ),
            )
            return self._decode_patch_row(con, row)

    def begin_patch_rollback(self, patch_id: str) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as con:
            cursor = con.execute(
                """
                UPDATE patch_transactions SET status='rolling_back', updated_at=?
                WHERE patch_id=? AND status='applied'
                """,
                (now, patch_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("patch is not in applied state")
            row = con.execute(
                "SELECT * FROM patch_transactions WHERE patch_id=?",
                (patch_id,),
            ).fetchone()
            assert row is not None
            return self._decode_patch_row(con, row)

    def complete_patch_rollback(self, patch_id: str) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as con:
            cursor = con.execute(
                """
                UPDATE patch_transactions
                SET status='rolled_back', rolled_back_at=?, updated_at=?
                WHERE patch_id=? AND status='rolling_back'
                """,
                (now, now, patch_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("patch is not in rolling_back state")
            row = con.execute(
                "SELECT * FROM patch_transactions WHERE patch_id=?",
                (patch_id,),
            ).fetchone()
            assert row is not None
            con.execute(
                """
                INSERT INTO events(task_id,event_type,payload_json,created_at)
                VALUES(?,?,?,?)
                """,
                (
                    row["task_id"],
                    "patch_rolled_back",
                    json.dumps({"patch_id": patch_id}, sort_keys=True),
                    now,
                ),
            )
            return self._decode_patch_row(con, row)

    def get_patch(
        self,
        *,
        patch_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any] | None:
        if (patch_id is None) == (idempotency_key is None):
            raise ValueError("provide exactly one patch identifier")
        column = "patch_id" if patch_id is not None else "idempotency_key"
        value = patch_id if patch_id is not None else idempotency_key
        with self.connect() as con:
            row = con.execute(
                f"SELECT * FROM patch_transactions WHERE {column}=?",
                (value,),
            ).fetchone()
            return self._decode_patch_row(con, row) if row is not None else None

    def claim_git_checkpoint(
        self,
        *,
        checkpoint_id: str,
        patch_id: str | None,
        task_id: str | None,
        actor: str,
        reason: str,
        idempotency_key: str,
        request_sha256: str,
        base_commit: str | None,
        paths: list[str],
        diff_sha256: str,
    ) -> tuple[bool, dict[str, Any]]:
        checkpoint_id = _require_safe_text(
            "checkpoint_id", checkpoint_id, maximum=200
        )
        actor = _require_safe_text("actor", actor, maximum=200)
        reason = _require_safe_text("reason", reason, maximum=2_000)
        idempotency_key = _require_safe_text(
            "idempotency_key", idempotency_key, maximum=500
        )
        request_sha256 = _require_sha256("request_sha256", request_sha256)
        diff_sha256 = _require_sha256("diff_sha256", diff_sha256)
        if base_commit is not None:
            base_commit = _require_git_hash("base_commit", base_commit)
        if patch_id is not None:
            patch_id = _require_safe_text("patch_id", patch_id, maximum=200)
        if not paths:
            raise ValueError("checkpoint requires at least one path")
        normalized_paths = [_require_portable_path("checkpoint path", path) for path in paths]
        if len({path.casefold() for path in normalized_paths}) != len(normalized_paths):
            raise ValueError("checkpoint paths must be unique")
        paths_json = json.dumps(
            normalized_paths,
            sort_keys=False,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        now = utc_now()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute(
                "SELECT * FROM git_checkpoints WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                return False, self._decode_checkpoint_row(existing)
            if patch_id is not None:
                patch = con.execute(
                    "SELECT status FROM patch_transactions WHERE patch_id=?",
                    (patch_id,),
                ).fetchone()
                if patch is None:
                    raise ValueError("checkpoint patch_id does not exist")
                if patch["status"] != "applied":
                    raise ValueError("checkpoint patch must be in applied state")
            con.execute(
                """
                INSERT INTO git_checkpoints(
                    checkpoint_id, patch_id, task_id, actor, reason,
                    idempotency_key, request_sha256, status, base_commit,
                    paths_json, diff_sha256, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,'preparing',?,?,?,?,?)
                """,
                (
                    checkpoint_id,
                    patch_id,
                    task_id,
                    actor,
                    reason,
                    idempotency_key,
                    request_sha256,
                    base_commit,
                    paths_json,
                    diff_sha256,
                    now,
                    now,
                ),
            )
            con.execute(
                """
                INSERT INTO events(task_id,event_type,payload_json,created_at)
                VALUES(?,?,?,?)
                """,
                (
                    task_id,
                    "git_checkpoint_preparing",
                    json.dumps(
                        {
                            "checkpoint_id": checkpoint_id,
                            "patch_id": patch_id,
                            "paths": normalized_paths,
                        },
                        sort_keys=True,
                    ),
                    now,
                ),
            )
            row = con.execute(
                "SELECT * FROM git_checkpoints WHERE checkpoint_id=?",
                (checkpoint_id,),
            ).fetchone()
            assert row is not None
            return True, self._decode_checkpoint_row(row)

    def complete_git_checkpoint(
        self,
        checkpoint_id: str,
        commit_hash: str,
    ) -> dict[str, Any]:
        commit_hash = _require_git_hash("commit_hash", commit_hash)
        now = utc_now()
        with self.connect() as con:
            cursor = con.execute(
                """
                UPDATE git_checkpoints
                SET status='committed', commit_hash=?, completed_at=?, updated_at=?
                WHERE checkpoint_id=? AND status='preparing'
                """,
                (commit_hash, now, now, checkpoint_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Git checkpoint is not in preparing state")
            row = con.execute(
                "SELECT * FROM git_checkpoints WHERE checkpoint_id=?",
                (checkpoint_id,),
            ).fetchone()
            assert row is not None
            con.execute(
                """
                INSERT INTO events(task_id,event_type,payload_json,created_at)
                VALUES(?,?,?,?)
                """,
                (
                    row["task_id"],
                    "git_checkpoint_committed",
                    json.dumps(
                        {
                            "checkpoint_id": checkpoint_id,
                            "patch_id": row["patch_id"],
                            "commit_hash": commit_hash,
                        },
                        sort_keys=True,
                    ),
                    now,
                ),
            )
            return self._decode_checkpoint_row(row)

    def fail_git_checkpoint(
        self,
        checkpoint_id: str,
        error: str,
        *,
        recovery_required: bool,
    ) -> dict[str, Any]:
        status = "recovery_required" if recovery_required else "failed"
        safe_error = _require_safe_text("checkpoint error", error, maximum=4_000)
        now = utc_now()
        with self.connect() as con:
            cursor = con.execute(
                """
                UPDATE git_checkpoints SET status=?, error=?, updated_at=?
                WHERE checkpoint_id=? AND status IN ('preparing','reverting')
                """,
                (status, safe_error, now, checkpoint_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Git checkpoint cannot transition to failure state")
            row = con.execute(
                "SELECT * FROM git_checkpoints WHERE checkpoint_id=?",
                (checkpoint_id,),
            ).fetchone()
            assert row is not None
            con.execute(
                """
                INSERT INTO events(task_id,event_type,payload_json,created_at)
                VALUES(?,?,?,?)
                """,
                (
                    row["task_id"],
                    "git_checkpoint_recovery_required" if recovery_required else "git_checkpoint_failed",
                    json.dumps(
                        {"checkpoint_id": checkpoint_id, "error": safe_error},
                        sort_keys=True,
                    ),
                    now,
                ),
            )
            return self._decode_checkpoint_row(row)

    def begin_git_checkpoint_revert(self, checkpoint_id: str) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as con:
            cursor = con.execute(
                """
                UPDATE git_checkpoints SET status='reverting', updated_at=?
                WHERE checkpoint_id=? AND status='committed'
                """,
                (now, checkpoint_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Git checkpoint is not in committed state")
            row = con.execute(
                "SELECT * FROM git_checkpoints WHERE checkpoint_id=?",
                (checkpoint_id,),
            ).fetchone()
            assert row is not None
            return self._decode_checkpoint_row(row)

    def complete_git_checkpoint_revert(
        self,
        checkpoint_id: str,
        revert_commit_hash: str,
    ) -> dict[str, Any]:
        revert_commit_hash = _require_git_hash(
            "revert_commit_hash", revert_commit_hash
        )
        now = utc_now()
        with self.connect() as con:
            cursor = con.execute(
                """
                UPDATE git_checkpoints
                SET status='reverted', revert_commit_hash=?, reverted_at=?, updated_at=?
                WHERE checkpoint_id=? AND status='reverting'
                """,
                (revert_commit_hash, now, now, checkpoint_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Git checkpoint is not in reverting state")
            row = con.execute(
                "SELECT * FROM git_checkpoints WHERE checkpoint_id=?",
                (checkpoint_id,),
            ).fetchone()
            assert row is not None
            if row["patch_id"] is not None:
                con.execute(
                    """
                    UPDATE patch_transactions
                    SET status='rolled_back', rolled_back_at=?, updated_at=?
                    WHERE patch_id=? AND status='applied'
                    """,
                    (now, now, row["patch_id"]),
                )
            con.execute(
                """
                INSERT INTO events(task_id,event_type,payload_json,created_at)
                VALUES(?,?,?,?)
                """,
                (
                    row["task_id"],
                    "git_checkpoint_reverted",
                    json.dumps(
                        {
                            "checkpoint_id": checkpoint_id,
                            "patch_id": row["patch_id"],
                            "revert_commit_hash": revert_commit_hash,
                        },
                        sort_keys=True,
                    ),
                    now,
                ),
            )
            return self._decode_checkpoint_row(row)

    def get_git_checkpoint(
        self,
        *,
        checkpoint_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any] | None:
        if (checkpoint_id is None) == (idempotency_key is None):
            raise ValueError("provide exactly one checkpoint identifier")
        column = "checkpoint_id" if checkpoint_id is not None else "idempotency_key"
        value = checkpoint_id if checkpoint_id is not None else idempotency_key
        with self.connect() as con:
            row = con.execute(
                f"SELECT * FROM git_checkpoints WHERE {column}=?",
                (value,),
            ).fetchone()
        return self._decode_checkpoint_row(row) if row is not None else None

    @staticmethod
    def _decode_repair_attempt_row(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        proposal_json = record.pop("proposal_json", None)
        record["proposal"] = (
            json.loads(proposal_json) if proposal_json is not None else None
        )
        return record

    def _decode_repair_run_row(
        self,
        con: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        record = dict(row)
        record["policy"] = json.loads(record.pop("policy_json"))
        context_json = record.pop("failure_context_json", None)
        record["failure_context"] = (
            json.loads(context_json) if context_json is not None else None
        )
        attempts = con.execute(
            """
            SELECT * FROM repair_attempts
            WHERE run_id=? ORDER BY attempt_number
            """,
            (record["run_id"],),
        ).fetchall()
        record["attempts"] = tuple(
            self._decode_repair_attempt_row(attempt) for attempt in attempts
        )
        return record

    def claim_repair_run(
        self,
        *,
        run_id: str,
        task_id: str,
        actor: str,
        objective: str,
        idempotency_key: str,
        request_sha256: str,
        policy: Mapping[str, Any],
        deadline_at: str,
    ) -> tuple[bool, dict[str, Any]]:
        """Atomically claim a bounded repair run or replay its durable record."""

        run_id = _require_safe_text("run_id", run_id, maximum=200)
        task_id = _require_safe_text("task_id", task_id, maximum=200)
        actor = _require_safe_text("actor", actor, maximum=200)
        objective = _require_safe_text("objective", objective, maximum=4_000)
        idempotency_key = _require_safe_text(
            "idempotency_key", idempotency_key, maximum=500
        )
        request_sha256 = _require_sha256("request_sha256", request_sha256)
        deadline_at = _require_safe_text("repair deadline", deadline_at, maximum=80)
        policy_json = json.dumps(
            dict(policy), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        if len(policy_json) > 20_000:
            raise ValueError("repair policy is too large")

        now = utc_now()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute(
                "SELECT * FROM repair_runs WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                return False, self._decode_repair_run_row(con, existing)
            con.execute(
                """
                INSERT INTO repair_runs(
                    run_id, task_id, actor, objective, idempotency_key,
                    request_sha256, policy_json, status, started_at, deadline_at,
                    updated_at
                ) VALUES(?,?,?,?,?,?,?,'running',?,?,?)
                """,
                (
                    run_id,
                    task_id,
                    actor,
                    objective,
                    idempotency_key,
                    request_sha256,
                    policy_json,
                    now,
                    deadline_at,
                    now,
                ),
            )
            con.execute(
                """
                INSERT INTO events(task_id,event_type,payload_json,created_at)
                VALUES(?,?,?,?)
                """,
                (
                    task_id,
                    "repair_run_started",
                    json.dumps({"run_id": run_id}, sort_keys=True),
                    now,
                ),
            )
            inserted = con.execute(
                "SELECT * FROM repair_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            return True, self._decode_repair_run_row(con, inserted)

    def get_repair_run(
        self,
        *,
        run_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any] | None:
        if (run_id is None) == (idempotency_key is None):
            raise ValueError("provide exactly one repair run identifier")
        column = "run_id" if run_id is not None else "idempotency_key"
        value = run_id if run_id is not None else idempotency_key
        with self.connect() as con:
            row = con.execute(
                f"SELECT * FROM repair_runs WHERE {column}=?", (value,)
            ).fetchone()
            return self._decode_repair_run_row(con, row) if row is not None else None

    def record_repair_initial_failure(
        self,
        run_id: str,
        failure_sha256: str,
        failure_context: Mapping[str, Any],
    ) -> dict[str, Any]:
        failure_sha256 = _require_sha256("failure_sha256", failure_sha256)
        context_json = json.dumps(
            dict(failure_context),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        if len(context_json) > 50_000:
            raise ValueError("repair failure context is too large")
        now = utc_now()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            current = con.execute(
                "SELECT * FROM repair_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if current is None:
                raise KeyError(f"unknown repair run: {run_id}")
            if current["initial_failure_sha256"] is not None:
                if current["initial_failure_sha256"] != failure_sha256:
                    raise RuntimeError("repair run initial failure already differs")
                return self._decode_repair_run_row(con, current)
            updated = con.execute(
                """
                UPDATE repair_runs SET
                    initial_failure_sha256=?, last_failure_sha256=?,
                    identical_failure_count=1, no_progress_count=0,
                    failure_context_json=?, updated_at=?
                WHERE run_id=? AND status='running'
                """,
                (failure_sha256, failure_sha256, context_json, now, run_id),
            )
            if updated.rowcount != 1:
                raise RuntimeError("repair run is not active")
            row = con.execute(
                "SELECT * FROM repair_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            return self._decode_repair_run_row(con, row)

    def claim_repair_attempt(
        self,
        *,
        attempt_id: str,
        run_id: str,
        attempt_number: int,
        agent_label: str,
        failure_before_sha256: str,
        estimated_cost_usd: float,
    ) -> tuple[bool, dict[str, Any]]:
        attempt_id = _require_safe_text("attempt_id", attempt_id, maximum=240)
        agent_label = _require_safe_text("agent_label", agent_label, maximum=200)
        failure_before_sha256 = _require_sha256(
            "failure_before_sha256", failure_before_sha256
        )
        if (
            not isinstance(attempt_number, int)
            or isinstance(attempt_number, bool)
            or attempt_number <= 0
        ):
            raise ValueError("attempt_number must be a positive integer")
        if not isinstance(estimated_cost_usd, (int, float)) or not (
            0 <= float(estimated_cost_usd) < float("inf")
        ):
            raise ValueError("estimated repair cost must be finite and non-negative")
        now = utc_now()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute(
                "SELECT * FROM repair_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if existing is not None:
                return False, self._decode_repair_attempt_row(existing)
            run = con.execute(
                "SELECT * FROM repair_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise KeyError(f"unknown repair run: {run_id}")
            if run["status"] != "running":
                raise RuntimeError("repair run is not active")
            if attempt_number != int(run["attempt_count"]) + 1:
                raise RuntimeError("repair attempt number is not next in sequence")
            con.execute(
                """
                INSERT INTO repair_attempts(
                    attempt_id, run_id, attempt_number, agent_label, status,
                    failure_before_sha256, estimated_cost_usd,
                    created_at, updated_at
                ) VALUES(?,?,?,?,'proposing',?,?,?,?)
                """,
                (
                    attempt_id,
                    run_id,
                    attempt_number,
                    agent_label,
                    failure_before_sha256,
                    float(estimated_cost_usd),
                    now,
                    now,
                ),
            )
            con.execute(
                """
                UPDATE repair_runs SET attempt_count=?, updated_at=?
                WHERE run_id=?
                """,
                (attempt_number, now, run_id),
            )
            row = con.execute(
                "SELECT * FROM repair_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            return True, self._decode_repair_attempt_row(row)

    def record_repair_proposal(
        self,
        attempt_id: str,
        *,
        proposal_sha256: str,
        proposal: Mapping[str, Any],
        hypothesis: str,
        actual_cost_usd: float,
    ) -> dict[str, Any]:
        proposal_sha256 = _require_sha256("proposal_sha256", proposal_sha256)
        hypothesis = _require_safe_text("repair hypothesis", hypothesis, maximum=4_000)
        if not isinstance(actual_cost_usd, (int, float)) or not (
            0 <= float(actual_cost_usd) < float("inf")
        ):
            raise ValueError("actual repair cost must be finite and non-negative")
        proposal_json = json.dumps(
            dict(proposal), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        if len(proposal_json) > 2_500_000:
            raise ValueError("repair proposal is too large")
        now = utc_now()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                """
                SELECT a.run_id,a.status,a.agent_label,r.task_id
                FROM repair_attempts a JOIN repair_runs r ON r.run_id=a.run_id
                WHERE a.attempt_id=?
                """,
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown repair attempt: {attempt_id}")
            updated = con.execute(
                """
                UPDATE repair_attempts SET
                    status='proposal_received', proposal_sha256=?,
                    proposal_json=?, hypothesis=?, actual_cost_usd=?, updated_at=?
                WHERE attempt_id=? AND status='proposing'
                """,
                (
                    proposal_sha256,
                    proposal_json,
                    hypothesis,
                    float(actual_cost_usd),
                    now,
                    attempt_id,
                ),
            )
            if updated.rowcount != 1:
                raise RuntimeError("repair attempt is not awaiting a proposal")
            con.execute(
                """
                UPDATE repair_runs SET cost_usd=cost_usd+?, updated_at=?
                WHERE run_id=? AND status='running'
                """,
                (float(actual_cost_usd), now, row["run_id"]),
            )
            con.execute(
                """
                INSERT INTO telemetry(
                    task_id,step_id,provider,model,estimated_cost_usd,
                    stop_reason,created_at
                ) VALUES(?,?,?,? ,?,'repair_proposal_received',?)
                """,
                (
                    row["task_id"],
                    attempt_id,
                    "repair_agent",
                    row["agent_label"],
                    float(actual_cost_usd),
                    now,
                ),
            )
            stored = con.execute(
                "SELECT * FROM repair_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            return self._decode_repair_attempt_row(stored)

    def reject_repair_proposal(
        self,
        attempt_id: str,
        *,
        proposal_sha256: str,
        actual_cost_usd: float,
        error: str,
    ) -> dict[str, Any]:
        proposal_sha256 = _require_sha256("proposal_sha256", proposal_sha256)
        safe_error = _require_safe_text("repair proposal error", error, maximum=4_000)
        if not isinstance(actual_cost_usd, (int, float)) or not (
            0 <= float(actual_cost_usd) < float("inf")
        ):
            raise ValueError("actual repair cost must be finite and non-negative")
        now = utc_now()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                """
                SELECT a.run_id,a.agent_label,r.task_id
                FROM repair_attempts a JOIN repair_runs r ON r.run_id=a.run_id
                WHERE a.attempt_id=?
                """,
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown repair attempt: {attempt_id}")
            updated = con.execute(
                """
                UPDATE repair_attempts SET
                    status='rejected', proposal_sha256=?, actual_cost_usd=?,
                    error=?, completed_at=?, updated_at=?
                WHERE attempt_id=? AND status='proposing'
                """,
                (
                    proposal_sha256,
                    float(actual_cost_usd),
                    safe_error,
                    now,
                    now,
                    attempt_id,
                ),
            )
            if updated.rowcount != 1:
                raise RuntimeError("repair attempt is not awaiting a proposal")
            con.execute(
                """
                UPDATE repair_runs SET cost_usd=cost_usd+?, updated_at=?
                WHERE run_id=? AND status='running'
                """,
                (float(actual_cost_usd), now, row["run_id"]),
            )
            con.execute(
                """
                INSERT INTO telemetry(
                    task_id,step_id,provider,model,estimated_cost_usd,
                    stop_reason,error,created_at
                ) VALUES(?,?,?,? ,?,'repair_proposal_rejected',?,?)
                """,
                (
                    row["task_id"],
                    attempt_id,
                    "repair_agent",
                    row["agent_label"],
                    float(actual_cost_usd),
                    safe_error,
                    now,
                ),
            )
            stored = con.execute(
                "SELECT * FROM repair_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            return self._decode_repair_attempt_row(stored)

    def mark_repair_patch_applied(
        self,
        attempt_id: str,
        patch_id: str,
    ) -> dict[str, Any]:
        patch_id = _require_safe_text("patch_id", patch_id, maximum=200)
        now = utc_now()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            patch = con.execute(
                "SELECT status FROM patch_transactions WHERE patch_id=?", (patch_id,)
            ).fetchone()
            if patch is None or patch["status"] != "applied":
                raise RuntimeError("repair patch is not durably applied")
            updated = con.execute(
                """
                UPDATE repair_attempts SET
                    status='patch_applied', patch_id=?, updated_at=?
                WHERE attempt_id=? AND status='proposal_received'
                """,
                (patch_id, now, attempt_id),
            )
            if updated.rowcount != 1:
                raise RuntimeError("repair attempt is not ready for patch linkage")
            row = con.execute(
                "SELECT * FROM repair_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            return self._decode_repair_attempt_row(row)

    def record_repair_validation(
        self,
        attempt_id: str,
        *,
        failure_sha256: str,
        outcome: str,
    ) -> dict[str, Any]:
        failure_sha256 = _require_sha256("validation_sha256", failure_sha256)
        outcome = _require_safe_text("validation outcome", outcome, maximum=40)
        status = "validation_passed" if outcome == "PASS" else "validation_failed"
        now = utc_now()
        with self.connect() as con:
            updated = con.execute(
                """
                UPDATE repair_attempts SET
                    status=?, validation_after_sha256=?, validation_outcome=?,
                    updated_at=?
                WHERE attempt_id=? AND status='patch_applied'
                """,
                (status, failure_sha256, outcome, now, attempt_id),
            )
            if updated.rowcount != 1:
                raise RuntimeError("repair attempt is not awaiting validation")
            row = con.execute(
                "SELECT * FROM repair_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            return self._decode_repair_attempt_row(row)

    def complete_repair_attempt_rollback(self, attempt_id: str) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as con:
            row = con.execute(
                "SELECT patch_id FROM repair_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown repair attempt: {attempt_id}")
            patch = con.execute(
                "SELECT status FROM patch_transactions WHERE patch_id=?",
                (row["patch_id"],),
            ).fetchone()
            if patch is None or patch["status"] != "rolled_back":
                raise RuntimeError("repair patch is not durably rolled back")
            updated = con.execute(
                """
                UPDATE repair_attempts SET
                    status='rolled_back', completed_at=?, updated_at=?
                WHERE attempt_id=?
                  AND status IN ('validation_failed','validation_passed')
                """,
                (now, now, attempt_id),
            )
            if updated.rowcount != 1:
                raise RuntimeError("repair attempt is not ready to finish rollback")
            stored = con.execute(
                "SELECT * FROM repair_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            return self._decode_repair_attempt_row(stored)

    def fail_repair_attempt(self, attempt_id: str, error: str) -> dict[str, Any]:
        safe_error = _require_safe_text("repair attempt error", error, maximum=4_000)
        now = utc_now()
        with self.connect() as con:
            updated = con.execute(
                """
                UPDATE repair_attempts SET
                    status='failed', error=?, completed_at=?, updated_at=?
                WHERE attempt_id=?
                  AND status IN ('proposal_received','patch_applied')
                """,
                (safe_error, now, now, attempt_id),
            )
            if updated.rowcount != 1:
                raise RuntimeError("repair attempt cannot transition to failed")
            row = con.execute(
                "SELECT * FROM repair_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            return self._decode_repair_attempt_row(row)

    def record_repair_progress(
        self,
        run_id: str,
        *,
        last_failure_sha256: str,
        failure_context: Mapping[str, Any],
        identical_failure_count: int,
        no_progress_count: int,
    ) -> dict[str, Any]:
        last_failure_sha256 = _require_sha256(
            "last_failure_sha256", last_failure_sha256
        )
        if identical_failure_count < 1 or no_progress_count < 0:
            raise ValueError("repair progress counters are invalid")
        context_json = json.dumps(
            dict(failure_context),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        if len(context_json) > 50_000:
            raise ValueError("repair failure context is too large")
        now = utc_now()
        with self.connect() as con:
            updated = con.execute(
                """
                UPDATE repair_runs SET
                    last_failure_sha256=?, identical_failure_count=?,
                    no_progress_count=?, failure_context_json=?, updated_at=?
                WHERE run_id=? AND status='running'
                """,
                (
                    last_failure_sha256,
                    identical_failure_count,
                    no_progress_count,
                    context_json,
                    now,
                    run_id,
                ),
            )
            if updated.rowcount != 1:
                raise RuntimeError("repair run is not active")
            row = con.execute(
                "SELECT * FROM repair_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            return self._decode_repair_run_row(con, row)

    def complete_repair_success(
        self,
        run_id: str,
        attempt_id: str,
        checkpoint_id: str,
    ) -> dict[str, Any]:
        checkpoint_id = _require_safe_text(
            "checkpoint_id", checkpoint_id, maximum=200
        )
        now = utc_now()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            checkpoint = con.execute(
                "SELECT status FROM git_checkpoints WHERE checkpoint_id=?",
                (checkpoint_id,),
            ).fetchone()
            if checkpoint is None or checkpoint["status"] != "committed":
                raise RuntimeError("repair checkpoint is not durably committed")
            attempt = con.execute(
                """
                UPDATE repair_attempts SET
                    status='checkpointed', checkpoint_id=?, completed_at=?, updated_at=?
                WHERE attempt_id=? AND run_id=? AND status='validation_passed'
                """,
                (checkpoint_id, now, now, attempt_id, run_id),
            )
            if attempt.rowcount != 1:
                raise RuntimeError("repair attempt is not ready for checkpoint completion")
            run = con.execute(
                """
                UPDATE repair_runs SET
                    status='passed', stop_reason='validation_passed',
                    checkpoint_id=?, completed_at=?, updated_at=?
                WHERE run_id=? AND status='running'
                """,
                (checkpoint_id, now, now, run_id),
            )
            if run.rowcount != 1:
                raise RuntimeError("repair run is not active")
            row = con.execute(
                "SELECT * FROM repair_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            return self._decode_repair_run_row(con, row)

    def finish_repair_run(
        self,
        run_id: str,
        *,
        status: str,
        stop_reason: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        if status not in {"passed", "blocked", "recovery_required"}:
            raise ValueError("invalid terminal repair run status")
        stop_reason = _require_safe_text("repair stop reason", stop_reason, maximum=200)
        safe_error = (
            _require_safe_text("repair error", error, maximum=4_000)
            if error is not None
            else None
        )
        now = utc_now()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            updated = con.execute(
                """
                UPDATE repair_runs SET
                    status=?, stop_reason=?, error=?, completed_at=?, updated_at=?
                WHERE run_id=? AND status='running'
                """,
                (status, stop_reason, safe_error, now, now, run_id),
            )
            if updated.rowcount != 1:
                current = con.execute(
                    "SELECT * FROM repair_runs WHERE run_id=?", (run_id,)
                ).fetchone()
                if current is None:
                    raise KeyError(f"unknown repair run: {run_id}")
                if (
                    current["status"] == status
                    and current["stop_reason"] == stop_reason
                ):
                    return self._decode_repair_run_row(con, current)
                raise RuntimeError("repair run is not active")
            con.execute(
                """
                INSERT INTO events(task_id,event_type,payload_json,created_at)
                SELECT task_id,?,?,? FROM repair_runs WHERE run_id=?
                """,
                (
                    f"repair_run_{status}",
                    json.dumps(
                        {"run_id": run_id, "stop_reason": stop_reason},
                        sort_keys=True,
                    ),
                    now,
                    run_id,
                ),
            )
            row = con.execute(
                "SELECT * FROM repair_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            return self._decode_repair_run_row(con, row)

    def integrity_check(self) -> str:
        with self.connect() as con:
            return str(con.execute("PRAGMA integrity_check").fetchone()[0])

    def add_telemetry(self, **record: Any) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO telemetry (
                    task_id, step_id, provider, model, input_tokens, output_tokens,
                    estimated_cost_usd, latency_ms, stop_reason, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["task_id"], record.get("step_id"),
                    record["provider"], record["model"],
                    record.get("input_tokens"), record.get("output_tokens"),
                    record["estimated_cost_usd"], record.get("latency_ms"),
                    record.get("stop_reason"), record.get("error"), utc_now()
                ),
            )

    def spend(self, *, since_iso: str | None = None, task_id: str | None = None) -> float:
        sql = "SELECT COALESCE(SUM(estimated_cost_usd),0) AS total FROM telemetry WHERE 1=1"
        params: list[Any] = []
        if since_iso:
            sql += " AND created_at >= ?"
            params.append(since_iso)
        if task_id:
            sql += " AND task_id = ?"
            params.append(task_id)
        with self.connect() as con:
            row = con.execute(sql, params).fetchone()
        return float(row["total"] or 0)

    def active_reservations(
        self,
        *,
        since_iso: str | None = None,
        task_id: str | None = None,
    ) -> float:
        sql = """
            SELECT COALESCE(SUM(reserved_usd),0) AS total
            FROM budget_reservations
            WHERE status='reserved'
        """
        params: list[Any] = []
        if since_iso:
            sql += " AND created_at >= ?"
            params.append(since_iso)
        if task_id:
            sql += " AND task_id = ?"
            params.append(task_id)
        with self.connect() as con:
            row = con.execute(sql, params).fetchone()
        return float(row["total"] or 0)

    def reserve(self, reservation_id: str, task_id: str, step_id: str, amount: float) -> None:
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute(
                "SELECT * FROM budget_reservations WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["task_id"] != task_id
                    or existing["step_id"] != step_id
                    or abs(float(existing["reserved_usd"]) - float(amount)) > 1e-12
                ):
                    raise RuntimeError(
                        "budget reservation id belongs to a different request"
                    )
                return
            con.execute(
                """
                INSERT INTO budget_reservations (
                    reservation_id, task_id, step_id, reserved_usd,
                    status, created_at
                ) VALUES (?, ?, ?, ?, 'reserved', ?)
                """,
                (reservation_id, task_id, step_id, amount, utc_now()),
            )

    def get_budget_reservation(self, reservation_id: str) -> dict[str, Any] | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT * FROM budget_reservations WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def settle(self, reservation_id: str, actual_usd: float) -> None:
        with self.connect() as con:
            con.execute(
                """
                UPDATE budget_reservations
                SET actual_usd=?, status='settled', settled_at=?
                WHERE reservation_id=?
                """,
                (actual_usd, utc_now(), reservation_id),
            )

    def event(self, event_type: str, payload: dict, task_id: str | None = None) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO events(task_id,event_type,payload_json,created_at) VALUES(?,?,?,?)",
                (task_id, event_type, json.dumps(payload), utc_now()),
            )
