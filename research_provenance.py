from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import socket
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.parse import SplitResult, urlsplit, urlunsplit

from ledger import Ledger, utc_now


class ResearchError(RuntimeError):
    """Base class for governed research failures."""


class ResearchIdempotencyConflict(ResearchError):
    """One research idempotency key was reused for different semantics."""


class ResearchRecoveryRequired(ResearchError):
    """A previous live retrieval may have dispatched without a final record."""


class ResearchRunNotReplayable(ResearchError):
    """A terminal non-successful run cannot be retried under the same key."""


class LiveRetrievalDenied(PermissionError):
    """Live HTTP retrieval is not authorized by policy."""


class UnsafeResearchUrl(ValueError):
    """A source URL violates the governed HTTP boundary."""


class SourceType(str, Enum):
    OFFICIAL_DOCUMENTATION = "OFFICIAL_DOCUMENTATION"
    OFFICIAL_PRICING = "OFFICIAL_PRICING"
    REGULATORY = "REGULATORY"
    ORIGINAL_RESEARCH = "ORIGINAL_RESEARCH"
    SECONDARY = "SECONDARY"


class ClaimType(str, Enum):
    SOURCED_FACT = "SOURCED_FACT"
    INFERENCE = "INFERENCE"
    UNRESOLVED = "UNRESOLVED"


class RetrievalMode(str, Enum):
    OFFLINE_FIXTURE = "OFFLINE_FIXTURE"
    LIVE_HTTP = "LIVE_HTTP"


def _safe_text(name: str, value: Any, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be a non-empty safe string")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    return normalized


def _optional_text(name: str, value: Any, *, maximum: int) -> str | None:
    if value is None:
        return None
    return _safe_text(name, value, maximum=maximum)


def _iso_date(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _safe_text(name, value, maximum=32)
    try:
        date.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date") from exc
    return normalized


def _iso_timestamp(name: str, value: str) -> str:
    normalized = _safe_text(name, value, maximum=64)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return normalized


def canonicalize_url(value: str) -> str:
    raw = _safe_text("source URL", value, maximum=2_000)
    parsed = urlsplit(raw)
    if parsed.scheme.casefold() != "https":
        raise UnsafeResearchUrl("research source URLs must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeResearchUrl("research source URLs must not contain user information")
    if parsed.hostname is None:
        raise UnsafeResearchUrl("research source URL requires a hostname")
    try:
        hostname = parsed.hostname.encode("idna").decode("ascii").casefold()
    except UnicodeError as exc:
        raise UnsafeResearchUrl("research source hostname is invalid") from exc
    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeResearchUrl("research source URL has an invalid port") from exc
    if port not in (None, 443):
        raise UnsafeResearchUrl("research source URL must use the default HTTPS port")
    netloc = hostname
    path = parsed.path or "/"
    canonical = SplitResult("https", netloc, path, parsed.query, "")
    return urlunsplit(canonical)


@dataclass(frozen=True)
class SourceSpec:
    source_key: str
    url: str
    title: str
    source_type: SourceType
    is_primary: bool
    applicable_version: str | None = None
    applicable_date: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_key", _safe_text("source_key", self.source_key, maximum=120)
        )
        object.__setattr__(self, "url", canonicalize_url(self.url))
        object.__setattr__(self, "title", _safe_text("title", self.title, maximum=500))
        if not isinstance(self.source_type, SourceType):
            raise TypeError("source_type must be a SourceType")
        if not isinstance(self.is_primary, bool):
            raise TypeError("is_primary must be a boolean")
        if self.source_type == SourceType.SECONDARY and self.is_primary:
            raise ValueError("a SECONDARY source cannot be designated primary")
        object.__setattr__(
            self,
            "applicable_version",
            _optional_text(
                "applicable_version", self.applicable_version, maximum=200
            ),
        )
        object.__setattr__(
            self,
            "applicable_date",
            _iso_date("applicable_date", self.applicable_date),
        )


@dataclass(frozen=True)
class CitationSpec:
    source_key: str
    excerpt: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_key", _safe_text("source_key", self.source_key, maximum=120)
        )
        object.__setattr__(
            self, "excerpt", _safe_text("citation excerpt", self.excerpt, maximum=4_000)
        )


@dataclass(frozen=True)
class ClaimSpec:
    claim_key: str
    statement: str
    claim_type: ClaimType
    citations: tuple[CitationSpec, ...] = ()
    rationale: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "claim_key", _safe_text("claim_key", self.claim_key, maximum=120)
        )
        object.__setattr__(
            self, "statement", _safe_text("claim statement", self.statement, maximum=4_000)
        )
        if not isinstance(self.claim_type, ClaimType):
            raise TypeError("claim_type must be a ClaimType")
        if not isinstance(self.citations, tuple) or not all(
            isinstance(item, CitationSpec) for item in self.citations
        ):
            raise TypeError("citations must be a tuple of CitationSpec values")
        source_keys = [item.source_key.casefold() for item in self.citations]
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("a claim may cite each source at most once")
        rationale = _optional_text("claim rationale", self.rationale, maximum=4_000)
        object.__setattr__(self, "rationale", rationale)
        if self.claim_type == ClaimType.SOURCED_FACT and not self.citations:
            raise ValueError("SOURCED_FACT requires at least one citation")
        if self.claim_type in {ClaimType.INFERENCE, ClaimType.UNRESOLVED} and not rationale:
            raise ValueError(f"{self.claim_type.value} requires an explicit rationale")


@dataclass(frozen=True)
class ResearchRequest:
    run_id: str
    task_id: str
    objective: str
    idempotency_key: str
    sources: tuple[SourceSpec, ...]
    claims: tuple[ClaimSpec, ...] = ()
    require_primary_source: bool = True

    def __post_init__(self) -> None:
        for name, maximum in (
            ("run_id", 200),
            ("task_id", 200),
            ("idempotency_key", 500),
        ):
            object.__setattr__(
                self, name, _safe_text(name, getattr(self, name), maximum=maximum)
            )
        object.__setattr__(
            self, "objective", _safe_text("objective", self.objective, maximum=4_000)
        )
        if not isinstance(self.sources, tuple) or not self.sources:
            raise ValueError("research requires at least one source")
        if not all(isinstance(item, SourceSpec) for item in self.sources):
            raise TypeError("sources must contain only SourceSpec values")
        if not isinstance(self.claims, tuple) or not all(
            isinstance(item, ClaimSpec) for item in self.claims
        ):
            raise TypeError("claims must contain only ClaimSpec values")
        source_keys = [item.source_key.casefold() for item in self.sources]
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("research source keys must be unique")
        claim_keys = [item.claim_key.casefold() for item in self.claims]
        if len(claim_keys) != len(set(claim_keys)):
            raise ValueError("research claim keys must be unique")
        known = set(source_keys)
        for claim in self.claims:
            for citation in claim.citations:
                if citation.source_key.casefold() not in known:
                    raise ValueError(
                        f"claim cites an unknown source key: {citation.source_key}"
                    )
        if not isinstance(self.require_primary_source, bool):
            raise TypeError("require_primary_source must be a boolean")
        if self.require_primary_source and not any(item.is_primary for item in self.sources):
            raise ValueError("research request requires at least one primary source")


@dataclass(frozen=True)
class ResearchPolicy:
    allow_live_http: bool = False
    allowed_hosts: frozenset[str] = frozenset()
    max_sources: int = 12
    max_claims: int = 100
    max_source_bytes: int = 500_000
    max_total_bytes: int = 2_000_000
    timeout_seconds: float = 20.0
    allowed_content_types: frozenset[str] = frozenset(
        {
            "text/html",
            "text/plain",
            "text/markdown",
            "application/json",
            "application/xml",
            "text/xml",
        }
    )

    def __post_init__(self) -> None:
        if not isinstance(self.allow_live_http, bool):
            raise TypeError("allow_live_http must be a boolean")
        normalized_hosts: set[str] = set()
        for host in self.allowed_hosts:
            candidate = _safe_text("allowed host", host, maximum=253).casefold()
            if ":" in candidate or "/" in candidate:
                raise ValueError("allowed hosts must contain hostnames only")
            normalized_hosts.add(candidate.encode("idna").decode("ascii"))
        object.__setattr__(self, "allowed_hosts", frozenset(normalized_hosts))
        for name in ("max_sources", "max_claims", "max_source_bytes", "max_total_bytes"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_total_bytes < self.max_source_bytes:
            raise ValueError("max_total_bytes must be at least max_source_bytes")
        if not isinstance(self.timeout_seconds, (int, float)) or not math.isfinite(
            self.timeout_seconds
        ) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive finite number")
        normalized_types = frozenset(
            _safe_text("content type", item, maximum=100).casefold()
            for item in self.allowed_content_types
        )
        object.__setattr__(self, "allowed_content_types", normalized_types)

    def validate_request(self, request: ResearchRequest) -> None:
        if len(request.sources) > self.max_sources:
            raise ValueError("research source count exceeds policy")
        if len(request.claims) > self.max_claims:
            raise ValueError("research claim count exceeds policy")


@dataclass(frozen=True)
class FixtureDocument:
    url: str
    title: str
    text: str
    retrieved_at: str
    content_type: str = "text/plain"
    status_code: int = 200

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", canonicalize_url(self.url))
        object.__setattr__(self, "title", _safe_text("fixture title", self.title, maximum=500))
        object.__setattr__(self, "text", _safe_text("fixture text", self.text, maximum=2_000_000))
        object.__setattr__(
            self, "retrieved_at", _iso_timestamp("retrieved_at", self.retrieved_at)
        )
        content_type = _safe_text(
            "fixture content_type", self.content_type, maximum=100
        ).casefold().split(";", 1)[0].strip()
        object.__setattr__(self, "content_type", content_type)
        if not isinstance(self.status_code, int) or not 200 <= self.status_code < 300:
            raise ValueError("fixture status_code must be a successful HTTP status")


@dataclass(frozen=True)
class RetrievedDocument:
    canonical_url: str
    title: str
    text: str
    retrieved_at: str
    content_type: str
    status_code: int
    duration_ms: int
    capture_method: RetrievalMode


class DocumentRetriever(Protocol):
    mode: RetrievalMode

    def retrieve(
        self, source: SourceSpec, policy: ResearchPolicy
    ) -> RetrievedDocument: ...


class FixtureRetriever:
    mode = RetrievalMode.OFFLINE_FIXTURE

    def __init__(self, fixtures: Mapping[str, FixtureDocument]) -> None:
        self.fixtures = {
            canonicalize_url(key): value for key, value in fixtures.items()
        }
        if not self.fixtures:
            raise ValueError("at least one fixture is required")
        for key, fixture in self.fixtures.items():
            if fixture.url != key:
                raise ValueError("fixture mapping key must match fixture URL")
        self.call_count = 0

    def retrieve(
        self, source: SourceSpec, policy: ResearchPolicy
    ) -> RetrievedDocument:
        self.call_count += 1
        fixture = self.fixtures.get(source.url)
        if fixture is None:
            raise ResearchError(f"no offline fixture exists for source: {source.source_key}")
        return RetrievedDocument(
            canonical_url=fixture.url,
            title=fixture.title,
            text=fixture.text,
            retrieved_at=fixture.retrieved_at,
            content_type=fixture.content_type,
            status_code=fixture.status_code,
            duration_ms=0,
            capture_method=self.mode,
        )


@dataclass(frozen=True)
class HttpPayload:
    final_url: str
    status_code: int
    content_type: str
    body: bytes
    title: str | None = None


class HttpTransport(Protocol):
    def get(self, url: str, *, timeout_seconds: float, max_bytes: int) -> HttpPayload: ...


class HttpxTransport:
    """Small, redirect-disabled transport with no ambient proxy inheritance."""

    def get(self, url: str, *, timeout_seconds: float, max_bytes: int) -> HttpPayload:
        import httpx

        headers = {
            "Accept": "text/html,text/plain,text/markdown,application/json,application/xml",
            "User-Agent": "AI-Project-OS-v0.3-authoritative-docs/phase6",
        }
        started = time.perf_counter()
        del started  # Duration is measured by the governed retriever.
        with httpx.Client(
            follow_redirects=False,
            trust_env=False,
            timeout=timeout_seconds,
            headers=headers,
        ) as client:
            with client.stream("GET", url) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise ResearchError("HTTP response exceeds the source byte limit")
                return HttpPayload(
                    final_url=str(response.url),
                    status_code=int(response.status_code),
                    content_type=response.headers.get(
                        "content-type", "application/octet-stream"
                    ),
                    body=bytes(body),
                )


def _default_resolver(hostname: str) -> tuple[str, ...]:
    addresses = {
        str(item[4][0])
        for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    }
    return tuple(sorted(addresses))


class HttpDocumentRetriever:
    mode = RetrievalMode.LIVE_HTTP

    def __init__(
        self,
        *,
        transport: HttpTransport | None = None,
        resolver: Callable[[str], Sequence[str]] | None = None,
    ) -> None:
        self.transport = transport or HttpxTransport()
        self.resolver = resolver or _default_resolver
        self.call_count = 0

    def retrieve(
        self, source: SourceSpec, policy: ResearchPolicy
    ) -> RetrievedDocument:
        if not policy.allow_live_http:
            raise LiveRetrievalDenied("live HTTP retrieval is disabled by policy")
        parsed = urlsplit(source.url)
        assert parsed.hostname is not None
        hostname = parsed.hostname.casefold()
        if hostname not in policy.allowed_hosts:
            raise LiveRetrievalDenied("source hostname is not allowlisted")
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            raise UnsafeResearchUrl("IP-literal research targets are not allowed")
        addresses = tuple(self.resolver(hostname))
        if not addresses:
            raise UnsafeResearchUrl("research source hostname did not resolve")
        for value in addresses:
            try:
                address = ipaddress.ip_address(value)
            except ValueError as exc:
                raise UnsafeResearchUrl("resolver returned an invalid IP address") from exc
            if not address.is_global:
                raise UnsafeResearchUrl(
                    "research source resolved to a non-public network address"
                )

        self.call_count += 1
        started = time.perf_counter()
        payload = self.transport.get(
            source.url,
            timeout_seconds=policy.timeout_seconds,
            max_bytes=policy.max_source_bytes,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        if 300 <= payload.status_code < 400:
            raise UnsafeResearchUrl("HTTP redirects are refused")
        if not 200 <= payload.status_code < 300:
            raise ResearchError(f"HTTP retrieval failed with status {payload.status_code}")
        final_url = canonicalize_url(payload.final_url)
        if final_url != source.url:
            raise UnsafeResearchUrl("HTTP transport returned an unexpected final URL")
        content_type = payload.content_type.casefold().split(";", 1)[0].strip()
        if content_type not in policy.allowed_content_types:
            raise ResearchError(f"HTTP content type is not allowed: {content_type}")
        if len(payload.body) > policy.max_source_bytes:
            raise ResearchError("HTTP response exceeds the source byte limit")
        try:
            text = payload.body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ResearchError("HTTP response is not valid UTF-8 text") from exc
        return RetrievedDocument(
            canonical_url=final_url,
            title=payload.title or source.title,
            text=text,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            content_type=content_type,
            status_code=payload.status_code,
            duration_ms=duration_ms,
            capture_method=self.mode,
        )


@dataclass(frozen=True)
class SourceCapture:
    source_id: str
    source_key: str
    requested_url: str
    canonical_url: str
    title: str
    source_type: SourceType
    is_primary: bool
    capture_method: RetrievalMode
    retrieved_at: str
    applicable_version: str | None
    applicable_date: str | None
    content_type: str
    status_code: int
    content_sha256: str
    content_text: str
    content_bytes: int
    duration_ms: int


@dataclass(frozen=True)
class ResearchResult:
    run_id: str
    task_id: str
    objective: str
    status: str
    retrieval_mode: RetrievalMode
    sources: tuple[SourceCapture, ...]
    claims: tuple[ClaimSpec, ...]
    request_count: int
    bytes_retrieved: int
    cost_usd: float
    replayed: bool = False


def research_request_sha256(
    request: ResearchRequest,
    policy: ResearchPolicy,
    retrieval_mode: RetrievalMode,
) -> str:
    payload = {
        "task_id": request.task_id,
        "objective": request.objective,
        "idempotency_key": request.idempotency_key,
        "sources": [
            {
                **asdict(source),
                "source_type": source.source_type.value,
            }
            for source in request.sources
        ],
        "claims": [
            {
                **asdict(claim),
                "claim_type": claim.claim_type.value,
                "citations": [asdict(citation) for citation in claim.citations],
            }
            for claim in request.claims
        ],
        "require_primary_source": request.require_primary_source,
        "retrieval_mode": retrieval_mode.value,
        "policy": {
            "allow_live_http": policy.allow_live_http,
            "allowed_hosts": sorted(policy.allowed_hosts),
            "max_sources": policy.max_sources,
            "max_claims": policy.max_claims,
            "max_source_bytes": policy.max_source_bytes,
            "max_total_bytes": policy.max_total_bytes,
            "timeout_seconds": float(policy.timeout_seconds),
            "allowed_content_types": sorted(policy.allowed_content_types),
        },
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalized_excerpt(value: str) -> str:
    return " ".join(value.split()).casefold()


class ResearchStore:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def claim(
        self,
        request: ResearchRequest,
        *,
        request_sha256: str,
        retrieval_mode: RetrievalMode,
    ) -> tuple[bool, dict[str, Any]]:
        now = utc_now()
        with self.ledger.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute(
                "SELECT * FROM research_runs WHERE idempotency_key=?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                record = dict(existing)
                if record["request_sha256"] != request_sha256:
                    raise ResearchIdempotencyConflict(
                        "research idempotency key belongs to a different request"
                    )
                return False, record
            con.execute(
                """
                INSERT INTO research_runs(
                    run_id,task_id,objective,idempotency_key,request_sha256,
                    status,retrieval_mode,require_primary_source,started_at,updated_at
                ) VALUES(?,?,?,?,?,'retrieving',?,?,?,?)
                """,
                (
                    request.run_id,
                    request.task_id,
                    request.objective,
                    request.idempotency_key,
                    request_sha256,
                    retrieval_mode.value,
                    int(request.require_primary_source),
                    now,
                    now,
                ),
            )
            self._event(
                con,
                request.task_id,
                "research_started",
                {
                    "run_id": request.run_id,
                    "retrieval_mode": retrieval_mode.value,
                    "source_count": len(request.sources),
                    "claim_count": len(request.claims),
                },
                now,
            )
            row = con.execute(
                "SELECT * FROM research_runs WHERE run_id=?", (request.run_id,)
            ).fetchone()
            assert row is not None
            return True, dict(row)

    @staticmethod
    def _event(con, task_id: str, event_type: str, payload: Mapping[str, Any], now: str) -> None:
        con.execute(
            """
            INSERT INTO events(task_id,event_type,payload_json,created_at)
            VALUES(?,?,?,?)
            """,
            (task_id, event_type, json.dumps(dict(payload), sort_keys=True), now),
        )

    def sources(self, run_id: str) -> list[dict[str, Any]]:
        with self.ledger.connect() as con:
            rows = con.execute(
                "SELECT * FROM research_sources WHERE run_id=? ORDER BY ordinal",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_source(
        self,
        *,
        run_id: str,
        ordinal: int,
        source: SourceSpec,
        document: RetrievedDocument,
    ) -> dict[str, Any]:
        content = document.text.encode("utf-8")
        content_sha256 = hashlib.sha256(content).hexdigest()
        source_id = hashlib.sha256(
            f"{run_id}\x00{source.source_key}".encode("utf-8")
        ).hexdigest()
        now = utc_now()
        with self.ledger.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            run = con.execute(
                "SELECT task_id,status FROM research_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise ResearchError("research run does not exist")
            if run["status"] != "retrieving":
                raise ResearchError("research source cannot be added in the current state")
            existing = con.execute(
                "SELECT * FROM research_sources WHERE run_id=? AND source_key=?",
                (run_id, source.source_key),
            ).fetchone()
            if existing is not None:
                if (
                    existing["content_sha256"] != content_sha256
                    or existing["canonical_url"] != document.canonical_url
                ):
                    raise ResearchIdempotencyConflict(
                        "stored research source differs from replayed source"
                    )
                return dict(existing)
            con.execute(
                """
                INSERT INTO research_sources(
                    source_id,run_id,source_key,ordinal,requested_url,canonical_url,
                    title,source_type,is_primary,capture_method,retrieved_at,
                    applicable_version,applicable_date,content_type,status_code,
                    content_sha256,content_text,content_bytes,duration_ms
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    source_id,
                    run_id,
                    source.source_key,
                    ordinal,
                    source.url,
                    document.canonical_url,
                    document.title,
                    source.source_type.value,
                    int(source.is_primary),
                    document.capture_method.value,
                    document.retrieved_at,
                    source.applicable_version,
                    source.applicable_date,
                    document.content_type,
                    document.status_code,
                    content_sha256,
                    document.text,
                    len(content),
                    document.duration_ms,
                ),
            )
            self._event(
                con,
                str(run["task_id"]),
                "research_source_captured",
                {
                    "run_id": run_id,
                    "source_id": source_id,
                    "source_key": source.source_key,
                    "content_sha256": content_sha256,
                    "content_bytes": len(content),
                    "capture_method": document.capture_method.value,
                },
                now,
            )
            row = con.execute(
                "SELECT * FROM research_sources WHERE source_id=?", (source_id,)
            ).fetchone()
            assert row is not None
            return dict(row)

    def complete(self, request: ResearchRequest, *, run_id: str | None = None) -> None:
        durable_run_id = run_id or request.run_id
        now = utc_now()
        with self.ledger.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            run = con.execute(
                "SELECT * FROM research_runs WHERE run_id=?", (durable_run_id,)
            ).fetchone()
            if run is None or run["status"] != "retrieving":
                raise ResearchError("research run is not ready for completion")
            sources = con.execute(
                "SELECT * FROM research_sources WHERE run_id=? ORDER BY ordinal",
                (durable_run_id,),
            ).fetchall()
            if len(sources) != len(request.sources):
                raise ResearchError("research run does not contain every requested source")
            source_by_key = {str(row["source_key"]).casefold(): row for row in sources}
            for claim in request.claims:
                claim_record_id = hashlib.sha256(
                    f"{durable_run_id}\x00{claim.claim_key}".encode("utf-8")
                ).hexdigest()
                con.execute(
                    """
                    INSERT INTO research_claims(
                        claim_record_id,run_id,claim_key,statement,claim_type,
                        rationale,created_at
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        claim_record_id,
                        durable_run_id,
                        claim.claim_key,
                        claim.statement,
                        claim.claim_type.value,
                        claim.rationale,
                        now,
                    ),
                )
                for citation in claim.citations:
                    source = source_by_key[citation.source_key.casefold()]
                    excerpt_sha256 = hashlib.sha256(
                        citation.excerpt.encode("utf-8")
                    ).hexdigest()
                    con.execute(
                        """
                        INSERT INTO research_citations(
                            claim_record_id,source_id,excerpt,excerpt_sha256
                        ) VALUES(?,?,?,?)
                        """,
                        (
                            claim_record_id,
                            source["source_id"],
                            citation.excerpt,
                            excerpt_sha256,
                        ),
                    )
            request_count = sum(
                1 for row in sources if row["capture_method"] == RetrievalMode.LIVE_HTTP.value
            )
            # Fixture reads are counted as research retrieval operations as well.
            if sources and request_count == 0:
                request_count = len(sources)
            bytes_retrieved = sum(int(row["content_bytes"]) for row in sources)
            cursor = con.execute(
                """
                UPDATE research_runs
                SET status='completed',source_count=?,claim_count=?,request_count=?,
                    bytes_retrieved=?,cost_usd=0,completed_at=?,updated_at=?,error=NULL
                WHERE run_id=? AND status='retrieving'
                """,
                (
                    len(sources),
                    len(request.claims),
                    request_count,
                    bytes_retrieved,
                    now,
                    now,
                    durable_run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ResearchError("research run completion state changed concurrently")
            self._event(
                con,
                request.task_id,
                "research_completed",
                {
                    "run_id": durable_run_id,
                    "source_count": len(sources),
                    "claim_count": len(request.claims),
                    "bytes_retrieved": bytes_retrieved,
                    "cost_usd": 0,
                },
                now,
            )

    def fail(self, run_id: str, error: str, *, recovery_required: bool) -> None:
        status = "recovery_required" if recovery_required else "failed"
        now = utc_now()
        safe_error = _safe_text("research error", error, maximum=4_000)
        with self.ledger.connect() as con:
            run = con.execute(
                "SELECT task_id,status FROM research_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None:
                return
            if run["status"] != "retrieving":
                return
            con.execute(
                """
                UPDATE research_runs SET status=?,error=?,completed_at=?,updated_at=?
                WHERE run_id=? AND status='retrieving'
                """,
                (status, safe_error, now, now, run_id),
            )
            self._event(
                con,
                str(run["task_id"]),
                "research_recovery_required" if recovery_required else "research_failed",
                {"run_id": run_id, "error": safe_error},
                now,
            )

    def load_result(self, run_id: str, *, replayed: bool) -> ResearchResult:
        with self.ledger.connect() as con:
            run = con.execute(
                "SELECT * FROM research_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None or run["status"] != "completed":
                raise ResearchRunNotReplayable("research run is not completed")
            source_rows = con.execute(
                "SELECT * FROM research_sources WHERE run_id=? ORDER BY ordinal",
                (run_id,),
            ).fetchall()
            claim_rows = con.execute(
                "SELECT * FROM research_claims WHERE run_id=? ORDER BY claim_key",
                (run_id,),
            ).fetchall()
            citation_rows = con.execute(
                """
                SELECT c.claim_record_id,c.excerpt,s.source_key
                FROM research_citations c
                JOIN research_sources s ON s.source_id=c.source_id
                JOIN research_claims q ON q.claim_record_id=c.claim_record_id
                WHERE q.run_id=?
                ORDER BY c.claim_record_id,s.source_key
                """,
                (run_id,),
            ).fetchall()
        captures = tuple(
            SourceCapture(
                source_id=str(row["source_id"]),
                source_key=str(row["source_key"]),
                requested_url=str(row["requested_url"]),
                canonical_url=str(row["canonical_url"]),
                title=str(row["title"]),
                source_type=SourceType(str(row["source_type"])),
                is_primary=bool(row["is_primary"]),
                capture_method=RetrievalMode(str(row["capture_method"])),
                retrieved_at=str(row["retrieved_at"]),
                applicable_version=row["applicable_version"],
                applicable_date=row["applicable_date"],
                content_type=str(row["content_type"]),
                status_code=int(row["status_code"]),
                content_sha256=str(row["content_sha256"]),
                content_text=str(row["content_text"]),
                content_bytes=int(row["content_bytes"]),
                duration_ms=int(row["duration_ms"]),
            )
            for row in source_rows
        )
        citations_by_claim: dict[str, list[CitationSpec]] = {}
        for row in citation_rows:
            citations_by_claim.setdefault(str(row["claim_record_id"]), []).append(
                CitationSpec(
                    source_key=str(row["source_key"]),
                    excerpt=str(row["excerpt"]),
                )
            )
        claims = tuple(
            ClaimSpec(
                claim_key=str(row["claim_key"]),
                statement=str(row["statement"]),
                claim_type=ClaimType(str(row["claim_type"])),
                citations=tuple(citations_by_claim.get(str(row["claim_record_id"]), ())),
                rationale=row["rationale"],
            )
            for row in claim_rows
        )
        return ResearchResult(
            run_id=str(run["run_id"]),
            task_id=str(run["task_id"]),
            objective=str(run["objective"]),
            status=str(run["status"]),
            retrieval_mode=RetrievalMode(str(run["retrieval_mode"])),
            sources=captures,
            claims=claims,
            request_count=int(run["request_count"]),
            bytes_retrieved=int(run["bytes_retrieved"]),
            cost_usd=float(run["cost_usd"]),
            replayed=replayed,
        )


class ResearchRunner:
    def __init__(
        self,
        ledger: Ledger,
        retriever: DocumentRetriever,
        *,
        policy: ResearchPolicy | None = None,
    ) -> None:
        self.store = ResearchStore(ledger)
        self.retriever = retriever
        self.policy = policy or ResearchPolicy()

    def run(self, request: ResearchRequest) -> ResearchResult:
        self.policy.validate_request(request)
        if self.retriever.mode == RetrievalMode.LIVE_HTTP and not self.policy.allow_live_http:
            raise LiveRetrievalDenied("live HTTP retrieval is disabled by policy")
        fingerprint = research_request_sha256(
            request,
            self.policy,
            self.retriever.mode,
        )
        claimed, record = self.store.claim(
            request,
            request_sha256=fingerprint,
            retrieval_mode=self.retriever.mode,
        )
        if not claimed:
            status = str(record["status"])
            if status == "completed":
                return self.store.load_result(str(record["run_id"]), replayed=True)
            if status == "retrieving" and self.retriever.mode == RetrievalMode.LIVE_HTTP:
                self.store.fail(
                    str(record["run_id"]),
                    "live retrieval has an incomplete durable dispatch boundary",
                    recovery_required=True,
                )
                raise ResearchRecoveryRequired(
                    "incomplete live research requires reviewed recovery"
                )
            if status not in {"retrieving"}:
                raise ResearchRunNotReplayable(
                    f"research run cannot replay from terminal state: {status}"
                )

        run_id = str(record["run_id"])
        try:
            existing = {
                str(item["source_key"]).casefold(): item
                for item in self.store.sources(run_id)
            }
            total_bytes = sum(int(item["content_bytes"]) for item in existing.values())
            for ordinal, source in enumerate(request.sources, start=1):
                if source.source_key.casefold() in existing:
                    continue
                document = self.retriever.retrieve(source, self.policy)
                canonical = canonicalize_url(document.canonical_url)
                if canonical != source.url:
                    raise ResearchError("retrieved source URL differs from the request")
                content_type = document.content_type.casefold().split(";", 1)[0].strip()
                if content_type not in self.policy.allowed_content_types:
                    raise ResearchError(
                        f"retrieved content type is not allowed: {content_type}"
                    )
                content_bytes = len(document.text.encode("utf-8"))
                if content_bytes > self.policy.max_source_bytes:
                    raise ResearchError("retrieved source exceeds the source byte limit")
                total_bytes += content_bytes
                if total_bytes > self.policy.max_total_bytes:
                    raise ResearchError("research run exceeds the total byte limit")
                safe_document = RetrievedDocument(
                    canonical_url=canonical,
                    title=_safe_text("retrieved title", document.title, maximum=500),
                    text=_safe_text(
                        "retrieved text",
                        document.text,
                        maximum=self.policy.max_source_bytes,
                    ),
                    retrieved_at=_iso_timestamp(
                        "retrieved_at", document.retrieved_at
                    ),
                    content_type=content_type,
                    status_code=document.status_code,
                    duration_ms=document.duration_ms,
                    capture_method=document.capture_method,
                )
                self.store.record_source(
                    run_id=run_id,
                    ordinal=ordinal,
                    source=source,
                    document=safe_document,
                )

            captured = {
                str(item["source_key"]).casefold(): str(item["content_text"])
                for item in self.store.sources(run_id)
            }
            for claim in request.claims:
                for citation in claim.citations:
                    haystack = _normalized_excerpt(captured[citation.source_key.casefold()])
                    needle = _normalized_excerpt(citation.excerpt)
                    if needle not in haystack:
                        raise ResearchError(
                            f"citation excerpt was not found in captured source: {citation.source_key}"
                        )
            self.store.complete(request, run_id=run_id)
            return self.store.load_result(run_id, replayed=False)
        except Exception as exc:
            recovery_required = self.retriever.mode == RetrievalMode.LIVE_HTTP and not isinstance(
                exc,
                (
                    LiveRetrievalDenied,
                    UnsafeResearchUrl,
                    ResearchIdempotencyConflict,
                ),
            )
            self.store.fail(
                run_id,
                f"{type(exc).__name__}: {exc}",
                recovery_required=recovery_required,
            )
            raise
