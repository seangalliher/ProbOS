# AD-718a — Agent-authored voice profile (v1)

**Wave:** 136
**Depends on:** AD-718 (SHIPPED Wave 133, voice-profile baseline), AD-721d (SHIPPED Wave 134, agent-authored DSL pattern template)
**Pairs with:** AD-718d (same wave, ships AFTER this prompt — see §10)
**Issue:** [#522](https://github.com/seangalliher/ProbOS/issues/522)
**Risk:** LOW–MEDIUM (new endpoint + new capability + parser; reuses existing storage and existing PUT)
**Estimated tests:** ≥ 14 Python + 3 Vitest

> **Build order is HARD:** AD-718a ships first (commit N). AD-718d ships second (commit N+1). Do NOT begin AD-718d until this prompt's gate is green.
>
> **Builder:** read `prompts/WAVE-136-DISPATCH.md` for cross-AD context, license posture, and the engineering-principles checklist. Read `prompts/BUILDER-EXECUTION-PLAN.md` for the standing test-gate command and quarantine procedure. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 1. Goal

Transpose the AD-721d agent-authored-DSL pattern onto voice. The agent reflects on its `CrewProfile.personality` (Big-Five), `display_name`, `department`, and `rank`, then **proposes** a candidate `VoiceProfile`. The Captain reviews a preview (showing the four fields and a sample utterance) and either **Approves** (persists via the existing `PUT /api/agent/{id}/voice-profile`), **Requests revisions** (re-runs `propose_voice_profile()` with an optional Captain note), or **Rejects** (closes the preview without persisting).

**Two-step preview-then-approve flow**, mirroring AD-721d byte-for-byte. Captain just lived through AD-721d; surfacing a different flow for voice would be jarring.

## 2. Why now

- Wave 133 closed AD-718 (per-agent voice profile baseline). Counselor (Echo) currently uses operator-supplied or default voice values.
- AD-721d (Wave 134) established the agent-authored data-artifact pattern (LLM proposes → Captain approves). Voice is the natural sibling.
- Cluster A roadmap target: every standing-crew agent owns its voice the way it owns its face by end of Wave 136.

## 3. Verified Against Codebase (2026-05-09)

```
grep -n "class VoiceProfile" src/probos/crew_profile.py
   96: class VoiceProfile:
  105:     voice_name: str = ""
  110:     def __post_init__(self) -> None:
  111:         if not 0.0 <= self.pitch <= 2.0:
  113:         if not 0.1 <= self.rate <= 10.0:
  115:         if not 0.0 <= self.volume <= 1.0:
  124:     # from_dict gates fields to the four allowed keys

grep -n "voice-profile\|set_agent_voice_profile\|SetVoiceProfileRequest" src/probos/routers/agents.py
   19: from ..api_models import SetVoiceProfileRequest, ...
  224: @router.put("/{agent_id}/voice-profile")
  225: async def set_agent_voice_profile(...)
  227:     req: SetVoiceProfileRequest,

grep -n "class SetVoiceProfileRequest" src/probos/api_models.py
  227: class SetVoiceProfileRequest(BaseModel):
        # Fields: voice_name: str = "", pitch: float = 0.9,
        #         rate: float = 0.95, volume: float = 0.8.

grep -n "propose_appearance\|_parse_appearance_dsl\|_MAX_PROPOSAL_BYTES" src/probos/cognitive/cognitive_agent.py
  2592: async def propose_appearance(self, ...) -> AvatarDSL:
  2721:     return self._parse_appearance_dsl(text)
  2724: def _parse_appearance_dsl(cls, text: str) -> "AvatarDSL":

grep -n "VoiceProfile\|voiceProfile\|currentProfile" ui/src/components/profile/ProfileInfoTab.tsx
   3: import { ... type VoiceProfile } from '../../audio/voice';
  52: // AD-718: Per-agent voice profile editor state.
  53: const [currentProfile, setCurrentProfile] = useState<VoiceProfile>({...});
  75: const persistVoiceProfile = (next: VoiceProfile): void => {
  76:     fetch(`/api/agent/${agent.id}/voice-profile`, ...)
```

**Dispatch corrections folded in:**

- Dispatch §4 D1 specified a `VoiceProposal` Pydantic model. **Captain override (per dispatch reply Q on scope):** NO Pydantic model. The proposal is a `VoiceProfile` instance round-tripped through the dataclass; rationale is a sibling field on the response envelope, not embedded in `VoiceProfile`. This means **two** independent server-side bounds checks (parser→`VoiceProfile.__post_init__` on the propose path; `SetVoiceProfileRequest`→`VoiceProfile.__post_init__` on the approve path), not three. Defense-in-depth still holds — both layers see every field.
- Dispatch §4 D2 named the capability `propose_voice(...)`. **Captain override:** name is `propose_voice_profile()` to mirror `CrewProfile.voice` and the existing `voice-profile` endpoint segment.
- Dispatch §6 row "Episodic write only on approve-from-proposal" stands. Captain confirmed Q4 defer: hand-edit PUT writes no episode in this wave; the proposal-rationale → approval path IS in scope and is the learning signal.

## 4. Scope (v1 only)

D1–D9 below. Two-step preview-then-approve flow. No proposal persistence (transient until approve).

## 5. Non-goals (deferred forward markers)

- **AD-718a-1** — proposal revision cycle if v1 needs it (e.g. multi-turn refinement, persisted proposal log). v1 ships single-shot propose with "Request revisions" re-invoking the LLM.
- **AD-718b** ([#523](https://github.com/seangalliher/ProbOS/issues/523)) — third-party TTS backend. Firewalled OFF; zero new deps in this wave.
- **Episode-write parity for hand-edit PUT.** Captain deferred (Q4): hand-edits carry no rationale to learn from.
- **Persisted proposal log** (`VoiceProposalStore` or similar). Voice changes are reversible at the picker; proposals stay transient.

## 6. Deliverables

### D1 — `VoiceProposalError` exception + parser module

**New file:** `src/probos/voice/__init__.py` (empty package init).
**New file:** `src/probos/voice/proposal.py`.

```python
class VoiceProposalError(Exception):
    """Raised when an LLM voice-proposal response fails parsing or validation."""
```

Module also defines:

- `_MAX_PROPOSAL_BYTES = 16 * 1024` (mirror `_MAX_PROPOSAL_BYTES` in `cognitive_agent.py`).
- `_MAX_DEPTH = 8`.
- A pure helper `parse_voice_proposal(text: str) -> tuple[VoiceProfile, str]` returning `(profile, rationale)`.

**Parse pipeline (mirror `_parse_appearance_dsl` byte-for-byte):**

1. Hard-cap input size at `_MAX_PROPOSAL_BYTES`. Over-cap → `VoiceProposalError("response oversized")`.
2. Reject any byte-level occurrence of `&`, `*`, or `!!` (anchor / alias / tag tokens). Hit → `VoiceProposalError("anchor/alias/tag rejected")`.
3. `yaml.safe_load(text)`. **Forbidden:** `yaml.load` without the safe loader, `pickle.loads`, `exec`, `eval`, `compile`, `importlib.import_module`. Reviewer greps the diff.
4. Walk the parsed object; reject documents nested deeper than `_MAX_DEPTH`. Hit → `VoiceProposalError("nesting too deep")`.
5. The parsed object MUST be a dict with the keys `{voice_name, pitch, rate, volume, rationale}`. Unknown keys → `VoiceProposalError("unknown key: <k>")`. Missing optional keys are filled with `VoiceProfile` defaults (`voice_name=""`, `pitch=0.9`, `rate=0.95`, `volume=0.8`); `rationale` defaults to `""`.
6. Construct `VoiceProfile(voice_name=..., pitch=..., rate=..., volume=...)`. The dataclass `__post_init__` (crew_profile.py:110-116) re-runs all bounds. `ValueError` from `__post_init__` → wrap as `VoiceProposalError(str(e))`.
7. Return `(profile, rationale_str_truncated_to_500_chars)`.

**No `VoiceProposal` Pydantic model.** The dataclass is the single source of bounds truth.

### D2 — `propose_voice_profile()` capability on `CognitiveAgent`

**Modify:** `src/probos/cognitive/cognitive_agent.py`. Mirror `propose_appearance` at L2592-L2722 byte-for-byte at the structural level.

```python
async def propose_voice_profile(
    self,
    *,
    captain_note: str = "",
    llm_client: LLMClient | None = None,
) -> tuple[VoiceProfile, str]:
    """Reflect on personality + role, propose a candidate (VoiceProfile, rationale).

    NOT persisted. Caller (the propose endpoint) returns the candidate
    to the UI; Captain approval flows through the existing
    PUT /voice-profile endpoint.

    Raises:
        VoiceProposalError: LLM call failed, response oversized,
            or schema validation rejected the proposal.
    """
```

Implementation rules:

1. **Prompt construction.** Pull `CrewProfile.personality` (Big-Five), `display_name`, `department`, `rank` from the agent's profile (`self._profile` or the existing accessor that `propose_appearance` uses — verify and reuse). Include a one-line description of the Web Speech API knob semantics (`pitch ∈ [0, 2]`, `rate ∈ [0.1, 10]`, `volume ∈ [0, 1]`; `voice_name` is the exact `SpeechSynthesisVoice.name` to prefer or `""` for the global default). If `captain_note` is non-empty, include it verbatim under a "Captain note" section so the Builder's "Request revisions" flow propagates context.
2. **Strict structured output.** Same pattern as `propose_appearance`: where the LLM tier exposes `response_format={"type":"json_object"}`, use it; otherwise the system prompt instructs strict JSON. Tier: **fast** (Sonnet via Copilot proxy, 30s timeout) — same tier as `propose_appearance`.
3. **Hardened parse path.** Pass the LLM response to `parse_voice_proposal()` from D1. Any failure → `VoiceProposalError` propagates.
4. **No persistence in this method.** Returns `(VoiceProfile, rationale)`.
5. **Logging.** Tier-2 log-and-degrade only on the LLM-call layer; schema violations propagate.

### D3 — `POST /api/agent/{agent_id}/voice-profile/propose` endpoint

**Modify:** `src/probos/routers/agents.py`. Place the new route adjacent to the existing PUT at L224.

```python
@router.post("/{agent_id}/voice-profile/propose")
async def propose_agent_voice_profile(
    agent_id: str,
    req: ProposeVoiceProfileRequest,  # see D5
) -> ProposeVoiceProfileResponse:    # see D5
```

- Looks up the agent via the existing runtime accessor (mirror what `propose_appearance` endpoint uses; verify the helper at HEAD before writing).
- Calls `await agent.propose_voice_profile(captain_note=req.captain_note)`.
- On `VoiceProposalError`: HTTP 422 with `{"detail": "<reason>"}`.
- On agent-not-found: HTTP 404 (consistent with the existing GET/PUT).
- On success: HTTP 200 with `ProposeVoiceProfileResponse(agent_id=agent_id, voice_profile={...}, rationale=...)`.
- **Does NOT persist.** Calling twice returns two independent proposals (LLM-non-determinism is acceptable).
- `async def`. No `subprocess.run`. No `asyncio.ensure_future`.

### D4 — Approve flow extends existing PUT endpoint

**Modify:** `src/probos/api_models.py` `SetVoiceProfileRequest`:

```
===SEARCH===
class SetVoiceProfileRequest(BaseModel):
    """Request body for per-agent voice profile (AD-718)."""
    voice_name: str = ""
    pitch: float = 0.9
    rate: float = 0.95
    volume: float = 0.8
===REPLACE===
class SetVoiceProfileRequest(BaseModel):
    """Request body for per-agent voice profile (AD-718, extended AD-718a).

    ``proposal_rationale`` is set ONLY on approve-from-proposal flows
    (see AD-718a). Hand-edits leave it empty; episode-write is gated on
    a non-empty value.
    """
    voice_name: str = ""
    pitch: float = 0.9
    rate: float = 0.95
    volume: float = 0.8
    proposal_rationale: str = ""  # AD-718a: non-empty iff approve-from-proposal
===END REPLACE===
```

**Modify:** `src/probos/routers/agents.py` `set_agent_voice_profile` (L224-L257):

- Existing flow: build `VoiceProfile(voice_name=..., pitch=..., rate=..., volume=...)` (the new field is NOT passed to the dataclass — `from_dict` already gates to the four canonical keys at crew_profile.py:124).
- After persistence: **if `req.proposal_rationale` is non-empty**, write an episode with:
  - `intent="voice_profile_change"`
  - `signals={"old_voice": old_voice_dict, "new_voice": new_voice_dict, "rationale": req.proposal_rationale, "agent_id": agent_id}`
  - Use the existing episode-write helper that `propose_appearance` approval path uses; verify the symbol name at HEAD before referencing.
- Hand-edits (empty `proposal_rationale`) follow the existing path unchanged. **No new episode.**

### D5 — API request/response models

**Modify:** `src/probos/api_models.py`. Add alongside the existing voice/appearance models (around L227).

```python
class ProposeVoiceProfileRequest(BaseModel):
    """AD-718a: Optional Captain revision note for "Request revisions" flows."""
    captain_note: str = ""


class ProposeVoiceProfileResponse(BaseModel):
    """AD-718a: Validated VoiceProfile candidate returned for Captain review (NOT yet persisted)."""
    agent_id: str
    voice_profile: dict  # VoiceProfile.to_dict() shape
    rationale: str       # agent's reasoning, max 500 chars
```

### D6 — "Propose voice" affordance + preview surface

**Modify:** `ui/src/components/profile/ProfileInfoTab.tsx` (extend the voice editor block at L52-L80).

Two new pieces of component state:

```ts
const [proposal, setProposal] = useState<VoiceProfile | null>(null);
const [proposalRationale, setProposalRationale] = useState<string>('');
```

UI affordances (all stroke-based inline SVG, `strokeWidth: 1.5`, `strokeLinecap: round`; active amber `#f0b060`, inactive dim `#666680`; **NO emoji**):

- **"Propose voice" button** — calls `POST /api/agent/{id}/voice-profile/propose` with `{captain_note: ""}`. On 200 → `setProposal(response.voice_profile)`, `setProposalRationale(response.rationale)`. On 422/404 → surface error toast via existing pattern.
- **Preview panel** (renders only when `proposal !== null`) — shows the four fields in a diff-style layout (`Current 0.9 → Proposed 1.05`), the rationale text, and:
  - **Sample button** — calls `speakResponse("This is how I would sound.", proposal, agent.id)` with the **proposed** profile. (No signals yet — AD-718d has not shipped at AD-718a build time. Pass `undefined` for the signals slot if `speakResponse` already takes one; if it does not, do NOT modify the signature here. Modifying `speakResponse` is AD-718d's deliverable.)
  - **Approve button** — calls `PUT /api/agent/{id}/voice-profile` with `{voice_name, pitch, rate, volume, proposal_rationale: proposalRationale}`. On 200 → `setProposal(null)`, `setProposalRationale('')`, refresh `currentProfile` from response.
  - **Request revisions button** — opens an inline text input (max 280 chars). On submit, re-calls `POST /voice-profile/propose` with the note as `captain_note`. Updates `proposal` and `proposalRationale`.
  - **Reject button** — `setProposal(null)`, `setProposalRationale('')`. No PUT.

Captain MAY hand-edit the proposed values directly in the preview before approving (the inputs in the existing voice editor remain editable while the preview is visible; the proposal is a *suggestion*, not a lock).

### D7 — Tests (parser)

**New file:** `tests/test_ad718a_voice_proposal_parser.py` (≥ 7 tests).

- `test_happy_path_returns_profile_and_rationale` — well-formed JSON with all fields → returns `(VoiceProfile, "rationale text")`.
- `test_oversized_response_rejected` — input > 16 KiB → `VoiceProposalError("response oversized")`.
- `test_yaml_anchor_rejected` — input contains `&anchor` → `VoiceProposalError`.
- `test_yaml_alias_rejected` — input contains `*alias` → `VoiceProposalError`.
- `test_yaml_tag_rejected` — input contains `!!python/object` → `VoiceProposalError`.
- `test_deep_nesting_rejected` — 9-level nested dict → `VoiceProposalError("nesting too deep")`.
- `test_pitch_out_of_bounds_rejected` — `pitch: 3.0` → `VoiceProposalError` (delegates to `VoiceProfile.__post_init__`).
- `test_unknown_key_rejected` — `{"hostile": true}` in payload → `VoiceProposalError("unknown key: hostile")`.
- `test_missing_optional_keys_use_defaults` — `{"rationale": "x"}` only → returns `VoiceProfile()` defaults.
- `test_no_eval_or_exec_in_module` — AST scan of `src/probos/voice/proposal.py` produces zero `Call` nodes whose function id is `eval` / `exec` / `compile` / `pickle.loads`.

### D8 — Tests (capability + endpoint)

**New file:** `tests/test_ad718a_propose_voice.py` (≥ 6 tests).

- `test_propose_voice_profile_happy_path` — fake LLM client returning a known JSON payload → `(VoiceProfile, rationale)`.
- `test_propose_voice_profile_raises_on_malformed_llm` — LLM returns non-JSON → `VoiceProposalError`.
- `test_propose_endpoint_returns_proposal` — `POST /voice-profile/propose` → 200 with `voice_profile` + `rationale`.
- `test_propose_endpoint_422_on_parser_failure` — patched parser raises → 422.
- `test_propose_endpoint_404_when_agent_missing` — unknown `agent_id` → 404.
- `test_approve_with_rationale_writes_episode` — `PUT /voice-profile` with `proposal_rationale="…"` → episode store gains one entry with `intent="voice_profile_change"`.
- `test_approve_without_rationale_writes_no_episode` — `PUT /voice-profile` with `proposal_rationale=""` → episode store unchanged.
- `test_round_trip_propose_then_approve` — propose → approve → re-fetch profile → values match.

### D9 — Tests (UI / Vitest)

**New file:** `ui/src/__tests__/ProfileInfoTab.proposeVoice.test.tsx` (≥ 5 tests).

- `test_propose_button_renders` — button present in voice section.
- `test_propose_button_calls_endpoint` — click → fetch mock receives `POST /voice-profile/propose`.
- `test_preview_renders_proposal_diff` — after 200, preview shows `Current → Proposed` for each field plus rationale.
- `test_approve_calls_put_with_rationale` — click Approve → fetch mock receives `PUT /voice-profile` body containing `proposal_rationale`.
- `test_reject_clears_preview_without_put` — click Reject → preview gone, no PUT call.
- `test_request_revisions_recalls_propose_with_note` — submit a Captain note → second `POST /voice-profile/propose` with `captain_note` populated.

## 7. Hard-stop conditions (verbatim from `WAVE-136-DISPATCH.md` §8)

1. **Phantom API.** A grep of any asserted method/class/endpoint at HEAD returns zero matches AND the prompt does not introduce it. The four NEW symbols introduced by this wave (`propose_voice_profile`, `parse_voice_proposal` / `VoiceProposalError` / `_MAX_PROPOSAL_BYTES` in voice/proposal.py, `POST /voice-profile/propose`) are **introduced by this prompt**; flagging them as missing is a false positive.
2. **Architectural contract change required.** Any change to `VoiceProfile`'s public shape (adding/removing fields), to `AgentSignals`, to `CognitiveAgent`'s base contract, or to the existing PUT endpoint's request *response* shape is a **hard stop**. AD-718a layers ON TOP of `VoiceProfile`; it does NOT modify the dataclass. Adding `proposal_rationale` to `SetVoiceProfileRequest` is the ONE exception to "no contract change" — it is additive, defaulted to `""`, and out-of-band of the dataclass.
3. **Pydantic vs dataclass tension.** N/A in this prompt — Captain override removed `VoiceProposal` Pydantic. `VoiceProfile.__post_init__` is the single source of bounds truth. If a future prompt re-introduces a Pydantic layer and the two disagree on bounds, STOP and surface.
4. **Working tree integrity.** Pre-flight `git diff --numstat | sort -k2nr | head -5`. Any tracked file with > 200 lines deleted that the Builder did not author is a stop-the-line event (per user-memory note 2026-05-08).
5. **Test gate failure under `-n 0` after passing under `-n 16`.** Order-dependent test pollution. Quarantine via BF entry pointing at AD-682; do NOT block the wave (per BUILDER-EXECUTION-PLAN.md hard-stop rules).
6. **License creep.** Any new third-party Python or JS dep is a hard stop. Wave 136's license posture is "zero new deps."
7. **Emoji in diff.** Any emoji literal in `*.tsx` / `*.ts` / `*.py` of the diff is a hard stop. HXI Design Principle #3 is non-negotiable.
8. **Modulation writes to trust.** N/A in this prompt (AD-718d concern); listed for parity.
9. **`exec` / `eval` / `compile` / `pickle.loads` on LLM output.** Hard stop. Reviewer greps the diff and `voice/proposal.py` AST.
10. **Anchor / alias / tag tokens accepted by the parser.** If a test inputs `&anchor` and the parser does NOT raise, hard stop — defense-in-depth has been weakened.

## 8. Forward markers

- **AD-718a-1** — proposal revision cycle if v1 needs more (e.g. multi-turn refinement, persisted proposal log). File at gate-3 if "Request revisions" UX feedback indicates v1 is insufficient.
- **AD-718-1** — voice on multi-agent surface (filed during Wave 135 per dispatch §10). Independent of AD-718a; does not block.

## 9. What this AD does NOT change

- `VoiceProfile` dataclass shape (extended only by additive consumer; `__post_init__` unchanged).
- `crew_profile.py` `ProfileStore` schema (no new SQLite table).
- The AD-721 `CrewVRM` runtime expression layer.
- `speakResponse` signature in `voice.ts` — that is AD-718d's deliverable. AD-718a calls `speakResponse(text, proposal, agent.id)` using the **existing** signature (which already takes `agent_id` as the 3rd argument per voice.ts:92-110).
- The hand-edit branch through `PUT /voice-profile` — episode write is gated on a non-empty `proposal_rationale` only.

## 10. Build order

**This prompt ships first (commit N).** Do NOT begin AD-718d until:

1. `tests/test_ad718a_*.py` all green under `-n 0`.
2. `ui/src/__tests__/ProfileInfoTab.proposeVoice.test.tsx` green under `cd ui && npx vitest run`.
3. Full gate green: `pytest tests/ -q -n 16 --dist=loadfile` (or `-n 8` per BUILDER-EXECUTION-PLAN.md fallback).
4. Commit landed and PROGRESS.md / DECISIONS-era file appended.

AD-718d (`prompts/ad-718d-emotional-voice-modulation-v1.md`) ships at commit N+1.

## 11. Engineering principles compliance

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

Specific checkpoints (Builder confirms each in the build report):

- **Cloud-Ready Storage** — voice persists through the existing `CrewProfile.voice` round-trip; no new SQLite table, no new `aiosqlite` path.
- **Defense in Depth** — size cap → anchor/alias/tag reject → `yaml.safe_load` → depth guard → `VoiceProfile(...)` `__post_init__` (parse path); `SetVoiceProfileRequest` → `VoiceProfile(...)` `__post_init__` (approve path). Two independent server-side bounds checks; both run for any approved-from-proposal flow.
- **Three-tier exceptions** — LLM call: log-and-degrade; parser: propagate; bounds: propagate. No `except: pass`.
- **Async discipline** — `propose_voice_profile` is `async`; endpoint is `async def`; uses `await`. No `asyncio.ensure_future`.
- **No private-attr access** — UI reads `profileData.voiceProfile` (already public-shaped); no reach into store internals from the propose flow.
- **HXI Design Principles** — stroke SVG, no emoji, amber-active.
- **Type annotations** — all new public methods fully typed (`VoiceProfile`, `tuple[VoiceProfile, str]`, etc.).
- **Logging quality** — every log message has what/why/what-next context.
- **Episodic completeness** — approve-from-proposal writes an episode (the rationale IS the learning signal); hand-edit does not (Captain Q4 defer).

## 12. Acceptance criteria

- All ≥ 14 Python tests + ≥ 5 Vitest tests pass.
- Per-prompt gate green: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad718a_*.py -v -n 0`.
- Full gate green: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 16 --dist=loadfile` (fall back to `-n 8`).
- UI Vitest green: `cd ui && npx vitest run`.
- `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-718a-agent-authored-voice-v1.md` — accepted false positives (introduced by this prompt: `propose_voice_profile`, `VoiceProposalError`, `parse_voice_proposal`) noted in build report.
- Files touched (target list):
  - **New:** `src/probos/voice/__init__.py`, `src/probos/voice/proposal.py`, `tests/test_ad718a_voice_proposal_parser.py`, `tests/test_ad718a_propose_voice.py`, `ui/src/__tests__/ProfileInfoTab.proposeVoice.test.tsx`.
  - **Modified:** `src/probos/cognitive/cognitive_agent.py` (add `propose_voice_profile`), `src/probos/routers/agents.py` (add propose endpoint, extend PUT for episode write), `src/probos/api_models.py` (add `ProposeVoiceProfileRequest` / `ProposeVoiceProfileResponse`, extend `SetVoiceProfileRequest` with `proposal_rationale`), `ui/src/components/profile/ProfileInfoTab.tsx` (add Propose button + preview surface), `PROGRESS.md` (Wave 136 entry).
- `decisions-era-4-evolution.md` (or current DECISIONS-era file owning AD-718) appended with AD-718a entry.
- GH issue [#522](https://github.com/seangalliher/ProbOS/issues/522) closed.
- AD-718a-1 forward marker filed at gate-3 if "Request revisions" UX needs more work.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
