"""Tests for Phase 17 — DependencyResolver."""

from __future__ import annotations

import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.dependency_resolver import (
    IMPORT_TO_PACKAGE,
    DependencyResolver,
    DependencyResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolver(
    allowed: list[str] | None = None,
    install_fn=None,
    approval_fn=None,
) -> DependencyResolver:
    """Create a DependencyResolver with test defaults."""
    allowed = allowed or [
        "asyncio", "pathlib", "json", "os", "re", "datetime",
        "typing", "dataclasses", "collections", "math",
        "httpx", "feedparser", "bs4", "yaml", "pandas",
    ]
    return DependencyResolver(
        allowed_imports=allowed,
        install_fn=install_fn,
        approval_fn=approval_fn,
    )


def _stdlib_source() -> str:
    """Source code that only imports stdlib modules."""
    return textwrap.dedent("""\
        import json
        import os
        import asyncio
        from pathlib import Path
        x = json.dumps({})
    """)


def _third_party_source(module: str = "feedparser") -> str:
    """Source code that imports a third-party module."""
    return textwrap.dedent(f"""\
        import {module}
        result = {module}
    """)


def _from_import_source(module: str = "bs4", name: str = "BeautifulSoup") -> str:
    """Source code using 'from X import Y' form."""
    return textwrap.dedent(f"""\
        from {module} import {name}
        result = {name}
    """)


# ---------------------------------------------------------------------------
# TestDetectMissing — Detection tests
# ---------------------------------------------------------------------------


class TestDetectMissingStdlib:
    """detect_missing() with stdlib-only code."""

    def test_stdlib_returns_empty(self):
        """Stdlib imports are always available via find_spec."""
        r = _resolver()
        result = r.detect_missing(_stdlib_source())
        assert result == []

    def test_empty_source_returns_empty(self):
        r = _resolver()
        assert r.detect_missing("") == []

    def test_syntax_invalid_returns_empty(self):
        """Don't crash on syntax errors."""
        r = _resolver()
        assert r.detect_missing("def ??? invalid") == []


class TestDetectMissingThirdParty:
    """detect_missing() with third-party imports."""

    def test_missing_import_detected(self):
        """A package on allowed list but not installed should be detected."""
        r = _resolver()
        with patch("probos.cognitive.dependency_resolver.importlib.util.find_spec") as mock_fs:
            def side_effect(name):
                if name == "feedparser":
                    return None
                return MagicMock()
            mock_fs.side_effect = side_effect
            result = r.detect_missing(_third_party_source("feedparser"))
            assert "feedparser" in result

    def test_installed_package_not_in_missing(self):
        """A package that IS installed should not appear in missing."""
        r = _resolver()
        with patch("probos.cognitive.dependency_resolver.importlib.util.find_spec") as mock_fs:
            mock_fs.return_value = MagicMock()  # All modules found
            result = r.detect_missing(_third_party_source("feedparser"))
            assert result == []

    def test_import_form(self):
        """Both 'import X' and 'from X import Y' are detected."""
        r = _resolver()
        with patch("probos.cognitive.dependency_resolver.importlib.util.find_spec") as mock_fs:
            def side_effect(name):
                if name == "bs4":
                    return None
                return MagicMock()
            mock_fs.side_effect = side_effect
            result = r.detect_missing(_from_import_source("bs4", "BeautifulSoup"))
            assert "bs4" in result

    def test_dotted_import_checks_root(self):
        """from xml.etree import ElementTree -> checks 'xml' root."""
        r = _resolver(allowed=["xml", "xml.etree", "xml.etree.ElementTree"])
        # xml is stdlib so find_spec always works
        result = r.detect_missing("from xml.etree import ElementTree\n")
        assert result == []

    def test_only_allowed_imports_checked(self):
        """Imports NOT on the allowed list are ignored (not flagged)."""
        r = _resolver(allowed=["json", "os"])
        with patch("probos.cognitive.dependency_resolver.importlib.util.find_spec") as mock_fs:
            mock_fs.return_value = None
            result = r.detect_missing("import requests\nimport json\n")
            assert "requests" not in result

    def test_multiple_missing(self):
        """Multiple missing packages detected."""
        r = _resolver()
        source = "import feedparser\nimport bs4\nimport pandas\n"
        with patch("probos.cognitive.dependency_resolver.importlib.util.find_spec") as mock_fs:
            def side_effect(name):
                if name in ("feedparser", "bs4", "pandas"):
                    return None
                return MagicMock()
            mock_fs.side_effect = side_effect
            result = r.detect_missing(source)
            assert len(result) == 3
            assert set(result) == {"feedparser", "bs4", "pandas"}


# ---------------------------------------------------------------------------
# TestImportToPackage — Package name mapping
# ---------------------------------------------------------------------------


class TestImportToPackage:
    """IMPORT_TO_PACKAGE mapping correctness."""

    def test_bs4_maps_to_beautifulsoup4(self):
        assert IMPORT_TO_PACKAGE["bs4"] == "beautifulsoup4"

    def test_yaml_maps_to_pyyaml(self):
        assert IMPORT_TO_PACKAGE["yaml"] == "pyyaml"

    def test_dateutil_maps_to_python_dateutil(self):
        assert IMPORT_TO_PACKAGE["dateutil"] == "python-dateutil"

    def test_unmapped_uses_import_name(self):
        """If not in mapping, package name = import name."""
        assert "feedparser" not in IMPORT_TO_PACKAGE
        assert "pandas" not in IMPORT_TO_PACKAGE

    @pytest.mark.asyncio
    async def test_mapping_used_during_install(self):
        """Resolver uses IMPORT_TO_PACKAGE to get the right package name."""
        install = AsyncMock(return_value=(True, "ok"))
        approval = AsyncMock(return_value=True)
        r = _resolver(install_fn=install, approval_fn=approval)
        source = "import bs4\n"
        with patch("probos.cognitive.dependency_resolver.importlib.util.find_spec") as mock_fs:
            def side_effect(name):
                if name == "bs4":
                    return None
                return MagicMock()
            mock_fs.side_effect = side_effect

            result = await r.resolve(source)
            assert "beautifulsoup4" in result.installed or "beautifulsoup4" in result.failed


# ---------------------------------------------------------------------------
# TestResolveFlow — Resolution orchestration
# ---------------------------------------------------------------------------


class TestResolveFlow:
    """resolve() orchestration tests."""

    @pytest.mark.asyncio
    async def test_nothing_missing_returns_success(self):
        r = _resolver()
        result = await r.resolve(_stdlib_source())
        assert result.success is True
        assert result.installed == []

    @pytest.mark.asyncio
    async def test_calls_approval_fn(self):
        """When packages missing, approval_fn is called."""
        approval = AsyncMock(return_value=True)
        install = AsyncMock(return_value=(True, "ok"))
        r = _resolver(approval_fn=approval, install_fn=install)

        source = "import feedparser\n"
        with patch("probos.cognitive.dependency_resolver.importlib.util.find_spec") as mock_fs:
            def side_effect(name):
                if name == "feedparser":
                    return None
                return MagicMock()
            mock_fs.side_effect = side_effect

            await r.resolve(source)
            approval.assert_called_once()

    @pytest.mark.asyncio
    async def test_declined_returns_failure(self):
        """When user declines, result has declined packages."""
        approval = AsyncMock(return_value=False)
        r = _resolver(approval_fn=approval)

        source = "import feedparser\n"
        with patch("probos.cognitive.dependency_resolver.importlib.util.find_spec") as mock_fs:
            def side_effect(name):
                if name == "feedparser":
                    return None
                return MagicMock()
            mock_fs.side_effect = side_effect

            result = await r.resolve(source)
            assert result.success is False
            assert "feedparser" in result.declined

    @pytest.mark.asyncio
    async def test_calls_install_after_approval(self):
        """After approval, _install_package is called."""
        approval = AsyncMock(return_value=True)
        install = AsyncMock(return_value=(True, "ok"))
        r = _resolver(approval_fn=approval, install_fn=install)

        source = "import feedparser\n"
        with patch("probos.cognitive.dependency_resolver.importlib.util.find_spec") as mock_fs:
            def side_effect(name):
                if name == "feedparser":
                    return None
                return MagicMock()
            mock_fs.side_effect = side_effect

            await r.resolve(source)
            install.assert_called_once_with("feedparser")

    @pytest.mark.asyncio
    async def test_success_with_installed_packages(self):
        """Successful install reports packages."""
        approval = AsyncMock(return_value=True)
        install = AsyncMock(return_value=(True, "ok"))
        r = _resolver(approval_fn=approval, install_fn=install)

        source = "import feedparser\n"
        with patch("probos.cognitive.dependency_resolver.importlib.util.find_spec") as mock_fs:
            call_count = {"feedparser": 0}
            def side_effect(name):
                if name == "feedparser":
                    call_count["feedparser"] += 1
                    if call_count["feedparser"] <= 1:
                        return None
                    return MagicMock()
                return MagicMock()
            mock_fs.side_effect = side_effect

            result = await r.resolve(source)
            assert result.success is True
            assert "feedparser" in result.installed

    @pytest.mark.asyncio
    async def test_failed_install_returns_failure(self):
        """Failed install reports failure."""
        approval = AsyncMock(return_value=True)
        install = AsyncMock(return_value=(False, "error: not found"))
        r = _resolver(approval_fn=approval, install_fn=install)

        source = "import feedparser\n"
        with patch("probos.cognitive.dependency_resolver.importlib.util.find_spec") as mock_fs:
            def side_effect(name):
                if name == "feedparser":
                    return None
                return MagicMock()
            mock_fs.side_effect = side_effect

            result = await r.resolve(source)
            assert result.success is False
            assert "feedparser" in result.failed

    @pytest.mark.asyncio
    async def test_verify_after_install(self):
        """After install, find_spec is called again to verify."""
        approval = AsyncMock(return_value=True)
        install = AsyncMock(return_value=(True, "ok"))
        r = _resolver(approval_fn=approval, install_fn=install)

        source = "import feedparser\n"
        with patch("probos.cognitive.dependency_resolver.importlib.util.find_spec") as mock_fs:
            mock_fs.return_value = None  # Still missing after install
            result = await r.resolve(source)
            assert "feedparser" in result.failed


# ---------------------------------------------------------------------------
# TestInstallPackage — Installation
# ---------------------------------------------------------------------------


class TestInstallPackage:
    """_install_package() tests."""

    @pytest.mark.asyncio
    async def test_uses_install_fn_override(self):
        """When install_fn is provided, it's used instead of subprocess."""
        install = AsyncMock(return_value=(True, "installed"))
        r = _resolver(install_fn=install)
        success, output = await r._install_package("feedparser")
        assert success is True
        install.assert_called_once_with("feedparser")

    @pytest.mark.asyncio
    async def test_returns_false_on_failure(self):
        """Install failure returns (False, error)."""
        install = AsyncMock(return_value=(False, "not found"))
        r = _resolver(install_fn=install)
        success, output = await r._install_package("bad_package")
        assert success is False


# ---------------------------------------------------------------------------
# TestDependencyResult — Dataclass defaults
# ---------------------------------------------------------------------------


class TestDependencyResult:
    """DependencyResult dataclass tests."""

    def test_default_values(self):
        r = DependencyResult(success=True)
        assert r.installed == []
        assert r.declined == []
        assert r.failed == []
        assert r.error is None

    def test_success_nothing_installed(self):
        r = DependencyResult(success=True, installed=[])
        assert r.success is True

    def test_success_with_installed(self):
        r = DependencyResult(success=True, installed=["feedparser"])
        assert r.success is True
        assert "feedparser" in r.installed

    def test_failure_declined(self):
        r = DependencyResult(success=False, declined=["feedparser"])
        assert r.success is False
        assert "feedparser" in r.declined

    def test_failure_failed(self):
        r = DependencyResult(success=False, failed=["feedparser"], error="install failed")
        assert r.success is False
        assert "feedparser" in r.failed
        assert r.error == "install failed"
