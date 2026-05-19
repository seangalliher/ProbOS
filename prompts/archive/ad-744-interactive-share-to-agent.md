# AD-744 — Interactive share-to-agent (one-shot DM-attached screen frame)

**Status:** Drafted 2026-05-19, GATE 1 pending.
**Closes:** (new top-level AD; no existing GH issue — filed at wave close per AD-722c-3).
**Depends on:** AD-733-2 (passive screen sensing — provides `source="screen"` and `useScreenStream`), AD-720/731 (AttachmentStore refs), AD-742c (per-agent bindings), AD-733a (VisionConsumer + `force=True` bypass per BF-302).
**Estimated tests:** +10 pytest, +6 vitest.

## Problem

AD-733-2 ships **ambient** screen sensing — the agent sees what's on screen, throttled by the supervisor's novelty gate. But the most common operator request is **explicit, one-shot**: "Hey Counselor, look at THIS for a moment and tell me what you see." Today the Captain has to type a description; ambient mode would either drop the frame (novelty gate) or show it to every vision-capable agent (privacy leak).

The user-visible bug: there is no first-class "share THIS to {agent}" UX. The plumbing exists in scattered pieces (AD-720 AttachmentStore, AD-742c bound_agent_ids, AD-733a force-describe via BF-302) but the composed flow is missing.

## Solution overview

A "Share screen" button on the DM composer. Click opens a stroke-SVG monitor/window picker modal (extends the AD-742c-6 multiplexer panel pattern). On confirm:

1. `getDisplayMedia({video: true})` captures ONE frame to a `<canvas>` and converts to JPEG blob.
2. Multipart POST to `POST /api/perception/camera/frame` with `source="screen"`, `force="true"`, and `agent_ids=<callsign_or_id>` (existing AD-742c form field). This bypasses the AD-733a supervisor's novelty gate (per BF-302 `force=True`) and restricts fan-out to the target agent.
3. The resulting `attachment_ref` (SHA-256) is attached inline to the next DM turn the Captain sends — populated into the existing `attachment_ids` field on `POST /api/chat/agents/{agent_id}/dm` (already shipped, see `routers/agents.py:agent_chat`).
4. The agent receives both the Captain's text AND the screen frame as a single composed multimodal message via the existing AD-731 OpenAI-shape resolver (BF-268).

## Scope

- IN: HXI "Share screen to {agent}" button on the DM composer; stroke-SVG monitor/window picker modal extending AD-742c-6 pattern; one-shot frame capture (NOT a long-lived stream — distinct from AD-733-2 ambient mode); inline attachment to the next DM turn via existing `attachment_ids`; bypass of supervisor novelty gate via existing `force=True` form field (BF-302); per-agent fan-out via existing `agent_ids` form field (AD-742c).
- IN (consensus posture): NON-destructive. The DM turn itself is the existing pipeline. NO new IntentDescriptor; `vision_observation` reused unchanged (`requires_consensus=False`).
- IN (AD-731): frame flows through `AttachmentStore.write` → SHA ref → `attachment_ids: [<sha>]` on the chat request. NEVER inline bytes.
- IN (AD-541b): the resulting LLM call produces an Episode in the normal DM pipeline; new `AnchorFrame(channel="perception", trigger_type="captain_explicit_share")` distinguishes from ambient + camera streams.
- IN (HXI #11 agentic-first): the UX phrase is "Share to Counselor" not "Open screen-sharing dialog." Captain commands the agent; agent acts.
- OUT: agent action on the screen (AD-745 ships that).
- OUT: persistent long-lived share session (that's AD-733-2).
- OUT: cross-agent share fan-out (forward marker AD-744-1).
- OUT: redaction / mask region UI before sharing (forward marker AD-744-2 — important privacy primitive).

## Verification: existing code referenced by this AD

```
Select-String -Path src/probos/routers/perception.py -Pattern "force.*Form|force:"
  103:    force: str = Form(""),
  146:    is_forced = force.lower() in {"1", "true", "yes"}

Select-String -Path src/probos/routers/perception.py -Pattern "agent_ids.*Form|bound_agent_ids"
  104:    agent_ids: str = Form(""),
  151:    bound_agent_ids: list[str] = []
  157:        _params["bound_agent_ids"] = bound_agent_ids

Select-String -Path src/probos/routers/agents.py -Pattern "attachment_ids|agent_chat"
  (large file; agent_chat accepts attachment_ids in the request body —
   already shipped via AD-720 and AD-730-3.)

Select-String -Path src/probos/perception/consumer.py -Pattern '"force"|params.get."force"'
  (BF-302 force=True bypasses supervisor; verify the exact line during build.)

Select-String -Path ui/src/components/settings/sections/PerceptionLivePanel.tsx -Pattern "CAMERA BINDINGS"
  (AD-742c-6 surface; the new picker modal reuses its design language.)

Select-String -Path ui/src/store/useCameraMultiplexerStore.ts -Pattern "devices|enumerateDevices"
  (precedent for surface-listing pattern.)
```

## Implementation

### Section 0: Config

`src/probos/config.py` — extend `PerceptionConfig` with ONE field:

```python
explicit_share_enabled: bool = Field(default=True,
    description="AD-744: master switch for Captain-initiated 'Share to agent' shortcuts.")
```

Default True is intentional and Wave 10 convention #14-compliant: the underlying capability (`getDisplayMedia`) requires browser-prompt consent on every click, so default-on doesn't break Captain consent posture. The toggle is provided for operators who want to disable the surface entirely (e.g., kiosk mode).

Add 1 FieldDescriptor to `_PERCEPTION_SECTION.fields`: `perception.explicit_share_enabled` (bool, hot_reload=True).

### Section 1: Backend — reuse only

**No new endpoint.** The existing `POST /api/perception/camera/frame` already accepts `source`, `force`, `agent_ids` form fields per AD-733-2 + AD-742c. Wave 178 AD-733-2 must land first.

Honest-degrade addition: when `cfg.explicit_share_enabled=False`, the existing endpoint returns 503 `explicit_share_disabled` for any POST that combines `force=true` AND non-empty `agent_ids`. This signals to the HXI that the share surface should be hidden.

### Section 2: Browser hook

New file `ui/src/hooks/useScreenShare.ts`:

```ts
export async function captureScreenShareFrame(opts: {
  agentId: string;
  agentCallsign?: string;
}): Promise<{ attachment_id: string; mime: string; size_bytes: number } | null>
```

Implementation:

1. `getDisplayMedia({video: { frameRate: 1 }, audio: false})` — picker pops.
2. Wait for `track.readyState === 'live'`, then `ImageCapture(track).grabFrame()` (or fallback to `<video>` + canvas) → JPEG blob at q=0.7.
3. **Stop the track immediately** — this is a one-shot, NOT a stream. `track.stop()` in finally.
4. Multipart POST: `file`, `session_id=share_<agentId>_<unix_ms>`, `source=screen`, `force=true`, `agent_ids=<agentCallsignOrId>`.
5. Return `{attachment_id, mime, size_bytes}` from the response, or `null` on any failure (Tier-2 honest-degrade; UX shows a stroke-error banner without throwing).

Module-singleton state: NONE. This is one-shot — every call captures fresh, no shared track.

### Section 3: HXI — DM composer

`ui/src/components/IntentSurface.tsx` (or wherever the DM composer for agent surfaces lives — verify exact file during pre-flight grep):

1. Add a stroke-SVG "Share screen" button next to the existing attach + send buttons. Glyph: monitor + arrow-into-monitor. `strokeWidth: 1.5`, `strokeLinecap: round`. Active state amber `#f0b060`; inactive dim `#666680`. NO emoji.
2. On click, invoke `captureScreenShareFrame({agentId, agentCallsign})`.
3. On success: append the returned `attachment_id` to the composer's `attachment_ids` state — the existing send-DM path includes them in the chat POST. The composer renders an inline preview thumbnail (stroke-bordered, scaled-down) so the Captain sees what's queued.
4. On failure / `null` return: render a 5-second stroke-SVG error banner. Original DM text preserved (NEVER clobbered).
5. The composer's `attachment_ids` are sent verbatim to `POST /api/chat/agents/{agent_id}/dm` — no new server code. The frame becomes part of the same composed multimodal message via the AD-733a `render_for_prompt()` scene block PLUS the existing `attachment_ids` resolver.

**Subtlety:** the AD-733a `force_describe_current_frame` path is per-session-scoped, so a frame uploaded under `session_id=share_<agentId>_<unix_ms>` lands in its own working-memory bucket. The chat handler should treat the share frame as "fresh attachment" via the AD-720 path, NOT via the AD-733a session-cached scene-block. This avoids the share frame being overwritten by the next ambient camera frame.

### Section 4: HXI — confirm/preview modal (optional v1, required v1.1)

For v1, the browser-native `getDisplayMedia` picker provides confirmation. The `track.onended` (user clicks browser's "Stop sharing") naturally cancels the capture if the operator changes their mind.

For v1.1 (forward marker AD-744-3): an in-HXI preview modal showing the captured frame BEFORE attaching to the composer, with a "redact region" affordance (canvas overlay + black-out rect). Captain ruling required before v1.1 because the redaction pipeline interacts with AD-541b episode storage.

### Section 5: Tests

`tests/test_ad744_explicit_share.py`:
1. POST with `source=screen` + `force=true` + `agent_ids="e1"` succeeds when `explicit_share_enabled=True`.
2. POST with the same fields returns 503 `explicit_share_disabled` when the master switch is False.
3. Per BF-302: `force=true` admits the frame through the supervisor regardless of novelty.
4. Per AD-742c: `bound_agent_ids` restricts WM fan-out to the named agent.
5. AD-541b: anchor episode written with `trigger_type="captain_explicit_share"` (NEW trigger type; verify the AD-541b anchor schema accepts it via the existing free-string `trigger_type` field).
6. AD-731 source-scan rerun.
7. Composed multimodal message contains BOTH the Captain's DM text AND the share-frame SHA-256 ref under `attachment_ids`.
8. Integration test: end-to-end `share → DM → agent_chat` produces an Episode with BOTH the captain_explicit_share anchor AND the agent's response.

`ui/src/hooks/__tests__/useScreenShare.test.ts`:
1. `captureScreenShareFrame` calls `getDisplayMedia` once.
2. Frame track is stopped immediately after grab (`.stop()` called on every track).
3. POST contains `source=screen`, `force=true`, `agent_ids=<id>`.
4. Returns `null` on `getDisplayMedia` rejection (Tier-2 honest-degrade).

`ui/src/components/__tests__/IntentSurface.shareScreen.test.tsx`:
5. Share button click invokes `captureScreenShareFrame` with the current agent id.
6. On success, the returned `attachment_id` is appended to composer state.

Total: +8 pytest, +6 vitest.

## Acceptance criteria

- All tests pass with the standard gate.
- `cd ui && npm run build` exits 0.
- AD-731 invariant source-scan passes.
- Zero new pip deps. Zero new npm deps. 0-line license diff.
- Forward markers filed with TECHNICAL triggers:
  - AD-744-1 — Cross-agent share fan-out (share-to-many). Trigger: Captain demand after share-to-one has been exercised ≥3 times AND operator requests multi-agent visibility.
  - AD-744-2 — Region masking / redaction before share. Trigger: Captain shares an inadvertently-sensitive frame OR Counselor flags a privacy-bearing observation.
  - AD-744-3 — In-HXI preview modal with redact-region affordance. Trigger: graduates from AD-744-2 when the redaction primitive is approved.
- PROGRESS.md Wave 178 block updated post-ship.

## Out-of-scope (explicit)

- Action on the shared screen (AD-745).
- Long-lived screen-share session (AD-733-2).
- Federation cross-host share (no operator demand).
- Redaction UI (AD-744-2 forward marker).
- "Share to many agents" (AD-744-1 forward marker).

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`, especially the consensus + minimal-authority + reversibility requirements for destructive screen-action intents.**
