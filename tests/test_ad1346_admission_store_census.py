"""AD-1346 M3e4a (#1604): the census of #1604 property 1's store-write class, its SQL write statements.

``tests/fixtures/ad1346_store_census.py`` holds the census: ``sql_write_points`` scans ``src`` for SQL write
statements; ``STORE_WRITE_SCOPES`` gives each scope that holds one in twelve files a coverage (AD-1346 M3e4b, M3e4d1,
M3e4d2, M3e4d3, M3e4d4, M3e4d5, M3e4d6, M3e4d7, M3e4d8); ``STORE_WRITE_FILES`` gives each other file that holds one a
coverage; ``AGENT_ATTRIBUTED_SCOPES`` gives a scope and an author name for each file whose row is pending for AD-1346
M3e4d (AD-1346 M3e4c); from AD-1346 M3e4d8 it is empty.

- WC1  every file the scan finds is a row of ``STORE_WRITE_FILES`` or a file of ``STORE_WRITE_SCOPES``, not both, and
       every row is one: 79 files, of which 12 are scoped and 67 are rows (66 system and 1 command-line); in the scoped
       files the scopes the scan finds are the rows of ``STORE_WRITE_SCOPES``: 20 check rows, 75 system rows under
       ``system:ship_computer`` and 21 rows pending for AD-1346 M3e4d.
- WC2  the scan on a synthetic module: a constant, an f-string whose table is a placeholder, a triple-quoted statement
       that starts on the line after its quotes, an implicit concatenation, the left operand of ``+``, a statement in a
       lambda, one in a nested function and a module-level constant are points; a module's, a class's and a
       function's docstring, a ``SELECT``, a ``CREATE TABLE``, prose with a write's words after its start, lower-case
       SQL, a bytes constant and a string inside an f-string's placeholder are not.
- WC3  no file's row is pending and ``AGENT_ATTRIBUTED_SCOPES`` is empty; the pending scopes are 21 scopes of
       ``workforce.py``, each owned by AD-1346 M3e4d; ``admission/store.py`` and ``agent_stop.py`` are system rows; the
       checked scopes are the episodic store's, the Ward Room's posts, edits, endorsements and threads, the clinical
       notes store's notes, the skill request store's filings and decisions, the persistent task store's task
       creation, the chat thread store's thread creation and messages, the assignment service's assignment creation,
       the Ward Room channel manager's channel and DM channel creation, the capability request store's filings and
       decisions, with the ladder's, the artifact store's added versions and reconciled first versions, and the work
       item store's inserted work items.
- WC4  the system rows' principal is ``system:ship_computer``, a member of ``SYSTEM_PRINCIPALS``; the command-line row
       is ``__main__.py``, under ``OUTSIDE_RUNTIME``; in ``src`` the scan finds the Ward Room's f-string whose table is a
       placeholder and a knowledge-edge statement that starts on the line after its quotes, each in its async method.
- WC5  each scope of ``AGENT_ATTRIBUTED_SCOPES`` holds a SQL write statement the scan finds in its file, and the part
       of its author name before the first dot is a parameter of the one function of that qualified name in the file.
"""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Callable

from probos.admission.taxonomy import SYSTEM_PRINCIPALS
from tests.fixtures.ad1346_effect_census import OUTSIDE_RUNTIME, SHIP, OutsideRuntime, Pending, System, src_sources
from tests.fixtures.ad1346_store_census import (
    AGENT_ATTRIBUTED_SCOPES,
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
    """WC1 (D219, D220, D221; AD-1346 M3e4b: D229; AD-1346 M3e4c: D240; AD-1346 M3e4d1: D284; AD-1346 M3e4d2: D291;
    AD-1346 M3e4d3: D298; AD-1346 M3e4d4: D306; AD-1346 M3e4d5: D313; AD-1346 M3e4d6: D320; AD-1346 M3e4d7: D327;
    AD-1346 M3e4d8: D334; AD-1346 M3e4d9: D341; AD-1346 M3e4d10: D346; AD-1346 M3e4d11: D351; kills EV-9, EA-2, EA-6,
    ED-9, EY-5, EY-7, EU-7, EU-9, EO-6, EO-8, ET-8, ET-10, RQ-9, RQ-10, AV-9, AV-10, WF-5, WF-6, WF-7, WG-1, WG-2,
    WG-3, WG-4, WH-1, WH-2, WH-3, WH-4, WN-1, WN-2, WN-3, WN-4, WN-5): a file that gains its first SQL write statement,
    or a scope of a scoped file that gains its first, fails here until it is classified or listed as pending."""
    found = sql_write_files()
    scoped = {path for path, _scope in STORE_WRITE_SCOPES}
    assert sorted(scoped & STORE_WRITE_FILES.keys()) == []
    assert sorted(found - STORE_WRITE_FILES.keys() - scoped) == []
    assert sorted((STORE_WRITE_FILES.keys() | scoped) - found) == []
    kinds = Counter(_kind(cover) for cover in STORE_WRITE_FILES.values())
    assert kinds == {"System": 66, "OutsideRuntime": 1}, kinds
    assert len(found) == 79 and len(scoped) == 12, (len(found), sorted(scoped))
    points = {(path, scope) for path, scope, _line in sql_write_points() if path in scoped}
    assert sorted(points - STORE_WRITE_SCOPES.keys()) == []
    assert sorted(STORE_WRITE_SCOPES.keys() - points) == []
    assert Counter(type(cover).__name__ for cover in STORE_WRITE_SCOPES.values()) == {"StoreCheck": 20, "System": 75, "Pending": 21}
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
    """WC3 (D218, D221; AD-1346 M3e4b: D229; AD-1346 M3e4c: D239, D240; AD-1346 M3e4d1: D284; AD-1346 M3e4d2: D291;
    AD-1346 M3e4d3: D298; AD-1346 M3e4d4: D306; AD-1346 M3e4d5: D313; AD-1346 M3e4d6: D320; AD-1346 M3e4d7: D327;
    AD-1346 M3e4d8: D334; AD-1346 M3e4d9: D341; AD-1346 M3e4d10: D346; AD-1346 M3e4d11: D351; kills EW-8, EA-1, EA-7,
    WF-8)."""
    pending = {path: cover.owner for path, cover in STORE_WRITE_FILES.items() if isinstance(cover, Pending)}
    assert pending == dict.fromkeys(AGENT_ATTRIBUTED_SCOPES, "M3e4d"), pending
    assert sorted(AGENT_ATTRIBUTED_SCOPES.items()) == []  # AD-1346 M3e4d8 (D334): workforce.py is split by scope
    # AD-1346 M3e4d8 (D334): the pending scopes, each a scope of workforce.py owned by M3e4d.
    assert Counter((path, cover.owner) for (path, _scope), cover in STORE_WRITE_SCOPES.items() if isinstance(cover, Pending)) == {
        ("src/probos/workforce.py", "M3e4d"): 21,  # AD-1346 M3e4d9 to M3e4d11 (D341, D346, D351): 24 scopes are system rows
    }
    for path in ("src/probos/admission/store.py", "src/probos/agent_stop.py"):
        assert type(STORE_WRITE_FILES[path]) is System, path
    assert sorted(site for site, cover in STORE_WRITE_SCOPES.items() if isinstance(cover, StoreCheck)) == [
        ("src/probos/artifacts/__init__.py", "ArtifactStore.add_version"),
        ("src/probos/artifacts/__init__.py", "ArtifactStore.reconcile_exact_version"),
        ("src/probos/assignment.py", "AssignmentService.create_assignment"),
        ("src/probos/capability_request.py", "CapabilityRequestStore.decide"),
        ("src/probos/capability_request.py", "CapabilityRequestStore.file_request"),
        ("src/probos/capability_request.py", "_decide_ladder_row"),
        ("src/probos/cognitive/clinical_notes_store.py", "ClinicalNotesStore.write_note"),
        ("src/probos/cognitive/episodic.py", "EpisodicMemory.store"),
        ("src/probos/persistent_tasks.py", "PersistentTaskStore.create_task"),
        ("src/probos/skill_request.py", "SkillRequestStore.decide"),
        ("src/probos/skill_request.py", "SkillRequestStore.file_request"),
        ("src/probos/threads/__init__.py", "ChatThreadStore.append_message_once"),
        ("src/probos/threads/__init__.py", "ChatThreadStore.create_thread"),
        ("src/probos/ward_room/channels.py", "ChannelManager.create_channel"),
        ("src/probos/ward_room/channels.py", "ChannelManager.get_or_create_dm_channel"),
        ("src/probos/ward_room/messages.py", "MessageStore.create_post"),
        ("src/probos/ward_room/messages.py", "MessageStore.edit_post"),
        ("src/probos/ward_room/messages.py", "MessageStore.endorse"),
        ("src/probos/ward_room/threads.py", "ThreadManager.create_thread"),
        ("src/probos/workforce.py", "WorkItemStore._insert_work_item"),
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


def _parameters(path: str, qualified: str) -> list[set[str]]:
    """The names of the positional-only, positional and keyword-only parameters of each function of ``path`` that is
    reached through class and function bodies, by dotted name."""
    found: list[set[str]] = []

    def visit(body: list[ast.stmt], scope: list[str]) -> None:
        for node in body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = [*scope, node.name]
                if not isinstance(node, ast.ClassDef) and ".".join(name) == qualified:
                    arguments = node.args
                    found.append({arg.arg for arg in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)})
                visit(node.body, name)

    visit(ast.parse(src_sources()[path], filename=path).body, [])
    return found


def test_each_agent_attributed_scope_writes_and_names_its_author() -> None:
    """WC5 (D239, D240, D241; kills EA-3, EA-4, EA-5, EA-8)."""
    points = {(path, scope) for path, scope, _line in sql_write_points()}
    for path, (scope, author) in AGENT_ATTRIBUTED_SCOPES.items():
        assert (path, scope) in points, (path, scope)
        assert [author.split(".")[0] in names for names in _parameters(path, scope)] == [True], (path, scope, author)
