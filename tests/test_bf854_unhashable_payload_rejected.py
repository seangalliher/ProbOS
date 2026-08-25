"""BF-854: the validator must refuse what the dedup key cannot hash.

A lone surrogate (``"\\ud800"``) is a legal Python ``str``, survives
``json.loads`` of the escape sequence a database row holds, and passes straight
through ``_canonical_json`` because that sets ``ensure_ascii=False``. So
``validate_action_payload`` accepted it: its own canonicalisation did not raise,
and only the resulting LENGTH was checked.

``action_dedup_key`` then raises ``UnicodeEncodeError`` on the same value. The
existing ``try/except`` in that function does not help -- it wraps
``_canonical_json``, which does not raise; the failure lands on the unguarded
``material.encode("utf-8")`` at the end.

That asymmetry is not one bad request. ``_find_pending_action`` re-derives the
key for EVERY cached row on every filing, and ``_refresh_cache`` loads all rows
at ``start()``. One such row therefore makes ``file_action_request`` raise for
every unrelated caller until it is removed -- a single row silently disabling
the approval path.

Measured before the fix, by field:

    scope_key       validated=True  hashable=False   <-- accepted but unhashable
    params value    validated=True  hashable=False   <-- accepted but unhashable
    params key      validated=True  hashable=False   <-- accepted but unhashable
    thread_id       validated=True  hashable=True
    session_id      validated=True  hashable=True
    tool_id         validated=False (regex rejects)
    action          validated=False (regex rejects)

Surrogates are how Python carries undecodable bytes -- ``surrogateescape`` is
the standard handler -- so any path routing raw tool output, subprocess stderr
or a filesystem name into a payload can produce one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from probos.capability_request import (
    _ACTION_PAYLOAD_MAX_CHARS,
    CapabilityRequestStore,
    _decode_payload,
    action_dedup_key,
    validate_action_payload,
)

LONE_SURROGATE = "\ud800"


def _payload(**over):
    base = {
        "tool_id": "browser",
        "action": "dispatch",
        "params": {"detail": "ordinary"},
        "scope_key": "s1",
        "session_id": None,
        "thread_id": "t1",
    }
    base.update(over)
    return base


def _hashable(payload) -> bool:
    try:
        action_dedup_key(agent_id="a1", payload=payload, work_item_id=None)
    except UnicodeEncodeError:
        return False
    return True


# ---------------------------------------------------------------------------
# The premise
# ---------------------------------------------------------------------------

def test_an_ordinary_payload_still_validates_and_hashes() -> None:
    """Guards the guard: if this fails the rest proves nothing."""
    payload = _payload()

    assert validate_action_payload(payload) is payload
    assert _hashable(payload)


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "field, payload",
    [
        ("scope_key", _payload(scope_key=LONE_SURROGATE)),
        ("params value", _payload(params={"detail": LONE_SURROGATE})),
        ("params key", _payload(params={LONE_SURROGATE: "x"})),
        ("thread_id", _payload(thread_id=LONE_SURROGATE)),
        ("session_id", _payload(session_id=LONE_SURROGATE)),
    ],
)
def test_anything_the_validator_accepts_can_be_hashed(field, payload) -> None:
    """The whole point: acceptance and hashability must not disagree.

    Asserted as an implication rather than as a list of rejections, so it holds
    however the rejection is implemented -- and would still hold if a future
    change made one of these hashable instead of rejected.
    """
    if validate_action_payload(payload) is not None:
        assert _hashable(payload), (
            f"a lone surrogate in {field} was accepted but cannot be hashed; "
            "one such row breaks file_action_request for every caller"
        )


def test_the_three_key_bearing_fields_are_rejected() -> None:
    """``scope_key`` and both halves of ``params`` feed the key material.

    Named separately from the implication above because these are the ones that
    were measured broken -- the implication would also pass if they were made
    hashable, and that is not what shipped.
    """
    assert validate_action_payload(_payload(scope_key=LONE_SURROGATE)) is None
    assert validate_action_payload(_payload(params={"d": LONE_SURROGATE})) is None
    assert validate_action_payload(_payload(params={LONE_SURROGATE: "x"})) is None


@pytest.mark.parametrize("field", ["thread_id", "session_id"])
def test_rejecting_the_non_key_fields_is_not_a_regression(
    field: str, tmp_path: Path,
) -> None:
    """``thread_id`` and ``session_id`` do NOT feed the key material, and before
    this change they validated AND hashed. Rejecting them could therefore be a
    regression -- so prove it is not: such a payload could never be PERSISTED.

    ``_canonical_json`` sets ``ensure_ascii=False``, so the str bound to the
    TEXT column carries the raw surrogate and SQLite raises on the insert. The
    guard converts a crash at write time into a clean ``None`` with a logged
    warning, which is why it is checked over the whole canonical payload rather
    than only over the key-bearing fields.
    """
    import json
    import sqlite3

    payload = _payload(**{field: LONE_SURROGATE})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False)

    conn = sqlite3.connect(tmp_path / f"{field}.db")
    try:
        conn.execute("CREATE TABLE t (payload TEXT)")
        # Premise: an ordinary payload must persist, or this proves nothing.
        conn.execute("INSERT INTO t VALUES (?)", (
            json.dumps(_payload(), sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False),
        ))

        with pytest.raises(UnicodeEncodeError):
            conn.execute("INSERT INTO t VALUES (?)", (encoded,))
    finally:
        conn.close()

    # And so refusing it up front is the correct behaviour, not a loss.
    assert validate_action_payload(payload) is None


# ---------------------------------------------------------------------------
# The bound must NOT become a byte bound
# ---------------------------------------------------------------------------

def test_a_multibyte_payload_under_the_char_bound_is_still_accepted() -> None:
    """The migration hazard, pinned.

    Expressing this fix by switching the length bound to bytes would reject
    payloads that were valid when they were written -- and ``_decode_payload``
    re-validates on READ, so those approvals would silently lose their payload
    on the next restart. This payload is comfortably under the character bound
    and far over it in bytes; it must remain acceptable.
    """
    # Each CJK character is 3 UTF-8 bytes.
    body = "\u6f22" * 2000
    payload = _payload(params={"detail": body})

    assert validate_action_payload(payload) is payload
    assert _hashable(payload)

    import json
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False)
    assert len(encoded) <= _ACTION_PAYLOAD_MAX_CHARS
    assert len(encoded.encode("utf-8")) > _ACTION_PAYLOAD_MAX_CHARS


# ---------------------------------------------------------------------------
# The consumer
# ---------------------------------------------------------------------------

def test_a_poisoned_row_decodes_to_none_instead_of_raising() -> None:
    """``_decode_payload`` documents that it never raises. A stored row holding
    the escape sequence must degrade to ``payload=None``, not take the store
    down on the way up."""
    raw = (
        '{"tool_id":"browser","action":"dispatch",'
        '"params":{"detail":"\\ud800"},'
        '"scope_key":"s1","session_id":null,"thread_id":"t1"}'
    )

    assert _decode_payload(raw) is None


@pytest.mark.asyncio
async def test_the_store_starts_with_a_poisoned_row_present(
    tmp_path: Path,
) -> None:
    """End to end: the row is already on disk when the store opens.

    This is the shape that matters -- the defect is not a rejected request, it
    is a persisted row that breaks every later filing.
    """
    import aiosqlite

    db = str(tmp_path / "cap.db")
    store = CapabilityRequestStore(db_path=db)
    await store.start()
    try:
        row = await store.file_action_request(
            agent_id="a1",
            payload=_payload(),
            work_item_id=None,
            rationale="first",
        )
        assert row is not None
    finally:
        await store.stop()

    # Poison the stored payload behind the store's back.
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "UPDATE capability_requests SET payload = ?",
            ('{"tool_id":"browser","action":"dispatch",'
             '"params":{"detail":"\\ud800"},'
             '"scope_key":"s1","session_id":null,"thread_id":"t1"}',),
        )
        await conn.commit()

    reopened = CapabilityRequestStore(db_path=db)
    await reopened.start()
    try:
        # A later, unrelated filing must still succeed.
        later = await reopened.file_action_request(
            agent_id="a2",
            payload=_payload(scope_key="s2"),
            work_item_id=None,
            rationale="unrelated",
        )
        assert later is not None, (
            "a poisoned row broke an unrelated filing"
        )
    finally:
        await reopened.stop()
