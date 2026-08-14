from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from project_contract import AuthorityLevel


class TaskGraphError(ValueError):
    """A compiled backlog is invalid or outside its declared bounds."""


_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_SENSITIVE_FRAGMENTS = ("api-key", "api_key", "password", "secret", "token")


def _safe_text(name: str, value: Any, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise TaskGraphError(f"{name} must be non-empty text")
    normalized = " ".join(value.split())
    if len(normalized) > maximum:
        raise TaskGraphError(f"{name} exceeds {maximum} characters")
    return normalized


def _key(name: str, value: Any) -> str:
    normalized = _safe_text(name, value, 64).casefold()
    if not _KEY_PATTERN.fullmatch(normalized):
        raise TaskGraphError(f"{name} must use lowercase kebab-case")
    return normalized


def _json_value(name: str, value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        raise TaskGraphError(f"{name} exceeds maximum nesting depth")
    if value is None or isinstance(value, (bool, int, str)):
        if isinstance(value, str):
            if "\x00" in value or len(value) > 8_000:
                raise TaskGraphError(f"{name} contains unsafe text")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TaskGraphError(f"{name} must not contain a non-finite number")
        return value
    if isinstance(value, (list, tuple)):
        if len(value) > 128:
            raise TaskGraphError(f"{name} contains too many items")
        return [_json_value(name, item, depth=depth + 1) for item in value]
    if isinstance(value, Mapping):
        if len(value) > 128:
            raise TaskGraphError(f"{name} contains too many fields")
        normalized: dict[str, Any] = {}
        for raw_key in sorted(value, key=lambda item: str(item).casefold()):
            key = _safe_text(f"{name} key", raw_key, 120)
            folded = key.casefold()
            if any(fragment in folded for fragment in _SENSITIVE_FRAGMENTS):
                raise TaskGraphError(f"{name} contains a sensitive-looking field: {key}")
            if key in normalized:
                raise TaskGraphError(f"{name} contains duplicate field: {key}")
            normalized[key] = _json_value(
                f"{name}.{key}", value[raw_key], depth=depth + 1
            )
        return normalized
    raise TaskGraphError(f"{name} must contain only JSON-compatible values")


@dataclass(frozen=True)
class TaskSpec:
    task_key: str
    title: str
    description: str
    kind: str
    authority: AuthorityLevel
    dependencies: tuple[str, ...] = ()
    estimated_cost_usd: float = 0.0
    max_attempts: int = 1
    inputs: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_key", _key("task_key", self.task_key))
        object.__setattr__(self, "title", _safe_text("task title", self.title, 200))
        object.__setattr__(
            self, "description", _safe_text("task description", self.description, 2_000)
        )
        object.__setattr__(self, "kind", _key("task kind", self.kind))
        if not isinstance(self.authority, AuthorityLevel):
            raise TypeError("task authority must be an AuthorityLevel")
        if not isinstance(self.dependencies, tuple):
            raise TypeError("task dependencies must be a tuple")
        dependencies = tuple(_key("dependency", item) for item in self.dependencies)
        if len(dependencies) != len(set(dependencies)):
            raise TaskGraphError("task dependencies must not contain duplicates")
        object.__setattr__(self, "dependencies", dependencies)
        if not isinstance(self.estimated_cost_usd, (int, float)):
            raise TypeError("estimated task cost must be numeric")
        cost = float(self.estimated_cost_usd)
        if not math.isfinite(cost) or cost < 0 or cost > 10_000:
            raise TaskGraphError("estimated task cost must be finite and between 0 and 10000")
        object.__setattr__(self, "estimated_cost_usd", cost)
        if not isinstance(self.max_attempts, int) or isinstance(self.max_attempts, bool):
            raise TypeError("max_attempts must be an integer")
        if not 1 <= self.max_attempts <= 5:
            raise TaskGraphError("max_attempts must be between 1 and 5")
        object.__setattr__(
            self,
            "inputs",
            _json_value("task inputs", self.inputs or {}),
        )

    def payload(self, ordinal: int) -> dict[str, Any]:
        return {
            "task_key": self.task_key,
            "ordinal": ordinal,
            "title": self.title,
            "description": self.description,
            "kind": self.kind,
            "authority": self.authority.value,
            "dependencies": list(self.dependencies),
            "estimated_cost_usd": self.estimated_cost_usd,
            "max_attempts": self.max_attempts,
            "inputs": self.inputs,
        }


@dataclass(frozen=True)
class TaskGraph:
    tasks: tuple[TaskSpec, ...]
    topological_order: tuple[str, ...]
    graph_sha256: str

    @property
    def by_key(self) -> Mapping[str, TaskSpec]:
        return {task.task_key: task for task in self.tasks}

    def ready_tasks(
        self,
        *,
        completed: set[str] | frozenset[str],
        terminal: set[str] | frozenset[str] = frozenset(),
    ) -> tuple[TaskSpec, ...]:
        return tuple(
            task
            for task in self.tasks
            if task.task_key not in completed
            and task.task_key not in terminal
            and all(dependency in completed for dependency in task.dependencies)
        )


def task_graph_sha256(tasks: Sequence[TaskSpec]) -> str:
    payload = {
        "schema_version": 1,
        "tasks": [task.payload(index) for index, task in enumerate(tasks, start=1)],
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def validate_task_graph(
    tasks: Sequence[TaskSpec],
    *,
    max_tasks: int,
    supported_kinds: frozenset[str] | None = None,
) -> TaskGraph:
    if isinstance(tasks, (str, bytes)) or not tasks:
        raise TaskGraphError("a project plan requires at least one task")
    if not isinstance(max_tasks, int) or max_tasks <= 0:
        raise TaskGraphError("max_tasks must be positive")
    normalized = tuple(tasks)
    if len(normalized) > max_tasks:
        raise TaskGraphError(
            f"project plan contains {len(normalized)} tasks but policy allows {max_tasks}"
        )
    if any(not isinstance(task, TaskSpec) for task in normalized):
        raise TypeError("project plan must contain TaskSpec instances")

    keys = [task.task_key for task in normalized]
    if len(keys) != len(set(keys)):
        raise TaskGraphError("project plan contains duplicate task keys")
    known = set(keys)
    if supported_kinds is not None:
        unsupported = sorted(
            {task.kind for task in normalized if task.kind not in supported_kinds}
        )
        if unsupported:
            raise TaskGraphError(f"unsupported task kind(s): {', '.join(unsupported)}")
    for task in normalized:
        if task.task_key in task.dependencies:
            raise TaskGraphError(f"task {task.task_key} depends on itself")
        missing = sorted(set(task.dependencies).difference(known))
        if missing:
            raise TaskGraphError(
                f"task {task.task_key} has missing dependencies: {', '.join(missing)}"
            )

    ordinal = {task.task_key: index for index, task in enumerate(normalized)}
    remaining = {task.task_key: set(task.dependencies) for task in normalized}
    ready = sorted(
        (key for key, dependencies in remaining.items() if not dependencies),
        key=ordinal.__getitem__,
    )
    topological: list[str] = []
    while ready:
        key = ready.pop(0)
        topological.append(key)
        for candidate in sorted(remaining, key=ordinal.__getitem__):
            dependencies = remaining[candidate]
            if key in dependencies:
                dependencies.remove(key)
                if not dependencies and candidate not in topological and candidate not in ready:
                    ready.append(candidate)
        ready.sort(key=ordinal.__getitem__)
    if len(topological) != len(normalized):
        cyclic = sorted(set(keys).difference(topological), key=ordinal.__getitem__)
        raise TaskGraphError(f"project task graph contains a cycle: {', '.join(cyclic)}")

    return TaskGraph(
        tasks=normalized,
        topological_order=tuple(topological),
        graph_sha256=task_graph_sha256(normalized),
    )
