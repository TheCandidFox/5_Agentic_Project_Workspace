# Cursor Phase 10 Handoff

## Purpose

This file is the short operational handoff. The binding authority is
`docs/planning/PHASE_10_CONTRACT_PARITY_HARDENING_AND_CURSOR_ONBOARDING_CONTRACT.md`.

Do not ask Cursor to “finish Phase 10,” “start Phase 11,” or “make the system
autonomous.” The first Cursor action is a bounded plan for Tranche 1A only.

## Preconditions

The human must create and open a dedicated key-free worktree whose starting
point is tag `v0.3-phase10-cursor-onboarding` and whose branch is
`phase10/contract-parity-hardening`.

Before Cursor is opened, the human verifies:

```bash
test ! -e .env && echo "PASS: no .env"
test ! -e ledger.db && echo "PASS: no ledger"
git status --short
git branch --show-current
git rev-parse HEAD
python -m pytest -q
```

## First Cursor prompt — plan only

Paste this prompt exactly:

```text
Read AGENTS.md, .cursor/rules/agentic-workspace-governance.mdc,
docs/planning/ACTIVE_IMPLEMENTATION_CONTRACT.md, and the complete active Phase
10 contract.

Do not edit or create files. Do not install packages. Do not run network or
provider commands.

Inspect the repository only far enough to produce a plan for Tranche 1A:
Phase 10 policy bounds and durable revision-attempt records.

Return:
1. the active contract path and SHA-256;
2. the baseline commit and current branch;
3. the exact files you propose to change;
4. the exact tests you propose to add or modify;
5. how max_dispatches will be enforced atomically before dispatch;
6. how an absolute max_runtime_seconds deadline will survive restart;
7. how revision_attempts will be created, transitioned, replayed, and linked;
8. how known and unknown cost reconciliation remain exactly-once;
9. how accepted artifact bytes remain protected on every stop path;
10. every ambiguity, risk, or contract conflict;
11. the exact stopping point for Tranche 1A.

Do not implement anything. Stop after the plan.
```

## First human handoff

Return Cursor's complete plan to ChatGPT. Do not summarize it and do not
authorize implementation yet.

ChatGPT will compare the plan with the exact source, Phase 10 contract, ledger
schema, transition rules, tests, and preserved product goal. The next prompt
will be generated only after that review.

## Prohibited shortcuts

- Do not give Cursor the real `.env`.
- Do not let Cursor operate in the canonical repository folder.
- Do not start with a coding prompt.
- Do not combine Tranches 1A, 1B, and 1C.
- Do not let Cursor commit or push.
- Do not run a live Phase 10 canary.
- Do not proceed to autonomous code repair or notifications.

The next step after onboarding is only: create the key-free worktree, establish
the green baseline, and obtain the Tranche 1A plan.
