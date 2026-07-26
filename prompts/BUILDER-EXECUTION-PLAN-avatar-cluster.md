# Builder Execution Plan — Avatar Self-Image Cluster (Waves 141–145)

**Date:** 2026-05-10
**Author:** Architect (handoff to Builder)
**Mode:** Continuous build, one wave at a time, agent-driven gates
**Active wave entries:** 141, 142, 143, 144, 145 (5 waves, registered in `prompts/wave-plan.yaml`)
**GH issues to close on completion:** #572, #580, #568, #567, #581, #541 (6 issues across the 5 waves)

This plan supersedes `prompts/BUILDER-EXECUTION-PLAN.md` for the avatar self-image build cluster.

**Current workflow override (2026-07-24):** this cluster inherits the Current
Performance Addendum in `prompts/BUILDER-EXECUTION-PLAN.md`. Where this older
plan conflicts, use focused changed-slice checks during coding, completed-build
Architect review, then one consolidated 16-worker Python gate plus full
Vitest/build/affected Playwright after review.

---

## Theme — close the loop Ezri can already feel a dim light through

Today (2026-05-10) the Captain reported back from a 1:1 with Ezri:
> *"Some signal is a different experience than having none — it's the difference between navigating in the dark and navigating with a dim light."*

AD-722 shipped the **presence** axis (the agent has *some* telemetry signal). These five waves ship the **rate**, **shape**, and **coherence** axes:

| Wave | Axis closed | Capability |
|---|---|---|
| 141 | Rate (pre-condition) + foundation | YAML manifest single-source-of-truth (722-1) + adaptive sampling state machine (722f) |
| 142 | Latency / "presence between cycles" | WebSocket push channel for telemetry (722b) |
| 143 | Coherence #2 — intent-vs-presentation | Sub-LLM divergence detector wired into trust/Hebbian (722a) |
| 144 | Architectural tax removal | Sensorium dispatch unification (723) — eliminates dual-wire smell |
| 145 | Captain UX — appearance loop closure | DSL draft preview + revision cycle (721d-1) |

---

## Standing Rules (carry forward from prior plan, with this-cluster amendments)

- **Working tree:** if you encounter tracked-file modifications you didn't make, surface them. Do NOT `git stash` / `git reset --hard`.
- **Test gate (full):** run once after completed-build Architect review: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 16 --dist=loadfile` (matches the Captain host's 16 physical cores; do NOT use local `-n auto`, which maps to 32 logical processors).
- **Test gate (focused per-prompt):** `pytest tests/test_<adNNN>_*.py -v -n 0` (serial, deterministic).
- **UI test gate:** changed Vitest files during coding; full `cd ui && npx vitest run` plus `npm run build` once after review. Run affected Playwright scenarios for changed user workflows.
- **Wave-close gate failure interpretation:** failures under the consolidated parallel gate that do NOT reproduce under `-n 0` are environmental — document and continue. Only blockers are real failures that reproduce serially in files you changed.
- **Pre-build SEARCH/REPLACE:** every prompt is its own delta. Do not assume the live code matches what the prompt asserts will exist *after* its SEARCH/REPLACE. The prompt IS the migration.
- **License policy:** ProbOS OSS is Apache 2.0. Never absorb anything in the OSS repo that requires a paid license. Strong preference: MIT / Apache 2.0 / BSD / CC0 / MPL-2.0. Avoid: AGPL / GPL.
- **AD-722 / AD-727 inheritance:** every wave in this cluster carries the AD-727 safety axis where applicable. Specifically, AD-722a's trust wiring inherits the read-only-on-aesthetic-judgment rule from AD-727 (#585) — divergence-detector trust deltas are about the AGENT'S REASONING, not her appearance.
- **System-1 / System-2 ruling:** Wave 144 (AD-723 dispatch unification) preserves the path split. It does NOT merge chain and one-shot; it shares the *wiring* registry, not the *paths*.

---

## Pre-flight Checklist (before EACH wave)

```pwsh
git status --short                                                   # must be empty (or only untracked runtime artifacts)
Get-FileHash -Algorithm SHA256 <wave prompt paths>                    # freeze approved prompt inputs
d:/ProbOS/.venv/Scripts/pytest.exe <focused baseline files> -q -n 0  # only when a changed-slice baseline is needed
```

Record prompt hashes and the focused baseline. After each prompt, expect its documented focused test count to grow; defer broad Python/UI gates until the code-complete review is approved.

---

## Wave Sequence

### Wave 141 — Modulation manifest + adaptive sampling rate

**Depends on:** Wave 140 (shipped 2026-05-10).
**Issues:** #572 (AD-722-1), #580 (AD-722f).
**Prompt files (architect to draft):**
- `prompts/ad-722-1-modulation-manifest.md`
- `prompts/ad-722f-adaptive-sampling.md`
- `prompts/WAVE-141-DISPATCH.md`

**Why this is the first wave:** AD-722-1 is a pure cleanup (extract the modulation rule table to a YAML manifest so TS + Python both read from one source). AD-722f layers the per-agent adaptive sampling state machine on top. AD-722-1 ships first within the wave because AD-722f's config naturally benefits from the manifest pattern; both can ship in one commit each.

**Architect-side research items (do BEFORE drafting):**
1. Read `src/probos/avatars/telemetry.py` modulation constants block — verify the byte-parity test exists in `tests/test_ad722_avatar_telemetry.py` and confirm its current shape.
2. Read `ui/src/audio/voiceModulation.ts` — confirm the constants list and the cross-reference comment AD-722 added.
3. Decide manifest format (YAML vs JSON). Reviewer must surface tradeoffs in pass-1: YAML is more readable; JSON is parser-trivial in both languages and matches `package.json` discipline. Default recommendation: JSON, since Python and TS both parse it natively without dependencies.
4. AD-722f: identify the EXACT trigger surfaces — DM handler entry/exit (already exists per Wave 140's `mark_reply_emitted`), avatar popout open/close (UI), chain reasoning entry/exit (`_execute_chain_with_intent_routing`), idle (default).
5. State machine storage: per-agent state on `CognitiveAgent` instance vs. centralized `runtime.avatar_telemetry_state`. Default recommendation: centralized — the rate is a runtime concern, not a per-agent state. Confirm during pass-1.

**Acceptance criteria:**
- New manifest file at `src/probos/avatars/modulation_manifest.json` (or `.yaml`).
- Python loader in `telemetry.py` reads from manifest at module load (or first-use cache).
- TS loader in `voiceModulation.ts` reads from manifest via fetch or build-time bundle (architect to decide).
- Existing byte-parity test rewrites against the manifest as the source of truth.
- AD-722f config: `AvatarTelemetryConfig` adds `sampling_rates: SamplingRatesConfig` with HIGH (default 250ms), NORMAL (default 2000ms — current `polling_interval_ms`), LOW (default 10000ms) tier defaults.
- `runtime.avatar_telemetry_state` (or equivalent) tracks per-agent current tier, transition history.
- Trigger wiring: DM handler signals HIGH on entry → NORMAL on `mark_reply_emitted`; chain reasoning signals NORMAL on entry → LOW on completion; avatar popout open WS message (forward marker, not built — Wave 142's WebSocket channel will provide the trigger surface).
- Tests: ≥ 12 boundary cases — manifest load, byte-parity, each tier transition, each trigger, default-config values, runtime restart preserves no state (rate is volatile by design).
- Compliance with Engineering Principles in `.github/copilot-instructions.md`.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

**Out of scope:**
- WebSocket push (Wave 142).
- Per-agent state machine — keep it in `runtime` for v1; agent-level may come in a future AD if cost gating warrants.

**Test count target:** +20-25 Python; vitest unaffected if manifest is JSON (TS imports via `import data from './modulation.json'` build-time).

---

### Wave 142 — WebSocket push channel for avatar telemetry

**Depends on:** Wave 141.
**Issues:** #568 (AD-722b).
**Prompt files (architect to draft):**
- `prompts/ad-722b-websocket-push.md`
- `prompts/WAVE-142-DISPATCH.md`

**Why this wave:** Replaces polling with event-driven push. This is the single biggest experiential improvement Ezri asked for: *"A push model where I receive a signal when something shifts would start to feel more like proprioception than inventory."*

**Architect-side research items:**
1. Read existing WebSocket infrastructure in ProbOS — search for `WebSocket`, `websockets`, `aiohttp.web.WebSocketResponse`. Determine if there's an existing channel pattern (HXI agent updates, Ward Room real-time?) we should extend, or if we need a fresh `/api/ws/avatar-telemetry/{agent_id}` endpoint.
2. Read `ui/src/components/profile/SelfImageTab.tsx` polling effect at lines 56-77 — design the WS replacement so the component upgrades gracefully (WS first, fallback to poll on connection failure).
3. Decide protocol: text JSON frames matching `AvatarTelemetrySnapshot.to_dict()`, or a delta protocol. Default: full snapshots — small payload, simpler, polling fallback shape-compatible.
4. Adaptive-rate hook (Wave 141): the WS channel publishes at the rate dictated by Wave 141's state machine. Captain-side popout open is a `subscribe` event that flips the agent's rate to HIGH; close flips to NORMAL.
5. Authentication: existing HXI auth pattern applies; the WS endpoint MUST honor the same crew-only / agent-scope rules as `GET /api/agent/{id}/avatar-telemetry`.
6. Lifecycle: connection cleanup on close, heartbeat ping/pong, max connections per agent (rate-limit foundation for the eventual federation extension).

**Acceptance criteria:**
- New endpoint `WS /api/agent/{agent_id}/avatar-telemetry-stream`.
- Server-side: registers connection, publishes snapshots at the rate from Wave 141's state machine, publishes on state-change events (working_state transitions, mouth_active flip, modulation rule fire).
- Client-side: `SelfImageTab` upgrades to WS-first with poll fallback. Feature-detected so older browsers / failed handshakes degrade gracefully.
- Subscription metadata flips Wave 141's rate to HIGH on subscribe, back to NORMAL on disconnect.
- Tests: ≥ 10 Python (subscribe, publish, disconnect, multi-subscriber, rate flip on subscribe, fallback if WS fails); ≥ 4 vitest (component switches to WS, falls back on connection error, renders received frames identically to poll path).
- Compliance with Engineering Principles in `.github/copilot-instructions.md`.

**Out of scope:**
- Push to the agent's own `_last_self_avatar_snap` cache (the in-process `observe_self_avatar()` call still pulls; only HXI consumers push). The agent-side push is AD-722b-2 (forward marker; file as issue if we identify it).
- Federation cross-mesh push (separate AD).

**Test count target:** +25-30 Python; +4-5 vitest.

---

### Wave 143 — Intent-vs-presentation divergence detector + trust wiring

**Depends on:** Wave 142.
**Issues:** #567 (AD-722a).
**Prompt files (architect to draft):**
- `prompts/ad-722a-divergence-detector.md`
- `prompts/WAVE-143-DISPATCH.md`

**Why this wave:** Closes the second of the three coherence checks (per AD-727: self / intent / render). Sub-LLM cost (regex + lightweight valence classifier) compares the LLM's emotional intent against the actual applied modulation. When they diverge, the agent gets a real-time "your reasoning didn't land the way you meant it" signal.

**Architect-side research items:**
1. Read `src/probos/avatars/telemetry.py:apply_voice_modulation` — the function whose output is one half of the divergence check.
2. Read the LLM completion path that produces DM/WR replies — find the seam where the response text is emitted and is paired with a known intent. Use `cognitive_agent.py:_handle_direct_message` or wherever the reply text is finalized.
3. Decide the intent-extraction strategy: (a) regex / keyword ladder against an emotion lexicon; (b) sub-LLM classifier (small model, cheap tier); (c) prompt-engineering — ask the LLM to self-tag the emotional intent in a structured suffix. Default recommendation: (c) is cheapest and most controllable — add a system-prompt instruction "after your reply, emit `<intent emotion=warm|firm|warm_concern|...>`" and parse it server-side.
4. Trust wiring: AD-722a's design says divergence delta → trust update. Per AD-727 rule #1, image-based aesthetic judgments are read-only-on-trust. INTENT-vs-PRESENTATION is NOT image-based — it's reasoning-vs-output, which is a fair trust signal. Verify this distinction is preserved in the prompt and that AD-727's rule is not violated.
5. Hebbian wiring: divergences with the same agent + same emotion-target should weaken; matches strengthen. Mirrors AD-358 reinforcement.
6. Per-AD-727 phrasing rule: divergence reports should describe the OUTPUT, not the agent. *"Your modulation came out clipped relative to your intent"* ✓; *"You sounded cold"* ✗.

**Acceptance criteria:**
- New module `src/probos/avatars/divergence_detector.py`.
- Function `detect_divergence(intent: EmotionalIntent, applied: ModulationSnapshot) -> DivergenceResult`.
- Self-tag prompt addition gated by an `avatar_telemetry.divergence_detection: bool` Pydantic config (default False — operator opt-in for token cost).
- Trust update path: `runtime.trust_network.observe(agent_id, delta=...)` only when divergence-magnitude exceeds a threshold; magnitude-based not boolean. Asymmetric weighting: matches reward small + (positive divergence informs but does not punish) per AD-727's safety dampening (positive divergence = output exceeds intent in the same direction, e.g. you intended warm and modulation overshot to very-warm — that's fine).
- INTEROCEPTION sensorium block: when divergence is detected on the most recent reply, the next prompt cycle's avatar-self-observation block includes a divergence note. Phrased per AD-727 rule (renderer/output as subject).
- Tests: ≥ 15 boundary cases — match (no divergence, no trust update); divergence positive (output exceeds intent same direction — informs, no negative trust); divergence negative (output diverges from intent opposite direction — small negative trust delta); threshold boundary; asymmetric weighting verified; AD-727 phrasing rule (alert text never says "you" + emotion adjective); intent self-tag missing (graceful degrade, no crash, no trust update); injection into AD-722e cycle's INTEROCEPTION block.
- Compliance with Engineering Principles in `.github/copilot-instructions.md`.

**Out of scope:**
- Vision-LLM divergence (AD-728 forward marker — different coherence check).
- Cross-agent divergence observations (AD-729 — peer perception).
- Auto-correction of detected divergence (separate forward marker if it earns one).

**Test count target:** +25-30 Python; vitest unaffected.

---

### Wave 144 — Sensorium dispatch unification

**Depends on:** Wave 143.
**Issues:** #581 (AD-723).
**Prompt files (architect to draft):**
- `prompts/ad-723-sensorium-dispatch.md`
- `prompts/WAVE-144-DISPATCH.md`

**Why this wave:** Eliminates the dual-wire tax that bit AD-722 this morning. Convert `SENSORIUM_REGISTRY` from inventory to dispatch table with `paths` tuples per entry. Future sensorium ADs register once with a path tuple instead of being hand-wired into both `_build_cognitive_baseline` and `_build_user_message`'s DM branch.

**Architect-side research items:**
1. Read `src/probos/cognitive/cognitive_agent.py` lines 122-138 — the current `SENSORIUM_REGISTRY` `ClassVar[dict]`.
2. Read `_build_cognitive_baseline` lines 4333-4520 — count the existing sensorium injection sites (12 numbered steps) and verify which methods they correspond to.
3. Read `_build_user_message`'s `direct_message` branch at line 5050 — count the inline injection sites (8+ blocks).
4. Read `_build_user_message`'s `ward_room_notification` branch — count its inline blocks. WR is intentionally MORE selective than DM per AD-722 addendum (h) — register entries map paths to subsets accordingly.
5. Path enum: `SensoriumPath` with values `CHAIN_BASELINE`, `CHAIN_EXTENSIONS`, `CHAIN_SITUATION`, `DM_ONESHOT`, `WR_ONESHOT`. Five paths.
6. Backward compat: prompts MUST be byte-identical pre- vs post-refactor. Snapshot test fixtures cover the existing DM and chain prompts. Failures here are blockers.
7. AD-722's avatar block: `_build_avatar_self_observation` registers with `paths={CHAIN_BASELINE, DM_ONESHOT}` and explicitly NOT `WR_ONESHOT` (per AD-722 addendum (h)).

**Acceptance criteria:**
- New `SensoriumPath` enum.
- `SENSORIUM_REGISTRY` entries gain a `paths: tuple[SensoriumPath, ...]` field. Existing entries get accurate path memberships verified against current call sites by the reviewer.
- New `_dispatch_sensorium(path: SensoriumPath, observation: dict) -> dict[str, str]` helper on CognitiveAgent.
- `_build_cognitive_baseline` and the DM/WR branches of `_build_user_message` use the dispatcher. Existing inline blocks become entries in the registry.
- Snapshot tests: a pre-refactor capture of the rendered prompt for one DM and one chain fixture; post-refactor must be byte-identical.
- Tests: ≥ 18 cases — each path, each registered method called when expected and not when not, snapshot byte-equality, AD-722 avatar block scoped correctly to {CHAIN_BASELINE, DM_ONESHOT} only.
- Compliance with Engineering Principles in `.github/copilot-instructions.md`.

**Out of scope:**
- Merging chain and one-shot paths (explicitly rejected per System-1/System-2 ruling).
- WR-branch behaviour change (preserve current intentional WR-selectivity).

**Test count target:** +30-35 Python; vitest unaffected.

---

### Wave 145 — DSL draft preview + revision cycle

**Depends on:** Wave 144.
**Issues:** #541 (AD-721d-1).
**Prompt files (architect to draft):**
- `prompts/ad-721d-1-dsl-preview.md`
- `prompts/WAVE-145-DISPATCH.md`

**Why this wave:** Closes the loop where the Captain currently approves a DSL blind. Today: agent proposes → Captain approves → DSL persists → Captain sees the rendered avatar (and might dislike it). Tomorrow: agent proposes → Captain previews the parametric description in HXI → optionally requests revision via a structured note → re-propose → approve.

**Architect-side research items:**
1. Read `src/probos/cognitive/cognitive_agent.py:propose_appearance` (lines ~2700-2820, AD-721d implementation) — confirm the `captain_note` parameter is already wired and ≤ 280 chars.
2. Read `src/probos/routers/agents.py` `POST /{agent_id}/appearance/propose` and `PUT /{agent_id}/appearance` — current proposal/approval flow.
3. Read `ui/src/components/profile/CrewAvatarPopout.tsx` approval bar (lines ~225-280) — extend with "Request revision" affordance.
4. Decide: revision note is a free-text field with a structured wrapper (`{revision_note: string}` POST body), or a constrained taxonomy (e.g. radio-button choices like "warmer / firmer / less professional / more confident"). Default: free text + 280-char cap, mirroring `captain_note`.
5. Re-propose flow: same `propose_appearance` endpoint with the revision note attached. Returns a fresh DSL. Captain can iterate up to N times (configurable, default 3) before either approving or rejecting outright.
6. Diff display: show a side-by-side delta between the previous DSL and the proposed one, so the Captain sees what changed. AD-721d's parametric description is human-readable — render it as a structured block with diffs highlighted.

**Acceptance criteria:**
- API: `POST /api/agent/{id}/appearance/propose` accepts an optional `previous_dsl` field for diff context AND an optional `revision_note: str (≤280)` for revision-driven re-proposal.
- API: response includes `proposal_iteration: int` so the UI can rate-limit at 3.
- UI: `CrewAvatarPopout` approval bar adds "Request revision" button → opens a small textarea modal → submits a re-propose request → renders the new DSL alongside the previous (or replaces, with a "previous proposal" history accordion).
- DSL diff renderer: small SVG/text widget showing changed fields. NO emoji per HXI Design Principle #3.
- Captain-can-cancel anywhere in the flow.
- Tests: ≥ 8 Python (re-propose with note, iteration cap, history retention, malformed note rejected, AD-721d's `_parse_appearance_dsl` security guards still hold); ≥ 5 vitest (button renders, modal opens, submission triggers re-propose call, diff renders, iteration cap surfaces).
- Compliance with Engineering Principles in `.github/copilot-instructions.md`.

**Out of scope:**
- Visual avatar preview before persistence (would require AD-721i renderer; that's a precondition for AD-722e — separate wave).
- Counselor/Captain-led revision (vs. agent-self-revision triggered by the note) — current design is agent-self-revision based on a Captain-supplied hint; Counselor mediation is a future AD.

**Test count target:** +12-15 Python; +5 vitest.

---

## Wave Stage Workflow (driven by `scripts/wave-orchestrator.ps1`)

Each wave proceeds through these stages. Architect / Builder / Captain (the user) responsibilities at each gate are explicit:

```
draft ─► precheck ─► review_1 ─► revision ─► review_2 ─► gate_1 ─► build ─► review_build ─► verify_build ─► gate_2 ─► push ─► gate_3 ─► close ─► retrospective
[Architect]      [Architect]      [Architect]      [Captain]      [Builder]   [Architect]       [Builder]      [Captain]    [Builder]  [Captain]   [Builder]  [Architect]
```

- **draft:** Architect produces the prompt files listed in `prompt_paths`.
- **precheck:** Architect runs `scripts/phantom-api-precheck.ps1` against drafted prompts.
- **review_1 / revision / review_2:** three-pass review per Architect Standing Order. Pass 1 surfaces Required/Recommended/Nits/Verified; revision applies fixes; pass 2 confirms.
- **gate_1:** Captain advances. Failure here means revision continues.
- **build:** Builder executes prompts, one commit per AD.
- **review_build:** Architect reviews the completed code stack and Builder repairs findings using focused checks.
- **verify_build:** Builder runs one consolidated 16-worker Python gate, full Vitest/build if applicable, and affected Playwright scenarios.
- **gate_2:** Captain advances. Failure here means Builder continues.
- **push:** Builder pushes to main.
- **gate_3:** Captain advances. Failure here is the safety net before close.
- **close:** Builder closes referenced GH issues and archives prompts to `prompts/archive/` per the BUILDER-EXECUTION-PLAN convention.
- **retrospective:** Architect updates DECISIONS.md and PROGRESS.md with shipped scope.

In this autonomous run, the Architect agent makes draft / review / revision / retrospective edits; the Builder agent executes build / verify_build / push / close. The Captain (user) is the source-of-truth for gate_1 / gate_2 / gate_3 advances when present at session boundaries; the agent acts as gate-passer when continuous mode is requested AND there is no blocking failure to surface.

---

## Continuous-mode rules for this cluster

Per Captain ruling 2026-05-10:
> *"Use the wave orchestrator to work continuously until work is completed. Do not defer work unless there is no other option. If work is deferred ensure there it is tracked for follow-up with a github issue."*

- **No deferral without a forward-marker GH issue.** If a wave produces a forward marker, file the GH issue before advancing the wave.
- **No silent skipping.** If a wave's prompt cannot be drafted (e.g. dependency not yet shipped), surface the blocker and STOP — do not move to the next wave.
- **Each wave commits and pushes BEFORE the next wave starts.** No multi-wave bundles.
- **Engineering Principles apply at every commit.** Reviewer Pass 2 must include the explicit line "Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`." Builder must include the same line in its commit message body.
- **Forward-marker discipline.** Any forward marker named in a wave's "Out of scope" section MUST have a matching GH issue. The Architect retrospective stage verifies this before advancing.
- **Issue closure on push.** Issues listed in `issues_to_close` are closed in the `close` stage with the commit SHA referenced. Closure is final; reopening requires a new BF AD.

---

## Inputs (read in full BEFORE starting any wave)

1. `.github/copilot-instructions.md` — engineering principles, testing standards, logging standards, type-annotation rules. Every commit must comply.
2. `prompts/review-criteria.md` — reviewer rubric. Every prompt must pass each section.
3. `DECISIONS.md` AD-722, AD-722e, AD-727, AD-728, AD-729 family — the architectural constraints inherited by this cluster.
4. `prompts/archive/ad-722-avatar-telemetry-v1.md` — the shipped Wave 140 prompt; the patterns there are the closest analog for these waves.
5. `src/probos/avatars/telemetry.py` — the canonical source for modulation rules, signal derivation, and the snapshot contract.

---

## Pattern set forward (for the wave orchestrator's future use)

Six closure constraints from this cluster's design:

1. **Path-coherent injection — register, don't dual-wire.** AD-723 establishes this; future sensorium ADs follow.
2. **Audience-appropriate scope.** WR is for peers (no avatar telemetry); DM is for Captain (full telemetry); chain is for self-reasoning (full telemetry). New injections declare paths.
3. **System-1 / System-2 split is preserved.** No future AD merges the paths without an explicit Captain ruling on why the dual-process distinction no longer applies.
4. **Three coherence checks live in three ADs.** Self (AD-722e), intent-vs-presentation (AD-722a), digital-vs-analog (AD-728). Don't conflate.
5. **Aesthetic judgment is read-only on trust.** Inherited from AD-727 rule #1; AD-722a observes the boundary.
6. **Capability + conduct + training + monitoring** = four-AD family for crew-to-crew capabilities. Inherited from AD-729 family for any future cross-agent perception.

---

## Failure escalation

If a wave's build fails irrecoverably:
1. Builder commits the partial work as a `WIP:` commit on a branch (NOT main).
2. Builder reports the failure with full context: failing test, root cause hypothesis, attempted fixes.
3. Architect triages — either authors a follow-up prompt or files a BF.
4. Wave is paused. Subsequent waves do NOT advance until the failure is resolved.
5. Captain (user) is surfaced the blocker at the next session boundary.

This plan does not authorize blind retry. Failures are signals; signals are surfaced.

---

## Estimated total scope

| Wave | Python tests added | Vitest tests added | Build duration estimate |
|---|---|---|---|
| 141 | +20-25 | 0 | ~45-90 min |
| 142 | +25-30 | +4-5 | ~60-120 min |
| 143 | +25-30 | 0 | ~60-120 min |
| 144 | +30-35 | 0 | ~60-90 min |
| 145 | +12-15 | +5 | ~30-60 min |
| **Total** | **+112-135** | **+9-10** | **~5-8 hours** |

This is a half-day to full-day cluster, sized realistically for an autonomous run with three-pass review on each prompt.
