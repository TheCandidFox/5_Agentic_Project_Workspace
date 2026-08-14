# AI Project OS v0.3 — Phase 8 Implementation and Acceptance Contract

**Status:** approved implementation boundary

**User repository baseline:**
`d14b4bca67d39247e444b8539f3c0da9bf935ee6`

**Baseline tag:** `v0.3-phase7-markdown-orchestration`

**Target branch:** `bootstrap/local-execution`

**Validation posture:** offline and zero external cost

## 1. Purpose

Phase 8 adds the first opt-in provider-backed project profile above the durable
Phase 7 Markdown orchestrator. It is the governed foundation for a deliberately
small live canary, not permission to start one automatically.

The phase proves, with injected offline provider fixtures, that a bounded
Markdown goal can be routed through provider-call authorization, durable call
provenance, strict response schemas, declared-artifact writing, independent
semantic review, truth-governed acceptance, restart protection, and completed
replay. Real provider use remains disabled unless a human supplies an exact
approval fingerprint on an explicit live command.

## 2. Preserved Boundaries

All Phase 1–7 controls remain active. Phase 8 must not:

- make a provider or live-network call during installation, testing, status,
  preparation, or mock-canary execution;
- construct a provider client in status-only or offline-simulation modes;
- read, copy, print, persist, or package `.env` or API-key values;
- accept free-form shell commands, code execution, external research, or remote
  repository actions from a model response;
- write outside explicitly declared `outputs/` Markdown deliverables;
- let model text select a provider, model, authority level, budget, file path,
  or task-graph shape;
- silently redispatch an ambiguous orchestration or provider call;
- treat semantic review as deterministic proof;
- repair or overwrite a generated artifact after a failed review in Phase 8;
- claim general autonomous goal completion from one bounded document profile;
- run a live canary without a separate post-install review with the user.

## 3. Governed Live Contract

Phase 8 extends the parser with profile `governed-live-v1` while preserving
`offline-checklist-v1` as the safe default. The live profile requires:

- authority ceiling `live-network`;
- a finite positive project budget no greater than `$5`;
- exactly one declared Markdown deliverable below `outputs/`;
- at most four tasks, eight scheduler iterations, two no-progress results, and
  600 seconds unless a stricter contract value is supplied;
- at least the deterministic criteria `deliverable-exists` and
  `required-sections`;
- constraints `workspace-confined`, `declared-artifact-only`, and
  `no-external-side-effects`.

Provider and model routes are operator inputs, not Markdown inputs. This keeps
untrusted goal text from increasing authority or selecting a paid route.

## 4. Fixed Bounded Plan

`governed-live-v1` compiles a fixed two-task DAG:

1. `compose-markdown` requests one strict JSON composition envelope from the
   approved composer route and writes only the declared artifact;
2. `review-markdown` reads that artifact, requests one strict JSON review
   envelope from the separately approved reviewer route, combines semantic
   assessments with deterministic artifact checks, and submits complete
   evidence to the Phase 6 acceptance engine.

The model cannot add tasks, dependencies, tools, paths, retries, or authority.
Phase 8 permits one attempt per task. A failed criterion results in `REPAIR`,
but Phase 8 does not mutate or redispatch the artifact; repair is a Phase 9
feedback target.

## 5. Provider Gateway and Durable Provenance

Migration `0007_governed_provider_calls` adds `provider_calls`. Every authorized
call records, without secrets or raw prompts:

- stable call, run, task, attempt, and idempotency identities;
- provider, model, prompt-template version, prompt SHA-256, response schema,
  and maximum output tokens;
- execution mode (`offline-simulation` or `live`);
- status, provider request id, response SHA-256, validated payload JSON;
- input/output usage, estimated cost, latency, stop reason, and safe error.

The durable call claim is written before adapter dispatch. A non-terminal call
is ambiguous and cannot be reused automatically. Responses must be a single
UTF-8 JSON object with exact bounded fields; prose wrappers, fenced JSON,
unknown fields, missing identities, unsafe content, or oversized content fail
closed.

## 6. Cost and Authority Gates

Live execution requires all of these independent gates:

1. the Markdown contract permits `live-network`;
2. the kernel policy explicitly permits `live-network` and positive cost;
3. the runner is in `live` mode;
4. an exact approval fingerprint matches the contract, routes, models, token
   limits, budget, and prompt-template versions;
5. the provider and model match the approved route allowlist;
6. a conservative per-call quote fits the task allocation;
7. project, daily, monthly, and task budget reservations pass before dispatch.

Usage and estimated cost are recorded after a response. Provider invoices
remain authoritative. Missing or invalid usage causes a safe recovery stop
rather than an unmeasured success.

## 7. Offline Simulation and Live Preparation

The Phase 8 entry point supports:

```powershell
python run_phase8.py --status-only
python run_phase8.py --mock-canary
python run_phase8.py --prepare-live --contract project/phase8_live_canary_goal.md
```

Status-only validates the live contract, routes, graph, migration, and gates
without constructing an adapter or writing an artifact. Mock-canary uses an
explicit in-memory fixture adapter and a separate mock contract/output path. It
exercises the same gateway, schema, kernel, acceptance, and replay path at zero
external cost.

`--prepare-live` prints the exact approval fingerprint and proposed live
configuration but does not call a provider. The later live command requires
both `--live` and that fingerprint. The installer never supplies them.

## 8. Acceptance Gate

Phase 8 is complete only when:

- the complete Phase 1–7 regression suite remains passing;
- migration `0007` applies exactly once with checksum protection;
- the Phase 7 offline sample remains unchanged and replayable;
- both Phase 8 contract profiles parse safely with unchanged offline defaults;
- malformed live policies and missing mandatory controls fail before dispatch;
- status and live preparation construct no provider client, claim no provider
  call, write no artifact, and incur no cost;
- mock-canary completes two simulated calls, one artifact, acceptance `PASS`,
  and completed replay with zero new calls or rewrites;
- provider/model drift, fingerprint mismatch, disabled live mode, budget denial,
  schema failure, response identity mismatch, and usage/cost anomalies fail
  closed;
- ambiguous provider or task calls require recovery and never redispatch;
- only SHA-256 prompt/response evidence and validated output payloads persist;
- SQLite integrity remains `ok`;
- no test or installer path calls a provider or live network;
- the package excludes `.git`, `.env`, `.venv`, ledgers, outputs, logs, caches,
  and other mutable state.

## 9. Delivery

Delivery uses the established workflow:

1. a Phase 8 implementation ZIP containing full source, update patch, manifest,
   handoff, and checksums;
2. a standalone Git Bash installer placed beside the ZIP and repository in
   `0_GitHub_Projects`.

The installer verifies the exact Phase 7 baseline, preserves `.env`, creates a
pre-install safety tag, applies the reviewed patch, runs offline validation and
the simulated canary/replay, creates a local Phase 8 commit/tag, and never
pushes or makes a provider call.
