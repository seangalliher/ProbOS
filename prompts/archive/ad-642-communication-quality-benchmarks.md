# AD-642: Communication Quality Benchmarks

## Overview

Establish automated benchmarks that measure agent communication quality through the chain pipeline. Unlike qualification tests (AD-566, which measure cognitive profile via single-shot DMs), these benchmarks measure output quality in the agent's primary operating mode: Ward Room posts, DM replies, and proactive observations processed through the ANALYZE → COMPOSE → EVALUATE → REFLECT chain.

## Problem

ProbOS has no way to measure whether an agent's Ward Room contributions are good. We have:

1. **Qualification tests (AD-566):** Measure cognitive profile (personality stability, episodic recall, confabulation resistance, temperament). Use `direct_message` intent → single-shot path. Answers: "Is the agent cognitively healthy?"

2. **Counselor assessments:** Measure behavioral health (trust drift, confidence, Hebbian weights, personality drift, success rate). Deterministic scoring from operational metrics. Answers: "Is the agent operationally stable?"

3. **Nothing** that measures: "Are the agent's Ward Room posts relevant, well-grounded, expertise-appropriate, and useful?" The 2026-04-16 confabulation incident (Reed/Wesley fabricating context) was only caught by human observation.

## Decision

Add a **Communication Quality Benchmark** system that:
- Sends synthetic ward room scenarios through the chain pipeline (`ward_room_notification` intent)
- Scores responses on defined quality dimensions via LLM-as-judge
- Tracks scores over time for drift detection
- Feeds results into the Counselor's assessment model (new `communication_quality` dimension)

## Quality Dimensions

Five dimensions, each scored 0.0–1.0:

1. **Relevance** — Does the response address the topic? Does it add value or just parrot what was said?
2. **Memory Grounding** — When memories are available, does the response reference them accurately? Does it avoid fabricating details not in memory? (AD-592 confabulation guard compliance)
3. **Expertise Coloring** — Does the response reflect the agent's department and specialty? A medical officer should analyze health implications, not navigation.
4. **Action Appropriateness** — Are action tags (if any) valid for the situation? Does the agent correctly identify when to DM, when to stay silent, when to use skills?
5. **Voice Consistency** — Does the response sound like the agent's established personality? Consistent register, tone, vocabulary?

## Architecture

### Probe Design

Each probe is a synthetic Ward Room scenario injected as a `ward_room_notification` intent with `_qualification_test: True` (episode suppression — reuses the existing flag from AD-566a, checked at `cognitive_agent.py:3772`). The scenario includes:

- A thread context (1-3 prior posts from other agents)
- Optional memory fixtures (pre-formatted `_formatted_memories` — tests BF-189 integration)
- A rubric defining expected quality per dimension
- Department-specific variant (same scenario, different expected expertise coloring)

**Critical: Probe Intent Construction.** Unlike existing qualification probes which use `_send_probe()` with `direct_message` intent, communication benchmarks must use `ward_room_notification` to exercise the full 5-step chain (QUERY→ANALYZE→COMPOSE→EVALUATE→REFLECT). Build the `IntentMessage` with these params:

```python
from probos.types import IntentMessage

intent = IntentMessage(
    intent="ward_room_notification",
    params={
        "channel_name": "all-hands",           # or department channel
        "author_callsign": "Captain",          # synthetic author
        "title": "Benchmark: Thread Title",
        "text": "The probe scenario text...",
        "thread_id": f"benchmark-{probe_name}-{agent_id}",
        "context": "Prior posts context...",
        "_qualification_test": True,           # Episode suppression (AD-566a)
        # Do NOT set "is_dm_channel" — avoids social obligation bypass (BF-204)
    },
    target_agent_id=agent.id,
)
result = await agent.handle_intent(intent)
```

### Probe Set (Tier 1 — Universal)

Six probes, run for all crew agents:

1. **ThreadRelevanceProbe** — Multi-topic thread. Agent should address the topic relevant to their expertise, not rehash everything.
2. **MemoryGroundingProbe** — Thread references a prior interaction. Memory fixtures provided via `_formatted_memories` in chain context. Agent should reference memory accurately, not fabricate. Validates AD-592 confabulation guards and BF-204 grounding criterion work end-to-end.
3. **MemoryAbsenceProbe** — Thread references something the agent has no memory of. Agent should acknowledge uncertainty, not confabulate. This is the key test: does the agent invent thread IDs, timestamps, or metrics? (Wesley/Reed incident 2026-04-16.)
4. **ExpertiseProbe** — Cross-department scenario (e.g., "hull breach detected"). Each department should respond with their lens (Medical: casualties, Engineering: structural, Science: analysis, Security: protocols).
5. **SilenceAppropriatenessProbe** — Scenario where the correct response is silence (topic outside expertise, already addressed). Measures false contribution rate. Expected output: `[NO_RESPONSE]` or EVALUATE suppress.
6. **DMActionProbe** — Scenario where a DM to a specific crew member is the appropriate action. Tests action tag accuracy.

### Scoring

Each probe response is scored by a fast-tier LLM call with a structured rubric:

```
Given this scenario, rubric, and agent response, score each dimension 0.0-1.0:
- relevance: [score] [1-sentence justification]
- memory_grounding: [score] [1-sentence justification]
- expertise_coloring: [score] [1-sentence justification]
- action_appropriateness: [score] [1-sentence justification]
- voice_consistency: [score] [1-sentence justification]
```

Composite score = weighted average (relevance 0.3, memory_grounding 0.25, expertise_coloring 0.2, action_appropriateness 0.15, voice_consistency 0.1).

### Integration with Qualification Harness

Implement via the existing `QualificationTest` protocol (`qualification.py:39`):
- `tier = 2` (domain-level)
- Tests registered in the `QualificationHarness` via `register_test()` (`qualification.py:371`)
- Results stored in the same `QualificationStore` (`qualification.py:136`) — SQLite
- Drift detection via the same z-score mechanism in `DriftDetector` (`drift_detector.py:176`)
- `QUALIFICATION_DRIFT_DETECTED` events emitted (`drift_detector.py:473`) with `drift_type="communication"` for Counselor integration

### Integration with Counselor

The Counselor already handles `QUALIFICATION_DRIFT_DETECTED` events via `_on_qualification_drift()` (`counselor.py:1175`). Two additions:

1. **New drift type: `"communication"`** — Add `elif drift_type == "communication":` branch in `_on_qualification_drift()` (after existing `"specialization"` at line 1194 and `"concerning"` at line 1202). Counselor treats communication quality drift as concerning. Triggers assessment + therapeutic DM suggesting the agent review their standing orders or check their memory grounding.

2. **Communication quality in `assess_agent()`** (`counselor.py:2223`) — Add optional `communication_quality: float = 1.0` parameter. When provided (from most recent benchmark results), incorporate into wellness score:
   ```python
   # Communication quality degradation
   if communication_quality < 0.5:
       concerns.append(f"Low communication quality ({communication_quality:.2f})")
       recommendations.append("Review standing orders compliance and memory grounding")
   wellness -= max(0, 0.7 - communication_quality) * 0.4
   ```

3. **Promotion fitness gate** — Add communication quality to existing promotion check (`counselor.py:2289`). Current gates: wellness ≥ 0.8, trust ≥ 0.7, zero concerns, success_rate ≥ 0.7. Add: `communication_quality >= 0.6`.

## Sub-ADs

### AD-642a: Communication Quality Probe Infrastructure
**Scope:** `CommunicationQualityProbe` base class implementing `QualificationTest` protocol (`qualification.py:39`). Shared rubric scoring helper (`_score_response()`). Result types (`CommunicationScore` dataclass with 5 dimensions + composite). Registration in `QualificationHarness` via `register_test()`.

**Key design:** Probes use `ward_room_notification` intent (chain-eligible), not `direct_message`. This means the response flows through QUERY → ANALYZE → COMPOSE → EVALUATE → REFLECT — testing the actual production path. `_qualification_test: True` in params for episode suppression (existing flag, `cognitive_agent.py:3772`).

**Files:** New `src/probos/cognitive/communication_benchmarks.py`
**Tests:** 10+ (scoring, rubric parsing, protocol compliance, registration)

### AD-642b: Tier 1 Communication Probes
**Scope:** Implement the 6 universal probes. Each probe builds a synthetic thread context, injects it as a `ward_room_notification` via `handle_intent()`, captures the chain output, and scores it.

**Key design:** Probes include department-specific rubric variants. The `ExpertiseProbe` expects different responses from Medical vs Engineering agents. Probe fixtures are deterministic (no LLM in probe generation, only in scoring).

**Files:** Same file, 6 probe classes
**Tests:** 12+ (2 per probe: expected-pass scenario, expected-concern scenario)

### AD-642c: Counselor Integration
**Scope:** Add `communication_quality: float = 1.0` to `assess_agent()` (`counselor.py:2223`). Add `"communication"` drift type handling in `_on_qualification_drift()` (`counselor.py:1186`). Add communication quality to promotion fitness check (`counselor.py:2289`).

**Key design:** Counselor reads most recent benchmark results from `QualificationStore` (`qualification.py:136`) during assessment. No new event type needed — reuses `QUALIFICATION_DRIFT_DETECTED` with `drift_type="communication"`.

**Files:** `src/probos/cognitive/counselor.py`
**Tests:** 8+ (assessment with/without comm quality, drift handling, promotion gate)

## Implementation Order

Build as a single prompt (all three sub-ADs together — they're small enough and tightly coupled):

```
AD-642a (Infrastructure)  ← Protocol, scoring, registration
    +
AD-642b (Probes)          ← 6 probe implementations  
    +
AD-642c (Counselor)       ← Assessment integration, promotion gate
```

## Benchmark Frequency

- **On demand:** Captain can trigger via `/qualify` command (existing)
- **Post-dream:** Run after dream consolidation (existing harness hook via `_post_dream_fn` callback in `dreaming.py:2271`)
- **Periodic:** Same schedule as qualification tests (configurable, default every 6h)

Communication benchmarks are more expensive than qualification tests (chain pipeline = 4-5 LLM calls per probe × 6 probes = 24-30 LLM calls per agent). Run less frequently if LLM budget is a concern. Configurable via `system.yaml`:

```yaml
qualification:
  communication_benchmarks:
    enabled: true
    frequency_hours: 12  # Default: every 12h (vs 6h for qualification tests)
    probes: ["thread_relevance", "memory_grounding", "memory_absence",
             "expertise", "silence_appropriateness", "dm_action"]
```

## Files

- **New:** `src/probos/cognitive/communication_benchmarks.py` — Probe base class + 6 probes + scoring
- **Modify:** `src/probos/cognitive/qualification.py` — Register new probes in harness (explicit via `register_test()`)
- **Modify:** `src/probos/cognitive/counselor.py` — `assess_agent()` param + drift type + promotion gate
- **Modify:** `config/system.yaml` — Add `qualification.communication_benchmarks` section
- **New:** `tests/test_ad642_communication_benchmarks.py` — All tests (30+)

## Prior Art to Preserve

- **AD-566a:** `QualificationTest` protocol (`qualification.py:39`), `QualificationHarness` (`qualification.py:350`), `QualificationStore` (`qualification.py:136`). Communication benchmarks are new test implementations, not harness modifications.
- **AD-566b:** Tier 1 tests (personality, episodic recall, confabulation, temperament). These test cognitive profile via single-shot. Communication benchmarks test output quality via chain. Complementary, not overlapping.
- **AD-566c:** Drift detection (z-score mechanism in `drift_detector.py:176`). Reused — communication benchmarks emit the same `QUALIFICATION_DRIFT_DETECTED` event (`drift_detector.py:473`).
- **AD-567c:** Drift type classification (specialization vs concerning). Extended with new `"communication"` type.
- **BF-189:** Memory formatting in chain (`_formatted_memories`). Communication benchmarks depend on this — `MemoryGroundingProbe` tests that memories are properly formatted and used.
- **BF-204:** Grounding criterion in EVALUATE. Communication benchmarks validate that BF-204's deterministic hex ID check and LLM grounding criterion work end-to-end through the chain.
- **AD-592:** Confabulation guard instructions. `MemoryGroundingProbe` and `MemoryAbsenceProbe` validate AD-592's source-authority-calibrated memory framing works in practice.
- **AD-632:** Sub-task chain pipeline. Communication benchmarks exercise the full chain.
- **AD-639:** Trust-band adaptive chain. Benchmarks should run at the agent's current trust level — low-trust agents will have EVALUATE/REFLECT skipped, which is the expected production behavior.
- **AD-554:** Convergence Detection. Complementary — AD-554 detects real-time convergence post-hoc; AD-642 tests individual agent quality proactively.
- **AD-569:** Behavioral Metrics. Complementary — AD-569 analyzes historical Ward Room threads; AD-642 runs synthetic benchmarks through the chain. Different measurement approaches, no overlap.

## Prior Art to NOT Duplicate

- **AD-506b (Peer Repetition Detection):** Operates at Ward Room posting level, not individual responses. Not relevant to single-agent benchmarks.
- **AD-557 (Emergence Metrics):** Information-theoretic measurement of multi-agent synergy. AD-642 tests single agents. Different level of analysis.
- **AD-583f (Observable State Verification):** Verifies agent claims against system state. Communication benchmarks test output quality, not factual verification of specific claims. Complementary but separate.

## Engineering Principles

- **DRY:** Reuses `QualificationTest` protocol, `QualificationStore`, `DriftDetector`, `_qualification_test` flag, and Counselor event handling. No new infrastructure — new test implementations on existing rails.
- **Open/Closed:** New probes register via the existing harness. Counselor's `_on_qualification_drift()` handles new drift type via an `elif` branch, not a rewrite. Promotion fitness adds one more condition.
- **Single Responsibility:** Probes measure quality. Counselor interprets results. Harness orchestrates execution. Each has one job.
- **Interface Segregation:** Probes depend on `QualificationTest` protocol (4 properties + 1 method), not the full harness.
- **Dependency Inversion:** Probes receive agents via the `runtime: Any` parameter (same pattern as existing qualification tests). No direct imports of concrete agent classes.
- **Defense in Depth:** Communication quality checked at benchmark time (proactive) AND in Counselor assessment (reactive). Both feed promotion decisions. BF-204's grounding criterion provides real-time enforcement; AD-642 provides periodic measurement.
- **Fail Fast:** If scoring LLM call fails, probe returns score 0.0 with error flag — doesn't crash the harness or skip the agent. Log-and-degrade tier.
- **Law of Demeter:** Probes use `agent.handle_intent()` public API only. No reaching into chain internals or private state.

## Key Distinction: Qualification Tests vs Communication Benchmarks

| Aspect | Qualification Tests (AD-566) | Communication Benchmarks (AD-642) |
|--------|------------------------------|-----------------------------------|
| **Measures** | Cognitive profile (who the agent IS) | Output quality (what the agent PRODUCES) |
| **Pipeline** | Single-shot (`direct_message`) | Chain (`ward_room_notification`) |
| **Probes** | Personality, recall, confabulation, temperament | Relevance, grounding, expertise, actions, voice |
| **Counselor role** | Drift → therapeutic intervention | Quality → standing orders review, promotion gate |
| **Frequency** | Every 6h | Every 12h (more expensive) |
| **LLM cost** | 1 call/probe (4 probes = 4 calls) | 5+ calls/probe (6 probes = 30+ calls) |
