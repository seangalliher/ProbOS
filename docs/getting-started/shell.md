# Interactive Shell

ProbOS provides a Rich-powered interactive shell with natural language input and 42 slash commands.

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
| `/ping` | Show system uptime |
| `/scaling` | Show pool scaling status |
| `/federation` | Show federation status |
| `/peers` | Show peer node models |
| `/credentials` | Show agent credentials and DIDs |
| `/debug` | Toggle debug mode |
| `/help` | All available commands |

### Memory & Learning

| Command | Description |
|---------|-------------|
| `/memory` | Working memory snapshot |
| `/history` | Recent episodic memory entries |
| `/recall <query>` | Search episodic memory |
| `/dream now` | Force a dream consolidation cycle |

### Knowledge & Search

| Command | Description |
|---------|-------------|
| `/knowledge` | Show knowledge store status |
| `/search <query>` | Search across all knowledge |
| `/rollback` | Rollback a knowledge artifact |
| `/anomalies` | Show emergent behavior detection |
| `/scout <query>` | Deploy Scout for research |

### Directives & Orders

| Command | Description |
|---------|-------------|
| `/orders` | Show Standing Orders hierarchy |
| `/order <agent> <directive>` | Issue a directive to an agent |
| `/directives` | List active directives |
| `/revoke <id>` | Revoke a directive |
| `/amend <id>` | Amend a directive |
| `/imports` | Manage allowed imports |

### Plan & Approval

| Command | Description |
|---------|-------------|
| `/plan` | View proposed DAG before execution |
| `/approve` | Approve a proposed DAG |
| `/reject` | Reject a proposed DAG |
| `/feedback` | Rate last execution |
| `/correct` | Correct the last execution |

### Procedures & Qualifications

| Command | Description |
|---------|-------------|
| `/procedure` | View compiled procedures |
| `/gap` | Show detected skill gaps |
| `/qualify` | Run qualification tests |

### Autonomous Operations

| Command | Description |
|---------|-------------|
| `/conn` | Toggle autonomous mode (CONN) |
| `/night-orders` | Set night orders for autonomous operation |
| `/watch` | Show current watch section |

### LLM & Model Management

| Command | Description |
|---------|-------------|
| `/models` | Show all available models across all sources |
| `/registry` | Show model registry |
| `/tier fast\|standard\|deep` | Switch LLM tier |

### Introspection & Monitoring

| Command | Description |
|---------|-------------|
| `/weights` | Hebbian connection weights |
| `/gossip` | Show gossip protocol view |
| `/designed` | Show self-designed agent status |
| `/qa` | Show QA status for designed agents |
| `/prune` | Permanently remove an agent |
| `/log` | Show recent event log entries |
| `/attention` | Task priority queue + focus history |
| `/cache` | Workflow cache contents |
