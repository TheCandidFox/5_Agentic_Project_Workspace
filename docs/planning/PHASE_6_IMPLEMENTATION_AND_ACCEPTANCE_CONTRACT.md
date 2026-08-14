# AI Project OS v0.3 — Phase 6 Implementation and Acceptance Contract

**Status:** approved implementation boundary
**Baseline source:** recovered Phase 5 snapshot originally associated with
`a83880594c8337af1c36acd947a59c7f0241cf48`
**Validated recovered repository baseline:**
`e007c9edcf408cfba45e6cebc9978ef7621beab6`
**Target branch on the user's repository:** `bootstrap/local-execution`
**Execution posture:** offline-first; no paid provider calls; live HTTP disabled
by default

## 1. Purpose

Phase 6 completes the local bootstrap needed before the general project
contract/orchestration layer is built. It adds three separately testable and
reversible tranches:

1. current-authoritative-documentation research with provenance;
2. acceptance and truth governance;
3. an integrated final bootstrap acceptance gate.

Phase 6 does not make the program a general Markdown-goal runner. That work is
the next development phase. Phase 6 supplies the governed research and
acceptance primitives that runner will depend on.

## 2. Preserved Baseline and Hard Boundaries

The following Phase 1–5 behavior must remain intact:

- workspace/path confinement;
- shell-free allowlisted local command execution;
- secret/environment protection and redaction;
- durable, idempotent command and validation records;
- normalized deterministic validation;
- hash-locked transactional patches and exact rollback;
- scoped local Git checkpoints;
- bounded repair attempts, cost, duration, repeated failure/patch, and
  no-progress limits;
- conservative recovery for ambiguous dispatch;
- portable project-relative paths;
- additive, checksummed SQLite migrations;
- the frozen v0.2 architecture and validation references.

Phase 6 must not:

- construct or call OpenAI, Anthropic, or another model provider;
- authorize paid repair or paid research;
- make a live HTTP request from the default or acceptance entry point;
- enable redirects, ambient proxy use, unrestricted URLs, or private-network
  retrieval;
- merge, push, fetch, or otherwise contact a Git remote;
- promote the candidate to the approved baseline;
- deploy cloud infrastructure or production systems;
- add a PWA, GraphRAG, permanent vector service, or broad provider layer;
- read, persist, log, or package credentials;
- modify the frozen v0.2 backup or an unrelated directory.

## 3. Tranche A — Authoritative Documentation Research

### 3.1 Structured research request

A research action is application-owned and machine-readable. It records:

- stable run, task, and idempotency identities;
- objective and source plan;
- URL and canonical URL;
- source key, title, type, and primary/secondary designation;
- applicable version and/or applicable date when supplied;
- whether a primary source is required;
- bounded source and run byte limits;
- retrieval mode and live-network authority.

The request fingerprint includes all semantics that could change the result.
Reusing an idempotency key for a different request fails closed.

### 3.2 Source capture

Each captured source records:

- requested and canonical URL;
- capture method: `OFFLINE_FIXTURE` or `LIVE_HTTP`;
- retrieval timestamp;
- applicable version/date;
- HTTP status and content type where relevant;
- primary-source designation and source type;
- bounded UTF-8 text, exact byte count, and SHA-256;
- duration and run-level request/byte/cost telemetry.

The local bootstrap stores bounded source text in SQLite so the evidence can be
replayed without silently retrieving a changed page. Larger artifact storage is
deferred to the later artifact/memory architecture.

### 3.3 Claim-to-source provenance

Research manifests distinguish:

- `SOURCED_FACT` — requires at least one citation to a captured source;
- `INFERENCE` — requires an explicit rationale and may cite supporting sources;
- `UNRESOLVED` — preserves uncertainty without fabricating support.

A citation identifies a captured source and a bounded excerpt. For a sourced
fact, the normalized excerpt must occur in the captured text. Unknown source
keys, missing excerpts, duplicate identities, and fabricated citations fail
before the run is completed.

Source conflict is represented later by `DISPUTED`; the research layer does
not average conflicting claims into a synthetic fact.

### 3.4 Offline-first and live HTTP posture

All automated tests and the Phase 6 acceptance entry point use deterministic
fixtures. Fixture content, URLs, timestamps, applicable versions/dates, and
hashes are controlled test inputs.

A real HTTP adapter is included but disabled by default. Enabling it requires
all of the following:

- an explicit `allow_live_http=True` policy;
- an explicit hostname allowlist;
- HTTPS;
- no user information in the URL;
- no IP-literal target;
- public DNS results only;
- no ambient proxy inheritance;
- redirects refused rather than followed;
- an allowlisted textual content type;
- bounded timeout and response size.

The adapter is a local retrieval primitive, not authorization for an autonomous
or paid run. A live smoke test remains a separate human-approved gate.

### 3.5 Research durability

Migration `0004_research_provenance` adds:

- `research_runs`;
- `research_sources`;
- `research_claims`;
- `research_citations`.

Completed runs replay from SQLite. A completed source is not fetched again.
Interrupted live retrieval does not silently redispatch under the same key.
Compact events contain identities, outcomes, counts, hashes, and portable
metadata—not secret values or machine-specific paths.

## 4. Tranche B — Acceptance and Truth Governance

### 4.1 Truth labels

The application owns these labels:

- `VERIFIED`;
- `SUPPORTED`;
- `INFERRED`;
- `DISPUTED`;
- `UNKNOWN`.

No model can mark itself accepted merely by asserting confidence. The engine
checks whether the submitted label is structurally supported by the referenced
evidence:

- `VERIFIED` requires positive deterministic, observed, primary-source, or
  human evidence and no contradiction;
- `SUPPORTED` requires at least one positive evidence reference and no
  contradiction;
- `INFERRED` requires an explicit rationale;
- `DISPUTED` requires both supporting and contradicting evidence;
- `UNKNOWN` is permitted when evidence is insufficient.

These checks validate evidence structure and governance. They do not pretend
to solve semantic truth without an authorized evaluator or human.

### 4.2 Acceptance outcomes

The engine returns only:

- `PASS`;
- `REPAIR`;
- `BLOCK`;
- `HUMAN_DECISION`;
- `DEFER`.

Aggregation is deterministic:

1. a violated hard constraint produces `BLOCK`;
2. a failed required criterion produces `REPAIR`;
3. an unresolved/disputed required criterion produces its declared
   `HUMAN_DECISION` or `DEFER` action;
4. optional uncertainty may remain explicitly labeled;
5. all required criteria passing produces `PASS`.

The engine never converts model agreement into `VERIFIED` and never fabricates
consensus between legitimate alternatives.

### 4.3 Acceptance durability

Migration `0005_acceptance_truth` adds:

- `acceptance_runs`;
- `acceptance_evidence`;
- `acceptance_claims`;
- `acceptance_criteria`;
- `acceptance_constraints`.

The complete request, deterministic request fingerprint, evidence links,
labels, criterion outcomes, constraint findings, and aggregate outcome are
durable and idempotent. Existing v0.2 and Phase 1–5 schema remains additive and
unchanged.

### 4.4 Calibration set

The deterministic calibration contains exactly these controlled cases:

1. known-complete deliverable → `PASS`;
2. known-incomplete deliverable → `REPAIR`;
3. properly labeled supported uncertainty → `PASS` with `UNKNOWN` retained;
4. explicit hard-constraint violation → `BLOCK`;
5. legitimate unresolved disagreement → `HUMAN_DECISION`.

The set runs repeatedly with stable results. A mismatch blocks Phase 6
acceptance; the program does not recursively validate the validator forever.

## 5. Tranche C — Final Bootstrap Acceptance Gate

The final gate maps the original bootstrap contract to ten named capabilities:

1. passing and failing command capture;
2. workspace confinement;
3. patch plus rollback;
4. repair of a tiny broken Python fixture;
5. bounded failure on an unfixable fixture;
6. local Git checkpoint;
7. budget denial before overspend;
8. restart/resume;
9. validator/truth calibration;
10. authoritative research with provenance.

`run_bootstrap_phase6.py --status-only` may apply migrations and inspect
readiness, but it performs no tests, network requests, provider calls, or Git
mutations.

`run_bootstrap_phase6.py` runs the complete offline Python/pytest regression
suite, deterministic research fixture/replay, truth calibration, SQLite
integrity checks, and Git/workspace readiness. The result is `PASS` only when
all ten gates are represented and all executed evidence passes.

This is the final bootstrap suite, not the later five-project generalization
benchmark. The user's real workbook remains out-of-sample.

## 6. Cross-Platform Baseline Repair

The Phase 5 source resolves allowlisted executable symlinks before launch. On
POSIX, a virtual environment's `python` is commonly a symlink; launching the
resolved base interpreter bypasses the virtual environment and makes nested
pytest validation fail with `No module named pytest`. Windows does not expose
this behavior because its venv interpreter is normally a file rather than a
symlink.

Phase 6 may repair this pre-existing portability defect by preserving the
authorized absolute launch path while separately resolving and rechecking its
target for allowlist identity. Tests must cover a venv-style executable
symlink. This repair must not permit an unvalidated executable substitution.

## 7. Acceptance Contract

Phase 6 is complete only when:

- all existing Phase 1–5 tests still pass, except the existing platform-
  privilege skip where link creation is unavailable;
- migrations `0001` through `0005` apply once and checksum tampering is
  rejected;
- research fixture execution and completed-run replay make zero live requests;
- URL policy blocks disabled live access, unsafe schemes, unapproved hosts,
  credentials, IP literals, private addresses, redirects, oversized content,
  and unapproved content types;
- a sourced fact without valid captured evidence is rejected;
- research telemetry and provenance survive restart/replay;
- truth-label evidence invariants are enforced;
- the five calibration cases return the expected stable outcomes;
- all ten final bootstrap gates pass;
- `python run_bootstrap_phase6.py --status-only` passes without provider or
  network activity;
- `python run_bootstrap_phase6.py` passes without provider or network activity;
- `python run_loop_v0_2.py --preflight-only` still passes in the user's
  configured local environment;
- SQLite integrity is `ok`;
- source paths and durable records remain portable;
- the resulting source contains no credentials, generated ledger, logs,
  outputs, virtual environment, or local Git metadata.

Any unmet item ends in a bounded failure report with preserved evidence. Phase
6 does not authorize weakening a gate to obtain a passing result.

## 8. Delivery and Checkpoint Plan

The Work Mode implementation uses a local comparison repository whose history
is not represented as the user's recovered Git history. Delivery will contain:

- updated source and tests;
- Phase 6 planning and implementation documentation;
- installation/checkpoint instructions;
- a machine-readable change manifest and SHA-256 checksums;
- a safe ZIP excluding `.git`, `.env`, `.venv`, ledgers, logs, outputs, and
  caches.

The user applies the reviewed update to `bootstrap/local-execution`, reruns the
documented gates, commits it as a descendant of recovered commit `e007c9e`, and
creates the Phase 6 recovery-safe tag only after validation.
