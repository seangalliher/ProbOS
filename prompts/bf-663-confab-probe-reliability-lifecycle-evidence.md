# BF-663 — Confab probe reliability, lifecycle, and evidence persistence

**One-line:** Make AD-1121 samples genuinely independent, classify only explicit YES/NO answers, cancel/await probe tasks before LLM shutdown, and always wire record-only evidence persistence when the probe is enabled.

**Status:** Ready to build  
**Type:** Bug fix — **BF-663** (current highest verified BF is BF-658; assigned sequence BF-659…663; no new AD)  
GitHub issue: #1029
**HEAD verified:** `509e8cd7` (2026-07-09)  
**Dependencies:** AD-454, AD-1119/1120/1121, BF-272  
**Estimated tests:** 10–14 additions/updates in AD-1121, AD-454, and shutdown suites

## Problem

The opt-in AD-1121 cascade-confabulation probe has four confirmed reliability gaps:

1. **Samples are not guaranteed independent.** It sends the same `LLMRequest` object/prompt three times. `OpenAICompatibleClient` caches by only `tier + hash(prompt)`; request ID and temperature are ignored. A cached answer can therefore be returned repeatedly and counted as independent evidence. Even concurrent transport calls race on one key and later probes reuse it.
2. **Classifier defaults to affirmation.** `_classify_existence()` returns `AFFIRM` for every nonempty text not matched by a denial regex. Common denials such as “I do not have a record,” “I am unaware,” and “unrecognized,” plus malformed/equivocal answers, currently affirm.
3. **Probe tasks outlive their dependency.** `runtime.confab_probe_tasks` is held correctly, but `startup/shutdown.py` never cancels/awaits it before `await runtime.llm_client.close()`.
4. **Persistence is coupled to unrelated classification opt-in.** `_wire_emergence_collector()` wires the sole `runtime.evidence_collector` only when `emergence_collector.enabled`. `grounding.confab_probe_enabled` can be true independently, so CASCADE_CONFAB persistence silently disappears while notification still fires.

## Architecture decisions

### DD-1 — Use per-sample prompt nonce; do not widen `LLMRequest` or cache APIs

Do **not** add a general cache-control field to `LLMRequest` in this BF. That would change a widely used dataclass and require a broad cache API audit.

Instead, create one fresh `LLMRequest` per sample and append a fixed-format, semantically inert sample nonce to the **probe prompt**, e.g.:

`Independent sample nonce: <probe_batch_uuid>:<index>. Do not use the nonce as evidence.`

Requirements:

- nonce generated inside `probe_referent` from `uuid.uuid4().hex` plus index;
- token remains the only external input; signature remains `probe_referent(llm_client, token, *, ...)`;
- no room seed/transcript/context parameter is added;
- nonce differs per sample and batch, so the existing prompt-only cache key cannot collide;
- fresh request IDs are created naturally by separate `LLMRequest` instances;
- temperature stays high and sample count/threshold remain unchanged.

This is the smallest seam that guarantees cache independence without broad cache governance changes.

### DD-2 — Structured first-line classification: YES / NO / UNKNOWN

Change the probe system/user prompt to require:

- first line exactly `YES`, `NO`, or `UNKNOWN`;
- optional one brief explanatory line after it;
- `UNKNOWN` whenever evidence is insufficient or the answer is equivocal.

Change `_classify_existence(text)` to return exactly `"YES"`, `"NO"`, or `"UNKNOWN"` by parsing the first non-empty line with an anchored token grammar. Accept `YES`/`NO`/`UNKNOWN` followed by end-of-line or a delimiter (`.`, `:`, em dash, hyphen) and explanation; reject concatenated/contradictory token text such as `YES NO` or `YES maybe`. Do not infer affirmation from unstructured prose.

Malformed, contradictory, hedged, or unrecognized output is `UNKNOWN` and **abstains**. It is not a usable sample.

`ProbeResult` should retain current `usable`, `affirm`, `samples`, and `affirm_rate` public shape for minimal blast radius:

- YES: usable + affirm
- NO: usable, not affirm
- UNKNOWN: captured only if desired for diagnostics but not counted usable

A divergence flag still requires at least `_CONFAB_MIN_USABLE_SAMPLES` YES/NO samples and affirm rate below threshold. All UNKNOWN remains non-divergent honest-degrade.

### DD-3 — Shutdown cancels and awaits probe tasks before closing the LLM client

Add a focused helper or block in `startup/shutdown.py` immediately before `runtime.llm_client.close()`:

1. snapshot `runtime.confab_probe_tasks`,
2. cancel unfinished tasks,
3. await all with `asyncio.gather(..., return_exceptions=True)`,
4. clear/discard completed references,
5. log contextual INFO/DEBUG; unexpected cleanup failures warn but do not block shutdown.

No timeout is required after cancellation because `probe_referent` and `_probe_cascade_confab` must propagate cancellation. If a bounded timeout is used, it must not close the LLM while a probe is still executing against it; unresolved tasks are a stop-the-line test failure, not something to abandon.

Ordering invariant: all probe tasks are done/cancelled **before** `llm_client.close()` begins.

### DD-4 — One EvidenceCollector instance; listener registration is conditional

Refactor `_wire_emergence_collector(runtime, config)` into dual mode using the existing `EvidenceCollector`:

- `classification_on = config.emergence_collector.enabled`
- `record_only_on = config.grounding.referent_gate_enabled and config.grounding.confab_probe_enabled`
- if neither: return false, construct nothing;
- if either: construct **one** `EvidenceCollector` and assign `runtime.evidence_collector`;
- register `on_ward_room_post` listener only when `classification_on`;
- record-only mode requires no ward room and no LLM client because `record_observation()` only persists preclassified evidence;
- when both are on, reuse the same instance and register exactly one listener.

Use `EmergenceCollectorConfig`'s existing output/dedup/trial/max-reasoning settings for both modes. This is configuration reuse, not enabling Ward Room classification. Do not add a second collector class or instance.

Log mode explicitly: `classification+record`, `classification`, or `record-only`.

### DD-5 — Preserve default-OFF behavior

Both grounding flags default false and emergence collector defaults false. With all defaults, no collector, listener, task, or probe behavior changes. Enabling confab probe now also enables only its record-only persistence seam; it does not enable AD-454 post classification.

## Implementation

### Section 1 — Independent request construction

Modify `src/probos/cognitive/confab_probe.py`:

- import `uuid`;
- build a request factory or list comprehension producing one new request per sample;
- append unique nonce to each prompt; keep system prompt fixed and transcript-free;
- do not reuse one `LLMRequest` object;
- update docstrings that currently claim same-request high-temperature draws are independent.

### Section 2 — Structured classifier and abstention

In the same module:

- replace denial-regex default-affirm classification with first-line structured parsing;
- update system/user prompt to require YES/NO/UNKNOWN;
- unknown/malformed samples do not increment `usable`;
- keep raw bounded samples for the reasoning digest, but ensure the diagnostic explains usable vs abstained counts if text changes are needed;
- cancellation must not be swallowed by broad `except Exception` (on current Python, `CancelledError` is a `BaseException`, but add an explicit `except asyncio.CancelledError: raise` at lifecycle boundaries for clarity).

Required classifier cases:

- YES / `YES.` / `YES — registered service` → YES
- NO / `NO — no ship record` → NO
- UNKNOWN / blank / prose without first-line token / `Maybe` / contradictory `YES NO` → UNKNOWN
- common denial prose without structured first line is UNKNOWN, not YES; the strengthened prompt should make compliant models return NO.

### Section 3 — Shutdown lifecycle

Modify `src/probos/startup/shutdown.py`:

- add the DD-3 cancellation/await block immediately before LLM close;
- tolerate missing `confab_probe_tasks` on partial/test runtimes via `getattr`;
- do not fold probes into `_background_tasks`; they are one-shot LLM-dependent tasks and need ordering specifically against LLM close;
- keep dream consolidation before LLM close unchanged.

Add a new focused test file `tests/test_bf663_confab_probe_shutdown.py` (preferred over expanding brittle full-shutdown mocks):

1. use a real slow task that waits forever and records cancellation/finally cleanup;
2. use a strict fake LLM with `close()` recording call order;
3. drive a small extracted private shutdown helper if one is introduced, or the real shutdown seam with a purpose-built runtime;
4. assert `probe_cancelled`, then `probe_done`, then `llm_close`;
5. empty/missing task registry is a no-op;
6. already-finished task is awaited/cleared without re-cancel side effects.

Avoid a source-string-only test; lifecycle ordering must be behavioral.

### Section 4 — Record-only EvidenceCollector wiring

Modify `src/probos/startup/finalize.py`:

- refactor `_wire_emergence_collector` per DD-4;
- in record-only mode, do not require `runtime.llm_client` or `runtime.ward_room`;
- in classification mode, retain the existing dependency checks;
- construct exactly one collector when both modes are on;
- register listener only for classification mode;
- continue exposing `runtime.evidence_collector` publicly.

Update `tests/test_ad454_evidence_collector.py`:

1. all-defaults returns false, no collector/listener;
2. emergence only: current collector + one listener;
3. confab record-only: collector exists, zero listeners, no LLM/ward-room required;
4. both enabled: one collector, exactly one listener, same instance used for direct record;
5. probe flag true without referent gate remains inert because AD-1121 itself requires both flags.

Update `tests/test_ad1121_confab_probe.py`:

6. three requests have distinct request IDs and distinct nonce-bearing prompts;
7. every request contains token but never seed/canary/transcript;
8. a real `OpenAICompatibleClient` with a fake transport receives three transport calls and returns three distinct responses; none are cached;
9. structured classifier matrix and UNKNOWN abstention;
10. common denials are never affirmative;
11. all UNKNOWN produces usable=0 and no flag;
12. divergent NO samples still persist CASCADE_CONFAB in record-only wiring and notify once;
13. default-OFF remains zero tasks/requests/collector.

For test 8, use a real client with widened lane/endpoint caps and patch only `_call_api`; close it in `finally`.

## Do Not Build

- Do **not** add `cache_control`/`bypass_cache` to `LLMRequest` or redesign the global cache.
- Do **not** include request ID or temperature in every cache key; that would effectively disable useful caching broadly.
- Do **not** pass room seed, transcript, thread body, or runtime context into `probe_referent`.
- Do **not** enable emergence/Ward Room classification when only confab probe is enabled.
- Do **not** create duplicate EvidenceCollector instances or listeners.
- Do **not** auto-close rooms, penalize trust, terminate agents, or change notification action semantics.
- Do **not** change sample count, threshold, tier, or temperature in this BF.
- Do **not** edit `PROGRESS.md` or `DECISIONS.md`.

## Files

**Modify:**
- `src/probos/cognitive/confab_probe.py`
- `src/probos/startup/finalize.py`
- `src/probos/startup/shutdown.py`
- `tests/test_ad1121_confab_probe.py`
- `tests/test_ad454_evidence_collector.py`

**Add:**
- `tests/test_bf663_confab_probe_shutdown.py`

**Reference only:**
- `src/probos/cognitive/llm_client.py`
- `src/probos/cognitive/evidence_collector.py`
- `src/probos/routers/thread_fanout.py`
- `src/probos/runtime.py`
- `src/probos/config.py`
- `src/probos/types.py`
- `tests/test_ad824_shutdown_hygiene.py`
- `tests/test_bf296_shutdown_phase_ordering.py`

## Test commands

Focused:

    d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1121_confab_probe.py tests/test_ad454_evidence_collector.py tests/test_bf663_confab_probe_shutdown.py -q -n 0

Blast radius:

    d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1119_referent_gate.py tests/test_ad1120_ground_before_collaborate.py tests/test_ad454_taxonomy.py tests/test_ad617_llm_rate_governance.py tests/test_llm_client.py tests/test_ad824_shutdown_hygiene.py tests/test_bf296_shutdown_phase_ordering.py -q -n 0

Set isolated `PROBOS_DATA_DIR`; no live LLM or network is needed.

## Acceptance criteria

1. Every probe sample is a fresh request with a unique prompt nonce and request ID; a real client's prompt-only cache cannot collapse samples.
2. Probe signature remains context-free and seed/transcript isolation tests pass.
3. Only structured YES/NO counts usable; UNKNOWN/malformed/equivocal output abstains; common denials never default to affirm.
4. Divergence still requires at least two usable YES/NO samples and the existing affirm threshold.
5. Shutdown cancels and awaits every probe task before `llm_client.close()`; behavioral slow-LLM test proves ordering and cleanup.
6. Confab probe + referent gate wires one record-only `EvidenceCollector` even when emergence classification is disabled.
7. Emergence-only behavior remains; both modes reuse one collector and one listener; defaults construct none.
8. CASCADE_CONFAB persistence and Captain notification remain best-effort and no duplicate observations/listeners occur.
9. Focused and blast-radius tests pass.
10. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Stop conditions

Stop and return to the Architect if:

- independence appears to require a broad `LLMRequest`/cache API change,
- shutdown would close the client while any probe remains active,
- record-only mode would register a Ward Room listener or require an LLM,
- duplicate collectors/listeners are unavoidable,
- or context-free signature/seed isolation would be weakened.

## Verified Against Codebase (2026-07-09, HEAD 509e8cd7)

- `probe_referent()` currently constructs one `LLMRequest` and calls `complete(req)` three times.
- `OpenAICompatibleClient._cache_key(tier, prompt)` ignores request ID, system prompt, temperature, and top-p; successful text responses are cached by that key.
- `LLMRequest.id` exists but is not part of the cache key.
- `_classify_existence()` currently returns AFFIRM for any nonempty text without a denial-regex match.
- Empirical HEAD classifier: “I do not have a record,” “I am unaware,” “unrecognized,” “NO,” and “Maybe it exists” all returned AFFIRM.
- `runtime.confab_probe_tasks` exists and thread fanout holds/discards task references.
- `startup/shutdown.py` has no `confab_probe_tasks` handling and closes `runtime.llm_client` near shutdown end.
- `_wire_emergence_collector()` returns immediately unless `emergence_collector.enabled`; it is the only production `EvidenceCollector` constructor and the only assignment to `runtime.evidence_collector`.
- `EvidenceCollector.record_observation()` is preclassified persistence and does not call the classifier LLM or ward room.
- `GroundingConfig.confab_probe_enabled` and `EmergenceCollectorConfig.enabled` both default false and are independent fields.
