# Configuration

ProbOS is configured with YAML validated by Pydantic models. Every setting has a default, so a short file is a complete configuration.

## Which File Loads

`probos` and `probos serve` load the file given with `--config PATH`; without it, `~/.probos/config.yaml` (written by `probos setup`); without that, the checkout's [`config/system.yaml`](https://github.com/seangalliher/ProbOS/blob/main/config/system.yaml). The file that loads replaces the others rather than layering over them: anything it does not list takes its built-in default.

- **`config/system.yaml`** is the full reference configuration — 181 sections, with the Ward Room, proactive crew cognition, the agentic loop and its tools, code execution, the approvals center and NATS turned on.
- **`~/.probos/config.yaml`** from `probos setup` is minimal: the LLM tiers, self-modification, the knowledge repository, utility agents and a security profile. Subsystems whose built-in default is off stay off until you add them.

`probos doctor` prints which config file and data directory it checked. The [Configuration Reference](../development/config-reference.md) is generated from the models and lists every section and field with its default.

## Key Sections

| Section | Controls |
|---------|----------|
| `system` | Instance name, log level |
| `pools`, `scaling` | Default, minimum and maximum pool sizes, spawn cooldown, health checks, demand-based scaling |
| `mesh` | Gossip interval, Hebbian decay and reward rates |
| `consensus`, `trust_dampening` | Minimum votes, approval threshold, trust priors (Beta distribution), red-team pool size, cascade dampening |
| `cognitive` | LLM endpoints and models per tier, token budgets, timeouts |
| `memory`, `dreaming`, `knowledge`, `records` | Episodic memory, dream consolidation, the knowledge repository, Ship's Records |
| `ward_room`, `proactive_cognitive`, `earned_agency` | Crew communication, proactive crew thinking, trust-tiered autonomy |
| `agentic_loop`, `dm_agentic`, `agentic_tools`, `execution`, `browser_tool`, `mcp` | The agentic loop, its tools, code execution, the browser tool and MCP servers |
| `approval_inbox`, `persistent_tasks`, `security`, `firewall` | Approvals, durable tasks, permissions, and the communication contagion firewall |
| `nats`, `federation` | The event bus and multi-node federation |
| `channels` | Discord, Slack and webhook adapters (Telegram, Slack and Matrix also have `probos channel <name> setup`) |

```yaml
pools:
  default_pool_size: 3
  min_pool_size: 2
  max_pool_size: 7
  spawn_cooldown_ms: 500
  health_check_interval_seconds: 5.0
```

## LLM Tiers

ProbOS routes LLM calls through named tiers, each with its own endpoint, model and sampling settings:

| Tier | Use |
|------|-----|
| `fast` | Classification, gist extraction, quick routing decisions |
| `standard` | General-purpose decomposition, agent instructions |
| `deep` | Complex multi-step reasoning, code generation, architecture design |
| `vision`, `vision_fast` | Image understanding |
| `compute_use` | Computer use |
| `image_gen` | Image generation |

`probos setup` configures the fast, standard and deep text tiers; the others are optional. Switch the active text tier at runtime with `/tier fast|standard|deep`, and inspect the configuration with `/models`.

## Standing Orders

Agent behavior is governed by a four-tier instruction hierarchy stored as Markdown in [`config/standing_orders/`](https://github.com/seangalliher/ProbOS/tree/main/config/standing_orders):

| Tier | File | Scope |
|------|------|-------|
| Federation Constitution | `federation.md` | Universal, immutable |
| Ship Standing Orders | `ship.md` | Per instance |
| Department Protocols | `engineering.md`, `science.md`, `medical.md`, … | Per department |
| Agent Standing Orders | `architect.md`, `counselor.md`, `builder.md`, … | Per agent, evolvable |

`compose_instructions()` assembles them at call time and injects the result into every crew agent's LLM request. Crew personalities and seed callsigns live in `config/standing_orders/crew_profiles/`.

## Vessel Ontology

[`config/ontology/`](https://github.com/seangalliher/ProbOS/tree/main/config/ontology) defines the ship's organization: departments, posts, the chain of command, and which agent type fills each post. See the [Agent Inventory](../agents/inventory.md).

## Environment Variables

A few settings can be overridden from the environment — for example `PROBOS_NATS_ENABLED=false` runs without NATS, and `PROBOS_LLM_URL` replaces the shared LLM base URL. ProbOS also loads a `.env` file at startup; see [`.env.example`](https://github.com/seangalliher/ProbOS/blob/main/.env.example). Use `--data-dir DIR` to choose the data directory.
