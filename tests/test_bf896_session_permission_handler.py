"""BF-896 (#1550) M1: the visiting build session's permission policy, its seeding and its wiring.

The queued visiting build used to run its SDK session in the build's real worktree under the SDK's approve-all
handler. The session now runs in its own directory under ``build_session_permission_handler`` (deny by default).
These tests drive the real handler through both SDK request shapes (the 0.1.32 dataclass with an ``Enum`` kind, the
0.1.30 wire dict with a ``str`` kind), the real seeding helper, and the real adapter on a fake SDK client (the AD-1200
pattern).

Every denial is paired with approvals asserted FIRST in the same handler: a handler that denied everything would fail
here, not pass. Setups that must discriminate (a sibling directory, a link, a relative directory) assert their premise.
Windows-only forms (``C:foo``, ``GIT~1``, ``NUL``, ``con.py``) are refused lexically on every platform; symlink,
junction and 8.3 cases skip where the platform or account cannot create them.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any, Callable

import pytest

from probos.cognitive import copilot_adapter as sdk
from probos.cognitive.builder import BuildResult, BuilderAgent, BuildSpec, execute_approved_build
from probos.cognitive.copilot_adapter import (
    build_session_permission_handler,
    seed_session_directory,
)


# ── Permission-request fakes ───────────────────────────────────────────────


class _Kind(Enum):
    """The 0.1.32 request kind: a real Enum, never a str."""

    WRITE = "write"
    READ = "read"
    SHELL = "shell"
    URL = "url"
    MCP = "mcp"
    MEMORY = "memory"
    CUSTOM_TOOL = "custom-tool"
    FROBNICATE = "frobnicate"  # a kind the handler has never heard of (a newer SDK's addition)


class _OddKind(Enum):
    ODD = 3  # an Enum whose value is not a str


class _LyingStr(str):
    """A str subclass that equals the good value; the handler accepts exact ``str`` only."""


@dataclass
class _Request:
    """The 0.1.32 request shape: attributes, snake_case, an Enum kind."""

    kind: Any = None
    file_name: Any = None
    path: Any = None
    possible_paths: Any = None
    tool_name: Any = None
    full_command_text: Any = None


_TOOLS = ("standing_orders_lookup", "codebase_query")
# logical field -> (0.1.32 attribute, 0.1.30 wire key)
_FIELDS = {
    "file": ("file_name", "fileName"),
    "path": ("path", "path"),
    "possible": ("possible_paths", "possiblePaths"),
    "tool": ("tool_name", "toolName"),
    "command": ("full_command_text", "fullCommandText"),
}


def _make(shape: str, kind: Any, **fields: Any) -> Any:
    """One permission request in either SDK shape. A *kind* of None means the kind is missing."""
    if shape == "dataclass":
        if type(kind) is str:
            try:
                kind = _Kind(kind)
            except ValueError:
                pass  # not a kind the Enum names: the request carries the raw value
        return _Request(kind=kind, **{_FIELDS[name][0]: value for name, value in fields.items()})
    wire = {_FIELDS[name][1]: value for name, value in fields.items()}
    if kind is not None:
        wire["kind"] = kind
    return wire


def _kind_of(result: Any) -> Any:
    """The verdict's kind from either result shape (a dict in 0.1.30, a dataclass in 0.1.32)."""
    return result["kind"] if isinstance(result, dict) else result.kind


def _inside(path: str | Path, root: str | Path) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(str(path)), os.path.normcase(str(root))]) == os.path.normcase(str(root))
    except ValueError:
        return False


@dataclass
class _Session:
    root: Path
    outside: Path
    handler: Callable[..., Any]

    def ask(self, request: Any) -> Any:
        return self.handler(request, {"session_id": "bf896-fixture"})


def _resolve(value: Any, session: _Session) -> Any:
    """Fill a table entry: a callable builds a session-relative value, containers are filled recursively."""
    if callable(value):
        return value(session)
    if isinstance(value, list):
        return [_resolve(item, session) for item in value]
    if isinstance(value, tuple):
        return tuple(_resolve(item, session) for item in value)
    if isinstance(value, dict):
        return {key: _resolve(item, session) for key, item in value.items()}
    return value


@pytest.fixture(params=["dataclass", "wire-dict"])
def shape(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def session(tmp_path: Path) -> _Session:
    root = tmp_path / "session"
    root.mkdir()
    seeded = seed_session_directory(
        str(root), {"src/x.py": "x = 1\n", "pyproject.toml": "[project]\nname = 'fixture'\n"},
    )
    # Premise: a seeded reference file (pyproject.toml) and a seeded target really exist in the session directory.
    assert sorted(seeded) == ["pyproject.toml", "src/x.py"]
    assert (root / "pyproject.toml").is_file() and (root / "src" / "x.py").is_file()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.py").write_text("outside = 1\n", encoding="utf-8")
    (tmp_path / "session_evil").mkdir()  # the sibling a prefix comparison would wrongly accept
    return _Session(root=root, outside=outside, handler=build_session_permission_handler(str(root), _TOOLS))


def _assert_controls_are_approved(session: _Session, shape: str) -> None:
    """The handler is live: what it should approve, it approves (asserted before any denial)."""
    for kind, fields in (
        ("write", {"file": "src/ok.py"}),
        ("read", {"path": "src/x.py"}),
        ("custom-tool", {"tool": "standing_orders_lookup"}),
    ):
        result = session.ask(_make(shape, kind, **fields))
        assert _kind_of(result) == "approved", f"control {kind} {fields} was not approved in the {shape} shape: {result!r}"


# ── Handler: approvals ─────────────────────────────────────────────────────

_APPROVALS = [
    pytest.param("write", {"file": "src/x.py"}, id="relative-write"),
    pytest.param("write", {"file": lambda s: str(s.root / "src" / "y.py")}, id="absolute-write-inside"),
    pytest.param("write", {"file": "src/probos/newpkg/deeper/mod.py"}, id="write-in-a-new-subdirectory"),
    pytest.param("read", {"path": "src/x.py"}, id="read-inside"),
    pytest.param("read", {"path": "pyproject.toml"}, id="read-of-a-seeded-pyproject"),
    pytest.param("custom-tool", {"tool": "standing_orders_lookup"}, id="registered-tool-standing-orders-lookup"),
    pytest.param("custom-tool", {"tool": "codebase_query"}, id="another-registered-tool"),
    pytest.param("write", {"file": "tests/test_new.py"}, id="write-a-test-file"),
    pytest.param("write", {"file": "top-level.py"}, id="write-at-the-session-root"),
    pytest.param(
        "write", {"file": "src/a.py", "possible": ["src/a.py", lambda s: str(s.root / "tests" / "b.py")]},
        id="write-with-every-possible-path-inside",
    ),
    pytest.param("write", {"file": "src/a.py", "possible": ("src/a.py",)}, id="write-with-possible-paths-as-a-tuple"),
    pytest.param("read", {"path": "src/x.py", "possible": ["src/x.py", "pyproject.toml"]}, id="read-with-possible-paths-inside"),
    pytest.param(
        "write", {"file": "src\\win.py"}, id="write-with-backslash-separators",
        marks=pytest.mark.skipif(os.name != "nt", reason="a backslash separates components only on Windows"),
    ),
]


@pytest.mark.parametrize("kind, fields", _APPROVALS)
def test_handler_approves(session: _Session, shape: str, kind: str, fields: dict[str, Any]) -> None:
    result = session.ask(_make(shape, kind, **_resolve(fields, session)))
    assert _kind_of(result) == "approved", f"{kind} {fields!r} in the {shape} shape: {result!r}"


def test_handler_accepts_the_request_alone_and_with_an_invocation(session: _Session) -> None:
    request = _make("dataclass", "write", file="src/ok.py")
    assert _kind_of(session.handler(request)) == "approved"
    assert _kind_of(session.handler(request, {"session_id": "s1"})) == "approved"
    refused = _make("dataclass", "shell", command="ls")
    assert _kind_of(session.handler(refused)) == "denied-by-rules"
    assert _kind_of(session.handler(refused, {"session_id": "s1"})) == "denied-by-rules"


# ── Handler: denials ───────────────────────────────────────────────────────

# Denied for a write AND for a read: strictly-inside is the rule for both.
_SHARED_PATH_DENIALS = [
    ("parent-traversal", lambda s: "../x"),
    ("nested-traversal", lambda s: "src/../../x"),
    ("bare-parent", lambda s: ".."),
    ("dotdot-that-stays-inside", lambda s: "src/../src/x.py"),
    ("absolute-outside", lambda s: str(s.outside / "x.py")),
    ("rooted-outside", lambda s: "/outside-root/x.py"),
    ("sibling-prefix", lambda s: str(s.root) + "_evil" + os.sep + "x"),
    ("ntfs-stream", lambda s: "src/a.py:stream"),
    ("drive-relative", lambda s: "C:foo"),
    ("nul-byte", lambda s: "src/x\x00.py"),
    ("bytes", lambda s: b"src/x.py"),
    ("int", lambda s: 5),
    ("str-subclass", lambda s: _LyingStr("src/x.py")),
    ("empty-string", lambda s: ""),
    ("the-root-as-dot", lambda s: "."),
    ("the-root-itself", lambda s: str(s.root)),
]
# Denied for a write only: the executor's own lexical rules (builder_write_refusal), applied earlier.
_WRITE_ONLY_DENIALS = [
    ("git-config", lambda s: ".git/config"),
    ("git-alias-mixed-case", lambda s: ".GiT/hooks/pre-commit"),
    ("github-workflow", lambda s: ".github/x.yml"),
    ("pyproject", lambda s: "pyproject.toml"),
    ("dot-env", lambda s: ".env"),
    ("short-name-8.3", lambda s: "GIT~1/config"),
    ("device-nul", lambda s: "NUL"),
    ("device-con-with-extension", lambda s: "con.py"),
    ("unc-path", lambda s: "\\\\server\\share\\x.py"),
    ("rooted-backslash", lambda s: "\\x.py"),
    ("outside-the-allowed-directories", lambda s: "scripts/run.py"),
    ("option-shaped", lambda s: "-rf"),
]
_KIND_DENIALS = [
    pytest.param("shell", {"command": "git push --force origin main"}, None, id="shell"),
    pytest.param(
        "shell", {"command": "cat src/x.py", "file": "src/x.py", "possible": ["src/x.py"]}, "write",
        id="shell-naming-only-inside-paths",
    ),
    pytest.param("url", {}, None, id="url"),
    pytest.param("url", {"path": "src/x.py"}, "read", id="url-with-an-inside-path"),
    pytest.param("mcp", {}, None, id="mcp"),
    pytest.param("mcp", {"tool": "standing_orders_lookup"}, "custom-tool", id="mcp-naming-a-registered-tool"),
    pytest.param("memory", {}, None, id="memory"),
    pytest.param("memory", {"path": "src/x.py"}, "read", id="memory-with-an-inside-path"),
    pytest.param("frobnicate", {"path": "src/x.py"}, "read", id="unknown-kind"),
    pytest.param(None, {"file": "src/x.py"}, "write", id="missing-kind"),
    pytest.param(3, {"file": "src/x.py"}, "write", id="int-kind"),
    pytest.param("WRITE", {"file": "src/x.py"}, "write", id="upper-case-kind"),
    pytest.param("write ", {"file": "src/x.py"}, "write", id="padded-kind"),
    pytest.param(b"write", {"file": "src/x.py"}, "write", id="bytes-kind"),
    pytest.param(_LyingStr("write"), {"file": "src/x.py"}, "write", id="str-subclass-kind"),
    pytest.param(_OddKind.ODD, {"file": "src/x.py"}, "write", id="enum-with-a-non-str-value"),
]
_TOOL_DENIALS: list[tuple[str, dict[str, Any]]] = [
    ("unregistered-name", {"tool": "shell_exec"}),
    ("padded-name", {"tool": "standing_orders_lookup "}),
    ("upper-case-name", {"tool": "STANDING_ORDERS_LOOKUP"}),
    ("empty-name", {"tool": ""}),
    ("int-name", {"tool": 5}),
    ("bytes-name", {"tool": b"standing_orders_lookup"}),
    ("list-name", {"tool": ["standing_orders_lookup"]}),
    ("str-subclass-name", {"tool": _LyingStr("standing_orders_lookup")}),
    ("none-name", {"tool": None}),
    ("no-name", {}),
]


def _denial_rows() -> list[Any]:
    rows: list[Any] = list(_KIND_DENIALS)
    for name, make in _SHARED_PATH_DENIALS:
        rows.append(pytest.param("write", {"file": make}, None, id=f"write-{name}"))
        rows.append(pytest.param("read", {"path": make}, None, id=f"read-{name}"))
    for name, make in _WRITE_ONLY_DENIALS:
        rows.append(pytest.param("write", {"file": make}, None, id=f"write-{name}"))
    for name, fields in _TOOL_DENIALS:
        rows.append(pytest.param("custom-tool", fields, None, id=f"custom-tool-{name}"))
    outside = lambda s: str(s.outside / "x.py")  # noqa: E731 - a table helper, filled per session
    rows += [
        # No named target at all is no authority: a request must name something strictly inside.
        pytest.param("write", {}, None, id="write-with-no-path-field"),
        pytest.param("read", {}, None, id="read-with-no-path-field"),
        pytest.param("write", {"file": None}, None, id="write-with-a-none-path"),
        pytest.param("write", {"possible": []}, None, id="write-with-only-an-empty-possible-paths"),
        # Every possible path is a named target, and possible_paths must be a list or tuple.
        pytest.param("write", {"file": "src/ok.py", "possible": ["src/ok.py", outside]}, None, id="write-with-one-possible-path-outside"),
        pytest.param("read", {"path": "src/x.py", "possible": ["src/x.py", outside]}, None, id="read-with-one-possible-path-outside"),
        pytest.param("write", {"file": "src/ok.py", "possible": "src/ok.py"}, None, id="write-with-possible-paths-as-a-str"),
        pytest.param("write", {"file": "src/ok.py", "possible": {"src/ok.py"}}, None, id="write-with-possible-paths-as-a-set"),
        pytest.param("write", {"file": "src/ok.py", "possible": {"src/ok.py": 1}}, None, id="write-with-possible-paths-as-a-dict"),
        pytest.param("write", {"file": "src/ok.py", "possible": 5}, None, id="write-with-possible-paths-as-an-int"),
    ]
    return rows


@pytest.mark.parametrize("kind, fields, control_kind", _denial_rows())
def test_handler_denies(
    session: _Session, shape: str, kind: Any, fields: dict[str, Any], control_kind: str | None,
) -> None:
    _assert_controls_are_approved(session, shape)
    resolved = _resolve(fields, session)
    if control_kind is not None:
        # The same payload under an approved kind is approved: only the varied element makes this request denied.
        twin = session.ask(_make(shape, control_kind, **resolved))
        assert _kind_of(twin) == "approved", f"twin {control_kind} {fields!r} was not approved: {twin!r}"
    result = session.ask(_make(shape, kind, **resolved))
    assert _kind_of(result) == "denied-by-rules", f"{kind!r} {fields!r} in the {shape} shape: {result!r}"


def test_the_denial_fixtures_discriminate(session: _Session) -> None:
    root = str(session.root)
    evil = root + "_evil" + os.sep + "x"
    # A prefix comparison would approve the sibling: it starts with the session path and exists beside it.
    assert evil.startswith(root) and os.path.isdir(root + "_evil") and not _inside(evil, root)
    # The traversals are real escapes, and the ".." that stays inside leaves only the lexical rule to refuse it.
    assert not _inside(os.path.realpath(os.path.join(root, "src/../../x")), root)
    assert not _inside(os.path.realpath(os.path.join(root, "..")), root)
    assert _inside(os.path.realpath(os.path.join(root, "src/../src/x.py")), root)
    assert not _inside(os.path.realpath(str(session.outside / "x.py")), root) and (session.outside / "x.py").is_file()
    # The str subclass would pass an isinstance check and compares equal to the good value.
    assert _LyingStr("write") == "write" and isinstance(_LyingStr("write"), str) and type(_LyingStr("write")) is not str
    assert _OddKind.ODD.value == 3 and _Kind.WRITE.value == "write"
    # pyproject.toml is seeded, so its read approval and its write denial are tested against a file that exists.
    assert (session.root / "pyproject.toml").is_file()


def test_handler_denies_when_any_named_target_is_outside(session: _Session) -> None:
    outside = str(session.outside / "x.py")
    pairs: list[tuple[str, Any, Any]] = [
        (
            "dataclass file_name and path",
            _Request(kind=_Kind.WRITE, file_name="src/ok.py", path="src/ok.py"),
            _Request(kind=_Kind.WRITE, file_name="src/ok.py", path=outside),
        ),
        (
            "dict fileName and path",
            {"kind": "write", "fileName": "src/ok.py", "path": "src/ok.py"},
            {"kind": "write", "fileName": "src/ok.py", "path": outside},
        ),
        (
            "dict camelCase beside snake_case",
            {"kind": "write", "fileName": "src/ok.py", "file_name": "src/ok2.py"},
            {"kind": "write", "fileName": "src/ok.py", "file_name": outside},
        ),
        (
            "dict possiblePaths beside possible_paths",
            {"kind": "write", "fileName": "src/ok.py", "possiblePaths": ["src/ok.py"], "possible_paths": ["src/ok2.py"]},
            {"kind": "write", "fileName": "src/ok.py", "possiblePaths": ["src/ok.py"], "possible_paths": ["src/ok2.py", outside]},
        ),
        (
            "dataclass read with possible_paths",
            _Request(kind=_Kind.READ, path="src/x.py", possible_paths=["src/x.py"]),
            _Request(kind=_Kind.READ, path="src/x.py", possible_paths=["src/x.py", outside]),
        ),
        (
            "dict custom-tool names",
            {"kind": "custom-tool", "toolName": "standing_orders_lookup", "tool_name": "codebase_query"},
            {"kind": "custom-tool", "toolName": "standing_orders_lookup", "tool_name": "shell_exec"},
        ),
        (
            "possible_paths that is a set",
            _Request(kind=_Kind.WRITE, file_name="src/ok.py", possible_paths=["src/ok.py"]),
            _Request(kind=_Kind.WRITE, file_name="src/ok.py", possible_paths={"src/ok.py"}),
        ),
        (
            "possiblePaths that is a plain string",
            {"kind": "write", "fileName": "src/ok.py", "possiblePaths": ["src/ok.py"]},
            {"kind": "write", "fileName": "src/ok.py", "possiblePaths": "src/ok.py"},
        ),
        (
            "possible_paths that is a dict",
            _Request(kind=_Kind.READ, path="src/x.py", possible_paths=["src/x.py"]),
            _Request(kind=_Kind.READ, path="src/x.py", possible_paths={"src/x.py": 1}),
        ),
    ]
    for label, good, bad in pairs:
        assert _kind_of(session.ask(good)) == "approved", f"control for {label} was not approved"
    for label, good, bad in pairs:
        assert _kind_of(session.ask(bad)) == "denied-by-rules", f"{label}: a request naming a target outside was approved"


def test_handler_logs_the_denied_kind_and_never_the_request_payload(
    session: _Session, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="probos.cognitive.copilot_adapter")
    secret = "SECRET-TOKEN-4f9a1c"
    assert _kind_of(session.ask(_make("dataclass", "write", file="src/ok.py"))) == "approved"
    assert not [r for r in caplog.records if "denied" in r.getMessage()]  # an approval logs no denial
    shell = _make("dataclass", "shell", command=f"curl -H 'Authorization: {secret}' https://example.invalid/")
    assert _kind_of(session.ask(shell)) == "denied-by-rules"
    assert _kind_of(session.ask(_make("wire-dict", "write", file=f"../{secret}"))) == "denied-by-rules"
    messages = [r.getMessage() for r in caplog.records if "denied" in r.getMessage()]
    assert any("shell" in m for m in messages) and any("write" in m for m in messages)
    assert secret not in caplog.text


# ── Handler: links, 8.3 names, relative and unusable session directories ───


def _make_link(kind: str, link: Path, target: Path) -> None:
    """Create a link at *link* to *target*, or skip when this platform or account cannot."""
    try:
        if kind == "junction":
            if os.name != "nt":
                pytest.skip("directory junctions exist only on Windows")
            done = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True, check=False,
            )
            if done.returncode != 0:
                pytest.skip(f"cannot create a junction here: {(done.stderr or done.stdout).strip()}")
        else:
            os.symlink(target, link, target_is_directory=(kind == "dir-symlink"))
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create a {kind} on this platform or account: {exc}")


@pytest.mark.parametrize("link_kind", ["dir-symlink", "file-symlink", "junction"])
def test_handler_denies_a_link_that_leaves_the_session_and_approves_one_that_stays(
    session: _Session, shape: str, link_kind: str,
) -> None:
    src = session.root / "src"
    inner = src / "real"
    inner.mkdir(parents=True)
    (inner / "y.py").write_text("y = 1\n", encoding="utf-8")
    if link_kind == "file-symlink":
        stays, leaves = src / "alias_in.py", src / "alias_out.py"
        stays_target, leaves_target = src / "x.py", session.outside / "x.py"
        stays_request, leaves_request = "src/alias_in.py", "src/alias_out.py"
    else:
        stays, leaves = src / "link_in", src / "link_out"
        stays_target, leaves_target = inner, session.outside
        stays_request, leaves_request = "src/link_in/new.py", "src/link_out/new.py"
    made: list[Path] = []
    try:
        _make_link(link_kind, stays, stays_target)
        made.append(stays)
        _make_link(link_kind, leaves, leaves_target)
        made.append(leaves)
        # Premises: the link that leaves really resolves outside the session, the one that stays resolves inside.
        assert not _inside(os.path.realpath(session.root / leaves_request), session.root)
        assert _inside(os.path.realpath(session.root / stays_request), session.root)
        _assert_controls_are_approved(session, shape)
        for kind, field in (("write", "file"), ("read", "path")):
            assert _kind_of(session.ask(_make(shape, kind, **{field: stays_request}))) == "approved", (
                f"a {kind} through a {link_kind} that stays inside was denied"
            )
        for kind, field in (("write", "file"), ("read", "path")):
            assert _kind_of(session.ask(_make(shape, kind, **{field: leaves_request}))) == "denied-by-rules", (
                f"a {kind} through a {link_kind} that leaves the session was approved"
            )
    finally:
        if link_kind == "junction":
            for link in made:
                try:
                    os.rmdir(link)  # removes the junction only, never its target
                except OSError:
                    pass


def _short_path(path: Path) -> str | None:
    """The 8.3 form of an existing Windows path, or None where there is none."""
    if os.name != "nt":
        return None
    import ctypes

    buffer = ctypes.create_unicode_buffer(1024)
    length = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))  # type: ignore[attr-defined]
    return buffer.value if 0 < length < len(buffer) else None


def test_handler_expands_existing_8_3_components_in_the_session_directory_and_the_request(tmp_path: Path) -> None:
    long_session = tmp_path / "bf896 long session directory"
    (long_session / "src").mkdir(parents=True)
    outside = tmp_path / "bf896 long outside directory"
    outside.mkdir()
    short_session, short_outside = _short_path(long_session), _short_path(outside)
    if short_session is None or short_outside is None or "~" not in short_session or "~" not in short_outside:
        pytest.skip("this platform or volume has no 8.3 short names")
    assert short_session.lower() != str(long_session).lower()  # premise: the two spellings differ
    assert os.path.samefile(short_session, long_session)
    handler = build_session_permission_handler(short_session, _TOOLS)  # the session directory given in its short form
    long_write = _make("dataclass", "write", file=str(long_session / "src" / "a.py"))
    short_write = _make("dataclass", "write", file=os.path.join(short_session, "src", "a.py"))
    outside_via_short = _make("dataclass", "write", file=os.path.join(short_outside, "a.py"))
    assert _kind_of(handler(long_write, {})) == "approved"
    assert _kind_of(handler(short_write, {})) == "approved"
    assert not _inside(os.path.realpath(os.path.join(short_outside, "a.py")), long_session)  # premise: a real escape
    assert _kind_of(handler(outside_via_short, {})) == "denied-by-rules"
    # The same short spelling of the session directory also seeds it correctly (the seam to the scan's keys).
    seeded = seed_session_directory(short_session, {"src/seeded.py": "seeded = 1\n"})
    assert seeded == {"src/seeded.py": "seeded = 1\n"}
    assert (long_session / "src" / "seeded.py").read_text(encoding="utf-8") == "seeded = 1\n"


_UNUSABLE_ROOTS = [
    pytest.param("bad\x00path", id="nul-byte"),
    pytest.param("", id="empty"),
    pytest.param(None, id="none"),
    pytest.param("ordinary-relative", id="ordinary-relative"),
    pytest.param("<existing-relative>", id="existing-relative-directory"),
    pytest.param("<missing>", id="missing-directory"),
    pytest.param("<file>", id="a-file-not-a-directory"),
    pytest.param(5, id="int"),
    pytest.param(b"bytes-session", id="bytes"),
]


@pytest.mark.parametrize("root", _UNUSABLE_ROOTS)
def test_handler_never_raises_and_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session: _Session, shape: str, root: Any,
) -> None:
    monkeypatch.chdir(tmp_path)
    assert not os.path.exists("ordinary-relative")  # premise: the relative name names no directory from here
    # Requests that look inside a session directory: a usable session approves the first two (the controls).
    inside_usable = ["src/x.py", str(session.root / "src" / "x.py")]
    inside_unusable: list[str] = []
    if root == "<existing-relative>":
        # A relative name that DOES resolve from the cwd must still be refused (BF-896 D1: the directory is absolute).
        (tmp_path / "rel-dir").mkdir()
        assert os.path.isdir("rel-dir"), "premise: the relative directory exists from the cwd"
        root = "rel-dir"
    elif root == "<missing>":
        root = str(tmp_path / "does-not-exist")
        assert not os.path.exists(root)
        inside_unusable.append(os.path.join(root, "src", "x.py"))
    elif root == "<file>":
        target = tmp_path / "a-file.txt"
        target.write_text("not a directory", encoding="utf-8")
        root = str(target)
        inside_unusable.append(os.path.join(root, "src", "x.py"))
    _assert_controls_are_approved(session, shape)
    for candidate in inside_usable:
        assert _kind_of(session.ask(_make(shape, "write", file=candidate))) == "approved", candidate
        assert _kind_of(session.ask(_make(shape, "read", path=candidate))) == "approved", candidate
    handler = build_session_permission_handler(root, _TOOLS)  # constructs: the factory never raises
    for candidate in inside_usable + inside_unusable:
        assert _kind_of(handler(_make(shape, "write", file=candidate), {})) == "denied-by-rules", candidate
        assert _kind_of(handler(_make(shape, "read", path=candidate), {})) == "denied-by-rules", candidate
    # Only the path requests are denied: a registered tool is still approved, an unregistered one is not.
    assert _kind_of(handler(_make(shape, "custom-tool", tool="standing_orders_lookup"), {})) == "approved"
    assert _kind_of(handler(_make(shape, "custom-tool", tool="shell_exec"), {})) == "denied-by-rules"


class _RaisingRequest:
    """A request whose every attribute access raises."""

    def __getattribute__(self, name: str) -> Any:
        raise RuntimeError(f"boom reading {name}")


class _RaisingDict(dict):  # type: ignore[type-arg]
    """A wire-dict request whose lookups raise."""

    def get(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("boom in get")


@pytest.mark.parametrize(
    "make_request",
    [
        pytest.param(_RaisingRequest, id="attribute-access-raises"),
        pytest.param(lambda: _RaisingDict(kind="write", fileName="src/ok.py"), id="dict-lookup-raises"),
        pytest.param(lambda: None, id="none"),
        pytest.param(lambda: object(), id="plain-object"),
        pytest.param(lambda: "write", id="bare-string"),
        pytest.param(lambda: [], id="list"),
        pytest.param(lambda: 42, id="int"),
        pytest.param(lambda: {}, id="empty-dict"),
        pytest.param(lambda: MappingProxyType({"kind": "write", "fileName": "src/ok.py"}), id="a-mapping-that-is-not-a-dict"),
    ],
)
def test_handler_never_raises_and_fails_closed_on_a_request_it_cannot_read(
    session: _Session, shape: str, make_request: Callable[[], Any],
) -> None:
    _assert_controls_are_approved(session, shape)
    result = session.ask(make_request())  # must not raise
    assert _kind_of(result) == "denied-by-rules"
    assert _kind_of(session.ask(_make(shape, "write", file="src/ok.py"))) == "approved"  # and the handler lives on


def test_handler_logs_a_warning_for_a_request_that_raises(
    session: _Session, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="probos.cognitive.copilot_adapter")
    assert _kind_of(session.ask(_make("dataclass", "write", file="src/ok.py"))) == "approved"
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert _kind_of(session.ask(_RaisingRequest())) == "denied-by-rules"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "could not be evaluated" in warnings[0].getMessage()
    assert warnings[0].exc_info is not None


def _names_then_raise() -> Any:
    yield "standing_orders_lookup"
    raise RuntimeError("boom listing the tools")


@pytest.mark.parametrize(
    "make_names",
    [
        pytest.param(_names_then_raise, id="iterable-raises-after-a-name"),
        pytest.param(lambda: None, id="none"),
        pytest.param(lambda: 5, id="int"),
        pytest.param(lambda: [None, 5, b"standing_orders_lookup", _LyingStr("standing_orders_lookup")], id="no-exact-str-names"),
    ],
)
def test_handler_never_raises_and_fails_closed_on_tool_names_it_cannot_use(
    session: _Session, shape: str, make_names: Callable[[], Any],
) -> None:
    _assert_controls_are_approved(session, shape)  # a handler built from a good list approves the tool
    handler = build_session_permission_handler(str(session.root), make_names())  # constructs
    # Fails closed to an empty tool set, even for a name the iterable yielded before it raised ...
    assert _kind_of(handler(_make(shape, "custom-tool", tool="standing_orders_lookup"), {})) == "denied-by-rules"
    # ... while path requests, which do not depend on the tool names, are unaffected.
    assert _kind_of(handler(_make(shape, "write", file="src/ok.py"), {})) == "approved"
    assert _kind_of(handler(_make(shape, "read", path="src/x.py"), {})) == "approved"


def test_handler_keeps_only_exact_str_tool_names(session: _Session, shape: str) -> None:
    handler = build_session_permission_handler(
        str(session.root), [None, 5, "standing_orders_lookup", _LyingStr("codebase_query")],
    )
    assert _kind_of(handler(_make(shape, "custom-tool", tool="standing_orders_lookup"), {})) == "approved"
    assert _kind_of(handler(_make(shape, "custom-tool", tool="codebase_query"), {})) == "denied-by-rules"


# ── Handler: the result type ───────────────────────────────────────────────


def test_handler_result_uses_the_sdk_result_type(session: _Session, monkeypatch: pytest.MonkeyPatch) -> None:
    # Built BEFORE the result type is replaced: the verdict must be made with the SDK's type at call time.
    approve = _make("dataclass", "write", file="src/ok.py")
    refuse = _make("dataclass", "shell", command="ls")
    calls: list[str] = []

    @dataclass
    class _Recording:
        kind: str = "unset"

        def __post_init__(self) -> None:
            calls.append(self.kind)

    monkeypatch.setattr(sdk, "PermissionRequestResult", _Recording)
    approved, denied = session.ask(approve), session.ask(refuse)
    assert isinstance(approved, _Recording) and isinstance(denied, _Recording)
    assert (approved.kind, denied.kind) == ("approved", "denied-by-rules")
    assert calls == ["approved", "denied-by-rules"]

    # The 0.1.30 call shape: a TypedDict constructor, which builds a plain dict that release's client reads.
    monkeypatch.setattr(sdk, "PermissionRequestResult", lambda **kwargs: dict(kwargs))
    approved, denied = session.ask(approve), session.ask(refuse)
    assert isinstance(approved, dict) and isinstance(denied, dict)
    assert approved == {"kind": "approved"} and denied == {"kind": "denied-by-rules"}

    # The verdicts are handed back untouched, whatever the type is.
    sentinel = object()
    monkeypatch.setattr(sdk, "PermissionRequestResult", lambda **kwargs: sentinel)
    assert session.ask(approve) is sentinel and session.ask(refuse) is sentinel


@pytest.mark.skipif(sdk._SDK_AVAILABLE, reason="the stand-in result type exists only when the SDK is not installed")
def test_fallback_permission_result_carries_a_kind_and_does_not_default_to_approved() -> None:
    assert sdk.PermissionRequestResult(kind="approved").kind == "approved"
    assert sdk.PermissionRequestResult(kind="denied-by-rules").kind == "denied-by-rules"
    assert sdk.PermissionRequestResult().kind != "approved"


# ── seed_session_directory ─────────────────────────────────────────────────


def test_seed_session_directory(tmp_path: Path) -> None:
    session = tmp_path / "session"
    session.mkdir()
    seeded = seed_session_directory(str(session), {
        "src/probos/a.py": "a = 1\n",
        "./src/probos/dot.py": "dot = 1\n",
        "src\\probos\\back.py": "back = 1\n",
        str(session / "tests" / "abs.py"): "abs = 1\n",
        "pyproject.toml": "[project]\nname = 'fixture'\n",
        "src/probos/not_yet.py": "",
    })
    # Non-empty entries are written, keyed by the normalized session-relative path the scan compares against.
    assert seeded == {
        "src/probos/a.py": "a = 1\n",
        "src/probos/dot.py": "dot = 1\n",
        "src/probos/back.py": "back = 1\n",
        "tests/abs.py": "abs = 1\n",
        "pyproject.toml": "[project]\nname = 'fixture'\n",
        "src/probos/not_yet.py": "",
    }
    for rel, text in seeded.items():
        if text:
            assert (session / rel).read_text(encoding="utf-8") == text
    # An empty entry (a target that does not exist yet) is kept in the result and not written.
    assert not (session / "src" / "probos" / "not_yet.py").exists()
    # The "./" and backslash spellings landed at the normalized path: no stray entry carries the raw spelling.
    assert sorted(p.name for p in (session / "src" / "probos").iterdir()) == ["a.py", "back.py", "dot.py"]
    assert sorted(p.name for p in session.iterdir()) == ["pyproject.toml", "src", "tests"]


@pytest.mark.parametrize(
    "key",
    [
        pytest.param("../x", id="parent-traversal"),
        pytest.param("src/../../x", id="nested-traversal"),
        pytest.param("<absolute-outside>", id="absolute-outside"),
        pytest.param("x\x00", id="nul-byte"),
        pytest.param("<sibling-prefix>", id="sibling-prefix"),
        pytest.param("src/a.py:stream", id="ntfs-stream"),
        pytest.param("C:foo", id="drive-relative"),
        pytest.param("", id="empty"),
    ],
)
def test_seed_session_directory_drops_and_logs_a_key_outside_the_directory(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, key: str,
) -> None:
    session = tmp_path / "session"
    session.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("original", encoding="utf-8")  # premise: a write through the key would visibly change this
    evil = tmp_path / "session_evil"
    evil.mkdir()
    if key == "<absolute-outside>":
        key = str(outside)
    elif key == "<sibling-prefix>":
        key = str(evil / "x.py")
        assert key.startswith(str(session))  # premise: a prefix comparison would accept it
    caplog.set_level(logging.WARNING, logger="probos.cognitive.copilot_adapter")
    seeded = seed_session_directory(str(session), {"src/ok.py": "ok = 1\n", key: "boom"})
    # The control is seeded in the same call; the key is dropped, logged, and wrote nothing anywhere.
    assert seeded == {"src/ok.py": "ok = 1\n"}
    assert (session / "src" / "ok.py").read_text(encoding="utf-8") == "ok = 1\n"
    assert outside.read_text(encoding="utf-8") == "original"
    assert not (tmp_path / "x").exists() and not (evil / "x.py").exists()
    dropped = [r.getMessage() for r in caplog.records if "not seeding" in r.getMessage()]
    assert len(dropped) == 1 and repr(key) in dropped[0]


@pytest.mark.parametrize("unusable", ["<missing>", "<file>", "", None, "bad\x00path", 5])
def test_seed_session_directory_raises_value_error_on_an_unusable_directory(
    tmp_path: Path, unusable: Any,
) -> None:
    good = tmp_path / "session"
    good.mkdir()
    assert seed_session_directory(str(good), {"src/ok.py": "ok = 1\n"}) == {"src/ok.py": "ok = 1\n"}  # control
    if unusable == "<missing>":
        unusable = str(tmp_path / "does-not-exist")
        assert not os.path.exists(unusable)
    elif unusable == "<file>":
        target = tmp_path / "a-file.txt"
        target.write_text("not a directory", encoding="utf-8")
        unusable = str(target)
    with pytest.raises(ValueError, match="BF-896"):
        seed_session_directory(unusable, {"src/x.py": "x = 1\n"})
    assert not (tmp_path / "src").exists()


def test_seed_session_directory_ignores_non_str_content_and_accepts_an_empty_mapping(tmp_path: Path) -> None:
    session = tmp_path / "session"
    session.mkdir()
    assert seed_session_directory(str(session), {}) == {}
    seeded = seed_session_directory(
        str(session), {"src/ok.py": "ok = 1\n", "src/none.py": None, "src/bytes.py": b"x"},  # type: ignore[dict-item]
    )
    assert seeded == {"src/ok.py": "ok = 1\n"}
    assert sorted(p.name for p in (session / "src").iterdir()) == ["ok.py"]


# ── The adapter on a fake SDK client (the AD-1200 pattern) ─────────────────


class _FakeSdk:
    """What the adapter handed the fake Copilot client, plus what the fake agent does in its session."""

    def __init__(self) -> None:
        self.options: list[dict[str, Any]] = []
        self.configs: list[dict[str, Any]] = []
        self.lifecycle: list[str] = []
        self.agent: Callable[[dict[str, Any]], None] | None = None
        self.output: str = "done"  # the text the fake session answers with


def _install_fake_sdk(monkeypatch: pytest.MonkeyPatch) -> _FakeSdk:
    fake = _FakeSdk()

    class _FakeSession:
        def __init__(self, config: dict[str, Any]) -> None:
            self._config = config

        async def send_and_wait(self, prompt: dict[str, str], *, timeout: float) -> None:
            if fake.agent is not None:
                fake.agent(self._config)

        async def get_messages(self) -> list[Any]:
            return [SimpleNamespace(type="assistant", data=SimpleNamespace(content=fake.output))]

        async def disconnect(self) -> None:
            fake.lifecycle.append("disconnect")

    class _FakeClient:
        def __init__(self, options: dict[str, Any]) -> None:
            fake.options.append(options)

        async def start(self) -> None:
            fake.lifecycle.append("start")

        async def create_session(self, config: dict[str, Any]) -> _FakeSession:
            fake.configs.append(config)
            return _FakeSession(config)

        async def stop(self) -> None:
            fake.lifecycle.append("stop")

    monkeypatch.setattr(sdk, "_SDK_AVAILABLE", True)
    monkeypatch.setattr(sdk, "CopilotClient", _FakeClient, raising=False)
    monkeypatch.setattr(sdk, "SessionEventType", SimpleNamespace(ASSISTANT_MESSAGE="assistant"), raising=False)
    monkeypatch.setattr(sdk, "Tool", lambda **kwargs: SimpleNamespace(**kwargs), raising=False)
    return fake


async def _run(
    adapter: sdk.CopilotBuilderAdapter, spec: BuildSpec | None = None, files: dict[str, str] | None = None,
) -> sdk.CopilotBuildResult:
    await adapter.start()
    try:
        return await adapter.execute(spec or BuildSpec(title="BF-896 fixture", description="No changes."), files or {})
    finally:
        await adapter.stop()


def _write(root: Path, rel: str, text: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _instruction_frames(prompt: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in prompt.splitlines() if line.startswith('{"source":')]


@pytest.mark.asyncio
@pytest.mark.parametrize("cwd", ["", None], ids=["empty-cwd", "none-cwd"])
async def test_execute_refuses_without_a_session_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cwd: str | None,
) -> None:
    fake = _install_fake_sdk(monkeypatch)
    discovered: list[Any] = []
    real_discover = sdk.discover_build_repository_instructions

    def spy(work_dir: Any, **kwargs: Any) -> Any:
        discovered.append(work_dir)
        return real_discover(work_dir, **kwargs)

    monkeypatch.setattr(sdk, "discover_build_repository_instructions", spy)
    session = tmp_path / "session"
    session.mkdir()
    # Control first: with a session directory the same fakes ARE reached (create_session and discovery both run).
    controlled = await _run(sdk.CopilotBuilderAdapter(cwd=str(session)))
    assert len(fake.configs) == 1 and discovered == [str(session)]
    assert controlled.error == ""
    fake.configs.clear()
    fake.options.clear()
    fake.lifecycle.clear()
    discovered.clear()

    result = await _run(sdk.CopilotBuilderAdapter(cwd=cwd))
    assert result.success is False
    assert "session directory" in result.error
    assert result.file_blocks == []
    assert fake.configs == []  # create_session never called
    assert discovered == []  # discovery never ran
    assert len(fake.options) == 1 and fake.options[0]["cwd"] == str(sdk._PROJECT_ROOT)  # start() keeps the client cwd
    assert fake.lifecycle == ["start", "stop"]


_FULL_TOOLS = [
    "standing_orders_lookup", "codebase_query", "codebase_find_callers", "codebase_get_imports",
    "codebase_find_tests", "codebase_read_source", "system_self_model",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("full", [True, False], ids=["every-tool-registered", "standing-orders-only"])
async def test_execute_installs_the_session_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shape: str, full: bool,
) -> None:
    fake = _install_fake_sdk(monkeypatch)
    session = tmp_path / "session"
    session.mkdir()
    outside = tmp_path / "outside" / "x.py"
    adapter = sdk.CopilotBuilderAdapter(
        cwd=str(session),
        codebase_index=object() if full else None,  # type: ignore[arg-type]
        runtime=SimpleNamespace(data_dir=str(tmp_path / "instance")) if full else None,  # type: ignore[arg-type]
    )
    await _run(adapter)
    assert len(fake.configs) == 1
    config = fake.configs[0]
    names = [tool.name for tool in config["tools"]]
    assert names == (_FULL_TOOLS if full else ["standing_orders_lookup"])  # premise: which tools this session registered
    assert config["working_directory"] == str(session)
    handler = config["on_permission_request"]
    assert callable(handler)

    def ask(kind: str, **fields: Any) -> Any:
        return _kind_of(handler(_make(shape, kind, **fields), {"session_id": "fake"}))

    # Controls first: a write inside cwd, a read inside cwd, and every registered tool are approved.
    assert ask("write", file="src/probos/new.py") == "approved"
    assert ask("write", file=str(session / "tests" / "test_new.py")) == "approved"
    assert ask("read", path="src/probos/new.py") == "approved"
    for name in names:
        assert ask("custom-tool", tool=name) == "approved", name
    # Then the denials: shell, an absolute write outside, an unregistered tool, other kinds.
    assert ask("shell", command="git status") == "denied-by-rules"
    assert ask("write", file=str(outside)) == "denied-by-rules"
    assert ask("read", path=str(outside)) == "denied-by-rules"
    assert ask("write", file="pyproject.toml") == "denied-by-rules"
    assert ask("custom-tool", tool="shell_exec") == "denied-by-rules"
    assert ask("url") == "denied-by-rules" and ask("mcp") == "denied-by-rules" and ask("memory") == "denied-by-rules"
    if not full:
        # A tool the adapter could register but did not for THIS session is denied: the names come from the session.
        assert ask("custom-tool", tool="codebase_query") == "denied-by-rules"
    # The agent is told what the policy enforces (Section 5), in the system message the session receives.
    assert "permission policy" in config["system_message"]["content"]


@pytest.mark.asyncio
async def test_the_handler_is_built_in_execute_over_the_directory_as_it_is_then(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_sdk(monkeypatch)
    later = tmp_path / "created-after-the-adapter"
    adapter = sdk.CopilotBuilderAdapter(cwd=str(later))  # constructs although the directory does not exist yet
    assert not later.exists()  # premise: a handler built in the constructor would have no usable session root
    later.mkdir()
    await _run(adapter)
    handler = fake.configs[0]["on_permission_request"]
    assert _kind_of(handler(_make("dataclass", "write", file="src/probos/new.py"), {})) == "approved"
    assert _kind_of(handler(_make("dataclass", "write", file=str(tmp_path / "elsewhere.py")), {})) == "denied-by-rules"


@pytest.mark.asyncio
async def test_instruction_work_dir_is_separate_from_the_session_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_sdk(monkeypatch)
    seen: list[Any] = []
    real_discover = sdk.discover_build_repository_instructions

    def spy(work_dir: Any, **kwargs: Any) -> Any:
        seen.append(work_dir)
        return real_discover(work_dir, **kwargs)

    monkeypatch.setattr(sdk, "discover_build_repository_instructions", spy)
    worktree = tmp_path / "worktree"
    (worktree / ".git").mkdir(parents=True)
    _write(worktree, "AGENTS.md", "WORKTREE-MARKER")
    session = tmp_path / "session"
    session.mkdir()
    assert not (session / "AGENTS.md").exists()  # premise: the guidance exists only in the worktree

    # Named: guidance is discovered from the worktree; the session runs in its own directory.
    await _run(sdk.CopilotBuilderAdapter(cwd=str(session), instruction_work_dir=str(worktree)))
    assert seen == [str(worktree)]
    config = fake.configs[-1]
    assert config["working_directory"] == str(session)
    assert fake.options[-1]["cwd"] == str(session)
    assert [frame["content"] for frame in _instruction_frames(config["system_message"]["content"])] == ["WORKTREE-MARKER"]
    # The permission policy is built over the session directory, not the worktree.
    handler = config["on_permission_request"]
    assert _kind_of(handler(_make("dataclass", "write", file=str(session / "src" / "a.py")), {})) == "approved"
    assert _kind_of(handler(_make("dataclass", "write", file=str(worktree / "src" / "a.py")), {})) == "denied-by-rules"
    assert _kind_of(handler(_make("dataclass", "read", path=str(worktree / "AGENTS.md")), {})) == "denied-by-rules"

    # Omitted: the session directory doubles as the instruction directory (AD-1200's behaviour is kept).
    seen.clear()
    await _run(sdk.CopilotBuilderAdapter(cwd=str(worktree)))
    assert seen == [str(worktree)]
    config = fake.configs[-1]
    assert config["working_directory"] == str(worktree)
    assert [frame["content"] for frame in _instruction_frames(config["system_message"]["content"])] == ["WORKTREE-MARKER"]


@pytest.mark.asyncio
async def test_scan_reports_only_changes_and_every_block_carries_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_sdk(monkeypatch)
    session = tmp_path / "session"
    session.mkdir()
    original = {
        "src/probos/changed.py": "value = 1\n",
        "src/probos/untouched.py": "value = 2\n",
        "pyproject.toml": "[project]\nname = 'fixture'\n",  # a reference file the agent leaves alone
    }
    seeded = seed_session_directory(str(session), original)
    assert seeded == original  # premise: seeding keeps the keys the scan compares against

    def agent(config: dict[str, Any]) -> None:
        _write(session, "src/probos/created.py", "created = True\n")
        _write(session, "src/probos/changed.py", "value = 100\n")

    fake.agent = agent
    spec = BuildSpec(
        title="Scan fixture", description="Create one file, change one.",
        target_files=["src/probos/changed.py", "src/probos/created.py"],
    )
    result = await _run(sdk.CopilotBuilderAdapter(cwd=str(session)), spec, seeded)
    assert result.success is True and result.error == ""
    # Premise: the untouched seeded files are still on disk, so the scan saw them and chose not to report them.
    assert (session / "src" / "probos" / "untouched.py").read_text(encoding="utf-8") == "value = 2\n"
    assert (session / "pyproject.toml").is_file()
    blocks = {block["path"]: block for block in result.file_blocks}
    assert len(result.file_blocks) == 2 and sorted(blocks) == ["src/probos/changed.py", "src/probos/created.py"]
    assert blocks["src/probos/changed.py"] == {
        "path": "src/probos/changed.py", "mode": "modify", "content": "value = 100\n", "base": "value = 1\n",
    }
    assert blocks["src/probos/created.py"] == {
        "path": "src/probos/created.py", "mode": "create", "content": "created = True\n", "base": "",
    }


@pytest.mark.asyncio
async def test_scan_reports_a_created_empty_seed_target_as_a_create_with_empty_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_sdk(monkeypatch)
    session = tmp_path / "session"
    session.mkdir()
    seeded = seed_session_directory(str(session), {"src/probos/target.py": "", "src/probos/kept.py": "kept = 1\n"})
    assert seeded == {"src/probos/target.py": "", "src/probos/kept.py": "kept = 1\n"}
    assert not (session / "src" / "probos" / "target.py").exists()  # premise: the empty entry was not written

    fake.agent = lambda config: _write(session, "src/probos/target.py", "target = 1\n")
    result = await _run(sdk.CopilotBuilderAdapter(cwd=str(session)), None, seeded)
    assert result.success is True
    assert result.file_blocks == [
        {"path": "src/probos/target.py", "mode": "create", "content": "target = 1\n", "base": ""}
    ]


@pytest.mark.asyncio
async def test_scan_reports_a_file_absent_from_the_seed_map_as_a_create_with_empty_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_sdk(monkeypatch)
    session = tmp_path / "session"
    session.mkdir()
    seeded = seed_session_directory(str(session), {"src/probos/kept.py": "kept = 1\n"})
    assert "src/probos/brand_new.py" not in seeded, "premise: the key is absent from the seed map"

    fake.agent = lambda config: _write(session, "src/probos/brand_new.py", "")  # an empty new file
    result = await _run(sdk.CopilotBuilderAdapter(cwd=str(session)), None, seeded)
    assert result.success is True
    assert result.file_blocks == [{"path": "src/probos/brand_new.py", "mode": "create", "content": "", "base": ""}]


@pytest.mark.asyncio
async def test_the_installed_policy_gates_what_the_session_writes_and_the_scan_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole chain: handler in the config -> the (fake) agent asks before each write -> the scan -> the blocks."""
    fake = _install_fake_sdk(monkeypatch)
    session = tmp_path / "session"
    session.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    attempts = [
        ("src/probos/ok.py", "ok = True\n"),
        ("../escape.py", "escape = True\n"),
        (str(outside / "abs.py"), "abs = True\n"),
        ("pyproject.toml", "[project]\nname = 'hijack'\n"),
        (".github/workflows/ci.yml", "name: hijack\n"),
    ]
    verdicts: list[tuple[str, Any]] = []

    def agent(config: dict[str, Any]) -> None:
        ask = config["on_permission_request"]
        for target, text in attempts:
            verdict = _kind_of(ask(_Request(kind=_Kind.WRITE, file_name=target), {"session_id": "fake"}))
            verdicts.append((target, verdict))
            if verdict == "approved":  # a denial returns an error to the model, which then writes nothing
                destination = Path(target) if os.path.isabs(target) else session / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(text, encoding="utf-8")

    fake.agent = agent
    result = await _run(sdk.CopilotBuilderAdapter(cwd=str(session)))
    assert verdicts == [
        ("src/probos/ok.py", "approved"),
        ("../escape.py", "denied-by-rules"),
        (str(outside / "abs.py"), "denied-by-rules"),
        ("pyproject.toml", "denied-by-rules"),
        (".github/workflows/ci.yml", "denied-by-rules"),
    ]
    assert not (tmp_path / "escape.py").exists()
    assert not (outside / "abs.py").exists()
    assert not (session / "pyproject.toml").exists()
    assert not (session / ".github").exists()
    assert result.success is True
    assert result.file_blocks == [{"path": "src/probos/ok.py", "mode": "create", "content": "ok = True\n", "base": ""}]


# ── The text fallback: every whole-file block the adapter emits carries base (BF-896 round 2, R2-1) ─────────────────────

_needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
_TEXT_TARGET = "src/probos/target.py"
_TEXT_BRANCH = "builder/bf896-text-fallback"
_FULL_FILE = "kept = 1\nvalue = 2\n"
_EXCERPT = "value = 2\n"  # what a localized perceive() would have seeded instead of the whole file


def _text_file_block(path: str, content: str) -> str:
    return f"===FILE: {path}===\n{content}===END FILE===\n"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


def _init_text_repo(repo: Path, files: dict[str, str]) -> None:
    repo.mkdir(parents=True)
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "bf896@example.invalid"),
        ("config", "user.name", "BF896 Tester"),
        ("config", "commit.gpgsign", "false"),
        ("config", "core.autocrlf", "false"),
    ):
        assert _git(repo, *args).returncode == 0, f"premise: git {args[0]} must succeed"
    for rel, text in files.items():
        _write(repo, rel, text)
    assert _git(repo, "add", "-A").returncode == 0, "premise: git add must succeed"
    assert _git(repo, "commit", "-q", "-m", "seed").returncode == 0, "premise: the seed commit"


def _show(repo: Path, ref: str, rel: str) -> str:
    shown = _git(repo, "show", f"{ref}:{rel}")
    assert shown.returncode == 0, f"{ref}:{rel} must exist ({shown.stderr.strip()})"
    return shown.stdout.replace("\r\n", "\n")


def _commit_count(repo: Path) -> int:
    return int(_git(repo, "rev-list", "--all", "--count").stdout.strip())


def _branches(repo: Path) -> list[str]:
    return sorted(_git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").stdout.split())


async def _text_build(
    root: Path, monkeypatch: pytest.MonkeyPatch, repo_files: dict[str, str], seed: dict[str, str], answer: str,
) -> tuple[sdk.CopilotBuildResult, BuildResult, Path]:
    """The fake session writes nothing to disk and answers *answer*; the blocks go into the real executor on a real repo."""
    fake = _install_fake_sdk(monkeypatch)
    fake.output = answer
    repo = root / "repo"
    _init_text_repo(repo, repo_files)
    session = root / "session"
    session.mkdir()
    seeded = seed_session_directory(str(session), seed)
    spec = BuildSpec(title="Text fallback", description="", branch_name=_TEXT_BRANCH, target_files=[_TEXT_TARGET])
    generated = await _run(sdk.CopilotBuilderAdapter(cwd=str(session)), spec, seeded)
    # Premises: the session wrote nothing (the disk scan finds nothing), so the blocks came from the text.
    on_disk = sorted(p.relative_to(session).as_posix() for p in session.rglob("*") if p.is_file())
    assert on_disk == sorted(seeded)
    assert generated.success is True and generated.error == "" and generated.raw_output == answer
    built = await execute_approved_build(generated.file_blocks, spec, str(repo), run_tests=False)
    return generated, built, repo


@_needs_git
@pytest.mark.asyncio
async def test_text_file_block_over_a_file_the_seed_holds_in_part_is_refused_and_the_file_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = _text_file_block(_TEXT_TARGET, "value = 3\n")
    # Control first: the seed IS the whole file, so the same text block applies to it.
    generated, built, repo = await _text_build(tmp_path / "whole", monkeypatch, {_TEXT_TARGET: _FULL_FILE}, {_TEXT_TARGET: _FULL_FILE}, answer)
    assert [b["base"] for b in generated.file_blocks] == [_FULL_FILE]
    assert built.success is True and built.files_modified == [_TEXT_TARGET] and built.commit_hash
    assert _show(repo, built.branch_name, _TEXT_TARGET) == "value = 3\n"

    # The repro: the seed is a localized excerpt of the real file (the native path's all_files).
    generated, built, repo = await _text_build(tmp_path / "excerpt", monkeypatch, {_TEXT_TARGET: _FULL_FILE}, {_TEXT_TARGET: _EXCERPT}, answer)
    assert _FULL_FILE != _EXCERPT, "premise: the seed differs from the file"
    assert [b["base"] for b in generated.file_blocks] == [_EXCERPT]  # the block carries the seeded base
    assert built.success is False and "different content" in built.error
    assert built.commit_hash == "" and built.files_written == [] and built.files_modified == []
    assert _commit_count(repo) == 1 and _branches(repo) == ["main"]
    assert _show(repo, "main", _TEXT_TARGET) == _FULL_FILE  # the original "kept = 1" line survives
    assert (repo / _TEXT_TARGET).read_text(encoding="utf-8").replace("\r\n", "\n") == _FULL_FILE


@_needs_git
@pytest.mark.asyncio
async def test_text_file_block_for_an_absent_path_is_applied_with_an_empty_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = _text_file_block("src/probos/brand_new.py", "fresh = 1\n")
    generated, built, repo = await _text_build(tmp_path, monkeypatch, {"src/probos/kept.py": "kept = 1\n"}, {"src/probos/kept.py": "kept = 1\n"}, answer)
    assert not (repo / "src/probos/brand_new.py").exists(), "premise: the path is absent before the build"
    assert [(b["path"], b["base"]) for b in generated.file_blocks] == [("src/probos/brand_new.py", "")]
    assert built.success is True and built.files_written == ["src/probos/brand_new.py"] and built.files_modified == []
    assert _show(repo, built.branch_name, "src/probos/brand_new.py") == "fresh = 1\n"


@_needs_git
@pytest.mark.asyncio
async def test_text_file_block_over_an_existing_file_the_seed_does_not_name_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = _text_file_block(_TEXT_TARGET, "value = 3\n")
    # Control first: the seed names the file (the same text as the file), so the block applies.
    _, built, repo = await _text_build(tmp_path / "named", monkeypatch, {_TEXT_TARGET: _FULL_FILE}, {_TEXT_TARGET: _FULL_FILE}, answer)
    assert built.success is True and built.files_modified == [_TEXT_TARGET]

    # The seed holds only another file: the path is absent from it, so base is "" while the file is not empty.
    generated, built, repo = await _text_build(tmp_path / "unnamed", monkeypatch, {_TEXT_TARGET: _FULL_FILE, "src/probos/other.py": "o = 1\n"}, {"src/probos/other.py": "o = 1\n"}, answer)
    assert (repo / _TEXT_TARGET).is_file(), "premise: the target exists in the repository"
    assert [b["base"] for b in generated.file_blocks] == [""]
    assert built.success is False and "different content" in built.error and built.commit_hash == ""
    assert _commit_count(repo) == 1 and _branches(repo) == ["main"]
    assert _show(repo, "main", _TEXT_TARGET) == _FULL_FILE


@_needs_git
@pytest.mark.asyncio
async def test_text_modify_block_stays_base_free_and_applies_by_its_search_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = f"===MODIFY: {_TEXT_TARGET}===\n===SEARCH===\nvalue = 2\n===REPLACE===\nvalue = 3\n===END REPLACE===\n===END MODIFY===\n"
    # An excerpt seed: a base on this block would be refused, so the absence of one is what lets it apply.
    generated, built, repo = await _text_build(tmp_path, monkeypatch, {_TEXT_TARGET: _FULL_FILE}, {_TEXT_TARGET: _EXCERPT}, answer)
    assert len(generated.file_blocks) == 1 and generated.file_blocks[0]["mode"] == "modify"
    assert "replacements" in generated.file_blocks[0], "premise: the block was parsed from the text"
    assert "base" not in generated.file_blocks[0]
    assert built.success is True and built.files_modified == [_TEXT_TARGET] and built.commit_hash
    assert _show(repo, built.branch_name, _TEXT_TARGET) == "kept = 1\nvalue = 3\n"


def test_the_shared_text_parser_still_emits_base_free_blocks() -> None:
    text = (
        _text_file_block(_TEXT_TARGET, "value = 3\n")
        + f"===MODIFY: {_TEXT_TARGET}===\n===SEARCH===\nvalue = 2\n===REPLACE===\nvalue = 3\n===END REPLACE===\n===END MODIFY===\n"
    )
    blocks = BuilderAgent._parse_file_blocks(text)
    assert [b["mode"] for b in blocks] == ["create", "modify"], "premise: both block kinds were parsed"
    assert all("base" not in block for block in blocks)
