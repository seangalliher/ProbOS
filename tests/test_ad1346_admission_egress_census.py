"""AD-1346 M3e3a (#1604): the census of #1604 property 1's egress class.

``tests/fixtures/ad1346_effect_census.py`` holds the census: ``egress_points`` scans ``src`` for egress points by
(file, enclosing scope), and ``EGRESS_SITES`` gives each (file, scope) one coverage. No sink is added by AD-1346 M3e3a:
each pending row's sink is AD-1346 M3e3b's.

- EN1  every (file, scope) the scan finds is a row with its count, and every row is one: 43 points in 40 rows, 5
       pending, 1 of another class, 28 system in 27 rows, 2 reached only from named files and 7 command-line in 5 rows.
- EN2  the scan on a synthetic module: an import alias, a lambda, a nested function, an argument, a keyword argument, a
       from-import, a function's own import and a module-level call are points; a parameter named like a module, a
       method of an attribute, an annotation and a name only a relative import binds are not.
- EN3  the pending rows, each owned by ``M3e3b``.
- EN4  the other-class row names a delivered class other than egress, in its own file, and its check function holds one
       ``check_at`` call whose effect is that class's constant.
- EN5  for each row reached only from named files, ``unreached_references`` finds a reference to its names, and every
       one it finds is in a file under the row's ``allowed`` prefixes.
- EN6  the system rows' principal is ``system:ship_computer``, a member of ``SYSTEM_PRINCIPALS``; the command-line rows
       are under ``OUTSIDE_RUNTIME``; and the scan finds an aliased import, a from-import inside a method and a call
       inside a lambda.
- EN7  every top-level module ``src`` imports, other than ``probos``, ``__future__`` and the names in
       ``sys.stdlib_module_names``, is the first component of a name of ``EGRESS_PRIMITIVES`` or a member of
       ``IMPORTS_WITHOUT_PRIMITIVE``; every member is imported and is no such component.
"""

from __future__ import annotations

import ast
import sys

from probos.admission.taxonomy import SYSTEM_PRINCIPALS
from tests.fixtures.ad1343_seam_census import calls, function
from tests.fixtures.ad1346_effect_census import (
    DELIVERED,
    EGRESS_PRIMITIVES,
    EGRESS_SITES,
    IMPORTS_WITHOUT_PRIMITIVE,
    OUTSIDE_RUNTIME,
    SHIP,
    OtherClass,
    OutsideRuntime,
    Pending,
    ReachedOnlyFrom,
    System,
    census_problems,
    egress_counts,
    egress_points,
    egress_scan,
    imported_modules,
    src_sources,
    unreached_references,
)

#: The constant a delivered class's sink statement passes as ``effect``.
_CLASS_CONSTANT = {"model_call": "SEAM_MODEL_CALL", "tool": "SEAM_TOOL", "subprocess": "EFFECT_SUBPROCESS"}


def test_every_egress_point_is_a_row_and_every_row_a_point() -> None:
    """EN1 (D194, D195; kills EG-3, EG-5, EG-7): a new, removed or recounted egress point fails here."""
    found = egress_counts()
    assert census_problems(found, EGRESS_SITES) == []
    kinds = (Pending, OtherClass, System, ReachedOnlyFrom, OutsideRuntime)
    points = {kind.__name__: sum(n for n, cover in EGRESS_SITES.values() if type(cover) is kind) for kind in kinds}
    rows = {kind.__name__: sum(type(cover) is kind for _n, cover in EGRESS_SITES.values()) for kind in kinds}
    assert points == {"Pending": 5, "OtherClass": 1, "System": 28, "ReachedOnlyFrom": 2, "OutsideRuntime": 7}, points
    assert rows == {"Pending": 5, "OtherClass": 1, "System": 27, "ReachedOnlyFrom": 2, "OutsideRuntime": 5}, rows
    assert sum(found.values()) == 43


def test_the_egress_scan_on_synthetic_modules() -> None:
    """EN2 (D194; kills EG-4, EG-6, EG-11, EG-12)."""
    source = (
        "import asyncio as aio\n"
        "import httpx\n"
        "from zeroconf.asyncio import AsyncZeroconf\n"
        "\n"
        "\n"
        "class C:\n"
        "    def __init__(self, http=None):\n"
        "        self.make = http or (lambda: httpx.AsyncClient())\n"
        "\n"
        "    async def run(self, requests):\n"
        "        await requests.get('id')\n"
        "        await self.client.post('u')\n"
        "        client: httpx.AsyncClient | None = None\n"
        "\n"
        "        def inner():\n"
        "            return AsyncZeroconf()\n"
        "\n"
        "        return await asyncio_to_thread(aio.open_connection, 'h', 1), inner, client\n"
        "\n"
        "\n"
        "def lazy():\n"
        "    import urllib.request\n"
        "    return urllib.request.urlopen('u')\n"
        "\n"
        "\n"
        "httpx.get('u')\n"
        "from .httpx import AsyncClient\n"
        "AsyncClient()\n"
        "run_later(target=httpx.Client)\n"
    )
    assert egress_scan(source) == [
        ("C.__init__", 8, "httpx.AsyncClient", "direct"),
        ("C.run.inner", 16, "zeroconf.asyncio.AsyncZeroconf", "direct"),
        ("C.run", 18, "asyncio.open_connection", "by-reference"),
        ("lazy", 23, "urllib.request.urlopen", "direct"),
        ("<module>", 26, "httpx.get", "direct"),
        ("<module>", 29, "httpx.Client", "by-reference"),
    ]


def test_each_pending_egress_row_is_owned_by_m3e3b() -> None:
    """EN3 (D195, D199)."""
    pending = sorted(site for site, (_n, cover) in EGRESS_SITES.items() if isinstance(cover, Pending))
    assert pending == [
        ("src/probos/agents/http_fetch.py", "HttpFetchAgent._follow_and_fetch"),
        ("src/probos/agents/red_team.py", "RedTeamAgent._verify_http_fetch"),
        ("src/probos/cognitive/image_gen_dispatch.py", "dispatch_image_gen"),
        ("src/probos/tools/browser/session.py", "BrowserSession._connect_impl"),
        ("src/probos/tools/browser/session.py", "BrowserSession._start_impl"),
    ]
    assert {cover.owner for _n, cover in EGRESS_SITES.values() if isinstance(cover, Pending)} == {"M3e3b"}


def test_an_other_class_row_names_a_delivered_class_whose_check_its_function_holds() -> None:
    """EN4 (D195; kills EG-8)."""
    rows = [(site, cover) for site, (_n, cover) in EGRESS_SITES.items() if isinstance(cover, OtherClass)]
    assert [site for site, _cover in rows] == [("src/probos/cognitive/llm_client.py", "OpenAICompatibleClient._build_client")]
    for (path, _scope), cover in rows:
        assert cover.effect_class in DELIVERED and cover.effect_class != "egress", cover
        assert cover.check[0] == path, cover
        checks = [node for node in ast.walk(function(*cover.check)) if calls("check_at")(node)]
        assert len(checks) == 1, cover.check
        keywords = {keyword.arg: ast.unparse(keyword.value) for keyword in checks[0].keywords}
        assert keywords["effect"] == _CLASS_CONSTANT[cover.effect_class], keywords


def test_a_row_reached_only_from_named_files_is_referenced_only_there() -> None:
    """EN5 (D195; kills EG-10)."""
    rows = [(site, cover) for site, (_n, cover) in EGRESS_SITES.items() if isinstance(cover, ReachedOnlyFrom)]
    assert sorted(site for site, _cover in rows) == [
        ("src/probos/federation/a2a/client.py", "A2AClient.__init__"),
        ("src/probos/provider_setup.py", "_probe_client"),
    ]
    for (path, scope), cover in rows:
        found = unreached_references(src_sources(), path, cover.names)
        assert found, (path, cover.names)  # premise: the helper finds the files that name it
        assert [(rel, line) for rel, line in found if not rel.startswith(cover.allowed)] == [], (path, scope)


def test_the_system_and_command_line_rows_and_three_shapes_the_scan_finds() -> None:
    """EN6 (D166, D167, D194)."""
    principals = {cover.principal for _n, cover in EGRESS_SITES.values() if isinstance(cover, System)}
    assert principals == {SHIP} and principals <= SYSTEM_PRINCIPALS, principals
    outside = [path for (path, _scope), (_n, cover) in EGRESS_SITES.items() if isinstance(cover, OutsideRuntime)]
    assert outside and all(path.startswith(OUTSIDE_RUNTIME) for path in outside), outside
    reached = {(path, scope, primitive, shape) for path, scope, _line, primitive, shape in egress_points()}
    # `import asyncio as _aio` is in `_check_nats`; the call is in the nested `_probe`.
    assert ("src/probos/__main__.py", "_check_nats._probe", "asyncio.open_connection", "direct") in reached
    # `from zeroconf.asyncio import AsyncZeroconf` inside a method.
    assert ("src/probos/discovery/advertiser.py", "ZeroconfAdvertiser.start", "zeroconf.asyncio.AsyncZeroconf", "direct") in reached
    # A lambda takes its enclosing function's scope.
    assert ("src/probos/startup/finalize.py", "_wire_repair_dispatcher", "httpx.AsyncClient", "direct") in reached


def test_each_top_level_module_src_imports_is_a_primitive_module_or_listed() -> None:
    """EN7 (D201; kills EG-13, EG-14): a top-level module other than ``probos`` and the standard library's that ``src``
    starts to import fails here until it is classified."""
    third_party = {name for name in imported_modules() if name not in sys.stdlib_module_names} - {"probos", "__future__"}
    primitive_modules = {name.split(".")[0] for name in EGRESS_PRIMITIVES}
    assert {"httpx", "zmq"} <= third_party, sorted(third_party)
    assert sorted(third_party - primitive_modules - IMPORTS_WITHOUT_PRIMITIVE) == []
    assert sorted(IMPORTS_WITHOUT_PRIMITIVE - third_party) == []
    assert IMPORTS_WITHOUT_PRIMITIVE.isdisjoint(primitive_modules), sorted(IMPORTS_WITHOUT_PRIMITIVE & primitive_modules)
