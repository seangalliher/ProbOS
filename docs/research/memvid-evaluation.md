# Memvid Evaluation — Memory Infrastructure Comparison

**Date:** 2026-04-05
**Repository:** https://github.com/memvid/memvid
**License:** Apache 2.0 (same as ProbOS)
**Language:** Rust (edition 2024, requires 1.85.0+)
**Verdict:** Do NOT switch infrastructure. Absorb 3 design patterns.

---

## 1. What Is Memvid?

A single-file AI memory layer written in Rust. Packages documents, embeddings, search indices, and metadata into a portable `.mv2` binary file. Eliminates RAG pipeline infrastructure complexity — no database servers, no sidecar files. One file = one memory.

**v1** used QR codes (deprecated). **v2** is a custom binary format inspired by video container formats (hence "memvid") — append-only immutable frames organized in segments with a TOC footer.

**SDKs:** Node.js (`@memvid/sdk`), Python (`memvid-sdk`), CLI (`memvid-cli`), native Rust.

---

## 2. Core Architecture

### Storage Format (.mv2 v2.1)

```
Header (4KB)        — magic MV2\0, version, offsets, WAL metadata
Embedded WAL        — 1-64MB crash recovery (scaled by file capacity)
Data Segments       — Zstd or LZ4 compressed frames
Lex Index           — Tantivy BM25 full-text search (optional)
Vec Index           — HNSW vectors or brute-force (optional)
Time Index          — Chronological ordering for temporal queries
TOC (Footer)        — Segment catalog with SHA-256 checksums
```

**Key invariant:** Single file. No `.wal`, `.shm`, `.lock`, or sidecar files. Ever. WAL is embedded within the file itself.

### Smart Frames

Atomic unit of storage. Each frame: `frame_id` (monotonic u64), URI (`mv2://...`), title, timestamp, encoding type (Raw/Zstd/Lz4), compressed payload, SHA-256 checksum, key-value tags, status (active/tombstoned). Frames are append-only, never modified in place.

### MemoryCards

Structured layer on top of frames. Entity-slot-value triples with rich metadata:
- `MemoryKind`: Fact, Preference, Event, Profile, Relationship, Goal
- `Polarity`: Positive, Negative, Neutral
- `VersionRelation`: Sets, Updates, Extends, Retracts
- Temporal: `event_date` vs `document_date`
- Provenance: source frame, engine, confidence

### Embeddings

- **Local:** ONNX-based (BGE-small 384d default, BGE-base 768d, Nomic 768d, GTE-large 1024d)
- **Cloud:** OpenAI (text-embedding-3-small 1536d, text-embedding-3-large 3072d)
- **Visual:** CLIP embeddings for image search
- **Model binding:** Persistent model identity prevents querying BGE-small index with OpenAI vectors

### Retrieval

- **Lexical:** Tantivy (Rust Lucene equivalent) with BM25 ranking
- **Vector:** HNSW (M=16, ef=50) above 1000 vectors; brute-force L2 (SIMD-accelerated) below
- **Hybrid graph+vector:** QueryPlanner parses natural language ("who works at Google") into `GraphPattern` triple patterns, `GraphMatcher` executes against MemoryCards, re-ranks by vector similarity
- **Temporal:** Time-index chronological queries, natural language date parsing

### Additional Capabilities

- **Product Quantization (PQ96)** for compressed vectors (100+ threshold)
- **Enrichment pipeline:** Per-frame, per-engine-version manifest tracking for incremental processing
- **Logic Mesh:** Entity-relationship graph with DistilBERT-NER via ONNX
- **Replay:** Time-travel debugging — rewind, replay, or branch memory state
- **Schema inference:** Analyzes MemoryCards to infer types and cardinality
- **PII detection:** Regex-based for privacy-aware storage
- **Multi-modal:** Audio (Whisper via Candle), images (CLIP), PDF (multiple extractors + SymSpell OCR repair)

---

## 3. Comparison: Memvid vs ProbOS Episodic Memory

| Dimension | Memvid | ProbOS EpisodicMemory |
|-----------|--------|----------------------|
| **Language** | Rust (synchronous) | Python (async) |
| **Storage** | Custom binary `.mv2` single-file | ChromaDB (SQLite + vector store) |
| **Embeddings** | Local ONNX or OpenAI API | ChromaDB built-in (sentence-transformers) |
| **Vector index** | Custom HNSW + brute-force + PQ | ChromaDB HNSW |
| **Text search** | Tantivy BM25 | ChromaDB metadata filtering + keyword scoring |
| **Unit of storage** | Smart Frame (content blob + metadata) | Episode (summary + AnchorFrame metadata dict) |
| **Memory model** | MemoryCard (entity/slot/value triples) | Episode with salience, emotional valence, anchor confidence |
| **Temporal** | Time index + `get_at_time()` point queries | Timestamp metadata, temporal context (AD-502) |
| **Versioning** | Explicit Sets/Updates/Extends/Retracts per slot | Append-only; dream consolidation resolves contradictions |
| **Consolidation** | Enrichment engines (rule-based, LLM) | Dream consolidation (9-step pipeline) |
| **Retrieval** | BM25 + vector + graph match | Salience-weighted recall, anchor confidence gating, ACT-R activation |
| **Identity** | Single agent per file | Per-agent sovereign shard within shared Ship's Computer |
| **Crash safety** | Embedded WAL | SQLite WAL mode (ChromaDB) |
| **Portability** | Single file — email, copy, git | Database directory — requires ChromaDB |
| **Graph** | MemoryCard entity-slot-value + Logic Mesh | No explicit graph; trust + Hebbian are separate systems |
| **Multi-modal** | Text + PDF + Audio + Images | Text only |

### Philosophy Difference

- **Memvid** is a storage format with retrieval. Infrastructure — a file format any agent can use. No concept of agent identity, personality, trust, dreams, or social dynamics. A "memory hard drive."
- **ProbOS** episodic memory is a cognitive subsystem. Episodes carry salience, emotional valence, and anchor confidence, processed by dream consolidation that promotes patterns from private experience to shared knowledge. Memory is inseparable from the agent's identity and cognitive architecture.

---

## 4. Decision: Do NOT Switch Infrastructure

**Reasons:**

1. **Wrong abstraction level.** ProbOS's cognitive value (salience weighting, anchor confidence, dream consolidation, activation tracking, sovereign shards) is ProbOS code layered on top of ChromaDB. ChromaDB is a thin backend. Swapping it changes plumbing but none of the cognitive architecture. The real gaps (behavioral metrics, confabulation, orientation) are in the layers above storage.

2. **Architectural mismatch.** Memvid is synchronous Rust, single-writer, single-file. ProbOS is async Python, multi-agent concurrent reads/writes to a shared Ship's Computer service. FFI bridges (PyO3) would add complexity and hard Rust toolchain dependency. The single-file portability — memvid's killer feature — is a liability for ProbOS's centralized memory model.

3. **Violates Cloud-Ready Storage principle.** ProbOS engineering principles require abstract connection interfaces for commercial overlay backend swaps (SQLite → Postgres). Memvid's .mv2 format is proprietary and non-swappable — harder to cloud-migrate, not easier.

---

## 5. Absorbable Design Patterns (3)

### Pattern 1: Explicit Memory Version Relations

**Concept:** Memvid's MemoryCard `VersionRelation` enum: Sets (creates), Updates (replaces), Extends (adds to), Retracts (negates). Each new card explicitly states its relationship to prior knowledge on the same entity+slot.

**ProbOS gap:** Episodes are append-only. Contradictions are resolved by dream consolidation, but the dream engine has no explicit conflict model — it discovers contradictions via semantic similarity during consolidation (AD-551), which is best-effort.

**Absorption target:** AD-563 (Knowledge Linting — inconsistency detection). Add explicit version relations to notebook entries so inconsistency detection has structured data rather than relying on semantic similarity alone. When an agent writes "trust patterns are degrading," the system can check if a prior entry on the same topic said "stabilizing" and flag the relation as an explicit Update/Retract rather than discovering it post-hoc.

### Pattern 2: Enrichment Manifest Tracking

**Concept:** Memvid tracks per-frame, per-engine-version what has been processed. New enrichment engines only process unenriched frames — no redundant reprocessing.

**ProbOS gap:** Dream consolidation re-examines episodes without tracking what has already been consolidated. Each dream cycle processes the full episode window, including episodes that were already consolidated in prior cycles.

**Absorption target:** Dream pipeline (note on AD-538 or new sub-AD). Add a `consolidation_manifest` that tracks which episodes have been processed by which dream step+version. Dream cycles skip already-consolidated episodes unless they've been modified (reconsolidation, AD-541b) or decayed (AD-538). Reduces dream cycle cost as episode count grows.

### Pattern 3: Structured Anchor-Field Queries

**Concept:** Memvid's `QueryPlanner` detects relational queries ("who works at Google"), resolves against entity-slot-value triples (structured graph search), then re-ranks with vector similarity. Hybrid structured+semantic retrieval.

**ProbOS gap:** Episodic recall is semantic-only. AnchorFrame fields (temporal, spatial, social, causal, evidential) only influence scoring weight — you cannot query BY anchor fields. No way to ask "find all episodes from Engineering department" or "find all episodes involving Worf." Identified as gap #1 in AD-567g research.

**Absorption target:** New AD-570 (Anchor-Indexed Episodic Recall). Add structured query support for AnchorFrame fields alongside semantic search. Enables "who/what/where/when" queries that are currently impossible. Foundation for AD-567g's re-localization (spatial/temporal locality lookup) and AD-569's behavioral metrics (department-level analysis requires department-indexed episode queries).
