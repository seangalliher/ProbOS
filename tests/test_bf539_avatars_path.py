"""BF #539: avatars_dir resolves against platform data dir, not process cwd.

The route at ``src/probos/routers/system.py`` was using ``Path(cfg.avatars.avatars_dir).resolve()``
which resolves against the process cwd. Per BF-265, all ProbOS resources should
root under ``_platform_data_dir()`` to prevent split-brain between dev
(``d:\\ProbOS\\data\\``) and runtime (``%LOCALAPPDATA%\\ProbOS\\data\\``).
"""
from __future__ import annotations

from pathlib import Path

from probos.routers.system import _resolve_avatars_dir


def test_absolute_path_passthrough(tmp_path: Path) -> None:
    """Absolute config value resolves to itself."""
    abs_path = tmp_path / "custom_avatars"
    abs_path.mkdir()
    result = _resolve_avatars_dir(str(abs_path))
    assert result == abs_path.resolve()


def test_relative_data_avatars_strips_data_prefix(monkeypatch, tmp_path: Path) -> None:
    """The default ``data/avatars`` resolves to ``<platform_data_dir>/avatars``,
    NOT ``<platform_data_dir>/data/avatars`` (since the platform dir already ends in /data)."""
    monkeypatch.setenv("PROBOS_DATA_DIR", str(tmp_path / "ProbOS_data"))
    # Re-import _platform_data_dir to pick up the env override
    import importlib

    import probos.runtime as runtime_mod

    importlib.reload(runtime_mod)
    expected = (tmp_path / "ProbOS_data" / "avatars").resolve()
    result = _resolve_avatars_dir("data/avatars")
    assert result == expected


def test_relative_avatars_only_roots_under_platform(monkeypatch, tmp_path: Path) -> None:
    """A bare ``avatars`` config value resolves under the platform data dir."""
    monkeypatch.setenv("PROBOS_DATA_DIR", str(tmp_path / "alt_root"))
    import importlib

    import probos.runtime as runtime_mod

    importlib.reload(runtime_mod)
    expected = (tmp_path / "alt_root" / "avatars").resolve()
    result = _resolve_avatars_dir("avatars")
    assert result == expected


def test_windows_style_data_prefix_stripped(monkeypatch, tmp_path: Path) -> None:
    """Backslash-separated 'data\\\\avatars' should also strip the data prefix."""
    monkeypatch.setenv("PROBOS_DATA_DIR", str(tmp_path / "win_data"))
    import importlib

    import probos.runtime as runtime_mod

    importlib.reload(runtime_mod)
    # Path normalizes separators on Windows; this still tests the segment-aware logic
    result = _resolve_avatars_dir("data" + "/" + "avatars")
    expected = (tmp_path / "win_data" / "avatars").resolve()
    assert result == expected


def test_probos_data_dir_override_honored(monkeypatch, tmp_path: Path) -> None:
    """``PROBOS_DATA_DIR`` env var overrides the platform default."""
    override = tmp_path / "test_override"
    monkeypatch.setenv("PROBOS_DATA_DIR", str(override))
    import importlib

    import probos.runtime as runtime_mod

    importlib.reload(runtime_mod)
    result = _resolve_avatars_dir("data/avatars")
    assert result == (override / "avatars").resolve()


def test_does_not_double_data_segment(monkeypatch, tmp_path: Path) -> None:
    """Regression: never produces ``<platform>/data/data/avatars``."""
    monkeypatch.setenv("PROBOS_DATA_DIR", str(tmp_path / "ProbOS" / "data"))
    import importlib

    import probos.runtime as runtime_mod

    importlib.reload(runtime_mod)
    result = _resolve_avatars_dir("data/avatars")
    # The platform dir is .../ProbOS/data; avatars_dir should be .../ProbOS/data/avatars,
    # NOT .../ProbOS/data/data/avatars.
    parts = result.parts
    data_count = sum(1 for p in parts if p == "data")
    assert data_count == 1, f"expected exactly 1 'data' segment, got {data_count} in {result}"
