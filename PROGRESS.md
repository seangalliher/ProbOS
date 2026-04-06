# ProbOS — Progress Tracker

## Current Status: AD-526a COMPLETE (Social Channels + Tic-Tac-Toe — agent recreation framework. GameEngine protocol + TicTacToeEngine. RecreationService with game lifecycle, Ship's Records integration, GAME_COMPLETED event emission. Recreation + Creative default Ward Room channels with auto-subscription. Proactive integration: Recreation channel context gathering, [CHALLENGE @callsign game_type] and [MOVE position] action extraction with rank gating (Lieutenant+). cognitive_agent.py challenge/move instructions. RecreationService wired in finalize.py with ward_room + records_store + emit_event. 10 files modified, 47 tests). AD-570 COMPLETE (Anchor-Indexed Episodic Recall — Structured AnchorFrame Queries. Promotes 4 anchor fields (department, channel, trigger_type, trigger_agent) to top-level ChromaDB metadata for native where-clause filtering. One-time migration backfills existing episodes. recall_by_anchor() API with two modes: enumeration (structured filters, no embedding) and semantic re-ranking (structured + vector similarity). Post-retrieval agent_id filtering, activation tracking, hash verification. 2 files modified, 23 tests). BF-109 CLOSED (Qualification Probe Param Key Mismatch. _send_probe() sent params={"message":...} but perceive() reads params.get("text"). All Tier 1/2 probe results were unreliable — agents never received the question. One-line fix: "message" → "text". First real qualification run: 130/131 pass (99.2%), 15 agents, 130 baselines established. Only failure: Security Officer mti_temperament at 0.000). BF-108 CLOSED (LLM Unreachable — No Runtime Visibility. MockLLMClient.get_health_status() now returns overall:"mock" with all tiers offline. runtime.llm_is_mock property. Chat endpoint returns explicit offline message instead of triggering self-mod. /system/services correctly reports LLM as offline. 4 files, 0 new tests — covered by existing 82 tests). AD-567g COMPLETE (Cognitive Re-Localization — final AD in Memory Anchoring lineage 567a→g. Structured orientation at boot: cold start full orientation (identity + cognitive grounding + first duty), warm boot stasis recovery, diminishing proactive supplement. Anchor field gap fixes: watch_section, event_log_window, Ward Room department. OrientationService, OrientationContext, derive_watch_section(). Subsumes BF-034 cold-start note. 28 tests). AD-567f COMPLETE (Social Verification Protocol — absorbs AD-462d. Cross-agent claim verification, corroboration scoring, cascade confabulation detection. Privacy-preserving: agents see metadata not content. Anchor independence discriminates corroboration from cascade. Ward Room integration after AD-506b peer similarity. Bridge Alerts on medium/high risk. Counselor therapeutic DMs on high risk. 28 tests). AD-567d COMPLETE (Anchor-Preserving Dream Consolidation + Active Forgetting — provenance composition through dream pipeline (absorbs AD-559), ACT-R activation-based memory lifecycle (absorbs AD-462b), ActivationTracker with SQLite access log, dream Step 12 activation pruning, micro-dream replay reinforcement, recall access recording, 31 tests). AD-567c COMPLETE (Anchor Quality & Integrity — Johnson-weighted confidence scoring, RPMS confidence gating, per-agent AnchorProfile for Counselor diagnostics, SIF check_anchor_integrity(), drift classification (specialization/concerning/unclassified), absorbs AD-567e). AD-567b COMPLETE (Anchor-Aware Recall + Salience-Weighted Retrieval — RecallScore composite scoring, FTS5 keyword search sidecar, anchor context headers in memory formatting, SECONDHAND source wiring, recall_weighted() API with budget enforcement. Absorbs AD-462a). AD-567a COMPLETE (Episode Anchor Metadata — AnchorFrame dataclass with 10 fields across 5 dimensions, all 15 episode creation sites wired, serialization round-trip through ChromaDB, content hash exclusion, backwards compatible). BF-104 CLOSED (Display Crew Agent Count — registry.crew_count(), shell prompt shows crew not total, status panel/API/working memory updated). AD-566f COMPLETE (/qualify Shell Command — manual trigger and inspection, 5 subcommands: status/run/agent/baselines). AD-566e COMPLETE (Tier 3 Collective Tests — 5 crew-wide probes: CoordinationBreakevenProbe, ScaffoldDecompositionProbe, CollectiveIntelligenceProbe, ConvergenceRateProbe, EmergenceCapacityProbe + QualificationHarness.run_collective() + DriftScheduler collective integration). AD-566d COMPLETE (Tier 2 Domain Tests — 5 department-gated probes: TheoryOfMindProbe, CompartmentalizationProbe, DiagnosticReasoningProbe, AnalyticalSynthesisProbe, CodeQualityProbe + DriftScheduler tier generalization). AD-566c COMPLETE (Drift Detection Pipeline — DriftDetector z-score engine, DriftScheduler periodic runner, Counselor/VitalsMonitor/BridgeAlerts integration). AD-566b COMPLETE (Tier 1 Baseline Tests — 4 psychometric probes: PersonalityProbe, EpisodicRecallProbe, ConfaculationProbe, TemperamentProbe). AD-566a COMPLETE (Qualification Test Harness Infrastructure — psychometric protocol, store, harness engine). AD-541f COMPLETE (Eviction Audit Trail — Append-Only Accountability). AD-541 Lineage CLOSED (6/6 pillars complete). AD-541e COMPLETE (Content Hashing — Cryptographic Episode Integrity). BF-103 CLOSED (Episodic Memory Agent ID Mismatch — sovereign ID normalization + migration). AD-541d COMPLETE (Guided Reminiscence — Therapeutic Memory Sessions). AD-541c COMPLETE (Spaced Retrieval Therapy — Active Recall Practice). AD-541b COMPLETE (Reconsolidation Protection — Read-Only Memory Framing). AD-555 COMPLETE (Notebook Quality Metrics & Dashboarding). AD-554 COMPLETE (Real-Time Cross-Agent Convergence & Divergence Detection). AD-553 COMPLETE (Quantitative Baseline Auto-Capture). AD-552 COMPLETE (Notebook Self-Repetition Detection). AD-551 COMPLETE (Notebook Consolidation — Dream Step 7g). AD-550 COMPLETE. BF-069 CLOSED. BF-101/102 COMPLETE. AD-560 COMPLETE. AD-557 COMPLETE. AD-558 COMPLETE. BF-099 CLOSED. Cognitive JIT pipeline COMPLETE (9/9). 618 Cognitive JIT tests. 6,338 tests (6,189 pytest + 149 vitest).

---

## Development Eras

| Era | Phases | Codename | Status |
|-----|--------|----------|--------|
| [**Era I: Genesis**](progress-era-1-genesis.md) | 1-9 | Building the Ship | Complete |
| [**Era II: Emergence**](progress-era-2-emergence.md) | 10-21 | The Ship Comes Alive | Complete |
| [**Era III: Product**](progress-era-3-product.md) | 22-29 | The Ship Sets Sail | Complete |
| [**Era IV: Evolution**](DECISIONS.md) | 30 | The Ship Evolves | Active |
| Era V: Civilization | 31-36 | The Ship Becomes a Society | Planned |

## Release Tagging Policy

Tags use the format `v{major}.{minor}.{patch}-phase{N}` (e.g., `v0.4.0-phase29c`).

| Event | Tag? | Example |
|-------|------|---------|
| Phase completed | Yes — bump minor version | `v0.5.0-phase30` |
| Critical bug fix between phases | Yes — bump patch version | `v0.4.1-phase29c` |
| Roadmap/docs-only changes | No | — |
| Mid-phase work (partial features) | No | — |
| First production-ready release | Yes — `v1.0.0` | After security hardening (Phase 31) |

**Current tags:**

| Tag | Commit | Date | Notes |
|-----|--------|------|-------|
| `v0.1.0-phase12` | — | — | End of Era I: Genesis |
| `v0.4.0-phase29c` | `13d52a7` | 2026-03-17 | End of Phase 29c: Codebase Knowledge |

## Design Principles

See [design-principles.md](docs/development/design-principles.md) for full design principles:
- "Brains are Brains" (Nooplex core principle)
- Agent Development Model (Communication + Simulation)
- HXI Self-Sufficiency, Agent-First Design, Cockpit View
- Probabilistic Agents, Consensus Governance
- Agent Classification Framework (Core / Utility / Domain)
- Foundational Governance Axioms (Safety Budget, Reversibility, Minimal Authority)
- "Cooperate, Don't Compete" (Federation philosophy)
- Visiting Officer Subordination
- Extension-First Architecture
- Markdown is Code

---

## Environment

- **Platform:** Windows 11 Pro (10.0.26200)
- **Python:** 3.12.13 (installed via uv)
- **Toolchain:** uv 0.10.9
- **Key deps:** pydantic 2.12.5, pyyaml 6.0.3, aiosqlite 0.22.1, httpx 0.28+, rich 13.0+, chromadb 1.5.4, pytest 9.0.2, pytest-asyncio 1.3.0, pytest-xdist 3.8.0, pytest-timeout 2.4.0
- **LLM endpoints:** Fast tier: Ollama at `http://127.0.0.1:11434/v1`, Standard/Deep tier: VS Code Copilot proxy at `http://127.0.0.1:8080/v1`
- **LLM models:** fast=qwen3.5:35b (local Ollama), standard=claude-sonnet-4.6 (Copilot proxy), deep=claude-opus-4.6 (Copilot proxy)
- **Run tests:** `uv run pytest tests/ -v` (sequential) or `uv run pytest -n auto` (parallel, 13x faster)
- **Run fast tests:** `uv run pytest -n auto -m "not slow"` (skip 65 sleep-heavy tests)
- **Run demo:** `uv run python demo.py`
- **Run interactive:** `uv run python -m probos`
