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

## LLM Configuration

ProbOS connects to an OpenAI-compatible LLM endpoint at `http://127.0.0.1:8080/v1` (configurable in `config/system.yaml`).

If the endpoint is unavailable, it falls back to a built-in `MockLLMClient` with regex pattern matching for deterministic operation without any external dependencies.

!!! tip "No LLM required for testing"
    The mock client handles all standard operations, so you can explore ProbOS without setting up a local LLM. The full test suite (1605 tests) runs entirely on the mock client.

## Run Tests

```bash
# Python tests (1590 tests)
uv run pytest tests/ -v

# UI tests (15 Vitest tests)
cd ui && npx vitest run
```
