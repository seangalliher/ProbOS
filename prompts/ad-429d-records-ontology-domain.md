# AD-429d: Records Ontology Domain — Ship's Records Schema

## Context

AD-429a through 429c delivered seven ontology domains (Vessel, Organization, Crew, Skills, Operations, Communication, Resources). The `VesselOntologyService` in `src/probos/ontology.py` (851 lines) loads YAML schemas from `config/ontology/`, builds in-memory models, and provides query methods. The pattern is well-established.

AD-429d completes the eighth and final ontology domain: **Records** — the formal schema for the Ship's Records system (AD-434). This defines document classes, retention policies, classification levels, and the three-tier knowledge model that connects episodic memory (Tier 1), ship's records (Tier 2), and operational state (Tier 3).

**Important:** AD-434 (the actual RecordsStore runtime service) is NOT yet implemented. AD-429d defines the **ontology schema only** — what the records system IS, so agents can reason about it and the eventual AD-434 implementation has a formal data model to build against.

## Important Constraints

- This is **schema only**. Do NOT create a RecordsStore service, Git repository, or any persistence layer. Those belong to AD-434.
- Follow the exact pattern from 429c: YAML schema → dataclasses → `_load_*()` method → query methods → REST endpoint → tests.
- Keep it lean. This is the smallest of the eight domains — 1 YAML file, ~6 dataclasses, ~6 query methods.
- Do NOT modify any existing files except `ontology.py` and `api.py`.

---

## Step 1: Schema YAML — `config/ontology/records.yaml`

```yaml
# Domain 8: Records — Ship's Records schema (AD-434 data model)
#
# Defines the formal structure for ProbOS's instance knowledge system.
# The actual RecordsStore service is implemented in AD-434.
# This schema provides the ontology so agents understand what records ARE
# and how the three-tier knowledge model works.

# Three-tier knowledge model
# Connects to resources.yaml knowledge_sources (already defined)
knowledge_tiers:
  - tier: 1
    name: "Experience"
    store: "EpisodicMemory"
    description: "Per-agent episodic memories — sovereign shard, private diary"
    access: own_shard_only
    persistence: chromadb
    promotion_path: "Agents observe patterns in their experiences → write to Records (Tier 2)"
  - tier: 2
    name: "Records"
    store: "Ship's Records"
    description: "Git-backed instance knowledge — duty logs, notebooks, published reports"
    access: all_crew
    persistence: git
    promotion_path: "Published records indexed in KnowledgeStore for semantic search"
  - tier: 3
    name: "Operational State"
    store: "KnowledgeStore"
    description: "Trust snapshots, routing weights, agent source code, workflow state"
    access: ship_computer
    persistence: git
    promotion_path: null

# Document classifications — access control levels
classifications:
  - id: private
    name: "Private"
    description: "Visible only to the authoring agent — personal notebook entries"
    access_scope: author_only
  - id: department
    name: "Department"
    description: "Visible to department members — department briefings, internal analysis"
    access_scope: same_department
  - id: ship
    name: "Ship"
    description: "Visible to all crew — published reports, duty logs, Captain's Log"
    access_scope: all_crew
  - id: fleet
    name: "Fleet"
    description: "Shared across federated instances — federation-level knowledge"
    access_scope: federation

# Document classes — categories of records
document_classes:
  - id: captains_log
    name: "Captain's Log"
    description: "Official ship record — append-only, daily entries, signed via git commit"
    classification_default: ship
    retention: permanent
    format: "YYYY-MM-DD.md"
    special_rules:
      - "Append-only — entries cannot be edited after commit"
      - "Daily file format — one markdown file per day"
      - "Signed via git commit signature"
      - "Legal record — permanent retention, never archived"
  - id: notebook
    name: "Agent Notebook"
    description: "Personal agent workspace — observations, analysis, draft ideas"
    classification_default: private
    retention: archive_90_days
    format: "free-form markdown"
    special_rules:
      - "Each agent has their own notebook directory"
      - "Dream consolidation may promote patterns from notebook to published reports"
      - "Private by default — agent can explicitly publish entries"
  - id: report
    name: "Published Report"
    description: "Formal analysis or recommendation — reviewed and published for crew consumption"
    classification_default: ship
    retention: archive_365_days
    format: "structured markdown with YAML frontmatter"
    special_rules:
      - "Requires explicit publish action"
      - "Indexed in KnowledgeStore with records: prefix for semantic search"
      - "Version-tracked — edit history preserved in git"
  - id: duty_log
    name: "Duty Log"
    description: "Operational records — watch handoffs, incident reports, maintenance logs"
    classification_default: department
    retention: archive_180_days
    format: "structured markdown"
    special_rules:
      - "One log per department per watch period"
      - "Handoff summaries at watch transitions"
  - id: operations
    name: "Operations Record"
    description: "System-generated operational data — deployment records, configuration changes"
    classification_default: ship
    retention: archive_365_days
    format: "structured YAML/JSON"
    special_rules:
      - "Machine-generated, not agent-authored"
      - "Provides ground truth for agent reasoning"
  - id: manual
    name: "Manual / Reference"
    description: "Standing reference documentation — procedures, protocols, technical specs"
    classification_default: ship
    retention: permanent
    format: "structured markdown"
    special_rules:
      - "Version-controlled — superseded versions archived, not deleted"
      - "Living documents — updated as procedures evolve"

# Retention policies
retention_policies:
  - id: permanent
    name: "Permanent"
    description: "Never archived or deleted — legal and historical record"
    archive_after_days: null
    delete_after_days: null
    applies_to: ["captains_log", "manual"]
  - id: archive_90_days
    name: "Archive after 90 days"
    description: "Moved to archive directory after 90 days of inactivity"
    archive_after_days: 90
    delete_after_days: null
    applies_to: ["notebook"]
  - id: archive_180_days
    name: "Archive after 180 days"
    description: "Moved to archive directory after 180 days"
    archive_after_days: 180
    delete_after_days: null
    applies_to: ["duty_log"]
  - id: archive_365_days
    name: "Archive after 1 year"
    description: "Moved to archive directory after 1 year"
    archive_after_days: 365
    delete_after_days: null
    applies_to: ["report", "operations"]

# Document frontmatter schema — defines the metadata fields for each record
document_schema:
  required_fields:
    - name: author
      type: string
      description: "Agent callsign or 'Captain' or 'System'"
    - name: classification
      type: enum
      values: [private, department, ship, fleet]
      description: "Access control classification"
    - name: document_class
      type: enum
      values: [captains_log, notebook, report, duty_log, operations, manual]
      description: "Document category"
    - name: created
      type: datetime
      description: "ISO 8601 creation timestamp"
  optional_fields:
    - name: status
      type: enum
      values: [draft, review, published, archived, superseded]
      description: "Document lifecycle status"
      default: draft
    - name: department
      type: string
      description: "Authoring department (for department-classified docs)"
    - name: topic
      type: string
      description: "Subject area or topic tag"
    - name: tags
      type: list
      description: "Free-form tags for categorization"
    - name: updated
      type: datetime
      description: "Last modification timestamp"
    - name: supersedes
      type: string
      description: "Path to document this one supersedes"

# Repository structure (AD-434 will implement this)
repository_structure:
  description: "Git-backed repository at {data_dir}/ship-records/"
  directories:
    - path: "captains-log/"
      description: "Captain's Log entries — YYYY-MM-DD.md"
    - path: "notebooks/{callsign}/"
      description: "Per-agent notebook directories"
    - path: "reports/"
      description: "Published reports"
    - path: "duty-logs/{department}/"
      description: "Per-department duty logs"
    - path: "operations/"
      description: "System-generated operational records"
    - path: "manuals/"
      description: "Reference documentation"
    - path: "archive/"
      description: "Archived documents past retention period"
```

---

## Step 2: Data Models in `ontology.py`

Add Records domain dataclasses after the Resources models:

```python
# --- Records domain (AD-429d) ---

@dataclass
class KnowledgeTier:
    """One tier of the three-tier knowledge model."""
    tier: int
    name: str
    store: str
    description: str
    access: str
    persistence: str
    promotion_path: str | None

@dataclass
class DocumentClassification:
    """Document access control classification."""
    id: str  # "private", "department", "ship", "fleet"
    name: str
    description: str
    access_scope: str

@dataclass
class DocumentClass:
    """Category of ship's record."""
    id: str  # "captains_log", "notebook", "report", etc.
    name: str
    description: str
    classification_default: str
    retention: str  # retention policy id
    format: str
    special_rules: list[str]

@dataclass
class RetentionPolicy:
    """Retention and archival policy for a document class."""
    id: str
    name: str
    description: str
    archive_after_days: int | None
    delete_after_days: int | None
    applies_to: list[str]  # document class ids

@dataclass
class DocumentField:
    """A field in the document frontmatter schema."""
    name: str
    type: str
    description: str
    values: list[str] | None = None
    default: str | None = None

@dataclass
class RepositoryDirectory:
    """A directory in the records repository structure."""
    path: str
    description: str
```

---

## Step 3: VesselOntologyService Extensions

### New Instance Variables

Add to `__init__()`:

```python
# Records domain (AD-429d)
self._knowledge_tiers: list[KnowledgeTier] = []
self._classifications: list[DocumentClassification] = []
self._document_classes: list[DocumentClass] = []
self._retention_policies: list[RetentionPolicy] = []
self._document_fields_required: list[DocumentField] = []
self._document_fields_optional: list[DocumentField] = []
self._repository_directories: list[RepositoryDirectory] = []
```

### Loading Method

```python
def _load_records_schema(self, path: Path) -> None:
    """Load records.yaml — knowledge tiers, classifications, document classes, retention."""
    import yaml
    with open(path) as f:
        data = yaml.safe_load(f)

    # Knowledge tiers
    for t in data.get("knowledge_tiers", []):
        self._knowledge_tiers.append(KnowledgeTier(
            tier=t["tier"], name=t["name"], store=t["store"],
            description=t["description"], access=t["access"],
            persistence=t["persistence"],
            promotion_path=t.get("promotion_path"),
        ))

    # Classifications
    for c in data.get("classifications", []):
        self._classifications.append(DocumentClassification(
            id=c["id"], name=c["name"],
            description=c["description"], access_scope=c["access_scope"],
        ))

    # Document classes
    for dc in data.get("document_classes", []):
        self._document_classes.append(DocumentClass(
            id=dc["id"], name=dc["name"], description=dc["description"],
            classification_default=dc["classification_default"],
            retention=dc["retention"], format=dc["format"],
            special_rules=dc.get("special_rules", []),
        ))

    # Retention policies
    for rp in data.get("retention_policies", []):
        self._retention_policies.append(RetentionPolicy(
            id=rp["id"], name=rp["name"], description=rp["description"],
            archive_after_days=rp.get("archive_after_days"),
            delete_after_days=rp.get("delete_after_days"),
            applies_to=rp.get("applies_to", []),
        ))

    # Document schema
    schema = data.get("document_schema", {})
    for f in schema.get("required_fields", []):
        self._document_fields_required.append(DocumentField(
            name=f["name"], type=f["type"], description=f["description"],
            values=f.get("values"),
        ))
    for f in schema.get("optional_fields", []):
        self._document_fields_optional.append(DocumentField(
            name=f["name"], type=f["type"], description=f["description"],
            values=f.get("values"), default=f.get("default"),
        ))

    # Repository structure
    repo = data.get("repository_structure", {})
    for d in repo.get("directories", []):
        self._repository_directories.append(RepositoryDirectory(
            path=d["path"], description=d["description"],
        ))
```

### Call from `initialize()`

Add `("records.yaml", self._load_records_schema)` to the existing loop in `initialize()` alongside the 429c domain loaders.

### Query Methods

```python
# --- Records queries (AD-429d) ---
def get_knowledge_tiers(self) -> list[KnowledgeTier]:
    """Get the three-tier knowledge model."""
    return list(self._knowledge_tiers)

def get_knowledge_tier(self, tier: int) -> KnowledgeTier | None:
    """Get a specific knowledge tier (1, 2, or 3)."""
    for kt in self._knowledge_tiers:
        if kt.tier == tier:
            return kt
    return None

def get_classifications(self) -> list[DocumentClassification]:
    """Get all document classification levels."""
    return list(self._classifications)

def get_document_classes(self) -> list[DocumentClass]:
    """Get all document class definitions."""
    return list(self._document_classes)

def get_document_class(self, class_id: str) -> DocumentClass | None:
    """Get a specific document class by id."""
    for dc in self._document_classes:
        if dc.id == class_id:
            return dc
    return None

def get_retention_policies(self) -> list[RetentionPolicy]:
    """Get all retention policies."""
    return list(self._retention_policies)

def get_retention_policy(self, policy_id: str) -> RetentionPolicy | None:
    """Get a specific retention policy."""
    for rp in self._retention_policies:
        if rp.id == policy_id:
            return rp
    return None

def get_repository_structure(self) -> list[RepositoryDirectory]:
    """Get the records repository directory layout."""
    return list(self._repository_directories)
```

### Extend `get_crew_context()`

Add records context — minimal, just awareness that the records system exists:

```python
# Records context (AD-429d)
if self._knowledge_tiers:
    context["knowledge_model"] = {
        "tiers": [
            {"tier": kt.tier, "name": kt.name, "access": kt.access}
            for kt in self._knowledge_tiers
        ],
        "note": "Tier 1 (Experience) is your episodic memory. Tier 2 (Records) is the ship's shared knowledge. Tier 3 (Operational State) is infrastructure.",
    }
```

---

## Step 4: REST API Endpoint

Add to `api.py`:

```python
@app.get("/api/ontology/records")
async def get_ontology_records():
    """Records domain — knowledge tiers, classifications, document classes, retention."""
    if not runtime.ontology:
        return JSONResponse({"error": "Ontology not initialized"}, 503)
    ont = runtime.ontology
    return {
        "knowledge_tiers": [asdict(kt) for kt in ont.get_knowledge_tiers()],
        "classifications": [asdict(c) for c in ont.get_classifications()],
        "document_classes": [asdict(dc) for dc in ont.get_document_classes()],
        "retention_policies": [asdict(rp) for rp in ont.get_retention_policies()],
        "repository_structure": [asdict(d) for d in ont.get_repository_structure()],
    }
```

---

## Step 5: Tests

Create `tests/test_ontology_records.py` with:

1. **Load records.yaml** — verify parsing succeeds
2. **Knowledge tiers** — 3 tiers loaded (1, 2, 3)
3. **Knowledge tier query** — `get_knowledge_tier(2)` returns "Records" with access "all_crew"
4. **Knowledge tier unknown** — `get_knowledge_tier(99)` returns None
5. **Classifications** — 4 levels: private, department, ship, fleet
6. **Document classes** — 6 classes loaded
7. **Document class query** — `get_document_class("captains_log")` returns correct data
8. **Document class unknown** — `get_document_class("blog_post")` returns None
9. **Captain's Log special rules** — has "Append-only" rule, permanent retention, classification "ship"
10. **Notebook defaults** — classification "private", retention "archive_90_days"
11. **Retention policies** — 4 policies loaded
12. **Retention policy query** — `get_retention_policy("permanent")` has no archive/delete days
13. **Retention policy unknown** — `get_retention_policy("immediate")` returns None
14. **Archive policy days** — "archive_90_days" has archive_after_days=90
15. **Repository structure** — 7 directories defined
16. **Crew context includes knowledge model** — `get_crew_context()` has `knowledge_model` key with 3 tiers

---

## Verification

1. `uv run pytest tests/test_ontology_records.py -v` — all 16 tests pass
2. `uv run pytest tests/test_ontology.py tests/test_ontology_skills.py tests/test_ontology_ops_comms_resources.py -v` — existing ontology tests pass
3. `uv run pytest` — full suite passes
4. `cd ui && npm run build` — frontend still builds
5. Manual: `curl http://127.0.0.1:18900/api/ontology/records` returns full records domain

---

## Files

| File | Action |
|------|--------|
| `config/ontology/records.yaml` | **NEW** — Records domain: knowledge tiers, classifications, document classes, retention policies, document schema, repository structure |
| `src/probos/ontology.py` | **MODIFY** — 6 new dataclasses, `_load_records_schema()`, 8 query methods, `get_crew_context()` extension |
| `src/probos/api.py` | **MODIFY** — 1 new REST endpoint: `/api/ontology/records` |
| `tests/test_ontology_records.py` | **NEW** — 16 tests |
