# WAVE 131 DISPATCH — AD-454 EvidenceCollector (taxonomy + agent)

**Wave:** 131
**Mode:** main
**Depends on:** 130
**Builder required:** yes
**Issues to close:** #510
**Date:** 2026-05-08

## Overview

Issue #510 (filed today, originally "AD-454: OSS EvidenceCollector for AD-453 emergence research") was earlier blocked because the dispatch referenced a taxonomy doc that didn't exist in the OSS repo. **Verify-first finding (2026-05-08):** the taxonomy DOES exist in the **commercial repo** at `<private-research-repo>\research\emergence-evidence-log.md` (18 codes, 13 documented observations across 2 trials). The work is done; it just needs to be ported to OSS and the agent built on top.

This wave ships **2 prompts in sequence**:
1. **`ad-454-emergence-taxonomy-v1.md`** — the prerequisite research/design prompt. Ports the taxonomy to OSS, adds any missing codes from the architect's review (cascade-confab is the obvious candidate), grounds it in external research, ships as `docs/research/emergence-taxonomy.md`.
2. **`ad-454-evidence-collector-v1.md`** — the EvidenceCollector agent that classifies Ward Room posts against the now-OSS taxonomy. Consumes the taxonomy doc as the source of truth.

The Builder builds prompt 1 first (the doc), then prompt 2 (the agent that imports the taxonomy).

## Subagent Prompt — Architect (drafting + research pass)

You are drafting **2 prompts** for Wave 131.

### Prompt 1: `prompts/ad-454-emergence-taxonomy-v1.md`

This is a **research-tier + design prompt**. Builder's job is to commit a research doc + a Python data module containing the taxonomy.

**Architect must do the research as part of drafting:**

1. **Internal work to absorb (read these files first):**
   - `<private-research-repo>\research\emergence-evidence-log.md` — 18-code taxonomy + 13 observations. PORT this taxonomy into the OSS prompt (the taxonomy itself is OSS-publishable; the trial observations stay commercial).
   - `<private-research-repo>\research\evidence-log.md` — earlier 7-code framing (EOB-MGMT, EOB-COORD, EOB-POLICY, EOB-COMPLY, EOB-BRIEF, EOB-RISK, EOB-ROLE). Compare to the 18-code version; document the evolution.
   - `decisions-era-2-emergence.md` line 803 region, `decisions-era-3-product.md` line 448, `decisions-era-4-evolution.md` line 434, `decisions-era-5-unification.md` line 504. Read each emergent-behavior reference — there may be additional codes implied by ProbOS's own AD-trail that the commercial taxonomy missed.
   - `src/probos/cognitive/emergent_detector.py` — already detects `cooperation_cluster`, `trust_anomaly`, `routing_shift`, `consolidation_anomaly`, `emergence_trends`. These are **system-level** patterns (population dynamics) — distinct from the **organizational-behavior** taxonomy (individual-agent acts). Document the distinction so the EvidenceCollector doesn't duplicate emergent_detector's job.

2. **External research to absorb (fetch URLs as part of drafting):**
   - **Riedl 2026** "Emergent Coordination in Multi-Agent Language Models" (arXiv:2510.05174). Already cited in `docs/research/emergent-coordination-research.md`. Re-read; extract the Partial Information Decomposition (PID) of Time-Delayed Mutual Information (TDMI) framework as the **quantitative** complement to our **qualitative** taxonomy. Each taxonomy code is a *qualitative* observation; PID gives us *quantitative* synergy/redundancy/unique-info atoms. The EvidenceCollector should produce both a qualitative tag AND a quantitative attribution where possible.
   - **Park et al. 2023** Generative Agents (Stanford). Their work is *peer-to-peer social emergence*; ours is *hierarchical organizational emergence*. The taxonomy must clearly distinguish — that's our novel contribution.
   - **MetaGPT / CrewAI / CAMEL** — static role assignment baseline. Document why their patterns DON'T appear in our taxonomy (they don't exhibit these behaviors; they execute scripted roles).

3. **Architect's required additions to the taxonomy** (things commercial missed):
   - **CASCADE-CONFAB** (anti-pattern code) — correlated misreading of an ambient stimulus propagating across departments without independent verification. Empirical evidence from this very session (2026-05-08): `pipeline_post_budget_exceeded` BF-237 telemetry was misinterpreted as a token-budget violation by 4-5 agents in convergence; the convergence looked emergent but was shared confabulation. This is the inverse of `RESEARCH-COLLAB` and is exactly the kind of failure the EvidenceCollector must distinguish from real organizational behavior. Critical to AD-453 paper validity — without this code, false positives go uncounted.
   - **Architect should propose any other codes** that emerged from internal-work review (e.g., `BILLET-NEGOTIATE` if AD-595 work surfaces negotiation behavior; `STANDING-ORDER-COMPLIANCE` distinct from `COC-COMP`).

**Deliverables to spec for the Builder:**

- D1: New file `docs/research/emergence-taxonomy.md` with the structure:
  - § Origin & evolution (commercial repo's 7-code → 18-code → this OSS canonical N-code version)
  - § Distinction from EmergentDetector (qualitative organizational behavior vs. quantitative population dynamics)
  - § Distinction from prior work (Park et al., MetaGPT, CrewAI — what they detect vs. what we detect)
  - § Connection to Riedl 2026 PID/TDMI (qualitative + quantitative complementary)
  - § The N-code taxonomy table (codes, categories, descriptions, examples, OSS-vs-commercial-trial-data note)
  - § Anti-pattern codes (CASCADE-CONFAB and any others)
  - § Cross-references to ProbOS internals (which AD/file each code can be detected from)
  - § Versioning policy (taxonomy v1 → v2 process)

- D2: New module `src/probos/cognitive/emergence_taxonomy.py` containing:
  - `class BehaviorCode(str, Enum)` with all N codes
  - `@dataclass class TaxonomyEntry` with code, category, description, example, references
  - `TAXONOMY: dict[BehaviorCode, TaxonomyEntry]` — single source of truth for the EvidenceCollector to import
  - `get_entry(code: BehaviorCode) -> TaxonomyEntry`
  - `as_classifier_prompt() -> str` — renders the taxonomy into an LLM classifier system prompt (for use by EvidenceCollector)

- D3: Tests at `tests/test_ad454_taxonomy.py`:
  - All N codes enumerated
  - Every entry has all required fields populated
  - `as_classifier_prompt()` includes every code
  - Anti-pattern codes are flagged distinctly from positive codes (e.g., `is_anti_pattern: bool` on TaxonomyEntry)

- D4: DECISIONS.md entry: `### AD-454 — Emergence Behavior Taxonomy (OSS canonical N-code with anti-patterns)`

**Acceptance:**
- Pre-flight: working-tree integrity check (>200 deletions = STOP).
- Focused: `pytest tests/test_ad454_taxonomy.py -v -n 0` green.
- Full gate: `pytest tests/ -q -n 8 --dist=loadfile` non-decreasing.
- Comply with engineering principles in `.github/copilot-instructions.md`.

**Out of scope:** the actual classifier agent (that's prompt 2). The trial observation data stays in the commercial repo; only the taxonomy ports.

### Prompt 2: `prompts/ad-454-evidence-collector-v1.md`

Code-tier prompt. Builder constructs the EvidenceCollector agent.

**Architect must verify-first:**
- How does ProbOS subscribe to Ward Room post events? Grep for the actual event type and subscription pattern. Likely candidates: `EventType.WARD_ROOM_POST_CREATED`, `WardRoomBus.subscribe(...)`, etc.
- What's the existing infrastructure-tier agent pattern? Grep `tier="infrastructure"` or similar; the EvidenceCollector inherits whatever the canonical pattern is, with no sovereign DID, no trust, no Hebbian.
- LLM client API for fast-tier classification. Pin to whatever AD-700c shipped (per-call tier override) — fast tier per the issue spec.
- Episode anchors / Cognitive Journal: the EvidenceCollector should write structured observations somewhere — confirm the right write path. Spec says `data/research/emergence-evidence/` (file-based), but check if there's a more idiomatic location like the Knowledge Store or ChromaDB.

**Deliverables to spec for the Builder:**

- D1: New module `src/probos/cognitive/evidence_collector.py`:
  - `class EvidenceCollector(BaseAgent)` (or whatever the infrastructure tier base is) — no Hebbian, no trust, no Ward Room participation. Pure observer.
  - Subscribes to Ward Room post events.
  - For each post: builds context (post body + author callsign + recent thread context up to N posts), calls fast-tier LLM with the taxonomy classifier prompt from `emergence_taxonomy.as_classifier_prompt()`, parses response (one or more `BehaviorCode` + confidence in [0,1] + reasoning).
  - Threshold: confidence >= 0.7 for log; below threshold = silent skip.
  - Per-(author, code) dedup window: 600s default, configurable.
  - Writes observation to `data/research/emergence-evidence/<trial-id>/OBS-NNNN.yaml` with: timestamp, author_id, author_callsign, behavior_code(s), confidence, reasoning, post_id, thread_id.
  - Writes to OS-tier file storage; not federation-synced (research artifact only).
- D2: Configuration in `config.py`:
  - `class EmergenceCollectorConfig(BaseModel)` with `enabled: bool = False` (default off — research opt-in), `confidence_threshold: float = 0.7`, `dedup_window_seconds: float = 600.0`, `output_dir: str = "data/research/emergence-evidence"`, `llm_tier: str = "fast"`.
- D3: Wire into `startup/finalize.py` via `_wire_emergence_collector(*, runtime, config)` finalize wirer. Default-disabled.
- D4: Tests at `tests/test_ad454_evidence_collector.py`:
  - Happy path: Ward Room post with clear MGT-DIR pattern → classified, observation written.
  - Confidence below threshold → no write.
  - Dedup: same (author, code) within window → no second write.
  - Anti-pattern detection: post that triggers CASCADE-CONFAB → tagged.
  - Disabled config → wirer no-ops.
  - Concurrent posts → no race on the OBS-NNNN counter.

**Acceptance:** Same standard set, plus the working-tree integrity pre-flight bullet.

**Out of scope:** federation-tier sharing of evidence; LLM-judge meta-evaluation of the classifier's accuracy; auto-paper-generation. Each is a clean follow-up AD.

## Output rules

- Place both prompts under `prompts/`.
- Touch nothing else. Do not modify code, tests, wave-plan.yaml, BUILDER-EXECUTION-PLAN.md, or DECISIONS.md.
- For prompt 1, include all upstream URLs / file paths the Architect actually fetched/read as part of drafting (audit trail).

## Final report

After both prompts are written, return ONE message containing:
1. One-line summary of each prompt.
2. Final taxonomy code count (N) and any architect-proposed additions beyond CASCADE-CONFAB with rationale.
3. Verify-first findings on both prompts (any contradictions with the dispatch).
4. Risk classification per prompt (LOW / MEDIUM / HIGH).
5. Standing-convention concerns surfaced during drafting.

Do not include the prompt bodies in your final message. Return summary only.

## Build phase ordering

Strictly serial: Builder builds prompt 1 (taxonomy + module) first, then prompt 2 (collector imports the module). Both close issue #510 jointly via `Closes #510` on the second commit.
