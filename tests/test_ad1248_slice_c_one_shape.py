"""AD-1248 slice C groundwork: the crew execution record has ONE shape.

The persisted ``crew_execution`` record was declared THREE times: byte-identical
named copies in ``crew_session`` and ``crew_finalizer``, plus an INLINE 14-key
literal in ``crew_executor``'s resume path. Five exact-key guards compare
against it and raise on any mismatch.

That is what makes adding a field here an all-or-nothing landing. Worse, the
executor's rejection is converted to ``child_execution_integrity``, which blocks
the whole crew session rather than failing one child -- so a writer that added a
field would take the session down on resume rather than degrade.

Slice C has to add ``tool_failures`` to this record, so the shape is
consolidated first, as a separate behaviour-preserving change.

The census below is an AST scan, not a regex. A regex over ``crew_*.py`` found
only the two NAMED copies and reported "exactly four sites" -- the inline
literal in the executor was invisible to it, which is exactly how it survived.
"""

from __future__ import annotations

import ast
import importlib
import itertools
import pathlib
import subprocess
import sys

import pytest

from probos.crew_utils import CREW_EXECUTION_KEYS

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "probos"
TESTS = REPO / "tests"

#: The one name every exact-key guard must dereference.
CANONICAL_NAME = "CREW_EXECUTION_KEYS"

#: The needle the census searches for -- taken FROM the contract, not restated.
#:
#: An independent literal here would be one more copy to update, and this file
#: exists to remove those. The literal is pinned in exactly one place,
#: ``tests/test_bf680_token_usage_fallback.py``, which
#: :func:`test_the_shape_literal_is_pinned_in_exactly_one_test` enforces.
EXPECTED_SHAPE = frozenset(CREW_EXECUTION_KEYS)

#: The single test permitted to restate the shape as a literal.
SHAPE_PIN = "tests/test_bf680_token_usage_fallback.py"


def _string_containers(node: ast.AST) -> frozenset[str] | None:
    """The plain-string elements of a set/list/tuple literal, if it is one."""
    if not isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        return None
    elts = node.elts
    if not elts:
        return None
    if not all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in elts):
        return None
    return frozenset(e.value for e in elts)  # type: ignore[attr-defined]


def _string_set_literals(tree: ast.AST) -> list[tuple[int, frozenset[str]]]:
    """Every literal that yields a SET of plain strings, with its line number.

    Covers ``{...}``, ``frozenset({...})``, ``set([...])``, ``frozenset([...])``
    and ``set((...))``. A regex census missed an inline copy once already, and
    a narrower AST census would still miss the list and tuple spellings -- a
    validator can regain a private copy in any of them.

    A plain dict literal with these keys is deliberately NOT matched: the record
    PRODUCER necessarily builds that payload, so matching it would flag the
    producer as a duplicate contract.

    **This census is a secondary defence and is deliberately not claimed to be
    exhaustive.** Adversarial review enumerated spellings it does not see --
    ``frozenset({"version": None, ...})``, ``FIELDS = (...)`` then
    ``set(FIELDS)``, ``set("version parent_id ...".split())``, ``{...} | {...}``
    and ``{*(...)}``. Chasing every spelling is unwinnable. The load-bearing
    guard is :func:`test_every_production_guard_compares_against_the_canonical_object`,
    which reads what the validators actually COMPARE AGAINST, so a private copy
    in any spelling fails there whether or not the census recognises it.
    """
    found: list[tuple[int, frozenset[str]]] = []
    inner: set[int] = set()

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"set", "frozenset"}
            and len(node.args) == 1
        ):
            literal = _string_containers(node.args[0])
            if literal is not None:
                inner.add(id(node.args[0]))
                found.append((getattr(node, "lineno", 0), literal))

    for node in ast.walk(tree):
        if isinstance(node, ast.Set) and id(node) not in inner:
            literal = _string_containers(node)
            if literal is not None:
                found.append((getattr(node, "lineno", 0), literal))

    return found


def _reads_crew_execution(node: ast.AST) -> bool:
    """Does this expression pull a value out of ``crew_execution`` metadata?"""
    constants = [n.value for n in ast.walk(node) if isinstance(n, ast.Constant)]
    if "crew_execution" not in constants:
        return False
    return any(
        (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get")
        or isinstance(n, ast.Subscript)
        for n in ast.walk(node)
    )


def _exact_key_guards(tree: ast.AST) -> list[tuple[int, str, list[str]]]:
    """``(lineno, function, comparator sources)`` for every exact-key guard.

    A guard is a comparison whose left operand is ``set(x)``/``frozenset(x)``
    where ``x`` was read out of ``crew_execution`` metadata in the same
    function. That is the shape all five production guards take, and it is what
    decides whether a persisted record is accepted on resume.
    """
    guards: list[tuple[int, str, list[str]]] = []

    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        tainted: set[str] = set()
        for node in ast.walk(fn):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if _reads_crew_execution(node.value):
                    tainted.update(t.id for t in targets if isinstance(t, ast.Name))

        for node in ast.walk(fn):
            if not isinstance(node, ast.Compare):
                continue
            left = node.left
            if (
                isinstance(left, ast.Call)
                and isinstance(left.func, ast.Name)
                and left.func.id in {"set", "frozenset"}
                and len(left.args) == 1
                and isinstance(left.args[0], ast.Name)
                and left.args[0].id in tainted
            ):
                guards.append(
                    (node.lineno, fn.name, [ast.unparse(c) for c in node.comparators])
                )

    return guards


def test_every_production_guard_compares_against_the_canonical_object() -> None:
    """What the validators DEREFERENCE, not what the module happens to import.

    This is the load-bearing guard of this file. Review showed the literal
    census can be walked past in half a dozen spellings, and that a module
    could keep an unused canonical import while validating against a private
    copy -- leaving every identity assertion green and the whole-session
    restart rejection quietly back in place.

    So: read each guard's comparator. It must be the canonical NAME. Then
    import each module that owns a guard -- enumerated from this scan, never
    hardcoded, so a guard added in a new module is covered the day it lands --
    and prove that name resolves to the one object.
    """
    from probos.crew_utils import CREW_EXECUTION_KEYS as canonical

    located: list[str] = []
    wrong: list[str] = []
    modules: set[str] = set()

    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(REPO).as_posix()
        dotted = "probos." + ".".join(path.relative_to(SRC).with_suffix("").parts)
        for lineno, fn_name, comparators in _exact_key_guards(tree):
            located.append(f"{rel}:{lineno} [{fn_name}]")
            modules.add(dotted)
            for comparator in comparators:
                if comparator != CANONICAL_NAME and not comparator.endswith(
                    f".{CANONICAL_NAME}"
                ):
                    wrong.append(f"{rel}:{lineno} [{fn_name}] -> {comparator}")

    # A scan that finds nothing passes every assertion below it. Fail instead.
    assert located, (
        "found no exact-key crew_execution guard at all -- the scan no longer "
        "matches production, so everything below it is vacuous"
    )

    assert not wrong, (
        f"every crew_execution exact-key guard must compare against "
        f"{CANONICAL_NAME}; these compare against something else, which is how "
        f"a private copy silently returns: {wrong}"
    )

    for dotted in sorted(modules):
        module = importlib.import_module(dotted)
        assert getattr(module, CANONICAL_NAME, None) is canonical, (
            f"{dotted} guards on {CANONICAL_NAME} but its {CANONICAL_NAME} is "
            "not the canonical object -- it shadows the contract locally"
        )


def test_the_execution_shape_is_declared_exactly_once_in_production() -> None:
    """An AST scan over ALL of src/probos, not a regex over crew_*.py.

    A literal anywhere is a second copy of the contract, whether or not it is
    bound to a name a search would recognise.
    """
    copies: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for lineno, literal in _string_set_literals(tree):
            if literal == EXPECTED_SHAPE:
                copies.append(f"{path.relative_to(REPO).as_posix()}:{lineno}")

    assert len(copies) == 1, (
        "the crew_execution shape must have exactly ONE literal declaration in "
        f"production; found {copies}"
    )
    assert copies[0].startswith("src/probos/crew_utils.py:"), copies


def test_the_shape_literal_is_pinned_in_exactly_one_test() -> None:
    """The suite restates the shape ONCE, as a deliberate pin.

    Production consolidation is only half the landing. THREE test files held
    their own copies of the key list -- ``test_ad1141_crew_loop_sigma``,
    ``test_ad1142_crew_child_compaction`` and ``test_ad1155_loop_until_done``
    -- none of which a scan over ``src`` could see. A field added to the record
    had to land in all of them in the same commit or the suite broke, which is
    the same all-or-nothing trap, one layer over.

    One literal pin is kept on purpose: if every test compared against the
    imported constant, the suite would assert the record matches whatever the
    constant currently says, and a wrong edit to the constant would pass
    everywhere.
    """
    copies: list[str] = []
    for path in sorted(TESTS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for lineno, literal in _string_set_literals(tree):
            if literal == EXPECTED_SHAPE:
                copies.append(f"{path.relative_to(REPO).as_posix()}:{lineno}")

    assert len(copies) == 1, (
        "the suite must restate the crew_execution shape exactly once, as the "
        f"pin in {SHAPE_PIN}; every other test imports {CANONICAL_NAME}. "
        f"Found {copies}"
    )
    assert copies[0].startswith(f"{SHAPE_PIN}:"), copies


def test_every_module_that_validates_the_shape_uses_the_one_constant() -> None:
    """Enumerated by import, not by reading source."""
    from probos.cognitive.crew_executor import CREW_EXECUTION_KEYS as executor_keys
    from probos.cognitive.crew_finalizer import CREW_EXECUTION_KEYS as finalizer_keys
    from probos.crew_utils import CREW_EXECUTION_KEYS as canonical

    assert finalizer_keys is canonical
    assert executor_keys is canonical


def test_the_shape_is_unchanged_by_the_consolidation() -> None:
    """Behaviour-preserving: still a frozenset, still re-exported here.

    The KEY COUNT is deliberately not re-asserted -- it is pinned once, in
    ``test_bf680_token_usage_fallback``. Four separate count assertions were
    part of what made adding a field an all-or-nothing edit.
    """
    from probos.cognitive.crew_session import CREW_EXECUTION_KEYS as re_exported

    assert isinstance(re_exported, frozenset)


_GUARD_MODULES = (
    "probos.cognitive.crew_session",
    "probos.cognitive.crew_finalizer",
    "probos.cognitive.crew_executor",
)
_IMPORT_ORDERS = list(itertools.permutations(_GUARD_MODULES))
_IMPORT_ORDER_IDS = [
    "-".join(name.rsplit(".", 1)[-1] for name in order) for order in _IMPORT_ORDERS
]


@pytest.mark.parametrize("order", _IMPORT_ORDERS, ids=_IMPORT_ORDER_IDS)
def test_every_import_order_yields_one_object_in_a_fresh_interpreter(
    order: tuple[str, ...],
) -> None:
    """A FRESH process per ORDER, importing all three -- not one each.

    Two earlier versions read stronger than they were. The first called
    ``importlib.import_module`` in-process, after other tests had already
    imported all three, so it only read ``sys.modules``. The second spawned a
    process per module but imported just that one module, which cannot observe
    an order-dependent rebinding at all; review caught it. Import every module,
    in every order, and assert identity inside the child.
    """
    program = (
        "import importlib\n"
        f"names = {list(order)!r}\n"
        "modules = [importlib.import_module(name) for name in names]\n"
        "canonical = importlib.import_module('probos.crew_utils').CREW_EXECUTION_KEYS\n"
        "assert all(m.CREW_EXECUTION_KEYS is canonical for m in modules), names\n"
        "print('OK')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"import order {order} failed:\n{proc.stderr[-2000:]}"
    )
    assert "OK" in proc.stdout


def test_every_exact_key_validator_shares_one_contract() -> None:
    """All five guards dereference the SAME object.

    Deliberately NOT called "adding a field is one edit" -- review proved that
    overclaims. Extending this contract updates every VALIDATOR, but the record
    is also BUILT by ``_build_execution_evidence`` in ``crew_executor``, and a
    builder that does not emit the new field still produces a 14-key record
    that the widened guard then rejects. Slice C must change both.
    """
    from probos.cognitive import crew_executor, crew_finalizer, crew_session

    shared = {
        id(crew_session.CREW_EXECUTION_KEYS),
        id(crew_finalizer.CREW_EXECUTION_KEYS),
        id(crew_executor.CREW_EXECUTION_KEYS),
    }
    assert len(shared) == 1, (
        "the three validating modules must share ONE object, or a field added "
        "to the writer fails resume against whichever copy lagged"
    )


def test_the_record_builder_emits_exactly_the_contract() -> None:
    """The producer side of the same contract.

    Review found `_build_execution_evidence` rebuilds the record during
    recovery validation, so a widened key set with an unchanged builder yields
    `crew_recovery_plan_runtime_invalid`. Pinning the builder's output here
    means slice C sees the producer half fail immediately rather than
    discovering it through a blocked session.
    """
    from types import SimpleNamespace

    from probos.cognitive.crew_executor import _build_execution_evidence
    from probos.crew_utils import CREW_EXECUTION_KEYS

    record = _build_execution_evidence(
        parent_id="p1",
        child=SimpleNamespace(id="c1", assigned_to="ezri", spec_id="s1"),
        thread_id="t1",
        status="done",
        stopped_reason="complete",
        output="the output",
        tool_trace_ref=None,
        artifact_refs=[],
        actual_tokens=10,
        started_at=1.0,
        finished_at=2.0,
        blocked_dependency_ids=[],
    )

    assert set(record) == set(CREW_EXECUTION_KEYS), (
        "the builder must emit exactly the contract; "
        f"missing={set(CREW_EXECUTION_KEYS) - set(record)} "
        f"extra={set(record) - set(CREW_EXECUTION_KEYS)}"
    )
