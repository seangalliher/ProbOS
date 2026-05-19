# WAVE 172 DISPATCH — AD-733c Adaptive Perception Cadence

**Status:** Drafted 2026-05-18. GATE 1 pending. Do NOT dispatch Builder until GATE 1 verdict.

**Closes:** #675 (AD-733c umbrella).

**Highest shipped AD prior to this wave:** AD-741 (Wave 170). AD-742a..f are forward-marker issues (#669-#674) that remain open. Sub-AD numbering uses the pre-existing AD-733c umbrella line.

## Slate

| Prompt | AD | Scope | Issues | Est. tests |
|---|---|---|---|---|
| `ad-733c-1-dm-force-describe.md` | AD-733c-1 | DM-receive force describe of latest frame before WM render | closes part of #675 | +6 pytest |
| `ad-733c-2-mode-controller.md` | AD-733c-2 | `PerceptionModeController` with DORMANT/AMBIENT/ENGAGED presets driving BF-308 setters | closes part of #675 | +12 pytest, +4 vitest |
| `ad-733c-3-wake-engage.md` | AD-733c-3 | `POST /api/perception/engage` + `wakeWord.ts` agent-route -> engage call + avatar surface | closes part of #675 | +4 pytest, +3 vitest |
| `ad-733c-4-idle-drop-back.md` | AD-733c-4 | Background timer engaged→ambient→dormant on idle | closes #675 | +5 pytest |

Forward markers (filed as new issues at GATE 1 close, BEFORE Builder dispatch):
- **AD-733c-5** — per-agent engagement (Ezri engaged, Atlas ambient); v1 is per-runtime.
- **AD-733c-6** — per-session/daily LLM call budget guard for engaged mode.
- **AD-733c-7** — Silero VAD as secondary "Captain is speaking" engagement trigger.

## Research Phase

### Pattern absorption table

| Project | License | Pattern studied | Adopt / Pass | Why |
|---|---|---|---|---|
| OpenWakeWord (`dscripka/openWakeWord`) | Apache 2.0 | Custom keyword detector with ONNX runtime; emits `(detection_event, confidence)` per audio frame | **Already absorbed** in AD-705 (`wakeWord.ts`). No new code. | The existing `routeWakeTranscript()` API in `ui/src/audio/wakeWord.router.ts:78` already produces `{surface: 'system'\|'agent', agentCallsign?, cleanedText}` — exactly the shape AD-733c-3 needs. We hook the existing `onWake` callback in `IntentSurface.tsx:185`; no new detector. |
| Picovoice Porcupine | Commercial (paid) | Wake-event payload shape: `(keyword_index, confidence, timestamp)` | **Pass.** | Paid license — violates Captain's OSS license rule. Reference shape only: our `/api/perception/engage` payload uses `{agent, phrase, source}` instead. |
| LiveKit Agents (`livekit/agents`) | Apache 2.0 | Multi-modal state machine: `idle / listening / thinking / speaking`. Transitions on `user_turn_start` / `agent_turn_start` / VAD events. State held centrally; consumers subscribe. | **Architecture absorbed.** No code copy. | Closest mature pattern. ProbOS port: `PerceptionModeController` holds `current_mode`, exposes `transition_to()`, listens to DM-activity + wake-word + idle-timer signals. Their "race-condition" lesson — user interrupts agent mid-speak — informs the cooldown (5s) on wake-triggered transitions. |
| Silero VAD (`snakers4/silero-vad`) | MIT | Frame-level voice-activity detection — emits `is_speech: bool` per ~30ms PCM chunk. | **Out of scope for v1. Filed as AD-733c-7 forward marker.** | Adds a 1-1.5MB ONNX model + audio plumbing. v1 ships wake-word + DM-activity triggers; VAD is the obvious "Captain spoke but did not say a wake-word" upgrade. |
| HumeEVI | Commercial / closed | Affect-state-driven conversational mode shifts (frustration → escalate; satisfaction → recede). | **Pass.** | Closed source. The Counselor wellness review path (already shipped) is our analog; not a perception-mode concern. |

**License posture:** zero new pip deps, zero new npm deps. All four sub-ADs reuse existing infrastructure (BF-308 setters, AD-733a VisionConsumer, AD-705 wake-word). Expected license-diff: 0 lines.

### Decisions on the 11 research questions

1. **Wake-word integration today.** `ui/src/audio/wakeWord.ts:157` exports `startWakeWordLoop(onWake, opts)`. The `onWake` callback receives a `WakeRoute` (`{surface, agentCallsign?, cleanedText}`). When `surface==='agent'`, today's behavior is: prepend `@callsign` and submit to the standard chat input (see `IntentSurface.tsx:185-203`). **AD-733c-3 piggybacks the same onWake hook:** when `surface==='agent'`, fire a fire-and-forget `POST /api/perception/engage` BEFORE the chat submit. Browser-side wake events are sufficient; no backend wake listener.

2. **Reply pipeline force-describe seam.** Per Wave 171 memory + grep: `routers/agents.py:1932-1942` is where `render_for_prompt()` injects the WM scene block into `message_text`, gated on `perception.enabled`. **The force-describe hook attaches here, BEFORE `render_for_prompt()` is called.** Not in `cognitive/dm/reply_pipeline.py` — that pipeline runs post-LLM (`step_5_episodic_store`, etc.). The pre-LLM seam is in `routers/agents.py:agent_chat`.

3. **Latest frame SHA cache.** Recommended: **on `VisionConsumer` as a per-session attribute** `_latest_frame_by_session: dict[str, tuple[str, float]]` updated in `_handle()` BEFORE the supervisor gate (so dropped/throttled frames still update the cache). Rationale: keeps perception state inside the perception subsystem (Demeter); `_handle` already sees every intake; survives supervisor drops. For v1 single-Captain we ALSO expose `latest_frame_sha()` (no session arg) returning the globally most-recent SHA — AgentChatRequest has no `session_id` field, so DM-force-describe uses the global view.

4. **Mode controller lifecycle.** Construct in `startup/finalize.py` immediately after the `VisionConsumer` wire-up block (line 3950+), inside the same `if perception.enabled` guard. Default mode: `AMBIENT` if `perception.enabled` else `DORMANT`. Background timer task started by `controller.start()`. Teardown in `startup/shutdown.py` mirroring the `recording_reaper` pattern (line 203): `if hasattr(runtime, 'perception_mode_controller') and runtime.perception_mode_controller: await runtime.perception_mode_controller.stop()`.

5. **Mode transition triggers.**
   - DM activity: **hook in `routers/agents.py:agent_chat`** at the same point as the force-describe (just BEFORE WM injection). Single call: `controller.note_dm_activity()`. Clean, no event bus.
   - Wake word: `POST /api/perception/engage` endpoint receives the event from the UI (per Q1).
   - Idle drop-back: **single `asyncio.create_task` background task** owned by the controller, polling every 30s. Pattern matches `recording_reaper`. Holds task reference, catches `CancelledError` + cleanup + re-raise (Engineering Principles, BF-211 lesson).

6. **Per-agent vs per-runtime.** **Per-runtime for v1.** Single global `controller.current_mode`. Per-agent split is forward marker **AD-733c-5** (depends on AD-742c per-agent camera #671). The current `VisionConsumer` is runtime-singleton so per-agent mode would require also per-agent supervisors — out of scope.

7. **Working memory across mode transitions.** **Preserve WM contents across transitions** — no clearing. Going engaged→ambient must not erase the recent visual context; the agent's last few observations remain valid recall material. Document this in the controller docstring.

8. **Avatar response coupling.** Tier-2 best-effort. When `transition_to(ENGAGED)` fires from a wake-word source, emit a `PERCEPTION_ENGAGED` event with `agent_callsign` payload. The HXI already has avatar-surfacing logic in `IntentSurface` (the `setActive(true)` call at line 196). For v1 the existing `@callsign + form.requestSubmit()` path already surfaces the avatar via the standard DM flow. **No new avatar-surface API in this wave.** If the operator hits "Hello Ezri" without typing anything after, AD-733c-3 still flips the mode; the avatar follows on the first DM. Captain's "she pops up with her avatar" framing is satisfied by the existing chat submit path.

9. **Privacy semantics in dormant.** **DORMANT pushes `min_interval_seconds=60.0` to the supervisor** but does NOT stop browser-side capture. Rationale: stopping `getUserMedia` requires UI choreography that mirrors `stopCameraStream()` — would need a new BroadcastChannel signal from backend to browser. v1 keeps the browser stream running at its configured rate; the supervisor rejects 99% of frames at DORMANT cadence. Captain's privacy concern is satisfied because (a) the operator can still hit STOP in the Perception panel to fully cut the stream, (b) no LLM calls fire when supervisor drops the frame, (c) frames still hit AttachmentStore SHA-dedup so the disk cost is bounded. **Forward marker AD-733c-7 (or sibling)** to add a "dormant pauses browser capture" UX once we have the broadcast channel.

10. **Cost discipline.** Engaged-mode default preset: `min_interval=2.0s` × 1 LLM call per admit × supervisor novelty gating ≈ 15-30 calls/minute worst-case sustained. Combined with AD-733b proactive cap (3 emissions/session, 30s dwell) the upper bound is ~600 calls/hour. **For v1 we do NOT add a hard daily budget guard** — the BF-304 single-flight lock + supervisor min-interval is sufficient for single-Captain. **Forward marker AD-733c-6** files a per-session/daily cap surfaced in Settings → Perception (built on AD-742e #673 HXI vision budget badge).

11. **Recovery from process restart.** **Ephemeral state.** On restart, the controller initializes to `AMBIENT` (if perception enabled) or `DORMANT`. No persistence. Rationale: the Captain's natural cadence — closing the laptop, restarting ProbOS — is roughly "I am stepping away"; ambient is the correct default-after-restart. Document in `mode_controller.py` docstring + `PERCEPTION_MODE_INITIALIZED` event on every boot.

### Open architectural questions (Captain review)

None blocking. The 11 decisions above are pre-cleared by Captain's framing in the issue ("dormant = another room, ambient = same room reading a book, engaged = looking at you"). Two notes for awareness:

- **AmbientObserver wake-up signal (Captain's "BIG scene change" trigger).** The existing `ProactiveVisionObserver` (AD-733b) emits a DM when high-novelty fires. **AD-733c-2 piggybacks that path:** when proactive observer DM fires AND current mode is `AMBIENT`, the controller listens for the same signal (via a new optional callback wired by finalize.py) and transitions to `ENGAGED`. This is "scene change → wake up the agent" without needing a new event bus topic.
- **Wake-word race with cold avatar/camera.** Captain's note re. "wake fires but Ezri's avatar hasn't loaded" — addressed by AD-733c-3 firing `/api/perception/engage` BEFORE `form.requestSubmit()`. The engage call is async/fire-and-forget; the chat submit proceeds immediately. By the time the LLM responds (~3s), the supervisor has already had 1.5s at engaged cadence. Not perfect; no UI "warming up" badge in v1 (operator sees the existing CAMERA LIVE indicator + the new mode badge).

### Considerations the issue surfaced

| Concern | Disposition |
|---|---|
| "Hello Ezri" race vs cold avatar | Best-effort. Engage POSTed first, then chat submit. Mode flips within 100ms; LLM response is ~3s. Sufficient. |
| Mode transition observability | New badge in `CameraLiveIndicator` + `PerceptionLivePanel` (text-based per HXI Principle #3, no emoji). Amber when engaged, dim amber when ambient, very dim when dormant. |
| Multi-agent attention conflict | Per-runtime v1: ALL agents transition together. "Hello Counselor" engages the whole subsystem. AD-733c-5 forward marker for per-agent. |
| Wake-word false positives | Existing `wakeWord.ts` cooldown + ONNX confidence threshold + `_matchesLeading()` word-boundary check handle this. No new logic. |
| Engaged-on-engaged latency | Controller exposes idempotent `transition_to()` — same-mode call is a no-op log. No re-emit. |
| Settings UI for presets | v1: presets are CODE CONSTANTS. Settings → Perception shows current mode (readonly) + last 3 transitions + manual override button (POST /api/perception/mode). Editable presets is forward marker AD-733c-6's sibling. |

## Standing rules (carried from BUILDER-EXECUTION-PLAN.md)

1. **Working-tree integrity check.** Builder MUST run `git diff --numstat | Sort-Object {[int]$_.Split("\`t")[1]} -Descending | Select-Object -First 5` before starting each prompt. Any tracked-file deletion >200 lines → hard stop.
2. **No `asyncio.create_subprocess_*`** (BF-280). No subprocess in these prompts anyway.
3. **No MagicMock at substrate boundary** (BF-287). Use real `AgentRegistry`, real `IntentBus`, real `SystemConfig`. New tests use `runtime.registry.all()` not `registry.agents`.
4. **`multi_replace_string_in_file` discipline** (BF-274/278). When two SEARCH blocks are adjacent in the same file, prefer two separate `replace_string_in_file` calls.
5. **HXI Principle #3: no emoji** in new UI components. Inline stroke SVG only.
6. **AD-731 invariant:** frame bytes flow as SHA refs end-to-end. The force-describe path passes SHA, NEVER inline bytes. Source-scan test extension: `test_ad731_invariant_no_inline_base64_in_perception_modules` now covers `mode_controller.py`.
7. **AD-541b anchored episodes** still written on every force-describe path that lands a WM entry (importance=6, channel="perception").
8. **Test gate after each prompt:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -n 4 --dist=loadfile -q`. Triage failures at `-n 0` before quarantining.
9. **Per-prompt commit.** Each AD = one commit. Use the `ad-733c-N` slug.
10. **No `Stop-Process` sweeps.** Use `scripts/kill-stale-pytest.ps1` (reads `data/probos.pid` to skip the live runtime).

## Hard-stop conditions

1. Pre-flight grep finds a missing anchor in any of the four prompts.
2. `wakeWord.ts:onWake` callback signature has drifted from `(routed: WakeRoute) => void`.
3. `runtime.vision_consumer` attribute missing or renamed.
4. `BF-308` setters (`set_min_interval_seconds`, `set_novelty_threshold`, `set_baseline_max_age_seconds`) on `PerceptualHashStrategy` missing.
5. `routers/agents.py:1924` `targeted_recall_block` injection seam moved/renamed.
6. >5 quarantine markers needed across the wave.

## Build order

```
ad-733c-1  (foundation: force-describe + DM seam)
    ↓
ad-733c-2  (controller + presets; depends on 1 for DM-activity hook reuse)
    ↓
ad-733c-3  (wake-word engage; depends on 2 for transition_to)
    ↓
ad-733c-4  (idle timers; depends on 2 for controller)
```

## GATE 1 verdict slot

`_filled in by architect after pass-2 review_`

## Acceptance test for the wave

Captain's full-loop smoke (already implied by #675):
1. Boot ProbOS with perception enabled. Mode initializes to AMBIENT.
2. Wait 5 min. Verify supervisor admits at ambient cadence (~1 frame/2min); WM grows slowly.
3. Captain says "Hello Ezri" into mic. UI fires `/api/perception/engage` with `{agent: "ezri"}`. Mode flips to ENGAGED.
4. Captain types DM "what am I holding?". Force-describe fires, agent's reply references the held object.
5. Captain stops chatting. After 5 min idle, mode drops to AMBIENT (log entry).
6. After 30 more min idle, mode drops to DORMANT (log entry).
7. Captain manually flips mode to ENGAGED via `POST /api/perception/mode` (operator override).
