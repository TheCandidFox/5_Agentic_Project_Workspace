# Bounded Autonomy — Bootstrap Phase 5

## Scope

Phase 5 adds the durable local repair state machine described by the v0.3
bootstrap design. It composes the existing `TestRunner`, `PatchManager`,
`GitCheckpointManager`, `BudgetGuard`, and `Ledger`; it does not replace their
individual safety checks.

The implementation is provider-neutral. A caller injects a `RepairAgent` that
can estimate the worst-case cost of one proposal and return a structured
`RepairProposal`. No OpenAI, Anthropic, or other provider client is constructed
by the bootstrap entry point or test suite.

## Repair sequence

`BoundedRepairLoop.run()` performs this sequence:

1. claim the repair run with a request fingerprint and durable deadline;
2. run and persist the initial validation suite;
3. stop immediately when the candidate is already valid;
4. enforce time, attempt, run-cost, daily, monthly, and task admission limits;
5. reserve the estimated proposal cost with a deterministic reservation key;
6. durably claim the proposal dispatch before invoking the repair agent;
7. validate and persist a structured, project-relative proposal;
8. apply its hash-locked patch transaction;
9. rerun the validation suite with attempt-specific idempotency keys;
10. create a scoped Git checkpoint when validation passes; or
11. roll the exact patch back when validation fails;
12. stop on success or on a structured bounded-failure reason.

The loop never merges, pushes, contacts a Git remote, promotes the candidate to
the frozen baseline, deploys, or invokes a provider on its own.

## Hard bounds

`RepairPolicy` requires finite values for:

- `max_attempts`;
- `max_cost_usd`;
- `max_wall_seconds`;
- `max_identical_failures`;
- `max_identical_patches`;
- `max_no_progress_attempts`.

The default policy allows three attempts, one dollar of repair-agent cost,
fifteen minutes, three identical failures, no duplicate patch, and two
consecutive non-improving attempts. These are library defaults, not authority
to spend. A caller still needs an enabled provider adapter, credentials, and a
configured `BudgetGuard`; a positive-cost proposal is blocked when no budget
guard is supplied.

Progress compares passing/not-applicable check count and normalized suite
outcome. Identical-failure detection hashes portable validation evidence.
Identical-patch detection hashes project-relative paths, expected pre-image
hashes, and proposed UTF-8 content. Hypothesis wording cannot disguise a
duplicate patch.

## Durable state and migration

Checksummed migration `0003_bounded_autonomy` adds:

- `repair_runs` — request fingerprint, policy, durable deadline, total cost,
  counters, latest portable failure context, terminal reason, and checkpoint;
- `repair_attempts` — proposal claim, agent label, cost reservation evidence,
  proposal hash/body, patch, post-patch validation, checkpoint, and state.

Proposal bodies are stored so a crash after receipt does not require another
paid dispatch. Event rows contain compact identities and outcomes. Repair paths
are project-relative; runtime failure context replaces the candidate root with
`<workspace>`.

The migration is additive. Existing v0.2, Phase 1, Phase 2, patch, and Git
tables are preserved.

## Attempt and run states

Attempt states are:

```text
proposing
  -> proposal_received
  -> patch_applied
  -> validation_passed -> checkpointed
  -> validation_failed -> rolled_back
```

Rejected proposals and safely failed patch attempts are terminal attempt
states. A run ends as:

- `passed` — initially valid or repaired, validated, and checkpointed;
- `blocked` — a hard bound or recoverable policy condition stopped work;
- `recovery_required` — an ambiguous or incomplete side effect needs review.

## Restart and ambiguity rules

The following completed boundaries replay safely:

- stored proposal before patch;
- applied patch before validation linkage;
- stored validation before rollback or checkpoint;
- completed rollback before attempt completion;
- committed checkpoint before run completion.

An attempt left at `proposing` is deliberately different. The provider call may
have been accepted even if no response was persisted, so restart changes the
run to `recovery_required` instead of blindly charging for a duplicate request.
Its reservation remains visible until a human or future provider-specific
reconciliation adapter determines the actual outcome.

Patch or Git states already marked `recovery_required` are never bypassed with
a new idempotency key.

## Cost handling

The agent adapter must reserve a conservative worst-case cost before dispatch
and report actual cost with its proposal. The loop rejects actual cost above the
reservation, records the overage, and stops without applying the patch.

Budget reservations now accept an optional deterministic idempotency key.
Replaying that key returns the original reservation rather than reserving the
same amount twice. Accepted and rejected proposal cost is recorded in telemetry
and in the repair run.

## Offline verification

```powershell
python -m pytest -q
python run_bootstrap_bounded.py --status-only
python run_bootstrap_bounded.py
```

Status-only mode applies migrations and checks SQLite, required columns, prior
transactional readiness, and Git conflicts. Full mode also runs the complete
guarded syntax/pytest suite. Neither mode configures a repair agent or makes a
provider call.

The tests cover:

- successful repair, validation, checkpoint, and terminal replay;
- failed-candidate rollback and attempt exhaustion;
- repeated patch, repeated failure, and no-progress stops;
- budget denial and wall-clock denial before dispatch;
- resume from a stored proposal without redispatch;
- ambiguous proposal dispatch requiring recovery;
- project-relative proposal paths and portable failure context;
- prior v0.2 and bootstrap regressions.

## Deliberate limitations

1. Phase 5 supplies the safety state machine and agent interface, not a live
   provider-specific repair adapter.
2. Synchronous provider calls without a provider operation ID cannot always be
   reconciled after an ambiguous network failure; those runs stop for review.
3. Patch proposals still replace complete UTF-8 files and cannot delete files.
4. Validation quality depends on the supplied deterministic checks. A passing
   weak test suite is not proof that the objective is correct.
5. Git checkpointing still requires the repair patch to be the only worktree
   change. Unrelated human edits block checkpoint creation and are never swept
   into an autonomous commit.
6. The controls are application boundaries, not an operating-system sandbox
   for hostile generated code.

## Next bootstrap package

Add current-authoritative-documentation research with provenance, followed by
the acceptance/truth abstraction and final bootstrap acceptance review. A live
repair-agent adapter should be introduced only with explicit provider choice,
structured-output validation, populated budgets, and a deliberately approved
paid test.

