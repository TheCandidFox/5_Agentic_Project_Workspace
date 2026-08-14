# Phase 9 Changelog

## Added

- Opt-in `governed-live-v2` recovery profile.
- One policy-owned reviewer retry for the known `response-truncated` failure;
  composer attempts remain fixed at one.
- Additive migration `0008_recovery_observability` with provider failure kind,
  bounded redacted response excerpt, and excerpt SHA-256.
- Measured `ProviderCallFailed` results that preserve the cost of failed-but-
  billable responses and distinguish them from ambiguous transport failures.
- Controlled pause and explicit restart/resume for known retryable failures.
- Redacted per-run diagnostic bundles and a five-segment operator status view.
- A concise reviewer prompt and a 5,000-token reviewer ceiling to reduce the
  truncation risk observed in the Phase 8 canary.
- Exact Phase 8 failure regression fixtures: composer success, reviewer
  truncation at 3,000 billed output tokens, reviewer-only retry, acceptance,
  completed replay, and zero composer redispatch.
- A Phase 9 recovery canary contract and durable Phase 8 canary findings.

## Changed

- Provider adapters preserve incomplete/max-token stop reasons for
  classification.
- Known measured schema and truncation failures now terminate their dispatch
  records instead of leaving them falsely `dispatching`.
- Task dispatch failures retain a bounded diagnostic summary.
- Live provider accounting includes completed and failed-but-billable calls.
- Project contracts accept `governed-live-v2` under the same live-network,
  budget, workspace, deliverable, and time ceilings.
- Earlier migration regression expectations include additive migration `0008`.

## Preserved

- The Phase 8 canary artifact is never overwritten during reviewer recovery.
- Ambiguous transport failures still require human recovery and are never
  automatically repeated.
- Provider/model routes, task graph, retries, token ceilings, authority, paths,
  and budgets remain application/operator owned.
- `.env`, virtual environments, ledgers, outputs, logs, caches, and Git metadata
  remain outside delivery archives.
- Installation and all automated validation remain offline and zero cost.

## Not enabled

- Automatic execution of a real Phase 9 live canary.
- Retry of ambiguous calls, composer calls, or non-classified failures.
- Artifact mutation in response to reviewer feedback.
- Arbitrary task decomposition, model-selected tools, code execution, or live
  research.
- Conversation-to-contract intake, selectable collaboration profiles,
  multi-judge consensus, remote/mobile status, or automatic overnight launch.
- Git push, remote merge, or merge to `main`.
