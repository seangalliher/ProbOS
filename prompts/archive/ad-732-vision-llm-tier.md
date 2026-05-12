# AD-732 — Dedicated Vision LLM Tier + Honest Degrade

**Status:** Ready for Builder
**GH issue:** [#640](https://github.com/seangalliher/ProbOS/issues/640)
**Dependencies:** AD-720 (AttachmentStore, shipped), AD-720d (vision pipe-through for `/api/chat`, shipped), AD-730 (per-agent DM vision pipe-through, shipped), AD-731 (content-addressable refs, shipped Wave 152), BF-268 (OpenAI image_url shape at the vendor boundary, shipped 2026-05-11)
**Wave:** 153
**Estimated tests:** ≥ 14 new (`tests/test_ad732_vision_tier.py`) + small extensions to AD-730/AD-731 suites

---

## Captain decisions baked in

1. **Vision is a first-class fourth tier.** Same structure as `fast`/`standard`/`deep`: per-tier `base_url`, `api_key`, `model`, `timeout`, `api_format`, `temperature`, `top_p`. Same `CognitiveConfig.tier_config("vision")` API. Same health probe. Same `_clients` dedupe.
2. **OSS default: local Ollama + llava.** `config/system.yaml` ships a documented (but commented-out) example block pointing at `http://127.0.0.1:11434/v1` with model `llava:34b`. Operator uncomments + runs `ollama pull llava:34b`. No paid keys, no internet calls, matches the BYOM ethos.
3. **`AttachmentsConfig.vision_tier` default changes from `"standard"` to `"vision"`.** Existing operator configs that explicitly set `vision_tier: "standard"` keep working (validator allows it); new installs default to the dedicated tier and degrade honestly when it's unconfigured.
4. **Honest degrade replaces silent failure.** When vision is requested and the vision tier is unconfigured OR unhealthy, the reply is a single, operator-facing sentence that names the exact config keys and the recommended `ollama pull` command. No more "Try again in a moment" (misleading) and no more pretending the image went through (Ezri's confusion).
5. **No fallback chain for vision.** `fast → standard → deep` is the existing fallback for text completions. Vision does NOT participate (standard/deep can't see the image; falling back to them is what BF-268 already established as wrong). Vision tier failures degrade to the honest-degrade message — they never silently route to a non-vision endpoint.
6. **Vision tier is opt-in. Default unconfigured = degrade.** AD-720d default-on for non-image attachments stays unchanged. Operators who don't want vision pay zero cost.

---

## Problem (verified diagnostic baseline — 2026-05-11)

After AD-731 (refs on bus) + BF-268 (OpenAI image_url shape at vendor boundary) shipped and a fresh image was sent through both `/api/chat` and `/api/agent/{id}/chat`, the LLM still doesn't see the image. Captain's repro: Ezri reports "no image visible on my end." `/api/chat` repro: `gpt-4o` describes "Visual Studio Code editor with open files" — the Copilot proxy is injecting its own editor context and the image bytes are not reaching the model.

Root cause is the **endpoint**, not the wire format. The Copilot proxy ([gratajik/vscode-copilot-proxy](https://github.com/gratajik/vscode-copilot-proxy)) is a passthrough over the VS Code Language Model API (`vscode.lm.selectChatModels(...).sendRequest(...)`). That API:
- Does not pipe arbitrary user-supplied images through for free-form turns.
- Strips non-text content parts when building `LanguageModelChatMessage`.
- Returns 200 OK even when image content was dropped (no error signal).
- Re-injects VS Code's own editor context into the prompt, polluting unrelated requests.

Direct testing against the proxy with three shapes (Anthropic `source.base64`, OpenAI `image_url` to Claude, OpenAI `image_url` to gpt-4o) confirms: no shape gets images to the model through that proxy. **No client-side wire-format adjustment can fix this.**

AD-731 + BF-268 were correct — provider adaptation belongs at the vendor boundary. AD-732 says: the vendor boundary for *vision* has to point at an endpoint that can actually carry images.

## Solution

Promote `vision` to a fourth peer-tier of `fast`/`standard`/`deep`. Reuse the entire existing infrastructure: per-tier config block, health probe, client dedupe, status tracking. Document local Ollama + llava as the OSS-default operator setup; degrade honestly with a named recommendation when the tier is unconfigured.

The architectural shape: **provider-agnostic content blocks on the bus (AD-731); provider-specific shape adaptation in the LLM client (BF-268); endpoint selection per-tier (AD-732)**. Three orthogonal concerns, each at the right layer.

---

## Section 0 — Files touched

| File | Change |
|---|---|
| `src/probos/config.py` `CognitiveConfig` | Add 7 fields: `llm_base_url_vision`, `llm_api_key_vision`, `llm_model_vision`, `llm_timeout_vision`, `llm_api_format_vision`, `llm_temperature_vision`, `llm_top_p_vision` (all `Optional`, default `None`). Extend `tier_config()` (config.py:230, map dicts ~240-264) to resolve them with shared-default fallback. |
| `src/probos/config.py` `AttachmentsConfig` | Default `vision_tier` changes from `"standard"` to `"vision"`. Extend `_vision_tier_must_be_known` (config.py:1107) allow-set to `{"fast", "standard", "deep", "vision"}`. |
| `src/probos/cognitive/llm_client.py` | Single-source-of-truth refactor: introduce module-level `_LLM_TIERS = ("fast", "standard", "deep", "vision")` for state-init loops (Section 2a). Keep `_TIER_ORDER = ["fast", "standard", "deep"]` for the fallback chain (vision NOT in fallback). Replace every hardcoded `("fast", "standard", "deep")` tuple in this file via grep-and-replace (~12 occurrences at HEAD); only intentional exclusion is `_TIER_ORDER` at line ~483. Update class docstring (line ~49) and `check_connectivity` docstring (line ~293) to mention four tiers. Health probe runs for vision the same way. `check_connectivity` returns a dict that now includes `"vision"`. |
| `src/probos/cognitive/llm_client.py` `MockLLMClient.get_health_status` (~line 1050; tier tuple at ~line 1054) | Include vision in the tier dict with `status: "operational"` so test scaffolding constructing `MockLLMClient` satisfies vision-path code. |
| `src/probos/experience/commands/commands_llm.py` (lines 33, 79) | Loop over the new tuple. |
| `src/probos/__main__.py` (lines 86, 186, 844) | Loop over the new tuple. Connectivity report at line 186 now reports vision too. |
| `src/probos/runtime.py` (line 3775 — separate concern, only 2 tiers there) | Leave unchanged; that path is a `fast`/`standard`-only convenience, not the per-tier infra. |
| `config/system.yaml` | Add documented commented-out vision tier block with the llava recommendation. |
| `src/probos/routers/chat.py` (line ~309) and `src/probos/routers/agents.py` (line ~926) | Replace the current "try again in a moment" stub with the honest-degrade message helper (see Section 3). Distinguish "vision tier unconfigured" vs "vision tier unhealthy" — both surface the same operator-facing remediation, but with different log levels (info vs warning). |
| `src/probos/cognitive/vision_dispatch.py` | New small helper `is_vision_tier_configured(cfg: CognitiveConfig, tier_name: str) -> bool` — returns True iff the tier has a non-default `llm_base_url_<tier>` OR a non-default `llm_model_<tier>` configured. Used by the degrade decision. |
| `tests/test_ad732_vision_tier.py` | NEW — 14+ tests covering config wiring, tier_config resolution, honest-degrade routing, AttachmentsConfig default, Pydantic validator, MockLLMClient health surface. |
| `tests/test_ad730_agent_chat_vision.py` | UPDATE — assertions for the new degrade message text; tier-status branches now also test unconfigured. |
| `tests/test_ad731_attachment_ref_wire_format.py` | VERIFY — no shape changes; the bus is unchanged. Should be green without edits. |
| `PROGRESS.md` | Wave 153 entry + test count delta. |
| `DECISIONS.md` | Append AD-732 closure block. |
| `docs/development/roadmap.md` | Mark AD-732 shipped Wave 153. |
| `.github/copilot-instructions.md` | Add a one-line bullet under "Common Review Flags": *"New tier added to LLM client: every `(\"fast\", \"standard\", \"deep\")` tuple in the file must be replaced by the single-source-of-truth constant `_LLM_TIERS`. The fallback chain `_TIER_ORDER` is a separate concern — vision does NOT join it."* |

**Do NOT touch:**
- `src/probos/cognitive/vision_dispatch.py` build_multimodal_messages (unchanged; sender shape is fine from AD-731).
- `src/probos/cognitive/llm_client.py` `_resolve_attachment_refs_for_openai` (unchanged; BF-268's shape is correct for OpenAI-compat endpoints including Ollama OpenAI compat).
- `IntentMessage` / `AttachmentStore` Protocol.
- HXI / TypeScript UI.
- Federation strip behavior (still pinned to AD-731a forward marker).

---

## Section 1 — Config

### 1a. Extend `CognitiveConfig` with the vision tier fields

Add to `src/probos/config.py` `CognitiveConfig`, immediately after the existing `llm_*_deep` field block (around line 200-205):

```python
    llm_base_url_vision: str | None = None
    llm_api_key_vision: str | None = None
    llm_timeout_vision: float | None = None
    llm_api_format_vision: str | None = None  # "openai" or "ollama"

    # Per-tier sampling overrides also need vision entries
    llm_temperature_vision: float | None = None
    llm_top_p_vision: float | None = None

    # Model name follows the same Optional[str] pattern as the other vision fields.
    # ``None`` (or empty string from explicit YAML) = vision unconfigured →
    # ``is_vision_tier_configured`` returns False → honest-degrade message fires.
    llm_model_vision: str | None = None
```

All seven fields are `Optional[None]` for consistency. The `is_vision_tier_configured` helper (Section 3a) treats both `None` and empty string as unconfigured via a single `not cfg.llm_model_vision` truthiness check.

### 1b. Extend `tier_config("vision")`

Add `"vision"` to every existing map dict in `tier_config` (config.py:230, map dicts ~240-264):
```python
model_map = {
    "fast": self.llm_model_fast,
    "standard": self.llm_model_standard,
    "deep": self.llm_model_deep,
    "vision": self.llm_model_vision,
}
url_map = {
    "fast": self.llm_base_url_fast,
    "standard": self.llm_base_url_standard,
    "deep": self.llm_base_url_deep,
    "vision": self.llm_base_url_vision,
}
# ...same pattern for key_map, timeout_map, format_map, temp_map, top_p_map
```

The existing `return { ... }` dict expression is shape-correct; no changes needed there. Note: `model_map.get(tier, self.llm_model_standard)` retains the existing fallback-to-standard behavior, which means if vision somehow ends up with `model = None`, it falls back to the standard model name. That is the documented behavior; the honest-degrade short-circuit in Section 2c catches the unconfigured case before this matters.

### 1c. `AttachmentsConfig` updates

```python
# Default changes from "standard" to "vision"
vision_tier: str = "vision"

@field_validator("vision_tier")
@classmethod
def _vision_tier_must_be_known(cls, v: str) -> str:
    allowed = {"fast", "standard", "deep", "vision"}  # add "vision"
    if v not in allowed:
        raise ValueError(
            f"AD-720a/AD-732: vision_tier must be one of {sorted(allowed)}; got {v!r}"
        )
    return v
```

The error-message AD reference is updated from `AD-720a` to `AD-720a/AD-732` for traceability.

**DO NOT touch `config.py:2189` `ModelDispatchConfig._tier_values_valid`.** That validator gates `model_tier_overrides` (AD-476 specialty→tier map: `backend`/`frontend`/`test`/`infrastructure`/`data` → tier). Adding `"vision"` there would let operators write `model_tier_overrides: {backend: "vision"}` which is semantically meaningless (vision is for image content, not a code-gen specialty) and creates an operator-misconfig surface. The ONLY validator that needs `"vision"` is `AttachmentsConfig._vision_tier_must_be_known` at config.py:1107 (handled above).

### 1d. `config/system.yaml` — documented opt-in example

Add after the existing `llm_model_deep` block, around line 60:

```yaml
  # AD-732 — Vision tier. Default-unconfigured. Enable for image-aware DMs.
  #
  # Recommended OSS setup: local Ollama + llava (free, no API key).
  #   1. Install Ollama: https://ollama.com/download
  #   2. Run: ollama pull llava:34b
  #   3. Uncomment the four lines below.
  #
  # Cloud alternative: point at OpenAI / Anthropic direct (set llm_api_key_vision).
  #
  # llm_base_url_vision: "http://127.0.0.1:11434/v1"
  # llm_model_vision: "llava:34b"
  # llm_api_format_vision: "openai"  # Ollama's OpenAI-compat endpoint
  # llm_timeout_vision: 120  # local inference can be slow on first load
```

Do NOT uncomment — Builder leaves the example commented. The operator opts in.

---

## Section 2 — LLM client: tier as a first-class peer

### 2a. Module-level tier constants

At the top of `src/probos/cognitive/llm_client.py`, after the existing imports:

```python
# AD-732: single source of truth for the tier set. State-init loops use this.
# The fallback chain (_TIER_ORDER, defined locally where used) is a separate
# concern — vision deliberately does NOT participate in fallback because
# fallback exists for text-completion graceful degrade, and standard/deep
# cannot see images. Vision failures route to the honest-degrade message.
_LLM_TIERS: tuple[str, ...] = ("fast", "standard", "deep", "vision")
```

### 2b. Replace every hardcoded tuple in this file

Grep the file for the literal pattern `("fast", "standard", "deep")` (also as a dict-comprehension iterator like `t in ("fast", "standard", "deep")`). At HEAD there are ~12 occurrences. Replace EVERY match with `_LLM_TIERS`.

**Do NOT replace** `_TIER_ORDER = ["fast", "standard", "deep"]` (line ~483, a list-literal not a tuple). That is the fallback-chain order and vision is intentionally excluded.

Docstring drift to update in the same pass (verify-and-update):
- llm_client.py:49 (`OpenAICompatibleClient` class docstring): change `Each tier (fast/standard/deep) can have its own:` to mention `vision` as the fourth tier.
- llm_client.py:293 (`check_connectivity` docstring): change the `Returns {"fast": ..., "standard": ..., "deep": ...}` example to include `"vision"`.

AFTER the grep-and-replace pass, the only `("fast", "standard", "deep")` literal remaining in llm_client.py should be inside `_TIER_ORDER`. Confirm with a final grep before commit.

### 2c. Health probe runs for vision

`check_connectivity` already iterates `_LLM_TIERS` after Section 2b. The ping payload (`messages=[{"role":"user","content":"ping"}]`) is text-only, which works against llava (it is a vision-capable text model). No code change in the probe itself.

**Special case**: if `llm_model_vision == ""` (unconfigured sentinel), `check_connectivity` should mark the tier as `unreachable` WITHOUT making an HTTP call. Add at the start of the per-tier connectivity check:

```python
# AD-732: vision tier unconfigured short-circuit
if tier == "vision":
    tc = self._tier_configs["vision"]
    if not tc.get("model"):  # empty-string sentinel
        connectivity["vision"] = False
        continue
```

This prevents nonsense probes against a default base URL with no model name.

### 2d. `MockLLMClient` parity

Update `MockLLMClient.get_health_status` (defined at ~line 1050; tier tuple at ~line 1054) so its returned tier dict includes `"vision"` with `status: "operational"`. Mocks are always green for vision so the existing test scaffolding keeps working. The mock has no real endpoint; it just needs to satisfy `get_health_status()["tiers"]["vision"]["status"] == "operational"` for test consumers.

Note: there are TWO `get_health_status` methods in the file — one on `OpenAICompatibleClient` (~line 953) and one on `MockLLMClient` (~line 1050). The grep-and-replace in Section 2b covers the OpenAI one's loop (line 967). Section 2d specifically targets the Mock one (line 1054).

---

## Section 3 — Honest degrade

### 3a. Helper: `is_vision_tier_configured`

In `src/probos/cognitive/vision_dispatch.py`, add at module level:

```python
def is_vision_tier_configured(cfg, tier_name: str) -> bool:
    """AD-732: vision tier is "configured" iff it has both a model name and
    (a non-default base URL OR an explicit non-vision tier alias).

    The empty-string ``llm_model_vision`` sentinel means unconfigured;
    operators must set both a base URL and a model name to enable vision.

    When the configured tier_name is one of the legacy tiers ("fast",
    "standard", "deep"), defer to the existing health probe — they're
    always configured by default. Only "vision" needs the configured-check.
    """
    if tier_name != "vision":
        return True
    model = getattr(cfg, "llm_model_vision", "") or ""
    base_url = getattr(cfg, "llm_base_url_vision", None)
    return bool(model and base_url)
```

### 3b. Operator-facing degrade message

Add a new module-level constant in `src/probos/cognitive/vision_dispatch.py`:

```python
VISION_UNCONFIGURED_MESSAGE = (
    "Vision LLM is not configured on this ProbOS instance. Image attachments "
    "require a vision-capable model. To enable it, install Ollama "
    "(https://ollama.com), run `ollama pull llava:34b`, then uncomment the "
    "vision tier block in config/system.yaml. Alternatively, point "
    "cognitive.llm_base_url_vision and cognitive.llm_model_vision at "
    "OpenAI, Anthropic, or any other OpenAI-compatible vision endpoint."
)

VISION_UNHEALTHY_MESSAGE = (
    "Vision LLM endpoint is configured but currently unreachable. "
    "Check that the configured vision endpoint (cognitive.llm_base_url_vision) "
    "is running and reachable. Once the endpoint recovers, image attachments "
    "will work again on the next message."
)
```

Two distinct messages because they have different operator remediations: "unconfigured" needs setup; "unhealthy" needs the endpoint restarted.

### 3c. Wire into the existing degrade sites

Two sites already check `tier_status != "operational"` and return / fall through. They become:

**`src/probos/routers/chat.py` line ~309** (the existing `tier_status != "operational"` block in `/api/chat`):

```python
if tier_status != "operational":
    from probos.cognitive.vision_dispatch import (
        VISION_UNCONFIGURED_MESSAGE,
        VISION_UNHEALTHY_MESSAGE,
        is_vision_tier_configured,
    )
    if not is_vision_tier_configured(runtime.config.cognitive, tier):
        logger.info(
            "AD-732: vision DM requested but vision tier unconfigured; "
            "returning honest-degrade message"
        )
        return {"response": VISION_UNCONFIGURED_MESSAGE, "dag": None, "results": None}
    logger.warning(
        "AD-732: vision tier=%s configured but unhealthy (status=%s); "
        "returning honest-degrade message. attachment_ids=%s",
        tier, tier_status, list(req.attachment_ids),
    )
    return {"response": VISION_UNHEALTHY_MESSAGE, "dag": None, "results": None}
```

Remove the existing thin-stub `"I see {len(req.attachment_ids)} attachment(s) ..."` string entirely.

**`src/probos/routers/agents.py` line ~926-948** (the agent_chat DM path):

The current code logs a warning and falls through to `augment_prompt_with_attachment_text`, which gives the agent only text markers. After AD-732 that path is replaced with:

```python
if tier_status != "operational":
    from probos.cognitive.vision_dispatch import (
        VISION_UNCONFIGURED_MESSAGE,
        VISION_UNHEALTHY_MESSAGE,
        is_vision_tier_configured,
    )
    # Look up the callsign once — mirror the established pattern at
    # agents.py:1013-1015 (callsign_registry is a stable runtime attribute,
    # no hasattr guard needed).
    _callsign = runtime.callsign_registry.get_callsign(agent.agent_type)
    if not is_vision_tier_configured(runtime.config.cognitive, tier):
        logger.info(
            "AD-732: agent_chat vision DM unconfigured for %s; honest-degrade",
            agent_id,
        )
        # Don't even call the agent — return the message directly so we
        # don't waste an LLM call AND don't confuse the crew member
        # (the agent has no way to surface this config issue itself).
        return {
            "response": VISION_UNCONFIGURED_MESSAGE,
            "callsign": _callsign,
            "agentId": agent_id,
        }
    logger.warning(
        "AD-732: agent_chat vision tier=%s unhealthy for %s; honest-degrade",
        tier, agent_id,
    )
    return {
        "response": VISION_UNHEALTHY_MESSAGE,
        "callsign": _callsign,
        "agentId": agent_id,
    }
```

**Safety note (verified)**: the early-return happens BEFORE `_sampling_state.enter_dm`, `_avatar_event_bus.notify`, `observe_self_avatar`, and `intent_bus.send` (all at agents.py:990-1010). Because the matching `exit_dm` is bracketed by the `enter_dm` invariant, never-enter → never-exit is correct — no refcount leak. AD-722 self-avatar refresh is also never triggered, which is desirable (we're not actually serving the agent's perception loop).

Rationale for the early return on the agent path: the agent itself cannot fix a missing endpoint config. Routing the message into the agent's perception loop and asking it to "do something" with an image it cannot see produces hallucinated responses (Ezri's "no image visible on my end" was actually a HIT on the right truth, but the OS shouldn't rely on the crew to surface infra issues). The OS speaks for itself when the OS is the problem.

### 3d. Plain text DMs unchanged

Both branches above only fire when `image_ids` is non-empty. Text-only DMs with no attachments, and DMs with non-image attachments (PDF/txt/md/json/csv), continue through the existing `augment_prompt_with_attachment_text` path unchanged.

---

## Section 4 — Tests (≥ 14 new in `tests/test_ad732_vision_tier.py`)

Each test = one behavior. Use `pytest-asyncio` and `_Fake*` stubs.

### Config wiring (4 tests)

1. **`test_cognitive_config_vision_tier_fields_default_unconfigured`** — `CognitiveConfig()` has `llm_model_vision == ""`, `llm_base_url_vision is None`. The empty-string sentinel is what `is_vision_tier_configured` checks.
2. **`test_tier_config_vision_returns_resolved_dict`** — `CognitiveConfig(llm_base_url_vision="http://127.0.0.1:11434/v1", llm_model_vision="llava:34b").tier_config("vision")` returns `{"base_url": "http://127.0.0.1:11434/v1", "model": "llava:34b", ...}`. Falls back to shared `llm_base_url` only when explicitly None.
3. **`test_tier_config_vision_falls_back_to_shared_when_unset`** — When per-tier is None and the shared fallback is set, vision inherits shared (mirrors fast/standard/deep behavior).
4. **`test_attachments_config_default_vision_tier_is_vision`** — `AttachmentsConfig().vision_tier == "vision"`. The validator now allows `"vision"` and still rejects `"deep_unknown"`.

### Honest degrade routing (5 tests)

5. **`test_api_chat_vision_unconfigured_returns_unconfigured_message`** — Build a runtime with default config (vision unconfigured). POST `/api/chat` with an image attachment_id. Assert response.body["response"] == `VISION_UNCONFIGURED_MESSAGE`. Assert NO LLM call was made (capture via fake transport).
6. **`test_api_chat_vision_unhealthy_returns_unhealthy_message`** — Vision tier configured but `get_health_status()["tiers"]["vision"]["status"]` returns `"unhealthy"`. Assert response is `VISION_UNHEALTHY_MESSAGE`.
7. **`test_agent_chat_vision_unconfigured_returns_unconfigured_message`** — Same but for `/api/agent/{id}/chat`. Assert NO IntentMessage was dispatched (capture via fake bus). The crew never sees an image-DM intent it can't handle.
8. **`test_agent_chat_vision_healthy_routes_through_to_agent`** — Vision tier operational. POST with image attachment. Assert the IntentMessage carries `vision_messages` with the AD-731 `attachment_ref` shape AND the request reaches the agent's perception loop (capture via fake bus).
9. **`test_text_only_dm_unchanged_when_vision_unconfigured`** — DM with no attachments. Assert vision-tier state is irrelevant; request flows through the normal text path. Regression sentinel — vision degrade must not affect plain DMs.

### LLM client tier infra (5 tests)

10. **`test_llm_client_tracks_vision_tier_in_health_status`** — Construct `OpenAICompatibleClient` with a vision tier configured. `client.get_health_status()["tiers"]["vision"]` is a dict with `status`, `consecutive_failures`, etc.
11. **`test_llm_client_skips_health_probe_when_vision_unconfigured`** — Construct with `llm_model_vision=None`. `await client.check_connectivity()` returns `{"vision": False, ...}` WITHOUT making an HTTP call to the vision base_url.

    **Mechanism**: `OpenAICompatibleClient.__init__` creates its own `httpx.AsyncClient` instances in `self._clients` (llm_client.py:135). To assert zero requests, the test should replace each entry in `client._clients` with `httpx.AsyncClient(transport=httpx.MockTransport(recorder))` AFTER construction, then run `check_connectivity()`, then assert no recorded request has `request.url.host` matching the vision base_url's host. Alternative: monkeypatch `httpx.AsyncClient` to default `transport=` to a recorder before construction. Either is fine; pick the smaller test footprint.
12. **`test_llm_client_clients_dedupe_when_vision_shares_endpoint`** — Configure vision to use the same `base_url + api_format` as standard. Assert `len(client._clients)` does not grow (existing dedupe logic).
13. **`test_llm_client_clients_separate_when_vision_distinct_endpoint`** — Different base URL → separate httpx client entry.
14. **`test_mock_llm_client_health_status_includes_vision`** — `MockLLMClient().get_health_status()["tiers"]["vision"]["status"] == "operational"`. Required for test scaffolding that constructs `MockLLMClient` to satisfy vision-path code.

### Fallback chain isolation (1 test)

15. **`test_vision_tier_not_in_fallback_chain`** — Construct client with all four tiers configured. Trigger a `complete(request_with_tier="standard")` where standard fails. The fallback chain must NOT touch the vision tier. Capture which tiers were attempted; assert `"vision"` is absent from the list.

### Other suite updates

- `tests/test_ad730_agent_chat_vision.py` — any test that asserts on the current "Try again in a moment" stub is updated to assert on `VISION_UNCONFIGURED_MESSAGE` or `VISION_UNHEALTHY_MESSAGE`. Tier-routing tests stay green (the agent-side branch is unchanged when vision IS healthy).
- `tests/test_ad731_attachment_ref_wire_format.py` — VERIFY only. Should be green without edits.

### Test gates

After Section 1 (config): run `pytest tests/test_ad732_vision_tier.py tests/test_config*.py -q`.
After Section 2 (llm_client tier infra): run `pytest tests/test_ad732_vision_tier.py tests/test_llm*.py -q`.
After Section 3 (honest degrade): full vision suite green.

Final gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`. The 4 documented HEAD-flake tests (test_callsign_routing × 3, test_ad719_chat_fanout × 1) are the expected baseline.

---

## Section 5 — Documentation

- **`DECISIONS.md`** — Append AD-732 closure block. Cite: (a) the Copilot proxy investigation (links to https://github.com/gratajik/vscode-copilot-proxy and the README's Limitations section), (b) the three-shape probe results from 2026-05-11, (c) the architectural separation Captain ruling: provider-agnostic bus (AD-731) + vendor adaptation (BF-268) + endpoint selection per tier (AD-732). Reference the user-memory lesson "Don't change the architecture to fix a symptom" — AD-732 is the right outcome of that lesson applied at the endpoint layer (don't fork the wire format; fork the endpoint).
- **`PROGRESS.md`** — Wave 153 entry. AD-732 shipped. Test count delta (+14 net). Highest AD now AD-732.
- **`docs/development/roadmap.md`** — Mark AD-732 shipped. Add forward markers:
  - **AD-732a** — Per-agent vision tier override (`agent.vision_tier` config — when a hypothetical Imaging Officer wants a different model than the rest of the crew).
  - **AD-732b** — Vision tier autodetect on startup (probe localhost:11434 and auto-uncomment llava if available — "zero-config OSS magic").
  - **AD-732c** — Vision tier hot-reload on config change (operator edits system.yaml, vision tier reloads without restart).
- **`.github/copilot-instructions.md`** — Add the new bullet under "Common Review Flags" (text above in Section 0).

---

## Engineering Principles compliance

- **Single Responsibility**: AD-732 changes endpoint resolution. AD-731 owns the bus shape. BF-268 owns vendor adaptation. Three concerns, three sites.
- **Open/Closed**: Adding the fourth tier extends `tier_config` and `_LLM_TIERS` via public mechanisms; no existing tier-handling code is patched in place beyond the tuple replacement.
- **Dependency Inversion**: No new concretions. The LLM client still depends on `httpx.AsyncClient`; the new tier just adds a new entry to `_clients`.
- **Fail Fast / Log-and-Degrade**: Unconfigured vision → log INFO and degrade with a remediation message. Unhealthy vision → log WARNING and degrade. Neither raises into the LLM call.
- **Cloud-Ready Storage**: Unaffected — AttachmentStore Protocol seam unchanged.
- **DRY**: Eliminates 11+ hardcoded tier tuples by introducing `_LLM_TIERS`.
- **Type annotations**: All new fields are properly typed. The new helper has a full signature.
- **Logging quality**: Each degrade log line includes what was requested, what was missing, and what to do (the remediation message itself is in the response).
- **Async hygiene**: No new tasks.

---

## Out of scope (explicit Do-Not-Build list)

- **No per-agent vision tier overrides** (AD-732a forward marker).
- **No autodetection of local Ollama on startup** (AD-732b forward marker).
- **No hot-reload of vision tier config** (AD-732c forward marker).
- **No vision tier participation in the existing `_TIER_ORDER` fallback chain.** That chain is for text completions; vision deliberately does not join.
- **No changes to AD-731's `attachment_ref` shape.** The bus is unchanged.
- **No changes to BF-268's `image_url` adaptation.** The vendor boundary shape is unchanged.
- **No changes to the federation strip.** Cross-mesh attachment distribution is still AD-731a's problem.
- **No `image_generation` capability for agents.** Agents replying with images is AD-730-3.
- **No HXI UI changes.** The HXI keeps uploading via `/api/chat/attachments/multipart` and sending `attachment_ids` exactly as today.
- **No multi-image DMs in v1.** AD-730-2 forward marker stays open.
- **No fallback to a different vision endpoint when the primary fails.** If `llm_base_url_vision` is down, the honest-degrade message fires. Operator deploys redundancy at the endpoint layer (e.g., LiteLLM router) if they need it. This is not a wire-shape concern; it's an operator deployment concern.

---

## Acceptance criteria

- ✅ `CognitiveConfig` exposes vision-tier fields with the same shape as fast/standard/deep.
- ✅ `tier_config("vision")` returns a fully-resolved dict.
- ✅ `AttachmentsConfig().vision_tier == "vision"` by default; validator allows `"vision"`.
- ✅ `OpenAICompatibleClient` tracks vision in all per-tier state dicts (failures, successes, request_timestamps, etc.) via `_LLM_TIERS`.
- ✅ Vision tier does NOT appear in `_TIER_ORDER`.
- ✅ `check_connectivity()["vision"]` is computed without an HTTP call when vision is unconfigured.
- ✅ Both `/api/chat` and `/api/agent/{id}/chat` return the operator-facing `VISION_UNCONFIGURED_MESSAGE` when an image attachment is sent and vision is unconfigured. No LLM call. No intent dispatch.
- ✅ Both endpoints return `VISION_UNHEALTHY_MESSAGE` when vision is configured but unreachable.
- ✅ Text-only DMs are bit-for-bit unaffected by AD-732.
- ✅ `config/system.yaml` ships a documented (commented-out) vision tier example block with the llava recommendation.
- ✅ All pre-existing tests green: `pytest tests/ -q -n 4 --dist=loadfile` minus the 4 documented HEAD-flakes.
- ✅ Manual smoke test (operator-side, post-merge): `ollama pull llava:34b`, uncomment the vision block in `config/system.yaml`, restart HXI, paperclip-upload a cat image, DM Ezri. Expected: a real visual description of the cat (colors, shapes, content).
- ✅ Manual smoke test (degrade): with vision still commented out, DM Ezri with the same image. Expected: the `VISION_UNCONFIGURED_MESSAGE` text appears as Ezri's "reply" (technically from the OS, not the agent — that's the design).
- ✅ `DECISIONS.md` AD-732 entry includes the Copilot proxy investigation findings and the three-layer separation (bus + vendor + endpoint).
- ✅ Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Builder notes

- **Pre-flight already done by Architect (2026-05-11):** the 11+ tier-tuple sites are verified at HEAD; the `_TIER_ORDER` fallback site at line ~483 is verified to be intentionally separate; `AttachmentsConfig.vision_tier` default and validator are verified at config.py lines 1099+1107; `tier_config()` map dicts at lines 234-258 are verified.
- **Commit shape:** one commit per Section (Sections 1-3 + tests + docs). Use the AD-732 prefix on every commit. Final commit message body must include `Closes #640`. **Do NOT push** — Architect validates first.
- **If you discover a Section is no-op at HEAD**, mark the Section's commit as `verify-only: <reason>` and move on. Do not invent work.
- **If a SEARCH block does not match HEAD, STOP and report.** Do not silently work around it.
- **The honest-degrade messages are user-facing.** Read them out loud once before shipping — if they sound condescending, robotic, or unclear, flag it for Architect revision.
