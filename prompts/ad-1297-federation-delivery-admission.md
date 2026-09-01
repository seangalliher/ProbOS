# AD-1297 — Federation delivery admission for watch dispatch (BF-870 / #1346)

**Status:** READY
**Closes:** #1346 (BF-870)
**AD Number:** AD-1297 (pre-resolved)
**Depends on:** AD-1276 (always-reply envelope), BF-814 (local candidate predicate), BF-790/BF-790a (watch-path refusal semantics)
**Estimated tests:** 10-16 updated/new
**Target files:**
- `src/probos/federation/bridge.py`
- `src/probos/mesh/intent.py`
- `src/probos/runtime.py`
- `tests/test_bf814_no_subscriber_is_not_execution.py`
- `tests/test_federation.py`

---

## Problem

`forward_intent` can already distinguish several outcomes, but one remains ambiguous:

1. no peer selected: early return
2. forwarded, peer never answered: `response is None`
3. peer denied/failed locally: payload has `denied` or `error`
4. peer answered with `results: []`: ambiguous between:
   - no local subscriber on the peer
   - local handler ran and returned no result

AD-1276 intentionally made peers always reply, so this ambiguity became structurally stable instead of timeout-driven.

BF-814 fixed the local part by checking `candidate_agent_ids(intent)` before declaring execution. Watch dispatch still treats federation as configured-vs-not-configured via `forwards_to_peers` (configured transport), which is a proxy and not delivery admission.

---

## Solution Overview

Add a **delivery-admission fact** to federation intent responses, aggregate it in `forward_intent`, and consume that aggregate in `IntentBus.broadcast` only when the caller explicitly opts in.

Design constraints:
- Keep AD-1276 always-reply behavior unchanged.
- Keep mixed-version safety: omission of the new key means **unknown**, never false.
- Do not widen `IntentNoSubscriber` globally. Only the watch bridge opts into the new no-subscriber raise path.

---

## Mixed-Version Compatibility Rule (Hard)

When reading peer responses:
- `admitted=True` means peer had at least one local candidate for the intent.
- `admitted=False` means peer had no local candidate.
- `admitted` key omitted means **UNKNOWN** (old peer or non-upgraded callback shape).

**UNKNOWN must never be treated as “no candidate”.**

---

## Section 1 — Add admission fact on the responding peer

**File:** `src/probos/federation/bridge.py`
**Function:** `_handle_intent_request` (around AD-1276 response envelope)

### Change

Capture local candidate admission before local broadcast and include it in `response_payload`.

- Compute once, before `broadcast`:
  - `local_candidates = self._intent_bus.candidate_agent_ids(intent.intent)`
  - `admitted = bool(local_candidates)`
- Always include `admitted` in the response payload for upgraded peers, regardless of results/denial/error.
- Preserve existing `results`, `denied`, `reason`, `entry_point`, and `error` keys and behavior.

### SEARCH/REPLACE sketch

In `_handle_intent_request`, locate the AD-1276 block that builds:
- `response_payload: dict[str, Any] = {"results": serialized_results}`

Replace with shape that includes admission:

```python
response_payload: dict[str, Any] = {
    "results": serialized_results,
    "admitted": admitted,
}
```

while keeping existing conditional additions (`denied`, `reason`, `entry_point`, `error`) unchanged.

---

## Section 2 — Enrich `forward_intent` return shape with admission aggregate

**File:** `src/probos/federation/bridge.py`
**Function:** `forward_intent`

### Change

Introduce a list-compatible outcome type and return it from `forward_intent`.

Add a lightweight list subclass in this module:

```python
class FederationForwardOutcome(list[IntentResult]):
    peers_attempted: int
    peers_answered: int
    peers_admitted: int
    peers_unknown: int
```

Implementation requirements:
- Keep list behavior so existing code that iterates, indexes, checks length, or compares to `[]` continues to work.
- Store four counters as attributes.

In `forward_intent`:
- Count selected peers as `peers_attempted`.
- For each peer response:
  - if timeout (`response is None`): no answer, no unknown increment.
  - else increment `peers_answered`.
  - read `admitted = response.payload.get("admitted")`:
    - `True` => increment `peers_admitted`
    - key omitted / `None` => increment `peers_unknown`
    - `False` => no increment
- Deserialize remote results exactly as today.
- Return `FederationForwardOutcome(results, peers_attempted=..., peers_answered=..., peers_admitted=..., peers_unknown=...)`.

Do not remove result validation or trust-outcome recording.

---

## Section 3 — Consume admission aggregate in `IntentBus.broadcast` (opt-in)

**File:** `src/probos/mesh/intent.py`
**Functions/areas:** `broadcast`, federation callback handling, optional kwargs pass-through

### Change

Add a new broadcast/publish opt-in flag:
- `raise_on_no_subscriber: bool = False`

Behavior when flag is true:
- Raise `IntentNoSubscriber(intent.intent)` only if all of the following hold:
  1. no local candidates for the intent
  2. final result list is empty
  3. federation admission is known and zero admitted peers
  4. federation unknown count is zero

Federation admission inputs:
- If callback returns `FederationForwardOutcome`, use its counters.
- If callback returns plain list (legacy callback shape), treat as `unknown > 0` for safety.
- If callback raises and existing code degrades (current debug swallow), treat as unknown for this decision path so infrastructure failure is not misreported as “no subscriber”.

Implementation notes:
- Keep default behavior unchanged for all existing callers (`raise_on_no_subscriber=False`).
- Keep `forwards_to_peers` property for compatibility; do not delete it in this AD.
- Keep existing denial behavior (`raise_on_denial`) unchanged.

### SEARCH/REPLACE sketch

In `broadcast`:
1. Capture local candidate set once using existing candidate computation.
2. Execute current local fan-out.
3. Execute federation forwarding and parse aggregate counters via `getattr` on callback result for compatibility.
4. Apply the no-subscriber raise predicate above only when `raise_on_no_subscriber=True`.

In `publish`, ensure kwargs pass-through continues and can carry `raise_on_no_subscriber`.

---

## Section 4 — Watch-path bridge uses the new admission-aware raise

**File:** `src/probos/runtime.py`
**Function:** `_dispatch_watch_intent`

### Change

Replace the current proxy check (`candidate_agent_ids` + `forwards_to_peers`) with explicit admission-aware publish call.

- Keep `raise_on_denial=True`.
- Add `raise_on_no_subscriber=True`.
- Remove the post-publish `if not candidates and not self.intent_bus.forwards_to_peers:` block.

Resulting contract:
- local no candidate + federation configured but no peer answered/admitted => raises `IntentNoSubscriber`
- any admitted peer (even with empty result payload) => no `IntentNoSubscriber`
- unknown/mixed-version admission => no `IntentNoSubscriber`

---

## Section 5 — Tests

### 5.1 Update BF-814 watch regression file

**File:** `tests/test_bf814_no_subscriber_is_not_execution.py`

Required updates:

1. **Update, do not delete**
   - Rename and update `test_known_limitation_federation_configured_but_no_peer_still_consumes` to assert corrected behavior:
   - federation configured + no peer answering/admitting => one-shot order remains active and uncounted.

2. Add acceptance-positive case:
   - peer admission true with empty result list => order is consumed exactly once.

3. Add mixed-version safety case:
   - legacy federation callback shape (plain list, no admission counters) => treated as unknown; order is not rejected as no-subscriber by this AD.

Implementation hint for test doubles:
- Use a callback returning `FederationForwardOutcome` for known-admission tests.
- Use callback returning plain `[]` for legacy unknown-shape test.

### 5.2 Add/adjust federation bridge tests for admission counters

**File:** `tests/test_federation.py`

Add tests that validate `forward_intent` aggregate counters:

1. peer times out (no response):
   - `peers_attempted > 0`, `peers_answered == 0`, `peers_admitted == 0`, `peers_unknown == 0`

2. response omits `admitted` key (old peer simulation):
   - `peers_answered >= 1`, `peers_unknown >= 1`

3. response has `admitted=True` and empty results:
   - `peers_admitted >= 1` and list remains empty

Keep existing forward-intent behavioral tests intact (list semantics, stats, validation).

---

## What This Does NOT Change

1. Do not redesign federation transport, peer selection, or timeout policy.
2. Do not remove or alter AD-1276 always-reply guarantee.
3. Do not widen `IntentNoSubscriber` semantics beyond the watch dispatch path.
4. Do not alter directed-send/directed-response contracts.
5. Do not change `CaptainOrder` modeling or seed behavior in this AD.

---

## Acceptance Criteria

1. Federation configured with no local candidates and no peer answering/admitting leaves one-shot Captain order ACTIVE and UNCOUNTED.
2. A peer that admits and returns no result is treated as consumed (order deactivates/count increments once).
3. The existing BF-814 known-limitation test is updated to the new expected behavior, not deleted.
4. Mixed-version case is covered: old peer or legacy callback omits admission key/counters and is treated as UNKNOWN, not as “no candidate”.
5. Existing non-watch broadcast/send behavior remains unchanged unless caller opts into `raise_on_no_subscriber=True`.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-09-01)

### Symbols and anchors

- `src/probos/federation/bridge.py`
  - `1136: async def forward_intent(self, intent: IntentMessage) -> list[IntentResult]:`
  - AD-1276 reply envelope and always-reply behavior in `_handle_intent_request` block (around `1660`, response payload build around `1690`)

- `src/probos/mesh/intent.py`
  - `271: self._federation_fn: Callable[[IntentMessage], Awaitable[list[IntentResult]]] | None = None`
  - `1009: def forwards_to_peers(self) -> bool:`
  - `1019: def candidate_agent_ids(self, intent_name: str) -> set[str]:`
  - `1459-1463`: federation forwarding path in `broadcast` with exception swallow (`logger.debug`)
  - `1788: def set_federation_handler(self, fn: Callable) -> None:`

- `src/probos/runtime.py`
  - `1855: async def _dispatch_watch_intent(self, intent_type: str, params: dict) -> Any:`
  - `1914: if not candidates and not self.intent_bus.forwards_to_peers:`

- `tests/test_bf814_no_subscriber_is_not_execution.py`
  - `310: async def test_known_limitation_federation_configured_but_no_peer_still_consumes() -> None:`

### Absence verified

Claim: no production call sites directly invoke `forward_intent` besides handler wiring; direct usage is primarily tests.

Enumerations run:
- `rg -n "forward_intent\(" src/probos tests`
- `rg -n "set_federation_handler\(" src/probos`

Observed:
- Production wiring at `src/probos/startup/fleet_organization.py:226` via `intent_bus.set_federation_handler(bridge.forward_intent)`
- Direct invocations are in test modules.

This keeps blast radius centered on federation/watch behavior and tests.
