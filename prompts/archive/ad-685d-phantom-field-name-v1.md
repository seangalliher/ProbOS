# AD-685d v1 — Phantom-API Pre-Check Dataclass/Pydantic Field-Name Validation

**Status:** Drafted Wave 47, 2026-05-04. Single-AD continuous-build wave.
**Dependencies:** AD-685 (kwarg names), AD-685b (method names), AD-685c (kwarg type-shape) — all SHIPPED Waves through 46.
**Test floor:** 10. Plan: 12 (over-floor by 2; drop targets #5 + #11 if drift).
**Closes:** GH issue #407.

## Problem

The phantom-API pre-check now catches:
- AD-685: kwarg names against any same-named function signature (`obj.method(unknown_kwarg=...)`).
- AD-685b: method names against the resolved class (`obj.unknown_method(...)`).
- AD-685c: kwarg value types against annotation shapes (`obj.method(name=42)` vs `name: str`).

It does **not** catch:
- **Field-name typos on dataclass / Pydantic instances** when accessed as attributes (`meta.totel_ops`) or passed as constructor kwargs (`AgentMeta(succes_count=5)`). AD-685c only validates *types* of kwargs, and only against function signatures via the `index` keyed by method name. Constructor calls today match against any `__init__` whose kwarg list happens to overlap, which is a weak signal vs walking `dataclasses.fields()` / Pydantic field set explicitly.
- **Property/field collisions across inheritance**: a child class declares a dataclass field `status: str` while its parent has `@property def status(self): ...`. This silently shadows the property at instance access — common cause of subtle field drift bugs (Wave 32 retrospective gap).

Wave 32 surfaced a real-world variant of this: a prompt asserted `meta.failure_count` against an indexed class where the actual field was `failures` (truncated). Today the helper flags nothing — the kwarg/method indexes don't carry per-class field knowledge.

## Solution

Extend `scripts/phantom_api_ast_helper.py` with a third index keyed by class name → `{fields, parent_classes, properties, file, line}` covering `@dataclass`-decorated classes (frozen or not) and `BaseModel` subclasses. Two new walkers:

1. `find_field_phantoms(body, ...)` flags:
   - **Constructor kwarg phantom**: `MyDataclass(unknown_field=...)` where `unknown_field` is not in the class's transitive field set (own fields ∪ parent fields). Distinct from AD-685's `__init__`-param check because it specifically validates against the dataclass/Pydantic field declaration site, NOT against any same-named `__init__` lurking elsewhere.
   - **Attribute-access phantom**: `obj.unknown_field` where `obj` resolves to a known class (via existing Pattern A `runtime.X` or Pattern B `var = MyClass(...)`) and `unknown_field` is not in the transitive field set or method set. Skip when the access is followed by `(` (that's a method call → AD-685b territory).
2. `find_property_field_collisions(class_index)` flags every indexed class that declares a field whose name matches a `@property` or non-dunder method on any transitive parent class.

Both emit new categories: `field_phantom` and `property_field_collision`. Backward compat: existing AD-685/685b/685c category records ship unchanged.

### Why single-file extension (architect call)

Same as AD-685c: the helper is a single ~1000-line file at HEAD. Splitting is a refactor AD. v1 stays single-file (helper grows ~280 lines).

## Section 0: New Categories

| Category | Trigger | Sample render |
|---|---|---|
| `field_phantom` (constructor) | `MyDc(typo_field=1)` and `typo_field` not in dataclass/Pydantic fields | `MyDc(typo_field=...) -> not in fields {a,b,c}` |
| `field_phantom` (attribute) | `obj.typo_field` where `obj : MyDc` and not a field/method | `obj.typo_field -> not in fields {a,b,c} (class=MyDc)` |
| `property_field_collision` | Child dataclass field shadows parent `@property` or method | `MyChild.status shadows MyParent.status (property)` |

## Section 1: Class-Field Index

Add to `scripts/phantom_api_ast_helper.py` after the existing `_RUNTIME_CONFLICTS_CACHE` declaration (line ~89):

```
# AD-685d: class field index cache.
# class_name -> {"fields": set[str], "parents": list[str], "properties": set[str],
#                "methods": set[str], "kind": "dataclass"|"pydantic"|"plain"}
_CLASS_FIELDS_CACHE: dict[str, dict[str, dict]] = {}
```

Add new builder after `build_class_method_index()`:

```python
# Pydantic base classes we recognize. Matched by trailing-name-only at
# class definition site (handles `from pydantic import BaseModel` and
# also `pydantic.BaseModel` import styles).
_PYDANTIC_BASES = frozenset({"BaseModel"})


def _is_dataclass_decorated(node: ast.ClassDef) -> bool:
    """True if class has @dataclass / @dataclasses.dataclass decorator."""
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == "dataclass":
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == "dataclass":
            return True
        # @dataclass(frozen=True) — Call wrapping Name/Attribute.
        if isinstance(dec, ast.Call):
            f = dec.func
            if isinstance(f, ast.Name) and f.id == "dataclass":
                return True
            if isinstance(f, ast.Attribute) and f.attr == "dataclass":
                return True
    return False


def _base_names(node: ast.ClassDef) -> list[str]:
    """Extract simple base class names (last segment for dotted bases)."""
    names: list[str] = []
    for b in node.bases:
        if isinstance(b, ast.Name):
            names.append(b.id)
        elif isinstance(b, ast.Attribute):
            names.append(b.attr)
        # Subscripted bases (Generic[T]) — skip.
    return names


def _is_pydantic_class(node: ast.ClassDef) -> bool:
    """True if any base name matches a known Pydantic base."""
    return any(n in _PYDANTIC_BASES for n in _base_names(node))


def build_class_field_index(src_root: Path) -> dict[str, dict]:
    """Build a class_name -> field/property metadata index.

    For each `@dataclass`-decorated class and each `BaseModel` subclass,
    record:
      fields:     set of AnnAssign target names (excluding ClassVar / dunders)
      parents:    list of simple base class names (for transitive lookup)
      properties: set of names decorated with @property
      methods:    set of non-dunder def/async-def names
      kind:       "dataclass" | "pydantic" | "plain"

    Plain (non-dataclass non-Pydantic) classes are recorded ONLY when they
    contain `@property` or method definitions that downstream classes
    might collide with — to support property/field collision checks across
    plain-class parents.
    """
    cache_key = str(src_root.resolve())
    if cache_key in _CLASS_FIELDS_CACHE:
        return _CLASS_FIELDS_CACHE[cache_key]

    classes: dict[str, dict] = {}
    for py_file in src_root.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            is_dc = _is_dataclass_decorated(node)
            is_pyd = _is_pydantic_class(node)
            kind = "dataclass" if is_dc else ("pydantic" if is_pyd else "plain")
            fields: set[str] = set()
            properties: set[str] = set()
            methods: set[str] = set()
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    name = item.target.id
                    if name.startswith("__") and name.endswith("__"):
                        continue
                    # Skip ClassVar[...] annotations — those are class-level
                    # constants, not instance fields.
                    ann = item.annotation
                    if isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name) \
                            and ann.value.id == "ClassVar":
                        continue
                    if is_dc or is_pyd:
                        fields.add(name)
                elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    is_property = any(
                        (isinstance(d, ast.Name) and d.id == "property")
                        for d in item.decorator_list
                    )
                    if is_property:
                        properties.add(item.name)
                    else:
                        if not (item.name.startswith("__") and item.name.endswith("__")):
                            methods.add(item.name)
            if kind == "plain" and not properties and not methods:
                continue
            existing = classes.get(node.name)
            if existing is None:
                classes[node.name] = {
                    "fields": fields,
                    "parents": _base_names(node),
                    "properties": properties,
                    "methods": methods,
                    "kind": kind,
                }
            else:
                existing["fields"].update(fields)
                existing["properties"].update(properties)
                existing["methods"].update(methods)
                # Keep first-seen kind/parents — multiple ClassDefs of same
                # name across files are rare and non-canonical here.

    _CLASS_FIELDS_CACHE[cache_key] = classes
    return classes


def _resolve_transitive_fields(
    class_name: str,
    class_index: dict[str, dict],
    *,
    _seen: set[str] | None = None,
) -> tuple[set[str], set[str], set[str]]:
    """Return (fields, properties, methods) including all transitive parents.

    Cycle-safe via _seen. Unknown parents (third-party / stdlib) contribute
    nothing — the validator treats them as adding no constraint, which is
    the conservative skip-on-unknown stance.
    """
    seen = _seen if _seen is not None else set()
    if class_name in seen:
        return set(), set(), set()
    seen.add(class_name)
    info = class_index.get(class_name)
    if info is None:
        return set(), set(), set()
    fields = set(info["fields"])
    properties = set(info["properties"])
    methods = set(info["methods"])
    for parent in info["parents"]:
        pf, pp, pm = _resolve_transitive_fields(parent, class_index, _seen=seen)
        fields.update(pf)
        properties.update(pp)
        methods.update(pm)
    return fields, properties, methods
```

## Section 2: Constructor + Attribute Field-Phantom Detection

Add after `find_type_shape_phantoms()`:

```python
# `<ClassName>(<kwargs>)` constructor call site.
_CTOR_RE = re.compile(
    r"\b([A-Z][a-zA-Z0-9_]+)\s*\(([^()]*)\)",
)
# `<obj>.<field>` attribute access NOT followed by `(`.
# (Method calls are AD-685b territory; this restricts to true attribute reads.)
_ATTR_RE = re.compile(
    r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-z_][a-z0-9_]*)\b(?!\s*\()",
)


def find_field_phantoms(
    body: str,
    class_index: dict[str, dict],
    runtime_attrs: dict[str, str],
    pattern_b_vars: dict[str, str],
) -> list[dict]:
    """Scan body for dataclass/Pydantic field-name phantoms.

    Detects two patterns:
      1. Constructor kwargs: `MyDc(unknown_field=...)` where MyDc is a
         dataclass or Pydantic model and `unknown_field` is not in its
         transitive field set.
      2. Attribute accesses: `obj.unknown_field` (NOT followed by `(`)
         where `obj` resolves to a known dataclass/Pydantic class and
         `unknown_field` is neither field, property, nor method.

    Conservative skip rules (no flag emitted):
      - Class not in class_index → skip (unknown classes contribute nothing).
      - Class kind is "plain" → skip (only validate dataclass/Pydantic).
      - Field name starts with underscore → skip (private; conventionally
        unchecked).
      - Receiver doesn't resolve to a class → skip silently (mirrors
        AD-685b Pattern B silent skip rationale).
    """
    phantoms: list[dict] = []
    seen: set[str] = set()

    def _add(call_site: str, kind_label: str, class_name: str,
             field_name: str, valid_fields: set[str]) -> None:
        key = f"{call_site}::{class_name}::{field_name}"
        if key in seen:
            return
        seen.add(key)
        phantoms.append({
            "call_site": call_site,
            "class": class_name,
            "field": field_name,
            "category": "field_phantom",
            "access_kind": kind_label,
            "valid_fields": sorted(valid_fields)[:20],
        })

    # --- Pattern 1: constructor calls ---
    for m in _CTOR_RE.finditer(body):
        cls = m.group(1)
        kwarg_block = m.group(2)
        if cls in _NOISY_RECEIVER_TOKENS:
            continue
        info = class_index.get(cls)
        if info is None or info["kind"] == "plain":
            continue
        valid_fields, _, _ = _resolve_transitive_fields(cls, class_index)
        if not valid_fields:
            continue
        try:
            expr = ast.parse(f"_f({kwarg_block})", mode="eval")
        except SyntaxError:
            continue
        if not isinstance(expr.body, ast.Call):
            continue
        for kw in expr.body.keywords:
            name = kw.arg
            if name is None or name.startswith("_"):
                continue
            if name in valid_fields:
                continue
            call_site = f"{cls}({kwarg_block.strip()})"
            _add(call_site, "constructor", cls, name, valid_fields)

    # --- Pattern 2: attribute accesses ---
    for m in _ATTR_RE.finditer(body):
        recv = m.group(1)
        field_name = m.group(2)
        if field_name.startswith("_"):
            continue
        if recv in _NOISY_RECEIVER_TOKENS:
            continue
        # Resolve receiver → class.
        if recv == "runtime":
            # Skip — `runtime.X` here is the resolution edge; field access
            # would be `runtime.X.field` which has more segments and is
            # handled elsewhere if class is resolved via Pattern A. We skip
            # to avoid flagging public runtime attrs which are themselves
            # objects whose classes we don't model uniformly.
            continue
        # `runtime.X` Pattern A: requires preceding "runtime." in body.
        # Detect via match position — if the char before recv is '.', this
        # is a chained access we can't statically resolve from a single
        # regex hit (would need full AST walk). Skip per AD-685b precedent.
        if m.start() > 0 and body[m.start() - 1] == ".":
            continue
        cls_name = pattern_b_vars.get(recv)
        if cls_name is None:
            continue
        info = class_index.get(cls_name)
        if info is None or info["kind"] == "plain":
            continue
        valid_fields, valid_props, valid_methods = _resolve_transitive_fields(
            cls_name, class_index,
        )
        if field_name in valid_fields:
            continue
        if field_name in valid_props or field_name in valid_methods:
            continue
        if not valid_fields and not valid_props and not valid_methods:
            continue
        call_site = f"{recv}.{field_name}"
        _add(call_site, "attribute", cls_name, field_name, valid_fields)

    return phantoms


def find_property_field_collisions(
    class_index: dict[str, dict],
) -> list[dict]:
    """Flag classes whose fields shadow a parent property or method.

    Walks each indexed class's transitive parents (via class_index entries
    only — unknown parents skipped silently) and flags every (child_field,
    parent_property) and (child_field, parent_method) pair where names
    collide. Parent properties are higher-confidence collisions; methods
    are still surfaced because shadowing a parent method with an instance
    field is also a real bug.
    """
    collisions: list[dict] = []
    for cls, info in class_index.items():
        if info["kind"] not in ("dataclass", "pydantic"):
            continue
        own_fields = info["fields"]
        if not own_fields:
            continue
        for parent in info["parents"]:
            if parent == cls:
                continue
            pinfo = class_index.get(parent)
            if pinfo is None:
                continue
            _, parent_props, parent_methods = _resolve_transitive_fields(
                parent, class_index,
            )
            for fname in own_fields:
                if fname in parent_props:
                    collisions.append({
                        "child": cls,
                        "parent": parent,
                        "name": fname,
                        "kind": "property",
                        "category": "property_field_collision",
                    })
                elif fname in parent_methods:
                    collisions.append({
                        "child": cls,
                        "parent": parent,
                        "name": fname,
                        "kind": "method",
                        "category": "property_field_collision",
                    })
    return collisions
```

## Section 3: Wire into `main()`

SEARCH:
```python
    type_shape_phantoms = find_type_shape_phantoms(body, index)

    print(json.dumps({
        "phantoms": kwarg_phantoms + method_phantoms + type_shape_phantoms,
        "unresolved": unresolved,
    }), flush=True)
    return 0
```

REPLACE:
```python
    type_shape_phantoms = find_type_shape_phantoms(body, index)
    class_field_index = build_class_field_index(args.src_root)
    field_phantoms = find_field_phantoms(
        body, class_field_index, runtime_attrs, pattern_b_vars,
    )
    collision_phantoms = find_property_field_collisions(class_field_index)

    print(json.dumps({
        "phantoms": (kwarg_phantoms + method_phantoms + type_shape_phantoms
                     + field_phantoms + collision_phantoms),
        "unresolved": unresolved,
    }), flush=True)
    return 0
```

## Section 4: PowerShell Wrapper Dispatch

SEARCH (in `scripts/phantom-api-precheck.ps1`, the existing dispatch block):
```powershell
                    } elseif ($p.category -eq 'type_shape_mismatch') {
                        $expected = ($p.expected_types -join '|')
                        if (-not $expected) { $expected = '<unknown>' }
                        [void]$phantomsHere.Add(@{
                            Symbol = "$($p.method)($($p.kwarg)=<$($p.value_type)> -> expected <$expected>)"
                            Category = 'type_shape_mismatch'
                            CallSite = $p.call_site
                        })
                    } else {
```

REPLACE:
```powershell
                    } elseif ($p.category -eq 'type_shape_mismatch') {
                        $expected = ($p.expected_types -join '|')
                        if (-not $expected) { $expected = '<unknown>' }
                        [void]$phantomsHere.Add(@{
                            Symbol = "$($p.method)($($p.kwarg)=<$($p.value_type)> -> expected <$expected>)"
                            Category = 'type_shape_mismatch'
                            CallSite = $p.call_site
                        })
                    } elseif ($p.category -eq 'field_phantom') {
                        $valid = ($p.valid_fields -join ',')
                        if ($valid.Length -gt 80) { $valid = $valid.Substring(0, 80) + '...' }
                        [void]$phantomsHere.Add(@{
                            Symbol = "$($p.class).$($p.field) <$($p.access_kind)> -> not in fields {$valid}"
                            Category = 'field_phantom'
                            CallSite = $p.call_site
                        })
                    } elseif ($p.category -eq 'property_field_collision') {
                        [void]$phantomsHere.Add(@{
                            Symbol = "$($p.child).$($p.name) shadows $($p.parent).$($p.name) ($($p.kind))"
                            Category = 'property_field_collision'
                            CallSite = "$($p.child).$($p.name)"
                        })
                    } else {
```

## Section 5: Tests

NEW file `tests/test_ad685d_phantom_field_name.py`:

```python
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
```

## What This AD Does NOT Change (out of scope by design)

- **TypedDict field validation** — TypedDict is not used heavily in `src/probos/`. Defer to AD-685e if it ever becomes a hotspot.
- **Runtime introspection** — strictly AST-static. Fields injected via metaclass / `__init_subclass__` / dynamic `__annotations__` mutation are invisible.
- **Per-instance type narrowing across function boundaries** — Pattern B (`var = MyClass(...)`) only resolves within the prompt body. No flow analysis.
- **Constructor kwarg type-shape on dataclass fields** — AD-685c handles type-shape against function annotations; extending it to dataclass field annotations is a separate concern (AD-685e candidate; would require unifying the kwarg validators).
- **NamedTuple / attrs / msgspec** — not in scope. Same deferral pattern as TypedDict.
- **No exit-code semantics change** — field phantoms and collisions flow into the same `phantoms` list, contributing to non-zero exit per existing rule.
- **No new directory layout** — single-file helper grows ~280 lines (~1280 total).

## Hard Stops

1. **Builder must NOT import from `src/probos/`** — helper is AST-static; import would break sandbox.
2. **Builder must NOT change `_NOISY_RECEIVER_TOKENS` / `_NOISY_METHODS`** — those are AD-685/685b/685c surfaces; field validator skips by class-kind, not by these constants.
3. **Builder must NOT add a `category` field to existing AD-685 v1 kwarg-phantom records** — they remain category-less for back-compat.
4. **Builder must clear all 5 caches between fixtures** — `_INDEX_CACHE`, `_CLASS_METHODS_CACHE`, `_RUNTIME_ATTRS_CACHE`, `_RUNTIME_CONFLICTS_CACHE`, `_CLASS_FIELDS_CACHE`.
5. **Builder must NOT add field-attribute resolution through `runtime.X.field`** — that requires multi-segment AST walk; defer.

## Tracking

- `PROGRESS.md` — prepend AD-685d entry above AD-685c.
- `docs/development/roadmap.md` — flip AD-685d row Scoped→Complete (or add row if absent).
- `DECISIONS.md` — prepend new entry; group with AD-685/685b/685c.

## Acceptance Criteria

1. 12 new tests pass at `tests/test_ad685d_phantom_field_name.py`.
2. Existing AD-685, AD-685b, AD-685c test files (`test_phantom_api_precheck_kwargs.py`, `test_ad685b_phantom_method_name.py`, `test_ad685c_phantom_type_shape.py`) continue to pass — no record-shape drift.
3. Full gate non-decreasing vs Wave 46 baseline 11122. Expected delta: +12 (range 11132–11134).
4. Wrapper self-test on this prompt returns exit code in `{0, 1}` — clean preferred, ≤3 FP candidates acceptable if all reference the prompt's own fixture class names (`AgentMeta`/`PoolConfig`/etc.).
5. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-04, HEAD `893f29b`)

```
grep -n "^class TypeShape" scripts/phantom_api_ast_helper.py
  335: class TypeShape:

grep -n "^class ValueShape" scripts/phantom_api_ast_helper.py
  376: class ValueShape:

grep -n "find_type_shape_phantoms" scripts/phantom_api_ast_helper.py
  468: def find_type_shape_phantoms(

grep -n "_RUNTIME_CONFLICTS_CACHE" scripts/phantom_api_ast_helper.py
  88: _RUNTIME_CONFLICTS_CACHE: dict[str, set[str]] = {}

grep -n "build_class_method_index" scripts/phantom_api_ast_helper.py
  686: def build_class_method_index(src_root: Path) -> dict[str, set[str]]:

grep -n "elseif .*type_shape_mismatch" scripts/phantom-api-precheck.ps1
  282:                    } elseif ($p.category -eq 'type_shape_mismatch') {

grep -n "@dataclass" src/probos/types.py
  25: @dataclass
  35: @dataclass
  ... (multiple)

grep -n "class.*BaseModel" src/probos/config.py
  115: class PoolConfig(BaseModel):
  ... (multiple)

grep -n "@property" src/probos/types.py
  44:     @property
```

All architectural anchors verified at HEAD.
