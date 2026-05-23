"""BF-295 (#748): per-migration timeout + elapsed-time logging.

Tests:
1. Config default and validation range.
2. Helper logs start message before the migration is awaited.
3. Helper logs WARNING + returns normally on TimeoutError.
4. Helper logs INFO with elapsed time on success.
5. Helper logs WARNING with traceback on unexpected exception.
"""

from __future__ import annotations

import asyncio
import logging
import re

import pytest

from probos.config import MemoryConfig, SystemConfig
from probos.startup.cognitive_services import _run_one_migration


def test_migration_timeout_config_default_is_300s() -> None:
    config = SystemConfig()
    assert config.memory.migration_timeout_s == 300.0


def test_migration_timeout_config_validates_range() -> None:
    # Accepts boundary values
    assert MemoryConfig(migration_timeout_s=10.0).migration_timeout_s == 10.0
    assert MemoryConfig(migration_timeout_s=3600.0).migration_timeout_s == 3600.0
    assert MemoryConfig(migration_timeout_s=300.0).migration_timeout_s == 300.0

    # Rejects out-of-range
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        MemoryConfig(migration_timeout_s=5.0)
    with pytest.raises(ValidationError):
        MemoryConfig(migration_timeout_s=4000.0)


@pytest.mark.asyncio
async def test_migration_start_message_logged_before_call(
    caplog: pytest.LogCaptureFixture,
) -> None:
    awaited = {"flag": False}

    async def fake_migration() -> int:
        awaited["flag"] = True
        await asyncio.sleep(0.01)
        return 0

    caplog.set_level(logging.INFO, logger="probos.startup.cognitive_services")
    await _run_one_migration(
        "BF-103",
        fake_migration,
        timeout_s=5.0,
        success_template="BF-103: Migrated %d episodes in %.1fs",
        noop_template="BF-103: completed in %.1fs (no episodes needed migration)",
    )

    assert awaited["flag"] is True
    start_records = [
        r for r in caplog.records
        if "BF-103: starting" in r.getMessage()
    ]
    assert len(start_records) == 1
    assert "timeout=5s" in start_records[0].getMessage()


@pytest.mark.asyncio
async def test_migration_timeout_logs_warning_and_does_not_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def slow_migration() -> int:
        await asyncio.sleep(10.0)
        return 0

    caplog.set_level(logging.WARNING, logger="probos.startup.cognitive_services")

    # Must not raise
    await _run_one_migration(
        "BF-103",
        slow_migration,
        timeout_s=0.05,
        success_template="BF-103: Migrated %d episodes in %.1fs",
        noop_template="BF-103: completed in %.1fs",
    )

    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "BF-103" in r.getMessage()
    ]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "timed out after 0s" in msg
    assert "proceeding with degraded state" in msg


@pytest.mark.asyncio
async def test_migration_success_logs_elapsed_time(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fast_migration() -> int:
        await asyncio.sleep(0.02)
        return 7

    caplog.set_level(logging.INFO, logger="probos.startup.cognitive_services")
    await _run_one_migration(
        "BF-103",
        fast_migration,
        timeout_s=5.0,
        success_template="BF-103: Migrated %d episodes to sovereign IDs in %.1fs",
        noop_template="BF-103: completed in %.1fs (no episodes needed migration)",
    )

    success_msgs = [
        r.getMessage() for r in caplog.records
        if "Migrated 7 episodes" in r.getMessage()
    ]
    assert len(success_msgs) == 1
    # e.g. "BF-103: Migrated 7 episodes to sovereign IDs in 0.0s"
    assert re.search(r"Migrated 7 episodes .* in \d+\.\d+s", success_msgs[0])


@pytest.mark.asyncio
async def test_migration_unexpected_exception_logs_with_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def boom_migration() -> int:
        raise RuntimeError("synthetic")

    caplog.set_level(logging.WARNING, logger="probos.startup.cognitive_services")

    # Must not raise
    await _run_one_migration(
        "BF-103",
        boom_migration,
        timeout_s=5.0,
        success_template="BF-103: Migrated %d episodes in %.1fs",
        noop_template="BF-103: completed in %.1fs",
    )

    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "BF-103: failed" in r.getMessage()
    ]
    assert len(warnings) == 1
    # exc_info populated by logger.warning(..., exc_info=True)
    assert warnings[0].exc_info is not None
    assert warnings[0].exc_info[0] is RuntimeError


@pytest.mark.asyncio
async def test_migration_noop_logs_completion_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When migrated == 0, the noop template is used (not the success template)."""

    async def noop_migration() -> int:
        await asyncio.sleep(0.01)
        return 0

    caplog.set_level(logging.INFO, logger="probos.startup.cognitive_services")
    await _run_one_migration(
        "AD-570",
        noop_migration,
        timeout_s=5.0,
        success_template="AD-570: Promoted anchor metadata for %d episodes in %.1fs",
        noop_template="AD-570: anchor metadata migration completed in %.1fs (no episodes needed migration)",
    )

    noop_msgs = [
        r.getMessage() for r in caplog.records
        if "no episodes needed migration" in r.getMessage()
    ]
    assert len(noop_msgs) == 1
    assert "AD-570" in noop_msgs[0]
