"""BF-883 (#1458): a runtime built without ``data_dir`` resolves its default when it
is constructed, never when ``probos.runtime`` is imported.

``runtime.py`` used to compute ``_DEFAULT_DATA_DIR = _platform_data_dir()`` at
import. Test collection imports the module before the AD-682 session fixture sets
``PROBOS_DATA_DIR``, so every runtime built without ``data_dir`` -- six of them
started per full run -- booted into the live vessel's ``%LOCALAPPDATA%\\ProbOS\\data``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

import probos.runtime as runtime_module
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.runtime import ProbOSRuntime

# Read while this module is collected: the moment the old default froze.
_AT_COLLECTION = os.environ.get("PROBOS_DATA_DIR")


def _construct(data_dir: str | Path | None) -> ProbOSRuntime:
    return ProbOSRuntime(config=SystemConfig(), data_dir=data_dir, llm_client=MockLLMClient())


@pytest.mark.parametrize("data_dir", [None, ""])
def test_default_data_dir_honours_an_override_set_after_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, data_dir: str | None
) -> None:
    # Premise: the module was imported before the override existed, as in collection.
    assert "probos.runtime" in sys.modules
    override = tmp_path / "late-override"
    monkeypatch.setenv("PROBOS_DATA_DIR", str(override))

    runtime = _construct(data_dir)
    try:
        assert runtime.data_dir == override
        # The constructor's own I/O followed it: ProfileStore opens its DB in __init__.
        assert (override / "crew_profiles.db").is_file()
    finally:
        runtime.profile_store.close()  # opened in __init__; nothing else was started


def test_explicit_data_dir_wins_over_the_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    override = tmp_path / "override"
    explicit = tmp_path / "explicit"
    monkeypatch.setenv("PROBOS_DATA_DIR", str(override))

    runtime = _construct(explicit)
    try:
        assert runtime.data_dir == explicit
        assert (explicit / "crew_profiles.db").is_file()
        assert not override.exists()
    finally:
        runtime.profile_store.close()


def test_data_dir_is_isolated_before_test_modules_are_collected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _AT_COLLECTION, "PROBOS_DATA_DIR was unset while test modules were collected"
    monkeypatch.delenv("PROBOS_DATA_DIR", raising=False)
    platform_default = runtime_module._platform_data_dir().resolve()
    collected = Path(_AT_COLLECTION).resolve()

    assert collected != platform_default
    assert not collected.is_relative_to(platform_default)
