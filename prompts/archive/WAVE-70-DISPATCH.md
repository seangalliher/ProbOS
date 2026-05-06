# WAVE 70 DISPATCH — AD-526e v1 Spectator Registry (Combo Reframe, FINAL wave)

**Wave id:** 70 (FINAL wave of the queued sweep)
**Single AD:** AD-526e (the LAST remaining buildable child of the AD-526c–h combo)
**Closes (partial):** GH issue #101 — two children already shipped, three wholesale-deferred to AD-526f/g/h with explicit forcing functions, one shipping this wave
**Baseline test count:** 11419 (HEAD `66c89ff`, post-Wave-69) → expected **11431** (+12 net), window **[+10, +14]**
**HEAD at draft:** `66c89ff`, working tree clean
**Builder:** required

## Reframe Summary (Wave-10 pattern, 6→1)

Wave 70 was originally queued as a 6-AD combo (AD-526c/d/e/f/g/h) per `prompts/wave-plan.yaml` id=70. Verify-first against HEAD reveals five of those six children are NOT outstanding work in this wave's scope. Reality at HEAD `66c89ff`:

| Child | Outstanding? | Source-of-truth |
|---|---|---|
| **AD-526c** | ❌ NO — partial-shipped Wave 13 (Combo C, commit ffda515) as v1 (`GameMetadata` + `default_game` preference + `RECREATION_GAME_REGISTERED` emit). v2 (additional engine implementations: checkers, Go, word games) is non-trivial — each engine = its own `GameEngine` protocol implementation with valid-moves + win-detection + render. Out of single-wave scope; no forcing function blocks it but Captain has not commissioned the engine work | `recreation/metadata.py:1-14`, `recreation/service.py:42-75` (`_metadata`/`default_game`/`get_metadata`/`register_engine(metadata=)`), `events.py:232` (`RECREATION_GAME_REGISTERED`), `docs/development/roadmap.md:3040` (status `(partial — v1 ships GameMetadata + default_game preference + RECREATION_GAME_REGISTERED emit; spectators + holodeck integration deferred to AD-526d/e)`) |
| **AD-526d** | ❌ NO — shipped Wave 13 (Combo C, commit ffda515) | `recreation/preferences.py:24-82` (`GamePreferenceTracker.record_game`/`get_preferences`/`top_game_for`), `runtime.py:457-461` (`runtime.recreation_preference_tracker` public attribute + `set_event_callback(self.emit_event)` late-bind), `events.py:312` (`GAME_PREFERENCE_RECORDED`), `docs/development/roadmap.md:3041` (status `(complete)`) |
| **AD-526e** | ✅ YES — last buildable | spectator-registry read-side analytics surface; deferred from Combo C with the AD-526d docstring forcing function (`exposing the data-collection hook that AD-526e/f/g/h … will share` at `preferences.py:4-6`). Mirrors AD-526d's shape: in-memory dict + 2 EventTypes + `set_event_callback` late-bind + `runtime.recreation_spectator_registry` public attribute |
| **AD-526f** | ❌ NO — wholesale-deferred to AD-526f-i. Hard forcing function: `src/probos/holodeck/` package does NOT exist at HEAD (verified absent). AD-486 (Holodeck Birth Chamber) referenced as Holodeck-infra source-of-truth across 7+ ADs (AD-486, AD-509, AD-511c, AD-525d, AD-526f, AD-543, etc.) but no holodeck package exists yet. AD-526f cannot ship until AD-486 lands a `HolodeckService` surface. NOT a wave-70-buildable item | `Get-ChildItem src/probos -Directory` returns `creative`, `recreation`, `ward_room`, etc. — NO `holodeck` directory; `roadmap.md:3043` status `(planned, depends: AD-526a, Holodeck)` |
| **AD-526g** | ❌ NO — wholesale-deferred to AD-526g-i. Hard forcing function: AD-525 v1 (Wave 16) already ships the creative-output surface (`src/probos/creative/output_writer.py` with `CreativeOutputWriter`, `creative/skills_registry.py` with `CreativeSkillsRegistry`, `events.py:307-309` `CREATIVE_WORK_PUBLISHED`/`CREATIVE_SKILL_AFFINITY_QUERIED`). The Recreation-Creative-channel (`ward_room/channels.py:89` AD-526a default channel) is a separate concern from creative-output-publication. AD-526g would either duplicate AD-525 (DRY violation) or pivot to a thin Recreation→Creative-channel-bridge — neither is in v1 scope. Forcing function: AD-525b (Time Allocation) and/or AD-525d (Cultural Emergence Detection) need to land first to clarify which surface AD-526g extends | `creative/__init__.py:1-22` lists 4 public symbols; `events.py:307-309` confirms 2 EventTypes shipped under AD-525; `roadmap.md:3044` status `(planned, depends: AD-526a)` |
| **AD-526h** | ❌ NO — wholesale-deferred to AD-526h-i. Hard forcing function: `python-chess` is NOT in `pyproject.toml` (verified absent — Wave-70 dispatch checked). Adding a runtime dependency requires an explicit Captain decision and is not a combo-trivial line item; Elo-rating algorithm + PGN game recording + chess-specific board rendering is a 2-3 file standalone build (engine.py + ratings.py + tests for both) — too large for combo. AD-526h ships standalone after the dep decision | `pyproject.toml` does NOT list `python-chess`; `roadmap.md:3039` status `(planned, depends: AD-526a)`; AD-526h is the renumbered chess engine (originally tagged AD-526b in `decisions-era-4-evolution.md:2786` before Wave 8 / Wave 13 reshuffled the lettering) |

**Reframe verdict: ship AD-526e alone. Partially close #101 noting (2 shipped + 3 deferred-with-forcing-functions + 1 shipping-this-wave). The remaining work cannot land in a single combo prompt without exceeding the +14-test ceiling and either creating a runtime dependency or adding 3+ file packages.** This is the same Wave-10 architectural-honesty-over-scope pattern applied at AD-scoping (Wave 67 5→1, Wave 68 4→0, Wave 69 2→1, now Wave 70 6→1). Captain has been notified separately via the wave plan update; the dispatch document below is the build contract.

## Summary

ProbOS recreation games (`RecreationService` AD-526a) currently support exactly two participant roles per game: challenger and challenged. There is no surface for a third agent to observe a running game, post commentary about it, or react to a finished game. The AD-526d docstring explicitly names spectator commentary as one of the four siblings that will share the read-side analytics pattern (`preferences.py:4-6`), but no producer or store has been wired.

AD-526e v1 ships the missing analytics surface as a thin, in-memory, observation-only registry. Public API mirrors `GamePreferenceTracker` exactly: `add_spectator(game_id, agent_id) -> bool` (idempotent — returns True only on the first add per game/agent pair) / `remove_spectator(game_id, agent_id) -> bool` / `get_spectators(game_id) -> tuple[str, ...]` (frozen) / `record_commentary(game_id, agent_id, text) -> None` (best-effort emit) / `get_commentary(game_id) -> tuple[dict[str, Any], ...]` (frozen list of `{agent_id, text, timestamp}` dicts) / `clear_game(game_id) -> None` (called by the future cognitive-integration AD when a game ends — present in v1 only as a sweep helper exposed for tests) / `set_event_callback(emit_fn)` late-bind (Wave-5 convention #1, mirror `BilletRegistry` + `GamePreferenceTracker`).

**No service-side change** to `RecreationService`, `GameEngine`, `TicTacToeEngine`, or `WardRoomService`. **No new Pydantic config** (the registry is enabled by virtue of being constructed unconditionally, exactly mirroring AD-526d). **No producer wiring** — agents do NOT call `add_spectator` or `record_commentary` in v1; the cognitive integration is AD-526e-1.

**Deferred at the prompt level:**
- AD-526e-1 — proactive cognitive integration. New `[SPECTATE @callsign game_id]` and `[COMMENT game_id text]` action tags in `cognitive_agent.py`, extracted in `proactive.py`. Registers spectators on intent + records commentary as a side effect. Out of scope for v1: the registry's read-side surface needs to land first so the cognitive integration has a stable target. Forcing function: AD-526e v1 ships and `runtime.recreation_spectator_registry` is a public attribute.
- AD-526e-2 — `RecreationService.complete_game` calls `runtime.recreation_spectator_registry.clear_game(game_id)` to free spectator/commentary state when a game ends. Out of scope: this is a service-side wiring concern; v1 is observational and the test suite can call `clear_game` directly. Forcing function: AD-526e v1 ships and an end-of-game lifecycle observer is needed.
- AD-526e-3 — HXI rendering of spectator/commentary feed alongside the `GamePanel.tsx` (AD-526b). Pure UI integration, post-cognitive-integration AD. Forcing function: AD-526e-1 ships and commentary actually accumulates.
- AD-526e-4 — *(Commercial)* tenant-scoped spectator policy (per-mesh registry instance behind a tenant prefix). The OSS registry remains tenant-agnostic; the seam is the `runtime.recreation_spectator_registry` public attribute, which a commercial overlay can replace via a tenant-aware factory.

## Architect calls (Decision Log)

- **DLog #1 — Mirror AD-526d shape exactly.** The combo precedent is "ship analytics surface as standalone read-side, defer producers as -1/-2 children". AD-526d (`preferences.py`) is the authoritative pattern: in-memory dict, 1 EventType emit per record, late-bind `set_event_callback`, no Pydantic config, no startup/finalize sync-wirer (constructor-only wiring in `runtime.py`). AD-526e follows the same shape verbatim. Any deviation (Pydantic config, finalize-side wirer, sub-package layout) is a hard-stop.

- **DLog #2 — Two EventTypes, NOT one.** Spectator-add (`RECREATION_SPECTATOR_JOINED`) and commentary-record (`RECREATION_SPECTATOR_COMMENTARY`) are separate lifecycle moments — joining a gallery is a discrete signal that downstream consumers (Counselor agent, Hebbian routing) will weight differently from a per-comment signal. Removal does NOT emit (mirrors AD-526d, where `record_game` emits but no symmetric "record removed" event exists — removals are implicit via lack of subsequent records). EventType strings: `recreation_spectator_joined`, `recreation_spectator_commentary`. Verified collision-free against `events.py` at HEAD `66c89ff`.

- **DLog #3 — Idempotent `add_spectator` returns bool.** First add returns `True` and emits; duplicate add returns `False` and does NOT emit. Mirrors AD-477b `qualifications_registry.add_credential` shape. The bool return is the producer-side hook the future AD-526e-1 will use to decide whether to post a "@callsign joined the gallery" message in the Recreation channel.

- **DLog #4 — Module-level `_GAME_LOG_CACHE` not introduced.** v1 holds spectator + commentary state purely in instance dicts. No process-global caching. No persistence. No bounded-ring eviction in v1 (commentary list grows unbounded for the lifetime of a game; AD-526e-2 will trim on game completion via `clear_game`). The unbounded-growth window is bounded operationally by game duration (typical tic-tac-toe game = <30 moves = <30 commentary entries; checkers/chess later games will need a ring, deferred to AD-526e-1 when the producer side knows the actual write rate).

- **DLog #5 — `clear_game` exposed in v1 even without a producer.** Test #12 needs to assert that `clear_game(game_id)` drops spectators AND commentary. The method is small (4 lines) and is the natural pair to `add_spectator` — exposing it now keeps the API symmetric. Does not violate YAGNI: AD-526e-2 is the wiring AD, not a new-method AD.

- **DLog #6 — `record_commentary` swallows empty inputs.** When `agent_id`, `text`, or `game_id` is empty/whitespace-only, `record_commentary` returns silently and emits no event. Mirrors AD-526d `record_game` empty-suppress at `preferences.py:48-49`. The producer side (AD-526e-1) is allowed to call freely without pre-validating input.

- **DLog #7 — Tier-2 log-and-degrade on emit failure.** Both `add_spectator` and `record_commentary` wrap their emit in `try/except → logger.warning("AD-526e: ... emit failed", exc_info=True)`. Mirrors AD-526d `preferences.py:62-71`. The state-update side effects (dict mutation) are NOT wrapped — a `TypeError` from a non-string `agent_id` should fail loud and let the caller fix it; only event emission is best-effort.

- **DLog #8 — `get_spectators` returns `tuple[str, ...]`, NOT `set` or `list`.** Mirrors `qualifications_registry.list_credentials` shape and `RecreationService.get_active_games` shape. Tuple = frozen + ordered + safely returnable without defensive copy. Caller insertion order is preserved. AD-526e-1 will iterate this tuple to render "@callsign1, @callsign2 watching" in the gallery.

- **DLog #9 — `get_commentary` returns `tuple[dict[str, Any], ...]`.** Each entry is `{"agent_id": str, "text": str, "timestamp": float}`. Frozen tuple of frozen-dict-by-convention (caller MUST NOT mutate). Insertion order preserved. Timestamp is `time.time()` at the moment of `record_commentary` call. AD-526e-3 (HXI) will render these chronologically.

- **DLog #10 — `runtime.recreation_spectator_registry` public attribute, NOT property.** Constructor-set in `__init__` (mirror line 458 `runtime.recreation_preference_tracker`). Wave-5 convention #1: no leading underscore, no `set_*` setter, no async getter. Test fixture access pattern: `runtime.recreation_spectator_registry.add_spectator(...)`.

- **DLog #11 — Construction is unconditional in `runtime.py`.** No Pydantic enable flag. The registry is in-memory only and adds zero startup cost. Mirrors AD-526d construction at `runtime.py:457-461` — no `if config.recreation_preferences.enabled:` gate. Adding a config gate would create asymmetry with AD-526d and require a wave to remove later.

- **DLog #12 — `set_event_callback` called in-line at construction.** `runtime.py` block is exactly:
  ```python
  # --- Recreation Spectator Registry (AD-526e) ---
  from probos.recreation.spectators import SpectatorRegistry
  self.recreation_spectator_registry: SpectatorRegistry = SpectatorRegistry()
  self.recreation_spectator_registry.set_event_callback(self.emit_event)
  ```
  Line-for-line mirror of AD-526d's block at `runtime.py:457-461`.

- **DLog #13 — No new Pydantic config field, no `system.yaml` change, no `config/` migration.** The registry boots out of the box (zero-config-required principle from copilot-instructions.md). Adding a `RecreationSpectatorConfig` would create a 4th sibling for AD-526a/b/c/d and break the established pattern that "in-memory analytics surfaces don't need a config gate". Hard-stop on any test or source change that introduces config plumbing.

- **DLog #14 — Test count target +12 (window [+10, +14]).** Two EventType-existence tests + 12 behavioral tests = 14, but two of the 14 collapse into table-driven cases at Builder discretion. Floor +10 absorbs Builder folding two tests; ceiling +14 absorbs Builder splitting one boundary case in two. Test list:
   1. `test_event_type_recreation_spectator_joined_exists`
   2. `test_event_type_recreation_spectator_commentary_exists`
   3. `test_add_spectator_first_call_returns_true_and_emits`
   4. `test_add_spectator_duplicate_returns_false_and_does_not_re_emit`
   5. `test_remove_spectator_present_returns_true`
   6. `test_remove_spectator_absent_returns_false`
   7. `test_get_spectators_returns_frozen_tuple_in_insertion_order`
   8. `test_get_spectators_unknown_game_returns_empty_tuple`
   9. `test_record_commentary_stores_entry_and_emits_event`
   10. `test_record_commentary_empty_inputs_no_op`
   11. `test_get_commentary_returns_frozen_tuple_with_timestamp`
   12. `test_clear_game_drops_spectators_and_commentary`
   13. `test_emit_failure_logged_and_swallowed`
   14. `test_runtime_wires_recreation_spectator_registry_with_callback`

- **DLog #15 — `tests/test_ad526e_spectator_registry.py` is a NEW file.** Verified absent at HEAD `66c89ff` (no `test_ad526e*.py` file exists). Builder creates from scratch — no SEARCH/REPLACE on the test file.

- **DLog #16 — Phantom-API pre-check status.** Same recurring blocker as Waves 52–69 — `scripts/phantom-api-precheck.ps1` PowerShell parser error documented in user-memory. Manual verify-first pass at draft (10 verifying greps; all confirmed against HEAD `66c89ff`). Net-new symbols are intra-prompt-introduction (`SpectatorRegistry`, `RECREATION_SPECTATOR_JOINED`, `RECREATION_SPECTATOR_COMMENTARY`, `recreation_spectator_registry` runtime attribute, `_GAME_LOG_CACHE` is NOT introduced — DLog #4). Same FP class as Waves 27–69.

- **DLog #17 — Commercial-leak audit: clean.** AD-526e is OSS plumbing — one new module, one EventType pair, one runtime attribute, fourteen tests. The AD-526e-4 *(Commercial)* deferral names tenant-scoped variants; the OSS registry remains tenant-agnostic. Dispatch contains zero pricing, revenue model, customer counts, professional-services positioning, competitive analysis, GTM language, or "commercial overlay marketplace" wording. The reframe table cites only architectural state (which children shipped where, which is blocked on what forcing function). **Clean.**

- **DLog #18 — Issue #101 partial-close stance.** Comment on close: lists the six children with one-line status and source-of-truth pointers. Three of six have explicit forcing functions named (AD-486 for f, AD-525b/d for g, `python-chess` Captain decision for h). Two are already shipped (c partial, d full). One ships this wave (e). The six children are recreation-specific; closing the umbrella issue does not orphan any of them — each deferred child's forcing function is a separate Captain decision. **`gh issue close 101 --reason completed`** is the right verb.

## Builder workflow (standard)

1. **Pre-flight gate:** `pytest tests/ -q -n 4 --dist=loadfile` → confirm 11419 collected at HEAD `66c89ff`.
2. Apply Section 1 (`events.py` 2 new EventType lines). Run `pytest tests/test_events*.py -n 0 -q` if it exists; else proceed.
3. Apply Section 2 (`recreation/spectators.py` NEW file). No tests should regress yet — additive only.
4. Apply Section 3 (`runtime.py` ctor block + import). Run `pytest tests/test_runtime*.py tests/test_ad526*.py tests/test_recreation*.py -n 0 -q` to confirm zero regression on the recreation surface.
5. Apply Section 4 (NEW test file `tests/test_ad526e_spectator_registry.py`). Add the 14 tests one at a time; confirm each passes before adding the next.
6. **Final gate:** `pytest tests/ -q -n 4 --dist=loadfile` → expect 11431 (+12 net target; window [+10, +14] = [11429, 11433]).
7. **Update tracking:**
   - `PROGRESS.md` — append CLOSED paragraph (one entry covering AD-526e v1 + the partial-close stance for #101).
   - `docs/development/roadmap.md` — flip the AD-526e entry from `*(planned, depends: AD-526a)*` to `*(complete via AD-526e v1, Wave 70 — observational SpectatorRegistry; cognitive integration deferred to AD-526e-1, end-of-game cleanup wiring deferred to AD-526e-2, HXI rendering deferred to AD-526e-3)*`.
   - `prompts/wave-plan.yaml` (id 70) — `status: done`. Note in the entry: "Reframed combo → single AD; 2 of 6 already shipped (c partial, d full), 3 of 6 deferred with forcing functions (f→AD-486 Holodeck, g→AD-525b/d, h→python-chess dep decision), 1 of 6 shipping (e)."
   - GH issue #101 — close with comment listing the six child statuses + this commit hash + the three forcing functions.

## Hard-stop conditions

1. Test count delta lands outside [+10, +14]. → Triage which class over/under-shot.
2. Existing AD-526a / AD-526b / AD-526c / AD-526d tests fail. → The new module is shadowing or import-ordering-poisoning the existing recreation surface. Hard-stop and re-read DLog #1.
3. Real working-tree changes appear in source files NOT named in this dispatch (`src/probos/events.py`, `src/probos/recreation/spectators.py`, `src/probos/runtime.py`, `tests/test_ad526e_spectator_registry.py`, plus tracking files). → Hard stop, surface to Captain.
4. Any source change to `src/probos/recreation/service.py`, `src/probos/recreation/engine.py`, `src/probos/recreation/metadata.py`, `src/probos/recreation/preferences.py`, `src/probos/recreation/__init__.py`, `src/probos/cognitive/cognitive_agent.py`, or `src/probos/cognitive/proactive.py`. → AD-526e v1 does NOT modify these files (DLog #1, DLog #5, AD-526e-1 deferral). Hard-stop.
5. Any new Pydantic config field, any change to `src/probos/config.py`, any change to `config/system.yaml`, or any new `*Config` class. → DLog #11, DLog #13. Hard-stop.
6. Any change to `src/probos/startup/finalize.py` (the registry is constructor-wired, NOT finalize-wired — DLog #11). → Hard-stop.
7. Any test boots a real `ProbOSRuntime` to validate Section 3 wiring. → Use `MagicMock` per Wave 13/66/67 fixture precedent. Full-runtime fixtures explode wave-gate runtime budget. Test #14 instantiates `SpectatorRegistry()` directly + verifies the runtime construction by asserting `hasattr(runtime, 'recreation_spectator_registry')` against a mock-runtime fixture or by reading the runtime.py source line directly. Hard-stop on any `ProbOSRuntime(...)` boot in this test file.
8. The `clear_game` method is omitted, OR the `set_event_callback` late-bind is replaced with a constructor kwarg, OR the `_GAME_LOG_CACHE` module-level cache from DLog #4 is introduced. → DLog #4, #5, #12 violations. Hard-stop and re-read.
9. Section 1 inserts the new EventTypes anywhere other than directly below `RECREATION_GAME_REGISTERED` at `events.py:232` OR introduces a NEW `# AD-526e` section comment block. → Mirror AD-526c sibling placement; do NOT create a new section header. Hard-stop.
10. The Builder elects to ship AD-526f, AD-526g, or AD-526h "while we're here" — even partially, even as a stub. → Reframe is hard. Hard-stop.

## Acceptance criteria

1. Full gate passes at 11431 ± 2.
2. All Section 1–4 SEARCH/REPLACE blocks applied byte-for-byte as specified.
3. 14 new tests in `tests/test_ad526e_spectator_registry.py` all pass.
4. No file outside the dispatch's named set is modified (other than tracking files: `PROGRESS.md`, `docs/development/roadmap.md`, `prompts/wave-plan.yaml`).
5. The Builder build report cites the test count delta + the seven "what this AD does NOT change" verifications (no edits to `service.py`, `engine.py`, `metadata.py`, `preferences.py`, `recreation/__init__.py`, `cognitive_agent.py`, `proactive.py`).
6. The Builder build report explicitly cites that AD-526f/g/h were NOT shipped this wave and names the three forcing functions (AD-486 Holodeck for f, AD-525b/d for g, `python-chess` Captain decision for h).
7. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-05, HEAD `66c89ff`)

```
grep -n "RECREATION_GAME_REGISTERED|GAME_PREFERENCE_RECORDED" src/probos/events.py
  232:  RECREATION_GAME_REGISTERED = "recreation_game_registered"  # AD-526c
  312:  GAME_PREFERENCE_RECORDED = "game_preference_recorded"  # AD-526d
  (collision-free for net-new RECREATION_SPECTATOR_JOINED + RECREATION_SPECTATOR_COMMENTARY)

grep -n "recreation_preference_tracker" src/probos/runtime.py
  458:  self.recreation_preference_tracker: GamePreferenceTracker = (
  461:  self.recreation_preference_tracker.set_event_callback(self.emit_event)
  (pattern AD-526e ctor block must mirror)

ls src/probos/recreation/
  __init__.py  engine.py  metadata.py  preferences.py  service.py
  (NO spectators.py — net-new file confirmed)

grep -n "exposing the data-collection hook that AD-526e" src/probos/recreation/preferences.py
  4:  exposing the data-collection hook that AD-526e/f/g/h (spectator
  (forcing-function evidence: AD-526d explicitly names AD-526e as the next sibling)

ls src/probos/  (filtered for creative|holodeck|recreation)
  creative/  recreation/
  (NO holodeck/ directory — AD-526f forcing function confirmed: depends on AD-486 Holodeck infra that does not exist)

grep -n "python-chess|python_chess" pyproject.toml
  (no matches — AD-526h forcing function confirmed: dependency not present)

grep -n "class CreativeOutputWriter|class CreativeSkillsRegistry" src/probos/creative/
  output_writer.py: class CreativeOutputWriter
  skills_registry.py: class CreativeSkillsRegistry
  (AD-526g overlap with AD-525 confirmed)

grep -rn "test_ad526e" tests/
  (no matches — net-new test file confirmed)

grep -n "RECREATION_GAME_REGISTERED\|GAME_PREFERENCE_RECORDED" docs/development/roadmap.md
  3040: AD-526c partial
  3041: AD-526d complete
  3042: AD-526e planned
  3043: AD-526f planned (depends: Holodeck)
  3044: AD-526g planned
  3039: AD-526h planned
  (roadmap state confirms reframe table)

grep -n "AD-526e\|AD-526f\|AD-526g\|AD-526h" PROGRESS.md
  (no completion entries — reframe table confirms only AD-526c/d are PROGRESS.md-recorded)
```

---

## Per-AD prompt path

`prompts/ad-526e-spectator-registry.md`
