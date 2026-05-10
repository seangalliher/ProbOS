# WAVE 136 DISPATCH — Agent-authored voice + emotional voice modulation (AD-718a + AD-718d)

**Wave:** 136
**Mode:** main
**Depends on:** 133 (AD-718 v1 voice profile baseline), 134 (AD-721d agent-authored DSL pattern + AD-721 expression channels)
**Builder required:** yes
**Issues to close:** [#522](https://github.com/seangalliher/ProbOS/issues/522) (AD-718a), [#525](https://github.com/seangalliher/ProbOS/issues/525) (AD-718d)
**Date:** 2026-05-09

---

## 1. Goal

Close the loop on "agents own their voice the way they own their face." Two paired prompts:

- **AD-718a** — agent reflects on `CrewProfile.personality` (Big-Five) and proposes a `VoiceProfile` edit. Captain reviews and approves; on approve, the proposal lands on `CrewProfile.voice` via the existing `PUT /api/agent/{id}/voice-profile` endpoint. **This is the AD-721d pattern transposed onto voice.** Risk: LOW–MEDIUM.
- **AD-718d** — at speak-time, modulate `pitch` / `rate` / `volume` based on the live agent-state channel that AD-721 already feeds the avatar (`trust_delta`, `load`, `working_state`, `tier3_alert`). Browser-only modulation; no server changes beyond optional emit-of-signals (already present). Voice and avatar expression align by sourcing the same signal contract. Risk: LOW.

Both prompts stay strictly within the Web Speech API knobs (`pitch ∈ [0, 2]`, `rate ∈ [0.1, 10]`, `volume ∈ [0, 1]`). No new audio backend, no Coqui/ElevenLabs/Bark — that's AD-718b ([#523](https://github.com/seangalliher/ProbOS/issues/523)) and is firewalled OFF for this wave.

This is the gentlest of Cluster A's three waves. Resist scope creep — the wave is intentionally a single dispatch.

---

## 2. Prior-work + license disposition

| Prior work / candidate | What we found at HEAD | Disposition |
|---|---|---|
| `VoiceProfile` dataclass | `src/probos/crew_profile.py:96-128`. Fields `voice_name: str = ""`, `pitch: float = 0.9`, `rate: float = 0.95`, `volume: float = 0.8`. `__post_init__` enforces `pitch ∈ [0, 2]`, `rate ∈ [0.1, 10]`, `volume ∈ [0, 1]`. `from_dict` at L122. Wired onto `CrewProfile.voice` at L210. | **Reuse as-is.** All proposal validation paths terminate in `VoiceProfile(...)` so the dataclass `__post_init__` is the **single source of bounds truth**. AD-718a and AD-718d MUST NOT re-implement the bounds check; they MUST round-trip through `VoiceProfile`. |
| `PUT /api/agent/{id}/voice-profile` endpoint | `src/probos/routers/agents.py:224-257`. Body is `SetVoiceProfileRequest`; constructs a `VoiceProfile(...)` at L236; persists. | **Reuse as-is for AD-718a's "Captain approves" path.** No new write endpoint. AD-718a adds a **read-only proposal** endpoint (`POST /api/agent/{id}/voice-profile/propose`) that returns a candidate `VoiceProfile` without persisting; the existing PUT is the approve path. |
| `voice_profile_defaults.default_voice_for(agent_type)` | Imported at `routers/agents.py:118`. Used as fallback for the GET-side voice profile. | **Pattern reference only.** AD-718a's proposal generator does NOT consult `default_voice_for` — the whole point of the proposal is "agent picks for itself." Defaults remain the seed for un-proposed agents. |
| `propose_appearance(...)` on CognitiveAgent | `src/probos/cognitive/cognitive_agent.py:2592-2722`. LLM-driven, returns a validated `AvatarDSL`. Strict-JSON parse via `_parse_appearance_dsl` (L2724-L2782): size cap, anchor/alias reject, `yaml.safe_load`, depth guard, Pydantic `model_validate`. | **Direct template for AD-718a's `propose_voice(...)`.** Mirror the parse pipeline byte-for-byte: size cap ≤16 KiB, anchor/alias reject, `yaml.safe_load`, Pydantic-equivalent validation (see "VoiceProposal" decision row below). No `exec`/`eval`/`compile`. |
| `AvatarDSL` Pydantic model | `src/probos/avatars/dsl.py:118`. `ConfigDict(extra="forbid")`. All fields have defaults — `AvatarDSL()` succeeds. | **Pattern template.** AD-718a introduces a new `VoiceProposal` Pydantic model alongside the existing `VoiceProfile` dataclass. **Decision (drafter must surface in §4):** the Pydantic layer is a *parse-time validator*, NOT a replacement for the `VoiceProfile` dataclass. After `VoiceProposal.model_validate(...)` succeeds, the proposal is converted to a `VoiceProfile(...)` instance (which re-runs `__post_init__`). Defense in depth: two independent bounds checks, one in Pydantic, one in `__post_init__`. The `VoiceProfile` dataclass is NOT migrated to Pydantic in this wave. |
| `AppearanceProfile.dsl: dict[str, Any] | None` | `src/probos/crew_profile.py:147`. Holds the Captain-approved AvatarDSL serialized as a dict. | **Pattern reference.** The voice-side analogue does NOT need a parallel "approved proposal" field. Approved proposals overwrite `CrewProfile.voice` directly via the existing PUT endpoint — the proposal is a *transient* artifact, not an appended history. (Voice changes are reversible at the voice picker; appearance changes were heavier and warranted a persisted artifact. See §6 "Cross-AD integration points" for trade-off rationale.) |
| `ui/src/audio/voice.ts` `speakResponse(text, profile?, agent_id?)` | L92-L110. Currently takes a `VoiceProfile` and applies `pitch/rate/volume` to a `SpeechSynthesisUtterance`. | **Extend in AD-718d.** Add an optional 3rd argument `signals?: AgentSignals` (or pull from store at the call site — drafter picks; document in §5). If signals are present, apply emotional modulation as a **multiplicative offset** on top of the agent's `VoiceProfile` baseline, then **re-clamp** to Web Speech API bounds before assigning to the utterance. The clamp lives inside `voice.ts`; the runtime never sees the modulated values. |
| `ui/src/components/profile/avatarSignals.ts` `AgentSignals` | L11-L23. `{ trust_delta: number; load: number; working_state: 'idle' \| 'thinking' \| 'busy' \| 'responding'; tier3_alert: boolean }`. Selector at L41-L48 reads from store. | **Reuse as the modulation source.** AD-718d does NOT introduce a new signal type. The same selector that drives `applyExpressionsFromSignals` (CrewVRM.tsx:95-129) feeds AD-718d's voice modulation. Voice + avatar align by construction. |
| `ui/src/components/profile/CrewVRM.tsx` `applyExpressionsFromSignals` | L95-L129. Maps `trust_delta > 0` → `happy`, `trust_delta < 0` → `sad`, `tier3_alert` → `surprised`. | **Reference pattern.** AD-718d's `applyEmotionalModulation(profile, signals)` mirrors the *same source-of-truth signals* with a different output codomain (utterance knobs instead of VRM blend shapes). Both are pure functions — easy to test. |
| `ui/src/components/profile/ProfileInfoTab.tsx` voice picker | L52-L70. Voice-profile editor with `currentProfile` state seeded from `profileData?.voiceProfile` and persisted via PUT. | **Extend in AD-718a.** Add a "Propose" affordance (inline-SVG glyph, NOT emoji) that calls the new propose endpoint, displays the candidate values in a diff-style preview, and invokes the existing PUT-approve flow on Captain confirm. The Captain can also still hand-edit values — the proposal is a *suggestion*, not a lock. |
| `AD-722` self-state telemetry (issue [#545](https://github.com/seangalliher/ProbOS/issues/545)) | Filed today. Future work: agents observe their own avatar render state. | **NOT consumed by this wave.** AD-718d uses the existing `AgentSignals` selector (already wired by AD-721). AD-722 is on the roadmap as a deepening of the same channel; AD-718d remains independently shippable today. |
| `AD-721b` phoneme lipsync (issue [#529](https://github.com/seangalliher/ProbOS/issues/529)) | Forward-marker. Drives `aa/ih/ou/ee/oh` morphs from TTS phoneme stream. | **Disjoint.** Lipsync is a different morph set from emotional expressions (`happy/sad/angry/surprised`). They co-exist on the same VRM. AD-718d touches neither — it touches the utterance, not the avatar. |
| `AD-718b` Coqui/ElevenLabs/Bark backend (issue [#523](https://github.com/seangalliher/ProbOS/issues/523)) | Future, paid-license-laden absorption candidate. | **Firewalled OFF.** Wave 136 ships zero new audio deps. License audit confirmed: zero new deps. AD-718b will be its own wave with its own license disposition (per user-memory license hygiene, expect pattern-absorption only for the open-source overlay). |

**Top-level license posture:** OSS Apache 2.0 stays Apache 2.0. Web Speech API is browser-native — no third-party JS or Python deps added. No new model weights, no new audio backends, no fonts, no glyph fonts. License audit: **clean**.

---

## 3. Engineering-principles checklist

Builder must verify each in the per-prompt acceptance criteria. Reviewer flags any miss as **Required**.

| Principle (`.github/copilot-instructions.md`) | Where it applies | Verifying deliverable |
|---|---|---|
| **Strict JSON / structured output for agent proposal** | AD-718a `propose_voice(...)` LLM output parser | Mirror `_parse_appearance_dsl` (cognitive_agent.py:2724-2782) byte-for-byte: size cap **≤16 KiB**, reject `&`/`*`/`!!` anchor-alias-tag tokens, `yaml.safe_load` (NOT `pyyaml.load`), depth guard at parse, then `VoiceProposal.model_validate(...)`. **Forbidden:** `exec`, `eval`, `compile`, `importlib.import_module`, `pickle.loads`. Reviewer fails the prompt on any of those tokens in the new module. |
| **Defense in depth** | AD-718a end-to-end + AD-718d clamp | (1) LLM-output boundary: `VoiceProposal.model_validate(...)` enforces enums/bounds. (2) Conversion to `VoiceProfile(...)` re-runs `__post_init__` bounds. (3) API boundary: existing `SetVoiceProfileRequest` + `VoiceProfile(...)` constructor in `set_agent_voice_profile` (routers/agents.py:236) re-runs `__post_init__` a third time on the approve path. (4) AD-718d: after multiplicative modulation, **clamp** to `pitch ∈ [0, 2]`, `rate ∈ [0.1, 10]`, `volume ∈ [0, 1]` before the utterance is constructed. Three independent server-side bounds checks; one client-side clamp. |
| **Async discipline** | New `POST /voice-profile/propose` endpoint | Endpoint is `async def`. Calls into `agent.propose_voice(...)` via `await`. **No** `subprocess.run`. **No** `asyncio.ensure_future` — only `asyncio.create_task` (and only if a fire-and-forget call is genuinely needed, which it isn't in v1). |
| **No private-attr access** | UI propose-flow + server-side propose endpoint | UI reads `profileData.voiceProfile` (already public-shaped), posts to a public endpoint, on success the response shape is `{voiceProfile: {...}}` matching the existing PUT response. No reaching into `_callsign_map`, `_voice_profile_cache`, or any other private. The `AgentSignals` selector at `avatarSignals.ts:41-48` is already public; AD-718d uses it via the public `useStore` selector pattern. |
| **No emoji in HXI** (HXI Design Principle #3) | Propose affordance icon, modulation badge | Inline SVG with `strokeWidth: 1.5`, `strokeLinecap: round`. Active amber `#f0b060`, inactive dim `#666680`. Reviewer fails on any emoji literal in the diff. The "modulation active" indicator (e.g. a tiny waveform glyph) is also stroke-based SVG, NOT a text emoji. |
| **No private-attr access on store** | AD-718d signals consumption | Use the existing `selectAgentSignals(state, agentId)` selector at `avatarSignals.ts`. Do NOT reach into `state.notifications` or `state.agents[id]._private` directly from `voice.ts`. If a new selector is needed, add it next to the existing one. |
| **Episodic completeness** | AD-718a Captain-approved voice change | When the Captain approves a proposal (the existing PUT path runs), an episode SHOULD be written for the proposal-approval event with intent `voice_profile_change` and a signals dict capturing `{old_voice, new_voice, agent_id}`. **Borderline call:** the existing PUT path does not currently write an episode for hand-edits (the dataclass fields are mutated in place). Drafter decides: either (a) AD-718a writes an episode ONLY for the approve-from-proposal path (proposal id present in the request), OR (b) the existing PUT path also gains an episode write. Decision criterion: option (a) for v1 — narrower blast radius, the hand-edit path stays unchanged. AD-718d does NOT write episodes (modulation is transient, per-turn). |
| **Trust + Hebbian alignment** | AD-718d signals → utterance | Modulation is a **read-only** consumer of trust state. Trust state is NEVER updated *by* modulation (there is no feedback loop where the agent's own voice softening changes its trust score). Captain feedback drives trust; AD-718d only surfaces trust *visually/aurally*. Reviewer fails the prompt if any modulation code path imports or writes to `consensus/trust.py`. |
| **Async + browser-native** | AD-718d voice modulation | `voice.ts`'s modulation is synchronous (pure function on numbers). No new `Promise`-shaped helpers. Existing `speakResponse` stays synchronous. |
| **Configuration via Pydantic** | New knobs, if any | AD-718d ships a constants file (`ui/src/audio/voiceModulation.ts`) for the modulation coefficients (e.g. `TRUST_DELTA_PITCH_GAIN = 0.15`). These are NOT runtime-configurable in v1; they're compile-time constants chosen by the drafter and surfaced in PR description for Captain review. AD-718a does NOT introduce new server-side config (size cap and depth guard are stdlib-style constants in the parser module, mirroring `_MAX_PROPOSAL_BYTES` in `cognitive_agent.py`). |
| **Storage abstraction (Protocol)** | Persistence | AD-718a uses the existing `ProfileStore` and existing dataclass — no new SQLite tables, no new storage layer, no new Protocol. The wave does NOT introduce a `VoiceProposalStore`; proposals are transient and not persisted (the candidate values flow proposal → UI preview → approve PUT → CrewProfile.voice). If the Captain dismisses the preview, the proposal evaporates. Drafter must surface this trade-off vs. the AD-721d pattern (which persists `AppearanceProfile.dsl`) in §6. |
| **Test gates** | Both prompts | Per-prompt: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad718a_*.py -v -n 0` and `tests/test_ad718d_*.py -v -n 0`. Full gate: `pytest tests/ -q -n 16 --dist=loadfile` (fall back to `-n 8` per BUILDER-EXECUTION-PLAN.md hard-stop). UI Vitest: `cd ui && npx vitest run` MUST be green. AD-718a ships at least `ProfileInfoTab.proposeVoice.test.tsx`; AD-718d ships at least `voice.modulation.test.ts` (pure-function tests on the modulation math) AND `voice.speakResponse.modulation.test.ts` (integration test that the utterance receives clamped values). |

---

## 4. AD-718a scope — Agent-authored voice profile

**Issue:** [#522](https://github.com/seangalliher/ProbOS/issues/522). The agent reflects on its personality and proposes a `VoiceProfile`. Captain reviews and approves; the existing PUT endpoint persists.

### Deliverables

| ID | Deliverable | File(s) | Verification |
|---|---|---|---|
| **D1** | `VoiceProposal` Pydantic model | New `src/probos/voice/proposal.py` (drafter verifies the path; if `src/probos/voice/` doesn't exist, create it with `__init__.py`) | `class VoiceProposal(BaseModel)` with `ConfigDict(extra="forbid")`. Fields: `voice_name: str = ""` (max length 200), `pitch: float = Field(default=0.9, ge=0.0, le=2.0)`, `rate: float = Field(default=0.95, ge=0.1, le=10.0)`, `volume: float = Field(default=0.8, ge=0.0, le=1.0)`, `rationale: str = Field(default="", max_length=500)` (free-form short text — agent's reasoning). `model_validate({})` MUST succeed (defaults everywhere, mirror `AvatarDSL`). |
| **D2** | `propose_voice(...)` capability on `CognitiveAgent` | `src/probos/cognitive/cognitive_agent.py` (extend; mirror `propose_appearance` at L2592) | `async def propose_voice(self, *, llm_client=None) -> VoiceProposal`. Builds an `instructions`-driven LLM prompt that includes the agent's `CrewProfile.personality` (Big-Five), `display_name`, `department`, `rank`, and a one-line description of the Web Speech API knob semantics. LLM returns JSON; parse via the new `_parse_voice_proposal` helper (D3). On parse failure, raise `VoiceProposalError` (new exception in D1's module, mirroring `AppearanceProposalError`). |
| **D3** | `_parse_voice_proposal` helper | Same module as D2 OR a sibling parser module (drafter picks; align with `_parse_appearance_dsl` location which lives next to `propose_appearance`) | **Mirror `_parse_appearance_dsl` (cognitive_agent.py:2724-2782) byte-for-byte:** size cap `_MAX_PROPOSAL_BYTES = 16 * 1024`; reject `&`/`*`/`!!` tokens (anchor/alias/tag); `yaml.safe_load`; depth guard at parse; `VoiceProposal.model_validate(parsed)`. Convert to a plain dict at the boundary (`proposal.model_dump()`). On any failure, raise `VoiceProposalError` with a short reason string (no LLM output echoed back). |
| **D4** | `POST /api/agent/{agent_id}/voice-profile/propose` endpoint | `src/probos/routers/agents.py` (extend; the file already owns `/voice-profile` PUT at L224-L257) | Returns `{agentId, proposal: {voice_name, pitch, rate, volume, rationale}}`. **Does NOT persist.** Idempotent — calling twice returns two independent proposals (LLM-non-determinism is acceptable; the Captain decides which one to approve). On `VoiceProposalError`, returns HTTP 422 with `{detail: "<reason>"}`. On agent-not-found, returns 404 (consistent with the existing GET/PUT). |
| **D5** | Approve flow uses existing PUT | No new endpoint. UI calls existing `PUT /api/agent/{agent_id}/voice-profile` with the proposal's values. | Conversion happens at the API boundary: `VoiceProfile(**proposal_subset)` re-runs `__post_init__` (third bounds check, per §3 row "Defense in depth"). Reject the request if `voice_name` is longer than the existing GET payload allows (drafter verifies the existing limit; if none, mirror Pydantic `max_length=200`). |
| **D6** | "Propose" affordance in voice picker | `ui/src/components/profile/ProfileInfoTab.tsx` (extend the voice editor block at L52-L70) | Inline-SVG button next to the voice picker row. Clicking calls `POST /api/agent/{id}/voice-profile/propose` and renders a small diff-style preview ("Current 0.9 → Proposed 1.05"). Captain can "Approve" (calls the existing PUT) or "Dismiss" (clears the preview). Captain can also hand-edit the proposed values before approving. Active state amber, inactive dim. **No emoji.** |
| **D7** | Episode write on proposal-approval path | `routers/agents.py` `set_agent_voice_profile` OR a service-layer hook (drafter picks; document in prompt) | When the request body carries a marker indicating "approved-from-proposal" (drafter chooses the marker shape — recommended: optional `proposal_rationale: str` field on `SetVoiceProfileRequest`), the handler writes an episode with `intent="voice_profile_change"`, `signals={"old_voice": old_dict, "new_voice": new_dict, "rationale": rationale, "agent_id": agent_id}`. Hand-edits without a `proposal_rationale` follow the existing path unchanged (no episode). |
| **D8** | Tests: parser | New `tests/test_ad718a_voice_proposal_parser.py` | (1) Happy path: well-formed JSON parses to `VoiceProposal`. (2) Size cap: input >16 KiB raises `VoiceProposalError`. (3) Anchor-alias reject: input containing `&` or `*` or `!!` raises. (4) Out-of-bounds pitch: input with `pitch=3.0` raises. (5) `model_validate({})` succeeds with all defaults. (6) `extra="forbid"` rejects unknown keys. |
| **D9** | Tests: capability + endpoint | New `tests/test_ad718a_propose_voice.py` | (1) `propose_voice` returns a `VoiceProposal` for a fake LLM client returning a known JSON payload. (2) `propose_voice` raises `VoiceProposalError` on malformed LLM output. (3) `POST /voice-profile/propose` returns 200 + a proposal dict. (4) `POST /voice-profile/propose` returns 422 on parser failure. (5) Captain approve via existing PUT round-trips the proposed values into `CrewProfile.voice`. (6) Approval-with-`proposal_rationale` writes an episode; hand-edit without it does not. |
| **D10** | Tests: UI | New `ui/src/__tests__/ProfileInfoTab.proposeVoice.test.tsx` | (1) "Propose" button renders. (2) Clicking calls the propose endpoint (mock fetch). (3) Preview renders with diff styling. (4) "Approve" calls PUT with the proposed values + `proposal_rationale`. (5) "Dismiss" clears state without calling PUT. |

### Wiring

The propose endpoint is registered when the agents router is wired (existing pattern, no startup wiring change). The capability is invoked on a per-agent basis through the existing `runtime.agent_for(agent_id)` lookup (drafter verifies the lookup helper at HEAD). LLM client tier: **fast** (Sonnet via Copilot proxy), 30s timeout — same tier as `propose_appearance`.

---

## 5. AD-718d scope — Emotional voice modulation

**Issue:** [#525](https://github.com/seangalliher/ProbOS/issues/525). At speak-time, modulate `pitch`/`rate`/`volume` based on `AgentSignals`. Browser-only. Voice and avatar align by sourcing the same selector.

### Deliverables

| ID | Deliverable | File(s) | Verification |
|---|---|---|---|
| **E1** | Pure modulation function | New `ui/src/audio/voiceModulation.ts` | `export function applyEmotionalModulation(profile: VoiceProfile, signals: AgentSignals): VoiceProfile`. Returns a NEW `VoiceProfile`-shaped object with modulated values, **clamped** to Web Speech API bounds (`pitch ∈ [0, 2]`, `rate ∈ [0.1, 10]`, `volume ∈ [0, 1]`). Pure function — no DOM access, no store access. |
| **E2** | Modulation rule constants | Same module as E1 | Compile-time constants. Initial values (drafter justifies in PR description; Captain reviews): `TRUST_DELTA_PITCH_GAIN = 0.15` (positive trust → slightly higher pitch, "warmer"), `TIER3_ALERT_RATE_GAIN = 0.10` (alert → slightly faster), `LOAD_VOLUME_ATTEN = 0.05` (high load → slightly quieter, "tired"), `WORKING_STATE_RESPONDING_RATE_GAIN = 0.05`. All gains are small — modulation should be perceptible but never override the agent's baseline character. **No** rule that modulates a knob to its boundary under normal signal values; clamping should be a defense-in-depth net, not a routine occurrence. |
| **E3** | `speakResponse` integration | `ui/src/audio/voice.ts` (extend `speakResponse` at L92-L110) | Add an optional 3rd-or-4th argument `signals?: AgentSignals`. If present and non-null, replace the inline `profile?.pitch ?? 0.9` etc. with the modulated values from `applyEmotionalModulation(profile, signals)`. Backward compatible — existing callers without `signals` see no change. |
| **E4** | Wire signals at the call site | The component(s) that currently call `speakResponse` (drafter greps the codebase: likely `ProfileChatTab.tsx`, `IntentSurface.tsx`, possibly others) | Each call site that knows its `agent_id` reads the signals via the existing `selectAgentSignals(agent_id)` selector and passes them. Call sites that lack an `agent_id` (e.g. Ship's Computer fallback) pass `undefined` and behavior is unchanged. |
| **E5** | Modulation indicator (subtle, optional) | `ui/src/components/profile/ProfileInfoTab.tsx` voice section, OR the avatar bloom area (drafter picks) | Tiny inline-SVG waveform glyph that brightens when modulation is active (any signal is non-zero). **Optional in v1** — if it adds UI risk, defer to AD-718d-1. The wave is small enough that the indicator should ship; only defer if it materially complicates the Vitest harness. **No emoji.** |
| **E6** | Tests: pure function | New `ui/src/__tests__/voiceModulation.test.ts` | (1) Idle signals (all zero) return the input profile **unchanged** (or numerically equal). (2) `trust_delta = 0.5` raises pitch by `0.5 * TRUST_DELTA_PITCH_GAIN` (clamped). (3) `trust_delta = -0.5` lowers pitch. (4) Modulated value above 2.0 clamps to 2.0. (5) Modulated value below 0.1 (rate) clamps to 0.1. (6) Modulated value below 0.0 (volume) clamps to 0.0. (7) Multi-signal interaction: trust + tier3 + load combine without exceeding any clamp. (8) Function does NOT mutate input. |
| **E7** | Tests: integration | New `ui/src/__tests__/voice.speakResponse.modulation.test.ts` | Mock `SpeechSynthesisUtterance`. (1) `speakResponse(text, profile, undefined)` produces utterance with un-modulated values. (2) `speakResponse(text, profile, signals)` produces utterance with modulated, clamped values. (3) `speakResponse(text, undefined, signals)` falls back to default profile + modulation (verifies default-profile path is also modulated correctly). |

### Server-side

**Zero server changes.** The `AgentSignals` selector already reads from store state populated by AD-721. AD-722 (issue [#545](https://github.com/seangalliher/ProbOS/issues/545)) will deepen the channel later but is NOT a prerequisite. If a future signal source (e.g. real `trust_delta` from server) requires a backend change, that's a separate AD.

---

## 6. Cross-AD integration points

| Integration | What it means | Builder action |
|---|---|---|
| **Voice + avatar align via shared selector** | Both `applyExpressionsFromSignals` (CrewVRM.tsx:95) and `applyEmotionalModulation` (E1) read from `selectAgentSignals(agent_id)`. When Counselor's `trust_delta > 0`, her avatar smiles **and** her voice pitches up — same source, two surfaces. | No code-level coupling between the two functions. Both are pure consumers of the same selector. **Test:** a single Vitest case asserts both functions produce non-default outputs from the same `signals` instance. |
| **Proposal lifecycle vs. appearance lifecycle** | AD-721d persists the approved DSL on `AppearanceProfile.dsl` because re-rendering an avatar is heavy (Blender, .vrm). AD-718a does NOT persist the proposal — voice changes are reversible at the picker, the approved values flow directly into `CrewProfile.voice`. | Drafter MUST justify this divergence in the AD-718a prompt body §1 (one paragraph). Reviewer flags as **Required** if the divergence is silent. |
| **Three independent bounds checks (server)** | `VoiceProposal.model_validate` → `VoiceProfile.__post_init__` (in capability conversion) → `VoiceProfile.__post_init__` (in PUT handler). All three run for any approved-from-proposal flow. | Acceptable redundancy — each layer protects a distinct boundary (LLM output, proposal-to-dataclass conversion, API request). Prompt body explicitly calls this out as defense-in-depth, not over-engineering. |
| **Modulation never updates trust** | Modulation is read-only on trust state. No code path writes to `consensus/trust.py` or any trust-update helper from `voiceModulation.ts` or `voice.ts`. | Reviewer fails the prompt if any modulation path imports `trust` or `consensus.*` modules. |
| **Episodic write only on approve-from-proposal** | The hand-edit path through the existing PUT does NOT gain an episode in this wave. Only approve-from-proposal writes an episode, and only because the proposal carries the agent's rationale (which is the new learning signal). | Builder MUST NOT add episode writes to the hand-edit branch. If reviewer asks for parity, decision is "out of scope, file as a follow-up AD." |

---

## 7. Out-of-scope / deferred to later waves

- **AD-718b** — third-party TTS backend (Coqui / ElevenLabs / Bark / Tortoise). Issue [#523](https://github.com/seangalliher/ProbOS/issues/523). License-laden absorption candidate. Firewalled OFF.
- **AD-718c** — per-agent wake-word. Issue [#524](https://github.com/seangalliher/ProbOS/issues/524). Independent of voice profile; separate wave.
- **AD-718e** — multi-language voice. Issue [#526](https://github.com/seangalliher/ProbOS/issues/526). Browser voice catalogue surfaces are per-locale; deferred.
- **AD-718f** — per-agent global volume control on the Captain side. Issue [#527](https://github.com/seangalliher/ProbOS/issues/527). Operator-side, distinct from agent-side modulation.
- **AD-722** — agent self-state telemetry (avatar render-state observable to the agent). Issue [#545](https://github.com/seangalliher/ProbOS/issues/545). AD-718d does NOT depend on it; AD-722 may later replace `AgentSignals` with a richer self-model.
- **AD-718a-1** (proposed forward marker if needed) — proposal history persisted on a new `VoiceProposalLog`. Out of scope; voice proposals stay transient in v1.
- **AD-718d-1** (proposed forward marker if E5 indicator is deferred) — modulation activity indicator on the avatar HUD.
- **Voice rendering through a server-side audio graph** — explicitly forbidden in this wave. Web Speech API only.
- **Captain-driven feedback loop on voice proposals** (e.g. "Counselor, that voice was too high — try again with lower pitch"): not in v1. The Captain edits the proposal manually before approving, OR re-invokes propose to get a fresh LLM attempt.

---

## 8. Hard-stop conditions for the Builder

Builder MUST stop and surface to Architect if any of the following occur:

1. **Phantom API.** A grep of any asserted method/class/endpoint at HEAD returns zero matches AND the prompt does not introduce it. Examples to watch for: `propose_voice` (NEW — introduced by D2), `VoiceProposal` (NEW — introduced by D1), `_parse_voice_proposal` (NEW — introduced by D3), `applyEmotionalModulation` (NEW — introduced by E1). All four are introduced by this wave; flagging them as missing is a **false positive** (per architect-learnings memo, Wave 10 phantom-API false-positive class).
2. **Architectural contract change required.** Any change to `VoiceProfile`'s public shape (adding/removing fields), to `AgentSignals`, to the existing PUT endpoint contract, or to `CognitiveAgent`'s base contract is a **hard stop**. AD-718a layers ON TOP of `VoiceProfile`; it does not modify it.
3. **Pydantic vs dataclass tension.** If `VoiceProposal.model_validate(...)` and `VoiceProfile(...)` disagree on what's valid (e.g. Pydantic accepts a value that `__post_init__` rejects), STOP and surface. The two layers MUST agree on bounds. Resolution: tighten the looser side to match the stricter — likely Pydantic adopts the dataclass's bounds, since the dataclass is the source of truth.
4. **Working tree integrity.** Pre-flight `git diff --numstat | sort -k2nr | head -5`. Any file with >200 lines deleted that the Builder did not author is a stop-the-line event (per user-memory note 2026-05-08).
5. **Test gate failure under `-n 0` after passing under `-n 16`.** Order-dependent test pollution. Quarantine via BF entry pointing at AD-682, do NOT block the wave (per BUILDER-EXECUTION-PLAN.md hard-stop rules).
6. **License creep.** Any new third-party dep (Python or JS) introduced by either prompt is a hard stop. Wave 136's license posture is "zero new deps."
7. **Emoji in diff.** Any emoji literal in `*.tsx` / `*.ts` / `*.py` of the diff is a hard stop. HXI Design Principle #3 is non-negotiable.
8. **Modulation writes to trust.** Any import of `consensus.trust`, `consensus.quorum`, or any trust-update helper from `voice.ts` / `voiceModulation.ts` / `voice/proposal.py` is a hard stop.
9. **`exec`/`eval`/`compile`/`pickle.loads` on LLM output.** Hard stop in either prompt.
10. **Anchor-alias-tag tokens accepted by the parser.** If a test inputs `&anchor` and the parser does NOT raise, hard stop — defense-in-depth has been weakened.

---

## 9. Acceptance criteria

For each prompt, the Builder MUST:

1. Run `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-718a-…-v1.md` and `…ad-718d-…-v1.md` after drafting; resolve any flagged phantoms (or document them as "introduced by this prompt" in the prompt's "Verified Against Codebase" footer).
2. Pass per-prompt test gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad718a_*.py -v -n 0` and `tests/test_ad718d_*.py -v -n 0`.
3. Pass full test gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 16 --dist=loadfile` (fall back to `-n 8` if worker crashes per BUILDER-EXECUTION-PLAN.md). Total test count grows by ~16 (AD-718a parser ~6, capability+endpoint ~6, UI ~5, AD-718d pure ~8, integration ~3, indicator if shipped ~2; drafter pins exact targets in each prompt).
4. Pass UI Vitest: `cd ui && npx vitest run`.
5. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
6. PROGRESS.md updated: highest AD bumped to AD-721i (no change — sub-letter ADs do not bump the highest). Wave 136 entry appended with paired ADs.
7. `decisions-era-4-evolution.md` (or whichever DECISIONS-era file owns AD-718) appended with AD-718a + AD-718d entries citing the wave dispatch.
8. `docs/development/roadmap.md` Bug Tracker — no new BF entries expected; if any test pollution surfaces and gets quarantined, file the BF and add a row.
9. Issues closed: [#522](https://github.com/seangalliher/ProbOS/issues/522), [#525](https://github.com/seangalliher/ProbOS/issues/525). Verify the wave-plan.yaml `issues_to_close` matches.
10. Memory artifacts: nothing new for `/memories/probos-architect-learnings.md` unless a fresh pattern emerges. If the AD-721d → AD-718a pattern transposition reveals a reusable template for "agent-authored data artifact pairs" (DSL + voice profile both follow the same shape), add a one-liner.

---

## 10. AD-numbering verification

**Current highest AD as of HEAD:** **AD-721i** (verified at `PROGRESS.md:11`: *"DECISIONS.md — append-only architectural decisions (current highest AD: AD-721i)"*).

**This wave:**

| AD | Issue | Status |
|---|---|---|
| AD-718a | [#522](https://github.com/seangalliher/ProbOS/issues/522) | Sub-letter of AD-718; no collision. |
| AD-718d | [#525](https://github.com/seangalliher/ProbOS/issues/525) | Sub-letter of AD-718; no collision. |

**Sub-letter family at HEAD:** AD-718 (Wave 133, shipped), AD-718a (this wave), AD-718b ([#523](https://github.com/seangalliher/ProbOS/issues/523), filed, deferred), AD-718c ([#524](https://github.com/seangalliher/ProbOS/issues/524), filed, deferred), AD-718d (this wave), AD-718e ([#526](https://github.com/seangalliher/ProbOS/issues/526), filed, deferred), AD-718f ([#527](https://github.com/seangalliher/ProbOS/issues/527), filed, deferred). AD-718-1 noted in user request as filed during Wave 135 (forward marker for voice on multi-agent surface deferred from AD-719) — drafter verifies in PROGRESS.md or wave-plan.yaml before drafting the per-AD prompts.

**No new top-level ADs.** Highest stays at AD-721i.

---

## Final report (Architect)

- **Path written:** [prompts/WAVE-136-DISPATCH.md](prompts/WAVE-136-DISPATCH.md)
- **Outline:** Wave 136 closes Cluster A with the gentlest pair: AD-718a transposes the AD-721d agent-authored-DSL pattern onto voice (LLM proposes → Captain approves via the existing PUT endpoint), and AD-718d adds emotional modulation in the browser by reading the same `AgentSignals` selector that AD-721 already feeds the avatar. Zero new deps, three independent server-side bounds checks, defense-in-depth-by-construction. The wave is small enough to be a single dispatch; resist scope creep.
- **Open Captain questions:**
  1. **Approval flow shape.** AD-721d's "Captain approves" is a heavy gate (re-render an avatar). Voice changes are reversible at the picker. Should AD-718a's approve flow be (a) the existing two-step "preview then approve" (what this dispatch specifies), OR (b) a one-shot "propose-and-apply" with a single Undo? Recommendation: (a). It mirrors AD-721d, keeps the Captain in the loop on every change, and the Captain can always hand-edit the values before approving. (b) is a future simplification.
  2. **Modulation indicator (E5).** Ship in v1 or defer to AD-718d-1? Recommendation: ship if the Vitest harness allows a clean assertion against the selector-driven rendering; otherwise defer. Drafter calls it during prompt-draft.
  3. **Coupling AD-718d to AD-722 telemetry.** Currently AD-718d reads `AgentSignals` from the store, populated by AD-721. AD-722 will deepen the channel into agent-self-observable telemetry. Should AD-718d declare AD-722 a forward dep (to be revisited when AD-722 ships), OR stay agnostic? Recommendation: stay agnostic. AD-718d ships independently today; if AD-722 lands later, the selector contract stays the same and AD-718d benefits silently.
  4. **Episode write parity** (per §6 row "Episodic write only on approve-from-proposal"). The hand-edit path through PUT does NOT gain an episode in this wave. If the Captain wants symmetry, file as a separate AD. Recommendation: defer; the proposal-rationale is the actual learning signal.
- **Risk classification:**
  - **AD-718a** — LOW–MEDIUM. New endpoint + new Pydantic model + new capability; reuses existing storage and existing PUT endpoint. The novel surface is the JSON parser (mirrored byte-for-byte from AD-721d's hardened parser). UI is a small extension to an existing editor.
  - **AD-718d** — LOW. Pure function + small integration with existing call sites. No server changes. Test surface is small and well-bounded.
  - **Wave overall** — LOW.
- **Phantom-API check output:** _Run `pwsh scripts/phantom-api-precheck.ps1 prompts/WAVE-136-DISPATCH.md` after this file lands; expected hits are introduced-by-this-wave (`propose_voice`, `VoiceProposal`, `_parse_voice_proposal`, `applyEmotionalModulation`) and should be flagged in the per-AD prompts' "Verified Against Codebase" footers. Verified-at-HEAD references (`VoiceProfile`, `propose_appearance`, `_parse_appearance_dsl`, `AgentSignals`, `applyExpressionsFromSignals`, `speakResponse`, `PUT /voice-profile` at routers/agents.py:224) all grepped clean during dispatch drafting._
- **Audit trail:**
  - VoiceProfile dataclass + `__post_init__`: `src/probos/crew_profile.py:96-128`. Field on CrewProfile: `:210`.
  - PUT endpoint: `src/probos/routers/agents.py:224-257`.
  - `propose_appearance` template: `src/probos/cognitive/cognitive_agent.py:2592-2722`.
  - `_parse_appearance_dsl` parser template: `src/probos/cognitive/cognitive_agent.py:2724-2782`.
  - `AvatarDSL` Pydantic template: `src/probos/avatars/dsl.py:118` (`ConfigDict(extra="forbid")`).
  - `AgentSignals`: `ui/src/components/profile/avatarSignals.ts:11-23` (`trust_delta`, `load`, `working_state`, `tier3_alert`).
  - `applyExpressionsFromSignals` reference: `ui/src/components/profile/CrewVRM.tsx:95-129`.
  - `speakResponse` extension target: `ui/src/audio/voice.ts:92-110`.
  - ProfileInfoTab voice editor: `ui/src/components/profile/ProfileInfoTab.tsx:52-70`.
  - Wave-plan.yaml entry: `prompts/wave-plan.yaml:3130-3138` (Wave 136, Cluster A wave 3).
  - Highest AD: `PROGRESS.md:11` → AD-721i.
