# BF-722: approval transaction integrity

**Issue:** #1167 · **Epic:** #1162 · **Repo:** OSS (`d:\ProbOS`), branch `main`

Two defects that share one concern: **an approval is durably recorded while its consequences
are not**, and the system then reports success.

Do not fix anything else in these files. Do not touch the UI (see *Out of scope*).

---

## Part A — the cache is published before the commit

### Verified current state

`CapabilityRequestStore.get()` (`src/probos/capability_request.py`) is:

```python
async def get(self, request_id: str) -> CapabilityRequest | None:
    """Return a request by id, or None if unknown."""
    return self._cache.get(request_id)
```

It returns **the cached object itself**, not a copy. `CapabilityRequest` is a plain
`@dataclass` (not frozen). So in `decide()`:

```python
req = await self.get(request_id)      # <- THE cached instance
...
req.status = "approved" if approve else "denied"   # <- cache is now decided
req.decided_at = time.time()
req.decided_by = decided_by
req.decision_reason = reason
if self._db:
    await self._db.execute(...)       # <- can raise
    await self._db.commit()           # <- can raise
self._cache[req.id] = req             # <- no-op; same object
```

A lock or commit failure leaves memory decided while the durable row stays `pending`.
`list_pending()` drops the request, the card disappears, and a restart resurrects it. The final
re-assignment reads like a publish step but is a no-op.

### FOUR methods have this shape, not two

The issue names `decide()` on both stores. `mark_fulfilled()` has the identical defect and is
NOT in the issue text — I found it while verifying:

| File | Method | Mutation line |
|---|---|---|
| `capability_request.py` | `decide()` | `req.status = "approved" if approve else "denied"` |
| `capability_request.py` | `mark_fulfilled()` | `req.status = "fulfilled"` |
| `skill_request.py` | `decide()` | `req.status = "approved" if approve else "denied"` |
| `skill_request.py` | `mark_fulfilled()` (verify it exists and matches) | — |

Fix all that match. `mark_fulfilled` matters more after #1164, which will call it for every
request kind rather than only `continue`.

### Required change

In each method: build the updated object with `dataclasses.replace(req, ...)`, perform the
`execute` + `commit`, and only then publish it into `self._cache`. Return the new object.

- On exception the cache must still hold the **pending** original, and the exception must
  propagate — callers decide how to degrade. Do not swallow it here.
- The `_emit(...)` payload and the trust `record_outcome` call must read from the **updated**
  object, and must run only after a successful commit. A decision that did not persist must not
  emit `CAPABILITY_REQUEST_DECIDED` and must not move trust.
- When `self._db` is falsy (the documented cache-only mode) the publish still happens — that
  path has no commit to fail, and its behaviour must stay byte-identical to today.

---

## Part B — a failed fulfilment reports success and consumes the only retry

### Verified current state

`src/probos/routers/capability_requests.py`:

- `:87` — the already-decided guard raises HTTP 400 for any `existing.status != "pending"`.
- `:92` — `decide()` records the decision durably.
- `:101` — `await _maybe_fulfil_on_approval(...)`; **the return value is discarded**.
- `:148-156` — the helper catches its own exceptions and returns `False`.

So: approval recorded, fulfilment failed, HTTP 200 returned, card removed by the UI, work item
still blocked, and a second attempt is refused as already decided.

### Required change

Admit a **retry of the fulfilment** — not a re-decision:

- When `existing.status == "approved"` and the incoming request has `approve is True`, do
  **not** call `store.decide()` again. Re-run the fulfilment step only.
- **This is load-bearing:** `decide()` calls `self._trust_network.record_outcome(...)`. Calling
  it twice for one approval would inflate the requesting agent's trust on a retry. Deciding
  once and retrying fulfilment separately is what prevents that.
- Every other non-pending status keeps returning HTTP 400. A `denied` request is not
  re-decidable here, and re-*denying* an approved one is a revocation — a different operation,
  explicitly out of scope.
- Add the fulfilment outcome to the response body (e.g. a boolean) so a caller can tell
  "approved and fulfilled" from "approved, fulfilment pending". Keep the existing keys.
- The route still returns 200 when fulfilment fails. Do **not** raise. The approval is durably
  recorded and failing the request would discard it — that is worse than the bug being fixed.

---

## Out of scope — do not do these

- **No UI changes.** Making the card survive an unfulfilled approval is #1168's, which is
  already rewriting that panel's reconciliation. Two units editing
  `CapabilityRequestPanel.tsx` would collide.
- Do not add fulfillers for `grant` / `install` / `build` — that is #1164.
- Do not change `_FULFIL_ON_APPROVAL_KINDS`.
- Do not alter the denial path: `CapabilityGapDriver._cancel` already handles a denied request
  off the `DECIDED` event.

---

## Tests

`tests/test_bf722_approval_transaction_integrity.py`.

**Part A — one test per method per store (four minimum):**
1. Inject a connection whose `execute` raises → request is still `pending` in
   `list_pending()`, cache is unchanged, no `DECIDED`/`FULFILLED` event emitted, no trust
   movement.
2. Same for `commit` raising.
3. Success path unchanged: state, event and trust all as today.
4. `db_path=""` cache-only mode is byte-identical.

Per repo convention, a store change also needs a **real-DB round-trip** (`tmp_path`): decide →
`stop()` → reopen → assert the decision reloaded. Cache-only tests cannot see column or
publish-ordering errors.

**Part B — through the actual HTTP route, not the helper:**
5. `mark_fulfilled` raises → HTTP 200, response reports not-fulfilled, request remains visible
   as an approved-unfulfilled item, work item still blocked.
6. A second POST with `approve=True` then **fulfils** it: `FULFILLED` fires and the work item
   leaves `blocked`. **This is the chain test — it must span route → store → event → work
   item.** A helper-level test does not satisfy it.
7. The retry records trust exactly **once** across both POSTs.
8. A `denied` request still returns HTTP 400 on a second decision.

**Mutation-check every fix:** revert the production change, confirm the new test fails, restore.

---

## Gates

1. Focused: the new file plus every existing test naming these modules —
   `rg -l 'capability_request|skill_request' tests/`.
2. Full Python gate:
   ```
   $env:PROBOS_DATA_DIR="$env:TEMP\bf722_$(Get-Random)"; $env:PROBOS_EMBEDDINGS='local'
   & d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/ -q -n 16 --dist=loadfile --timeout=600 2>&1 | Tee-Object -FilePath d:\ProbOS\logs\bf722-gate.log
   ```
   Never place a filter after `Tee-Object` — it silences the stream and the run gets
   backgrounded. Baseline is **22,703 nodes** (passed + skipped + failed); reconcile
   `baseline + new tests` against the result.
3. No UI change ⇒ no Vitest run required. If any `.tsx`/`.ts` file is staged, stop — that is
   scope creep.

Known flakes, not regressions: `test_ad580_alert_feedback::test_resolve_refires_after_clean_period`
(#1143) and `test_ad484_ux_adoption::test_doctor_returns_zero_on_clean_setup` (#1144).

---

## Report back

- The four (or however many) methods changed, and whether `skill_request.mark_fulfilled` existed.
- Gate numbers, reconciled against the 22,703 baseline.
- Any existing test that had to change — **especially one that encoded the current behaviour as
  the contract.** Update and explain inline; never delete. Four such tests turned up this week.
- Anything in the issue that turned out not to be true. Say so rather than implementing around it.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
