# COST_MODEL.md

## 1. Purpose, Scope, and Evidence Posture

This module defines a transparent, reproducible way to estimate, track, and cap spend for the multi-model agentic system, calibrated to a **~$150/month API spend target** for the VALUE architecture, with an explicit comparison envelope for the QUALITY-MAX architecture. It does not re-litigate provider selection (MODEL_ROUTING_MATRIX) or infrastructure hosting (DEPLOYMENT) — it consumes their outputs as inputs to a cost ledger.

**Evidence posture, stated up front because it materially affects how this model must be used:** every provider price cited across the research tracks carries some degree of staleness or conflict risk. Two conflicts are load-bearing enough to change the budget by multiples and are **not resolved**:

- OpenAI's cheapest ("economy") tier has a **5x price conflict** between OpenAI's own catalog page ($1/$6 per MTok) and its own pricing page ($0.20/$1.20 per MTok). This is unresolved and must not be used as a single point estimate.
- DeepSeek's pricing is corroborated only by six independent trackers, not by a vendor-audited price card, and its own docs flag a **pending, undated price increase**.

Because of this, every dollar figure in this document is labeled as either **VERIFIED** (multi-source or official, dated), **PLANNING ESTIMATE** (best available, sensitivity-banded), or **ILLUSTRATIVE** (order-of-magnitude only, not for budget lock-in). Nothing here should be treated as a committed invoice forecast. A pre-launch re-pull of every rate against live provider pricing pages is a hard prerequisite before this cost model is used to approve real spend (see §9).

## 2. Cost Ledger: What We Actually Meter

A workload's true cost is not "input tokens + output tokens." The ledger meters seven independent line items per task, because several research tracks converged on the same correction: token price alone systematically undercounts real spend.

1. **Input tokens** — uncached, billed at the model's standard input rate.
2. **Cache-write tokens** — billed at a premium over standard input (OpenAI: ~1.25x; Anthropic: cache writes carry their own multiplier by TTL) whenever a new or invalidated prefix is written to cache.
3. **Cache-read (hit) tokens** — billed at a steep discount (OpenAI ~10% of input; Anthropic ~10% of input) but only when the exact prefix/breakpoint is reused — a **measured**, not assumed, hit rate.
4. **Output tokens**, including hidden reasoning/thinking tokens on reasoning-mode calls, which can bill materially above the visible completion length.
5. **Tool/retrieval fees** — flat or metered charges independent of token volume: web search ($/1,000 calls), file-search storage ($/GB-day) and per-call fees, Perplexity's per-request search-context-depth fee, container/code-execution session time.
6. **Storage/embedding costs** — vector index storage, file-search storage beyond free tiers, object storage for artifacts/logs (tracked in DEPLOYMENT, referenced here as a budget-adjacent line).
7. **Retry/failure overhead** — tokens and tool calls consumed by failed attempts, escalation repeats, and reviewer passes that do not produce an accepted result.

**Guardrail-relevant levers that reduce this ledger, treated as upside, not baseline:**
- **Batch API discounts** (OpenAI ~50%, Anthropic ~50%) — deterministic, but eligible only for non-interactive, deferrable work with provider/model-specific eligibility that must be checked, not assumed universal.
- **Prompt caching** — real, but its savings are contingent on stable, reusable prefixes and must be empirically measured per agent role rather than budgeted at a fixed percentage.

## 3. Provider Rate Inputs and Verification Status

| Provider / tier | Role in routing | Price status | Note |
|---|---|---|---|
| OpenAI flagship (`gpt-5.6-sol`) | Escalation / coding-agentic | VERIFIED ($5/$30 per MTok, cross-source agreement) | Stable anchor for flagship-tier cost |
| OpenAI mid (`gpt-5.6-terra`) | Default for moderate tasks | PLANNING ESTIMATE (~$2–2.50/$12–15, minor cross-source variance) | Not budget-critical |
| OpenAI economy (`gpt-5.6-luna`) | High-volume cheap lane | **UNRESOLVED 5x CONFLICT** ($1/$6 vs $0.20/$1.20) | Do not lock budget; use sensitivity band (§6) |
| Anthropic Haiku 4.5 | Cheap/fast lane | VERIFIED ($1/$5) | |
| Anthropic Sonnet 5 | Default/mid lane | VERIFIED, **time-boxed**: $2/$10 through Aug 31 2026, then $3/$15 | Budget must use the post-cliff $3/$15 rate to avoid understating steady-state cost |
| Anthropic Opus 5 | Capped escalation | VERIFIED ($5/$25) | |
| Anthropic Fable 5 / Mythos | Rare quality-max escalation only | VERIFIED to exist; DEFERRED for value routing | 2x Opus cost, excluded from VALUE default |
| Gemini cheapest tier | Triage / cheap first-pass | PLANNING ESTIMATE (audit-cited, not re-pulled this pass) | Pending workload benchmark |
| DeepSeek V4-Flash/Pro | Non-sensitive bulk coding/reasoning | Tracker-corroborated, not vendor-audited; pending price increase flagged by DeepSeek itself | Governance-gated (data-classification allowlist), not price-gated |
| Perplexity Sonar family | Research retrieval | Formula verified (tokens + search-depth fee + optional citation/reasoning fees); exact fee amounts DEFERRED | Model the formula, not a fixed number |
| xAI/Grok | Bench-test candidate | Tool/reasoning surface verified; long-context **repricing cliff** verified (crossing a threshold reprices the *whole* request) | Must be modeled per-model at implementation time |
| OpenRouter | Secondary/fallback only | VERIFIED fees: 5.5% credit purchase, 5% BYOK past 1M free requests/month | Never routes core-provider (OpenAI/Anthropic) traffic |

All figures require a **dated re-pull against the live official page immediately before COST_MODEL numbers are used to approve real spend.**

## 4. Example Monthly Workloads (Illustrative Scenarios)

These scenarios exist to pressure-test whether a $150/month budget is *plausible*, not to forecast an exact invoice. Task counts and token volumes are placeholders pending the EMPIRICAL_EVAL_PLAN and must be replaced with measured values.

**Workload mix, aligned to stated priorities (coding/automation/research highest; data medium-high; documents medium; strategy/image lower):**

| Category | Est. tasks/month | Default lane | Escalation rate (assumed, unvalidated) |
|---|---|---|---|
| Coding / software | 400 | Cheap/mid cascade | ~20–25% to flagship, ~5% cross-provider review |
| Automations/integrations | 150 | Cheap/mid cascade | ~15% to flagship on tool-call failure |
| Web research | 150 | Cheap model + Perplexity/native search | ~10% to Deep Research / higher search depth |
| Spreadsheet/structured data | 80 | Mid tier | ~10% escalation |
| Document generation | 40 | Mid tier, Batch-eligible | ~5% escalation |
| Business strategy / images | 10 | Mid tier / native multimodal | Rare escalation |

**Illustrative token/tool ledger (per month, sensitivity-banded on the OpenAI economy-tier conflict):**

- Cheap/economy lane: ~40–50M input tokens, ~8–10M output tokens.
  - At $0.20/$1.20 (low case): ≈ $8–10 input + $10–12 output ≈ **$18–22/month**.
  - At $1/$6 (high case): ≈ $40–50 input + $48–60 output ≈ **$88–110/month**.
  - This single conflict alone can swing the cheap lane by ~$70–90/month — the reason it is flagged CRITICAL in §7.
- Mid lane (Sonnet 5 / OpenAI mid, steady-state pricing): ~9M input (50% assumed cache-hit, unvalidated) + ~1.8M output ≈ **$40–45/month**.
- Escalation lane (Opus 5 / flagship, capped volume): ~0.8M input / 0.2M output ≈ **$8–10/month**.
- Tool/retrieval line items (web search flat fees, file-search storage, Perplexity depth fees, code-execution containers): budgeted as a **separate ~$10–15/month reserve**, since these are flat/metered and can dominate cost on low-token, tool-heavy automation tasks even when token spend is trivial.
- DeepSeek (non-sensitive bulk overflow, governance-gated): optional ~$5–10/month workhorse lane if the classification gate is enforced and its price holds.

**Net illustrative total:** roughly **$80–115/month at the low-conflict-case, $150–185/month at the high-conflict-case**, before infra (~$10–20/month, tracked in DEPLOYMENT) and before OpenRouter/aggregator opportunistic use. This range is precisely why the Luna conflict is a release-blocking verification item, not a rounding error — it is the difference between comfortably under budget and structurally over budget.

## 5. Guardrails, Caps, and Degradation Policy

Because pricing is volatile and several inputs are unresolved, the system must enforce spend discipline mechanically, not by hoping the estimate holds.

- **Global monthly ceiling:** hard cap at $150/month API spend for VALUE architecture, tracked from real provider usage/billing fields, not from the estimate above.
- **Per-provider and per-lane sub-caps**, set below the global ceiling, each independently enforced (e.g., OpenAI economy lane, Anthropic mid lane, DeepSeek non-sensitive lane, tool-fee reserve). No single lane may consume the entire budget.
- **Per-task budget reservation before dispatch**, sized by importance band, covering expected output tokens, hidden reasoning tokens, tool calls, and one retry/escalation — dispatch is blocked if remaining budget cannot cover the worst permitted escalation for that task.
- **Graceful degradation, not hard failure:** when a sub-cap is approached, the router de-escalates to a cheaper tier or defers non-urgent work (e.g., shifts to Batch) rather than stopping entirely; only exhaustion of the global cap halts new task dispatch.
- **Daily spend ceiling** as an early-warning guardrail beneath the monthly cap, to prevent a single burst day from consuming most of the month's budget before human review occurs.
- **Escalation-depth cap** (max 3 tiers) and **disagreement/retry cap** (max 1 repeat before human review) — both cost guardrails and anti-loop guardrails simultaneously, since unbounded escalation is itself a cost driver.
- **Data-classification gate precedes cost routing:** DeepSeek, OpenRouter, and any free/low-retention-guarantee tier are default-deny for any task not explicitly tagged non-sensitive; this is a guardrail against a cost optimization silently becoming a data-exposure incident.
- **Account-tier readiness guardrail:** VALUE architecture must budget a ramp period to reach the provider account tier required to sustain peak-day burst (e.g., OpenAI Tier 1 ≈ $100/month cap, Tier 2 requires $50 cumulative paid usage); the system must not assume day-one capacity to hit $150/month of usage.

## 6. VALUE ($150/mo) vs QUALITY-MAX Cost Envelopes

| Dimension | VALUE architecture | QUALITY-MAX architecture |
|---|---|---|
| Target monthly spend | ~$150 (hard cap, sensitivity-banded per §4) | No fixed cap; cost is a tracked output, not the constraint |
| Default model tier | Cheapest eligible per cascade | Flagship-tier first attempt on priority workloads |
| Review | Deterministic verifier default; cross-provider review sampled (Band 2–3 tasks only) | Deterministic verifier + near-universal cross-provider review on priority workloads |
| Redundancy/ensembling | None by default | Stakes-gated (parallel implementations, independent research verification) for high-importance tasks only |
| Rare/expensive tiers (Fable/Mythos, Fast Mode, xAI long-context) | Excluded by default | Available as capped, evidence-gated escalation |
| Batch/caching | Used aggressively wherever eligible to protect the cap | Used for non-blocking review passes to protect responsiveness, not primarily for cost |
| Illustrative monthly order of magnitude | $80–185 (see §4 sensitivity) | Multiple times VALUE — no validated multiplier exists; the previously circulated "~3.2x / $423" figure is an **unaudited scenario, not a finding**, and must not be treated as decision-grade until the same workload ledger is run against quality-max routing choices |

The honest position: a specific quality-max dollar figure **cannot yet be stated as fact**. It must be produced by re-running the §4 ledger with quality-max's routing defaults (flagship-first, near-universal review, occasional rare-tier escalation) once task-volume assumptions are empirically grounded.

## 7. Failure Modes and Cost Drivers

- **[CRITICAL]** OpenAI economy-tier 5x pricing conflict (§3) — until resolved by a live billed test, the VALUE budget cannot be locked; treat $150/month as a midpoint hypothesis inside a $80–185 band.
- **Reasoning-token opacity** — hidden reasoning tokens can inflate output cost well above sticker price; no verified multiplier exists, so this must be instrumented per call, not assumed.
- **Tool-fee dominance on low-token tasks** — a research or automation task with heavy tool/search calls but light token volume can have tool fees exceed token cost entirely; must be tracked as an independent ledger line, not folded into token estimates.
- **Cache-hit rate overestimation** — assumed hit rates (e.g., the 50% used in §4) are placeholders; real hit rate depends on prefix/breakpoint stability and must be measured, not assumed, per agent role.
- **Rate-schedule cliffs** — Anthropic's Sonnet 5 promotional-to-standard price step (Sep 1 2026, +50%) is a known example; any model using pre-cliff pricing without a hard expiry reminder will silently understate steady-state cost.
- **DeepSeek/aggregator governance failure** — a misrouted sensitive task reaching a non-eligible low-cost provider is a security failure disguised as a cost optimization; mandatory classification-gate testing is required before this lane is trusted.
- **Escalation/disagreement loops** — without hard depth/retry caps, cascades and reviewer disagreement can consume budget without bound; this is both a cost driver and a stopping-condition failure.
- **Provider/pricing drift** — hardcoded model IDs or prices will go stale as catalogs change (demonstrated directly by the Sol/Terra/Luna naming churn and DeepSeek's pending increase); the router must consume a periodically-refreshed rate registry, not constants in code.
- **Long-context repricing cliffs (xAI, and possibly others)** — a prompt only marginally over a threshold can reprice the *entire* request, silently multiplying single-task cost; must be modeled per model before large-context calls are routed automatically.

## 8. Empirical Validation Plan (Required Before Lock-In)

1. Live billed test resolving the OpenAI economy-tier conflict (100K-token round trip, read actual invoice line).
2. Measured cache-hit rate per agent role on real prompt structure, not assumed percentage.
3. Instrumented reasoning/output token counts per task class and effort level.
4. Measured escalation rate and quality delta across the representative task suite (coding, automation, research, data, documents) at cheap/mid/flagship tiers.
5. Confirmed Batch/cache eligibility and discount magnitude per provider/model actually selected.
6. Re-pulled, dated official pricing for every provider/tier in §3 immediately before budget lock-in.
7. A dry-run of the full §5 guardrail stack (sub-caps, degradation, classification gate) with injected sensitive-task and budget-exhaustion scenarios, confirming no silent overspend or misroute.

## 9. Sources & Re-Verification Requirements

This model synthesizes OpenAI, Anthropic, third-party provider, routing, and infrastructure research tracks, all of which carry the same standing instruction: **every price is dated and perishable.** No figure in this document may be used to authorize real spend without a same-day re-pull of the corresponding official pricing page and a recorded retrieval timestamp. Until the §8 items are closed, this cost model is a **planning instrument**, not a committed budget.

<!-- ARTIFACT_COMPLETE -->
