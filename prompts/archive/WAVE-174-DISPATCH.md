# Wave 174 — Vision Performance + Identity

**Status:** GATE 1 — pre-dispatch draft, two-pass review pending.
**Closes:** #669 (AD-742a), #670 (AD-742b), #673 (AD-742e).
**Starting SHA:** `65c97214` (Wave 173 close: BF-312 perception backfill).
**Estimated:** ~14h, three commits, +~30 pytest, +~6 vitest.
**Theme:** make the AD-733b ENGAGED-mode perception pipeline *sustainable* — separate fast/deep vision tiers, replace the per-session LLM identity prompt with cheap face embeddings, surface real-time cost telemetry in the HXI status bar.

---

## Slate

| AD | Closes | Title | Estimate | Tests |
|---|---|---|---|---|
| **AD-742a** | #669 | `vision_fast` LLM tier + 8-guard audit | ~5h | +12 pytest |
| **AD-742b** | #670 | Face-embedding identity (replace LLM "is this the Captain?" prompt) | ~6h | +12 pytest |
| **AD-742e** | #673 | Vision LLM call budget telemetry in HXI status badge | ~3h | +6 pytest, +6 vitest |

**Highest current AD:** AD-741 shipped (Wave 170). AD-742a/b/e are forward markers filed Wave 171 (issues #669/670/673). Wave 174 promotes them to shipped ADs. AD-742c/d/f remain forward markers (#671/672/674).

## Build order

1 → 2 → 3 (strict). Rationale:
- AD-742a registers the `vision_fast` tier in `_LLM_TIERS`, which AD-742b's face-embedding code path does NOT use (face embedding is a local pip dep, not an LLM call), but AD-742a touches the same `consumer.py` describe path and `tier_config` shape that AD-742b's identity path lives in. Shipping AD-742a first means AD-742b sees the post-split tier shape.
- AD-742e reads counters maintained by both AD-742a's describe path AND AD-742b's identity path. Shipping last means the telemetry sees both surfaces complete.

---

## Research findings

### Fast vision model candidates (AD-742a)

Target: per-frame supervisor-flagged describe calls (sub-1s) instead of the AD-732 27B narrative-tier model.

| Model | License | Params | Ollama tag | Expected latency (RTX 3060+) | Verdict |
|---|---|---|---|---|---|
| **moondream** | Apache 2.0 (code) / CC-BY-SA 4.0 (model card declares Apache for weights) | 1.8B | `moondream` (latest = 1.8B Q4) | ~400-800ms single 512px frame | **v1 default**. Smallest + fastest; designed explicitly for per-frame describe. Model card: "designed for edge devices." |
| qwen2-vl:2b | Apache 2.0 | 2B | `qwen2-vl:2b` | ~600ms-1.2s | Backup. Better at structured output; ~30% slower than moondream on small frames. Tag verified `ollama pull qwen2-vl:2b`. |
| llava-phi3 | MIT (Phi-3 base) | 3.8B | `llava-phi3` | ~1-2s | Too heavy for per-frame; falls between vision_fast and AD-732 deep tier. Skip. |
| bakllava | Apache 2.0 | 7B | `bakllava` | ~2-4s | Equivalent to existing AD-732 tier; not a fast replacement. Skip. |

**v1 default:** `moondream` (Apache 2.0). Operator override via `llm_model_vision_fast` config field.
**License posture:** zero new pip deps; Ollama already resident from AD-732. `THIRD_PARTY_LICENSES.md` adds a moondream entry under "AD-742a" with model-card URL.
**Quality trade-off:** moondream hallucinates more than qwen3.6:27b on cluttered/partial scenes — acceptable for per-frame supervisor describes that feed into the WM ring buffer (the 8-frame buffer averages out single-frame errors). Scene-introduction + high-novelty proactive DMs continue to use the AD-732 `vision` tier (qwen3.6:27b) for narrative quality. **Forward marker AD-742a-1 (file as part of this wave):** A/B comparison study moondream vs qwen2-vl:2b on Captain's actual feed.

### Face-embedding candidates (AD-742b)

License is **dispositive** — AGPL/GPL out. Storage of an enrollment embedding raises a privacy question (see threat model in AD-742b prompt).

| Library | License (code) | License (default weights) | CPU? | Embedding dim | Install footprint | Verdict |
|---|---|---|---|---|---|---|
| **facenet-pytorch** | MIT | Apache 2.0 (VGGFace2 + CASIA-WebFace pretrained checkpoints, distributed by timesler/facenet-pytorch under MIT) | Yes (slow ~200ms/face); GPU ~20ms | 512 | ~110MB checkpoint + torch dep (already resident) | **v1 default.** MIT, single pip dep (`pip install facenet-pytorch`), torch already resident in venv (verified). Cosine distance threshold 0.6 well-documented. |
| face_recognition (ageitgey) | MIT | dlib's models are Boost-licensed / permissive | Yes (~150ms/face) | 128 | ~100MB dlib build; needs CMake on Windows | Backup. Smaller embedding (128-d), but Windows build chain pain. MIT-clean. |
| InsightFace | MIT (code) | **buffalo_l weights are mixed** — `arcface_r100_v1` is research-use-only; `buffalo_s` (small) is MIT | Yes | 512 | Heavy (onnxruntime, opencv) | Rejected v1 — model-weight license is a footgun. The default `buffalo_l` model has non-commercial clauses per the InsightFace ModelZoo page; operator could accidentally redistribute. |
| DeepFace | MIT wrapper | Multiple backends (depends on which) | Yes | 128-512 | Heavy meta-dep | Rejected — wrapper that pulls in TensorFlow + multiple models; install bloat unjustified when facenet-pytorch alone suffices. |
| mediapipe face_mesh + FaceNet wrapper | Apache 2.0 | Apache 2.0 | Yes (browser too) | landmarks not embedding | Rejected — gives 478 landmarks, not an embedding; would need a second model on top. |

**v1 default:** `facenet-pytorch` (MIT, pretrained Apache 2.0 weights, 512-d, torch already resident).
**License posture:** ONE new pip dep (`facenet-pytorch`); license stamp added to `THIRD_PARTY_LICENSES.md` under AD-742b with checksum of the imported checkpoint URL. NO new npm deps.
**Storage strategy:** the Captain's reference embedding is 512 float32s = 2048 bytes. **Decision: store inline in a new `data/captain_identity.json`** (sibling of existing `data/scout_seen.json`), NOT in AttachmentStore — AD-731 invariant is about RPC bus payloads (>4KB on the bus is the anti-pattern); a 2KB file on the operator's disk is the right shape for a per-instance enrollment artifact. AttachmentStore is content-addressable + cleaned by reaper — wrong semantics for "stable, one-per-operator, lifecycle-managed-by-user." Privacy threat model in the prompt.

### Cost telemetry patterns (AD-742e)

Shape-survey (architecture absorbed, no code):
- **LangSmith:** per-run cost line in a left rail; daily roll-up at top; expand-on-click breakdown by model.
- **OpenAI dashboard:** monthly accumulator with daily bars; no per-call live feed.
- **LiteLLM:** Prometheus-style counters exposed at `/metrics`; no UX of its own.
- **Anthropic console:** message-by-message breakdown in a Logs tab.

**Pattern absorbed:** rolling per-session counter (always visible when > 0) + daily roll-up (visible when > 0 today). NO per-call line item — that's panel territory, and the AD-733b PerceptionLivePanel already shows per-frame events.

**UX decision for HXI status bar:** **threshold-trigger** — append `· Vis 12/120` when `vision_calls_this_session > 0`; expand to `· Vis 12 (today 47)` when `vision_calls_today > 0`. Hidden entirely when both are zero (default boot state). Rationale: HXI Design Principle #5 (progressive disclosure) + #6 (the canvas IS the information). Daily roll-up only requires SQLite persistence if it must survive restarts; **v1 keeps it in-memory** and forward-markers persistence as AD-742e-1.

---

## Considerations surfaced beyond the issues

1. **AD-742a 8-guard audit table (full).** Every site that enumerates LLM tier names. AD-732 lesson: forgetting one breaks the new tier silently.

   | # | Site | Type | Current handling | Required change |
   |---|---|---|---|---|
   | 1 | `cognitive/llm_client.py:32` `_LLM_TIERS` | Constant | 6 tiers | Add `"vision_fast"` (7 tiers) |
   | 2 | `cognitive/llm_client.py:38` `_TIER_ORDER` | Constant | 3 text tiers | **DO NOT MODIFY** (BF-269: vision tiers never fall back to text) |
   | 3 | `cognitive/llm_client.py:261` ModelRouter bypass | `if tier in (..)` | vision, compute_use | Add `"vision_fast"` |
   | 4 | `cognitive/llm_client.py:346` health-probe unconfigured short-circuit | `tier == "vision"` | vision-only | Extend to `tier in ("vision", "vision_fast") and not tc.get("model")` |
   | 5 | `cognitive/llm_client.py:557` fallback chain | `if tier in (..)` | vision, compute_use | Add `"vision_fast"` |
   | 6 | `cognitive/llm_client.py:452` probe timeout | `min(timeout, 30s)` | All tiers via `_LLM_TIERS` loop | N/A (already correct — uses `_LLM_TIERS`) |
   | 7 | `config.py:286` `tier_config()` (6 maps) | Method body | 6 tiers explicit | Add `"vision_fast"` to all 6 maps + add 5 fields to CognitiveConfig |
   | 8 | `cognitive/vision_dispatch.py:56` `is_vision_tier_configured` | Function | vision + compute_use branches | Add `"vision_fast"` branch (model + base_url both required) |
   | 9 | `__main__.py:139` doctor command tier loop | Hardcoded tuple | `("fast", "standard", "deep", "vision")` | Replace with `_LLM_TIERS` import — AD-732 lesson #1 says single source of truth. **Refactor to import `_LLM_TIERS`** at all 3 sites. |
   | 10 | `__main__.py:239` ditto | Hardcoded tuple | Same | Same refactor |
   | 11 | `__main__.py:944` ditto | Hardcoded tuple | Same | Same refactor |
   | 12 | `experience/commands/commands_llm.py:33` tier loop | Hardcoded tuple | Same | Same refactor |
   | 13 | `experience/commands/commands_llm.py:79` tier loop | Hardcoded tuple | Same | Same refactor |
   | 14 | `settings/section_registry.py:103-105` LLM Tiers section | FieldDescriptor list | Fast/Std/Deep/Vision base URLs + models + timeouts | Add 3 new `FieldDescriptor` rows for `llm_base_url_vision_fast`, `llm_model_vision_fast`, `llm_timeout_vision_fast` |
   | 15 | LLMResponseCache (BF-272 multimodal bypass) | Behavior | Bypasses any multimodal request | N/A (shape-based, tier-agnostic) |

2. **Identity caching per frame.** Recomputing a face embedding 4 fps × 60s × 5 min = 1200 embeddings per session is wasteful when most frames look the same. Cache per-session: hold the most recent `(sha → result)` AND a TTL'd "last verified at" timestamp; only re-verify identity every N seconds OR when the supervisor admits a high-novelty frame. **Decision:** identity verification runs ONLY on supervisor-admitted frames (the same frames that fire the vision LLM describe call). That naturally throttles to ~1 every `vision_min_interval_seconds` (default 3s). NO per-frame embedding pass on rejected frames.

3. **Identity threshold operator-configurable.** `PerceptionConfig.identity_match_threshold: float = 0.6` (cosine distance; smaller = stricter match). Operator-tunable via Settings panel. Hot-reloadable via the BF-308 setter pattern (forward marker AD-742b-1 if not in v1).

4. **Identity privacy threat model.** Stored in `data/captain_identity.json` as plain JSON (`{"embedding": [...512 floats], "enrolled_at": "...", "model_id": "facenet-pytorch-vggface2"}`). **Not** tied to OAuth vault (AD-706f is for service credentials, not biometric). **Not** encrypted on disk — operator-local file; threat model is "operator owns the box; if a remote attacker can read `data/`, they can read everything else worse." Documented threat model + opt-out in the AD-742b prompt. **Hard rule:** the enrollment image MUST be deleted after embedding (we keep the 2048-byte embedding, not the photo). Photo is supplied via the existing AttachmentStore upload path and explicitly purged after enrollment.

5. **Budget telemetry storage.** Per-tier (vision / vision_fast) counters maintained on `VisionConsumer`:
   - `_calls_this_session: dict[str, int]` (per-tier; resets on session start)
   - `_calls_today: dict[str, int]` (per-tier; resets on date rollover)
   - `_last_call_at: float | None` (monotonic; for "next allowed in X.Xs")
   - **v1 in-memory only.** Forward marker AD-742e-1 for SQLite persistence (small table: `vision_call_log (tier TEXT, ts REAL, session_id TEXT)`; daily roll-up via SQL query). Issue to file post-build.

6. **Status badge UX (final).** Append-with-threshold (no always-show). Format `· Vis 12/120` (current/budget). Color: amber when `0 < calls < 80%`, dim red when `>= 80%`, bright red when at ceiling. Hover-title shows "vision: N · vision_fast: M · today: K · next allowed in T.Ts". Implemented as a new sub-component `<VisionBudgetBadge />` mounted in `DecisionSurface.tsx` immediately after the Entropy span (line 122). Five SVG icons reused from `icons/Glyphs.tsx`; **NO emoji** (HXI Principle #3).

7. **Vision tier name conflicts.** `vision_fast` deliberately separate from `vision`. BF-269 invariant preserved: vision_fast also does NOT fall back to text tiers. Verified all 15 audit sites above; if a Builder skips any, the test scaffold catches it (see AD-742a prompt Section 6).

8. **Hot-reload posture.**
   - **Restart-required:** `llm_base_url_vision_fast`, `llm_model_vision_fast`, `llm_api_key_vision_fast`, `llm_timeout_vision_fast`, `llm_api_format_vision_fast` (matches all existing tier base_url/model/key fields — they're read once in `LLMClient.__init__`).
   - **Hot-reloadable via BF-308 setters:** `PerceptionConfig.identity_match_threshold`, `PerceptionConfig.budget_badge_threshold_pct`. Both proxied through the existing supervisor-setter pattern at supervisor.py:58 (next BF-308 setter slot is identity threshold).
   - Documented per-AD.

9. **AD-541b anchored episodes + BF-311 agent_ids.** AD-742b's face-embedding identity result writes the same `subject_identity` field on `VisionObservation` that the AD-733b LLM-prompt path wrote. Episode payload unchanged. BF-311 `agent_ids` tagging unaffected. Smoke test: existing `test_ad733a_vision_consumer.py::test_vision_observation_anchored_episode_carries_agent_ids` must still pass.

10. **AD-731 invariant (RPC blob → ref).** Face embedding is 2 KB — *technically* under the 4 KB threshold and could ride the bus inline. **But** it's not actually broadcast on the bus; it's stored on disk and read locally by `_resolve_subject_identity`. No bus blob path. **Invariant preserved.**

---

## Pre-flight gate (Builder MUST run before Section 1 of any prompt)

```powershell
cd D:\ProbOS
git pull --ff-only
git status --short                                                # must be empty
git rev-parse HEAD                                                # expect 65c97214 (or descendant)
git diff --numstat | Sort-Object {[int]$_.Split("`t")[1]} -Descending | Select-Object -First 5
# Working-tree integrity (BF-274 lesson): any tracked file with >200 deletions is a STOP.

# Baseline test gate (full parallel):
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile
# Expected: green, ~14108-14042 baseline (Wave 173 close).
```

If `git status` is dirty with Architect-authored prompts/reviews/docs under `prompts/` or `Reviews/`, commit them on the architect's behalf with a descriptive message and continue (per BUILDER-EXECUTION-PLAN.md). If source code under `src/probos/` or `tests/` is dirty, **STOP**.

---

## Hard-stop conditions

1. Pre-flight grep finds a missing anchor in any of the three prompts.
2. `facenet-pytorch` pip install fails OR the imported checkpoint license differs from MIT/Apache-2.0 at install time. (Grep `pip show facenet-pytorch` output for License field. If `License: UNKNOWN`, STOP and surface to user.)
3. The Ollama model `moondream` is not pullable on the Captain's instance (Builder runs `ollama pull moondream` as part of AD-742a Section 0 smoke; if it returns a non-zero exit OR > 5 minutes, STOP).
4. Any 8-guard site listed above is missed AND a regression test catches it.
5. `tests/test_ad742a_vision_fast_tier.py` AS-EXISTS scan: `git ls-files | Select-String test_ad742a` — if the file already exists from a prior wave, STOP (means we're rebuilding a shipped AD).
6. > 5 quarantine markers across the wave.

---

## Per-AD UI gate (BF-279, AD-738b)

Only AD-742e touches `ui/src/**`. The UI gate applies to **AD-742e only**:

```powershell
cd D:\ProbOS\ui
npx vitest run                                                    # MUST be green
npm run build                                                     # MUST exit 0 — vitest does NOT run tsc
```

AD-742a and AD-742b have ZERO ui/src changes. Skip the UI gate for those two.

---

## Per-prompt gate order

For each of the three prompts:
1. Architect Pass-1 review (verify-first, anti-pattern scan).
2. Architect Pass-2 review (re-read post-Pass-1 fixes).
3. GATE 1 verdict.
4. Builder pre-flight (above).
5. Builder Section-by-Section build.
6. Per-AD test gate.
7. Commit + push.
8. (AD-742e only) UI gate.
9. Wave-close: archive prompts, update wave-plan.yaml status, update wave-orchestrator-state.json.

---

## Forward markers filed in this wave

- **AD-742a-1** — A/B comparison: moondream vs qwen2-vl:2b on Captain's actual feed (file as issue post-build).
- **AD-742b-1** — Hot-reload `identity_match_threshold` via BF-308 setter (file post-build).
- **AD-742b-2** — Multi-operator enrollment (multiple known faces; v1 is Captain-only). Refers to existing #671 (per-agent).
- **AD-742e-1** — SQLite persistence for vision call log + daily roll-up across restart (file post-build).

---

## Drafted prompt files

- `prompts/ad-742a-vision-fast-tier.md`
- `prompts/ad-742b-face-embedding-identity.md`
- `prompts/ad-742e-vision-budget-telemetry.md`

---

## GATE 1 verdict (Pass-2, pre-review of own draft)

**Verdict:** ⚠️ Conditional — pending Pass-1 + Pass-2 review of the three prompt files themselves. The dispatch doc itself: APPROVED for use as wave-orchestrator state.

### Required (must fix before Builder dispatch)
*(populated after Pass-1/Pass-2 review of each prompt file)*

### Recommended
1. Confirm `ollama pull moondream` works on Captain's machine before Builder runs Section 0 smoke. Could be a 1.7 GB download — out of band, not test budget.
2. The 5 refactor sites in `__main__.py` + `commands_llm.py` (audit rows 9-13) could be split into a forward-marker BF if they balloon AD-742a's scope. Decision: keep in AD-742a — they're 5-line edits and AD-732 lesson #1 demands single source of truth.

### Nits
1. The "vision: N · vision_fast: M" hover-title format may not fit the existing tooltip font width — verify in vitest snapshot.

### Verified
- AD-741 highest shipped (PROGRESS.md line search confirmed AD-742 entries are forward-marker mentions only, not shipped).
- `_LLM_TIERS` at `cognitive/llm_client.py:32`, `_TIER_ORDER` at line 38.
- ModelRouter bypass at line 261; fallback chain at line 557; health probe at line 346.
- `tier_config` at `config.py:286` with 6 dict-maps to update.
- `PerceptionConfig.captain_avatar_ref` at `config.py:2015` (AD-733b v1 field — AD-742b deprecates).
- `is_vision_tier_configured` at `vision_dispatch.py:56`.
- HXI status bar at `ui/src/components/DecisionSurface.tsx:71-121` (Entropy span at lines 116-121 — new VisionBudgetBadge mounts after).
- `VisionConsumer._describe` at `consumer.py:385`; `_resolve_subject_identity` at `consumer.py:430`.
- `tests/test_ad742a_vision_fast_tier.py` does NOT yet exist (Wave 174 is build-new).
- 5 tier-tuple-duplication sites confirmed in `__main__.py` (3) and `commands_llm.py` (2).
