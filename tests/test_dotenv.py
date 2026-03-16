"""Tests for .env file support (AD-286)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


class TestDotenvLoading:
    def test_main_does_not_crash_without_env_file(self, tmp_path, monkeypatch):
        """main() works fine when no .env file exists."""
        monkeypatch.chdir(tmp_path)
        from probos.__main__ import main

        # main() parses args — give it --help to exit quickly
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["probos", "--help"]):
                main()
        assert exc_info.value.code == 0

    def test_main_does_not_crash_without_dotenv_package(self, monkeypatch):
        """main() handles missing python-dotenv gracefully."""
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "dotenv":
                raise ImportError("no dotenv")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        from probos.__main__ import main

        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["probos", "--help"]):
                main()
        assert exc_info.value.code == 0

    def test_env_file_loads_values(self, tmp_path, monkeypatch):
        """A .env file in cwd should populate os.environ."""
        env_file = tmp_path / ".env"
        env_file.write_text("PROBOS_TEST_DOTENV_VAR=hello_from_dotenv\n")
        monkeypatch.chdir(tmp_path)

        # Clean up env var if it exists
        monkeypatch.delenv("PROBOS_TEST_DOTENV_VAR", raising=False)

        from dotenv import load_dotenv
        load_dotenv(dotenv_path=str(env_file))

        assert os.environ.get("PROBOS_TEST_DOTENV_VAR") == "hello_from_dotenv"

        # Cleanup
        monkeypatch.delenv("PROBOS_TEST_DOTENV_VAR", raising=False)
