# WAVE 74 DISPATCH — AD-571b + AD-571c v1 Agent Tier Trust Separation (Phase 2 + Phase 3)

**Wave id:** 74
**Single per-AD prompt:** `prompts/ad-571b-c-tier-trust-v1.md` (combined backend, shared tier_registry wiring)
**Closes:** GH issue #21 (AD-571a-c umbrella)
**Baseline test count:** 11463 (HEAD `4d0242a`, post-Wave-73) → expected **11479** (+16 net), window **[+14, +20]** = [11477, 11483]
**HEAD at draft:** `4d0242a`, working tree clean
**Builder:** required

## Already-shipped vs in-scope vs deferred

**AD-571a — already shipped at HEAD `4d0242a`** (no Wave-74 work):
- `AgentTier` enum + `AgentTierRegistry` at `src/probos/substrate/agent_tier.py:8,16`
- `AgentTierConfig` at `src/probos/config.py:2202` (crew_types + core_types)
- `TrustNetwork.all_scores(crew_only: bool = False)` parameter at `consensus/trust.py:453` *(note: parameter is named `crew_only`, not the `is_crew` named in the GH issue body — semantic spirit shipped, name diverged)*
- CORE-tier `record_outcome()` skip at `consensus/trust.py:354-358`
- `HebbianRouter.set_tier_registry()` at `mesh/routing.py:72`, `EmergenceMetrics.set_tier_registry()` at `cognitive/emergence_metrics.py:363`
- Tier-registry finalize wiring at `startup/finalize.py:853-862`
- 15 AD-571 tests at `tests/test_ad571_tier_separation.py`
- BF-252 (mock public+private name) closed in same wave family

**Wave-74 in-scope (full v1, no further deferral):**

- **AD-571b v1 — Operational Status Model (backend only)**
  - New `substrate/operational_status.py` — `OperationalStatus` enum (`AVAILABLE` / `DEGRADED` / `OFFLINE` / `MAINTENANCE`) + `ReliabilityMetrics` frozen dataclass + `OperationalStatusTracker` (in-memory, ring-buffered per-agent call records; computes success_rate, p50/p95 latency, error_count, status from rolling window).
  - Tracker injected into runtime alongside tier_registry; only records calls for non-crew agents (utility + core_infrastructure). Crew agents go through Rank, not status.
  - Public API: `tracker.record_call(agent_id, success, latency_ms)`, `tracker.get_status(agent_id) -> OperationalStatus`, `tracker.get_metrics(agent_id) -> ReliabilityMetrics | None`.
  - `OperationalStatusConfig` Pydantic model in `config.py` (window size, p95 latency threshold for DEGRADED, error_count threshold for OFFLINE, sample_window_size). All defaults — zero config required.
  - `runtime.operational_status_tracker` public attribute. `startup/finalize.py` wires the tracker the same way `_populate_agent_tiers` already wires `_tier_registry`.
  - **Single mandatory call site for v1:** `HttpFetchAgent.run()` records every fetch outcome with latency. This proves the wiring; the full call-site sweep is AD-571b-i.

- **AD-571c v1 — Hebbian Scope Reduction (backend, no HXI)**
  - New `MeshConfig.hebbian_social_decay_rate: float = 0.999` (slow decay, social bonds persist) alongside the existing `hebbian_decay_rate: float = 0.995` at `config.py:129` (used for intent routing).
  - `HebbianRouter.__init__` takes a new `social_decay_rate` parameter; default falls back to the existing `decay_rate` so behavior is unchanged when not provided.
  - `HebbianRouter.decay_all()` applies per-`rel_type` decay rate: `REL_INTENT` / `REL_AGENT` / `REL_BUILDER_VARIANT` / `REL_STRATEGY` use `decay_rate`; `REL_SOCIAL` uses `social_decay_rate`.
  - `HebbianRouter.record_interaction()` — when `tier_registry` is set AND `rel_type == REL_INTENT` AND **both** source and target tiers are `UTILITY`, return `0.0` without recording (utility-utility prune). CORE_INFRASTRUCTURE pairs are unaffected (tools may still route to system agents). Crew-as-source or crew-as-target always records.
  - Runtime construction at `runtime.py:304` passes `social_decay_rate=self.config.mesh.hebbian_social_decay_rate`.

**Deferred (with explicit forcing functions, GH-tracked at close-comment time):**

- **AD-571b-i — Rank.from_trust call-site migration.** 20+ existing call sites of `Rank.from_trust()` across `agent_onboarding.py`, `ward_room_router.py` (3 sites), `proactive.py` (4 sites), `runtime.py` (2 sites), `ontology/service.py`, `cognitive_agent.py` (3 sites), `commands/commands_tool_access.py`. Most are already in code paths guarded by `is_crew_agent()` (verified in `agent_onboarding.py:195,289,385`); the remainder need a guarded audit. Wave-10 lesson: 6+ existing call sites of any deprecated method → defer. Forcing function: enumerate call sites with grep, classify each as crew-guarded / utility-guarded / mixed, then migrate consumers in a sub-AD. *Not blocking AD-571b backend.*
- **AD-571b-ii — HXI surfacing of Operational Status.** HXI crew roster needs to render `OperationalStatus` for utility agents and `Rank` for crew. Per copilot-instructions HXI fragility note ("InstancedMesh raycasting breaks if instance count changes", "any change to agents.tsx or CognitiveCanvas.tsx can break hover/click"), every UI change is risk-priced and requires its own AD with a manual visual review gate. Forcing function: AD-571b backend must ship public `runtime.operational_status_tracker` first; UI then has a stable read surface.
- **AD-571c-i — Differential decay landed on a clean event surface.** Differential decay is a behavioral change to a system that's been at one decay rate since AD-264. v1 ships the new path under the new config field but leaves the existing default `social_decay_rate` falling back to `decay_rate` until a benchmark exists. Forcing function: an AD-557 emergence-metric benchmark before flipping the v1 default to `0.999`.
- **AD-571c-ii — Full call-site sweep of `record_interaction` for utility-utility pruning.** v1 only prunes the `REL_INTENT` path. `REL_AGENT` (verification), `REL_BUILDER_VARIANT`, `REL_STRATEGY` continue to record across tier boundaries because their semantics are not "social/collaborative" in the AD-571c sense — they are pipeline-correctness signals. Forcing function: explicit per-rel_type semantic review.

**No commercial leak.** AD-571b/c are OSS plumbing — agent-tier discipline is core mesh hygiene, not a paid SKU. Commercial overlay does not touch trust internals.

## Architect calls (Decision Log)

The full 12-item decision log lives in `prompts/ad-571b-c-tier-trust-v1.md` Section "Architect calls". Highest-risk items repeated for Builder pre-flight:

- **DLog #1 — `OperationalStatus` lives in `substrate/`, not `consensus/`.** Status is a substrate-tier concern (agent health/availability), not a consensus-tier concern (trust). Mirrors `agent_tier.py` placement.
- **DLog #2 — In-memory tracker only, no SQLite in v1.** Reliability metrics are runtime-observable, regenerable from event_log. Persistence is AD-571b-iii if ever needed. Avoids new ConnectionFactory wiring this wave.
- **DLog #3 — Tracker records only non-crew agents.** Crew get Rank via trust; mixing the two surfaces would force every consumer to pick a side. Tracker silently no-ops for `tier_registry.is_crew(agent_id) is True`.
- **DLog #4 — Single call site for v1 (`HttpFetchAgent.run()`).** Proves the wiring in production code without a 30-call-site audit. AD-571b-i fans out.
- **DLog #5 — `Rank.from_trust()` is NOT modified in this wave.** 20+ call sites; Wave-10 6+ rule. Returning `None` for non-crew is breaking-change-on-first-commit anti-pattern. Sibling helper `Rank.from_trust_for_agent()` is also deferred — adds a public API the consumer side hasn't asked for yet.
- **DLog #6 — `social_decay_rate` defaults to fall back to `decay_rate`.** Behavior-equivalent at the new field's default. Captain can flip the YAML to `0.999` once benchmarks land. v1 ships the dial, not the new default.
- **DLog #7 — Utility-utility prune is `REL_INTENT`-only.** REL_AGENT, REL_BUILDER_VARIANT, REL_STRATEGY are not social weights and have legitimate utility-to-utility semantics (red-team-verifies-tool, builder-variant rewires, strategy-routes-to-tool). Pruning all rel_types is a separate semantic call.
- **DLog #8 — CORE_INFRASTRUCTURE is exempt from utility-utility prune.** Tools-routing-to-event_log and similar are valid intent edges; only utility-pair-of-tools is noise.
- **DLog #9 — Tracker wiring at `startup/finalize.py` next to existing `_populate_agent_tiers`.** Same precedent block as AD-571a; do not invent a new lifecycle hook.
- **DLog #10 — `OperationalStatusConfig` is a top-level `SystemConfig` field, not nested under `MeshConfig`.** Operational status is a substrate concern; mesh config is for routing. Mirrors `AgentTierConfig` placement at `config.py:2202`.
- **DLog #11 — No HXI / router changes this wave.** AD-571b-ii forcing function is the public tracker surface.
- **DLog #12 — Commercial-leak audit: clean.** No pricing tier, no enterprise feature, no go-to-market language in either prompt or any source comment.

## Builder workflow (standard)

1. **Pre-flight gate:** `pytest tests/ -q -n 4 --dist=loadfile` → confirm 11463 collected at HEAD `4d0242a`. Working tree clean.
2. **Apply Section 1** (`config.py` — `OperationalStatusConfig` Pydantic class + `MeshConfig.hebbian_social_decay_rate` field + `SystemConfig.operational_status` field). Run `pytest tests/test_config*.py -n 0 -q` → no regressions; new fields default-valid.
3. **Apply Section 2** (NEW `src/probos/substrate/operational_status.py` — enum + frozen dataclass + tracker). No existing tests touch this file; nothing to regress.
4. **Apply Section 3** (`mesh/routing.py` — new `social_decay_rate` ctor param + per-rel_type decay in `decay_all()` + utility-utility prune guard in `record_interaction()`). Run `pytest tests/test_*hebbian* tests/test_*routing* tests/test_ad571* -n 0 -q` → existing AD-571a tests must still pass; the prune guard only fires when both endpoints are UTILITY.
5. **Apply Section 4** (`runtime.py:304` — pass `social_decay_rate` to `HebbianRouter()` ctor + add `self.operational_status_tracker = OperationalStatusTracker(...)` next to `self.hebbian_router`). Run `pytest tests/test_runtime*.py -n 0 -q`.
6. **Apply Section 5** (`startup/finalize.py:853-862` — wire `runtime.operational_status_tracker.set_tier_registry(registry)` next to existing trust/emergence/router wiring). Run `pytest tests/test_*finalize* tests/test_ad571* -n 0 -q`.
7. **Apply Section 6** (`agents/http_fetch.py` — record_call after each fetch with latency_ms; defensive `getattr(self._runtime, "operational_status_tracker", None)` because the sandbox runtime is `None` per `repo-notes`). Run `pytest tests/test_*http_fetch* -n 0 -q`.
8. **Apply Section 7** (NEW `tests/test_ad571bc_tier_trust.py` — 16 tests, see per-AD prompt). Add tests one at a time; confirm each passes before adding the next.
9. **Final gate:** `pytest tests/ -q -n 4 --dist=loadfile` → expect 11479 (+16 net target; window [11477, 11483]).
10. **Update tracking:**
    - `PROGRESS.md` — append CLOSED paragraph for AD-571b v1 + AD-571c v1.
    - `docs/development/roadmap.md` — flip AD-571 entry status from `*(planned, OSS, depends: AD-398)*` to `*(complete via AD-571a Wave 60-family + AD-571b/c v1 Wave 74; HXI surfacing AD-571b-ii deferred per HXI fragility, Rank.from_trust migration AD-571b-i deferred per Wave-10 6+ rule, full rel_type prune AD-571c-ii deferred per per-rel_type semantic review)*`.
    - `prompts/wave-plan.yaml` (id 74) — `status: done`.
    - GH issue #21 — close with summary listing AD-571a (already shipped, 15 tests), AD-571b v1 (OperationalStatus + tracker + HttpFetchAgent call site), AD-571c v1 (per-rel_type decay + utility-utility prune), four deferred children with their forcing functions, and this commit hash.

## Hard-stop conditions

1. Test count delta lands outside [+14, +20]. → Triage which Section over/under-shot.
2. Existing AD-571a tests at `tests/test_ad571_tier_separation.py` regress. → Section 3 prune guard logic likely catches a tier pair it shouldn't (CORE_INFRASTRUCTURE confusion). Re-verify the `AgentTier.UTILITY` check is exact-match, not membership.
3. Real working-tree changes appear in source files NOT named in this dispatch (`src/probos/config.py`, `src/probos/substrate/operational_status.py` (NEW), `src/probos/mesh/routing.py`, `src/probos/runtime.py`, `src/probos/startup/finalize.py`, `src/probos/agents/http_fetch.py`, `tests/test_ad571bc_tier_trust.py` (NEW), plus tracking files). → Hard stop, surface to Captain.
4. Any source change to `src/probos/crew_profile.py` (Rank.from_trust). → DLog #5 violation. Hard-stop.
5. Any source change to `src/probos/consensus/trust.py`. → AD-571a is already shipped here; v2 wave does not touch trust.py. Hard-stop.
6. Any new SQLite schema, ConnectionFactory wiring, or async start()/stop() lifecycle on `OperationalStatusTracker`. → DLog #2 violation. Hard-stop.
7. Any HXI / `ui/` / `routers/` change. → DLog #11 violation; AD-571b-ii forcing function. Hard-stop.
8. Any change to `Rank.from_trust()` call sites in `agent_onboarding.py`, `ward_room_router.py`, `proactive.py`, `ontology/service.py`, `cognitive/cognitive_agent.py`, `commands/commands_tool_access.py`, or `runtime.py:876,1033`. → AD-571b-i out of scope. Hard-stop.
9. Test boots a real `ProbOSRuntime` to validate Section 5 wiring. → Use `MagicMock` per Wave 13/66/67/68/69/70/72/73 fixture precedent. Hard-stop on any `ProbOSRuntime(...)` boot in this test file.
10. The Builder elects to ship AD-571b-i, AD-571b-ii, AD-571c-i (default flip), or AD-571c-ii "while we're here". → Out of scope. Hard-stop.

## Acceptance criteria

1. Full gate passes at 11479 ± 2 (target +16; window [11477, 11483]).
2. All Section 1–7 SEARCH/REPLACE / CREATE blocks applied byte-for-byte as specified.
3. 16 new tests in `tests/test_ad571bc_tier_trust.py` all pass.
4. No file outside the dispatch's named set is modified (other than tracking files).
5. The Builder build report cites the test count delta + the ten "what this AD does NOT change" verifications.
6. The Builder build report explicitly cites which deferred children remain (AD-571b-i, AD-571b-ii, AD-571c-i, AD-571c-ii) and what their forcing functions are.
7. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-05, HEAD `4d0242a`)

The full 18-item verify-first table lives in the per-AD prompt at `prompts/ad-571b-c-tier-trust-v1.md` "Verified Against Codebase" footer. Highest-risk anchors repeated:

```
grep -n "class AgentTier" src/probos/substrate/agent_tier.py
  8:class AgentTier(StrEnum):
  (DLog #1: substrate placement precedent confirmed)

grep -n "REL_SOCIAL" src/probos/mesh/routing.py
  30:REL_SOCIAL = "social"  # agent_id → agent_id (AD-453 Ward Room interactions)
  (DLog #6/#7: rel_type partition already exists; v1 only adds decay rate variance + intent-only prune)

grep -n "set_tier_registry" src/probos/startup/finalize.py
  853:    if trust and hasattr(trust, "set_tier_registry"):
  854:        trust.set_tier_registry(registry)
  857:    if emergence and hasattr(emergence, "set_tier_registry"):
  858:        emergence.set_tier_registry(registry)
  861:    if router and hasattr(router, "set_tier_registry"):
  862:        router.set_tier_registry(registry)
  (DLog #9: precedent block; tracker wiring inserts after line 862)

grep -n "hebbian_decay_rate" src/probos/config.py
  129:    hebbian_decay_rate: float = 0.995
  (Section 1 anchor; new social_decay_rate slots in immediately below)

grep -n "self.hebbian_router = HebbianRouter(" src/probos/runtime.py
  304:        self.hebbian_router = HebbianRouter(
  (Section 4 anchor)

grep -n "def from_trust" src/probos/crew_profile.py
  38:    def from_trust(cls, trust_score: float) -> "Rank":
  (DLog #5: NOT modified this wave)

grep -c "Rank.from_trust" src/probos/**/*.py tests/**/*.py
  20+ call sites — Wave-10 6+ deferral rule applies.
  (Defers AD-571b-i call-site migration.)
```
