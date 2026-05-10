# AD-718c build report — Wave 137 commit N+1

**Prompt:** [prompts/ad-718c-per-agent-wake-phrase-v1.md](../ad-718c-per-agent-wake-phrase-v1.md)
**Builder:** GitHub Copilot (Builder mode)
**Date:** 2026-05-09
**Status:** SHIPPED

## Files changed

- `src/probos/crew_profile.py` — `wake_phrase` field on `VoiceProfile`; `__post_init__` strips/length/anchor reject; `from_dict` extended.
- `src/probos/voice/proposal.py` — `_ALLOWED_KEYS` and `_PROFILE_KEYS` extended with `wake_phrase`.
- `src/probos/cognitive/cognitive_agent.py` — `propose_voice_profile` system prompt updated with schema entry, guidance, and example.
- `src/probos/api_models.py` — `SetVoiceProfileRequest.wake_phrase: str = ""`.
- `src/probos/routers/agents.py` — PUT handler forwards `wake_phrase` to `VoiceProfile(...)`.
- `ui/src/audio/voice.ts` — `VoiceProfile` TS type extended with optional `wake_phrase`.
- `ui/src/audio/wakeWord.ts` — track `_activeAgentCallsign` so commit routes to per-agent surface; `_simulateWakeFire` accepts `agentCallsign`.
- `ui/src/components/IntentSurface.tsx` — collect non-empty per-agent wake phrases from store and pass via `agentTriggers`.
- `ui/src/components/profile/ProfileInfoTab.tsx` — wake-phrase `<input>` row + state plumbing + persist on blur.
- `ui/src/store/types.ts` — `Agent.voice_profile?.wake_phrase`; `AgentProfileData.voiceProfile.wake_phrase`.
- `tests/test_ad718c_wake_phrase.py` (NEW, 8 cases).
- `ui/src/__tests__/wakeWord.perAgent.test.ts` (NEW, 5 cases).
- `ui/src/__tests__/ProfileInfoTab.wakePhrase.test.tsx` (NEW, 3 cases).
- `decisions-era-4-evolution.md` — appended AD-718c entry.
- `progress-era-5-unification.md` — appended one-line entry.

## Sections implemented

- **E1**: dataclass field + `__post_init__` checks (length, strip, anchor reject) + `from_dict` round-trip.
- **E2**: parser allow-list extension (no new Pydantic model — single source of truth in dataclass).
- **E3**: LLM prompt update + worked example (no capability-gap regex matches).
- **E4**: `SetVoiceProfileRequest.wake_phrase` + PUT forward.
- **E5**: ProfileInfoTab wake-phrase row + propose-affordance roundtrip.
- **E6**: IntentSurface collector + Agent type extension + wakeWord.ts agent-callsign tracking.
- **E7**: Reuses AD-718a episode hook; `wake_phrase` rides on `to_dict()` automatically.
- **E8**: 8 Python + 8 Vitest cases.

## Post-build section audit

All eight `###` sections (E1–E8) have corresponding code.

## Tests

- Targeted Python: `pytest tests/test_ad718c_wake_phrase.py -v -n 0` — 8 passed.
- Targeted UI: `cd ui && npx vitest run src/__tests__/wakeWord.perAgent.test.ts src/__tests__/ProfileInfoTab.wakePhrase.test.tsx` — 8 passed.
- Full UI gate: 524 passed (delta +8 vs commit N).
- Full Python gate: `pytest tests/ -q -n 16 --dist=loadfile` — 13053 passed, 7 failed, 20 skipped. **All 7 failures verified pre-existing** by `git stash` + re-run on commit N (AD-705): same 7 fail before AD-718c lands. Failures are: 3 in `test_callsign_routing.py` (unrelated to voice profile), 1 in `test_ad719_chat_fanout.py`, 1 `test_runtime::test_capabilities_registered` (memory-noted heavy-fixture flake), 1 `test_experience::test_nl_unrecognized`, 1 `test_ad632h_parallel_dispatch::test_three_step_parallel_wave` (memory-noted parallel-only environmental).

## Hard-stop verifications

| # | Hard-stop | Status |
|---|---|---|
| 1 | AD-705 not yet merged | Verified: AD-705 is commit N (`a3a89ff`); AD-718c builds on top of it. |
| 2 | Phantom API | `wake_phrase` is the only new symbol; introduced by this prompt across both languages. |
| 3 | Architectural contract change | None. AD-718a parser shape preserved (just allow-list constants extended); BaseAgent / IntentMessage untouched; wake-word loop state machine extended only by `_activeAgentCallsign` private field. |
| 4 | Working tree integrity | Pre-flight clean; no >200-line deletions. |
| 5 | License creep | Zero new deps. |
| 6 | Emoji in diff | None. |
| 7 | Anchor / alias / tag tokens accepted | Rejected at the dataclass `__post_init__` boundary; tested. |
| 8 | exec/eval/compile/pickle on wake_phrase | None. |
| 9 | Default-True | `wake_phrase` defaults to empty string. |
| 10 | New approval flow | None. Reuses AD-718a's existing PUT + episode hook. |
| 11 | Test gate flake | All 8 new Python + 8 new Vitest cases pass under `-n 0` and `-n 16`. |

## Captain ruling alignment

- **"Hey Ezri" / @Ezri routing**: The IntentSurface useEffect collects per-agent wake_phrase values, the wake-word loop registers them as additional triggers, and `routeWakeTranscript` returns `surface='agent'` with the matched callsign. The IntentSurface onWake handler prepends `@callsign` to the cleaned text so the existing `/api/chat` `@`-mention path dispatches to the agent unchanged.
- **"Computer" still answers**: STATIC_WAKE_PHRASES is unchanged; system wake takes priority over agent wake (rule order in `routeWakeTranscript` D4). Both coexist.
- **TTS unchanged**: `voice.ts` only modified to extend the `VoiceProfile` TS type; the synthesis path is untouched.

## Dispatch corrections applied during draft

1. **§5 E2 said "Pydantic mirror in `VoiceProposal`"** — there is no `VoiceProposal` Pydantic model. AD-718a is parser-only. Corrected E2 to extend the parser's `_ALLOWED_KEYS` / `_PROFILE_KEYS` constants. Bounds for `wake_phrase` flow through `VoiceProfile.__post_init__` (single source of truth).
2. **§5 E3 said `propose_voice`** — actual method is `propose_voice_profile` (`cognitive_agent.py:2800`). Corrected throughout.

## Deviations

None beyond the dispatch corrections noted above (which the prompt itself called out and the Builder applied verbatim).

## Forward markers

None new. AD-718c-1 (global per-agent disable toggle) and AD-718c-2 (collision detection) are filed only if Captain post-merge feedback surfaces the need.
