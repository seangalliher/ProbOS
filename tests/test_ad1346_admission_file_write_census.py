"""AD-1346 M3e4c3a (#1604): the census of #1604 property 1's store-write class, its file writes.

``tests/fixtures/ad1346_file_write_census.py`` holds the census: ``file_write_points`` scans ``src``;
``FILE_WRITE_FILES`` gives each file that holds a point a coverage; ``FILE_AGENT_ATTRIBUTED_SCOPES`` gives a scope and
an author name for each file whose row is pending for AD-1346 M3e4d.

- WF1  every file the scan finds is a row of ``FILE_WRITE_FILES`` and every row is one: 72 files (1 pending for
       AD-1346 M3e4d, 69 pending for AD-1346 M3e4c3b and 2 command-line), and 207 points counted by name.
- WF2  the scan on a synthetic module: the seven methods of ``FILE_WRITE_METHODS``, the seven functions of
       ``MODULE_WRITES``, ``os.open`` with a write flag, ``open`` and ``fdopen`` with a mode that writes (by position
       and by keyword), a ``Path`` replace and rename with one argument, a method handed to an executor and to
       ``asyncio.to_thread``, a write in a lambda, one in a nested function and one at module level are points;
       ``str.replace`` with two arguments or with a keyword, ``open`` with no mode, a read mode or a mode in a variable,
       a file name that starts with a mode's letter, ``os.open`` with a read flag or with flags in a variable, a
       handle's ``write``, ``json.dump``, a method reached through ``getattr`` and a string that holds a write's text
       are not.
- WF3  the one row pending for AD-1346 M3e4d is the Ship's Records' file and the table is pinned; its scope holds a
       point the scan finds, its author name is a parameter (positional-only, positional or keyword-only) of the one
       function of that qualified name, and a dict display in that function maps the ``str`` constant of that name
       to that name.
- WF4  the command-line rows are ``__main__.py`` and the doctor's data-directory check, each under
       ``OUTSIDE_RUNTIME``, and no other row lies under it.
- WF5  in ``src`` the scan finds two methods handed to an executor (``cognitive/session_manager.py``), a ``Path``
       rename with one argument (``cognitive/dreaming.py``), and in ``task_sessions/browser.py`` one point, the file
       its rendered script is written to.
"""

from __future__ import annotations

import ast
from collections import Counter

from tests.fixtures.ad1346_effect_census import OUTSIDE_RUNTIME, OutsideRuntime, Pending, src_sources
from tests.fixtures.ad1346_file_write_census import (
    FILE_AGENT_ATTRIBUTED_SCOPES,
    FILE_WRITE_FILES,
    file_write_files,
    file_write_points,
    file_write_scan,
)

_RECORDS = "src/probos/knowledge/records_store.py"

_SYNTHETIC = '''\
import asyncio
import json
import os
import shutil


class Store:
    def write(self, path, tmp, loop, fd, data, kw, text, mode, handle):
        path.write_text(data)
        path.write_bytes(data)
        path.unlink(missing_ok=True)
        shutil.rmtree(path)
        shutil.copy2(tmp, path)
        shutil.copyfile(tmp, path)
        shutil.copytree(tmp, path)
        shutil.copy(tmp, path)
        shutil.move(tmp, path)
        os.replace(tmp, path)
        os.rename(tmp, path)
        os.remove(path)
        os.link(tmp, path)
        os.write(fd, data)
        os.open(path, os.O_WRONLY | os.O_CREAT)
        open(path, "w")
        path.open("a")
        os.fdopen(fd, "wb")
        open(path, mode="r+")
        tmp.replace(path)
        tmp.rename(path)
        loop.run_in_executor(None, path.unlink)
        asyncio.to_thread(os.replace, tmp, path)
        text.replace("a", "b")
        text.replace(old="a")
        open(path)
        open(path, "rb")
        path.open(mode="r")
        os.open(path, os.O_RDONLY)
        os.open(path, kw)
        open(path, mode)
        open("w.log")
        handle.write(data)
        json.dump(data, handle)
        getattr(path, "unlink")()
        script = "path.write_text(data)"
        later = lambda: os.replace(tmp, path)

        def inner():
            return path.write_text(data)

        return later, inner, script


shutil.rmtree("p")
'''


def _kind(cover: Pending | OutsideRuntime) -> str:
    return f"Pending {cover.owner}" if isinstance(cover, Pending) else type(cover).__name__


def _found(path: str) -> set[tuple[str, str]]:
    """(scope, name) of each point the scan finds in ``path``."""
    return {(scope, name) for rel, scope, _line, name in file_write_points() if rel == path}


def _function(path: str, qualified: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """The one function of ``path``, reached through class and function bodies, whose dotted name is ``qualified``."""
    found: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    def visit(body: list[ast.stmt], scope: list[str]) -> None:
        for node in body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = [*scope, node.name]
                if not isinstance(node, ast.ClassDef) and ".".join(name) == qualified:
                    found.append(node)
                visit(node.body, name)

    visit(ast.parse(src_sources()[path], filename=path).body, [])
    assert len(found) == 1, (path, qualified, len(found))
    return found[0]


def test_every_file_with_a_file_write_is_a_row_and_every_row_is_one() -> None:
    """WF1 (D253, D254; kills EF-10, EF-12): a file that gains its first file write fails here."""
    found = file_write_files()
    assert sorted(found - FILE_WRITE_FILES.keys()) == []
    assert sorted(FILE_WRITE_FILES.keys() - found) == []
    assert len(found) == 72, len(found)
    kinds = Counter(_kind(cover) for cover in FILE_WRITE_FILES.values())
    assert kinds == {"Pending M3e4d": 1, "Pending M3e4c3b": 69, "OutsideRuntime": 2}, kinds
    assert Counter(name for _path, _scope, _line, name in file_write_points()) == {
        "write_text": 59,
        "write_bytes": 7,
        "unlink": 66,
        "rmtree": 13,
        "copy2": 2,
        "copyfile": 1,
        "copytree": 1,
        "replace": 24,
        "rename": 2,
        "open": 16,
        "fdopen": 10,
        "write": 2,
        "link": 4,
    }


def test_the_file_write_scan_on_a_synthetic_module() -> None:
    """WF2 (D253; kills EF-1, EF-2, EF-3, EF-4, EF-6, EF-9, EF-13, EF-14, EF-15)."""
    assert file_write_scan(_SYNTHETIC) == [
        ("Store.write", 9, "write_text"),
        ("Store.write", 10, "write_bytes"),
        ("Store.write", 11, "unlink"),
        ("Store.write", 12, "rmtree"),
        ("Store.write", 13, "copy2"),
        ("Store.write", 14, "copyfile"),
        ("Store.write", 15, "copytree"),
        ("Store.write", 16, "copy"),
        ("Store.write", 17, "move"),
        ("Store.write", 18, "replace"),
        ("Store.write", 19, "rename"),
        ("Store.write", 20, "remove"),
        ("Store.write", 21, "link"),
        ("Store.write", 22, "write"),
        ("Store.write", 23, "open"),
        ("Store.write", 24, "open"),
        ("Store.write", 25, "open"),
        ("Store.write", 26, "fdopen"),
        ("Store.write", 27, "open"),
        ("Store.write", 28, "replace"),
        ("Store.write", 29, "rename"),
        ("Store.write", 30, "unlink"),
        ("Store.write", 31, "replace"),
        ("Store.write", 45, "replace"),
        ("Store.write.inner", 48, "write_text"),
        ("<module>", 53, "rmtree"),
    ]


def test_the_agent_attributed_row_writes_and_records_its_author() -> None:
    """WF3 (D239, D255; kills EF-7, EF-8)."""
    pending = {path for path, cover in FILE_WRITE_FILES.items() if isinstance(cover, Pending) and cover.owner == "M3e4d"}
    assert pending == FILE_AGENT_ATTRIBUTED_SCOPES.keys() == {_RECORDS}, pending
    assert FILE_AGENT_ATTRIBUTED_SCOPES[_RECORDS] == ("RecordsStore.write_entry", "author")
    points = {(path, scope) for path, scope, _line, _name in file_write_points()}
    for path, (scope, author) in FILE_AGENT_ATTRIBUTED_SCOPES.items():
        assert (path, scope) in points, (path, scope)
        function = _function(path, scope)
        arguments = function.args
        parameters = {arg.arg for arg in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)}
        assert author in parameters, (path, scope, author)
        assert any(
            isinstance(key, ast.Constant) and key.value == author and isinstance(value, ast.Name) and value.id == author
            for node in ast.walk(function)
            if isinstance(node, ast.Dict)
            for key, value in zip(node.keys, node.values)
        ), (path, scope, author)


def test_the_command_line_rows() -> None:
    """WF4 (D167; kills EF-11)."""
    outside = sorted(path for path, cover in FILE_WRITE_FILES.items() if isinstance(cover, OutsideRuntime))
    assert outside == ["src/probos/__main__.py", "src/probos/doctor/checks/data_dir_check.py"], outside
    assert all(path.startswith(OUTSIDE_RUNTIME) for path in outside), outside
    inside = sorted(path for path, cover in FILE_WRITE_FILES.items() if not isinstance(cover, OutsideRuntime))
    assert [path for path in inside if path.startswith(OUTSIDE_RUNTIME)] == []


def test_three_shapes_the_scan_finds_in_src() -> None:
    """WF5 (D253; kills EF-5)."""
    # Methods handed to an executor, not called.
    assert _found("src/probos/cognitive/session_manager.py") == {
        ("SessionManager.close_session", "rename"),
        ("SessionManager._write", "write_text"),
    }
    # A Path rename with one argument.
    assert _found("src/probos/cognitive/dreaming.py") == {("DreamingEngine.dream_cycle", "rename")}
    # The rendered script's writes are text in an f-string; the one point is the file the script is written to.
    assert _found("src/probos/task_sessions/browser.py") == {("write_script", "write_text")}
