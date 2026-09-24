# Installation

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended package manager)

## Install

```bash
# Clone the repository
git clone https://github.com/seangalliher/ProbOS.git
cd ProbOS

# Install dependencies
uv sync
```

## Launch

```bash
# Start the interactive shell
uv run python -m probos

# Or run the visual demo
uv run python demo.py
```

## LLM Backend

ProbOS connects to an OpenAI-compatible LLM endpoint. Three tiers (fast/standard/deep) with per-tier temperature and top-p tuning. The setup command configures all three at once: it asks for a provider and model, and for an API key when the provider needs one, checks them against the provider before it writes, and never prints the key itself. Provider error excerpts appear only for errors other than a rejected key, with the key's literal, percent-encoded and base64 forms redacted; a provider can still echo it in another form.

```bash
uv run python -m probos setup

# Or without prompts, reading the key from an environment variable:
uv run python -m probos setup --provider openrouter --api-key-env OPENROUTER_API_KEY --model <model-id> --yes
```

| Option | Setup |
|--------|-------|
| **No LLM (default)** | Works out of the box — falls back to a built-in `MockLLMClient` with regex pattern matching. Good for exploring the architecture and running tests. |
| **Ollama (local)** | Install [Ollama](https://ollama.com/), pull a model (`ollama pull qwen3.5:35b`), then run setup with `--provider ollama`. It uses Ollama's OpenAI-compatible API at `http://localhost:11434/v1` and, when it asks for a model, suggests the models Ollama lists. |
| **OpenAI, OpenRouter or another OpenAI-compatible API** | Run setup with `--provider openai`, `--provider openrouter`, or `--provider custom --base-url <url>`, and give the key with `--api-key-env <VARIABLE>` or at the hidden prompt. |
| **Copilot Proxy** | Use a VS Code Copilot proxy extension at `127.0.0.1:8080` to route through GitHub Copilot's multi-model backend. Setup with `--provider copilot-proxy` writes the shipped model names. |

Setup writes `~/.probos/config.yaml`, which `probos` and `probos serve` load in preference to the repository's `config/system.yaml`. In a source checkout, adding `--config config/system.yaml` makes setup edit that file instead; do not commit it with a key. Setup configures only the fast, standard and deep tiers. While an optional tier such as vision has a model but no `llm_base_url_<tier>` of its own, it uses the shared `llm_base_url`, so setup leaves that URL unchanged and names the tier.

!!! tip "No LLM required for testing"
    The mock client handles all standard operations, so you can explore ProbOS without setting up a local LLM. The full test suite (2502 pytest + 34 vitest = 2536 tests) runs entirely on the mock client.

## Run Tests

```bash
# Python tests (2502 tests)
uv run pytest tests/ -v

# UI tests (34 Vitest tests)
cd ui && npx vitest run
```
