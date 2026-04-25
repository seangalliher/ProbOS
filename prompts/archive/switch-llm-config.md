# Switch LLM Config — All Tiers to Copilot Proxy (Sonnet + Opus)

## Change

Switch from Ollama (fast tier) + Copilot proxy (standard/deep) to ALL tiers on Copilot proxy. Removes Ollama dependency for normal operation.

## Config update

**File:** `config/system.yaml`

Update the cognitive section:

```yaml
cognitive:
  llm_base_url: "http://127.0.0.1:8080/v1"
  llm_model: "claude-sonnet-4-20250514"
  llm_api_key: ""
  llm_timeout_seconds: 30
  default_llm_tier: "fast"

  # ── Fast tier ──
  # Current: Sonnet via Copilot proxy
  llm_base_url_fast: "http://127.0.0.1:8080/v1"
  llm_model_fast: "claude-sonnet-4-20250514"
  llm_api_key_fast: ""
  llm_timeout_fast: 30
  llm_api_format_fast: "openai"
  # To switch back to Ollama, uncomment below and comment out the lines above:
  # llm_base_url_fast: "http://127.0.0.1:11434"
  # llm_model_fast: "qwen3.5:35b"
  # llm_api_key_fast: ""
  # llm_timeout_fast: 30
  # llm_api_format_fast: "ollama"

  # ── Standard tier ──
  llm_base_url_standard: "http://127.0.0.1:8080/v1"
  llm_model_standard: "claude-sonnet-4-20250514"
  llm_api_key_standard: ""
  llm_timeout_standard: 30

  # ── Deep tier ──
  llm_base_url_deep: "http://127.0.0.1:8080/v1"
  llm_model_deep: "claude-opus-4-20250514"
  llm_api_key_deep: ""
  llm_timeout_deep: 60
```

Key changes:
- `llm_base_url_fast` changed from `http://127.0.0.1:11434` (Ollama) to `http://127.0.0.1:8080/v1` (Copilot proxy)
- `llm_model_fast` changed from `qwen3.5:35b` to `claude-sonnet-4-20250514`
- `llm_api_format_fast` changed from `"ollama"` to `"openai"` (Copilot proxy uses OpenAI-compatible API)
- `llm_timeout_fast` changed from 30 to 30 (no change, but verify)

## Also update `__main__.py` if it has Ollama auto-start logic

**File:** `src/probos/__main__.py`

If there's code that auto-starts Ollama on boot, make it conditional — don't fail or warn if Ollama isn't running when all tiers point to the Copilot proxy. The boot sequence should check connectivity per-tier and only warn for tiers that are unreachable.

## Also update node configs

**Files:** `config/node-1.yaml`, `config/node-2.yaml`

Same changes — all tiers to Copilot proxy. These are used for federation testing.

## After change

1. Restart `probos serve` (or `python -m probos`)
2. Type `/model` — should show all three tiers pointing to Copilot proxy with Sonnet/Opus models
3. Test: "hello" — should respond quickly via Sonnet
4. Test: "what time is it?" — should work (Sonnet decomposes faster than qwen)
5. Run tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q` — MockLLMClient is unaffected by config changes
