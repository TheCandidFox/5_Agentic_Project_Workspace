from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from ledger import Ledger
from workspace_guard import WorkspaceGuard, WorkspaceViolation


class PatchError(RuntimeError):
    """Base class for controlled patch failures."""


class PatchConflict(PatchError):
    """Raised when a path or pre-image no longer matches the patch request."""


class PatchIdempotencyConflict(PatchError):
    """Raised when an idempotency key is reused for different content."""


class PatchRecoveryRequired(PatchError):
    """Raised when durable state indicates an interrupted transaction."""


class PatchPreviouslyFailed(PatchError):
    """Raised instead of implicitly retrying a prior failed patch."""


@dataclass(frozen=True)
class FilePatch:
    path: str | Path
    new_content: str
    expected_sha256: str | None = None


@dataclass(frozen=True)
class PatchRequest:
    patch_id: str
    idempotency_key: str
    actor: str
    reason: str
    files: Sequence[FilePatch]
    task_id: str | None = None


@dataclass(frozen=True)
class PatchFileResult:
    path: str
    operation: str
    pre_sha256: str | None
    post_sha256: str
    size_before: int | None
    size_after: int


@dataclass(frozen=True)
class PatchResult:
    patch_id: str
    idempotency_key: str
    status: str
    files: tuple[PatchFileResult, ...]
    replayed: bool = False


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PatchManager:
    """Apply UTF-8 file replacements with durable, hash-locked rollback.

    Requests can create files or replace existing files. Deletion is not an
    accepted patch operation; rollback may remove only a file created by the
    same recorded transaction.
    """

    RESERVED_ROOTS = frozenset(
        {
            ".git",
            ".venv",
            ".pytest_cache",
            ".pytest_tmp",
            "__pycache__",
            "logs",
            "outputs",
        }
    )
    RESERVED_FILES = frozenset(
        {".env", "secrets.env", "ledger.db", "ledger.db-shm", "ledger.db-wal"}
    )

    def __init__(
        self,
        guard: WorkspaceGuard,
        ledger: Ledger,
        *,
        max_file_bytes: int = 1_000_000,
        max_total_bytes: int = 4_000_000,
    ) -> None:
        if max_file_bytes <= 0 or max_total_bytes <= 0:
            raise ValueError("patch byte limits must be positive")
        if max_file_bytes > max_total_bytes:
            raise ValueError("per-file patch limit cannot exceed total limit")
        self.guard = guard
        self.ledger = ledger
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes

    @staticmethod
    def _safe_text(name: str, value: Any, maximum: int) -> str:
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise ValueError(f"{name} must be a non-empty safe string")
        if len(value) > maximum:
            raise ValueError(f"{name} exceeds {maximum} characters")
        return value

    @staticmethod
    def _validate_digest(value: str | None) -> str | None:
        if value is None:
            return None
        digest = value.casefold()
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise ValueError("expected_sha256 must be a SHA-256 hex digest")
        return digest

    def _reject_reserved(self, relative_path: str) -> None:
        parts = Path(relative_path).parts
        if not parts:
            raise WorkspaceViolation("patch path must identify a file")
        root_name = parts[0].casefold()
        file_name = parts[-1].casefold()
        if root_name in self.RESERVED_ROOTS or file_name in self.RESERVED_FILES:
            raise WorkspaceViolation(f"runtime/protected patch path: {relative_path}")
        if file_name.startswith(".env.") and file_name != ".env.example":
            raise WorkspaceViolation(f"runtime/protected patch path: {relative_path}")

    def _normalize(self, request: PatchRequest) -> tuple[list[dict[str, Any]], str]:
        self._safe_text("patch_id", request.patch_id, 200)
        self._safe_text("idempotency_key", request.idempotency_key, 500)
        self._safe_text("actor", request.actor, 200)
        self._safe_text("reason", request.reason, 2_000)
        if isinstance(request.files, (str, bytes)) or not request.files:
            raise ValueError("patch requires at least one file")

        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        total_bytes = 0
        for change in request.files:
            if not isinstance(change, FilePatch):
                raise TypeError("patch files must contain FilePatch instances")
            if not isinstance(change.new_content, str) or "\x00" in change.new_content:
                raise ValueError("patch content must be NUL-free UTF-8 text")
            content = change.new_content.encode("utf-8")
            if len(content) > self.max_file_bytes:
                raise ValueError(f"patch file exceeds {self.max_file_bytes} bytes")
            total_bytes += len(content)
            if total_bytes > self.max_total_bytes:
                raise ValueError(f"patch exceeds {self.max_total_bytes} total bytes")

            authorized = self.guard.authorize_write(
                change.path,
                expect_directory=False,
            )
            self._reject_reserved(authorized.relative_path)
            path_key = os.path.normcase(authorized.relative_path)
            if path_key in seen:
                raise ValueError(f"duplicate patch path: {authorized.relative_path}")
            seen.add(path_key)
            if not authorized.path.parent.exists() or not authorized.path.parent.is_dir():
                raise FileNotFoundError(
                    f"patch parent directory does not exist: {authorized.relative_path}"
                )

            expected = self._validate_digest(change.expected_sha256)
            if authorized.path.exists():
                if not authorized.path.is_file():
                    raise IsADirectoryError(
                        f"patch target is not a file: {authorized.relative_path}"
                    )
                if expected is None:
                    raise PatchConflict(
                        f"existing patch target requires expected_sha256: "
                        f"{authorized.relative_path}"
                    )
                backup = authorized.path.read_bytes()
                actual = hashlib.sha256(backup).hexdigest()
                if actual != expected:
                    raise PatchConflict(
                        f"patch pre-image mismatch: {authorized.relative_path}"
                    )
                operation = "replace"
                size_before: int | None = len(backup)
                pre_mode: int | None = stat.S_IMODE(authorized.path.stat().st_mode)
            else:
                if expected is not None:
                    raise PatchConflict(
                        f"missing patch target cannot match expected_sha256: "
                        f"{authorized.relative_path}"
                    )
                backup = None
                actual = None
                operation = "create"
                size_before = None
                pre_mode = None
            normalized.append(
                {
                    "path": authorized.relative_path,
                    "absolute_path": authorized.path,
                    "operation": operation,
                    "pre_sha256": actual,
                    "post_sha256": hashlib.sha256(content).hexdigest(),
                    "backup_blob": backup,
                    "pre_mode": pre_mode,
                    "size_before": size_before,
                    "size_after": len(content),
                    "content": content,
                }
            )

        return normalized, self._fingerprint(request, normalized)

    @staticmethod
    def _fingerprint(
        request: PatchRequest,
        normalized: Sequence[dict[str, Any]],
    ) -> str:
        fingerprint_payload = {
            "patch_id": request.patch_id,
            "task_id": request.task_id,
            "actor": request.actor,
            "reason": request.reason,
            "files": [
                {
                    "path": item["path"],
                    "operation": item["operation"],
                    "expected_sha256": item["pre_sha256"],
                    "post_sha256": item["post_sha256"],
                    "size_after": item["size_after"],
                }
                for item in normalized
            ],
        }
        serialized = json.dumps(
            fingerprint_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _fingerprint_existing(
        self,
        request: PatchRequest,
        existing: dict[str, Any],
    ) -> str:
        self._safe_text("patch_id", request.patch_id, 200)
        self._safe_text("idempotency_key", request.idempotency_key, 500)
        self._safe_text("actor", request.actor, 200)
        self._safe_text("reason", request.reason, 2_000)
        if isinstance(request.files, (str, bytes)) or not request.files:
            raise ValueError("patch requires at least one file")
        stored = {item["path"].casefold(): item for item in existing["files"]}
        normalized: list[dict[str, Any]] = []
        total_bytes = 0
        for change in request.files:
            if not isinstance(change, FilePatch):
                raise TypeError("patch files must contain FilePatch instances")
            if not isinstance(change.new_content, str) or "\x00" in change.new_content:
                raise ValueError("patch content must be NUL-free UTF-8 text")
            content = change.new_content.encode("utf-8")
            if len(content) > self.max_file_bytes:
                raise ValueError(f"patch file exceeds {self.max_file_bytes} bytes")
            total_bytes += len(content)
            if total_bytes > self.max_total_bytes:
                raise ValueError(f"patch exceeds {self.max_total_bytes} total bytes")
            authorized = self.guard.authorize_write(
                change.path,
                expect_directory=False,
            )
            self._reject_reserved(authorized.relative_path)
            stored_file = stored.get(authorized.relative_path.casefold())
            if stored_file is None:
                raise PatchIdempotencyConflict(
                    "patch idempotency key belongs to different paths"
                )
            expected = self._validate_digest(change.expected_sha256)
            normalized.append(
                {
                    "path": authorized.relative_path,
                    "operation": "replace" if expected is not None else "create",
                    "pre_sha256": expected,
                    "post_sha256": hashlib.sha256(content).hexdigest(),
                    "size_after": len(content),
                }
            )
        if len(normalized) != len(stored):
            raise PatchIdempotencyConflict(
                "patch idempotency key belongs to a different file count"
            )
        return self._fingerprint(request, normalized)

    def validate_request(self, request: PatchRequest) -> str:
        """Validate without writing and return the request fingerprint.

        The repair loop uses this before persisting a provider proposal.
        ``apply`` validates again so a pre-image changed after this check is
        still rejected at the actual write boundary.
        """

        _, request_sha256 = self._normalize(request)
        return request_sha256

    @staticmethod
    def _atomic_write(path: Path, content: bytes, mode: int | None) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=".ai_loop_patch_",
                suffix=".tmp",
                dir=path.parent,
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if mode is not None:
                os.chmod(temporary, mode)
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    @staticmethod
    def _file_result(record: dict[str, Any]) -> PatchFileResult:
        return PatchFileResult(
            path=str(record["path"]),
            operation=str(record["operation"]),
            pre_sha256=record.get("pre_sha256"),
            post_sha256=str(record["post_sha256"]),
            size_before=record.get("size_before"),
            size_after=int(record["size_after"]),
        )

    def _result(self, record: dict[str, Any], *, replayed: bool) -> PatchResult:
        return PatchResult(
            patch_id=str(record["patch_id"]),
            idempotency_key=str(record["idempotency_key"]),
            status=str(record["status"]),
            files=tuple(self._file_result(item) for item in record["files"]),
            replayed=replayed,
        )

    def _portable_error(self, exc: BaseException) -> str:
        return f"{type(exc).__name__}: {exc}".replace(
            str(self.guard.root), "<workspace>"
        )[:4_000]

    def apply(self, request: PatchRequest) -> PatchResult:
        existing = self.ledger.get_patch(idempotency_key=request.idempotency_key)
        if existing is not None:
            request_sha256 = self._fingerprint_existing(request, existing)
            if existing["request_sha256"] != request_sha256:
                raise PatchIdempotencyConflict(
                    "patch idempotency key belongs to different content"
                )
            if existing["status"] in {"applied", "rolled_back"}:
                return self._result(existing, replayed=True)
            if existing["status"] in {
                "prepared",
                "rolling_back",
                "recovery_required",
            }:
                raise PatchRecoveryRequired(
                    f"patch requires recovery from state: {existing['status']}"
                )
            raise PatchPreviouslyFailed(existing.get("error") or "patch previously failed")

        normalized, request_sha256 = self._normalize(request)
        claimed, record = self.ledger.claim_patch(
            patch_id=request.patch_id,
            task_id=request.task_id,
            actor=request.actor,
            reason=request.reason,
            idempotency_key=request.idempotency_key,
            request_sha256=request_sha256,
            files=normalized,
        )
        if not claimed:
            if record["request_sha256"] != request_sha256:
                raise PatchIdempotencyConflict(
                    "patch idempotency key belongs to different content"
                )
            if record["status"] in {"applied", "rolled_back"}:
                return self._result(record, replayed=True)
            if record["status"] in {"prepared", "rolling_back", "recovery_required"}:
                raise PatchRecoveryRequired(
                    f"patch requires recovery from state: {record['status']}"
                )
            raise PatchPreviouslyFailed(record.get("error") or "patch previously failed")

        applied: list[dict[str, Any]] = []
        try:
            for item in normalized:
                self._atomic_write(
                    item["absolute_path"],
                    item["content"],
                    item["pre_mode"],
                )
                applied.append(item)
                if file_sha256(item["absolute_path"]) != item["post_sha256"]:
                    raise OSError(
                        f"post-write hash mismatch: {item['path']}"
                    )
            stored = self.ledger.complete_patch(request.patch_id)
            return self._result(stored, replayed=False)
        except Exception as exc:
            rollback_error: BaseException | None = None
            try:
                self._restore_applied(applied)
            except Exception as restore_exc:
                rollback_error = restore_exc
            error = self._portable_error(exc)
            if rollback_error is not None:
                error += "; rollback: " + self._portable_error(rollback_error)
            self.ledger.fail_patch(
                request.patch_id,
                error,
                recovery_required=rollback_error is not None,
            )
            if rollback_error is not None:
                raise PatchRecoveryRequired(error) from exc
            raise PatchError(error) from exc

    def _restore_applied(self, applied: Sequence[dict[str, Any]]) -> None:
        for item in reversed(applied):
            path = Path(item["absolute_path"])
            if item["operation"] == "create":
                if path.exists():
                    if file_sha256(path) != item["post_sha256"]:
                        raise PatchConflict(
                            f"created file changed before rollback: {item['path']}"
                        )
                    path.unlink()
            else:
                backup = item["backup_blob"]
                assert isinstance(backup, bytes)
                self._atomic_write(path, backup, item["pre_mode"])

    def rollback(self, patch_id: str) -> PatchResult:
        record = self.ledger.get_patch(patch_id=patch_id)
        if record is None:
            raise KeyError(f"unknown patch: {patch_id}")
        if record["status"] == "rolled_back":
            return self._result(record, replayed=True)
        if record["status"] != "applied":
            raise PatchRecoveryRequired(
                f"patch cannot roll back from state: {record['status']}"
            )

        prepared: list[dict[str, Any]] = []
        for item in record["files"]:
            authorized = self.guard.authorize_write(
                item["path"],
                expect_directory=False,
            )
            self._reject_reserved(authorized.relative_path)
            if not authorized.path.exists():
                raise PatchConflict(f"patched file is missing: {item['path']}")
            if file_sha256(authorized.path) != item["post_sha256"]:
                raise PatchConflict(f"patched file changed: {item['path']}")
            prepared.append({**item, "absolute_path": authorized.path})

        self.ledger.begin_patch_rollback(patch_id)
        try:
            self._restore_applied(prepared)
            stored = self.ledger.complete_patch_rollback(patch_id)
            return self._result(stored, replayed=False)
        except Exception as exc:
            error = self._portable_error(exc)
            self.ledger.fail_patch(
                patch_id,
                error,
                recovery_required=True,
            )
            raise PatchRecoveryRequired(error) from exc
