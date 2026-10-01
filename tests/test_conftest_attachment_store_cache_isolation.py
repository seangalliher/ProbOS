"""tests/conftest.py isolates the chat router's id(runtime)-keyed store cache.

``probos.routers.chat._ATTACHMENT_STORE_CACHE`` is keyed by ``id(runtime)``.
Python recycles ids once an object is freed, so an entry a finished test left
behind could answer a later test's brand-new runtime with the wrong store. In CI
that made BF-666's resolver-failure test see no CancelledError. The autouse
``_ad682_clear_module_caches`` fixture clears the cache before every test.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

import probos.routers.chat as chat_router


class _Runtime:
    pass


#: Held for the whole module so its id cannot be recycled while seeded.
_EARLIER_RUNTIME = _Runtime()


@pytest.fixture(scope="module")
def entry_left_by_an_earlier_test() -> Iterator[int]:
    """Seeds a stale entry the way an earlier test on the worker would.

    Module scope is set up before the function-scoped autouse fixture under
    test, so the entry exists when that fixture runs.
    """
    key = id(_EARLIER_RUNTIME)
    chat_router._ATTACHMENT_STORE_CACHE[key] = object()
    yield key
    chat_router._ATTACHMENT_STORE_CACHE.pop(key, None)


def test_each_test_starts_with_an_empty_attachment_store_cache(
    entry_left_by_an_earlier_test: int,
) -> None:
    assert entry_left_by_an_earlier_test not in chat_router._ATTACHMENT_STORE_CACHE, (
        "an id-keyed entry from an earlier test survived into this one"
    )
    assert chat_router._ATTACHMENT_STORE_CACHE == {}
