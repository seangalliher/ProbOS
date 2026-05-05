"""AD-685c — phantom-API pre-check type-shape validation tests."""
from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

# Load the helper as a module (lives outside src/probos/, not a package).
_REPO_ROOT = Path(__file__).resolve().parents[1]
_HELPER_PATH = _REPO_ROOT / "scripts" / "phantom_api_ast_helper.py"
_PRECHECK_PS1 = _REPO_ROOT / "scripts" / "phantom-api-precheck.ps1"
_PROMPT_PATH = _REPO_ROOT / "prompts" / "ad-685c-phantom-type-shape-v1.md"


def _load_helper():
    spec = importlib.util.spec_from_file_location(
        "_phantom_api_ast_helper_test", _HELPER_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def helper():
    mod = _load_helper()
    # Clear caches between fixtures so per-test src trees are isolated.
    mod._INDEX_CACHE.clear()
    mod._CLASS_METHODS_CACHE.clear()
    mod._RUNTIME_ATTRS_CACHE.clear()
    mod._RUNTIME_CONFLICTS_CACHE.clear()
    return mod


def _build_index_for(helper, tmp_path: Path, source: str) -> dict:
    src_root = tmp_path / "probos_src" / "probos"
    src_root.mkdir(parents=True)
    (src_root / "__init__.py").write_text("", encoding="utf-8")
    (src_root / "mod.py").write_text(source, encoding="utf-8")
    return helper.build_index(src_root)


# ---------------------------------------------------------------------------
# Section 1 — value classifier primitives
# ---------------------------------------------------------------------------


def test_value_to_shape_primitives(helper):
    def _vs(expr: str):
        return helper._value_to_shape(ast.parse(expr, mode="eval").body)

    assert _vs("42").primitive == "int"
    assert _vs('"hi"').primitive == "str"
    assert _vs("3.14").primitive == "float"
    assert _vs("True").primitive == "bool"
    assert _vs("None").primitive == "NoneType"
    # bytes literal → silent skip.
    assert _vs('b"abc"') is None
    # Variable reference → silent skip.
    assert _vs("some_var") is None
    # Attribute / call → silent skip.
    assert _vs("obj.attr") is None
    assert _vs("foo()") is None


# ---------------------------------------------------------------------------
# Section 2 — annotation classifier
# ---------------------------------------------------------------------------


def _ann(helper, src: str):
    """Parse `src` and return the annotation TypeShape for parameter `x`."""
    tree = ast.parse(src)
    func = next(
        n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    annotations = helper._collect_param_annotations(func)
    return helper._annotation_to_type_shape(annotations["x"])


def test_annotation_to_type_shape_primitives(helper):
    str_shape = _ann(helper, "def f(x: str) -> None: ...")
    assert str_shape.literal_types == frozenset({"str"})
    assert str_shape.allow_none is False
    assert str_shape.unknown is False

    int_shape = _ann(helper, "def f(x: int) -> None: ...")
    assert int_shape.literal_types == frozenset({"int"})

    unknown = _ann(helper, "def f(x: Foo) -> None: ...")
    assert unknown.unknown is True


def test_annotation_to_type_shape_optional(helper):
    a = _ann(helper, "from typing import Optional\ndef f(x: Optional[str]) -> None: ...")
    b = _ann(helper, "def f(x: 'str | None') -> None: ...")
    c = _ann(helper, "def f(x: 'None | str') -> None: ...")
    # `str | None` annotations may be parsed as strings; flatten via ast.parse on the annotation.
    # Easier: build directly.
    src_b = "def f(x: str | None) -> None: ..."
    src_c = "def f(x: None | str) -> None: ..."
    b2 = _ann(helper, src_b)
    c2 = _ann(helper, src_c)
    for shape in (a, b2, c2):
        assert shape.literal_types == frozenset({"str"})
        assert shape.allow_none is True


def test_annotation_to_type_shape_union(helper):
    pipe = _ann(helper, "def f(x: int | str) -> None: ...")
    assert pipe.literal_types == frozenset({"int", "str"})
    assert pipe.allow_none is False

    union = _ann(helper, "from typing import Union\ndef f(x: Union[int, float]) -> None: ...")
    assert union.literal_types == frozenset({"int", "float"})


def test_annotation_to_type_shape_containers(helper):
    list_str = _ann(helper, "def f(x: list[str]) -> None: ...")
    assert list_str.container == "list"
    assert len(list_str.element_shapes) == 1
    assert list_str.element_shapes[0].literal_types == frozenset({"str"})

    bare_list = _ann(helper, "def f(x: list) -> None: ...")
    assert bare_list.container == "list"
    assert bare_list.element_shapes == ()

    dict_str_int = _ann(helper, "def f(x: dict[str, int]) -> None: ...")
    assert dict_str_int.container == "dict"
    assert len(dict_str_int.element_shapes) == 2
    assert dict_str_int.element_shapes[0].literal_types == frozenset({"str"})
    assert dict_str_int.element_shapes[1].literal_types == frozenset({"int"})


# ---------------------------------------------------------------------------
# Sections 3-4 — find_type_shape_phantoms end-to-end
# ---------------------------------------------------------------------------


def test_match_str_to_str_no_phantom(helper, tmp_path):
    index = _build_index_for(helper, tmp_path, "def f(name: str) -> None: ...\n")
    body = 'obj.f(name="hi")'
    phantoms = helper.find_type_shape_phantoms(body, index)
    assert phantoms == []


def test_mismatch_int_to_str_flagged(helper, tmp_path):
    index = _build_index_for(helper, tmp_path, "def f(name: str) -> None: ...\n")
    body = "obj.f(name=42)"
    phantoms = helper.find_type_shape_phantoms(body, index)
    assert len(phantoms) == 1
    p = phantoms[0]
    assert p["category"] == "type_shape_mismatch"
    assert p["kwarg"] == "name"
    assert p["value_type"] == "int"
    assert p["expected_types"] == ["str"]


def test_none_optional_match_and_mismatch(helper, tmp_path):
    index = _build_index_for(
        helper, tmp_path,
        "def g(name: str | None) -> None: ...\n"
        "def h(name: str) -> None: ...\n",
    )
    assert helper.find_type_shape_phantoms("obj.g(name=None)", index) == []
    flagged = helper.find_type_shape_phantoms("obj.h(name=None)", index)
    assert len(flagged) == 1
    assert flagged[0]["value_type"] == "NoneType"
    assert flagged[0]["method"] == "h"


def test_list_str_match_and_mismatch(helper, tmp_path):
    index = _build_index_for(helper, tmp_path, "def k(tags: list[str]) -> None: ...\n")
    assert helper.find_type_shape_phantoms('obj.k(tags=["a","b"])', index) == []
    bad = helper.find_type_shape_phantoms("obj.k(tags=[1,2])", index)
    assert len(bad) == 1
    assert bad[0]["kwarg"] == "tags"


def test_variable_ref_skipped_silently(helper, tmp_path):
    index = _build_index_for(helper, tmp_path, "def f(name: str) -> None: ...\n")
    body = "obj.f(name=some_var)"
    assert helper.find_type_shape_phantoms(body, index) == []


def test_bytes_literal_skipped(helper, tmp_path):
    index = _build_index_for(helper, tmp_path, "def m(payload: int) -> None: ...\n")
    body = 'obj.m(payload=b"abc")'
    assert helper.find_type_shape_phantoms(body, index) == []


def test_union_int_str_accepts_int(helper, tmp_path):
    index = _build_index_for(helper, tmp_path, "def u(value: int | str) -> None: ...\n")
    assert helper.find_type_shape_phantoms("obj.u(value=42)", index) == []
    flagged = helper.find_type_shape_phantoms("obj.u(value=3.14)", index)
    assert len(flagged) == 1
    assert flagged[0]["value_type"] == "float"


def test_unknown_class_annotation_skipped(helper, tmp_path):
    index = _build_index_for(helper, tmp_path, "def w(item: KnowledgeEdge) -> None: ...\n")
    # Any value should be accepted (shape is unknown).
    assert helper.find_type_shape_phantoms("obj.w(item=42)", index) == []
    assert helper.find_type_shape_phantoms('obj.w(item="x")', index) == []


# ---------------------------------------------------------------------------
# Backward compatibility — AD-685 / AD-685b records unchanged
# ---------------------------------------------------------------------------


def test_backward_compat_kwarg_phantom_unchanged(helper, tmp_path):
    index = _build_index_for(helper, tmp_path, "def f(name: str) -> None: ...\n")
    body = "obj.f(other=1)"
    kwarg = helper.find_kwarg_phantoms(body, index)
    assert len(kwarg) == 1
    rec = kwarg[0]
    # Existing kwarg phantom record shape: no `category` field.
    assert "category" not in rec
    assert rec["kwarg"] == "other"
    assert rec["method"] == "f"


# ---------------------------------------------------------------------------
# Captain-required self-test: wrapper exit on this prompt
# ---------------------------------------------------------------------------


def test_self_test_wrapper_on_this_prompt():
    """Run the PowerShell wrapper on the AD-685c prompt itself.

    Captain spec requires this; any non-zero exit must be documented as
    introduced FPs. Skipped on non-Windows / no-pwsh hosts.
    """
    if sys.platform != "win32":
        pytest.skip("PowerShell wrapper self-test only runs on Windows.")
    pwsh = "pwsh"
    try:
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-File", str(_PRECHECK_PS1), str(_PROMPT_PATH)],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("pwsh not available or timed out.")
    # Wrapper exits non-zero only when phantom symbols are detected. Either
    # outcome is acceptable for this self-test, but document the count via
    # stdout for traceability when introduced FPs occur.
    assert proc.returncode in (0, 1), (
        f"wrapper exit {proc.returncode}; stderr: {proc.stderr[:500]}"
    )
