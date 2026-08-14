# Phase 8 Live Canary Findings — 2026-08-14

## Executive finding

The live canary was valuable and safe. The composer produced a strong,
implementation-ready 12,464-byte blueprint, but the independent reviewer hit
its 3,000-output-token ceiling before returning one complete JSON object. The
run stopped at `recovery_required`; it did not silently repeat the ambiguous
reviewer dispatch. This is a transport/envelope completion defect, not evidence
that the composed artifact was poor.

## Reproducible evidence

| Field | Observed value |
|---|---|
| Repository checkpoint | `afc2c683adc0fe524f020314204e4cd46e32bf80` |
| Contract | `contract-d7213ae231374d30fe6d` |
| Run | `phase8-live-d7213ae231374d30fe6d` |
| Final state | `recovery_required` / `ambiguous-dispatch` |
| Completed tasks | 1 of 2 |
| Composer | completed; 1,050 input / 3,234 output tokens; 39,706 ms; `$0.051135` |
| Reviewer | failed; 6,759 input / 3,000 output tokens; 30,050 ms; `$0.043518` |
| Reviewer stop reason | `max_tokens` |
| Measured provider total | `$0.094653` |
| Project total reported by Phase 8 | `$0.051135` |
| Artifact | 12,464 bytes; SHA-256 prefix `eff960a5e36c` |
| Replay behavior | zero new provider calls |

Phase 8 did persist the failed provider call's measured cost, but the project
total omitted it because the failure never became a terminal task result. That
accounting gap is a Phase 9 acceptance requirement.

## Artifact assessment

The blueprint gave concrete scope, deterministic normalization rules, declared
file boundaries, a seven-item dependency-aware backlog, role handoffs,
traceability, fixtures, escalation gates, recovery state, and a five-segment
status view. A manual structural review found 14 of 16 intended quality signals
fully present. The two meaningful weaknesses were both operational:

1. several defaults still required human approval before implementation;
2. the reviewer never delivered its formal acceptance envelope, so semantic
   agreement could not be recorded.

No claim is made that the artifact passed the missing independent review.

## Root cause

The reviewer prompt combined the full contract, a large artifact, and verbose
per-criterion/per-constraint rationale requirements. The provider consumed its
entire 3,000-token allowance and returned an incomplete JSON object. The strict
single-object parser correctly rejected it. However, Phase 8 classified every
measured response parse failure as ambiguous, left task/dispatch state
nonterminal, excluded the billable failure from project cost, and provided no
purpose-built resume command or concise diagnostic bundle.

## Phase 9 requirements derived from the canary

- Distinguish measured, known response failures from transport ambiguity.
- Classify output-limit termination as `response-truncated` before JSON parse.
- Finish the failed provider and task-dispatch records durably.
- Include failed-but-billable calls in task/project cost.
- Allow exactly one reviewer-only retry; never redispatch the successful
  composer or overwrite its artifact.
- Use a concise reviewer envelope and a reviewed 5,000-token ceiling.
- Demonstrate controlled pause and new-process resume from durable state.
- Emit redacted diagnostics with failure kind, attempt, cost, latency, artifact
  identity, acceptance state, and recommended next action.
- Show goal-relative progress in five operator-visible segments.
- Keep ambiguous transport failures human-gated.

These requirements are implemented and tested in Phase 9's offline recovery
canary before another live experiment is proposed.
