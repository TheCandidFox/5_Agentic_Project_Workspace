# Phase 10 Contract-Parity Hardening and Cursor Onboarding Contract

## Status and authority

- Status: bounded implementation contract; installed inactive until the human
  authorizes a reviewed Cursor plan.
- Required source commit:
  `920305270a05ac2cc5196cb6f27cc918cb76c259`.
- Required source tag: `v0.3-phase10-offline-completion-candidate`.
- Onboarding checkpoint tag: `v0.3-phase10-cursor-onboarding`.
- Development branch after onboarding:
  `phase10/contract-parity-hardening`.
- Provider and live-network authority: absent.
- External-side-effect authority: absent.
- Git mutation by Cursor: prohibited.
- Actual authority: this committed contract plus explicit human approval of the
  current plan and tranche.

If an implementation convenience, model recommendation, previous handoff, or
roadmap summary conflicts with this contract, this contract wins and the work
stops for review.

## End goal relationship

The product goal is a bounded AI project operating system that can plan,
develop, test, review, recover, checkpoint, notify, and pause for human judgment
without routine terminal transcription or silent authority expansion.

This checkpoint does not attempt that whole goal. It closes the Phase 10
runtime gaps that must be resolved before a paid Phase 10 revision canary and
before the existing repair, patch, command, provider, and Git components are
connected into the first governed autonomous code loop.

## Why this checkpoint is required

The Phase 10 source passes its current test suite and offline replay. Source
inspection nevertheless found contract requirements that are declared but not
fully enforced:

1. `RevisionPolicy.max_dispatches` is stored but not enforced.
2. `RevisionPolicy.max_runtime_seconds` is stored but not enforced.
3. `revision_attempts` exists in migration `0009_bounded_revision_cycle` but is
   not written or transitioned by `RevisionCycle`.
4. continuation payloads do not yet carry the full recovery context required
   by the Phase 10 contract;
5. materialization reconciliation reports states but does not complete the
   interrupted recovery action;
6. accepted status can leave verification segments displayed as pending;
7. no Phase 10 live adapter or exact live approval fingerprint exists.

Only items 1–3 are active in Tranche 1A. The other items remain preserved for
later tranches.

## Checkpoint scope

### Tranche 1A — policy bounds and durable revision attempts

Objective: make dispatch, runtime, and revision-attempt limits application-
owned, durable, restart-safe, and testable without a provider call.

Initially, Cursor may only inspect and propose a Tranche 1A plan. Implementation
begins only after ChatGPT reviews the plan and the human explicitly approves it.

After plan approval, the default allowed implementation paths are:

- `revision_cycle.py`;
- `ledger.py`;
- `tests/test_phase10_revision.py`;
- `tests/test_phase10_completion.py`.

The approved plan may use a strict subset. Adding any other path requires a
contract amendment before editing.

Required behavior:

1. Validate all `RevisionPolicy` values at construction. Counts and byte/runtime
   ceilings must use bounded integer/finite-number rules. Zero-cost and a
   deliberately zero-revision review-only policy may remain valid when the
   behavior is explicit and tested.
2. Persist an absolute run deadline when a Phase 10 run begins. Restarting or
   replaying the run must not reset or extend that deadline.
3. Check runtime before every provider-dispatch claim, candidate preservation,
   comparison, materialization, and acceptance action. Exhaustion creates a
   deterministic `BOUNDED_STOP` and continuation capsule before returning.
4. Count every review and revision dispatch claim durably. A claim that would
   exceed `max_dispatches` must be denied before any call or reservation.
5. Make dispatch-count enforcement atomic under the same SQLite write lock as
   the claim transition so two workers cannot both consume the last slot.
6. Create a `revision_attempts` row before a revision provider dispatch can
   occur. Bind it to run, ordinal, idempotency key, baseline version, target
   finding-set hash, normalized plan hash, quoted/reserved cost, start time, and
   immutable deadline.
7. Transition the attempt through application-owned states matching the
   existing schema. Replays return the existing attempt; conflicting reuse of
   an idempotency key fails closed.
8. Tie candidate preservation, validation/comparison evidence, ambiguity,
   completion, failure, and cost reconciliation to the correct attempt record.
9. Reconcile known cost exactly once. Unknown usage retains the reservation and
   routes to a human gate; it never becomes assumed zero.
10. Preserve the last accepted artifact on every bound, failure, ambiguity,
    cancellation, and recovery path.
11. Do not add a live provider route, network call, notification, dynamic task
    graph, code-repair path, or new external side effect.

### Tranche 1B — recovery and operator completeness

Inactive until Tranche 1A is accepted and a fresh plan is approved.

Planned scope:

- full continuation context and deterministic capsule supersession;
- actionable hash-based materialization recovery;
- transition-boundary fault injection;
- accurate accepted/blocked/recovery five-segment status;
- exact next-action and remaining-bounds reporting.

Allowed files are not granted by this document yet. They will be activated by
an updated active-contract pointer after Tranche 1A acceptance.

### Tranche 1C — exhaustive acceptance and Windows checkpoint

Inactive until Tranche 1B is accepted and a fresh plan is approved.

Planned scope:

- full contract-parity matrix;
- complete suite twice;
- same-ledger offline canary replay and status;
- interrupted-process resume evidence;
- sanitized acceptance report and Windows installation checkpoint.

## Application-owned invariants

The implementation must preserve these existing boundaries:

- provider output is untrusted data;
- the last accepted artifact is never overwritten by an unaccepted candidate;
- no unknown/ambiguous provider dispatch is automatically repeated;
- no new authority is inferred from a model response;
- budgets and bounds are checked before the affected action;
- SQLite claims and idempotency determine durable ownership;
- status-only and replay modes make no provider call;
- real credentials, raw provider content, and runtime ledgers remain outside
  source control and review artifacts;
- Git push, merge, tag, and release remain human actions.

## Tranche 1A deterministic test requirements

At minimum, add tests for:

1. valid default policy and invalid negative, non-finite, Boolean, zero where
   prohibited, and excessive policy values;
2. absolute deadline persistence across reconstruction/restart;
3. runtime denial before review claim;
4. runtime denial before revision claim and before acceptance;
5. exact last allowed dispatch succeeds and the next claim stops before call;
6. concurrent claims cannot exceed the dispatch ceiling;
7. revision-attempt creation before dispatch;
8. unique `(run_id, ordinal)` and idempotency conflict behavior;
9. attempt replay without a duplicate record or reservation;
10. candidate, comparison, terminal reason, and continuation linkage;
11. exactly-once known-cost reconciliation;
12. unknown cost retains its reservation and gates;
13. bound stops preserve accepted output bytes and hashes;
14. all previous Phase 1–10 tests remain green.

Tests must be deterministic and offline. Do not manufacture a paid failure.

## Cursor operating contract

Cursor must use two separate turns:

1. **Plan only.** Read relevant code and tests, return the exact proposed paths,
   schema/state changes, invariants, tests, assumptions, risks, and stopping
   point. Make no edits.
2. **Implement one approved tranche.** Modify only the approved paths, run the
   approved targeted tests and the full suite, complete the evidence packet,
   then stop with an uncommitted worktree.

Cursor may not:

- continue from Tranche 1A to 1B;
- alter this contract, the active pointer, `AGENTS.md`, `.cursorignore`, or the
  Cursor rule;
- access or create `.env`, credentials, ledger, outputs, or logs;
- install or update packages;
- call a provider or network;
- change model routes, budgets, dependencies, command policies, or unrelated
  modules;
- weaken, skip, or delete tests;
- commit, tag, push, merge, rebase, reset, clean, restore, or stash;
- resolve ambiguity by assumption.

## Independent review sequence

1. Cursor returns the completed evidence packet and uncommitted diff.
2. Claude reviews the exact contract, diff, and evidence without editing code.
3. Claude returns criterion-linked `PASS`, `REPAIR`, `BLOCK`, or
   `HUMAN_DECISION` findings.
4. ChatGPT reconciles Cursor evidence, deterministic results, and Claude
   findings against this contract.
5. The human authorizes a candidate Git commit only after blocking findings are
   resolved.
6. The target Windows installation closes the checkpoint before an annotated
   hardening tag is pushed.

No majority vote can override a hard constraint or missing deterministic
evidence.

## Mandatory stop conditions

Stop without further edits if any of these occurs:

- baseline, branch, contract, or worktree identity differs from expectation;
- an edit outside the allowed paths is required or appears unexpectedly;
- a test, dependency, provider, model, budget, command, network, or authority
  change is proposed outside scope;
- a migration/schema change cannot be proven additive and compatible;
- dispatch or cost ownership is ambiguous;
- an accepted artifact could be overwritten before acceptance;
- tests fail in a way unrelated to the approved change;
- the plan requires guessing about product intent;
- credentials or unsanitized runtime evidence are discovered;
- Git reports conflicts, unrelated modifications, or an unsafe state.

The handoff must name the stop reason, evidence, preserved state, and exact
human decision required.

## Tranche 1A acceptance gates

Tranche 1A is accepted only when:

1. every approved policy value is validated;
2. runtime and dispatch bounds are durable and enforced before action;
3. revision-attempt rows are created, transitioned, replayed, and reconciled;
4. concurrency and idempotency tests prove no double ownership;
5. cost reservations remain exactly-once and fail closed when unknown;
6. accepted artifacts remain byte-identical on all stop paths;
7. targeted tests pass;
8. the complete Phase 1–10 suite passes;
9. `git diff --check` passes;
10. only approved paths changed;
11. diagnostics/evidence contain no secrets or raw provider content;
12. Claude has no unresolved `BLOCK` finding;
13. ChatGPT finds the implementation aligned with this contract;
14. the human explicitly approves the candidate checkpoint.

## Explicit non-goals

This checkpoint does not implement:

- the Phase 10 paid live canary;
- autonomous code repair;
- Cursor SDK integration;
- dynamic task planning or multi-agent profiles;
- notifications, background daemons, scheduling, dashboards, or phone control;
- Git push, merge, release, or automatic next-task selection.

These remain downstream goals. Preserving their clean integration boundaries is
required; implementing them early is prohibited.

## Required handoff

Use `docs/templates/IMPLEMENTATION_EVIDENCE_PACKET.md` without omitting
sections. The handoff must identify the exact next safe action and must not ask
the human to reconstruct context from terminal history.
