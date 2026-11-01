"""AD-1346 M3e4c2 (#1604): the census of #1604 property 1's store-write class, its ChromaDB and JetStream writes.

``tests/fixtures/ad1346_store_family_census.py`` holds the census: ``vector_write_points`` and ``bus_write_points``
scan ``src``; ``VECTOR_WRITE_SCOPES`` and ``BUS_WRITE_SCOPES`` give each (file, enclosing scope) that holds a point a
coverage.

- WK1  every (file, scope) the ChromaDB scan finds is a row of ``VECTOR_WRITE_SCOPES`` and every row is one: 53 points
       in 39 scopes of 5 files, counted by name; 1 check and 38 system rows under ``system:ship_computer``.
- WK2  the ChromaDB scan on a synthetic module: a record write with ``ids`` first or later, a record write handed to
       ``asyncio.to_thread`` or ``functools.partial`` with ``ids``, the four collection writes, a write in a lambda, one
       in a nested function and one at module level are points; a read with ``ids``, a query, ``ids`` by position or
       through ``**``, a method reached through ``getattr``, a set's ``add`` and a ``to_thread`` call without ``ids``
       are not.
- WK3  the one check row is the episode's, the row ``STORE_WRITE_SCOPES`` gives ``EpisodicMemory.store``; in that
       method the ``check_at`` call is a statement of its body, before each statement of its body that holds a
       ChromaDB write.
- WK4  every (file, scope) the JetStream scan finds is a row of ``BUS_WRITE_SCOPES`` and every row is one: 9 points in 6
       scopes of 5 files, counted by name; 4 system rows under ``system:ship_computer`` and 2 rows pending for M3e4d,
       the keys of ``BUS_AGENT_ATTRIBUTED``, each of whose scopes binds its author name and records it in a dict under
       a key of that name; ``mesh/nats_bus.py`` holds points the scan leaves out.
- WK5  the JetStream scan on a synthetic module: ``js_publish`` through a name and through an attribute chain,
       ``ensure_stream``, ``recreate_stream`` and a publish in a nested function are points; ``publish``,
       ``publish_raw``, ``js_subscribe``, ``delete_consumer``, a method reached through ``getattr``, a string, a
       ``def js_publish`` and a method bound to a name are not.
"""

from __future__ import annotations

import ast
from collections import Counter

from probos.admission.taxonomy import SYSTEM_PRINCIPALS
from tests.fixtures.ad1346_effect_census import SHIP, Pending, System, src_sources
from tests.fixtures.ad1346_store_census import STORE_WRITE_SCOPES, StoreCheck
from tests.fixtures.ad1346_store_family_census import (
    BUS_AGENT_ATTRIBUTED,
    BUS_WRITE_SCOPES,
    NATS_BUS,
    VECTOR_WRITE_SCOPES,
    bus_write_points,
    bus_write_scan,
    vector_write_points,
    vector_write_scan,
)

_EPISODIC = "src/probos/cognitive/episodic.py"
_STORE = (_EPISODIC, "EpisodicMemory.store")

_VECTOR_SYNTHETIC = '''\
import asyncio
import functools


class Store:
    def write(self, col, client, kw, seen, enc):
        col.add(ids=["a"], documents=["x"])
        col.upsert(documents=["x"], ids=["b"])
        asyncio.to_thread(col.update, ids=["c"], metadatas=[{}])
        functools.partial(col.delete, ids=["d"])
        client.create_collection("e")
        client.get_or_create_collection(name="f")
        client.delete_collection("g")
        col.modify(metadata={})
        col.get(ids=["h"])
        col.query(query_texts=["i"])
        col.add(["j"], documents=["x"])
        col.upsert(**kw)
        getattr(col, "update")(ids=["k"])
        seen.add("l")
        asyncio.to_thread(enc.delete, "m")
        later = lambda: col.delete(ids=["n"])

        def inner():
            return col.update(ids=["o"])

        return later, inner


client.delete_collection("p")
'''

_BUS_SYNTHETIC = '''\
class Bridge:
    async def send(self, bus, subject, payload):
        await bus.js_publish(subject, payload)
        await self._nats_bus.js_publish(subject, payload, headers={})
        await bus.ensure_stream("S", ["s.>"])
        await bus.recreate_stream("T", ["t.>"], max_msgs=1)
        await bus.publish(subject, payload)
        await bus.publish_raw(subject, payload)
        await bus.js_subscribe(subject, None)
        await bus.delete_consumer("S", "d")
        await getattr(bus, "js_publish")(subject, payload)
        name = "js_publish"

        async def inner():
            await bus.js_publish(subject, payload)

        return inner, name

    async def js_publish(self, subject, payload):
        return None


publish = Bridge.js_publish
'''


def _functions(path: str, qualified: str) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Each function in one ``src`` module whose enclosing classes and functions and own name, joined by dots, are
    ``qualified``, as the scans join a scope."""
    found: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    stack: list[tuple[ast.AST, str]] = [(ast.parse(src_sources()[path], filename=path), "")]
    while stack:
        node, prefix = stack.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}.{child.name}" if prefix else child.name
                if name == qualified and not isinstance(child, ast.ClassDef):
                    found.append(child)
                stack.append((child, name))
            else:
                stack.append((child, prefix))
    return found


def test_every_chromadb_write_scope_is_a_row_and_every_row_is_one() -> None:
    """WK1 (D245, D247, D248; kills EK-2, EK-5): a scope that gains its first ChromaDB write fails here until it is
    classified."""
    points = vector_write_points()
    scopes = {(path, scope) for path, scope, _line, _name in points}
    assert sorted(scopes - VECTOR_WRITE_SCOPES.keys()) == []
    assert sorted(VECTOR_WRITE_SCOPES.keys() - scopes) == []
    assert Counter(name for _path, _scope, _line, name in points) == {
        "add": 6,
        "upsert": 11,
        "update": 7,
        "delete": 3,
        "create_collection": 3,
        "get_or_create_collection": 6,
        "delete_collection": 4,
        "modify": 13,
    }
    assert len(scopes) == 39 and len({path for path, _scope in scopes}) == 5, sorted(scopes)
    assert Counter(type(cover).__name__ for cover in VECTOR_WRITE_SCOPES.values()) == {"StoreCheck": 1, "System": 38}
    principals = {cover.principal for cover in VECTOR_WRITE_SCOPES.values() if isinstance(cover, System)}
    assert principals == {SHIP} and principals <= SYSTEM_PRINCIPALS, principals


def test_the_vector_write_scan_on_a_synthetic_module() -> None:
    """WK2 (D245; kills EK-1, EK-8)."""
    assert vector_write_scan(_VECTOR_SYNTHETIC) == [
        ("Store.write", 7, "add"),
        ("Store.write", 8, "upsert"),
        ("Store.write", 9, "update"),
        ("Store.write", 10, "delete"),
        ("Store.write", 11, "create_collection"),
        ("Store.write", 12, "get_or_create_collection"),
        ("Store.write", 13, "delete_collection"),
        ("Store.write", 14, "modify"),
        ("Store.write", 22, "delete"),
        ("Store.write.inner", 25, "update"),
        ("<module>", 30, "delete_collection"),
    ]


def test_the_episode_vector_write_is_under_the_episodic_store_check() -> None:
    """WK3 (D248; kills EK-3, EK-4)."""
    checks = {site: cover for site, cover in VECTOR_WRITE_SCOPES.items() if isinstance(cover, StoreCheck)}
    assert checks == {_STORE: STORE_WRITE_SCOPES[_STORE]}, checks
    tree = ast.parse(src_sources()[_EPISODIC], filename=_EPISODIC)
    [memory] = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "EpisodicMemory"]
    [store] = [node for node in memory.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "store"]
    checks_at = [
        index
        for index, statement in enumerate(store.body)
        if isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Name)
        and statement.value.func.id == "check_at"
    ]
    writes = [line for path, scope, line, _name in vector_write_points() if (path, scope) == _STORE]
    holders = [
        index
        for line in writes
        for index, statement in enumerate(store.body)
        if statement.lineno <= line <= (statement.end_lineno or statement.lineno)
    ]
    assert len(checks_at) == 1 and writes and len(holders) == len(writes), (checks_at, writes, holders)
    assert all(index > checks_at[0] for index in holders), (checks_at, holders)


def test_every_jetstream_write_scope_is_a_row_and_every_row_is_one() -> None:
    """WK4 (D246, D247, D248, D251; kills EK-6, EK-7, EK-9, EK-11, EK-12, EK-13): a scope that gains its first
    JetStream write fails here until it is classified."""
    points = bus_write_points()
    scopes = {(path, scope) for path, scope, _line, _name in points}
    assert sorted(scopes - BUS_WRITE_SCOPES.keys()) == []
    assert sorted(BUS_WRITE_SCOPES.keys() - scopes) == []
    assert Counter(name for _path, _scope, _line, name in points) == {"js_publish": 4, "ensure_stream": 1, "recreate_stream": 4}
    assert len(scopes) == 6 and len({path for path, _scope in scopes}) == 5, sorted(scopes)
    assert Counter(type(cover).__name__ for cover in BUS_WRITE_SCOPES.values()) == {"System": 4, "Pending": 2}
    principals = {cover.principal for cover in BUS_WRITE_SCOPES.values() if isinstance(cover, System)}
    assert principals == {SHIP} and principals <= SYSTEM_PRINCIPALS, principals
    pending = {site: cover for site, cover in BUS_WRITE_SCOPES.items() if isinstance(cover, Pending)}
    assert pending.keys() == BUS_AGENT_ATTRIBUTED.keys() and {cover.owner for cover in pending.values()} == {"M3e4d"}, pending
    for site, (path, scope, author) in BUS_AGENT_ATTRIBUTED.items():
        [function] = _functions(path, scope)
        bound = {node.arg for node in ast.walk(function.args) if isinstance(node, ast.arg)}
        bound |= {node.id for node in ast.walk(function) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
        entries = {
            (key.value, value.id)
            for node in ast.walk(function)
            if isinstance(node, ast.Dict)
            for key, value in zip(node.keys, node.values)
            if isinstance(key, ast.Constant) and isinstance(value, ast.Name)
        }
        assert author in bound and (author, author) in entries, (site, path, scope, author)
    assert bus_write_scan(src_sources()[NATS_BUS], NATS_BUS) != []


def test_the_bus_write_scan_on_a_synthetic_module() -> None:
    """WK5 (D246; kills EK-10)."""
    assert bus_write_scan(_BUS_SYNTHETIC) == [
        ("Bridge.send", 3, "js_publish"),
        ("Bridge.send", 4, "js_publish"),
        ("Bridge.send", 5, "ensure_stream"),
        ("Bridge.send", 6, "recreate_stream"),
        ("Bridge.send.inner", 15, "js_publish"),
    ]
