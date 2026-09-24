# ProbOS Quickstart -- 5 Minutes to First Conversation

This guide gets you from zero to talking with the ship's crew in five minutes.

## Prerequisites

- Python 3.12+
- ~500MB disk space
- One LLM endpoint: OpenAI, OpenRouter, a local Ollama, the GitHub Copilot proxy, or any OpenAI-compatible server

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
