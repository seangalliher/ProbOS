# BF-665 — Generation-safe shared LLM refresh and persistent-empty failover

**Verdict:** APPROVED FOR BUILDER
**One-line:** Add endpoint-keyed generation leases around every pooled LLM transport borrower, singleflight compare-and-swap refresh, deferred retirement close, and failed-tier accounting for an empty post-refresh response.

**Status:** Ready to build
**Type:** Bug fix — **BF-665**; no new AD
**GitHub issue:** #1031 — https://github.com/seangalliher/ProbOS/issues/1031
**Exact base HEAD:** `5e28b579765c28b86a9033a6a6b832ebe679e1c6`
**Numbering verified:** highest shipped entries at this base are **AD-1121** and **BF-664**; issue #1031 already reserves BF-665
**Dependencies:** BF-069/BF-240/BF-246, BF-272, BF-612, AD-617, AD-636/AD-637f, BF-654/BF-659
**License disposition:** none — standard-library state/locking only; no dependency or absorbed external code
**Estimated tests:** 14–20 new or revised cases in the five existing LLM test files below; no new test file

## Scope

Repair one private lifecycle inside `OpenAICompatibleClient`: the shared `httpx.AsyncClient` selected by `base_url|api_format`. Keep pooling, per-endpoint throughput caps, priority lanes, fallback, caching, model routing, retries, and public protocols intact.

The implementation must guarantee:

1. every production transport that borrows a pooled client holds a generation lease for the complete transport await;
2. one observed generation can be replaced at most once;
3. a retired client closes only after its last borrower releases;
4. cancellation cannot leak a lane, endpoint permit, borrower count, retired client, or cleanup task; and
5. a second empty OpenAI-compatible response is a failed tier attempt, never healthy success.

No UI work is authorized.

---

## Problem and verified root cause

At the exact base:

- `OpenAICompatibleClient.__init__()` deduplicates clients in `self._clients` by `_client_key(tier)`, where `_client_key()` returns `base_url|api_format` (`llm_client.py:145–154`, `244–247`). Default fast/standard/deep configurations share one key, but per-tier URLs can legitimately differ.
- BF-654/BF-659 creates one endpoint semaphore per same key and `_endpoint_permit(attempt_tier)` holds it around the whole same-tier attempt (`llm_client.py:204–221`, `250–262`, `697`). CRITICAL bypass is task-local through `_ENDPOINT_GOVERNED` (`27–29`, `568–600`).
- `_complete_inner(request)` resolves `client = self._clients[...]` after the endpoint permit, but `_refresh_client(tier)` closes that shared client in place and then replaces the dictionary entry (`283–309`, call at `743`). At cap greater than one, or for CRITICAL calls that bypass the cap, peers may still be awaiting transport on the closed object.
- `_refresh_client()` has no endpoint-keyed refresh lock, generation comparison, or borrower tracking. Two callers that saw the same stale object can each close/rebuild; a stale caller can act after another caller installed a newer object.
- After BF-612 retries on a fresh pool, `_complete_inner()` does not reclassify a second empty response. It falls through cache-write guarding into success dwell (`759–799`) and returns the empty `LLMResponse` (`804`), so failures can clear and `last_success` can advance.
- `_check_endpoint(tier)` directly borrows `self._clients[...]` without either endpoint permit or lifetime lease (`511–568`). It treats any status below 500, including an HTTP 200 with empty assistant content, as reachable. `check_connectivity()` then advances success dwell and can report recovery (`406–443`).
- The final no-cache failure envelope already exists and must remain exactly the fallback: `LLMResponse(..., error=f"All LLM tiers unavailable ({last_error})", ...)` (`895–905`).

### Production borrower audit

Grep found exactly two production paths that look up a pooled LLM client for network transport:

1. `_complete_inner()` → `_call_api()` (initial and BF-612 retry);
2. `_check_endpoint()` → `client.post()` (boot/periodic connectivity probe).

`_call_openai()` and `_call_ollama_native()` take a client argument and are also called directly by low-level unit tests with caller-owned fakes/clients; they must not acquire a second pool lease internally.

### Exact live signatures at the build base

```text
OpenAICompatibleClient.__init__(
  self,
  base_url: str = "http://127.0.0.1:8080/v1",
  api_key: str = "",
  models: dict[str, str] | None = None,
  timeout: float = 30.0,
  default_tier: str = "standard",
  config: Any = None,
  rate_config: Any = None,
  *,
  model_router: Any = None,
  attachment_store: AttachmentStore | None = None,
) -> None

def _client_key(self, tier: str) -> str
async def _endpoint_permit(self, attempt_tier: str) -> AsyncIterator[None]
def _build_client(self, tier: str) -> httpx.AsyncClient
async def _refresh_client(self, tier: str) -> None
async def check_connectivity(self) -> dict[str, bool]
async def _check_endpoint(self, tier: str) -> bool
async def complete(
  self,
  request: LLMRequest,
  *,
  priority: Priority = Priority.NORMAL,
) -> LLMResponse
async def _complete_inner(self, request: LLMRequest) -> LLMResponse
async def _call_api(
  self,
  request: LLMRequest,
  model: str,
  client: httpx.AsyncClient,
  *,
  api_format: str = "openai",
  timeout: float = 30.0,
  effective_temp: float | None = None,
  effective_top_p: float | None = None,
  effective_max_tokens: int | None = None,
  effective_system_suffix: str | None = None,
) -> LLMResponse
async def close(self) -> None
```

BF-665 changes only the private `_refresh_client` signature and adds private state/lease helpers. Every other signature above remains exact.

---

## Issue-contract resolutions

These are clarifications required by the live code; they do not weaken #1031.

1. **All-tier persistent-empty error is a cache-miss criterion.** The existing contract is attempts → cache → error, and #1031 forbids changing cache behavior. Therefore the required all-tier persistent-empty test must use a cache miss. A valid existing cache hit remains authoritative after failed live attempts.
2. **There is no cancellable await inside the atomic swap.** The required “cancellation at swap” coverage is split into (a) cancellation while waiting for the state lock, before any mutation, and (b) cancellation during post-swap retirement close, after the synchronous map/generation swap. Inserting an await into the swap would create the partial-state bug the issue asks to prevent.
3. **Health probes join the endpoint cap.** #1031 requires every transport borrower to lease and requires background peak to remain bounded. `_check_endpoint()` is background transport, so it must acquire the existing endpoint permit as well as the lifetime lease. CRITICAL completion still bypasses the endpoint semaphore.
4. **`self._clients` remains the current-client map.** Existing per-tier/vision/tier-adaptation tests replace private map entries with `MockTransport` clients. Generation metadata therefore lives beside the map rather than changing map values to wrapper objects. This preserves the current private test seam while making production mutation lock-owned.

---

## Pinned design decisions

### DD-1 — Endpoint-keyed state; `_clients` remains current-client compatibility surface

Add two module-private dataclasses (names may vary only if semantics and test readability remain exact):

- `_ClientLease` — frozen/slots; fields `client_key: str`, `generation: int`, `client: httpx.AsyncClient`.
- `_ClientPoolState` — slots; fields:
  - `generation: int` (starts at `0`);
  - `state_lock: asyncio.Lock`;
  - `refresh_lock: asyncio.Lock`;
  - `borrowers: dict[int, int]` (generation → active lease count);
  - `retired: dict[int, httpx.AsyncClient]` (old generation → client awaiting final release).
  - `borrowers_zero: asyncio.Event`, initially set, cleared on the zero→one total-borrower transition and set after the one→zero transition has claimed any eligible retired close;
  - `retirement_closes: dict[int, asyncio.Event]` (generation → completion signal installed before a retired client leaves `retired` for its unique closer);
  - `closing: bool` and `closed: bool`.

Construct every mutable/lock field per instance (`field(default_factory=asyncio.Lock)` / `field(default_factory=dict)`, or explicit fresh values). No shared mutable dataclass default is permitted.

Add `self._client_pool_states: dict[str, _ClientPoolState]`, exactly one state per distinct key in `self._clients`, after initial client construction. The state owner is the `OpenAICompatibleClient` instance. A tier does not own a state; all sibling tiers with the same `_client_key()` share it.

Keep:

```text
self._clients: dict[str, httpx.AsyncClient]
```

as the current-generation client map. Do not replace values with wrappers and do not create a client per tier/request.

Invariants:

- `state.generation` names the object currently at `self._clients[client_key]`.
- A generation is either current or retired, never both.
- `borrowers[g]` is incremented before a borrower receives the object and decremented after its transport await completes/cancels.
- A retired client is removed from `retired` by exactly one closer only when `borrowers[g] == 0`.
- No test-only fallback may silently manufacture missing state. Tests that construct via `__new__` must initialize the real private state shape or move that fixture to the real constructor.

### DD-2 — One lifetime lease around every pooled production transport

Add:

```text
@asynccontextmanager
async def _client_lease(self, tier: str) -> AsyncIterator[_ClientLease]
```

Acquire semantics:

1. resolve `client_key = self._client_key(tier)` and its `_ClientPoolState`;
2. await `state_lock`;
3. recheck the client-wide/endpoint closing gates under S; refuse if closing;
4. snapshot `state.generation` and `self._clients[client_key]` atomically;
5. if the endpoint's total borrower count was zero, clear `borrowers_zero`; increment `borrowers[generation]`;
6. release `state_lock`;
7. yield the immutable lease.

Release semantics:

1. run release as a locally-held cleanup task under `asyncio.shield()`;
2. await `state_lock`;
3. decrement exactly once; remove the zero counter;
4. if that generation is retired and now has zero borrowers and has no existing close event, pop its client as the sole closer and install `retirement_closes[generation]` before releasing S;
5. if the endpoint's total borrower count is now zero, set `borrowers_zero` only after step 4 has made close ownership visible;
6. release `state_lock`;
7. await `aclose()` outside every lock;
8. set the generation's retirement-close event in `finally`, then remove that exact event under S; log-and-degrade a close failure with endpoint/generation context; never close the current client by mistake.

The local cleanup task is not fire-and-forget: retain it, drain it to completion, and only then propagate caller cancellation. Mirror the cancellation-deferred shape of `KnowledgeStore._await_skill_task()` (`knowledge/store.py:584–604`) without coupling the two modules.

Use the lease at:

- each `_call_api()` await in `_complete_inner()` (initial and retry are separate leases);
- the `client.post()` await in `_check_endpoint()`.

Do not put a lease around model selection, rate-limit sleep, 429 backoff, jitter, response accounting, cache access, or parsing after the response body is loaded.

### DD-3 — Lock and permit order is total and non-cyclic

The only allowed nesting order is:

```text
priority lane L → endpoint semaphore E → refresh lock R → state lock S
```

Not every path uses every level:

- NORMAL/LOW completion: `L → E`; brief `S` for each lease; on empty and with no lease held, `L → E → R → S`.
- CRITICAL completion: interactive `L`; **no E**; brief `S` per transport; on empty `L → R → S`.
- health probe: `E → S`; no lane and no refresh.
- lease release: `S` only.

Rules:

- never acquire a lane inside `_complete_inner()`;
- never acquire E, R, or L while holding S;
- never acquire R while holding S;
- refresh rechecks the client-wide/endpoint closing gate under S and cannot publish after close admission shuts;
- do not hold S or R across `_call_api()`, `post()`, `sleep()`, or `aclose()`;
- the endpoint permit continues to span jitter, refresh, retry, and all same-tier 429 backoff exactly as BF-659 requires;
- CRITICAL bypasses E exactly as today, but never bypasses S/lease accounting.

### DD-4 — Compare-observed-generation singleflight refresh

Change the private refresh contract to require evidence:

```text
async def _refresh_client(
    self,
    tier: str,
    *,
    observed_generation: int,
) -> bool
```

Return `True` only for the caller that installed a replacement; `False` for a stale observation or build failure. This is private API churn only; `BaseLLMClient`, `complete()`, `_complete_inner()`, requests, and responses stay unchanged.

Algorithm:

1. derive endpoint key/state;
2. await the endpoint-keyed `refresh_lock`;
3. await `state_lock`;
4. if the client/endpoint is closing or `state.generation != observed_generation`, release locks and return `False`; do not build, close, or mutate anything;
5. while holding S, call synchronous `_build_client(tier)` first; if construction raises, log with endpoint/generation context, leave all state unchanged, return `False`;
6. still under S and with no intervening await, enter a rollback-safe publication block:
   - capture `old = self._clients[key]`;
   - install the new client in `_clients[key]`;
   - set `state.generation = observed_generation + 1`;
   - place old in `state.retired[observed_generation]`;
  - if old has zero borrowers, pop it as `close_now` and install its `retirement_closes` event before releasing S;
  - if any synchronous mutation unexpectedly raises before publication is complete, restore the old map/generation/retired state under S, retain the unpublished new client as `discard_new`, and leave the observed generation current;
7. release S and R;
8. close `discard_new` and/or `close_now`, if any, outside locks through the same cancellation-deferred cleanup primitive; a published retired generation signals/removes its installed close event in `finally`, while an unpublished discard never enters generation state;
9. return `True`.

There is no await between successful construction and the map/generation/retirement mutation. Consequently cancellation can occur only before mutation or during cleanup after a complete swap. A client that is built but not published is always closed; it is never leaked or inserted into `retired` as if it had served traffic.

Concurrency proof:

- N callers may all hold leases to generation G and observe empty.
- They release those leases before refresh.
- One caller takes R, sees G current, installs G+1, retires G.
- Every later caller takes R, sees `current != G`, returns `False`, and cannot close G+1.
- G closes immediately only if no peer still leases it; otherwise its final releaser closes it.

### DD-5 — Completion retry leases by transport; refresh budget keys by endpoint generation

Keep `_endpoint_permit(attempt_tier)` around the whole attempt. Inside its existing try/429 loop:

1. acquire `_client_lease(attempt_tier)`;
2. call `_call_api(..., lease.client, ...)`;
3. retain `lease.client_key` and `lease.generation` with the response;
4. release the lease before jitter or refresh;
5. on a refreshable empty response, call `_refresh_client(attempt_tier, observed_generation=lease.generation)`;
6. acquire a **new** lease and compare its generation with the observed generation:
  - if it differs, a local or concurrent refresh installed a current generation; perform this request's one retry with that lease (a stale observer still gets one retry, but causes no second swap);
  - if it is unchanged, client construction failed and no fresh generation exists; release without another transport and classify the tier attempt as failed;
7. release any retry lease before accounting.

Replace `_refreshed_tiers: set[str]` with a per-call endpoint-generation budget such as:

```text
_refreshed_generations: set[tuple[str, int]]
```

A refreshable empty is still exactly:

```text
not response.content
and not response.content_blocks
and not response.error
and api_format != "ollama"
```

The set prevents the same request from requesting another refresh for the same shared endpoint generation through a sibling tier. The endpoint refresh lock/generation comparison prevents different requests from swapping that generation more than once. Preserve the one immediate retry ceiling. A refreshable empty response that cannot refresh because its `(client_key, generation)` budget was already consumed is classified as a failed tier attempt; it must not fall through to success.

### DD-6 — Persistent post-refresh empty is one failed tier attempt

After the optional refresh/retry handling, re-run the same usability predicate before cache write or success dwell. This check runs whether the retry stayed empty, no fresh generation could be built, or this request had already consumed the refresh budget for that endpoint generation. If the attempt still ends empty:

- set a contextual `last_error` identifying persistent empty content for that tier/model;
- increment `_consecutive_failures[attempt_tier]` exactly once for this tier attempt;
- set `_consecutive_successes[attempt_tier] = 0`;
- set `_last_failure[attempt_tier] = time.monotonic()`;
- do **not** change `_last_success`;
- do **not** reset the 429 counter as a success;
- do **not** write the response cache;
- log a contextual warning that fallback will be attempted;
- break to the next existing fallback tier.

Do not raise a new exception type. If all text attempts fail and the original-tier cache misses, return the existing all-tier `LLMResponse` envelope unchanged. If a cache hit exists, preserve it. Tool-call `content_blocks` remain success. Ollama remains non-refreshing and retains its existing completion behavior.

### DD-7 — Health probes are capacity-bounded, leased, and content-aware

In `_check_endpoint(tier)`:

1. preserve the current tier-specific payload/path/timeout;
2. explicitly set `_ENDPOINT_GOVERNED=True` with a token/reset scope, then acquire `_endpoint_permit(tier)`; health is always background-governed and must not inherit a caller's CRITICAL bypass context;
3. acquire `_client_lease(tier)`;
4. await `lease.client.post(...)`;
5. release lease and endpoint permit through their context managers;
6. preserve non-200 connectivity semantics: any status `<500` other than the special HTTP-200 content validation still proves the server is reachable;
7. for HTTP 200 only, parse the already-loaded body and require non-whitespace usable assistant output:
   - OpenAI-compatible: `choices[0].message.content`, falling back to `message.reasoning` as `_call_openai()` does;
   - Ollama: `message.content`;
8. malformed/shape-missing/empty HTTP 200 returns `False` and logs what/why/next without logging the response body;
9. never refresh from a health probe.

In `check_connectivity()`:

- successful probes keep the existing success-dwell behavior;
- a false probe sets `_consecutive_successes[tier] = 0` so an empty sample cannot leave/report `recovering`;
- do not clear or increment `_consecutive_failures` merely for this probe sample; completion attempts remain the failure-count authority.

The ContextVar token is reset in `finally`, including cancellation. Do not change `_endpoint_permit()`'s signature to achieve this.

This resolves the issue without redesigning BF-069 health scoring.

### DD-8 — Cancellation is deferred only for ownership cleanup, never swallowed

Required await-point behavior:

| Await point | Ownership at cancellation | Required result |
|---|---|---|
| lane wait | no lane | propagate; no release |
| endpoint wait | lane only | propagate; lane releases |
| lease state-lock wait | lane/optional endpoint; no borrower yet | propagate; held permits release; no borrower entry |
| initial transport | lane/optional endpoint + one lease | propagate after lease count is released; permits restore |
| jitter | lane/endpoint; no lease | propagate; permits restore |
| refresh-lock wait | lane/optional endpoint; no lease | propagate; no swap; permits restore |
| swap state-lock wait | lane/optional endpoint; no lease | propagate; no build/swap |
| post-swap retirement close | complete new generation installed | shield/drain the close, then propagate; no half-swap/task leak |
| retry transport | lane/optional endpoint + new-generation lease | propagate after lease release; permits restore |
| 429 backoff | lane/endpoint; no lease | existing propagation and permit restoration |
| final retired-borrower close | lease count already reaches zero | shield/drain exactly one close, then propagate |
| health transport | endpoint + one lease | propagate after both restore |
| full-client close drain/close | lease admission closed; current/retired ownership remains | shield/drain all ownership cleanup, then propagate |

Never use `asyncio.ensure_future()`. Every cleanup task is locally retained until done. Do not catch and convert `CancelledError` into an LLM failure/fallback response.

### DD-9 — `close()` drains the same generation state idempotently

BF-665 changes client ownership, so the existing raw `for client in self._clients.values(): await client.aclose()` loop cannot remain the shutdown owner by itself.

Add client-wide `_closing` / `_closed` flags initialized in `__init__`, plus the endpoint state flags from DD-1. `_client_lease()` checks the client-wide gate before and again under S so a close/borrow race fails closed. `close()` must:

1. stop the health probe first, as today, so it cannot register a new lease;
2. set the client-wide closing gate before awaiting any per-endpoint drain, then mark every endpoint state closing under its state lock; `_client_lease()` refuses a new borrow after this point with a contextual `RuntimeError` that `_complete_inner()` already handles as a failed attempt;
3. under R→S, move the current generation into `retired`, remove its current-map entry, claim every zero-borrower retired client by installing a retirement-close event, and snapshot pre-existing retirement-close events;
4. close each claimed distinct object once, outside locks, through the cancellation-deferred cleanup helper;
5. await `borrowers_zero` without polling; then under S claim any retired client made eligible by the final release and snapshot every outstanding retirement-close event;
6. close newly claimed clients and await every snapped close-completion event; recheck under S that `borrowers`, `retired`, and `retirement_closes` are empty before marking that endpoint closed;
7. serialize concurrent `close()` callers with a client-wide close lock/task; one caller owns cleanup and later callers await the same result rather than racing or double-closing; a call after `_closed=True` performs no further client cleanup;
8. if caller cancellation arrives during drain/close, complete ownership cleanup before re-raising.

No request cancellation is introduced by `close()`; shutdown waits for admitted borrowers. Existing BF-663 runtime shutdown closes LLM-dependent probe admission/tasks before `llm_client.close()`, and the health task is stopped here. Do not edit shutdown wiring.

Add exact tests (place in `tests/test_bf654_endpoint_concurrency_cap.py` unless an existing close-focused class in `tests/test_llm_client.py` is cleaner):

- `test_close_waits_for_active_generation_lease_then_closes_once`
- `test_close_closes_current_and_retired_distinct_clients_once`
- `test_close_rejects_new_lease_after_closing_begins`
- `test_refresh_waiter_cannot_publish_after_close_begins`
- `test_close_is_idempotent`
- `test_concurrent_close_callers_share_one_cleanup`
- `test_cancel_close_drains_clients_then_propagates`

### DD-10 — Compatibility boundaries

Preserve all of the following:

- `BaseLLMClient.complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse`;
- `OpenAICompatibleClient.complete(...)` same signature;
- `_complete_inner(self, request: LLMRequest) -> LLMResponse` same signature (BF-659 direct callers depend on it);
- `_endpoint_permit(self, attempt_tier: str) -> AsyncIterator[None]` same signature and CRITICAL task-local behavior;
- `_check_endpoint(self, tier: str) -> bool` same signature;
- `_call_api()` / `_call_openai()` / `_call_ollama_native()` signatures;
- `_TIER_ORDER = ("fast", "standard", "deep")` and vision/compute/image isolation;
- endpoint cap default/disable behavior;
- AD-636 lane timeout policy;
- RPM and 429 policy/backoff;
- cache lookup/write policy other than preventing persistent-empty success;
- model routing and per-tier adaptation;
- tool-call content blocks;
- Ollama no-refresh behavior;
- jitter and one retry;
- shutdown order and public protocols.

No sealed protocol, config model, EventType, database, API, UI, or external dependency changes.

---

## Ordered implementation

### Section 1 — Add private generation state during client construction

**Modify:** `src/probos/cognitive/llm_client.py`

1. Add standard-library dataclass imports and the DD-1 private types.
2. Keep initial `_clients` construction unchanged.
3. Build one `_ClientPoolState(generation=0, ...)` per distinct `_clients` key.
4. Do not key state by tier.
5. Keep `_endpoint_semaphores` construction/config unchanged.

### Section 2 — Add lifetime lease and cancellation-deferred retirement cleanup

**Modify:** `src/probos/cognitive/llm_client.py`

1. Implement `_client_lease()` exactly as DD-2.
2. Implement one focused inner release operation and one cancellation-deferred task-drain helper.
3. Close a retired client outside locks and at most once.
4. Include endpoint key/generation in close-failure logs.
5. Do not expose a public lease API.

### Section 3 — Replace close-and-rebuild with observed-generation singleflight

**Modify:** `src/probos/cognitive/llm_client.py`

1. Change `_refresh_client()` to the exact DD-4 private signature and boolean outcome.
2. Compare under endpoint refresh lock and state lock.
3. Build/swap/retire synchronously with no intervening await.
4. Defer old close until zero borrowers.
5. A stale observer returns without touching any client.

### Section 4 — Lease both completion transports and fail persistent empty into fallback

**Modify:** `src/probos/cognitive/llm_client.py`

1. Keep endpoint permit scope exactly where BF-659 placed it.
2. Lease each actual `_call_api()` separately.
3. Release the initial lease before refresh; reacquire current for retry.
4. Key refresh budget by `(client_key, observed_generation)`.
5. Add persistent-empty failure accounting before all success/cache accounting.
6. Preserve fallback, cache, tool-call, Ollama, 429, and vision behavior.

### Section 5 — Lease and validate health probes

**Modify:** `src/probos/cognitive/llm_client.py`

1. Put `_check_endpoint()` transport under endpoint permit + generation lease.
2. Validate usable content only for HTTP 200.
3. Reset success dwell on a false connectivity sample without changing the failure count.
4. Do not refresh from the probe.

### Section 6 — Make shutdown a generation-aware ownership barrier

**Modify:** `src/probos/cognitive/llm_client.py`

1. Add closing/closed state and a notification primitive to each endpoint state (or an equivalent endpoint-owned no-poll barrier).
2. Maintain `borrowers_zero` and `retirement_closes` in the exact claim-before-signal order from DD-2/DD-9.
3. Make `close()` follow DD-9; do not leave the raw current-map-only close loop.
4. Keep `stop_health_probe()` first and keep runtime shutdown wiring unchanged.

### Section 7 — Update existing tests; do not add a test file

#### `tests/test_bf612_empty_content_retry.py`

Update direct `_refresh_client()` tests to acquire an observed generation first. Required names/behaviors:

- `test_refresh_installs_new_generation_same_key`
- `test_refresh_closes_unborrowed_old_generation`
- `test_refresh_close_failure_still_keeps_new_generation`
- `test_persistent_empty_records_failure_and_falls_back`
- `test_all_text_tiers_persistent_empty_returns_existing_error_on_cache_miss`
- retain healthy first response, tool-call content block, one-retry ceiling, and Ollama-no-refresh coverage.

The fallback test must assert the failed tier receives exactly one failure increment, success dwell resets to zero, `last_failure` advances, `last_success` does not, and the next tier serves.

#### `tests/test_bf654_endpoint_concurrency_cap.py`

Keep every BF-654/BF-659 cap/priority/cancellation regression. Replace obsolete cancellation expectations that assume refresh leaves the old generation current. Add:

- `test_refresh_does_not_close_inflight_peer_at_cap_gt_one`
- `test_concurrent_empty_callers_swap_one_observed_generation`
- `test_stale_empty_observer_retries_installed_generation_without_second_swap`
- `test_retired_generation_closes_only_after_final_borrower`
- `test_critical_bypasses_cap_but_holds_lifetime_lease`
- `test_cancel_waiting_refresh_lock_restores_lane_endpoint_and_state`
- `test_cancel_waiting_swap_state_lock_makes_no_mutation`
- `test_cancel_post_swap_retirement_close_drains_then_propagates`
- `test_cancel_retry_transport_releases_new_generation_lease`
- `test_cancel_final_borrower_cleanup_closes_once_and_leaves_no_task`

Use cap > 1 for the headline peer-close regression. Use events/barriers, not timing-only sleeps. Assert actual client identity/open state, state generation, borrower/retired maps, endpoint/lane values, close call count, and absence of lingering named cleanup tasks.

#### `tests/test_llm_client.py`

- Change the existing OpenAI probe-success fixture to return non-empty assistant content.
- Add `test_openai_probe_empty_http_200_returns_false`.
- Add `test_openai_probe_reasoning_only_http_200_returns_true`.
- Add `test_ollama_probe_empty_http_200_returns_false_without_refresh`.
- Preserve client-map deduplication and direct caller-owned `_call_openai`/`_call_ollama_native` tests.

#### `tests/test_bf069_llm_health.py`

- Update the `__new__` dwell fixture to initialize the real generation-state shape, or use the real constructor; do not add a production fallback for an incomplete test object.
- Add `test_persistent_empty_counts_one_failure_and_resets_recovery_dwell`.
- Assert no false last-success update and no failure clearing.

#### `tests/test_bf246_llm_health_probe.py`

- Add `test_empty_http_200_probe_does_not_advance_recovery` (seed failures plus partial success dwell; empty sample leaves failures intact, resets successes, and status is not recovering/operational).
- Add `test_health_probe_holds_endpoint_permit_and_client_lease`.
- Add `test_health_probe_forces_governance_even_in_inherited_critical_context`.
- Add `test_cancel_health_probe_transport_releases_endpoint_and_lease`.
- Keep start/stop/transition-event behavior unchanged.

### Section 8 — Tracking and commit only after gates, only when directed

Current one-BF precedent (`BF-659`, `BF-661`, `BF-662`, `BF-664`) commits the two prompt files in place beside implementation and updates `PROGRESS.md`; it does **not** archive the pair, edit `DECISIONS.md`, or add a roadmap row.

If and only if the orchestrator explicitly directs closeout after green gates:

1. prepend one concise BF-665 shipped entry to `PROGRESS.md` with exact test counts;
2. leave `docs/development/roadmap.md`, all era files, and `DECISIONS.md` untouched;
3. keep both BF-665 prompt files at their current `prompts/` paths (no archive move under current convention);
4. stage only the allowlist;
5. perform the deletion sanity check from the execution document;
6. commit exactly:

```text
BF-665: make shared LLM refresh generation-safe (closes #1031)
```

Do not push, run `gh issue close`, or otherwise mutate issue state unless the orchestrator separately directs it. The commit trailer closes #1031 only when that commit reaches GitHub.

---

## Exact file allowlist

### Production — modify exactly one

- `src/probos/cognitive/llm_client.py`

### Tests — modify exactly five

- `tests/test_bf612_empty_content_retry.py`
- `tests/test_bf654_endpoint_concurrency_cap.py`
- `tests/test_llm_client.py`
- `tests/test_bf069_llm_health.py`
- `tests/test_bf246_llm_health_probe.py`

### Architect documents — already present before Builder edits; include in an authorized commit, do not rewrite/archive

- `prompts/bf-665-llm-generation-safe-refresh.md`
- `prompts/bf-665-llm-generation-safe-refresh-execution.md`

### Conditional closeout only

- `PROGRESS.md`

No other source, test, config, workflow, dependency, UI, tracker, roadmap, decision, or issue file is authorized. No new test file is authorized.

### Reference/run only

- `.github/copilot-instructions.md`
- `prompts/_TEMPLATE.md`
- `prompts/bf-659-llm-endpoint-concurrency-correctness.md`
- `prompts/bf-659-llm-endpoint-concurrency-correctness-execution.md`
- `src/probos/config.py`
- `src/probos/types.py`
- `src/probos/startup/shutdown.py`
- `tests/test_ad617_llm_rate_governance.py`
- `tests/test_ad636_llm_priority_scheduling.py`
- `tests/test_ad637f_priority.py`
- `tests/test_ad463_model_routing.py`
- `tests/test_per_tier_llm.py`
- `tests/test_ad543_tool_call_protocol.py`
- `tests/test_ad706c2_compute_use.py`
- `tests/test_ad720d_vision_pipethrough.py`
- `tests/test_ad730_3_agent_image_gen.py`
- `tests/test_ad731_attachment_ref_wire_format.py`
- `tests/test_ad732_vision_tier.py`
- `tests/test_ad734_wire_shape_contract.py`
- `tests/test_ad742a_vision_fast_tier.py`
- `tests/test_ad835_tier_adaptation.py`

---

## Test commands

Run from `D:\ProbOS`. Use no live endpoint and no broad suite in this prompt.

### Focused BF-665 gate

```powershell
Set-Location 'D:\ProbOS'
$gateDir = Join-Path $env:TEMP ("probos_bf665_focused_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
try {
    & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_bf612_empty_content_retry.py tests/test_bf654_endpoint_concurrency_cap.py tests/test_llm_client.py tests/test_bf069_llm_health.py tests/test_bf246_llm_health_probe.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning
} finally {
    Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

### LLM blast-radius gate

```powershell
Set-Location 'D:\ProbOS'
$gateDir = Join-Path $env:TEMP ("probos_bf665_blast_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
try {
    & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_bf612_empty_content_retry.py tests/test_bf654_endpoint_concurrency_cap.py tests/test_llm_client.py tests/test_bf069_llm_health.py tests/test_bf246_llm_health_probe.py tests/test_ad463_model_routing.py tests/test_ad543_tool_call_protocol.py tests/test_ad617_llm_rate_governance.py tests/test_ad636_llm_priority_scheduling.py tests/test_ad637f_priority.py tests/test_ad706c2_compute_use.py tests/test_ad720d_vision_pipethrough.py tests/test_ad730_3_agent_image_gen.py tests/test_ad731_attachment_ref_wire_format.py tests/test_ad732_vision_tier.py tests/test_ad734_wire_shape_contract.py tests/test_ad742a_vision_fast_tier.py tests/test_ad835_tier_adaptation.py tests/test_per_tier_llm.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning
} finally {
    Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

Do not use `-n auto`, xdist, a live Copilot proxy, or timing-only sleeps for the new concurrency assertions.

---

## Acceptance criteria

1. Every production pooled-client transport lookup in `_complete_inner()` and `_check_endpoint()` occurs inside `_client_lease()`.
2. No refresh closes a client while any request, CRITICAL call, or health probe leases that generation.
3. N callers observing generation G produce exactly one G→G+1 replacement and cannot close G+1 through a stale refresh.
4. The old generation closes exactly once after its final borrower, outside every state/refresh lock.
5. Endpoint throughput remains bounded by `max_inflight_per_endpoint`; CRITICAL remains unthrottled by E but lifetime-safe.
6. The endpoint permit still spans BF-612 jitter/refresh/retry and AD-617 429 backoff; lane→endpoint ordering remains intact.
7. Persistent post-refresh empty content records one failed tier attempt, resets success dwell, sets `last_failure`, does not update `last_success`, does not cache, and continues existing fallback.
8. A cache-miss request with all text tiers persistently empty returns the existing `All LLM tiers unavailable (...)` envelope, never an empty success.
9. Existing valid cache fallback remains unchanged.
10. Tool-call `content_blocks` remain successful and never refresh merely because text is empty.
11. Ollama remains non-refreshing; completion, model, RPM/429, cache, jitter, one-retry, fallback-order, vision/compute/image, and priority behavior remain otherwise unchanged.
12. Empty/malformed HTTP 200 probes are false, do not refresh, do not advance recovery, and reset partial success dwell; non-empty/reasoning probes and current sub-500 connectivity semantics remain valid.
13. Health probes always observe the endpoint cap even if invoked from a task context carrying CRITICAL endpoint bypass; their ContextVar override resets afterward.
14. `close()` stops health admission, rejects new leases, waits without polling for admitted borrowers, closes current plus retired clients exactly once, is idempotent, and completes cleanup before propagating cancellation.
15. Cancellation at endpoint/lease/refresh/state waits, initial/retry/health transport, jitter, 429 backoff, retirement close, and full-client close leaves exact lane/endpoint/borrower/retired/task state restored and propagates `CancelledError`.
16. `_complete_inner(request)` and all public/sealed protocols keep exact signatures.
17. Only the allowlisted files change; no UI work, new dependency, config, schema, protocol, EventType, or new test file appears.
18. Focused and blast-radius gates pass in serial with isolated data, local embeddings, cache disabled, timeout bound, and `RuntimeWarning` promoted to error.
19. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Do not build

- Do not disable pooling or create one client per request/tier.
- Do not change `_client_key()`, endpoint-cap defaults, lane sizes/timeouts, or throttle CRITICAL with the endpoint semaphore.
- Do not increase retries, add a second empty retry, reorder fallback, or change cache precedence.
- Do not change RPM/token governance, 429 policy/backoff, jitter policy, model routing, per-tier adaptation, or tier enumeration.
- Do not treat tool-only replies as empty.
- Do not refresh Ollama or refresh from health probes.
- Do not change vision/vision_fast/compute_use/image_gen fallback or cache behavior.
- Do not move lease acquisition into `_call_openai()`/`_call_ollama_native()`; those accept caller-owned clients in unit tests.
- Do not introduce a generic pool library, background reaper, queue, config map, new dependency, EventType, public API, or sealed-protocol change.
- Do not make `close()` poll with sleeps, abandon active leases, or close only the current map while retired generations remain owned.
- Do not alter the upstream proxy.
- Do not edit UI, config, workflows, roadmap, era files, or `DECISIONS.md`.
- Do not mint an AD; this is BF-665.
- Do not archive the prompt pair under the current one-BF commit convention.
- Do not commit, push, or close #1031 unless the orchestrator explicitly directs it.

---

## Hard stops

Stop and return to the Architect if:

- HEAD is not exactly `5e28b579765c28b86a9033a6a6b832ebe679e1c6` at Builder start;
- working-tree state before Builder edits is anything except the two BF-665 architect prompt files;
- any production pooled-client transport borrower exists beyond the two verified paths;
- correctness requires changing `BaseLLMClient`, `LLMRequest`, `LLMResponse`, `_complete_inner()` signature, config, or a sealed protocol;
- a design would await between client construction and generation/map swap;
- a path closes under S/R or closes a generation with borrowers;
- a stale observed generation can build, swap, or close;
- CRITICAL would acquire the endpoint semaphore;
- persistent empty would be returned/cached/counted successful or cache precedence would change;
- cancellation cleanup requires fire-and-forget work or swallowed `CancelledError`;
- shutdown can accept a new lease after the closing barrier, double-close, poll, or return with a current/retired client still owned;
- a required regression needs a sixth modified test file or a new test file;
- focused or blast failures reproduce serially and require behavior outside BF-665;
- or any file outside the exact allowlist appears necessary.

---

## Verified against codebase (2026-07-13; exact HEAD `5e28b579765c28b86a9033a6a6b832ebe679e1c6`)

```text
src/probos/cognitive/llm_client.py
  27: _ENDPOINT_GOVERNED: ContextVar[bool]
  40: _LLM_TIERS = (fast, standard, deep, vision, vision_fast, compute_use, image_gen)
  46: _TIER_ORDER = (fast, standard, deep)
  94: OpenAICompatibleClient.__init__(... rate_config ..., *, model_router ..., attachment_store ...)
  145: self._clients: dict[str, httpx.AsyncClient] = {}
  152–154: dedupe/build by client_key
  204–221: endpoint semaphores keyed by _client_key; configured cap default 8
  244: def _client_key(self, tier: str) -> str
  250: async def _endpoint_permit(self, attempt_tier: str) -> AsyncIterator[None]
  264: def _build_client(self, tier: str) -> httpx.AsyncClient
  283: async def _refresh_client(self, tier: str) -> None  [BF-665 changes this private signature]
  299–309: old client closes before replacement; no generation/lease
  406: async def check_connectivity(self) -> dict[str, bool]
  432/440–443: _check_endpoint result advances dwell and may clear failures
  511: async def _check_endpoint(self, tier: str) -> bool
  528: health probe directly reads self._clients
  553: reachable = resp.status_code < 500
  568: async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse
  580–600: CRITICAL lane + task-local endpoint bypass; cleanup in finally
  602: async def _complete_inner(self, request: LLMRequest) -> LLMResponse
  652: text fallback order derives from _TIER_ORDER
  656–658: current retry guard is per tier
  697–698: endpoint permit then current-client lookup
  703: initial _call_api
  721–727: exact refreshable-empty predicate; content_blocks and Ollama exclusions
  743–745: refresh then second client lookup/call
  759–804: cache guard then unconditional success dwell and return
  895–905: existing no-cache all-tier error envelope
  907: async def _call_api(... client: httpx.AsyncClient, ...)
  1027: async def _call_openai(... client ...)
  1182: async def _call_ollama_native(... client ...)
  1322: async def close(self) -> None

tests/test_bf612_empty_content_retry.py
  69/81/91: direct private refresh tests encode old close-before-replace contract
  111: empty then content recovery
  133: one refresh per tier old guard
  182: tool-call content_blocks exclusion
  209: Ollama no-refresh

tests/test_bf654_endpoint_concurrency_cap.py
  145: endpoint cap headline
  225: CRITICAL bypass
  357/395/548/592/646/712: cancellation branches
  448: BF-659 waiter resolves current client after permit
  894: actual fallback endpoint cap
  969/1002: permit spans BF-612/429 retry
  1036: direct _complete_inner default governance

tests/test_llm_client.py
  198/214/231: current _clients mapping/dedupe contract
  494/515/532: current health transport tests
  515: OpenAI probe currently accepts an empty HTTP-200 body (must be revised)
  618: existing cache fallback
  654: fast→standard fallback

tests/test_bf069_llm_health.py
  539–570: __new__ dwell fixture manually constructs current private client state
  580–695: success/failure/recovery dwell contracts

tests/test_bf246_llm_health_probe.py
  42–151: start/stop/probe/transition/cancellation lifecycle tests; no empty-content probe case

src/probos/config.py
  874: class LLMRateConfig
  892: max_concurrent_calls = 6
  894: interactive_reserved_slots = 2
  904: max_inflight_per_endpoint = 8

src/probos/types.py
  82: class Priority(StrEnum): CRITICAL/NORMAL/LOW
  233: class LLMRequest
  253: class LLMResponse

src/probos/startup/shutdown.py
  38–112: BF-663 drains LLM-dependent probe tasks before llm_client.close()

Prompt/tracking convention verified from git history
  d0a6a50b BF-659: PROGRESS + two prompts in place + source/test; no DECISIONS/roadmap
  d64920ac BF-661: same convention
  c394529e BF-662: same convention
  5e28b579 BF-664: same convention
```

---

## Architect three-pass self-review

### Pass 1 — Required / recommended / nits / license / boundary

**Verdict:** ⚠️ Conditional before revision.

**Required findings:**

1. A lease-only health design would still let background probes exceed the endpoint cap; probe must take E + lease.
2. “All tiers empty returns error” conflicted with the binding existing-cache fallback; qualify it to a cache miss.
3. “Cancel during swap” was under-specified; an atomic swap must contain no await, so split pre-mutation lock-wait cancellation from post-swap close cancellation.
4. Replacing `_clients` values with generation wrappers would break verified per-tier/vision `MockTransport` replacement seams; keep current-client values and adjacent state.
5. An untracked cleanup task would violate async discipline; cleanup must be locally retained, shielded, and drained.
6. `_endpoint_permit()` is task-local; a health probe must explicitly override inherited CRITICAL bypass or the “every background borrower is capped” guarantee is false.
7. The initial design left `close()` as a raw current-map loop; generation retirement makes that incomplete and potentially double-closing. Shutdown must drain the same ownership state.

**Recommended:** key the per-call refresh budget by endpoint generation, update the BF-069 `__new__` fixture rather than adding a production fallback, and assert no task remains after cancellation tests.

**Nits:** preserve exact all-tier error text and document reasoning-only probe success.

**License:** none.

**Boundary:** OSS is correct; this changes product runtime reliability, contains no commercial material, and requires no UI.

### Pass 2 — Required findings revised

All seven required findings and all recommendations above are incorporated in DD-1 through DD-10, the named tests, cache-miss acceptance wording, allowlist, and execution hard stops. No unresolved required item remains.

### Pass 3 — Final verify-first approval

**Verdict:** ✅ APPROVED FOR BUILDER.

Every concrete production symbol/signature, existing test seam, config default, fallback envelope, prompt convention, and tracking rule in this document maps to the live grep evidence above. No phantom API is consumed; all new private entities are introduced by this prompt. No dependency/license, repo-boundary, sealed-protocol, UI, AD-numbering, or unresolved architecture stop remains.
