# ProbOS Progress

**Status (2026-05-11).** Open OSS issues: 10 (#582 closed Wave 150; 3 from Wave 138 — AD-721b-1/-2/-3; 5 from Wave 143 — AD-722a-1/-2/-3/-4/-6 forward markers (AD-722a-5 closed Wave 147); 1 from Wave 144 — AD-723a-1 #617 DM/WR consumer-side sensorium dispatch migration; 3 from Wave 145 — AD-721d-2 #621 Counselor-mediated revision, AD-721d-3 #622 visual preview requires AD-721i, AD-721d-4 #623 proposal-history persistence). Most recent shipped wave: 150 (AD-724 DM sanity gate — behavior-preserving migration of BF-120/BF-119/AD-572 regexes into `DmSanityGate` + 3 new log-only checks; 5 forward markers AD-724-1/-2/-3/-4/-5 filed).
AD-697 + AD-698 establish the commercial-overlay seam
(`pip install -e ../<commercial-package>` → overlay active; uninstall →
back to OSS).

**Authoritative state.**
- `prompts/wave-plan.yaml` — wave roster (current wave: 150 done; next slot is 151).
- `DECISIONS.md` — append-only architectural decisions (current highest AD: AD-738).
- `tests/` — 13449 pytest at HEAD (4 pre-existing flakes in test_callsign_routing/test_ad719_chat_fanout + occasional dreaming/ward_room flakes outside this wave) + 633 vitest; gate runs `-n 4 --dist=loadfile`.

**Wave 161 in flight (2026-05-15):**
- AD-730-2-1 — Image-budget tracker JSON sidecar persistence (+5 pytest tests; closes #656). New `src/probos/attachments/image_budget_store.py` (`load`/`save` module functions, atomic temp-file + `os.replace`). Runtime boot loads from `<data_dir>/image_budget.json` (configurable via `AttachmentsConfig.image_budget_path`). `ImagePolicyEnforcer.check_budget` persists on append AND on prune. Tier-2 throughout — disk failure logs and degrades; in-memory tracker remains authoritative. AD-731 invariant untouched (BUDGET tracker only — image bytes still flow through AttachmentStore SHA-256 refs). Forward markers AD-730-2-1a (write throttle) + AD-730-2-1b (ConnectionFactory backend swap) filed.
- AD-721d-4 — Avatar proposal-history JSON sidecar persistence (+5 pytest tests; closes #620, #623 dup). New `proposal_history.configure(path)` loads + binds the on-disk sidecar; `_persist_locked()` rewrites after every mutation (`append`, `clear`, `reset_all`). Path resolves to `AvatarsConfig.proposal_history_path` or defaults to `<data_dir>/proposal_history.json`. 5 existing public function signatures unchanged. Tier-2 throughout (disk failure logs + degrades). AD-721d-1 module-level dict + RLock unchanged. Forward markers AD-721d-4a (`ConnectionFactory` migration) + AD-721d-4b (periodic compaction) filed.
- AD-723a-2 — WR branch consumer-side sensorium dispatch migration (+6 pytest tests; closes #625). New `_WR_SELF_WRAPPED_KEYS: ClassVar[tuple[str, ...]] = ()` (sibling of `_DM_SELF_WRAPPED_KEYS`). WR branch of `_build_user_message` invokes `_dispatch_sensorium_async(SensoriumPath.WR_ONESHOT, observation)` inside Tier-2 try/except, mirrors AD-723a-1 DM path. Byte-parity preserved with empty selector (current registry shape). AD-723a-1 DM-branch tests all still green. Forward marker AD-723a-2a (populate `_WR_SELF_WRAPPED_KEYS` with first real consumer) filed.

**Wave 160 in flight (2026-05-14):**
- AD-726 — DM post-LLM cleanup pipeline extracted to DmReplyPipeline (+12 pytest tests; closes #584 partial — pre-LLM prep deferred to AD-726a/b/c forward markers). `agent_chat` shrinks 574→~305 lines. AD-722c-3 (#654) folded — BEP standing rule bullet for technical-not-commercial forward-marker language.
- AD-723a-3 — SensoriumEntry gains injection_zone + wrapper metadata (+7 pytest tests; closes #626). Backward-compatible — both fields default None. Dispatcher applies wrapper to string outputs only (dict-return contract unchanged). `_DM_SELF_WRAPPED_KEYS` still the v1 selector; per-entry migration deferred to AD-723a-3a.
- AD-722a-4 — Auto-correction loop on high-magnitude divergence (+9 pytest tests; closes #613). Default OFF. Re-modulates prosody only — response_text never rewritten. Per-utterance budget (1 correction). `DivergenceResult` gains `corrected: bool` field. `runtime.divergence_corrections` sibling map populated by `apply_divergence_check`, cleared at reply-entry by `DmReplyPipeline.step_1_sanity_gate_retry` (NOT step_7 — TTS reads slot post-reply). `apply_voice_modulation` gains keyword-only `noise_scale_factor` / `length_scale_factor` with default-1.0 no-op preserved.
- AD-730-2 — Multi-image DM policy (+9 pytest tests; closes #632). Hard cap (8, 413), in-place PIL downscale to 1024px bounding box (Tier-2; AD-731 invariant preserved via NEW refs), per-Captain rolling 24h budget (50, 429 with Retry-After). No new pip deps (Pillow 12.2.0 already in venv).
- AD-722b-4 — Fleet avatar telemetry stream (+6 pytest +3 vitest tests; closes #601). New WS at `/api/agent/avatar-telemetry/stream` fans out per-agent publish loops over one connection. Every frame carries explicit `agent_id` field. Per-agent endpoint preserved. `fleet_stream_enabled` default-ON. HXI hook stub `useFleetAvatarTelemetry` ships; per-agent store migration deferred to AD-722b-4a.

**Wave 159 in flight (2026-05-14):**
- AD-722c — Avatar telemetry JSONL history + query endpoint (+6 pytest tests; closes #569). New `src/probos/avatars/telemetry_history.py` `TelemetryHistoryWriter` (append-only JSONL, per-agent lock, executor-backed write, agent_id boundary sanitizer). `AvatarTelemetryConfig.history_enabled`/`history_retention_days`/`history_dir` added with `>= 1` validator on retention. Writer constructed in `runtime.py` next to the AvatarEventBus and exposed as `runtime.avatar_telemetry_history`. `_publish_loop` (both initial-send and per-interval send) appends snapshots best-effort — log-and-degrade, never blocks the WS publish. New `GET /api/agent/{id}/avatar-telemetry/history?limit=&since=` endpoint clamps limit to `[1, 1000]` and returns `{"agent_id", "rows": []}` when the feature is off. Forward markers AD-722c-1 (size-based rotation) + AD-722c-2 (`TelemetryHistoryStore` Protocol for commercial overlay backend swap) filed. Known dreaming flake (`test_nl_to_dream_cycle_changes_weights`, environmental Chroma boot under serial) noise-only.
- AD-722d — Auto-write significant telemetry events to Ship's Records (+5 pytest tests; closes #570). New `src/probos/avatars/records_writer.py` `TelemetryRecordsWriter` — three v1 events (`emotion_divergence_high`, `working_state_transition_to_blocked`, `sustained_silence`), priority pick (divergence > blocked > silence), per-agent throttle (default 3600 s, in-memory, resets on restart by design), Tier-2 log-and-degrade. `AvatarTelemetryConfig` gains `records_auto_write_enabled=False` (Captain opt-in), `records_throttle_seconds=3600`, `records_significant_events` list (default-factory; unknown names silently dropped), `sustained_silence_seconds=1800` — validators bound all three. Two-phase wiring in `runtime.py`: attribute declared as `None` next to AvatarEventBus, real `TelemetryRecordsWriter` constructed after `self._records_store = cog.records_store` finalize line. `_publish_loop` initial + per-interval hooks observe AFTER the AD-722c history append. Tests use `_FakeRecordsStore` stub — no git subprocess. Forward markers AD-722d-1 (operator-defined event classifiers) + AD-722d-2 (Records-side dedup/aggregation) filed.
- AD-722b-3 — Fine-grained snapshot-diff for WS push (+6 pytest tests + 1 Vitest test; closes #600). New `src/probos/avatars/snapshot_diff.py` `compute_diff(prev, next, threshold, skip_fields)` with `last_observed_at` in `DEFAULT_SKIP_FIELDS`. New `AvatarTelemetryConfig` fields: `ws_diff_enabled=True`, `ws_diff_threshold=0.05`, `ws_full_snapshot_every_n=10` (with validators). `_publish_loop` now tracks per-connection `last_sent_snap_dict` + `tick_count`; emits `{"type":"snapshot", ...flat}` on first frame / every Nth tick / fallback, otherwise `{"type":"diff","agent_id":...,"changed":{...}}`. Empty diffs are suppressed entirely (zero bytes on the wire). Frontend `SelfImageTab.tsx` `onmessage` merges diff frames into a closure-scoped `lastSnapshot` and strips the `type` field on snapshot frames for shape parity with the GET endpoint. The shared `_ws_endpoint_runtime` fixture explicitly disables diffing so the AD-722b legacy tests keep their one-frame-per-wake semantics. Forward markers AD-722b-3a (RFC 6902 JSON-Patch payload) + AD-722b-3b (server-side `SubscriberState` Protocol for fan-out broker) filed.
- AD-720e + AD-738e-2 — Audio attachment playback + Refs-trailer standing rule (+5 pytest tests + 3 Vitest tests; closes #566, #653). `AttachmentsConfig.allowed_mime_types` defaults extended with `audio/mpeg`, `audio/mp4`, `audio/ogg`. `attachments/mime.py._SIGNATURES` registers MP3 sync bytes (4 variants) + MP4 ftyp brands (3 variants) + Ogg `OggS`; `_ANY_OF` extends to include `audio/mpeg` + `audio/mp4` so the existing any-of branch validates them. `IntentSurface.tsx` attachment preview gains middle audio branch rendering `<audio controls preload="metadata">` between the image and file-icon branches. `WardRoomThreadDetail.tsx` paste handler accepts audio MIMEs (chip-only render — playback delivered through IntentSurface, scope-collapse per AD). AD-731 SHA-ref invariant preserved (audio bytes flow through AttachmentStore exactly like images). Transcription explicitly deferred (AD-705a forward marker). BUILDER-EXECUTION-PLAN standing rule for orphan sub-AD Refs-trailer added per #653; DECISIONS AD-738e-1 forward-marker AD-738e-2 (noise_w / sentence_silence) renumbered to AD-738e-2-prosody so #653 owns the AD-738e-2 slot. Forward markers AD-720e-1 (drop-zone visual feedback) + AD-720e-2 (waveform thumbnail) + AD-720e-3 (inline player in WR/Profile chips) filed.
- AD-725 — Targeted sub-intent dispatch on DM one-shot path (+11 pytest tests; closes #583). New `src/probos/cognitive/dm_targeted_lookup.py` `LookupDispatcher` + `SubintentClassifier` Protocol + v1 `RegexSubintentClassifier` (episodic → codebase → knowledge → oracle → none ladder). New `DmTargetedLookupConfig` (default `enabled=False`, `timeout_ms=500`, per-store enables, `max_lookup_chars=1500`, classifier-tier validator with `{regex, embedding}`). Wired into `routers/agents.py::agent_chat` BEFORE the vision-pipeline branch. Result prepended to `message_text` as `--- Targeted Recall (<type>) ---` block immediately before IntentMessage build. Four hard contracts: (1) at most one lookup per turn, (2) read-only, (3) hard `asyncio.wait_for` timeout, (4) no `intent_bus` broadcast. Defensive dispatch — missing methods log INFO and degrade to `""`. Test #10 explicitly verifies zero `trust_network`/`intent_bus`/`hebbian_router`/`consensus_engine` mock calls (firewall regression test). Forward markers AD-725-1 (sensorium-path registration) + AD-725-2 (embedding classifier) + AD-725-3 (per-agent sub-intent vocabulary) + AD-725-4 (multi-store fan-out) + AD-725-5 (LRU cache) + AD-725-6 (Episode dataclass stringify) filed.

**Wave 158 in flight (2026-05-13):**
- AD-737a — Divergence-detector hygiene (+3 pytest tests; closes #648). Hoisted `import dataclasses` to module-top; collapsed the two-pass `parse_intent_self_tag` re-parse in `apply_divergence_check` (palette fetched first, single parse); documented the test-fake contract for `runtime.profile_store` / `divergence_results` / `divergence_history` in the function docstring.
- AD-738a — Orchestrator commit-count audit + voice.ts test gate (+2 Vitest tests; closes #650). `Format-Gate2` now prints a COMMIT-COUNT AUDIT line comparing the wave-plan expectation vs HEAD's unpushed commits (audit trail only — never blocks push). `_resetTtsStatusForTests` gated behind `import.meta.env.MODE === 'test'` so production callers are inert. Renumbered Wave-157 forward markers AD-738a/b/c/d → AD-738f/g/h/i atomically in `docs/development/roadmap.md` and the AD-738 closure block.
- AD-738b — Per-wave UI gate codifies `npm run build` requirement (closes #651, BF-279 root cause). Standing rule added to `BUILDER-EXECUTION-PLAN.md` and surfaced in `wave-orchestrator.ps1:Format-BuildDispatch` so every UI-touching prompt's per-commit gate runs `npx vitest run` AND `npm run build` (Vitest skips `tsc -b` strict; BF-279 was 32h of stale-bundle drift across three waves).
- AD-738c — rhubarb→Oculus viseme mapping polish (+4 pytest tests + 1 Vitest test; closes #652). Duration-aware Preston-Blair → Oculus routing: long `B` frames (>80 ms) now route to `ih` (full vowel) instead of `kk` (stop consonant default). Consonant residuals in `VISEME_TARGETS` bumped from 0.10–0.20 → 0.20–0.30 so stop consonants are visible above the perceptual blend baseline. AD-721b-3 (#561 whisper.cpp WASM tiny.en) remains the long-term proper fix.
- AD-738e-1 — Per-emotion Piper prosody overrides (+7 pytest tests + 2 Vitest tests). Additive on top of AD-738e global defaults; concerned (slower + expressive), excited (faster + more variation), formal (drier). Custom AD-737 emotions resolve to v1 parent server-side via the new public `resolve_emotion_to_v1` alias before reaching the chat response. PiperBackend merges overrides per-call (no instance mutation).

**Wave 157 in flight (2026-05-13):**
- AD-738 — Server-streamed TTS via Piper (+26 pytest tests + 6 Vitest tests + 1 regression Vitest; closes forward marker AD-721b-2.3). MIT-licensed operator-provided binary at `tools/piper/piper(.exe)` + MIT-licensed default voice model `en_US-amy-medium.onnx[.json]` at `tools/piper/voices/`. New `src/probos/audio/tts/` module with `TTSBackend` Protocol + `PiperBackend` subprocess wrapper + `NullBackend` honest-degrade. New `TTSConfig` Pydantic model (default `backend = "browser"` — zero behaviour change for operators who don't install Piper). New `GET /api/avatars/tts/status` probe endpoint + `POST /api/avatars/tts` synthesis endpoint (AD-731 ref-shape invariant — audio bytes flow through AttachmentStore as SHA-256 refs, never inline). Browser `speakResponse` caches the one-time status probe in module-level state and skips POST entirely when `backend != "piper"` (load-bearing zero-HTTP-per-utterance guarantee). On piper happy path, browser plays via `<audio>` element + injects visemes into `useLipSyncCapture` via new `injectLipSyncFrames` setter. AD-735 volume + AD-737 emotion modulation apply to BOTH paths. Honest-degrade chain preserves `SpeechSynthesisUtterance` fallback at three tiers. Forward markers AD-738a (per-agent voice selection), AD-738b (GPU TTS backend eval — Kokoro/StyleTTS2), AD-738c (server-side voice modulation), AD-738d (TTS text caching) filed.

**Wave 156 in flight (2026-05-13):**
- AD-735 — Per-agent volume slider in `ProfileInfoTab.tsx` (+5 Vitest tests; closes #527). Backend chain (`VoiceProfile.volume`, `SetVoiceProfileRequest`, `PUT /api/agents/{id}/voice-profile`, `voice.ts` playback) was already shipped under AD-718; this AD exposed the UI slider with inline SVG speaker glyph (HXI Design Principle #3) and percent display. Mirrors Pitch/Rate `onMouseUp`/`onTouchEnd` persistence semantics. No backend, deps, or wire-shape changes.
- AD-736 — Mic-permission UX polish (+8 Vitest tests; closes #558). New `MicPermissionState` enum (`pending` / `granted` / `denied` / `unavailable`) + `onMicPermissionState` listener API in `wakeWord.ts`. Pre-flight `navigator.mediaDevices.enumerateDevices` hardware probe distinguishes "no audio device" from "permission denied"; `audio-capture` SR error mapped to `unavailable`. New `MicPermissionHint.tsx` HXI overlay mounts at `App.tsx` root; renders only on `denied`/`unavailable`. Dismissal sticky via `localStorage[hxi_mic_hint_dismissed]`. Inline SVG mic glyph (HXI Design Principle #3) — no emoji. AD-705 wake-word algorithm + AD-731 attachment invariant unchanged.
- AD-737 — Per-agent custom emotion taxonomy v2 (+8 pytest tests; closes #612). New `EmotionProfile` dataclass + `CrewProfile.custom_emotions` field (max 8 entries, must not collide with the v1 fixed 8). `parse_intent_self_tag` accepts custom names; `apply_voice_modulation` resolves through `inherits`, composes additive ±0.15 deltas, and emits BOTH the parent `intent_X` rule (so `compute_divergence`'s `startswith('intent_')` filter preserves scoring) and a `custom_X` observability tag. `apply_divergence_check` pre-resolves the custom name to its v1 parent for scoring, then restores the custom name on the `DivergenceResult` for observability. Prompt builder dynamically renders v1 + custom names from `profile_store`. Parent-equivalence pinned: zero-shift custom emotion inheriting `concerned` scores `match_score=1.0` identical to `concerned`. `EmotionalIntent`, `INTENT_EXPECTED_RULES`, `_REQUIRED_INTENT_EMOTIONS`, manifest, AD-731 invariant all unchanged.

**Wave 155 in flight (2026-05-12):**
- AD-721b-1 — Server-side rhubarb-lip-sync backend (+16 pytest tests; closes #559). MIT-licensed operator-provided binary at `tools/rhubarb/`; honest-degrade to AD-721b v1 heuristic when binary absent. Section 0.5 extends `AttachmentsConfig.allowed_mime_types`, `attachments/mime.py._SIGNATURES`, and `attachments/filesystem_store.py._MIME_TO_EXT` for `audio/webm` and `audio/wav`. `POST /api/avatars/lipsync` endpoint accepts AD-720 sha256 attachment refs and returns Oculus-mapped viseme schedule.
- AD-721b-2 — Browser-side real-audio capture infrastructure (+8 Vitest tests; closes #560). Always-on capture via `MediaStreamAudioDestinationNode` + `MediaRecorder`; honest-degrade end-to-end on the server (capture-fail → server-fail → empty frames → CrewVRM falls back to v1 heuristic → AD-721 D5 amplitude). AD-731 invariant honored: captured bytes upload via `/api/chat/attachments/multipart` as a sha256 ref; the lipsync request body carries only the hash, never inline base64. Most browsers today do not route SpeechSynthesis through Web Audio — the infrastructure ships ahead of upstream browser routability.

**Wave 154 in flight (2026-05-12):**
- AD-719c + AD-718d-1 — HXI polish: @-picker keyboard nav (↑/↓/Tab) + ModulationIndicator pulse overlay (+6 Vitest tests; closes #548, #553).
- AD-730-1-1 — WardRoomThreadDetail drag/drop + paste-image attachment (+3 Vitest tests; closes #646; #647 closed as duplicate pre-flight).
- AD-720d-1 — Multi-image batch + per-attachment timing; AttachmentsConfig.multi_image_warn_threshold soft warning (+5 pytest tests; closes #563).
- AD-724-1 + AD-724-2 + AD-724-5 — DM sanity gate hardening: one-shot retry on rejection, stdlib SequenceMatcher fuzzy repetition, shared `apply_dm_sanity` helper lifted into proactive WR/chain paths (+12 pytest tests; closes #627, #628, #629).

**Recent eras (archived):**
- [Era I — Genesis](progress-era-1-genesis.md)
- [Era II — Emergence](progress-era-2-emergence.md)
- [Era III — Product](progress-era-3-product.md)
- [Era IV — Evolution](progress-era-4-evolution.md)
- [Era V — Unification](progress-era-5-unification.md)

----

## Era VI — Commercial Bridge (Waves 105-128, May 2026)

### What landed (this era)

| Wave | AD/BF | Summary |
|------|-------|---------|
| 105 | AD-641g v1 | NATS cognitive chain pipeline foundation (publish-side, opt-in) |
| 106 | BF #423 | knowledge/store git-recovery test coverage (+6 tests) |
| 107 | AD-694a | extract `/api/ontology/graph` edge logic to `ontology/graph_snapshot.py` |
| 108 | BF #426 | `KnowledgeGraphView` TRUST mode O(n²) edge cap |
| 109 | BF #425 / AD-696 | wave-plan status drift reconciliation + convention docs |
| 110 | Nit #427 | `TrainingAgent` redundant `_runtime` override removed |
| 111 | AD-697 v1 | commercial overlay extension-point registry |
| 112 | AD-641g-1 | chain NATS consumer foundation (subscriber side, opt-in) |
| 113 | AD-697-1 + AD-698 | overlay seam validation: HXI badge + pre-intent authorization hook |
| 114 | BF #465 | roadmap reconciliation — flip 27 shipped `(planned, OSS)` tags |
| 115 | AD-443 (drift) | mobility protocol — already shipped |
| 116 | AD-482 (drift) | self-improvement pipeline — already shipped |
| 117 | AD-529 + AD-568 | comm contagion firewall + source governance |
| 118 | AD-660b | `/api/causal-templates` router |
| 119 | AD-572d-i + AD-573e-i | interruptible-wait + `recent_for_agent` infra |
| 120 | AD-539c-i + AD-539d-i | active gap remediation + federated aggregation |
| 121 | AD-509b/c/d + AD-507b | boot-camp continuations + curriculum progression |
| 122 | AD-511b + AD-511d | protective disengagement + boundary-probing detection |
| 123 | AD-522b + AD-522c | Cp/Cpk capability indices + graduated-response zone mapping |
| 124 | AD-583f/g (drift); AD-574c-i partial | observable state already shipped; DM convergence partial-deferred |
| 125 | AD-686c + AD-647d | `oracle.semantic_stats()` + chain CONSULT checkpoint store |
| 126 | AD-473 + AD-474 | PWA Web Push subscription registry + voice STT/TTS substrate |
| 127 | priority-4 cleanup combo | AD-509e/507c/507d/511c/511e/522d/522e/660c/660d |
| 128 | BF #466 | xdist stabilization: `-n 16 --dist=loadfile` |
| BF | BF #467 | distinguish leading @callsign (DM) from embedded mention (broadcast) |

**Net new tests this era:** ~145 pytest + ~5 vitest. Issue count: 37 closed.

### What's open (forcing-function deferrals)

| AD | Forcing function |
|----|------------------|
| AD-574c-ii | DM conversation convergence (full ProfileChatTab refactor — substrate now ready) |
| AD-641g-1-1 | flip executor to `await` ANALYZE results from NATS (depends on AD-641g-1 consumer in production use) |

----

## Era VI — Closing Notes

- **Commercial overlay seam is live.** `runtime.commercial_overlay_loaded` and `/api/system/extensions` expose registry state. `pre_intent_authorization` hook fires on every `IntentBus.broadcast`; default-empty registry means zero overhead.
- **No open OSS issues.** Pre-public-release tracker stays clean unless a regression or a new commercial-tagged AD lands.
- **Roadmap drift convention:** `(SHIPPED, OSS)` for landed entries; `(planned, OSS)` for pending. Reconciliation runs on demand (tracked in BF #465 / AD-696).


