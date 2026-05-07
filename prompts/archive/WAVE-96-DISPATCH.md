# WAVE 96 DISPATCH — AD-521 v1 SWE/Build Pipeline Separation — Model A (closes #96)

## Wave summary

**Umbrella AD:** AD-521 (SWE/Build Pipeline Separation — Model A — decided 2026-03-29 at `decisions-era-4-evolution.md:1427-1467`, indexed at `docs/development/roadmap.md:6624-6634`).

**Wave kind:** Source-modifying v1 — structural refactor. Extracts `BuildPipeline` as a Ship's Computer service from `cognitive/builder.py` (currently 117 KB / ~2900 lines, conflates sovereign crew agent with mechanical pipeline functions), renames the crew agent class `BuilderAgent` → `SoftwareEngineerAgent` with a `BuilderAgent` back-compat alias, wires `runtime.build_pipeline` into `ProbOSRuntime`, and preserves every existing import path via module-level re-exports. Pure structural separation — zero behaviour change at runtime, zero changes to LLM prompts, parsing rules, fix loop, or pre-flight gates.

**Reframe decision — BUILD v1 (no defer):**

AD-521 has been in **DECIDED** status since 2026-03-29. Implementation was deferred awaiting "build prompt and builder execution" (`decisions-era-4-evolution.md:1467`). The architectural intent is well-specified: three-layer separation (SWE crew sovereign / Build pipeline infrastructure / external tools as visiting officers); SWE always in the chain; pipeline shareable across multiple SWEs. The structural refactor required to realise this intent is tractable in one Builder cycle:

1. **The split inside `cognitive/builder.py` is already structural.** Lines 1-1685 are pure pipeline functions and dataclasses (`BuildSpec`, `BuildResult`, `BuildFailureReport`, `ChunkSpec`, `ChunkResult`, `BuildBlueprint`, `ValidationResult`, `classify_build_failure`, `create_blueprint`, `decompose_blueprint`, `execute_chunks`, `assemble_chunks`, blueprint/chunk decomposition helpers, transporter helpers, the visiting-vs-native router). Lines 1687-2510 are the `BuilderAgent` crew class. Lines 2512-end are `execute_approved_build` plus its git/test/fix helpers. The two concerns are already on opposite sides of a class boundary.

2. **The runtime injection pattern is already established.** `WarmBootService`, `DreamAdapter`, `WardRoomRouter`, `SelfModManager`, `AgentOnboarding` were extracted as Ship's Computer services in AD-515 (`runtime.py:567-569`). `BuildPipeline` slots into the same pattern: `runtime.build_pipeline = BuildPipeline(runtime=self)` initialised in `start()`, exposed as a public attribute, called by `routers/build.py` and `build_dispatcher.py` via the runtime handle.

3. **Back-compat is straightforward.** Existing imports (`from probos.cognitive.builder import execute_approved_build`, `BuildSpec`, `BuildResult`, `BuilderAgent`, `_should_use_visiting_builder`, `_check_sealed_path`, `_PROJECT_ROOT`) are preserved as re-exports from `cognitive/builder.py` pointing at the new service module. 16 test files import from `probos.cognitive.builder` (verified) — all keep working unchanged via the shim.

4. **Captain rule "don't defer unless no choice" satisfied non-vacuously.** AD-521 v1 is a structural prerequisite for AD-543-549 (the SWE Tool Harness wave at GH #13, queued next). Without the separation, the agentic loop in AD-545 would graft onto a class that conflates crew and infrastructure — every later AD would be paying interest on the architectural debt. Shipping v1 now keeps the AD-543-549 wave clean.

**v1 IN scope (concrete):**
- New module `src/probos/build_pipeline.py` (~180 lines): `BuildPipeline` class with `execute_approved_build(...)` and `parse_file_blocks(...)` instance methods. Constructor takes `runtime` (for `pre_flight_runner`, `emit_event`, `llm_client` access) — no global lookups, full constructor injection per Engineering Principles.
- `cognitive/builder.py` refactor: class `BuilderAgent` renamed to `SoftwareEngineerAgent`, `BuilderAgent = SoftwareEngineerAgent` module-level alias for back-compat, class docstring updated to reflect SWE crew role. `agent_type = "builder"`, `callsign = "Scotty"`, pool name `"builder"`, standing-orders mapping `builder → engineering` ALL UNCHANGED — these identifiers are role/pool keys, not class names, and their churn would break 16+ allow-list / spawner / standing-orders / skill-framework references for zero architectural gain.
- `cognitive/builder.py` shim: `execute_approved_build(...)` remains a module-level coroutine that delegates to `BuildPipeline(runtime=runtime).execute_approved_build(...)` when called without a runtime, or to `runtime.build_pipeline.execute_approved_build(...)` when a runtime is passed. Preserves the existing call sites in `build_dispatcher.py:18` and `routers/build.py:382` without changes.
- `runtime.py` wiring: `self.build_pipeline: BuildPipeline | None = None` declared in `__init__` alongside the other service attributes, instantiated in `start()` after `pre_flight_runner` is built (so `BuildPipeline` can read it through `self._runtime.pre_flight_runner`).
- New test file `tests/test_ad521_swe_pipeline_separation.py` with 12 tests (see Test plan below).

**v1 OUT scope (deferred with explicit forcing functions):**
- **AD-543 ToolCall protocol + ToolExecutor** — next wave (GH #13). Forcing function: AD-545 agentic loop cannot be built without ToolDefinition/ToolCallRequest data model; AD-543 is its hard dependency.
- **AD-544 native tool suite** — depends on AD-543; ships in same harness wave.
- **AD-545 agentic loop** — depends on AD-543/544.
- **AD-546 BuildPipeline integration of agentic loop** — depends on AD-545; this AD is precisely where SWE delegates to native vs visiting builder via tool selection. It explicitly cites AD-521 as the architectural precondition (`docs/development/roadmap.md:6768` — "depends: AD-545, AD-521"). Shipping AD-521 v1 unblocks AD-546.
- **AD-547 session compaction**, **AD-548 trust-tier permissions**, **AD-549 visiting-builder migration** — all attached to the harness wave.
- **Cognitive JIT (Phase 32)** — far-future, not blocked by v1.
- **The Inspector / ReviewerAgent crew role** — already exists as `CodeReviewAgent` (`src/probos/cognitive/code_reviewer.py:1`, invoked from `cognitive/builder.py:2654-2674`). v1 verifies the existing wiring is preserved through the refactor; no new code.

**The crew-tier-licensing class-extension plug-in point (out-of-repo overlay):**
AD-521 documents two SWE tiers (`decisions-era-4-evolution.md:1453-1456`) — the OSS Scotty (functional, follows process) and the closed-source Pro variant (deeper cognitive chains, solution tree search, peer-level code review). v1 ships the OSS class structure as a clean extension point: `SoftwareEngineerAgent` is subclassable, `BuildPipeline` is composable, `runtime.build_pipeline` is settable. The closed-source overlay slots in via the AD-452 class-extension mechanism (out-of-repo, governed by the placeholder-tier licensing AD that lives in the private commercial-repo path token surface). v1 itself ships zero closed-source content; placeholder-only references in this dispatch and the per-AD prompt.

## AD numbering

Highest stem at HEAD `08bfc7f` is **AD-696** (verified by `Select-String -Path PROGRESS.md, DECISIONS.md, decisions-era-*.md, docs/development/roadmap.md -Pattern 'AD-(\d{3})' -AllMatches | … Measure-Object -Maximum` → 696). Highest BF at HEAD: **BF-596** (same scan returning 596). Wave 96 mints zero new AD numbers and zero new BF numbers — AD-521 already exists, no sub-AD letters added.

## Verify-first against HEAD `08bfc7f`

Eight grep-anchored claims, all verified live:

- **`decisions-era-4-evolution.md:1427`** — `## AD-521: SWE/Build Pipeline Separation — Model A (2026-03-29)` is the canonical decision header. Status footer at `:1467` reads `**Status:** **DECIDED** (2026-03-29). Architecture approved. Implementation deferred — requires build prompt and builder execution.` Verified by reading lines 1427-1467 directly.
- **`docs/development/roadmap.md:6624-6634`** — Engineering Crew Architecture section. AD-521 bullet at `:6628` begins `**AD-521: SWE/Build Pipeline Separation — Model A** *(decided, OSS + Commercial, depends: AD-398, AD-452)*`. Verified.
- **`docs/development/roadmap.md:6768`** — AD-546 bullet `*(planned, OSS, depends: AD-545, AD-521)*` confirms AD-546 is the downstream forcing function for shipping AD-521 v1 ahead of the harness wave. Verified.
- **`PROGRESS.md`** — `Select-String -Path PROGRESS.md -Pattern 'AD-521' -SimpleMatch` returns **zero hits** at HEAD. W96 ADDS a new status note line in the recent-activity block (canonical pattern matches the `AD-652 REALISED (Wave 95 close, 2026-05-07)` line at PROGRESS.md:331). The SEARCH anchor in the per-AD prompt targets a stable adjacent line (e.g. the AD-652 line itself or the BF-227 line at :329); Builder INSERTS the AD-521 note after that anchor.
- **`src/probos/cognitive/builder.py:1690`** — `class BuilderAgent(CognitiveAgent):` is the current class declaration. Verified by `grep -n "class BuilderAgent" src/probos/cognitive/builder.py` returning `1690`.
- **`src/probos/cognitive/builder.py:2512`** — `async def execute_approved_build(` is the current module-level coroutine signature. Verified.
- **`src/probos/runtime.py:567-569`** — service injection pattern (`self.warm_boot: WarmBootService | None = None`, `self.dream_adapter: DreamAdapter | None = None`) is the canonical site for adding `self.build_pipeline: BuildPipeline | None = None`. Verified.
- **`src/probos/startup/finalize.py:1644`** — `runtime.pre_flight_runner = PreFlightRunner(...)` is set in the startup finalize module, NOT in `runtime.__init__` or `runtime.start()`. The current builder-side access pattern at `cognitive/builder.py:2548` is `getattr(runtime, "pre_flight_runner", None)` — defensive lookup. `BuildPipeline` MUST preserve the same `getattr` defensive pattern; ordering between `build_pipeline` instantiation and `pre_flight_runner` initialisation is irrelevant because the runtime attribute is read at `execute_approved_build` invocation time, not at `BuildPipeline.__init__` time. Verified.
- **`src/probos/runtime.py:697`** — `self.spawner.register_template("builder", BuilderAgent)` is the spawner registration. Stays unchanged because `BuilderAgent` remains importable from `cognitive/builder.py` as the alias for `SoftwareEngineerAgent`. Verified.

The 16 test files importing from `probos.cognitive.builder` were enumerated by `findstr /S /I /M "BuilderAgent" tests\*.py` and `findstr /S /I /M "execute_approved_build" tests\*.py` — coverage spans `test_builder_agent.py`, `test_builder_api.py`, `test_builder_guardrails.py`, `test_build_dispatcher.py`, `test_build_queue.py`, `test_architect_agent.py`, `test_dispatch_wiring.py`, `test_copilot_adapter.py`, `test_codebase_skill.py`, `test_ad398_crew_identity.py`, `test_ad481_extensions.py`. All keep working unchanged because every name they import (`BuilderAgent`, `BuildSpec`, `BuildResult`, `_should_use_visiting_builder`, `_check_sealed_path`, `_PROJECT_ROOT`, `execute_approved_build`) is preserved as a module-level re-export.

## Reframe decision — build v1, not defer

**One concrete sub-AD letter built in v1 + zero future sub-AD letters parked + the closed-source crew-tier overlay as out-of-repo plug-in point + zero hard-deferrals.**

AD-521 v1 ships the architectural separation specified in the 2026-03-29 decision: BuildPipeline as Ship's Computer service, SoftwareEngineerAgent as crew class, runtime wiring, full back-compat via aliases and shims. The agentic-loop tooling (AD-543-549) is the next wave (GH #13) and depends on AD-521 v1 as its prerequisite — shipping v1 now unblocks the harness wave cleanly.

Captain rule "don't defer unless no choice" satisfied non-vacuously: the structural separation is necessary infrastructure for AD-543-549, the surface area is bounded (one new module, one class rename + alias, one runtime attribute, full back-compat), and the test impact is well-defined (12 new boundary tests, zero existing-test churn).

## Files

- `prompts/WAVE-96-DISPATCH.md` (this file)
- `prompts/ad-521-swe-build-pipeline-separation-v1.md` (per-AD prompt — new module, class rename + alias, runtime wiring, 12-test plan, tracker updates, verification footer)
- `prompts/wave-plan.yaml` (W96 entry appended after W95 tail)

## Wave-96 baseline + targets

- **HEAD:** `08bfc7f` (`Wave 95 archive: AD-652 cognitive code-switching (#302)`). Captain reference HEAD `08bfc7f` matches `origin/main` exactly; no upstream BF commits between Captain HEAD and this draft HEAD.
- **Baseline pytest:** **12130** (verified by `.venv\Scripts\pytest.exe --collect-only -q tests/` → `12130 tests collected` per Captain reference).
- **Target pytest:** **≥12142** (Δ ≥ +12 — 12 new boundary tests in `tests/test_ad521_swe_pipeline_separation.py`). Builder may exceed +12 with additional edge-case tests; minimum gate is +12.
- **Issue closed:** `#96 — AD-521: SWE/Build Pipeline Separation — Model A` (single issue; no children minted by W96; AD-543-549 already tracked under GH #13 for the next wave).

## Banned-pattern audit on this dispatch + the per-AD prompt + this audit prose itself

Eleven patterns checked, descriptor-only language used throughout: "the e-word + tier phrase", "the private commercial-repo path token", "the e-word overlay phrase", "the e-word-prefixed repo token", "monthly-price regex", "per-month abbreviation regex", "rev-proj phrase", "the recurring-revenue acronym", "outcome-style pricing phrase", "the GTM-pattern phrase", "the patterns-to-absorb phrase". The audit text itself does NOT contain literal forms of any banned pattern — descriptor-only references throughout. The pre-commit hook trips on literal "the e-word + tier phrase" and "the private commercial-repo path token" forms; this dispatch (and the per-AD prompt + the wave-plan.yaml notes block) avoids both literal forms via descriptor-only references. Pre-commit-hook simulation `Select-String -Path prompts/WAVE-96-DISPATCH.md, prompts/ad-521-swe-build-pipeline-separation-v1.md -Pattern <pattern> -SimpleMatch` returns zero hits per pattern across all artefacts.

The closed-source overlay scope is genuine — AD-521 documents an OSS-vs-closed-source crew-tier split (`decisions-era-4-evolution.md:1453-1456`) — but v1 ships zero closed-source content. The class-extension plug-in point is the architectural surface; the overlay implementation lives in the private commercial-repo path token surface, governed by AD-452 class-extension mechanism. Descriptor-only language is appropriate here: the audit is a real hygiene check on a real plug-in surface.

## Captain rule alignment

- **Don't defer unless no choice:** zero deferrals beyond the AD-543-549 harness wave (already tracked under GH #13). v1 ships the complete architectural separation specified in the 2026-03-29 decision. The agentic-loop tooling is genuinely a separate wave with its own dependency chain.
- **Verify-first:** every concrete claim in the per-AD prompt has an explicit grep-evidence line in the `## Verified Against Codebase (2026-05-07, HEAD 08bfc7f)` footer. Eight grep-anchored claims confirm decision header, status footer, downstream dependency, runtime injection pattern, current class declaration, current coroutine signature, current spawner registration, and import-path coverage across 16 test files.
- **`.github/copilot-instructions.md` compliance:** explicit acceptance-criteria line in the per-AD prompt — "Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`." The refactor honours: SOLID (BuildPipeline is single-responsibility infrastructure; SoftwareEngineerAgent is single-responsibility crew judgment + delegation); Dependency Inversion (constructor injection of runtime, no globals); Layer discipline (BuildPipeline lives at top-level alongside other Ship's Computer services, not in `cognitive/`); Logging context (every BuildPipeline log message includes operation + runtime state + outcome); Type annotations (all public methods on BuildPipeline fully typed); Async hygiene (`asyncio.iscoroutinefunction` guards preserved on `escalation_hook`); Layer 1 cloud-ready (no new DB access; existing patterns preserved).
- **Close #96 cleanly:** issue closed at end of W96 with the canonical paragraph in Section 6 of the per-AD prompt; no children minted, no follow-up issues. AD-543-549 stays tracked under GH #13.
- **No commercial leak:** descriptor-only audit, banned-pattern scan returns zero hits across all 11 patterns. The closed-source overlay plug-in point is documented descriptor-only with a placeholder forward-reference to the AD-452 class-extension AD that lives in the private commercial-repo path token surface.

## Build groups

Single Builder cycle — no dependency DAG, no build group ordering. The work decomposes into five sections applied top-to-bottom:

1. **Section 1 — `src/probos/build_pipeline.py`** — new module, `BuildPipeline` class with `execute_approved_build(...)` and `parse_file_blocks(...)` instance methods. Constructor takes `runtime: ProbOSRuntime | None = None`. Methods delegate to (or absorb) the existing module-level helpers in `cognitive/builder.py`. New file, ~180 lines.
2. **Section 2 — `src/probos/cognitive/builder.py` rename + shim** — class `BuilderAgent` → `SoftwareEngineerAgent`, module-level `BuilderAgent = SoftwareEngineerAgent` alias, class docstring update. The module-level `execute_approved_build(...)` becomes a thin shim that constructs/uses a `BuildPipeline` and forwards. Pure rename + shim — zero behaviour change.
3. **Section 3 — `src/probos/runtime.py` wiring** — declare `self.build_pipeline: BuildPipeline | None = None` after the existing service attributes (alongside `self.warm_boot` / `self.dream_adapter` at runtime.py:567-569), instantiate in `start()` early (no ordering constraint vs `pre_flight_runner` because `BuildPipeline.execute_approved_build` reads the runtime attribute via `getattr` at invocation time — same pattern as the current `cognitive/builder.py:2548` lookup).
4. **Section 4 — `tests/test_ad521_swe_pipeline_separation.py`** — new test file, 12 tests. See Test plan below.
5. **Section 5 — Tracker updates** — `decisions-era-4-evolution.md` AD-521 status footer at `:1467` flips from `**DECIDED** (2026-03-29). Architecture approved. Implementation deferred — requires build prompt and builder execution.` to `**v1 COMPLETE** (2026-05-07)` plus realisation summary; `docs/development/roadmap.md` AD-521 bullet at `:6628` flips from `*(decided, OSS + Commercial, depends: AD-398, AD-452)*` to `*(v1 complete, OSS + Commercial, depends: AD-398, AD-452)*` plus realisation list; `PROGRESS.md` ADDS a new status note (no existing AD-521 line to flip — zero AD-521 matches at HEAD); `prompts/wave-plan.yaml` W96 entry appended after W95 tail.

Total: **5 sections, 1 new source module (~180 lines), 1 modified source module (`cognitive/builder.py` rename + shim), 1 modified runtime wiring file, 1 new test file (12 tests), 4 trackers reconciled (one of which — PROGRESS.md — is an INSERT not a flip).**

## Test plan (12 tests)

`tests/test_ad521_swe_pipeline_separation.py`:

1. `test_build_pipeline_class_exists_at_top_level` — `from probos.build_pipeline import BuildPipeline` succeeds; class is at top level of module hierarchy (Ship's Computer service, not in `cognitive/`).
2. `test_build_pipeline_constructor_accepts_runtime` — `BuildPipeline(runtime=fake_runtime)` succeeds; `BuildPipeline()` (no runtime) also succeeds for unit-test ergonomics.
3. `test_build_pipeline_execute_approved_build_signature` — `BuildPipeline.execute_approved_build` is an `async def` method whose signature mirrors the module-level coroutine (file_changes, spec, work_dir, run_tests, max_fix_attempts, llm_client, escalation_hook, builder_source).
4. `test_build_pipeline_parse_file_blocks_signature` — `BuildPipeline.parse_file_blocks` is a method (instance or static) accepting raw LLM text and returning a list of file-change dicts.
5. `test_software_engineer_agent_class_exists` — `from probos.cognitive.builder import SoftwareEngineerAgent` succeeds; `SoftwareEngineerAgent` is a `CognitiveAgent` subclass with `agent_type == "builder"`.
6. `test_builder_agent_alias_preserved` — `from probos.cognitive.builder import BuilderAgent` succeeds; `BuilderAgent is SoftwareEngineerAgent` evaluates True. Existing import patterns in 16 test files keep working.
7. `test_software_engineer_agent_handles_build_code_intent` — `SoftwareEngineerAgent._handled_intents == {"build_code"}` and `IntentDescriptor` for `build_code` has `requires_consensus=True`. Crew identity unchanged.
8. `test_module_level_execute_approved_build_shim_preserved` — `from probos.cognitive.builder import execute_approved_build` succeeds; calling it with a fake-but-minimally-complete `BuildSpec` and an empty `file_changes` list returns a `BuildResult` (not a runtime error). Validates the shim path.
9. `test_runtime_build_pipeline_attribute_declared` — `ProbOSRuntime.__init__` declares `self.build_pipeline: BuildPipeline | None`, initialised to `None` before `start()`.
10. `test_runtime_build_pipeline_instantiated_in_start` — after `await runtime.start()`, `runtime.build_pipeline` is an instance of `BuildPipeline`.
11. `test_build_pipeline_uses_runtime_pre_flight_runner` — when `runtime.pre_flight_runner` is set, `BuildPipeline.execute_approved_build` invokes pre-flight via the runtime handle (verified via fake runtime + monkeypatched pre-flight). Confirms constructor injection works end-to-end without globals.
12. `test_class_rename_preserves_callsign_and_pool_name` — `SoftwareEngineerAgent.agent_type == "builder"`, callsign mapping in `crew_profile`/`crew_utils` continues to resolve "Scotty" for `agent_type == "builder"`, pool name `"builder"` preserved at `runtime.py:697`. Confirms the rename is class-only, not role-key churn.

All 12 tests use `_FakeRuntime` / `_FakeAgent` stubs per existing patterns in `tests/conftest.py`. No real LLM calls, no real git operations, no real file writes (except `tmp_path` fixtures in tests 8/11). Order-independent. Each test creates its own fixtures.

## Hard-stops specific to W96

- **W96-1:** Any of the SEARCH blocks fails to match (anchor drift since draft) → Builder surfaces back to Architect, do not improvise. Anchor verification footer in the per-AD prompt provides exact line numbers and grep evidence — drift means an unrelated commit landed between draft and build.
- **W96-2:** Pytest gate returns fewer than 12142 tests passing → Builder hard-stops. The +12 boundary tests are the minimum gate; a regression in any of the 16 existing import-path test files indicates the alias / shim is not fully back-compat and must be fixed before commit.
- **W96-3:** Pre-commit hook flags banned literal in any of the modified surfaces → Builder hard-stops and surfaces back. The closed-source overlay scope is real but v1 ships zero closed-source content; if the hook trips, descriptor-only language has been violated somewhere in the per-AD prompt.
- **W96-4:** Builder elects to rename `agent_type` from `"builder"` to `"software_engineer"` "while we're here" → out of scope. The rename is class-only by explicit design; agent_type is a pool/role key referenced in 16+ allow-list / spawner / standing-orders / skill-framework sites and churning it is a separate AD. Hard-stop.
- **W96-5:** Builder elects to ship AD-543 ToolCall protocol or any AD-543-549 harness component "while we're here" → out of scope. Those belong to GH #13 and the next wave. Hard-stop.
- **W96-6:** Builder elects to mint a new GH issue for any deferred sub-AD letter → out of scope. AD-521 v1 has no sub-AD letters; AD-543-549 are tracked under GH #13 already. Hard-stop.
- **W96-7:** Builder elects to remove or refactor `CodeReviewAgent` (Inspector role) "while we're here" → out of scope. The Inspector is already wired (`cognitive/builder.py:2654-2674` invocation site preserved through the refactor). Hard-stop.

## Pre-flight checklist (Builder reads before starting)

1. `git status` — confirm clean working tree at HEAD `08bfc7f`.
2. `git rev-parse HEAD` — confirm `08bfc7f`.
3. `.venv\Scripts\pytest.exe --collect-only -q tests/` — confirm `12130 tests collected`.
4. `Select-String -Path prompts/WAVE-96-DISPATCH.md, prompts/ad-521-swe-build-pipeline-separation-v1.md -Pattern '<each of the 11 banned patterns>' -SimpleMatch` — confirm zero hits.
5. Read `prompts/ad-521-swe-build-pipeline-separation-v1.md` top-to-bottom. Confirm every SEARCH block matches its target line range in the verification footer.
6. Apply Sections 1-5 in order. Run pytest gate after Section 4 completes.
7. Commit with message `AD-521 v1: SWE/Build Pipeline Separation — Model A (extract BuildPipeline service, rename BuilderAgent → SoftwareEngineerAgent + alias, runtime wiring, +12 tests)`.
8. Archive `prompts/WAVE-96-DISPATCH.md` and `prompts/ad-521-swe-build-pipeline-separation-v1.md` to `prompts/archive/`.
9. `gh issue close 96 -c "<canonical paragraph from Section 6 of per-AD prompt>"`.
