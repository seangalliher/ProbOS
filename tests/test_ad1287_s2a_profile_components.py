"""AD-1287 S2a (M1): the two component-digest producers of ``probos.cognitive.profile_components``.

``skill_resource_digest`` digests a skill directory read from disk; ``tool_schema_digest`` digests a tool's declared
input and output schemas. Every known-answer vector is built HERE from the literal domain bytes and
``probos.federation.ard.jcs.canonicalize`` (the canonicaliser the module's ``canonicalize_projection`` wraps), never by
calling the function under test, so a changed domain, field, order or encoding cannot move the expectation with it.
Lower bounds are applied with ``monkeypatch.setattr(profile_components, "MAX_...", n)``; the skill depth bound is
exercised at its real value. Links are made with ``os.symlink`` and, on Windows, ``_winapi.CreateJunction``: a case
whose link cannot be made on the machine running the suite is skipped with the reason, never silently passed.
"""

from __future__ import annotations

import ast
import enum
import hashlib
import importlib.util
import math
import os
import re
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive import profile_components
from probos.cognitive.profile_components import ComponentDigestError, skill_resource_digest, tool_schema_digest
from probos.federation.ard import jcs

_SKILL_DOMAIN = b"probos.execution_profile/skill_resources/v1\x00"
_TOOL_DOMAIN = b"probos.execution_profile/tool_schema/v1\x00"
_HEX64 = re.compile(r"[0-9a-f]{64}")
_MAX_DEPTH = profile_components.MAX_SCHEMA_DEPTH


class _ColorEnum(enum.StrEnum):
    """A ``str`` the canonicaliser digests as its text; only the module's exact-type walk can refuse it."""

    RED = "red"


class _LevelEnum(enum.IntEnum):
    """An ``int`` the canonicaliser digests as its number; only the module's exact-type walk can refuse it."""

    ONE = 1


class _TextSubclass(str):
    """A ``str`` subclass the canonicaliser digests as plain text."""


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def _write_tree(root: Path, files: dict[str, bytes]) -> None:
    """Create ``files`` (relative POSIX path -> bytes) under ``root``, in the mapping's own order."""
    root.mkdir(parents=True, exist_ok=True)
    for relative, data in files.items():
        target = root.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _files_under(root: Path) -> dict[str, bytes]:
    """Every regular file under ``root`` by the test's own walk: relative POSIX path -> bytes."""
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _dirs_under(root: Path) -> set[str]:
    """Every directory under ``root`` by the test's own walk, as relative POSIX paths."""
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_dir()}


def _expected_skill_digest(files: dict[str, bytes]) -> str:
    """The digest ``files`` must have: ascending by path, each entry path/sha256/size, RFC 8785, domain-prefixed."""
    entries = [
        {"path": path, "sha256": hashlib.sha256(files[path]).hexdigest(), "size": len(files[path])}
        for path in sorted(files)
    ]
    return hashlib.sha256(_SKILL_DOMAIN + jcs.canonicalize({"files": entries})).hexdigest()


def _expected_tool_digest(input_schema: Any, output_schema: Any) -> str:
    """The digest a schema pair must have: RFC 8785 of both schemas under the literal tool-schema domain."""
    payload = {"input_schema": input_schema, "output_schema": output_schema}
    return hashlib.sha256(_TOOL_DOMAIN + jcs.canonicalize(payload)).hexdigest()


def _assert_refusal(caught: pytest.ExceptionInfo[BaseException], kind: type[BaseException], code: str) -> None:
    """The refusal is exactly ``kind`` (a subclass would not do) and carries only the stable ``code``."""
    assert type(caught.value) is kind
    assert caught.value.args == (code,)


def _try_link(link: Path, target: Path, kind: str) -> str | None:
    """Make ``link`` point at ``target`` as a ``"symlink"`` or a ``"junction"``.

    Returns ``None`` when the link was made, else the reason this machine cannot make it (used as the skip reason).
    """
    if kind == "junction" and sys.platform != "win32":
        return "junctions exist on Windows only"
    try:
        if kind == "junction":
            import _winapi  # CPython's Windows-only module; the test alone uses it, to make a junction without a shell

            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError) as exc:
        reason = getattr(exc, "strerror", None) or type(exc).__name__
        return f"cannot make a {kind} on this machine: {reason}"
    return None


def _stats(value: Any, ancestors: tuple[int, ...] = ()) -> tuple[float, float]:
    """``(depth, node count)`` of a JSON-shaped value by the test's own count; a cycle measures ``(inf, inf)``.

    A scalar is one node at depth 1; a container is one node and one level deeper than its deepest child; only
    values are nodes (a key is not), which is how the module's budget counts.
    """
    if id(value) in ancestors:
        return math.inf, math.inf
    if isinstance(value, dict):
        children = list(value.values())
    elif isinstance(value, (list, tuple)):
        children = list(value)
    else:
        return 1, 1
    below = [_stats(child, (*ancestors, id(value))) for child in children]
    return 1 + max((depth for depth, _ in below), default=0), 1 + sum(nodes for _, nodes in below)


def _pair_shape(input_schema: Any, output_schema: Any) -> tuple[float, float]:
    """``(deepest level, total nodes)`` across a schema pair, the way the module's shared budget counts it."""
    (depth_in, nodes_in), (depth_out, nodes_out) = _stats(input_schema), _stats(output_schema)
    return max(depth_in, depth_out), nodes_in + nodes_out


def _types_in(value: Any) -> set[type]:
    """Every exact type that occurs at any node of a JSON-shaped value."""
    found: set[type] = {type(value)}
    if isinstance(value, dict):
        for item in value.values():
            found |= _types_in(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            found |= _types_in(item)
    return found


def _is_probos(module: str) -> bool:
    return module == "probos" or module.startswith("probos.")


def _probos_imports(source: bytes) -> set[str]:
    """Every ProbOS module an import node anywhere in ``source`` (any depth) names; a relative import keeps its dots."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names if _is_probos(alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                modules.add("." * node.level + (node.module or ""))
            elif node.module and _is_probos(node.module):
                modules.add(node.module)
    return modules


# --------------------------------------------------------------------------------------
# 1-2. skill_resource_digest: identity
# --------------------------------------------------------------------------------------


def test_skill_digest_known_answer(tmp_path: Path) -> None:
    # Arrange: z.md is created FIRST but sorts LAST (after both subdirectory entries); bytes carry CRLF and NUL
    files = {
        "z.md": b"last in code-point order, created first\r\n",
        "references/a.md": b"# reference\nline two\n",
        "assets/bin.dat": b"\x00\x01\r\n\xff\x00tail",
        "SKILL.md": b"# Skill\r\nBody with CRLF\r\n",
    }
    ascending = ["SKILL.md", "assets/bin.dat", "references/a.md", "z.md"]
    assert next(iter(files)) == "z.md"  # premise: created first ...
    assert ascending[-1] == "z.md"  # ... yet last in the manifest, after the subdirectory entries
    assert ascending == sorted(files)  # premise: the literal order really is ascending by code point
    assert any(b"\r\n" in data for data in files.values())  # premise: some bytes carry CRLF ...
    assert any(b"\x00" in data for data in files.values())  # ... and some carry NUL
    root = tmp_path / "skill"
    _write_tree(root, files)
    entries = [
        {"path": path, "sha256": hashlib.sha256(files[path]).hexdigest(), "size": len(files[path])}
        for path in ascending
    ]
    expected = hashlib.sha256(_SKILL_DOMAIN + jcs.canonicalize({"files": entries})).hexdigest()

    # Act
    digest = skill_resource_digest(root)

    # Assert
    assert digest == expected


def test_skill_digest_is_deterministic(tmp_path: Path) -> None:
    # Arrange: the same content created in opposite orders under two differently named roots
    files = {"a.md": b"alpha\n", "sub/b.md": b"bravo\r\n", "sub/deeper/c.bin": b"\x00charlie", "z.md": b"zulu\n"}
    first_order = list(files)
    second_order = list(reversed(files))
    assert first_order != second_order  # premise: the creation orders differ
    first, second = tmp_path / "first_skill", tmp_path / "second_skill_other_name"
    _write_tree(first, {path: files[path] for path in first_order})
    _write_tree(second, {path: files[path] for path in second_order})
    assert _files_under(first) == _files_under(second) == files  # premise: equal content

    # Act
    digest_first = skill_resource_digest(first)
    digest_second = skill_resource_digest(second)
    digest_again = skill_resource_digest(first)

    # Assert
    assert _HEX64.fullmatch(digest_first)
    assert digest_second == digest_first
    assert digest_again == digest_first


# --------------------------------------------------------------------------------------
# 3. skill_resource_digest: what the digest tracks
# --------------------------------------------------------------------------------------

_BASELINE = {"SKILL.md": b"# Skill\nfirst line\nsecond line\n", "notes/one.md": b"note one\n"}


def _flip_first_byte(root: Path) -> None:
    path = root / "SKILL.md"
    data = path.read_bytes()
    path.write_bytes(bytes([data[0] ^ 0x01]) + data[1:])  # same length: only a byte moves


def _rename_file(root: Path) -> None:
    (root / "notes" / "one.md").rename(root / "notes" / "uno.md")  # same bytes: only a path moves


def _add_empty_file(root: Path) -> None:
    (root / "empty.txt").write_bytes(b"")  # no bytes at all: only an entry (path, empty sha256, size 0) appears


def _lf_to_crlf(root: Path) -> None:
    path = root / "SKILL.md"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))  # the bytes and the size both move


def _add_empty_directory(root: Path) -> None:
    (root / "hollow").mkdir()  # a directory is not an entry


@pytest.mark.parametrize(
    ("change", "digest_moves"),
    [
        pytest.param(_flip_first_byte, True, id="one_changed_byte"),
        pytest.param(_rename_file, True, id="renamed_file"),
        pytest.param(_add_empty_file, True, id="added_empty_file"),
        pytest.param(_lf_to_crlf, True, id="lf_to_crlf"),
        pytest.param(_add_empty_directory, False, id="added_empty_directory_pinned_unchanged"),
    ],
)
def test_skill_digest_tracks_each_byte_path_and_size(
    tmp_path: Path, change: Callable[[Path], None], digest_moves: bool
) -> None:
    # Arrange: two identical trees; the change is applied to one of them only
    before, after = tmp_path / "before", tmp_path / "after"
    _write_tree(before, _BASELINE)
    _write_tree(after, _BASELINE)
    assert _files_under(before) == _files_under(after) == _BASELINE  # premise: identical until the change
    change(after)
    assert (_files_under(after) != _files_under(before)) is digest_moves  # premise: a file moved, or none did ...
    assert (_dirs_under(after) != _dirs_under(before)) is (not digest_moves)  # ... because only a directory appeared

    # Act
    digest_before = skill_resource_digest(before)
    digest_after = skill_resource_digest(after)

    # Assert
    assert (digest_after != digest_before) is digest_moves


# --------------------------------------------------------------------------------------
# 4-5. skill_resource_digest: links and non-regular entries
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("link_kind", "target_is_dir", "link_is_root", "code"),
    [
        pytest.param("symlink", False, False, "skill_resource_link_refused", id="file_symlink_below_root"),
        pytest.param("symlink", True, False, "skill_resource_link_refused", id="directory_symlink_below_root"),
        pytest.param("junction", True, False, "skill_resource_link_refused", id="junction_below_root"),
        pytest.param("symlink", True, True, "skill_resource_dir_invalid", id="root_is_a_symlink"),
        pytest.param("junction", True, True, "skill_resource_dir_invalid", id="root_is_a_junction"),
    ],
)
def test_skill_digest_refuses_links(
    tmp_path: Path, link_kind: str, target_is_dir: bool, link_is_root: bool, code: str
) -> None:
    # Arrange
    assert hasattr(os.DirEntry, "is_junction")  # premise: the module's link test can see a junction at all
    skill, elsewhere = tmp_path / "skill", tmp_path / "elsewhere"
    _write_tree(skill, {"SKILL.md": b"# skill\n"})
    _write_tree(elsewhere, {"target.md": b"target\n", "refs/a.md": b"a\n"})
    link = tmp_path / "skill_link" if link_is_root else skill / "link"
    target = elsewhere if target_is_dir else elsewhere / "target.md"
    real_root = elsewhere if link_is_root else skill
    assert _HEX64.fullmatch(skill_resource_digest(real_root))  # premise: the same tree digests fine without the link
    reason = _try_link(link, target, link_kind)
    if reason is not None:
        pytest.skip(reason)
    try:
        # premise: the link made is the kind claimed, and it is what the module is handed (the root) or meets (below it)
        assert link.is_junction() if link_kind == "junction" else link.is_symlink()
        root = link if link_is_root else skill

        # Act
        with pytest.raises(ComponentDigestError) as caught:
            skill_resource_digest(root)

        # Assert
        _assert_refusal(caught, ComponentDigestError, code)
    finally:
        link.unlink()  # removes the link itself, never its target


@pytest.mark.skipif(
    not hasattr(os, "mkfifo"), reason="os.mkfifo is POSIX-only: no non-regular, non-link entry can be made here"
)
def test_skill_digest_refuses_non_regular(tmp_path: Path) -> None:
    # Arrange
    root = tmp_path / "skill"
    _write_tree(root, {"SKILL.md": b"# skill\n"})
    pipe = root / "pipe"
    os.mkfifo(pipe)
    assert stat.S_ISFIFO(os.lstat(pipe).st_mode)  # premise: neither a regular file, a directory nor a link

    # Act
    with pytest.raises(ComponentDigestError) as caught:
        skill_resource_digest(root)

    # Assert
    _assert_refusal(caught, ComponentDigestError, "skill_resource_not_regular")


# --------------------------------------------------------------------------------------
# 6-7. skill_resource_digest: bounds and a bad root
# --------------------------------------------------------------------------------------


def _nested_layout(levels: int) -> dict[str, bytes]:
    """One file at the bottom of ``levels`` nested directories: ``d1/d2/.../f.md``."""
    return {"/".join([*(f"d{level}" for level in range(1, levels + 1)), "f.md"]): b"deep\n"}


@pytest.mark.parametrize(
    ("limit_name", "lowered_to", "files", "refused"),
    [
        pytest.param("MAX_SKILL_FILES", 3, {"a.md": b"a", "b.md": b"b", "c.md": b"c"}, False, id="files_3_at_bound_ok"),
        pytest.param(
            "MAX_SKILL_FILES",
            3,
            {"a.md": b"a", "b.md": b"b", "c.md": b"c", "d.md": b"d"},
            True,
            id="files_4_one_over_refused",
        ),
        pytest.param("MAX_SKILL_BYTES", 10, {"a.md": b"123456", "b.md": b"7890"}, False, id="bytes_10_at_bound_ok"),
        pytest.param(
            "MAX_SKILL_BYTES", 10, {"a.md": b"123456", "b.md": b"78901"}, True, id="bytes_11_one_over_refused"
        ),
        pytest.param("MAX_SKILL_DEPTH", None, _nested_layout(8), False, id="depth_8_at_real_bound_ok"),
        pytest.param("MAX_SKILL_DEPTH", None, _nested_layout(9), True, id="depth_9_one_over_refused"),
    ],
)
def test_skill_digest_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    lowered_to: int | None,
    files: dict[str, bytes],
    refused: bool,
) -> None:
    # Arrange
    assert (lowered_to is None) is (limit_name == "MAX_SKILL_DEPTH")  # premise: only depth stays at its real value
    if lowered_to is not None:
        monkeypatch.setattr(profile_components, limit_name, lowered_to)
    bound = getattr(profile_components, limit_name)
    measured = {
        "MAX_SKILL_FILES": len(files),
        "MAX_SKILL_BYTES": sum(len(data) for data in files.values()),
        "MAX_SKILL_DEPTH": max(path.count("/") for path in files),
    }[limit_name]
    assert measured == bound + (1 if refused else 0)  # premise: the tree sits exactly at the bound, or one past it
    root = tmp_path / "skill"
    _write_tree(root, files)

    # Act / Assert
    if refused:
        with pytest.raises(ComponentDigestError) as caught:
            skill_resource_digest(root)
        _assert_refusal(caught, ComponentDigestError, "skill_resource_limit")
    else:
        assert skill_resource_digest(root) == _expected_skill_digest(files)


def _missing_root(base: Path) -> Path:
    return base / "absent"


def _regular_file_root(base: Path) -> Path:
    path = base / "plain.md"
    path.write_bytes(b"a file, not a directory\n")
    return path


def _str_root(base: Path) -> str:
    return str(base)


@pytest.mark.parametrize(
    ("make_bad_root", "error_type", "exists"),
    [
        pytest.param(_missing_root, ComponentDigestError, False, id="missing_path"),
        pytest.param(_regular_file_root, ComponentDigestError, True, id="regular_file_path"),
        pytest.param(_str_root, TypeError, True, id="str_instead_of_path"),
    ],
)
def test_skill_digest_refuses_bad_root(
    tmp_path: Path, make_bad_root: Callable[[Path], Any], error_type: type[Exception], exists: bool
) -> None:
    # Arrange
    bad_root = make_bad_root(tmp_path)
    assert Path(bad_root).exists() is exists  # premise: missing, or present but not a directory Path
    assert not (isinstance(bad_root, Path) and bad_root.is_dir())  # premise: never a Path to a directory

    # Act
    with pytest.raises(error_type) as caught:
        skill_resource_digest(bad_root)

    # Assert
    _assert_refusal(caught, error_type, "skill_resource_dir_invalid")


# --------------------------------------------------------------------------------------
# 8-9. tool_schema_digest: identity
# --------------------------------------------------------------------------------------


def test_tool_schema_digest_known_answer() -> None:
    # Arrange: nested dicts, lists, ints, a float (``minimum: 0.5``) and a bool
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1},
            "limit": {"type": "integer", "minimum": 0.5, "maximum": 50},
        },
        "required": ["query"],
        "additionalProperties": False,
    }
    output_schema = {"type": "object", "properties": {"hits": {"type": "array", "items": {"type": "string"}}}}
    assert type(input_schema) is dict and type(output_schema) is dict  # premise: both exactly dict
    assert {float, bool, list, int} <= _types_in(input_schema)  # premise: the vector uses every non-trivial node kind
    payload = jcs.canonicalize({"input_schema": input_schema, "output_schema": output_schema})
    assert payload.startswith(b'{"input_schema":{') and b',"output_schema":{' in payload  # premise: RFC 8785 order
    expected = hashlib.sha256(b"probos.execution_profile/tool_schema/v1\x00" + payload).hexdigest()

    # Act
    digest = tool_schema_digest(input_schema, output_schema)

    # Assert
    assert digest == expected


def test_tool_schema_digest_is_order_free_and_role_bound() -> None:
    # Arrange: the same schema with another insertion order (list order is meaning, so it stays), and a different one
    schema_a = {
        "type": "object",
        "properties": {"x": {"type": "string"}, "y": {"type": "integer"}},
        "required": ["x", "y"],
    }
    schema_a_reordered = {
        "required": ["x", "y"],
        "properties": {"y": {"type": "integer"}, "x": {"type": "string"}},
        "type": "object",
    }
    schema_b = {"type": "string"}
    assert schema_a == schema_a_reordered  # premise: equal as mappings ...
    assert list(schema_a) != list(schema_a_reordered)  # ... yet inserted in another order, at the top ...
    assert list(schema_a["properties"]) != list(schema_a_reordered["properties"])  # ... and below it
    assert schema_a != schema_b  # premise: swapping the two schemas is a real change

    # Act
    digest = tool_schema_digest(schema_a, schema_b)
    reordered_digest = tool_schema_digest(schema_a_reordered, schema_b)
    swapped_digest = tool_schema_digest(schema_b, schema_a)

    # Assert
    assert _HEX64.fullmatch(digest)
    assert reordered_digest == digest
    assert swapped_digest != digest


# --------------------------------------------------------------------------------------
# 10. tool_schema_digest: what is refused
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bad_schema", "canonicaliser_accepts"),
    [
        pytest.param([{"type": "string"}], True, id="top_level_list"),
        pytest.param({_ColorEnum.RED: "x"}, True, id="strenum_key"),
        pytest.param({"minimum": _LevelEnum.ONE}, True, id="intenum_value"),
        pytest.param({"type": _TextSubclass("string")}, True, id="str_subclass_value"),
        pytest.param({"enum": [_ColorEnum.RED]}, True, id="strenum_value_inside_a_list"),
        pytest.param({"enum": {"a", "b"}}, False, id="set"),
        pytest.param({"default": b"raw"}, False, id="bytes"),
        pytest.param({"minimum": float("nan")}, False, id="nan"),
        pytest.param({"minimum": float("inf")}, False, id="infinity"),
        pytest.param({"maximum": 2**53}, False, id="int_beyond_the_i_json_range"),
    ],
)
def test_tool_schema_digest_refuses_non_json(bad_schema: Any, canonicaliser_accepts: bool) -> None:
    # Arrange
    valid = {"type": "string"}
    payload = {"input_schema": bad_schema, "output_schema": valid}
    if canonicaliser_accepts:
        # premise: the canonicaliser alone would digest it, so only the module's exact-type walk can refuse it
        assert isinstance(jcs.canonicalize(payload), bytes)
    else:
        # premise: the canonicaliser alone refuses it, as a plain ValueError the module must translate
        with pytest.raises(ValueError):
            jcs.canonicalize(payload)

    # Act
    with pytest.raises(ComponentDigestError) as caught:
        tool_schema_digest(bad_schema, valid)

    # Assert
    _assert_refusal(caught, ComponentDigestError, "tool_schema_invalid")


# --------------------------------------------------------------------------------------
# 11. tool_schema_digest: bounds
# --------------------------------------------------------------------------------------

_PAIR_DEPTH = 5  # hand count of ``_pair``: top dict 1, "properties" 2, the "b" dict 3, its "enum" list 4, "x" 5
_PAIR_NODES = 13  # hand count: input 11 (3 dicts + 2 lists + 6 scalars), output 2


def _nested(levels: int) -> dict[str, Any]:
    """A dict nested ``levels`` dicts deep: ``levels=1`` is ``{}``, ``levels=3`` is ``{"n": {"n": {}}}``."""
    value: dict[str, Any] = {}
    for _ in range(levels - 1):
        value = {"n": value}
    return value


def _deep(levels: int) -> Callable[[], tuple[Any, Any]]:
    return lambda: (_nested(levels), {})


def _pair() -> tuple[Any, Any]:
    input_schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"enum": ["x", "y"]}},
        "required": ["a"],
    }
    return input_schema, {"type": "boolean"}


def _pair_one_node_more() -> tuple[Any, Any]:
    input_schema, output_schema = _pair()
    return input_schema, {**output_schema, "nullable": True}


def _self_referencing() -> tuple[Any, Any]:
    cyclic: dict[str, Any] = {"type": "object"}
    cyclic["self"] = cyclic
    return cyclic, {"type": "string"}


@pytest.mark.parametrize(
    ("build", "nodes_lowered_to", "shape", "refused"),
    [
        pytest.param(_deep(_MAX_DEPTH), None, (_MAX_DEPTH, _MAX_DEPTH + 1), False, id="depth_at_bound_ok"),
        pytest.param(_deep(_MAX_DEPTH + 1), None, (_MAX_DEPTH + 1, _MAX_DEPTH + 2), True, id="depth_one_over_refused"),
        pytest.param(_pair, _PAIR_NODES, (_PAIR_DEPTH, _PAIR_NODES), False, id="nodes_at_bound_ok"),
        pytest.param(
            _pair_one_node_more, _PAIR_NODES, (_PAIR_DEPTH, _PAIR_NODES + 1), True, id="nodes_one_over_refused"
        ),
        pytest.param(_self_referencing, None, (math.inf, math.inf), True, id="self_reference_refused"),
    ],
)
def test_tool_schema_digest_bounds(
    monkeypatch: pytest.MonkeyPatch,
    build: Callable[[], tuple[Any, Any]],
    nodes_lowered_to: int | None,
    shape: tuple[float, float],
    refused: bool,
) -> None:
    # Arrange
    input_schema, output_schema = build()
    # premise: the pair sits exactly at the bound it probes (or one past it), by the test's own count
    assert _pair_shape(input_schema, output_schema) == shape
    if nodes_lowered_to is not None:
        monkeypatch.setattr(profile_components, "MAX_SCHEMA_NODES", nodes_lowered_to)

    # Act / Assert
    if refused:
        with pytest.raises(ComponentDigestError) as caught:
            tool_schema_digest(input_schema, output_schema)
        _assert_refusal(caught, ComponentDigestError, "tool_schema_invalid")
    else:
        assert tool_schema_digest(input_schema, output_schema) == _expected_tool_digest(input_schema, output_schema)


# --------------------------------------------------------------------------------------
# 12. tool_schema_digest: what is accepted
# --------------------------------------------------------------------------------------


def _scalar_schemas() -> tuple[Any, Any, Any, Any]:
    input_schema = {
        "type": "object",
        "properties": {
            "ratio": {"type": "number", "minimum": 0.5, "maximum": 1e21},
            "strict": {"type": "boolean", "default": False},
            "note": {"type": "string", "default": None},
            "count": {"type": "integer", "default": 3},
            "tags": {"enum": ["a", "b"]},
        },
    }
    output_schema = {"type": "null"}
    return input_schema, output_schema, input_schema, output_schema


def _tuple_and_list_schemas() -> tuple[Any, Any, Any, Any]:
    with_tuple = {"type": "string", "enum": ("a", "b")}
    with_list = {"type": "string", "enum": ["a", "b"]}
    return with_tuple, {"type": "null"}, with_list, {"type": "null"}


@pytest.mark.parametrize(
    ("build", "required_types"),
    [
        pytest.param(_scalar_schemas, {float, bool, type(None), int, str, list}, id="floats_bools_none"),
        pytest.param(_tuple_and_list_schemas, {tuple}, id="tuple_digests_as_the_same_list"),
    ],
)
def test_tool_schema_digest_accepts_json_scalars_and_tuples(
    build: Callable[[], tuple[Any, Any, Any, Any]], required_types: set[type]
) -> None:
    # Arrange: the schemas as handed in, and the list-only form of them that the digest must equal
    input_schema, output_schema, list_input, list_output = build()
    assert required_types <= _types_in(input_schema)  # premise: the kinds this case is about really occur
    assert tuple not in _types_in(list_input)  # premise: the expectation is built from lists only

    # Act
    digest = tool_schema_digest(input_schema, output_schema)

    # Assert
    assert digest == _expected_tool_digest(list_input, list_output)
    assert digest == tool_schema_digest(list_input, list_output)


# --------------------------------------------------------------------------------------
# 13. imports
# --------------------------------------------------------------------------------------


def test_components_module_imports_only_elastic_team() -> None:
    # Arrange
    spec = importlib.util.find_spec(profile_components.__name__)
    assert spec is not None and spec.origin is not None  # premise: a source module with a file behind it
    assert Path(spec.origin).name == "profile_components.py"
    source = Path(spec.origin).read_bytes()

    # Act
    imports = _probos_imports(source)

    # Assert
    assert imports == {"probos.cognitive.elastic_team"}
    # negative control: the scanner flags an import outside that set whatever its form or depth
    assert _probos_imports(b"from probos.tools import registry\n") == {"probos.tools"}
    assert _probos_imports(b"import probos.tools.registry\n") == {"probos.tools.registry"}
    assert _probos_imports(b"def late():\n    import probos.tools\n") == {"probos.tools"}
    assert _probos_imports(b"from . import registry\n") == {"."}
    assert _probos_imports(b"import os\nfrom pathlib import Path\n") == set()
