# Phase 8 Changelog

## Added

- Opt-in `governed-live-v1` Markdown execution profile.
- Fixed composer/reviewer task graph with application-owned routes and bounds.
- Additive migration `0007_governed_provider_calls`.
- Durable provider claims, request identities, prompt/response hashes,
  schema-valid payloads, usage, estimated cost, latency, and failure evidence.
- Strict JSON-only composition and review response envelopes.
- Exact provider/model/token route allowlists.
- Conservative per-call quoting plus project, task, daily, and monthly budget
  gates before adapter dispatch.
- Exact live-approval fingerprint over the contract, graph, routes, models,
  token limits, pricing inputs, budget limits, and prompt-template versions.
- Deterministic deliverable/heading checks combined with explicitly labeled
  semantic-review evidence.
- Offline `ScriptedProviderClient` and simulated canary/replay.
- Proposed small live-canary contract, kept inactive during installation.
- Phase 8 gateway, profile, entry-point, parser, recovery, and regression tests.

## Changed

- `project_contract.py` now accepts `governed-live-v1` with stricter live-only
  policy invariants while preserving `offline-checklist-v1` as the default.
- `provider_adapter.py` loads SDK packages and constructs clients lazily only
  when an authorized provider call reaches the adapter.
- Migration assertions in earlier regression tests include additive migration
  `0007`.
- README documentation now distinguishes offline Phase 7 execution from the
  opt-in governed Phase 8 path.

## Preserved

- Phase 7 deterministic sample behavior and zero-cost default profile.
- All Phase 1–7 authority, workspace, durability, ambiguity, acceptance, and
  replay controls.
- `.env`, virtual environment, ledger, outputs, logs, caches, and Git metadata
  remain outside delivery archives.
- No installer, test, mock, status, or preparation command calls a provider or
  live network.

## Not enabled

- Automatic live-canary execution.
- Model-selected tools, task graphs, providers, models, budgets, or paths.
- Shell commands, code execution, external research, or external mutations.
- Automatic artifact repair or overwrite after a failed review.
- General arbitrary-goal decomposition or completion claims.
- Automatic Git push, remote merge, or merge to `main`.
