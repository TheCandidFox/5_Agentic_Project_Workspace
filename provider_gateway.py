from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Protocol, Sequence

from budget_guard import BudgetGuard
from ledger import Ledger, utc_now
from provider_adapter import ProviderResponse
from telemetry import estimate_cost, record_call


class ProviderGatewayError(RuntimeError):
    """Base error for the governed Phase 8 provider boundary."""


class ProviderAuthorizationError(ProviderGatewayError):
    """A provider call was not explicitly authorized."""


class ProviderCallConflict(ProviderGatewayError):
    """A provider-call idempotency key was reused with changed semantics."""


class AmbiguousProviderCall(ProviderGatewayError):
    """A durable provider claim already exists and cannot be safely repeated."""


class ProviderResponseError(ProviderGatewayError):
    """A provider response failed identity, usage, cost, or schema checks."""


class ProviderExecutionMode(str, Enum):
    OFFLINE_SIMULATION = "offline-simulation"
    LIVE = "live"


_SAFE_ROUTE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9.-]{0,119}$")


def _safe_route_value(name: str, value: str) -> str:
    if not isinstance(value, str) or not _SAFE_ROUTE.fullmatch(value):
        raise ValueError(f"{name} contains unsupported characters")
    return value


def _safe_schema_value(name: str, value: str) -> str:
    if not isinstance(value, str) or not _SAFE_SCHEMA.fullmatch(value):
        raise ValueError(f"{name} must use a bounded lowercase identifier")
    return value


def strict_json_object(text: str) -> Mapping[str, Any]:
    """Parse one JSON object; prose wrappers and fenced JSON fail closed."""

    if not isinstance(text, str) or not text.strip() or "\x00" in text:
        raise ProviderResponseError("provider response must be non-empty NUL-free text")
    encoded = text.encode("utf-8")
    if len(encoded) > 131_072:
        raise ProviderResponseError("provider response exceeds 131072 bytes")
    stripped = text.strip()
    is_object_shape = stripped.startswith("{") and stripped.endswith("}")
    is_array_shape = stripped.startswith("[") and stripped.endswith("]")
    if not is_object_shape and not is_array_shape:
        raise ProviderResponseError("provider response must contain only one JSON object")
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ProviderResponseError("provider response is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ProviderResponseError("provider response root must be a JSON object")
    return parsed


@dataclass(frozen=True)
class ProviderRoute:
    provider: str
    model: str
    max_output_tokens: int
    input_per_mtok: float
    output_per_mtok: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider", _safe_route_value("provider", self.provider).casefold()
        )
        if self.provider not in {"openai", "anthropic"}:
            raise ValueError(f"unsupported provider route: {self.provider}")
        object.__setattr__(self, "model", _safe_route_value("model", self.model))
        if not isinstance(self.max_output_tokens, int) or isinstance(
            self.max_output_tokens, bool
        ):
            raise TypeError("max_output_tokens must be an integer")
        if not 64 <= self.max_output_tokens <= 16_384:
            raise ValueError("max_output_tokens must be between 64 and 16384")
        for name in ("input_per_mtok", "output_per_mtok"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or not 0 < value <= 1_000:
                raise ValueError(f"{name} must be finite and between 0 and 1000")
            object.__setattr__(self, name, value)

    @property
    def identity(self) -> tuple[str, str, int]:
        return self.provider, self.model, self.max_output_tokens


class ProviderClient(Protocol):
    offline_fixture: bool

    def call(
        self,
        *,
        provider: str,
        model: str,
        prompt: str,
        max_output_tokens: int,
    ) -> ProviderResponse: ...


@dataclass(frozen=True)
class ProviderCallRequest:
    run_id: str
    task_key: str
    attempt_number: int
    route: ProviderRoute
    prompt_template_version: str
    prompt_sha256: str
    response_schema: str
    quoted_cost_usd: float
    execution_mode: ProviderExecutionMode

    @property
    def idempotency_key(self) -> str:
        return (
            f"phase8:{self.run_id}:{self.task_key}:attempt:{self.attempt_number}:"
            f"provider:{self.route.provider}:{self.route.model}:"
            f"template:{self.prompt_template_version}"
        )

    @property
    def request_sha256(self) -> str:
        payload = {
            "schema_version": 1,
            "run_id": self.run_id,
            "task_key": self.task_key,
            "attempt_number": self.attempt_number,
            "provider": self.route.provider,
            "model": self.route.model,
            "max_output_tokens": self.route.max_output_tokens,
            "prompt_template_version": self.prompt_template_version,
            "prompt_sha256": self.prompt_sha256,
            "response_schema": self.response_schema,
            "quoted_cost_usd": self.quoted_cost_usd,
            "execution_mode": self.execution_mode.value,
        }
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GovernedCallResult:
    payload: Mapping[str, Any]
    provider: str
    model: str
    prompt_sha256: str
    response_sha256: str
    provider_request_id: str | None
    input_tokens: int
    output_tokens: int
    actual_cost_usd: float
    latency_ms: int


class ProviderCallStore:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    @staticmethod
    def _call_id(idempotency_key: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key))

    def claim(self, request: ProviderCallRequest) -> str:
        now = utc_now()
        call_id = self._call_id(request.idempotency_key)
        with self.ledger.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute(
                "SELECT * FROM provider_calls WHERE idempotency_key=?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                if str(existing["request_sha256"]) != request.request_sha256:
                    raise ProviderCallConflict(
                        "provider-call idempotency key belongs to changed semantics"
                    )
                raise AmbiguousProviderCall(
                    "provider call already has a durable claim and will not be repeated"
                )
            con.execute(
                """
                INSERT INTO provider_calls(
                    provider_call_id,run_id,task_key,attempt_number,
                    idempotency_key,request_sha256,execution_mode,provider,model,
                    prompt_template_version,prompt_sha256,response_schema,
                    max_output_tokens,quoted_cost_usd,status,started_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'dispatching',?,?)
                """,
                (
                    call_id,
                    request.run_id,
                    request.task_key,
                    request.attempt_number,
                    request.idempotency_key,
                    request.request_sha256,
                    request.execution_mode.value,
                    request.route.provider,
                    request.route.model,
                    request.prompt_template_version,
                    request.prompt_sha256,
                    request.response_schema,
                    request.route.max_output_tokens,
                    request.quoted_cost_usd,
                    now,
                    now,
                ),
            )
        return call_id

    def complete(
        self,
        call_id: str,
        *,
        response: ProviderResponse,
        response_sha256: str,
        response_payload: Mapping[str, Any],
        actual_cost_usd: float,
    ) -> None:
        serialized = json.dumps(
            response_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        if len(serialized.encode("utf-8")) > 131_072:
            raise ProviderResponseError("validated provider payload exceeds 131072 bytes")
        now = utc_now()
        with self.ledger.connect() as con:
            cursor = con.execute(
                """
                UPDATE provider_calls SET
                    status='completed',provider_request_id=?,response_sha256=?,
                    response_json=?,input_tokens=?,output_tokens=?,
                    estimated_cost_usd=?,latency_ms=?,stop_reason=?,error=NULL,
                    completed_at=?,updated_at=?
                WHERE provider_call_id=? AND status='dispatching'
                """,
                (
                    response.request_id,
                    response_sha256,
                    serialized,
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                    actual_cost_usd,
                    response.latency_ms,
                    response.stop_reason,
                    now,
                    now,
                    call_id,
                ),
            )
            if cursor.rowcount != 1:
                raise AmbiguousProviderCall("provider call is not durably dispatching")

    def fail(
        self,
        call_id: str,
        error: BaseException,
        *,
        response: ProviderResponse | None = None,
        response_sha256: str | None = None,
        actual_cost_usd: float | None = None,
    ) -> None:
        now = utc_now()
        safe_error = f"{type(error).__name__}: {error}"[:4_000]
        with self.ledger.connect() as con:
            con.execute(
                """
                UPDATE provider_calls SET
                    status='failed',provider_request_id=?,response_sha256=?,
                    input_tokens=?,output_tokens=?,estimated_cost_usd=?,
                    latency_ms=?,stop_reason=?,error=?,completed_at=?,updated_at=?
                WHERE provider_call_id=? AND status='dispatching'
                """,
                (
                    response.request_id if response else None,
                    response_sha256,
                    response.usage.input_tokens if response else None,
                    response.usage.output_tokens if response else None,
                    actual_cost_usd,
                    response.latency_ms if response else None,
                    response.stop_reason if response else None,
                    safe_error,
                    now,
                    now,
                    call_id,
                ),
            )


class GovernedProviderGateway:
    def __init__(
        self,
        *,
        ledger: Ledger,
        client: ProviderClient,
        execution_mode: ProviderExecutionMode,
        approved_routes: Sequence[ProviderRoute],
        daily_limit_usd: float,
        monthly_limit_usd: float,
        live_authorized: bool = False,
    ) -> None:
        if not isinstance(execution_mode, ProviderExecutionMode):
            raise TypeError("execution_mode must be a ProviderExecutionMode")
        fixture = bool(getattr(client, "offline_fixture", False))
        if execution_mode == ProviderExecutionMode.OFFLINE_SIMULATION and not fixture:
            raise ProviderAuthorizationError(
                "offline simulation requires an explicit fixture provider client"
            )
        if execution_mode == ProviderExecutionMode.LIVE:
            if fixture:
                raise ProviderAuthorizationError("live mode cannot use a fixture client")
            if not live_authorized:
                raise ProviderAuthorizationError(
                    "live provider mode requires an exact approval fingerprint"
                )
        routes = tuple(approved_routes)
        if not routes or len(routes) > 4:
            raise ValueError("one to four approved provider routes are required")
        identities = [route.identity for route in routes]
        if len(identities) != len(set(identities)):
            raise ValueError("approved provider routes must be unique")
        for name, value in (
            ("daily_limit_usd", daily_limit_usd),
            ("monthly_limit_usd", monthly_limit_usd),
        ):
            parsed = float(value)
            if not math.isfinite(parsed) or parsed <= 0:
                raise ValueError(f"{name} must be finite and positive")
        self.ledger = ledger
        self.client = client
        self.execution_mode = execution_mode
        self.approved_routes = frozenset(identities)
        self.budget = BudgetGuard(
            ledger,
            daily_limit_usd=float(daily_limit_usd),
            monthly_limit_usd=float(monthly_limit_usd),
        )
        self.store = ProviderCallStore(ledger)
        self.call_count = 0

    @staticmethod
    def _quote(prompt: str, route: ProviderRoute) -> float:
        # One token cannot contain less than one UTF-8 byte, so byte count is a
        # deliberately conservative upper bound for provider input tokens.
        maximum_input_tokens = len(prompt.encode("utf-8"))
        return (
            maximum_input_tokens / 1_000_000 * route.input_per_mtok
            + route.max_output_tokens / 1_000_000 * route.output_per_mtok
        )

    @staticmethod
    def _actual_cost(response: ProviderResponse, route: ProviderRoute) -> float:
        return estimate_cost(
            route.provider,
            response.usage,
            openai_input_per_mtok=(
                route.input_per_mtok if route.provider == "openai" else 1
            ),
            openai_output_per_mtok=(
                route.output_per_mtok if route.provider == "openai" else 1
            ),
            anthropic_input_per_mtok=(
                route.input_per_mtok if route.provider == "anthropic" else 1
            ),
            anthropic_output_per_mtok=(
                route.output_per_mtok if route.provider == "anthropic" else 1
            ),
        )

    def call_json(
        self,
        *,
        run_id: str,
        task_key: str,
        attempt_number: int,
        route: ProviderRoute,
        prompt: str,
        prompt_template_version: str,
        response_schema: str,
        max_call_cost_usd: float,
        project_budget_usd: float,
        parser: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    ) -> GovernedCallResult:
        if route.identity not in self.approved_routes:
            raise ProviderAuthorizationError("provider route is not on the approved allowlist")
        if not isinstance(prompt, str) or not prompt.strip() or "\x00" in prompt:
            raise ValueError("provider prompt must be non-empty NUL-free text")
        if len(prompt.encode("utf-8")) > 65_536:
            raise ValueError("provider prompt exceeds 65536 bytes")
        template = _safe_schema_value(
            "prompt_template_version", prompt_template_version
        )
        schema = _safe_schema_value("response_schema", response_schema)
        if not isinstance(attempt_number, int) or not 1 <= attempt_number <= 5:
            raise ValueError("attempt_number must be between 1 and 5")
        maximum = float(max_call_cost_usd)
        project_budget = float(project_budget_usd)
        if not math.isfinite(maximum) or maximum <= 0:
            raise ValueError("max_call_cost_usd must be finite and positive")
        if not math.isfinite(project_budget) or project_budget <= 0:
            raise ValueError("project_budget_usd must be finite and positive")
        quote = self._quote(prompt, route)
        if quote > maximum + 1e-12:
            raise ProviderAuthorizationError(
                f"conservative provider quote exceeds task allocation: "
                f"${quote:.6f} > ${maximum:.6f}"
            )
        prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        request = ProviderCallRequest(
            run_id=run_id,
            task_key=task_key,
            attempt_number=attempt_number,
            route=route,
            prompt_template_version=template,
            prompt_sha256=prompt_sha,
            response_schema=schema,
            quoted_cost_usd=quote,
            execution_mode=self.execution_mode,
        )
        reservation_id = self.budget.reserve(
            task_id=run_id,
            step_id=task_key,
            amount_usd=quote,
            task_limit_usd=project_budget,
            idempotency_key=request.idempotency_key,
        )
        call_id = self.store.claim(request)
        response: ProviderResponse | None = None
        response_sha: str | None = None
        actual_cost: float | None = None
        try:
            self.call_count += 1
            response = self.client.call(
                provider=route.provider,
                model=route.model,
                prompt=prompt,
                max_output_tokens=route.max_output_tokens,
            )
            if response.provider != route.provider or response.model != route.model:
                raise ProviderResponseError("provider response route identity mismatch")
            if not isinstance(response.usage.input_tokens, int) or not isinstance(
                response.usage.output_tokens, int
            ):
                raise ProviderResponseError("provider usage must contain integer token counts")
            if response.usage.input_tokens < 0 or response.usage.output_tokens < 0:
                raise ProviderResponseError("provider usage token counts must be non-negative")
            if self.execution_mode == ProviderExecutionMode.LIVE and (
                response.usage.input_tokens == 0 or response.usage.output_tokens == 0
            ):
                raise ProviderResponseError("live provider usage must be measurable")
            if response.usage.output_tokens > route.max_output_tokens:
                raise ProviderResponseError("provider output usage exceeds the approved limit")
            response_sha = hashlib.sha256(response.text.encode("utf-8")).hexdigest()
            actual_cost = (
                0.0
                if self.execution_mode == ProviderExecutionMode.OFFLINE_SIMULATION
                else self._actual_cost(response, route)
            )
            if actual_cost > quote + 1e-12 or actual_cost > maximum + 1e-12:
                raise ProviderResponseError("provider usage cost exceeds its authorization")
            parsed = parser(strict_json_object(response.text))
            if not isinstance(parsed, Mapping):
                raise TypeError("provider response parser must return a mapping")
            validated = dict(parsed)
            self.store.complete(
                call_id,
                response=response,
                response_sha256=response_sha,
                response_payload=validated,
                actual_cost_usd=actual_cost,
            )
            self.budget.settle(reservation_id, actual_cost)
            record_call(
                self.ledger,
                task_id=run_id,
                step_id=task_key,
                provider=route.provider,
                model=route.model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                estimated_cost_usd=actual_cost,
                latency_ms=response.latency_ms,
                stop_reason=response.stop_reason,
                error=None,
            )
            return GovernedCallResult(
                payload=validated,
                provider=route.provider,
                model=route.model,
                prompt_sha256=prompt_sha,
                response_sha256=response_sha,
                provider_request_id=response.request_id,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                actual_cost_usd=actual_cost,
                latency_ms=response.latency_ms,
            )
        except Exception as exc:
            if response is not None and actual_cost is None:
                try:
                    actual_cost = (
                        0.0
                        if self.execution_mode
                        == ProviderExecutionMode.OFFLINE_SIMULATION
                        else self._actual_cost(response, route)
                    )
                except Exception:
                    actual_cost = None
            self.store.fail(
                call_id,
                exc,
                response=response,
                response_sha256=response_sha,
                actual_cost_usd=actual_cost,
            )
            if actual_cost is not None:
                self.budget.settle(reservation_id, actual_cost)
                if response is not None:
                    record_call(
                        self.ledger,
                        task_id=run_id,
                        step_id=task_key,
                        provider=route.provider,
                        model=route.model,
                        input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens,
                        estimated_cost_usd=actual_cost,
                        latency_ms=response.latency_ms,
                        stop_reason=response.stop_reason,
                        error=f"{type(exc).__name__}: {exc}"[:4_000],
                    )
            raise
