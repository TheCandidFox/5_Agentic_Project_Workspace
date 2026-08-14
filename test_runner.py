from __future__ import annotations

import hashlib
import json
import math
import os
import time
import tokenize
import uuid
from dataclasses import dataclass, field, fields, is_dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, TypeAlias

from command_runner import CommandOutcome, CommandRequest, CommandResult
from workspace_guard import WorkspaceGuard, WorkspaceViolation


class ValidationOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ValidationKind(str, Enum):
    PYTHON_SYNTAX = "PYTHON_SYNTAX"
    PYTEST = "PYTEST"
    COMMAND = "COMMAND"
    FILE = "FILE"
    JSON = "JSON"


class ValidationIdempotencyConflict(RuntimeError):
    """Raised when one validation key is reused for a different check."""


class CommandExecutor(Protocol):
    def run(self, request: CommandRequest) -> CommandResult: ...


class ValidationStore(Protocol):
    def get_validation(self, idempotency_key: str) -> Mapping[str, Any] | None: ...

    def record_validation(self, record: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True, kw_only=True)
class ValidationCheck:
    check_id: str
    task_id: str | None = None
    action_id: str | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.check_id, str) or not self.check_id.strip():
            raise ValueError("check_id must be a non-empty string")
        for name in ("task_id", "action_id", "idempotency_key"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str) or not value.strip() or "\x00" in value
            ):
                raise ValueError(f"{name} must be a non-empty safe string when set")


@dataclass(frozen=True, kw_only=True)
class PythonSyntaxCheck(ValidationCheck):
    paths: tuple[str | Path, ...] = (".",)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.paths:
            raise ValueError("Python syntax checks require at least one path")


@dataclass(frozen=True, kw_only=True)
class PytestCheck(ValidationCheck):
    arguments: tuple[str, ...] = ("-q",)
    cwd: str | Path = "."
    timeout_seconds: float = 120.0
    max_output_bytes: int | None = None
    environment: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not all(
            isinstance(argument, str) and "\x00" not in argument
            for argument in self.arguments
        ):
            raise ValueError("pytest arguments must be strings")
        if not isinstance(self.timeout_seconds, (int, float)) or not math.isfinite(
            self.timeout_seconds
        ) or self.timeout_seconds <= 0:
            raise ValueError("pytest timeout_seconds must be a positive finite number")
        if self.max_output_bytes is not None and (
            not isinstance(self.max_output_bytes, int)
            or isinstance(self.max_output_bytes, bool)
            or self.max_output_bytes <= 0
        ):
            raise ValueError("pytest max_output_bytes must be a positive integer")
        if not isinstance(self.environment, Mapping):
            raise ValueError("pytest environment must be a mapping")


@dataclass(frozen=True, kw_only=True)
class CommandCheck(ValidationCheck):
    request: CommandRequest


@dataclass(frozen=True, kw_only=True)
class FileCheck(ValidationCheck):
    path: str | Path
    must_exist: bool = True
    expect_directory: bool = False
    min_size_bytes: int | None = None
    expected_sha256: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.min_size_bytes is not None and (
            not isinstance(self.min_size_bytes, int)
            or isinstance(self.min_size_bytes, bool)
            or self.min_size_bytes < 0
        ):
            raise ValueError("min_size_bytes must be a non-negative integer")
        if self.expect_directory and (
            self.min_size_bytes is not None or self.expected_sha256 is not None
        ):
            raise ValueError("directory checks cannot use size or hash assertions")
        if self.expected_sha256 is not None:
            digest = self.expected_sha256.casefold()
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ValueError("expected_sha256 must be a 64-character hex digest")
            object.__setattr__(self, "expected_sha256", digest)


@dataclass(frozen=True, kw_only=True)
class JsonCheck(ValidationCheck):
    path: str | Path
    root_type: str = "object"
    required_keys: tuple[str, ...] = ()
    expected_values: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.root_type not in {"object", "array", "any"}:
            raise ValueError("root_type must be object, array, or any")
        if not all(isinstance(key, str) and key for key in self.required_keys):
            raise ValueError("required JSON keys must be non-empty strings")
        if not isinstance(self.expected_values, Mapping):
            raise ValueError("expected JSON values must be a mapping")


AnyValidationCheck: TypeAlias = (
    PythonSyntaxCheck | PytestCheck | CommandCheck | FileCheck | JsonCheck
)


@dataclass(frozen=True)
class ValidationResult:
    validation_id: str
    check_id: str
    kind: ValidationKind
    outcome: ValidationOutcome
    summary: str
    details: Mapping[str, Any]
    started_at: str
    completed_at: str
    duration_ms: int
    task_id: str | None = None
    action_id: str | None = None
    idempotency_key: str | None = None
    command_id: str | None = None
    spec_sha256: str | None = None
    replayed: bool = False

    def to_record(self) -> dict[str, Any]:
        return {
            "validation_id": self.validation_id,
            "check_id": self.check_id,
            "kind": self.kind.value,
            "outcome": self.outcome.value,
            "summary": self.summary,
            "details": dict(self.details),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "task_id": self.task_id,
            "action_id": self.action_id,
            "idempotency_key": self.idempotency_key,
            "command_id": self.command_id,
            "spec_sha256": self.spec_sha256,
        }

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        replayed: bool,
    ) -> "ValidationResult":
        details = record.get("details", {})
        if isinstance(details, str):
            details = json.loads(details)
        return cls(
            validation_id=str(record["validation_id"]),
            check_id=str(record["check_id"]),
            kind=ValidationKind(str(record["kind"])),
            outcome=ValidationOutcome(str(record["outcome"])),
            summary=str(record["summary"]),
            details=dict(details),
            started_at=str(record["started_at"]),
            completed_at=str(record["completed_at"]),
            duration_ms=int(record["duration_ms"]),
            task_id=record.get("task_id"),
            action_id=record.get("action_id"),
            idempotency_key=record.get("idempotency_key"),
            command_id=record.get("command_id"),
            spec_sha256=record.get("spec_sha256"),
            replayed=replayed,
        )


@dataclass(frozen=True)
class ValidationSuiteResult:
    outcome: ValidationOutcome
    results: tuple[ValidationResult, ...]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_value(value: Any) -> Any:
    if is_dataclass(value):
        return {
            "type": type(value).__name__,
            "fields": {
                item.name: _canonical_value(getattr(value, item.name))
                for item in fields(value)
            },
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported validation specification value: {type(value).__name__}")


def validation_spec_sha256(check: AnyValidationCheck) -> str:
    serialized = json.dumps(
        _canonical_value(check),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_python_files(
    guard: WorkspaceGuard,
    requested_paths: Sequence[str | Path] = (".",),
) -> dict[str, Path]:
    """Return authorized Python files while pruning runtime/protected trees."""

    skipped_directories = {
        "__pycache__",
        ".pytest_cache",
        ".pytest_tmp",
        "outputs",
        "logs",
        *guard.protected_names,
    }
    candidates: dict[str, Path] = {}
    for requested in requested_paths:
        authorized = guard.authorize_read(requested)
        if authorized.path.is_file():
            if authorized.path.suffix.casefold() == ".py":
                candidates[authorized.relative_path] = authorized.path
            continue
        for directory, directory_names, file_names in os.walk(
            authorized.path,
            topdown=True,
            followlinks=False,
        ):
            safe_directories: list[str] = []
            for name in directory_names:
                if name.casefold() in skipped_directories:
                    continue
                candidate = Path(directory, name)
                lexical = candidate.relative_to(guard.root).as_posix()
                try:
                    guard.authorize_read(lexical, expect_directory=True)
                except (OSError, WorkspaceViolation):
                    continue
                safe_directories.append(name)
            directory_names[:] = safe_directories

            for name in file_names:
                if Path(name).suffix.casefold() != ".py":
                    continue
                candidate = Path(directory, name)
                lexical = candidate.relative_to(guard.root).as_posix()
                try:
                    safe = guard.authorize_read(lexical, expect_directory=False)
                except (OSError, WorkspaceViolation):
                    continue
                candidates[safe.relative_path] = safe.path
    return candidates


class TestRunner:
    """Normalize deterministic checks and allowlisted command validation."""

    __test__ = False
    _DETAIL_PREVIEW = 4_000

    def __init__(
        self,
        guard: WorkspaceGuard,
        *,
        command_runner: CommandExecutor | None = None,
        store: ValidationStore | None = None,
    ) -> None:
        self.guard = guard
        self.command_runner = command_runner
        self.store = store

    def run(self, check: AnyValidationCheck) -> ValidationResult:
        if not isinstance(
            check,
            (PythonSyntaxCheck, PytestCheck, CommandCheck, FileCheck, JsonCheck),
        ):
            raise TypeError("unsupported validation check type")

        spec_sha256 = validation_spec_sha256(check)
        if self.store is not None and check.idempotency_key is not None:
            existing = self.store.get_validation(check.idempotency_key)
            if existing is not None:
                if existing.get("spec_sha256") != spec_sha256:
                    raise ValidationIdempotencyConflict(
                        "validation idempotency key belongs to a different check"
                    )
                return ValidationResult.from_record(existing, replayed=True)

        started_at = _utc_now()
        started = time.perf_counter()
        validation_id = str(uuid.uuid4())
        try:
            outcome, summary, details, command_id = self._execute(check)
        except WorkspaceViolation as exc:
            outcome = ValidationOutcome.ERROR
            summary = "validation could not access an authorized workspace input"
            details = {"error_type": type(exc).__name__}
            command_id = None
        except PermissionError as exc:
            outcome = ValidationOutcome.ERROR
            summary = "validation was denied by execution policy"
            details = {"error_type": type(exc).__name__}
            command_id = None
        except (OSError, UnicodeError) as exc:
            outcome = ValidationOutcome.ERROR
            summary = "validation could not read or execute its input"
            details = {"error_type": type(exc).__name__}
            command_id = None
        except Exception as exc:
            outcome = ValidationOutcome.ERROR
            summary = "validation raised an unexpected error"
            details = {
                "error_type": type(exc).__name__,
                "error": str(exc)[: self._DETAIL_PREVIEW],
            }
            command_id = None
        completed_at = _utc_now()
        result = ValidationResult(
            validation_id=validation_id,
            check_id=check.check_id,
            kind=self._kind(check),
            outcome=outcome,
            summary=summary,
            details=details,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=int((time.perf_counter() - started) * 1000),
            task_id=check.task_id,
            action_id=check.action_id,
            idempotency_key=check.idempotency_key,
            command_id=command_id,
            spec_sha256=spec_sha256,
        )
        if self.store is None:
            return result

        stored = self.store.record_validation(result.to_record())
        if stored.get("spec_sha256") != spec_sha256:
            raise ValidationIdempotencyConflict(
                "validation idempotency key was concurrently used by a different check"
            )
        return ValidationResult.from_record(
            stored,
            replayed=str(stored["validation_id"]) != validation_id,
        )

    def run_suite(
        self,
        checks: Sequence[AnyValidationCheck],
        *,
        stop_on_failure: bool = False,
    ) -> ValidationSuiteResult:
        results: list[ValidationResult] = []
        for check in checks:
            result = self.run(check)
            results.append(result)
            if stop_on_failure and result.outcome not in {
                ValidationOutcome.PASS,
                ValidationOutcome.NOT_APPLICABLE,
            }:
                break
        return ValidationSuiteResult(
            outcome=self._suite_outcome(results),
            results=tuple(results),
        )

    @staticmethod
    def _kind(check: AnyValidationCheck) -> ValidationKind:
        if isinstance(check, PythonSyntaxCheck):
            return ValidationKind.PYTHON_SYNTAX
        if isinstance(check, PytestCheck):
            return ValidationKind.PYTEST
        if isinstance(check, CommandCheck):
            return ValidationKind.COMMAND
        if isinstance(check, FileCheck):
            return ValidationKind.FILE
        return ValidationKind.JSON

    @staticmethod
    def _suite_outcome(results: Sequence[ValidationResult]) -> ValidationOutcome:
        outcomes = {result.outcome for result in results}
        for outcome in (
            ValidationOutcome.ERROR,
            ValidationOutcome.TIMEOUT,
            ValidationOutcome.FAIL,
        ):
            if outcome in outcomes:
                return outcome
        if ValidationOutcome.PASS in outcomes:
            return ValidationOutcome.PASS
        return ValidationOutcome.NOT_APPLICABLE

    def _execute(
        self,
        check: AnyValidationCheck,
    ) -> tuple[ValidationOutcome, str, dict[str, Any], str | None]:
        if isinstance(check, PythonSyntaxCheck):
            outcome, summary, details = self._python_syntax(check)
            return outcome, summary, details, None
        if isinstance(check, PytestCheck):
            request = CommandRequest(
                argv=("python", "-m", "pytest", *check.arguments),
                cwd=check.cwd,
                timeout_seconds=check.timeout_seconds,
                max_output_bytes=check.max_output_bytes,
                environment=check.environment,
                task_id=check.task_id,
                action_id=check.action_id or check.check_id,
                idempotency_key=(
                    f"{check.idempotency_key}:command"
                    if check.idempotency_key is not None
                    else None
                ),
            )
            return self._command(request)
        if isinstance(check, CommandCheck):
            request = check.request
            if request.task_id is None and check.task_id is not None:
                request = replace(request, task_id=check.task_id)
            if request.action_id is None:
                request = replace(request, action_id=check.action_id or check.check_id)
            if request.idempotency_key is None and check.idempotency_key is not None:
                request = replace(
                    request,
                    idempotency_key=f"{check.idempotency_key}:command",
                )
            return self._command(request)
        if isinstance(check, FileCheck):
            outcome, summary, details = self._file(check)
            return outcome, summary, details, None
        outcome, summary, details = self._json(check)
        return outcome, summary, details, None

    def _python_syntax(
        self,
        check: PythonSyntaxCheck,
    ) -> tuple[ValidationOutcome, str, dict[str, Any]]:
        candidates = discover_python_files(self.guard, check.paths)

        if not candidates:
            return (
                ValidationOutcome.NOT_APPLICABLE,
                "no Python files matched the syntax check",
                {"files_checked": 0},
            )

        failures: list[dict[str, Any]] = []
        for relative, path in sorted(candidates.items()):
            try:
                with tokenize.open(path) as stream:
                    source = stream.read()
                compile(source, relative, "exec")
            except (SyntaxError, UnicodeError, ValueError) as exc:
                failures.append(
                    {
                        "path": relative,
                        "line": getattr(exc, "lineno", None),
                        "offset": getattr(exc, "offset", None),
                        "message": str(exc)[: self._DETAIL_PREVIEW],
                    }
                )

        details = {
            "files_checked": len(candidates),
            "failures": failures,
        }
        if failures:
            return ValidationOutcome.FAIL, "Python syntax validation failed", details
        return ValidationOutcome.PASS, "Python syntax validation passed", details

    def _command(
        self,
        request: CommandRequest,
    ) -> tuple[ValidationOutcome, str, dict[str, Any], str | None]:
        if self.command_runner is None:
            return (
                ValidationOutcome.ERROR,
                "no command runner is configured",
                {},
                None,
            )
        result = self.command_runner.run(request)
        outcome = {
            CommandOutcome.PASS: ValidationOutcome.PASS,
            CommandOutcome.FAIL: ValidationOutcome.FAIL,
            CommandOutcome.ERROR: ValidationOutcome.ERROR,
            CommandOutcome.TIMEOUT: ValidationOutcome.TIMEOUT,
        }[result.outcome]
        details = {
            "argv": list(result.argv),
            "cwd": result.cwd,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "stdout_preview": result.stdout[: self._DETAIL_PREVIEW],
            "stderr_preview": result.stderr[: self._DETAIL_PREVIEW],
            "stdout_tail": result.stdout[-self._DETAIL_PREVIEW :],
            "stderr_tail": result.stderr[-self._DETAIL_PREVIEW :],
            "stdout_sha256": hashlib.sha256(result.stdout.encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(result.stderr.encode("utf-8")).hexdigest(),
            "stdout_truncated": result.stdout_truncated,
            "stderr_truncated": result.stderr_truncated,
            "error": result.error,
            "command_replayed": result.replayed,
        }
        summary = f"command validation {outcome.value.lower()}"
        return outcome, summary, details, result.command_id

    def _file(
        self,
        check: FileCheck,
    ) -> tuple[ValidationOutcome, str, dict[str, Any]]:
        try:
            authorized = self.guard.authorize_read(
                check.path,
                expect_directory=check.expect_directory,
            )
        except FileNotFoundError:
            outcome = ValidationOutcome.FAIL if check.must_exist else ValidationOutcome.PASS
            return outcome, "file presence assertion evaluated", {"exists": False}

        details: dict[str, Any] = {
            "path": authorized.relative_path,
            "exists": True,
            "is_directory": authorized.path.is_dir(),
        }
        failures: list[str] = []
        if check.min_size_bytes is not None:
            size = authorized.path.stat().st_size
            details["size_bytes"] = size
            if size < check.min_size_bytes:
                failures.append("file is smaller than the required minimum")
        if check.expected_sha256 is not None:
            digest = _file_sha256(authorized.path)
            details["sha256"] = digest
            if digest != check.expected_sha256:
                failures.append("file hash does not match")
        details["failures"] = failures
        if failures:
            return ValidationOutcome.FAIL, "file assertion failed", details
        return ValidationOutcome.PASS, "file assertion passed", details

    def _json(
        self,
        check: JsonCheck,
    ) -> tuple[ValidationOutcome, str, dict[str, Any]]:
        authorized = self.guard.authorize_read(check.path, expect_directory=False)
        try:
            with authorized.path.open("r", encoding="utf-8") as stream:
                document = json.load(stream)
        except json.JSONDecodeError as exc:
            return (
                ValidationOutcome.FAIL,
                "JSON parsing failed",
                {
                    "path": authorized.relative_path,
                    "line": exc.lineno,
                    "column": exc.colno,
                    "message": exc.msg,
                },
            )

        failures: list[str] = []
        if check.root_type == "object" and not isinstance(document, dict):
            failures.append("JSON root is not an object")
        if check.root_type == "array" and not isinstance(document, list):
            failures.append("JSON root is not an array")

        if (check.required_keys or check.expected_values) and not isinstance(document, dict):
            failures.append("key assertions require an object root")
        elif isinstance(document, dict):
            missing = sorted(key for key in check.required_keys if key not in document)
            if missing:
                failures.append("missing required keys: " + ", ".join(missing))
            for key, expected in check.expected_values.items():
                if key not in document:
                    failures.append(f"missing expected-value key: {key}")
                elif document[key] != expected:
                    failures.append(f"value does not match for key: {key}")

        details = {
            "path": authorized.relative_path,
            "root_type": type(document).__name__,
            "failures": failures,
        }
        if failures:
            return ValidationOutcome.FAIL, "JSON assertion failed", details
        return ValidationOutcome.PASS, "JSON assertion passed", details
