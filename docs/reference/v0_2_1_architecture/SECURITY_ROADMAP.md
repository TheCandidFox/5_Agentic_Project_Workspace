# SECURITY_ROADMAP.md

## Purpose and Scope

This module defines staged, testable security, privacy, and multi-tenant/business separation requirements for the multi-model agentic system across both the VALUE (~$150/month) and QUALITY-MAX architectures. It governs API keys and secrets, sensitive-data handling, permissions/least privilege, auditability, retention, encryption, and business/tenant separation. It does not select infrastructure vendors (see DEPLOYMENT) or provider routing rules (see MODEL_ROUTING_MATRIX) beyond the security gates those modules must implement. Current phase: **single operator, non-sensitive data only**, per the master goal. Everything below is staged so that adding a second user, a second business/tenant, or any Confidential/Regulated data has a named, pre-built upgrade path rather than a redesign.

Provider-asserted retention/training/credential-scoping claims are labeled **PROVIDER CLAIM** and must be re-verified against each provider's current, endpoint-specific documentation immediately before reliance, and quarterly thereafter — provider policies and account controls vary by endpoint, account type, and project/workspace configuration, not just by vendor, and have already been shown to drift (e.g., an earlier draft's incorrect "7-day" Anthropic retention figure). Internal system decisions (this system's own retention, backup, encryption, and permission rules) are labeled **DECISION** — they are choices this architecture makes, not facts to verify externally.

---

## 1. Data Sensitivity Classification (Gate Zero)

All routing, storage, and tool-access decisions depend on a deterministic, rule-based classifier applied at task-decomposition time — never on model self-judgment. Four classes:

- **Public** — no confidentiality concern.
- **Internal** — non-sensitive operator/business data (current default class for this project).
- **Confidential** — real business or third-party sensitive data, including any future second business or tenant's data (future phase).
- **Regulated** — anything with legal/compliance obligations (future phase, out of scope until triggered).

**DECISION:** every task carries a mandatory sensitivity tag. Any task without an explicit non-sensitive tag is treated as **sensitive by default** (fail-closed). This tag, combined with a versioned `provider_endpoint_policy` registry (provider × model × endpoint × feature × training-use × retention × ZDR eligibility × allowed tier), is the single source of truth the router consults — never a hardcoded provider-level assumption. This directly enforces the master-goal requirement that sensitive-data access requires approval and is never a silent routing decision.

**Current-phase rule:** only Public/Internal-class tasks are eligible for DeepSeek, xAI, OpenRouter, or any aggregator/reseller path. OpenAI and Anthropic (core providers) are the only providers eligible for anything above Internal, and only after the endpoint-level policy re-verification above.

---

## 2. API Keys and Secrets (Stage 0 → Stage 2)

**Stage 0 (current — solo operator, non-sensitive data):**
- One distinct API key/service credential **per component** (orchestrator, agent/worker runtime, backup job) — never one shared key across roles, so a compromised worker credential cannot also read backups or rotate other keys.
- Keys live in an encrypted secrets file (SOPS/age or equivalent) in the private repo, git-ignored in plaintext form; the decryption key is **never** co-located on the same persistent disk as the ciphertext it decrypts.
- No keys in client-side/browser code, ever — this applies even to the future PWA surface, which must proxy all provider calls through the server.
- Fixed rotation schedule (recommended: every 90 days) plus immediate rotation on suspected compromise.
- Full-disk encryption (BitLocker/FileVault) required on any machine holding secrets or cached credentials — this is a baseline control, not optional hardening.
- **Open item flagged for testing, not yet closed:** the exact bootstrap mechanism by which a running VM obtains a decrypted, runtime-only secrets artifact at deploy/restart (without persisting the private key) must be implemented and drilled — including rotation and offline key recovery — before any production credential is handled.

**PROVIDER CLAIM requiring a verification gate (corrects a prior draft's unverified assertion):** OpenAI and Anthropic both offer some form of project/workspace-scoped API keys, and per-component key separation (§2, above) is adopted as the Stage-0 default *regardless* of what further scoping either provider supports. However, the previously asserted claim that this automatically yields **independent spend limits and rate limits per component** is a provider-specific capability that varies by account type (individual vs. organization), project/workspace structure, and key type, and it has **not** been confirmed against current OpenAI/Anthropic primary-source documentation in this pass. This architecture therefore does not rely on independent per-key spend/rate ceilings as a load-bearing control at Stage 0.

- **Verification gate (must run before production use):** before go-live, document for the actual OpenAI and Anthropic account/project constructs in use: (a) whether keys are scoped to a project/workspace or only to the top-level account, (b) whether spend limits and rate limits are configurable and enforced per project/key or only per organization, (c) revocation granularity (can one component's key be revoked without affecting others), and (d) whether key-level usage is separately visible in each provider's own audit/usage log.
- **Fallback if granularity is unavailable:** if either provider does not support independent per-component spend/rate limits at the account tier in use, per-component least privilege is preserved instead by the application's own **budget-reservation ledger** (see LONG_RUNNING_WORK / COST_MODEL) — which already enforces atomic pre-dispatch budget reservation per task/run/component — plus the per-component security audit log (§4) as the compensating control, rather than depending on provider-native rate/spend isolation.

**Stage 1 (multi-machine / small team):** move to a hosted secrets manager (Doppler, Infisical, or 1Password Connect); CI uses workload-identity/OIDC rather than long-lived deploy secrets; SSO/MFA for human access to the secrets store; re-run the §2 provider-key verification gate against the then-current account tier.

**Stage 2 (multi-tenant / business separation / Confidential-Regulated data present):** cloud-KMS-backed secrets or managed Vault; envelope encryption; per-tenant/per-business key material for high-value tenants.

---

## 3. Permissions and Least Privilege

**Stage 0 (DECISION):**
- Single Operator identity holds full access. Every other credential (orchestrator, worker, backup job) is scoped to only what that component needs, per §2.
- No autonomous agent holds permission to: change billing, delete data, export or delete audit records, or approve irreversible external actions (email sends, real purchases, deployments, deletions). These require explicit Operator approval, operationalizing the master goal's approval gate **at the credential layer**, not merely in policy text.
- Sandboxed, egress-allow-listed code execution (ephemeral container, no standing production credentials) is a required Stage-0 component — cheap relative to model spend, and it closes the largest agentic risk (unsafe generated code, tool misuse, exfiltration via shell).
- Provider/workspace-scoped API keys are adopted as the least-privilege boundary to the extent confirmed available under the §2 verification gate; where that gate finds the provider account tier lacks per-component spend/rate isolation, the application-level budget ledger and audit log are the compensating controls, not an assumed provider guarantee.

**Stage 1:** full RBAC with a distinct "admin" role required for credential changes, policy-registry edits, and audit-log read/export; per-environment (dev/staging/prod) service accounts; SSO/MFA for all human roles.

**Stage 2:** a dedicated, provider-neutral policy-enforcement service sits between the orchestrator and all model/tool providers, deciding actor + tenant/business + task + sensitivity + allowed providers/endpoints/tools + budget + approval state. The model may recommend but never unilaterally select credentials, alter its own sensitivity classification, or approve irreversible actions.

---

## 4. Auditability and Logging

Operational telemetry (tokens, cost, model choice, errors, progress — already required by the master goal) and the **security audit log** are related but distinct systems; the former does not satisfy the latter.

**DECISION — security audit log control boundary (Stage 0, mandatory):**
- **Write access:** service/worker identities may append only (`INSERT`-only grant, no `UPDATE`/`DELETE`, or append-only object storage).
- **Read access:** restricted to the Operator/Admin identity; ordinary application roles cannot read it.
- **Content:** actor, task ID, sensitivity class, provider/endpoint selected, tool invocations, approval decisions, credential/key changes — metadata, not raw sensitive content.
- **Retention:** ≥90 days at Stage 0, exported to a location the primary application's own credentials cannot delete (separate account/bucket or credential scope), so a compromised worker cannot erase its own trail.
- **Tamper detection:** Stage 0 minimum is a physically separate write path plus no delete permission for normal roles; Stage 1+ adds hash-chaining or write-once storage for stronger tamper evidence, extending retention to ≥1 year pending compliance need.

**Empirical gate:** an audit-integrity drill must confirm that worker and ordinary-admin identities cannot modify or delete existing audit records, and that any attempted modification is itself logged in the physically separate store.

---

## 5. Retention and Privacy

**Internal data-lifecycle (DECISION, this system's own retention — independent of provider behavior):** task/goal records and model outputs persist until the parent project is deleted (cascading delete, target ≤30 days from request); artifacts mirror the same lifecycle; embeddings cascade-delete by source and are treated as rebuildable; caches expire on a ≤24h local TTL and are **not** an approved store for Confidential/Regulated content; operational telemetry rolls off at 90 days; backups rotate on a 30-day window; the security audit log follows §4.

**Provider-side retention/training (PROVIDER CLAIM, re-verify before sensitive use):** OpenAI, Anthropic, and Gemini each publish different retention windows for base chat endpoints versus stateful features (file storage, batch, caching, background mode, live sessions) — treating "paid API" as one privacy tier is incorrect and must not drive routing. Perplexity offers a documented ZDR option for Sonar; DeepSeek and xAI currently have insufficient primary-source evidence for enterprise-grade retention/subprocessor/residency terms and are **DEFERRED** for any Confidential/Regulated data — non-sensitive, cost-driven use only. Aggregators (OpenRouter) are an additional processing hop requiring the same endpoint-level review, not a privacy-neutral routing layer.

**DECISION:** backup RPO ≤ 24 hours, RTO ≤ 8 hours at Stage 0 (manual restoration acceptable given current solo, non-production-critical status). **Upgrade trigger:** tighten these targets and assign a named runbook owner at the first of (a) a second real human user or a second business/tenant being onboarded, or (b) any Confidential/Regulated data entering the system.

---

## 6. Encryption

**Stage 0 baseline (DECISION, mandatory, not optional):**
- Transit: TLS for all provider API calls and all internal service-to-database/object-store connections.
- At rest: managed-service default encryption (e.g., cloud provider default AES-256 SSE) for the database, object storage, backups, and the audit-log export destination — confirmed enabled at provisioning time, not assumed.
- Local: full-disk encryption on any machine holding secrets or cached credentials.
- Keys: provider-managed/cloud-default keys are acceptable at this stage.

**Stage 1/2:** move to customer-managed keys (KMS/CMK) for at least the audit-log and backup destinations; evaluate per-tenant/per-business envelope encryption for high-value tenants once real multi-tenant traffic exists.

---

## 7. Business/Tenant Separation Roadmap

No real second business, tenant, or user exists today; the system is built with the *shape* of business separation now to avoid an expensive retrofit.

**Stage 0 (now):** `tenant_id` column on all relevant tables plus Postgres Row-Level Security (RLS) enabled — understood explicitly as **one layer, not complete isolation**: RLS does not apply to table owners, superusers, or `BYPASSRLS` roles, and requires correct per-transaction context-setting under connection pooling. No table owner/superuser credential is used by the running application.

**Stage 1 (before any second real user or second business is onboarded — hard gate):** application-layer authorization checks in addition to RLS; business/tenant isolation enforced consistently across database, object store, vector index, cache, queue, and logs — not just one table property. A tenant-isolation test suite (API access, direct SQL, pooled connections, background workers, cache, vector search) must pass with **zero cross-tenant/cross-business leakage and fail-closed behavior on missing tenant context** before onboarding proceeds.

**Stage 2 (real multi-tenant/multi-business data, compliance-relevant):** evaluate schema- or database-per-tenant isolation instead of pooled RLS alone as the business separation mechanism; per-tenant/per-business backup/export/delete workflows; per-tenant envelope encryption for high-value tenants.

---

## 8. Roadmap Summary and Empirical Gates

| Stage | Trigger | Key additions |
|---|---|---|
| 0 (current) | Solo operator, non-sensitive data | Sensitivity gate, per-component keys + provider-key verification gate/fallback, RLS+`tenant_id`, append-only audit log, TLS + managed-default encryption, sandboxed code execution, manual backup/restore (RPO≤24h/RTO≤8h) |
| 1 | Multi-machine, small team, or second user/business pending | Hosted secrets manager, RBAC/SSO/MFA, app-layer tenant/business checks, tenant-isolation suite passed, hash-chained audit log, ≥1yr audit retention |
| 2 | Real multi-tenant/multi-business or Confidential/Regulated data live | KMS/CMK, per-tenant/per-business crypto, schema/DB-per-tenant business separation, policy-enforcement service, cross-account WORM backups |

**Flagged for empirical testing (not resolved by this document):** provider-specific verification of OpenAI/Anthropic key-scoping, spend-limit, rate-limit, revocation, and audit granularity (§2); provider-endpoint retention re-verification; prompt-injection red-team against web/PDF/repo/MCP inputs; tool-authorization test for irreversible actions; provider-control acceptance test (ZDR/caching/background actually matches documented policy); credential-compromise drill; backup/restore drill against the §5 targets; cost/loop-containment test; audit-integrity drill (§4); DeepSeek/xAI supplier review before any Confidential-tier use.

<!-- ARTIFACT_COMPLETE -->
