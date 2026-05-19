# WAVE 176 — DISPATCH

**Drafted:** 2026-05-19
**Status:** GATE 1 (architect-only). Pass-1 complete.
**Captain authorization:** Wave 176 slate approved 2026-05-19.
**Posture:** **Perception-completion + UX-polish.** Four ADs:
one isolated UX (AD-743 / #662); three perception-completion ADs
(AD-733c-5 / #676, AD-733c-7 / #678, AD-742c / #671). All
additive, all opt-in / default-off, default behavior bit-for-bit
preserved. Build order is strict because AD-733c-5 ships
`CrewProfile.perception` which AD-742c depends on; AD-733c-7
plugs into the per-agent registry from AD-733c-5.

## Slate

| # | AD | Issue | Closes | Tests | Build order |
|---|----|-------|--------|-------|-------------|
| 1 | AD-743 | #662 | Adaptive conversational pacing in 1:1 DMs (multi-message, follow-ups) | +12 pytest | First (independent UX) |
| 2 | AD-733c-5 | #676 | Per-agent perception engagement | +11 pytest, +3 vitest | Second (introduces `CrewProfile.perception`) |
| 3 | AD-733c-7 | #678 | Silero VAD secondary engagement trigger | +8 pytest, +5 vitest | Third (depends on AD-733c-5 registry) |
| 4 | AD-742c | #671 | Per-agent camera selection | +10 pytest, +4 vitest | Fourth (depends on `CrewProfile.perception.camera_device_id`) |

Total: **+41 pytest, +12 vitest.** Zero new pip deps. Zero new npm
deps (Silero VAD pulls existing `onnxruntime-web`; model bytes
operator-pulled, gitignored). 0-line diff on `pyproject.toml`,
`package.json`, `package-lock.json`, `LICENSE`; **+1 line** on
`THIRD_PARTY_LICENSES.md` (Silero VAD attribution) and **+1 line**
on `.gitignore` (Silero model directory).

## Highest current AD

**Before Wave 176:** AD-742 (top-level), with shipped sub-ADs
through AD-742f and AD-733c-6 (Wave 175).

**Confirmed via:**

```
Select-String -Path PROGRESS.md,DECISIONS.md,docs/development/roadmap.md \
  -Pattern "AD-7[0-9]{2}[a-z]*-?[0-9]*" -AllMatches \
  | Sort-Object -Unique | Select-Object -Last 5
# → AD-742, AD-742a-f, AD-733c-1..6, AD-740
```

**Wave 176 assignments:**
- AD-743 (new top-level — #662 has no pre-assigned number).
- AD-733c-5 (pre-assigned by Wave 172 GATE 1 forward marker).
- AD-733c-7 (pre-assigned by Wave 172 GATE 1 forward marker).
- AD-742c (pre-assigned by Wave 171 forward marker).

**After Wave 176:** AD-743 top-level; the three perception sub-ADs
plug under existing series. Next top-level AD will be AD-744.

## Drafted prompts

| # | Prompt | Closes |
|---|--------|--------|
| 1 | `prompts/ad-743-adaptive-dm-pacing.md` | #662 |
| 2 | `prompts/ad-733c-5-per-agent-engagement.md` | #676 |
| 3 | `prompts/ad-733c-7-silero-vad-engagement.md` | #678 |
| 4 | `prompts/ad-742c-per-agent-camera.md` | #671 |

## Build order (strict)

1 → 2 → 3 → 4. Rationale:

1. **AD-743 first (isolated UX).** No dependency on perception
   wave. Lands as a self-contained scheduler service + new bracket
   marker. Builder ships, validates regression suite, commits.
2. **AD-733c-5 second (foundation).** Introduces
   `CrewProfile.perception` block (with `engagement_enabled`,
   `initial_mode`, `camera_device_id` reserved). Promotes
   `PerceptionModeController` to per-agent registry. Keeps a
   back-compat singleton pointer.
3. **AD-733c-7 third (trigger plug-in).** Adds
   `note_voice_activity()` method on the per-agent controller +
   browser-side VAD module + `POST /api/perception/voice-activity`
   endpoint. Routes through the AD-733c-5 registry.
4. **AD-742c fourth (camera multiplexer).** Wires
   `camera_device_id` from AD-733c-5's block into the actual
   capture multiplexer + selective fan-out via new
   `bound_agent_ids` IntentMessage param. **HARD pre-flight:
   verifies `CrewProfile.perception` exists at HEAD before
   touching anything.**

## Pre-flight gate

Before any Builder dispatch:

```pwsh
git status --porcelain
# expect: clean working tree (only architect prompts + tracker
# updates dirty BEFORE wave starts; clean AFTER each commit)

git log --oneline -1
# expect: HEAD includes Wave 175 close + vision_fast default-on
# commit

.\.venv\Scripts\pytest.exe tests/ -q -n 4 --dist=loadfile 2>&1 | Select -Last 3
# baseline: 13449 (PROGRESS line 4) + Wave 175 +31 = 13480 ish
# (subject to Wave 175 final commit count)
```

Per-prompt pre-flight:

- AD-743: verify `cognitive/dm_sanity_gate.py:46` `_SELF_CHECK_RE`
  precedent + `cognitive/dm/reply_pipeline.py:82` `_steps` tuple
  shape + `cognitive_agent.py:3090` `mark_reply_emitted`.
- AD-733c-5: verify `crew_profile.py:306` PeerPerceptionProfile +
  `crew_profile.py:372` field definition + `mode_controller.py:101`
  __init__ signature + `finalize.py:4122` singleton construction
  site.
- AD-733c-7: verify `mode_controller.py` WAKE_WORD_COOLDOWN_S
  precedent + `wakeWord.ts` lazy-loads `onnxruntime-web`.
- AD-742c: **verify `CrewProfile.perception` block exists at HEAD**
  (depends on AD-733c-5 landing). If absent, hard-stop.

## Hard-stop conditions

Builder must stop and surface (not work around) on any of:

1. Pre-flight grep finds a missing anchor.
2. Pre-flight gate fails — baseline tests not green.
3. New pip dep introduced (license diff non-zero on `pyproject.toml`
   or `THIRD_PARTY_LICENSES.md` beyond the +1 Silero entry).
4. New npm dep introduced (license diff non-zero on `package.json` /
   `package-lock.json` — `onnxruntime-web` must already be resident).
5. AD-731 invariant violated — image bytes leak into RPC messages
   (especially watch for AD-742c since it touches the upload
   endpoint).
6. `pytest tests/test_ad733a_vision_consumer.py
   tests/test_ad733c2_mode_controller.py
   tests/test_ad724_dm_sanity_gate.py -v -n 0` fails after any of
   the four ADs land — proves default behavior diverged.
7. `cd ui && npm run build` fails.
8. >5 quarantine markers across the wave.
9. Working-tree shows deletions >200 lines on any file the wave
   didn't intend to modify (BF-274 wipe pattern; canonical lesson
   from 2026-05-08).
10. AD-742c starts before AD-733c-5 lands (build-order violation).

## Conservative posture

- **All default-off transitional flags (convention #14).** Every
  new feature defaults to current behavior:
  - `AvatarsConfig.pacing_enabled = False`.
  - `PerceptionProfile.engagement_enabled = True` (legacy profiles
    without the block default to True — identical to current
    singleton).
  - `PerceptionConfig.vad_engagement_enabled = False`.
  - `PerceptionProfile.camera_device_id = ""` (empty → default
    camera, current v1 behavior).
- **No live perception path touched mid-flight.** AD-733c-5
  promotes singleton → registry at finalize (boot-time). AD-742c
  multiplexer reacts to bindings at POST time only.
- **Single source of truth for tests** — every new test uses real
  fixtures over MagicMock (BF-287); every new test uses single
  `replace_string_in_file` per adjacent edit (BF-274 lesson).
- **HXI gate**: AD-733c-5, AD-733c-7, AD-742c each touch UI.
  Builder MUST run `cd ui && npm run build` AND `npx vitest run`
  after each (BF-279 stale-bundle).

## Cross-AD design decisions (made at draft time)

1. **#678 VAD ↔ #676 per-agent engagement:** VAD is a NEW TRIGGER
   feeding the same per-agent `PerceptionModeController`, NOT a
   strategy plugin. Adds `note_voice_activity()` method next to
   the existing `note_dm_activity` / `note_high_novelty_event` /
   `note_wake_word`. Single state owner; orthogonal triggers.
2. **#676 per-agent engagement ↔ #671 per-agent camera:** Share
   the new `CrewProfile.perception` block. AD-733c-5 ships the
   block (with `camera_device_id` reserved). AD-742c populates
   the binding. Single agent-ID schema across both ADs.
3. **#662 pacing ↔ DM dispatch:** Pacing PLUGS INTO
   `DmReplyPipeline` as a new `step_5_follow_up_parse` and a
   sibling runtime service (`ConversationPacingScheduler`).
   Does NOT replace the existing reply path. Synthesized
   follow-up rides the existing `IntentMessage` shape.
4. **AD-742d STRATEGY_REGISTRY ↔ AD-733c-5 engagement:** Separate
   abstractions. AD-742d is supervisor-frame admission;
   engagement is runtime mode state. NOT reused; engagement gets
   its own `PerceptionEngagementRegistry` (thin dict-wrapper).

## NOT in this wave (forward markers post-build)

- **AD-743-1** — Captain-silence "Still there?" trigger.
- **AD-743-2** — Same-tick multi-message split.
- **AD-743-3** — Correction-driven budget reset.
- **AD-733c-5-1** — HXI editor for `PerceptionProfile`.
- **AD-733c-5-2** — Hot-reload of `engagement_enabled` toggle.
- **AD-733c-5-3** — Federation cross-host engagement sync.
- **AD-733c-7-1** — Browser pause `getUserMedia` in DORMANT.
- **AD-733c-7-2** — Multi-mic disambiguation.
- **AD-733c-7-3** — Speaker diarization.
- **AD-733c-7-4** — VAD-driven wake-word mute.
- **AD-742c-1** — Screen capture binding per agent.
- **AD-742c-2** — Federation cross-host camera sync.
- **AD-742c-3** — IP camera RTSP ingestion.
- **AD-742c-4** — Audio device per-agent binding.
- **AD-742c-5** — Per-agent camera permissions.

All to be filed as GH issues at wave close (per the standing
2026-05-08 rule from `/memories/repo/probos-notes.md`).

## GATE 1 verdict

**✅ Approved (Conditional on Builder pre-flight).**
**All four prompts ready for Builder; build order strict 1→2→3→4.**

### Required (must verify at Builder pre-flight)

1. AD-743 pre-flight grep anchors (6 listed in prompt).
2. AD-733c-5 pre-flight grep anchors (12 listed in prompt).
3. AD-733c-7 pre-flight grep anchors (8 listed in prompt).
4. AD-742c pre-flight grep anchors (7 listed in prompt) — most
   critically, `CrewProfile.perception` block must exist at HEAD
   (AD-733c-5 must have landed).

### Recommended

1. After AD-733c-5: re-run `pytest tests/test_ad733c2_mode_controller.py
   tests/test_ad733c3_engage_endpoint.py tests/test_ad733c6_engaged_budget_enforcement.py
   -v -n 0` to verify per-agent promotion preserved AD-733c-2/3/6
   contracts.
2. After AD-742c: re-run `pytest tests/test_ad733_frame_endpoint.py
   tests/test_ad733a_vision_consumer.py -v -n 0` to verify
   selective fan-out preserved legacy semantics.
3. Each prompt committed as a standalone commit titled
   `AD-743: adaptive DM pacing (closes #662)` /
   `AD-733c-5: per-agent engagement (closes #676)` /
   `AD-733c-7: Silero VAD engagement (closes #678)` /
   `AD-742c: per-agent camera (closes #671)`.

### Verified Improvements over previous waves

1. **Cross-AD design choices documented upfront** in dispatch.
2. **Build-order hard dependency surfaced** — AD-742c MUST
   land after AD-733c-5; pre-flight enforces this.
3. **License posture explicit** — +1 line each on
   THIRD_PARTY_LICENSES.md and .gitignore (Silero VAD) is the
   ONLY allowed license diff for this wave.
4. **BF-274 single-edit discipline** applied in every prompt.
5. **BF-287 real-fixture discipline** in every test plan.
6. **HXI Principle #3** enforced in three UI-touching prompts.

---

## Builder dispatch checklist (for after GATE 2)

- [ ] Pre-flight gate green.
- [ ] AD-743 built, tested, committed.
- [ ] AD-724 / AD-728d regression suite re-run after AD-743 → green.
- [ ] AD-733c-5 built, tested, committed.
- [ ] AD-733c-2 / AD-733c-3 / AD-733c-6 regression suite re-run → green.
- [ ] AD-733c-7 built, tested, committed.
- [ ] AD-733c-5 regression suite re-run after AD-733c-7 → green.
- [ ] AD-742c built, tested, committed (PRE-FLIGHT: verify
      `CrewProfile.perception` exists).
- [ ] AD-733 / AD-733a frame upload + fan-out suites re-run → green.
- [ ] Full wave gate green at `-n 4 --dist=loadfile`.
- [ ] `cd ui && npm run build` green after each UI-touching AD.
- [ ] Forward marker GH issues filed (count: 13).
- [ ] PROGRESS.md + roadmap.md updated.
- [ ] Wave 176 prompts archived (mv to `prompts/archive/`).
