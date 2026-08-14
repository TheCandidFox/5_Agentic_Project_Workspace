from __future__ import annotations

import pytest

from project_contract import AuthorityLevel
from task_graph import TaskGraphError, TaskSpec, validate_task_graph


def task(key: str, *dependencies: str, kind: str = "fixture-task") -> TaskSpec:
    return TaskSpec(
        task_key=key,
        title=f"Task {key}",
        description=f"Execute {key}.",
        kind=kind,
        authority=AuthorityLevel.READ_ONLY,
        dependencies=tuple(dependencies),
    )


def test_valid_graph_has_stable_topological_order_and_ready_tasks():
    graph = validate_task_graph(
        (task("first"), task("second"), task("third", "first", "second")),
        max_tasks=3,
        supported_kinds=frozenset({"fixture-task"}),
    )

    assert graph.topological_order == ("first", "second", "third")
    assert [item.task_key for item in graph.ready_tasks(completed=set())] == [
        "first",
        "second",
    ]
    assert [
        item.task_key for item in graph.ready_tasks(completed={"first", "second"})
    ] == ["third"]
    assert len(graph.graph_sha256) == 64


def test_declared_order_breaks_ready_task_ties_deterministically():
    graph = validate_task_graph(
        (task("z-last-name"), task("a-first-name")),
        max_tasks=2,
    )
    assert graph.topological_order == ("z-last-name", "a-first-name")


def test_rejects_missing_dependencies_and_cycles():
    with pytest.raises(TaskGraphError, match="missing dependencies"):
        validate_task_graph((task("one", "missing"),), max_tasks=2)

    with pytest.raises(TaskGraphError, match="cycle"):
        validate_task_graph(
            (task("one", "two"), task("two", "one")),
            max_tasks=2,
        )


def test_rejects_duplicate_keys_self_dependency_limit_and_kind():
    with pytest.raises(TaskGraphError, match="duplicate"):
        validate_task_graph((task("one"), task("one")), max_tasks=2)
    with pytest.raises(TaskGraphError, match="depends on itself"):
        validate_task_graph((task("one", "one"),), max_tasks=2)
    with pytest.raises(TaskGraphError, match="policy allows"):
        validate_task_graph((task("one"), task("two")), max_tasks=1)
    with pytest.raises(TaskGraphError, match="unsupported task kind"):
        validate_task_graph(
            (task("one", kind="unknown"),),
            max_tasks=1,
            supported_kinds=frozenset({"fixture-task"}),
        )


def test_task_spec_rejects_unsafe_or_sensitive_inputs():
    with pytest.raises(TaskGraphError, match="sensitive-looking"):
        TaskSpec(
            task_key="unsafe",
            title="Unsafe",
            description="Unsafe input.",
            kind="fixture-task",
            authority=AuthorityLevel.READ_ONLY,
            inputs={"api_token": "do-not-store"},
        )
    with pytest.raises(TaskGraphError, match="finite"):
        TaskSpec(
            task_key="unsafe",
            title="Unsafe",
            description="Unsafe input.",
            kind="fixture-task",
            authority=AuthorityLevel.READ_ONLY,
            estimated_cost_usd=float("nan"),
        )
