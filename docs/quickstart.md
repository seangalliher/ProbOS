# ProbOS Quickstart -- Install to First Conversation

**Status: Beta.** An automated test (`tests/test_ad1137_quickstart_chain.py`)
runs `probos setup`, `probos doctor` and a first conversation end to end, through
the real CLI and against a local stand-in for a model provider. It starts from an
installed checkout: the install step is not part of the test, because installing
downloads the dependencies. The rest of ProbOS is Alpha.

## Prerequisites

- Python 3.12 or newer, and git
- One LLM endpoint: OpenAI, OpenRouter, a local Ollama, the GitHub Copilot proxy, or any OpenAI-compatible server
- Room for the dependencies: the core install includes PyTorch, ChromaDB and sentence-transformers

## Install

ProbOS is not on PyPI yet (the release is tracked in issue #1053), so install it
from source into a virtual environment:

```bash
git clone https://github.com/seangalliher/ProbOS.git
cd ProbOS
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e .
```

## Configure your model

```bash
probos setup
```

ProbOS detects a local Ollama or Copilot proxy, then asks for a provider and
model, and for an API key when the provider needs one. It checks them against
the provider before writing `~/.probos/config.yaml`, and never prints the key
itself: provider error excerpts have its literal, percent-encoded and base64
forms redacted, though a provider can still echo it in another form.
`probos init` still creates a base config without a provider check.

## Diagnostic check

```bash
probos doctor
```

This checks the Python version, the config file `probos` would load (and that it
loads), the data directory, that each LLM tier's provider answers with your key
and model, and which optional extras are installed, then NATS (if enabled),
ChromaDB and the other subsystems. Each failed check (`✗`) names its fix, and
doctor exits non-zero while any check fails; a `⚠` is not a failure. To check a
different config file, run `probos doctor --config PATH`.

## First conversation

```bash
probos
```

You will land in the interactive shell. Try:

```
> What can you do?
```

The Ship's Computer will respond. Try a slash command:

```
> /agents
```

This lists the registered crew. Each agent represents a domain capability.
`/quit` leaves the shell. If the shell reports that no LLM endpoint is reachable
and falls back to the mock client, run `probos doctor` again.

## Next

- [Getting Started](getting-started.md) -- what ProbOS is and how it differs.
- [Architecture Overview](architecture/overview.md) -- the layered design.
- [Agent Concepts](agents/concepts.md) -- how the crew works.
