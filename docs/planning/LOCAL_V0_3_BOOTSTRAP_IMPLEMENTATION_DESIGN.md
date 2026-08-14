# Local v0.3 Bootstrap Layer — Implementation Design

**Status:** Draft for implementation next session  
**Target:** Extend the frozen v0.2 orchestrator into a candidate that can execute, observe, repair, and validate local work without manual terminal copy/paste.  
**Important:** Build in a separate candidate copy. Do not modify the frozen known-good v0.2 snapshot.

---

## 1. Why the Bootstrap Exists

The frozen v0.2 system can:

- persist tasks and stages;
- make OpenAI and Anthropic API calls;
- enforce budgets;
- record telemetry;
- checkpoint completed stages;
- resume without duplicate paid work;
- recover from provider failure.

It does **not** yet provide a general autonomous local execution loop.

Specifically, it cannot yet reliably:

- run arbitrary authorized commands;
- capture stdout/stderr/exit status into durable task state;
- inspect failures and feed them back to an agent;
- apply controlled patches;
- rerun tests;
- bound repair loops;
- create local Git checkpoints around candidate changes;
- use current web/documentation research as a first-class orchestrator tool.

The bootstrap layer adds only enough capability to make the subsequent overnight architecture run meaningfully hybrid.

---

## 2. Safety Model

### Known-good baseline

- Frozen v0.2 ZIP/folder is immutable.
- Work occurs only in `v0.3_candidate`.
- Prefer local Git initialized inside the candidate.

### Allowed bootstrap actions

Within the candidate workspace:

- read files;
- create files;
- modify candidate files;
- run Python;
- run pytest;
- run explicitly permitted development commands;
- capture stdout/stderr/exit codes;
- inspect environment metadata;
- create/use a Python virtual environment;
- install Python packages when allowed by project policy;
- use OpenAI/Anthropic APIs;
- perform public web/documentation research where supported;
- use local Git status/diff/add/commit/branch/restore;
- create logs/JSON/Markdown artifacts.

### Not allowed without explicit human approval

- merge candidate into approved baseline;
- delete/overwrite frozen v0.2;
- modify unrelated directories;
- modify OS-wide settings;
- alter production business systems;
- send communications;
- spend outside approved API/tool budgets;
- delete production/cloud resources;
- expose secret values in logs/model prompts;
- make irreversible external changes.

---

## 3. Minimal Components

### 3.1 `command_runner.py`

Controlled subprocess execution with:

- structured command input;
- allowed working directory;
- timeout;
- stdout/stderr/exit-code capture;
- duration;
- durable event logging;
- safe handling of large output.

### 3.2 `workspace_guard.py`

Prevent candidate agents from writing outside granted scope.

Required behavior:

- canonicalize paths;
- enforce workspace root;
- deny path traversal;
- distinguish read/write authority;
- protect immutable paths;
- prevent accidental secret exposure.

### 3.3 `patch_manager.py`

Controlled candidate-file modification.

Requirements:

- workspace confinement;
- pre/post hashes;
- actor/task/reason metadata;
- non-destructive failure;
- optional backup/checkpoint.

### 3.4 `test_runner.py`

Normalized validation interface.

Initial checks:

- Python syntax/compile;
- pytest;
- selected project commands;
- deterministic schema/file assertions.

Normalized result:

- PASS
- FAIL
- ERROR
- TIMEOUT
- NOT_APPLICABLE

### 3.5 `repair_loop.py`

Bounded autonomous development loop:

1. run validation;
2. if PASS, stop;
3. if failure, summarize relevant failure context;
4. ask selected agent for repair hypothesis/patch;
5. apply controlled patch;
6. rerun validation;
7. stop on success or bounded failure.

Hard limits:

- max attempts;
- max cost;
- max wall-clock duration;
- repeated-identical-failure detection;
- repeated-identical-patch detection;
- no-progress detection.

### 3.6 `git_checkpoint.py`

Local rollback/versioning without GitHub.

Initial features:

- detect/init local Git;
- status;
- diff;
- branch;
- add/commit;
- capture commit hash in ledger;
- restore/revert within candidate;
- never auto-merge to approved baseline.

### 3.7 Current-documentation research capability

Tonight's run must be able to research current authoritative documentation rather than rely solely on pretrained model knowledge.

Requirements:

- current web/documentation access;
- URL/source metadata;
- primary-source preference;
- retrieval date/version;
- sourced fact vs inference;
- research usage/cost telemetry.

### 3.8 Extended ledger schema

Likely additions:

- `commands`
- `artifacts`
- `knowledge_items`
- `decisions`
- `backlog_items`
- `validation_runs`
- `human_actions`
- `git_checkpoints`

Preserve existing v0.2 tables where possible.

Use migrations or schema-version metadata.

---

## 4. Execution Contract

Use structured tool/action requests rather than arbitrary shell text.

Possible actions:

- READ_FILE
- WRITE_FILE
- APPLY_PATCH
- RUN_COMMAND
- RUN_TEST
- GIT_STATUS
- GIT_DIFF
- GIT_CHECKPOINT
- RESEARCH_WEB
- CREATE_BACKLOG_ITEM
- REQUEST_HUMAN_DECISION

Each action should include task ID, arguments, risk/authority class, expected result/evidence, and idempotency key where practical.

Python decides whether the action is permitted.

---

## 5. Authority and Risk

### Tier 0 — Read-only
May run unattended.

### Tier 1 — Reversible local change
Candidate files, tests, local Git, candidate venv. May run unattended within project scope with checkpoints.

### Tier 2 — Broad machine/system change
Human approval required initially.

### Tier 3 — External consequential change
Production deploys, communications, inventory/data changes, destructive cloud actions, or non-model financial actions. Human approval required.

---

## 6. Truth / Validation Bootstrap

Acceptance engine should combine:

1. deterministic validators;
2. authoritative evidence;
3. observed command/test outcomes;
4. semantic reviewer when useful;
5. human escalation.

Truth labels:

- VERIFIED
- SUPPORTED
- INFERRED
- DISPUTED
- UNKNOWN

Acceptance outcomes:

- PASS
- REPAIR
- BLOCK
- HUMAN_DECISION
- DEFER

### Validator calibration

Controlled cases:

- known complete;
- known incomplete;
- supported uncertainty;
- explicit constraint violation;
- legitimate unresolved disagreement.

Record false-pass, false-fail, and instability.

Do not spend indefinitely validating the validator.

---

## 7. Model/Agent Topology

Do not hard-code the existing four-call topology as universal.

Possible strategies:

- deterministic tool only;
- single-agent execution;
- planner → executor;
- researcher → critic;
- developer → tester/repairer;
- parallel investigators;
- competing approaches + adjudication;
- architect → executor → auditor → revision.

Topology selection should be explicit and logged.

---

## 8. Cost Guard Changes

Keep existing reservation logic.

Add:

- project/run hard ceiling;
- provider-specific ceiling;
- safety reserve;
- pre-run estimate;
- actual-vs-estimated reporting;
- validation budget;
- repair-loop budget;
- provider outage/rate-limit handling.

Future accounting should distinguish:

- confirmed actual cost;
- reserved cost;
- released reservation;
- uncertain/unreconciled cost.

---

## 9. Bootstrap Acceptance Tests

Before using the bootstrap for the overnight contract, prove:

1. passing and failing command capture;
2. workspace confinement;
3. patch + rollback;
4. autonomous repair of a tiny broken Python fixture;
5. bounded failure on an unfixable fixture;
6. local Git checkpoint;
7. budget denial before overspend;
8. restart/resume;
9. validator calibration;
10. current authoritative research with provenance.

---

## 10. Implementation Order

1. Copy frozen v0.2 → `v0.3_candidate`.
2. Initialize local Git.
3. Add workspace guard.
4. Add command runner.
5. Add test runner.
6. Add patch manager.
7. Extend ledger/events.
8. Add Git checkpoint helper.
9. Add bounded repair loop.
10. Add current-documentation research capability.
11. Add acceptance/truth abstraction.
12. Run bootstrap acceptance suite.
13. Re-review and launch the overnight contract.

Do not add cloud, PWA, GraphRAG, permanent vector infrastructure, or broad third-party-provider implementation during bootstrap.

---

## 11. Bootstrap Definition of Done

The bootstrap is complete when a controlled candidate task can:

- run a failing local test;
- capture the failure without user copy/paste;
- give the failure to an authorized agent;
- receive/apply a candidate repair;
- rerun validation;
- reach PASS or bounded BLOCK;
- preserve commands/patches/evidence;
- remain within workspace and budget;
- survive restart/resume;
- preserve a Git/checkpoint trail.

At that point the candidate has enough local autonomy to run the subsequent research + implementation contract meaningfully.

---

## 12. Resume Instruction

In the next session:

1. Keep frozen v0.2 untouched.
2. Create a separate `v0.3_candidate`.
3. Review this design before coding.
4. Implement the minimal bootstrap only.
5. Run bootstrap acceptance tests.
6. Re-review the overnight contract.
7. Estimate cost and duration.
8. Obtain explicit budget authorization.
9. Launch the overnight run.
