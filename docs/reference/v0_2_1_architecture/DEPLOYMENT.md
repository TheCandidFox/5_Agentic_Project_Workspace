# DEPLOYMENT.md — Cloud Migration and Machine-Agnostic Operations

## 1. Purpose and Deployment Principles

This module defines the migration path from the current local Windows-based GPT↔Claude Python loop to a cloud-hosted, OS- and machine-agnostic control plane. It covers deployment topology, private GitHub usage, database and object storage placement, secrets delivery, operational access from Windows/macOS, and a later PWA/mobile visibility surface.

This is deliberately a small-control-plane architecture. The system is a persistent, low-QPS orchestrator with potentially long-running jobs; it is not a conventional high-traffic public web application. Deployment should therefore optimize for:

1. **One canonical source of truth** for task state, budgets, approvals, artifacts, and decisions.
2. **Simple recovery over premature high availability.**
3. **Cloud-hosted execution with local machines acting as authenticated clients.**
4. **Provider-independent durable state**, rather than treating OpenAI, Anthropic, or any retrieval provider as the system of record.
5. **API-spend preservation:** infrastructure should occupy a small portion of the approximately $150/month value-tier budget.
6. **Safe progression toward future sensitive data and multi-user separation** without imposing enterprise infrastructure on the current non-sensitive, single-operator phase.

The architecture must never permit an agent to autonomously alter the user’s primary goal. Goal changes, external side effects, budget exceptions, data deletion, credential changes, and access to sensitive data remain server-enforced approval actions.

---

## 2. Target Cloud Topology

### 2.1 Value architecture: one canonical cloud control plane

The value architecture deploys one canonical Linux host. It runs the durable orchestration service and exposes a narrow authenticated control API. Windows and macOS machines do not synchronize state files, databases, or credentials between themselves; they interact with this canonical service.

```text
Windows / macOS / browser / later PWA
                 |
        Authenticated HTTPS control API
                 |
       Canonical Linux cloud host
  ┌──────────────────────────────────────┐
  │ API + scheduler + router              │
  │ One active orchestration worker       │
  │ Provider adapters / policy gateway    │
  │ Sandboxed tool-worker launcher        │
  │ Postgres task and idempotency ledger  │
  └──────────────────────────────────────┘
                 |              |
          Direct provider APIs   | S3-compatible API
          OpenAI / Anthropic     |
                                v
                    Cloudflare R2 or S3 object storage
                    artifacts, logs, backups, exports
```

The deployed service has these logical components:

| Component | Responsibility | Deployment rule |
|---|---|---|
| Control API | Dashboard/PWA access, task submission, approvals, status, artifact links | Public HTTPS endpoint with authentication |
| Scheduler/router | Admissions, budgets, task dependencies, model selection, retries, escalation | One active instance in value tier |
| Worker | Executes claimed steps and invokes provider/tool adapters | One active worker initially; lease-based claims required |
| Database | Tasks, steps, budget reservations, approvals, idempotency, progress, telemetry metadata | Transactional Postgres ledger |
| Object storage | Large prompts, raw outputs, documents, screenshots, run bundles, database backups | S3-compatible storage; never Git |
| Tool sandbox | Browser automation, code execution, rendering, controlled integration actions | Ephemeral, isolated, no standing production secrets |
| Policy gateway | Data-classification, tool authorization, provider/endpoint allowlists | Must be enforced before dispatch |

### 2.2 Database decision and research contradiction

There is a tension in the research record:

- The cloud/machine-independence track recommends SQLite with a single canonical writer and manual failover for the value tier.
- The long-running-work track concludes that deployed multi-machine, restartable operation requires a Postgres-backed ledger and permits SQLite only for local single-worker development.

This deployment module resolves the contradiction conservatively:

- **Local development:** SQLite is permitted for a single developer process.
- **Deployed value architecture:** use **Postgres** as the task, idempotency, budget, approval, and event ledger.
- **Quality-max architecture:** use managed or separately operated Postgres with stronger backup, role separation, and optional multiple worker roles.

The reason is functional rather than scale-driven: Windows/macOS access, multi-day work, restarts, worker leases, and future concurrent workers are core requirements. A Postgres ledger avoids treating a VM-local database file as a distributed-state mechanism. It also permits the canonical cloud API to serve multiple machines without database-file synchronization.

For the value tier, Postgres may run on the same canonical host as the orchestrator if that is cheaper and operationally simpler than a managed database. It must still have encrypted daily backups to separate object storage and a documented restore procedure. This is not high availability; it is recoverable single-host operation.

**Empirical check required:** benchmark the chosen VM size with Postgres, the orchestrator, and one active worker under representative workloads. A low-memory host may be insufficient. Provisioning cost and memory headroom must be verified before declaring the $10–20/month infrastructure estimate achievable.

---

## 3. Windows, macOS, and Local Development Migration

### 3.1 Local machines become portable development clients

The initial Windows Python loop should be refactored so that model-routing logic and durable state are no longer coupled to one workstation. Windows remains fully supported, but it becomes one client environment among several.

The same development contract must work on:

- **Windows 11**, preferably through Docker Desktop with WSL2 where available;
- **macOS**, through Docker Desktop or a compatible container runtime;
- Linux development environments and optional GitHub Codespaces later.

Use a repository-root `devcontainer.json` and Docker Compose configuration to standardize:

- Python version and dependency lockfile;
- database client tooling;
- lint/test commands;
- migration commands;
- local service startup;
- environment-variable names;
- sandbox image versions;
- canonical `make`/task-runner commands.

Minimum portable commands:

```text
make bootstrap
make test
make db-migrate
make run-local
make deploy-check
make restore-drill
```

No operating-system-specific script should be required for normal development, testing, or deployment. Host-specific shell wrappers may exist only as convenience wrappers around the canonical commands.

### 3.2 Migration stages from the local Python loop

| Stage | Change | Exit condition |
|---|---|---|
| 0. Stabilize local loop | Preserve current GPT↔Claude behavior; add structured run IDs, logs, artifacts, and configuration separation | Existing loop can replay a completed run from stored inputs |
| 1. Extract durable interfaces | Separate provider adapters, task/step model, budget checks, and artifact writing from the local script | A step can be resumed after process restart without duplicate provider dispatch |
| 2. Add local database mode | Use SQLite locally for rapid development and tests; add migrations compatible with Postgres | Test suite passes against both SQLite development mode and Postgres integration mode where feasible |
| 3. Deploy cloud control plane | Deploy API, one worker, Postgres, object storage, and backups | Windows and macOS submit/view the same cloud task state |
| 4. Move durable execution | Make the cloud ledger authoritative; local loop becomes a client or local development worker only | Restarting or replacing a laptop does not interrupt canonical cloud work |
| 5. Add dashboard/PWA | Add read/status/approval surface after core recovery and authorization controls work | Mobile approval cannot create duplicate or unauthorized actions |

The migration must not require copying a SQLite database, `.env` file, artifact directory, or provider session between machines. Any local state required for developer convenience is disposable and reproducible from GitHub code plus cloud-hosted canonical records.

---

## 4. GitHub, CI, and Release Flow

### 4.1 Private GitHub repository boundaries

Use a private GitHub repository as the versioned source for:

- application source code;
- infrastructure configuration;
- database migrations;
- prompt templates and schemas;
- routing policies;
- policy-registry definitions;
- test fixtures containing only non-sensitive or sanitized data;
- documentation and runbooks;
- container definitions;
- deployment manifests.

GitHub is **not** the system of record for:

- mutable task state;
- task transcripts or raw generated artifacts;
- provider API keys;
- decrypted secrets;
- production database exports;
- raw telemetry;
- audit-log records.

Secret scanning and push protection are useful supplementary controls, but they do not replace pre-commit checks, credential rotation, or a proper secrets-delivery design.

### 4.2 Deployment pipeline

The initial release flow should remain simple:

1. A change is merged to a protected main branch in private GitHub.
2. GitHub Actions runs linting, unit tests, integration tests, schema checks, and container build checks.
3. A manually approved deployment job publishes a versioned container image or deploys through a host-specific command.
4. The cloud host pulls the immutable build version and runs database migrations once.
5. A post-deploy smoke test verifies the control API, database connectivity, object-storage access, provider-adapter configuration, and worker health.
6. The deployment record stores commit SHA, migration version, container/image digest, policy-registry version, and deploy actor.

For the value tier, do not automatically deploy unreviewed changes directly from every commit. Manual promotion is consistent with the goal’s approval requirements and reduces the chance that an agent-generated code change alters production behavior.

**Secrets warning:** GitHub Actions secrets and Codespaces secrets have different scopes and should not be assumed interchangeable. Prefer short-lived deployment credentials or manual operator-mediated deployment until an OIDC workload-identity design is implemented.

---

## 5. Object Storage and Artifact Lifecycle

### 5.1 S3-compatible object storage

Use Cloudflare R2 as the value-tier default object store because it is S3 API-compatible, inexpensive at small volumes, and avoids R2-side egress fees. AWS S3 remains the compatible alternative where future IAM, compliance, residency, or integration needs justify it.

Object storage holds:

- raw provider responses where retention policy allows;
- input and output documents;
- browser screenshots and research captures;
- generated spreadsheets and reports;
- task context packets and compaction snapshots;
- append-only run bundles;
- encrypted database backups;
- audit-log exports;
- rebuildable retrieval-source corpora.

Use immutable object keys. A write creates a new object rather than overwriting a prior artifact:

```text
tenant-or-workspace/project/run-id/artifact-type/content-hash.ext
```

The database stores the authoritative metadata, content hash, object URI, sensitivity class, retention date, and access policy. Object storage is not queried blindly by agents; the policy gateway must authorize retrieval and tool access.

### 5.2 Backup and recovery

The deployment baseline is:

- daily encrypted database dumps;
- continuous or frequent database backup where feasible;
- object-storage replication or scheduled copy to a separate account/bucket;
- rolling 30-day retention for backups;
- distinct backup credentials that the normal worker cannot use to delete backup copies;
- restore access requiring an elevated operator credential.

The Stage 0 recovery target is **RPO ≤24 hours** and **RTO ≤8 hours**. This is adequate only for the current single-operator, non-sensitive phase. The target must be reassessed when either a second real user is granted access or Confidential/Regulated data is stored.

Cloudflare R2 native versioning, retention, and object-lock capabilities must be verified at implementation time before being relied upon. Until then, immutable keys and a separately credentialed backup copy are the required fallback.

---

## 6. Secrets, Access, and Cloud Operations

### 6.1 Value-tier secrets approach

Use separate credentials for:

- orchestrator/provider dispatch;
- tool worker;
- object storage runtime access;
- backup writer;
- deployment;
- database administration.

No browser, PWA, client-side JavaScript bundle, or mobile device may contain provider API keys, object-store credentials, or database credentials.

For the current solo phase, SOPS/age-encrypted configuration in private GitHub is acceptable only if the bootstrap process is documented and tested. The decryption identity must not simply persist beside the encrypted file on the same cloud VM.

Before production credentials are used, implement and test:

- initial host bootstrap;
- runtime secret injection;
- restart behavior;
- file permissions and deletion of temporary plaintext;
- API-key rotation;
- lost-device recovery;
- emergency revocation.

This remains an empirical implementation gate, not a completed security claim. A hosted secrets manager becomes the preferred upgrade when multiple environments, operators, or sensitive data are introduced.

### 6.2 Simple operations model

The value deployment has one active orchestrator and one active worker. It does not claim automatic high availability.

Operational controls:

- supervised services using `systemd`, Docker restart policies, or equivalent;
- health endpoint for API, worker, database, and object storage;
- structured logs with run/task/step IDs;
- daily backup success alert;
- budget and provider-error alerts;
- bounded retry policies honoring provider `Retry-After`;
- lease-based task claims in Postgres;
- dispatch-intent record before each provider call;
- `submitted_unknown` reconciliation state after network ambiguity;
- idempotent tool wrappers for any external write.

If a host fails, value-tier recovery is manual:

1. Confirm the old host is terminated or network-isolated.
2. Revoke or rotate its write-capable credentials.
3. Restore database and required artifacts from backups.
4. Deploy the replacement host.
5. Start exactly one scheduler/worker after reconciliation.
6. Reconcile any steps in `submitted_unknown` before re-dispatching.

Do not enable automatic failover until a concrete fencing-token protocol has been designed and passed a partition/host-loss drill.

---

## 7. PWA, Mobile, and Dashboard Deployment

The PWA/mobile surface is a later visibility and approval client, not an agent runtime and not a source of truth.

Its allowed capabilities are:

- read task/run status;
- review costs, model choices, errors, and progress;
- receive push notifications;
- approve or reject pending actions;
- view artifacts through short-lived authorized links;
- cancel a run or request human review where policy permits.

It must not:

- execute the orchestration loop;
- retain long-lived provider credentials;
- independently schedule tasks;
- make server-side authorization decisions;
- rely on mobile background execution for timers or recovery.

All approval actions must be server-side, authenticated, CSRF-protected, idempotent, time-limited, and tied to a specific task/step/policy version. Push notifications are advisory; the server remains responsible for expiration, escalation, and workflow continuity.

iOS/iPadOS support for Home Screen web push exists on current supported versions, but actual iOS and Android notification behavior must be tested on real devices before mobile notifications are treated as operationally reliable.

---

## 8. Quality-Max Deployment Differences

The quality-max architecture preserves the same logical boundaries but expands operational separation when justified:

- dedicated control-plane compute;
- separate tool-worker pool for browser automation, document generation, and sandboxed code execution;
- managed or separately operated Postgres;
- stronger object-store IAM and cross-account backup;
- hosted secrets manager with audit logging and environment separation;
- optional cold standby host, never a simultaneous unfenced writer;
- separate queues or worker classes for batch review fan-out;
- optional owned retrieval/vector infrastructure after empirical justification;
- higher-frequency restore drills and stronger evidence/artifact hashing.

A Temporal-class workflow platform is not a default quality-max dependency. It is considered only if the Postgres-backed state machine fails the defined multi-day fault-injection suite or becomes operationally inadequate.

---

## 9. Deployment Acceptance Tests and Deferred Decisions

Before treating the cloud migration as complete, pass the following tests:

| Test | Pass condition |
|---|---|
| Windows/macOS portability | Both environments run the canonical bootstrap, test, and local development commands |
| Cloud restart recovery | Worker restart resumes work without loss or duplicate external action |
| Provider dispatch ambiguity | Crash/network loss after dispatch results in reconciliation, not blind duplicate submission |
| Database restore | Restore meets Stage 0 RPO/RTO and preserves task/idempotency integrity |
| Object-storage restore | Required artifacts and audit exports restore from separate backup location |
| Credential separation | Worker cannot delete backups, rotate keys, or read audit stream |
| PWA approval | Duplicate submission, expired approval, and CSRF attempt all fail safely |
| Budget enforcement | Reserved budget prevents dispatch beyond task/run/month caps |
| Host-loss drill | Manual recovery proves only one active writer resumes |
| Sensitive-data gate | Disallowed provider/endpoint/tool combinations are blocked before transmission |

The following remain explicitly deferred pending empirical verification:

- actual Fly.io, Hetzner, Railway, managed Postgres, and R2 monthly billing;
- selected VM memory requirements under realistic Postgres and worker load;
- R2 versioning/object-lock/retention feature suitability;
- SOPS/age production bootstrap and key-recovery design;
- provider-specific endpoint retention and ZDR eligibility before Confidential data use;
- mobile push behavior on the user’s actual iOS and Android devices;
- any automated-failover fencing implementation.

<!-- ARTIFACT_COMPLETE -->
