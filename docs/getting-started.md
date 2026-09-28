# Getting Started with ProbOS

## What ProbOS Is

ProbOS is a probabilistic agent-native OS runtime -- a coordinated mesh of
domain agents that handle natural-language work via consensus voting,
Bayesian trust, and Hebbian-learned routing.

Unlike a single-agent assistant, ProbOS:

- **Decomposes** your request into a directed-acyclic graph of typed intents.
- **Routes** each intent to the agent best suited to handle it (learned weights).
- **Gates** destructive operations behind multi-agent consensus voting.
- **Records** every step in episodic memory for replay and continuous learning.

## Why It's Different

- **Agent-native**: every component is an autonomous agent. There is no central
  scheduler. Agents self-organize via capability matching.
- **Probabilistic consensus**: destructive ops require multi-agent quorum
  voting with confidence weighting and Shapley attribution.
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
