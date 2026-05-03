# ProbOS Quickstart -- 5 Minutes to First Conversation

This guide gets you from zero to talking with the ship's crew in five minutes.

## Prerequisites

- Python 3.12+
- ~500MB disk space
- One LLM endpoint (one of: local Ollama, GitHub Copilot proxy, Anthropic API key)

## Install

```bash
pip install probos
```

Or from source:

```bash
git clone https://github.com/seangalliher/ProbOS.git
cd ProbOS
pip install -e .
```

## Initialize

```bash
probos init
```

ProbOS will detect available LLM providers and prompt you for an endpoint and
model. The defaults are sensible.

## Diagnostic check

```bash
probos doctor
```

This reports config, data-dir writability, LLM reachability, NATS (if enabled),
and ChromaDB. Resolve any red `x` marks before continuing.

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

## Next

- [Getting Started](getting-started.md) -- what ProbOS is and how it differs.
- [Architecture Overview](architecture/overview.md) -- the layered design.
- [Agent Concepts](agents/concepts.md) -- how the crew works.
