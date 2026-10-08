# ProbOS

**Probabilistic agent-native OS runtime** — an operating system kernel where every component is an autonomous agent, coordination happens through consensus, and the system learns from its own behavior. The agents are organized as the crew of a starship: departments, ranks, a chain of command, standing orders, and a human Captain.

> *"What if an OS didn't execute instructions — it negotiated them?"*

**[Documentation](https://probos.dev)** · **[Quickstart](docs/quickstart.md)** · **[Roadmap](docs/development/roadmap.md)** · **[Nooplex Readiness](docs/development/nooplex-readiness.md)** · **[Discord](https://discord.gg/cbprTVfsjt)**

> **Alpha** — ProbOS is under active development. APIs will change, features may break, and documentation may lag behind the code. The getting-started path is **Beta**: an automated test runs the [quickstart](docs/quickstart.md)'s `probos setup`, `probos doctor` and first conversation end to end; the install step is not part of the test. Contributions and feedback welcome.

**Nooplex readiness:** ProbOS currently implements an alpha, single-mesh Cognitive Mesh with an experimental federation substrate. A dependable supported mesh, authenticated multi-mesh operation, the Nooplex Core Fabric, and emergence validation are separate evidence gates tracked in the [Nooplex Readiness Map](docs/development/nooplex-readiness.md).

## What Is This?

ProbOS reimagines the OS as a mesh of probabilistic agents rather than deterministic processes. Instead of syscalls, you speak natural language. Instead of a central scheduler, agents select their own work through capability matching, Hebbian-learned routing and Bayesian trust. Instead of permissions alone, consequential actions are governed by multi-agent consensus, chain-of-command approval and an audit trail.

The agents are persistent. A ProbOS vessel keeps running when you step away: its crew remembers, talks in the Ward Room, consolidates what it learned while idle ("dreaming"), and continues durable work within the authority you delegate. The design goal is that a governed crew agent reaches the same productive ceiling as a foreground coding agent — governance is what buys the autonomy to act unattended, not a tax on capability.

<img width="1911" height="1042" alt="The ProbOS HXI showing the cognitive mesh canvas" src="https://github.com/user-attachments/assets/bb4a20d1-bd63-4f0a-a3bb-9fcf48605173" />

**See it in action:** [ProbOS: An AI Operating System That Builds Its Own Agents (Live Demo)](https://youtu.be/0cFoQ3QOmh0) — recorded March 2026; the interface has grown since.

## What ProbOS Does Today

- **A crew, not a pipeline.** Fifteen sovereign crew agents serve across six departments — Bridge, Engineering, Science, Medical, Security and Operations — each with a `did:probos` identity and birth certificate, a Big Five personality seed, episodic memory, a trust record and a rank. Crew agents choose their own callsigns at commissioning. A Yeoman serves as the Captain's personal assistant.
- **Agentic work with governed tools.** In 1:1 conversations and dispatched work items, crew agents work through a multi-turn agentic loop bounded by step, cost and trust limits, with a shared tool registry: capability search, task delegation, work-item tools, MCP servers with per-agent and per-tool authorization, governed Python execution in per-agent workspaces, and a browser tool. Word, PowerPoint and Excel document agents serve the whole mesh.
- **Consensus, trust and learned routing.** Bayesian Beta(α, β) trust per agent, Hebbian intent-to-agent routing, and confidence-weighted quorum voting with red-team verification and Shapley attribution. Each consensus intent declares what its vote buys: file writes and MCP tool calls commit only on approval, code builds wait for the Captain, and intents that cannot observe without acting (shell commands, Python execution, package installs) run first and are scored afterwards — the runtime lists those at startup.
- **Durable, approvable work.** Work items agents can discover and claim, crew sessions with recovery and verified finalization, persistent tasks, an approvals center on the Bridge, delegated approvals with decision pre-clearance, and Night Orders and the conn for operating while the Captain is away.
- **Memory that consolidates.** ChromaDB-backed episodic memory with anchored provenance, Ship's Records (Git-backed notebooks, duty logs and the Captain's Log), a vessel ontology and knowledge graph, and a multi-stage dream cycle that replays and prunes, recalibrates trust, extracts procedures and decays unreinforced memories while the system is idle.
- **Learning loops.** Human corrections patch the responsible agent and retry. Repeated successful work compiles into procedures that replay without an LLM call and fall back to it on failure (Cognitive JIT). Capability gaps can start the self-modification pipeline: design → static validation → sandbox → probationary trust → QA → behavioral monitoring.
- **Identity and federation (experimental).** Agents and ships carry W3C-style DID identities, birth certificates and a hash-chained identity ledger. Ship-level Ed25519 key binding, signed federation envelopes and authenticated peer admission have been proven between two separately started nodes. Federation — including an A2A adapter and agentic resource discovery (ARD) catalogs — is off by default and is not yet a supported multi-mesh.
- **Beyond the terminal.** The HXI is a React + Three.js bridge: the cognitive mesh canvas, crew chat, the Ward Room, approvals, embedded workstations (browser and code), voice and avatars. An Electron tray host wraps it on the desktop, and channel adapters connect Discord, Slack, Telegram, Matrix, Microsoft Teams, Gmail and webhooks, with DM pairing.
- **Operator tooling.** `probos setup` (provider wizard), `probos doctor` (diagnostics), `probos verify-snapshot` and `probos backup-reclaim` (backups), tiered `probos reset`, `probos migrate` (import from OpenClaw or Hermes Agent) and `probos rebuild-episodic`.

## Design Philosophy

Traditional operating systems use rigid, deterministic mechanisms: syscalls, schedulers, ACLs. ProbOS replaces each with a probabilistic, self-organizing equivalent:

| Traditional OS | ProbOS Equivalent |
|---------------|-------------------|
| Syscalls | Natural language decomposed into intent DAGs |
| Process scheduler | Attention-based priority scoring with Hebbian learning |
| File permissions / ACLs | Multi-agent consensus, earned trust and chain-of-command approval |
| Process table | Agent registry with health monitoring and auto-recycling |
| IPC | Pub/sub intent bus with concurrent fan-out; the Ward Room between crew |
| Cron / scheduled tasks | Dreaming engine — offline consolidation during idle periods |
| Command history | Episodic memory with semantic recall |
| Shell aliases | Workflow cache and compiled procedures — learned shortcuts for repeated patterns |

Every agent maintains a confidence score and trust reputation. The system doesn't just execute operations — it *deliberates*, *verifies*, and *learns*.

## Architecture

Five layers, each built on the one below, plus cross-cutting services:

> See [docs/architecture/self-perception-framing.md](docs/architecture/self-perception-framing.md) for the public-framing paragraph on AD-722e self-perception (denser self-state injection, not consciousness).

```
┌──────────────────────────────────────────────────────────────┐
│  Experience   Interactive shell · HXI (React + Three.js) ·   │
│               FastAPI + WebSocket API · desktop tray host ·  │
│               channel adapters                               │
├──────────────────────────────────────────────────────────────┤
│  Cognitive    Decomposer + DAG executor · CognitiveAgent ·   │
│               agentic loop + tool layer · standing orders ·  │
│               working/episodic memory · attention ·          │
│               dreaming · procedures · self-modification      │
├──────────────────────────────────────────────────────────────┤
│  Consensus    Quorum voting · Bayesian trust · red team ·    │
│               Shapley attribution · escalation · dampening   │
├──────────────────────────────────────────────────────────────┤
│  Mesh         Intent bus · Hebbian routing · capability      │
│               registry · gossip · signals · Ward Room        │
├──────────────────────────────────────────────────────────────┤
│  Substrate    Agent lifecycle · pools · pool groups ·        │
│               spawner · registry · heartbeat · event log     │
├──────────────────────────────────────────────────────────────┤
│  Cross-cutting                                               │
│   Knowledge   Ship's Records · KnowledgeStore · ChromaDB ·   │
│               vessel ontology · knowledge graph              │
│   Identity    did:probos · birth certificates · ledger ·     │
│               Ed25519 key binding                            │
│   Security    Egress/SSRF policy · tool permissions ·        │
│               approvals · audit log                          │
│   Federation  NATS or ZeroMQ transport · signed envelopes ·  │
│               peer admission · A2A · ARD (experimental)      │
└──────────────────────────────────────────────────────────────┘
```

- **Substrate.** Agents follow a `perceive → decide → act → report` lifecycle. A spawner creates them from templates, resource pools keep target sizes and recycle degraded agents, pool groups organize pools into departments, and a heartbeat monitors liveness. Lifecycle events go to an append-only SQLite event log.
- **Mesh.** An intent bus fans out to every subscriber and agents self-select through `perceive()`. A Hebbian router learns which agents handle which intents best, a capability registry does fuzzy matching, and gossip spreads state. The Ward Room carries threaded channel and direct-message traffic between crew members and the Captain.
- **Consensus.** Quorum voting is confidence-weighted, trust is a Beta distribution per agent, red-team agents independently verify results, Shapley values attribute credit, and dampening keeps a trust failure from cascading through the network.
- **Cognitive.** The Ship's Computer decomposes natural language into a DAG of typed intents and executes it. The decomposer's prompt is **self-assembling**: each agent class declares `IntentDescriptor` metadata, so a new agent type makes its intents available without editing any prompt or routing table. Crew agents are instructions-first `CognitiveAgent`s whose standing orders are composed into every LLM call.
- **Experience.** A Rich-powered shell, the HXI, a REST + WebSocket API, the desktop host and external channels.

**Hybrid coordination.** Agents decide *what* to work on and *how*: intent routing, capability matching, Hebbian pairings, proactive attention and claiming published work. Deterministic services own durable workflow time where the requirement is a guarantee rather than a judgement — admission and concurrency bounds, compare-and-set state transitions, crash recovery, exactly-once delivery, cancellation. There is no central planner deciding which agent thinks about what.

**Composable cognition.** A crew agent is an organism: a cognitive spine plus organs such as attention and dreaming, which are child components of the agent rather than mesh peers. The migration to this model is incremental and behavior-preserving; see [Composable Cognition](docs/development/composable-cognition.md).

## The Crew

The vessel ontology ([`config/ontology/organization.yaml`](config/ontology/organization.yaml)) defines departments, posts and the chain of command. The Captain is you; everyone else is an agent.

| Department | Posts (seed callsign) |
|------------|-----------------------|
| **Bridge** | Captain (human) · First Officer — Architect (*Number One*, also Chief Science Officer) · Ship's Counselor (*Troi*) · Ship's Yeoman (*Yeo*) |
| **Engineering** | Chief Engineer (*LaForge*) · Builder (*Forge*) |
| **Science** | Scout (*Wesley*) · Data Analyst (*Rahda*) · Systems Analyst (*Dax*) · Research Specialist (*Brahms*) |
| **Medical** | Chief Medical Officer — Diagnostician (*Bones*) · Surgeon (*Pulaski*) · Pharmacist (*Ogawa*) · Pathologist (*Selar*) |
| **Security** | Chief of Security (*Worf*) |
| **Operations** | Chief of Operations (*O'Brien*) · Training Officer (*Tucker*) |

Seed callsigns are defaults: on a vessel's first boot each crew agent takes part in a naming ceremony and may choose its own name, so callsigns differ from ship to ship. Rank is earned — Ensign, Lieutenant, Commander, Senior — and gates how freely an agent acts and how deeply it recalls.

Beneath the crew, the Ship's Computer runs agents without sovereign identity: infrastructure agents (file, directory, search, code search, shell, HTTP fetch, introspection, red team, vitals, QA, engineering and operations monitors, office documents, consensus proposers) and ten bundled utility agents (web search, page reader, weather, news, translator, summarizer, calculator, todo, notes, scheduler). With the shipped [`config/system.yaml`](config/system.yaml), a boot spawns 81 agents in 51 pools; smaller configurations spawn fewer. See the [Agent Inventory](https://probos.dev/agents/inventory/).

## Quick Start

New to ProbOS? The [quickstart](docs/quickstart.md) goes from install to a first conversation; an automated test runs it from `probos setup` on.

**Requirements:** Python 3.12+, git, and room for the dependencies (the core install includes PyTorch, ChromaDB and sentence-transformers). An LLM endpoint is optional to start — see below.

```bash
git clone https://github.com/seangalliher/ProbOS.git
cd ProbOS
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e .             # or with uv: `uv sync`, then prefix each command with `uv run`

probos setup                 # choose a provider and model; writes ~/.probos/config.yaml
probos doctor                # check the config, data directory, LLM tiers and subsystems
probos                       # the interactive shell; try: What can you do?
```

**The HXI.** The web interface is served by the API server once it has been built (Node.js 20+):

```bash
cd ui && npm install && npm run build && cd ..
probos serve                 # API + HXI at http://127.0.0.1:18900
```

`probos serve --interactive` also runs the shell, and `--discord` starts the Discord adapter. The Electron tray host in [`desktop/`](desktop/) wraps the HXI; see [ProbOS Desktop](docs/getting-started/desktop.md).

**Which configuration loads.** `probos` and `probos serve` load `--config PATH` when given, else `~/.probos/config.yaml`, else the checkout's [`config/system.yaml`](config/system.yaml). `probos setup` writes a minimal file; anything it does not list uses built-in defaults, which leave several subsystems off — among them the Ward Room, proactive crew cognition, the agentic loop and its tools, and code execution. `config/system.yaml` is the full reference configuration with those on: start ProbOS with `--config config/system.yaml`, or run setup with that flag to edit it in place (do not commit it with a key). The reference configuration expects a local NATS server with JetStream; the shell and `probos serve` start `nats-server` when it is on your `PATH` or in `tools/`, and otherwise you can install it or set `PROBOS_NATS_ENABLED=false`.

### LLM Backend

ProbOS connects to OpenAI-compatible LLM endpoints through three text tiers — fast, standard and deep — plus optional vision, computer-use and image-generation tiers. `probos setup` asks for a provider, model and (when needed) API key, checks them against the provider, and writes `~/.probos/config.yaml`, which ProbOS loads in preference to `config/system.yaml`; in a source checkout, `--config config/system.yaml` edits that file instead (do not commit it with a key). Then `probos doctor` checks that each tier's provider answers with that key and model.

| Option | Setup |
|--------|-------|
| **No LLM (default)** | Works out of the box — falls back to a built-in `MockLLMClient` with regex pattern matching. Good for exploring the architecture and running tests. |
| **Ollama (local)** | Install [Ollama](https://ollama.com/), pull a model (`ollama pull qwen3.5:35b`), then run setup with `--provider ollama`. |
| **OpenAI, OpenRouter or another OpenAI-compatible API** | Run setup with `--provider openai`, `openrouter` or `custom --base-url <url>`; without prompts: `--provider openrouter --api-key-env OPENROUTER_API_KEY --model <model-id> --yes`. |
| **Copilot Proxy** | Run setup with `--provider copilot-proxy` to use a VS Code Copilot proxy extension at `127.0.0.1:8080`. |

## Interactive Shell

```
probos> read pyproject.toml and summarize it      # natural language → intent DAG
probos> write hello to /tmp/out.txt               # consensus-gated write
probos> what just happened?                       # introspection
probos> why did you use file_reader?              # self-explanation
probos> @<callsign> how is your department?       # 1:1 session with a crew member
probos> /bridge                                   # return from the 1:1 session
```

The shell has 61 slash commands (`/help` lists them all):

| Area | Commands |
|------|----------|
| Status and crew | `/status` `/readiness` `/agents` `/manifest` `/ping` `/scaling` `/credentials` `/insights` `/debug` `/help` `/quit` |
| Memory and knowledge | `/memory` `/history` `/recall` `/dream` `/knowledge` `/search` `/rollback` `/anomalies` `/scout` |
| Plans and feedback | `/plan` `/approve` `/reject` `/feedback` `/correct` `/explain` |
| Orders and authority | `/orders` `/order` `/directives` `/amend` `/revoke` `/imports` `/conn` `/night-orders` `/watch` `/alert` `/grant` `/tool-access` |
| Learning and skills | `/procedure` `/gap` `/qualify` `/skill` `/designed` `/qa` `/prune` |
| Mesh introspection | `/weights` `/gossip` `/attention` `/cache` `/log` `/federation` `/peers` |
| Models | `/models` `/registry` `/tier` |
| Health and diagnostics | `/clinical` `/diagnostic` |
| Scheduling and voice | `/remind` `/schedule` `/wake-word` |
| Sessions | `/bridge` |

See the [shell guide](https://probos.dev/getting-started/shell/) for what each command does.

## How It Works

When you give the Ship's Computer a natural-language request:

1. **Working memory** assembles system state (agent health, trust scores, Hebbian weights, capabilities) within a token budget
2. **Episodic recall** surfaces similar past interactions as context
3. **Workflow cache** checks for previously successful DAG patterns (exact match, then fuzzy with pre-warm intents)
4. **LLM decomposer** converts text into a `TaskDAG` — a directed acyclic graph of typed intents with dependencies
5. **Attention manager** scores tasks: `urgency × relevance × deadline_factor × dependency_bonus`
6. **DAG executor** runs independent intents in parallel, respects dependency ordering
7. **Consensus** sends intents that require it to a quorum vote with red-team verification
8. **Reflection** (optional) sends execution results back to the LLM for synthesis
9. **Hebbian router** strengthens successful agent-intent pairings, weakens failures
10. **Episodic memory** stores the interaction for future recall
11. **Workflow cache** stores successful patterns to bypass the LLM on repeat queries
12. **Dreaming engine** consolidates learning during idle periods — replays episodes, prunes weak connections, adjusts trust scores, pre-warms likely upcoming intents

Conversations with crew members — 1:1 sessions, Ward Room threads and HXI chat — run through each agent's own cognitive cycle: standing orders composed into its instructions and recall from its own memory. 1:1 replies and dispatched work items can also use the agentic tool loop. Their outcomes feed the same trust, Hebbian and episodic learning loops.

## Configuration

| Where | What |
|-------|------|
| [`config/system.yaml`](config/system.yaml) | The reference configuration — 180+ sections covering pools, mesh, consensus, cognitive tiers, memory, dreaming, the Ward Room, the agentic loop, tools, security and federation |
| [Configuration reference](docs/development/config-reference.md) | Generated reference for every section and field, with defaults |
| [`config/standing_orders/`](config/standing_orders/) | The crew's constitution — Federation, Ship, Department and Agent standing orders — and crew profiles |
| [`config/ontology/`](config/ontology/) | The vessel ontology: departments, posts, chain of command and assignments |

Every setting is a Pydantic model with a default, so a short file is a complete configuration. Runtime state lives in a platform data directory (`%LOCALAPPDATA%\ProbOS\data` on Windows, `~/Library/Application Support/ProbOS/data` on macOS, `$XDG_DATA_HOME/ProbOS/data` elsewhere), or wherever `--data-dir` points. `probos doctor` prints the config file and data directory it checked.

## Project Structure

```
ProbOS/
├── src/probos/          # The runtime (~990 Python modules)
│   ├── __main__.py      #   The `probos` CLI: shell, serve, setup, doctor, reset, …
│   ├── runtime.py       #   Top-level orchestrator
│   ├── startup/         #   Boot phases: agent fleet, fleet organization, finalize, …
│   ├── substrate/       #   BaseAgent, pools, spawner, registry, heartbeat, event log
│   ├── mesh/            #   Intent bus, Hebbian routing, capability registry, gossip
│   ├── consensus/       #   Quorum voting, Bayesian trust, Shapley attribution, escalation
│   ├── cognitive/       #   CognitiveAgent, decomposer, memory, dreaming, procedures,
│   │                    #   agentic dispatch, crew orchestration, self-modification
│   ├── agents/          #   Infrastructure, utility and department agents
│   ├── tools/           #   Tool registry, code execution, browser, delegation, work items
│   ├── ward_room/       #   Agent communication fabric: channels, threads, messages
│   ├── knowledge/       #   Ship's Records, KnowledgeStore, semantic layer, knowledge edges
│   ├── ontology/        #   Vessel ontology, departments, billets
│   ├── security/        #   Egress and URL guards, permissions, sandboxes, audit
│   ├── federation/      #   Transports, bridge and router, signed envelopes, admission, A2A, ARD
│   ├── integrations/    #   MCP bridge, Microsoft 365
│   ├── channels/        #   Discord, Slack, Telegram, Matrix, Teams, Gmail, webhooks
│   ├── routers/         #   FastAPI routers behind `probos serve`
│   ├── experience/      #   Shell, slash commands, renderer, panels
│   └── …                #   doctor, voice, avatars, perception, holodeck, workstations, …
├── ui/                  # HXI — React 19, Three.js, Zustand, Vite
├── desktop/             # Electron tray host for the HXI
├── config/              # system.yaml, standing orders, ontology, skills, manuals
├── docs/                # probos.dev sources (MkDocs Material)
├── tests/               # pytest suite
└── scripts/             # Test gate, AD ledger and CI helpers
```

## Tests

As of October 2026 the Python suite collects 39,700+ tests, and the HXI and desktop host have Vitest suites (357 and 10 test files).

```bash
uv run pytest tests/test_trust.py -q    # a focused run
uv run pytest tests/ -q                 # the full suite, parallel through pytest-xdist; takes a while
npm --prefix ui test                    # HXI tests (Vitest)
npm --prefix desktop test               # desktop host tests (Vitest)
```

See [Contributing](docs/development/contributing.md) for testing standards and the review workflow.

## Status and Roadmap

ProbOS development began in March 2026 and proceeds one numbered architecture decision (AD) or bug fix (BF) at a time — AD numbers have passed 1,300 — recorded in [DECISIONS.md](DECISIONS.md) and [PROGRESS.md](PROGRESS.md):

| Era | Highlights |
|-----|------------|
| I — Genesis | Substrate, mesh, consensus, cognitive core, shell, federation transport |
| II — Emergence | Self-modification, skills, LLM tiers, dreaming, persistent knowledge, Shapley trust |
| III — Product | HXI, Discord adapter, bundled agents, medical and science teams |
| IV — Evolution | Standing orders, Ward Room, sovereign DID identity, ontology, Cognitive JIT, self-regulation, emergence metrics |
| V — Unification | Knowledge graph, brain-enhancement work, commercial-overlay seam |
| VI — Commercial Bridge (May 2026) | Extension-point registry, NATS cognitive-chain pipeline, contagion firewall, voice substrate |

Since June 2026 the work has run as programs: the agentic loop and governed tools (MCP, code execution, browser), durable crew execution and approvals, composable cognition, `probos setup` / `probos doctor` onboarding, authenticated two-node federation (AD-1196–1198), and the [AD-1270 Platform Maturity Program](docs/development/platform-maturity-program.md).

**Current priorities** (from the [roadmap](docs/development/roadmap.md), 2026-09-07):

1. **Finish the dependable mesh** — AD-1270 / [#1324](https://github.com/seangalliher/ProbOS/issues/1324): exercised capabilities, robust seams, modular owners, fast gates and truthful docs.
2. **Measure benefit as paths become ready** — the Sigma ablation ([#1064](https://github.com/seangalliher/ProbOS/issues/1064)) and Ship Trials ([#1123](https://github.com/seangalliher/ProbOS/issues/1123)).
3. **Bring human contribution and independent adoption forward** — typed human claims ([#1136](https://github.com/seangalliher/ProbOS/issues/1136)) and a PyPI release ([#1053](https://github.com/seangalliher/ProbOS/issues/1053)).
4. **Authenticate before wider federation** — fleet policy ([#479](https://github.com/seangalliher/ProbOS/issues/479)) follows the two-node authentication now in place.
5. **Keep extensions tied to outcomes** — elastic-team trials ([#1337](https://github.com/seangalliher/ProbOS/issues/1337)) and governed self-maintenance ([#1352](https://github.com/seangalliher/ProbOS/issues/1352)).

**Readiness against the Nooplex architecture** ([readiness map](docs/development/nooplex-readiness.md)):

| Tier | Name | Status | Permitted claim |
|------|------|--------|-----------------|
| A | Dependable Cognitive Mesh | `planned` | "ProbOS is an alpha implementation of a governed Cognitive Mesh." |
| B | Secure Multi-Mesh | `planned` | "ProbOS has an experimental federation transport." |
| C | Nooplex Core Fabric | `not-started` | "ProbOS provides local foundations for a future Nooplex Core." |
| D | Emergence Research | `research` | "ProbOS is an experimental platform for testing the Nooplex hypothesis." |

## Dependencies

Python 3.12+; the full list is in [pyproject.toml](pyproject.toml).

| Area | Packages |
|------|----------|
| Runtime and configuration | pydantic, pyyaml, python-dotenv, rich, croniter, tzdata |
| Storage and memory | aiosqlite, chromadb, sentence-transformers, torch |
| API and networking | fastapi, uvicorn, python-multipart, httpx, nats-py, pyzmq, jsonschema |
| Identity and credentials | cryptography, keyring, msal |
| Documents and data for agents | pypdf, python-docx, python-pptx, openpyxl, reportlab, matplotlib, pillow, numpy, pandas, beautifulsoup4, lxml, tabulate, requests |
| Perception | facenet-pytorch |

Optional extras: `dev`, `discord`, `slack`, `copilot` (GitHub Copilot SDK), `browser` (Playwright), `discovery` (zeroconf), and `crew-tools` (more document and data libraries for sandboxed code) — for example `pip install -e ".[discord,browser]"`. The HXI is built with React 19, Three.js, Zustand and Vite; the desktop host with Electron.

## Contributing and Community

Read [Contributing](docs/development/contributing.md) for the engineering principles, testing standards and review workflow, and join the [Discord](https://discord.gg/cbprTVfsjt). Bugs and proposals go to [GitHub Issues](https://github.com/seangalliher/ProbOS/issues).

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Disclaimer

This is a personal research project. It is not affiliated with, endorsed by, or supported by my employer.
