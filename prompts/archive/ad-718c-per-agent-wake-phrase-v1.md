# AD-718c — Per-agent wake phrase v1

**Status:** READY FOR BUILDER
**Wave:** 137
**Dispatch:** [prompts/WAVE-137-DISPATCH.md](prompts/WAVE-137-DISPATCH.md)
**Depends on:** AD-705 (Wave 137 commit N — wake-word loop substrate; this prompt is commit N+1 and imports the loop's `agentTriggers` option), AD-718a (`parse_voice_proposal` parser + `propose_voice_profile` LLM flow), AD-718 (`VoiceProfile` dataclass + `SetVoiceProfileRequest` Pydantic model + PUT `/voice-profile` route)
**Risk:** **LOW–MEDIUM** — single dataclass field + parser allow-list extension + UI text input + wake-word loop trigger registration
**Estimated tests:** ~7 Python (`tests/test_ad718c_*.py`), ~5 Vitest
**Issue:** [#524](https://github.com/seangalliher/ProbOS/issues/524)
**Build order:** Ships **second** (commit N+1). Imports the wake-word loop substrate from AD-705. **MUST NOT merge before AD-705 lands.**

---

## 1. Goal

Add an optional `wake_phrase` to each agent's `VoiceProfile`. When the wake-word loop is active and an agent's `wake_phrase` is non-empty, saying that phrase routes directly to the agent's `@callsign` chat path — no `@`-typing required.

### Why now (Captain ruling 2026-05-09)

> "I want to say 'Hey Ezri' and have it land in Counselor without me typing the at-sign. The Ship's Computer should also still answer to 'Computer'. Both should coexist."

Implements the per-agent wake-phrase forward-marker filed as AD-718's child during Wave 133. Reuses the existing AD-718a propose / Captain-approve / persist flow — no new approval pipeline, no new endpoints, no new SQLite tables.

---

## 2. Verified Against Codebase (2026-05-09 @ HEAD `31b9e92`)

```
git rev-parse HEAD
  31b9e9278d3a881eb7130966c1d0fb32c6884a2d

# VoiceProfile dataclass
grep -n "class VoiceProfile" src/probos/crew_profile.py
  96: class VoiceProfile:

# Parser allow-lists (CRITICAL — there is NO Pydantic VoiceProposal model)
grep -nE "_ALLOWED_KEYS|_PROFILE_KEYS|class VoiceProposalError|def parse_voice_proposal" src/probos/voice/proposal.py
  33: _ALLOWED_KEYS = {"voice_name", "pitch", "rate", "volume", "rationale"}
  35: _PROFILE_KEYS = ("voice_name", "pitch", "rate", "volume")
  39: class VoiceProposalError(Exception):
  68: def parse_voice_proposal(text: str) -> tuple[VoiceProfile, str]:

# voice/proposal.py module docstring confirms NO Pydantic model
grep -n "no Pydantic" src/probos/voice/proposal.py
  9: Wave 136 dispatch, no Pydantic ``VoiceProposal`` model is introduced;

# CognitiveAgent method (NOTE: dispatch said `propose_voice` — actual method is `propose_voice_profile`)
grep -n "async def propose_voice_profile" src/probos/cognitive/cognitive_agent.py
  2800: async def propose_voice_profile(

# Pydantic request model + PUT route
grep -n "class SetVoiceProfileRequest" src/probos/api_models.py
  227: class SetVoiceProfileRequest(BaseModel):
grep -n "voice-profile" src/probos/routers/agents.py
  226: @router.put("/{agent_id}/voice-profile")
  319: @router.post("/{agent_id}/voice-profile/propose", response_model=ProposeVoiceProfileResponse)

# UI voice profile editor
grep -n "voice-profile\|voice_name" ui/src/components/profile/ProfileInfoTab.tsx
  7: type VoiceProfile,
  54: voice_name: profileData?.voiceProfile?.voice_name ?? '',
  83: fetch(`/api/agent/${agent.id}/voice-profile`,

# AD-705 substrate (this prompt's runtime dependency)
# Builder verifies AD-705 prompt §4 D3 introduces:
#   StartWakeWordLoopOptions.agentTriggers: ReadonlyArray<{ callsign: string; phrase: string }>
# from prompts/ad-705-wake-word-voice-loop-v1.md
```

**Dispatch corrections applied in this prompt** (architect noted during draft, 2026-05-09):

1. Dispatch §5 E3 said `propose_voice` — actual method is **`propose_voice_profile`** (line 2800). Corrected throughout this prompt.
2. Dispatch §5 E2 said "Pydantic mirror in `VoiceProposal`" — **there is no `VoiceProposal` Pydantic model**. AD-718a's `voice/proposal.py` is a parser-only module; bounds are validated by `VoiceProfile.__post_init__` (the dataclass), and the parser uses `_ALLOWED_KEYS` / `_PROFILE_KEYS` constants as the allow-lists. Corrected E2 to extend those constants instead.

**Phantom-API false-positives introduced by this prompt** (will appear in pre-check; document in commit): `voice_profile.wake_phrase` (TypeScript), `wake_phrase` (Python — new dataclass + Pydantic + parser key).

---

## 3. License posture

This prompt introduces **no new third-party dependencies**. License posture unchanged.

---

## 4. Scope (v1 only) — Deliverables

### E1. `wake_phrase` field on `VoiceProfile` dataclass

- **File:** `src/probos/crew_profile.py` lines 96–127 (`VoiceProfile` dataclass).
- Add field: `wake_phrase: str = ""`. Default empty = no per-agent wake phrase (system-wide "Computer" only).
- Extend `__post_init__`:
  - Strip whitespace: `object.__setattr__(self, 'wake_phrase', self.wake_phrase.strip())` (or assignment if dataclass not frozen — Builder verifies; current `VoiceProfile` is not frozen, so assignment works).
  - Validate length: `if len(self.wake_phrase) > 50: raise ValueError(f"wake_phrase must be ≤50 chars, got {len(self.wake_phrase)}")`.
  - Validate no anchor/alias/tag tokens: `if '&' in self.wake_phrase or '!!' in self.wake_phrase: raise ValueError(...)`. Defense-in-depth (mirrors AD-718a's parser-side check). Reviewer will look for this — it's not redundant because the dataclass is also constructed directly from PUT requests, not just parser output.
- Extend `from_dict` to round-trip the field (line ~125 — keep the existing pattern, add `'wake_phrase'` to the tuple).
- `to_dict` already uses `asdict()` so it picks up the new field automatically.

### E2. Parser allow-list update

- **File:** `src/probos/voice/proposal.py`.
- Line 33: extend `_ALLOWED_KEYS = {"voice_name", "pitch", "rate", "volume", "rationale", "wake_phrase"}`.
- Line 35: extend `_PROFILE_KEYS = ("voice_name", "pitch", "rate", "volume", "wake_phrase")`.
- **No new Pydantic model.** Bounds for `wake_phrase` are validated entirely by `VoiceProfile.__post_init__` (E1) — single source of truth, mirrors AD-718a's design.
- Parser change is additive: existing LLM responses that omit `wake_phrase` parse identically (the dataclass default is `""`).

### E3. Capability-prompt update — `propose_voice_profile`

- **File:** `src/probos/cognitive/cognitive_agent.py` line 2800 (`async def propose_voice_profile(...)`).
- Extend the LLM `instructions` block to inform the agent it MAY propose a `wake_phrase`. Suggested phrasing (Captain reviews):

  > "You may also propose an optional `wake_phrase` (≤ 50 characters): a short phrase the Captain can speak to address you directly without typing `@`. Two-syllable phrases work best. May be your first name, callsign, or rank. Keep it short and distinct from other crew members. If you have no preference, omit the field — the system-wide 'Computer' wake will still route to you when the Captain types `@<your callsign>`."

- Update the example JSON in the instructions block to show `"wake_phrase": "Ezri"` (or similar) on at least one example.
- The instructions text MUST NOT contain phrases that match `_CAPABILITY_GAP_RE` (`can't`, `don't have`, `unable to` — see copilot-instructions.md "prompt text triggering gap regex"). Builder verifies.

### E4. API surface

- **File:** `src/probos/api_models.py` lines 227–238 (`SetVoiceProfileRequest`).
- Add field: `wake_phrase: str = ""`. Pydantic validates type + default; the bounds check happens server-side at `VoiceProfile(...)` construction in the PUT handler.
- **File:** `src/probos/routers/agents.py` lines 226–250 (`set_agent_voice_profile`).
- Forward the new field: in the `VoiceProfile(...)` constructor call (around line 240), add `wake_phrase=req.wake_phrase`. The dataclass `__post_init__` handles validation; `ValueError` is already mapped to HTTP 400.
- GET surface: `VoiceProfile.to_dict()` already serializes the new field (uses `asdict()`); no GET handler change needed.

### E5. UI: wake-phrase row in voice editor

- **File:** `ui/src/components/profile/ProfileInfoTab.tsx`.
- Extend the `VoiceProfile` TypeScript type (or its source — Builder follows the existing import on line 7) to include `wake_phrase?: string`.
- Add a `<input type="text" maxLength={50}>` field labeled "Wake phrase" in the voice editor block. State managed alongside the existing `voice_name` / `pitch` / `rate` / `volume` state (line 53 onward).
- Default: empty string (line 54-pattern: `wake_phrase: profileData?.voiceProfile?.wake_phrase ?? ''`).
- The `persistVoiceProfile` body (line 82+) sends the new field through the existing PUT.
- The "Propose" affordance from AD-718a (which calls `POST /voice-profile/propose` and renders the proposal preview) now ALSO surfaces the proposed `wake_phrase`. Captain can hand-edit before approve.
- **No emoji.** Inline-SVG icons only if any new icon is added (none required for v1 — text input + label is sufficient).

### E6. UI: wake-phrase loaded into wake-word loop

- **File:** `ui/src/audio/wakeWord.ts` (introduced by AD-705 D3) — extend the loop's start path.
- The single owner from AD-705 D9 (the `useEffect` in `IntentSurface.tsx` keyed on `wakeWordEnabled`) collects per-agent triggers from the store:

  ```ts
  const agentTriggers = Array.from(useStore.getState().agents.values())
    .filter(a => a.voice_profile?.wake_phrase && a.voice_profile.wake_phrase.length > 0)
    .map(a => ({ callsign: a.callsign, phrase: a.voice_profile!.wake_phrase! }));
  ```

- Pass via `startWakeWordLoop(onWake, { agentTriggers })`.
- Subscribe to `useStore` updates (debounced `PERAGENT_TRIGGER_DEBOUNCE_MS = 500` per AD-705 D3) — when agents update, re-collect and call `stopWakeWordLoop()` + `startWakeWordLoop(...)` with the new list. Builder picks the cleanest restart pattern; reviewer flags any path that double-starts the loop.
- The router (AD-705 D4 `routeWakeTranscript`) already accepts agent triggers via the `agents` map's `voice_profile.wake_phrase` field — no router change in this prompt; it just starts seeing non-empty values.

### E7. Governance — Captain approves the phrase (no new flow)

Reuses AD-718a flow byte-for-byte:

1. Agent's `propose_voice_profile` (E3) returns a `VoiceProfile` candidate that may carry `wake_phrase`.
2. Existing UI (E5) renders the candidate including the wake phrase.
3. Captain hand-edits if desired, clicks Approve.
4. Existing `PUT /voice-profile` (E4) persists with `proposal_rationale` non-empty.
5. Existing approve-from-proposal episode hook (AD-718a D7) writes the episode. The `signals` dict gains a `wake_phrase` key (Builder adds one line to the episode-signals construction in `routers/agents.py` around the existing rationale-writing path).

**No new approval flow. No new endpoints. No new tables.**

### E8. UI: indicator label on per-agent fire (Captain answer Q3 + Q4 hint, 2026-05-09)

When the wake-word loop fires on a per-agent trigger (router returns `surface='agent'`), the `WakeWordIndicator` (AD-705 D7) MAY surface the matched callsign briefly during the `capturing` state (e.g. small text label "→ Ezri" next to the dot, fading after capture commits). Builder picks: subtle one-line text, font-size 11 px, color `#aaaabb`, no emoji, fades out 800 ms after `capturing → submit` transition. Reviewer fails any persistent badge that lingers past the capture window.

---

## 5. Tests required

### Python (`tests/test_ad718c_wake_phrase.py` — new file, ≥ 7 cases)

1. `VoiceProfile(wake_phrase="Hey Ezri")` constructs cleanly; `to_dict()`/`from_dict()` round-trip preserves the value.
2. `VoiceProfile(wake_phrase=" Ezri ")` strips whitespace in `__post_init__` → `"Ezri"`.
3. `VoiceProfile(wake_phrase="x" * 51)` raises `ValueError` (length bound).
4. `VoiceProfile(wake_phrase="bad &anchor")` raises `ValueError` (anchor token defense-in-depth).
5. `parse_voice_proposal('{"voice_name":"","pitch":1.0,"rate":1.0,"volume":0.8,"wake_phrase":"Ezri","rationale":"r"}')` returns a `VoiceProfile` with `wake_phrase="Ezri"`.
6. `parse_voice_proposal('{"voice_name":"","pitch":1.0,"rate":1.0,"volume":0.8,"wake_phrase":"' + "x"*51 + '","rationale":"r"}')` raises `VoiceProposalError("schema_violation", ...)` (parser delegates bound check to `VoiceProfile.__post_init__`).
7. PUT `/api/agent/{id}/voice-profile` with `{"wake_phrase": "Ezri", ...}` round-trips; subsequent GET returns `wake_phrase="Ezri"`.

### Vitest (≥ 5 cases, distributed across new + existing test files)

`ui/src/__tests__/ProfileInfoTab.wakePhrase.test.tsx`:

8. Input field renders with `maxLength={50}`.
9. Editing the field + clicking Save persists via PUT (mocked fetch) with the new value.
10. Loading a profile with `wake_phrase="Ezri"` populates the input.

`ui/src/__tests__/wakeWord.perAgent.test.ts`:

11. `routeWakeTranscript("Ezri, run a scan", agentsMap)` where agentsMap has Ezri with `voice_profile.wake_phrase="Ezri"` → returns `surface='agent'`, `agentCallsign='Ezri'`, `cleanedText='run a scan'`.
12. Empty `wake_phrase` for an agent does NOT register a trigger (collector filter check).

---

## 6. What this does NOT change (out of scope — hard fences)

- No new endpoints. PUT `/voice-profile` and POST `/voice-profile/propose` keep their existing shapes (just one optional new field on PUT).
- No new SQLite tables. Field rides on the existing `crew_profiles.data` JSON blob.
- No new Pydantic model. (Dispatch §5 E2 said "VoiceProposal Pydantic mirror" — corrected: no such model exists; AD-718a is parser-only.)
- No global per-agent wake-phrase opt-out toggle (Captain answer Q4, 2026-05-09: rely on empty `wake_phrase` field; if all agents have empty, only system "Computer" wake fires). Forward marker only if needed.
- No custom wake-word training pipeline (AD-705c forward marker).
- No training UI (AD-705c forward marker).
- No change to the AD-705 wake-word loop's state machine, router signature, indicator component, or fallback behavior beyond what AD-705 D3's `agentTriggers` option already supports.
- Edge Online Natural TTS path stays. Any change to `voice.ts` synthesis is a HARD STOP.

---

## 7. Hard-stop conditions

Builder MUST stop and surface to Architect if any of the following occur:

1. **AD-705 not yet merged.** This prompt's E6 imports `wakeWord.ts`'s `agentTriggers` option, which is introduced by AD-705 D3. If `git log --oneline | grep AD-705` returns nothing on the current branch, HARD STOP — wait for AD-705 to land first.
2. **Phantom API.** `voice_profile.wake_phrase` (TS) and `wake_phrase` (Python `VoiceProfile` field, parser allow-list, Pydantic field) are introduced by THIS prompt. Pre-check false-positives — document in commit.
3. **Architectural contract change required.** Any change to `BaseAgent`, `IntentMessage`, the AD-718a parser's overall shape (beyond extending `_ALLOWED_KEYS`/`_PROFILE_KEYS`), or the wake-word loop's state machine is a HARD STOP.
4. **Working tree integrity.** Pre-flight `git diff --numstat | sort -k2nr | head -5`. Any tracked file with > 200 lines deleted that the Builder did not author is a stop-the-line event.
5. **License creep.** This prompt introduces NO new deps. Any new third-party dep is a HARD STOP.
6. **Emoji in diff.** Any emoji literal in `*.tsx` / `*.ts` / `*.py` is a HARD STOP. HXI Design Principle #3.
7. **Anchor / alias / tag tokens accepted by `wake_phrase`.** AD-718a's parser-side check rejects them at the parser surface; the dataclass `__post_init__` (E1) is the second check. If a `wake_phrase` containing `&`, `!!`, or `*<word>` round-trips through PUT, HARD STOP.
8. **`exec` / `eval` / `compile` / `pickle.loads` on `wake_phrase`.** HARD STOP.
9. **Default-True on the field.** `wake_phrase` MUST default to empty string. Any default that pre-populates a non-empty wake phrase is a HARD STOP — Captain explicitly authors via Approve flow.
10. **New approval flow.** If E7 introduces any new endpoint, episode hook, or approval gate beyond the existing AD-718a `proposal_rationale` path, HARD STOP. Reuse only.
11. **Test gate failure under `-n 0` after passing under `-n 16`.** Order-dependent test pollution → quarantine via BF entry pointing at AD-682, do NOT block the wave.

---

## 8. Acceptance criteria

Builder MUST:

1. Run `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-718c-per-agent-wake-phrase-v1.md` and document the expected `wake_phrase` false-positives.
2. Pass per-prompt Python test gate: `pytest tests/test_ad718c_*.py -v -n 0`. ≥ 7 cases.
3. Pass UI test gate: `cd ui && npx vitest run`. ≥ 5 new cases (E5 + E6).
4. Pass full Python gate: `pytest tests/ -q -n 16 --dist=loadfile` (fall back to `-n 8` per BUILDER-EXECUTION-PLAN.md).
5. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
6. PROGRESS.md unchanged on the highest-AD line (AD-721i stays; AD-718c is a sub-letter, does not bump highest). Add one-line entry: "AD-718c — per-agent wake phrase v1 shipped (Wave 137, commit N+1)".
7. `decisions-era-4-evolution.md` (or current era) appended with an AD-718c entry citing this prompt + wave dispatch.
8. `docs/development/roadmap.md` Bug Tracker — no new BF entries expected on the happy path.
9. Issue [#524](https://github.com/seangalliher/ProbOS/issues/524) closed via the merge commit message.
10. License attribution: no new attributions needed (no new deps).
11. Memory artifacts: no new architect-memory entry expected. The "AD-718a parser-only design + dataclass-as-bounds-truth extends cleanly to wake_phrase" pattern is already learned; recurrence here only confirms the pattern works.

---

## 9. Engineering principles compliance (Builder verifies — copilot-instructions.md)

- ✅ **SOLID — Single source of truth for bounds.** `VoiceProfile.__post_init__` (E1) is the single bounds-truth; `_ALLOWED_KEYS` / Pydantic just allow the field through. Pattern matches AD-718a / AD-718.
- ✅ **Defense in depth.** Parser allow-list (E2) + Pydantic schema (E4) + dataclass `__post_init__` (E1) — three independent boundary checks.
- ✅ **No private-attr access.** All wiring uses public APIs.
- ✅ **No emoji.** No HXI emoji introduced.
- ✅ **Tier-3 propagate** for `ValueError` from dataclass → HTTP 400 in PUT handler (existing pattern).
- ✅ **Type annotations.** `wake_phrase: str = ""` on dataclass + Pydantic + parser allow-list constants. UI: `wake_phrase?: string`.
- ✅ **Logging quality.** Existing PUT handler's structured logs cover the new field automatically (it's a standard request param).
- ✅ **Episodic completeness.** Reuses AD-718a's approve-from-proposal episode hook; `signals` gains `wake_phrase` key (one-line addition).
- ✅ **No new Pydantic config in `config.py`.** This prompt extends an existing API request model only.
- ✅ **Boundary tests.** Happy path (E5/E6 round-trips) + error case (length bound) + edge case (empty `wake_phrase` does not register a trigger) covered in §5.
- ✅ **Async discipline.** No new async paths; all wiring is sync field forwarding.

---

## 10. Forward markers (none new)

This AD itself **was** the forward marker. No new forward markers introduced.

If Captain post-merge feedback surfaces a need for:

- **Global per-agent wake-phrase disable toggle** (single switch to suppress ALL per-agent triggers without editing each profile) — file as AD-718c-1.
- **Wake-phrase collision detection** (warn Captain when two agents propose the same phrase) — file as AD-718c-2.
- **Voice-trained per-agent wake** (custom ONNX per agent) — already covered by AD-705c forward marker; do not duplicate.

---

## 11. Tracking

| Tracker | Update |
|---|---|
| `PROGRESS.md` | Add one-line entry: "AD-718c — per-agent wake phrase v1 shipped (Wave 137)" |
| `progress-era-*.md` (current era) | Add detailed entry citing tests + Captain approve flow reuse |
| `DECISIONS.md` (or `decisions-era-4-evolution.md`) | Append AD-718c entry citing wave dispatch |
| `docs/development/roadmap.md` | Mark AD-718c closed in roadmap |
| GitHub Issues | Close [#524](https://github.com/seangalliher/ProbOS/issues/524) |
| `prompts/wave-plan.yaml` | NOT modified by this prompt (Captain's instruction) |
| `prompts/build-reports/wave-137-ad-718c.md` | New build report per BUILDER-EXECUTION-PLAN.md |

---

## 12. Issue link

[#524](https://github.com/seangalliher/ProbOS/issues/524)
