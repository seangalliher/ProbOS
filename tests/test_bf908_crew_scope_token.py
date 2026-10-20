"""BF-908 (#1605): the crew-scope token's keyring core, accessor, wiring, doctor check, CLI and guards (slice C1a, M1-M3).

What each test proves, and what it does not (contract section 10). No test here touches the OS keyring:
``tests/conftest.py`` forces the fail backend, and every test that needs a keyring passes an in-memory duck from
``tests/fixtures/crew_scope_keyring.py``. A token is never asserted by printing it: ``TOKEN not in text``.
Milestone M2 adds the route (D), startup (E) and vault (I) rows; milestone M3 adds the doctor (F), CLI (G) and
structural (H) rows. Every route test builds its own app over a ``SimpleNamespace`` runtime holding a real
``CredentialStore`` that has read a duck once, as startup does, and calls it through ``httpx.ASGITransport`` on the
test's own loop. None of them builds a real runtime, reads a real config file or calls ``CredentialStore.get``.
E5 alone boots a real ``ProbOSRuntime`` (the BF-906 real-boot pattern), because a source-order check cannot show
that a real boot reaches the keyring read.
The CLI tests (G) call ``crew_token_cli.run`` with an in-memory keyring duck, an injected secret reader and a config
file under ``tmp_path``; only G8 starts a CLI child, and it too passes ``--config <tmp file>`` and inherits the fail
backend. A1 and B9 start a ``python -c`` child that inherits it as well; B9's child reads only a duck its own
script defines.

A1  the suite never reaches the real OS keyring
    Proves: this process, and any child that inherits ``os.environ``, picks the fail backend, and the keyring
    step finds no secure backend here.
    Does not prove: anything about a child built with ``build_command_env``. It does not inherit the variable,
    so no such child in a test may import ``keyring``.
B1  the keyring step reads a stored token
    Proves: a secure backend's entry comes back as the token, and the token is not in ``repr(read)``.
    Does not prove: the OS keyring's own behaviour; the backend is a duck.
B2  an empty secure keyring is ABSENT
    Proves: a secure backend that answers with nothing is "no token", not a failure.
    Does not prove: that a vessel with no token is open; that is the route rows (later milestones).
B3  a host without a secure backend has no keyring step
    Proves: a backend below the recommended priority is never read and never supplies a token.
    Does not prove: how AD-1196's key store treats such a backend (its own tests do).
B3b a chain is used through its first secure member only
    Proves: a ``ChainerBackend`` is replaced by its first recommended member and never read through, even when
    an insecure member comes first; a chain of insecure members has no keyring step.
    Does not prove: how the real chainer orders its members. It sorts by priority, so a real chain never puts
    an insecure member first; the stand-in does, to show the rule does not depend on that order.
B4  a failing secure keyring is UNAVAILABLE, never ABSENT
    Proves: a read that raises is not read as "no token", and the reason names the exception type only.
    Does not prove: what a route answers while unavailable (the D rows).
B5  a malformed entry is UNAVAILABLE
    Proves: an entry that fails the stored-token rule is not used as the token.
    Does not prove: which malformed shapes exist; B7 pins the rule itself.
B6  a keyring that does not answer is UNAVAILABLE
    Proves: the bounded read gives up on a blocked backend and reports it unavailable.
    Does not prove: the 10 s production bound; the test passes a short one. That the process can exit while
    the read is blocked (B9).
B7  the stored-token rule
    Proves: 15 characters, a space, a tab, non-ASCII text and a non-string are refused; 16 printable ASCII
    characters are accepted.
    Does not prove: the CLI's prompts (a later milestone).
B8  a refused deletion is never reported as absent
    Proves: a ``PasswordDeleteError`` that leaves the entry in place, or whose read-back fails, is a refusal naming
    the type only; "none was there" only when the read-back finds no entry. The premise pins keyring's macOS
    backend, which raises that error for a denied keychain too.
    Does not prove: a real keychain's answer; the backends are ducks shaped on keyring's source.
B9  a read that never answers does not hold the process at exit
    Proves: in a real child, ``asyncio.run`` returns and the interpreter exits while the keyring call is still
    blocked, with the read reported unavailable.
    Does not prove: what a real keychain prompt does; the child's backend is a duck that never returns.
B10 a late answer is dropped quietly
    Proves: the read runs on one daemon thread, and an answer that arrives after the caller gave up raises nothing
    on the loop or in the thread.
    Does not prove: B9's exit; this runs in the test's own process.
B11 a late answer after the loop closed is dropped quietly
    Proves: the worker meets a closed loop without an exception escaping the thread.
    Does not prove: anything about a loop that is still running (B10).
C1  the accessor prefers the keyring, then the config
    Proves: with a real ``CredentialStore``, the keyring's token wins once startup has read it, and the config's
    token answers before that and after a read that found none.
    Does not prove: that the accessor is the only reader (the guard test, a later milestone).
C2  a test double reads its config only
    Proves: a runtime without a real ``CredentialStore`` (none, ``MagicMock``, ``None``) reads its config only,
    and never reads as locked.
    Does not prove: the 95 existing test sites; their own files run in the focused check.
C3  the accessor reads the runtime's current config
    Proves: replacing ``runtime.config`` after the store was built changes the answer.
    Does not prove: that the Settings route leaves the keyring's token out of the file (D4, a later milestone).
C4  a locked keyring refuses while no token is configured
    Proves: an unreadable secure keyring with no configured token reads as locked; a configured token, or a
    host with no secure backend, does not.
    Does not prove: what a route does when locked (the D rows).
C5  the keyring's token is never reachable through ``get`` or the JSON store
    Proves: no registered or crew-scope-shaped name, department or tier makes ``get()`` return it; ``rotate()``
    cannot replace it; it is not in the JSON store or ``os.environ``.
    Does not prove: that in-process ProbOS code cannot call ``runtime.credential_store.crew_scope.token(...)``;
    it can, as it can read any attribute.
C6  an unread keyring refuses while no token is configured
    Proves: a real ``CredentialStore`` that startup never loaded is locked with no configured token (403
    ``crew_scope_token_unavailable``; sockets close 1008), and a configured token is enforced in that state.
    Does not prove: that startup loads it (E5).
D1  the stop routes accept the keyring's token and refuse without it
    Proves: with the token only in the keyring, ``GET /api/stops`` answers 200 to it and 401 to a wrong token, to
    none and to the config file's token; with nothing set it answers 403 ``agent_stop_requires_crew_scope_token``;
    with a keyring that fails and no configured token it answers 403 ``crew_scope_token_unavailable`` to every
    caller. The whole chain runs: keyring duck, real store, accessor, ``require_crew_scope``, the route.
    Does not prove: live HXI behaviour, or the other Captain routes (D2, D5).
D2  every Captain-only gate reads the one accessor
    Proves: the identity key-action and peer-reset gates hand back their sentinel when only the keyring holds the
    token, and refuse 403 when nothing is set or the keyring cannot be read; the remote attachment route gets past
    its token gate with the keyring's token (400 on the bad hash) and refuses 403 with nothing set.
    Does not prove: that no other module reads the setting (the guard test, a later milestone); live HXI behaviour.
D3  sockets are refused while locked
    Proves: with a secure keyring that cannot be read and no configured token, ``verify_ws_token`` returns False and
    closes 1008 for no token and for any token; the keyring's token is accepted; with nothing set a socket is
    accepted, as before.
    Does not prove: a real WebSocket handshake (the check runs before ``accept()``, over a duck socket).
D4  a Settings save never writes the keyring's token into the config file
    Proves: ``POST /api/config`` over a runtime whose keyring holds the token, authenticated with it, rewrites the
    file from the in-memory config, which never held the token: the file has the new setting, an empty
    ``auth.crew_scope_token`` and not the keyring's token.
    Does not prove: that a token already in the file is removed (it is not; requirement 2).
D5  an ordinary crew-scope route refuses while locked
    Proves: ``require_crew_scope`` raises 403 ``crew_scope_token_unavailable`` while locked, accepts the keyring's
    token, and stays a pass-through with nothing set.
    Does not prove: the 401 paths (``tests/test_ad722b_1_crew_scope_auth.py`` and D1 run them).
D6  the browser actor's basis follows the keyring's token
    Proves: ``require_browser_actor`` answers ``SHARED_CREW_SCOPE`` when only the keyring holds the token and
    ``SINGLE_OPERATOR_COMPATIBILITY`` when nothing is set.
    Does not prove: what the browser tool does with the basis.
E1  a token only in the config file keeps working, with one warning
    Proves: an existing deployment with the token in the file is enforced as before; startup logs exactly one
    WARNING naming the file and ``auth.crew_scope_token`` and saying how to move the token (``probos crew-token
    set``: ``load`` logs the posture's message and its remediation in that one call), never the value; the file's
    bytes are untouched.
    Does not prove: anything about other config files.
E2  a token in both uses the keyring's and names the file's as unused
    Proves: the one WARNING says the file's token "is not used", the accessor answers the keyring's, the file's
    token is refused, and neither value reaches the log.
    Does not prove: that the file's line is removed; ProbOS never edits the file.
E3  a locked keyring is an ERROR without a value
    Proves: a secure keyring that fails, with no configured token, logs one ERROR that names
    ``crew_scope_token_unavailable`` and carries the exception type only.
    Does not prove: what a route answers meanwhile (D1, D3, D5).
E4  startup reads the keyring once, before anything reads the token
    Proves: ``ProbOSRuntime.start`` holds exactly one ``crew_scope.load(`` call, after the stop record opens and
    before NATS and ``finalize_startup``.
    Does not prove: that a real boot reaches it; E5 does. A source-order check passes with the call under
    ``if False:``.
E5  a real boot reads the keyring after the stop record and before NATS
    Proves: ``ProbOSRuntime.start`` calls the keyring step's ``load`` exactly once, with the stop record already
    built and NATS not yet started; the read has finished when NATS starts; before the boot the runtime refuses
    (locked), after it the keyring's token is enforced.
    Does not prove: the exact line (E4); the OS keyring (a duck is injected).
I1  the file vault is keyed from the keyring's token
    Proves: with an empty config token and the keyring holding one, ``_wire_browser_tool`` builds the encrypted
    file vault.
    Does not prove: the vault's format or its KEK derivation (AD-706f tests); a real browser.
F1  the doctor says where the token comes from
    Proves: over a real loaded config, ``crew_scope_token`` is OK for a keyring token alone and for no token at all;
    WARN, naming the file and ``auth.crew_scope_token`` and carrying ``probos crew-token set`` and the 401 caveat in
    its remediation, for a token only in the file; WARN "is not used" for a token in both; WARN "no secure OS
    keyring" for a file token on a host without one; FAIL for a keyring that fails with no file token. No message or
    remediation holds a token.
    Does not prove: the real OS keyring (a duck is injected), or how the report renders a result.
F2  the check is registered once
    Proves: importing the doctor package registers ``crew_scope_token`` exactly once.
    Does not prove: the check's place in the report order.
F3  the check skips without a config
    Proves: with no loaded config the check warns "skipped".
    Does not prove: which check reports the config's own failure (``config_check`` does).
G1  the CLI stores a prompted token and never prints it
    Proves: ``set`` with two equal prompted entries stores the token in the keyring, tells the Captain to restart the
    vessel and that panels must send the token (401), and prints no token.
    Does not prove: ``getpass`` on a real terminal; the secret reader is injected.
G2  the CLI refuses what it must
    Proves: two entries that differ, a 15-character token, a keyring that already holds a token (``set`` names
    ``rotate``), a host with no secure backend and a keyring that fails each exit 1, name their reason, leave the
    keyring as it was and print no token.
    Does not prove: the refusals' exact wording beyond the reason each names.
G3  standard input is read only with the flag
    Proves: without ``--stdin`` a standard input that is not a terminal is refused (exit 2) before any prompt, even
    when it holds a token, and nothing is stored; with the flag one line of it is stored.
    Does not prove: how a real terminal's input reaches the prompt.
G4  a different token is refused while the file vault holds entries
    Proves: with the browser file vault enabled and holding entries, ``rotate`` to a different token exits 1 and
    keeps the entry, while the token in use is accepted (``rotate`` to it, or ``set`` moving the file's); a vault
    that cannot be read refuses a different token too.
    Does not prove: that the vault decrypts; its entries are counted, never opened (AD-706f tests).
G5  ``clear`` removes the entry and is never refused for the vault
    Proves: with a vault holding entries, ``clear`` exits 0, removes the entry and names the vault; a second ``clear``
    says the keyring held none, because the read-back found no entry (D22); on a host with no secure backend it
    exits 0 and touches no backend.
    Does not prove: that a running vessel stops using the token; it keeps what it started with (residual R5).
G6  ``status`` never prints the token
    Proves: with one token in the keyring and another in the file, ``status`` exits 0, says the file's "is not used"
    and prints neither value.
    Does not prove: how the doctor renders the same posture (F1).
G7  a keyring that does not keep the token is reported
    Proves: a backend that accepts the write but returns nothing on the read-back makes ``set`` exit 1 with
    "did not keep", and the token is not printed.
    Does not prove: other backend faults (B4 and B5 pin the read side).
G8  the CLI takes no token on the command line
    Proves: the CLI's real entry takes no token as an argument and reaches the keyring layer end to end (refused here
    by the fail backend); a rejected argument is not in the child's standard output.
    Does not prove: interactive ``getpass`` on a real terminal. Standard error: argparse echoes a mistyped value
    there (residual R8, D23), so it is not asserted.
G9  a config that does not load shows its type, never its text
    Proves: a config that does not load is refused (exit 2) before the keyring is read. The output names the file,
    the exception's type and ``probos doctor``, never the exception's text, though that text quotes a value.
    Does not prove: which setting is at fault: that is ``probos doctor``'s job (AD-1137 tests).
G10 a token the CLI stored is the one the vessel enforces (a seam test, not a contract row)
    Proves: after ``set`` through the CLI, a store that reads the same backend as startup does answers the token, and
    a Captain-route gate accepts it (200) and refuses another (401): CLI, keyring, startup read, accessor and gate.
    Does not prove: the same across two real processes; the keyring is a duck here.
G11 a refused deletion is reported, and the entry stays
    Proves: ``clear`` over a backend that refuses the deletion and keeps the entry exits 1 with "Not cleared" and
    the error's type, never "held no", the backend's text or a token.
    Does not prove: a real keychain (B8's premise pins keyring's macOS contract).
H1, H2  one reader of the setting, one writer of the entry
    Proves: no module but the owner reads the setting (attribute, ``getattr`` or subscript); only the CLI calls the
    writers; only three modules import the keyring module (relative imports included), and none is a router, tool,
    federation or MCP module; the CLI imports nothing from the doctor package.
    Does not prove: that a same-user process cannot call ``keyring`` itself (residual R1). A read through a computed
    name (``getattr(a, "crew_" + "scope_token")``).
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import inspect
import io
import logging
import os
import subprocess
import sys
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import keyring
import keyring.errors
import pytest
import yaml
from fastapi import APIRouter, FastAPI, HTTPException, Request
from keyring.backends.chainer import ChainerBackend
from pydantic import ValidationError
from rich.console import Console

import probos
import probos.credential_store as credential_store_module
from probos import crew_token_cli
from probos.agent_stop import AgentStopService
from probos.cognitive.llm_client import MockLLMClient
from probos.config import AttachmentsConfig, AuthConfig, SystemConfig, load_config
from probos.credential_store import CredentialStore, crew_scope_locked, crew_scope_token
from probos.doctor.checks.crew_scope_check import _CrewScopeCheck
from probos.doctor.protocol import CheckOutcome, DoctorContext
from probos.doctor.registry import iter_checks
from probos.routers import agent_stop as stop_routes
from probos.routers import config as config_routes
from probos.routers import federation_attachments
from probos.routers import identity as identity_routes
from probos.routers.auth import require_browser_actor, require_crew_scope, verify_ws_token
from probos.runtime import ProbOSRuntime
from probos.security.crew_scope import (
    CREW_SCOPE_KEYRING_SERVICE,
    CREW_SCOPE_READ_THREAD_NAME,
    CrewScopeKeyring,
    CrewScopeKeyringError,
    CrewScopeSource,
    KeyringRead,
    clear_keyring_token,
    read_keyring_token,
    read_keyring_token_bounded,
    token_refusal,
)
from probos.startup.finalize import _wire_browser_tool
from probos.tools.browser.lifecycle import BrowserAuthorityBasis
from probos.tools.registry import ToolRegistry
from tests.fixtures.crew_scope_keyring import (
    DENIAL_DETAIL,
    ENTRY,
    FILE_TOKEN,
    KEYRING_TOKEN,
    ROTATED_TOKEN,
    FailingKeyring,
    ForgetfulKeyring,
    InsecureKeyring,
    LockedDeleteKeyring,
    MemoryKeyring,
    RefusingDeleteKeyring,
    SilentKeyring,
    loaded_store,
)


class _CountingInsecureKeyring(InsecureKeyring):
    """An insecure backend that counts reads, to show the keyring step never makes one."""

    def __init__(self, *, token: str | None = None) -> None:
        super().__init__(token=token)
        self.reads = 0

    def get_password(self, service: str, username: str) -> str | None:
        self.reads += 1
        return super().get_password(service, username)


def _backend_name(backend_class: type) -> str:
    return f"{backend_class.__module__}.{backend_class.__qualname__}"


# --------------------------------------------------------------------------- #
# A -- the suite never reaches the real OS keyring
# --------------------------------------------------------------------------- #


def test_the_suite_never_reaches_the_real_os_keyring() -> None:
    # The order matters. The variable first, then what keyring picked, then a read: were tests/conftest.py's line
    # missing, the first assertion fails and nothing below it asks a real backend for anything.
    assert os.environ.get("PYTHON_KEYRING_BACKEND") == "keyring.backends.fail.Keyring"
    assert type(keyring.get_keyring()).__module__ == "keyring.backends.fail"
    assert read_keyring_token().source is CrewScopeSource.NO_SECURE_BACKEND
    child = subprocess.run(
        [sys.executable, "-c", "import keyring; print(type(keyring.get_keyring()).__module__)"],
        env=dict(os.environ), capture_output=True, text=True, timeout=120,
    )
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == "keyring.backends.fail"


# --------------------------------------------------------------------------- #
# B -- the keyring step
# --------------------------------------------------------------------------- #


def test_keyring_step_reads_a_stored_token() -> None:
    read = read_keyring_token(MemoryKeyring(token=KEYRING_TOKEN))

    assert read.source is CrewScopeSource.KEYRING
    assert read.token == KEYRING_TOKEN
    assert KEYRING_TOKEN not in repr(read)


def test_keyring_step_an_empty_secure_keyring_is_absent() -> None:
    read = read_keyring_token(MemoryKeyring())

    assert read.source is CrewScopeSource.ABSENT
    assert read.token == ""


def test_keyring_step_a_host_without_a_secure_backend_has_none() -> None:
    insecure = _CountingInsecureKeyring(token=KEYRING_TOKEN)
    assert insecure.entries.get(ENTRY) == KEYRING_TOKEN  # premise: the backend does hold the token

    read = read_keyring_token(insecure)

    assert read.source is CrewScopeSource.NO_SECURE_BACKEND
    assert read.token == ""
    assert KEYRING_TOKEN not in repr(read)
    assert insecure.reads == 0  # never read


def test_keyring_step_a_chain_uses_its_first_secure_member() -> None:
    insecure = _CountingInsecureKeyring(token=FILE_TOKEN)
    secure = MemoryKeyring(token=KEYRING_TOKEN)
    # The real chainer sorts its members by priority, so an insecure member never precedes a secure one there. The
    # stand-in puts it first: a rule that takes the chain's first member, or reads through the chain, fails here.
    with patch.object(ChainerBackend, "backends", [insecure, secure]):
        chain = ChainerBackend()
        assert chain.backends[0] is insecure  # premise: the first member is the insecure one
        read = read_keyring_token(chain)

    assert read.source is CrewScopeSource.KEYRING
    assert read.token == KEYRING_TOKEN
    assert read.backend == _backend_name(MemoryKeyring)
    assert insecure.reads == 0

    with patch.object(ChainerBackend, "backends", [InsecureKeyring(token=FILE_TOKEN), InsecureKeyring()]):
        only_insecure = read_keyring_token(ChainerBackend())

    assert only_insecure.source is CrewScopeSource.NO_SECURE_BACKEND
    assert only_insecure.token == ""


def test_keyring_step_a_failing_secure_keyring_is_unavailable_never_absent() -> None:
    read = read_keyring_token(FailingKeyring())

    assert read.source is CrewScopeSource.UNAVAILABLE
    assert "RuntimeError" in read.reason
    assert "keychain locked" not in read.reason


def test_keyring_step_a_malformed_entry_is_unavailable() -> None:
    read = read_keyring_token(MemoryKeyring(token="short"))

    assert read.source is CrewScopeSource.UNAVAILABLE
    assert read.token == ""


async def test_keyring_step_a_keyring_that_does_not_answer_is_unavailable() -> None:
    silent = SilentKeyring()
    try:
        read = await read_keyring_token_bounded(silent, timeout_seconds=0.05)
    finally:
        silent.release.set()

    assert read.source is CrewScopeSource.UNAVAILABLE
    assert "did not answer" in read.reason


def test_keyring_step_a_refused_deletion_is_never_reported_as_absent() -> None:
    import keyring.backends.macOS as macos_backend

    # Premise (keyring's own macOS backend): every api.Error from a deletion, a denied keychain included, is raised
    # as PasswordDeleteError, so that error alone does not mean "none was there". If keyring changes this, re-examine D22.
    deletion = inspect.getsource(macos_backend.Keyring.delete_password)
    assert "except api.Error" in deletion
    assert "raise PasswordDeleteError(" in deletion
    refusing = RefusingDeleteKeyring(token=KEYRING_TOKEN)
    with pytest.raises(keyring.errors.PasswordDeleteError):
        refusing.delete_password(*ENTRY)  # premise: the duck raises it and keeps the entry
    assert refusing.entries[ENTRY] == KEYRING_TOKEN

    with pytest.raises(CrewScopeKeyringError) as kept:
        clear_keyring_token(backend=refusing)
    assert "PasswordDeleteError" in str(kept.value)
    assert DENIAL_DETAIL not in str(kept.value)
    assert refusing.entries[ENTRY] == KEYRING_TOKEN

    with pytest.raises(CrewScopeKeyringError) as unreadable:  # the read-back fails too: not "absent"
        clear_keyring_token(backend=LockedDeleteKeyring(token=KEYRING_TOKEN))
    assert "PasswordDeleteError" in str(unreadable.value)
    assert DENIAL_DETAIL not in str(unreadable.value)

    assert clear_keyring_token(backend=MemoryKeyring()) is False  # truly absent
    held = MemoryKeyring(token=KEYRING_TOKEN)
    assert clear_keyring_token(backend=held) is True
    assert ENTRY not in held.entries


_NEVER_ANSWERS_CHILD = """
import asyncio
import threading

from probos.security.crew_scope import read_keyring_token_bounded


class NeverAnswers:
    priority = 5  # recommended, as a secure backend is

    def get_password(self, service, username):
        threading.Event().wait()  # never returns: a keychain prompt nobody answers


async def main():
    read = await read_keyring_token_bounded(NeverAnswers(), timeout_seconds=0.2)
    print(read.source.value, "did not answer" in read.reason, flush=True)


asyncio.run(main())
"""


def test_keyring_step_a_read_that_never_answers_does_not_hold_the_process_at_exit(tmp_path: Path) -> None:
    src_dir = Path(probos.__file__).resolve().parents[1]  # the tree this test runs against
    env = {**os.environ, "PYTHONPATH": str(src_dir)}
    assert env.get("PYTHON_KEYRING_BACKEND") == "keyring.backends.fail.Keyring"  # premise: no real keyring in the child
    try:
        child = subprocess.run(
            [sys.executable, "-c", _NEVER_ANSWERS_CHILD], capture_output=True, text=True, timeout=60,
            check=False, cwd=tmp_path, env=env,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("BF-908 A2: the child did not exit within 60 s; a keyring read that never answers held it open")

    assert child.returncode == 0, child.stderr
    assert child.stdout.split() == ["unavailable", "True"]


def _read_threads_since(before: frozenset[threading.Thread]) -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t not in before and t.name == CREW_SCOPE_READ_THREAD_NAME]


async def test_keyring_step_a_late_answer_is_dropped_quietly(monkeypatch: pytest.MonkeyPatch) -> None:
    thread_errors: list[object] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: thread_errors.append(args.exc_type))
    loop = asyncio.get_running_loop()
    loop_errors: list[object] = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: loop_errors.append(context.get("exception") or context["message"]))
    silent = SilentKeyring()
    before = frozenset(threading.enumerate())
    try:
        try:
            read = await read_keyring_token_bounded(silent, timeout_seconds=0.05)
            workers = _read_threads_since(before)
            assert len(workers) == 1  # premise: the read ran on its own thread
            assert workers[0].daemon is True  # D20: a daemon thread never holds up exit
            assert workers[0].is_alive()  # premise: the backend was still blocked when the caller gave up
        finally:
            silent.release.set()
        workers[0].join(5)
        assert not workers[0].is_alive()
        await asyncio.sleep(0.05)  # the late answer's hand-over runs on this loop
    finally:
        loop.set_exception_handler(previous)

    assert read.source is CrewScopeSource.UNAVAILABLE
    assert "did not answer" in read.reason
    assert loop_errors == []
    assert thread_errors == []


def test_keyring_step_a_late_answer_after_the_loop_closed_is_dropped_quietly(monkeypatch: pytest.MonkeyPatch) -> None:
    thread_errors: list[object] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: thread_errors.append(args.exc_type))
    silent = SilentKeyring()
    before = frozenset(threading.enumerate())
    loop = asyncio.new_event_loop()
    try:
        read = loop.run_until_complete(read_keyring_token_bounded(silent, timeout_seconds=0.05))
    finally:
        loop.close()
        workers = _read_threads_since(before)
        silent.release.set()

    assert len(workers) == 1  # premise: the read ran on its own thread
    workers[0].join(5)
    assert not workers[0].is_alive()
    assert read.source is CrewScopeSource.UNAVAILABLE
    assert thread_errors == []  # the worker met the closed loop and returned


@pytest.mark.parametrize(
    ("value", "refusal"),
    [
        pytest.param("a" * 15, "shorter than 16 characters", id="15-characters-refused"),
        pytest.param("a" * 16, None, id="16-characters-accepted"),
        pytest.param("a" * 8 + " " + "a" * 8, "not printable ASCII without spaces", id="space-refused"),
        pytest.param("a" * 8 + "\t" + "a" * 8, "not printable ASCII without spaces", id="tab-refused"),
        pytest.param("\u00e9" * 16, "not printable ASCII without spaces", id="non-ascii-refused"),
        pytest.param(None, "not text", id="none-refused"),
    ],
)
def test_keyring_step_token_rule(value: object, refusal: str | None) -> None:
    assert token_refusal(value) == refusal


# --------------------------------------------------------------------------- #
# C -- the accessor
# --------------------------------------------------------------------------- #


async def test_accessor_prefers_the_keyring_then_the_config() -> None:
    config = SystemConfig(auth=AuthConfig(crew_scope_token=FILE_TOKEN))
    backend = MemoryKeyring(token=KEYRING_TOKEN)
    store = CredentialStore(config=config)
    store.crew_scope = CrewScopeKeyring(backend=backend)
    runtime = SimpleNamespace(config=config, credential_store=store)

    assert crew_scope_token(runtime) == FILE_TOKEN  # startup has not read the keyring yet

    await store.crew_scope.load(config=config)
    assert crew_scope_token(runtime) == KEYRING_TOKEN

    backend.entries.clear()
    await store.crew_scope.load(config=config)  # reloaded over an empty keyring
    assert store.crew_scope.source is CrewScopeSource.ABSENT
    assert crew_scope_token(runtime) == FILE_TOKEN


def test_accessor_a_test_double_reads_its_config_only() -> None:
    config = SystemConfig(auth=AuthConfig(crew_scope_token=FILE_TOKEN))
    no_store = SimpleNamespace(config=config)
    mock_store = SimpleNamespace(config=config, credential_store=MagicMock())

    assert crew_scope_token(no_store) == FILE_TOKEN
    assert crew_scope_token(mock_store) == FILE_TOKEN
    assert crew_scope_token(None) == ""
    assert crew_scope_token(SimpleNamespace(config=SimpleNamespace())) == ""  # a config without ``auth``
    assert crew_scope_locked(no_store) is False
    assert crew_scope_locked(mock_store) is False
    assert crew_scope_locked(None) is False


async def test_accessor_reads_the_runtime_s_current_config() -> None:
    first = SystemConfig(auth=AuthConfig(crew_scope_token=FILE_TOKEN))
    runtime = SimpleNamespace(config=first, credential_store=await loaded_store(first, MemoryKeyring()))
    assert crew_scope_token(runtime) == FILE_TOKEN

    # A test replaces ``runtime.config`` after the store was built; the store's own copy is the old one.
    runtime.config = SystemConfig(auth=AuthConfig(crew_scope_token=ROTATED_TOKEN))

    assert crew_scope_token(runtime) == ROTATED_TOKEN


async def test_accessor_a_locked_keyring_refuses_while_no_token_is_configured() -> None:
    empty = SystemConfig()
    locked = SimpleNamespace(config=empty, credential_store=await loaded_store(empty, FailingKeyring()))
    assert locked.credential_store.crew_scope.source is CrewScopeSource.UNAVAILABLE  # premise
    assert crew_scope_locked(locked) is True
    assert crew_scope_token(locked) == ""

    configured = SystemConfig(auth=AuthConfig(crew_scope_token=FILE_TOKEN))
    with_file_token = SimpleNamespace(
        config=configured, credential_store=await loaded_store(configured, FailingKeyring()),
    )
    assert with_file_token.credential_store.crew_scope.source is CrewScopeSource.UNAVAILABLE  # premise
    assert crew_scope_locked(with_file_token) is False
    assert crew_scope_token(with_file_token) == FILE_TOKEN

    no_backend = SimpleNamespace(config=empty, credential_store=await loaded_store(empty, InsecureKeyring()))
    assert no_backend.credential_store.crew_scope.source is CrewScopeSource.NO_SECURE_BACKEND  # premise
    assert crew_scope_locked(no_backend) is False


async def test_accessor_an_unread_keyring_refuses_while_no_token_is_configured() -> None:
    empty = SystemConfig()
    unread = SimpleNamespace(config=empty, credential_store=CredentialStore(config=empty))
    assert unread.credential_store.crew_scope.source is CrewScopeSource.UNREAD  # premise: startup never read it
    assert crew_scope_locked(unread) is True  # D21: a skipped read refuses, never opens
    assert crew_scope_token(unread) == ""
    with pytest.raises(HTTPException) as refused:
        await require_crew_scope(_http_request(), authorization=None, runtime=unread)
    assert (refused.value.status_code, refused.value.detail) == (403, "crew_scope_token_unavailable")
    for presented in (None, KEYRING_TOKEN):
        socket = _DuckSocket(presented)
        assert await verify_ws_token(socket, unread) is False, presented
        assert [code for code, _reason in socket.closed] == [1008], presented

    configured = SystemConfig(auth=AuthConfig(crew_scope_token=FILE_TOKEN))
    with_file_token = SimpleNamespace(config=configured, credential_store=CredentialStore(config=configured))
    assert with_file_token.credential_store.crew_scope.source is CrewScopeSource.UNREAD  # premise
    assert crew_scope_locked(with_file_token) is False  # a configured token is enforced in every state
    assert crew_scope_token(with_file_token) == FILE_TOKEN
    assert await require_crew_scope(
        _http_request(), authorization=f"Bearer {FILE_TOKEN}", runtime=with_file_token,
    ) is None
    with pytest.raises(HTTPException) as unauthenticated:
        await require_crew_scope(_http_request(), authorization=None, runtime=with_file_token)
    assert unauthenticated.value.status_code == 401


async def test_the_keyring_token_is_never_reachable_through_get_or_the_json_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The built-in "github" spec ends in a CLI step (``gh auth token``), and that tool reads its own credential
    # store: no real CLI runs here. The stand-in records what it is offered and fails as an absent CLI does.
    for variable in ("GH_TOKEN", "GITHUB_TOKEN", "PROBOS_DISCORD_TOKEN", "LLM_API_KEY"):
        monkeypatch.delenv(variable, raising=False)
    offered: list[list[str]] = []

    def _no_cli(argv: list[str], **_kwargs: object) -> None:
        offered.append(list(argv))
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(
        credential_store_module, "subprocess", SimpleNamespace(run=_no_cli, TimeoutExpired=subprocess.TimeoutExpired),
    )
    config = SystemConfig()
    secrets = tmp_path / "secrets.json"
    store = CredentialStore(config=config, store_path=secrets)
    store.crew_scope = CrewScopeKeyring(backend=MemoryKeyring(token=KEYRING_TOKEN))
    await store.crew_scope.load(config=config)
    assert store.crew_scope.token(config) == KEYRING_TOKEN  # premise: the store holds the token

    listed = [str(entry["name"]) for entry in store.list_credentials()]
    assert "github" in listed  # premise: the built-in specs are there
    crew_scope_names = ["crew_scope", "crew_scope_token", "auth.crew_scope_token", CREW_SCOPE_KEYRING_SERVICE]
    for enforcement in (False, True):
        store.set_tier_enforcement(enforcement)
        for department in (None, "engineering"):
            for name in [*listed, *crew_scope_names]:
                assert store.get(name, department=department) != KEYRING_TOKEN, (name, department, enforcement)
    assert not [name for name in listed if "crew_scope" in name]
    assert offered
    assert all(argv == ["gh", "auth", "token"] for argv in offered)  # the stand-in saw every CLI step

    assert store.rotate("crew_scope_token", ROTATED_TOKEN) is True  # premise: the JSON store is written
    assert store.crew_scope.token(config) == KEYRING_TOKEN
    assert KEYRING_TOKEN not in secrets.read_text(encoding="utf-8")
    assert KEYRING_TOKEN not in os.environ.values()


# --------------------------------------------------------------------------- #
# D -- the routes and the socket check
# --------------------------------------------------------------------------- #


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@contextlib.asynccontextmanager
async def _stop_service(tmp_path: Path) -> AsyncIterator[AgentStopService]:
    """A started ``AgentStopService`` over a real ``agent_stops.db`` in ``tmp_path``, closed when the block ends."""
    service = AgentStopService(data_dir=tmp_path / "stops")
    await service.start()
    try:
        yield service
    finally:
        await service.stop()


@contextlib.asynccontextmanager
async def _client(router: APIRouter, runtime: Any) -> AsyncIterator[httpx.AsyncClient]:
    """``router`` on a minimal app over ``runtime``, called in the test's own loop (never ``TestClient``)."""
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = runtime
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def _runtime_over(backend: Any, *, config: SystemConfig | None = None, **extra: Any) -> SimpleNamespace:
    """A runtime double whose real ``CredentialStore`` has read ``backend`` once, as startup does."""
    config = config if config is not None else SystemConfig()
    return SimpleNamespace(config=config, credential_store=await loaded_store(config, backend), **extra)


def _serving_config() -> SystemConfig:
    return SystemConfig(attachments=AttachmentsConfig(serve_remote_enabled=True))


class _DuckSocket:
    """The two members ``verify_ws_token`` uses: ``query_params`` and an async ``close`` that records its arguments."""

    def __init__(self, token: str | None = None) -> None:
        self.query_params: dict[str, str] = {} if token is None else {"token": token}
        self.closed: list[tuple[int, str]] = []

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed.append((code, reason))


def _http_request() -> Request:
    return Request({"type": "http", "query_string": b"", "headers": []})


async def test_the_stop_routes_accept_the_keyring_token_and_refuse_without_it(tmp_path: Path) -> None:
    async with _stop_service(tmp_path) as service:
        in_keyring = await _runtime_over(MemoryKeyring(token=KEYRING_TOKEN), agent_stops=service)
        assert in_keyring.config.auth.crew_scope_token == ""  # premise: the config holds no token, only the keyring does
        async with _client(stop_routes.router, in_keyring) as client:
            accepted = await client.get("/api/stops", headers=_bearer(KEYRING_TOKEN))
            assert accepted.status_code == 200
            assert accepted.json()["stops"] == []
            for presented in (ROTATED_TOKEN, FILE_TOKEN):  # a wrong token, and a token the keyring does not hold
                assert (await client.get("/api/stops", headers=_bearer(presented))).status_code == 401
            assert (await client.get("/api/stops")).status_code == 401  # none presented

        nothing = await _runtime_over(MemoryKeyring(), agent_stops=service)
        assert nothing.credential_store.crew_scope.source is CrewScopeSource.ABSENT  # premise
        async with _client(stop_routes.router, nothing) as client:
            unset = await client.get("/api/stops")
            assert (unset.status_code, unset.json()["detail"]) == (403, "agent_stop_requires_crew_scope_token")

        locked = await _runtime_over(FailingKeyring(), agent_stops=service)
        assert locked.credential_store.crew_scope.source is CrewScopeSource.UNAVAILABLE  # premise
        async with _client(stop_routes.router, locked) as client:
            for headers in ({}, _bearer(KEYRING_TOKEN)):  # every caller, whatever it presents
                refused = await client.get("/api/stops", headers=headers)
                assert (refused.status_code, refused.json()["detail"]) == (403, "crew_scope_token_unavailable")


async def test_every_captain_only_gate_reads_the_one_accessor() -> None:
    binding, exchange = object(), object()  # sentinels: the gates hand back whatever the runtime holds
    in_keyring = await _runtime_over(
        MemoryKeyring(token=KEYRING_TOKEN), identity_key_binding=binding, federation_identity_exchange=exchange,
    )
    assert in_keyring.config.auth.crew_scope_token == ""  # premise: only the keyring holds a token
    assert await identity_routes._key_action_binding(in_keyring) is binding
    assert await identity_routes._peer_reset_exchange(in_keyring) is exchange

    for backend in (MemoryKeyring(), FailingKeyring()):  # nothing set, then a keyring that cannot be read
        runtime = await _runtime_over(backend, identity_key_binding=binding, federation_identity_exchange=exchange)
        for gate in (identity_routes._key_action_binding, identity_routes._peer_reset_exchange):
            with pytest.raises(HTTPException) as refused:
                await gate(runtime)
            assert refused.value.status_code == 403
            assert refused.value.detail == "identity_keys_require_token"

    keyring_runtime = await _runtime_over(MemoryKeyring(token=KEYRING_TOKEN), config=_serving_config())
    async with _client(federation_attachments.router, keyring_runtime) as client:
        past_the_gate = await client.get("/api/federation/attachments/nothex", headers=_bearer(KEYRING_TOKEN))
    assert (past_the_gate.status_code, past_the_gate.json()["detail"]) == (400, "invalid_content_hash")

    empty_runtime = await _runtime_over(MemoryKeyring(), config=_serving_config())
    async with _client(federation_attachments.router, empty_runtime) as client:
        refused_remote = await client.get("/api/federation/attachments/nothex")
    assert (refused_remote.status_code, refused_remote.json()["detail"]) == (403, "remote_serving_requires_token")


async def test_websockets_refuse_every_caller_while_locked() -> None:
    locked = await _runtime_over(FailingKeyring())
    assert crew_scope_locked(locked) is True  # premise
    for presented in (None, KEYRING_TOKEN, FILE_TOKEN):  # no token, then tokens that would pass in another state
        socket = _DuckSocket(presented)
        assert await verify_ws_token(socket, locked) is False, presented
        assert [code for code, _reason in socket.closed] == [1008], presented

    in_keyring = await _runtime_over(MemoryKeyring(token=KEYRING_TOKEN))
    accepted = _DuckSocket(KEYRING_TOKEN)
    assert await verify_ws_token(accepted, in_keyring) is True
    assert accepted.closed == []

    nothing = await _runtime_over(MemoryKeyring())
    unchanged = _DuckSocket()
    assert await verify_ws_token(unchanged, nothing) is True  # nothing set, keyring absent: the default is unchanged
    assert unchanged.closed == []


async def test_a_settings_save_never_writes_the_keyring_token_into_the_config_file(tmp_path: Path) -> None:
    path = tmp_path / "system.yaml"
    path.write_text(yaml.safe_dump({}), encoding="utf-8")
    runtime = await _runtime_over(
        MemoryKeyring(token=KEYRING_TOKEN), config_path=str(path), _start_time=0.0,
    )
    assert crew_scope_token(runtime) == KEYRING_TOKEN  # premise: the keyring's token is what authenticates
    assert runtime.config.auth.crew_scope_token == ""  # premise: the in-memory config never holds it

    async with _client(config_routes.router, runtime) as client:
        snapshot = await client.get("/api/config", headers=_bearer(KEYRING_TOKEN))
        assert snapshot.status_code == 200
        saved = await client.post(
            "/api/config",
            json={"patch": {"system": {"log_level": "DEBUG"}}},
            headers={**_bearer(KEYRING_TOKEN), "X-Probos-CSRF": snapshot.json()["csrf_token"]},
        )
    assert saved.status_code == 200, saved.text

    text = path.read_text(encoding="utf-8")
    assert yaml.safe_load(text)["system"]["log_level"] == "DEBUG"  # premise: the save did rewrite the file
    assert KEYRING_TOKEN not in text
    assert yaml.safe_load(text)["auth"]["crew_scope_token"] == ""


async def test_an_ordinary_crew_scope_route_refuses_while_locked() -> None:
    locked = await _runtime_over(FailingKeyring())
    with pytest.raises(HTTPException) as refused:
        await require_crew_scope(_http_request(), authorization=None, runtime=locked)
    assert refused.value.status_code == 403
    assert refused.value.detail == "crew_scope_token_unavailable"

    in_keyring = await _runtime_over(MemoryKeyring(token=KEYRING_TOKEN))
    assert await require_crew_scope(
        _http_request(), authorization=f"Bearer {KEYRING_TOKEN}", runtime=in_keyring,
    ) is None

    nothing = await _runtime_over(MemoryKeyring())
    assert await require_crew_scope(_http_request(), authorization=None, runtime=nothing) is None  # today's pass-through


async def test_the_browser_actor_basis_follows_the_keyring_token() -> None:
    in_keyring = await _runtime_over(MemoryKeyring(token=KEYRING_TOKEN))
    actor = await require_browser_actor(runtime=in_keyring, crew_scope=None)
    assert actor.authority_basis is BrowserAuthorityBasis.SHARED_CREW_SCOPE

    nothing = await _runtime_over(MemoryKeyring())
    single = await require_browser_actor(runtime=nothing, crew_scope=None)
    assert single.authority_basis is BrowserAuthorityBasis.SINGLE_OPERATOR_COMPATIBILITY


# --------------------------------------------------------------------------- #
# E -- startup says where the token comes from, once, and never with a value
# --------------------------------------------------------------------------- #

_STARTUP_LOGGER = "probos.security.crew_scope"


def _startup_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """What the keyring step logged at WARNING or above."""
    return [r for r in caplog.records if r.name == _STARTUP_LOGGER and r.levelno >= logging.WARNING]


def _write_config_with_file_token(tmp_path: Path) -> Path:
    path = tmp_path / "system.yaml"
    path.write_text(yaml.safe_dump({"auth": {"crew_scope_token": FILE_TOKEN}}), encoding="utf-8")
    return path


async def test_a_token_only_in_the_config_file_keeps_working_with_the_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    path = _write_config_with_file_token(tmp_path)
    config = load_config(path)
    assert config.auth.crew_scope_token == FILE_TOKEN  # premise: the file's token loaded
    before = path.read_bytes()

    with caplog.at_level(logging.WARNING, logger=_STARTUP_LOGGER):
        store = await loaded_store(config, MemoryKeyring(), config_path=str(path))

    records = _startup_records(caplog)
    assert [r.levelno for r in records] == [logging.WARNING]  # exactly one, and a WARNING
    warning = records[0].getMessage()
    assert str(path) in warning
    assert "auth.crew_scope_token" in warning
    assert "probos crew-token set" in warning  # D7: the logged line itself says how to move the token
    assert FILE_TOKEN not in caplog.text

    async with _stop_service(tmp_path) as service:
        runtime = SimpleNamespace(config=config, credential_store=store, agent_stops=service)
        async with _client(stop_routes.router, runtime) as client:
            working = await client.get("/api/stops", headers=_bearer(FILE_TOKEN))
    assert working.status_code == 200
    assert path.read_bytes() == before  # ProbOS never edits the file


async def test_a_token_in_both_uses_the_keyring_s_and_names_the_file_s_as_unused(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    path = _write_config_with_file_token(tmp_path)
    config = load_config(path)

    with caplog.at_level(logging.WARNING, logger=_STARTUP_LOGGER):
        store = await loaded_store(config, MemoryKeyring(token=KEYRING_TOKEN), config_path=str(path))

    records = _startup_records(caplog)
    assert [r.levelno for r in records] == [logging.WARNING]
    assert "is not used" in records[0].getMessage()

    async with _stop_service(tmp_path) as service:
        runtime = SimpleNamespace(config=config, credential_store=store, agent_stops=service)
        assert crew_scope_token(runtime) == KEYRING_TOKEN
        async with _client(stop_routes.router, runtime) as client:
            accepted = await client.get("/api/stops", headers=_bearer(KEYRING_TOKEN))
            refused = await client.get("/api/stops", headers=_bearer(FILE_TOKEN))
    assert accepted.status_code == 200  # premise: the keyring's token is the one the route takes
    assert refused.status_code == 401
    assert KEYRING_TOKEN not in caplog.text
    assert FILE_TOKEN not in caplog.text


async def test_a_locked_keyring_is_logged_as_an_error_without_a_value(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_STARTUP_LOGGER):
        await loaded_store(SystemConfig(), FailingKeyring())

    records = _startup_records(caplog)
    assert [r.levelno for r in records] == [logging.ERROR]
    assert "crew_scope_token_unavailable" in records[0].getMessage()
    assert "keychain locked" not in caplog.text  # the exception's text could quote a value; only its type is kept


def test_startup_reads_the_keyring_once_before_anything_reads_the_token() -> None:
    source = inspect.getsource(ProbOSRuntime.start)

    assert source.count("crew_scope.load(") == 1
    stop_record = source.index("await self.agent_stops.start()")
    keyring_read = source.index(
        "await self.credential_store.crew_scope.load(config=self.config, config_path=self.config_path)"
    )
    assert stop_record < keyring_read < source.index("await init_nats(") < source.index("finalize_startup(")


class _RecordingKeyringStep(CrewScopeKeyring):
    """The real keyring step over a duck, recording what the runtime had started when startup called ``load``."""

    def __init__(self, runtime: ProbOSRuntime, backend: Any) -> None:
        super().__init__(backend=backend)
        self._runtime = runtime
        self.calls: list[tuple[bool, bool]] = []  # (the stop record exists, NATS not started yet)

    async def load(self, *, config: Any = None, config_path: str | None = None) -> KeyringRead:
        self.calls.append((self._runtime.agent_stops is not None, self._runtime.nats_bus is None))
        return await super().load(config=config, config_path=config_path)


def _boot_config() -> SystemConfig:
    # The BF-906 real-boot configuration (tests/test_bf906_crew_enrollment_boot.py, ``_config``).
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    return config


async def test_a_real_boot_reads_the_keyring_after_the_stop_record_and_before_nats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.startup import nats as startup_nats

    runtime = ProbOSRuntime(config=_boot_config(), data_dir=tmp_path / "data", llm_client=MockLLMClient())
    step = _RecordingKeyringStep(runtime, MemoryKeyring(token=KEYRING_TOKEN))
    runtime.credential_store.crew_scope = step
    assert step.source is CrewScopeSource.UNREAD  # premise
    assert crew_scope_locked(runtime) is True  # D21: before the read, no configured token -> refuse
    assert crew_scope_token(runtime) == ""

    real_init_nats = startup_nats.init_nats
    seen_at_nats: list[CrewScopeSource] = []

    async def recording_init_nats(config: SystemConfig) -> Any:
        seen_at_nats.append(runtime.credential_store.crew_scope.source)
        return await real_init_nats(config)

    monkeypatch.setattr(startup_nats, "init_nats", recording_init_nats)
    await runtime.start()
    try:
        assert step.calls == [(True, True)]  # once, after the stop record, before NATS
        assert seen_at_nats == [CrewScopeSource.KEYRING]  # the read had finished when NATS started
        assert crew_scope_token(runtime) == KEYRING_TOKEN
        assert crew_scope_locked(runtime) is False
    finally:
        await runtime.stop()


# --------------------------------------------------------------------------- #
# I -- the browser vault
# --------------------------------------------------------------------------- #


async def test_the_file_vault_is_keyed_from_the_keyring_token(tmp_path: Path) -> None:
    pytest.importorskip("playwright.async_api")
    from probos.tools.browser.credentials import EncryptedFileCredentialVault

    config = SystemConfig()
    config.browser_tool.enabled = True
    config.browser_tool.credential_vault.enabled = True
    config.browser_tool.credential_vault.file_path = str(tmp_path / "vault.json")
    assert config.auth.crew_scope_token == ""  # premise: only the keyring can key the vault
    runtime = SimpleNamespace(
        tool_registry=ToolRegistry(), audit_log=None, emit_event=None, config=config,
        credential_store=await loaded_store(config, MemoryKeyring(token=KEYRING_TOKEN)),
    )

    _wire_browser_tool(runtime=runtime, config=config)

    assert isinstance(runtime.credential_vault, EncryptedFileCredentialVault)


# --------------------------------------------------------------------------- #
# F -- the doctor check
# --------------------------------------------------------------------------- #


def _config_file(
    tmp_path: Path, *, file_token: str | None = None, vault: Path | None = None, name: str = "config.yaml",
) -> Path:
    """A config file under ``tmp_path``, optionally with ``auth.crew_scope_token`` and an enabled file vault."""
    settings: dict[str, Any] = {}
    if file_token is not None:
        settings["auth"] = {"crew_scope_token": file_token}
    if vault is not None:
        settings["browser_tool"] = {"credential_vault": {"enabled": True, "backend": "file", "file_path": str(vault)}}
    path = tmp_path / name
    path.write_text(yaml.safe_dump(settings), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("make_backend", "file_token", "outcome", "in_message", "in_remediation"),
    [
        pytest.param(
            partial(MemoryKeyring, token=KEYRING_TOKEN), None, CheckOutcome.OK, ["held in the OS keyring"], [],
            id="keyring-only",
        ),
        pytest.param(
            MemoryKeyring, FILE_TOKEN, CheckOutcome.WARN, ["{path}", "auth.crew_scope_token"],
            ["probos crew-token set", "401"], id="file-only",
        ),
        pytest.param(
            partial(MemoryKeyring, token=KEYRING_TOKEN), FILE_TOKEN, CheckOutcome.WARN, ["is not used"], [],
            id="both",
        ),
        pytest.param(MemoryKeyring, None, CheckOutcome.OK, ["not set"], [], id="neither"),
        pytest.param(FailingKeyring, None, CheckOutcome.FAIL, [], [], id="locked-keyring-no-file-token"),
        pytest.param(
            InsecureKeyring, FILE_TOKEN, CheckOutcome.WARN, ["no secure OS keyring"], [],
            id="no-secure-backend-file-token",
        ),
    ],
)
async def test_doctor_says_where_the_token_comes_from(
    tmp_path: Path, make_backend: Callable[[], Any], file_token: str | None, outcome: CheckOutcome,
    in_message: list[str], in_remediation: list[str],
) -> None:
    path = _config_file(tmp_path, file_token=file_token)
    ctx = DoctorContext(config=load_config(path), home_dir=tmp_path, data_dir=tmp_path, config_path=path)

    result = await _CrewScopeCheck(backend=make_backend()).run(ctx)

    assert result.outcome is outcome, result
    for expected in in_message:
        assert expected.format(path=path) in result.message
    for expected in in_remediation:
        assert expected in result.remediation
    for text in (result.message, result.remediation):
        assert FILE_TOKEN not in text
        assert KEYRING_TOKEN not in text


def test_doctor_check_is_registered_once() -> None:
    from probos.doctor import checks  # noqa: F401 -- importing the package registers every built-in check

    assert [check.name for check in iter_checks()].count("crew_scope_token") == 1


async def test_doctor_check_skips_without_a_config(tmp_path: Path) -> None:
    ctx = DoctorContext(config=None, home_dir=tmp_path, data_dir=tmp_path, config_path=None)

    result = await _CrewScopeCheck(backend=MemoryKeyring(token=KEYRING_TOKEN)).run(ctx)

    assert result.outcome is CheckOutcome.WARN
    assert "skipped" in result.message


# --------------------------------------------------------------------------- #
# G -- the Captain's CLI (``probos crew-token``)
# --------------------------------------------------------------------------- #

_SHORT_TOKEN = "bf908-short-tok"  # 15 characters: one below the stored-token rule


class _CountingKeyring(MemoryKeyring):
    """A secure in-memory backend that counts reads, to show a refused config never reaches the keyring."""

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0

    def get_password(self, service: str, username: str) -> str | None:
        self.reads += 1
        return super().get_password(service, username)


def _quiet_console() -> tuple[Console, io.StringIO]:
    """A console that writes to a buffer and never wraps, so a path or a message is not split across lines."""
    buffer = io.StringIO()
    return Console(file=buffer, width=300, soft_wrap=True, color_system=None), buffer


def _forbidden_secret(prompt: str) -> str:
    raise AssertionError(f"the secret prompt {prompt!r} was reached on a path that must refuse before it")


def _prompted(*answers: str) -> Callable[[str], str]:
    """A secret reader that gives each answer in turn, one per prompt."""
    remaining = iter(answers)
    return lambda _prompt: next(remaining)


def _assert_prints_no_token(text: str) -> None:
    for token in (KEYRING_TOKEN, FILE_TOKEN, ROTATED_TOKEN, _SHORT_TOKEN):
        assert token not in text


def test_cli_set_stores_a_prompted_token_and_never_prints_it(tmp_path: Path) -> None:
    mem = MemoryKeyring()
    console, out = _quiet_console()

    code = crew_token_cli.run(
        "set", config_path=_config_file(tmp_path), console=console, read_secret=lambda _: KEYRING_TOKEN,
        stdin_is_tty=lambda: True, backend=mem,
    )

    text = out.getvalue()
    assert code == 0
    assert mem.entries[ENTRY] == KEYRING_TOKEN
    assert KEYRING_TOKEN not in text
    assert "Restart the vessel" in text
    assert "401" in text


@pytest.mark.parametrize(
    ("make_backend", "answers", "reason"),
    [
        pytest.param(MemoryKeyring, (KEYRING_TOKEN, ROTATED_TOKEN), "differ", id="entries-differ"),
        pytest.param(MemoryKeyring, (_SHORT_TOKEN, _SHORT_TOKEN), "shorter than 16 characters", id="short-token"),
        pytest.param(
            partial(MemoryKeyring, token=KEYRING_TOKEN), (ROTATED_TOKEN, ROTATED_TOKEN), "crew-token rotate",
            id="already-held",
        ),
        pytest.param(InsecureKeyring, (KEYRING_TOKEN, KEYRING_TOKEN), "no secure OS keyring", id="no-secure-backend"),
        pytest.param(FailingKeyring, (KEYRING_TOKEN, KEYRING_TOKEN), "could not be read", id="failing-keyring"),
    ],
)
def test_cli_set_refuses(
    tmp_path: Path, make_backend: Callable[[], Any], answers: tuple[str, str], reason: str,
) -> None:
    assert len(_SHORT_TOKEN) == 15  # premise: one below the stored-token rule
    mem = make_backend()
    before = dict(mem.entries)
    console, out = _quiet_console()

    code = crew_token_cli.run(
        "set", config_path=_config_file(tmp_path), console=console, read_secret=_prompted(*answers),
        stdin_is_tty=lambda: True, backend=mem,
    )

    text = out.getvalue()
    assert code == 1
    assert reason in text
    assert mem.entries == before
    _assert_prints_no_token(text)


def test_cli_reads_standard_input_only_with_the_flag(tmp_path: Path) -> None:
    path = _config_file(tmp_path)
    mem = MemoryKeyring()
    console, out = _quiet_console()

    without_flag = crew_token_cli.run(
        "set", config_path=path, console=console, read_secret=_forbidden_secret, stdin_is_tty=lambda: False,
        stdin=io.StringIO(KEYRING_TOKEN + "\n"), backend=mem,
    )

    assert without_flag == 2
    assert mem.entries == {}  # the token waiting on standard input was not taken without the flag
    _assert_prints_no_token(out.getvalue())

    console, out = _quiet_console()
    with_flag = crew_token_cli.run(
        "set", config_path=path, console=console, use_stdin=True, read_secret=_forbidden_secret,
        stdin=io.StringIO(KEYRING_TOKEN + "\n"), backend=mem,
    )

    assert with_flag == 0
    assert mem.entries[ENTRY] == KEYRING_TOKEN
    _assert_prints_no_token(out.getvalue())


def test_cli_refuses_a_new_token_while_the_file_vault_holds_entries(tmp_path: Path) -> None:
    vault = tmp_path / "vault.json"
    vault.write_text('{"refs": {"r1": {}}}', encoding="utf-8")
    path = _config_file(tmp_path, vault=vault)
    held = MemoryKeyring(token=KEYRING_TOKEN)
    console, out = _quiet_console()

    different = crew_token_cli.run(
        "rotate", config_path=path, console=console, read_secret=lambda _: ROTATED_TOKEN, stdin_is_tty=lambda: True,
        backend=held,
    )

    assert different == 1
    assert held.entries[ENTRY] == KEYRING_TOKEN
    assert "holds 1 entry" in out.getvalue()
    _assert_prints_no_token(out.getvalue())

    console, out = _quiet_console()
    in_use = crew_token_cli.run(
        "rotate", config_path=path, console=console, read_secret=lambda _: KEYRING_TOKEN, stdin_is_tty=lambda: True,
        backend=held,
    )

    assert in_use == 0  # entering the token in use is not a change of key
    assert held.entries[ENTRY] == KEYRING_TOKEN
    _assert_prints_no_token(out.getvalue())

    console, out = _quiet_console()
    empty = MemoryKeyring()
    moved = crew_token_cli.run(
        "set", config_path=_config_file(tmp_path, file_token=FILE_TOKEN, vault=vault, name="moving.yaml"),
        console=console, read_secret=lambda _: FILE_TOKEN, stdin_is_tty=lambda: True, backend=empty,
    )

    assert moved == 0  # moving the config file's token into the keyring keeps the vault readable
    assert empty.entries[ENTRY] == FILE_TOKEN
    _assert_prints_no_token(out.getvalue())

    vault.write_text("{", encoding="utf-8")
    console, out = _quiet_console()
    unreadable = crew_token_cli.run(
        "rotate", config_path=path, console=console, read_secret=lambda _: ROTATED_TOKEN, stdin_is_tty=lambda: True,
        backend=held,
    )

    assert unreadable == 1
    assert held.entries[ENTRY] == KEYRING_TOKEN
    assert "cannot be read" in out.getvalue()
    _assert_prints_no_token(out.getvalue())


def test_cli_clear_removes_the_entry_and_is_never_refused_for_the_vault(tmp_path: Path) -> None:
    vault = tmp_path / "vault.json"
    vault.write_text('{"refs": {"r1": {}}}', encoding="utf-8")
    path = _config_file(tmp_path, vault=vault)
    mem = MemoryKeyring(token=KEYRING_TOKEN)
    console, out = _quiet_console()

    cleared = crew_token_cli.run("clear", config_path=path, console=console, backend=mem)

    assert cleared == 0
    assert ENTRY not in mem.entries
    assert str(vault.resolve()) in out.getvalue()  # the vault whose entries need the cleared token is named
    _assert_prints_no_token(out.getvalue())

    console, out = _quiet_console()
    again = crew_token_cli.run("clear", config_path=path, console=console, backend=mem)

    assert again == 0
    assert "held no" in out.getvalue()

    console, out = _quiet_console()
    insecure = InsecureKeyring(token=KEYRING_TOKEN)
    no_secure_backend = crew_token_cli.run("clear", config_path=path, console=console, backend=insecure)

    assert no_secure_backend == 0
    assert insecure.entries[ENTRY] == KEYRING_TOKEN  # a backend that is not secure is never touched
    _assert_prints_no_token(out.getvalue())


def test_cli_clear_reports_a_refused_deletion_and_keeps_the_entry(tmp_path: Path) -> None:
    refusing = RefusingDeleteKeyring(token=KEYRING_TOKEN)
    console, out = _quiet_console()

    code = crew_token_cli.run("clear", config_path=_config_file(tmp_path), console=console, backend=refusing)

    text = out.getvalue()
    assert code == 1
    assert "Not cleared" in text
    assert "PasswordDeleteError" in text
    assert "held no" not in text  # D22: a refusal is never reported as "none was there"
    assert DENIAL_DETAIL not in text
    assert refusing.entries[ENTRY] == KEYRING_TOKEN
    _assert_prints_no_token(text)


def test_cli_status_never_prints_the_token(tmp_path: Path) -> None:
    path = _config_file(tmp_path, file_token=FILE_TOKEN)
    console, out = _quiet_console()

    code = crew_token_cli.run("status", config_path=path, console=console, backend=MemoryKeyring(token=KEYRING_TOKEN))

    text = out.getvalue()
    assert code == 0
    assert KEYRING_TOKEN not in text
    assert FILE_TOKEN not in text
    assert "is not used" in text


def test_a_keyring_that_does_not_keep_the_token_is_reported(tmp_path: Path) -> None:
    console, out = _quiet_console()

    code = crew_token_cli.run(
        "set", config_path=_config_file(tmp_path), console=console, read_secret=lambda _: KEYRING_TOKEN,
        stdin_is_tty=lambda: True, backend=ForgetfulKeyring(),
    )

    assert code == 1
    assert "did not keep" in out.getvalue()
    _assert_prints_no_token(out.getvalue())


def test_the_cli_takes_no_token_on_the_command_line(tmp_path: Path) -> None:
    src_dir = Path(probos.__file__).resolve().parents[1]  # the tree this test runs against
    config = _config_file(tmp_path)  # never the Captain's config: the child is always told which file to read
    env = {**os.environ, "PYTHONPATH": str(src_dir)}
    assert env.get("PYTHON_KEYRING_BACKEND") == "keyring.backends.fail.Keyring"  # premise: the child inherits it
    command = [sys.executable, "-m", "probos", "--config", str(config), "crew-token", "set"]

    as_argument = subprocess.run(
        [*command, KEYRING_TOKEN], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120,
        check=False, cwd=tmp_path, env=env,
    )
    on_stdin = subprocess.run(
        [*command, "--stdin"], input=KEYRING_TOKEN + "\n", capture_output=True, text=True, timeout=120,
        check=False, cwd=tmp_path, env=env,
    )

    assert as_argument.returncode == 2, as_argument.stderr  # argparse refuses the extra argument
    # BF-908 A2 (D23): stderr is deliberately not asserted. argparse echoes the mistyped value there (residual R8);
    # it was already in the shell's history. Pinning the echo as the contract would be wrong; so would asserting
    # its absence, which no test here can make true without redacting the root parser.
    assert KEYRING_TOKEN not in as_argument.stdout
    assert on_stdin.returncode == 1, on_stdin.stderr
    assert "no secure OS keyring" in on_stdin.stdout
    assert KEYRING_TOKEN not in on_stdin.stdout
    assert KEYRING_TOKEN not in on_stdin.stderr


@pytest.mark.parametrize("command", ["status", "set", "clear"])
def test_cli_a_config_that_does_not_load_shows_its_type_never_its_text(tmp_path: Path, command: str) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"cognitive": {"llm_timeout_seconds": FILE_TOKEN}}), encoding="utf-8")
    with pytest.raises(ValidationError) as exc_info:
        load_config(path)
    assert FILE_TOKEN in str(exc_info.value)  # premise: the exception's text quotes the value (Pydantic's input_value)
    mem = _CountingKeyring()
    console, out = _quiet_console()

    code = crew_token_cli.run(
        command, config_path=path, console=console, read_secret=_forbidden_secret, stdin_is_tty=lambda: True,
        backend=mem,
    )

    text = out.getvalue()
    assert code == 2
    assert str(path) in text
    assert "ValidationError" in text
    assert "probos doctor --config" in text
    assert FILE_TOKEN not in text
    assert mem.entries == {}
    assert mem.reads == 0  # refused before the keyring was read


async def test_a_token_the_cli_stored_is_the_one_the_vessel_enforces(tmp_path: Path) -> None:
    # A seam test, not a contract row: the rows above and the route rows each pin one half (the CLI writes the entry;
    # startup reads it and a route enforces it). This one crosses the whole chain on one backend: CLI -> keyring ->
    # startup read -> accessor -> a Captain-route gate.
    path = _config_file(tmp_path)
    mem = MemoryKeyring()
    console, _ = _quiet_console()

    stored = crew_token_cli.run(
        "set", config_path=path, console=console, read_secret=lambda _: KEYRING_TOKEN, stdin_is_tty=lambda: True,
        backend=mem,
    )

    assert stored == 0
    config = load_config(path)
    assert config.auth.crew_scope_token == ""  # premise: the file holds no token, so only the CLI's entry can answer
    async with _stop_service(tmp_path) as service:
        runtime = await _runtime_over(mem, config=config, agent_stops=service)
        async with _client(stop_routes.router, runtime) as client:
            accepted = await client.get("/api/stops", headers=_bearer(KEYRING_TOKEN))
            refused = await client.get("/api/stops", headers=_bearer(ROTATED_TOKEN))
    assert accepted.status_code == 200
    assert refused.status_code == 401


# --------------------------------------------------------------------------- #
# H -- one reader of the setting, one writer of the entry (structural guards over src/probos)
# --------------------------------------------------------------------------- #

_SRC = Path(probos.__file__).resolve().parent
_OWNER = "probos.security.crew_scope"
_SETTING = "crew_scope_token"
_WRITERS = frozenset({"store_keyring_token", "clear_keyring_token"})


def _modules() -> Iterator[tuple[str, ast.Module]]:
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC.parent).with_suffix("")
        name = ".".join(rel.parts)
        yield name, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(module: str, tree: ast.Module) -> set[str]:
    """Dotted names ``tree`` imports, anywhere in it; relative imports resolved against ``module``'s package.

    ``module`` is the dotted name ``_modules()`` yields (``probos.routers.auth``; a package's
    ``__init__`` yields ``probos.routers.__init__``, whose package is ``probos.routers``).
    """
    package = module.split(".")[:-1]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                anchor = package[: len(package) - (node.level - 1)]
                base = ".".join([*anchor, *([node.module] if node.module else [])])
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names)
    return found


def _names_setting(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == _SETTING


def _setting_reads(tree: ast.Module) -> list[tuple[int, str]]:
    """Where ``tree`` reads the setting by name, as ``(line, shape)``, sorted by line.

    A read is an attribute (``x.crew_scope_token``), a ``getattr``/``hasattr``/``setattr`` call that names it as its
    second argument, or a subscript by it. The same text in any other position is not a read: the doctor check's
    ``name`` and the keyring entry's username are constants.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == _SETTING:
            found.append((node.lineno, "attribute"))
        elif (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in ("getattr", "hasattr", "setattr")
            and len(node.args) >= 2 and _names_setting(node.args[1])
        ):
            found.append((node.args[1].lineno, node.func.id))
        elif isinstance(node, ast.Subscript) and _names_setting(node.slice):
            found.append((node.slice.lineno, "subscript"))
    return sorted(found)


def _writer_names(tree: ast.Module) -> set[str]:
    """The keyring writers ``tree`` refers to, as a bare name or as an attribute."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in _WRITERS:
            names.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in _WRITERS:
            names.add(node.attr)
    return names


def test_no_module_reads_the_token_setting_directly() -> None:
    probe = ast.parse(
        'getattr(a, "crew_scope_token", "")\nb["crew_scope_token"]\nc.auth.crew_scope_token\nname: str = "crew_scope_token"'
    )
    # Detector premise: the three read shapes are found at their lines, and the same text as a name is not a read.
    assert [line for line, _ in _setting_reads(probe)] == [1, 2, 3]

    visited = 0
    owner_reads: list[tuple[int, str]] = []
    offenders: list[str] = []
    for name, tree in _modules():
        visited += 1
        reads = _setting_reads(tree)
        if name == _OWNER:
            owner_reads = reads
        else:
            offenders.extend(f"{name}:{line} ({shape})" for line, shape in reads)

    assert visited > 500, f"the scan visited only {visited} files"
    assert offenders == [], f"BF-908: these read auth.crew_scope_token, not through crew_scope_token(runtime): {offenders}"
    assert [shape for _, shape in owner_reads] == ["attribute"]  # the one read, in configured_crew_scope_token


def test_only_the_captain_s_cli_writes_the_keyring_entry() -> None:
    # Detector premise: a relative import is resolved, so ``from ..security import crew_scope`` in a router is seen.
    assert "probos.security.crew_scope" in _imports("probos.routers.x", ast.parse("from ..security import crew_scope"))

    writers: set[str] = set()
    cli_importers: set[str] = set()
    keyring_importers: set[str] = set()
    cli_imports: set[str] | None = None
    for name, tree in _modules():
        module = name.removesuffix(".__init__")
        imports = _imports(name, tree)
        if module != _OWNER and _writer_names(tree):
            writers.add(module)
        if "probos.crew_token_cli" in imports:
            cli_importers.add(module)
        if _OWNER in imports:
            keyring_importers.add(module)
        if module == "probos.crew_token_cli":
            cli_imports = imports

    assert writers == {"probos.crew_token_cli"}
    assert cli_importers == {"probos.__main__"}
    assert keyring_importers == {
        "probos.credential_store", "probos.crew_token_cli", "probos.doctor.checks.crew_scope_check",
    }
    assert cli_imports is not None, "the scan did not find probos.crew_token_cli"
    doctor_imports = sorted(n for n in cli_imports if n == "probos.doctor" or n.startswith("probos.doctor."))
    assert doctor_imports == [], (
        f"BF-908 (D19): probos.crew_token_cli imports the doctor package {doctor_imports}; only probos.__main__ may (AD-1137)"
    )
