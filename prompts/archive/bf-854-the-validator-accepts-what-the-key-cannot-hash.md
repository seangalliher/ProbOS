# BF-854 — `validate_action_payload` accepts a payload `action_dedup_key` cannot hash

**Status:** Ready to build
**Depends on:** nothing. Lands FIRST, alone.
**Blocks:** AD-1267 (repair proposals route arbitrary tool error text through `action_dedup_key`).
**Estimated tests:** ≥ 6 new

---

## Numbering

Highest allocated at time of writing: **AD-1266** (`prompts/ad-1266-restore-is-point-in-time.md`),
**BF-853**. Collision check run against `PROGRESS.md`, `DECISIONS.md` and
`docs/development/roadmap.md` for `AD-1267|BF-854` — **no hits, both free.**

- **This work is BF-854.** Next free BF after this one: **BF-855.**

---

## Problem

`validate_action_payload` accepts a payload that `action_dedup_key` then **raises** on. The two
functions disagree about what "well-formed" means, and the store's documented stance —
*bad payload returns `None`, never raises* — is broken by the disagreement.

`capability_request.py:99-143` validates in **characters** and never encodes:

```python
    try:
        encoded = _canonical_json(payload)          # json.dumps(ensure_ascii=False)
    except (TypeError, ValueError, OverflowError):
        return None
    if len(encoded) > _ACTION_PAYLOAD_MAX_CHARS:
        return None
    return payload
```

`json.dumps(..., ensure_ascii=False)` happily emits a lone surrogate, so a payload containing
`"\ud800"` validates. `capability_request.py:174-200` then encodes it, **outside** its guard:

```python
    try:
        canonical_params = _canonical_json(payload.get("params"))
    except (TypeError, ValueError, OverflowError):
        canonical_params = "\ufffd"
    material = "|".join([...])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()   # <- raises
```

### Measured against the real store

```
validate_action_payload(surrogate) is not None: True
action_dedup_key RAISED: UnicodeEncodeError

start() with a surrogate row: OK
cached rows: 1 payload loaded? True
a LATER unrelated file_action_request RAISED: UnicodeEncodeError <- store poisoned
```

Two distinct reachable harms:

1. **A live caller** passing a surrogate gets `UnicodeEncodeError` out of `file_action_request`,
   whose contract is to return `None` for a payload it will not record.
2. **One persisted row poisons the whole approval surface.** `_find_pending_action`
   (`capability_request.py:422`) re-derives the key for **every cached action row** on **every**
   filing. A single bad row makes every subsequent `file_action_request` — from any caller, for any
   tool — raise. `start()` itself succeeds, so this fails silently and late rather than loudly at boot.

### Why this is reachable, not hypothetical

Lone surrogates are how Python represents undecodable bytes: anything read with
`errors="surrogatepass"`/`"surrogateescape"` carries them. Tool error text is exactly such input, and
AD-1267 routes tool error text into `params`. This is on that critical path.

### Correction to the reported symptom

The originally-reported form of this — *"a persisted row prevents `CapabilityRequestStore.start()`
from starting, against `_decode_payload`'s never-raises contract"* — is **an artifact of the reverted
AD-1264 attempt, not a defect at HEAD.** That attempt changed the bound from characters to bytes
(`.git/AD1264_ATTEMPT.patch` line 116: `+ if len(encoded.encode("utf-8")) > _ACTION_PAYLOAD_MAX_BYTES:`),
which put an encode on the **read** path through `_decode_payload`. Verified at HEAD:

```
has _ACTION_PAYLOAD_MAX_CHARS: True
has _ACTION_PAYLOAD_MAX_BYTES: False
_decode_payload(surrogate row): OK, payload is None? False
```

`start()` does not crash at HEAD. The residue is narrower in scope and worse in character: silent,
deferred, and it takes out every caller rather than one.

---

## Solution

Reject at the boundary that decides well-formedness, and make the key function total.

**The bound stays in characters.** Switching it to bytes is a *tightening* applied on the read path
too (`_decode_payload` re-validates), so a persisted row that was valid under characters would load
with `payload=None` and silently lose the payload of an existing pending approval. That is a
migration hazard, it is what the reverted attempt introduced, and it is not this BF's problem to
solve. If the unit should change, that is its own AD with its own migration.

### Section 1 — `src/probos/capability_request.py`: reject unencodable text

Detect the surrogate explicitly, inside the existing guard, without touching the unit of the bound.

```
===SEARCH===
    try:
        encoded = _canonical_json(payload)
    except (TypeError, ValueError, OverflowError):
        return None
    if len(encoded) > _ACTION_PAYLOAD_MAX_CHARS:
        return None
    return payload
===REPLACE===
    try:
        encoded = _canonical_json(payload)
        # BF-854: json.dumps(ensure_ascii=False) emits lone surrogates happily,
        # but action_dedup_key must UTF-8 encode this to hash it, and sqlite
        # must encode it to store it. Accepting text that neither can encode is
        # what let one hand-edited row raise UnicodeEncodeError out of every
        # later file_action_request, for every caller. The bound below stays in
        # characters on purpose: measuring it in bytes would re-validate
        # persisted rows against a tighter rule on read and silently drop the
        # payload of approvals that were valid when filed.
        encoded.encode("utf-8")
    except (TypeError, ValueError, OverflowError, UnicodeEncodeError):
        return None
    if len(encoded) > _ACTION_PAYLOAD_MAX_CHARS:
        return None
    return payload
===END REPLACE===
```

This one change fixes **both** harms, because `_decode_payload` re-validates on load: a poisoned row
now loads with `payload=None`, and `_find_pending_action` already skips rows whose payload is `None`
(`capability_request.py:423`). Confirm that skip is present before relying on it.

### Section 2 — `src/probos/capability_request.py`: make the key function total

`action_dedup_key` is public and documents no precondition. Its callers now pre-validate, but the
guarantee should not rest on that.

```
===SEARCH===
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
===REPLACE===
    # BF-854: total by construction. Callers pre-validate, but this is public and
    # states no precondition; surrogatepass is byte-identical for encodable text,
    # so no existing key changes.
    return hashlib.sha256(
        material.encode("utf-8", errors="surrogatepass")
    ).hexdigest()
===END REPLACE===
```

Assert the "no existing key changes" claim in a test rather than in the comment alone.

---

## Tests

New file `tests/test_bf854_validator_and_key_agree.py`.

1. `test_a_lone_surrogate_payload_is_refused_not_raised` — `validate_action_payload` returns `None`;
   assert the same payload validated **before** this fix by asserting the *reason* (it is otherwise a
   well-formed six-key payload) so the test cannot pass for the wrong reason.
2. `test_file_action_request_refuses_a_surrogate_rather_than_raising` — real store on `tmp_path`;
   returns `None`, and `list_pending()` is empty.
3. `test_a_hand_edited_surrogate_row_does_not_poison_the_store` — the P6 reproduction. Seed a row via
   raw `sqlite3` with `json.dumps` (which escapes to `\ud800`), `start()` a real store, then assert an
   **unrelated** `file_action_request` from a different agent succeeds and returns a request.
   Positive premise first: assert the row is in `_cache` and that its `payload` is now `None`.
4. `test_the_poisoned_row_still_loads_as_a_request` — the row is not dropped; only its payload is.
   Guards against "fixed by deleting the row".
5. `test_valid_unicode_keys_are_unchanged` — pin a known-good payload's hex digest across the
   `surrogatepass` change: compute the digest with `errors="strict"` on the same material and assert
   equality. This is the assertion that Section 2 changed nothing for real traffic.
6. `test_a_wide_character_payload_is_still_measured_in_characters` — a payload of multi-byte
   characters whose UTF-8 length exceeds 4,000 but whose character length does not **still validates**.
   This pins the unit of the bound so a future change to bytes has to break a test that says why.

---

## What this does NOT change

- The unit of `_ACTION_PAYLOAD_MAX_CHARS`. Do **not** introduce `_ACTION_PAYLOAD_MAX_BYTES`.
- `file_request`'s commit-then-emit ordering.
- `_find_pending_action`'s pending-only filter.
- `_decode_payload`, `_migrate_payload_column`, `start`, `decide`, `mark_fulfilled`.
- Anything in `repair_dispatch.py`, `repair_brief.py` or `fault_report.py`. Those are AD-1267.

---

## Acceptance criteria

- [ ] The six tests above pass, each with a positive premise assertion beside every negative one.
- [ ] Full gate green: `pytest tests/ -q -n 4 --dist=loadfile`.
- [ ] The P6 reproduction fails against HEAD before the fix. Record the failure output in the commit
      message — a regression test that never failed is not a regression test.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Stop rule

If review finds a defect **inside the guard this BF adds** — not merely in the diff, but in the
rejection path itself — stop, revert, and hand back. Two findings at one seam is the signal; do not
open a third round. This is a six-line change and it should not have a protocol.

---

## Verified against codebase (2026-08-24)

```
HEAD f3348ca4, tree clean.

Probe against the real store:
  has _ACTION_PAYLOAD_MAX_CHARS: True
  has _ACTION_PAYLOAD_MAX_BYTES: False
  validate_action_payload(surrogate) is not None: True
  action_dedup_key RAISED: UnicodeEncodeError
  _decode_payload(surrogate row): OK, payload is None? False
  start() with a surrogate row: OK
  cached rows: 1 payload loaded? True
  a LATER unrelated file_action_request RAISED: UnicodeEncodeError

capability_request.py:54   _ACTION_PAYLOAD_MAX_CHARS = 4000
capability_request.py:99   def validate_action_payload(payload: Any) -> dict[str, Any] | None:
capability_request.py:146  def _decode_payload(raw: Any) -> dict[str, Any] | None:   ("Never raises")
capability_request.py:174  def action_dedup_key(...)
capability_request.py:422  def _find_pending_action(self, key: str) -> CapabilityRequest | None:

.git/AD1264_ATTEMPT.patch:116
  +    if len(encoded.encode("utf-8")) > _ACTION_PAYLOAD_MAX_BYTES:
  -> the start() crash was introduced by the reverted attempt, not present at HEAD.
```
