# ProbOS Progress

**Status (2026-05-11).** Open OSS issues: 10 (#582 closed Wave 150; 3 from Wave 138 — AD-721b-1/-2/-3; 5 from Wave 143 — AD-722a-1/-2/-3/-4/-6 forward markers (AD-722a-5 closed Wave 147); 1 from Wave 144 — AD-723a-1 #617 DM/WR consumer-side sensorium dispatch migration; 3 from Wave 145 — AD-721d-2 #621 Counselor-mediated revision, AD-721d-3 #622 visual preview requires AD-721i, AD-721d-4 #623 proposal-history persistence). Most recent shipped wave: 150 (AD-724 DM sanity gate — behavior-preserving migration of BF-120/BF-119/AD-572 regexes into `DmSanityGate` + 3 new log-only checks; 5 forward markers AD-724-1/-2/-3/-4/-5 filed).
AD-697 + AD-698 establish the commercial-overlay seam
(`pip install -e ../<commercial-package>` → overlay active; uninstall →
back to OSS).

**Authoritative state.**
- `prompts/wave-plan.yaml` — wave roster (current wave: 150 done; next slot is 151).
- `DECISIONS.md` — append-only architectural decisions (current highest AD: AD-735).
- `tests/` — 13396 pytest at HEAD (4 pre-existing flakes in test_callsign_routing/test_ad719_chat_fanout + 1 dreaming flake outside this wave) + 613 vitest; gate runs `-n 4 --dist=loadfile`.

**Wave 156 in flight (2026-05-13):**
- AD-735 — Per-agent volume slider in `ProfileInfoTab.tsx` (+5 Vitest tests; closes #527). Backend chain (`VoiceProfile.volume`, `SetVoiceProfileRequest`, `PUT /api/agents/{id}/voice-profile`, `voice.ts` playback) was already shipped under AD-718; this AD exposed the UI slider with inline SVG speaker glyph (HXI Design Principle #3) and percent display. Mirrors Pitch/Rate `onMouseUp`/`onTouchEnd` persistence semantics. No backend, deps, or wire-shape changes.

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


