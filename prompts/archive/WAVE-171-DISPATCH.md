# WAVE-171 DISPATCH — End-to-end live camera perception

**Stage:** GATE 1 (drafting + research pass)
**Captain's acceptance test:** Captain opens a 1:1 DM with Ezri (Counselor), points camera at scene, holds up a glass of water. Ezri (a) recognizes the Captain on camera, (b) names/describes the glass, (c) asks a question about it.
**Authorization:** Captain authorized over-budget; loop until end-to-end testable.

---

## Slate

| Slot | Prompt | Closes | Tests | Risk |
|---|---|---|---|---|
| 1 | `prompts/ad-733a-vision-consumer.md` | [#665](https://github.com/seangalliher/ProbOS/issues/665) | +18 pytest | medium-high |
| 2 | `prompts/ad-733b-proactive-observer.md` | [#666](https://github.com/seangalliher/ProbOS/issues/666) | +10 pytest | medium |
| 3 | `prompts/bf-298-settings-parent-child.md` | (BF — no GH issue) | +6 vitest | low |

**Total: +28 pytest, +6 vitest. Estimated 16h. AD numbering: AD-733a/733b reuse pre-existing umbrella numbers; BF-298 is the next BF after the highest-known BF-292 (#291 verified shipped Wave 166).**

**Current highest AD:** AD-741 (Wave 170). Forward markers added this wave: **AD-742a–AD-742f** (filed as issues #669–#674).

---

## Research absorption

### NeuralCompanion — three-tier vision pipeline (MIT, ABSORB)

| Pattern | Adopt | Rationale |
|---|---|---|
| `VisionSource → VisionSupervisor → VisionConsumer` taxonomy | YES | Direct architectural absorption. Names match. AD-733a Section 1-3 implements this triad in `perception/{supervisor,consumer,working_memory}.py`. Attribution noted in DECISIONS.md. |
| Supervisor as "behavior rules" registered via prompt contributors | PARTIAL | We adopt the Strategy Protocol (pluggable supervisor variants — AD-742d). We do NOT yet register supervisor prompt contributors as LLM-side rules — our v1 is pure aHash, no LLM in the supervisor. Forward marker: AD-742d's "Captain authors per-source rules" path. |
| Capture handlers returning `{captured_at, image_path, content_text, source}` dict | PASS | We have the AD-731 ref-shape invariant: refs not blobs. Their dict carries a path; ours carries a SHA. Same idea, our shape is stricter. |
| Checkable child tabs / settings (`ui.tab_enabled` capability) | PARTIAL | BF-298 introduces parent/child disable in our Settings panel. We don't replicate their capability bus — too much surface for v1. The disabled-when-parent-OFF UX is the user-facing equivalent. |
| Visual Reply addons (dock panel for generated images) | PASS | Out of scope. We have HXI surfaces already; not absorbing their Qt-style dock model. |

**License: MIT — clean absorb. Architecture only — no code copied.**

### Open-LLM-VTuber (MIT) — vision integration

| Pattern | Adopt | Rationale |
|---|---|---|
| Frame attached to user turn (poll latest frame, add to prompt) | YES | We already do this via AD-731 attachment shape (Captain uploads image with DM). AD-733a extends it to "agent always has latest WM frame in context, no operator upload required." |
| Continuous frame polling at fixed interval | PASS | We use event-driven `vision_observation` intents (push not pull). Their poll model would double our HTTP. |

### LiveKit Agents (Apache 2.0) — real-time multimodal framework

| Pattern | Adopt | Rationale |
|---|---|---|
| Session + Agent class + on_message handlers | PASS | We have CognitiveAgent + IntentBus already. Adopting LiveKit's class shape would be a major refactor. |
| Session frames as ordered turn artifacts | INSPIRATION | Confirms our "working memory as ordered observations" pattern is the conventional shape. No code adoption. |

### moondream2 / qwen2-vl:2b (Apache 2.0 model weights) — fast vision tier candidates

Forward marker AD-742a (#669). Not absorbed in Wave 171 — single `vision` tier reused. v1 ships with whatever Captain configured under AD-732 (qwen3.6:27b on the operator's local Ollama). Latency floor enforced via supervisor `min_interval=5s`.

---

## Decisions on the 8 research questions

1. **Frame supervisor strategy (v1):** Temporal throttle (5s floor) + perceptual aHash diff (64-bit, 8x8 grayscale, threshold 0.15 of bit-diff). Pure Python + Pillow (already transitive dep). Pluggable Strategy Protocol — AD-742d adds motion/CLIP/classifier variants.
2. **Sample rate:** Keep Wave 170's 1 fps client capture. Supervisor downsamples to ≤0.2 fps for LLM. No raise — increases bus traffic + AttachmentStore growth (retention is AD-733-1 / #667 forward marker).
3. **Vision tier model:** Reuse the single AD-732 `vision` tier. Forward marker AD-742a (#669) splits to `vision_fast` + `vision_deep` once the eight-guard tax is applied for the new tier.
4. **Identity recognition (v1):** One-shot vision LLM prompt comparing live frame against `PerceptionConfig.captain_avatar_ref` (SHA in AttachmentStore, manually configured). Returns "captain" / "other" / "unknown". One LLM call per session. Forward marker AD-742b (#670) for face-embedding.
5. **Working memory format:** `VisionWorkingMemory` per agent — `deque[VisionObservation]` of size 8 (configurable). Renders as `--- Current Visual Context ---` block with age, novelty, subject, and description. Confabulation guard: empty buffer renders explicit "no current visual data" sentinel (BF-294 lesson). Injected into `agent_chat` message_text via the same prepend pattern as AD-725 `targeted_recall_block` (verified `routers/agents.py:1922`).
6. **Proactive trigger (v1):** Two triggers in `ProactiveVisionObserver`: (a) `scene_introduction` — first WM-recorded observation in a session fires one DM; (b) `high_novelty` — novelty > 0.50, past dwell window, budget available. Capped at 3 emissions/session, 30s dwell. The observer sends a `[SYSTEM-INITIATED: ...]` user-turn to the agent — the **agent's own LLM** composes the actual operator-visible reply, preserving voice profile.
7. **Cost discipline:** `PerceptionConfig.vision_min_interval_seconds = 5.0` (LLM call floor). Plus `proactive_max_emissions = 3` per session. At 1 fps capture × 0.2 fps LLM × 600s = 120 calls/session worst case; typical session more like 20-40. AD-742e (#673) surfaces budget in HXI status badge.
8. **Retention:** Stay forward marker. AD-733-1 (#667) ships in a later wave. Wave 171 deliberately doesn't gate on retention so the end-to-end test path lands first.

---

## Considerations the original issues didn't anticipate

| Concern | Mitigation in this wave |
|---|---|
| "Camera just turned on" event — agent has no signal | `scene_introduction` proactive trigger fires once per camera session (AD-733b). |
| Frame staleness between supervisor call and DM turn | WM observations carry timestamps; `render_for_prompt` shows the age. Agent reasons honestly about "a moment ago I saw…". No forced fresh-frame pass (would burst the budget). |
| Multi-agent perception | All agents share the same physical camera; each maintains independent WM. Forward marker AD-742c (#671) for per-agent camera. |
| Cost surprise | Hard min-interval + soft session ceiling (proactive cap). Default values keep a 10-min session under ~120 calls. |
| Working-memory persistence | Lost on restart by design. Anchored episodes (importance=6) survive. Forward marker AD-742f (#674). |
| Conversational tone | Confabulation guard string is **prescriptive** ("Do NOT describe what you cannot see") — keeps Ezri's voice honest without re-engineering her prompt template. |

---

## New GH issues filed before dispatch

| # | Title | Reason |
|---|---|---|
| [#669](https://github.com/seangalliher/ProbOS/issues/669) | AD-742a: vision_fast LLM tier (per-frame supervisor + describe), separate from AD-732 vision (narrative/deep) | Per-frame describe is sub-1s job; reusing 27b model wastes latency budget. |
| [#670](https://github.com/seangalliher/ProbOS/issues/670) | AD-742b: Face-embedding identity recognition (replace v1 LLM "is this the Captain?" prompt) | LLM identity check costs one call/session and is brittle. |
| [#671](https://github.com/seangalliher/ProbOS/issues/671) | AD-742c: Per-agent camera selection | All agents currently share the runtime's single camera. |
| [#672](https://github.com/seangalliher/ProbOS/issues/672) | AD-742d: Pluggable VisionSupervisor strategies | v1 ships aHash + throttle; motion/CLIP/classifier deferred. |
| [#673](https://github.com/seangalliher/ProbOS/issues/673) | AD-742e: Vision LLM call budget telemetry in HXI status badge | Live cost visibility; #673 builds on BF-298's badge. |
| [#674](https://github.com/seangalliher/ProbOS/issues/674) | AD-742f: Per-agent vision working memory persistence across restart | Hot WM is in-RAM only; anchored episodes survive but the working-set projection does not. |

---

## Pre-flight gate (Builder must run BEFORE accepting dispatch)

```powershell
# 1. Clean tree.
git status --short
git diff --numstat | Sort-Object {[int]$_.Split("`t")[1]} -Descending | Select-Object -First 5

# 2. Baseline test count.
.\.venv\Scripts\pytest.exe tests/ -q -n 4 --dist=loadfile --no-header 2>&1 | Select-String -Pattern "passed|failed" | Select-Object -Last 3

# 3. Confirm verified-API anchors still exist (each prompt's Verified table).
Select-String -Path src\probos\mesh\intent.py -Pattern "def subscribe\(self, agent_id" -List
Select-String -Path src\probos\routers\agents.py -Pattern "targeted_recall_block is not None" -List
Select-String -Path src\probos\routers\agents.py -Pattern "_get_attachment_store" -List
Select-String -Path src\probos\cognitive\vision_dispatch.py -Pattern "async def build_multimodal_messages" -List
Select-String -Path src\probos\config.py -Pattern "class PerceptionConfig" -List
Select-String -Path src\probos\routers\perception.py -Pattern "AnchorFrame\(" -List
Select-String -Path src\probos\types.py -Pattern "class LLMRequest" -List

# 4. AD-731 source-scan baseline.
Select-String -Path src\probos\routers\perception.py -Pattern "b64encode|base64\.b64|blob_b64"
# Expected: zero hits.

# 5. UI baseline.
cd ui; npx vitest run; cd ..
cd ui; npm run build; cd ..  # BF-279/AD-738b: Vitest skips tsc.
```

---

## Hard-stop conditions

1. **Pre-flight grep finds a missing anchor.** Stop, report, do not modify the prompt without architect approval.
2. **`runtime.registry.agents` does not exist or returns a different shape.** Substrate-boundary phantom (BF-287 lesson). Stop, surface to architect.
3. **Pillow not importable at runtime.** Pillow is a transitive dep but the consumer's aHash path imports it. If unavailable, supervisor degrades to throttle-only (already coded). Note in build report; do not add Pillow to install_requires without approval.
4. **`build_multimodal_messages` signature drifted.** Surface — vision dispatch is a load-bearing seam.
5. **AD-731 source scan fails on any new file in `perception/`.** Stop; no inline base64 in vision code paths ever.
6. **More than 5 quarantine-marker tests across the wave.** Order-dependent rot escalates; surface to architect.

---

## Gate order

1. **GATE 1** (this doc) — architect approval. **AT THIS DOC. DO NOT DISPATCH BUILDER.**
2. **GATE 2** — pre-flight checklist clean, baseline test counts captured.
3. **GATE 3 per-prompt** — after each prompt commits, run `pytest tests/test_ad733{a,b}_*.py -v -n 0` then full gate `pytest tests/ -q -n 4 --dist=loadfile`. UI prompt also runs `cd ui && npx vitest run && npm run build`.
4. **GATE 4** — Captain test (manual): see acceptance script below.
5. **GATE 5** — close issues, append PROGRESS.md / roadmap.md / DECISIONS.md, push.

---

## Captain test (manual, GATE 4)

**Prerequisites:**
- ProbOS runtime running with the AD-732 vision tier configured (`cognitive.llm_base_url_vision` + `cognitive.llm_model_vision` set in `config/system.yaml`; verify with `curl http://127.0.0.1:8000/api/system/health` showing vision tier `operational`).
- Captain's reference avatar uploaded to AttachmentStore. Quick path: any portrait JPEG, `curl -F file=@portrait.jpg -F session_id=enroll http://127.0.0.1:8000/api/perception/camera/frame` (returns SHA). Set `perception.captain_avatar_ref: "<sha>"` in `config/system.yaml`.

**Steps:**
1. Open HXI. Open Settings → Perception. Confirm status badge reads `subsystem: OFF`. Toggle `perception.enabled` → status badge becomes `subsystem: ON · 0 modalities active`. APPLY.
2. Toggle `perception.camera.enabled` → APPLY. Click START on the PerceptionLivePanel. Browser prompts for camera permission; grant it. Status badge becomes `subsystem: ON · camera live`. Frame counter starts incrementing.
3. Open a 1:1 DM with Ezri. Within ~10s, Ezri proactively says something like "I can see you, Captain — what's that you're holding?" (scene_introduction trigger fires after first frame is described).
4. Hold up a glass of water. Within ~10s, Ezri sends a high-novelty DM ("Is that a glass of water? Are you about to take a break?") OR — if the dwell window blocks — type "What can you see?" to Ezri; her reply references the glass.
5. Verify in journal: `--- Current Visual Context ---` block prepended to the message_text; `Episode(reflection="Vision observation: ...", importance=6, anchors=AnchorFrame(channel="perception", trigger_type="vision_described"))` stored.

**Pass criteria:** Ezri's reply text mentions the glass (or whatever object Captain held up). No silent fallback. No exception in the runtime log.

**Fail-and-loop conditions:**
- Vision LLM call lands but description is "I see a person" with no object — model is too coarse. Captain re-runs with a different `cognitive.llm_model_vision` (e.g., qwen2-vl:7b instead of moondream).
- Identity always returns "unknown" — verify `perception.captain_avatar_ref` set and the SHA actually resolves to the uploaded portrait.
- Scene-introduction DM never fires — check `proactive_observer_enabled=true` and `runtime.vision_observer` attribute set. Debug-log grep for `AD-733b: proactive vision DM dispatched`.

---

## GATE 1 verdict

### Required (must fix before building)
None remaining. Pass-2 caught and fixed two defects inline:
1. ~~AD-733a Section 5 used the phantom `runtime.registry.agents`~~ — **FIXED inline**. Pass-2 grep confirmed `AgentRegistry` exposes `all()` returning `list[BaseAgent]` (`src/probos/substrate/registry.py:67`); private `_agents` is explicitly off-limits per BF-287. Prompt now uses `runtime.registry.all()` and iterates `agent.id`.
2. ~~AD-733b Section 3 had a tangled `is_first` ternary~~ — **FIXED inline**. Replaced with the clean `first_for_session` boolean tracked on `_sessions_with_observations`.

### Recommended
1. **Identity hook adds one extra vision LLM call per session.** Captain authorized over-budget. Document in the build report's "cost note" so the call count surfaces in the per-wave audit.
2. **`store.read(sha)` and `store.mime_for(sha)` are both async on `FilesystemAttachmentStore`** (`src/probos/attachments/filesystem_store.py:105, 125`). The prompts call them with `await` everywhere — verified.

### Nits
1. AD-733a Section 7 test case 16 ("test_dm_reply_prepends_scene_block") will need a stub `agent_chat` integration test — the simplest shape is to call the helper directly via `from probos.perception.consumer import get_or_create_working_memory; wm = get_or_create_working_memory("test"); wm.append(...); render = wm.render_for_prompt(); assert "..." in render`. Document the simpler unit test in case full integration is too costly.
2. BF-298 Section 1's "apply the same pattern to enum/int/text" is non-mechanical — Builder may want to extract a small `<DisabledWrapper>` helper. Acceptable either way; prompt does not mandate.

### Verified
- `IntentBus.subscribe(agent_id, handler, intent_names)` shape — `src/probos/mesh/intent.py:115`.
- `targeted_recall_block` prepend pattern — `src/probos/routers/agents.py:1922-1925`.
- `LLMRequest(messages=..., tier=..., max_tokens=...)` shape — `src/probos/types.py:227-245`.
- `Episode` + `AnchorFrame` shape — `src/probos/routers/perception.py:73-91`.
- `build_multimodal_messages` callable + signature — `src/probos/cognitive/vision_dispatch.py:158`.
- `PerceptionConfig` location — `src/probos/config.py:1920`.
- `PerceptionLivePanel.tsx` exists with constants used by BF-298 — `ui/src/components/settings/sections/PerceptionLivePanel.tsx:13-15`.
- `FieldRow` in `SettingsMain.tsx` — `ui/src/components/settings/SettingsMain.tsx:21`.
- `runtime.llm_client.complete` + `LLMResponse.content` — `src/probos/cognitive/llm_client.py:45, 490`.
- `AgentWorkingMemory` exists with `append(WorkingMemoryEntry)` shape (separate from new VisionWorkingMemory; we deliberately do not extend it to avoid coupling visual to text-conversational rendering) — `src/probos/cognitive/agent_working_memory.py:228`.
- AD-731 invariant preserved: all three new modules read frame bytes via `AttachmentStore.read(sha)`; no `b64encode` / `base64.b64` / `blob_b64` references.
- Eight-guard catalog NOT triggered — Wave 171 reuses the existing `vision` tier (AD-732). AD-742a (#669) carries the eight-guard tax when a new `vision_fast` tier is introduced.
- HXI Design Principles compliance: BF-298 uses inline color constants + monospace; no emoji, no Material Design.
- License posture: zero new deps, zero file additions outside `src/probos/perception/` + `ui/src/components/settings/`.

**Verdict: ✅ APPROVED for GATE 2 (Builder pre-flight). Recommended items can be addressed inline during build.**

**The architect has stopped here per Captain's instruction. Builder dispatch awaits explicit Captain go-ahead.**
