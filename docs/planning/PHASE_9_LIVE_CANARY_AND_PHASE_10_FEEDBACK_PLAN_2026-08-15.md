# Phase 9 Live Canary and Phase 10 Feedback Plan

**Status:** proposed canary ready for offline validation and human review

**Live execution:** not authorized by this document or its installer

**Contract:** `project/phase9_phase10_live_canary_goal.md`

**Declared output:** `outputs/phase9_phase10_revision_blueprint.md`

## Purpose

The canary has two jobs. First, it must validate the real Phase 9 composer,
reviewer, schema, cost, acceptance, replay, diagnostics, and operator-status
path under normal live conditions. Second, its planning artifact must answer
the questions needed to implement Phase 10's bounded artifact-revision cycle.

It does not intentionally cause a paid failure. Phase 9's deterministic
fixtures already prove truncation classification, reviewer-only retry,
failed-call accounting, controlled pause, fresh-process resume, and completed
replay.

## Highest-value feedback for Phase 10

| Priority | Question | Why it matters | Canary evidence |
|---|---|---|---|
| 1 | Can reviewer findings be converted into one precise repair task without rereading the entire run? | Vague criticism produces unsafe or repetitive repair loops. | Criterion verdicts, rationales, blueprint finding schema, operator assessment. |
| 2 | Which failures are automatically repairable and which require a human? | The revision loop must not convert uncertainty or authority changes into autonomous action. | Repair-eligibility decision table and escalation gates. |
| 3 | What exact artifact and evidence state must survive every revision? | Revision without immutable history makes rollback, comparison, and resume unreliable. | Version/hash/acceptance model and continuation capsule. |
| 4 | How will the loop detect no progress and regression? | More attempts do not imply improvement. | Repeated-finding, repeated-change, criterion-regression, and score-delta rules. |
| 5 | Does the independent reviewer disagree usefully and compactly? | Phase 10 depends on a reviewer that identifies specific shortcomings without overflowing its response envelope. | Schema validity, verdict distribution, rationale specificity, token use, latency. |
| 6 | Does restart context preserve direction of travel? | An overnight system must resume the intended work rather than merely reload files. | Capsule fields, exact next action, decisions, unresolved items, budgets. |
| 7 | Are cost and operator status sufficient to make continuation decisions? | The user needs to know whether another revision is worthwhile and safe. | Provider/project cost, attempts, active segment, remaining bounds, next action. |
| 8 | Can Phase 10 remain extensible without absorbing all later roadmap work? | Hard-coding one composer/reviewer loop would make goal intake and new collaboration profiles expensive later. | Named extension interfaces and explicitly deferred capabilities. |

## Edge cases

### Directly exercised by the live canary

- two different providers receive application-owned roles;
- strict JSON composition and review envelopes;
- a moderately detailed artifact and compact independent review;
- deterministic required-heading checks versus semantic review;
- complete usage, cost, latency, stop-reason, and response-hash telemetry;
- acceptance aggregation and completed replay with zero new calls;
- diagnostic export and five-segment goal-relative status.

### Designed in the artifact for Phase 10 tests

The blueprint must make these cases testable without claiming they occurred:

1. a deterministic validator fails while the semantic reviewer says `PASS`;
2. the reviewer returns `UNKNOWN` or `DISPUTED` because business intent is
   insufficient;
3. revision two fixes one criterion but regresses a previously passing one;
4. the same finding reappears after a materially identical change;
5. a proposed change repeats the previous artifact hash or patch hash;
6. budget, deadline, or attempt capacity is exhausted mid-cycle;
7. interruption occurs after an artifact write but before terminal task state;
8. provider dispatch is ambiguous and must not be automatically repeated;
9. a response is measured but truncated or schema-invalid;
10. a repair requests an undeclared path, provider, tool, or authority increase;
11. a continuation capsule references a stale artifact hash or superseded human
    decision;
12. a human decision remains unresolved when the process restarts.

### Kept as deterministic offline failure injection

- repeated provider truncation;
- adapter exception before response identity is known;
- invalid usage and cost overrun telemetry;
- SQLite or process interruption at controlled state boundaries;
- path traversal and undeclared artifact writes.

These failures should remain fixture-driven until a real occurrence provides
new evidence. Paying a provider to manufacture them adds cost without improving
reproducibility.

## Larger product goals included as extension boundaries

The artifact should reserve clean interfaces—not implementation—for:

- conversational idea-to-contract compilation and human approval;
- research sources and claim-level provenance;
- research/critic, divide-and-conquer, independent parallel, cross-review,
  adversarial, and consensus collaboration profiles;
- bounded dynamic DAGs and multiple deliverables;
- human decision queues and later notifications;
- stable progress events for a terminal, local UI, and eventual remote view.

This keeps Phase 10's durable state useful later while protecting its scope.

## Live evidence package

After a separately approved live run, retain:

- terminal log and process exit code;
- exact approval fingerprint and contract SHA-256;
- generated artifact and SHA-256;
- latest redacted diagnostic JSON;
- composer/reviewer provider, model, call count, attempt, token, latency, stop
  reason, and measured cost fields;
- criterion and constraint verdicts;
- first-run and replay call counts;
- whether any retry occurred and whether the artifact hash changed;
- human scores from 1–5 for usefulness, specificity, completeness,
  implementation readiness, and confidence in the proposed next action.

Do not collect `.env`, API keys, raw prompts, complete raw provider responses,
or an unsanitized live ledger.

## Canary interpretation

| Result | Interpretation | Phase 10 consequence |
|---|---|---|
| Clean `PASS`, no retry | The normal two-provider path is ready to inform Phase 10. | Use artifact/reviewer gaps to finalize the revision contract. |
| `PASS` after reviewer truncation retry | Recovery works live, but response compactness remains marginal. | Tighten review context/envelope before adding more criteria. |
| `REPAIR`, `DEFER`, or `HUMAN_DECISION` with actionable findings | Truth governance is doing useful work. | Preserve the finding structure and implement the appropriate revision or decision state. |
| Failed schema with measured response | The provider boundary is diagnosable but not reliable enough for iteration. | Harden envelopes and parsing before Phase 10 autonomy. |
| `recovery_required` from ambiguous dispatch | Safety boundary worked. | Diagnose manually; do not retry or start Phase 10 live iteration. |
| Cost, token, or latency near the project ceiling | The proposed loop would multiply unacceptable resource use. | Reduce context, choose stricter artifacts, or revise budgets before iteration. |

## Recommended next action

Install this canary-ready checkpoint, inspect the contract and plan, run
`python run_phase9.py --status-only --contract
project/phase9_phase10_live_canary_goal.md`, and then prepare a new approval
fingerprint. Preparation is offline. Review that fingerprint and configuration
with the user before any live command.
