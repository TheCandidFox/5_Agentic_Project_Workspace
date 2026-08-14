from __future__ import annotations

import codecs
import hashlib
import json
import math
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import ClassVar, Iterable, Mapping, Protocol, Sequence

from workspace_guard import AccessMode, WorkspaceGuard, WorkspaceViolation


_SENSITIVE_ENVIRONMENT_NAME = re.compile(
    r"(?i)(?:API_?KEY|TOKEN|SECRET|PASSWORD)"
)


class CommandDenied(PermissionError):
    """Raised before dispatch when a command violates application policy."""


class CommandOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True)
class ExecutableRule:
    alias: str
    executable: Path
    allowed_argument_prefixes: tuple[tuple[str, ...], ...] = ()
    allow_any_arguments: bool = False

    def __post_init__(self) -> None:
        alias = self.alias.strip()
        if not alias or any(separator in alias for separator in ("/", "\\")):
            raise ValueError("executable alias must be a non-empty basename")
        executable = Path(self.executable).expanduser().resolve(strict=True)
        if not executable.is_file():
            raise FileNotFoundError(f"allowed executable is not a file: {executable}")
        object.__setattr__(self, "alias", alias)
        object.__setattr__(self, "executable", executable)
        if self.allow_any_arguments and self.allowed_argument_prefixes:
            raise ValueError("allow_any_arguments cannot be combined with argument prefixes")
        for prefix in self.allowed_argument_prefixes:
            if not prefix:
                raise ValueError("allowed argument prefixes must not be empty")
            if not all(isinstance(value, str) and "\x00" not in value for value in prefix):
                raise ValueError("argument prefixes must contain valid strings")

    def permits(self, arguments: tuple[str, ...]) -> bool:
        if self.allow_any_arguments:
            return True
        if not arguments:
            return not self.allowed_argument_prefixes
        return any(
            arguments[: len(prefix)] == prefix
            for prefix in self.allowed_argument_prefixes
        )


@dataclass(frozen=True)
class CommandPolicy:
    rules: tuple[ExecutableRule, ...]
    allowed_environment_keys: frozenset[str] = frozenset()
    inherited_environment_keys: tuple[str, ...] = (
        "SystemRoot",
        "WINDIR",
        "TEMP",
        "TMP",
        "TMPDIR",
        "LANG",
        "LC_ALL",
    )
    max_timeout_seconds: float = 300.0
    max_output_bytes: int = 1_000_000
    allow_shell_executables: bool = False
    allow_sensitive_inherited_environment: bool = False

    SHELL_NAMES: ClassVar[frozenset[str]] = frozenset(
        {
            "cmd",
            "cmd.exe",
            "powershell",
            "powershell.exe",
            "pwsh",
            "pwsh.exe",
            "sh",
            "bash",
            "zsh",
            "fish",
            "wsl",
            "wsl.exe",
            "cscript.exe",
            "wscript.exe",
        }
    )

    def __post_init__(self) -> None:
        if not self.rules:
            raise ValueError("at least one executable rule is required")
        if not all(isinstance(rule, ExecutableRule) for rule in self.rules):
            raise TypeError("rules must contain only ExecutableRule instances")
        if not isinstance(self.max_timeout_seconds, (int, float)) or not math.isfinite(
            self.max_timeout_seconds
        ):
            raise ValueError("max_timeout_seconds must be a finite number")
        if self.max_timeout_seconds <= 0:
            raise ValueError("max_timeout_seconds must be positive")
        if not isinstance(self.max_output_bytes, int) or isinstance(
            self.max_output_bytes, bool
        ):
            raise ValueError("max_output_bytes must be an integer")
        if self.max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")

        aliases = [rule.alias.casefold() for rule in self.rules]
        if len(set(aliases)) != len(aliases):
            raise ValueError("executable aliases must be unique")
        if not self.allow_shell_executables:
            for rule in self.rules:
                if (
                    rule.alias.casefold() in self.SHELL_NAMES
                    or rule.executable.name.casefold() in self.SHELL_NAMES
                ):
                    raise ValueError(
                        f"shell executable requires explicit opt-in: {rule.executable.name}"
                    )

        for key in self.allowed_environment_keys:
            if not isinstance(key, str) or not key or "\x00" in key or "=" in key:
                raise ValueError("allowed environment keys must be valid names")
        normalized_keys = frozenset(key.casefold() for key in self.allowed_environment_keys)
        object.__setattr__(self, "allowed_environment_keys", normalized_keys)
        for key in self.inherited_environment_keys:
            if not isinstance(key, str) or not key or "\x00" in key or "=" in key:
                raise ValueError("inherited environment keys must be valid names")
            if (
                _SENSITIVE_ENVIRONMENT_NAME.search(key)
                and not self.allow_sensitive_inherited_environment
            ):
                raise ValueError(
                    f"sensitive inherited environment key requires explicit opt-in: {key}"
                )

    def resolve_rule(self, token: str) -> ExecutableRule:
        if not token or "\x00" in token:
            raise CommandDenied("invalid executable token")

        if Path(token).is_absolute() or any(separator in token for separator in ("/", "\\")):
            try:
                requested = Path(token).expanduser().resolve(strict=True)
            except OSError as exc:
                raise CommandDenied(f"executable cannot be resolved: {token}") from exc
            requested_key = os.path.normcase(str(requested))
            for rule in self.rules:
                if os.path.normcase(str(rule.executable)) == requested_key:
                    return rule
        else:
            alias = token.casefold()
            for rule in self.rules:
                if rule.alias.casefold() == alias:
                    return rule
        raise CommandDenied(f"executable is not allowlisted: {token}")


@dataclass(frozen=True)
class CommandRequest:
    argv: Sequence[str]
    cwd: str | Path = "."
    timeout_seconds: float = 60.0
    max_output_bytes: int | None = None
    environment: Mapping[str, str] = field(default_factory=dict)
    task_id: str | None = None
    action_id: str | None = None
    idempotency_key: str | None = None
    encoding: str = "utf-8"


@dataclass(frozen=True)
class CommandResult:
    outcome: CommandOutcome
    argv: tuple[str, ...]
    executable: str
    cwd: str
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    duration_ms: int
    started_at: str
    completed_at: str
    task_id: str | None
    action_id: str | None
    idempotency_key: str | None
    error: str | None = None
    command_id: str | None = None
    replayed: bool = False


class CommandEventSink(Protocol):
    def record(self, event: Mapping[str, object]) -> None: ...


class SecretRedactor:
    _KEY_ASSIGNMENT = re.compile(
        r"(?i)((?:OPENAI|ANTHROPIC|GOOGLE|GITHUB|GITLAB|AWS)?_?"
        r"(?:API_?KEY|TOKEN|SECRET|PASSWORD)\s*[=:]\s*)([^\s'\"]+)"
    )
    _BEARER = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)([^\s]+)")
    _PROVIDER_KEY = re.compile(r"(?i)\bsk-(?:ant-)?[A-Za-z0-9_-]{8,}\b")
    _SENSITIVE_NAME = _SENSITIVE_ENVIRONMENT_NAME

    def __init__(self, explicit_secrets: Iterable[str] = ()) -> None:
        self._explicit = tuple(
            sorted(
                {secret for secret in explicit_secrets if secret},
                key=len,
                reverse=True,
            )
        )

    def redact(self, value: str) -> str:
        redacted = value
        for secret in self._explicit:
            redacted = redacted.replace(secret, "[REDACTED]")
        redacted = self._KEY_ASSIGNMENT.sub(r"\1[REDACTED]", redacted)
        redacted = self._BEARER.sub(r"\1[REDACTED]", redacted)
        return self._PROVIDER_KEY.sub("[REDACTED]", redacted)

    def with_environment_secrets(self, environment: Mapping[str, str]) -> "SecretRedactor":
        environment_secrets = (
            value
            for key, value in environment.items()
            if self._SENSITIVE_NAME.search(key)
        )
        return SecretRedactor((*self._explicit, *environment_secrets))


class JsonlCommandEventSink:
    """Append compact, already-redacted command events inside the workspace."""

    def __init__(
        self,
        guard: WorkspaceGuard,
        path: str | Path = "logs/command_events.jsonl",
    ) -> None:
        self.guard = guard
        self.path = path
        self._lock = threading.Lock()
        self.guard.authorize_write(self.path, expect_directory=False)

    def record(self, event: Mapping[str, object]) -> None:
        authorized = self.guard.authorize_write(self.path, expect_directory=False)
        authorized.path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(dict(event), sort_keys=True, ensure_ascii=False)
        with self._lock:
            with authorized.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(serialized + "\n")
                stream.flush()
                os.fsync(stream.fileno())


class _CappedCapture:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.data = bytearray()
        self.total_bytes = 0

    @property
    def truncated(self) -> bool:
        return self.total_bytes > len(self.data)

    def append(self, chunk: bytes) -> None:
        self.total_bytes += len(chunk)
        remaining = self.limit - len(self.data)
        if remaining > 0:
            self.data.extend(chunk[:remaining])


def _drain(stream, capture: _CappedCapture) -> None:
    try:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                return
            capture.append(chunk)
    except (OSError, ValueError):
        return


class CommandRunner:
    """Run structured, allowlisted commands without invoking a shell."""

    def __init__(
        self,
        guard: WorkspaceGuard,
        policy: CommandPolicy,
        *,
        redactor: SecretRedactor | None = None,
        event_sink: CommandEventSink | None = None,
    ) -> None:
        self.guard = guard
        self.policy = policy
        self.redactor = redactor or SecretRedactor()
        self.event_sink = event_sink

    def _validate_request(
        self, request: CommandRequest
    ) -> tuple[ExecutableRule, tuple[str, ...], Path, str, int, dict[str, str]]:
        if isinstance(request.argv, (str, bytes)) or not isinstance(
            request.argv, Sequence
        ):
            raise CommandDenied("argv must be a sequence of separate arguments")
        argv = tuple(request.argv)
        if not argv or not all(isinstance(argument, str) for argument in argv):
            raise CommandDenied("argv must contain at least one string")
        if any("\x00" in argument for argument in argv):
            raise CommandDenied("command arguments must not contain NUL bytes")

        rule = self.policy.resolve_rule(argv[0])
        arguments = argv[1:]
        if not rule.permits(arguments):
            raise CommandDenied(f"arguments are not allowed for executable: {rule.alias}")

        if not isinstance(request.timeout_seconds, (int, float)) or not math.isfinite(
            request.timeout_seconds
        ):
            raise CommandDenied("timeout_seconds must be a finite number")
        if request.timeout_seconds <= 0:
            raise CommandDenied("timeout_seconds must be positive")
        if request.timeout_seconds > self.policy.max_timeout_seconds:
            raise CommandDenied(
                f"timeout exceeds policy maximum: {request.timeout_seconds} > "
                f"{self.policy.max_timeout_seconds}"
            )

        output_limit = (
            self.policy.max_output_bytes
            if request.max_output_bytes is None
            else request.max_output_bytes
        )
        if not isinstance(output_limit, int) or isinstance(output_limit, bool):
            raise CommandDenied("max_output_bytes must be an integer")
        if output_limit <= 0 or output_limit > self.policy.max_output_bytes:
            raise CommandDenied("max_output_bytes is outside policy bounds")

        try:
            codecs.lookup(request.encoding)
        except (LookupError, TypeError) as exc:
            raise CommandDenied(f"unknown output encoding: {request.encoding}") from exc

        try:
            cwd = self.guard.authorize_directory(
                request.cwd,
                access=AccessMode.EXECUTE,
            )
        except (OSError, WorkspaceViolation) as exc:
            raise CommandDenied(str(exc)) from exc

        child_environment: dict[str, str] = {}
        for key in self.policy.inherited_environment_keys:
            value = os.environ.get(key)
            if value is not None:
                child_environment[key] = value

        if not isinstance(request.environment, Mapping):
            raise CommandDenied("environment must be a mapping")
        for key, value in request.environment.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise CommandDenied("environment keys and values must be strings")
            if "\x00" in key or "=" in key or "\x00" in value:
                raise CommandDenied("invalid environment entry")
            if key.casefold() not in self.policy.allowed_environment_keys:
                raise CommandDenied(f"environment key is not allowlisted: {key}")
            child_environment[key] = value

        return rule, arguments, cwd.path, cwd.relative_path, output_limit, child_environment

    def _event_for(self, result: CommandResult) -> dict[str, object]:
        preview_limit = 1000
        return {
            "event_type": "command_completed",
            "task_id": result.task_id,
            "action_id": result.action_id,
            "idempotency_key": result.idempotency_key,
            "outcome": result.outcome.value,
            "argv": list(result.argv),
            "executable_alias": result.argv[0],
            "cwd": result.cwd,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "stdout_truncated": result.stdout_truncated,
            "stderr_truncated": result.stderr_truncated,
            "stdout_sha256": hashlib.sha256(result.stdout.encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(result.stderr.encode("utf-8")).hexdigest(),
            "stdout_preview": result.stdout[:preview_limit],
            "stderr_preview": result.stderr[:preview_limit],
            "error": result.error,
            "command_id": result.command_id,
            "replayed": result.replayed,
        }

    def describe_request(self, request: CommandRequest) -> dict[str, object]:
        """Validate a request and return a portable, redacted description.

        The resolved executable path is returned separately for immediate
        runtime use. Durable fields contain the allowlist alias and a
        workspace-relative working directory rather than machine-specific
        absolute paths.
        """

        rule, arguments, _, relative_cwd, output_limit, _ = self._validate_request(
            request
        )
        run_redactor = self.redactor.with_environment_secrets(request.environment)
        display_argv = tuple(
            run_redactor.redact(value) for value in (rule.alias, *arguments)
        )
        return {
            "argv": display_argv,
            "executable_alias": rule.alias,
            "resolved_executable": str(rule.executable),
            "cwd": relative_cwd,
            "timeout_seconds": float(request.timeout_seconds),
            "max_output_bytes": output_limit,
            "encoding": request.encoding,
            "environment_keys": sorted(request.environment, key=str.casefold),
        }

    def run(
        self,
        request: CommandRequest,
        *,
        command_id: str | None = None,
    ) -> CommandResult:
        rule, arguments, cwd, relative_cwd, output_limit, child_environment = (
            self._validate_request(request)
        )
        command = [str(rule.executable), *arguments]
        run_redactor = self.redactor.with_environment_secrets(request.environment)
        display_argv = tuple(run_redactor.redact(value) for value in (rule.alias, *arguments))

        stdout_capture = _CappedCapture(output_limit)
        stderr_capture = _CappedCapture(output_limit)
        started_at = datetime.now(timezone.utc).isoformat()
        started = time.perf_counter()
        process: subprocess.Popen[bytes] | None = None
        timed_out = False
        spawn_error: str | None = None

        popen_options: dict[str, object] = {
            "cwd": cwd,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "env": child_environment,
            "shell": False,
        }
        if os.name == "nt":
            popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_options["start_new_session"] = True

        threads: list[threading.Thread] = []
        try:
            process = subprocess.Popen(command, **popen_options)
            assert process.stdout is not None
            assert process.stderr is not None
            threads = [
                threading.Thread(
                    target=_drain,
                    args=(process.stdout, stdout_capture),
                    daemon=True,
                ),
                threading.Thread(
                    target=_drain,
                    args=(process.stderr, stderr_capture),
                    daemon=True,
                ),
            ]
            for thread in threads:
                thread.start()
            try:
                process.wait(timeout=request.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                process.wait(timeout=5)
        except OSError as exc:
            portable_error = repr(exc).replace(
                str(rule.executable),
                f"<executable:{rule.alias}>",
            ).replace(
                str(cwd),
                f"<workspace:{relative_cwd}>",
            )
            spawn_error = run_redactor.redact(portable_error)
        finally:
            for thread in threads:
                thread.join(timeout=2)
            if process is not None:
                for stream in (process.stdout, process.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()

        duration_ms = int((time.perf_counter() - started) * 1000)
        completed_at = datetime.now(timezone.utc).isoformat()
        stdout = run_redactor.redact(
            stdout_capture.data.decode(request.encoding, errors="replace")
        )
        stderr = run_redactor.redact(
            stderr_capture.data.decode(request.encoding, errors="replace")
        )

        if spawn_error is not None:
            outcome = CommandOutcome.ERROR
            exit_code = None
        elif timed_out:
            outcome = CommandOutcome.TIMEOUT
            exit_code = process.returncode if process is not None else None
        else:
            exit_code = process.returncode if process is not None else None
            outcome = CommandOutcome.PASS if exit_code == 0 else CommandOutcome.FAIL

        result = CommandResult(
            outcome=outcome,
            argv=display_argv,
            executable=str(rule.executable),
            cwd=relative_cwd,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_capture.truncated,
            stderr_truncated=stderr_capture.truncated,
            duration_ms=duration_ms,
            started_at=started_at,
            completed_at=completed_at,
            task_id=request.task_id,
            action_id=request.action_id,
            idempotency_key=request.idempotency_key,
            error=spawn_error,
            command_id=command_id,
        )
        if self.event_sink is not None:
            self.event_sink.record(self._event_for(result))
        return result
