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

ProbOS connects to an OpenAI-compatible LLM endpoint (configurable in `config/system.yaml`). Three options:

| Option | Setup |
|--------|-------|
| **No LLM (default)** | Works out of the box — falls back to a built-in `MockLLMClient` with regex pattern matching. Good for exploring the architecture and running tests. |
| **Ollama (local)** | Install [Ollama](https://ollama.com/), pull a model (`ollama pull qwen3.5:35b`), update `config/system.yaml` endpoints to `http://127.0.0.1:11434`. |
| **OpenAI-compatible API** | Point `llm_base_url` in `config/system.yaml` to any OpenAI-compatible endpoint and set your API key. |

!!! tip "No LLM required for testing"
    The mock client handles all standard operations, so you can explore ProbOS without setting up a local LLM. The full test suite (1605 tests) runs entirely on the mock client.

## Run Tests

```bash
# Python tests (1590 tests)
uv run pytest tests/ -v

# UI tests (15 Vitest tests)
cd ui && npx vitest run
```
