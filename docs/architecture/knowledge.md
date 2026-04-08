# Knowledge Layer

The Knowledge layer provides persistent storage across three tiers, each serving a different cognitive function.

## Three Knowledge Tiers

| Tier | System | Purpose |
|------|--------|---------|
| **Tier 1: Experience** | Episodic Memory | Raw episodes from agent interactions, anchored with provenance metadata |
| **Tier 2: Records** | Ship's Records | Consolidated knowledge — agent notebooks, duty logs, Captain's Log |
| **Tier 3: Operational State** | KnowledgeStore | System state persistence — trust snapshots, routing weights, agent source code |

!!! note "KnowledgeStore is operational state, not shared knowledge"
    Despite its name, KnowledgeStore stores system operational state (trust snapshots, routing weights, agent source code), not shared knowledge. Ship's Records is the actual shared knowledge fabric where agents write and read knowledge.

## Ship's Records

Git-backed instance knowledge store (AD-434). Three components:

- **Agent Notebooks** — each crew agent maintains a personal notebook for observations, analysis, and insights. Read-before-write deduplication prevents repetitive entries. Dream consolidation merges and refines entries.
- **Duty Logs** — operational records of agent activities and system events.
- **Captain's Log** — human-authored entries for strategic decisions and directives.

### Notebook Quality Pipeline (AD-550-555)

Six-stage pipeline ensuring notebook quality:

1. **Dedup / Read-Before-Write** (AD-550) — agents check existing entries before writing
2. **Dream Consolidation** (AD-551) — Step 7g merges scattered entries, detects cross-agent convergence
3. **Self-Repetition Detection** (AD-552) — extends peer repetition detection to knowledge layer
4. **Quantitative Baseline** (AD-553) — automatic quality metrics capture
5. **Convergence Detection** (AD-554) — detects when agents from different departments independently reach the same conclusion
6. **Quality Metrics Dashboard** (AD-555) — tracks lexical diversity, redundancy rate, entry length trends

## KnowledgeStore (Operational State)

Git-backed persistence for system operational state:

- **Versioned**: Every change is a commit — full history with rollback
- **Per-artifact rollback**: Revert a single artifact without affecting others
- **Warm boot**: On startup, the system loads its last known state

## Semantic Knowledge Layer

ChromaDB collections provide vector-similarity search across different knowledge types:

| Collection | Purpose |
|-----------|---------|
| Agent designs | Self-designed agent blueprints |
| Skills | Learned skill templates |
| Episodes | Episodic memory entries |
| Context | Working memory snapshots |
| Artifacts | General knowledge artifacts |

## Source Files

| File | Purpose |
|------|---------|
| `knowledge/store.py` | Git-backed operational state persistence |
| `knowledge/semantic.py` | SemanticKnowledgeLayer (ChromaDB collections) |
| `ships_records/notebooks.py` | Agent notebook management |
| `ships_records/duty_log.py` | Duty log entries |
| `ships_records/captains_log.py` | Captain's Log |
