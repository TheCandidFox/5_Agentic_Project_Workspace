# Authoritative Documentation Research — Phase 6 Tranche A

**Status:** implemented and verified with deterministic offline tests
**Default network posture:** denied
**Provider calls:** none

## Components

`research_provenance.py` adds an application-owned research action with:

- structured source plans and stable idempotency identities;
- authoritative/primary source metadata;
- URL, title, source type, applicable version/date, and retrieval timestamp;
- bounded captured UTF-8 text and SHA-256 evidence;
- `SOURCED_FACT`, `INFERENCE`, and `UNRESOLVED` claim types;
- claim-to-source excerpts that must occur in the captured source;
- deterministic fixture execution and completed-run replay;
- restart/resume from already captured offline sources;
- request, byte, duration, and zero-cost telemetry;
- a live HTTP adapter that is disabled unless explicitly authorized.

Migration `0004_research_provenance` adds `research_runs`,
`research_sources`, `research_claims`, and `research_citations`. The migration is
additive and checksummed by the existing ledger migration mechanism.

## Research sequence

`ResearchRunner.run()` performs this sequence:

1. validate the structured request and policy bounds;
2. fingerprint the complete request semantics;
3. claim the idempotency key under an immediate SQLite transaction;
4. replay a completed run without retrieval, when available;
5. reuse any already captured offline source after restart;
6. retrieve each missing source through the injected retriever;
7. enforce per-source and per-run byte/content-type bounds;
8. store capture metadata, text hash, bounded text, and compact events;
9. verify that every citation refers to a captured source and that its excerpt
   occurs in that captured text;
10. durably store claims/citations and complete the run.

A reused idempotency key with different request semantics is rejected. A failed
or recovery-required run is not silently retried under the same key.

## Offline fixture mode

`FixtureRetriever` is the only mode used by automated acceptance. Fixtures
provide a controlled URL, title, content type, captured text, status, and
timezone-aware retrieval timestamp. Replaying a completed research request
returns the SQLite evidence and makes zero retriever calls.

This allows provenance and staleness/version behavior to be tested without a
changed web page, network outage, DNS difference, provider fee, or hidden live
request.

## Live HTTP boundary

`HttpDocumentRetriever` and `HttpxTransport` are included for later authorized
use. The default `ResearchPolicy` has `allow_live_http=False` and an empty host
allowlist. The runner rejects live mode before DNS resolution or transport
dispatch.

When separately enabled, the adapter requires:

- exact allowlisted hostname;
- HTTPS with no URL user information and only the default port;
- non-IP-literal hostname;
- DNS results whose addresses are all public/global;
- redirects refused;
- successful HTTP status;
- allowlisted textual content type;
- valid UTF-8 text;
- finite timeout and bounded source size;
- `httpx` with `trust_env=False` and `follow_redirects=False`.

The resolver check is an application boundary, not a complete hostile-network
sandbox: a DNS-rebinding-capable network could change resolution between the
policy check and the transport connection. A future production transport should
pin the validated address while preserving TLS hostname verification or run in
a network sandbox. Until then, live retrieval remains an explicit, narrow,
human-authorized test capability.

## Evidence posture

`SOURCED_FACT` proves that a statement has a traceable captured excerpt. It does
not by itself prove that a source is correct. The Phase 6 acceptance/truth layer
governs whether evidence warrants `VERIFIED`, `SUPPORTED`, `INFERRED`,
`DISPUTED`, or `UNKNOWN`.

The local bootstrap stores bounded source text in SQLite for replay. Large raw
captures and long-lived artifact/object storage are deliberately deferred.

## Verified cases

The tranche tests cover:

- two authoritative captures with version/date metadata;
- content hashing, citation storage, and compact events;
- completed replay with zero retrieval calls;
- offline resume after one durable source capture;
- changed idempotent request rejection;
- fabricated/missing excerpt rejection;
- required primary-source enforcement;
- HTTP and credential-bearing URL rejection;
- live-mode denial before DNS/transport;
- exact host allowlisting;
- private-address, IP-literal, redirect, binary-content, and oversized-response
  rejection;
- fake-transport success with no real network access.
