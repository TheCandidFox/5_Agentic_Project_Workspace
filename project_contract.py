from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from project_paths import portable_project_path
from workspace_guard import WorkspaceGuard


class ProjectContractError(ValueError):
    """The submitted Markdown does not satisfy the project-contract schema."""


class AuthorityLevel(str, Enum):
    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"
    LOCAL_COMMAND = "local-command"
    LIVE_NETWORK = "live-network"
    EXTERNAL_SIDE_EFFECT = "external-side-effect"

    @property
    def rank(self) -> int:
        return tuple(AuthorityLevel).index(self)

    def permits(self, required: AuthorityLevel) -> bool:
        if not isinstance(required, AuthorityLevel):
            raise TypeError("required authority must be an AuthorityLevel")
        return self.rank >= required.rank


@dataclass(frozen=True)
class CriterionSpec:
    criterion_key: str
    description: str


@dataclass(frozen=True)
class ConstraintSpec:
    constraint_key: str
    description: str


@dataclass(frozen=True)
class DeliverableSpec:
    path: str
    description: str


@dataclass(frozen=True)
class ProjectExecutionPolicy:
    profile: str = "offline-checklist-v1"
    authority_ceiling: AuthorityLevel = AuthorityLevel.WORKSPACE_WRITE
    budget_usd: float = 0.0
    max_tasks: int = 8
    max_iterations: int = 16
    max_no_progress: int = 2
    max_runtime_seconds: int = 120


@dataclass(frozen=True)
class ProjectContract:
    contract_id: str
    contract_sha256: str
    source_sha256: str
    source_path: str
    title: str
    context: str | None
    goal: str
    acceptance_criteria: tuple[CriterionSpec, ...]
    deliverables: tuple[DeliverableSpec, ...]
    required_content: tuple[str, ...]
    constraints: tuple[ConstraintSpec, ...]
    out_of_scope: tuple[str, ...]
    policy: ProjectExecutionPolicy

    def canonical_payload(self) -> Mapping[str, Any]:
        return {
            "schema_version": 1,
            "source_path": self.source_path,
            "title": self.title,
            "context": self.context,
            "goal": self.goal,
            "acceptance_criteria": [asdict(item) for item in self.acceptance_criteria],
            "deliverables": [asdict(item) for item in self.deliverables],
            "required_content": list(self.required_content),
            "constraints": [asdict(item) for item in self.constraints],
            "out_of_scope": list(self.out_of_scope),
            "policy": {
                **asdict(self.policy),
                "authority_ceiling": self.policy.authority_ceiling.value,
            },
        }


_ALLOWED_SECTIONS = frozenset(
    {
        "context",
        "goal",
        "acceptance criteria",
        "deliverables",
        "required content",
        "constraints",
        "out of scope",
        "execution policy",
    }
)
_REQUIRED_SECTIONS = frozenset(
    {"goal", "acceptance criteria", "deliverables", "required content"}
)
_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_IDENTIFIED_ITEM = re.compile(r"^`([^`]+)`\s*:\s*(.+)$")
_DELIVERABLE_ITEM = re.compile(r"^`([^`]+)`\s*:\s*(.+)$")
_LIST_ITEM = re.compile(r"^[-*+]\s+(.+)$")
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_HTML = re.compile(r"<\s*(?:!|/?[A-Za-z])")
_POLICY_KEYS = {
    "profile": "profile",
    "authority": "authority",
    "budget usd": "budget",
    "max tasks": "max_tasks",
    "max iterations": "max_iterations",
    "max no progress": "max_no_progress",
    "max runtime seconds": "max_runtime_seconds",
}
_SUPPORTED_PROFILES = frozenset(
    {"offline-checklist-v1", "governed-live-v1", "governed-live-v2"}
)
_LIVE_REQUIRED_CRITERIA = frozenset({"deliverable-exists", "required-sections"})
_LIVE_REQUIRED_CONSTRAINTS = frozenset(
    {
        "workspace-confined",
        "declared-artifact-only",
        "no-external-side-effects",
    }
)


def _safe_text(name: str, value: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ProjectContractError(f"{name} must be non-empty text")
    normalized = " ".join(value.split())
    if len(normalized) > maximum:
        raise ProjectContractError(f"{name} exceeds {maximum} characters")
    return normalized


def _key(name: str, value: str) -> str:
    normalized = value.strip().casefold()
    if not _KEY_PATTERN.fullmatch(normalized):
        raise ProjectContractError(
            f"{name} must use lowercase kebab-case and contain at most 64 characters"
        )
    return normalized


def _strip_code_ticks(value: str) -> str:
    normalized = value.strip()
    if len(normalized) >= 2 and normalized.startswith("`") and normalized.endswith("`"):
        normalized = normalized[1:-1].strip()
    return normalized


def _prose(section: str, lines: list[str], *, required: bool) -> str | None:
    content = [line.strip() for line in lines if line.strip()]
    if not content:
        if required:
            raise ProjectContractError(f"section '{section}' must not be empty")
        return None
    if any(_LIST_ITEM.match(line) for line in content):
        raise ProjectContractError(f"section '{section}' must contain prose, not a list")
    return _safe_text(section, " ".join(content), maximum=8_000)


def _list(section: str, lines: list[str], *, required: bool) -> tuple[str, ...]:
    values: list[str] = []
    for raw in lines:
        if not raw.strip():
            continue
        match = _LIST_ITEM.match(raw.strip())
        if not match:
            raise ProjectContractError(
                f"section '{section}' must contain only Markdown bullet items"
            )
        values.append(_safe_text(f"{section} item", match.group(1), maximum=2_000))
    if required and not values:
        raise ProjectContractError(f"section '{section}' requires at least one item")
    folded = [value.casefold() for value in values]
    if len(folded) != len(set(folded)):
        raise ProjectContractError(f"section '{section}' contains duplicate items")
    if len(values) > 64:
        raise ProjectContractError(f"section '{section}' exceeds 64 items")
    return tuple(values)


def _identified_list(
    section: str,
    lines: list[str],
    *,
    kind: type[CriterionSpec] | type[ConstraintSpec],
    required: bool,
) -> tuple[CriterionSpec, ...] | tuple[ConstraintSpec, ...]:
    raw_items = _list(section, lines, required=required)
    parsed: list[CriterionSpec | ConstraintSpec] = []
    seen: set[str] = set()
    for item in raw_items:
        match = _IDENTIFIED_ITEM.fullmatch(item)
        if not match:
            raise ProjectContractError(
                f"section '{section}' items must use `identifier`: description"
            )
        item_key = _key(f"{section} identifier", match.group(1))
        if item_key in seen:
            raise ProjectContractError(f"section '{section}' contains duplicate key {item_key}")
        seen.add(item_key)
        description = _safe_text(
            f"{section} description", match.group(2), maximum=2_000
        )
        if kind is CriterionSpec:
            parsed.append(CriterionSpec(item_key, description))
        else:
            parsed.append(ConstraintSpec(item_key, description))
    return tuple(parsed)  # type: ignore[return-value]


def _deliverables(lines: list[str]) -> tuple[DeliverableSpec, ...]:
    raw_items = _list("deliverables", lines, required=True)
    parsed: list[DeliverableSpec] = []
    seen: set[str] = set()
    for item in raw_items:
        match = _DELIVERABLE_ITEM.fullmatch(item)
        if not match:
            raise ProjectContractError(
                "deliverables must use `outputs/project-relative.md`: description"
            )
        raw_path = match.group(1).strip().replace("\\", "/")
        try:
            path = portable_project_path(raw_path, Path.cwd())
        except ValueError as exc:
            raise ProjectContractError(f"unsafe deliverable path: {raw_path}") from exc
        parts = PurePosixPath(path).parts
        if not parts or parts[0].casefold() != "outputs" or len(parts) < 2:
            raise ProjectContractError("deliverables must be located below outputs/")
        if PurePosixPath(path).suffix.casefold() != ".md":
            raise ProjectContractError("Phase 7 deliverables must be Markdown files")
        path_key = path.casefold()
        if path_key in seen:
            raise ProjectContractError(f"duplicate deliverable path: {path}")
        seen.add(path_key)
        parsed.append(
            DeliverableSpec(
                path=path,
                description=_safe_text(
                    "deliverable description", match.group(2), maximum=2_000
                ),
            )
        )
    if len(parsed) > 8:
        raise ProjectContractError("Phase 7 supports at most 8 deliverables")
    return tuple(parsed)


def _positive_int(name: str, value: str, *, minimum: int, maximum: int) -> int:
    normalized = _strip_code_ticks(value)
    if not normalized.isdigit():
        raise ProjectContractError(f"{name} must be an integer")
    parsed = int(normalized)
    if not minimum <= parsed <= maximum:
        raise ProjectContractError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _execution_policy(lines: list[str]) -> ProjectExecutionPolicy:
    raw_items = _list("execution policy", lines, required=False)
    values: dict[str, str] = {}
    for item in raw_items:
        if ":" not in item:
            raise ProjectContractError("execution policy items must use Key: value")
        name, value = item.split(":", 1)
        normalized_name = " ".join(name.strip().casefold().split())
        mapped = _POLICY_KEYS.get(normalized_name)
        if mapped is None:
            raise ProjectContractError(f"unknown execution policy field: {name.strip()}")
        if mapped in values:
            raise ProjectContractError(f"duplicate execution policy field: {name.strip()}")
        values[mapped] = value.strip()

    profile = _strip_code_ticks(values.get("profile", "offline-checklist-v1"))
    if profile not in _SUPPORTED_PROFILES:
        raise ProjectContractError(f"unsupported execution profile: {profile}")
    authority_text = _strip_code_ticks(
        values.get("authority", AuthorityLevel.WORKSPACE_WRITE.value)
    ).casefold()
    try:
        authority = AuthorityLevel(authority_text)
    except ValueError as exc:
        raise ProjectContractError(f"unknown authority level: {authority_text}") from exc

    budget_text = _strip_code_ticks(values.get("budget", "0"))
    try:
        budget = float(budget_text)
    except ValueError as exc:
        raise ProjectContractError("Budget USD must be a number") from exc
    if not math.isfinite(budget) or budget < 0 or budget > 10_000:
        raise ProjectContractError("Budget USD must be finite and between 0 and 10000")

    return ProjectExecutionPolicy(
        profile=profile,
        authority_ceiling=authority,
        budget_usd=budget,
        max_tasks=_positive_int(
            "Max tasks", values.get("max_tasks", "8"), minimum=1, maximum=64
        ),
        max_iterations=_positive_int(
            "Max iterations",
            values.get("max_iterations", "16"),
            minimum=1,
            maximum=256,
        ),
        max_no_progress=_positive_int(
            "Max no progress",
            values.get("max_no_progress", "2"),
            minimum=1,
            maximum=16,
        ),
        max_runtime_seconds=_positive_int(
            "Max runtime seconds",
            values.get("max_runtime_seconds", "120"),
            minimum=1,
            maximum=3_600,
        ),
    )


def _canonical_sha(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def parse_project_contract(
    markdown: str,
    *,
    source_path: str = "project/goal.md",
) -> ProjectContract:
    if not isinstance(markdown, str):
        raise TypeError("Markdown contract must be text")
    normalized_markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    encoded = normalized_markdown.encode("utf-8")
    if not encoded or len(encoded) > 65_536:
        raise ProjectContractError("Markdown contract must contain 1 to 65536 bytes")
    if "\x00" in normalized_markdown:
        raise ProjectContractError("Markdown contract must not contain NUL characters")
    if "```" in normalized_markdown or "~~~" in normalized_markdown:
        raise ProjectContractError("fenced code blocks are not supported in Phase 7 contracts")
    if _HTML.search(normalized_markdown):
        raise ProjectContractError("HTML is not supported in Phase 7 contracts")

    try:
        portable_source = portable_project_path(source_path, Path.cwd())
    except ValueError as exc:
        raise ProjectContractError("contract source path must be project-relative") from exc

    title: str | None = None
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line_number, raw_line in enumerate(normalized_markdown.split("\n"), start=1):
        if len(raw_line) > 4_000:
            raise ProjectContractError(f"line {line_number} exceeds 4000 characters")
        heading = _HEADING.match(raw_line)
        if heading:
            level = len(heading.group(1))
            heading_text = _safe_text("heading", heading.group(2), maximum=200)
            if level == 1:
                if title is not None or sections:
                    raise ProjectContractError("the contract must contain exactly one leading title")
                title = heading_text
                current = None
                continue
            if level != 2:
                raise ProjectContractError("only level-one and level-two headings are supported")
            if title is None:
                raise ProjectContractError("the contract title must appear before sections")
            section_key = " ".join(heading_text.casefold().split())
            if section_key not in _ALLOWED_SECTIONS:
                raise ProjectContractError(f"unknown project-contract section: {heading_text}")
            if section_key in sections:
                raise ProjectContractError(f"duplicate project-contract section: {heading_text}")
            sections[section_key] = []
            current = section_key
            continue
        if current is None:
            if raw_line.strip():
                raise ProjectContractError("content outside a named section is not allowed")
            continue
        sections[current].append(raw_line)

    if title is None:
        raise ProjectContractError("a level-one project title is required")
    missing = sorted(_REQUIRED_SECTIONS.difference(sections))
    if missing:
        raise ProjectContractError(f"missing required section(s): {', '.join(missing)}")

    context = _prose("context", sections.get("context", []), required=False)
    goal = _prose("goal", sections["goal"], required=True)
    assert goal is not None
    criteria = _identified_list(
        "acceptance criteria",
        sections["acceptance criteria"],
        kind=CriterionSpec,
        required=True,
    )
    constraints = _identified_list(
        "constraints",
        sections.get("constraints", []),
        kind=ConstraintSpec,
        required=False,
    )
    deliverables = _deliverables(sections["deliverables"])
    required_content = _list(
        "required content", sections["required content"], required=True
    )
    out_of_scope = _list(
        "out of scope", sections.get("out of scope", []), required=False
    )
    policy = _execution_policy(sections.get("execution policy", []))

    if policy.profile in {"governed-live-v1", "governed-live-v2"}:
        live_profile = policy.profile
        if policy.authority_ceiling != AuthorityLevel.LIVE_NETWORK:
            raise ProjectContractError(
                f"{live_profile} requires the live-network authority ceiling"
            )
        if not 0 < policy.budget_usd <= 5:
            raise ProjectContractError(
                f"{live_profile} requires Budget USD greater than 0 and at most 5"
            )
        if len(deliverables) != 1:
            raise ProjectContractError(
                f"{live_profile} requires exactly one Markdown deliverable"
            )
        if policy.max_tasks > 4:
            raise ProjectContractError(f"{live_profile} permits at most 4 tasks")
        if policy.max_iterations > 8:
            raise ProjectContractError(
                f"{live_profile} permits at most 8 scheduler iterations"
            )
        if policy.max_no_progress > 2:
            raise ProjectContractError(
                f"{live_profile} permits at most 2 no-progress results"
            )
        if policy.max_runtime_seconds > 600:
            raise ProjectContractError(
                f"{live_profile} permits at most 600 runtime seconds"
            )
        criterion_keys = {item.criterion_key for item in criteria}
        missing_criteria = sorted(_LIVE_REQUIRED_CRITERIA.difference(criterion_keys))
        if missing_criteria:
            raise ProjectContractError(
                f"{live_profile} is missing required criteria: "
                + ", ".join(missing_criteria)
            )
        constraint_keys = {item.constraint_key for item in constraints}
        missing_constraints = sorted(
            _LIVE_REQUIRED_CONSTRAINTS.difference(constraint_keys)
        )
        if missing_constraints:
            raise ProjectContractError(
                f"{live_profile} is missing required constraints: "
                + ", ".join(missing_constraints)
            )

    identity_payload: dict[str, Any] = {
        "schema_version": 1,
        "source_path": portable_source,
        "title": title,
        "context": context,
        "goal": goal,
        "acceptance_criteria": [asdict(item) for item in criteria],
        "deliverables": [asdict(item) for item in deliverables],
        "required_content": list(required_content),
        "constraints": [asdict(item) for item in constraints],
        "out_of_scope": list(out_of_scope),
        "policy": {
            **asdict(policy),
            "authority_ceiling": policy.authority_ceiling.value,
        },
    }
    contract_sha256 = _canonical_sha(identity_payload)
    source_sha256 = hashlib.sha256(encoded).hexdigest()
    return ProjectContract(
        contract_id=f"contract-{contract_sha256[:20]}",
        contract_sha256=contract_sha256,
        source_sha256=source_sha256,
        source_path=portable_source,
        title=title,
        context=context,
        goal=goal,
        acceptance_criteria=criteria,  # type: ignore[arg-type]
        deliverables=deliverables,
        required_content=required_content,
        constraints=constraints,  # type: ignore[arg-type]
        out_of_scope=out_of_scope,
        policy=policy,
    )


def load_project_contract(
    guard: WorkspaceGuard,
    source_path: str | Path,
) -> ProjectContract:
    authorized = guard.authorize_read(source_path, expect_directory=False)
    raw = authorized.path.read_bytes()
    if len(raw) > 65_536:
        raise ProjectContractError("Markdown contract exceeds 65536 bytes")
    try:
        markdown = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectContractError("Markdown contract must be valid UTF-8") from exc
    return parse_project_contract(markdown, source_path=authorized.relative_path)
