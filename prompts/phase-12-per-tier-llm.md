# Phase 12: Per-Tier LLM Endpoints

**Goal:** Each LLM tier (fast/standard/deep) gets its own `base_url`, `api_key`, and `model` — not just a different model name on a shared endpoint. This enables mixing providers freely: a local Ollama instance for the fast tier, the VS Code Copilot proxy for standard/deep. The system checks each endpoint independently at boot and falls back gracefully when a tier's endpoint is unreachable.

**Motivation:** The user has Ollama running locally with `qwen3.5:35b`. Fast-tier calls (intent classification, simple decomposition, pre-warm hints) should hit the local model with zero latency and no proxy dependency. Standard/deep calls (complex decomposition, reflection, agent design) continue through the Copilot proxy to Claude/GPT.

---

## Context

Right now, `OpenAICompatibleClient` has:
- One shared `base_url` (from `CognitiveConfig`)
- One shared `api_key` (not currently in config — may be hardcoded or absent)
- Per-tier model names: `model_fast`, `model_standard`, `model_deep`
- One shared `httpx.AsyncClient`

All tiers hit the same endpoint. The only difference is the model name in the request body.

This phase changes `OpenAICompatibleClient` to:
- Per-tier `base_url` (with fallback to shared `base_url` for backward compat)
- Per-tier `api_key` (with fallback to shared — Ollama needs no key)
- Per-tier model names (unchanged — already exists)
- Per-tier `httpx.AsyncClient` instances (separate connection pools per endpoint)
- Per-tier connectivity checks at boot

---

## ⚠ AD Numbering

Check the latest AD number in PROGRESS.md before starting. All new architectural decisions start at the next available number.

---

## ⚠ Pre-Build Audit

**Before writing any code**, read:

1. `src/probos/config.py` — `CognitiveConfig` fields, how `SystemConfig` loads from YAML
2. `src/probos/cognitive/llm_client.py` — `OpenAICompatibleClient.__init__()`, `complete()`, `check_connectivity()`, tier routing logic, response cache, fallback chain
3. `config/system.yaml` — current cognitive section structure
4. `src/probos/__main__.py` — boot sequence, how `OpenAICompatibleClient` is constructed and connectivity is checked
5. `src/probos/experience/shell.py` — `/model` and `/tier` command implementations

Understand how the existing single-endpoint client works before modifying it. The per-tier change must be fully backward compatible — if no per-tier URLs are configured, behavior is identical to today.

---

## Deliverables

### 1. Update `CognitiveConfig` in `src/probos/config.py`

Add per-tier endpoint fields with `None` defaults (meaning "use shared endpoint"):

```python
class CognitiveConfig(BaseModel):
    # ... existing fields ...

    # Shared endpoint (existing — backward compat)
    llm_base_url: str = "http://127.0.0.1:8080/v1"
    llm_api_key: str = ""  # Empty = no auth header
    llm_timeout_seconds: float = 30.0

    # Per-tier overrides (None = fall back to shared)
    llm_base_url_fast: str | None = None
    llm_api_key_fast: str | None = None
    llm_timeout_fast: float | None = None
    model_fast: str = "gpt-4o-mini"

    llm_base_url_standard: str | None = None
    llm_api_key_standard: str | None = None
    llm_timeout_standard: float | None = None
    model_standard: str = "claude-sonnet-4.6"

    llm_base_url_deep: str | None = None
    llm_api_key_deep: str | None = None
    llm_timeout_deep: float | None = None
    model_deep: str = "claude-opus-4.6"

    # ... existing fields (max_concurrent_tasks, attention_decay_rate, etc.) ...
```

Each per-tier field falls back:
- `llm_base_url_fast` → if None, use `llm_base_url`
- `llm_api_key_fast` → if None, use `llm_api_key`
- `llm_timeout_fast` → if None, use `llm_timeout_seconds`

Add a helper method:

```python
def tier_config(self, tier: str) -> dict:
    """Return resolved endpoint config for a tier.

    Returns {"base_url": str, "api_key": str, "model": str, "timeout": float}
    with per-tier overrides applied, falling back to shared values.
    """
```

### 2. Update `config/system.yaml`

Add the per-tier fields under `cognitive:`. Example config for the user's setup:

```yaml
cognitive:
  # Shared defaults (used when per-tier not specified)
  llm_base_url: "http://127.0.0.1:8080/v1"
  llm_api_key: ""
  llm_timeout_seconds: 30

  # Fast tier: local Ollama (no auth needed)
  llm_base_url_fast: "http://127.0.0.1:11434/v1"
  llm_api_key_fast: ""
  model_fast: "qwen3.5:35b"
  llm_timeout_fast: 15

  # Standard tier: Copilot proxy (uses shared endpoint)
  model_standard: "claude-sonnet-4.6"

  # Deep tier: Copilot proxy (uses shared endpoint)
  model_deep: "claude-opus-4.6"
```

When `llm_base_url_standard` and `llm_base_url_deep` are absent, they fall back to the shared `llm_base_url`. The fast tier gets its own URL pointing to Ollama.

### 3. Update `OpenAICompatibleClient` in `src/probos/cognitive/llm_client.py`

Major changes:

```python
class OpenAICompatibleClient(BaseLLMClient):
    """Multi-endpoint OpenAI-compatible LLM client with per-tier routing.

    Each tier (fast/standard/deep) can have its own:
    - base_url (different server)
    - api_key (different auth)
    - model (different model name)
    - timeout (different latency budget)
    - httpx.AsyncClient (separate connection pool)

    When per-tier config is not specified, falls back to shared values.
    Tiers sharing the same base_url share the same httpx.AsyncClient
    (no duplicate connection pools for the same server).
    """

    def __init__(self, config: CognitiveConfig) -> None:
        self._config = config
        self._tier_configs: dict[str, dict] = {}  # tier → resolved config
        self._clients: dict[str, httpx.AsyncClient] = {}  # base_url → client (deduplicated)
        self._tier_status: dict[str, bool] = {}  # tier → connectivity status
        self.default_tier: str = "standard"

        # Resolve per-tier configs
        for tier in ("fast", "standard", "deep"):
            tc = config.tier_config(tier)
            self._tier_configs[tier] = tc
            # Create httpx client per unique base_url (deduplicate)
            if tc["base_url"] not in self._clients:
                headers = {}
                if tc["api_key"]:
                    headers["Authorization"] = f"Bearer {tc['api_key']}"
                self._clients[tc["base_url"]] = httpx.AsyncClient(
                    base_url=tc["base_url"],
                    headers=headers,
                    timeout=tc["timeout"],
                )

        # Response cache (shared across tiers)
        self._cache: dict[str, str] = {}

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Route request to the appropriate tier's endpoint.

        Fallback chain per tier:
        1. Live call to tier's endpoint
        2. Response cache (keyed by prompt hash + tier)
        3. If tier's endpoint is down, try shared endpoint (if different)
        4. Return error response
        """
        tier = request.tier or self.default_tier
        tc = self._tier_configs.get(tier, self._tier_configs["standard"])
        client = self._clients[tc["base_url"]]
        model = tc["model"]

        # ... existing request/response logic, using tier-specific client and model ...

    async def check_connectivity(self) -> dict[str, bool]:
        """Check connectivity for each tier independently.

        Returns {"fast": True/False, "standard": True/False, "deep": True/False}.
        A tier is reachable if its endpoint responds to a lightweight request
        (e.g., GET /models or a minimal completion).
        """
        results = {}
        checked_urls = {}  # base_url → result (avoid double-checking shared endpoints)
        for tier in ("fast", "standard", "deep"):
            tc = self._tier_configs[tier]
            url = tc["base_url"]
            if url in checked_urls:
                results[tier] = checked_urls[url]
            else:
                reachable = await self._check_endpoint(url, tc)
                checked_urls[url] = reachable
                results[tier] = reachable
            self._tier_status[tier] = results[tier]
        return results

    async def _check_endpoint(self, base_url: str, tier_config: dict) -> bool:
        """Check if a specific endpoint is reachable.

        Try a lightweight request. For Ollama, GET /v1/models works.
        For Copilot proxy, a minimal completion works.
        Use a short timeout (5s) for connectivity checks.
        """

    def tier_info(self) -> dict[str, dict]:
        """Return per-tier config for /model display.

        Returns {"fast": {"base_url": ..., "model": ..., "reachable": ...}, ...}
        """

    async def close(self) -> None:
        """Close all httpx clients."""
        for client in self._clients.values():
            await client.aclose()
```

**Key design constraints:**
- Clients are deduplicated by `base_url`. If standard and deep share the same URL, they share the same `httpx.AsyncClient`. This avoids unnecessary connection pools.
- Each client gets its own `Authorization` header (or none, for Ollama). Headers are set at client construction time, not per-request.
- The response cache is shared across tiers but keyed by `(prompt_hash, tier)` to avoid cross-tier cache hits.
- The existing `default_tier` and `/tier` switching mechanism is unchanged.

### 4. Update boot sequence in `__main__.py`

```python
# Current: single connectivity check
# New: per-tier connectivity check with individual status display

client = OpenAICompatibleClient(config.cognitive)
connectivity = await client.check_connectivity()

for tier, reachable in connectivity.items():
    tc = config.cognitive.tier_config(tier)
    if reachable:
        console.print(f"  ✓ LLM {tier}: {tc['model']} at {tc['base_url']}")
    else:
        console.print(f"  ✗ LLM {tier}: {tc['base_url']} unreachable")

if not any(connectivity.values()):
    console.print("[yellow]No LLM endpoints reachable — falling back to MockLLMClient[/yellow]")
    client = MockLLMClient()
elif not all(connectivity.values()):
    # Some tiers reachable, some not — warn but continue
    down_tiers = [t for t, r in connectivity.items() if not r]
    console.print(f"[yellow]Warning: {', '.join(down_tiers)} tier(s) unreachable — will use fallback[/yellow]")
```

The system boots even if some tiers are down. Only falls back to MockLLMClient if ALL tiers are unreachable.

### 5. Update `/model` command in shell

Show per-tier endpoint info:

```
LLM Configuration:
  Default tier: standard

  fast:
    Endpoint: http://127.0.0.1:11434/v1
    Model: qwen3.5:35b
    Status: ✓ connected

  standard:
    Endpoint: http://127.0.0.1:8080/v1
    Model: claude-sonnet-4.6
    Status: ✓ connected

  deep:
    Endpoint: http://127.0.0.1:8080/v1
    Model: claude-opus-4.6
    Status: ✓ connected (shared with standard)
```

When tiers share an endpoint, note it to avoid confusion.

### 6. Update `/tier` command in shell

The existing `/tier fast` command switches the default tier. Add a note showing what endpoint the new tier uses:

```
[7 agents | health: 0.80] probos> /tier fast
Switched to fast tier: qwen3.5:35b at http://127.0.0.1:11434/v1
```

### 7. Handle Ollama-specific quirks

Ollama's OpenAI-compatible endpoint has minor differences:
- No `Authorization` header needed (empty `api_key` = no header)
- Model names use Ollama tag format: `qwen3.5:35b` (colon-separated name and variant)
- The `/v1/models` endpoint returns available models — good for connectivity check
- Streaming is supported but not used by ProbOS (we use non-streaming completions)

No special-casing needed in the client — Ollama's `/v1/chat/completions` endpoint accepts the same JSON format as OpenAI. The only difference is the absence of an auth header, which is handled by the empty `api_key` field.

---

## Test Plan — ~15 new tests in `tests/test_per_tier_llm.py`

### TestCognitiveConfigTiers (5 tests)
1. Default config: all per-tier URLs are None, fall back to shared
2. Per-tier URL set: `tier_config("fast")` returns the override, not shared
3. Per-tier API key set: `tier_config("fast")` returns the override
4. Mixed: fast has override, standard/deep fall back to shared
5. `tier_config()` returns correct model name per tier

### TestOpenAICompatibleClientMultiEndpoint (5 tests)
6. Client creates separate httpx clients for different base_urls
7. Client deduplicates httpx clients for shared base_urls
8. `complete()` routes fast-tier request to fast endpoint's client
9. `complete()` routes standard-tier request to standard endpoint's client
10. `tier_info()` returns per-tier config with base_url and model

### TestConnectivityCheck (3 tests)
11. `check_connectivity()` returns per-tier status dict
12. Shared endpoint checked once, result reused for all tiers sharing it
13. Individual tier failure doesn't block other tiers

### TestBootSequence (2 tests)
14. All tiers unreachable → falls back to MockLLMClient
15. Some tiers reachable → continues with partial connectivity warning

---

## Build Order

1. **Pre-build audit**: Read `CognitiveConfig`, `OpenAICompatibleClient`, `__main__.py`, shell `/model` and `/tier` handlers.
2. **CognitiveConfig**: Add per-tier fields and `tier_config()` helper. Write tests 1–5.
3. **OpenAICompatibleClient**: Refactor to per-tier clients with deduplication. Write tests 6–10.
4. **Connectivity**: Update `check_connectivity()` to per-tier checks. Write tests 11–13.
5. **Boot sequence**: Update `__main__.py` for per-tier status display and partial connectivity. Write tests 14–15.
6. **Shell**: Update `/model` to show per-tier info. Update `/tier` to show endpoint on switch.
7. **system.yaml**: Add per-tier fields with Ollama fast tier config.
8. **PROGRESS.md**: Document changes and ADs.
9. **Final verification**: `uv run pytest tests/ -v` — all tests pass.

Run `uv run pytest tests/ -v` after each step.

---

## Architectural Decisions to Document

- **Per-tier endpoint config with shared fallback.** Each tier can override `base_url`, `api_key`, `timeout`. When not specified, falls back to the shared values. This is fully backward compatible — existing configs with only shared values work unchanged.
- **httpx client deduplication by base_url.** Tiers sharing the same endpoint share the same `httpx.AsyncClient`. This avoids duplicate connection pools and redundant connectivity checks. The deduplication is by URL string identity.
- **Per-tier connectivity at boot.** Each unique endpoint is checked independently. If Ollama is running but the Copilot proxy is down, the fast tier works while standard/deep fall back to cache or error. Only if ALL endpoints are unreachable does the system fall back to MockLLMClient.
- **Empty api_key means no Authorization header.** This handles Ollama (no auth) cleanly without a special "no auth" flag. If `api_key` is empty string or None, the `Authorization` header is omitted from the httpx client.
- **Response cache keyed by (prompt_hash, tier).** The cache is shared across tiers but tier-qualified. A cached response from the fast tier won't be served for a standard-tier request, since different models produce different outputs.

---

## Non-Goals

- **Auto-detection of local LLM servers.** The user configures endpoints explicitly in YAML. No port scanning or service discovery.
- **Model capability matching.** The system doesn't validate that a model can handle the complexity of a given request. The user decides which model serves which tier.
- **Streaming responses.** ProbOS uses non-streaming completions. Streaming support is orthogonal to per-tier endpoints.
- **Per-tier rate limiting.** All tiers share the same request patterns. Rate limiting per endpoint is a future concern.
- **Dynamic tier reassignment.** If the fast tier is down, requests don't automatically promote to standard. The fallback chain is: tier endpoint → cache → error. Automatic tier promotion would change latency characteristics unpredictably.
