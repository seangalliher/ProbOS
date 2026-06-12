# Epic AD-885 → AD-890: Skills & Tools Unification — the Capability Spine

**Status:** Architect verify-first review complete (2026-06-06) → revised → **ready for Builder.** All six GO (AD-890) / GO-WITH-FIX, fixes folded in. Forced build order: 885 → 886 → 887 → 888 → 889 → 890.
**Repo:** OSS (`d:\ProbOS`). This describes *how the product works* (capability assignment), not how it makes money.
**Highest committed AD at draft time: AD-884.** (BF-609 is the latest BF.) This epic reserves **AD-885 → AD-890** sequentially.
**Canonical design:** [`docs/development/skills-and-tools-architecture.md`](../docs/development/skills-and-tools-architecture.md).
**GitHub issues:** AD-885 [#849](https://github.com/seangalliher/ProbOS/issues/849) · AD-886 [#850](https://github.com/seangalliher/ProbOS/issues/850) · AD-887 [#851](https://github.com/seangalliher/ProbOS/issues/851) · AD-888 [#852](https://github.com/seangalliher/ProbOS/issues/852) · AD-889 [#853](https://github.com/seangalliher/ProbOS/issues/853) · AD-890 [#854](https://github.com/seangalliher/ProbOS/issues/854).

---

## Why this epic exists

Three unrelated things are all called a **"skill"**, and the capability
subsystems (ACM, Skill Library, Cognitive Skill Catalog, Tool Registry,
Role/Duty ontology) were each built in isolation. The pieces exist; the **edges
between them** were never wired. This epic finishes the wiring so the system
matches the authoritative model:

> An agent is assigned a **Role**; the Role defines a scope of **Duties/Processes**;
> performing a process exercises **Skills**; a Skill may require **Tools** to act.
> The **Tool Registry** and **Skill Library** are the masters; **ACM** is the
> assignment surface that binds them to a crew agent.

Read the canonical architecture doc before reviewing any AD below — it carries the
full diagram, the industry alignment (Claude Code / Copilot: legacy Python
self-mod "skills" are **tools**; `SKILL.md` files are **skills**), and the
AD-441c identity-axis precedent (crew = birth certificate / skills; tool agent =
`AssetTag` / tools).

---

## Binding rationale (applies to the whole epic)

- **Two-concept model.** A **Tool** is a deterministic capability the agent
  *invokes* (`ToolRegistry`). A **Skill** is a competency the agent *has* —
  developmental proficiency (AD-428) and/or cognitive instructions (AD-596).
- **No new "skill" species.** The legacy self-mod `Skill` is a **tool**, not a
  third skill kind. Bring the capability layer into agreement with the AD-441c
  identity layer, which already classifies its producer as inventory, not crew.
- **Traverse edges, don't invent them.** The spine is half-modelled already:
  `RoleTemplate.required_skills`, `SkillDefinition.preferred_tools`,
  `DutyDefinition.required_skills`. The work is making code traverse these.
- **Smallest blast radius first.** AD-885 (read-only lens) ships before any
  behavior change so the fragmentation is queryable while we converge.
- **Fail Fast → log-and-degrade.** Every cross-subsystem read is tier-2
  (`logger.debug/warning` + graceful fallback); a missing collaborator never
  raises into ACM, onboarding, or startup. Matches the existing
  `get_consolidated_profile` `hasattr`/`try` style.
- **BF-287 test discipline.** Use **real** fixtures at substrate/storage
  boundaries (real `ToolRegistry`, real `AgentSkillService` on a tmp DB, real
  `CognitiveSkillCatalog`). No MagicMock at the substrate boundary.
- **Every AD ends with:** "Verify all changes comply with the Engineering
  Principles in `.github/copilot-instructions.md`." One AD = one commit.

---

## AD-885 — ACM becomes the true single capability lens

**Issue:** [#849](https://github.com/seangalliher/ProbOS/issues/849)

**Problem.** [`ACM.get_consolidated_profile`](../src/probos/acm.py) (L277) aggregates
lifecycle, crew profile (AD-376), trust, earned agency (AD-357), AD-428 skills,
and episode count — but is **blind** to cognitive skills (AD-596), tool grants
(AD-423), and duties (AD-419). It cannot answer "what can this agent do, and
why?" across the whole spine.

**Change (read-only aggregation, additive).** In
[`acm.py`](../src/probos/acm.py), extend `get_consolidated_profile` with three new
blocks, each guarded `hasattr`/`try` exactly like blocks 5–6:

1. **Cognitive skills (AD-596).** If `runtime.cognitive_skill_catalog` is present,
   add `profile["cognitive_skills"] = [...]` from
   `catalog.get_descriptions()` (verify the exact return shape and adapt —
   `get_descriptions(...)` at [`skill_catalog.py`](../src/probos/cognitive/skill_catalog.py#L353)),
   plus `profile["cognitive_skill_count"]`.
2. **Tool grants (AD-423).** `runtime.tool_registry` is real ([`runtime.py`](../src/probos/runtime.py#L715)).
   Add `profile["tools"]` — the tool IDs this agent may use, computed by filtering
   `tool_registry.list_tools()` ([`tools/registry.py`](../src/probos/tools/registry.py#L147)) through
   `tool_registry.check_permission(agent_id, tool_id, ToolPermission.READ, agent_rank=<rank>, agent_department=<dept>)`
   (real signature [`registry.py`](../src/probos/tools/registry.py#L250):
   `check_permission(agent_id, tool_id, required, *, agent_department=None, agent_rank="ensign", agent_types=None)`).
   **Pass the agent's real `agent_rank`/`agent_department` from the crew identity
   already computed in block 2** — do NOT let it default to `"ensign"`/`None` or you
   compute ensign-level grants, not the agent's true rank-gated grants.
   Plus `profile["tool_count"]`.
3. **Duties — OMITTED in this AD (verify-first NO-SEAM).** There is **no public
   per-agent duty accessor**. `runtime.duty_schedule` is a `DutySchedule` scan-policy
   gate (`should_scan`/`next_scan_window`), **not** a per-agent lookup; the real
   `DutyScheduleTracker.get_due_duties(agent_type)` is **private** on
   `runtime.proactive_loop._duty_tracker` ([`proactive.py`](../src/probos/proactive.py#L384))
   and reaching it is a Law-of-Demeter violation; `runtime.duty_schedule_tracker` is
   aspirational/unshipped. **Do not add a duty block and do NOT reach into
   `_duty_tracker`.** Duties join the lens in a future AD that first ships a public
   `runtime.duty_schedule_tracker` property.

**Do not change.** The existing 6 blocks, the method signature, `acm.db` schema,
or any subsystem's own API. This AD only *reads*.

**Tests** (`tests/test_ad885_acm_unified_lens.py`, BF-287 real fixtures):
happy path with all three subsystems present populates the new keys; each
subsystem absent → its block omitted, no crash; tool block respects permission
filtering (a tool the agent lacks READ on is excluded); cognitive-skill count
matches catalog size. Existing ACM tests stay green.

**Acceptance:** new keys present when subsystems wired; fully backward-compatible
when not. Verify compliance with `.github/copilot-instructions.md`.

---

## AD-886 — Reclassify the legacy self-mod `Skill` as a Tool

**Issue:** [#850](https://github.com/seangalliher/ProbOS/issues/850)

**Problem.** The legacy `Skill` dataclass ([`types.py`](../src/probos/types.py#L733))
is a deterministic Python handler attached to a `SkillBasedAgent` — i.e. a
**tool** by every industry definition and by ProbOS's own AD-441c identity split.
It lives outside the `ToolRegistry`, so designed deterministic capabilities miss
persistence-of-record, permission resolution, and LOTO governance.

**Change.** When the self-mod pipeline produces a deterministic `Skill`, **also
register it into the `ToolRegistry`** as a tool. Verified facts (do not deviate):
- **Use `InfraServiceAdapter`, NOT `DeterministicFunctionAdapter`.** `Skill.handler`
  is an **async** callable ([`types.py`](../src/probos/types.py#L731)).
  `DeterministicFunctionAdapter.invoke` calls `self._handler(**params)`
  **synchronously** ([`adapters.py`](../src/probos/tools/adapters.py#L211)) → returns
  an un-awaited coroutine (silently broken). Register via
  `InfraServiceAdapter(intent_name=skill.name, intent_bus=runtime.intent_bus)` — it
  `await`s the bus and the skill is already bus-dispatched by `SkillBasedAgent`, so
  re-broadcast is correct. **Effective `tool_type = ToolType.INFRA_SERVICE`** (the
  adapter sets it at [`adapters.py`](../src/probos/tools/adapters.py#L55)); the
  earlier "UTILITY_AGENT/DETERMINISTIC_FUNCTION" framing was wrong — correct it.
- **Use `provider="designed"`, NOT `origin`.** `ToolRegistration` has
  `provider: str = ""` ([`protocol.py`](../src/probos/tools/protocol.py#L151)); there
  is **no** `origin` field. Mark `provider="designed"` to distinguish from built-in
  tools / AD-433 default grants.
- **Inject a `register_tool_fn` callback into the pipeline (connective tissue).**
  `SelfModificationPipeline.__init__` ([`self_mod.py`](../src/probos/cognitive/self_mod.py#L63))
  takes `register_fn`/`add_skill_fn` but has **no** tool-registry handle. The
  registration site is `handle_add_skill` ([`self_mod.py`](../src/probos/cognitive/self_mod.py#L570))
  where `Skill(...)` is built and attached via `_add_skill_fn`. Add an optional
  `register_tool_fn` constructor callback (mirror the existing callback-injection
  pattern), call it right after `_add_skill_fn`, and wire it from runtime to
  `runtime.tool_registry.register(...)`. A `None` callback is a no-op (degrade).

Keep the existing `SkillBasedAgent` dispatch working (the `Skill` object stays the
runtime handler via `_skills`/`add_skill` at
[`skill_agent.py`](../src/probos/substrate/skill_agent.py#L30)) — this AD **adds** a
ToolRegistry registration alongside it; it does not delete the dispatch path.

**Naming decision (Captain's call — default in this draft).** Keep the `Skill`
*class name* for now and add the ToolRegistry registration with a doc note (lower
blast radius). A hard rename `Skill → DesignedTool` is deferred to a future AD if
it earns it. *(If the Captain prefers the rename now, fold it in here and update
`types.py` + self-mod + tests.)*

**Do not change.** `SkillDefinition` (AD-428) — that is a *skill*, untouched. The
`CognitiveSkillCatalog`. The decomposer's intent routing.

**Tests** (`tests/test_ad886_selfmod_tool_registration.py`, real `ToolRegistry`):
a designed deterministic `Skill` appears in `tool_registry.list_tools()` with
`provider="designed"` and `tool_type == ToolType.INFRA_SERVICE`; it is invocable
(awaitable) through the `InfraServiceAdapter`; a `None` `register_tool_fn` is a
clean no-op; the existing `SkillBasedAgent` dispatch still handles its intent.
Self-mod tests stay green.

**Acceptance:** designed deterministic capabilities are first-class tools.
Verify compliance with `.github/copilot-instructions.md`.

---

## AD-887 — One Skill Library master

**Issue:** [#851](https://github.com/seangalliher/ProbOS/issues/851)

**Problem.** AD-428 `SkillRegistry`/`AgentSkillService` (developmental) and AD-596
`CognitiveSkillCatalog` (instruction files) are two stores. AD-596c bridges
catalog → registry but they are still queried separately, so "what skills does
this agent have?" has two answers.

**Change.** Make a single call report both skill kinds. Verified facts:
- The AD-596c bridge is **`SkillBridge(catalog, skill_service)`** in
  [`cognitive/skill_bridge.py`](../src/probos/cognitive/skill_bridge.py#L22)
  (holds `_catalog` = T2 cognitive and `_service` = T3 developmental), wired as
  `runtime.skill_bridge` ([`runtime.py`](../src/probos/runtime.py#L2217)). **It is
  NOT in `skill_catalog.py`** — build on `SkillBridge`.
- Today `SkillProfile{agent_id, pccs, role_skills, acquired_skills}`
  ([`skill_framework.py`](../src/probos/skill_framework.py#L612)) is **all
  developmental** `AgentSkillRecord`s — there is **no** `cognitive_skills` field and
  `AgentSkillService.get_profile` (T3-only, [`skill_framework.py`](../src/probos/skill_framework.py#L1371))
  never consults `_catalog`. Keep `AgentSkillService` **T3-pure**.
- Add a `cognitive_skills` field to `SkillProfile` (default empty) and add a
  **`SkillBridge` method** (e.g. `get_unified_profile(agent_id)`) that calls
  `_service.get_profile(agent_id)` and merges the agent's cognitive entries from
  `_catalog`, tagging each with its kind (`developmental` vs `cognitive`). The
  merge site is the bridge — not the service, not the catalog. No `skills.db`
  schema change (cognitive kind is derived, not stored).

**Do not change.** The `SKILL.md` on-disk format, progressive-disclosure loading
(`get_instructions`/`find_by_intent` stay as the runtime context-injection path),
or the developmental proficiency math.

**Tests** (`tests/test_ad887_skill_library_unification.py`, real
`AgentSkillService` on tmp DB + real `SkillBridge` + real catalog): an agent with
both a developmental skill and a cognitive catalog entry reports both through
`SkillBridge.get_unified_profile`, each tagged with its kind; cognitive-only and
developmental-only agents both resolve; `AgentSkillService.get_profile` stays
T3-only (unchanged). AD-428 and AD-596 suites stay green.

**Acceptance:** one query surface, two skill kinds. Verify compliance with
`.github/copilot-instructions.md`.

---

## AD-888 — Skill→Tool binding (finish the orphaned resolver)

**Issue:** [#852](https://github.com/seangalliher/ProbOS/issues/852)

**Problem.** `SkillDefinition.preferred_tools: list[ToolPreference]` exists
([`skill_framework.py`](../src/probos/skill_framework.py#L573), with SQLite
migration) but **nothing resolves it** — there is no path from "exercise skill X"
to "invoke the tool that fulfils it." This is Part 4 of the orphaned
[`unified-tool-layer.md`](../docs/development/unified-tool-layer.md).

**Change.** Add a pure, side-effect-free resolver (new small module, e.g.
`src/probos/tools/skill_tool_resolver.py`, or a method on `ToolRegistry` —
prefer the standalone service for Dependency Inversion):
`resolve_tools_for_skill(skill: SkillDefinition, *, agent_id, tool_registry, hebbian=None) -> list[ToolRegistration]`.
Resolution order:
1. Honour `skill.preferred_tools` priority order; keep only tools the agent has
   permission for (`tool_registry.check_permission`).
2. Fallback: capability-tag discovery via
   `tool_registry.list_tools(tag=...)` when no preferred tool is available.
3. **Hebbian is a documented no-op for now (verified type mismatch).** The real
   ranking primitive is `HebbianRouter.get_preferred_targets(source, candidates, rel_type=None, hint=None) -> list[AgentID]`
   ([`mesh/routing.py`](../src/probos/mesh/routing.py#L261)) — it ranks **agent→agent**
   compat (`REL_AGENT`). There are **no agent→tool edges** in the Hebbian graph, so
   there is nothing to rank tools by today. Keep the optional `hebbian` param in the
   signature but treat it as a **no-op** (rank purely by `ToolPreference.priority`,
   lower = higher) and add a `# TODO` noting it activates once agent→tool edges
   exist. The resolver must work with `hebbian=None`.

**Do not change.** The `ToolPreference`/`preferred_tools` schema, the agentic
executor (AD-543–549), or consensus gating. This AD only *resolves*; it does not
auto-invoke.

**Tests** (`tests/test_ad888_skill_tool_resolver.py`, real `ToolRegistry` +
`SkillDefinition`): preferred tool returned first (by `priority`);
permission-denied preferred tool skipped; tag-fallback when no preferred tool; a
provided `hebbian` does not change ordering (documented no-op); empty result is a
clean `[]`, never a raise.

**Acceptance:** a skill resolves to the tool(s) that fulfil it. Verify compliance
with `.github/copilot-instructions.md`.

---

## AD-889 — ACM assignment chain: Role → Skills → Tools (capstone)

**Issue:** [#853](https://github.com/seangalliher/ProbOS/issues/853)
**Hard dependency: AD-888 must ship first** (Role→Tools flows *through* the skill
resolver — see step 2). Forced order in this epic: 888 → 889.

**Problem.** `AgentSkillService.commission_agent` ([`skill_framework.py`](../src/probos/skill_framework.py#L1238))
assigns skills from a **hardcoded `ROLE_SKILL_TEMPLATES` dict** (L1254), not the
ontology `RoleTemplate`. Tools are never granted from skills. The spine is never
traversed end-to-end. **This is the capstone.**

**Change.** Make commissioning walk the real chain. Verified facts:
1. **Role → Skills.** Read
   `VesselOntologyService.get_role_template_for_agent(agent_type) -> RoleTemplate|None`
   ([`ontology/service.py`](../src/probos/ontology/service.py#L210));
   `RoleTemplate.required_skills: list[SkillRequirement]` with
   `SkillRequirement{skill_id, min_proficiency:int}` ([`ontology/models.py`](../src/probos/ontology/models.py#L74)).
   Acquire each `skill_id` at its `min_proficiency` — **convert the raw int (1–7)
   to `ProficiencyLevel`** (today commission acquires at `FOLLOW`). Fall back to the
   legacy `ROLE_SKILL_TEMPLATES` dict when the ontology has no template:
   `(ont.get_role_template_for_agent(t) if ont else None) or legacy`. PCC
   acquisition unchanged.
2. **Skills → Tools (this is why 888 is a hard dep).** `RoleTemplate` carries
   **skills only** — no tools. For each acquired skill, resolve tools via the AD-888
   `resolve_tools_for_skill` resolver, then **grant** each via the real API:
   `runtime.tool_permission_store.issue_grant(agent_id, tool_id, permission, *, is_restriction=False, reason="", issued_by="captain", expires_at=None) -> ToolAccessGrant`
   ([`tools/permissions.py`](../src/probos/tools/permissions.py#L110); accessor
   `getattr(runtime,"tool_permission_store",None)`). Honest-degrade if the store is
   absent.
3. **NO Duties step (verify-first NO-SEAM).** There is **no per-agent
   duty-registration API** in `src/`. Duties are config-schedule-driven per
   `agent_type` via the private `DutyScheduleTracker`, which auto-emits due duties
   by type — commissioning neither can nor should "register" duties. **Drop the
   Duties step entirely.** (A future AD may add a public duty-assignment API.)

**Wiring — the unification must not be inert (load-bearing).** `commission_agent`
is currently called from **exactly one place**: the manual `/skills` endpoint
(`runtime.skill_service.commission_agent(...)`, [`routers/skills.py`](../src/probos/routers/skills.py#L58)).
`agent_onboarding.py` only **reads/caches** a profile (`skill_bridge._service.get_profile`,
read-only, ~L177) — it never commissions. The prompt's earlier "onboarding
callers" assumption was wrong. **Builder must (a) find the real agent birth/
onboarding path and wire the new commission front door into it so crew agents are
commissioned at creation, OR (b) if no safe birth hook exists this AD, scope AD-889
to build + unit-test the composed `ACM.commission(agent_id, agent_type, runtime)`
front door and re-point the `/skills` endpoint to it, explicitly deferring the
birth-path wiring to a named follow-up AD.** Do NOT claim end-to-end unification
if nothing commissions at birth.

Prefer composing the orchestration in an **ACM method**
`ACM.commission(agent_id, agent_type, runtime)` (skills + resolver + tool grants),
keeping `skill_framework` skill-focused (Single Responsibility).

**Do not change.** The skill prerequisite checks, idempotency of
`commission_agent` (re-commission must stay safe), or the AD-433 default tool
grants for non-crew agents.

**Tests** (`tests/test_ad889_commission_chain.py`, real `AgentSkillService` +
real `ToolPermissionStore` + real ontology): commissioning an agent whose role has
a `RoleTemplate` acquires the template's skills at the right `ProficiencyLevel` and
grants the tools those skills prefer (via the AD-888 resolver); an agent type with
no ontology template falls back to the legacy dict; re-commission is idempotent; an
agent whose skill has no preferred tool commissions cleanly; a missing
`tool_permission_store` degrades without raising. AD-428 commissioning tests stay
green.

**Acceptance:** one commission call walks Role → Skills → Tools, and the front
door is wired into the real birth path (or explicitly deferred per the wiring
note). Verify compliance with `.github/copilot-instructions.md`.

---

## AD-890 — Supersede the stale capability docs

**Issue:** [#854](https://github.com/seangalliher/ProbOS/issues/854)

**Problem.** [`unified-tool-layer.md`](../docs/development/unified-tool-layer.md)
titles itself "AD-543: Unified Tool Layer," but AD-543 was consumed by the Native
SWE Harness ([`tools/executor.py`](../src/probos/tools/executor.py)). The doc's
skill→tool design is now orphaned and contradicts the shipped AD-543, confusing
every future reader.

**Change (docs only — no code).**
1. Add a header banner to `unified-tool-layer.md`: **SUPERSEDED** — its AD-543
   number is a collision (AD-543 shipped as the Native SWE Harness Tool Execution
   Abstraction / `tools/executor.py`); its skill→tool design landed as **AD-888**;
   point readers **primarily** to the canonical
   [`skills-and-tools-architecture.md`](../docs/development/skills-and-tools-architecture.md).
2. Add a one-line "Canonical: see skills-and-tools-architecture.md" pointer to
   the top of [`crew-capability-architecture.md`](../docs/research/crew-capability-architecture.md).
3. Confirm the AD-543 number-collision fact is already recorded in the canonical
   doc's history note (it is — [`skills-and-tools-architecture.md`](../docs/development/skills-and-tools-architecture.md) L198/235).

**Do not change.** Any source code, any test, any other doc.

**Tests.** None (docs-only) — but the epic's final step runs the full serial gate
to confirm AD-885→889 left the suite green.

**Acceptance:** no future reader is misled by the AD-543 collision. Verify
compliance with `.github/copilot-instructions.md`.

---

## Epic-level acceptance

- AD-885→889 each ship as one commit, full serial gate green after each
  (`d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 0 -p no:cacheprovider`).
- After AD-889, a single commissioning call demonstrably walks Role → Skills →
  Tools on a real ontology-backed agent type (the capstone end-to-end test).
- `PROGRESS.md` top banner updated per AD (Wave N), `DECISIONS.md` AD-885→890
  appended newest-first under "## Era V — Civilization."
- **Do not build in this epic:** PSA/ASA financials (commercial), a new skill
  *kind*, federation routing for tools, a hard `Skill→DesignedTool` rename
  (deferred unless the Captain opts in at AD-886), auto-invocation of resolved
  tools (AD-888 resolves only), a per-agent **duty-registration/accessor API**
  (no seam exists — dropped from AD-885's lens and AD-889's chain; future AD), or
  agent→tool Hebbian edges (AD-888's `hebbian` param stays a no-op).
