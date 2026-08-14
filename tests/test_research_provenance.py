from __future__ import annotations

from dataclasses import replace

import pytest

from ledger import Ledger
from research_provenance import (
    CitationSpec,
    ClaimSpec,
    ClaimType,
    FixtureDocument,
    FixtureRetriever,
    HttpDocumentRetriever,
    HttpPayload,
    LiveRetrievalDenied,
    ResearchError,
    ResearchIdempotencyConflict,
    ResearchPolicy,
    ResearchRequest,
    ResearchRunNotReplayable,
    ResearchRunner,
    ResearchStore,
    RetrievalMode,
    SourceSpec,
    SourceType,
    UnsafeResearchUrl,
    research_request_sha256,
)


DOCS_URL = "https://docs.example.test/platform/models"
PRICING_URL = "https://pricing.example.test/api"
RETRIEVED_AT = "2026-08-14T12:00:00+00:00"


def make_request(*, run_id="research-run-1", idempotency_key="research:key:v1"):
    return ResearchRequest(
        run_id=run_id,
        task_id="task-research",
        objective="Verify the current documented model and pricing metadata.",
        idempotency_key=idempotency_key,
        sources=(
            SourceSpec(
                source_key="official-models",
                url=DOCS_URL,
                title="Official model documentation",
                source_type=SourceType.OFFICIAL_DOCUMENTATION,
                is_primary=True,
                applicable_version="2026-08",
                applicable_date="2026-08-14",
            ),
            SourceSpec(
                source_key="official-pricing",
                url=PRICING_URL,
                title="Official API pricing",
                source_type=SourceType.OFFICIAL_PRICING,
                is_primary=True,
                applicable_date="2026-08-14",
            ),
        ),
        claims=(
            ClaimSpec(
                claim_key="model-fact",
                statement="The documented model identifier is model-current.",
                claim_type=ClaimType.SOURCED_FACT,
                citations=(
                    CitationSpec(
                        source_key="official-models",
                        excerpt="The current API model is model-current.",
                    ),
                ),
            ),
            ClaimSpec(
                claim_key="planning-inference",
                statement="The current model should be rechecked before a paid run.",
                claim_type=ClaimType.INFERENCE,
                citations=(
                    CitationSpec(
                        source_key="official-pricing",
                        excerpt="Prices can change after the applicable date.",
                    ),
                ),
                rationale="The captured page explicitly identifies time-sensitive pricing.",
            ),
        ),
    )


def make_fixtures():
    documents = (
        FixtureDocument(
            url=DOCS_URL,
            title="Official model documentation",
            text="The current API model is model-current. Applicable version: 2026-08.",
            retrieved_at=RETRIEVED_AT,
        ),
        FixtureDocument(
            url=PRICING_URL,
            title="Official API pricing",
            text="Prices can change after the applicable date. Verify before spending.",
            retrieved_at=RETRIEVED_AT,
            content_type="text/markdown",
        ),
    )
    return {item.url: item for item in documents}


def test_fixture_research_records_provenance_telemetry_and_replays(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db", project_root=tmp_path)
    request = make_request()
    first_retriever = FixtureRetriever(make_fixtures())

    first = ResearchRunner(ledger, first_retriever).run(request)

    assert first.status == "completed"
    assert first.replayed is False
    assert first_retriever.call_count == 2
    assert first.request_count == 2
    assert first.cost_usd == 0
    assert len(first.sources) == 2
    assert len(first.claims) == 2
    assert first.sources[0].capture_method == RetrievalMode.OFFLINE_FIXTURE
    assert first.sources[0].applicable_version == "2026-08"
    assert first.sources[0].applicable_date == "2026-08-14"
    assert first.sources[0].content_sha256
    assert first.bytes_retrieved == sum(item.content_bytes for item in first.sources)

    replay_retriever = FixtureRetriever(make_fixtures())
    replayed = ResearchRunner(ledger, replay_retriever).run(
        replace(request, run_id="ignored-replay-run-id")
    )

    assert replayed.run_id == request.run_id
    assert replayed.replayed is True
    assert replay_retriever.call_count == 0
    with ledger.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM research_sources").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM research_claims").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM research_citations").fetchone()[0] == 2
        payloads = [
            row[0]
            for row in con.execute(
                "SELECT payload_json FROM events WHERE event_type LIKE 'research_%'"
            ).fetchall()
        ]
    assert payloads
    assert str(tmp_path) not in "".join(payloads)
    assert "0004_research_provenance" in ledger.schema_migration_ids()


def test_offline_research_resumes_from_a_durable_source_without_refetch(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db", project_root=tmp_path)
    request = make_request()
    policy = ResearchPolicy()
    retriever = FixtureRetriever(make_fixtures())
    store = ResearchStore(ledger)
    claimed, _ = store.claim(
        request,
        request_sha256=research_request_sha256(
            request,
            policy,
            RetrievalMode.OFFLINE_FIXTURE,
        ),
        retrieval_mode=RetrievalMode.OFFLINE_FIXTURE,
    )
    assert claimed is True
    first_document = retriever.retrieve(request.sources[0], policy)
    store.record_source(
        run_id=request.run_id,
        ordinal=1,
        source=request.sources[0],
        document=first_document,
    )
    assert retriever.call_count == 1

    resumed = ResearchRunner(ledger, retriever, policy=policy).run(request)

    assert resumed.status == "completed"
    assert retriever.call_count == 2
    assert len(resumed.sources) == 2


def test_research_rejects_changed_idempotent_request_and_fabricated_citation(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db", project_root=tmp_path)
    request = make_request()
    runner = ResearchRunner(ledger, FixtureRetriever(make_fixtures()))
    runner.run(request)

    with pytest.raises(ResearchIdempotencyConflict):
        runner.run(replace(request, objective="A different objective"))
    with pytest.raises(ResearchIdempotencyConflict):
        ResearchRunner(
            ledger,
            FixtureRetriever(make_fixtures()),
            policy=ResearchPolicy(max_source_bytes=600_000),
        ).run(request)

    invalid = replace(
        request,
        run_id="research-run-invalid",
        idempotency_key="research:invalid:v1",
        claims=(
            ClaimSpec(
                claim_key="fabricated",
                statement="A claim whose quote is absent.",
                claim_type=ClaimType.SOURCED_FACT,
                citations=(
                    CitationSpec(
                        source_key="official-models",
                        excerpt="This sentence does not exist in the capture.",
                    ),
                ),
            ),
        ),
    )
    invalid_runner = ResearchRunner(ledger, FixtureRetriever(make_fixtures()))
    with pytest.raises(ResearchError, match="excerpt was not found"):
        invalid_runner.run(invalid)
    with pytest.raises(ResearchRunNotReplayable, match="terminal state: failed"):
        invalid_runner.run(invalid)


def test_research_request_requires_structured_primary_evidence():
    with pytest.raises(ValueError, match="SOURCED_FACT"):
        ClaimSpec(
            claim_key="unsupported",
            statement="Unsupported fact",
            claim_type=ClaimType.SOURCED_FACT,
        )

    with pytest.raises(ValueError, match="SECONDARY"):
        SourceSpec(
            source_key="misclassified",
            url="https://secondary.example.test/page",
            title="Misclassified secondary page",
            source_type=SourceType.SECONDARY,
            is_primary=True,
        )

    secondary = SourceSpec(
        source_key="secondary",
        url="https://secondary.example.test/page",
        title="Secondary page",
        source_type=SourceType.SECONDARY,
        is_primary=False,
    )
    with pytest.raises(ValueError, match="primary source"):
        ResearchRequest(
            run_id="no-primary",
            task_id="task",
            objective="Research",
            idempotency_key="no-primary:v1",
            sources=(secondary,),
        )

    with pytest.raises(UnsafeResearchUrl, match="HTTPS"):
        replace(secondary, url="http://secondary.example.test/page")
    with pytest.raises(UnsafeResearchUrl, match="user information"):
        replace(secondary, url="https://user:secret@secondary.example.test/page")


class FakeTransport:
    def __init__(self, payload: HttpPayload):
        self.payload = payload
        self.calls = 0

    def get(self, url, *, timeout_seconds, max_bytes):
        self.calls += 1
        return self.payload


def live_source(url=DOCS_URL):
    return SourceSpec(
        source_key="live-docs",
        url=url,
        title="Live official docs",
        source_type=SourceType.OFFICIAL_DOCUMENTATION,
        is_primary=True,
        applicable_date="2026-08-14",
    )


def test_live_http_is_disabled_before_dns_or_transport_dispatch(tmp_path):
    transport = FakeTransport(
        HttpPayload(
            final_url=DOCS_URL,
            status_code=200,
            content_type="text/plain",
            body=b"authoritative text",
        )
    )
    resolver_calls = []
    retriever = HttpDocumentRetriever(
        transport=transport,
        resolver=lambda host: resolver_calls.append(host) or ("93.184.216.34",),
    )
    request = ResearchRequest(
        run_id="live-disabled",
        task_id="task-live",
        objective="Retrieve official documentation.",
        idempotency_key="live-disabled:v1",
        sources=(live_source(),),
    )

    with pytest.raises(LiveRetrievalDenied, match="disabled"):
        ResearchRunner(Ledger(tmp_path / "ledger.db"), retriever).run(request)

    assert transport.calls == 0
    assert resolver_calls == []


def test_live_http_policy_accepts_only_bounded_public_allowlisted_text():
    source = live_source()
    policy = ResearchPolicy(
        allow_live_http=True,
        allowed_hosts=frozenset({"docs.example.test"}),
        max_source_bytes=100,
        max_total_bytes=100,
    )
    success = FakeTransport(
        HttpPayload(
            final_url=DOCS_URL,
            status_code=200,
            content_type="text/plain; charset=utf-8",
            body=b"authoritative text",
        )
    )
    retriever = HttpDocumentRetriever(
        transport=success,
        resolver=lambda host: ("93.184.216.34",),
    )

    document = retriever.retrieve(source, policy)

    assert document.text == "authoritative text"
    assert document.capture_method == RetrievalMode.LIVE_HTTP
    assert success.calls == 1

    private = HttpDocumentRetriever(
        transport=success,
        resolver=lambda host: ("127.0.0.1",),
    )
    with pytest.raises(UnsafeResearchUrl, match="non-public"):
        private.retrieve(source, policy)

    with pytest.raises(LiveRetrievalDenied, match="not allowlisted"):
        retriever.retrieve(
            replace(source, url="https://other.example.test/page"),
            policy,
        )
    with pytest.raises(UnsafeResearchUrl, match="IP-literal"):
        HttpDocumentRetriever(
            transport=success,
            resolver=lambda host: ("93.184.216.34",),
        ).retrieve(
            replace(source, url="https://93.184.216.34/page"),
            replace(policy, allowed_hosts=frozenset({"93.184.216.34"})),
        )

    redirect = HttpDocumentRetriever(
        transport=FakeTransport(
            HttpPayload(
                final_url=DOCS_URL,
                status_code=302,
                content_type="text/plain",
                body=b"redirect",
            )
        ),
        resolver=lambda host: ("93.184.216.34",),
    )
    with pytest.raises(UnsafeResearchUrl, match="redirects"):
        redirect.retrieve(source, policy)

    binary = HttpDocumentRetriever(
        transport=FakeTransport(
            HttpPayload(
                final_url=DOCS_URL,
                status_code=200,
                content_type="application/octet-stream",
                body=b"binary",
            )
        ),
        resolver=lambda host: ("93.184.216.34",),
    )
    with pytest.raises(ResearchError, match="content type"):
        binary.retrieve(source, policy)

    oversized = HttpDocumentRetriever(
        transport=FakeTransport(
            HttpPayload(
                final_url=DOCS_URL,
                status_code=200,
                content_type="text/plain",
                body=b"x" * 101,
            )
        ),
        resolver=lambda host: ("93.184.216.34",),
    )
    with pytest.raises(ResearchError, match="byte limit"):
        oversized.retrieve(source, policy)
