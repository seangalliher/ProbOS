"""AD-1360 S2b (#1828): every Episode( a recall can judge as direct forwards a cycle id, or is exempt with a reason.

S3 arms security.memory.correlation_cutoff; from then on, a recalled direct episode stored after it whose correlation_id
is empty, unresolved or unchecked is flagged. This guard enumerates every Episode( construction under src/probos with
BF-938's enumerator and requires, for each site whose source can be "direct" (a resolved "direct" label, the dataclass
default, or a computed copy), a correlation_id= keyword whose value is not a constant, unless the site is in _EXEMPT
with its reason. A site whose source is never "direct" needs no row: BF-938 resolves its labels.

The Ward Room's producers read the id from the context, so the routes that post outside a cycle are invisible to the
Episode( census. _ENTRY_CHAINS therefore pins every call to cycle_trace.entry_scope / issue_entry_id by (file, function)
and the kind it issues under; a new call or a moved one fails here until the table says so.

What it cannot see: a correlation_id passed positionally or inside **kwargs (reported as missing, so it fails closed);
a dataclasses.replace(...) copy; an Episode built outside src/probos (an overlay); whether a forwarded expression is
non-empty at run time (current_cycle_id() outside a cycle is ""); an entry point that calls neither helper.
"""

from __future__ import annotations

import ast
import functools

from tests.test_bf938_episode_source_guard import _SRC, _episode_calls, _sites

_REASONS = ("never stored", "copy", "dead", "outside any cycle by design")
# (file, enclosing function) -> why the direct-capable site needs no cycle id. Each reason starts with one of _REASONS.
_EXEMPT: dict[tuple[str, str], str] = {
    ("cognitive/episodic.py", "migrate_enriched_embedding"):
        "never stored: a minimal Episode whose only use is _prepare_document's text",
    ("knowledge/store.py", "load_episodes"):
        "copy: the knowledge store's JSON copy of a stored episode; it carries no stored_at, so no cutoff judges it",
}
# (file, enclosing function) -> the kinds its entry_scope / issue_entry_id calls issue under.
_ENTRY_CHAINS: dict[tuple[str, str], frozenset[str]] = {
    ("agents/quartermaster.py", "reconcile"): frozenset({"quartermaster_sweep"}),
    ("agents/quartermaster.py", "reconcile_for_agent"): frozenset({"quartermaster_reclaim"}),
    ("cognitive/feedback.py", "apply_correction_feedback"): frozenset({"captain_feedback"}),
    ("cognitive/feedback.py", "_store_feedback_episode"): frozenset({"captain_feedback"}),
    ("cognitive/ground_truth.py", "write"): frozenset({"ground_truth_verification"}),
    ("experience/renderer.py", "process_with_feedback"): frozenset({"nl_request"}),
    ("perception/consumer.py", "_anchor_episode"): frozenset({"vision_observation"}),
    ("routers/agents.py", "_agent_chat_impl"): frozenset({"hxi_dm"}),
    ("routers/agents.py", "set_agent_voice_profile"): frozenset({"hxi_request"}),
    ("routers/perception.py", "_write_anchor_episode"): frozenset({"hxi_request"}),
    ("routers/procedures.py", "teach_procedure"): frozenset({"hxi_post"}),
    ("routers/recreation.py", "make_move"): frozenset({"hxi_post"}),
    ("routers/wardroom.py", "wardroom_create_post"): frozenset({"hxi_post"}),
    ("routers/wardroom.py", "wardroom_create_thread"): frozenset({"hxi_post"}),
    ("runtime.py", "_execute_dag"): frozenset({"nl_request"}),
    ("runtime.py", "_run_qa_for_designed_agent"): frozenset({"system_qa"}),
}
_ENTRY_CALLS = frozenset({"entry_scope", "issue_entry_id"})
_MIN_DIRECT = 25  # 29 after S2b (2026-11-21); fewer means the enumeration broke


def _called(call: ast.Call) -> str:
    return call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", "")


def _forwards_an_id(call: ast.Call) -> bool:
    value = next((keyword.value for keyword in call.keywords if keyword.arg == "correlation_id"), None)
    return value is not None and not isinstance(value, ast.Constant)


def _may_be_direct(labels: frozenset[str], form: str) -> bool:
    return "direct" in labels or form in ("computed", "unresolved")


@functools.cache
def _calls() -> dict[str, ast.Call]:
    """file:line -> its Episode( call, keyed as BF-938's _Site.where."""
    found: dict[str, ast.Call] = {}
    for path in sorted(_SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "Episode(" not in text:
            continue
        relative = path.relative_to(_SRC).as_posix()
        for _owner, call in _episode_calls(ast.parse(text)):
            where = f"{relative}:{call.lineno}"
            assert where not in found, where  # premise: one Episode( per line
            found[where] = call
    return found


def _direct_sites() -> list[tuple[str, tuple[str, str], bool]]:
    """(where, (file, function), forwards an id) for every site whose source can be direct."""
    return [
        (site.where, (site.key[0], site.key[1]), _forwards_an_id(_calls()[site.where]))
        for site in _sites() if _may_be_direct(site.labels, site.form)
    ]


def _entry_chains() -> dict[tuple[str, str], frozenset[str]]:
    found: dict[tuple[str, str], set[str]] = {}

    def visit(node: ast.AST, relative: str, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Call) and _called(child) in _ENTRY_CALLS:
                kind = next((keyword.value for keyword in child.keywords if keyword.arg == "kind"), None)
                literal = isinstance(kind, ast.Constant) and isinstance(kind.value, str)
                found.setdefault((relative, owner), set()).add(kind.value if literal else "<not a literal>")
            visit(child, relative, child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else owner)

    for path in sorted(_SRC.rglob("*.py")):
        relative = path.relative_to(_SRC).as_posix()
        text = path.read_text(encoding="utf-8")
        if relative != "cycle_trace.py" and any(name in text for name in _ENTRY_CALLS):
            visit(ast.parse(text), relative, "<module>")
    return {key: frozenset(kinds) for key, kinds in found.items()}


def test_the_census_finds_its_sites_and_every_exemption_is_live() -> None:
    assert len(_sites()) >= 35
    direct = _direct_sites()
    assert len(direct) >= _MIN_DIRECT, len(direct)
    keys = {key for _where, key, _forwards in direct}
    assert set(_EXEMPT) <= keys, sorted(set(_EXEMPT) - keys)
    assert all(reason.startswith(_REASONS) for reason in _EXEMPT.values()), _EXEMPT


def test_every_direct_episode_forwards_a_cycle_id_or_is_exempt() -> None:
    missing = [(where, key) for where, key, forwards in _direct_sites() if not forwards and key not in _EXEMPT]
    assert missing == [], (
        "a direct Episode( stores no cycle id: pass correlation_id= (current_cycle_id(), the result's id, or "
        f"issue_entry_id(registry, kind=...) at an entry point), or add the site to _EXEMPT with its reason: {missing}"
    )


def test_an_exempt_site_that_forwards_an_id_is_a_stale_row() -> None:
    stale = sorted({key for _where, key, forwards in _direct_sites() if forwards and key in _EXEMPT})
    assert stale == [], f"remove these rows from _EXEMPT: {stale}"


def test_the_rule_rejects_a_missing_or_constant_id_and_accepts_an_expression() -> None:
    def call(source: str) -> ast.Call:
        node = ast.parse(source).body[0]
        assert isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        return node.value

    for source in (
        'Episode(source="direct")', 'Episode(user_input="x")', 'Episode(source="direct", correlation_id="")',
        'Episode(source="direct", correlation_id="abcdefabcdef")', 'Episode(source="direct", correlation_id=None)',
        'Episode(**payload)',
    ):
        assert not _forwards_an_id(call(source)), source
    for source in (
        'Episode(source="direct", correlation_id=current_cycle_id())', 'Episode(correlation_id=self.ctx.cycle_id)',
    ):
        assert _forwards_an_id(call(source)), source
    assert _may_be_direct(frozenset({"direct"}), "literal") and _may_be_direct(frozenset(), "computed")
    assert not _may_be_direct(frozenset({"reflection"}), "member")


def test_each_entry_point_issues_under_its_kind() -> None:
    assert _entry_chains() == _ENTRY_CHAINS
