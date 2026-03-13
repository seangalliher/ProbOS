# Phase 20 — Execution Instructions

## How To Use This Document

1. Read `prompts/phase-20-emergent-detection.md` first (the full spec)
2. This document repeats the highest-risk constraints and provides execution-order guidance
3. Follow the steps in order. Run tests after EVERY step

## Critical Constraints (stated redundantly)

### AD Numbering — HARD RULE
- **Current highest: AD-235** (Phase 18b)
- Phase 20 uses: AD-236, AD-237, AD-238, AD-239, AD-240
- VERIFY by reading PROGRESS.md before assigning any AD number
- If AD-235 is NOT the latest, shift ALL AD numbers up accordingly

### Test Gate — HARD RULE
- Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q` after EVERY step
- All 1358 existing tests must continue passing
- Do NOT proceed to the next step if any test fails
- Report test count after each step

### Scope — DO NOT BUILD
- No perception gateways or proactive agents
- No self-directed goal generation
- No policy engine changes  
- No knowledge graph
- No changes to the dream cycle itself
- No new background loop — analysis is on-demand + post-dream
- No changes to BehavioralMonitor
- No formal information-theoretic TC_N — use proxy metric
- No federation-specific detection
- No UI/HXI work beyond shell command

### Layer Violations — DO NOT CROSS
- EmergentDetector is in the **cognitive layer** (`src/probos/cognitive/`)
- It reads from mesh layer (HebbianRouter) and consensus layer (TrustNetwork) — this is allowed (higher reads from lower)
- It MUST NOT write to HebbianRouter, TrustNetwork, or any other subsystem
- It is purely observational — a reader, not a writer

### Existing Code — PRESERVE
- BehavioralMonitor is unchanged. It monitors individual self-created agents
- EmergentDetector monitors population-level dynamics. They are complementary
- IntrospectionAgent gains 2 new intents but all existing intents must work identically
- All existing shell commands must work identically

## Execution Sequence

### Step 1: EmergentDetector module
- **Create** `src/probos/cognitive/emergent_detector.py`
- Pure new file, no existing code changes
- Run tests → expect 1358 pass

### Step 2: Runtime wiring
- **Edit** `src/probos/runtime.py` — create EmergentDetector in start(), add to status(), wire post-dream callback
- Run tests → expect 1358 pass

### Step 3: Introspection agent + MockLLMClient
- **Edit** `src/probos/agents/introspect.py` — add `system_anomalies` and `emergent_patterns` intents
- **Edit** `src/probos/cognitive/llm_client.py` — add MockLLMClient patterns for new intents
- Run tests → expect 1358 pass

### Step 4: Shell command + panel rendering
- **Edit** `src/probos/experience/shell.py` — add `/anomalies` command
- **Edit** `src/probos/experience/panels.py` — add `render_anomalies_panel()`
- Run tests → expect 1358 pass

### Step 5: Tests
- **Create** `tests/test_emergent_detector.py`
- Target ~45-50 tests
- Run tests → expect ~1408 pass
- If any fail, fix before proceeding

### Step 6: PROGRESS.md update
- Update status line with new test count
- Add EmergentDetector to "What's Been Built"
- Add Phase 20 test summary to "What's Working"
- Add AD-236 through AD-240 to "Architectural Decisions"
- Mark "Emergent Behavior Detection" as complete in roadmap

## Key Design Decisions Summary

| AD | File | Decision |
|----|------|----------|
| AD-236 | `emergent_detector.py` | EmergentDetector — population-level dynamics analysis with proxy TC_N, cooperation clusters, trust anomaly detection, routing shift detection, consolidation anomaly detection. Pure reader, no background loop |
| AD-237 | `runtime.py` | Runtime wiring — unconditional creation (no config flag), post-dream analysis trigger, event logging for detected patterns, status() integration |
| AD-238 | `introspect.py` + `llm_client.py` | Two new introspection intents: `system_anomalies` (current anomalies) and `emergent_patterns` (dynamics overview with TC_N, entropy, clusters, trends). Both with `requires_reflect=True` |
| AD-239 | `shell.py` + `panels.py` | `/anomalies` command with `render_anomalies_panel()` showing metrics + pattern table with severity coloring |
| AD-240 | `test_emergent_detector.py` | ~50 tests covering all detectors, runtime integration, introspection, shell/panel |

## Verification Checklist

After completion, verify:
- [ ] `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q` — all tests pass
- [ ] `/anomalies` command works in interactive mode
- [ ] `system_anomalies` and `emergent_patterns` are in decomposer's intent table
- [ ] `status()` dict includes `"emergent"` key
- [ ] Event log records detected patterns with category `"emergent"`
- [ ] EmergentDetector never writes to HebbianRouter or TrustNetwork
- [ ] All 8 existing introspection intents still work
- [ ] PROGRESS.md updated with correct AD numbers and test count
