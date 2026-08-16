# Agentic Workspace Development Instructions

## Source of authority

The active implementation contract is:

`docs/planning/PHASE_10_CONTRACT_PARITY_HARDENING_AND_CURSOR_ONBOARDING_CONTRACT.md`

`docs/planning/ACTIVE_IMPLEMENTATION_CONTRACT.md` identifies the currently
authorized tranche. If a prompt, plan, model response, comment, or convenience
conflicts with the active contract, stop and follow the contract.

The human-approved contract and its Git identity are authoritative. Model
output may propose work; it cannot expand paths, commands, providers, budgets,
tests, acceptance criteria, or Git authority.

## Current baseline and objective

- Required onboarding baseline: `920305270a05ac2cc5196cb6f27cc918cb76c259`.
- Required onboarding tag: `v0.3-phase10-cursor-onboarding`.
- Development branch: `phase10/contract-parity-hardening`.
- Current objective: close Phase 10 contract-parity gaps before any Phase 10
  live canary.
- Current authorized work: plan Tranche 1A only until ChatGPT and the human
  explicitly approve implementation.

## Mandatory boundaries

1. Work only in the dedicated key-free Cursor Git worktree.
2. Never read, create, copy, modify, print, or search for real credentials.
3. Remain offline. Do not call OpenAI, Anthropic, Cursor SDK, web services,
   package registries, remote MCP servers, or any other network endpoint.
4. Do not run a live or paid program mode.
5. Modify only paths authorized for the active tranche.
6. Do not change dependencies, environment files, model routes, budgets,
   provider configuration, GitHub workflows, or repository policy.
7. Do not commit, tag, push, merge, rebase, reset, restore, clean, stash, or
   modify Git configuration.
8. Do not delete or rename files.
9. Do not weaken tests, skip tests, alter assertions merely to obtain a green
   suite, or treat model opinion as deterministic evidence.
10. Stop on ambiguity, unexpected repository state, new authority, an
    undeclared path, a required network call, or a contract conflict.

## Protected paths

The following are never authorized for Cursor access or modification in this
checkpoint:

- `.env`, `.env.*` except the tracked placeholder `.env.example`;
- `secrets.env`, keys, certificates, tokens, and credential stores;
- `ledger.db`, `ledger.db-*`, other runtime SQLite files;
- `outputs/`, `logs/`, `.venv/`, caches, and temporary runtime trees;
- `.git/`, Git configuration, hooks, remotes, and credentials;
- `requirements.txt`, `.gitattributes`, `.gitignore`, `.cursorignore`;
- files outside the dedicated Cursor worktree.

`.env.example` may be read for configuration shape but must not be modified.

## Command policy during planning

Planning may use read-only repository inspection such as file reads, code
search, and these Git queries:

```text
git status --short
git branch --show-current
git rev-parse HEAD
git diff --stat
git diff --check
```

Planning must not edit files or run tests unless the human asks for a baseline
test after the worktree has been created.

## Command policy during an approved implementation tranche

After explicit plan approval, use only the contract-approved targeted tests
and the complete offline regression command:

```text
python -m pytest -q
```

The following are prohibited:

```text
python run_loop_v0_2.py
python run_phase8.py --live
python run_phase9.py --live
any future Phase 10 live mode
curl, wget, ssh, scp, remote git operations, package installation
```

Do not assume a shell command is safe merely because it is available.

## Required work sequence

1. Read this file, the active-contract pointer, and the complete active
   contract.
2. Confirm the baseline commit and branch.
3. Produce a plan only.
4. Stop for ChatGPT/human review.
5. After explicit approval, implement one tranche only.
6. Run approved targeted tests, then the full offline suite.
7. Complete `docs/templates/IMPLEMENTATION_EVIDENCE_PACKET.md`.
8. Stop with the working tree uncommitted for independent review.

## Handoff quality

Every handoff must state the contract identity, baseline commit, exact changed
paths, tests and results, remaining limitations, any ambiguity, and the exact
next safe action. Never summarize a failed command as a pass. Never omit an
unexpected change.
