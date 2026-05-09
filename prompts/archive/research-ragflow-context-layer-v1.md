# RESEARCH — RAGFlow context-layer absorption study

**Issue:** [#496](https://github.com/seangalliher/ProbOS/issues/496)
**Type:** Research AD (no production code; doc + 1 concrete artifact)
**Upstream:** https://github.com/infiniflow/ragflow (Apache-2.0, 80k★, v0.25.1 latest 2026-05-01)
**Depends on:** AD-573 (Working Memory), AD-644 (Situation Awareness), AD-606 (Think-in-Memory composite scoring), AD-590–593 (recall pipeline).
**Wave:** 130

## Goal

`infiniflow/ragflow` describes itself as "a leading open-source RAG engine that fuses cutting-edge RAG with Agent capabilities to create a superior **context layer** for LLMs." Its top-line absorbable patterns are: **deep document understanding** (DeepDoc), **template-based chunking**, **multiple recall paired with fused re-ranking**, and **grounded citations with traceable references**. ProbOS already ships a working-memory + situation-awareness + composite-scoring stack — but none of it focuses on **document ingestion** or **citation-grounded recall**. The goal of AD-710 is to compare the two systems precisely and produce a written absorption decision: which RAGFlow patterns ProbOS should pull in, which it should reject, and which are already covered.

This is a **research-tier** prompt. The deliverable is a doc plus one concrete artifact — not new production code.

## Architect-fetched upstream summary (2026-05-08)

Pulled from `infiniflow/ragflow` `README.md` (https://github.com/infiniflow/ragflow):

- **What it is.** A self-hosted Docker stack: a Flask/Quart Python backend, a TypeScript web UI, and a Go CLI (`internal/`, `cmd/`). Storage by default is Elasticsearch; Infinity (their vector DB) is an optional swap. MySQL, MinIO, Redis are also part of the deps stack. License Apache-2.0.
- **DeepDoc parsing pipeline** (`deepdoc/` directory, README at `deepdoc/README.md`): handles PDF, DOCX, slides, scanned images, structured data. Extracts layout, tables, figures. This is the bulk of their differentiation. Recently absorbed MinerU and Docling as alternative parsers (2025-10-23 entry).
- **Template-based chunking** (`rag/`): chunking strategies are explicit and explainable, not just "split by N tokens." Templates are user-selectable per dataset.
- **Retrieval pipeline.** Multiple recall (BM25 + vector + (presumably) hybrid) followed by a fused re-ranker. The README's only direct quote on the architecture: "Multiple recall paired with fused re-ranking." Code lives at `rag/`.
- **Agent layer** (`agent/`). Recently added an "agentic workflow" with MCP integration (2025-08-01). 2025-12-26 added "Memory" for AI agent. 2026-04-24 supports DeepSeek v4. 2026-03-24 ships a "RAGFlow Skill on OpenClaw" that exposes RAGFlow datasets via OpenClaw — explicitly competitive overlap with ProbOS-style cognitive meshes.
- **Memory module** (`memory/`). Top-level directory, post-2025-12-26. Limited README detail; the absorption study must read the source to characterize.
- **Storage architecture.** ES + MySQL + MinIO + Redis is heavyweight. ProbOS ships a single SQLite + ChromaDB, intentionally light. The trade-off — ingestion fidelity vs. operational cost — is the headline tension.

Main absorption candidates identified during this fetch (this list is **at-least-this-set**, not exhaustive — Builder's section 4 of the absorption doc may add or drop candidates based on what they find when reading the upstream source):

1. **DeepDoc-style document parsing** as a pre-step to ProbOS episodic ingestion. Today, ProbOS has no first-class "ingest a PDF" path; everything is event-stream-shaped. DeepDoc could feed `Episode` objects with `anchors.source_origin_id` (AD-662 already exists for this).
2. **Template-based chunking** as a complement to ProbOS's `WorkflowCache` normalization — different kind of normalization, different layer.
3. **Fused re-ranking** vs. the existing `recall_weighted` / composite scoring (AD-606). The pattern names are similar; Architect needs the Builder to compare implementations and either declare ProbOS already covers it or file a tightening AD.
4. **Grounded citations**. ProbOS today lets the LLM hallucinate without forcing it to cite the recalled `Episode.id` set. RAGFlow's "visualization of text chunking to allow human intervention" suggests a citation surface ProbOS could lift.

## Verified Against Codebase (2026-05-08)

- ✅ AD-573 working memory exists (verify-first the file: `src/probos/cognitive/working_memory.py` per existing module conventions).
- ✅ AD-644 situation awareness exists (verify-first: search `class.*Situation` in `src/probos/cognitive/`).
- ✅ AD-606 think-in-memory + composite scoring: `src/probos/cognitive/episodic.py:2509` `recall_weighted`, `:1755` `recall_by_anchor_scored`. RAG-style fused re-ranking is **already partially present**.
- ✅ AD-662 source-provenance anchor fields: `src/probos/types.py:391–395` (`source_origin_id`, `artifact_version`, `anomaly_window_id`). Document ingestion would feed these.
- ✅ No existing module under `src/probos/` named `deepdoc/`, `chunking/`, `parsing/`, or `ingest/`. Document ingestion is a true gap.

## Scope

- Architect has done the surface-level fetch. **Builder's job: read the upstream source for a few concrete files** (`rag/__init__.py`, `agent/__init__.py`, `memory/__init__.py`, `deepdoc/README.md`) to fill in the implementation details Architect cannot infer from the README alone.
- Then write the absorption document and produce one concrete follow-up artifact.

## Deliverables

### D1. `docs/research/ragflow-absorption.md`

Required section structure (each section ≥ 100 words, ≤ 600):

1. **What It Does** — paraphrase the upstream README in ProbOS's vocabulary. Identify the four absorbable patterns (DeepDoc, template chunking, fused re-rank, grounded citation).
2. **Architecture** — describe the Docker-stack reality (ES + MySQL + MinIO + Redis + Flask + Go CLI). Note the operational-cost contrast with ProbOS.
3. **What ProbOS Has** — for each of the four patterns, name the ProbOS module that already addresses it (or "missing"). Cite file:line for every claim. The Builder MUST grep before asserting any equivalence — Wave 5 standing convention #4.
4. **Absorption Candidates** — ranked list. For each, state: pattern, current ProbOS gap, proposed AD number, estimated effort tier (S/M/L), risk classification (LOW/MEDIUM/HIGH).
5. **What We Reject** — patterns we deliberately do NOT absorb (e.g. the Docker-heavy storage stack). State the reason.
6. **Recommended Follow-ups** — at most 3 issue stubs. Each names a concrete AD title and one-line scope.

### D2. One concrete artifact

Pick **one** of:

(a) **A grep-and-cite test** at `tests/research/test_ragflow_coverage_claims.py` that asserts every "ProbOS already covers this" claim in section 3 of the absorption doc resolves to a real file:line. The test parses the doc's section 3, extracts each `path/to/file.py:NNN` citation, and asserts the file exists and has at least the named symbol on or after that line. This is a documentation-integrity guard.

(b) **A skipped-by-default benchmark stub** at `tests/research/test_ragflow_chunk_overlap.py` that, when opted-in via env var, ingests a small fixture document (same ~200-word paragraph), runs ProbOS's working-memory chunking, and counts how many of RAGFlow's published "template_chunking" boundary heuristics match. Skip with `pytest.mark.skipif(os.getenv("PROBOS_RESEARCH_BENCH") != "1", ...)`. **Note:** Architect did not fetch RAGFlow's actual chunking-boundary heuristics during the upstream summary above. Picking (b) therefore requires the Builder to read `rag/__init__.py` and the relevant chunker module *first* and pin the heuristics in the absorption doc — the harness has nothing to compare against otherwise. If the upstream-fetch budget cannot afford that, prefer (a) or (c).

(c) **A follow-up issue body** at `docs/research/ragflow-followup-stubs.md` formatted as ready-to-paste GitHub issue Markdown for the top-1 absorption candidate, with title, scope, dependencies, and acceptance criteria.

The Builder picks **(a)** unless the absorption doc identifies a concrete benchmarkable difference (then **(b)**) or a single high-value follow-up that's mature enough to file (then **(c)**). Default = (a). **Section 6 of the absorption doc MUST state which artifact was chosen and why** (one paragraph; cite the trigger condition).

## Hard constraints (do NOT do)

- Do **not** add a `deepdoc` parser to ProbOS in this AD. Implementation is deferred regardless.
- Do **not** add Elasticsearch, MySQL, MinIO, or Redis dependencies. ProbOS's storage stack is intentionally lighter.
- Do **not** copy code from the upstream repo verbatim — Apache-2.0 permits it but we don't need any. Paraphrase.
- Do **not** assert "ProbOS already covers X" without a grep-verified file:line citation. Wave 5 convention #4 is HARD.
- Do **not** ship more than one of (a)/(b)/(c).

## Acceptance criteria

- **Pre-flight (Wave 129 convention #20):** run `git diff --numstat | sort -k2nr | head -5`; >200 deletions on any tracked file = STOP and surface to the Architect before reading source.
- `docs/research/ragflow-absorption.md` exists with all six required sections.
- Exactly one of (a)/(b)/(c) ships.
- If (a): `d:/ProbOS/.venv/Scripts/pytest.exe tests/research/test_ragflow_coverage_claims.py -v -n 0` passes.
- If (b): the benchmark file exists, is skipped under default test runs, and runs successfully when `PROBOS_RESEARCH_BENCH=1`.
- If (c): the issue stub file exists and is well-formed Markdown.
- Full gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile` (research test, if any, is skipped or runs in <2s).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Forward markers

- **AD-710-1**: First absorption — the highest-ranked candidate from the doc, formalized as a code-tier prompt.
- The decision to ingest documents into the episodic store is itself a strategic choice; once the doc is written, the Architect will revisit whether ProbOS's "everything is an event" stance survives or bends.

## Revision (2026-05-08)

- **Recommended R2 (record-the-choice):** Hardened section 6 wording to MUST: "Section 6 of the absorption doc MUST state which artifact was chosen and why."
- **Recommended R3 (soften candidates):** Reframed the four absorbable patterns as "at-least-this-set; Builder may add or drop" instead of mandatory.
- **Recommended R4 (artifact-(b) caveat):** Added inline note that picking (b) requires Builder to fetch RAGFlow's chunking heuristics first, and to prefer (a)/(c) if upstream-fetch budget is constrained.
- **Cross-cutting:** Added pre-flight working-tree integrity reminder. No config.py edits in this AD — no Build Ordering Note required.
