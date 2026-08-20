"""BF-798: a cache hit must not replay a previous turn's provenance.

The AD-272 decision cache stored the whole decision dict, so a hit could bind a
Captain-visible claim to a PREVIOUS turn's tool trace. AD-1248's
``_cacheable_decision`` projection fixed it at one of three cache writes; this
pins the property at all of them, and pins the enumeration so a fourth write
cannot be added without a decision.
"""

from __future__ import annotations

import ast
import pathlib

from probos.cognitive.cognitive_agent import (
    _PER_RUN_PROVENANCE_KEYS,
    _cacheable_decision,
)

_SOURCE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src" / "probos" / "cognitive" / "cognitive_agent.py"
)


def test_the_projection_drops_every_per_run_key() -> None:
    decision = {
        "action": "execute",
        "llm_output": "the answer",
        "_tool_trace_ref": "sha256:deadbeef",
        "_dm_tool_failures": object(),
    }

    cached = _cacheable_decision(decision)

    assert cached == {"action": "execute", "llm_output": "the answer"}
    for key in _PER_RUN_PROVENANCE_KEYS:
        assert key not in cached


def test_the_projection_does_not_mutate_the_live_decision() -> None:
    """The turn still needs its own provenance after it is cached."""
    decision = {"llm_output": "x", "_tool_trace_ref": "sha256:beef"}

    _cacheable_decision(decision)

    assert decision["_tool_trace_ref"] == "sha256:beef"


def test_a_decision_with_no_provenance_is_unchanged() -> None:
    decision = {"action": "execute", "llm_output": "x"}
    assert _cacheable_decision(decision) == decision


def _decision_cache_writes() -> list[tuple[int, ast.expr]]:
    """Every ``cache[cache_key] = (...)`` assignment, with its first element."""
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    writes: list[tuple[int, ast.expr]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Tuple):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == "cache"
                and isinstance(target.slice, ast.Name)
                and target.slice.id == "cache_key"
            ):
                writes.append((node.lineno, node.value.elts[0]))
    return writes


def _is_projection_call(node: ast.expr) -> bool:
    """Exactly ``_cacheable_decision(...)`` -- not merely starting with it.

    A prefix match on the unparsed source accepts
    ``_cacheable_decision(x) or x`` and
    ``_cacheable_decision(x) if flag else x``, both of which can store the
    unprojected dict. Review caught the prefix version doing exactly that.
    """
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_cacheable_decision"
    )


def test_every_decision_cache_write_goes_through_the_projection() -> None:
    """An INVENTORY check over the three known writers, not a containment proof.

    Two of the three cache a chain result, which cannot carry provenance today:
    ``_attach_run_provenance`` is the only writer of it and only the agentic
    path calls it, and review separately confirmed no in-tree chain method
    copies the observation. That is a fact about today's call graph, not a
    guarantee -- generated agents may override those methods -- which is why
    every write projects rather than only the one that needs it.

    What this does NOT do is prevent a fourth writer. It matches
    ``cache[cache_key] = (...)`` with those exact names; an alias, an
    ``update()``, or a ``setdefault()`` would not be seen. Enforcing that would
    need the storage encapsulated behind a method, which is a larger change
    than this issue justifies. Stated so the guard is not mistaken for one.
    """
    writes = _decision_cache_writes()

    assert writes, "found no decision-cache write at all -- the scan is broken"

    ungated = [
        f"cognitive_agent.py:{lineno} caches {ast.unparse(expr)}"
        for lineno, expr in writes
        if not _is_projection_call(expr)
    ]
    assert not ungated, (
        "every decision-cache write must project out per-run provenance, or a "
        f"cache hit can replay a previous turn's tool trace: {ungated}"
    )


def test_the_guard_rejects_a_conditional_that_can_store_the_raw_dict() -> None:
    """The prefix-match weakness review found, pinned as its own case.

    ``_cacheable_decision(x) or x`` and the ternary form both START with the
    projection call and both store the unprojected dict on one branch. An
    exact call-node match is what rejects them.
    """
    for source in (
        "cache[cache_key] = (_cacheable_decision(d) or d, t, ttl)",
        "cache[cache_key] = (_cacheable_decision(d) if flag else d, t, ttl)",
    ):
        element = ast.parse(source).body[0].value.elts[0]  # type: ignore[attr-defined]
        assert not _is_projection_call(element), source

    exact = ast.parse("cache[cache_key] = (_cacheable_decision(d), t, ttl)")
    assert _is_projection_call(exact.body[0].value.elts[0])  # type: ignore[attr-defined]
