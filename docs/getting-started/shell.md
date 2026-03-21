# Interactive Shell

ProbOS provides a Rich-powered interactive shell with natural language input and 36+ slash commands.

## Natural Language

Just type what you want — ProbOS decomposes your request into an intent DAG and executes it:

```
probos> read /tmp/test.txt                   # File read
probos> list the files in /home/user/docs    # Directory listing
probos> write hello to /tmp/out.txt          # Consensus-verified write
probos> search for *.py in /home/user        # Recursive file search
probos> what just happened?                  # Introspection
probos> why did you use file_reader?         # Self-explanation
probos> how healthy is the system?           # System health assessment
```

## Slash Commands

### System Status

| Command | Description |
|---------|-------------|
| `/status` | Pool health, mesh state, cognitive state |
| `/agents` | Agent table with states and trust scores |
| `/weights` | Hebbian connection weights |
| `/model` | LLM client info |
| `/models` | Show all available models across all sources |
| `/registry` | Show model registry |
| `/debug` | Toggle debug mode |
| `/ping` | Show system uptime |
| `/help` | All available commands |

### Memory & Learning

| Command | Description |
|---------|-------------|
| `/memory` | Working memory snapshot |
| `/attention` | Task priority queue + focus history |
| `/dream now` | Force a dream consolidation cycle |
| `/cache` | Workflow cache contents |
| `/history` | Recent episodic memory entries |
| `/recall <query>` | Search episodic memory |
| `/knowledge` | Show knowledge store status |
| `/search <query>` | Search across all knowledge |

### Execution Control

| Command | Description |
|---------|-------------|
| `/explain` | Explain last execution |
| `/tier fast\|standard\|deep` | Switch LLM tier |
| `/feedback` | Rate last execution |
| `/correct` | Correct the last execution |

### Self-Modification

| Command | Description |
|---------|-------------|
| `/design` | Collaboratively design a new agent |
| `/designed` | Show self-designed agent status |
| `/plan` | View proposed DAG before execution |
| `/approve` | Approve a proposed DAG |
| `/reject` | Reject a proposed DAG |
| `/qa` | Show QA status for designed agents |
| `/imports` | Manage allowed imports |
| `/prune` | Permanently remove an agent |

### Operations & Monitoring

| Command | Description |
|---------|-------------|
| `/gossip` | Show gossip protocol view |
| `/log` | Show recent event log entries |
| `/scaling` | Show pool scaling status |
| `/federation` | Show federation status |
| `/peers` | Show peer node models |
| `/anomalies` | Show emergent behavior detection |
| `/orders` | Show Standing Orders hierarchy |
