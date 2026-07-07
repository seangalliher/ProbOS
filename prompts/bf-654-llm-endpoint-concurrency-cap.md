# BF-654: Per-endpoint in-flight concurrency cap for the LLM client

**One-line:** Bound total simultaneous requests to each LLM upstream (the shared Copilot proxy) with a per-`base_url` in-flight semaphore, composing with — not replacing — the AD-636 priority lanes, so a boot burst can't overwhelm the proxy into an empty-content storm.

**Status:** Ready to build
**Type:** BF (bug fix) — assign **BF-654** (verified next free; highest shipped is BF-653)
**GitHub issue:** seangalliher/ProbOS#1017
**Dependencies:** none (additive over AD-636 lanes + BF-612 recycle)
**Estimated tests:** ~9 new (one file) + 3 existing suites must stay green
**Target files:**
- `src/probos/config.py` (1 new field on `LLMRateConfig`)
- `src/probos/cognitive/llm_client.py` (`__init__` block + `complete()` acquire + 1 import; optional Section 3 in `_complete_inner`)
- `tests/test_bf654_endpoint_concurrency_cap.py` (new)

---

## 1. Problem (telemetry-verified)

On `probos serve` boot, a burst of concurrent LLM calls (warm boot + ~80 agents + the proactive loop's `analyze`/triage sub-tasks) overwhelms the Copilot proxy at `http://127.0.0.1:8080/v1`, which responds with **empty-content HTTP 200s** and disconnects. Direct proxy probes (single / 10-concurrent / 33K-prompt / all model variants) ALL succeed — the proxy is healthy for isolated and moderate load. The failures cluster **only** during the boot burst.

`fast`, `standard`, `deep` ALL target the same endpoint (`127.0.0.1:8080/v1`); `vision`/`vision_fast` target ollama (`11434`). The client already has AD-636 priority-lane semaphores, an AD-617 RPM limiter, and the BF-612 empty-200 recycle-retry — yet the burst still overwhelms the proxy.

### Root cause (the fail-open flood)

There is exactly **one** `OpenAICompatibleClient` instance (`src/probos/__main__.py:290`), so the AD-636 `_interactive_semaphore`/`_background_semaphore` are **global across all tiers** — a lane cap of `interactive_reserved (2) + background (4) = 6`. But the acquire path **fails open** under sustained contention (`llm_client.py:536-543`):

```python
sem = self._interactive_semaphore if priority == Priority.CRITICAL else self._background_semaphore
try:
    await asyncio.wait_for(sem.acquire(), timeout=30.0)
except asyncio.TimeoutError:
    logger.warning("AD-636: %s semaphore acquisition timed out, proceeding without", priority)
    sem = None  # ← proceeds WITHOUT any concurrency bound
```

At boot, ~80 background calls arrive nearly simultaneously. The first ~4 acquire the background lane; the remaining ~76 queue on `sem.acquire()`. Because the in-flight calls can be slow (deep tier httpx timeout is up to 300s), the ~76 queued calls **all time out at ~30s together** → each falls into the `sem = None` branch → **dozens of requests hit the proxy at once** → the empty-content storm. The AD-636 lane cap is defeated by its own fail-open in exactly the boot-burst condition it was meant to smooth.

---

## 2. Research answers (file:line)

**Q1 — One client for all tiers, or one per tier?**
**ONE client instance serves ALL tiers.** The only production construction site is `src/probos/__main__.py:290`:
```python
client = OpenAICompatibleClient(config=cog, rate_config=config.llm_rate)
```
handed to the runtime at `__main__.py:571` (`llm_client=llm_client`) and shared by every pool/agent (`cognitive_agent.py:591` `self._llm_client = kwargs.get("llm_client")`). So `self._interactive_semaphore`/`self._background_semaphore` (`llm_client.py:192-193`) **already bound concurrency GLOBALLY across all tiers**, by priority lane. The problem is NOT per-tier semaphore multiplication — it's the **fail-open** (§1) that converts the global lane cap into unbounded concurrency under the boot burst. => The fix is a hard per-endpoint backstop that does not fail-open the same way, not a re-architecture of the lanes.

**Q2 — Tier → base_url → client/pool mapping.**
`CognitiveConfig.tier_config(tier)` (`config.py:433`, resolution at `config.py:519`) returns `base_url = url_map.get(tier) or self.llm_base_url`. Per-tier `llm_base_url_{fast,standard,deep}` default `None` (`config.py:190-200`) → all three fall back to the shared `llm_base_url` (`config.py:162`, default `http://127.0.0.1:8080/v1`). `llm_base_url_vision`/`_vision_fast` (`config.py:212,241`) point at ollama (`11434`). httpx clients are pooled per **`_client_key(tier)` = `f"{base_url}|{api_format}"`** (`llm_client.py:211-214`), deduped into `self._clients` at `llm_client.py:148-153`. => `fast`/`standard`/`deep` share ONE httpx client (`http://127.0.0.1:8080/v1|openai`); `vision` gets a SEPARATE client on the ollama base_url. There is a `_build_client(tier)`/`_refresh_client(tier)` pair (BF-612) keyed by the same `_client_key`.

**Q3 — Semaphore sizes; RPM per-tier or global.**
Sizes are **config-driven** from `LLMRateConfig` (`llm_client.py:183-193`): `max_concurrent_calls` (default 6) and `interactive_reserved_slots` (default 2) → `_background_slots = max(1, 6-2) = 4`. Total concurrency permitted to the proxy today (in steady state, before fail-open) = **6**. The RPM limiter `_wait_for_rate_limit` (`llm_client.py:318`) is **per-tier** (a `deque` per tier in `self._request_timestamps`, `rpm_limits.get(tier, 60)`) — it is a requests-per-**minute** throttle, not a simultaneous-in-flight bound, and does not prevent a synchronized burst from being in flight at the same instant.

**Q4 — Which lane do boot calls use?**
**BACKGROUND.** `Priority.classify` (`types.py:95`) routes `proactive_think → LOW` and everything non-Captain/non-mention/non-DM → `NORMAL`; both LOW and NORMAL use the background lane (only `CRITICAL` uses the interactive lane — `complete()` selects `_interactive_semaphore` iff `priority == Priority.CRITICAL`). The boot-burst call sites confirm background:
- sub-tasks call `complete(request)` with **no `priority=`** (→ default `Priority.NORMAL`): `analyze.py:588`, `compose.py:657`, `evaluate.py:638`, `reflect.py:516`.
- `cognitive_agent.py:4876,5103,10015` use `priority=Priority.NORMAL`.
- Only `proactive.py:3529` (and Captain-DM/@mention paths) use `Priority.CRITICAL`.

So the boot burst is overwhelmingly the **background** lane — which is exactly the lane whose fail-open floods the proxy. This is what the fix must bound; the interactive lane must stay unthrottled (AD-636's "never block the Captain").

---

## 3. Solution

Add a **per-endpoint in-flight semaphore**, keyed by `_client_key(tier)` (`base_url|api_format` — the same key as the httpx pool), acquired in `complete()` **around the whole `_complete_inner` call**, applied to **background/NORMAL/LOW** calls only. `CRITICAL` (interactive) calls **bypass** the endpoint cap.

Why acquire in `complete()` (not inside `_complete_inner` per `_call_api`):
- The endpoint for a request is fixed by `request.tier` — the text fallback chain (`fast→standard→deep`) stays within the **same** base_url (all `127.0.0.1:8080`), and `vision`/`compute_use`/`image_gen` never fall back off their endpoint (BF-269 invariant, `llm_client.py:591-604`). So the endpoint key computed from `request.tier or self.default_tier` is correct for the entire call, including the BF-612 retry.
- Keeping the acquire in `complete()` means **`_complete_inner`'s signature is unchanged** — the existing tests that replace `_complete_inner` with a positional-only fake (`test_ad636…::test_concurrent_calls_respect_cap`'s `slow_complete(req)`) and `AsyncMock` stay green untouched.
- Holding the slot across the (rare) 429 backoff / BF-612 recycle is conservative backpressure (fewer concurrent to a struggling proxy) — the safe direction.

Vision/ollama is unaffected because it has a **different** `_client_key` → its **own separate** semaphore. Text saturation never consumes vision slots and vice-versa.

### Acquire order + deadlock argument (airtight)

Two semaphores per request: **L** = priority lane (acquired in `complete()`), **E** = per-endpoint cap (acquired in `complete()`, strictly **after** L, released **before** L in the `finally`). Every code path acquires **L then E** — never E then L. With a single, consistent global lock order there is no cyclic wait → **no deadlock**. Both acquisitions use `asyncio.wait_for(..., timeout=…)` with a fail-open on `TimeoutError`, so even a fully saturated system always makes forward progress (it degrades, never hangs).

### Fairness / no interactive starvation

`CRITICAL` calls **do not acquire E at all** (bypass). Therefore a Captain DM/@mention can never be queued behind background calls holding the endpoint cap — it is bounded only by its reserved interactive lane (2), exactly as AD-636 intends. Worst-case concurrency to the proxy = `E (background, default 8) + interactive_in_flight (~2)` ≈ 10, which is within the proxy's proven-healthy 10-concurrent probe. Background calls waiting on E is acceptable (proactive/warm-boot work is not latency-critical) and is the desired backpressure; the bounded wait + jittered fail-open guarantees they still progress.

### Config field + default (chosen: enabled-by-default, with a disable escape hatch)

New field on `LLMRateConfig`:
```python
max_inflight_per_endpoint: int = 8
```
- **Default 8 (enabled).** Justification: BF-654's whole point is that today's unbounded-past-fail-open behavior IS the bug — a default of 0 would ship the fix but leave every operator exposed until they opt in. `8` background + `~2` interactive ≈ `10` ≤ the proxy's proven-healthy 10-concurrent.
- **`<= 0` = disabled = unbounded** → no endpoint semaphores are created → the `complete()` endpoint block is fully skipped → **byte-identical to pre-BF-654**. This is the escape hatch AND the byte-identical regression test.
- Two internal tuning values are **instance attributes** (not config, to keep the operator surface to one field): `self._endpoint_acquire_timeout = 120.0` (intentionally longer than the 30s lane timeout so E holds firm through the boot-burst drain while the lane churns; still < the 300s deep httpx timeout so slots always free) and `self._endpoint_failopen_jitter_seconds = 0.5` (de-syncs a saturated-endpoint herd on the last-resort fail-open).

---

## Section 0 — Config field

`src/probos/config.py`, in `class LLMRateConfig` (`config.py:874`). Add after `interactive_reserved_slots`:

```python
# SEARCH
    # AD-636: Global concurrency cap for LLM calls
    max_concurrent_calls: int = 6
    # AD-636: Reserved slots for interactive (Captain DM) priority
    interactive_reserved_slots: int = 2
```
```python
# REPLACE
    # AD-636: Global concurrency cap for LLM calls
    max_concurrent_calls: int = 6
    # AD-636: Reserved slots for interactive (Captain DM) priority
    interactive_reserved_slots: int = 2

    # BF-654: max simultaneous in-flight requests to any SINGLE LLM endpoint
    # (keyed by base_url|api_format, i.e. the httpx pool). Bounds total
    # concurrency to the shared Copilot proxy during a boot burst, composing
    # with — not replacing — the AD-636 priority lanes. Endpoints on distinct
    # base_urls (e.g. the Copilot proxy vs. ollama for vision) get INDEPENDENT
    # caps, so vision is never throttled by the text cap. CRITICAL (interactive)
    # calls BYPASS this cap so the Captain is never throttled. 0/negative =
    # disabled (unbounded past the lane fail-open = pre-BF-654 byte-identical).
    max_inflight_per_endpoint: int = 8
```

(No change needed to `config/system.yaml`; the default applies when the key is absent. Operators may add `max_inflight_per_endpoint:` under the existing `llm_rate:` block at `system.yaml:1590`.)

---

## Section 1 — Construct the per-endpoint semaphores in `__init__`

`src/probos/cognitive/llm_client.py`. First add the import (imports are `asyncio, json, logging, re, time, uuid` at L5-10):

```python
# SEARCH
import asyncio
import json
import logging
import re
import time
import uuid
```
```python
# REPLACE
import asyncio
import json
import logging
import random
import re
import time
import uuid
```

Then append the BF-654 block after the AD-636 semaphore construction (end of `__init__`, `llm_client.py:183-193`):

```python
# SEARCH
        _background_slots = max(1, _max_concurrent - _interactive_reserved)
        self._interactive_semaphore = asyncio.Semaphore(_interactive_reserved)
        self._background_semaphore = asyncio.Semaphore(_background_slots)
```
```python
# REPLACE
        _background_slots = max(1, _max_concurrent - _interactive_reserved)
        self._interactive_semaphore = asyncio.Semaphore(_interactive_reserved)
        self._background_semaphore = asyncio.Semaphore(_background_slots)

        # BF-654: per-endpoint in-flight cap. One asyncio.Semaphore per distinct
        # upstream (keyed by _client_key = base_url|api_format, matching the
        # httpx pool grouping in self._clients) bounds TOTAL simultaneous
        # requests to each endpoint — the hard backstop the AD-636 lane
        # fail-open lacks. Text tiers (fast/standard/deep) share one key
        # (the Copilot proxy) and thus one cap; vision/ollama get their own,
        # so a saturated proxy never starves vision and vice-versa. Constructed
        # here (no running loop needed on 3.10+, exactly like the AD-636
        # semaphores above). <= 0 disables the feature (dict stays empty =>
        # complete() skips the whole endpoint block => pre-BF-654 byte-identical).
        _max_inflight = 8
        if rate_config and hasattr(rate_config, "max_inflight_per_endpoint"):
            _max_inflight = rate_config.max_inflight_per_endpoint
        self._endpoint_semaphores: dict[str, asyncio.Semaphore] = {}
        if _max_inflight and _max_inflight > 0:
            for tier in _LLM_TIERS:
                key = self._client_key(tier)
                if key not in self._endpoint_semaphores:
                    self._endpoint_semaphores[key] = asyncio.Semaphore(_max_inflight)
        # BF-654: how long a background call waits for an endpoint slot before
        # the last-resort jittered fail-open. Longer than the 30s lane timeout
        # so the endpoint cap holds firm through the boot-burst drain, shorter
        # than the 300s deep httpx timeout so slots always free.
        self._endpoint_acquire_timeout: float = 120.0
        self._endpoint_failopen_jitter_seconds: float = 0.5
```

---

## Section 2 — Acquire the endpoint cap in `complete()`

`src/probos/cognitive/llm_client.py:524-548`. Replace the acquire + try/finally (keep the docstring above it unchanged):

```python
# SEARCH
        # AD-637f: CRITICAL uses reserved interactive slots; NORMAL and LOW share background
        sem = self._interactive_semaphore if priority == Priority.CRITICAL else self._background_semaphore
        try:
            await asyncio.wait_for(sem.acquire(), timeout=30.0)
        except asyncio.TimeoutError:
            # Fail-open: if semaphore times out, proceed without it (degrade, don't block Captain)
            logger.warning("AD-636: %s semaphore acquisition timed out, proceeding without", priority)
            sem = None  # type: ignore[assignment]

        try:
            return await self._complete_inner(request)
        finally:
            if sem is not None:
                sem.release()
```
```python
# REPLACE
        # AD-637f: CRITICAL uses reserved interactive slots; NORMAL and LOW share background
        is_critical = priority == Priority.CRITICAL
        sem = self._interactive_semaphore if is_critical else self._background_semaphore
        try:
            await asyncio.wait_for(sem.acquire(), timeout=30.0)
        except asyncio.TimeoutError:
            # Fail-open: if semaphore times out, proceed without it (degrade, don't block Captain)
            logger.warning("AD-636: %s semaphore acquisition timed out, proceeding without", priority)
            sem = None  # type: ignore[assignment]

        # BF-654: per-endpoint in-flight cap. Acquired AFTER the priority lane
        # (single global lock order L->E => no deadlock) and released BEFORE it
        # in the finally. CRITICAL bypasses the cap entirely so the Captain is
        # never queued behind background work (no interactive starvation). The
        # endpoint is fixed by request.tier: the text fallback chain stays on
        # one base_url and vision never falls back, so this key is correct for
        # the whole call incl. the BF-612 retry.
        endpoint_sem: asyncio.Semaphore | None = None
        if not is_critical:
            _tier = request.tier or self.default_tier
            if _tier not in self._tier_configs:
                _tier = self.default_tier
            endpoint_sem = self._endpoint_semaphores.get(self._client_key(_tier))
        endpoint_acquired = False
        if endpoint_sem is not None:
            try:
                await asyncio.wait_for(
                    endpoint_sem.acquire(), timeout=self._endpoint_acquire_timeout
                )
                endpoint_acquired = True
            except asyncio.TimeoutError:
                # Last-resort fail-open. Unlike the lane, jitter the proceed so a
                # saturated-endpoint herd de-synchronizes instead of re-flooding
                # the proxy in lockstep (the BF-654 root cause).
                await asyncio.sleep(
                    random.uniform(0.0, self._endpoint_failopen_jitter_seconds)
                )
                logger.warning(
                    "BF-654: endpoint in-flight cap acquire timed out (tier=%s); "
                    "proceeding after jitter",
                    request.tier or self.default_tier,
                )

        try:
            return await self._complete_inner(request)
        finally:
            if endpoint_acquired and endpoint_sem is not None:
                endpoint_sem.release()
            if sem is not None:
                sem.release()
```

---

## Section 3 — (Optional, recommended) jitter the BF-612 recycle-retry

Defense-in-depth for the empty-200 path: even with the cap, a synchronized set of ≤8 in-flight calls could all receive an empty-200 at once and then all recycle+retry in lockstep. A tiny jitter before the recycle de-syncs them. Only jitter when the cap is enabled (else byte-identical). In `_complete_inner`, at the BF-612 branch (`llm_client.py:672-684`), insert a jitter **immediately before** `await self._refresh_client(attempt_tier)`:

```python
# SEARCH
                        _refreshed_tiers.add(attempt_tier)
                        logger.warning(
                            "BF-612: empty content from tier=%s (model=%s, "
                            "prompt_tokens=%d) — recycling connection pool and "
                            "retrying once on a fresh socket",
                            attempt_tier, model, response.prompt_tokens,
                        )
                        await self._refresh_client(attempt_tier)
```
```python
# REPLACE
                        _refreshed_tiers.add(attempt_tier)
                        logger.warning(
                            "BF-612: empty content from tier=%s (model=%s, "
                            "prompt_tokens=%d) — recycling connection pool and "
                            "retrying once on a fresh socket",
                            attempt_tier, model, response.prompt_tokens,
                        )
                        # BF-654: de-sync a synchronized empty-200 herd so the
                        # recycled sockets don't all retry the proxy in lockstep.
                        # No-op when the endpoint cap is disabled (byte-identical).
                        if self._endpoint_semaphores:
                            await asyncio.sleep(
                                random.uniform(0.0, self._endpoint_failopen_jitter_seconds)
                            )
                        await self._refresh_client(attempt_tier)
```

If the Builder judges this raises risk on the BF-612 suite, it may be **omitted** — Sections 0-2 are the core fix. If included, add `test_bf612_jitter_only_when_cap_enabled` (§ Test plan #9).

---

## 4. Test plan

New file `tests/test_bf654_endpoint_concurrency_cap.py`. Use a **real** `OpenAICompatibleClient` (BF-287: real fixtures at the substrate boundary), patch only the transport (`_call_api`) with a fake that counts concurrent entries. Mirror the `_FakeRateConfig` dataclass from `test_ad636_llm_priority_scheduling.py` and add `max_inflight_per_endpoint`.

Helper pattern:
```python
def _make_client(*, max_inflight=8, max_concurrent=100, interactive_reserved=2):
    # LARGE lane (100) so the LANE never binds — isolates the ENDPOINT cap as
    # the constraint under test.
    from probos.cognitive.llm_client import OpenAICompatibleClient
    rate = _FakeRateConfig(
        max_concurrent_calls=max_concurrent,
        interactive_reserved_slots=interactive_reserved,
        max_inflight_per_endpoint=max_inflight,
    )
    return OpenAICompatibleClient(rate_config=rate)

class _ConcurrencyCounter:
    def __init__(self): self.cur = 0; self.peak = 0
    async def call(self, request, model, client, **kwargs):
        from probos.types import LLMResponse
        self.cur += 1; self.peak = max(self.peak, self.cur)
        try:
            await asyncio.sleep(0.02)
            return LLMResponse(content="ok", model=model, tier="standard")
        finally:
            self.cur -= 1
```

1. **`test_endpoint_semaphores_created_by_default`** — `OpenAICompatibleClient()` (no rate_config) → `_endpoint_semaphores` has the text key (`_client_key("standard")`) with `._value == 8`.
2. **`test_disabled_when_zero_no_semaphores`** — `max_inflight_per_endpoint=0` → `_endpoint_semaphores == {}` (escape hatch / byte-identical construction).
3. **`test_at_most_N_concurrent_inflight_to_one_endpoint`** (HEADLINE) — `_make_client(max_inflight=8)`, patch `client._call_api = counter.call`, fire **30** concurrent background `complete(LLMRequest(prompt=f"r{i}", tier="standard"))`, `await asyncio.gather(...)`. Assert `counter.peak <= 8` and all 30 return `"ok"`. (Large lane ensures the ENDPOINT cap, not the lane, is what holds it at 8.)
4. **`test_ollama_endpoint_independent_of_copilot_cap`** — configure a distinct vision base_url (`CognitiveConfig(llm_base_url_vision="http://127.0.0.1:11434", llm_model_vision="qwen2.5vl:3b", llm_api_format_vision="ollama", …)`). Assert `_endpoint_semaphores` has **two distinct keys** (text vs vision). Behavioral: drain the TEXT endpoint semaphore to 0 (`for _ in range(8): await sem.acquire()`), then a `vision`-tier `complete()` (patched `_call_api`) still completes promptly — proving the vision cap is untouched by text saturation.
5. **`test_critical_bypasses_endpoint_cap`** — drain the text endpoint semaphore to 0. Replace `_complete_inner` with an `AsyncMock` returning `"ok"`. Fire `complete(req_standard, priority=Priority.CRITICAL)` under `asyncio.wait_for(..., timeout=2)` → completes; assert the endpoint semaphore `._value` is still 0 (CRITICAL never touched it).
6. **`test_no_deadlock_mixed_priorities`** — fill the background lane AND drain the endpoint semaphore partially; fire a mix of CRITICAL + background calls (patched fast `_call_api`), `await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)` → all complete (no hang).
7. **`test_endpoint_failopen_on_timeout`** — set `client._endpoint_acquire_timeout = 0.05`, drain the endpoint semaphore to 0, patch `_call_api` → a background `complete()` still returns `"ok"` (fails open after the tiny timeout; does not hang). Assert it logged the BF-654 warning (optional `caplog`).
8. **`test_default_safe_byte_identical_path`** — `max_inflight_per_endpoint=0`, replace `_complete_inner` with an `AsyncMock`, fire a background `complete()` → `_complete_inner` called exactly once; `_endpoint_semaphores == {}` (no acquire attempted).
9. **(if Section 3 built) `test_bf612_jitter_only_when_cap_enabled`** — assert the jitter branch is guarded by `self._endpoint_semaphores` truthiness (disabled client → BF-612 retry path has no added sleep). Reuse the BF-612 fake-`_call_api` empty-then-nonempty pattern from `test_bf612_empty_content_retry.py`.

**Regression (must stay green, run explicitly):**
- `tests/test_ad636_llm_priority_scheduling.py` — the lane tests fire ≤6 concurrent (< default 8) so the endpoint cap never binds; `test_concurrent_calls_respect_cap`'s `slow_complete(req)` and the `_complete_inner` AsyncMock tests are unaffected (signature unchanged).
- `tests/test_ad637f_priority.py`
- `tests/test_bf612_empty_content_retry.py` — single-call tests never bind the cap; Section 3 (if built) only adds a ≤0.5s sleep on the empty-200 branch.

**Gate command** (isolated data dir per repo convention):
```
$env:PROBOS_DATA_DIR = "$env:TEMP\probos_gate_$(Get-Random)"; New-Item -ItemType Directory -Force -Path $env:PROBOS_DATA_DIR | Out-Null
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf654_endpoint_concurrency_cap.py tests/test_ad636_llm_priority_scheduling.py tests/test_ad637f_priority.py tests/test_bf612_empty_content_retry.py -q -n 0
Remove-Item env:PROBOS_DATA_DIR
```

---

## 5. What this does NOT change (boundaries)

- **Do NOT rip out or modify the AD-636 priority lanes.** The endpoint cap composes with them; the lane fail-open stays exactly as-is (it's the "never block the Captain" escape). Only the two lines that compute `is_critical` and add the endpoint acquire/release are touched in `complete()`.
- **Do NOT change the BF-612 recycle-retry logic** (empty-200 detection, one-refresh-per-tier guard, `_refresh_client`). Section 3 only inserts an optional, cap-gated jitter *before* the existing `_refresh_client` call — no behavior change when the cap is disabled.
- **Do NOT change `_complete_inner`'s signature** or the fallback chain, RPM limiter (`_wait_for_rate_limit`), cache, health probe, or `_call_api`/`_call_openai`/`_call_ollama_native`.
- **Do NOT add a second client instance or per-tier clients.** The single-client architecture is correct.
- **Do NOT throttle vision/ollama by the text cap** — the per-`_client_key` keying already guarantees independence; do not collapse the keys.
- **Do NOT special-case which endpoints get a cap** (e.g. "only 8080"). Uniform per-endpoint keying is simpler and self-correct; a per-endpoint override knob is a FORWARD item.

---

## 6. Tracking

- `PROGRESS.md`: add a `**BF-654 shipped**` line (per repo convention; LOCAL — Captain decides push).
- `docs/development/roadmap.md` Bug Tracker: add a BF-654 row.
- `DECISIONS.md`: **not required** for a BF (only add if the Captain wants the endpoint-cap architecture logged).
- Close/comment `seangalliher/ProbOS#1017` on ship (use `gh` CLI, `--repo seangalliher/ProbOS`).

---

## 7. Acceptance criteria

1. `max_inflight_per_endpoint` exists on `LLMRateConfig` (default 8) and is read by `OpenAICompatibleClient.__init__` from `rate_config`.
2. With the default, at most 8 requests are concurrently in flight to a single endpoint under a 30-call background burst (test #3), while a distinct endpoint (vision/ollama) is unaffected (test #4).
3. CRITICAL calls bypass the cap and never wait on it (test #5); no deadlock under mixed priorities (test #6); background fails open (not hangs) on endpoint timeout (test #7).
4. `max_inflight_per_endpoint <= 0` is byte-identical to pre-BF-654 (no endpoint semaphores, no acquire) (tests #2, #8).
5. `test_ad636_llm_priority_scheduling.py`, `test_ad637f_priority.py`, `test_bf612_empty_content_retry.py` all pass unchanged.
6. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 8. Verify-first checklist (grep evidence)

Every concrete claim above maps to a live-code grep:

```
# Single client instance (Q1)
src/probos/__main__.py:290   client = OpenAICompatibleClient(config=cog, rate_config=config.llm_rate)
src/probos/__main__.py:571   config=config, data_dir=str(data_path), llm_client=llm_client,
src/probos/cognitive/cognitive_agent.py:591   self._llm_client = kwargs.get("llm_client")

# AD-636 lanes + fail-open (root cause)
src/probos/cognitive/llm_client.py:192-193   self._interactive_semaphore / self._background_semaphore = asyncio.Semaphore(...)
src/probos/cognitive/llm_client.py:536-543   sem = ... ; await asyncio.wait_for(sem.acquire(), 30.0) ; except TimeoutError: sem = None
src/probos/cognitive/llm_client.py:546-548   try: return await self._complete_inner(request) finally: sem.release()

# Endpoint / httpx pool key (Q2) + fallback stays on one endpoint
src/probos/cognitive/llm_client.py:211-214   _client_key -> f"{tc['base_url']}|{tc.get('api_format','openai')}"
src/probos/cognitive/llm_client.py:148-153   self._clients deduped by _client_key
src/probos/cognitive/llm_client.py:591-607   vision/compute_use/vision_fast fallback is endpoint-local (no text fallback)
src/probos/config.py:519                      base_url = url_map.get(tier) or self.llm_base_url
src/probos/config.py:162                      llm_base_url default http://127.0.0.1:8080/v1
src/probos/config.py:190-200,212,241          per-tier base_url_{fast,standard,deep}=None; _vision/_vision_fast set

# Sizes + RPM (Q3)
src/probos/cognitive/llm_client.py:183-193    _max_concurrent(6)/_interactive_reserved(2)/_background_slots
src/probos/cognitive/llm_client.py:318        _wait_for_rate_limit is per-tier (self._request_timestamps[tier])

# Boot lane = background (Q4)
src/probos/types.py:95                         classify: proactive_think->LOW, else NORMAL (both background)
src/probos/cognitive/sub_tasks/analyze.py:588  complete(request)  # no priority => NORMAL
src/probos/cognitive/sub_tasks/compose.py:657  complete(request)
src/probos/cognitive/sub_tasks/evaluate.py:638 complete(request)
src/probos/cognitive/sub_tasks/reflect.py:516  complete(request)
src/probos/cognitive/cognitive_agent.py:4876,5103,10015  priority=Priority.NORMAL

# Config seam + BF ceiling
src/probos/config.py:874                       class LLMRateConfig
src/probos/config.py:892-894                   max_concurrent_calls / interactive_reserved_slots (insertion anchor)
src/probos/config.py:6174                      SystemConfig.llm_rate = LLMRateConfig()
config/system.yaml:1590                        llm_rate: ... max_concurrent_calls: 6
src/probos/types.py:91                          Priority.CRITICAL = "critical" (StrEnum)
src/probos/types.py:238                         LLMRequest.tier: str = "standard"
# highest shipped BF = BF-653 (PROGRESS.md); BF-654 is free
```

The Builder must re-grep any line number before applying a SEARCH/REPLACE (line numbers drift); anchor on the quoted text, not the number.

---

## 9. Risk the Builder must watch

- **`asyncio.Semaphore` in `__init__` (no running loop):** safe on Python 3.10+ (the `loop` kwarg was removed; binding is lazy on first `await`). This exactly mirrors the existing AD-636 semaphores constructed in the same `__init__` — do not "fix" it by moving construction into an async method.
- **`_client_key(tier)` inside `__init__`:** works because Python resolves `self._client_key` at call time and `self._tier_configs` is already populated (L155-156); the existing `__init__` already calls `self._client_key(tier)` at L152. Do not reorder the BF-654 block above the `_tier_configs` build.
- **Default 8 vs existing lane tests:** the AD-636 tests fire ≤6 concurrent, below 8, so the endpoint cap never binds and they stay green. If any existing test is found to assert **>8** concurrent to one endpoint (i.e. asserting the old unbounded fail-open), that test encodes the BUG — repoint it (raise its `max_inflight_per_endpoint` or set it to 0), do not weaken the cap. Grep the lane tests before finalizing.
- **`request.tier` unknown value:** guarded (`if _tier not in self._tier_configs: _tier = self.default_tier`) so `_client_key` never raises. `LLMRequest.tier` defaults to `"standard"` (a valid tier), so this is belt-and-suspenders.
- **Do not thread `priority` into `_complete_inner`.** The endpoint acquire lives in `complete()` precisely so `_complete_inner`'s positional-only test fakes (`slow_complete(req)`) keep working.
- **`import random`** must be added (Sections 2 and 3 use `random.uniform`); it is not currently imported.
