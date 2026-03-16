# Knowledge Layer

The Knowledge layer provides persistent storage with semantic search — agents retain what they learn across sessions.

## Git-Backed Store

Artifacts are stored in a Git-backed repository:

- **Versioned**: Every change is a commit — full history with rollback
- **Per-artifact rollback**: Revert a single artifact without affecting others
- **Warm boot**: On startup, the system loads its last known state

## Semantic Knowledge Layer

Five ChromaDB collections provide vector-similarity search across different knowledge types:

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
| `knowledge/store.py` | Git-backed artifact persistence |
| `knowledge/semantic.py` | SemanticKnowledgeLayer (5 ChromaDB collections) |
