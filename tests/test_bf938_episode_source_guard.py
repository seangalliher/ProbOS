"""BF-938 (#1680) M1: every episode source production writes is one AD-607's provenance check knows.

``KNOWN_MEMORY_SOURCES`` is the allowlist behind ``enforce_provenance``, which the supported profile arms: a recalled
episode whose source is not in it is reported, and dropped when the flag is armed. Before BF-938 the set lacked four
MemorySource values and seven labels production writes. This guard enumerates every ``Episode(`` construction under
src/probos with the AST, resolves each ``source`` it can write, and fails when one is missing from the set.

Forms resolved: no ``source=`` (the dataclass default); a string literal; ``MemorySource.X`` or
``MemorySource.X.value``; a local name the enclosing function assigns only from those forms; ``Episode(**payload)``,
whose labels are the ``"source"`` keys of the dict literals in its declared feeder functions. Any other expression
must be in _COMPUTED, with the reason it only copies a label an enumerated producer wrote. Not enumerated:
``dataclasses.replace(ep, source=...)``, which copies an existing episode's label (episodic.py's content-hash
normalisation). The first test asserts the premises, so the guard cannot pass by finding nothing.
"""

from __future__ import annotations

import ast
import functools
from dataclasses import dataclass, fields
from pathlib import Path

import pytest

from probos.cognitive.memory_security import KNOWN_MEMORY_SOURCES, validate_provenance
from probos.types import Episode, MemorySource

_SRC = Path(__file__).resolve().parents[1] / "src" / "probos"
_FIELDS = [field.name for field in fields(Episode)]
_DEFAULT_SOURCE = next(field.default for field in fields(Episode) if field.name == "source")
_MIN_SITES = 35  # 41 on 9f43697f (2026-11-18); fewer means the enumeration broke, not that producers went away

# Expressions that copy a label an enumerated producer already wrote: (file, enclosing function, ast.unparse) -> why.
_COMPUTED: dict[tuple[str, str, str], str] = {
    ("cognitive/episodic.py", "_metadata_to_episode", "metadata.get('source', 'direct')"):
        "read back from the metadata store() and seed() wrote",
    ("cognitive/memory_security.py", "aggregate_with_dp", "getattr(ep, 'source', 'direct')"):
        "AD-607i's redacted copy of an episode it was given",
    ("knowledge/store.py", "load_episodes", "data.get('source', 'direct')"):
        "read back from the knowledge store's JSON copy of a stored episode",
}
# Episode(**payload) sites: (file, enclosing function) -> the functions whose dict literals build that payload.
_SPLAT_FEEDERS: dict[tuple[str, str], tuple[tuple[str, str], ...]] = {
    # AD-819 `probos rebuild-episodic`: rebuild_from_wardroom passes _row_to_episode_kwargs's dict to _store.
    ("__main__.py", "_store"): (("maintenance/rebuild_episodic.py", "_row_to_episode_kwargs"),),
    # The owned-steps effect replays the payload _legacy_episode_payload built (kind "collaboration_episode").
    ("cognitive/crew_synth.py", "_attempt_legacy_effect"): (("cognitive/crew_synth.py", "_legacy_episode_payload"),),
}
# What each form must find on its own: a broken form fails here instead of passing by finding nothing.
_EXPECTED_BY_FORM: dict[str, frozenset[str]] = {
    "default": frozenset({"direct"}),
    "literal": frozenset({
        "direct", "action_dispatch", "captain_chat", "crew_collaboration", "group_chat_fanout", "multi_agent_chat",
        "qualification_test",
    }),
    "member": frozenset({"direct", "reflection"}),
    "local": frozenset({"direct", "secondhand"}),
    "splat": frozenset({"crew_collaboration", "wardroom_import"}),
}
# The labels production writes outside MemorySource (BF-938, A-5), named here independently of the module's set.
_PRODUCTION_LABELS = (
    "action_dispatch", "captain_chat", "crew_collaboration", "group_chat_fanout", "multi_agent_chat",
    "qualification_test", "wardroom_import",
)


@dataclass(frozen=True)
class _Site:
    where: str                 # "file:line"
    form: str                  # default | literal | member | local | splat | computed | unresolved
    labels: frozenset[str]
    key: tuple[str, ...]       # (file, function) or (file, function, expression)


def _member(node: ast.expr) -> str | None:
    """``MemorySource.X`` or ``MemorySource.X.value`` -> the member's value."""
    if isinstance(node, ast.Attribute) and node.attr == "value":
        node = node.value
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "MemorySource"
        and node.attr in MemorySource.__members__
    ):
        return MemorySource[node.attr].value
    return None


def _label(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return _member(node)


def _resolve(node: ast.expr, owner: ast.AST | None) -> tuple[str, frozenset[str]] | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return "literal", frozenset({node.value})
    member = _member(node)
    if member is not None:
        return "member", frozenset({member})
    if isinstance(node, ast.Name) and owner is not None:
        values = [
            assign.value
            for assign in ast.walk(owner)
            if isinstance(assign, (ast.Assign, ast.AnnAssign))
            and assign.value is not None
            and any(
                isinstance(target, ast.Name) and target.id == node.id
                for target in (assign.targets if isinstance(assign, ast.Assign) else [assign.target])
            )
        ]
        labels = [_label(value) for value in values]
        if labels and None not in labels:
            return "local", frozenset(label for label in labels if label is not None)
    return None


def _feeder_labels(relative: str, function: str) -> frozenset[str]:
    tree = ast.parse((_SRC / relative).read_text(encoding="utf-8"))
    owners = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function
    ]
    assert len(owners) == 1, (relative, function, len(owners))  # premise: the declared feeder exists, once
    labels: set[str] = set()
    for node in ast.walk(owners[0]):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "source":
                    resolved = _resolve(value, owners[0])
                    assert resolved is not None, (relative, function, ast.unparse(value))
                    labels |= resolved[1]
    assert labels, (relative, function)  # premise: the feeder's dict literals were enumerated
    return frozenset(labels)


def _episode_calls(tree: ast.Module) -> list[tuple[ast.AST | None, ast.Call]]:
    """Every ``Episode(...)`` call with its innermost enclosing function (None at module level)."""
    found: list[tuple[ast.AST | None, ast.Call]] = []

    def visit(node: ast.AST, owner: ast.AST | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Call) and (
                (isinstance(child.func, ast.Name) and child.func.id == "Episode")
                or (isinstance(child.func, ast.Attribute) and child.func.attr == "Episode")
            ):
                found.append((owner, child))
            visit(child, child if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else owner)

    visit(tree, None)
    return found


@functools.cache
def _sites() -> tuple[_Site, ...]:
    sites: list[_Site] = []
    index = _FIELDS.index("source")
    for path in sorted(_SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "Episode(" not in text:
            continue
        relative = path.relative_to(_SRC).as_posix()
        for owner, call in _episode_calls(ast.parse(text)):
            function = getattr(owner, "name", "<module>")
            where = f"{relative}:{call.lineno}"
            source = next((keyword.value for keyword in call.keywords if keyword.arg == "source"), None)
            if source is None and len(call.args) > index and not isinstance(call.args[index], ast.Starred):
                source = call.args[index]
            if source is not None:
                resolved = _resolve(source, owner)
                expression = ast.unparse(source)
                if resolved is not None:
                    sites.append(_Site(where, resolved[0], resolved[1], (relative, function)))
                elif (relative, function, expression) in _COMPUTED:
                    sites.append(_Site(where, "computed", frozenset(), (relative, function, expression)))
                else:
                    sites.append(_Site(where, "unresolved", frozenset(), (relative, function, expression)))
            elif any(keyword.arg is None for keyword in call.keywords) or any(
                isinstance(arg, ast.Starred) for arg in call.args
            ):
                feeders = _SPLAT_FEEDERS.get((relative, function))
                if feeders is None:
                    sites.append(_Site(where, "unresolved", frozenset(), (relative, function)))
                else:
                    labels = frozenset().union(*(_feeder_labels(*feeder) for feeder in feeders))
                    sites.append(_Site(where, "splat", labels, (relative, function)))
            else:
                sites.append(_Site(where, "default", frozenset({_DEFAULT_SOURCE}), (relative, function)))
    return tuple(sites)


def test_the_enumeration_finds_every_form_it_must_handle() -> None:
    sites = _sites()
    assert len(sites) >= _MIN_SITES, len(sites)
    for form, expected in _EXPECTED_BY_FORM.items():
        found = frozenset().union(*(site.labels for site in sites if site.form == form))
        assert expected <= found, (form, sorted(expected - found))
    keys = {site.key for site in sites}
    assert set(_COMPUTED) <= keys, sorted(set(_COMPUTED) - keys)  # no stale allowlist entry
    assert set(_SPLAT_FEEDERS) <= keys, sorted(set(_SPLAT_FEEDERS) - keys)
    assert all(reason.strip() for reason in _COMPUTED.values())


def test_every_episode_construction_has_a_source_the_guard_can_resolve() -> None:
    unresolved = [(site.where, site.key) for site in _sites() if site.form == "unresolved"]
    assert unresolved == [], (
        "an Episode( source the guard cannot resolve: write a literal or a MemorySource member, or add the site to "
        f"_COMPUTED or _SPLAT_FEEDERS with the reason: {unresolved}"
    )


def test_every_episode_source_production_writes_is_a_known_memory_source() -> None:
    unknown = sorted(
        (site.where, label) for site in _sites() for label in site.labels if label not in KNOWN_MEMORY_SOURCES
    )
    assert unknown == [], f"enforce_provenance would drop these from recall as unknown_source: {unknown}"


@pytest.mark.parametrize("label", _PRODUCTION_LABELS)
def test_each_production_label_passes_the_provenance_check(label: str) -> None:
    assert validate_provenance(Episode(agent_ids=["agent-a"], source=label)) == (True, "")
