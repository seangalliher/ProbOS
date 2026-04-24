# BF-229: NATS Subject Prefix Rejects Colons from Ship DID

## Problem

After ship commissioning (Phase 7), `runtime.py:1543` sets the NATS subject prefix to `probos.{cert.ship_did}` — producing `probos.did:probos:d9832d8c-9059-4532-8fb2-c30c0678f672`. The colons in the DID cause JetStream `update_stream()` to fail silently during `set_subject_prefix()`, leaving all three JetStream streams (SYSTEM_EVENTS, WARDROOM, INTENT_DISPATCH) stranded with their Phase 1 `probos.local.*` subject filters.

All subsequent `js_publish()` calls use the new DID-based prefix, which matches no stream → `"nats: no response from stream"` on every JetStream publish.

**Impact:** Every system event, ward room event, and Hebbian update is silently dropped after ship commissioning. Core NATS pub/sub (subscriptions, request/reply) continues working because subscriptions are re-created correctly — only JetStream durable streams are affected.

## Root Cause

1. `runtime.py:1543`: `await self.nats_bus.set_subject_prefix(f"probos.{cert.ship_did}")` passes the raw DID `did:probos:<uuid>` into the subject prefix.
2. `nats_bus.py:144-148`: `set_subject_prefix()` calls `ensure_stream()` with the new prefix to update stream subject filters.
3. `nats_bus.py:555-562`: `ensure_stream()` tries `add_stream()` → fails (stream exists) → tries `update_stream()` with the colon-containing subject filter → NATS server rejects.
4. `nats_bus.py:564-565`: The outer `except Exception` catches the rejection and logs `logger.error(...)` — but does not re-raise. Silent swallow layer 1.
5. `nats_bus.py:149-150`: `set_subject_prefix()` catches any exception from `ensure_stream()` at `logger.warning`. Silent swallow layer 2.
6. Streams retain their Phase 1 `probos.local.*` subject filters. All DID-prefixed publishes match no stream.

## Fix

Three changes, all in existing files. No new files.

### 1. Sanitize Prefixes Inside NATSBus (Boundary Enforcement)

**File:** `src/probos/mesh/nats_bus.py`

**Rationale:** NATSBus is the only component that knows what characters are NATS-safe. Sanitization belongs at this boundary, not at callers. Any future caller (federation, AD-654e, multi-ship) passing a raw DID will get safe behavior automatically.

**Location:** At the top of the module (after imports), add a compiled regex for NATS-unsafe characters:

```python
import re

# BF-229: NATS subject tokens allow [A-Za-z0-9_\-] on all server versions.
# Dots are token separators. Colons, spaces, and other chars are unsafe.
_NATS_UNSAFE_CHAR = re.compile(r'[^A-Za-z0-9_\-.]')
```

**Location:** Inside `set_subject_prefix()` (line 119 of the real NATSBus class), add sanitization immediately after the method signature:

**Current code (lines 119-133):**
```python
    async def set_subject_prefix(self, prefix: str) -> None:
        """Update subject prefix and re-subscribe all tracked subscriptions.

        AD-637z: Subscriptions created via subscribe()/js_subscribe() are
        tracked in _active_subs with un-prefixed subjects. On prefix change,
        each is unsubscribed and re-created with the new prefix.
        """
        if prefix == self._subject_prefix:
            return
        old_prefix = self._subject_prefix
        self._subject_prefix = prefix
        logger.info("NATS subject prefix changed: %s → %s", old_prefix, prefix)
```

**New code:**
```python
    async def set_subject_prefix(self, prefix: str) -> None:
        """Update subject prefix and re-subscribe all tracked subscriptions.

        AD-637z: Subscriptions created via subscribe()/js_subscribe() are
        tracked in _active_subs with un-prefixed subjects. On prefix change,
        each is unsubscribed and re-created with the new prefix.

        BF-229: Sanitizes the prefix — replaces NATS-unsafe characters
        (colons, spaces, etc.) with underscores. Ship DIDs contain colons
        (did:probos:<uuid>) which some NATS server versions reject in
        subject tokens. NATSBus owns this constraint.
        """
        sanitized = _NATS_UNSAFE_CHAR.sub('_', prefix)
        if sanitized != prefix:
            logger.info("BF-229: Prefix sanitized %s → %s", prefix, sanitized)
        if sanitized == self._subject_prefix:
            return
        old_prefix = self._subject_prefix
        self._subject_prefix = sanitized
        logger.info("NATS subject prefix changed: %s → %s", old_prefix, sanitized)
```

**Also apply the same sanitization to `MockNATSBus.set_subject_prefix()`** (line 674):

**Current code (lines 674-679):**
```python
    async def set_subject_prefix(self, prefix: str) -> None:
        """Update prefix and rebuild subscriptions from _active_subs."""
        if prefix == self._subject_prefix:
            return
        old_prefix = self._subject_prefix
        self._subject_prefix = prefix
```

**New code:**
```python
    async def set_subject_prefix(self, prefix: str) -> None:
        """Update prefix and rebuild subscriptions from _active_subs."""
        sanitized = _NATS_UNSAFE_CHAR.sub('_', prefix)
        if sanitized == self._subject_prefix:
            return
        old_prefix = self._subject_prefix
        self._subject_prefix = sanitized
```

**Design choice:** Colons are replaced with underscores (`_`), not dots (`.`). Dots are NATS token separators — using dots would split `did:probos:<uuid>` into three tokens, changing the namespace depth from `probos.{ship}.*` (2 prefix tokens) to `probos.did.probos.<uuid>.*` (4 prefix tokens). This would break any position-dependent wildcards. Underscores keep the DID as a single token: `probos.did_probos_<uuid>.*` — same depth as `probos.local.*`.

### 2. Re-raise from ensure_stream() After Logging

**File:** `src/probos/mesh/nats_bus.py`

**Rationale:** The BF identifies two layers of silent swallowing. Fix #1 closes the outer layer (line 150), but `ensure_stream()` itself (line 564-565) also swallows. If a different stream issue surfaces after NATS upgrades, it will silently fail again. Re-raise gives callers a real exception.

**Location:** `ensure_stream()` outer exception handler (line 564-565).

**Current code:**
```python
        except Exception as e:
            logger.error("Failed to ensure stream '%s': %s", name, e)
```

**New code:**
```python
        except Exception as e:
            logger.error("Failed to ensure stream '%s': %s", name, e)
            raise
```

**Caller audit:** `ensure_stream()` has 4 callers:
- `startup/nats.py:54, 60, 66` — These three calls create initial streams. If they fail, startup should fail loudly. Re-raise is correct.
- `nats_bus.py:144` (inside `set_subject_prefix()`) — Already wrapped in its own `try/except` at line 149. The exception will be caught there and logged at ERROR (see Fix #3 below).

### 3. Promote Stream Update Failure to ERROR with Recovery Instructions

**File:** `src/probos/mesh/nats_bus.py`

**Location:** Line 149-150 (inside `set_subject_prefix()`).

**Current code (lines 149-150):**
```python
                except Exception as e:
                    logger.warning("Stream update on prefix change failed for %s: %s", sc["name"], e)
```

**New code:**
```python
                except Exception as e:
                    logger.error(
                        "BF-229: Stream update on prefix change failed for %s: %s — "
                        "JetStream publishes to this stream will fail. "
                        "Delete the stream (nats stream rm %s) and restart to recover.",
                        sc["name"], e, sc["name"],
                    )
```

## What This Does NOT Change

- **DID format** — `did:probos:<uuid>` remains the canonical DID everywhere (identity.py, identity ledger, birth certificates, API responses). Only the NATS subject representation is sanitized.
- **Core NATS subscriptions** — Already work correctly. The `_active_subs` re-subscription loop handles them fine.
- **JetStream consumer re-creation** — The BF-223 fix (delete-before-recreate at lines 175-191) works correctly regardless of prefix content. Consumers follow streams.
- **Federation subjects** — Use `publish_raw()`/`subscribe_raw()` (unprefixed). Verified via `grep -r 'subject_prefix' src/` — no callers reverse-parse the prefix back into a DID.
- **`runtime.py:1543`** — Still passes `f"probos.{cert.ship_did}"` to `set_subject_prefix()`. NATSBus sanitizes internally. The runtime log line (`logger.info("AD-637: NATS subject prefix updated to probos.%s", cert.ship_did)`) still shows the raw DID for traceability; the NATSBus log shows the sanitized form.
- **Durable consumer names** — Already NATS-safe (e.g., `"agent-dispatch-{agent_id}"`, `"wardroom-router"`). Not affected.

## NATS State Layers Checklist (BF-221/222/223 Lesson)

This fix operates at the prefix level, before any state layers are created/updated. All three layers verified:

- **Core NATS subscriptions** — Re-subscribed in `set_subject_prefix()` lines 157-197. Work correctly with sanitized prefix.
- **JetStream stream subject filters** — Updated in `set_subject_prefix()` lines 136-150 via `ensure_stream()`. Sanitized prefix produces valid subjects → `update_stream()` succeeds.
- **JetStream durable consumer filter_subjects** — Deleted and re-created in `set_subject_prefix()` lines 175-191 (BF-223 fix). New consumers inherit the sanitized prefix.
- **No other server-side config** bakes the subject at creation time.

## Tests

**File:** `tests/test_bf229_did_subject_sanitization.py`

### Test 1: DID colons sanitized to underscores in subject prefix
```python
@pytest.mark.asyncio
async def test_did_colons_sanitized_in_subject_prefix():
    """BF-229: Ship DID colons replaced with underscores for NATS subjects."""
    bus = MockNATSBus(subject_prefix="probos.local")
    await bus.start()

    # NATSBus sanitizes internally — caller passes raw DID
    await bus.set_subject_prefix("probos.did:probos:d9832d8c-9059-4532-8fb2-c30c0678f672")

    assert bus.subject_prefix == "probos.did_probos_d9832d8c-9059-4532-8fb2-c30c0678f672"
    assert ":" not in bus.subject_prefix
```

### Test 2: Subscriptions follow sanitized prefix
```python
@pytest.mark.asyncio
async def test_subscriptions_follow_sanitized_prefix():
    """BF-229: Subscriptions re-created with sanitized prefix deliver messages."""
    bus = MockNATSBus(subject_prefix="probos.local")
    await bus.start()

    received = []
    await bus.subscribe("system.events.test", lambda msg: received.append(msg.data))

    # Change to DID prefix — NATSBus sanitizes colons to underscores
    await bus.set_subject_prefix("probos.did:probos:abc123")

    # Publish on new (sanitized) prefix — should reach subscriber
    await bus.publish("system.events.test", {"ok": True})
    assert len(received) == 1
    assert received[0]["ok"] is True
```

### Test 3: JetStream publish succeeds after sanitized prefix change
```python
@pytest.mark.asyncio
async def test_js_publish_succeeds_after_sanitized_prefix():
    """BF-229: JetStream publishes use sanitized prefix, not raw DID."""
    bus = MockNATSBus(subject_prefix="probos.local")
    await bus.start()

    # Create stream with initial prefix
    await bus.ensure_stream("SYSTEM_EVENTS", ["system.events.>"])

    # Change to DID prefix — NATSBus sanitizes internally
    await bus.set_subject_prefix("probos.did:probos:abc123")

    # JS publish should succeed (stream filter matches sanitized prefix)
    await bus.js_publish("system.events.test_event", {"data": "value"})

    # Verify the published subject uses sanitized prefix (underscores, not colons)
    assert len(bus.published) > 0
    last_subject = bus.published[-1][0]
    assert ":" not in last_subject
    assert last_subject == "probos.did_probos_abc123.system.events.test_event"
```

### Test 4: Already-safe prefix passes through unchanged
```python
@pytest.mark.asyncio
async def test_safe_prefix_unchanged():
    """BF-229: Prefixes without unsafe chars pass through without modification."""
    bus = MockNATSBus(subject_prefix="probos.local")
    await bus.start()

    await bus.set_subject_prefix("probos.ship-abc-123")
    assert bus.subject_prefix == "probos.ship-abc-123"
```

### Test 5: Sanitization preserves namespace depth (underscores, not dots)
```python
@pytest.mark.asyncio
async def test_sanitization_preserves_namespace_depth():
    """BF-229: Colons become underscores (one token), not dots (multiple tokens).
    
    This preserves the probos.{ship}.* namespace hierarchy — the DID stays
    as a single NATS token, keeping subject depth consistent with probos.local.*.
    """
    bus = MockNATSBus(subject_prefix="probos.local")
    await bus.start()

    await bus.set_subject_prefix("probos.did:probos:abc-123")

    # Should be 2 prefix tokens (probos + did_probos_abc-123), not 4
    prefix_tokens = bus.subject_prefix.split(".")
    assert len(prefix_tokens) == 2
    assert prefix_tokens[0] == "probos"
    assert prefix_tokens[1] == "did_probos_abc-123"
```

### Update existing tests (3 occurrences)

All existing tests that pass raw DID prefixes to `set_subject_prefix()` now get automatic sanitization. Update assertions to expect the sanitized form. Greppable via `did:probos` in `tests/`.

**`tests/test_ad637a_nats_foundation.py:425-427`** — `test_nats_prefix_updated_after_ship_commissioning`:

Current assertion (line 427):
```python
        assert bus.subject_prefix == "probos.did:probos:abc123"
```
Updated:
```python
        # BF-229: NATSBus sanitizes colons → underscores
        assert bus.subject_prefix == "probos.did_probos_abc123"
```

**`tests/test_ad637z_nats_cleanup.py:46`** — `test_prefix_resubscription_routes_to_new_prefix`:

The `set_subject_prefix("probos.did:probos:abc123")` call is fine (NATSBus sanitizes internally), but if the test asserts on the exact prefix value anywhere, update to expect `"probos.did_probos_abc123"`. Verify the test still passes — it should, since publishes go through `_full_subject()` which uses the sanitized `_subject_prefix`.

**`tests/test_ad637z_nats_cleanup.py:330`** — `test_end_to_end_prefix_change_then_nats_send`:

Same pattern — `set_subject_prefix("probos.did:probos:ship-abc-123")` is fine (sanitized internally). Update any assertions on prefix value to expect `"probos.did_probos_ship-abc-123"`.

## Verification

```bash
# New BF-229 tests
pytest tests/test_bf229_did_subject_sanitization.py -v

# NATS regression (existing prefix tests updated)
pytest tests/test_ad637a_nats_foundation.py -v -k prefix
pytest tests/test_ad637z_nats_cleanup.py -v

# Full suite
pytest -n auto
```

## Post-Fix Operational Cleanup

After deploying the fix, stranded NATS streams from the old colon-containing prefix must be cleaned up once:

1. Stop ProbOS
2. Delete stranded streams: `nats stream rm SYSTEM_EVENTS`, `nats stream rm WARDROOM`, `nats stream rm INTENT_DISPATCH`
3. Start ProbOS — startup will recreate streams with the sanitized `probos.did_probos_<uuid>.*` subject filters

This is a one-time manual step. Document in the PR description.

## Tracking

Update these files after implementation:
- `PROGRESS.md` — Update BF-229 to CLOSED
- `docs/development/roadmap.md` — Update BF-229 row to Closed
- `DECISIONS.md` — Add entry: "BF-229: NATSBus owns subject sanitization; callers may pass any string."
