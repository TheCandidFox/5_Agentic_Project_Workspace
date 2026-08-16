# Phase 10 Cursor Onboarding Checkpoint

## Purpose

This checkpoint installs the governance and handoff material required to use
Cursor as a bounded implementation environment for Phase 10 contract-parity
hardening.

## Added

- repository-wide `AGENTS.md` instructions;
- `.cursorignore` secret/runtime exclusions;
- an always-applied Cursor governance rule;
- an active-contract pointer;
- the Phase 10 contract-parity hardening contract;
- a structured implementation evidence packet;
- a short sequential Cursor handoff.

## Runtime effect

None. This checkpoint adds documentation and development-governance files only.
It does not alter Python runtime behavior, provider routes, model selection,
budgets, ledger schema, tests, dependencies, live authorization, or Git remote
state.

## Safety boundary

Installation must preserve `.env`, make no provider or network call, run the
complete offline suite, create only a local commit and annotated onboarding
tag, and leave push/merge to the human after review.

## Next action

Create a dedicated key-free Git worktree from
`v0.3-phase10-cursor-onboarding`, run the baseline suite, open that worktree in
Cursor, and use the plan-only prompt in `CURSOR_PHASE_10_HANDOFF.md`.
