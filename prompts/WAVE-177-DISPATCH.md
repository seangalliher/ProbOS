# WAVE 177 — DISPATCH

**Drafted:** 2026-05-19
**Status:** GATE 1 (architect-only). Pass-1 complete.
**Captain authorization:** Wave 177 slate approved 2026-05-19.
**Posture:** **UI-completion slate.** Three forward markers from Wave 176
landed backend-only and deferred their UI surfaces. This wave ships the
three UI completions in order; zero production-code changes outside
`ui/src/`.

## Slate

| # | AD | Parent | Closes (forward marker) | Tests | Build order |
|---|----|--------|-------------------------|-------|-------------|
| 1 | AD-733c-5-4 | AD-733c-5 | HXI per-agent perception badges | +3 vitest | First (grounds the agent-ID concept in the UI; `CameraLiveIndicator` per-agent surface is the shared substrate for AD-733c-7-5 and AD-742c-6) |
| 2 | AD-733c-7-5 | AD-733c-7 | Browser-side Silero VAD integration | +5 vitest | Second (plugs SPEECH badge into the indicator alongside MODE badges) |
| 3 | AD-742c-6 | AD-742c | HXI camera multiplexer | +4 vitest | Third (extends `useCameraStream` to multi-stream + adds CAMERA BINDINGS to `PerceptionLivePanel`) |

Total: **+12 vitest. Zero new pytest.** Zero new pip / npm deps (Silero
VAD path uses the already-resident `onnxruntime-web` optional dep).
**0-line license diff** on all 5 license files. Zero diff on
`src/probos/`, `tests/`, `pyproject.toml`, `LICENSE`,
`THIRD_PARTY_LICENSES.md`, `package.json`, `package-lock.json`.

## Highest current AD

**Before Wave 177:** AD-743 (top-level, shipped Wave 176). Sub-ADs
include AD-733c-1..7, AD-742a..f. Forward markers AD-733c-5-1..5,
AD-733c-7-1..5, AD-742c-1..6.

**Confirmed via:**

```
Select-String -Path PROGRESS.md,DECISIONS.md,docs/development/roadmap.md \
  -Pattern "AD-7[0-9]{2}[a-z]*-?[0-9]*-?[0-9]*" -AllMatches \
  | Sort-Object -Unique | Select -Last 8
```

**Wave 177 assignments — ALL PRE-ASSIGNED:**

- AD-733c-5-4 (Wave 176 forward marker — DECISIONS.md:4658, roadmap.md:556).
- AD-733c-7-5 (Wave 176 forward marker — roadmap.md:563).
- AD-742c-6 (Wave 176 forward marker — roadmap.md:571).

**After Wave 177:** Highest AD **unchanged** (these are sub-ADs of
existing parents). Forward markers consumed: 3. Next top-level slot
remains AD-744.

## Drafted prompts

| # | Prompt | Parent AD |
|---|--------|-----------|
| 1 | `prompts/ad-733c-5-4-perception-badges.md` | AD-733c-5 |
| 2 | `prompts/ad-733c-7-5-vad-browser.md` | AD-733c-7 |
| 3 | `prompts/ad-742c-6-camera-multiplexer.md` | AD-742c |

## Build order (strict)

1 → 2 → 3. Rationale:

1. **AD-733c-5-4 first.** Establishes the per-agent badge substrate in
   `CameraLiveIndicator.tsx`. AD-733c-7-5 will add a SPEECH badge in
   the same region; AD-742c-6 will add a CAMS:N label in the same
   region. Building #1 first lets #2 and #3 integrate cleanly without
   redrawing the indicator layout three times.
2. **AD-733c-7-5 second.** The SPEECH badge sits alongside the
   per-agent MODE badges from #1. The Zustand store extension for
   `lastSpeechAt` is small.
3. **AD-742c-6 third.** The `useCameraStream` multi-stream refactor is
   the highest-risk file in the wave (load-bearing module-singleton
   state). Building last means the previous two prompts have already
   re-validated the indicator surface in production-build mode (`npm
   run build`) — any regression in the indicator surfaces before this
   one lands.

## Pre-flight gate

Before any Builder dispatch:

```pwsh
git status --porcelain
# expect: clean working tree (only the Wave 177 prompts + tracker
# updates dirty before commit; clean after each prompt's commit)

git log --oneline -1
# expect: HEAD = "wave-plan: queue Wave 177 (...)" commit

.\.venv\Scripts\pytest.exe tests/ -q -n 4 --dist=loadfile 2>&1 | Select -Last 3
# baseline: 14224 (PROGRESS line 4 post-Wave-176) - no pytest delta
# expected this wave; the gate is to confirm the baseline is green.

cd ui; npx vitest run 2>&1 | Select -Last 3
# baseline: existing vitest count (read PROGRESS line 4 vitest field
# at HEAD); after wave: baseline + 12.

cd ui; npm run build
# must exit 0 BEFORE wave starts (BF-279 stale-bundle baseline).
```

Per-prompt pre-flight: each prompt has its own grep-anchor list (4-7
anchors). Builder MUST verify each anchor exists at HEAD before
locking edits. **Hard-stop on any missing anchor.**

## Hard-stop conditions

Builder must stop and surface (not work around) on any of:

1. Pre-flight grep finds a missing anchor on any prompt.
2. Pre-flight gate fails — baseline pytest OR vitest OR `npm run build` not green.
3. New pip dep introduced (license diff non-zero on `pyproject.toml` or `THIRD_PARTY_LICENSES.md`).
4. New npm dep introduced (license diff non-zero on `package.json` /
   `package-lock.json`). `onnxruntime-web` must remain in
   `optionalDependencies` — promoting to `dependencies` is forbidden
   (first-paint regression for Captains who never enable VAD).
5. AD-731 invariant violated — image bytes leak into any RPC message
   (especially watch AD-742c-6 which touches the camera form-data
   path).
6. AD-733c-7 privacy invariant violated — audio bytes leave the
   browser. The `/voice-activity` POST body must contain ONLY
   `{agent?, source}` metadata.
7. `pytest tests/test_ad733c5_per_agent_engagement.py
   tests/test_ad733c7_vad_engagement.py
   tests/test_ad742c_per_agent_camera.py -v -n 0` fails after any
   prompt lands (proves backend contracts unchanged).
8. `cd ui && npm run build` fails after any prompt — stale-bundle
   regression risk (BF-279).
9. >5 quarantine markers across the wave.
10. Working-tree shows deletions >50 lines on any TSX file the wave
    didn't intend to modify (BF-274 wipe pattern; canonical lesson
    from 2026-05-08).
11. Builder modifies any file under `src/probos/`, `tests/`, or
    `pyproject.toml` (this is a UI-only wave; backend is frozen).
12. Static `import` of `onnxruntime-web` introduced anywhere (must
    stay dynamic-via-string-variable per `wakeWord.ts:268-289`
    precedent).

## Conservative posture

- **Backend frozen.** All three backend endpoints
  (`GET /api/perception/mode`, `POST /api/perception/voice-activity`,
  `GET /api/perception/cameras`, `POST /api/perception/cameras/binding`,
  `POST /api/perception/camera/frame` with `agent_ids` field) already
  ship from Wave 176. Builder consumes the existing surfaces verbatim.
- **Default-off transitional flags preserved.**
  `PerceptionConfig.vad_engagement_enabled=False` (AD-733c-7) keeps
  the SPEECH badge hidden until Captain opts in.
- **Single-agent / unconfigured deployments unchanged.** Each prompt
  has an explicit back-compat acceptance criterion: the UI renders
  bit-for-bit identical to HEAD when `perAgent` is empty (AD-733c-5-4),
  when `vad_engagement_enabled=false` (AD-733c-7-5), and when bindings
  are empty (AD-742c-6).
- **UI gate per BF-279 / AD-738b.** `cd ui && npm run build` AND
  `npx vitest run` after EACH prompt; not just at the end of the wave.
- **BF-274 single-replace discipline.** Every TSX edit uses single
  `replace_string_in_file` per adjacent block; no
  `multi_replace_string_in_file` on adjacent JSX.
- **BF-287 real-fixture discipline.** Every vitest mocks at the
  network boundary (fetch) or browser boundary (getUserMedia /
  enumerateDevices). No MagicMock at the Zustand-store layer.

## Cross-AD design decisions (made at draft time)

1. **`CameraLiveIndicator` grows as ONE component.** All three new
   pieces of state (per-agent MODE badges, SPEECH badge, CAMS:N
   label) render inside the single existing indicator. Rationale:
   keeps the zIndex/positioning logic in one place; preserves the
   4-corner snap + preview behavior from BF-301/BF-302/BF-305;
   matches HXI Principle #5 (progressive disclosure — components
   appear conditionally rather than as sibling indicators that
   visually compete).
2. **Zustand slice naming: SEPARATE slices, not merged.**
   - `usePerceptionModeStore` — extended with `perAgent` (read from
     `/api/perception/mode`). Same endpoint, same refresh cadence as
     existing mode state.
   - `useCameraMultiplexerStore` — NEW sibling slice (read from
     `/api/perception/cameras` + `enumerateDevices`). Separate
     endpoint, separate lifecycle (configuration, not lifecycle).
   - `useCameraStore` UNCHANGED — continues to track the single-stream
     lifecycle (active / framesSent / corner / preview position).
   - Rationale: SRP wins over slice reuse when endpoints differ.
3. **Mic-tap audio context: NEW dedicated stream.** No shared
   `useMicStream()` exists in the codebase. `wakeWord.ts` uses the
   browser's `SpeechRecognition` API (transcript-level, not PCM);
   `useCameraStream` is explicit `audio: false`. AD-733c-7-5 opens a
   new, dedicated `getUserMedia({audio: true})` stream. NOT a DRY
   violation — the existing audio surfaces operate at different
   abstraction layers. Forward marker AD-733c-7-5-1 if a future
   feature needs both raw audio AND transcripts from a shared mic.
4. **Backend frozen.** Builder MUST NOT modify
   `src/probos/routers/perception.py`. All four endpoints landed in
   Wave 176 with the exact request/response shapes the UI consumes:
   - `GET /api/perception/mode` → `{mode, since, last_dm_activity, presets, transitions, per_agent: {agent_id: mode_name}}`
   - `POST /api/perception/voice-activity` → `{ok, mode, transitioned, reason, agent_id}` from body `{agent?, source}`
   - `GET /api/perception/cameras` → `{bindings: {agent_id: device_id}}`
   - `POST /api/perception/cameras/binding` → `{ok, agent_id, device_id}` from body `{agent_id, device_id}`
   - `POST /api/perception/camera/frame` accepts optional `agent_ids` comma-separated form field
5. **`useCameraStream` extension over rewrite.** The hook is a
   load-bearing module-singleton with multiple BF-tracked invariants
   (BF-301/302/305). AD-742c-6 EXTENDS it: adds an optional `deviceId`
   kwarg to `startCameraStream`, adds a `Map<deviceId, MediaStream>`
   alongside the existing `_stream`, threads `agent_ids` into the
   form-data when bindings are present. The zero-arg call preserves
   legacy single-stream semantics bit-for-bit.

## NOT in this wave (forward markers post-build)

- **AD-733c-5-4-1** — Per-agent manual override buttons in the per-agent table.
- **AD-733c-5-4-2** — WebSocket push for per-agent mode changes (currently 2s polling).
- **AD-733c-5-4-3** — Callsign rendering in per-agent badges (requires `CallsignRegistry` snapshot in HXI).
- **AD-733c-7-5-1** — Shared mic-tap hook unifying VAD raw audio + wake-word transcription.
- **AD-742c-6-1** — Fade-on-unbind animation in CAMERA BINDINGS table.
- **AD-742c-6-2** — Agentic bind path ("agent: bind your camera to me") — requires new intent + tool permission.

All to be filed in `docs/development/roadmap.md` (no GH issues per the
2026-05-08 standing rule from `/memories/repo/probos-notes.md`).

## GATE 1 verdict

**✅ Approved (Conditional on Builder pre-flight).**
**All three prompts ready for Builder; build order strict 1→2→3.**

### Required (must verify at Builder pre-flight)

1. AD-733c-5-4 pre-flight grep anchors (6 listed in prompt).
2. AD-733c-7-5 pre-flight grep anchors (7 listed in prompt) — most
   critically `wakeWord.ts:268-289` lazy-import pattern (Builder MUST
   mirror it; static `import` is forbidden).
3. AD-742c-6 pre-flight grep anchors (7 listed in prompt) — most
   critically `useCameraStream.ts:18-27` module-singleton state
   (Builder EXTENDS not replaces).

### Recommended

1. After AD-733c-5-4: snapshot the indicator visual diff (manual or
   Storybook if available). The indicator is the most-modified TSX
   file in this wave — confirm the per-agent badges don't visually
   clobber the existing MODE/CAMERA-LIVE/MOVE/PREVIEW/REVOKE row.
2. After AD-733c-7-5: live smoke test with Captain mic on, set
   `vad_engagement_enabled=true`, restart, observe the SPEECH badge
   flash on real speech. Stale-bundle regression (BF-279) hits hardest
   when the operator never actually exercises the new code path.
3. After AD-742c-6: live smoke test with two cameras plugged in,
   bind agent e1 to camera A, agent e2 to camera B, observe both
   streams in the journal (`/api/perception/recent`) carrying
   distinct `bound_agent_ids`.
4. Each prompt committed as a standalone commit titled
   `AD-733c-5-4: HXI per-agent perception badges` /
   `AD-733c-7-5: HXI Silero VAD integration` /
   `AD-742c-6: HXI camera multiplexer`.

### Verified Improvements over previous waves

1. **Cross-AD design choices documented upfront** in dispatch —
   indicator-is-one-component, separate Zustand slices, dedicated
   mic stream.
2. **Backend frozen** — explicit hard-stop if Builder touches
   `src/probos/` or `tests/`. Removes a class of accidents.
3. **License posture explicit** — 0-line diff on all 5 license files;
   `onnxruntime-web` stays in `optionalDependencies`.
4. **HXI Principles #3 / #4 / #5 / #9 / #11 enforced per prompt** —
   each prompt has its own audit section mapping changes to specific
   principles.
5. **BF-274 single-replace discipline** applied to TSX edits — the
   `useCameraStream.ts` refactor in AD-742c-6 explicitly forbids
   `multi_replace_string_in_file`.
6. **BF-287 real-fixture discipline** in every vitest plan —
   fetch / enumerateDevices / getUserMedia mocked at the boundary;
   Zustand stores remain real.

---

## Builder dispatch checklist (for after GATE 2)

- [ ] Pre-flight gate green (`pytest`, `vitest`, `npm run build`).
- [ ] AD-733c-5-4 built, tested, committed.
- [ ] `cd ui && npx vitest run` green; `cd ui && npm run build` green.
- [ ] AD-733c-7-5 built, tested, committed.
- [ ] `cd ui && npx vitest run` green; `cd ui && npm run build` green.
- [ ] AD-742c-6 built, tested, committed.
- [ ] `cd ui && npx vitest run` green; `cd ui && npm run build` green.
- [ ] Full wave gate green at `pytest -n 4 --dist=loadfile` (no pytest
      delta expected; this confirms no accidental backend touch).
- [ ] Vitest delta = +12 (baseline + 12).
- [ ] PROGRESS.md + roadmap.md + DECISIONS.md updated.
- [ ] Wave 177 prompts archived (mv to `prompts/archive/`).
- [ ] `prompts/wave-plan.yaml` status flipped to `shipped`.
