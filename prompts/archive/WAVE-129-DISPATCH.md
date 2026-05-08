# WAVE 129 DISPATCH — 10-pack drafting

**Wave:** 129
**Mode:** main
**Depends on:** 128
**Builder required:** yes
**Issues to close:** #504, #505, #506, #507, #508, #509, #488, #489, #491, #510
**Date:** 2026-05-08

## Subagent Prompt — Architect (drafting pass)

You are drafting **9 build prompts** for Wave 129. One prompt per AD/BF below. Match the format of `prompts/ad-697-extension-registry-v1.md` and the existing `prompts/ad-581-completion-v1.md` (already drafted in this wave — do not redraft).

For **every** prompt you produce: verify-first against the live codebase before writing. State "Verified Against Codebase (2026-05-08)" with bullet citations of file paths and line ranges. Do not assert any class, method, attribute, or import path that you have not grepped for and confirmed. Apply all 19 standing conventions (see `DECISIONS.md` Wave 5/5-7/8 retrospective entries). Run `scripts/phantom-api-precheck.ps1` mentally as you go — `Class.method` shapes and kwargs must match live signatures.

Each prompt MUST include:
1. Issue number, type, depends_on, wave id (129).
2. Goal — one paragraph.
3. **Verified Against Codebase (2026-05-08)** — bullet list with file:line citations.
4. Scope — what this AD covers and what it explicitly does NOT cover.
5. Deliverables — sections D1, D2, ... each scoped to a single file or a tightly-coupled pair.
6. Non-Goals — explicit "do not change" list (BaseAgent, IntentMessage, RuntimeProtocol, etc.).
7. Acceptance — the exact pytest invocation that must pass (e.g. `pytest tests/test_<adNNN>_*.py -v -n 0` plus `pytest tests/ -q -n 16 --dist=loadfile` green).
8. Tracking — closes which GH issue, DECISIONS.md entry stub.

Tolerance: 1 ⚠️ allowed on the highest-risk prompt (likely AD-633 or AD-607). All others must be ✅ at review pass-2.

### Prompts to draft

1. **`prompts/bf-505-consultation-delivery-wiring-v1.md`** — closes #505.
   - Restore `_wire_consultation_delivery` in `startup/finalize.py` and `ConsultationDeliveryConfig` in `config.py`.
   - Make 3 currently-failing tests in `tests/test_ad594d_delivery_pipeline.py` pass.
   - Verify-first: confirm what the test expects each symbol to look like; do not invent the shape.

2. **`prompts/ad-490-eventlog-hash-chain-v1.md`** — closes #506.
   - Add `prev_hash` + `row_hash` columns to `substrate/event_log.py` events table; migrate existing DBs.
   - `log()` computes `row_hash = sha256(prev_hash || serialized_row)`.
   - Add `verify_chain()` walker that returns `(ok: bool, broken_at: int | None)`.
   - Mirror the pattern in `security/audit.py` (AD-456) — read it before drafting.
   - Tests in new file `tests/test_ad490_eventlog_hash_chain.py`.

3. **`prompts/ad-700a-diagnostic-slash-command-v1.md`** — closes #507.
   - Add `/diagnostic <level> [target]` to the HXI shell (`experience/shell.py` + `experience/panels.py`).
   - Use `DiagnosticLevel.parse_level()` from the AD-700 module already shipped at `src/probos/agents/medical/diagnostic_levels.py`.
   - Issue a `diagnose_system` intent; render result in panels.
   - Tests in `tests/test_ad700a_diagnostic_slash_command.py`.

4. **`prompts/ad-700b-cognitive-journal-level-tagging-v1.md`** — closes #508.
   - Tag `diagnose_system` Cognitive Journal entries with `level` and `level_rank`.
   - Verify-first: read the journal's current write-path; confirm whether free-form metadata is accepted (no schema migration) or requires a column add.
   - Single field addition; tests in `tests/test_ad700b_journal_level_tag.py`.

5. **`prompts/ad-700c-diagnostician-tier-routing-v1.md`** — closes #509.
   - Wire `perceive_result['level_llm_tier']` into the LLM call in `DiagnosticianAgent.decide()` (or its closest equivalent — verify the actual decision path).
   - L1 -> deep, L2/L3 -> fast, L4/L5 -> no LLM (already short-circuit).
   - Verify-first: confirm `cognitive_agent.py` `decide()` supports per-call tier override; if not, surface as blocking sub-AD instead of hacking around it.

6. **`prompts/ad-633-predictive-cognitive-branching-v1.md`** — closes #489. **HIGH RISK — pre-flight extra carefully.**
   - Implements `docs/research/predictive-cognitive-branching.md` minimum-viable scope only.
   - New module `cognitive/predictive_branching.py` with a `PredictiveBrancher` class.
   - One subscription point in proactive cycle that detects "likely upcoming situation" patterns and pre-computes a branch.
   - Cap on branch budget (max N branches in flight, configurable).
   - Tests in `tests/test_ad633_predictive_branching.py`.
   - **Defer**: full cognitive JIT integration; semantic generalization beyond keyword anchors. Document deferred items at the bottom of the prompt.

7. **`prompts/ad-607-memory-security-write-path-v1.md`** — closes #488 (narrowed scope per architectural review). **MEDIUM RISK.**
   - Narrowed: write-path scrubber only. Reject episodes whose `user_input` matches known prompt-injection signatures (basic regex shortlist).
   - Per-source-id rate limit on episode storage.
   - Defer: extraction-rate limit on recall path; full poisoning detection (those wait for federation memory sync, AD-693 commercial).
   - Tests in `tests/test_ad607_memory_security.py`.

8. **`prompts/ad-491-gitagent-interop-adapter-v1.md`** — closes #491.
   - Per the guardrail on the issue: interop boundary only, not internal representation.
   - New module `interop/gitagent.py` with `export_agent_to_gitagent_yaml(agent_id) -> str` and `import_gitagent_yaml(path) -> dict`.
   - The OSS sovereign DID identity stays authoritative — gitagent format is for **publish/install boundary** only.
   - Tests in `tests/test_ad491_gitagent_interop.py`.

9. **`prompts/ad-454-evidence-collector-v1.md`** — closes #510.
   - New infrastructure-tier agent `EvidenceCollector` (no sovereign identity, no Hebbian, no trust).
   - Subscribes to Ward Room post events; classifies via fast-tier LLM against AD-453 taxonomy (10 codes from emergence-evidence-log.md, plus add `CASCADE-CONFAB` per 2026-05-08 finding).
   - Confidence threshold >= 0.7. Per-(agent, behavior_code) dedup window 600s.
   - Writes structured YAML observations to `data/research/emergence-evidence/`.
   - Tests in `tests/test_ad454_evidence_collector.py`.

### Output
Place all 9 prompts under `prompts/`. Touch nothing else.
When the 9 are drafted, report back with a one-line summary per prompt and a list of any verify-first findings that contradicted the issue body (escalate before review pass-1 if any).

---

## Build phase (after prompts pass review)

Standard continuous-build mode per `prompts/BUILDER-EXECUTION-PLAN.md`. Order:

1. `bf-505` (smallest, unblocks AD-594d test suite)
2. `ad-700a`, `ad-700b`, `ad-700c` (AD-700 follow-up cluster)
3. `ad-490` (independent, foundational)
4. `ad-491` (independent, low risk)
5. `ad-454` (independent, observation-only)
6. `ad-607` (medium risk — depends only on existing recall path)
7. `ad-633` (highest risk — keep last)
8. `ad-581-completion` (already drafted; build last so the mesh wiring lands after the new event types)
