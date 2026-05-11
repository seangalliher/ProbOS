# WAVE 145 DISPATCH — DSL draft preview + revision cycle (AD-721d-1)

**Wave:** 145
**Mode:** main
**Depends on:** Wave 144 (AD-723 sensorium dispatch, shipped 2026-05-10).
**Builder required:** yes
**Issues to close:** [#541](https://github.com/seangalliher/ProbOS/issues/541) (AD-721d-1).
**Date:** 2026-05-10

---

## 1. Goal

Wave 145 closes the loop on the AD-721d agent-authored avatar pipeline. Today the Captain has only two affordances on a proposed DSL — **approve blind** or **reject**. There is no way to say *"close, but make the hair shorter."* Even though `propose_appearance(captain_note=...)` already accepts a 280-char revision hint at `src/probos/cognitive/cognitive_agent.py:3054`, no UI surfaces it and no server-side iteration counter exists.

AD-721d-1 adds:

1. **API** — `ProposeAppearanceRequest` gains optional `previous_dsl: dict | None`; `ProposeAppearanceResponse` gains `proposal_iteration: int` + `max_iterations: int`. New `DELETE /api/agent/{id}/appearance/proposal-history`. Iteration cap returns HTTP 429.
2. **Config** — `AvatarsConfig.max_proposal_iterations: int = 3` (validated 1 ≤ v ≤ 10).
3. **Server** — module-level in-memory history at `src/probos/avatars/proposal_history.py`. Per-agent iteration counter cleared on approve / DELETE.
4. **UI** — `CrewAvatarPopout` gains "Request revision" button + inline 280-char textarea + submit, plus a structured parametric description block with amber-tint diff highlighting on changed fields. At iteration cap, "Request revision" is disabled with a native tooltip.
5. **Audit** — three new `runtime.emit_event(...)` string keys: `appearance_proposal`, `appearance_approved`, `appearance_history_cleared`. No new `EventType` enum value (UX wave, not a substrate wave).

**Hard scope constraints (no Captain ruling needed — pre-applied):**

1. Re-use `captain_note` as the revision-note slot. **Do not add a parallel `revision_note` field.** The existing field plumbs through to the LLM unchanged; the semantic difference between "initial" and "revision" is carried by the presence of `previous_dsl` plus the iteration counter.
2. Use `runtime.emit_event(<string>, <payload>)` for audit. **Do not use `runtime.cognitive_journal.record(...)`** — that signature is LLM-call-shaped (`entry_id, prompt_tokens, completion_tokens, ...`, verified `cognitive/journal.py:360`) and is the wrong audit surface for UX events.
3. Module-level in-memory history. **Do not attach to runtime.** Avoids Phase-ordering risk (BF-259/260/261/262 lesson) — no `getattr(runtime, "appearance_proposal_history", None)` from earlier startup phases.
4. The AD-721d `_parse_appearance_dsl` security guards (size cap, YAML anchor/alias reject, depth guard) MUST still hold. v1 does NOT add a new parse path; `previous_dsl` is validated via `AvatarDSL.model_validate(...)` only.
5. No emoji in HXI. All new icons inline SVG, `strokeWidth={1.5}`, `strokeLinecap="round"`. (HXI Design Principle #3.)
6. No new top-level deps. UI uses a tiny client-side diff helper (~25 LOC).

---

## 2. Prior-work + license disposition

| Prior work / candidate | What we found at HEAD | Disposition |
|---|---|---|
| `propose_appearance(captain_note: str = "")` | Verified `cognitive_agent.py:3052-3054`. ≤ 280 char validator at line 3079-3083. `captain_note` already piped into the user message at line 3152-3154. | **Reuse verbatim.** AD-721d-1 does NOT touch the LLM-side prompt construction. |
| `_parse_appearance_dsl` security guards | Verified `cognitive_agent.py:3187-3234`. Size cap (16 KiB), YAML anchor/alias byte-level reject, depth guard (8), `yaml.safe_load` (no tag execution). | **Reuse verbatim.** Section 8 regression-test ensures these still hold after the API extension. |
| `ProposeAppearanceRequest` / `ProposeAppearanceResponse` / `SetAppearanceRequest` | Verified `api_models.py:267-289`. `ProposeAppearanceRequest.captain_note: str = ""` already in place. | **Extend** with `previous_dsl`, `proposal_iteration`, `max_iterations`. Additive — non-breaking. |
| `POST /{agent_id}/appearance/propose` + `PUT /{agent_id}/appearance` | Verified `routers/agents.py:389-491`. PUT writes `crew.appearance.dsl = dsl.model_dump()` via `profile_store`. | **Extend** propose with iteration logic + 429; extend PUT with history-clear + audit emit. **Bit-for-bit unchanged** for the JSON success path. |
| `runtime.emit_event(event, data)` | Verified `runtime.py:971`. Accepts `BaseEvent \| str \| EventType`. Used widely (trust, channels, dispatcher). | **Reuse.** String keys avoid `EventType` enum growth. |
| `CognitiveJournal.record(...)` | Verified `cognitive/journal.py:360`. Kw-only signature is LLM-call-shaped (entry_id, tokens, latency_ms). | **Deliberately NOT used.** Wrong shape for UX events. Documented in prompt as a phantom-API avoidance for the reviewer. |
| `CrewAvatarPopout` approval bar | Verified `ui/.../CrewAvatarPopout.tsx:225-290`. Existing approve/reject SVG glyphs, no emoji, matches HXI #3. | **Extend** with Request-revision affordance + structured parametric block + diff highlights. Existing approve/reject SVGs reused. |
| `AgentProfilePanel` design-button + popout instantiation | Verified `AgentProfilePanel.tsx:62,215-238,360-380`. State + POST handler + popout wiring already in place. | **Extend** state (previousDsl, proposalIteration, proposalMaxIterations) and the popout's prop bag. |
| UI diff helper | None exists at HEAD. | **Pattern absorption** — new file `ui/.../avatarDslDiff.ts` (~25 LOC, MIT-equivalent Apache 2.0 wrapper code). Zero new JS deps. |

**Top-level license posture:** Apache 2.0 stays Apache 2.0. **Zero new Python deps. Zero new JS deps.** No external code absorbed.

---

## 3. Engineering-principles checklist

Reviewer flags any miss as **Required**.

| Principle (`.github/copilot-instructions.md`) | Where it applies | Verifying deliverable |
|---|---|---|
| **Tier-2 log-and-degrade** | `runtime.emit_event` failure on any audit path | All three audit emits wrapped in `try/except Exception: logger.warning(...)`. Captain-visible flow (proposal returned, approval persisted, history cleared) MUST NOT be blocked by audit failure. |
| **Tier-3 propagate (security)** | `_parse_appearance_dsl` guards + `_avatars_feature_check` | Existing 503 / 422 / 422-on-malformed-DSL paths unchanged. New 429 (iteration cap) and 422-on-malformed-`previous_dsl` paths return structured `{reason, detail}` envelopes. |
| **Defense in depth** | Iteration cap at API AND UI | API returns 429 at iteration `> max_iterations`. UI ALSO disables "Request revision" at iteration `>= max_iterations`. Both layers enforce the same cap. |
| **DRY** | Iteration-count read | Single source of truth: `proposal_history.iteration_count(agent_id)`. Both the propose handler (gate check) and the response (`proposal_iteration` field) read from `proposal_history.append(...)`'s return value — no separate counter. |
| **SOLID — Single Responsibility** | `proposal_history.py` | Module exposes 5 functions (append / iteration_count / latest / clear / reset_all). No business logic; storage only. |
| **SOLID — Dependency Inversion** | Diff renderer | UI imports `diffAvatarDsl` from a separate file; the popout doesn't compute diffs inline. |
| **Cloud-Ready Storage** | `proposal_history` | Module-level dict for v1; signatures stable so a future commercial overlay can swap to redis-backed without changing call sites. Documented in the module docstring. |
| **Test isolation** | Python tests | `pytest.fixture(autouse=True)` calls `proposal_history.reset_all()` before AND after each test. No order-dependence (BF-255 lesson). |
| **No emoji in HXI** (HXI Design Principle #3) | UI surface | All new icons (curved-arrow revise glyph, paper-plane send glyph, color swatches) are inline `<svg>` with `strokeWidth={1.5}` and `strokeLinecap="round"`. Reviewer fails on any emoji literal in the diff. |
| **No private-attr access** | Server + UI wiring | All new code consumes public names. `runtime.emit_event` (public), `runtime.config.avatars` (public, gated by `_avatars_feature_check`), `proposal_history.*` (public functions). No `runtime._something` or `agent._private`. |
| **Async discipline** | Router handlers | All new code paths are sync inside async handlers (no new awaitable wiring). The LLM `await agent.propose_appearance(...)` path is unchanged. No `asyncio.ensure_future`, no fire-and-forget task without reference. The DELETE handler is sync inside async. |
| **Boundary tests** | Each new public method | `proposal_history.append/iteration_count/clear` have direct tests; the router endpoints have happy-path + 429 + 422 + 503 + per-agent-isolation tests. ≥ 12 Python total. |
| **No new top-level deps** | Whole wave | `pyproject.toml` and `ui/package.json` unchanged. Reviewer fails any dep-add diff. |
| **Test gates** | Whole wave | ≥ 12 Python (`tests/test_ad721d1_dsl_preview.py`), ≥ 5 vitest (`ui/src/__tests__/CrewAvatarPopout.{revision,diff}.test.tsx`). Full parallel gate passes: `pytest tests/ -q -n 4 --dist=loadfile`. |

---

## 4. Deliverables

| ID | Deliverable | File(s) | Verification |
|---|---|---|---|
| **D1** | Config field + validator | `src/probos/config.py` `AvatarsConfig` | `max_proposal_iterations: int = 3` plus `field_validator` enforcing 1 ≤ v ≤ 10. |
| **D2** | Proposal-history module | `src/probos/avatars/proposal_history.py` (new) | Module-level `_history: dict[str, list[ProposalEntry]]` behind a `threading.RLock`; 5 public functions; `__all__` exports. |
| **D3** | API model extensions | `src/probos/api_models.py` | `ProposeAppearanceRequest.previous_dsl: dict \| None = None`; `ProposeAppearanceResponse.proposal_iteration: int = 1` + `.max_iterations: int = 3`. |
| **D4** | Router — propose endpoint | `src/probos/routers/agents.py` | Iteration cap gate (429); `previous_dsl` shape validation (422); history append on success; `runtime.emit_event("appearance_proposal", ...)`. |
| **D5** | Router — PUT endpoint | `src/probos/routers/agents.py` | History clear on success; `runtime.emit_event("appearance_approved", ...)`. |
| **D6** | Router — DELETE endpoint | `src/probos/routers/agents.py` (new handler) | `DELETE /{agent_id}/appearance/proposal-history`; idempotent; emits `appearance_history_cleared`. |
| **D7** | UI diff helper | `ui/src/components/profile/avatarDslDiff.ts` (new) | `diffAvatarDsl(prev, curr): Set<string>` returning changed dotted paths. |
| **D8** | UI popout extension | `ui/src/components/profile/CrewAvatarPopout.tsx` | New props (`previousDsl`, `iteration`, `maxIterations`, `onRequestRevision`); structured parametric block with diff highlighting; revise / send inline SVG glyphs; 280-char counter; disabled-at-cap state. |
| **D9** | UI panel wiring | `ui/src/components/profile/AgentProfilePanel.tsx` | New state (`previousDsl`, `proposalIteration`, `proposalMaxIterations`); `onRequestRevision` callback; approve / reject callbacks updated to clear state + DELETE history. |
| **D10** | Python tests | `tests/test_ad721d1_dsl_preview.py` (new) | ≥ 12 cases per the prompt's test plan. `proposal_history.reset_all()` in autouse fixture. |
| **D11** | UI tests | `ui/src/__tests__/CrewAvatarPopout.revision.test.tsx` + `.diff.test.tsx` (new) | ≥ 5 cases combined per the prompt's test plan. |

---

## 5. Build order

Single commit. No staged AD split; no inter-AD pause. The prompt is structured so all sections in `prompts/ad-721d-1-dsl-preview.md` can be applied in order without cross-section dependencies — config first, then storage module, then API models, then router, then UI, then tests.

---

## 6. Test gates

| Stage | Command | Pass criterion |
|---|---|---|
| Focused gate (per-AD) | `pytest tests/test_ad721d1_dsl_preview.py -v -n 0` | All ≥ 12 cases pass. |
| UI gate | `cd ui && npx vitest run CrewAvatarPopout.revision CrewAvatarPopout.diff` | All ≥ 5 cases pass. |
| Full parallel gate | `pytest tests/ -q -n 4 --dist=loadfile` | Test count incremented by exactly the new tests; **zero regressions**. |
| HEAD inspection (post-build) | `git diff --numstat | sort -k2nr | head -5` | No tracked-file deletions ≥ 200 lines that the Builder did not author (working-tree-integrity check). |

---

## 7. Hard-stop conditions

| Condition | Action |
|---|---|
| `runtime.emit_event` accepts string keys differently than `BaseEvent | str | EventType` (signature drift since 2026-05-10 verification) | Surface immediately. Architect re-verifies; may need to wrap in a small adapter or add an EventType value. |
| `AvatarDSL.model_validate(previous_dsl_raw)` raises for shapes the LLM legitimately returns (e.g., extra forward-compat fields) | Surface. Architect decides whether to relax `model_config(extra="forbid")` or downgrade to a soft-check. v1 default: strict. |
| `proposal_history.reset_all()` is missing from the autouse fixture in any new test file | Block — order-dependence is a quarantine trigger. Builder fixes; no escalation. |
| New emoji literal anywhere in the UI diff | Block. Builder swaps to inline SVG. |
| New top-level dep in `pyproject.toml` or `ui/package.json` | Block. None expected; if Builder thinks one is needed, surface to Architect. |
| Test count regression in the parallel gate | Standard triage per `BUILDER-EXECUTION-PLAN.md` §"Hard-Stop Triage Rules" — rerun serially first, quarantine pre-existing rot, do not block on environmental flakes. |

---

## 8. Post-wave

| Task | Owner | When |
|---|---|---|
| Update `PROGRESS.md` (CLOSED entry + test-count bump) | Builder | On final commit. |
| Move #541 to Done on `docs/development/roadmap.md` | Builder | On final commit. |
| Append AD-721d-1 retrospective to `DECISIONS.md` | Architect | Post-merge. Captures: (a) `captain_note` reuse vs new `revision_note` field, (b) `emit_event` vs `cognitive_journal.record`, (c) module-level history vs runtime-attached. |
| Close #541 with retrospective comment | Architect | Post-merge. |
| Archive `prompts/ad-721d-1-dsl-preview.md` → `prompts/archive/` | Architect | Post-merge. |
| Archive `prompts/WAVE-145-DISPATCH.md` → `prompts/archive/` | Architect | Post-merge. |

---

## 9. Forward markers

Forward markers to file as GH issues after this wave merges:

### Forward marker A — AD-721d-2: Counselor-mediated revision

**Title:** AD-721d-2 — Counselor-mediated avatar revision (vs Captain-driven hint)

**Body:**
> AD-721d-1 (Wave 145) ships Captain-driven agent self-revision: the Captain types a 280-char hint, the agent re-proposes. This works for single-Captain mode but misses the Nooplex pattern of using a domain agent as a mediator.
>
> **Future scope:** route revision hints through the Counselor (or other domain-appropriate agent) so the Captain says "Counselor, Echo's avatar feels too formal — work with her on something warmer" and the Counselor handles the back-and-forth with the target agent's CognitiveAgent.
>
> Implementation sketch:
> - New intent: `mediate_appearance_revision(target_agent_id, captain_hint)`.
> - Counselor's `decide()` chain inspects the target agent's persisted DSL, formulates a Counselor-flavored revision hint, calls `propose_appearance` on the target.
> - Captain reviews the result as today.
> - Adds a "Counselor-mediated" toggle to the popout's "Request revision" panel.
>
> Out of scope until AD-721d-1 ships and operator-feedback confirms the Captain-driven flow is well-formed.

### Forward marker B — AD-721d-3: Visual preview before persistence

**Title:** AD-721d-3 — Visual avatar preview before DSL persistence (requires AD-721i renderer)

**Body:**
> AD-721d-1 (Wave 145) ships a parametric description preview — the Captain sees body type, hair, outfit, expression as structured text + color swatches, with diff highlights between iterations. The Captain does NOT see the rendered 3D avatar until AFTER approval (because rendering requires AD-721i's headless Blender pipeline, which is operator-installed).
>
> **Future scope:** wire a "preview render" path that runs the renderer on the in-memory proposed DSL (not the persisted one) and surfaces the result in the popout next to the parametric block. Requires AD-721i to ship first (operator brings the Blender binary).
>
> Out of scope until AD-721i + AD-722e (avatar-telemetry consumer migration) both ship.

### Forward marker C — AD-721d-4: Persistent proposal history

**Title:** AD-721d-4 — Persist avatar proposal history across runtime restarts

**Body:**
> AD-721d-1 (Wave 145) stores proposal history in a module-level `dict` for v1. Process restart drops in-flight iterations. For a single-operator personal-runtime this is fine — the Captain finishes a session, approves or rejects, then the restart is moot.
>
> **Future scope:** when a long-lived deployment needs to survive restarts mid-session, swap the in-memory dict for a SQLite-backed table (matching the existing `ProfileStore` JSON-blob pattern). The 5 public functions in `src/probos/avatars/proposal_history.py` are signature-stable specifically to make this swap drop-in.
>
> Out of scope until an operator surface complains. Commercial overlay candidate.

---

## 10. AD-numbering

| | |
|---|---|
| Current highest AD at start of Wave 145 | **AD-729** (verified `PROGRESS.md` line 10, 2026-05-10) |
| This wave's AD | **AD-721d-1** (already-issued sub-AD of AD-721d, GH #541) |
| AD-numbering risk | **None** — no new top-level AD allocated. |

Forward markers will be filed as GH issues without AD numbers; Architect allocates fresh AD numbers when each is picked up for build.
