from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from command_runner import (
    CommandOutcome,
    CommandPolicy,
    CommandRequest,
    CommandResult,
    CommandRunner,
    ExecutableRule,
)
from durable_execution import IdempotentCommandRunner
from ledger import Ledger
from workspace_guard import WorkspaceGuard, WorkspaceViolation


class GitCheckpointError(RuntimeError):
    """Base class for guarded Git checkpoint failures."""


class GitCheckpointConflict(GitCheckpointError):
    """Raised when repository state is unsafe for the requested operation."""


class GitCheckpointRecoveryRequired(GitCheckpointError):
    """Raised when an interrupted Git side effect requires review."""


@dataclass(frozen=True)
class GitChange:
    path: str
    index_status: str
    worktree_status: str

    @property
    def conflicted(self) -> bool:
        pair = self.index_status + self.worktree_status
        return "U" in pair or pair in {"AA", "DD"}

    @property
    def staged(self) -> bool:
        return self.index_status not in {" ", "?"}


@dataclass(frozen=True)
class RepositoryStatus:
    branch: str | None
    head: str | None
    changes: tuple[GitChange, ...]

    @property
    def clean(self) -> bool:
        return not self.changes

    @property
    def conflicts(self) -> tuple[GitChange, ...]:
        return tuple(change for change in self.changes if change.conflicted)


@dataclass(frozen=True)
class CheckpointRequest:
    checkpoint_id: str
    idempotency_key: str
    actor: str
    reason: str
    paths: Sequence[str | Path]
    patch_id: str | None = None
    task_id: str | None = None


@dataclass(frozen=True)
class CheckpointResult:
    checkpoint_id: str
    status: str
    base_commit: str | None
    commit_hash: str | None
    revert_commit_hash: str | None
    paths: tuple[str, ...]
    replayed: bool = False


_BRANCH_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,100}$")


class GitCheckpointManager:
    """Create and revert scoped Git checkpoints through CommandRunner.

    Checkpoints reject pre-staged, unrelated, protected, and conflicted paths.
    Revert is intentionally limited to the current HEAD checkpoint, keeping
    rollback ordered and avoiding implicit history surgery.
    """

    def __init__(
        self,
        guard: WorkspaceGuard,
        ledger: Ledger,
        *,
        git_executable: str | Path | None = None,
    ) -> None:
        self.guard = guard
        self.ledger = ledger
        discovered = git_executable or shutil.which("git")
        if discovered is None:
            raise FileNotFoundError("Git executable was not found")
        executable = Path(discovered)
        executable = executable.expanduser().resolve(strict=True)

        hooks = self.guard.authorize_write(
            "logs/git_hooks_disabled",
            expect_directory=True,
        )
        hooks.path.mkdir(parents=True, exist_ok=True)
        if any(hooks.path.iterdir()):
            raise GitCheckpointConflict("disabled Git hooks directory is not empty")
        self.environment = {
            "GIT_CONFIG_COUNT": "3",
            "GIT_CONFIG_KEY_0": "core.hooksPath",
            "GIT_CONFIG_VALUE_0": hooks.relative_path,
            "GIT_CONFIG_KEY_1": "user.name",
            "GIT_CONFIG_VALUE_1": "AI Project OS",
            "GIT_CONFIG_KEY_2": "user.email",
            "GIT_CONFIG_VALUE_2": "ai-project-os@localhost.invalid",
        }
        policy = CommandPolicy(
            rules=(
                ExecutableRule(
                    alias="git",
                    executable=executable,
                    allowed_argument_prefixes=(
                        ("status", "--porcelain=v1", "-z", "--untracked-files=all"),
                        ("rev-parse", "--show-toplevel"),
                        ("rev-parse", "--verify"),
                        ("symbolic-ref", "--short", "HEAD"),
                        ("diff", "--no-ext-diff", "--binary", "--"),
                        ("add", "--"),
                        ("restore", "--staged", "--"),
                        ("commit", "--no-gpg-sign", "--no-verify", "-m"),
                        ("revert", "--no-edit"),
                        ("revert", "--abort"),
                        ("check-ref-format", "--branch"),
                        ("switch", "-c"),
                        ("init", "--initial-branch"),
                    ),
                ),
            ),
            allowed_environment_keys=frozenset(self.environment),
            max_timeout_seconds=120,
            max_output_bytes=1_000_000,
        )
        self.runner = CommandRunner(guard, policy)
        self.durable_runner = IdempotentCommandRunner(self.runner, ledger)

    @staticmethod
    def _safe_text(name: str, value: Any, maximum: int) -> str:
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise ValueError(f"{name} must be a non-empty safe string")
        if len(value) > maximum:
            raise ValueError(f"{name} exceeds {maximum} characters")
        return value

    def _request(
        self,
        arguments: Sequence[str],
        *,
        action_id: str | None = None,
        idempotency_key: str | None = None,
        task_id: str | None = None,
    ) -> CommandRequest:
        return CommandRequest(
            argv=("git", *arguments),
            cwd=".",
            timeout_seconds=120,
            max_output_bytes=1_000_000,
            environment=self.environment,
            task_id=task_id,
            action_id=action_id,
            idempotency_key=idempotency_key,
        )

    def _run_read(self, *arguments: str, allow_failure: bool = False) -> CommandResult:
        result = self.runner.run(self._request(arguments))
        if result.outcome != CommandOutcome.PASS and not allow_failure:
            detail = (result.stderr or result.stdout or result.error or "Git failed").strip()
            raise GitCheckpointError(detail[:4_000])
        return result

    def _run_durable(
        self,
        arguments: Sequence[str],
        *,
        action_id: str,
        idempotency_key: str,
        task_id: str | None,
    ) -> CommandResult:
        return self.durable_runner.run(
            self._request(
                arguments,
                action_id=action_id,
                idempotency_key=idempotency_key,
                task_id=task_id,
            )
        )

    def _ensure_repository(self) -> None:
        result = self._run_read("rev-parse", "--show-toplevel", allow_failure=True)
        if result.outcome != CommandOutcome.PASS:
            raise GitCheckpointError("workspace is not a Git repository")
        reported = Path(result.stdout.strip()).resolve(strict=True)
        if os.path.normcase(str(reported)) != os.path.normcase(str(self.guard.root)):
            raise GitCheckpointConflict("Git repository root does not match workspace root")

    @staticmethod
    def _parse_status(output: str) -> tuple[GitChange, ...]:
        tokens = output.split("\x00")
        changes: list[GitChange] = []
        index = 0
        while index < len(tokens):
            entry = tokens[index]
            index += 1
            if not entry:
                continue
            if len(entry) < 4 or entry[2] != " ":
                raise GitCheckpointError("unexpected Git porcelain status record")
            index_status, worktree_status = entry[0], entry[1]
            path = entry[3:].replace("\\", "/")
            if "R" in (index_status, worktree_status) or "C" in (
                index_status,
                worktree_status,
            ):
                if index >= len(tokens) or not tokens[index]:
                    raise GitCheckpointError("incomplete Git rename/copy status record")
                index += 1
                raise GitCheckpointConflict(
                    "renamed/copied paths require a dedicated reviewed checkpoint"
                )
            changes.append(
                GitChange(
                    path=path,
                    index_status=index_status,
                    worktree_status=worktree_status,
                )
            )
        return tuple(changes)

    def status(self) -> RepositoryStatus:
        self._ensure_repository()
        status_result = self._run_read(
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        )
        changes = self._parse_status(status_result.stdout)
        for change in changes:
            self.guard.authorize_write(change.path, expect_directory=False)
        branch_result = self._run_read(
            "symbolic-ref", "--short", "HEAD", allow_failure=True
        )
        head_result = self._run_read(
            "rev-parse", "--verify", "HEAD", allow_failure=True
        )
        return RepositoryStatus(
            branch=branch_result.stdout.strip()
            if branch_result.outcome == CommandOutcome.PASS
            else None,
            head=head_result.stdout.strip().casefold()
            if head_result.outcome == CommandOutcome.PASS
            else None,
            changes=changes,
        )

    def initialize_repository(
        self,
        *,
        initial_branch: str = "main",
        idempotency_key: str,
        task_id: str | None = None,
    ) -> RepositoryStatus:
        probe = self._run_read("rev-parse", "--show-toplevel", allow_failure=True)
        if probe.outcome == CommandOutcome.PASS:
            reported = Path(probe.stdout.strip()).resolve(strict=True)
            if os.path.normcase(str(reported)) == os.path.normcase(
                str(self.guard.root)
            ):
                return self.status()
        self._validate_branch_name(initial_branch)
        result = self._run_durable(
            ("init", "--initial-branch", initial_branch),
            action_id="git-initialize",
            idempotency_key=idempotency_key,
            task_id=task_id,
        )
        if result.outcome != CommandOutcome.PASS:
            raise GitCheckpointError((result.stderr or result.stdout).strip())
        after = self.status()
        if after.branch != initial_branch:
            raise GitCheckpointRecoveryRequired(
                f"Git branch postcondition failed: expected {initial_branch}"
            )
        return after

    def _validate_branch_name(self, name: str) -> str:
        self._safe_text("branch name", name, 101)
        if (
            not _BRANCH_NAME.fullmatch(name)
            or ".." in name
            or "@{" in name
            or "//" in name
            or name.endswith(("/", ".", ".lock"))
        ):
            raise ValueError("unsafe Git branch name")
        result = self._run_read("check-ref-format", "--branch", name, allow_failure=True)
        if result.outcome != CommandOutcome.PASS:
            raise ValueError("Git rejected branch name")
        return name

    def create_branch(
        self,
        name: str,
        *,
        idempotency_key: str,
        task_id: str | None = None,
    ) -> RepositoryStatus:
        current = self.status()
        if not current.clean:
            raise GitCheckpointConflict("branch creation requires a clean worktree")
        name = self._validate_branch_name(name)
        result = self._run_durable(
            ("switch", "-c", name),
            action_id="git-create-branch",
            idempotency_key=idempotency_key,
            task_id=task_id,
        )
        if result.outcome != CommandOutcome.PASS:
            raise GitCheckpointError((result.stderr or result.stdout).strip())
        after = self.status()
        if after.branch != name:
            raise GitCheckpointRecoveryRequired(
                f"Git branch postcondition failed: expected {name}"
            )
        return after

    def _normalize_paths(self, paths: Sequence[str | Path]) -> tuple[str, ...]:
        if isinstance(paths, (str, bytes)) or not paths:
            raise ValueError("checkpoint requires at least one path")
        normalized: list[str] = []
        seen: set[str] = set()
        for path in paths:
            authorized = self.guard.authorize_write(path, expect_directory=False)
            key = os.path.normcase(authorized.relative_path)
            if key in seen:
                raise ValueError(f"duplicate checkpoint path: {authorized.relative_path}")
            seen.add(key)
            normalized.append(authorized.relative_path)
        return tuple(sorted(normalized, key=str.casefold))

    def diff(self, paths: Sequence[str | Path]) -> str:
        normalized = self._normalize_paths(paths)
        result = self._run_read("diff", "--no-ext-diff", "--binary", "--", *normalized)
        return result.stdout

    def _evidence_digest(self, paths: tuple[str, ...]) -> str:
        digest = hashlib.sha256()
        diff = self.diff(paths)
        digest.update(diff.encode("utf-8"))
        for relative_path in paths:
            authorized = self.guard.authorize_write(
                relative_path,
                expect_directory=False,
            )
            digest.update(relative_path.encode("utf-8"))
            digest.update(b"\x00")
            if authorized.path.exists():
                digest.update(hashlib.sha256(authorized.path.read_bytes()).digest())
            else:
                digest.update(b"<missing>")
            digest.update(b"\x00")
        return digest.hexdigest()

    @staticmethod
    def _checkpoint_fingerprint(
        request: CheckpointRequest,
        *,
        base_commit: str | None,
        paths: tuple[str, ...],
        diff_sha256: str,
    ) -> str:
        payload = {
            "checkpoint_id": request.checkpoint_id,
            "patch_id": request.patch_id,
            "task_id": request.task_id,
            "actor": request.actor,
            "reason": request.reason,
            "base_commit": base_commit,
            "paths": list(paths),
            "diff_sha256": diff_sha256,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _result(record: dict[str, Any], *, replayed: bool) -> CheckpointResult:
        return CheckpointResult(
            checkpoint_id=str(record["checkpoint_id"]),
            status=str(record["status"]),
            base_commit=record.get("base_commit"),
            commit_hash=record.get("commit_hash"),
            revert_commit_hash=record.get("revert_commit_hash"),
            paths=tuple(str(path) for path in record["paths"]),
            replayed=replayed,
        )

    def _portable_error(self, result: CommandResult) -> str:
        detail = (result.stderr or result.stdout or result.error or "Git failed").strip()
        return detail.replace(str(self.guard.root), "<workspace>")[:4_000]

    def create_checkpoint(self, request: CheckpointRequest) -> CheckpointResult:
        self._safe_text("checkpoint_id", request.checkpoint_id, 200)
        self._safe_text("idempotency_key", request.idempotency_key, 500)
        self._safe_text("actor", request.actor, 200)
        self._safe_text("reason", request.reason, 2_000)
        paths = self._normalize_paths(request.paths)
        existing = self.ledger.get_git_checkpoint(
            idempotency_key=request.idempotency_key
        )
        if existing is not None:
            fingerprint = self._checkpoint_fingerprint(
                request,
                base_commit=existing.get("base_commit"),
                paths=paths,
                diff_sha256=str(existing["diff_sha256"]),
            )
            if fingerprint != existing["request_sha256"]:
                raise GitCheckpointConflict(
                    "checkpoint idempotency key belongs to a different request"
                )
            if existing["status"] in {"committed", "reverted"}:
                return self._result(existing, replayed=True)
            raise GitCheckpointRecoveryRequired(
                f"checkpoint requires recovery from state: {existing['status']}"
            )

        status = self.status()
        if status.conflicts:
            raise GitCheckpointConflict("checkpoint cannot include unresolved conflicts")
        changed = {os.path.normcase(change.path): change for change in status.changes}
        requested = {os.path.normcase(path) for path in paths}
        if set(changed) != requested:
            extras = sorted(change.path for key, change in changed.items() if key not in requested)
            missing = sorted(path for path in paths if os.path.normcase(path) not in changed)
            details = []
            if extras:
                details.append("unrelated changes: " + ", ".join(extras))
            if missing:
                details.append("unchanged paths: " + ", ".join(missing))
            raise GitCheckpointConflict("; ".join(details))
        staged = [change.path for change in status.changes if change.staged]
        if staged:
            raise GitCheckpointConflict(
                "checkpoint refuses pre-staged paths: " + ", ".join(staged)
            )

        diff_sha256 = self._evidence_digest(paths)
        request_sha256 = self._checkpoint_fingerprint(
            request,
            base_commit=status.head,
            paths=paths,
            diff_sha256=diff_sha256,
        )
        claimed, record = self.ledger.claim_git_checkpoint(
            checkpoint_id=request.checkpoint_id,
            patch_id=request.patch_id,
            task_id=request.task_id,
            actor=request.actor,
            reason=request.reason,
            idempotency_key=request.idempotency_key,
            request_sha256=request_sha256,
            base_commit=status.head,
            paths=list(paths),
            diff_sha256=diff_sha256,
        )
        if not claimed:
            if record["request_sha256"] != request_sha256:
                raise GitCheckpointConflict(
                    "checkpoint idempotency key belongs to a different request"
                )
            if record["status"] in {"committed", "reverted"}:
                return self._result(record, replayed=True)
            raise GitCheckpointRecoveryRequired(
                f"checkpoint requires recovery from state: {record['status']}"
            )

        add_result = self._run_durable(
            ("add", "--", *paths),
            action_id="git-checkpoint-add",
            idempotency_key=f"{request.idempotency_key}:add",
            task_id=request.task_id,
        )
        if add_result.outcome != CommandOutcome.PASS:
            error = self._portable_error(add_result)
            self.ledger.fail_git_checkpoint(
                request.checkpoint_id,
                error,
                recovery_required=True,
            )
            raise GitCheckpointRecoveryRequired(error)

        message = f"checkpoint: {request.reason}"[:240]
        commit_result = self._run_durable(
            ("commit", "--no-gpg-sign", "--no-verify", "-m", message),
            action_id="git-checkpoint-commit",
            idempotency_key=f"{request.idempotency_key}:commit",
            task_id=request.task_id,
        )
        if commit_result.outcome != CommandOutcome.PASS:
            recovery_required = True
            if status.head is not None:
                cleanup = self._run_durable(
                    ("restore", "--staged", "--", *paths),
                    action_id="git-checkpoint-unstage",
                    idempotency_key=f"{request.idempotency_key}:unstage",
                    task_id=request.task_id,
                )
                recovery_required = cleanup.outcome != CommandOutcome.PASS
            error = self._portable_error(commit_result)
            self.ledger.fail_git_checkpoint(
                request.checkpoint_id,
                error,
                recovery_required=recovery_required,
            )
            if recovery_required:
                raise GitCheckpointRecoveryRequired(error)
            raise GitCheckpointError(error)

        after = self.status()
        if after.head is None or after.head == status.head or not after.clean:
            error = "Git checkpoint postcondition failed"
            self.ledger.fail_git_checkpoint(
                request.checkpoint_id,
                error,
                recovery_required=True,
            )
            raise GitCheckpointRecoveryRequired(error)
        stored = self.ledger.complete_git_checkpoint(
            request.checkpoint_id,
            after.head,
        )
        return self._result(stored, replayed=False)

    def revert_checkpoint(self, checkpoint_id: str) -> CheckpointResult:
        record = self.ledger.get_git_checkpoint(checkpoint_id=checkpoint_id)
        if record is None:
            raise KeyError(f"unknown Git checkpoint: {checkpoint_id}")
        if record["status"] == "reverted":
            return self._result(record, replayed=True)
        if record["status"] != "committed":
            raise GitCheckpointRecoveryRequired(
                f"checkpoint cannot revert from state: {record['status']}"
            )
        status = self.status()
        if not status.clean:
            raise GitCheckpointConflict("checkpoint revert requires a clean worktree")
        if status.head != record["commit_hash"]:
            raise GitCheckpointConflict(
                "only the current HEAD checkpoint can be reverted automatically"
            )

        self.ledger.begin_git_checkpoint_revert(checkpoint_id)
        result = self._run_durable(
            ("revert", "--no-edit", str(record["commit_hash"])),
            action_id="git-checkpoint-revert",
            idempotency_key=f"{record['idempotency_key']}:revert",
            task_id=record.get("task_id"),
        )
        if result.outcome != CommandOutcome.PASS:
            abort = self._run_durable(
                ("revert", "--abort"),
                action_id="git-checkpoint-revert-abort",
                idempotency_key=f"{record['idempotency_key']}:revert-abort",
                task_id=record.get("task_id"),
            )
            recovery_required = abort.outcome != CommandOutcome.PASS
            error = self._portable_error(result)
            self.ledger.fail_git_checkpoint(
                checkpoint_id,
                error,
                recovery_required=recovery_required,
            )
            if recovery_required:
                raise GitCheckpointRecoveryRequired(error)
            raise GitCheckpointError(error)
        after = self.status()
        if after.head is None or after.head == record["commit_hash"] or not after.clean:
            error = "Git revert postcondition failed"
            self.ledger.fail_git_checkpoint(
                checkpoint_id,
                error,
                recovery_required=True,
            )
            raise GitCheckpointRecoveryRequired(error)
        stored = self.ledger.complete_git_checkpoint_revert(
            checkpoint_id,
            after.head,
        )
        return self._result(stored, replayed=False)
