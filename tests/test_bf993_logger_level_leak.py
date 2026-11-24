"""BF-993 (#1523, #1815): calling _setup_logging in a test leaves no logger pinned."""

from __future__ import annotations

import logging
import uuid

import pytest

from tests.fixtures.logger_levels import restored_logger_levels
from tests.test_bf748_file_log_carries_the_date import _handlers

PINNED = (  # src/probos/__main__.py:187-197
    "asyncio", "aiosqlite", "httpx", "httpcore", "probos.substrate.agent",
    "probos.federation", "probos.cognitive.decomposer", "probos.mesh.intent",
    "probos.mesh.routing", "probos.substrate.spawner", "probos.substrate.pool",
)


def test_the_file_log_helper_leaves_the_pinned_loggers_as_it_found_them() -> None:
    root = logging.getLogger()
    root_level = root.level  # _setup_logging sets it; _handlers does not put it back
    try:
        with restored_logger_levels():
            for name in PINNED:
                logging.getLogger(name).setLevel(logging.NOTSET)
            for handler in _handlers():
                if isinstance(handler, logging.FileHandler):
                    handler.close()
            assert {name: logging.getLogger(name).level for name in PINNED} == dict.fromkeys(
                PINNED, logging.NOTSET,
            )
    finally:
        root.setLevel(root_level)


def test_a_level_set_inside_is_put_back_and_a_logger_made_inside_is_left_notset() -> None:
    existing = logging.getLogger("probos.test.bf993.existing")
    existing.setLevel(logging.INFO)
    try:
        with restored_logger_levels():
            existing.setLevel(logging.ERROR)
            made = logging.getLogger(f"probos.test.bf993.made.{uuid.uuid4().hex}")
            made.setLevel(logging.WARNING)
        assert (existing.level, made.level) == (logging.INFO, logging.NOTSET)
    finally:
        existing.setLevel(logging.NOTSET)


def test_the_levels_are_put_back_when_the_block_raises() -> None:
    decomposer = logging.getLogger("probos.cognitive.decomposer")
    before = decomposer.level
    with pytest.raises(RuntimeError), restored_logger_levels():
        decomposer.setLevel(logging.CRITICAL)
        raise RuntimeError("bf993")
    assert decomposer.level == before
