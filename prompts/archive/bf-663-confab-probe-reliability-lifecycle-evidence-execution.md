# BF-663 Builder Execution — Confab probe reliability/lifecycle/evidence

GitHub issue: #1029  
**Base:** HEAD `509e8cd7`  
**Scope:** execute only `prompts/bf-663-confab-probe-reliability-lifecycle-evidence.md`.

## Read first

- `.github/copilot-instructions.md`
- `prompts/bf-663-confab-probe-reliability-lifecycle-evidence.md`
- `src/probos/cognitive/confab_probe.py`
- `src/probos/cognitive/llm_client.py` cache paths
- `src/probos/cognitive/evidence_collector.py`
- `src/probos/startup/finalize.py`
- `src/probos/startup/shutdown.py`
- `tests/test_ad1121_confab_probe.py`
- `tests/test_ad454_evidence_collector.py`

## Exact files

**Modify:**
- `src/probos/cognitive/confab_probe.py`
- `src/probos/startup/finalize.py`
- `src/probos/startup/shutdown.py`
- `tests/test_ad1121_confab_probe.py`
- `tests/test_ad454_evidence_collector.py`

**Add:**
- `tests/test_bf663_confab_probe_shutdown.py`

Do not modify `LLMRequest`, global cache APIs, config models, trackers, or notification/trust behavior.

## Highest-risk instructions

1. Independence is a **per-sample prompt nonce + fresh request object**. Do not add global cache-control fields or broaden cache-key changes.
2. Keep `probe_referent(llm_client, token, *, ...)` context-free. Never add seed/thread/transcript/runtime parameters.
3. Classifier is strict first-line YES/NO/UNKNOWN. UNKNOWN is abstain, never affirm and never usable.
4. Keep sample count/tier/temperature/threshold unchanged.
5. Explicitly propagate cancellation from probe functions.
6. Shutdown must cancel **and await** probe tasks before `llm_client.close`; do not abandon tasks still using the client.
7. Record-only mode constructs one existing `EvidenceCollector`, requires no LLM/ward room, and registers zero listeners.
8. When emergence classification is also on, reuse the same collector and register exactly one listener.
9. All defaults remain inert.

## Required tests

- unique IDs/nonces and no seed leakage,
- real client/fake transport proves three uncached calls,
- YES/NO/UNKNOWN matrix + common denial/equivocal abstain,
- all UNKNOWN no false flag,
- slow probe cancelled/finished before fake LLM close,
- empty/missing/finished task registry cleanup,
- emergence-only, record-only, both, and all-off wiring,
- divergent record-only CASCADE_CONFAB persistence + one notification.

## Commands

    d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1121_confab_probe.py tests/test_ad454_evidence_collector.py tests/test_bf663_confab_probe_shutdown.py -q -n 0
    d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1119_referent_gate.py tests/test_ad1120_ground_before_collaborate.py tests/test_ad454_taxonomy.py tests/test_ad617_llm_rate_governance.py tests/test_llm_client.py tests/test_ad824_shutdown_hygiene.py tests/test_bf296_shutdown_phase_ordering.py -q -n 0

Set isolated `PROBOS_DATA_DIR` first.

## Stop conditions

Stop if:

- cache independence requires changing `LLMRequest`/global cache contracts,
- any probe remains active when LLM close begins,
- record-only mode registers a listener or needs LLM/ward room,
- more than one collector/listener is created,
- or context-free isolation/notification-only safety weakens.

Do not edit trackers. Do not commit. Report exact test counts and deviations.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
