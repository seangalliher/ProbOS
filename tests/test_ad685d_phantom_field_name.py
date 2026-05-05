"""AD-685d v1 — phantom-API field-name + property-collision tests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import importlib.util

REPO_ROOT = Path(__file__).resolve().parent.parent
HELPER = REPO_ROOT / "scripts" / "phantom_api_ast_helper.py"


@pytest.fixture
def helper_module():
    spec = importlib.util.spec_from_file_location("phantom_api_ast_helper", HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Clear module-level caches between tests.
    mod._INDEX_CACHE.clear()
    mod._CLASS_METHODS_CACHE.clear()
    mod._RUNTIME_ATTRS_CACHE.clear()
    mod._RUNTIME_CONFLICTS_CACHE.clear()
    mod._CLASS_FIELDS_CACHE.clear()
    return mod


@pytest.fixture
def fake_src(tmp_path: Path) -> Path:
    """Synthetic src tree with dataclass + Pydantic + property fixtures."""
    src = tmp_path / "src" / "probos"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("")
    (src / "models.py").write_text(
        "from dataclasses import dataclass\n"
        "from pydantic import BaseModel\n"
        "from typing import ClassVar\n"
        "\n"
        "@dataclass\n"
        "class AgentMeta:\n"
        "    spawn_time: float = 0.0\n"
        "    success_count: int = 0\n"
        "    failure_count: int = 0\n"
        "    KIND: ClassVar[str] = 'meta'\n"
        "    @property\n"
        "    def total_operations(self) -> int:\n"
        "        return self.success_count + self.failure_count\n"
        "    def reset(self) -> None: ...\n"
        "\n"
        "@dataclass\n"
        "class ChildMeta(AgentMeta):\n"
        "    extra: str = ''\n"
        "\n"
        "class PoolConfig(BaseModel):\n"
        "    name: str = 'default'\n"
        "    target_size: int = 1\n"
        "\n"
        "@dataclass\n"
        "class CollisionField(AgentMeta):\n"
        "    total_operations: int = 0\n"
        "\n"
        "@dataclass\n"
        "class CollisionMethod(AgentMeta):\n"
        "    reset: str = ''\n"
    )
    return src


def _run(helper_module, src: Path, body: str) -> dict:
    helper_module._INDEX_CACHE.clear()
    helper_module._CLASS_METHODS_CACHE.clear()
    helper_module._CLASS_FIELDS_CACHE.clear()
    index = helper_module.build_index(src)
    class_methods = helper_module.build_class_method_index(src)
    class_field_index = helper_module.build_class_field_index(src)
    runtime_attrs, _conflicts = helper_module.build_runtime_attr_index(src)
    pattern_b_vars, _ = helper_module._resolve_pattern_b(body)
    field_phantoms = helper_module.find_field_phantoms(
        body, class_field_index, runtime_attrs, pattern_b_vars,
    )
    collisions = helper_module.find_property_field_collisions(class_field_index)
    return {
        "field_phantoms": field_phantoms,
        "collisions": collisions,
        "class_field_index": class_field_index,
    }


# 1. dataclass field happy path — known field passes silently.
def test_dataclass_known_field_no_flag(helper_module, fake_src):
    body = "meta = AgentMeta(success_count=5)\nx = meta.success_count\n"
    out = _run(helper_module, fake_src, body)
    assert out["field_phantoms"] == []


# 2. dataclass unknown field via attribute access flags.
def test_dataclass_unknown_attribute_flagged(helper_module, fake_src):
    body = "meta = AgentMeta()\nbad = meta.totel_ops\n"
    out = _run(helper_module, fake_src, body)
    f = [p for p in out["field_phantoms"]
         if p["field"] == "totel_ops" and p["access_kind"] == "attribute"]
    assert len(f) == 1
    assert f[0]["category"] == "field_phantom"
    assert f[0]["class"] == "AgentMeta"


# 3. dataclass unknown field via constructor kwarg flags.
def test_dataclass_unknown_constructor_kwarg_flagged(helper_module, fake_src):
    body = "x = AgentMeta(succes_count=1)\n"
    out = _run(helper_module, fake_src, body)
    f = [p for p in out["field_phantoms"]
         if p["field"] == "succes_count" and p["access_kind"] == "constructor"]
    assert len(f) == 1
    assert f[0]["class"] == "AgentMeta"


# 4. Pydantic happy path — known field passes.
def test_pydantic_known_field_no_flag(helper_module, fake_src):
    body = "cfg = PoolConfig(name='x', target_size=2)\ny = cfg.name\n"
    out = _run(helper_module, fake_src, body)
    assert out["field_phantoms"] == []


# 5. Pydantic unknown field flagged.
def test_pydantic_unknown_field_flagged(helper_module, fake_src):
    body = "cfg = PoolConfig(unknown_field=1)\n"
    out = _run(helper_module, fake_src, body)
    f = [p for p in out["field_phantoms"] if p["field"] == "unknown_field"]
    assert len(f) == 1
    assert f[0]["class"] == "PoolConfig"


# 6. Property/field collision — child redefines parent property.
def test_property_field_collision_flagged(helper_module, fake_src):
    out = _run(helper_module, fake_src, "")
    cs = [c for c in out["collisions"]
          if c["child"] == "CollisionField" and c["name"] == "total_operations"]
    assert len(cs) == 1
    assert cs[0]["kind"] == "property"
    assert cs[0]["parent"] == "AgentMeta"
    assert cs[0]["category"] == "property_field_collision"


# 7. Method/field collision — child redefines parent method as field.
def test_method_field_collision_flagged(helper_module, fake_src):
    out = _run(helper_module, fake_src, "")
    cs = [c for c in out["collisions"]
          if c["child"] == "CollisionMethod" and c["name"] == "reset"]
    assert len(cs) == 1
    assert cs[0]["kind"] == "method"


# 8. Inherited fields recognized — child instance accessing parent field is fine.
def test_inherited_field_recognized(helper_module, fake_src):
    body = "child = ChildMeta()\nx = child.success_count\ny = ChildMeta(success_count=2)\n"
    out = _run(helper_module, fake_src, body)
    # `success_count` is from AgentMeta but ChildMeta extends it — must not flag.
    assert out["field_phantoms"] == []


# 9. Variable references with no resolvable class are silently skipped.
def test_unresolved_var_skipped(helper_module, fake_src):
    body = "result = some_function()\nx = result.totally_made_up_field\n"
    out = _run(helper_module, fake_src, body)
    assert out["field_phantoms"] == []


# 10. Output category strings are exactly the documented values.
def test_output_categories(helper_module, fake_src):
    body = "x = AgentMeta(bogus=1)\n"
    out = _run(helper_module, fake_src, body)
    assert all(p["category"] == "field_phantom" for p in out["field_phantoms"])
    assert all(c["category"] == "property_field_collision" for c in out["collisions"])


# 11. ClassVar annotation is not treated as a dataclass field.
def test_classvar_excluded_from_fields(helper_module, fake_src):
    out = _run(helper_module, fake_src, "")
    assert "KIND" not in out["class_field_index"]["AgentMeta"]["fields"]
    assert "success_count" in out["class_field_index"]["AgentMeta"]["fields"]


# 12. Self-test: running the helper on the AD-685d prompt itself is clean.
def test_self_test_on_prompt(helper_module):
    prompt = REPO_ROOT / "prompts" / "ad-685d-phantom-field-name-v1.md"
    if not prompt.is_file():
        pytest.skip("prompt file not on disk yet (pre-archive run)")
    src_root = REPO_ROOT / "src" / "probos"
    body = prompt.read_text(encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(HELPER), "--src-root", str(src_root)],
        input=body, capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    parsed = json.loads(proc.stdout)
    field_p = [p for p in parsed["phantoms"]
               if p.get("category") in ("field_phantom", "property_field_collision")]
    # Allow at most a handful of FPs (sample-class names in this prompt).
    # If any are flagged, they must reference fixture-only classes, never
    # production ones.
    for p in field_p:
        cls = p.get("class") or p.get("child", "")
        assert cls in {"", "AgentMeta", "ChildMeta", "PoolConfig",
                       "CollisionField", "CollisionMethod", "MyDc",
                       "MyChild", "MyParent"}, p
