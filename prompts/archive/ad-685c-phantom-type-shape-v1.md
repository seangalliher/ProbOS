# AD-685c v1 — Phantom-API Pre-Check Type-Shape Validation

**Status:** Ready for Builder
**Dependencies:** AD-685 v1 (kwarg validator, Wave 11), AD-685b v1 (method-call AST validator, Wave 15) — both shipped
**Estimated tests:** 10–12
**Closes:** GH issue #406

## Problem

The dispatch-time phantom-API pre-check (`scripts/phantom-api-precheck.ps1` shelling to `scripts/phantom_api_ast_helper.py`) currently validates two phantom shapes:

1. **AD-685** — kwarg names against any matching method signature.
2. **AD-685b** — method names against the resolved class.

It does **not** validate kwarg **values** against the parameter's annotated type. A prompt asserting `obj.method(name=42)` where the method declares `name: str` ships clean today.

GH issue #406 calls for type-shape validation: when a prompt asserts a literal value at a kwarg whose parameter has a static type annotation, flag the call when the literal's type is incompatible with the annotation.

## Solution

Extend the existing single-file Python helper `scripts/phantom_api_ast_helper.py` (note: NOT a `scripts/phantom-api-precheck/` directory — verified during verify-first; v1 stays single-file). Add a third candidate class `type_shape_mismatch` alongside the existing kwarg + method-name classes.

### Why single-file extension

Captain's spec referenced `scripts/phantom-api-precheck/` directory contents. Reality at HEAD `c33c38d`:

```
scripts/phantom-api-precheck.ps1     # PowerShell wrapper, 393 lines
scripts/phantom_api_ast_helper.py    # Single-file Python helper, ~620 lines
```

No directory exists. AD-685c v1 extends the existing single file. Splitting into a package is out of scope (would be a refactor AD).

### Architecture

1. **Type-shape index built in the same AST walk as `build_index()`** — zero extra file I/O. Each signature dict gains a new key `param_annotations: dict[str, ast.AST]` capturing parameter annotation AST nodes (None for unannotated params). Existing `params: list[str]` field unchanged.
2. **Annotation classifier `_annotation_to_type_shape(node) -> TypeShape`** — pure-AST, returns a structured shape:
   - `literal_types: frozenset[str]` — primitive type names the annotation accepts (subset of `{"str", "int", "float", "bool", "bytes"}`).
   - `allow_none: bool` — True if `Optional[X]` / `X | None` / `None | X`.
   - `container: str | None` — `"list"` / `"dict"` / `"tuple"` / `"set"` / `None`.
   - `element_shapes: tuple[TypeShape, ...]` — per-element annotations for containers (empty tuple if not a container).
   - `unknown: bool` — True if any branch of the annotation references a non-primitive class (e.g., `KnowledgeEdge`); when True the validator SKIPs (cannot validate without runtime introspection).
3. **Value classifier `_value_to_type(node) -> ValueShape | None`** — pure-AST over the call's kwarg-value expression:
   - `ast.Constant(int)` → primitive `"int"`.
   - `ast.Constant(str)` → primitive `"str"`.
   - `ast.Constant(float)` → primitive `"float"`.
   - `ast.Constant(bool)` → primitive `"bool"` (Python booleans are int subclasses; v1 also accepts these against `int` annotations — see compat rule).
   - `ast.Constant(None)` → `"NoneType"`.
   - `ast.Constant(bytes)` → returns `None` (Captain spec: "skipped on bytes/bytes-like — cannot resolve").
   - `ast.List` → container `"list"` + element value-shapes.
   - `ast.Dict` → container `"dict"` + key/value shapes.
   - `ast.Tuple` → container `"tuple"` + element shapes.
   - `ast.Set` → container `"set"` + element shapes.
   - `ast.Name` (variable ref) → returns `None` (silent skip).
   - `ast.Call` / `ast.Attribute` / anything else → returns `None`.
4. **Compatibility rule `_value_matches_shape(value: ValueShape, shape: TypeShape) -> bool`** — strict, with these allowances:
   - `value="NoneType"` matches iff `shape.allow_none`.
   - `value` primitive matches iff `value in shape.literal_types`.
   - `bool` value also matches `int` annotation (Python semantics).
   - Container value matches iff `value.container == shape.container` AND every element value-shape matches the corresponding element type-shape (for `list[T]` / `set[T]` all elements checked vs single T; for `dict[K,V]` keys vs K, values vs V; for `tuple[T,...]` all elements vs T; for `tuple[T1,T2,T3]` positional).
   - Empty container matches any container of the same kind (no element evidence to refute).
   - When `shape.unknown` is True → skip (return True; never flag).
   - When `shape.literal_types` is empty AND no container AND no allow_none AND not unknown → skip (return True; conservative).
5. **Pass `find_type_shape_phantoms(body, index)`** — for each call site successfully parsed via `ast.parse(f"f({kwarg_block})", mode="eval")`, walk `keywords`. For each keyword whose name is accepted by the matched signatures (i.e., NOT already a kwarg phantom), look up the union of param-annotation shapes across all candidates. If ALL candidate annotations exist AND none match the value, emit a `type_shape_mismatch` record. If ANY candidate accepts the value (or has no annotation, or has unknown shape) → no flag (conservative).
6. **Wrapper integration** — `main()` adds type-shape phantoms to the existing `phantoms` list. PowerShell wrapper extends category dispatch to render the new label. No exit-code change.

### Performance

Same single AST walk in `build_index()` extracts annotations alongside param names — additive O(1) per param. Module-level `_INDEX_CACHE` already memoises per src-root; multi-prompt scans reuse the index. Per-call ast-parse on kwarg blocks is ~microseconds for the regex-bounded slice. **Well under the Captain's <2x bound.**

### Backward compatibility

- Existing kwarg phantom records (no `category` field) and method-name phantom records (`category="method_phantom"`) ship unchanged.
- New `type_shape_mismatch` records carry their own category label and additional fields (`value_type`, `expected_types`, `kwarg`).
- `find_kwarg_phantoms()` and `find_method_phantoms()` are not modified beyond the index-shape change. Their existing flagging logic (kwarg-name acceptance, method-name presence) is the gate before type-shape validation runs.
- Existing AD-685 / AD-685b fixtures and live wave runs retain identical behaviour; the helper output simply gains type-shape entries when applicable.

## Implementation

### Section 1 — Extend `build_index()` to capture annotations

In `scripts/phantom_api_ast_helper.py`, modify `_collect_param_names()` to a parallel collector that also returns annotations, and update `build_index()` to record both.

Replace:

```python
def _collect_param_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Collect every accepted parameter name (positional + keyword-only)."""
    args = func.args
    names: list[str] = []
    for a in args.posonlyargs:
        names.append(a.arg)
    for a in args.args:
        names.append(a.arg)
    for a in args.kwonlyargs:
        names.append(a.arg)
    if args.vararg is not None:
        names.append(args.vararg.arg)
    if args.kwarg is not None:
        names.append(args.kwarg.arg)
    return names
```

with a parallel annotations collector. Add this new helper IMMEDIATELY after `_collect_param_names()`:

```python
def _collect_param_annotations(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, ast.AST]:
    """Collect parameter -> annotation AST nodes (only annotated params).

    Mirrors `_collect_param_names()` for positional, keyword-only, and
    *args/**kwargs categories. Unannotated params are omitted (caller treats
    absence as 'no shape constraint' per AD-685c v1 conservative rule).
    """
    args = func.args
    annotations: dict[str, ast.AST] = {}
    for a in args.posonlyargs:
        if a.annotation is not None:
            annotations[a.arg] = a.annotation
    for a in args.args:
        if a.annotation is not None:
            annotations[a.arg] = a.annotation
    for a in args.kwonlyargs:
        if a.annotation is not None:
            annotations[a.arg] = a.annotation
    if args.vararg is not None and args.vararg.annotation is not None:
        annotations[args.vararg.arg] = args.vararg.annotation
    if args.kwarg is not None and args.kwarg.annotation is not None:
        annotations[args.kwarg.arg] = args.kwarg.annotation
    return annotations
```

Then update the inside of `build_index()` to call it. Find:

```python
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                params = _collect_param_names(node)
                index.setdefault(node.name, []).append({
                    "file": str(py_file.relative_to(src_root.parent.parent)
                                  if src_root.parent.parent in py_file.parents
                                  else py_file),
                    "line": node.lineno,
                    "params": params,
                    "accepts_kwargs": _has_var_keyword(node),
                })
```

Replace with:

```python
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                params = _collect_param_names(node)
                annotations = _collect_param_annotations(node)
                index.setdefault(node.name, []).append({
                    "file": str(py_file.relative_to(src_root.parent.parent)
                                  if src_root.parent.parent in py_file.parents
                                  else py_file),
                    "line": node.lineno,
                    "params": params,
                    "param_annotations": annotations,
                    "accepts_kwargs": _has_var_keyword(node),
                })
```

### Section 2 — Add `TypeShape` + `_annotation_to_type_shape`

Add this block IMMEDIATELY after `_extract_class_from_annotation()` (line ~268, before `_is_none_node`):

```python
# ---------------------------------------------------------------------------
# AD-685c: Type-shape validation against kwarg literal values.
# ---------------------------------------------------------------------------

# Primitive Python type names that the validator can resolve from literals.
_PRIMITIVE_TYPE_NAMES = frozenset({"str", "int", "float", "bool", "bytes"})

# Container annotation names → canonical container kind.
_CONTAINER_ANNOTATIONS = {
    "list": "list", "List": "list",
    "dict": "dict", "Dict": "dict",
    "tuple": "tuple", "Tuple": "tuple",
    "set": "set", "Set": "set",
    "frozenset": "set", "FrozenSet": "set",
}


class TypeShape:
    """Structured type-shape extracted from an annotation AST.

    Fields:
      literal_types: primitive type names the annotation accepts.
      allow_none:    True iff `None` is a valid value.
      container:     'list'/'dict'/'tuple'/'set' or None.
      element_shapes: per-element/key/value shapes for containers.
      unknown:       True if any branch references a non-primitive class
                     (validator SKIPs to avoid false positives).
    """

    __slots__ = ("literal_types", "allow_none", "container",
                 "element_shapes", "unknown")

    def __init__(
        self,
        *,
        literal_types: frozenset[str] = frozenset(),
        allow_none: bool = False,
        container: str | None = None,
        element_shapes: tuple["TypeShape", ...] = (),
        unknown: bool = False,
    ) -> None:
        self.literal_types = literal_types
        self.allow_none = allow_none
        self.container = container
        self.element_shapes = element_shapes
        self.unknown = unknown

    def is_skippable(self) -> bool:
        """True if this shape carries no actionable validation evidence."""
        if self.unknown:
            return True
        if self.literal_types or self.container or self.allow_none:
            return False
        return True


_UNKNOWN_SHAPE = TypeShape(unknown=True)
_EMPTY_SHAPE = TypeShape()


def _annotation_to_type_shape(node: ast.AST) -> TypeShape:
    """Resolve an annotation AST node to a TypeShape.

    Handles primitives (str/int/float/bool/bytes), Optional[X], X | None,
    Union[A, B], list[T] / dict[K,V] / tuple[T,...] / set[T]. Any
    unrecognised class name yields a TypeShape(unknown=True) which the
    validator treats as 'skip — cannot validate'.
    """
    if isinstance(node, ast.Constant) and node.value is None:
        return TypeShape(allow_none=True)
    if isinstance(node, ast.Name):
        name = node.id
        if name == "None":
            return TypeShape(allow_none=True)
        if name in _PRIMITIVE_TYPE_NAMES:
            return TypeShape(literal_types=frozenset({name}))
        if name in _CONTAINER_ANNOTATIONS:
            # Bare 'list'/'dict' with no parameter — container kind known,
            # element shapes empty → permissive.
            return TypeShape(container=_CONTAINER_ANNOTATIONS[name])
        # Any other Name (e.g., KnowledgeEdge, MyClass) → unknown.
        return _UNKNOWN_SHAPE
    if isinstance(node, ast.Subscript):
        base = node.value
        if not isinstance(base, ast.Name):
            return _UNKNOWN_SHAPE
        base_name = base.id
        slice_node = node.slice
        if base_name == "Optional":
            inner = _annotation_to_type_shape(slice_node)
            if inner.unknown:
                # Optional[Unknown] still permits None as a known case but
                # we mark unknown to be safe — the inner is unverifiable.
                return TypeShape(
                    literal_types=inner.literal_types,
                    allow_none=True,
                    container=inner.container,
                    element_shapes=inner.element_shapes,
                    unknown=True,
                )
            return TypeShape(
                literal_types=inner.literal_types,
                allow_none=True,
                container=inner.container,
                element_shapes=inner.element_shapes,
            )
        if base_name == "Union":
            return _union_shape(_iter_tuple_elts(slice_node))
        if base_name in _CONTAINER_ANNOTATIONS:
            kind = _CONTAINER_ANNOTATIONS[base_name]
            elts = _iter_tuple_elts(slice_node)
            element_shapes = tuple(_annotation_to_type_shape(e) for e in elts)
            # Container is known even if elements are unknown — permissive
            # at element level; explicit unknown propagates per-element.
            return TypeShape(container=kind, element_shapes=element_shapes)
        return _UNKNOWN_SHAPE
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _union_shape(_flatten_bitor(node))
    return _UNKNOWN_SHAPE


def _iter_tuple_elts(node: ast.AST) -> list[ast.AST]:
    """Return the element list for a subscript slice (Tuple) or single expr."""
    if isinstance(node, ast.Tuple):
        return list(node.elts)
    return [node]


def _flatten_bitor(node: ast.AST) -> list[ast.AST]:
    """Flatten nested `A | B | C` BinOp chain to a list of leaf nodes."""
    leaves: list[ast.AST] = []

    def _walk(n: ast.AST) -> None:
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr):
            _walk(n.left)
            _walk(n.right)
        else:
            leaves.append(n)

    _walk(node)
    return leaves


def _union_shape(branches: list[ast.AST]) -> TypeShape:
    """Combine N branch annotations into a single union TypeShape."""
    literal_types: set[str] = set()
    allow_none = False
    container: str | None = None
    element_shapes: tuple[TypeShape, ...] = ()
    unknown = False
    for b in branches:
        sub = _annotation_to_type_shape(b)
        if sub.allow_none:
            allow_none = True
        if sub.literal_types:
            literal_types.update(sub.literal_types)
        if sub.container is not None:
            if container is not None and container != sub.container:
                # Mixed-container union (e.g., list[X] | dict[K,V]) — too
                # complex to validate element-wise in v1; mark unknown.
                unknown = True
            else:
                container = sub.container
                element_shapes = sub.element_shapes
        if sub.unknown:
            unknown = True
    return TypeShape(
        literal_types=frozenset(literal_types),
        allow_none=allow_none,
        container=container,
        element_shapes=element_shapes,
        unknown=unknown,
    )
```

### Section 3 — Add value classifier + compatibility check

Append IMMEDIATELY after the `_union_shape` function added in Section 2:

```python
class ValueShape:
    """Structured shape extracted from a kwarg value AST.

    Mirrors TypeShape but populated from a concrete literal expression.
    Returned None means 'cannot resolve' (variable refs, calls, bytes,
    anything non-static); the validator silently skips such kwargs.
    """

    __slots__ = ("primitive", "container", "element_shapes")

    def __init__(
        self,
        *,
        primitive: str | None = None,
        container: str | None = None,
        element_shapes: tuple["ValueShape", ...] = (),
    ) -> None:
        self.primitive = primitive  # 'str'/'int'/'float'/'bool'/'NoneType' or None
        self.container = container
        self.element_shapes = element_shapes


def _value_to_shape(node: ast.AST) -> ValueShape | None:
    """Classify a kwarg value AST. Returns None when not statically resolvable.

    bytes literals return None per AD-685c v1 spec ('skipped on bytes/bytes-like
    — cannot resolve'). Variable refs, calls, attribute accesses also return
    None (the validator silently skips these kwargs).
    """
    if isinstance(node, ast.Constant):
        v = node.value
        if v is None:
            return ValueShape(primitive="NoneType")
        if isinstance(v, bool):
            return ValueShape(primitive="bool")
        if isinstance(v, int):
            return ValueShape(primitive="int")
        if isinstance(v, float):
            return ValueShape(primitive="float")
        if isinstance(v, str):
            return ValueShape(primitive="str")
        if isinstance(v, bytes):
            return None  # Captain spec: bytes-like → skip.
        return None
    if isinstance(node, ast.List):
        return ValueShape(
            container="list",
            element_shapes=tuple(s for s in (_value_to_shape(e) for e in node.elts) if s is not None),
        )
    if isinstance(node, ast.Set):
        return ValueShape(
            container="set",
            element_shapes=tuple(s for s in (_value_to_shape(e) for e in node.elts) if s is not None),
        )
    if isinstance(node, ast.Tuple):
        return ValueShape(
            container="tuple",
            element_shapes=tuple(s for s in (_value_to_shape(e) for e in node.elts) if s is not None),
        )
    if isinstance(node, ast.Dict):
        keys = tuple(s for s in (_value_to_shape(k) for k in node.keys if k is not None) if s is not None)
        vals = tuple(s for s in (_value_to_shape(v) for v in node.values) if s is not None)
        # Encode dict as element_shapes = (key_shape*, value_shape*).
        return ValueShape(container="dict", element_shapes=keys + vals)
    return None


def _value_matches_shape(value: ValueShape, shape: TypeShape) -> bool:
    """True iff the concrete value is compatible with the annotation shape.

    Conservative — when the shape is skippable (unknown/empty), return True
    so the validator does not flag. False is reserved for clear mismatches.
    """
    if shape.is_skippable():
        return True
    if value.primitive == "NoneType":
        return shape.allow_none
    if value.container is not None:
        if shape.container is None:
            return False
        if value.container != shape.container:
            return False
        # Permissive when annotation has no element shapes (bare 'list').
        if not shape.element_shapes:
            return True
        if value.container in ("list", "set"):
            elem_shape = shape.element_shapes[0]
            return all(_value_matches_shape(e, elem_shape) for e in value.element_shapes)
        if value.container == "tuple":
            # tuple[T, ...] ellipsis form → annotation has 1 elem shape;
            # tuple[T1, T2] → matched positionally. v1: if 1 element shape
            # AND value has multiple elements, treat as homogeneous (T, ...).
            if len(shape.element_shapes) == 1:
                elem_shape = shape.element_shapes[0]
                return all(_value_matches_shape(e, elem_shape) for e in value.element_shapes)
            if len(shape.element_shapes) != len(value.element_shapes):
                return False
            return all(_value_matches_shape(e, s)
                       for e, s in zip(value.element_shapes, shape.element_shapes))
        if value.container == "dict":
            # element_shapes is (key_shape*, value_shape*) for the value;
            # annotation is (key_shape, value_shape). Empty dict → True.
            if not value.element_shapes:
                return True
            if len(shape.element_shapes) != 2:
                return True  # Bare 'dict' annotation → permissive.
            key_shape, val_shape = shape.element_shapes
            half = len(value.element_shapes) // 2
            keys = value.element_shapes[:half]
            vals = value.element_shapes[half:]
            if not all(_value_matches_shape(k, key_shape) for k in keys):
                return False
            if not all(_value_matches_shape(v, val_shape) for v in vals):
                return False
            return True
        return False
    # Primitive value.
    if value.primitive is None:
        return True  # Unresolvable → don't flag.
    if value.primitive in shape.literal_types:
        return True
    # Python: bool is an int subclass → bool literal matches int annotation.
    if value.primitive == "bool" and "int" in shape.literal_types:
        return True
    return False
```

### Section 4 — Add `find_type_shape_phantoms`

Append IMMEDIATELY after `_value_matches_shape` from Section 3:

```python
def find_type_shape_phantoms(
    body: str, index: dict[str, list[dict]],
) -> list[dict]:
    """Scan body for kwarg literals whose type mismatches the annotation.

    For each call-site whose kwarg name IS valid against the live signature
    index (i.e., not already a kwarg phantom), parse the value AST and
    check it against the union of param-annotation shapes across matching
    candidates. Flag iff every candidate has an annotation AND none match
    the value.
    """
    phantoms: list[dict] = []
    for match in _CALL_RE.finditer(body):
        receiver = match.group(1)
        method = match.group(2)
        kwarg_block = match.group(3)
        if receiver in _NOISY_RECEIVER_TOKENS:
            continue
        if method in _NOISY_METHODS:
            continue
        candidates = index.get(method)
        if not candidates:
            continue
        # If any candidate accepts **kwargs, type-shape can't be checked
        # (kwarg name is permissively accepted; annotation is unknown).
        if any(c["accepts_kwargs"] for c in candidates):
            continue
        # Re-parse the kwarg block as a call expression to get value ASTs.
        try:
            expr = ast.parse(f"_f({kwarg_block})", mode="eval")
        except SyntaxError:
            continue
        if not isinstance(expr.body, ast.Call):
            continue
        for keyword in expr.body.keywords:
            kwarg_name = keyword.arg
            if kwarg_name is None:
                # **kwargs spread — skip, can't validate.
                continue
            value_shape = _value_to_shape(keyword.value)
            if value_shape is None:
                continue
            # Collect every candidate that accepts this kwarg AND has an
            # annotation for it. If at least one such candidate exists and
            # NONE match the value, flag.
            applicable_shapes: list[TypeShape] = []
            for c in candidates:
                if kwarg_name not in c["params"]:
                    continue
                ann = c.get("param_annotations", {}).get(kwarg_name)
                if ann is None:
                    # Untyped param → permissive across this candidate.
                    applicable_shapes = []
                    break
                applicable_shapes.append(_annotation_to_type_shape(ann))
            if not applicable_shapes:
                continue
            if any(_value_matches_shape(value_shape, s) for s in applicable_shapes):
                continue
            expected = sorted({
                t for s in applicable_shapes for t in s.literal_types
            })
            value_label = (
                value_shape.primitive
                if value_shape.primitive is not None
                else (value_shape.container or "unknown")
            )
            call_site = f"{receiver}.{method}({kwarg_block.strip()})"
            phantoms.append({
                "call_site": call_site,
                "method": method,
                "kwarg": kwarg_name,
                "value_type": value_label,
                "expected_types": expected,
                "category": "type_shape_mismatch",
                "candidates": candidates[:5],
            })
    return phantoms
```

### Section 5 — Wire into `main()`

Find this block in `main()`:

```python
    kwarg_phantoms = find_kwarg_phantoms(body, index)
    method_phantoms, unresolved = find_method_phantoms(
        body,
        class_methods,
        runtime_attrs,
        runtime_conflicts,
        pattern_b_vars,
        pattern_b_unresolved,
    )

    print(json.dumps({
        "phantoms": kwarg_phantoms + method_phantoms,
        "unresolved": unresolved,
    }), flush=True)
    return 0
```

Replace with:

```python
    kwarg_phantoms = find_kwarg_phantoms(body, index)
    method_phantoms, unresolved = find_method_phantoms(
        body,
        class_methods,
        runtime_attrs,
        runtime_conflicts,
        pattern_b_vars,
        pattern_b_unresolved,
    )
    type_shape_phantoms = find_type_shape_phantoms(body, index)

    print(json.dumps({
        "phantoms": kwarg_phantoms + method_phantoms + type_shape_phantoms,
        "unresolved": unresolved,
    }), flush=True)
    return 0
```

### Section 6 — Wrapper category dispatch

In `scripts/phantom-api-precheck.ps1`, find the helper-output dispatch block:

```powershell
                foreach ($p in $parsed.phantoms) {
                    if ($p.category -eq 'method_phantom') {
                        [void]$phantomsHere.Add(@{
                            Symbol = "$($p.resolved_class).$($p.method)(...)"
                            Category = 'method_phantom'
                            CallSite = $p.call_site
                        })
                    } else {
                        [void]$phantomsHere.Add(@{
                            Symbol = "$($p.method)($($p.kwarg)=...)"
                            Category = 'kwarg_mismatch'
                            CallSite = $p.call_site
                        })
                    }
                }
```

Replace with (adds the third branch):

```powershell
                foreach ($p in $parsed.phantoms) {
                    if ($p.category -eq 'method_phantom') {
                        [void]$phantomsHere.Add(@{
                            Symbol = "$($p.resolved_class).$($p.method)(...)"
                            Category = 'method_phantom'
                            CallSite = $p.call_site
                        })
                    } elseif ($p.category -eq 'type_shape_mismatch') {
                        $expected = ($p.expected_types -join '|')
                        if (-not $expected) { $expected = '<unknown>' }
                        [void]$phantomsHere.Add(@{
                            Symbol = "$($p.method)($($p.kwarg)=<$($p.value_type)> -> expected <$expected>)"
                            Category = 'type_shape_mismatch'
                            CallSite = $p.call_site
                        })
                    } else {
                        [void]$phantomsHere.Add(@{
                            Symbol = "$($p.method)($($p.kwarg)=...)"
                            Category = 'kwarg_mismatch'
                            CallSite = $p.call_site
                        })
                    }
                }
```

## Tests

NEW file `tests/test_ad685c_phantom_type_shape.py`. Tests load the helper as a module via `importlib` (the helper lives outside `src/probos/`, so a sys.path insertion is needed). They build synthetic `tmp_path` source trees + invoke pure helper functions directly — no PowerShell required.

Test plan (12 tests, over the 10 floor by 2):

1. **`test_value_to_shape_primitives`** — `_value_to_shape` correctly classifies `42`/`"hi"`/`3.14`/`True`/`None` to int/str/float/bool/NoneType; bytes literal returns None; `ast.Name` ref returns None.
2. **`test_annotation_to_type_shape_primitives`** — `name: str` → literal_types={"str"}, allow_none=False; `count: int` → {"int"}; bare `Foo` → unknown=True.
3. **`test_annotation_to_type_shape_optional`** — `Optional[str]` and `str | None` and `None | str` all yield {"str"}+allow_none.
4. **`test_annotation_to_type_shape_union`** — `int | str` → {"int", "str"}; `Union[int, float]` → {"int", "float"}.
5. **`test_annotation_to_type_shape_containers`** — `list[str]` → container=list elem_shape={"str"}; bare `list` → container=list element_shapes=(); `dict[str, int]` → container=dict element_shapes=(K,V).
6. **`test_match_str_to_str_no_phantom`** — write `def f(name: str) -> None: ...`, build_index, run `find_type_shape_phantoms` on `obj.f(name="hi")` → no phantoms.
7. **`test_mismatch_int_to_str_flagged`** — same fixture, body `obj.f(name=42)` → 1 phantom with category=type_shape_mismatch, value_type=int, expected_types=["str"].
8. **`test_none_optional_match_and_mismatch`** — `def g(name: str | None) -> None: ...`: `g(name=None)` no phantom. `def h(name: str) -> None`: `h(name=None)` flagged with value_type="NoneType".
9. **`test_list_str_match_and_mismatch`** — `def k(tags: list[str]) -> None`: `k(tags=["a","b"])` no phantom; `k(tags=[1,2])` flagged.
10. **`test_variable_ref_skipped_silently`** — `obj.f(name=some_var)` → no phantom (not flagged as mismatch).
11. **`test_bytes_literal_skipped`** — `def m(payload: int) -> None`: `obj.m(payload=b"abc")` → no phantom (bytes-like cannot resolve).
12. **`test_union_int_str_accepts_int`** — `def u(value: int | str) -> None`: `obj.u(value=42)` no phantom; `obj.u(value=3.14)` flagged.
13. **`test_unknown_class_annotation_skipped`** — `def w(item: KnowledgeEdge) -> None`: any kwarg value is permitted (shape.unknown → True).
14. **`test_backward_compat_kwarg_phantom_unchanged`** — `def f(name: str) -> None`: body asserting `obj.f(other=1)` → existing kwarg phantom emitted (no `category` field) — proves AD-685 v1 path preserved.
15. **`test_backward_compat_method_phantom_unchanged`** — assert that with no type-shape input, `find_method_phantoms` continues to emit `method_phantom` records as before (smoke).
16. **`test_self_test_clean_on_this_prompt`** — invoke the **wrapper** `pwsh ./scripts/phantom-api-precheck.ps1 prompts/ad-685c-phantom-type-shape-v1.md` via subprocess; assert exit code is 0 (or that any non-zero exit is documented as expected FPs introduced by the prompt). This is the Captain's required self-test.

(Tests 14–16 may collapse if test count drifts above 12; floor is 10 + Captain's required self-test = 11 effective.)

## What this AD does NOT change

- No dataclass / Pydantic field-name typo detection — that is **AD-685d** (Wave 47).
- No type-shape on **return** values — separate AD if ever needed.
- No runtime introspection — strictly AST-static. Unknown class annotations (e.g., `KnowledgeEdge`, `Episode`) are SKIPPED, not validated.
- No new directory layout. The existing single-file helper grows by ~200 lines.
- No exit-code semantics change (`type_shape_mismatch` candidates flow into the same `phantoms` list and contribute to non-zero exit per existing rule).
- No PowerShell `$STDLIB_PREFIXES` / `$DOC_FILE_PATTERN` change.

## Verified Against Codebase (2026-05-04, HEAD `c33c38d`)

```
ls scripts/phantom-api-precheck.ps1
  scripts/phantom-api-precheck.ps1   (393 lines)
ls scripts/phantom_api_ast_helper.py
  scripts/phantom_api_ast_helper.py  (~620 lines)
ls scripts/phantom-api-precheck/
  Get-ChildItem: Cannot find path 'D:\ProbOS\scripts\phantom-api-precheck\' because it does not exist.

grep -n "def build_index" scripts/phantom_api_ast_helper.py
  120: def build_index(src_root: Path) -> dict[str, list[dict]]:

grep -n "def _collect_param_names" scripts/phantom_api_ast_helper.py
  152: def _collect_param_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:

grep -n "def find_kwarg_phantoms" scripts/phantom_api_ast_helper.py
  190: def find_kwarg_phantoms(body: str, index: dict[str, list[dict]]) -> list[dict]:

grep -n "def _extract_class_from_annotation" scripts/phantom_api_ast_helper.py
  237: def _extract_class_from_annotation(node: ast.AST) -> str | None:

grep -n "def find_method_phantoms" scripts/phantom_api_ast_helper.py
  445: def find_method_phantoms(

grep -n "def main" scripts/phantom_api_ast_helper.py
  555: def main(argv: list[str] | None = None) -> int:

grep -n "kwarg_phantoms = find_kwarg_phantoms" scripts/phantom_api_ast_helper.py
  592:     kwarg_phantoms = find_kwarg_phantoms(body, index)

grep -nE 'category.*method_phantom|category.*kwarg_mismatch' scripts/phantom-api-precheck.ps1
  274:                        if ($p.category -eq 'method_phantom') {
  281:                        Category = 'method_phantom'
  287:                        Category = 'kwarg_mismatch'

ls tests/test_*phantom* tests/test_*ad685* tests/test_*precheck*
  (no matches)
```

(Line numbers are approximate; surrounding context anchors in the SEARCH/REPLACE blocks above are the source of truth.)

## Tracking

- `PROGRESS.md` — prepend AD-685c v1 CLOSED entry (post-build).
- `docs/development/roadmap.md` — flip AD-685c row to Complete.
- `DECISIONS.md` — append AD-685c entry under Era V (existing AD-685 / AD-685b precedent).
- GH issue **#406** — close (note: EMU 403 may block; user closes manually).

## Acceptance Criteria

1. All 12 (or floor 10) new tests pass at `tests/test_ad685c_phantom_type_shape.py`.
2. Full test gate `pytest tests/ -q -n 8 --dist=loadfile` shows **no regressions** vs Wave 45 baseline 11106 (expected 11116-11118).
3. Self-test: `pwsh ./scripts/phantom-api-precheck.ps1 prompts/ad-685c-phantom-type-shape-v1.md` runs without error. Any phantom candidates emitted are documented in the build report as introduced-by-prompt FPs.
4. Existing AD-685 kwarg phantom records and AD-685b method-name phantom records continue to ship in their original shape (no `category` field on kwarg records, `category="method_phantom"` on method records).
5. No regression in performance — helper-level smoke shows index build remains <2s on full `src/probos/` tree (wall-clock budget the existing wave runs already meet).
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
