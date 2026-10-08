# Getting Started with ProbOS

## What ProbOS Is

ProbOS is a probabilistic agent-native OS runtime -- a coordinated mesh of
domain agents that handle natural-language work via consensus voting,
Bayesian trust, and Hebbian-learned routing.

Unlike a single-agent assistant, ProbOS:

- **Decomposes** your request into a directed-acyclic graph of typed intents.
- **Routes** each intent to the agent best suited to handle it (learned weights).
- **Governs** consequential operations through multi-agent consensus voting and
  the Captain's approval; each intent declares whether its vote authorizes the
  act beforehand or scores it afterwards.
- **Records** every step in episodic memory for replay and continuous learning.

## Why It's Different

- **Agent-native**: every component is an autonomous agent. No central planner
  decides which agent thinks about what — agents self-organize via capability
  matching and learned routing — while deterministic services guarantee durable
  workflow steps such as recovery and exactly-once delivery.
- **Probabilistic consensus**: consequential operations go to a multi-agent
  quorum vote with confidence weighting and Shapley attribution, and each
  intent declares whether its vote authorizes the act or scores it afterwards.
- **Bayesian trust**: each agent carries a Beta(alpha, beta) reputation that
  the runtime updates after every interaction.
- **Self-modification**: capability gaps trigger LLM-based agent design,
  static analysis, and probationary trust before promotion.

## Where Things Live

- `~/.probos/config.yaml` -- your runtime configuration, written by `probos setup`.
  Without it, a source checkout's `config/system.yaml` is used.
- The data directory -- episodic memory, trust DB, and runtime state:
  `~/AppData/Local/ProbOS/data` on Windows, `~/Library/Application Support/ProbOS/data`
  on macOS, and `$XDG_DATA_HOME/ProbOS/data` (by default `~/.local/share/ProbOS/data`)
  elsewhere. `probos --data-dir DIR` uses another one.
- `~/.probos/knowledge/` -- the agent's knowledge repository.

`probos doctor` prints the config file and data directory it checked.

## Next

- [Quickstart](quickstart.md) -- 5-minute install + first conversation.
- [Architecture Overview](architecture/overview.md) -- the layered design.
- [Agent Concepts](agents/concepts.md) -- how the crew works.
