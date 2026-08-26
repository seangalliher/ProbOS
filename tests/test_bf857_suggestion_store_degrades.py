"""BF-857 (#1327): the store said it never raises, and half of it did.

``WorkspaceSuggestionStore``'s class docstring claimed "All methods are
honest-degrading and never raise on bad keys". ``add`` and ``list`` built a
``dict`` key from ``(owner, path)``, so an unhashable owner raised
``TypeError``. ``clear(path=...)`` did the same. Only ``dismiss`` and
``clear(path=None)`` compared rather than hashed, and were genuinely safe.

Fixed by making the claim true rather than narrowing it: honest-degrade is this
module's stated contract, half the class already honoured it, and the keys
arrive from agent-supplied paths -- so "well-formed key" would be an assumption
about a caller, which BF-763 established a module cannot make on its callers'
behalf.

**A premise these tests exist to protect.** The probe that produced the issue
ran each method against an EMPTY store, and CPython skips hashing a lookup on
an empty dict -- so ``clear`` reported "ok" while still hashing. The issue was
filed saying ``clear`` was safe. It was not; the probe simply could not tell.
Every test below seeds the store first, and ``_seeded`` asserts that it did.
"""

from __future__ import annotations

import pytest

from probos.execution.workspace_suggestions import WorkspaceSuggestionStore

#: Unhashable. The whole point.
BAD_KEY: list[str] = []


class _Unstringable:
    def __str__(self) -> str:
        raise RuntimeError("unstringable")


def _seeded() -> WorkspaceSuggestionStore:
    """A store that is NOT empty.

    An empty dict can answer a lookup without hashing the key, so a bad-key
    test against an empty store proves nothing. This is the premise assertion
    the original probe lacked.
    """
    store = WorkspaceSuggestionStore()
    store.add("someone-else", "other/path", "content", "agent-0")
    assert store.list("someone-else", "other/path"), (
        "premise: the store must hold an entry, or a dict lookup may skip "
        "hashing and every assertion below is vacuous"
    )
    return store


def test_the_premise_that_the_key_is_actually_unhashable() -> None:
    """If ``BAD_KEY`` were hashable, none of this would be testing anything."""
    with pytest.raises(TypeError):
        {(BAD_KEY, "x"): 1}  # type: ignore[dict-item]


class TestEveryMethodDegrades:
    """One test per method, because it was per-method that they disagreed."""

    def test_add(self) -> None:
        assert _seeded().add(BAD_KEY, "x", "c", "a") is not None

    def test_list(self) -> None:
        assert _seeded().list(BAD_KEY, "x") == []

    def test_dismiss(self) -> None:
        """Always degraded -- it compares rather than hashes. Pinned so a
        future rewrite to a dict lookup does not reintroduce the defect."""
        assert _seeded().dismiss(BAD_KEY, "no-such-id") is False

    def test_clear_with_a_path(self) -> None:
        """The one the original probe got wrong."""
        _seeded().clear(BAD_KEY, "x")

    def test_clear_without_a_path(self) -> None:
        _seeded().clear(BAD_KEY)

    @pytest.mark.parametrize(
        "call",
        [
            lambda s: s.add(_Unstringable(), "x", "c", "a"),
            lambda s: s.list(_Unstringable(), "x"),
            lambda s: s.clear(_Unstringable(), "x"),
        ],
    )
    def test_even_a_key_whose_str_raises(self, call) -> None:
        """A store whose contract is "never raises" cannot make an exception
        for the object that made it hard."""
        call(_seeded())


class TestTheMethodsAgreeOnACoercedKey:
    """Degrading is not enough: if ``add`` normalises one way and ``dismiss``
    another, a suggestion becomes unreachable by the caller that created it --
    a quieter defect than the crash, and one a per-method fix would produce."""

    def test_add_then_list_finds_it(self) -> None:
        store = _seeded()

        store.add(BAD_KEY, "p", "content", "agent-1")

        assert len(store.list(BAD_KEY, "p")) == 1

    def test_add_then_dismiss_finds_it(self) -> None:
        store = _seeded()

        added = store.add(BAD_KEY, "p", "content", "agent-1")

        assert store.dismiss(BAD_KEY, added.id) is True

    def test_add_then_clear_empties_it(self) -> None:
        store = _seeded()
        store.add(BAD_KEY, "p", "content", "agent-1")

        store.clear(BAD_KEY, "p")

        assert store.list(BAD_KEY, "p") == []

    def test_add_then_clear_without_a_path_empties_it(self) -> None:
        """The path-less branch compares rather than hashes, so it never
        crashed -- but it compared the RAW owner against a normalised key and
        matched nothing. A mutant that stopped normalising here survived every
        other test in this file: not raising is not the same as working.
        """
        store = _seeded()
        store.add(BAD_KEY, "p", "content", "agent-1")
        store.add(BAD_KEY, "q", "content", "agent-1")

        store.clear(BAD_KEY)

        assert store.list(BAD_KEY, "p") == []
        assert store.list(BAD_KEY, "q") == []
        # And it cleared only that owner.
        assert len(store.list("someone-else", "other/path")) == 1

    def test_the_bad_key_does_not_collide_with_another_owner(self) -> None:
        """Coercion maps to a string, so it must not land on someone else's
        bucket. The seeded owner is the neighbour it could have hit."""
        store = _seeded()

        store.add(BAD_KEY, "p", "content", "agent-1")

        assert len(store.list("someone-else", "other/path")) == 1

    def test_a_bad_PATH_agrees_across_the_methods_too(self) -> None:
        """Review's gap: every other agreement test varies the OWNER, so a
        future edit could normalise the path inconsistently and crash nothing
        while making the suggestion unreachable."""
        store = _seeded()
        bad_path: list[str] = []

        store.add("owner", bad_path, "content", "agent-1")

        assert len(store.list("owner", bad_path)) == 1
        store.clear("owner", bad_path)
        assert store.list("owner", bad_path) == []


class TestCoercionAliasesDistinctKeys:
    """Stated, not accidental.

    ``str()`` is not injective, so an owner ``['a']`` and an owner ``"['a']"``
    share a bucket after coercion. Review confirmed this by execution and
    confirmed it is unreachable from production today: every ingress is typed
    ``str`` (``WorkspaceSuggestionCreate.path``, the list endpoint's query
    param) and the owner comes from ``workspace.key_for_agent``, which returns
    a sanitised string.

    Pinned rather than fixed. The alternative -- keying on identity for
    non-strings -- would make two calls with equal-but-distinct objects miss
    each other, which is a worse failure than aliasing for a store whose whole
    contract is honest-degrade. If a caller ever passes raw objects, this test
    is where the trade-off is written down.
    """

    def test_a_list_and_its_string_form_share_a_bucket(self) -> None:
        store = WorkspaceSuggestionStore()

        store.add(["a"], "p", "content", "agent-1")
        store.add("['a']", "p", "content", "agent-2")

        assert len(store.list(["a"], "p")) == 2

    def test_two_unstringable_owners_also_share_one(self) -> None:
        """Both degrade to the same sentinel. Same trade-off, same reasoning."""
        store = WorkspaceSuggestionStore()

        store.add(_Unstringable(), "p", "c", "a")
        store.add(_Unstringable(), "p", "c", "b")

        assert len(store.list(_Unstringable(), "p")) == 2


class TestOrdinaryKeysAreUntouched:
    """The fix must be invisible on the path everything actually uses."""

    def test_add_list_dismiss_clear_round_trip(self) -> None:
        store = WorkspaceSuggestionStore()

        one = store.add("owner", "p", "c", "a")
        assert len(store.list("owner", "p")) == 1
        assert store.dismiss("owner", one.id) is True

        store.add("owner", "p", "c", "a")
        store.clear("owner")
        assert store.list("owner", "p") == []

    def test_a_str_key_is_not_reconstructed(self) -> None:
        """``_key`` returns ``str`` inputs unchanged rather than round-tripping
        them through ``str()``, so no subclass with a custom ``__str__`` can
        silently change which bucket it lands in."""
        class _Weird(str):
            def __str__(self) -> str:
                return "something-else"

        store = WorkspaceSuggestionStore()
        store.add(_Weird("owner"), "p", "c", "a")

        assert len(store.list("owner", "p")) == 1


class TestTheDocstringMatchesTheCode:
    """BF-781's rule: a claim and its correction must both be checked, or the
    prose drifts back."""

    def test_the_claim_is_still_made(self) -> None:
        assert "never raise on bad keys" in (
            WorkspaceSuggestionStore.__doc__ or ""
        )

    def test_and_the_correction_records_why(self) -> None:
        doc = WorkspaceSuggestionStore.__doc__ or ""

        assert "BF-857" in doc
        assert "false for three of the five call shapes" in doc

    def test_the_correction_records_the_RIGHT_measurement(self) -> None:
        """The class docstring first carried the wrong table -- the one taken
        against an empty store, saying ``clear`` was safe. I corrected
        ``clear``'s own docstring and left this one false, which is the same
        split-brain defect in miniature. Both halves are pinned now."""
        doc = WorkspaceSuggestionStore.__doc__ or ""

        assert "clear(path=...): TypeError" in doc
        assert "dismiss: ok      clear(path=None): ok" in doc
        # And the reason the first measurement lied, so nobody repeats it.
        assert "without hashing" in doc
