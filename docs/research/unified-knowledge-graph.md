# Research: Unified Knowledge Graph for ProbOS

*Sean Galliher, 2026-05-03*
*Inspiration: Thoth (github.com/siddsachar/Thoth) triple-store pattern, Microsoft Fabric IQ capability mapping*

## Problem Statement

ProbOS has three disconnected graph structures, a six-layer memory stack, and no structural querying across them. An agent asking "what do we know about the DM loop incident?" gets vector-similar text chunks from ChromaDB — but not the structurally connected entities (which agents were involved, which BFs were filed, which decisions were made, which departments were affected). The relationships exist in the system but are not queryable as a graph.

### Current State — Three Disconnected Graphs

| Graph | Location | Nodes | Edges | Queryable? |
|-------|----------|-------|-------|------------|
| Ontology | `ontology/models.py` | Posts, Departments, Assignments | `reports_to`, `authority_over` | Yes — `DepartmentService` traversal |
| Hebbian | `ward_room_hebbian/router.py` | (topic, agent_id) pairs | Co-activation weights [0.0–1.0] | Yes — `get_weight()`, `top_contributors()` |
| Trust | `consensus/trust.py` | Agent IDs | Beta(α,β) reputation scores | Yes — `get_trust()`, TrustEvent log |

These graphs answer different questions: Who reports to whom? Who's good at what? How reliable is this agent? But none answers: What does the crew *know*, and how does that knowledge connect?

### Current State — Six-Layer Memory Stack

```
1. Global Workspace      → TaskDAG orchestration (ephemeral)
2. Working Memory        → Agent scratchpads (ephemeral)
3. Vector Store          → EpisodicMemory, SemanticKnowledgeLayer (associative)
4a. Formal Models        → Ontology, Standing Orders (constitutional)
4b. Operational Knowledge → Trust, Hebbian weights (learned)
5a. Institutional Memory → Ship's Records (persistent)
5b. Operational State    → KnowledgeStore (persistent)
6. Distributed Substrate → Instance repos, fleet remotes (federation)
```

The stack handles knowledge *lifecycle* well (ephemeral → persistent → federated). What it lacks is knowledge *structure* — typed relationships between entities across layers.

### The Gap

The "AI Meets Brain" survey (`docs/research/agent-memory-survey-absorption.md`) already identified graph-based retrieval as a gap. The survey cataloged Mem0 (26% improvement over baseline with graph-based representations) and G-Memory (three-tier hierarchical graph for multi-agent systems). ProbOS's absorption notes dismissed G-Memory as "hierarchy exists, just structured differently" — true for the tier model, but the *graph* part was the valuable contribution, not the hierarchy.

Thoth's triple-store (SQLite + NetworkX + FAISS) demonstrates the practical pattern: semantic search finds relevant text, graph expansion finds structurally connected entities. The combination is significantly richer than either alone.

## What a Unified Knowledge Graph Would Enable

### For Agents (Recall Quality)
- **Graph-enhanced recall:** "What happened with the DM loop?" → vector search finds BF-257 episode → graph expansion adds: Atlas, Sage, Lyra (involved agents), BF-163/184/187 (related BFs), routing entropy collapse (symptom), LLM capacity exhaustion (impact)
- **Structural reasoning:** Counselor can trace an agent's behavioral pattern through connected incidents, not just similar-sounding episodes
- **Cross-department knowledge:** Science findings connected to Engineering incidents connected to Medical observations — traversable in one query

### For Ship's Computer (Intelligence)
- **NL-to-graph query:** Captain asks a structural question → Ship's Computer routes to graph traversal instead of (or in addition to) vector search
- **Impact analysis:** "What would break if we changed the DM rate limiter?" → traverse dependency edges from BF-257 to connected systems
- **Anomaly detection:** Graph structure enables pattern detection that text similarity misses (e.g., an agent connected to an unusual number of incidents)

### For Federation (Provenance)
- **Knowledge lineage:** Every fact carries its derivation chain — which agent, from which duty, based on which observations, on which ship
- **Trust-weighted knowledge transfer:** When Ship A shares a finding with Ship B, the provenance graph lets B evaluate trustworthiness structurally, not just by source reputation
- **Selective memory export:** Clean Room transfers can be defined as graph subsets — export capabilities and qualifications, exclude incident-specific connections

### For Nooplex Commercial (Governance)
- **Data classification:** Graph edges carry classification labels (private/department/ship/fleet) — already defined in RecordsStore's `DocumentClassification`
- **Audit trails:** Who produced this knowledge? Through what chain of reasoning? Required for regulated industries (defense, finance, healthcare)
- **Agent portfolio analysis:** Which agents have knowledge graphs richest in a domain? Informs workforce assignment decisions

## Architecture Proposal

### Core Principle: Extend, Don't Replace

The six-layer memory stack is sound. The three existing graphs serve their operational purposes. The unified knowledge graph is a **queryable overlay** that connects entities across all layers, not a replacement for any of them.

### Entity Types (Initial)

Derived from existing ProbOS domain model:

| Entity Type | Source | Examples |
|-------------|--------|----------|
| `agent` | Ontology Assignments | Atlas, Ezri, Chapel |
| `department` | Ontology Departments | Science, Medical, Engineering |
| `incident` | New (from episodes + BFs) | BF-257 DM loop, BF-239 working memory |
| `decision` | DECISIONS.md entries | "Receive-side rate limiter over send-side" |
| `duty` | Duty logs | Watch standing, scheduled analysis |
| `finding` | Ship's Records notebooks | "DM cooldowns are unidirectional" |
| `capability` | PostCapability (AD-648) | threat_detection, dm_management |
| `standing_order` | Standing Orders tiers | Federation, Ship, Department, Agent |

### Relation Types (Initial)

| Relation | Domain → Range | Source |
|----------|----------------|--------|
| `reports_to` | agent → agent | Ontology (exists) |
| `member_of` | agent → department | Ontology (exists) |
| `competent_in` | agent → topic | Hebbian weights (exists, implicit) |
| `resolved_by` | incident → decision | New (links BFs to DECISIONS.md) |
| `involved_in` | agent → incident | New (from episode agent_ids) |
| `informed_by` | decision → finding | New (links decisions to notebook entries) |
| `depends_on` | incident → incident | New (BF cross-references) |
| `produced_by` | finding → duty | New (links notebook entries to duty context) |
| `classified_as` | * → classification | RecordsStore DocumentClassification (exists) |
| `originated_on` | * → ship_did | Identity Ledger (exists, for federation) |

### Storage Layer: SQLite First, Kùzu Upgrade Path

**Phase 1 — SQLite relations table** (zero new dependencies):

```sql
CREATE TABLE knowledge_edges (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    relation TEXT NOT NULL,
    target_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    confidence REAL DEFAULT 1.0,
    source_agent TEXT,           -- provenance: who created this edge
    source_duty TEXT,            -- provenance: from which duty
    classification TEXT DEFAULT 'ship',  -- private/department/ship/fleet
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX idx_ke_source ON knowledge_edges(source_id, relation);
CREATE INDEX idx_ke_target ON knowledge_edges(target_id, relation);
CREATE INDEX idx_ke_type ON knowledge_edges(source_type, target_type);
CREATE INDEX idx_ke_classification ON knowledge_edges(classification);
```

**Traversal via recursive CTEs:**

```sql
-- 2-hop expansion from a known entity
WITH RECURSIVE hops AS (
    SELECT target_id, target_type, relation, 1 AS depth
    FROM knowledge_edges
    WHERE source_id = :entity_id AND depth <= :max_depth
    UNION ALL
    SELECT ke.target_id, ke.target_type, ke.relation, h.depth + 1
    FROM knowledge_edges ke
    JOIN hops h ON ke.source_id = h.target_id
    WHERE h.depth < :max_depth
)
SELECT DISTINCT target_id, target_type, relation, depth FROM hops;
```

**Phase 2 — Kùzu migration** (when needed):

If graph queries grow beyond 3-hop CTEs, or pattern matching (e.g., "find all agents connected to incidents in department X that resolved with decision type Y") becomes unwieldy in SQL, migrate the `knowledge_edges` table to Kùzu. Kùzu is embedded (pip installable, no server), supports Cypher, and coexists with SQLite for non-graph data.

Decision criteria for migration: when more than 30% of knowledge queries require > 3 hops or use path-pattern matching.

### Recall Enhancement: Graph-Expanded Retrieval

Current recall flow:
```
Query → ChromaDB semantic search → ranked episodes → return
```

Enhanced flow:
```
Query → ChromaDB semantic search → ranked episodes
                                       ↓
                              Extract entity IDs from top-K results
                                       ↓
                              1-hop graph expansion (knowledge_edges)
                                       ↓
                              Merge: episodes + connected entities
                                       ↓
                              Return enriched context
```

This is the Thoth pattern (FAISS + 1-hop NetworkX expansion) adapted to ProbOS's existing ChromaDB + SQLite stack. No NetworkX needed — the 1-hop expansion is a single SQL query.

### Dream Consolidation Integration

Dream Step 10 (new): **Relationship Inference**

After existing dream steps complete, scan recent episodes for co-occurring entities that have no edge in `knowledge_edges`. Use LLM to classify the relationship type. This mirrors Thoth's dream cycle Phase 3 (relationship inference for co-occurring pairs with no edge).

Anti-contamination: same pattern as existing dream steps — per-entity caps, rejection cache, source tagging (`source="dream_relationship_inference"`).

### NL-to-Graph Query (Ship's Computer Enhancement)

When the Captain or an agent asks a structural question ("what led to X?", "who was involved in Y?", "how does A relate to B?"), the Ship's Computer routes to graph traversal:

1. LLM extracts entity references from the NL query
2. Look up entity IDs via vector search or exact match
3. Generate a bounded graph traversal (CTE or Cypher)
4. Return structured result with provenance

This is the Fabric IQ NL2GQL capability replicated locally. The LLM does schema-aware query generation; the graph engine does execution.

## OSS vs Commercial Split

Following the boundary rule: "how it works" → OSS; "how it makes money" → commercial.

### OSS (Core Knowledge Graph)

| Component | Rationale |
|-----------|-----------|
| `knowledge_edges` schema + SQLite storage | Infrastructure — how the graph works |
| Entity types and relation types | Domain model — part of the ontology |
| Graph-enhanced recall (ChromaDB → graph expansion) | Recall quality is core agent capability |
| Dream Step 10: relationship inference | Dream consolidation is OSS |
| Recursive CTE traversal utilities | Query infrastructure |
| Provenance fields (source_agent, source_duty) | Foundation for federation trust |
| Classification field | Schema — the field exists in OSS |

### Commercial (Governance + Fleet Analytics)

| Component | Rationale |
|-----------|-----------|
| Classification **enforcement** (access control per edge) | Governance policy is commercial |
| NL-to-graph query routing (Ship's Computer enhancement) | Premium cognitive capability |
| Cross-instance knowledge graph federation | Fleet-level feature |
| Audit trail reporting + compliance dashboards | Enterprise governance |
| Agent portfolio analysis (graph-based capability assessment) | Workforce management (Nooplex) |
| Kùzu migration tooling + Cypher query interface | Scale optimization for paying customers |
| Graph-based anomaly detection | Advanced operational intelligence |

### Split Rationale

The graph *structure* (schema, storage, basic traversal, dream inference) is OSS because it's foundational infrastructure that makes all agents smarter. The graph *exploitation* (governance enforcement, fleet analytics, NL query routing, anomaly detection) is commercial because it's operational intelligence that makes money.

This follows the same pattern as the ontology: the org chart model is OSS, workforce scheduling (AD-496–498) and agent services automation (AD-C-010+) are commercial.

## Oracle Integration — The Graph Should Live Inside the Oracle

The Oracle (`cognitive/oracle_service.py`, AD-462e) is ProbOS's cross-tier unified memory query service. It already searches four tiers in parallel (Episodic, Records, Operational, Archive), merges results with normalized scores, and tags each result with provenance. It's dependency-injected, stateless, and designed for exactly this kind of extension.

**The knowledge graph should not be a standalone service.** It should be the Oracle's fifth tier and its structural enrichment layer. The Oracle is already the single point where all knowledge tiers converge — adding graph awareness here means every consumer of the Oracle (agents, Ship's Computer, Counselor) gets graph-enhanced results without any changes to their code.

### Integration Architecture

**Current Oracle flow** (`OracleService.query()`):
```
query_text → parallel search:
    Tier 1: _query_episodic()     → ChromaDB vector + salience
    Tier 2: _query_records()      → Ship's Records keyword
    Tier 3: _query_operational()  → KnowledgeStore file lookup
    Tier 4: _query_archive()      → Cross-reset archive
→ merge all_results → sort by score → return OracleResult[]
```

**Enhanced Oracle flow:**
```
query_text → parallel search:
    Tier 1: _query_episodic()     → ChromaDB vector + salience
    Tier 2: _query_records()      → Ship's Records keyword
    Tier 3: _query_operational()  → KnowledgeStore file lookup
    Tier 4: _query_archive()      → Cross-reset archive
    Tier 5: _query_graph()        → Entity match + relation traversal  ← NEW
→ merge all_results → sort by score
→ _expand_via_graph(top_k)       → 1-hop enrichment on merged results ← NEW
→ return OracleResult[]
```

### Two Integration Points

**1. Tier 5: Direct Graph Query (`_query_graph`)**

A new private method on `OracleService`, following the exact pattern of the existing four tiers:

```python
async def _query_graph(
    self, query_text: str, *, k: int = 5,
) -> list[OracleResult]:
```

- Extract candidate entity names/IDs from query text (fuzzy match against known entity names in `knowledge_edges`)
- For each matched entity, traverse 1-2 hops and return connected nodes
- Score by: edge weight × confidence × hop proximity (closer = higher)
- Provenance tag: `[knowledge graph]`

This tier answers structural questions the other four cannot: "what's connected to X?", "who was involved in Y?", "what depends on Z?" The existing tiers find text that *mentions* things; Tier 5 finds things that are *structurally related* to things.

**2. Graph Expansion on Merged Results (`_expand_via_graph`)**

After all five tiers are merged and sorted, a post-merge enrichment step:

```python
async def _expand_via_graph(
    self, results: list[OracleResult], *, max_expansions: int = 5,
) -> list[OracleResult]:
```

- Extract entity IDs mentioned in the top-K results across all tiers
- For each, do a 1-hop graph expansion
- Add connected entities as supplementary results with discounted scores (e.g., 0.7× the parent result's score)
- Provenance tag: `[graph expansion from: episodic]` (or whichever source tier)

This is where the real recall quality improvement happens. An episodic hit about BF-257 gets enriched with the decision record, involved agents, and related BFs — even if those didn't appear in any tier's direct search results. The agent gets *context*, not just *matches*.

### Constructor Change

The `OracleService.__init__` already accepts dependency-injected stores. Add one parameter:

```python
def __init__(
    self,
    *,
    episodic_memory: Any = None,
    records_store: Any = None,
    knowledge_store: Any = None,
    archive_store: Any = None,
    trust_network: Any = None,
    hebbian_router: Any = None,
    expertise_directory: Any = None,
    knowledge_graph: Any = None,        # ← NEW: KnowledgeEdgeStore
) -> None:
```

All existing consumers continue working unchanged — `knowledge_graph=None` means Tier 5 and graph expansion are silently skipped.

### Why the Oracle and Not a Separate Service

1. **Single query point:** Every agent already queries knowledge through the Oracle. Adding a separate graph service means agents need to know about two services and merge results themselves — that's the problem the Oracle was built to solve.
2. **Cross-tier enrichment:** The graph expansion step needs access to results from *all* tiers to enrich them. Only the Oracle has the merged result set.
3. **Provenance consistency:** The Oracle already handles provenance tagging. Graph results get the same treatment without new infrastructure.
4. **Budget enforcement:** `query_formatted()` already has `max_chars` budget control. Graph-expanded results participate in the same budget, preventing context overflow.
5. **Expertise routing synergy:** AD-600's expertise directory routes episodic queries to the most relevant agent shards. The graph can inform this — if the graph knows which agents are connected to the query's entities, it can pre-filter shards before ChromaDB even runs.

### The Oracle Becomes the Knowledge Brain

With graph integration, the Oracle evolves from "search aggregator" to "knowledge reasoning engine." It doesn't just find relevant text — it understands the structural relationships between what it finds. This is the foundation for the NL-to-graph query capability (commercial layer): the Captain asks a structural question, the Ship's Computer delegates to the Oracle, and the Oracle knows whether to search text, traverse the graph, or both.

This is also what makes the Counselor Minority Report principle hold cleanly. The Oracle queries *published* knowledge — records, episodes, graph edges. The graph doesn't give the Oracle access to private agent state; it gives structural awareness of connections between things already in the public knowledge tiers.

## Phased Delivery

### Phase A: Foundation (2-3 ADs)

1. **AD-TBD-a: Knowledge Edge Store** — `knowledge_edges` table, CRUD operations, recursive CTE traversal, provenance fields. Integrate into Ship's Records module. Cloud-Ready storage abstract interface.
2. **AD-TBD-b: Oracle Graph Integration** — Add Tier 5 (`_query_graph`) and post-merge graph expansion (`_expand_via_graph`) to `OracleService`. New `knowledge_graph` constructor parameter. Provenance tagging for graph results.
3. **AD-TBD-c: Edge Population from Existing Data** — Backfill edges from: ontology (reports_to, member_of), Hebbian weights (competent_in above threshold), existing episodes (involved_in via agent_ids), DECISIONS.md cross-references.

### Phase B: Intelligence (2-3 ADs)

4. **AD-TBD-d: Dream Step 10 — Relationship Inference** — Nightly dream step scans recent episodes for co-occurring entities without edges. LLM classifies relationship type. Anti-contamination measures.
5. **AD-TBD-e: NL-to-Graph Query** — Ship's Computer structural query routing. LLM extracts entities → graph traversal → structured result. (Commercial layer)
6. **AD-TBD-f: Classification Enforcement** — Access control on graph edges per classification level. Federation export filters by classification. (Commercial layer)

### Phase C: Scale + Federation (2 ADs)

7. **AD-TBD-g: Federation Knowledge Sync** — Cross-instance edge synchronization. Trust-weighted acceptance of foreign knowledge. Provenance chain verification via DID signatures.
8. **AD-TBD-h: Kùzu Migration** — When SQLite CTEs hit complexity limits, migrate graph shard to embedded Kùzu. Dual-read during migration. (Commercial layer — scale optimization)

## Relationship to Existing ADs and Research

| Existing Work | Relationship |
|---------------|-------------|
| AD-434 (Ship's Records) | Knowledge edges live alongside Records in the institutional memory layer |
| AD-605 (Enhanced Embedding) | Enriched embeddings improve the vector search that feeds graph expansion |
| AD-606 (Evolved Thought Storage) | Evolved thoughts become high-value graph nodes with rich connections |
| AD-608 (Retroactive Memory Evolution) | Edge creation at store time IS retroactive evolution — A-MEM's linking pattern |
| AD-557 (Emergence Metrics) | Graph centrality metrics complement information-theoretic emergence measurement |
| AD-560 (Science Analytical Pyramid) | Data flows up the pyramid along graph edges, not just vector similarity |
| Phase 28 (Semantic Hebbian) | Hebbian weights become first-class edges in the unified graph |
| Phase 29 (Federation) | Knowledge lineage graph is the trust substrate for federated knowledge sharing |
| Fabric IQ comparison | Graph + ontology + NL query + lineage covers 4 of 5 Fabric IQ workload items; streaming analytics is the one ProbOS doesn't need |

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Graph becomes a second source of truth that diverges from primary stores | Edges are *derived from* primary stores, not independent. Backfill process is idempotent and re-runnable. |
| Edge explosion (too many low-value relationships) | Confidence threshold for edge creation. Dream inference has per-entity caps. Weight decay on unused edges. |
| Query performance with large graphs | Bounded traversal (max 3 hops default). SQLite indexes on source/target/type. Kùzu upgrade path if needed. |
| Complexity creep | Phase A is 3 ADs with zero new dependencies. Each subsequent phase is opt-in. |

## Decision Required

1. **AD numbering:** Assign AD block for knowledge graph work (suggest AD-685 through AD-692, or a new series)
2. **Phase A timing:** Can start after current wave completes — no blockers, all prerequisites (AD-434, ontology, ChromaDB) already built
3. **Commercial split confirmation:** Graph structure OSS, graph exploitation commercial — matches existing boundary rule?

## References

- Thoth triple-store: `github.com/siddsachar/Thoth` — SQLite + NetworkX + FAISS pattern
- Fabric IQ: Microsoft's graph + ontology + NL query + lineage + governance bundle
- "AI Meets Brain" survey: `docs/research/agent-memory-survey-absorption.md` — Mem0, G-Memory, A-MEM patterns
- ProbOS memory architecture: `docs/architecture/memory.md` — six-layer stack
- ProbOS knowledge layer: `docs/architecture/knowledge.md` — three-tier model
- Kùzu embedded graph DB: `kuzudb.com` — Cypher-compatible, pip installable, no server
