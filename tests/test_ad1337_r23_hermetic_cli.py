"""AD-1337 follow-up (#1820 R23, R7): the credential store's CLI step meets a stand-in, not ``gh``.

``tests/conftest.py`` (``_ad1337_r23_credential_cli``) replaces ``probos.credential_store.subprocess`` for each test
with a stand-in whose ``run`` records the command and fails it as if ``gh`` were not installed. Neither test below
requests that fixture, so each fails when it is not autouse. Both take ``started``, which refuses a ``gh`` start
through ``subprocess.Popen`` before the process exists, so a stand-in that falls through to the real ``subprocess``
fails them before ``gh`` runs. Contract: prompts/ad-1337-r23-r7-r1-masker-sources.md.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

import probos.credential_store as credential_store
import probos.knowledge.embeddings as embeddings_module
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.runtime import ProbOSRuntime

GH_TOKEN_CLI = ["gh", "auth", "token"]


def _boot_config() -> SystemConfig:
    """AD-1346's boot shape, as the BF-919 boot test uses it."""
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    return config


def _program(args: Any) -> str:
    """The program a ``Popen`` call starts: its first word, lower-case, without directory or suffix."""
    if isinstance(args, (str, bytes, os.PathLike)):
        words = os.fsdecode(args).split()
    else:
        words = [os.fsdecode(word) for word in list(args)[:1]]
    return Path(words[0]).stem.lower() if words else ""


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The program of each ``subprocess.Popen`` call; a ``gh`` start is refused before the process exists."""
    programs: list[str] = []

    class _GuardedPopen(subprocess.Popen):  # type: ignore[type-arg]
        def __init__(self, args: Any, *rest: Any, **kwargs: Any) -> None:
            program = _program(args)
            programs.append(program)
            if program == "gh":
                raise FileNotFoundError(program)
            super().__init__(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", _GuardedPopen)
    return programs


def test_the_stand_in_answers_and_a_dotted_patch_lands_on_it(
    monkeypatch: pytest.MonkeyPatch, started: list[str],
) -> None:
    stand_in = credential_store.subprocess
    real_run = subprocess.run
    assert stand_in is not subprocess, "the credential store's binding is replaced, not the subprocess module"
    assert stand_in.TimeoutExpired is subprocess.TimeoutExpired, "the store's except clause names the real class"
    with pytest.raises(FileNotFoundError):
        stand_in.run(GH_TOKEN_CLI, timeout=5)
    assert stand_in.calls == [GH_TOKEN_CLI]
    assert "gh" not in started, "the stand-in answered without a Popen of gh"

    def _replacement(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("not called")

    monkeypatch.setattr("probos.credential_store.subprocess.run", _replacement)
    assert credential_store.subprocess.run is _replacement, "a dotted patch lands on the stand-in"
    assert subprocess.run is real_run, "and leaves the shared subprocess.run as it was"


async def test_a_default_boot_reaches_the_stand_in_without_a_gh_popen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, started: list[str],
) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("PROBOS_EMBEDDINGS", "local")  # BF-657's backend, as the BF-919 boot test sets it
    monkeypatch.setattr(embeddings_module, "_embedding_available", None)
    monkeypatch.setattr(embeddings_module, "_embedding_fn", None)
    stand_in = credential_store.subprocess
    assert stand_in is not subprocess, "premise: the conftest stand-in is in place without being requested"
    rt = ProbOSRuntime(config=_boot_config(), data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await rt.start()
    try:
        priming = rt.secret_masking_prime_task
        assert isinstance(priming, asyncio.Task), "premise: the boot started the secret masker's priming"
        done, _ = await asyncio.wait({priming}, timeout=10.0)
        assert priming in done, "the priming finished, so its worker thread has run"
    finally:
        await rt.stop()
    assert stand_in.calls and all(argv == GH_TOKEN_CLI for argv in stand_in.calls), "the priming reached the CLI step"
    assert "gh" not in started, "and no Popen of gh was attempted"
