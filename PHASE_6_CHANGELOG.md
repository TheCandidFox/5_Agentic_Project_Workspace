# Phase 6 Changelog

## Scope

Phase 6 completes the offline local bootstrap in three checkpointed tranches:

1. authoritative-documentation research with provenance;
2. acceptance and truth governance;
3. final integrated bootstrap acceptance.

## Added

- `research_provenance.py`
  - structured source and claim manifests;
  - deterministic fixture retrieval;
  - completed replay and offline restart/resume;
  - source URL/title/type/primary status/version/date/timestamp metadata;
  - bounded captured text, SHA-256, citation excerpts, and usage telemetry;
  - disabled-by-default, allowlisted, redirect-refusing HTTP adapter.
- `acceptance_truth.py`
  - governed evidence references and dispositions;
  - `VERIFIED`, `SUPPORTED`, `INFERRED`, `DISPUTED`, and `UNKNOWN`;
  - `PASS`, `REPAIR`, `BLOCK`, `HUMAN_DECISION`, and `DEFER`;
  - deterministic criterion/constraint aggregation;
  - fixed five-case stable calibration.
- `bootstrap_acceptance.py`
  - exactly ten final bootstrap gates;
  - AST-checked test-evidence mapping;
  - fail-closed gate evaluation.
- `run_bootstrap_phase6.py`
  - status-only readiness gate;
  - complete offline regression;
  - research replay and research-to-acceptance smoke;
  - truth calibration and ten-gate report.
- Migrations:
  - `0004_research_provenance`;
  - `0005_acceptance_truth`.
- Phase 6 planning, implementation, installation, and acceptance documentation.

## Portability repair

Allowlisted executable launch now preserves the authorized absolute launch path
while separately recording and rechecking the resolved target. This prevents a
POSIX virtual-environment Python symlink from being replaced with the base
interpreter at launch, while still rejecting a changed symlink target. Windows
behavior remains compatible.

## Deliberately unchanged

- The v0.2 four-stage paid workflow remains available but is not automatically
  invoked by Phase 6.
- No live repair-agent provider adapter is enabled.
- No paid provider or live HTTP test is authorized.
- No merge, push, cloud deployment, PWA, GraphRAG, or baseline promotion is
  performed.
- The five later generalization benchmarks and real workbook remain outside
  Phase 6.
