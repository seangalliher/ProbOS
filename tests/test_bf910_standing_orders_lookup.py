"""BF-910 (#1608): a standing-orders lookup selects a name, never a path.

``probos.cognitive.standing_orders`` owns the flat layout of
``config/standing_orders/`` (one ``<name>.md`` per ship, department or agent),
so it also owns the three public helpers a lookup uses to turn a caller's value
into a file only by way of a name: ``is_standing_order_name`` (the shape of a
name), ``standing_orders_dir`` (the directory the loader reads by default) and
``standing_order_names`` (the names a caller may select from a directory).
``StandingOrdersLookupTool`` (``probos.cognitive.swe_harness.tools``) takes its
``department`` through them, and its tests are in this file too. So does
``CopilotBuilderAdapter._handle_standing_orders``
(``probos.cognitive.copilot_adapter``), the handler of the visiting Copilot
session's ``standing_orders_lookup``; its tests, T21 to T35, are in this file as
well.

The T numbers below are the rows of the test tables in the contract,
``prompts/bf-910-standing-orders-lookup-name-containment.md``: T1 to T20 in its
Tests section, T21 to T34 in its Amendment A1, T35 in its Amendment A2, T36
in its Amendment A3, and T37, T37b and T38 in its Amendment A4. T19b
is a row added to the first of them, for the order of the names.

This file proves, of the tool (built over a directory in ``tmp_path``, except
in T13):

- A ``department`` that is not one name gets one fixed refusal, in the
  ``department`` and the ``agent`` scope, before any file is read: a ``..`` or
  absolute path, a drive, UNC, extended-length or alternate-stream spelling, a
  NUL, a space, a trailing dot or newline, a look-alike letter, a value of 65
  or 10000 characters (T2), and any value that is not an exact ``str``, falsy
  or not: an empty ``str`` subclass, an object equal to ``""`` and an object
  whose ``==`` raises are refused too, with no exception and without falling to
  the default (T3). The result holds no marker planted outside the directory, never
  echoes the value, and no read is made: no verified read, and no ``.md`` file
  through ``Path.read_text``.
- A name that exists is read, once, from directly inside the resolved base, and
  ``ship`` ignores ``department`` (T4). No value, ``None`` or an exact ``""``
  means ``engineering`` (T5).
- An unlisted name, a directory's too, is not found and the answer lists the
  names (T6); a missing directory lists none (T6b); the wrong case (T7) and a
  device name (T8) are not found and no file is read.
- A listed name whose file is a link out of the directory is refused (T9); a
  base that is itself a link is read through its resolution (T10).
- The BF-758 floor refuses a directory inside the data directory (T11), and the
  operator's read roots refuse what lies outside them and admit what lies
  inside them (T12).
- Built with ``runtime`` alone, the tool reads the loader's directory, the
  checkout's tracked ``config/standing_orders/``: ``standing_orders_dir()`` is
  that directory, and the tool returns its ``engineering`` file by default and
  its ``ship`` file for the ``ship`` scope (T13).
- ``agent`` is not a parameter (T14); a CRLF file is returned with LF newlines
  (T15); a failed read names only its exception type, and a floor refusal is
  fixed text (T16); the scope refusal is unchanged and comes first (T17). A
  ``scope`` that is not an exact ``str`` gets it too, before it is compared,
  even one that equals a scope name, with no exception (T36).
- A ``department`` lookup that raises, in the ``department`` and the ``agent``
  scope, called directly and through a real ``ToolRegistry``, is answered with
  ``standing_orders_lookup failed: <type>``, or the fixed denied text for a
  ``FileAccessDenied``, with no read, no exception and not the exception's
  message, and only the type is logged (T37); ``ship`` does not look it up
  (T37b). The type is read with none of the code of the exception's class or
  metaclass: a class whose metaclass is not ``type``, or whose name is not an
  exact ``str``, is named ``Exception`` (T38).
- Across the inputs of T2 to T8, in both scopes, every verified read is of a
  file directly in the base, and no ``.md`` file is read with ``Path.read_text``
  (T18).

It proves, of the visiting session's handler (a ``CopilotBuilderAdapter`` built
with ``runtime`` and ``orders_dir`` over a directory in ``tmp_path``, except in
T33, and called directly as ``await adapter._handle_standing_orders(...)``, with
the two read spies of the tool's tests, a verified read and a plain
``Path.read_text``, the first one placed on the adapter's own
``read_verified_file``):

- A ``department`` that is not one name gets the adapter's one fixed refusal:
  each value of T2's list (T21), and each truthy value that is not an exact
  ``str``: ``5``, ``1.5``, ``True``, a list, a dict, bytes, a ``str``
  subclass, an object equal to ``""`` and an object whose ``==`` raises
  (T22). For T2's values the reply also holds no marker planted
  outside the directory and does not contain the value. For both, no read is
  made: no verified read, and no ``.md`` file through ``Path.read_text``.
- A falsy ``department`` (absent, ``None``, ``""``, ``0``, ``False``, ``[]``,
  ``{}`` or an empty ``str`` subclass) still answers ``No department
  specified`` and no read is made (T23).
- ``engineering``, ``builder`` and ``ship`` are each read once, from directly
  inside the resolved base (T24). An unlisted name, a directory's, the wrong
  case and a device name (``nosuch``, ``crew_profiles``, ``Engineering``,
  ``CON``, ``NUL``, ``COM1``) each get one fixed not-found reply that lists the
  names and does not contain the value, and no read is made (T25); a missing
  directory lists none (T26).
- A listed name whose file is a link out of the directory is refused with the
  fixed denied text, and the file's text is not in the reply (T27); a base that
  is itself a link is read through its resolution (T28).
- The BF-758 floor refuses a directory inside the data directory (T29), and the
  operator's read roots refuse what lies outside them and admit what lies inside
  them (T30); each refusal is the fixed denied text.
- A failed read names only its exception type, and a floor refusal is the fixed
  denied text (T31).
- The reply is the text ``Path.read_text(encoding="utf-8", errors="replace")``
  gives: a CRLF file with LF newlines, and an invalid byte as U+FFFD (T32).
- Built with neither ``runtime`` nor ``orders_dir`` (the platform data directory
  that the floor then falls back to is pointed into ``tmp_path``), the handler
  returns the ``engineering`` file of the loader's directory, the checkout's
  tracked ``config/standing_orders/``, and not the file of a decoy tree that
  ``_PROJECT_ROOT`` is pointed at for the test (T33).
- Across the inputs of T21 to T25, every verified read is of a file directly in
  the base, and no ``.md`` file is read with ``Path.read_text`` (T34).
- The handler that ``_build_mcp_tools`` registers under the name
  ``standing_orders_lookup`` refuses a path with the fixed text and returns a
  listed name's file (T35); a recorder stands in for the SDK's ``Tool``.

It proves, of the helpers:

- ``standing_order_names`` lists exactly the selectable stems: each
  ``<name>.md`` directly in the directory whose stem is a name. A subdirectory,
  a file that is not ``.md``, an upper-case ``.MD``, a dotted stem and a stem
  with a space are left out, and a missing directory has no names rather than
  raising (T19).
- ``standing_order_names`` returns the names in plain code-point order,
  ``0 B Z _x a m`` for the six planted, not in the case-insensitive order a
  listing may come in (T19b).
- ``is_standing_order_name`` accepts a 64-character name and refuses what lies
  just outside the shape: 65 characters, the empty value, ``None``, a ``str``
  subclass, a dot and a trailing newline (T20).

It does not prove:

- That every possible bypass is covered. The allowlist is the proof and the
  values here are a sample of its boundaries.
- Anything on a Windows host without symlink privilege, for T9 and T27: they
  skip there, and a Linux CI runs them.
- The registry the vessel builds: T37 and T37b send their calls through a real
  ``ToolRegistry`` that the test builds, with an ensign's read permission, and
  T13 makes the registration call's one argument, ``runtime``; none goes
  through ``register_native_swe_tools`` or the native tool loop.
- That the listing refuses a directory named ``*.md``: none is planted in any
  directory here, and the listing goes by file name only, so a consumer must
  still read through a verified reader.
- The Copilot session around the handler. T21 to T34 call
  ``_handle_standing_orders`` directly, and T35 calls the handler that
  ``_build_mcp_tools`` registers, with a ``SimpleNamespace`` in the place of the
  SDK's tool invocation and a recorder in the place of the SDK's ``Tool``: they
  do not start the SDK, a client or a session, and they use no network. What a
  session sends the handler is not exercised here.
- That the code which constructs the adapter passes what T33 passes. T33 builds
  ``CopilotBuilderAdapter()`` with neither ``runtime`` nor ``orders_dir``, which
  is what ``build_dispatcher`` passes for those two, but it does not go through
  the dispatcher or any other construction site.
- That the handler reads no checkout root other than through ``_PROJECT_ROOT``:
  T33 points ``_PROJECT_ROOT`` at a decoy, which tells the loader's directory
  from the one the handler used to read, but a handler that computed the
  checkout root afresh would, in a checkout, read the loader's directory.

All state lives in ``tmp_path``, except that T13 and T33 read the checkout's
tracked ``config/standing_orders/``, read-only. No live runtime data is touched,
nothing sleeps and nothing uses the network.
"""

from __future__ import annotations

import operator
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive import copilot_adapter, standing_orders
from probos.cognitive.copilot_adapter import CopilotBuilderAdapter
from probos.cognitive.standing_orders import (
    is_standing_order_name,
    standing_order_names,
    standing_orders_dir,
)
from probos.cognitive.swe_harness import tools
from probos.cognitive.swe_harness.tools import StandingOrdersLookupTool
from probos.security.file_access import FileAccessDenied
from probos.tools.protocol import ToolResult
from probos.tools.registry import ToolRegistry


class _Str(str):
    """A ``str`` subclass: a name must be an exact ``str``, never a subclass."""


class _EqualsEmpty:
    """Not a ``str``, but equal to ``""`` under ``==``: it is refused, not taken for no value."""

    def __eq__(self, other: object) -> bool:
        return isinstance(other, str) and other == ""


class _EqRaises:
    """Not a ``str``; ``==``, and so ``!=`` and ``in``, raise: it is refused before any comparison."""

    def __eq__(self, other: object) -> bool:
        raise ValueError("compared before its type was checked")


class _PassesTheScopeGate:
    """Not a ``str``: equal to ``"department"`` under ``==`` and ``in``, while ``!=`` raises."""

    def __eq__(self, other: object) -> bool:
        return isinstance(other, str) and other == "department"

    def __ne__(self, other: object) -> bool:
        raise ValueError("compared after the scope gate")


_MARKER_GET = "MARKER-BF910-GET"  # T37/T38: the message of each exception a ``department`` lookup raises


class _GetRaises(dict[str, object]):
    """A call's parameters whose ``get`` raises *error* for ``department``; other keys read as a ``dict``'s."""

    def __init__(self, items: dict[str, object], error: Exception) -> None:
        super().__init__(items)
        self.error = error
        self.department_lookups = 0

    def get(self, key: object, default: object = None) -> object:
        if key == "department":
            self.department_lookups += 1
            raise self.error
        return super().get(key, default)


class _Warnings:
    """Stands in for ``tools.logger``: the formatted message of each ``warning`` call."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def warning(self, msg: str, *args: object) -> None:
        self.messages.append(msg % args)


def _metaclass_named_failure() -> Exception:
    """T38: an exception whose metaclass raises when its class's ``__name__`` is read."""

    class NameRaises(type):
        @property
        def __name__(cls) -> str:
            raise RuntimeError("the class name was read")

    class Failure(Exception, metaclass=NameRaises):
        pass

    return Failure(_MARKER_GET)


def _renamed_failure() -> Exception:
    """T38: an exception whose class's ``__name__`` is a ``str`` subclass that raises when formatted."""

    class FormatRaises(str):
        def __format__(self, spec: str) -> str:
            raise RuntimeError("the class name was formatted")

    class Failure(Exception):
        pass

    Failure.__name__ = FormatRaises("Failure")
    return Failure(_MARKER_GET)


async def _send(route: str, tool: StandingOrdersLookupTool, params: dict[str, object]) -> ToolResult:
    """*params* sent to *tool* directly, or through a real ``ToolRegistry`` as an ensign holding read permission."""
    if route == "direct":
        return await tool.invoke(params)
    registry = ToolRegistry()
    registry.register(tool, default_permissions={"ensign": "read"})
    return await registry.check_and_invoke("bf910-probe", tool.tool_id, params)


async def _contained(call: Awaitable[ToolResult]) -> tuple[ToolResult | None, str | None]:
    """*call*'s result, or the ``__qualname__`` of the exception that left it.

    The exception is caught here rather than by pytest, so no report reads a
    probe's ``__name__``; ``__qualname__`` is answered by ``type``'s own lookup.
    """
    try:
        return await call, None
    except Exception as exc:  # the defect under test: a failure that left ``invoke``
        return None, type(exc).__qualname__


# T37: a ``department`` lookup that raises, as (id, the exception, the reply, the warnings logged).
_LOOKUP_FAILURES: tuple[tuple[str, Callable[[], Exception], str, tuple[str, ...]], ...] = (
    (
        "runtime-error",
        lambda: RuntimeError(_MARKER_GET),
        "standing_orders_lookup failed: RuntimeError",
        ("BF-910: standing_orders_lookup failed: RuntimeError",),
    ),
    (
        "file-access-denied",
        lambda: FileAccessDenied(_MARKER_GET, _MARKER_GET),
        tools._STANDING_ORDERS_DENIED,
        (),
    ),
)


_SHIP = "SHIP-ORDERS"
_ENG = "ENG-ORDERS"
_BUILDER = "BUILDER-ORDERS"
_SCI = "SCI-ORDERS"
_MARKER_CONFIG = "MARKER-BF910-CONFIG"
_MARKER_ROOT = "MARKER-BF910-ROOT"
# What a lookup answers for a name that is not listed: the ``orders`` fixture's names, in name order.
_NOT_FOUND = "Standing orders not found for that name; available: builder, engineering, science, ship"

# T2: values that are not one name, as (id, value). A callable is called with
# ``tmp_path`` and spells the absolute path of a marker planted outside the directory.
_NOT_ONE_NAME: tuple[tuple[str, object], ...] = (
    ("dotdot-slash", "../secret"),
    ("dotdot-backslash", "..\\secret"),
    ("dotdot-twice", "../../secret"),
    ("dotdot", ".."),
    ("dot", "."),
    ("subdirectory-slash", "crew_profiles/deep"),
    ("subdirectory-backslash", "crew_profiles\\deep"),
    ("dotdot-after-name", "engineering/../secret"),
    ("absolute-no-suffix", lambda tmp_path: str(tmp_path / "secret")),
    ("absolute-with-suffix", lambda tmp_path: str(tmp_path / "secret.md")),
    ("drive-relative", "C:secret"),
    ("drive-absolute", "C:\\secret"),
    ("unc-backslash", "\\\\server\\share\\secret"),
    ("unc-slash", "//server/share/secret"),
    ("extended-length", "\\\\?\\C:\\secret"),
    ("nul-suffix", "engineering\x00"),
    ("trailing-dot", "engineering."),
    ("trailing-space", "engineering "),
    ("leading-space", " engineering"),
    ("trailing-newline", "engineering\n"),
    ("alternate-stream", "engineering::$DATA"),
    ("inner-space", "engi neering"),
    ("percent-encoded", "%2e%2e%2fsecret"),
    # "engineering" in fullwidth letters (U+FF45 and so on), written as escapes so
    # that no look-alike character sits in the source.
    ("fullwidth-lookalike", "\uff45\uff4e\uff47\uff49\uff4e\uff45\uff45\uff52\uff49\uff4e\uff47"),
    ("x65", "x" * 65),
    ("x10000", "x" * 10000),
)

# T3: values that are not a ``str``, or only a subclass of it, as (id, value).
_NOT_A_STR: tuple[tuple[str, object], ...] = (
    ("int-zero", 0),
    ("false", False),
    ("true", True),
    ("int-five", 5),
    ("float", 1.5),
    ("list", ["engineering"]),
    ("dict", {"a": 1}),
    ("bytes", b"engineering"),
    ("str-subclass", _Str("engineering")),
    ("empty-str-subclass", _Str("")),
    ("equals-empty", _EqualsEmpty()),
    ("eq-raises", _EqRaises()),
)

# T36: a ``scope`` that is not an exact ``str``, two of them equal to a scope name, as (id, value).
_NOT_A_STR_SCOPE: tuple[tuple[str, object], ...] = (
    ("str-subclass-ship", _Str("ship")),
    ("str-subclass-department", _Str("department")),
    ("passes-the-scope-gate", _PassesTheScopeGate()),
    ("eq-raises", _EqRaises()),
)

# T4: a name that exists is read, as (id, scope, params, listed name, file text).
# The ``ship`` scope ignores ``department``.
_REAL_NAMES: tuple[tuple[str, str, dict[str, object], str, str], ...] = (
    ("ship", "ship", {}, "ship", _SHIP),
    ("ship-ignores-department", "ship", {"department": "../secret"}, "ship", _SHIP),
    ("department-engineering", "department", {"department": "engineering"}, "engineering", _ENG),
    ("department-science", "department", {"department": "science"}, "science", _SCI),
    ("agent-builder", "agent", {"department": "builder"}, "builder", _BUILDER),
)

# T5: no value for ``department``, in the three spellings a caller can give it, as (id, params).
_NO_VALUE: tuple[tuple[str, dict[str, object]], ...] = (
    ("absent", {}),
    ("none", {"department": None}),
    ("empty", {"department": ""}),
)

_UNKNOWN_NAMES = ("nosuch", "crew_profiles")  # T6: the second is a directory, not a name
_WRONG_CASE_NAMES = ("Engineering", "ENGINEERING")  # T7
_DEVICE_NAMES = ("CON", "NUL", "AUX", "PRN", "COM1", "LPT1")  # T8

# T22: the values of T3 that are truthy; the falsy ones are T23's, not a refusal.
_TRUTHY_NOT_A_STR: tuple[tuple[str, object], ...] = tuple(case for case in _NOT_A_STR if case[1])

# T23: a falsy ``department``, as (id, the ``arguments`` of the call). The first three are T5's.
_FALSY_DEPARTMENT: tuple[tuple[str, dict[str, object]], ...] = (
    *_NO_VALUE,
    ("int-zero", {"department": 0}),
    ("false", {"department": False}),
    ("empty-list", {"department": []}),
    ("empty-dict", {"department": {}}),
    ("empty-str-subclass", {"department": _Str("")}),
)

# T24: a name the visiting session selects and is given the file of, as (name, file text).
_ADAPTER_REAL_NAMES: tuple[tuple[str, str], ...] = (
    ("engineering", _ENG),
    ("builder", _BUILDER),
    ("ship", _SHIP),
)

# T25: values the shape admits but no file carries: an unlisted name, a directory,
# the wrong case and device names.
_ADAPTER_NOT_FOUND_NAMES = ("nosuch", "crew_profiles", "Engineering", "CON", "NUL", "COM1")
# What the adapter answers for them: the ``orders`` fixture's names, in name order.
_ADAPTER_NOT_FOUND = (
    "No standing orders found for that department; available: builder, engineering, science, ship"
)
_ADAPTER_UNSPECIFIED = "No department specified"  # T23: the reply to a falsy ``department``


class _Reads:
    """What a lookup read: every verified read, and every plain ``Path.read_text``."""

    def __init__(self) -> None:
        self.verified: list[Path] = []
        self.plain: list[Path] = []

    @property
    def plain_markdown(self) -> list[Path]:
        return [path for path in self.plain if path.suffix.lower() == ".md"]


def _spell(value: object, tmp_path: Path) -> object:
    """A table value as a caller sends it: a callable spells a path under ``tmp_path``."""
    return value(tmp_path) if callable(value) else value


def _runtime(tmp_path: Path, read_roots: tuple[Path, ...] = ()) -> SimpleNamespace:
    """A runtime shaped as the floor and the read policy read it, rooted in ``tmp_path``."""
    workspaces = tmp_path / "data" / "execution" / "workspaces"
    workspaces.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        data_dir=tmp_path / "data",
        config_path=None,
        config=SimpleNamespace(
            execution=SimpleNamespace(workspace_root=str(workspaces)),
            security_infra=SimpleNamespace(read_roots=[str(root) for root in read_roots]),
        ),
    )


def _tool(
    tmp_path: Path, orders_dir: Path, read_roots: tuple[Path, ...] = ()
) -> StandingOrdersLookupTool:
    return StandingOrdersLookupTool(_runtime(tmp_path, read_roots), orders_dir=orders_dir)


def _adapter(
    tmp_path: Path, orders_dir: Path, read_roots: tuple[Path, ...] = ()
) -> CopilotBuilderAdapter:
    """The visiting session's adapter over *orders_dir*; it is never started, so no SDK client or network."""
    return CopilotBuilderAdapter(runtime=_runtime(tmp_path, read_roots), orders_dir=orders_dir)


async def _ask(adapter: CopilotBuilderAdapter, arguments: dict[str, object]) -> str:
    """The text the visiting session is told for a ``standing_orders_lookup`` call with *arguments*."""
    result = await adapter._handle_standing_orders(SimpleNamespace(arguments=arguments))
    return result.text_result_for_llm


def _junction(link: Path, target: Path) -> None:
    """A directory link that needs no privilege on Windows (a junction)."""
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
        assert link.is_junction()
    else:
        link.symlink_to(target, target_is_directory=True)
        assert link.is_symlink()


def _unlink_junction(path: Path) -> None:
    if os.name == "nt":
        path.rmdir()
    else:
        path.unlink()


def _raising(error: Exception) -> Any:
    def read(*args: Any, **kwargs: Any) -> Any:
        raise error

    return read


@pytest.fixture
def orders(tmp_path: Path) -> Path:
    """A flat standing-orders directory, with one subdirectory beside the files."""
    directory = tmp_path / "checkout" / "config" / "standing_orders"
    (directory / "crew_profiles").mkdir(parents=True)
    (directory / "ship.md").write_text(_SHIP, encoding="utf-8")
    (directory / "engineering.md").write_text(_ENG, encoding="utf-8")
    (directory / "builder.md").write_text(_BUILDER, encoding="utf-8")
    (directory / "science.md").write_text(_SCI, encoding="utf-8")
    (directory / "crew_profiles" / "deep.md").write_text("MARKER-BF910-DEEP", encoding="utf-8")
    return directory


@pytest.fixture
def markers(orders: Path, tmp_path: Path) -> tuple[Path, Path]:
    """Two readable files outside the directory, which no lookup may return."""
    config_marker = orders.parent / "secret.md"
    root_marker = tmp_path / "secret.md"
    config_marker.write_text(_MARKER_CONFIG, encoding="utf-8")
    root_marker.write_text(_MARKER_ROOT, encoding="utf-8")
    return config_marker, root_marker


@pytest.fixture
def reads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    orders: Path,
    markers: tuple[Path, Path],
) -> _Reads:
    """Spies on both ways a lookup could read a file, installed after the files are written.

    Each spy records the call and then runs the real function, so a lookup
    behaves as it would unspied.
    """
    recorded = _Reads()
    real_verified = tools.read_verified_file
    real_read_text = Path.read_text

    def verified(path: Path, *args: Any, **kwargs: Any) -> Any:
        recorded.verified.append(Path(path))
        return real_verified(path, *args, **kwargs)

    def read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        recorded.plain.append(self)
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(tools, "read_verified_file", verified)
    monkeypatch.setattr(Path, "read_text", read_text)
    # Premise: the Path.read_text spy records a read, so "no .md was read" below is a finding.
    probe = tmp_path / "spy-probe.txt"
    probe.write_text("probe", encoding="utf-8")
    assert probe.read_text(encoding="utf-8") == "probe"
    assert recorded.plain == [probe]
    recorded.plain.clear()
    return recorded


@pytest.fixture
def adapter_reads(monkeypatch: pytest.MonkeyPatch, reads: _Reads) -> _Reads:
    """``reads``, plus a spy on the verified read the adapter makes through its own import of it.

    The adapter imports ``read_verified_file`` by name, so the spy replaces that
    name in ``probos.cognitive.copilot_adapter``. It records into the same
    ``_Reads`` as the tool's spy and then runs the real function. The lookup is
    strict about the name: if the module has no ``read_verified_file``, the
    fixture fails rather than leave a spy that never sees a call.
    """
    real_verified = copilot_adapter.read_verified_file

    def verified(path: Path, *args: Any, **kwargs: Any) -> Any:
        reads.verified.append(Path(path))
        return real_verified(path, *args, **kwargs)

    monkeypatch.setattr(copilot_adapter, "read_verified_file", verified)
    return reads


def test_premise_the_outside_markers_are_readable(markers: tuple[Path, Path]) -> None:
    """T1: each marker reads back directly, so a later refusal comes from the tool, not the filesystem."""
    config_marker, root_marker = markers

    assert config_marker.read_text(encoding="utf-8") == _MARKER_CONFIG
    assert root_marker.read_text(encoding="utf-8") == _MARKER_ROOT


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ("department", "agent"))
@pytest.mark.parametrize("value", [pytest.param(value, id=name) for name, value in _NOT_ONE_NAME])
async def test_a_name_that_is_not_one_segment_is_refused(
    scope: str,
    value: object,
    tmp_path: Path,
    orders: Path,
    markers: tuple[Path, Path],
    reads: _Reads,
) -> None:
    """T2: a value that is not one name gets the fixed refusal, before any file is touched."""
    spelled = _spell(value, tmp_path)

    result = await _tool(tmp_path, orders).invoke({"scope": scope, "department": spelled})

    assert "MARKER-BF910" not in repr(result)
    assert result.output is None
    assert result.error == tools._STANDING_ORDERS_NAME_REFUSAL
    assert spelled not in result.error
    assert reads.verified == []
    assert reads.plain_markdown == []


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ("department", "agent"))
@pytest.mark.parametrize("value", [pytest.param(value, id=name) for name, value in _NOT_A_STR])
async def test_a_non_string_department_is_refused(
    scope: str,
    value: object,
    tmp_path: Path,
    orders: Path,
    reads: _Reads,
) -> None:
    """T3: a non-string value, falsy or not, and a ``str`` subclass, empty or not, get the same refusal, with no exception."""
    result = await _tool(tmp_path, orders).invoke({"scope": scope, "department": value})

    assert result.output is None
    assert result.error == tools._STANDING_ORDERS_NAME_REFUSAL
    assert reads.verified == []
    assert reads.plain_markdown == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "params", "name", "expected"),
    [pytest.param(*case[1:], id=case[0]) for case in _REAL_NAMES],
)
async def test_real_names_resolve(
    scope: str,
    params: dict[str, object],
    name: str,
    expected: str,
    tmp_path: Path,
    orders: Path,
    reads: _Reads,
) -> None:
    """T4: a name that exists is read, once, from directly inside the resolved base."""
    result = await _tool(tmp_path, orders).invoke({"scope": scope, **params})

    assert result.error is None
    assert result.output == expected
    assert reads.verified == [orders.resolve() / f"{name}.md"]
    assert reads.plain_markdown == []


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ("department", "agent"))
@pytest.mark.parametrize("params", [pytest.param(params, id=name) for name, params in _NO_VALUE])
async def test_the_default_name_is_engineering(
    scope: str, params: dict[str, object], tmp_path: Path, orders: Path
) -> None:
    """T5: no value for ``department`` means ``engineering``, in both scopes."""
    result = await _tool(tmp_path, orders).invoke({"scope": scope, **params})

    assert result.error is None
    assert result.output == _ENG


@pytest.mark.asyncio
@pytest.mark.parametrize("value", _UNKNOWN_NAMES)
async def test_an_unknown_name_is_not_found_and_lists_the_names(
    value: str, tmp_path: Path, orders: Path, reads: _Reads
) -> None:
    """T6: an unlisted name, even a directory's, is not found, and the answer lists the names."""
    result = await _tool(tmp_path, orders).invoke({"scope": "department", "department": value})

    assert result.output is None
    assert result.error == _NOT_FOUND
    assert value not in result.error
    assert reads.verified == []
    assert reads.plain_markdown == []


@pytest.mark.asyncio
async def test_a_missing_directory_has_no_names(tmp_path: Path, reads: _Reads) -> None:
    """T6b: with no directory there are no names, so the answer lists none and nothing is read."""
    absent = tmp_path / "absent"
    assert not absent.exists()

    result = await _tool(tmp_path, absent).invoke({"scope": "department", "department": "engineering"})

    assert result.output is None
    assert result.error.endswith("available: none")
    assert reads.verified == []
    assert reads.plain_markdown == []


@pytest.mark.asyncio
@pytest.mark.parametrize("value", _WRONG_CASE_NAMES)
async def test_case_must_match_exactly(
    value: str, tmp_path: Path, orders: Path, reads: _Reads
) -> None:
    """T7: a name in the wrong case is not found on any OS, though a Windows filesystem would admit it."""
    result = await _tool(tmp_path, orders).invoke({"scope": "department", "department": value})

    assert result.output is None
    assert result.error == _NOT_FOUND
    assert value not in result.error
    assert reads.verified == []
    assert reads.plain_markdown == []


@pytest.mark.asyncio
@pytest.mark.parametrize("value", _DEVICE_NAMES)
async def test_device_names_are_never_opened(
    value: str, tmp_path: Path, orders: Path, reads: _Reads
) -> None:
    """T8: a name the shape admits but no file carries is never opened, a console device included."""
    result = await _tool(tmp_path, orders).invoke({"scope": "department", "department": value})

    assert result.output is None
    assert result.error == _NOT_FOUND
    assert reads.verified == []
    assert reads.plain_markdown == []


@pytest.mark.asyncio
async def test_a_link_in_the_directory_that_points_outside_is_refused(
    tmp_path: Path, orders: Path, markers: tuple[Path, Path], reads: _Reads
) -> None:
    """T9: a listed name whose file is a link out of the directory is refused by the verified read."""
    _, root_marker = markers
    try:
        (orders / "leak.md").symlink_to(root_marker)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation requires privilege on this host")
    assert "leak" in standing_order_names(orders)

    result = await _tool(tmp_path, orders).invoke({"scope": "department", "department": "leak"})

    assert result.output is None
    assert result.error == tools._STANDING_ORDERS_DENIED
    assert _MARKER_ROOT not in repr(result)
    assert reads.verified == [orders.resolve() / "leak.md"]


@pytest.mark.asyncio
async def test_a_linked_directory_is_read_through_its_resolution(
    tmp_path: Path, orders: Path, reads: _Reads
) -> None:
    """T10: a base that is itself a link is resolved first, so the read is of the real directory."""
    linked = tmp_path / "linked"
    _junction(linked, orders)
    try:
        result = await _tool(tmp_path, linked).invoke(
            {"scope": "department", "department": "engineering"}
        )
    finally:
        _unlink_junction(linked)

    assert result.error is None
    assert result.output == _ENG
    assert reads.verified == [orders.resolve() / "engineering.md"]


@pytest.mark.asyncio
async def test_the_floor_refuses_a_directory_inside_the_data_directory(tmp_path: Path) -> None:
    """T11: the BF-758 floor is wired into the lookup: the data directory's files are not returned."""
    inside = tmp_path / "data" / "orders"
    inside.mkdir(parents=True)
    (inside / "engineering.md").write_text(_ENG, encoding="utf-8")

    result = await _tool(tmp_path, inside).invoke(
        {"scope": "department", "department": "engineering"}
    )

    assert result.output is None
    assert result.error == tools._STANDING_ORDERS_DENIED
    assert _ENG not in repr(result)


@pytest.mark.asyncio
async def test_the_operator_read_policy_applies(tmp_path: Path, orders: Path) -> None:
    """T12: a read outside the operator's read roots is refused, and one inside them is admitted."""
    call = {"scope": "department", "department": "engineering"}

    refused = await _tool(tmp_path, orders, (tmp_path / "elsewhere",)).invoke(call)
    admitted = await _tool(tmp_path, orders, (tmp_path / "checkout",)).invoke(call)

    assert refused.output is None
    assert refused.error == tools._STANDING_ORDERS_DENIED
    assert _ENG not in repr(refused)
    assert admitted.error is None
    assert admitted.output == _ENG


@pytest.mark.asyncio
async def test_the_shipped_tool_reads_the_loaders_directory(tmp_path: Path) -> None:
    """T13: built as the registry builds it, with ``runtime`` alone, the tool reads the loader's directory."""
    shipped = Path(standing_orders.__file__).resolve().parents[3] / "config" / "standing_orders"
    assert standing_orders_dir() == shipped
    assert {"ship", "engineering", "builder"} <= set(standing_order_names())
    tool = StandingOrdersLookupTool(_runtime(tmp_path))

    by_default = await tool.invoke({"scope": "department"})
    ship = await tool.invoke({"scope": "ship"})

    assert by_default.error is None
    assert by_default.output == (standing_orders_dir() / "engineering.md").read_text(encoding="utf-8")
    assert ship.error is None
    assert ship.output == (standing_orders_dir() / "ship.md").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_agent_is_not_a_parameter(tmp_path: Path, orders: Path, reads: _Reads) -> None:
    """T14: ``agent`` is not a declared parameter, so it is refused by name and nothing is read."""
    result = await _tool(tmp_path, orders).invoke({"scope": "agent", "agent": "builder"})

    assert result.output is None
    assert "unknown parameter(s) agent." in result.error
    assert "Accepted: scope, department." in result.error
    assert reads.verified == []
    assert reads.plain_markdown == []


@pytest.mark.asyncio
async def test_output_matches_read_text_newlines(tmp_path: Path, orders: Path) -> None:
    """T15: a CRLF file reads back with ``\\n``, as ``Path.read_text`` gave."""
    (orders / "engineering.md").write_bytes(b"A\r\nB\r\n")
    assert (orders / "engineering.md").read_bytes() == b"A\r\nB\r\n"

    result = await _tool(tmp_path, orders).invoke({"scope": "department", "department": "engineering"})

    assert result.error is None
    assert result.output == "A\nB\n"


@pytest.mark.asyncio
async def test_a_read_failure_names_only_its_type(
    tmp_path: Path, orders: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T16: a failed read names only its exception type, and a floor refusal is the fixed text."""
    tool = _tool(tmp_path, orders)
    call = {"scope": "department", "department": "engineering"}
    failure = PermissionError(13, "denied", str(tmp_path / "secret.md"))
    assert tmp_path.name in str(failure)

    monkeypatch.setattr(tools, "read_verified_file", _raising(failure))
    failed = await tool.invoke(call)
    monkeypatch.setattr(
        tools, "read_verified_file", _raising(FileAccessDenied(str(tmp_path / "x.md"), "r"))
    )
    denied = await tool.invoke(call)

    assert failed.error == "standing_orders_lookup failed: PermissionError"
    assert denied.error == tools._STANDING_ORDERS_DENIED
    assert str(tmp_path) not in failed.error
    assert str(tmp_path) not in denied.error


@pytest.mark.asyncio
async def test_scope_refusal_is_unchanged(tmp_path: Path, orders: Path, reads: _Reads) -> None:
    """T17: the scope gate answers first, with the same text as before, whatever ``department`` holds."""
    result = await _tool(tmp_path, orders).invoke({"scope": "fleet", "department": "../secret"})

    assert result.output is None
    assert result.error == "scope must be one of ship|department|agent"
    assert reads.verified == []
    assert reads.plain_markdown == []


def test_premise_the_probes_compare_as_their_rows_say() -> None:
    """T36 (premise): each probe really equals, or raises, as T3's and T36's rows rely on."""
    assert _EqualsEmpty() == ""
    with pytest.raises(ValueError):
        operator.eq(_EqRaises(), "")
    probe = _PassesTheScopeGate()
    assert probe in tools._STANDING_ORDERS_SCOPES
    with pytest.raises(ValueError):
        operator.ne(probe, "ship")


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [pytest.param(value, id=name) for name, value in _NOT_A_STR_SCOPE])
async def test_a_scope_that_is_not_an_exact_str_is_refused(
    value: object, tmp_path: Path, orders: Path, reads: _Reads
) -> None:
    """T36: a ``scope`` that is not an exact ``str`` gets the scope refusal, before it is compared."""
    result = await _tool(tmp_path, orders).invoke({"scope": value, "department": "engineering"})

    assert result.output is None
    assert result.error == "scope must be one of ship|department|agent"
    assert reads.verified == []
    assert reads.plain_markdown == []


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["direct", "registry"])
@pytest.mark.parametrize("scope", ["department", "agent"])
@pytest.mark.parametrize(
    ("make_error", "reply", "logged"),
    [pytest.param(make, text, warned, id=name) for name, make, text, warned in _LOOKUP_FAILURES],
)
async def test_a_department_lookup_that_raises_is_answered(
    make_error: Callable[[], Exception],
    reply: str,
    logged: tuple[str, ...],
    scope: str,
    route: str,
    tmp_path: Path,
    orders: Path,
    reads: _Reads,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T37: a ``department`` lookup that raises gets a fixed reply, directly and through the registry."""
    warnings = _Warnings()
    monkeypatch.setattr(tools, "logger", warnings)
    params = _GetRaises({"scope": scope, "department": "engineering"}, make_error())

    result, escaped = await _contained(_send(route, _tool(tmp_path, orders), params))

    assert escaped is None
    assert result is not None
    assert result.output is None
    assert result.error == reply
    assert _MARKER_GET not in result.error
    assert tuple(warnings.messages) == logged
    assert params.department_lookups == 1
    assert reads.verified == []
    assert reads.plain_markdown == []


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["direct", "registry"])
async def test_ship_does_not_look_up_department(
    route: str, tmp_path: Path, orders: Path, reads: _Reads
) -> None:
    """T37b: the ``ship`` scope never asks the mapping for ``department``, and reads ``ship``."""
    params = _GetRaises({"scope": "ship", "department": "engineering"}, RuntimeError(_MARKER_GET))

    result, escaped = await _contained(_send(route, _tool(tmp_path, orders), params))

    assert escaped is None
    assert result is not None
    assert result.error is None
    assert result.output == _SHIP
    assert params.department_lookups == 0
    assert reads.verified == [orders.resolve() / "ship.md"]


def test_premise_the_failure_probes_run_their_own_code() -> None:
    """T38 (premise): each probe's class name runs the probe's code where a plain class's does not."""
    with pytest.raises(RuntimeError, match="the class name was read"):
        _ = type(_metaclass_named_failure()).__name__
    renamed = type(_renamed_failure()).__name__
    assert isinstance(renamed, str)
    assert type(renamed) is not str
    with pytest.raises(RuntimeError, match="the class name was formatted"):
        format(renamed, "")
    assert type(type(RuntimeError()).__name__) is str


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "make_error",
    [
        pytest.param(_metaclass_named_failure, id="metaclass-name-raises"),
        pytest.param(_renamed_failure, id="name-format-raises"),
    ],
)
async def test_a_failure_is_named_without_its_class_code(
    make_error: Callable[[], Exception],
    tmp_path: Path,
    orders: Path,
    reads: _Reads,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T38: the failure reply names the type with none of its class's or metaclass's code, else ``Exception``."""
    warnings = _Warnings()
    monkeypatch.setattr(tools, "logger", warnings)
    params = _GetRaises({"scope": "department", "department": "engineering"}, make_error())

    result, escaped = await _contained(_tool(tmp_path, orders).invoke(params))

    assert escaped is None
    assert result is not None
    assert result.error == "standing_orders_lookup failed: Exception"
    assert warnings.messages == ["BF-910: standing_orders_lookup failed: Exception"]
    assert params.department_lookups == 1
    assert reads.verified == []


@pytest.mark.asyncio
async def test_every_read_stays_in_the_base(
    tmp_path: Path, orders: Path, markers: tuple[Path, Path], reads: _Reads
) -> None:
    """T18: across the inputs of T2 to T8, in both scopes, every read is of a file directly in the base.

    D10's behavioural guard: no source scan, but a check of what was actually
    read, and that no ``.md`` file was ever read with ``Path.read_text``.
    """
    tool = _tool(tmp_path, orders)
    values = [
        *(_spell(value, tmp_path) for _, value in _NOT_ONE_NAME),
        *(value for _, value in _NOT_A_STR),
        "engineering",
        "science",
        "builder",
        *_UNKNOWN_NAMES,
        *_WRONG_CASE_NAMES,
        *_DEVICE_NAMES,
    ]
    calls: list[dict[str, object]] = [{"scope": "ship"}, {"scope": "ship", "department": "../secret"}]
    for scope in ("department", "agent"):
        calls += [{"scope": scope, "department": value} for value in values]
        calls += [{"scope": scope, **params} for _, params in _NO_VALUE]

    for call in calls:
        await tool.invoke(call)

    assert reads.verified, "no verified read happened, so the check below would prove nothing"
    assert all(path.parent == orders.resolve() for path in reads.verified)
    assert reads.plain_markdown == []


def test_standing_order_names_lists_only_selectable_stems(tmp_path: Path) -> None:
    """T19: only a ``<name>.md`` directly in the directory, whose stem is a name, is listed."""
    orders_dir = tmp_path / "orders"
    orders_dir.mkdir()
    files = ("a.md", "b-c_d.md", "notes.txt", "dotted.name.md", "UPPER.MD", "sp ace.md")
    for filename in files:
        (orders_dir / filename).write_text("x", encoding="utf-8")
    (orders_dir / "crew_profiles").mkdir()
    # Premise: every entry the listing must leave out is really there, so a
    # missing name is the filter at work and not an absent file.
    assert {entry.name for entry in orders_dir.iterdir()} == {*files, "crew_profiles"}

    assert standing_order_names(orders_dir) == ("a", "b-c_d")

    absent = tmp_path / "absent"
    assert not absent.exists()
    assert standing_order_names(absent) == ()


def test_standing_order_names_are_returned_in_name_order(tmp_path: Path) -> None:
    """T19b: the names come back in plain code-point order, which is the order ``sorted`` gives.

    That order differs from a case-insensitive listing, the order NTFS returns
    (``0 a B m Z _x``), so on such a filesystem only a sort can produce it.
    """
    orders_dir = tmp_path / "orders"
    orders_dir.mkdir()
    files = ("Z.md", "a.md", "m.md", "B.md", "0.md", "_x.md")
    for filename in files:
        (orders_dir / filename).write_text("x", encoding="utf-8")
    # Premise: all six files are really there, so the order below is the listing's
    # own and not a shorter list that happens to be in order.
    assert {entry.name for entry in orders_dir.iterdir()} == set(files)

    assert standing_order_names(orders_dir) == ("0", "B", "Z", "_x", "a", "m")


def test_name_shape_boundaries() -> None:
    """T20: the longest name passes; one past it, an empty or a non-exact ``str`` value does not."""
    assert is_standing_order_name("x" * 64) is True
    refused = (
        "x" * 65,  # one past the longest name
        "",  # empty
        _Str("a"),  # a str subclass is not an exact str
        None,  # not a str at all
        "a.b",  # a dot never belongs to a name
        "a\n",  # a trailing newline: the shape must fullmatch, not match
    )
    for value in refused:
        assert is_standing_order_name(value) is False, repr(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [pytest.param(value, id=name) for name, value in _NOT_ONE_NAME])
async def test_adapter_refuses_a_name_that_is_not_one_segment(
    value: object,
    tmp_path: Path,
    orders: Path,
    markers: tuple[Path, Path],
    adapter_reads: _Reads,
) -> None:
    """T21: a value that is not one name gets the adapter's fixed refusal, before any file is touched."""
    spelled = _spell(value, tmp_path)

    reply = await _ask(_adapter(tmp_path, orders), {"department": spelled})

    assert reply == copilot_adapter._STANDING_ORDERS_NAME_REFUSAL
    assert spelled not in reply
    assert "MARKER-BF910" not in reply
    assert adapter_reads.verified == []
    assert adapter_reads.plain_markdown == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value", [pytest.param(value, id=name) for name, value in _TRUTHY_NOT_A_STR]
)
async def test_adapter_refuses_a_truthy_non_string(
    value: object, tmp_path: Path, orders: Path, adapter_reads: _Reads
) -> None:
    """T22: a truthy value that is not an exact ``str``, a ``str`` subclass included, gets the same refusal."""
    reply = await _ask(_adapter(tmp_path, orders), {"department": value})

    assert reply == copilot_adapter._STANDING_ORDERS_NAME_REFUSAL
    assert adapter_reads.verified == []
    assert adapter_reads.plain_markdown == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments", [pytest.param(arguments, id=name) for name, arguments in _FALSY_DEPARTMENT]
)
async def test_adapter_falsy_department_is_unspecified(
    arguments: dict[str, object], tmp_path: Path, orders: Path, adapter_reads: _Reads
) -> None:
    """T23: a falsy ``department``, or none, still answers ``No department specified``, and nothing is read."""
    reply = await _ask(_adapter(tmp_path, orders), arguments)

    assert reply == _ADAPTER_UNSPECIFIED
    assert adapter_reads.verified == []
    assert adapter_reads.plain_markdown == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "expected"), [pytest.param(name, text, id=name) for name, text in _ADAPTER_REAL_NAMES]
)
async def test_adapter_real_names_resolve(
    name: str, expected: str, tmp_path: Path, orders: Path, adapter_reads: _Reads
) -> None:
    """T24: a name that exists is read, once, from directly inside the resolved base."""
    reply = await _ask(_adapter(tmp_path, orders), {"department": name})

    assert reply == expected
    assert adapter_reads.verified == [orders.resolve() / f"{name}.md"]
    assert adapter_reads.plain_markdown == []


@pytest.mark.asyncio
@pytest.mark.parametrize("value", _ADAPTER_NOT_FOUND_NAMES)
async def test_adapter_unknown_case_and_device_names_are_not_found(
    value: str, tmp_path: Path, orders: Path, adapter_reads: _Reads
) -> None:
    """T25: an unlisted name, a directory, the wrong case or a device name is not found, and not echoed."""
    reply = await _ask(_adapter(tmp_path, orders), {"department": value})

    assert reply == _ADAPTER_NOT_FOUND
    assert value not in reply
    assert adapter_reads.verified == []
    assert adapter_reads.plain_markdown == []


@pytest.mark.asyncio
async def test_adapter_missing_directory_has_no_names(tmp_path: Path, adapter_reads: _Reads) -> None:
    """T26: with no directory there are no names, so the reply lists none and nothing is read."""
    absent = tmp_path / "absent"
    assert not absent.exists()

    reply = await _ask(_adapter(tmp_path, absent), {"department": "engineering"})

    assert reply.endswith("available: none")
    assert adapter_reads.verified == []
    assert adapter_reads.plain_markdown == []


@pytest.mark.asyncio
async def test_adapter_link_in_directory_is_refused(
    tmp_path: Path, orders: Path, markers: tuple[Path, Path], adapter_reads: _Reads
) -> None:
    """T27: a listed name whose file is a link out of the directory is refused by the verified read."""
    _, root_marker = markers
    try:
        (orders / "leak.md").symlink_to(root_marker)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation requires privilege on this host")
    assert "leak" in standing_order_names(orders)

    reply = await _ask(_adapter(tmp_path, orders), {"department": "leak"})

    assert reply == copilot_adapter._STANDING_ORDERS_DENIED
    assert _MARKER_ROOT not in reply
    assert adapter_reads.verified == [orders.resolve() / "leak.md"]


@pytest.mark.asyncio
async def test_adapter_linked_directory_is_read_through_its_resolution(
    tmp_path: Path, orders: Path, adapter_reads: _Reads
) -> None:
    """T28: a base that is itself a link is resolved first, so the read is of the real directory."""
    linked = tmp_path / "linked"
    _junction(linked, orders)
    try:
        reply = await _ask(_adapter(tmp_path, linked), {"department": "engineering"})
    finally:
        _unlink_junction(linked)

    assert reply == _ENG
    assert adapter_reads.verified == [orders.resolve() / "engineering.md"]


@pytest.mark.asyncio
async def test_adapter_floor_refuses_data_dir(tmp_path: Path) -> None:
    """T29: the BF-758 floor is wired into the handler: the data directory's files are not returned."""
    inside = tmp_path / "data" / "orders"
    inside.mkdir(parents=True)
    (inside / "engineering.md").write_text(_ENG, encoding="utf-8")

    reply = await _ask(_adapter(tmp_path, inside), {"department": "engineering"})

    assert reply == copilot_adapter._STANDING_ORDERS_DENIED
    assert _ENG not in reply


@pytest.mark.asyncio
async def test_adapter_operator_read_policy_applies(tmp_path: Path, orders: Path) -> None:
    """T30: a read outside the operator's read roots is refused, and one inside them is admitted."""
    arguments = {"department": "engineering"}

    refused = await _ask(_adapter(tmp_path, orders, (tmp_path / "elsewhere",)), arguments)
    admitted = await _ask(_adapter(tmp_path, orders, (tmp_path / "checkout",)), arguments)

    assert refused == copilot_adapter._STANDING_ORDERS_DENIED
    assert _ENG not in refused
    assert admitted == _ENG


@pytest.mark.asyncio
async def test_adapter_read_failure_names_only_its_type(
    tmp_path: Path, orders: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T31: a failed read names only its exception type, and a floor refusal is the fixed text."""
    adapter = _adapter(tmp_path, orders)
    arguments = {"department": "engineering"}
    failure = PermissionError(13, "denied", str(tmp_path / "secret.md"))
    assert tmp_path.name in str(failure)

    monkeypatch.setattr(copilot_adapter, "read_verified_file", _raising(failure))
    failed = await _ask(adapter, arguments)
    monkeypatch.setattr(
        copilot_adapter, "read_verified_file", _raising(FileAccessDenied(str(tmp_path / "x.md"), "r"))
    )
    denied = await _ask(adapter, arguments)

    assert failed == "standing_orders_lookup failed: PermissionError"
    assert denied == copilot_adapter._STANDING_ORDERS_DENIED
    assert str(tmp_path) not in failed
    assert str(tmp_path) not in denied


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "expected"),
    [
        pytest.param(b"A\r\nB\r\n", "A\nB\n", id="crlf-as-lf"),
        pytest.param(b"A\xff", "A\ufffd", id="invalid-byte-as-replacement"),
    ],
)
async def test_adapter_output_parity(
    data: bytes, expected: str, tmp_path: Path, orders: Path
) -> None:
    """T32: the reply is ``Path.read_text(encoding="utf-8", errors="replace")``'s text, as it was before."""
    path = orders / "engineering.md"
    path.write_bytes(data)
    # Premise: the file holds the bytes, and the text the handler used to return for them is the expected one.
    assert path.read_bytes() == data
    assert path.read_text(encoding="utf-8", errors="replace") == expected

    reply = await _ask(_adapter(tmp_path, orders), {"department": "engineering"})

    assert reply == expected


@pytest.mark.asyncio
async def test_adapter_shipped_construction_reads_the_loaders_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T33: built as the dispatcher builds it, with no runtime and no ``orders_dir``, it reads the loader's directory."""
    # With no runtime the floor falls back to the platform data directory: point it into tmp_path,
    # so that no live data directory is consulted.
    monkeypatch.setenv("PROBOS_DATA_DIR", str(tmp_path / "data"))
    # A decoy checkout root whose config/standing_orders holds other text: a handler that read
    # _PROJECT_ROOT's directory rather than the loader's would answer with the decoy (row 35).
    decoy_marker = "MARKER-BF910-DECOY"
    decoy_orders = tmp_path / "decoy" / "config" / "standing_orders"
    decoy_orders.mkdir(parents=True)
    (decoy_orders / "engineering.md").write_text(decoy_marker, encoding="utf-8")
    monkeypatch.setattr(copilot_adapter, "_PROJECT_ROOT", tmp_path / "decoy")
    expected = (standing_orders_dir() / "engineering.md").read_text(encoding="utf-8", errors="replace")
    assert expected
    assert decoy_marker not in expected

    reply = await _ask(CopilotBuilderAdapter(), {"department": "engineering"})

    assert reply == expected


@pytest.mark.asyncio
async def test_adapter_every_read_stays_in_the_base(
    tmp_path: Path, orders: Path, markers: tuple[Path, Path], adapter_reads: _Reads
) -> None:
    """T34: across the inputs of T21 to T25, every verified read is of a file directly in the base.

    D10's behavioural guard, for the adapter: a check of what was actually read,
    and that no ``.md`` file was ever read with ``Path.read_text``.
    """
    adapter = _adapter(tmp_path, orders)
    values = [
        *(_spell(value, tmp_path) for _, value in _NOT_ONE_NAME),
        *(value for _, value in _TRUTHY_NOT_A_STR),
        *(name for name, _ in _ADAPTER_REAL_NAMES),
        *_ADAPTER_NOT_FOUND_NAMES,
    ]
    calls = [{"department": value} for value in values]
    calls += [arguments for _, arguments in _FALSY_DEPARTMENT]

    for arguments in calls:
        await _ask(adapter, arguments)

    assert adapter_reads.verified, "no verified read happened, so the check below would prove nothing"
    assert all(path.parent == orders.resolve() for path in adapter_reads.verified)
    assert adapter_reads.plain_markdown == []


@pytest.mark.asyncio
async def test_adapter_registered_handler_is_the_guarded_one(
    tmp_path: Path, orders: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T35: the handler ``_build_mcp_tools`` registers as ``standing_orders_lookup`` is the guarded one.

    Crosses registration to handler: the callable the visiting session is given
    refuses a path with the fixed text and returns a listed name's file.
    """
    registered: list[dict[str, Any]] = []

    def tool(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert not args, "the adapter registers its tools by keyword"
        registered.append(kwargs)
        return kwargs

    monkeypatch.setattr(copilot_adapter, "_SDK_AVAILABLE", True)
    monkeypatch.setattr(copilot_adapter, "Tool", tool, raising=False)
    adapter = _adapter(tmp_path, orders)

    adapter._build_mcp_tools()
    handlers = [kwargs["handler"] for kwargs in registered if kwargs.get("name") == "standing_orders_lookup"]
    assert len(handlers) == 1
    handler = handlers[0]

    refused = await handler(SimpleNamespace(arguments={"department": "../secret"}))
    found = await handler(SimpleNamespace(arguments={"department": "engineering"}))

    assert refused.text_result_for_llm == copilot_adapter._STANDING_ORDERS_NAME_REFUSAL
    assert found.text_result_for_llm == _ENG
