# AD-742a — `vision_fast` LLM tier (separate from AD-732 `vision`)

**Status:** Drafted Wave 174. Closes #669.
**Dependencies:** AD-732 (vision tier), AD-733a (VisionConsumer), AD-733b (subject identity hook).
**Estimated:** ~5 hours, single commit, +12 pytest.
**Risk:** MEDIUM — new LLM tier touches 8-guard catalog (15 enumeration sites). Mechanical edits, but a single skipped site silently breaks routing.

---

## Problem

AD-733a v1 routes both per-frame supervisor-flagged describe calls AND scene-introduction / high-novelty narrative summaries through the single AD-732 `vision` tier (qwen3.6:27b on local Ollama). That works, but is wasteful: a per-frame describe is a sub-1s job; spending 4-6 seconds of 27B inference on every flagged frame burns the supervisor's `vision_min_interval_seconds=3.0s` budget and produces a 2-second-stale WM ring buffer.

Add a `vision_fast` tier for per-frame describes (default model `moondream`, ~400-800ms). Narrative + identity stays on the AD-732 `vision` tier. Apply the full eight-guard catalog so the new tier never falls back to text tiers (BF-269), bypasses the ModelRouter (BF-273), has correct probe timeout (BF-270), and is honest-degrade when unconfigured (AD-732).

## Solution

Add `vision_fast` as a seventh peer tier in `_LLM_TIERS` with full per-tier config fields. Extend the 13 tier-enumerating audit sites (see WAVE-174-DISPATCH.md table). Refactor 5 hardcoded `("fast", "standard", "deep", "vision")` tuples in `__main__.py` and `commands_llm.py` to import `_LLM_TIERS` (AD-732 lesson #1). Route `VisionConsumer._describe` to `vision_fast` when configured; fall back to AD-733b `_resolve_subject_identity` and the AD-733b proactive observer narrative path continues to use `vision` (deep narrative tier).

---

## Section 0: Pre-flight smoke

Builder MUST run before Section 1:

```powershell
ollama pull moondream
ollama list | Select-String "moondream"
# Expected: a row showing moondream with a tag and size ~1.7 GB.
```

If `ollama pull` exits non-zero OR the operator's Ollama is unreachable, STOP and surface to user — moondream is the v1 default; without it the smoke test in Section 6 cannot run.

---

## Section 1: CognitiveConfig fields

Add 5 fields to `CognitiveConfig` in `src/probos/config.py`, mirroring the AD-732 vision-tier shape. Inserted immediately after the `llm_max_tokens_compute_use` line (line 230) and before the `# AD-730-3: image_gen tier` block.

```
===SEARCH===
    llm_base_url_compute_use: str | None = None
    llm_api_key_compute_use: str | None = None
    llm_model_compute_use: str | None = None
    llm_timeout_compute_use: float | None = None
    llm_api_format_compute_use: str | None = None  # "openai" or "ollama"
    llm_temperature_compute_use: float | None = None
    llm_top_p_compute_use: float | None = None
    llm_max_tokens_compute_use: int | None = None

    # AD-730-3: image_gen tier — sixth peer of fast/standard/deep/vision/
===REPLACE===
    llm_base_url_compute_use: str | None = None
    llm_api_key_compute_use: str | None = None
    llm_model_compute_use: str | None = None
    llm_timeout_compute_use: float | None = None
    llm_api_format_compute_use: str | None = None  # "openai" or "ollama"
    llm_temperature_compute_use: float | None = None
    llm_top_p_compute_use: float | None = None
    llm_max_tokens_compute_use: int | None = None

    # AD-742a (Wave 174): vision_fast tier — small-VLM peer of AD-732 vision.
    # Per-frame supervisor-flagged describe calls (~400-800ms target) instead
    # of the 27B narrative-tier model. Default unconfigured; opt-in via
    # system.yaml. When unconfigured OR unhealthy, VisionConsumer._describe
    # falls back to the AD-732 vision tier (NOT to text tiers).
    # ModelRouter bypassed (BF-273 lesson). Does NOT participate in the
    # fast→standard→deep fallback chain (BF-269 lesson).
    # Suggested default: moondream (Apache 2.0, 1.8B, Ollama-pullable).
    llm_base_url_vision_fast: str | None = None
    llm_api_key_vision_fast: str | None = None
    llm_model_vision_fast: str | None = None
    llm_timeout_vision_fast: float | None = None
    llm_api_format_vision_fast: str | None = None  # "openai" or "ollama"

    # AD-730-3: image_gen tier — sixth peer of fast/standard/deep/vision/
===END REPLACE===
```

Then extend the six dict-maps in `CognitiveConfig.tier_config()` (config.py:286+) — each map adds a `"vision_fast"` row. Use one SEARCH/REPLACE per map (six discrete edits) to avoid BF-274 multi-replace overlap. See Section 1b.

### Section 1b: Six `tier_config` dict-map extensions

For each of the six maps (`model_map`, `url_map`, `key_map`, `timeout_map`, `format_map`, `temp_map`), add a `"vision_fast": self.llm_<X>_vision_fast` row immediately after the `"compute_use"` row. Pattern for `model_map`:

```
===SEARCH===
            "vision": self.llm_model_vision,
            "compute_use": self.llm_model_compute_use,
            "image_gen": self.llm_model_image_gen,
        }
        url_map = {
===REPLACE===
            "vision": self.llm_model_vision,
            "vision_fast": self.llm_model_vision_fast,
            "compute_use": self.llm_model_compute_use,
            "image_gen": self.llm_model_image_gen,
        }
        url_map = {
===END REPLACE===
```

Repeat the same shape for `url_map`, `key_map`, `timeout_map`, `format_map`. `temp_map` has `vision_fast: None` (no sampling override field for v1 — forward marker if needed).

---

## Section 2: `_LLM_TIERS` constant + 5 tier-tuple refactors (AD-732 lesson #1)

```
===SEARCH===
_LLM_TIERS: tuple[str, ...] = ("fast", "standard", "deep", "vision", "compute_use", "image_gen")
===REPLACE===
_LLM_TIERS: tuple[str, ...] = ("fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen")
===END REPLACE===
```

Then refactor the 5 hardcoded tuples to use `_LLM_TIERS`. **Builder MUST verify** each site is a tier-enumeration loop (NOT a fallback-chain ordering, which uses `_TIER_ORDER` and must stay text-only).

- `src/probos/__main__.py:139` — `for tier in ("fast", "standard", "deep", "vision"):` → `for tier in _LLM_TIERS:` (add `from probos.cognitive.llm_client import _LLM_TIERS` to the imports)
- `src/probos/__main__.py:239` — same
- `src/probos/__main__.py:944` — same
- `src/probos/experience/commands/commands_llm.py:33` — same (add import)
- `src/probos/experience/commands/commands_llm.py:79` — same

**One SEARCH/REPLACE per site** (BF-274 discipline: do NOT batch adjacent edits in multi_replace).

---

## Section 3: 8-guard catalog edits in `llm_client.py`

### Section 3a: ModelRouter bypass (llm_client.py:261)

```
===SEARCH===
        if tier in ("vision", "compute_use"):
            # AD-706c-2: compute_use joins vision in router bypass — the
            # AD-463 ModelRouter registry has no entries for either tier and
            # would otherwise fall through to "pick first available text
            # model", routing requests to an endpoint that cannot fulfill them.
            return None
===REPLACE===
        if tier in ("vision", "vision_fast", "compute_use"):
            # AD-706c-2 + AD-742a: vision_fast joins vision/compute_use in
            # router bypass — the AD-463 ModelRouter registry has no entries
            # for these tiers and would otherwise fall through to "pick first
            # available text model", routing requests to an endpoint that
            # cannot fulfill them.
            return None
===END REPLACE===
```

### Section 3b: Health probe unconfigured short-circuit (llm_client.py:346)

```
===SEARCH===
        for tier in _LLM_TIERS:
            tc = self._tier_configs[tier]
            # AD-732: vision tier unconfigured short-circuit. We never probe
            # a default base URL with no model name — the operator either
            # configures the tier or accepts the honest-degrade message.
            if tier == "vision" and not tc.get("model"):
                results[tier] = False
                self._tier_status[tier] = False
                continue
===REPLACE===
        for tier in _LLM_TIERS:
            tc = self._tier_configs[tier]
            # AD-732 + AD-742a: vision/vision_fast tier unconfigured
            # short-circuit. We never probe a default base URL with no
            # model name — the operator either configures the tier or
            # accepts the honest-degrade fallback (vision_fast falls back
            # to vision; vision honest-degrades to the system message).
            if tier in ("vision", "vision_fast") and not tc.get("model"):
                results[tier] = False
                self._tier_status[tier] = False
                continue
===END REPLACE===
```

### Section 3c: Fallback chain (llm_client.py:557)

```
===SEARCH===
        if tier in ("vision", "compute_use"):
            fallback_tiers = [tier]
        else:
            fallback_tiers = [tier] + [t for t in _TIER_ORDER if t != tier]
===REPLACE===
        if tier in ("vision", "compute_use"):
            fallback_tiers = [tier]
        elif tier == "vision_fast":
            # AD-742a: vision_fast falls back to vision (NOT to text tiers
            # — BF-269 invariant). If the operator's fast vision model is
            # unreachable, the deeper 27B narrative tier is still vision-
            # capable and produces a correct (slower) describe.
            fallback_tiers = ["vision_fast", "vision"]
        else:
            fallback_tiers = [tier] + [t for t in _TIER_ORDER if t != tier]
===END REPLACE===
```

**Note for Builder:** `_TIER_ORDER` MUST NOT be modified. It stays `("fast", "standard", "deep")`.

---

## Section 4: `vision_dispatch.is_vision_tier_configured` (vision_dispatch.py:56)

```
===SEARCH===
    if tier_name == "vision":
        model = getattr(cfg, "llm_model_vision", None) or ""
        base_url = getattr(cfg, "llm_base_url_vision", None)
        return bool(model and base_url)
    if tier_name == "compute_use":
        # AD-706c-2: opt-in coordinate-prediction tier. Same shape as vision.
        model = getattr(cfg, "llm_model_compute_use", None) or ""
        base_url = getattr(cfg, "llm_base_url_compute_use", None)
        return bool(model and base_url)
    return True
===REPLACE===
    if tier_name == "vision":
        model = getattr(cfg, "llm_model_vision", None) or ""
        base_url = getattr(cfg, "llm_base_url_vision", None)
        return bool(model and base_url)
    if tier_name == "vision_fast":
        # AD-742a: vision_fast peer of vision. Same shape — both model AND
        # base_url must be set. Unconfigured = fall back to vision tier
        # (which itself may honest-degrade if also unconfigured).
        model = getattr(cfg, "llm_model_vision_fast", None) or ""
        base_url = getattr(cfg, "llm_base_url_vision_fast", None)
        return bool(model and base_url)
    if tier_name == "compute_use":
        # AD-706c-2: opt-in coordinate-prediction tier. Same shape as vision.
        model = getattr(cfg, "llm_model_compute_use", None) or ""
        base_url = getattr(cfg, "llm_base_url_compute_use", None)
        return bool(model and base_url)
    return True
===END REPLACE===
```

---

## Section 5: VisionConsumer routes describes to `vision_fast` when configured

`PerceptionConfig.vision_tier` currently defaults to `"vision"` (config.py:1989). Add a new field `vision_fast_tier: str = "vision_fast"` and use it in `_describe`. The existing `_resolve_subject_identity` keeps `self._tier` (the AD-733b deep narrative tier).

Edit `src/probos/config.py` `PerceptionConfig`:

```
===SEARCH===
    vision_tier: str = Field(default="vision",
        description="LLM tier name for vision describe calls. AD-742a forward marker for vision_fast split.",
    )
===REPLACE===
    vision_tier: str = Field(default="vision",
        description="LLM tier name for narrative / proactive-observer vision calls (AD-733b scene-introduction + high-novelty triggers). Falls back to standard/deep behavior if vision_fast is unset.",
    )
    vision_fast_tier: str = Field(default="vision_fast",
        description="AD-742a (Wave 174): LLM tier for per-frame supervisor-flagged describe calls. Falls back to vision_tier when unconfigured (which itself honest-degrades).",
    )
===END REPLACE===
```

Edit `src/probos/perception/consumer.py` `VisionConsumer.__init__`:

```
===SEARCH===
        vision_tier: str = "vision",
        max_describe_tokens: int = 220,
===REPLACE===
        vision_tier: str = "vision",
        vision_fast_tier: str = "vision_fast",
        max_describe_tokens: int = 220,
===END REPLACE===
```

```
===SEARCH===
        self._tier = vision_tier
        self._max_tokens = max_describe_tokens
===REPLACE===
        self._tier = vision_tier
        self._fast_tier = vision_fast_tier
        self._max_tokens = max_describe_tokens
===END REPLACE===
```

In `_describe` (consumer.py:385), route to `_fast_tier` with a runtime configured-check; fall back to `_tier` when fast is unconfigured. Helper-import shape:

```
===SEARCH===
            request = LLMRequest(
                prompt="",
                messages=messages,
                tier=self._tier,
                max_tokens=self._max_tokens,
                temperature=0.2,
            )
            response = await asyncio.wait_for(
                self._runtime.llm_client.complete(request),
                timeout=self._timeout,
            )
            return (response.content or "").strip()
        except Exception:
            logger.warning(
                "AD-733a: vision LLM describe failed for sha=%s",
                sha[:8], exc_info=True,
            )
            return ""
===REPLACE===
            # AD-742a: route per-frame describes to vision_fast when
            # configured. The LLMClient's fallback chain (llm_client.py:557)
            # automatically routes vision_fast -> vision when fast is
            # unconfigured / unhealthy. NO text-tier fallback (BF-269).
            from probos.cognitive.vision_dispatch import is_vision_tier_configured
            cog_cfg = getattr(self._runtime.config, "cognitive", None)
            describe_tier = self._fast_tier if (
                cog_cfg is not None
                and is_vision_tier_configured(cog_cfg, self._fast_tier)
            ) else self._tier

            request = LLMRequest(
                prompt="",
                messages=messages,
                tier=describe_tier,
                max_tokens=self._max_tokens,
                temperature=0.2,
            )
            response = await asyncio.wait_for(
                self._runtime.llm_client.complete(request),
                timeout=self._timeout,
            )
            return (response.content or "").strip()
        except Exception:
            logger.warning(
                "AD-733a: vision LLM describe failed for sha=%s",
                sha[:8], exc_info=True,
            )
            return ""
===END REPLACE===
```

Identity (`_resolve_subject_identity` at consumer.py:430) stays on `self._tier` — identity needs the deeper narrative tier's instruction-following. AD-742b replaces the LLM identity path entirely.

Edit `src/probos/startup/finalize.py:4022` to pass `vision_fast_tier`:

```
===SEARCH===
            consumer = VisionConsumer(
                runtime,
                min_interval_seconds=_perception_cfg.vision_min_interval_seconds,
                novelty_threshold=_perception_cfg.vision_novelty_threshold,
                baseline_max_age_seconds=_perception_cfg.vision_baseline_max_age_seconds,
                working_memory_capacity=_perception_cfg.working_memory_capacity,
                vision_tier=_perception_cfg.vision_tier,
            )
===REPLACE===
            consumer = VisionConsumer(
                runtime,
                min_interval_seconds=_perception_cfg.vision_min_interval_seconds,
                novelty_threshold=_perception_cfg.vision_novelty_threshold,
                baseline_max_age_seconds=_perception_cfg.vision_baseline_max_age_seconds,
                working_memory_capacity=_perception_cfg.working_memory_capacity,
                vision_tier=_perception_cfg.vision_tier,
                vision_fast_tier=_perception_cfg.vision_fast_tier,
            )
===END REPLACE===
```

---

## Section 6: Settings registry (3 new FieldDescriptors)

Edit `src/probos/settings/section_registry.py` LLM Tiers section. Add 3 rows immediately after the `llm_timeout_vision` row at line 105:

```
===SEARCH===
            FieldDescriptor("cognitive.llm_base_url_vision", "Vision tier — base URL", "text"),
            FieldDescriptor("cognitive.llm_model_vision", "Vision tier — model", "text"),
            FieldDescriptor("cognitive.llm_timeout_vision", "Vision tier — timeout (s)", "float"),
===REPLACE===
            FieldDescriptor("cognitive.llm_base_url_vision", "Vision tier — base URL", "text"),
            FieldDescriptor("cognitive.llm_model_vision", "Vision tier — model", "text"),
            FieldDescriptor("cognitive.llm_timeout_vision", "Vision tier — timeout (s)", "float"),
            FieldDescriptor("cognitive.llm_base_url_vision_fast", "Vision_fast tier — base URL", "text"),
            FieldDescriptor("cognitive.llm_model_vision_fast", "Vision_fast tier — model", "text"),
            FieldDescriptor("cognitive.llm_timeout_vision_fast", "Vision_fast tier — timeout (s)", "float"),
===END REPLACE===
```

---

## Section 7: `config/system.yaml` (commented-out example block)

Add an opt-in example block after the existing vision-tier block. Builder MUST grep for the exact anchor first — the system.yaml indentation matters.

```powershell
Select-String -Path config/system.yaml -Pattern "llm_base_url_vision:" -Context 0,5
```

Add a parallel `# llm_base_url_vision_fast: "http://localhost:11434"` block immediately after the vision block, with the same indentation. Suggested values:
```yaml
# AD-742a (Wave 174): vision_fast tier — per-frame supervisor describes.
# Uncomment to opt in. Falls back to the AD-732 vision tier when unset.
# llm_base_url_vision_fast: "http://localhost:11434"
# llm_api_format_vision_fast: "ollama"
# llm_model_vision_fast: "moondream"
# llm_timeout_vision_fast: 15.0
```

---

## Tests

`tests/test_ad742a_vision_fast_tier.py` (+12 pytest):

1. `test_llm_tiers_includes_vision_fast` — `_LLM_TIERS` literally contains `"vision_fast"`.
2. `test_tier_order_excludes_vision_fast` — `_TIER_ORDER` does NOT contain `"vision_fast"` (BF-269 invariant).
3. `test_cognitive_config_has_vision_fast_fields` — `CognitiveConfig().llm_model_vision_fast is None` and `tier_config("vision_fast")` returns a dict with `model=None`.
4. `test_tier_config_vision_fast_resolves_when_set` — set `llm_model_vision_fast="moondream"` + `llm_base_url_vision_fast="http://x"`; `tier_config("vision_fast")["model"] == "moondream"`.
5. `test_is_vision_tier_configured_vision_fast_branch` — `is_vision_tier_configured(cfg, "vision_fast")` returns False when unset, True when both fields set.
6. `test_model_router_bypasses_vision_fast` — construct LLMClient with a mock ModelRouter; calling `_resolve_model_for_tier("vision_fast")` returns None (router never consulted).
7. `test_fallback_chain_vision_fast_to_vision` — `_compute_fallback_tiers("vision_fast")` returns `["vision_fast", "vision"]` exactly; no text tiers. (If helper does not exist as a public method, inline the relevant branch test against the live `complete()` path with stub tier_configs.)
8. `test_fallback_chain_vision_unchanged` — `vision` still returns `["vision"]` (regression for BF-269).
9. `test_health_probe_short_circuit_vision_fast_unconfigured` — set `llm_model_vision_fast=""`; `check_health_all()` returns `vision_fast: False` without making an HTTP call. Assert no `httpx` call by patching `_check_endpoint`.
10. `test_perception_config_has_vision_fast_tier_field` — `PerceptionConfig().vision_fast_tier == "vision_fast"`.
11. `test_vision_consumer_routes_to_fast_tier_when_configured` — construct VisionConsumer with a runtime whose CognitiveConfig has `vision_fast` configured; mock `llm_client.complete` and assert the captured `request.tier == "vision_fast"`. Use real `Config()` per BF-287; runtime stub uses `_FakeRuntime` pattern, not MagicMock.
12. `test_vision_consumer_falls_back_to_vision_when_fast_unconfigured` — same setup but `llm_model_vision_fast=None`; captured request.tier == `"vision"`.

Plus one source-scan regression test in the existing `tests/test_ad732_vision_tier.py` (or test_wave171_acceptance.py):

13. (regression) `test_no_hardcoded_tier_tuples_outside_llm_client` — `Select-String` equivalent: scan all `.py` under `src/probos/` for the literal tuple pattern `("fast", "standard", "deep", "vision")` and assert the only match is in `cognitive/llm_client.py` (where `_LLM_TIERS` is defined).

**Builder MUST run tests in this file with `-n 0` (serial)** to catch order-dependent issues, then re-run under the wave gate `-n 8 --dist=loadfile` per pre-flight rule.

---

## What this does NOT change

- AD-732 `vision` tier behavior (continues to handle narrative + identity + AD-733b proactive observer).
- `_TIER_ORDER` (text-only fallback chain stays text-only — BF-269 invariant).
- LLMResponseCache (already multimodal-bypass per BF-272 — shape-based, tier-agnostic, no change needed).
- ModelRouter API (vision_fast joins existing bypass; no new router method).
- `image_gen` / `compute_use` tier behavior.
- AD-733b face-identity LLM path (AD-742b replaces it; here it continues to use `self._tier`).
- HXI UI surface (AD-742e adds the badge).

---

## Tracking

- PROGRESS.md — add AD-742a entry under Wave 174 with closing of #669.
- DECISIONS.md — append AD-742a entry: rationale for moondream as v1 default, 8-guard audit confirmation.
- docs/development/roadmap.md — flip AD-742a from forward-marker to shipped.
- `THIRD_PARTY_LICENSES.md` — add a "moondream (AD-742a)" section: Apache 2.0, model card URL, "operator-pullable via `ollama pull moondream`."

---

## Acceptance criteria

1. All 13 audit sites in WAVE-174-DISPATCH.md table updated (audit table grepped at end of build).
2. `_LLM_TIERS` has 7 entries.
3. `_TIER_ORDER` has 3 entries (unchanged).
4. 5 hardcoded tuple sites in `__main__.py` + `commands_llm.py` refactored to import `_LLM_TIERS`.
5. +12 pytest tests, all green under `-n 0` and `-n 8 --dist=loadfile`.
6. Full test gate green: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile`.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
8. ZERO new pip deps. ZERO new npm deps. License diff: `THIRD_PARTY_LICENSES.md` adds moondream entry only (no Python pkg).

---

## Verified Against Codebase (2026-05-18)

```
grep -n "_LLM_TIERS" src/probos/cognitive/llm_client.py
  32: _LLM_TIERS: tuple[str, ...] = ("fast", "standard", "deep", "vision", "compute_use", "image_gen")

grep -n "_TIER_ORDER" src/probos/cognitive/llm_client.py
  38: _TIER_ORDER: tuple[str, ...] = ("fast", "standard", "deep")

grep -n 'tier in ("vision", "compute_use")' src/probos/cognitive/llm_client.py
  261: if tier in ("vision", "compute_use"):
  557: if tier in ("vision", "compute_use"):

grep -n 'tier == "vision" and not tc.get' src/probos/cognitive/llm_client.py
  346: if tier == "vision" and not tc.get("model"):

grep -n "def tier_config" src/probos/config.py
  286: def tier_config(self, tier: str) -> dict:

grep -n "def is_vision_tier_configured" src/probos/cognitive/vision_dispatch.py
  56: def is_vision_tier_configured(cfg: Any, tier_name: str) -> bool:

grep -n "vision_tier:" src/probos/config.py
  1989: vision_tier: str = Field(default="vision",

grep -n "VisionConsumer(" src/probos/startup/finalize.py
  4017: consumer = VisionConsumer(

grep -n 'for tier in ("fast", "standard", "deep", "vision")' src/probos/
  __main__.py:139, 239, 944
  experience/commands/commands_llm.py:33, 79
```

All anchors confirmed against HEAD `65c97214` (Wave 173 close).
