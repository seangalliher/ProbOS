# WAVE 180 DISPATCH — live-use triage build

**Status:** drafted (Architect, 2026-05-19).
**Builder action:** continuous build — single dispatch, all four
prompts in strict order. Captain authorized the end-to-end loop;
Architect drafts → Builder runs immediately.
**Source of triage:** Captain's 2026-05-19 live-use report after
shipping Waves 175-179. Issues #681 + #682 + #683 + #684 filed +
roadmap rows added at HEAD commit `4beaba7e`.
**Prior-art research:** `prompts/RESEARCH-issues-2026-05-19.md`
(already shipped; do NOT re-research — every prompt references it).

---

## Strict build order

| # | Prompt | Issue | Why this slot |
|---|---|---|---|
| 1 | `prompts/bf-317-share-screen-discoverability.md` | [#681](https://github.com/seangalliher/ProbOS/issues/681) | UI-only; zero dependencies; cheapest fix; ships ahead so Captain sees an immediate quality-of-life delta. |
| 2 | `prompts/bf-318-mic-arbiter.md` | [#683](https://github.com/seangalliher/ProbOS/issues/683) | HARD prerequisite for AD-747. Bug fix in its own right. Ships standalone. |
| 3 | `prompts/ad-746-camera-screen-source-policy.md` | [#682](https://github.com/seangalliher/ProbOS/issues/682) | Backend-heavier; runs in parallel with BF-318 only at the architect's option — the prompt assumes strict serial dispatch for the Builder. |
| 4 | `prompts/ad-747-conversation-controller.md` | [#684](https://github.com/seangalliher/ProbOS/issues/684) | Consumes BF-318's `PRIORITY_CONVERSATION` lease. Cannot start until BF-318 lands. |

Each prompt is independently buildable, gated, and committable in its
own slot. **Do NOT batch commit.**

## Captain decisions (locked at triage; do not re-litigate)

1. **AD-746 v1 = Layer 1 fusion + Layer 2 per-agent binding.** Raw
   priority knob → forward marker AD-746-1.
2. **AD-747 ships AFTER BF-318.** No exceptions.
3. **AD-747 v1 silence timeout = 30 s** (matches ChatGPT advanced
   voice mode default).
4. **AD-747 barge-in defaults ON** (chatty-environment opt-out via
   `conversation_barge_in_enabled=False`; AD-747-1 forward marker
   for the smarter prosody-gated version).
5. **No new top-level ADs in this wave.** AD-747 is the highest;
   filed at triage commit. `Highest AD before/after Wave 180 = AD-747`.

## Cross-AD dependency graph (confirmed)

```
BF-317  (UI-only)  → standalone, no consumers
BF-318  (arbiter)  → AD-747 (consumer)
AD-746  (fusion + binding) → standalone in this wave;
                              future AD-746-3 will join with AD-747
AD-747  (controller) → consumes BF-318 arbiter API,
                       consumes AD-705a STT (Wave 179),
                       consumes AD-733c-7 / -5 / -7-5 (Waves 176/177),
                       consumes AD-744 share-screen path (Wave 178)
```

No circular dependencies. BF-317 has zero upstream consumers; can
ship in any slot but goes first per "cheapest visible delta" heuristic.

## v1 vs forward-marker matrix

| Capability | Wave 180 v1 | Forward marker |
|---|---|---|
| Share-screen button label + size + position | BF-317 | BF-317-1 (composer tool palette) |
| Composer tool-palette `[+]` for multi-affordance | — | BF-317-1 |
| Priority-queue mic arbiter | BF-318 | — |
| ConversationController state machine | AD-747 | — |
| VAD-gated STT auto-submit | AD-747 | — |
| Barge-in (VAD interrupts TTS) | AD-747 | AD-747-1 (prosody-gated) |
| 30 s silence timeout | AD-747 | AD-747-4 (goodbye classifier) |
| Press-to-talk button preserved | AD-747 | — |
| Cross-agent conversation handoff | — | AD-747-2 |
| Interruption sensitivity knob | — | AD-747-3 |
| Multi-Captain voice profile binding | — | AD-747-6 |
| Server-side streaming STT | — | AD-747-5 (pairs AD-705a-4) |
| `VisionAggregator` debounce fusion | AD-746 Layer 1 | — |
| Per-agent `bound_sources` | AD-746 Layer 2 | — |
| Raw source priority knob | — | AD-746-1 |
| Cross-modal salience scorer | — | AD-746-2 |
| Audio as third fused source | — | AD-746-3 (pairs AD-747-7) |
| Browser-side fusion preview | — | AD-746-4 |
| Retire legacy `source: str` anchor field | — | AD-746-5 |

## Per-prompt gate command (run after each AD lands)

```pwsh
# Backend gate (only relevant for AD-746 in this wave — BF-317, BF-318,
# AD-747 ship zero pytest delta).
pytest tests/test_<adNNN>_*.py -v -n 0
pytest tests/ -q -n 4 --dist=loadfile

# UI gate (all four prompts).
cd ui; npx vitest run; npm run build
```

`-n 4 --dist=loadfile` per BUILDER-EXECUTION-PLAN. `-n auto` is
forbidden until AD-682 lands.

UI gate `npm run build` is mandatory after BF-279 / AD-738b — vitest
alone is insufficient for shipping browser code.

## Per-commit hygiene

Per prompt, one commit on `main` with the standard message shape:

```
<area>: <one-line scope>
                            
<paragraph body — what, why, how>
                            
Closes #<issue>.
```

After all four lands, no separate "Wave 180 complete" commit — the
last prompt's commit IS the wave close.

## Known triage decisions that are NOT re-opened

- AD-746 fusion uses Pipecat `VisionAggregator` pattern; not LiveKit
  `MultiModalContext`. (Pipecat is simpler; LiveKit is for streaming
  topology, overkill here.)
- AD-747 absorbs LiveKit `VoicePipelineAgent` shape — not Pipecat
  `Pipeline`-of-FrameProcessors (LiveKit's API is more familiar
  to JS/TS authors).
- BF-318 priority levels (press_to_talk=100, conversation=75,
  wake_word=50) — derived from the rule that press-to-talk explicit
  user intent always wins; conversation explicit DM-open intent
  beats ambient wake-word listening.
- VAD device path is **not** in BF-318 scope. VAD uses dedicated
  `getUserMedia({audio:true})` (`voiceActivity.ts:213`) — separate
  acquisition surface from `SpeechRecognition`.
- AD-746 anchor metadata adds `sources: list[str]` and keeps legacy
  `source: str` as a one-wave compat alias. AD-746-5 retires the
  alias.

## Tracker state at dispatch (verified)

- HEAD: `4beaba7e` — `ADs: file BF-317 + AD-746 + BF-318 + AD-747 from
  2026-05-19 live-use triage`.
- Highest AD: **AD-747** (filed at triage). **No new top-level AD in
  this wave.**
- Highest BF: **BF-318** (filed at triage). **No new BF in this wave.**
- pytest baseline: `13449` per PROGRESS.md line 12 (4 known flakes).
- vitest baseline: `633` per PROGRESS.md line 12.
- Roadmap rows for BF-317 / AD-746 / AD-746-{1..4} / BF-318 /
  AD-747 / AD-747-{1..7} all present at `docs/development/roadmap.md`
  lines 563-570 (verified grep).

## Hard stops (Builder surfaces; Architect triages)

| Condition | Action |
|---|---|
| Working tree has tracked file changes the Builder didn't author | Stop. Surface to Architect. |
| Test fails under `-n 4`; re-run under `-n 0` also fails | Stop. Triage per architect standing rules. |
| Phantom API in a SEARCH/REPLACE block (target method/attribute doesn't exist at HEAD) | Stop. Surface to Architect with grep evidence. |
| AD-731 source-scan extension (`aggregator.py`) fails | Stop. Inline-bytes leak; surface immediately. |
| BF-318 arbiter API ships without `PRIORITY_CONVERSATION` export | Stop. AD-747 cannot start. |
| `npm run build` fails on any prompt's UI gate | Stop. Stale-bundle / AD-738b lesson — do NOT proceed to next prompt with broken bundle. |

## Closing notes

- BF-317 is a polish bug. AD-747 is a major UX delta. BF-318 +
  AD-746 are the load-bearing infrastructure in between.
- After Wave 180 ships, the next live-use triage cycle (forecast: 2-3
  weeks) likely surfaces AD-747-1 (barge-in false-positive rate) and
  AD-746-3 (mic context join) as the next prompts. Both are filed as
  forward markers; no action this wave.
- License posture across the whole wave: **0-line diff on
  `pyproject.toml`, `package.json`, `package-lock.json`, `LICENSE`,
  `THIRD_PARTY_LICENSES.md`.** Pattern-only absorption from LiveKit
  (Apache 2.0) + Pipecat (BSD-2-Clause).
