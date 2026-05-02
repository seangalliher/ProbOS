# Wave 7 Prompt Review Sweep — 2026-05-01

**Reviewer:** Architect (verify-first review of own drafts)
**Scope:** 5 prompts drafted in commit `2d6632e` for AD-466, AD-456, AD-528, AD-467, AD-463.
**Review file path pattern:** `prompts/Reviews/ad-NNN-*-review.md`.

---

## Verdicts at a Glance

| AD | Title | Verdict | Required | Recommended | Nits | Build Readiness |
|---|---|---|---|---|---|---|
| AD-466 | Engineering Infrastructure | **✅ Approved** | 0 | 4 | 4 | Yes |
| AD-456 | Security Infrastructure | **❌ Not Ready** | 3 | 5 | 4 | After scope decision |
| AD-528 | Ground-Truth Task Verification | **⚠️ Conditional** | 3 | 5 | 4 | After 15-min fix |
| AD-467 | Operations Crew | **⚠️ Conditional** | 2 | 5 | 4 | After 10-min fix |
| AD-463 | Model Diversity & Neural Routing | **⚠️ Conditional** | 3 | 5 | 4 | After 30-min fix |
| **Totals** | | **1 ✅ / 3 ⚠️ / 1 ❌** | **11** | **24** | **20** | |

The dispatch's tolerance allowed `4 ✅ + 1 ⚠️ on AD-463 only`. **Tolerance exceeded** — surfacing back per the standing rule. The exceeding prompts are AD-456 (❌), AD-528 (⚠️), AD-467 (⚠️). All three have concrete mechanical resolutions; none require architectural pivots.

Wave 5 history: 0 ✅ / 3 ⚠️ / 2 ❌ on first pass. Wave 7 first pass (1 ✅ / 3 ⚠️ / 1 ❌) is similar magnitude — within typical fresh-batch convergence.

---

## Aggregate Themes (recurring findings across the wave)

### 1. Phantom-attribute / phantom-API class (3 of 5 prompts affected)

The recurring Wave 6 phantom-API theme returns:

- **AD-456:** `SecretsManager` duplicates existing `CredentialStore` (AD-395 at `credential_store.py:32`). The prompt's verify-first footer didn't include `grep -n "CredentialStore"` — that single grep would have caught the duplication.
- **AD-528:** `EpisodicMemory.store(episode: Episode)` requires typed `Episode` dataclass. AD-528 passes a raw dict — runtime AttributeError.
- **AD-467:** `ResourcePool.active_count` is phantom. Live attribute is `current_size` (`pool.py:53`). Defensive `getattr(..., 0)` masks the bug — capacity reports always show `active=0`.
- **AD-463:** `LLMRequest.agent_id` is phantom — HebbianRouter integration is dead code; `getattr(request, "agent_id", "")` always returns `""`.

Pattern: when a prompt asserts "reads existing surface X.attr", the verify-first footer must include the grep that proves `X.attr` exists. Wave 7's drafting ran fast and skipped this discipline on 4 prompts.

**Recommendation for prompt-template hygiene:** before drafting the Verified Against Codebase footer, run a grep for every concrete attribute access in the implementation sections. Add the greps that confirm those attributes exist.

### 2. Hand-waved SEARCH/REPLACE blocks (1 of 5 prompts affected)

AD-463 Section 3 says "Builder must grep `complete()` body for the model-name resolution point and apply a minimal patch." This is the exact "Builder will figure out the anchor" pattern Wave 5 retrospective convention #6 forbids.

Concrete fix: replace the prose with a concrete SEARCH/REPLACE block at `_complete_inner` line 442-447 (verified live).

### 3. Footer line-number drift (5 of 5 prompts affected)

All 5 prompts' footers cite `runtime.emit_event` at line 775; actual is line 785 (verified). Off by 10. This is a Nit — not blocking — but indicates the footers were copy-pasted across prompts without re-grep.

**Recommendation:** the prompt template should treat footer greps as runtime-generated, not copy-pasted from sibling prompts.

### 4. No-theater discipline applied — except where overridden by Required findings

4 of 5 prompts cleanly applied Wave 5 retrospective convention #7. AD-463 needed special enforcement (HebbianRouter integration is theater per Required #1); resolution drops it from v1 wholesale.

The dispatch's pre-flagged concern about EgressPolicy (AD-456) being "theater dressed as deferral" is borderline — `EGRESS_BLOCKED` events fire under deny-by-default, so the surface produces real signal. Acceptable for v1.

### 5. Cross-AD dependencies cleanly documented

AD-467d LLM Cost Tracker explicitly waits on AD-463. AD-528 vs AD-451 orthogonality documented. AD-456 EXTENDS AD-455's `security/` package without modifying. ✅

---

## Required Findings — Per-Prompt Action

### AD-466 (✅ Approved — 0 Required)

No blocking changes. 4 Recommended findings are polish.

### AD-456 (❌ Not Ready — 3 Required)

| # | Finding | Action | Time |
|---|---|---|---|
| R#1 | `SecretsManager` duplicates `CredentialStore` | Pick: extend (a) / orthogonality (b) / defer (c). Recommended (a) | 25 min |
| R#2 | `ENV_PREFIX = "PROBOS_"` collides with mixed live convention | Resolves with R#1 | (in R#1) |
| R#3 | EgressPolicy / HttpFetchAgent integration not documented | Add 1-line AD-456b note in "What This Does NOT Change" | 2 min |

### AD-528 (⚠️ Conditional — 3 Required)

| # | Finding | Action | Time |
|---|---|---|---|
| R#1 | `EpisodicMemory.store()` requires `Episode` dataclass | Rewrite Section 2 to construct `Episode(...)` with verification metadata in `dag_summary` | 8 min |
| R#2 | `ALLOWED_EXCEPTIONS` entry for cognitive→workforce TYPE_CHECKING import | Add Section 7 spec for the test_layer_boundaries.py edit | 3 min |
| R#3 | `MemorySource` enum value selection | Builder grep step; recommend `source="direct"` for v1 | 2 min |

### AD-467 (⚠️ Conditional — 2 Required, 1 underlying cause)

| # | Finding | Action | Time |
|---|---|---|---|
| R#1 | `ResourcePool.active_count` phantom; live attr is `current_size` | Replace `active_count` with `current_size` in Section 2 (or use `to_dict()`) | 5 min |
| R#2 | Defensive `getattr(..., 0)` anti-pattern | Resolves with R#1 | (in R#1) |

### AD-463 (⚠️ Conditional — 3 Required)

| # | Finding | Action | Time |
|---|---|---|---|
| R#1 | `LLMRequest.agent_id` phantom; HebbianRouter integration is dead | Drop HebbianRouter from v1 (option b); defer to AD-463d | 15 min |
| R#2 | Section 3 SEARCH/REPLACE hand-waved | Provide concrete block at `_complete_inner` line 442-447 | 10 min |
| R#3 | `_resolve_model_for_tier` empty-string semantics | Docstring clarification | 2 min |

---

## Cross-Prompt Verifications

### Source-file overlap

All 5 prompts modify `events.py`, `config.py`, and `startup/finalize.py`. SEARCH anchors at distinct line neighborhoods. Section 5/6/7 fallback chains all terminate at AD-440 `orders: OrdersConfig` (config.py:1593). ✅

### EventType collisions

12 new EventTypes across the wave, all distinct:

```
AD-456: SECRET_ROTATED, EGRESS_BLOCKED, AUDIT_RECORDED
AD-463: MODEL_ROUTED, MODEL_FALLBACK
AD-466: BACKUP_COMPLETE, BACKUP_FAILED
AD-467: RESOURCE_ALLOCATED, TASK_SCHEDULED, WORKFLOW_STARTED
AD-528: VERIFICATION_PASSED, VERIFICATION_FAILED
```

All verified absent from `events.py`. ✅

### Public-attribute collisions

8 new public attributes verified non-overlapping:

```
AD-456: runtime.{secrets_manager, egress_policy, audit_log}
AD-463: runtime.{model_registry, model_router}
AD-466: runtime.{storage_backend, backup_service}
AD-528: runtime.{ground_truth_verifier, verification_episode_writer}
```

But: AD-456 R#1 may collapse `runtime.secrets_manager` if SecretsManager is folded into the existing `runtime.credential_store`. Net public-attribute count drops to 7. ✅

### Directory ownership

- AD-466 owns `src/probos/infrastructure/__init__.py` (verified does not exist)
- AD-467 owns `src/probos/agents/operations/__init__.py` (verified does not exist)
- AD-456 EXTENDS `src/probos/security/` (AD-455's package; explicitly does NOT touch `__init__.py`)
- AD-528 adds `src/probos/cognitive/ground_truth.py` (cognitive/ exists; no directory creation)
- AD-463 adds `src/probos/cognitive/{model_registry, model_router}.py` (cognitive/ exists; no directory creation)

✅ No conflicts.

### Wave-5 / Wave-6 convention coverage

| Convention | AD-466 | AD-456 | AD-528 | AD-467 | AD-463 |
|---|---|---|---|---|---|
| #1 Public-attribute wiring | ✅ | ⚠️ R#1 collision | ✅ | N/A | ⚠️ Rec#4 |
| #2 stdlib-only persistence | ✅ | ✅ | ✅ | ✅ | ✅ |
| #3 Coordinator-then-dispatch | ✅ | ✅ | ✅ | ✅ | ✅ |
| #4 Superset-filter discipline | ✅ | ✅ | ✅ | ✅ | ✅ |
| #5 init_phase signatures | ✅ | ✅ | ✅ | ✅ | ✅ |
| #6 Verify-first for anchors | ⚠️ Nit | ⚠️ R#1 | ⚠️ R#1 | ⚠️ R#1 | ⚠️ R#1+R#2 |
| #7 No-theater discipline | ✅ | ⚠️ R#1 | ✅ post-fix | ⚠️ R#1 | ⚠️ R#1 |
| Wave-6 TYPE_CHECKING | N/A | N/A | ⚠️ R#2 | N/A | ✅ |
| Wave-6 ASCII comments | ✅ | ✅ | ✅ | ✅ | ✅ |
| Wave-6 anchor-chain fallback | ✅ | ✅ | ✅ | ✅ | ✅ |

Convention #6 (verify-first for anchors) slipped on 4 of 5 prompts — same recurring pattern as Wave 6. The fix is mechanical: include the missing grep for every concrete attribute access.

---

## Hard-Stops Triggered

The dispatch enumerated 5 hard-stop conditions:

1. **Phantom API in prompt body** — TRIGGERED on 4 prompts (AD-456 SecretsManager, AD-528 Episode-as-dict, AD-467 active_count, AD-463 LLMRequest.agent_id). All resolvable mechanically, no scope expansion needed.
2. **AD-463 BaseLLMClient ABC changes required** — NOT TRIGGERED. The hook is on `OpenAICompatibleClient` only; ABC is unchanged.
3. **AD-456 EgressPolicy theater** — borderline, deemed acceptable. EGRESS_BLOCKED events fire under deny-by-default. Documented as intentional v1 surface.
4. **Cross-prompt source-file conflicts** — NOT TRIGGERED. Anchors are distinct.
5. **Section 0 EventType collisions** — NOT TRIGGERED. 12 new EventTypes all distinct.

---

## Recommended Build Readiness Order (after fixes)

1. **AD-466** — ✅ Approved as-is. Smallest blast radius. Owns `infrastructure/` directory creation.
2. **AD-456** — ⏸️ Requires architectural decision (extend CredentialStore vs orthogonal vs defer). After R#1 resolves, ship.
3. **AD-528** — ✅ After 15-min mechanical fix.
4. **AD-467** — ✅ After 10-min mechanical fix.
5. **AD-463** — ⚠️ After 30-min fix (Required #1 (b) drops HebbianRouter from v1; substantial scope reduction). Highest-risk foundation work; lands last.

---

## Architect Disposition

The 5 Wave 7 drafts are **actionable but require revision** before Builder dispatch. Same magnitude as Wave 5/6 first-pass review:

- Wave 5: 22 Required findings across 5 prompts (4.4/prompt)
- Wave 6: 18 Required findings across 5 prompts (3.6/prompt)
- **Wave 7: 11 Required findings across 5 prompts (2.2/prompt)**

Convergence is improving wave-over-wave. The Required findings cluster on a single recurring theme (verify-first for attribute access) — easily addressed with one revision pass.

**Recommended next step:** dispatch a single revision subagent for all 5 prompts in one pass, mirroring Wave 5/6 cadence. Total architect rework: **~60 minutes.** Required findings are concrete; no architectural decisions beyond the dispatching architect's authority needed.

After revision, dispatch a second-pass review. Wave 5/6 history shows fresh batches converge in 1–2 review iterations; Wave 7 should hit the same target.
