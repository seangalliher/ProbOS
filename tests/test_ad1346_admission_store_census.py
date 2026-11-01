"""AD-1346 M3e4a (#1604): the census of #1604 property 1's store-write class, its SQL write statements.

``tests/fixtures/ad1346_store_census.py`` holds the census: ``sql_write_points`` scans ``src`` for SQL write
statements; ``STORE_WRITE_SCOPES`` gives each scope that holds one in three files a coverage (AD-1346 M3e4b), and
``STORE_WRITE_FILES`` gives each other file that holds one a coverage.

- WC1  every file the scan finds is a row of ``STORE_WRITE_FILES`` or a file of ``STORE_WRITE_SCOPES``, not both, and
       every row is one: 79 files, of which 3 are scoped and 76 are rows (28 pending for AD-1346 M3e4c, 47 system and 1
       command-line); in the scoped files the scopes the scan finds are the rows of ``STORE_WRITE_SCOPES``: 5 checks
       and 13 system rows under ``system:ship_computer``.
- WC2  the scan on a synthetic module: a constant, an f-string whose table is a placeholder, a triple-quoted statement
       that starts on the line after its quotes, an implicit concatenation, the left operand of ``+``, a statement in a
       lambda, one in a nested function and a module-level constant are points; a module's, a class's and a
       function's docstring, a ``SELECT``, a ``CREATE TABLE``, prose with a write's words after its start, lower-case
       SQL, a bytes constant and a string inside an f-string's placeholder are not.
- WC3  a pending row's owner is AD-1346 M3e4c; ``admission/store.py`` and ``agent_stop.py`` are system rows; the
       checked scopes are the episodic store's and the Ward Room's posts, edits, endorsements and threads.
- WC4  the system rows' principal is ``system:ship_computer``, a member of ``SYSTEM_PRINCIPALS``; the command-line row
       is ``__main__.py``, under ``OUTSIDE_RUNTIME``; in ``src`` the scan finds the Ward Room's f-string whose table is a
       placeholder and a knowledge-edge statement that starts on the line after its quotes, each in its async method.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from probos.admission.taxonomy import SYSTEM_PRINCIPALS
from tests.fixtures.ad1346_effect_census import OUTSIDE_RUNTIME, SHIP, OutsideRuntime, Pending, System, src_sources
from tests.fixtures.ad1346_store_census import (
    STORE_WRITE_FILES,
    STORE_WRITE_SCOPES,
    StoreCheck,
    sql_write_files,
    sql_write_points,
    sql_write_scan,
)

_SYNTHETIC = '''\
"""INSERT INTO module_doc VALUES (1)"""
import sqlite3


class Store:
    """DELETE FROM class_doc"""

    def write(self, db, table):
        """UPDATE fn_doc SET x = 1"""
        db.execute("INSERT INTO a (x) VALUES (?)")
        db.execute(f"UPDATE {table} SET x = ?")
        db.execute(
            """
            INSERT OR REPLACE INTO b (x) VALUES (?)
            """
        )
        db.execute("REPLACE INTO c " "VALUES (?)")
        db.execute("DELETE FROM d " + "WHERE x = ?")
        db.execute("SELECT x FROM e")
        db.execute("CREATE TABLE f (x)")
        note = "No DELETE FROM in this module"
        db.execute("delete from g")
        db.execute(b"DELETE FROM h")
        db.execute(f"{'DELETE FROM i'} x")
        later = lambda: db.execute("UPDATE j SET x = 1")

        def inner():
            return "INSERT INTO k VALUES (1)"

        return later, inner, note


TEMPLATE = "DELETE FROM l"
'''


def _kind(cover: object) -> str:
    return f"Pending {cover.owner}" if isinstance(cover, Pending) else type(cover).__name__


def _scopes(path: str, wanted: Callable[[list[str], int], bool]) -> set[str]:
    """The scopes of the points in ``path`` whose line ``wanted`` accepts (lines split as the parser counts them)."""
    lines = src_sources()[path].split("\n")
    return {scope for rel, scope, line in sql_write_points() if rel == path and wanted(lines, line)}


def test_every_file_with_a_sql_write_statement_is_a_row_and_every_row_is_one() -> None:
    """WC1 (D219, D220, D221; AD-1346 M3e4b: D229; kills EV-9): a file that gains its first SQL write statement, or a
    scope of a scoped file that gains its first, fails here until it is classified."""
    found = sql_write_files()
    scoped = {path for path, _scope in STORE_WRITE_SCOPES}
    assert sorted(scoped & STORE_WRITE_FILES.keys()) == []
    assert sorted(found - STORE_WRITE_FILES.keys() - scoped) == []
    assert sorted((STORE_WRITE_FILES.keys() | scoped) - found) == []
    kinds = Counter(_kind(cover) for cover in STORE_WRITE_FILES.values())
    assert kinds == {"Pending M3e4c": 28, "System": 47, "OutsideRuntime": 1}, kinds
    assert len(found) == 79 and len(scoped) == 3, (len(found), sorted(scoped))
    points = {(path, scope) for path, scope, _line in sql_write_points() if path in scoped}
    assert sorted(points - STORE_WRITE_SCOPES.keys()) == []
    assert sorted(STORE_WRITE_SCOPES.keys() - points) == []
    assert Counter(type(cover).__name__ for cover in STORE_WRITE_SCOPES.values()) == {"StoreCheck": 5, "System": 13}
    assert {cover.principal for cover in STORE_WRITE_SCOPES.values() if isinstance(cover, System)} == {SHIP}


def test_the_sql_write_scan_on_a_synthetic_module() -> None:
    """WC2 (D219; kills EW-4, EW-5, EW-6, EW-9, EW-12)."""
    assert sql_write_scan(_SYNTHETIC) == [
        ("Store.write", 10),
        ("Store.write", 11),
        ("Store.write", 13),
        ("Store.write", 17),
        ("Store.write", 18),
        ("Store.write", 25),
        ("Store.write.inner", 28),
        ("<module>", 33),
    ]


def test_the_pending_rows_and_the_rows_of_the_services_that_check() -> None:
    """WC3 (D218, D221; AD-1346 M3e4b: D229; kills EW-8)."""
    pending = {path: cover.owner for path, cover in STORE_WRITE_FILES.items() if isinstance(cover, Pending)}
    assert set(pending.values()) == {"M3e4c"}
    for path in ("src/probos/admission/store.py", "src/probos/agent_stop.py"):
        assert type(STORE_WRITE_FILES[path]) is System, path
    assert sorted(site for site, cover in STORE_WRITE_SCOPES.items() if isinstance(cover, StoreCheck)) == [
        ("src/probos/cognitive/episodic.py", "EpisodicMemory.store"),
        ("src/probos/ward_room/messages.py", "MessageStore.create_post"),
        ("src/probos/ward_room/messages.py", "MessageStore.edit_post"),
        ("src/probos/ward_room/messages.py", "MessageStore.endorse"),
        ("src/probos/ward_room/threads.py", "ThreadManager.create_thread"),
    ]


def test_the_system_and_command_line_rows_and_two_shapes_the_scan_finds_in_src() -> None:
    """WC4 (D166, D167, D219; kills EW-10, EW-11)."""
    principals = {cover.principal for cover in STORE_WRITE_FILES.values() if isinstance(cover, System)}
    assert principals == {SHIP} and principals <= SYSTEM_PRINCIPALS, principals
    outside = [path for path, cover in STORE_WRITE_FILES.items() if isinstance(cover, OutsideRuntime)]
    assert outside == ["src/probos/__main__.py"] and all(path.startswith(OUTSIDE_RUNTIME) for path in outside), outside
    # An f-string whose table is a placeholder.
    assert _scopes(
        "src/probos/ward_room/messages.py", lambda lines, line: "UPDATE {table} SET" in lines[line - 1],
    ) == {"MessageStore.endorse"}
    # A triple-quoted statement that starts on the line after its quotes.
    assert _scopes(
        "src/probos/knowledge/edges.py",
        lambda lines, line: lines[line - 1].strip() == '"""'
        and lines[line].strip().startswith("INSERT OR REPLACE INTO knowledge_edges"),
    ) == {"SQLiteKnowledgeEdgeStore.add_edge"}
