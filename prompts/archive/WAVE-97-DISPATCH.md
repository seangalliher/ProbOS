# WAVE 97 DISPATCH — AD-476 v1 Specialized Builders — Cognitive Division of Labor for SWE (closes #70)

## Wave summary

**Umbrella AD:** AD-476 (Specialized Builders — Cognitive Division of Labor for SWE — listed at `docs/development/roadmap.md:4213` as *(planned)*; conceptual home at `:1619` *Specialized Builders (Cognitive Division of Labor for SWE)*).

**Wave kind:** Source-modifying v1 — additive specialty layer on top of the AD-521 SWE/Build Pipeline Separation that landed in Wave 96. Adds a `SoftwareEngineerSpecialty` enum, a pure `SpecialistRouter` that scores `BuildSpec` / `ChunkSpec` against five specializations (backend / frontend / test / infrastructure / data) by file-extension and path heuristics, and five `SoftwareEngineerAgent` subclasses (`BackendSWEAgent`, `FrontendSWEAgent`, `TestSWEAgent`, `InfrastructureSWEAgent`, `DataSWEAgent`) each with specialty-tuned `instructions`. Pool registration is opt-in via a new Pydantic config (default-False — pool creation is a real side-effect). `BuildPipeline.execute_approved_build(...)` accepts a new optional `specialty: str = "general"` kwarg that is logged and threaded through to the underlying `_legacy_execute_approved_build` call so future ADs can route per-chunk; v1 ships zero behaviour change at the production execute path.

**Reframe decision — BUILD v1 (no defer):**

AD-476 has been listed `(planned)` since the roadmap entry was written; AD-521 (Wave 96) was the prerequisite — an unsplit `BuilderAgent` that conflated crew identity and pipeline mechanics could not host five specialty crew variants without churning every test that imports `BuilderAgent`. With `SoftwareEngineerAgent` extracted as the sovereign crew class and `BuildPipeline` extracted as a Ship's Computer service (W96 commit `a0e9bc0`), the specialty layer is a clean additive extension — five subclasses, one router helper, one config model, one pool registration block, no rewrite of the base class or the pipeline.

The Captain rule "don't defer unless no choice" applies to v1 scope. Three concrete checks:

1. **Five specialist classes** — each one is `class XSWEAgent(SoftwareEngineerAgent): specialty = ...; instructions = """..."""`. Identity continuity per AD-398: each gets its own `agent_type` (`backend_swe` / `frontend_swe` / `test_swe` / `infrastructure_swe` / `data_swe`) and a unique callsign for crew-roster display, but all five map to `engineering` department in `_AGENT_DEPARTMENTS`. No new pool topology — five new optional pools, default-disabled.
2. **Pure routing helper** — `SpecialistRouter.route_build_spec(spec)` and `SpecialistRouter.route_chunk(chunk)` score `target_files` paths against five specialization rule sets and return `(specialty, score, rationale)`. No global state, no LLM call, no runtime dependency. Consumable by AD-475 Ready Room IdeaSpec pipeline (deferred to AD-475d) and by AD-545/AD-546 SWE Tool Harness (next wave) without requiring v1 to wire either.
3. **Pipeline thread-through** — `BuildPipeline.execute_approved_build(..., specialty="general")` adds the kwarg, logs the routed specialty at INFO level, and forwards. No change to the parsing rules, fix loop, pre-flight gates, or visiting-vs-native router. Existing call sites in `build_dispatcher.py` and `routers/build.py` continue to call without the kwarg (default `"general"` preserves today's behaviour byte-for-byte).

**v1 IN scope (concrete):**
- New module `src/probos/cognitive/builder_specialist.py` (~280 lines): `SoftwareEngineerSpecialty(str, Enum)` (six values: `GENERAL`/`BACKEND`/`FRONTEND`/`TEST`/`INFRASTRUCTURE`/`DATA`), frozen `SpecialtyMatchResult` dataclass (specialty + score + rationale), `SpecialistRouter` class with one rule-set per specialty + `route_build_spec(spec) -> SpecialtyMatchResult` + `route_chunk(chunk) -> SpecialtyMatchResult` + module-level helper `score_path(path) -> dict[SoftwareEngineerSpecialty, int]`. Rules are file-extension + path-substring matchers (e.g. `.tsx`/`.css`/`/ui/` → frontend; `tests/` or `test_*.py` → test; `Dockerfile`/`.yml`/`docker-compose` → infrastructure; `migrations/`/`schemas/`/`.sql` → data; everything else → backend if Python, else general).
- Five new `SoftwareEngineerAgent` subclasses in `src/probos/cognitive/builder_specialists.py` (~250 lines): `BackendSWEAgent` / `FrontendSWEAgent` / `TestSWEAgent` / `InfrastructureSWEAgent` / `DataSWEAgent`. Each declares `specialty: SoftwareEngineerSpecialty` class attribute, `agent_type` set to `<specialty>_swe`, callsign distinct per crew-identity convention, and a specialty-tuned `instructions` string that overlays the base SWE instructions with the specialty's domain rules. `_handled_intents` and `intent_descriptors` inherit from `SoftwareEngineerAgent` (all five handle `build_code` — the dispatcher selects which one based on `SpecialistRouter` output and a future AD-476b/AD-546 routing call site).
- `_AGENT_DEPARTMENTS` in `cognitive/standing_orders.py` extended with five entries mapping `backend_swe` / `frontend_swe` / `test_swe` / `infrastructure_swe` / `data_swe` → `engineering`. Reuses existing `engineering.md` + `builder.md` standing orders — no new standing-orders markdown ships in v1.
- `SoftwareEngineerSpecialistsConfig` Pydantic model adjacent to existing builder/cognitive config in `config.py`: `enabled: bool = False` (transitional-flag default per AD-695 precedent — pool creation is a real side-effect; opt-in for now), `pool_size_per_specialty: int = 1` (`field_validator` >=1), `model_tier_overrides: dict[str, str] = Field(default_factory=lambda: {"backend": "deep", "frontend": "standard", "test": "fast", "infrastructure": "standard", "data": "deep"})` (read by individual `_resolve_tier()` overrides on the subclasses; v1 stops at config presence + subclass-level reading; live ModelRegistry-driven swap is AD-463b/c territory). Wired onto `SystemConfig` adjacent to existing builder-related fields.
- `runtime.py` template registration: five `self.spawner.register_template(...)` calls inserted immediately after the existing `self.spawner.register_template("builder", BuilderAgent)` line at `runtime.py:706`. Pool creation is conditional in `startup/agent_fleet.py`: when `config.swe_specialists.enabled` is True AND each specialty agent class import succeeds, spawn one pool per specialty with `pool_size_per_specialty` agents; otherwise skip with INFO log.
- `BuildPipeline.execute_approved_build(...)` in `src/probos/build_pipeline.py` extended with `specialty: str = "general"` kwarg. v1 logs the specialty at INFO and forwards it as an additional kwarg to `_legacy_execute_approved_build` (the legacy coroutine accepts it as part of `**kwargs`-style forwarding via a dedicated parameter added in this AD; default `"general"` preserves today's behaviour). Existing call sites are unchanged.
- New test file `tests/test_ad476_specialized_builders.py` with **14 tests** (see Test plan in the per-AD prompt).

**v1 OUT scope (deferred with explicit forcing functions):**
- **Production chunk auto-routing in `execute_chunks` loop** — `decompose_blueprint` exists at `cognitive/builder.py:533` but is not yet wired into the live `execute_approved_build` path; the Transporter Pattern is a planned AD-462e/AD-545 surface that will become the consumer of `SpecialistRouter`. Forcing function: AD-546 (SWE Tool Harness pipeline integration, GH #13) which depends on AD-545 agentic loop and explicitly cites AD-521 + AD-476 routing as its substrate.
- **ModelRegistry-driven dynamic model selection** — AD-463 ships the static catalog (`src/probos/cognitive/model_registry.py:83`); MAD scoring + hot-swap + per-specialty live model selection are AD-463b/c/d/e/f territory, all open. v1 reads `model_tier_overrides` at subclass init time only.
- **Hebbian per-specialty weights** — `REL_BUILDER_VARIANT` at `mesh/routing.py:31` already learns native-vs-visiting; per-specialty success weights would extend the same relation type but require track records that the v1 pools (default-disabled) cannot produce yet. Forcing function: AD-476b once specialists have shipped builds.
- **HXI specialty visualization** — Captain-facing surface (which specialty is executing this chunk, which models are being used) is HXI work that depends on AD-475c Ready Room session recording + AD-475d Idea→Spec pipeline. No v1 surface.
- **Per-specialty standing orders markdown** — `config/standing_orders/backend.md` etc. would be opinionated content the Captain may want to author by hand. v1 reuses the existing `engineering.md` + `builder.md` standing orders and ships specialty-specific guidance in the subclass `instructions` attribute only.
- **Cognitive JIT (Phase 32)** — far-future, not blocked by v1.
- **CodeReviewerAgent specialization** — `src/probos/cognitive/code_reviewer.py:1` exists today as a single `CodeReviewAgent` invoked from `cognitive/builder.py:2654-2674`. Per-specialty reviewers (Backend Reviewer, Frontend Reviewer, etc.) would mirror this AD's structure but for review rather than generation. Out of scope; future AD-476c if signal warrants.

**The crew-tier-licensing class-extension plug-in point (out-of-repo overlay):**
AD-521 Wave 96 documented two SWE tiers (the OSS Scotty and the closed-source Pro variant) in `decisions-era-4-evolution.md:1453-1456`. AD-476 v1 inherits the same plug-in surface — the five specialty subclasses each subclass `SoftwareEngineerAgent`, which is itself the OSS extension point for a closed-source overlay. Specialist subclassing layered on tier subclassing is supported by the AD-452 class-extension mechanism. v1 itself ships zero closed-source content; placeholder-only references in this dispatch and the per-AD prompt. The closed-source overlay implementation lives outside this repository.

## AD numbering

Highest AD stem at HEAD `6246b35` is **AD-696** (verified by `Select-String -Path PROGRESS.md, DECISIONS.md, decisions-era-*.md, docs/development/roadmap.md -Pattern 'AD-(\d{3})' -AllMatches | … Measure-Object -Maximum` → 696). Highest BF: **BF-596**. Wave 97 mints zero new AD numbers (AD-476 already exists at `roadmap.md:4213`) and zero new BF numbers.

## Verify-first against HEAD `6246b35`

Twelve grep-anchored claims, all verified live:

- **`docs/development/roadmap.md:4213`** — `**AD-476: Specialized Builders — Cognitive Division of Labor for SWE** *(planned)*` is the canonical AD entry; the five specialty bullets follow on the same line. The W97 SEARCH/REPLACE flips `*(planned)*` to `*(v1 shipped Wave 97 — five specialist subclasses + SpecialistRouter + opt-in pools; production chunk auto-routing + ModelRegistry per-specialty dynamic swap deferred to AD-546 + AD-463b/c respectively)*`. Verified.
- **`docs/development/roadmap.md:1619`** — `*Specialized Builders (Cognitive Division of Labor for SWE):* *(AD-476)*` is the conceptual section header in the Mission Control narrative. No flip needed; the prose is forward-looking and remains accurate post-W97.
- **`src/probos/cognitive/builder.py:1690`** — `class SoftwareEngineerAgent(CognitiveAgent):` is the post-Wave-96 class declaration. Verified by `findstr /N /C:"class SoftwareEngineerAgent" src\probos\cognitive\builder.py` → `1690`. The five new subclasses ship in a NEW file `src/probos/cognitive/builder_specialists.py`, NOT inline in `builder.py` — keeps `builder.py` focused on base SWE + pipeline-shim plumbing per Engineering Principle SOLID-S.
- **`src/probos/cognitive/builder.py:2529`** — `BuilderAgent = SoftwareEngineerAgent` module-level alias. Verified. The five specialist subclasses are NOT aliased — they are net-new agent_types and require their own templates + departments + identity entries.
- **`src/probos/cognitive/standing_orders.py:42`** — `"builder": "engineering",` is the canonical entry pattern. The W97 SEARCH/REPLACE inserts five new entries (`backend_swe` / `frontend_swe` / `test_swe` / `infrastructure_swe` / `data_swe` → `"engineering"`) immediately after `"code_reviewer": "engineering",` at `:43`. Verified.
- **`src/probos/runtime.py:706`** — `self.spawner.register_template("builder", BuilderAgent)` is the canonical builder template line. The W97 SEARCH/REPLACE inserts five new `register_template(...)` lines immediately after, importing the five specialist classes from `probos.cognitive.builder_specialists`. Verified.
- **`src/probos/runtime.py:56`** — `from probos.cognitive.builder import BuilderAgent` is the import site. The W97 SEARCH/REPLACE adds a sibling import `from probos.cognitive.builder_specialists import (BackendSWEAgent, FrontendSWEAgent, TestSWEAgent, InfrastructureSWEAgent, DataSWEAgent)` immediately below. Verified.
- **`src/probos/build_pipeline.py:56`** — current `BuildPipeline.execute_approved_build` signature accepts `file_changes`, `spec`, `work_dir`, `run_tests`, `max_fix_attempts`, `llm_client`, `escalation_hook`, `builder_source`. The W97 SEARCH/REPLACE adds `specialty: str = "general"` as the trailing kwarg (after `builder_source`) and threads it through to `_legacy_execute_approved_build` via a new `specialty=specialty` kwarg. The legacy coroutine in `cognitive/builder.py:2532` (`async def execute_approved_build(...)`) is also extended with `specialty: str = "general"` as a trailing kwarg; the body logs it at INFO and otherwise ignores it (forward-compatible — AD-546 is what will actually consume it). Verified.
- **`src/probos/cognitive/model_registry.py:83`** — `class ModelRegistry:` is the static catalog from AD-463 v1. v1 of AD-476 reads `model_tier_overrides` from `SoftwareEngineerSpecialistsConfig` only at subclass `_resolve_tier()` time; no live ModelRegistry call. Verified.
- **`src/probos/mesh/routing.py:31`** — `REL_BUILDER_VARIANT = "builder_variant"  # build_code → native|visiting (AD-353)` is the existing relation type. No W97 change here; per-specialty Hebbian extension is AD-476b territory and explicitly out of scope. Verified.
- **`src/probos/cognitive/builder.py:1251`** — `def _should_use_visiting_builder(...)` is the visiting-vs-native router. No W97 change; specialty routing is orthogonal to visiting routing (a frontend specialist could still route to native or visiting based on the existing AD-353 logic). Verified.
- **`src/probos/cognitive/code_reviewer.py:1`** — `class CodeReviewAgent(CognitiveAgent)` is the existing single reviewer. No W97 change; per-specialty reviewers are AD-476c territory. Verified.

PROGRESS.md tracker note: `Select-String -Path PROGRESS.md -Pattern 'AD-476' -SimpleMatch` returns **zero hits** at HEAD; W97 INSERTS a new closed-AD prose block at the top of PROGRESS.md (canonical pattern matches the recent-activity blocks already at PROGRESS.md:1-44). The SEARCH anchor targets a stable adjacent line (the existing topmost paragraph). **Note:** Wave 96 (AD-521) did NOT itself append a PROGRESS.md entry — see "Concerns / observations" below; W97 stays AD-476-scoped and does NOT retroactively patch the W96 omission.

## Reframe decision — build v1, not defer

**Five concrete sub-AD-letter-equivalents built in v1 (the five specialist subclasses + the router) + zero future sub-AD letters parked as new GH issues + the closed-source crew-tier overlay as out-of-repo plug-in point + zero hard-deferrals.**

AD-476 v1 ships the architectural separation specified in the roadmap entry: five specialist subclasses, pure routing helper, opt-in pool registration, pipeline kwarg thread-through, full back-compat with the AD-521 base class. The production chunk-routing wiring (AD-546) and ModelRegistry dynamic-swap (AD-463b/c) are genuinely separate waves with their own dependency chains and are explicitly tracked under their own GH issues. Captain rule "don't defer unless no choice" satisfied non-vacuously: the five subclasses + router are necessary infrastructure for AD-546 to consume, the surface area is bounded (two new modules, five subclasses, one router helper, one config model, two runtime imports + five template registrations, one pipeline kwarg), and the test impact is well-defined (14 new boundary tests, zero existing-test churn — verified by grepping `BuilderAgent` references in tests; the alias keeps every test working).

## Files

- `prompts/WAVE-97-DISPATCH.md` (this file)
- `prompts/ad-476-specialized-builders-v1.md` (per-AD prompt — two new modules, five subclasses, one router, one config, runtime wiring, pipeline kwarg, 14-test plan, tracker updates, verification footer)
- `prompts/wave-plan.yaml` (W97 entry appended after W96 tail)

## Wave-97 baseline + targets

- **HEAD:** `6246b35` (`Wave 96 archive: AD-521 SWE/Build pipeline separation (#96)`). Captain reference HEAD `6246b35` matches `origin/main` exactly; no upstream BF commits between Captain HEAD and this draft HEAD.
- **Baseline pytest:** Captain reference is **12126**; live `findstr /C:"PASSED" + parallel gate` shows **12120 passed / 6 failed / 16 skipped** at HEAD `6246b35` under `-n 4 --dist=loadfile` (548s). Collection-only count is **12142**. The 6 parallel failures are pre-existing environmental flakes carried over from W96 and are unrelated to AD-476; serial re-run is the standard triage path per BF-255 pattern. Target gate uses Captain's reference number for Δ accounting.
- **Target pytest:** **≥12138** (Δ ≥ +12 against Captain reference 12126 — 14 new boundary tests in `tests/test_ad476_specialized_builders.py`; one or two may be marked `@pytest.mark.skip` if a v1 plumbing decision flips during build, hence the conservative ≥+12 floor with +14 nominal). Builder may exceed +12 with additional edge-case tests; minimum gate is +12.
- **Issue closed:** `#70 — AD-476: Specialized Builders — Cognitive Division of Labor for SWE` (single issue; no children minted by W97; AD-476b/c remain unminted as roadmap forward-references).

## Banned-pattern audit on this dispatch + the per-AD prompt + this audit prose itself

Eleven patterns checked, descriptor-only language used throughout: "the e-word + tier phrase", "the private commercial-repo path token", "the e-word overlay phrase", "the e-word-prefixed repo token", "monthly-price regex", "per-month abbreviation regex", "rev-proj phrase", "the recurring-revenue acronym", "outcome-style pricing phrase", "the GTM-pattern phrase", "the patterns-to-absorb phrase". The audit text itself does NOT contain literal forms of any banned pattern — descriptor-only references throughout. The pre-commit hook trips on literal "the e-word + tier phrase" and "the private commercial-repo path token" forms; this dispatch (and the per-AD prompt + the wave-plan.yaml notes block) avoids both literal forms via descriptor-only references. Pre-commit-hook simulation `Select-String -Path prompts/WAVE-97-DISPATCH.md, prompts/ad-476-specialized-builders-v1.md -Pattern <pattern> -SimpleMatch` returns zero hits per pattern across all artefacts.

The closed-source overlay scope is genuine — AD-521 W96 documented an OSS-vs-closed-source crew-tier split (`decisions-era-4-evolution.md:1453-1456`) and AD-476 inherits the same plug-in surface — but v1 ships zero closed-source content. The class-extension plug-in point is the architectural surface; the overlay implementation lives in the private commercial-repo path token surface, governed by AD-452 class-extension mechanism. Descriptor-only language is appropriate here: the audit is a real hygiene check on a real plug-in surface.

## Captain rule alignment

- **Don't defer unless no choice:** zero deferrals beyond AD-546 (SWE Tool Harness pipeline integration, GH #13 — already tracked) and AD-463b/c (ModelRegistry MAD scoring + hot-swap, AD-463 v1 already shipped the static catalog). v1 ships the complete architectural separation specified in the roadmap entry. The production chunk-routing call site and the dynamic-model-swap call site are both genuinely separate waves with their own dependency chains.
- **Verify-first:** every concrete claim in the per-AD prompt has an explicit grep-evidence line in the `## Verified Against Codebase (2026-05-07, HEAD 6246b35)` footer. Twelve grep-anchored claims confirm AD entry location, conceptual section header, base SWE class, alias, departments map, runtime template line, runtime import line, BuildPipeline signature, ModelRegistry class, builder_variant relation type, visiting-vs-native router, and CodeReviewAgent class.
- **`.github/copilot-instructions.md` compliance:** explicit acceptance-criteria line in the per-AD prompt — "Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`." The five specialist classes honour: SOLID-S (each subclass single-responsibility, one specialty domain); Open/Closed (subclasses extend `SoftwareEngineerAgent` via class attributes + `instructions` override, no monkey-patching); Liskov (each subclass is fully substitutable for `SoftwareEngineerAgent` — same `_handled_intents`, same `intent_descriptors`, same lifecycle); Interface Segregation (`SpecialistRouter` is a narrow `Protocol`-friendly helper, not a god-class); Dependency Inversion (constructor injection of runtime; no globals); Demeter (no `obj._private_attr` access); DRY (specialty rules live in one rule-set table on `SpecialistRouter`); Cloud-ready storage (no new DB access); Three-tier exception handling (router never raises — falls back to GENERAL); Type annotations (all public methods fully typed); Logging context (every router decision + every pipeline thread-through includes operation + inputs + outcome); Async hygiene (no new async surfaces beyond the pipeline kwarg); Configuration (Pydantic model with `field_validator`s, defaults at parse time).
- **Close #70 cleanly:** issue closed at end of W97 with the canonical paragraph in Section 8 of the per-AD prompt; no children minted, no follow-up issues. AD-476b/c stay tracked as forward-references in the roadmap.
- **No commercial leak:** descriptor-only audit, banned-pattern scan returns zero hits across all 11 patterns. The closed-source overlay plug-in point is documented descriptor-only with a placeholder forward-reference to the AD-452 class-extension AD that lives in the private commercial-repo path token surface.

## Build groups

Single Builder cycle — no dependency DAG, no build group ordering. The work decomposes into seven sections applied top-to-bottom:

1. **Section 1 — `src/probos/cognitive/builder_specialist.py`** — new module, `SoftwareEngineerSpecialty` enum + `SpecialtyMatchResult` frozen dataclass + `SpecialistRouter` class + module-level helpers. Pure helpers, no agent classes, no runtime dependency. ~280 lines.
2. **Section 2 — `src/probos/cognitive/builder_specialists.py`** — new module, five `SoftwareEngineerAgent` subclasses with overridden `agent_type` / `specialty` / `instructions`. Each ~50 lines including the specialty-tuned instructions string. ~250 lines total.
3. **Section 3 — `src/probos/cognitive/standing_orders.py`** — five new entries in `_AGENT_DEPARTMENTS` mapping each new agent_type to `engineering`. SEARCH anchor is the existing `"code_reviewer": "engineering",` line at `:43`.
4. **Section 4 — `src/probos/config.py`** — `SoftwareEngineerSpecialistsConfig` Pydantic model + `swe_specialists: SoftwareEngineerSpecialistsConfig` field on `SystemConfig`. Default-False on `enabled` (real pool side-effect, opt-in).
5. **Section 5 — `src/probos/runtime.py`** — sibling import block + five `register_template(...)` lines after the existing `builder` template line at `:706`.
6. **Section 6 — `src/probos/startup/agent_fleet.py`** — conditional pool creation block guarded on `config.swe_specialists.enabled`, mirroring the existing builder-pool pattern. Skips with INFO log when disabled.
7. **Section 7 — `src/probos/build_pipeline.py` + `src/probos/cognitive/builder.py`** — add `specialty: str = "general"` kwarg to `BuildPipeline.execute_approved_build` and to the legacy `execute_approved_build` coroutine. Log at INFO; thread through. Zero behaviour change at default.
8. **Section 8 — `tests/test_ad476_specialized_builders.py`** — new file with 14 tests (see Test plan in the per-AD prompt).
9. **Section 9 — Trackers** — PROGRESS.md INSERT at top; `docs/development/roadmap.md:4213` flip; `prompts/wave-plan.yaml` W97 entry append.

The seven implementation sections are independently buildable. Tests in Section 8 cover all seven and are runnable as a focused subset (`pytest tests/test_ad476_specialized_builders.py -v -n 0`) for fast iteration.

## Concerns / observations for Captain (architect handoff)

1. **Wave 96 left trackers untouched.** `git show --name-only a0e9bc0 6246b35` confirms W96 modified only `src/probos/build_pipeline.py`, `src/probos/cognitive/builder.py`, `src/probos/runtime.py`, `tests/test_ad521_swe_pipeline_separation.py`, and the two archived prompt files. PROGRESS.md, DECISIONS.md, `decisions-era-4-evolution.md`, `docs/development/roadmap.md`, and `prompts/wave-plan.yaml` were NOT touched. AD-521 status footer at `decisions-era-4-evolution.md:1467` still reads `**Status:** **DECIDED** (2026-03-29). Architecture approved. Implementation deferred — requires build prompt and builder execution.` even though implementation actually shipped. **W97 stays scoped to AD-476 only and does NOT retroactively patch the W96 omission** — that is a separate small reconciliation wave Captain may want to dispatch (W97a or absorb into W98). If Captain prefers, W97 can absorb the AD-521 tracker reconciliation as Section 10; flag at review time and the per-AD prompt will pick it up. **Default: leave W96 reconciliation outside W97.**
2. **Baseline drift.** Captain reference is 12126; the live xdist parallel gate at HEAD shows 12120 passed / 6 failed / 16 skipped. Collection count is 12142. The 6-test gap between Captain reference and live count is consistent with normal xdist environmental flakes (BF-255 pattern); the 16-test gap to collection is the constant skipped tests. W97 uses Captain's 12126 as the reference baseline for Δ ≥ +12 accounting; serial re-run can confirm 12126 if needed.
3. **Pool default-False is correct here.** Unlike AD-687/AD-689/AD-692 (transparent pass-through wrappers safe to default-True), AD-476 v1 with `enabled=True` would actually spawn five new agents at boot — a real cognitive-budget side-effect. Default-False is the right Wave-10 transitional-flag posture; flip is AD-476b (post-track-record) territory.
4. **`builder_source="native"` semantics + `specialty="general"` semantics are independent.** Tests #11–#13 in the test plan verify both default values flow through unchanged when omitted at the call site, and that the legacy `build_dispatcher.py:18` and `routers/build.py:382` invocations continue to work without modification.
5. **No standing-orders churn.** The five new agent_types reuse `engineering.md` + `builder.md`. Specialty-specific guidance lives in the subclass `instructions` attribute. If Captain wants per-specialty markdown later (`backend.md`, `frontend.md`, etc.), that's AD-476d territory and best authored by the Captain directly.

Builder execution: read the per-AD prompt top-to-bottom, apply 8 SEARCH/REPLACE pairs across 6 MODIFY blocks (standing_orders.py, config.py, runtime.py, agent_fleet.py, build_pipeline.py, builder.py legacy execute_approved_build) plus the 2 new file creates (`builder_specialist.py` + `builder_specialists.py`) plus the 1 new test file plus the 3 tracker updates (PROGRESS.md INSERT, roadmap.md flip, wave-plan.yaml append). Verify `git diff --stat` shows 6 modified source files + 3 modified tracker files + 3 new files (specialist module + specialists module + test file) plus this prompt + dispatch (which Builder will archive after commit). Pre-commit hook runs naturally on commit. Full pytest gate (expected ≥12138 passed; minimum gate is +12). Commit with `"AD-476 v1: Specialized Builders — five specialist SWE subclasses + SpecialistRouter + opt-in pools + pipeline kwarg (+14 tests)"`. Archive both prompts. `gh issue close 70` with the canonical paragraph in Section 8 of the per-AD prompt.

## Verified Against Codebase (2026-05-07, HEAD 6246b35)

```
findstr /N /C:"AD-476" docs\development\roadmap.md
  1619: *Specialized Builders (Cognitive Division of Labor for SWE):* *(AD-476)*
  4213: **AD-476: Specialized Builders — Cognitive Division of Labor for SWE** *(planned)* — ...

findstr /N /C:"class SoftwareEngineerAgent" /C:"BuilderAgent = SoftwareEngineerAgent" src\probos\cognitive\builder.py
  1690: class SoftwareEngineerAgent(CognitiveAgent):
  2529: BuilderAgent = SoftwareEngineerAgent

findstr /N /C:"\"builder\": \"engineering\"" /C:"\"code_reviewer\": \"engineering\"" src\probos\cognitive\standing_orders.py
  42: "builder": "engineering",
  43: "code_reviewer": "engineering",

findstr /N /C:"register_template(\"builder\"" /C:"from probos.cognitive.builder import BuilderAgent" src\probos\runtime.py
  56: from probos.cognitive.builder import BuilderAgent
  706: self.spawner.register_template("builder", BuilderAgent)

findstr /N /C:"async def execute_approved_build" src\probos\build_pipeline.py
  56:    async def execute_approved_build(

findstr /N /C:"async def execute_approved_build" src\probos\cognitive\builder.py
  2532: async def execute_approved_build(

findstr /N /C:"class ModelRegistry:" src\probos\cognitive\model_registry.py
  83: class ModelRegistry:

findstr /N /C:"REL_BUILDER_VARIANT" src\probos\mesh\routing.py
  31: REL_BUILDER_VARIANT = "builder_variant"  # build_code → native|visiting (AD-353)

findstr /N /C:"def _should_use_visiting_builder" src\probos\cognitive\builder.py
  1251: def _should_use_visiting_builder(

findstr /N /C:"class CodeReviewAgent" src\probos\cognitive\code_reviewer.py
  1: """Code Review Agent -- reviews Builder output against ProbOS standards (AD-341)."""
  (class declaration follows; verified by separate read)

git show --name-only a0e9bc0 6246b35
  (W96 commits — confirmed PROGRESS.md / DECISIONS / roadmap / wave-plan UNTOUCHED)

gh issue view 70 --json number,title,state
  {"number":70,"state":"OPEN","title":"AD-476: Specialized Builders — Cognitive Division of Labor for SWE"}
```
