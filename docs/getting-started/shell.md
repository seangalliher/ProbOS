# Interactive Shell

ProbOS provides a Rich-powered interactive shell with natural-language input, 1:1 sessions with crew members, and 61 slash commands. Start it with `probos` (or `uv run probos` in a uv checkout); `probos serve --interactive` runs it alongside the API server and HXI.

The prompt shows the crew count and overall health:

```
[15 crew | health: 0.95] probos>
```

## Natural Language

Just type what you want — the Ship's Computer decomposes your request into an intent DAG and executes it:

```
probos> read /tmp/test.txt                   # File read
probos> list the files in /home/user/docs    # Directory listing
probos> write hello to /tmp/out.txt          # Consensus-gated write
probos> search for *.py in /home/user        # Recursive file search
probos> what just happened?                  # Introspection
probos> why did you use file_reader?         # Self-explanation
probos> how healthy is the system?           # System health assessment
```

## Talking to the Crew

Start a message with `@` and a crew member's callsign to open a 1:1 session with that agent. The prompt changes to the agent's callsign, every following line goes to it, and another leading `@callsign` switches sessions. `/bridge` returns to the bridge.

```
probos> @Worf any security concerns this watch?
Worf ▸ what changed since yesterday?
Worf ▸ /bridge
probos>
```

Callsigns are chosen by the agents themselves at commissioning, so they differ from ship to ship; `/manifest` lists the crew aboard. An `@callsign` in the middle of a sentence is treated as a mention, not a session switch.

## Slash Commands

`/help` lists every command with a one-line summary.

### Status and Crew

| Command | Description |
|---------|-------------|
| `/status` | System status overview |
| `/readiness` | Ship readiness report |
| `/agents` | All agents with trust scores |
| `/manifest` | Crew manifest: `/manifest [<dept>] [watch:<name>]` or `/manifest --ship` |
| `/ping` | System uptime |
| `/scaling` | Pool scaling status |
| `/credentials` | Registered credentials and their status |
| `/insights` | Recent-activity summary: `/insights [--days N]` (default 7) |
| `/debug` | Toggle debug mode: `/debug on\|off` |
| `/help` | All available commands |
| `/quit` | Exit ProbOS |

### Memory and Knowledge

| Command | Description |
|---------|-------------|
| `/memory` | Working memory snapshot |
| `/history` | Recent episodic memory entries |
| `/recall <query>` | Semantic recall from episodic memory |
| `/dream` | Last dream report; `/dream now` triggers a cycle |
| `/knowledge` | Knowledge store status and history |
| `/search` | Search across all knowledge: `/search [--type agents,skills] <query>` |
| `/rollback` | Roll back a knowledge artifact: `/rollback <type> <id>` |
| `/anomalies` | Emergent behavior detection and system anomalies |
| `/scout` | Run a scout intelligence scan; `/scout report` shows the report |

### Plans and Feedback

| Command | Description |
|---------|-------------|
| `/plan` | Propose a plan before executing it: `/plan <text>`, `/plan remove N`, `/plan` |
| `/approve` | Execute the pending proposal |
| `/reject` | Discard the pending proposal |
| `/feedback` | Rate the last execution: `/feedback good\|bad` |
| `/correct` | Correct the last execution: `/correct <what to fix>` |
| `/explain` | Explain what happened in the last natural-language request |

### Orders and Authority

| Command | Description |
|---------|-------------|
| `/orders` | Standing Orders hierarchy and summaries |
| `/order` | Issue a directive: `/order <agent_type> <text>` |
| `/directives` | Active directives: `/directives [agent_type]` |
| `/amend` | Amend a directive: `/amend <id> <new text>` |
| `/revoke` | Revoke a directive: `/revoke <id>` |
| `/imports` | Manage allowed imports: `/imports`, `/imports add <pkg>`, `/imports remove <pkg>` |
| `/conn` | Delegate the conn: `/conn <callsign>`, `/conn return`, `/conn status`, `/conn log` |
| `/night-orders` | Guidance while the Captain is away: `/night-orders <template> [ttl_hours]`, `expire`, `status` |
| `/watch` | Watch bill status |
| `/alert` | Bridge alert suppression: dismiss, resolve, mute, unmute, list |
| `/grant` | Clearance grants: issue, revoke, list |
| `/tool-access` | Tool permissions: grant, restrict, revoke, break-lock, list, check |

### Learning and Skills

| Command | Description |
|---------|-------------|
| `/procedure` | Procedure governance: list-pending, approve, reject, list-promoted |
| `/gap` | Capability gap reports: list, detail, check, summary |
| `/qualify` | Qualification tests: `/qualify [run\|status\|agent <id>\|baselines]` |
| `/skill` | Cognitive skills: list, discover, import, info, enrich, remove |
| `/designed` | Self-designed agent status |
| `/qa` | QA status for designed agents: `/qa [agent_type]` |
| `/prune` | Permanently remove an agent: `/prune <agent_id>` |

### Mesh Introspection

| Command | Description |
|---------|-------------|
| `/weights` | Hebbian connection weights |
| `/gossip` | Gossip protocol view |
| `/attention` | Attention queue and current focus |
| `/cache` | Workflow cache entries |
| `/log` | Recent event log entries: `/log [category]` |
| `/federation` | Federation status |
| `/peers` | Peer node models |

### LLM and Models

| Command | Description |
|---------|-------------|
| `/models` | Active LLM tier configuration: endpoints, models, status |
| `/registry` | All available models across tiers, the Copilot SDK and local providers |
| `/tier` | Switch LLM tier: `/tier fast\|standard\|deep` |

### Health and Diagnostics

| Command | Description |
|---------|-------------|
| `/clinical` | Clinical telemetry — dreams, traces, circuit breakers, audit (Captain authority) |
| `/diagnostic` | Multi-level system diagnostic: `/diagnostic [<level>] [<focus>]` |

### Scheduling and Voice

| Command | Description |
|---------|-------------|
| `/remind` | One-shot reminder from natural language: `/remind <when> <what>` |
| `/schedule` | Schedule from natural language: `/schedule <NL>`, `list`, `cancel <id>` |
| `/wake-word` | Custom wake-word trainer: status, collect, train, test |

### Sessions

| Command | Description |
|---------|-------------|
| `/bridge` | Return to the bridge from a 1:1 crew session |
