# AD-727 — Safety constraints for AD-722e self-perception (Wave 154)

**GH:** [#585](https://github.com/seangalliher/ProbOS/issues/585). **Status:** Buildable.

**Must land BEFORE AD-722e (#571).**

## Problem

AD-722e is the first AD in the codebase where the agent gains a capacity that could cause **psychological** harm rather than operational harm. Per Captain ruling 2026-05-10, the safety stack must be ratified in code (not just docs) before AD-722e's capability prompt advances.

## Scope

Three deliverables:

### 1. Ratified DECISIONS.md AD-727 entry

Already filed as a forward marker in DECISIONS.md (see existing AD-727 section). Promote it from forward marker → "Ratified, gate active" by amending the entry's status line. Add cross-link to the new test file.

### 2. `tests/test_ad727_safety_constraints.py` (new)

Static-assertion tests that enforce the seven hard rules at the code level. These tests live forever; they are the durable gate.

Required tests (5 minimum):

1. `test_no_vision_llm_import_in_self_perception_v1` — read the source of `src/probos/cognitive/self_perception.py` (created by AD-722e); assert NO occurrence of `complete(` or `LLMRequest(` or `vision_tier`. Static AST or substring check. Rule #4 — Vision-LLM side-channel ELIMINATED in v1.
2. `test_no_browser_capture_import_in_self_perception_v1` — same file; assert NO occurrence of any of: `getDisplayMedia`, `chrome.tabCapture`, `puppeteer`, `playwright`, `selenium`, `pyppeteer`. Rule #5 — Browser-side capture ELIMINATED in v1.
3. `test_self_perception_projection_signature_forbids_peer_params` — import `project_self_perception`; use `inspect.signature` to assert NONE of `{peer_id, other_agent_id, agent_ids, other_id, peer}` are in `sig.parameters`. (Allowed parameters: `self_id` / `agent_id` and `runtime`.) Rule #7 — comparative perception is a separate AD.
4. `test_self_perception_does_not_call_trust_network` — patch `runtime.trust_network` with a Mock; invoke `project_self_perception`; assert `trust_network.update` / `record_outcome` / any mutation method was called zero times. Rule #1 — aesthetic self-judgment is READ-ONLY w.r.t. trust/Hebbian.
5. `test_self_perception_emits_pipeline_version` — invoke the projection; assert the returned `SelfPerceptionProjection` carries a non-empty `pipeline_version` string. Rule #2 — version the rendering pipeline alongside appearance.

Each test references AD-727 in its docstring. Failures of any of these MUST block CI.

### 3. `docs/architecture/self-perception-framing.md` (new, ~80 lines)

The README/public-framing paragraph required by Rule #8 (mirror-test analog). Plain markdown, no code. Cover:
- "Denser self-state injection, not consciousness."
- The deterministic-projection-only architecture in v1.
- The seven hard rules summarized.
- Forward markers for any future visual extension (AD-722e-2 vision-LLM verification, AD-722e-3 cross-crew).
- Link from README.md (one-line addition under any existing architecture-overview list).

## Out of scope

- Implementing the projection function itself (AD-722e).
- Building the visual extensions (AD-722e-2, AD-722e-3 forward markers).
- Counselor-mediated aesthetic-preference review (AD-721d-2 already covers; cite).

## Acceptance

- 5 new tests pass under `pytest tests/test_ad727_safety_constraints.py -v -n 0`. NOTE: some tests will fail until AD-722e ships — that is intentional and is the gate. **AD-727 commit may NOT include skip markers**; the tests MUST be live and the AD-722e prompt that follows MUST make them pass. Builder: when committing AD-727 in isolation, run focused gate `pytest tests/test_ad727_safety_constraints.py -v` and document which tests are red (those become acceptance criteria for AD-722e).
- DECISIONS.md AD-727 entry status flips from forward marker → ratified.
- `docs/architecture/self-perception-framing.md` exists, linked from README.
- Full test gate runs (other ADs untouched). Vision contract test AD-734 still green.

## Commit

`AD-727: safety constraints for self-perception ratified — joint Counselor+Architect gate (Wave 154). Closes #585.`
