# RAGFlow — Context-Layer Absorption Study

**AD:** AD-714
**Issue:** [#496](https://github.com/seangalliher/ProbOS/issues/496)
**Upstream:** [`infiniflow/ragflow`](https://github.com/infiniflow/ragflow) (Apache-2.0, ~80k★, v0.25.1)
**Status:** Research complete. No production code shipped.
**Date:** 2026-05-08

## 1. What It Does

RAGFlow markets itself as a *context layer* — an opinionated stack that turns documents (PDFs, slides, images, structured records) into a question-answering surface for LLMs. It bundles four absorbable patterns:

- **DeepDoc** — a parser that extracts layout, tables, and figures from PDFs/DOCX/scanned images, producing structured chunks that preserve the document's information topology rather than naively splitting on token boundaries.
- **Template-based chunking** — explicit, user-selectable chunking strategies per dataset; the rule that produced a chunk is a first-class artifact, not a hyperparameter buried in retrieval code.
- **Multiple recall + fused re-ranking** — combines BM25-style lexical recall, vector recall, and (optionally) hybrid recall, then applies a fused re-ranker before passing context to the LLM.
- **Grounded citations** — answers carry traceable references back to specific document chunks so a human can verify or veto.

The headline trade-off is operational cost (a Docker stack with ES + MySQL + MinIO + Redis + Flask + a Go CLI) for ingestion fidelity.

## 2. Architecture

RAGFlow is a self-hosted Docker stack. The default storage path uses Elasticsearch for the vector + lexical index, MinIO for binary artifacts, MySQL for structured metadata, and Redis for cache. Their own Infinity vector engine is an optional swap. The control plane is Flask/Quart (Python) plus a Go CLI under `cmd/`. The agent layer (`agent/`) was added in 2025-08 with MCP integration; a `memory/` directory landed in 2025-12 alongside the AI-agent memory feature.

ProbOS by contrast ships a single SQLite + ChromaDB and intentionally avoids the heavy stack. The cost contrast is the central reason RAGFlow's storage architecture itself is in our reject set — but the *abstractions* RAGFlow built on top of that storage (chunking templates, fused re-rank, grounded citations) are layer-portable.

## 3. What ProbOS Has

| RAGFlow pattern | ProbOS analogue | Citation | Coverage |
|---|---|---|---|
| Document ingestion (DeepDoc) | none — events flow in via NL/intent surface, not document upload | — | MISSING |
| Template-based chunking | none — `WorkflowCache._normalize` is query-side, not document-side | `src/probos/cognitive/workflow_cache.py:150` | MISSING |
| Fused re-ranking | `recall_weighted` composite scoring (AD-606) — semantic + recency + trust + composite | `src/probos/cognitive/episodic.py:2509` | PARTIAL |
| Grounded citations | none — `Episode.id` exists but the LLM is not forced to cite | `src/probos/types.py:445` | MISSING |
| Source provenance fields | `AnchorFrame.source_origin_id`, `artifact_version`, `anomaly_window_id` (AD-662) | `src/probos/types.py:391` | PRESENT (would feed any future ingestor) |
| Anchor-based structured recall | `recall_by_anchor` | `src/probos/cognitive/episodic.py:2747` | PRESENT |

## 4. Absorption Candidates

Ranked by gap-vs-effort:

1. **Grounded citations on LLM responses** — gap=high (no citation surface today); effort=S (post-process LLM output to require `[ep:<id>]` markers); risk=LOW. Proposed AD-714-3.
2. **Document ingestion as a first-class adapter** — gap=high; effort=L (parser, chunker, episodic adapter); risk=MEDIUM (changes the "everything is an event" stance). Proposed AD-714-1. This is the headline architectural choice the absorption invites.
3. **Template-based chunking as a sibling to query normalization** — gap=high; effort=M (chunking strategy registry + `WorkflowCache`-adjacent template store); risk=LOW. Proposed AD-714-2. Depends on AD-714-1 for an actual document corpus to chunk.
4. **Fused re-ranking comparison** — gap=PARTIAL (already have composite scoring, but no BM25/lexical lane); effort=M; risk=LOW. May not need a new AD; instead, pair with Memvid pattern 1 (AD-712) for a holistic "lexical + relational + semantic" tri-recall study.

## 5. What We Reject

- **Elasticsearch / MySQL / MinIO / Redis** stack. ProbOS deliberately ships a single-node SQLite + ChromaDB. We will not import this complexity to gain document parsing.
- **Flask/Quart REST control plane.** ProbOS uses its own HXI + slash-command + IntentBus surface; absorbing RAGFlow's UI would fork our user-facing identity.
- **The OpenClaw "RAGFlow Skill"** integration. RAGFlow shipped a skill that exposes its datasets through OpenClaw — directly competitive with ProbOS-style cognitive meshes. We do not use it.
- **DeepDoc as-is.** Their parser is impressive but tied to MinerU/Docling and a Python deep-learning stack we don't otherwise ship. If we absorb document ingestion (AD-714-1), we'll wrap a lighter parser (or expose DeepDoc behind an optional plugin).

## 6. Recommended Follow-ups & Artifact Choice

**Artifact chosen: option (a) — grep-and-cite test.** The absorption doc above makes "what ProbOS already covers" claims that must remain accurate as the codebase evolves. A coverage-claim grep test guards section 3's citations from drifting. The benchmark stub option (b) is rejected for v1 because it requires reading RAGFlow's actual chunking-boundary heuristics from the upstream source — outside the upstream-fetch budget Architect allocated. The follow-up issue body option (c) is folded into the table below.

| # | Title | Scope | AD candidate |
|---|---|---|---|
| 1 | Grounded citations on LLM responses | Post-process LLM output to enforce `[ep:<id>]` references back to recalled episodes; reject hallucinated cites | AD-714-3 |
| 2 | Document ingestion adapter (Phase 1) | Wrap a single PDF/DOCX parser, emit `Episode` objects with populated `AnchorFrame.source_origin_id` | AD-714-1 |
| 3 | Tri-recall lexical + relational + semantic comparison | Pair with AD-712 Memvid; benchmark BM25 + relational + vector against current `recall_weighted` baseline | AD-714-4 |

## Status

Research complete. No production code in this AD. Implementation candidates filed as forward markers `AD-714-{1,2,3,4}`.
