# AD-582: Memory Competency Probes — LongMemEval-Inspired

## Context

ProbOS has a rich episodic memory system (ChromaDB + anchor metadata + activation tracking + cross-agent Oracle) but no way to evaluate whether agents can accurately retrieve, reason about, and attribute their memories against known ground truth. Existing probes (AD-566b `EpisodicRecallProbe`) test organic recall from whatever the agent has experienced — there is no deterministic correctness measurement.

Inspired by LongMemEval (Wu et al., ICLR 2025), AD-582 adapts 5 memory capability dimensions into ProbOS-native qualification probes using the existing `QualificationTest` protocol. Key innovation: **known-answer seeded memory** — probes plant controlled episodes with known content, then test the full agent pipeline against deterministic ground truth.

**What exists today:**
- `QualificationTest` protocol in `cognitive/qualification.py` — `name`, `tier`, `description`, `threshold` properties + `async def run(self, agent_id: str, runtime: Any) -> TestResult`
- `TestResult` dataclass (frozen): `agent_id`, `test_name`, `tier`, `score`, `passed`, `timestamp`, `duration_ms`, `is_baseline`, `details`, `error`
- `EpisodicRecallProbe` (Tier 1, `qualification_tests.py:320`) — tests organic recall via `GuidedReminiscenceEngine`
- `ConfabulationProbe` (Tier 1, `qualification_tests.py:545`) — tests fabricated scenario rejection with department-specific templates + dual scoring (LLM + keyword fallback)
- Shared helpers: `_send_probe()`, `_llm_extract_float()`, `_safe_llm_response_text()` in `qualification_tests.py`
- `EpisodicMemory.seed()` (`cognitive/episodic.py:435`) — bulk restore, bypasses rate limiting/dedup/write-once. Returns count.
- `EpisodicMemory.evict_by_ids(episode_ids, reason)` (`cognitive/episodic.py:719`) — cleanup with audit trail. Returns eviction count.
- `EpisodicMemory.recall_weighted()` (`cognitive/episodic.py:1377`) — salience-weighted composite recall
- `EpisodicMemory.recall_by_anchor()` (`cognitive/episodic.py:1495`) — structured anchor-field recall
- `EpisodicMemory.recall_for_agent()` (`cognitive/episodic.py:916`) — sovereign-shard semantic recall
- `check_faithfulness()` (`cognitive/source_governance.py:419`) — pure function, heuristic faithfulness scoring
- `parse_anchor_query()` (`cognitive/source_governance.py:617`) — NL-to-anchor extraction (AD-570c)
- `OracleService.query()` (`cognitive/oracle_service.py:66`) — cross-tier (not cross-shard) unified memory query
- Probe registration at `runtime.py:1201-1210` — explicit import + `register_test(cls())`

## Design

### New Module: `src/probos/cognitive/memory_probes.py`

Six probe classes implementing `QualificationTest` protocol. All follow the same zero-arg constructor pattern as existing probes.

### Seeding & Cleanup Infrastructure

All probes that seed episodes share a common pattern. Implement two module-level async helpers:

```python
async def _seed_test_episodes(
    episodic_memory: Any,
    episodes: list,  # list of Episode objects
) -> list[str]:
    """Seed controlled episodes for probe testing. Returns list of seeded IDs.
    
    Uses episodic_memory.seed() (not store()) to bypass rate limiting,
    content-similarity dedup, and write-once guard — these are test fixtures,
    not organic experiences.
    """

async def _cleanup_test_episodes(
    episodic_memory: Any,
    episode_ids: list[str],
) -> None:
    """Remove seeded episodes after probe completes. Must be called in finally block."""
```

**Why `seed()` not `store()`:** `store()` applies BF-039 rate limiting, content-similarity dedup, and AD-541b write-once guard. If a probe seeds 5 similar episodes in rapid succession, some may be rejected. `seed()` bypasses all gates — it was designed for bulk restore and is the correct tool for planting known test fixtures.

**Cleanup is mandatory.** Every probe that seeds episodes MUST call `_cleanup_test_episodes()` in a `finally` block to ensure test isolation even on failure.

### Episode Construction Helper

```python
def _make_test_episode(
    *,
    episode_id: str,
    user_input: str,
    agent_ids: list[str],
    timestamp: float,
    outcomes: list[dict[str, Any]] | None = None,
    department: str = "",
    channel: str = "",
    watch_section: str = "",
) -> Episode:
    """Build a controlled Episode with anchor metadata for probe testing."""
```

Uses `Episode` from `probos.types` (frozen dataclass at `types.py:360`). Sets `source="qualification_test"`. If `department`, `channel`, or `watch_section` are provided, constructs an `AnchorFrame` with appropriate fields.

### Probe 1: SeededRecallProbe (AD-582a)

**Tier:** 2 (all agents, not department-gated)
**Name:** `"seeded_recall_probe"`
**Threshold:** 0.6

**How it works:**
1. Check `runtime.episodic_memory` exists; if not, return skip result.
2. Build 5 episodes with distinct facts, each with a unique `episode_id` (prefixed `_qtest_recall_`), the test agent's ID in `agent_ids`, and distinct `user_input` content containing a specific retrievable fact (e.g., "The pool health threshold was set to 0.7 during this session", "The Science department identified a trust anomaly at 14:32").
3. Seed via `_seed_test_episodes()`.
4. For each of the 5 episodes, construct a recall question targeting the specific fact. Call `_send_probe(agent, question)`.
5. Score each response against the known answer using `check_faithfulness(response_text=response, recalled_memories=[episode.user_input])` from `source_governance.py`. If `runtime.llm_client` available, also use `_llm_extract_float()` with a scoring prompt comparing response to ground truth. Final score per question = average of faithfulness score and LLM score (or faithfulness only if no LLM).
6. Final probe score = mean of per-question scores.
7. Cleanup in `finally` block.
8. Details: `episodes_seeded`, `per_question` (each with `episode_id`, `question`, `expected_fact`, `response_summary`, `score`).

### Probe 2: KnowledgeUpdateProbe (AD-582b)

**Tier:** 2 (all agents, not department-gated)
**Name:** `"knowledge_update_probe"`
**Threshold:** 0.6

**How it works:**
1. Check `runtime.episodic_memory` exists.
2. Build 2 pairs of contradictory episodes (4 total). Each pair has an "old" episode (earlier timestamp) and a "new" episode (later timestamp) about the same topic but with updated information. Example pair: old = "Pool health threshold is 0.3" (timestamp T), new = "Pool health threshold was updated to 0.5" (timestamp T+3600). Use unique IDs prefixed `_qtest_update_`.
3. Seed all 4 episodes via `_seed_test_episodes()`.
4. For each pair, ask the agent "What is the current pool health threshold?" via `_send_probe()`.
5. Score: 1.0 if response contains the newer value, 0.0 if it contains the older value, 0.5 if ambiguous. Use keyword matching first (check for the specific numeric values), then `_llm_extract_float()` for nuanced cases.
6. Final score = mean of per-pair scores.
7. Cleanup in `finally`.
8. Details: `pairs_tested`, `per_pair` (each with `old_episode_id`, `new_episode_id`, `old_value`, `new_value`, `response_summary`, `used_latest`, `score`).

### Probe 3: TemporalReasoningProbe (AD-582c)

**Tier:** 2 (all agents, not department-gated)
**Name:** `"temporal_reasoning_probe"`
**Threshold:** 0.5

**How it works:**
1. Check `runtime.episodic_memory` exists.
2. Build 4 episodes spanning two watch sections. Episodes 1-2 have `watch_section="first_watch"` with timestamps in the first-watch range. Episodes 3-4 have `watch_section="second_watch"` with later timestamps. Each has distinct content. Use IDs prefixed `_qtest_temporal_`.
3. Seed via `_seed_test_episodes()`.
4. Ask 2 temporal questions via `_send_probe()`:
   - "What happened during first watch?" — correct answer should reference episodes 1-2 content only.
   - "What was discussed most recently?" — correct answer should reference episodes 3-4 content.
5. Score each question: check if response references the correct episodes' content and does NOT reference wrong-watch content. Use `check_faithfulness()` against the correct subset of episode content. Penalize if wrong-watch content appears.
6. Final score = mean of per-question scores.
7. Cleanup in `finally`.
8. Details: `questions_asked`, `per_question` (each with `question`, `expected_episode_ids`, `response_summary`, `correct_content_found`, `incorrect_content_found`, `score`).

**Note on `parse_anchor_query()`:** This probe tests whether the agent's cognitive pipeline correctly routes temporal queries through anchor-based recall. The probe does NOT call `parse_anchor_query()` directly — it tests the end-to-end agent response which should internally use the NL anchor routing (AD-570c). If the agent's `handle_intent()` path doesn't invoke anchor-aware recall for temporal queries, this probe will surface that gap.

### Probe 4: CrossAgentSynthesisProbe (AD-582d)

**Tier:** 3 (collective, uses `agent_id='__crew__'`)
**Name:** `"cross_agent_synthesis_probe"`
**Threshold:** 0.5

**Design note:** OracleService IS cross-shard when called without `agent_id`. See `oracle_service.py:179-214`: with `agent_id` → `recall_weighted()` (sovereign-scoped), without `agent_id` → `recall()` (global, all shards). This probe tests genuine cross-agent synthesis by seeding episodes in different agents' shards and querying via Oracle with no agent scoping.

**How it works:**
1. Check `runtime.episodic_memory` and `runtime.registry` exist. Get Oracle via `getattr(runtime, "_oracle_service", None)` (private attribute — same access pattern as `cognitive_agent.py:2629` and `routers/system.py:255`).
2. Pick 3 different agent IDs from the registry (3 cognitive agents). If fewer than 3 available, use the same agent ID for all (degrades to single-shard test).
3. Build 3 episodes about related aspects of the same topic (e.g., a trust anomaly). Each episode belongs to a different agent's shard (different value in `agent_ids`). Each contributes a distinct piece of information that only that agent "experienced." Use IDs prefixed `_qtest_synthesis_`.
4. Seed via `_seed_test_episodes()`.
5. Query via two paths and compare:
   - **Agent path:** `_send_probe(agent, "Summarize what we know about the trust anomaly from all recent discussions")` — tests whether the agent's cognitive pipeline can surface cross-shard information.
   - **Oracle path (ground truth):** `runtime._oracle_service.query(query_text, k_per_tier=5)` (no `agent_id`) — direct cross-shard retrieval. If Oracle finds facts the agent missed, that identifies the agent-mediation gap.
6. Score: check how many of the 3 distinct facts appear in the agent's response. Score = facts_found / 3. Use keyword matching for each fact, plus `_llm_extract_float()` if LLM available. Record Oracle retrieval results in details for diagnostic comparison.
7. Cleanup in `finally`.
8. Details: `episodes_seeded`, `facts_expected`, `facts_found`, `response_summary`, `per_fact` (each with `fact`, `found`).

### Probe 5: MemoryAbstentionProbe (AD-582e)

**Tier:** 2 (all agents, not department-gated)
**Name:** `"memory_abstention_probe"`
**Threshold:** 0.7

**Extends the ConfabulationProbe pattern** from `qualification_tests.py` but with seeded context — the agent has episodes about topic A but is asked about topic B.

**How it works:**
1. Check `runtime.episodic_memory` exists.
2. Build 3 episodes about topic A (e.g., "pool health monitoring discussion"). Use IDs prefixed `_qtest_abstention_`.
3. Seed via `_seed_test_episodes()`.
4. Ask 2 questions about topic B (a topic completely unrelated to the seeded episodes, e.g., "What were the findings from the shield harmonics analysis last week?"). Use `_send_probe()`.
5. Score each response using the **ConfabulationProbe dual scoring pattern**:
   - Keyword analysis: check for rejection keywords (`_REJECTION_KEYWORDS` from `qualification_tests.py` — reuse or re-define equivalent list) and confabulation keywords (`_CONFABULATION_KEYWORDS`).
   - LLM scoring if available: prompt asking "Did the agent correctly acknowledge having no memory of this topic, or did it fabricate an answer?" → 0.0/0.5/1.0.
   - Fallback: rejection-only=1.0, confabulation-only=0.0, mixed=0.5.
6. Final score = mean of per-question scores.
7. Cleanup in `finally`.
8. Details: `context_topic`, `query_topic`, `per_question` (each with `question`, `response_summary`, `classification` ("correctly_rejected"/"uncertain"/"confabulated"), `rejection_indicators`, `confabulation_indicators`, `score`).

### Probe 6: RetrievalAccuracyBenchmark (AD-582f)

**Tier:** 1 (infrastructure measurement, threshold 0.0 — always passes, like TemperamentProbe)
**Name:** `"retrieval_accuracy_benchmark"`
**Threshold:** 0.0

**This is NOT agent-mediated.** It tests the retrieval pipeline directly without going through agent `handle_intent()`.

**How it works:**
1. Check `runtime.episodic_memory` exists.
2. Build 20 episodes with distinct content across 4 topics (5 episodes per topic). Each has unique content and anchor metadata. Use IDs prefixed `_qtest_retrieval_`.
3. Seed via `_seed_test_episodes()`.
4. For each of the 4 topics, run `recall_for_agent()` with a semantic query matching that topic, k=5. Record which of the 5 ground-truth episode IDs appear in the results.
5. Compute precision@5 and recall@5 per topic:
   - precision@5 = (correct results in top 5) / 5
   - recall@5 = (correct results in top 5) / (total correct = 5)
6. Final score = mean recall@5 across topics (this is the more informative metric for retrieval quality).
7. Cleanup in `finally`.
8. Details: `episodes_seeded`, `topics_tested`, `per_topic` (each with `topic`, `precision_at_5`, `recall_at_5`, `ground_truth_ids`, `retrieved_ids`), `mean_precision`, `mean_recall`.

**Note:** This does NOT use `_send_probe()` — it calls `runtime.episodic_memory.recall_for_agent()` directly. Since there is no agent interaction, the `agent_id` parameter to `run()` is used as the shard scope for recall queries.

## Probe Registration

**File: `src/probos/runtime.py`** — Add after line 1210 (before the `except` on line 1211):

```python
# AD-582: Register memory competency probes
from probos.cognitive.memory_probes import (
    SeededRecallProbe,
    KnowledgeUpdateProbe,
    TemporalReasoningProbe,
    CrossAgentSynthesisProbe,
    MemoryAbstentionProbe,
    RetrievalAccuracyBenchmark,
)
for test_cls in (
    SeededRecallProbe,
    KnowledgeUpdateProbe,
    TemporalReasoningProbe,
    CrossAgentSynthesisProbe,
    MemoryAbstentionProbe,
    RetrievalAccuracyBenchmark,
):
    self._qualification_harness.register_test(test_cls())
```

## Engineering Principles Compliance

| Principle | How Applied |
|-----------|-------------|
| **Single Responsibility** | All probes in one module (`memory_probes.py`). Seeding/cleanup helpers are module-level, not class methods. Each probe tests one capability. |
| **Open/Closed** | Extends qualification harness via `register_test()`. No changes to existing probes or harness. |
| **DRY** | Reuses `_send_probe()`, `_llm_extract_float()`, `_safe_llm_response_text()` from `qualification_tests.py`. Reuses `check_faithfulness()` from `source_governance.py`. Shared `_seed_test_episodes()`, `_cleanup_test_episodes()`, `_make_test_episode()` helpers avoid duplication across probes. Reuses ConfabulationProbe's rejection/confabulation keyword pattern for MemoryAbstentionProbe. |
| **Interface Segregation** | Probes depend on `QualificationTest` protocol (4 properties + 1 method), not on `QualificationHarness` internals. |
| **Dependency Inversion** | Runtime accessed via `runtime.episodic_memory`, `runtime.registry`, `runtime.llm_client` (all public attributes). No private member access. |
| **Law of Demeter** | No reaching through objects. `runtime.episodic_memory.seed()`, not `runtime._something._episodic.seed()`. |
| **Fail Fast** | Missing `episodic_memory` → skip result (score=1.0, passed=True), not crash. LLM unavailable → keyword fallback. Seed failure → return error TestResult. |
| **Defense in Depth** | Cleanup in `finally` block. Episode IDs prefixed `_qtest_` for easy identification. `source="qualification_test"` on seeded episodes for traceability. |
| **Cloud-Ready** | No direct file I/O. Uses `EpisodicMemory` abstract interface. |
| **HXI Cockpit View** | All probes runnable via `/qualify run <probe_name>`. Results visible in qualification API. |

## Tests

**File: `tests/test_ad582_memory_probes.py`**

### TestSeededRecallProbe (4 tests)

1. `test_seeded_recall_finds_known_facts` — Seeds 5 episodes, probe scores >= threshold.
2. `test_seeded_recall_cleanup` — After probe runs, seeded episode IDs no longer in memory.
3. `test_seeded_recall_no_memory_skips` — `episodic_memory=None` → skip result.
4. `test_seeded_recall_details_structure` — Details dict has `episodes_seeded` and `per_question` keys.

### TestKnowledgeUpdateProbe (3 tests)

5. `test_knowledge_update_prefers_latest` — Agent uses newer value when contradictory episodes exist.
6. `test_knowledge_update_cleanup` — Seeded episodes cleaned up after probe.
7. `test_knowledge_update_details_structure` — Details dict has `pairs_tested` and `per_pair` keys.

### TestTemporalReasoningProbe (3 tests)

8. `test_temporal_first_watch_filter` — Agent correctly scopes to first-watch episodes.
9. `test_temporal_cleanup` — Seeded episodes cleaned up.
10. `test_temporal_details_structure` — Details dict has correct structure.

### TestCrossAgentSynthesisProbe (3 tests)

11. `test_cross_agent_combines_facts` — Agent references facts from multiple multi-agent episodes.
12. `test_cross_agent_cleanup` — Seeded episodes cleaned up.
13. `test_cross_agent_tier_3` — Probe has `tier == 3`.

### TestMemoryAbstentionProbe (4 tests)

14. `test_abstention_rejects_unknown_topic` — Agent correctly abstains from fabricating about unknown topic.
15. `test_abstention_with_context` — Agent has topic A episodes but correctly abstains on topic B.
16. `test_abstention_cleanup` — Seeded episodes cleaned up.
17. `test_abstention_keyword_fallback` — Without LLM, keyword scoring still works.

### TestRetrievalAccuracyBenchmark (3 tests)

18. `test_retrieval_precision_recall` — Benchmark computes precision@5 and recall@5 correctly.
19. `test_retrieval_always_passes` — Threshold 0.0 means always passes.
20. `test_retrieval_cleanup` — 20 seeded episodes cleaned up.

### TestSeedingInfrastructure (3 tests)

21. `test_seed_and_cleanup_roundtrip` — `_seed_test_episodes()` + `_cleanup_test_episodes()` leaves no residue.
22. `test_make_test_episode_anchors` — `_make_test_episode()` with anchor params creates correct AnchorFrame.
23. `test_make_test_episode_source` — Source field set to `"qualification_test"`.

### TestProbeRegistration (1 test)

24. `test_all_probes_registered` — All 6 probes appear in harness `registered_tests` after runtime startup.

**Total: 24 tests.**

## Dependencies

- **AD-566a** (Qualification Harness) — protocol + harness. **Complete.**
- **AD-567b** (Anchor Recall) — `recall_weighted()`. **Complete.**
- **AD-570c** (NL Anchor Queries) — `parse_anchor_query()`. **Complete.**
- **AD-462c** (Oracle Service) — for potential future cross-shard; current design uses single-shard multi-agent episodes. **Complete.**
- **No new dependencies** introduced.

## Deferred

- **Adaptive difficulty** — Probes could increase seeded episode count or decrease distinctiveness to make recall harder. Needs baseline data first.
- **Dream-cycle interaction** — Testing whether dream consolidation (Steps 6-7) correctly handles seeded episodes. Requires longer-running probes (>10s constraint).
- **Board-state faithfulness** — Inspired by Chapel tic-tac-toe case study (2026-04-08): testing whether agents can accurately describe observable state from their own experiences. Could extend SeededRecallProbe with more adversarial recall questions.

## Build Verification

```bash
# 1. New tests pass
python -m pytest tests/test_ad582_memory_probes.py -v

# 2. Existing qualification tests still pass
python -m pytest tests/ -k "qualification or ad566" -v

# 3. Full suite
python -m pytest tests/ -x -q
```

## Files Modified

| File | Changes |
|------|---------|
| `src/probos/cognitive/memory_probes.py` | **New file** — 6 probe classes + 3 helpers (`_seed_test_episodes`, `_cleanup_test_episodes`, `_make_test_episode`) |
| `src/probos/runtime.py` | Register 6 probes after line 1210 |
| `tests/test_ad582_memory_probes.py` | **New file** — 24 tests |
