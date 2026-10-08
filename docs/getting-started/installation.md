# Installation

The [Quickstart](../quickstart.md) is the shortest path; an automated test runs it from `probos setup` on.
This page covers the uv workflow, the web interface, configuration choices and the LLM options.

## Requirements

- Python 3.12+ and git
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Room for the dependencies: the core install includes PyTorch, ChromaDB and sentence-transformers
- Node.js 20+ to build the HXI web interface or run the desktop host (optional)

## Install

```bash
# Clone the repository
git clone https://github.com/seangalliher/ProbOS.git
cd ProbOS

# Install dependencies into .venv (includes the dev tools)
uv sync
```

With pip instead, create and activate a virtual environment and run `pip install -e .` (add `".[dev]"` for the test tools). Optional extras: `discord`, `slack`, `copilot`, `browser`, `discovery` and `crew-tools`, for example `pip install -e ".[discord,browser]"`.

## Launch

```bash
uv run probos setup     # configure an LLM provider (see below)
uv run probos doctor    # check the installation
uv run probos           # start the interactive shell
```

### The HXI

The HXI (Human Experience Interface) is a React + Three.js web interface served by the API server. Build it once, then start the server:

```bash
cd ui && npm install && npm run build && cd ..
uv run probos serve     # API + HXI at http://127.0.0.1:18900
```

`probos serve` accepts `--host`, `--port`, `--interactive` (also run the shell) and `--discord` (also start the Discord adapter). The [desktop tray host](desktop.md) wraps the same interface.

## Which Configuration Loads

`probos` and `probos serve` load, in order of preference:

1. the file given with `--config PATH`;
2. `~/.probos/config.yaml`, which `probos setup` creates;
3. the checkout's `config/system.yaml`.

`probos setup` writes a minimal file. Settings it does not list take their built-in defaults, which leave several subsystems off — among them the Ward Room, proactive crew cognition, the agentic loop and its tools, and code execution. `config/system.yaml` is the full reference configuration with those subsystems on: start ProbOS with `--config config/system.yaml`, or run setup with that flag to edit it in place (do not commit it with a key).

!!! note "NATS"
    The reference configuration uses a local [NATS](https://nats.io/) server with JetStream at `nats://localhost:4222`. The shell and `probos serve` start `nats-server` automatically when it is on your `PATH` or in the checkout's `tools/` directory. Otherwise install it, or set `PROBOS_NATS_ENABLED=false`. The file `probos setup` writes leaves NATS off.

## LLM Backend

ProbOS connects to OpenAI-compatible LLM endpoints. Three text tiers (fast/standard/deep) carry per-tier temperature and top-p tuning; optional vision, vision-fast, computer-use and image-generation tiers have their own models. The setup command configures the three text tiers at once: it asks for a provider and model, and for an API key when the provider needs one, checks them against the provider before it writes, and never prints the key itself. Provider error excerpts appear only for errors other than a rejected key, with the key's literal, percent-encoded and base64 forms redacted; a provider can still echo it in another form.

```bash
uv run probos setup

# Or without prompts, reading the key from an environment variable:
uv run probos setup --provider openrouter --api-key-env OPENROUTER_API_KEY --model <model-id> --yes
```

Then check what setup wrote. Doctor reports whether each tier's provider answers with that key
and model, and exits non-zero while any check fails:

```bash
uv run probos doctor
```

| Option | Setup |
|--------|-------|
| **No LLM (default)** | Works out of the box — falls back to a built-in `MockLLMClient` with regex pattern matching. Good for exploring the architecture and running tests. |
| **Ollama (local)** | Install [Ollama](https://ollama.com/), pull a model (`ollama pull qwen3.5:35b`), then run setup with `--provider ollama`. It uses Ollama's OpenAI-compatible API at `http://localhost:11434/v1` and, when it asks for a model, suggests the models Ollama lists. |
| **OpenAI, OpenRouter or another OpenAI-compatible API** | Run setup with `--provider openai`, `--provider openrouter`, or `--provider custom --base-url <url>`, and give the key with `--api-key-env <VARIABLE>` or at the hidden prompt. |
| **Copilot Proxy** | Use a VS Code Copilot proxy extension at `127.0.0.1:8080` to route through GitHub Copilot's multi-model backend. Setup with `--provider copilot-proxy` writes the shipped model names. |

Setup writes `~/.probos/config.yaml`, which `probos` and `probos serve` load in preference to the repository's `config/system.yaml`. In a source checkout, adding `--config config/system.yaml` makes setup edit that file instead; do not commit it with a key. Setup configures only the fast, standard and deep tiers. While an optional tier such as vision has a model but no `llm_base_url_<tier>` of its own, it uses the shared `llm_base_url`, so setup leaves that URL unchanged and names the tier.

!!! tip "No LLM required for testing"
    The mock client handles all standard operations, so you can explore ProbOS without setting up a local LLM. The test suite needs no LLM.

## Run Tests

```bash
# A focused run
uv run pytest tests/test_trust.py -q

# The full Python suite (~40,000 tests, parallel through pytest-xdist; takes a while)
uv run pytest tests/ -q

# HXI and desktop host tests (Vitest), from the repository root
npm --prefix ui test
npm --prefix desktop test
```
