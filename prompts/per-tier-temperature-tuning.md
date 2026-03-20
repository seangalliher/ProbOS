# Build Prompt: Per-Tier Temperature & Top-P Tuning (AD-358)

## Context

ProbOS routes LLM requests through 3 tiers (fast, standard, deep), each with
per-tier endpoint, model, timeout, and API format config. However, **temperature
and top_p are not configurable per tier** — temperature is hardcoded on each
`LLMRequest` call site (mostly 0.0), and top_p is not supported at all.

Research from Kimi K2.5 (Moonshot AI) shows that different cognitive modes
benefit from different generation temperatures: deep reasoning benefits from
higher temperature (diversity of thought), while fast classification benefits
from lower temperature (deterministic, consistent). ProbOS should support this.

**Goal:** Add per-tier `temperature` and `top_p` configuration that serves as
the default for each tier, while still allowing individual `LLMRequest` callers
to override when needed.

---

## Issue 1: Add Per-Tier Fields to CognitiveConfig

**File:** `src/probos/config.py`

Add 6 new optional fields to `CognitiveConfig`, following the existing per-tier
override pattern (e.g., `llm_timeout_fast`, `llm_base_url_standard`):

```python
# Per-tier sampling overrides (None = use request-level value)
llm_temperature_fast: float | None = None
llm_temperature_standard: float | None = None
llm_temperature_deep: float | None = None

llm_top_p_fast: float | None = None
llm_top_p_standard: float | None = None
llm_top_p_deep: float | None = None
```

Place these **after** the existing `llm_api_format_deep` field (line 72) and
**before** the `default_llm_tier` field (line 74).

Update `tier_config()` to include the new fields in the returned dict:

```python
temp_map = {
    "fast": self.llm_temperature_fast,
    "standard": self.llm_temperature_standard,
    "deep": self.llm_temperature_deep,
}
top_p_map = {
    "fast": self.llm_top_p_fast,
    "standard": self.llm_top_p_standard,
    "deep": self.llm_top_p_deep,
}
```

Add to the returned dict:
```python
"temperature": temp_map.get(tier),   # None = use request default
"top_p": top_p_map.get(tier),        # None = don't send
```

Note: these return `None` when not configured (not a fallback value). The LLM
client will use them as defaults only when the caller hasn't specified a value.

---

## Issue 2: Add top_p to LLMRequest

**File:** `src/probos/types.py`

Add a `top_p` field to the `LLMRequest` dataclass:

```python
@dataclass
class LLMRequest:
    """A request to the LLM client."""

    prompt: str
    system_prompt: str = ""
    tier: str = "standard"  # LLMTier value
    temperature: float = 0.0
    top_p: float | None = None   # <-- ADD THIS LINE
    max_tokens: int = 2048
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
```

`top_p` defaults to `None` (meaning "don't send to API unless tier config
specifies it").

---

## Issue 3: Wire Tier Defaults into LLM Client

**File:** `src/probos/cognitive/llm_client.py`

### 3a. Apply tier defaults in `complete()`

In the `complete()` method, after resolving the tier config (around line 214),
apply tier-level temperature/top_p defaults to the request **only if the caller
hasn't set a non-default value**:

```python
tc = self._tier_configs.get(attempt_tier, self._tier_configs["standard"])

# Apply tier-level sampling defaults (caller override wins)
effective_temp = request.temperature
if effective_temp == 0.0 and tc.get("temperature") is not None:
    effective_temp = tc["temperature"]

effective_top_p = request.top_p
if effective_top_p is None and tc.get("top_p") is not None:
    effective_top_p = tc["top_p"]
```

Then pass `effective_temp` and `effective_top_p` to `_call_api()`. Add these
as new keyword parameters on `_call_api()`:

```python
async def _call_api(
    self, request: LLMRequest, model: str, client: httpx.AsyncClient,
    *, api_format: str = "openai", timeout: float = 30.0,
    effective_temp: float = 0.0, effective_top_p: float | None = None,
) -> LLMResponse:
```

### 3b. Use effective values in `_call_openai()`

Pass `effective_temp` and `effective_top_p` through from `_call_api()` to
`_call_openai()` as keyword parameters. Update the OpenAI payload:

```python
payload = {
    "model": model,
    "messages": messages,
    "temperature": effective_temp,     # was request.temperature
    "max_tokens": request.max_tokens,
}
if effective_top_p is not None:
    payload["top_p"] = effective_top_p
```

### 3c. Use effective values in `_call_ollama_native()`

Same pattern — pass through and use:

```python
if effective_temp is not None:
    payload.setdefault("options", {})["temperature"] = effective_temp
if effective_top_p is not None:
    payload.setdefault("options", {})["top_p"] = effective_top_p
```

Replace the existing `request.temperature` reference (line 352-353) with the
`effective_temp` parameter.

### 3d. Update `tier_info()` to include sampling params

Add temperature and top_p to the tier_info output so `/models` and `/registry`
can display them:

```python
info[tier] = {
    "base_url": tc["base_url"],
    "model": tc["model"],
    "timeout": tc["timeout"],
    "api_format": tc.get("api_format", "openai"),
    "reachable": self._tier_status.get(tier),
    "temperature": tc.get("temperature"),    # ADD
    "top_p": tc.get("top_p"),                # ADD
}
```

---

## Issue 4: Add Config to system.yaml

**File:** `config/system.yaml`

Add commented-out temperature/top_p lines under the `cognitive:` section, after
the existing per-tier blocks. Use comments to explain the intent:

```yaml
  # Per-tier sampling parameters (uncomment to override request defaults)
  # Deep tier: higher temperature for reasoning diversity
  # llm_temperature_deep: 0.7
  # llm_top_p_deep: 0.95
  #
  # Standard tier: moderate temperature
  # llm_temperature_standard: 0.3
  #
  # Fast tier: low temperature for deterministic classification
  # llm_temperature_fast: 0.0
```

Place this after the `llm_timeout_deep: 300` line (around line 54) and before
any non-LLM cognitive config.

---

## Test Requirements

### New Tests (add to `tests/test_per_tier_llm.py`)

1. **`test_tier_config_returns_temperature_when_set`** — Set
   `llm_temperature_deep=0.7`, verify `tier_config("deep")["temperature"]` is
   `0.7` and `tier_config("fast")["temperature"]` is `None`.

2. **`test_tier_config_returns_top_p_when_set`** — Set `llm_top_p_deep=0.95`,
   verify `tier_config("deep")["top_p"]` is `0.95` and
   `tier_config("fast")["top_p"]` is `None`.

3. **`test_tier_defaults_not_set_returns_none`** — Default `CognitiveConfig()`
   returns `None` for temperature and top_p in all tiers.

4. **`test_tier_info_includes_sampling_params`** — Create an
   `OpenAICompatibleClient` with `llm_temperature_fast=0.1`, verify
   `tier_info()["fast"]["temperature"]` is `0.1`.

5. **`test_llm_request_top_p_field`** — Verify `LLMRequest` accepts `top_p`
   parameter and defaults to `None`.

### Existing Tests

6. Verify all existing `test_per_tier_llm.py` tests still pass unchanged.

7. Verify all existing `test_llm_client.py` tests still pass unchanged.

---

## Files to Modify

- `src/probos/config.py` — Issue 1 (CognitiveConfig fields + tier_config)
- `src/probos/types.py` — Issue 2 (LLMRequest.top_p)
- `src/probos/cognitive/llm_client.py` — Issue 3 (complete, _call_api, _call_openai, _call_ollama_native, tier_info)
- `config/system.yaml` — Issue 4 (commented-out config lines)
- `tests/test_per_tier_llm.py` — Tests 1-5

## Constraints

- Do NOT modify any other files
- Do NOT change existing caller temperature values (builder.py, decomposer.py, etc.)
- Do NOT add shared/fallback temperature defaults — per-tier only, `None` when not set
- Request-level values ALWAYS override tier defaults (caller wins)
- `top_p` is only sent to the API when explicitly set (not sent as 0.0 or 1.0 default)
- Keep the existing `request.temperature` default of 0.0 in LLMRequest
- Temperature override logic: if `request.temperature == 0.0` (the default) AND tier config has a temperature, use the tier config value. If the caller explicitly set temperature to any value (including 0.0 for deterministic), it should be honored — but since we can't distinguish "caller set 0.0" from "default 0.0", the tier config will override 0.0. This is the desired behavior: tier defaults replace the hardcoded 0.0 pattern.
