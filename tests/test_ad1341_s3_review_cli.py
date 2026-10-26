"""AD-1341 S3 M2 (#1569): ``probos archive pending`` and ``probos archive veto``, the Captain's review before canon.

The real ``_cmd_archive``, ``_cmd_reset`` and ``main`` on a temporary data directory, with S1's real configuration,
Ship's Records producers, ``ArchiveStore`` and ``OracleService``. The config loader is the one stand-in, as in S1's
tests (``main``'s dispatch test also replaces the command it dispatches to). The tests are synchronous, because each
command runs its own event loop, as the CLI does.
"""

from __future__ import annotations

import asyncio
from argparse import Namespace as _Namespace
from pathlib import Path
from typing import Any

import pytest

from probos import __main__ as cli
from tests.test_ad1341_s1_reset_and_erase import (
    _CONVERGENCE,
    _NEXT_SHIP,
    _SHIP,
    _archive_store,
    _config,
    _data_dir,
    _erase,
    _oracle_query,
    _records,
    _reset,
    _rows,
    _write_records,
)
from tests.test_ad1341_s3_veto_store import _PRIVATE, _REVISED, _counts, _naming, _review_scene


def _archive(monkeypatch: pytest.MonkeyPatch, config: Any, data_dir: Path, command: str, **values: Any) -> Any:
    """The real ``_cmd_archive`` with the loader returning ``config``; returns what it returns."""
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(cli, "_load_config_with_fallback", lambda _path: (config, None))
    return cli._cmd_archive(_Namespace(archive_cmd=command, config=None, data_dir=data_dir, **values))


def _veto(
    monkeypatch: pytest.MonkeyPatch, config: Any, data_dir: Path, source_ref: str, reason: str = "not canon",
    *, yes: bool = True,
) -> Any:
    return _archive(monkeypatch, config, data_dir, "veto", source_ref=source_ref, reason=reason, yes=yes)


def _vetoes_on_disk(archive: Path) -> int:
    """Veto rows, without creating the file when the command never opened it."""
    if not archive.exists():
        return 0
    return _rows(archive, "SELECT COUNT(*) FROM archive_vetoes")[0][0]


# --- C1: the review ------------------------------------------------------------------------------------------------


def test_pending_shows_what_the_next_promotion_would_do_with_each_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    archive = tmp_path / "archive.db"

    async def _scene() -> dict[str, str]:
        store = _archive_store(tmp_path)
        await store.initialize()
        try:
            return await _review_scene(data_dir, store, archive)
        finally:
            await store.close()

    refs = asyncio.run(_scene())
    ids = dict(_rows(archive, "SELECT source_ref, id FROM archive"))
    before = _counts(archive)

    assert _archive(monkeypatch, _config(tmp_path), data_dir, "pending") == 0

    out = capsys.readouterr().out
    assert f"Ship's Archive review for timeline {_SHIP}: 5 eligible, 1 withheld" in out
    assert f"  + would be promoted (a revision of entry {ids[refs['revised']]}): {refs['revised']}" in out
    assert f"  = already archived (entry {ids[refs['present']]}): {refs['present']}" in out
    assert f"  x erased by the Captain: {refs['erased']}" in out
    assert f"  x vetoed by the Captain: {refs['vetoed']}" in out
    assert f"  + would be promoted: {refs['new']}" in out
    assert f"  - withheld: {_PRIVATE}" in out
    assert _counts(archive) == before


# --- C2: the real seam -------------------------------------------------------------------------------------------


def test_a_vetoed_source_survives_two_resets_without_reaching_the_archive_or_a_later_crew(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    archive = tmp_path / "archive.db"

    assert _archive(monkeypatch, config, data_dir, "pending") == 0
    assert f"  + would be promoted: {_CONVERGENCE}" in capsys.readouterr().out  # premise: it is pending

    assert _veto(monkeypatch, config, data_dir, _CONVERGENCE, "  not canon: one officer's reading  ") == 0
    assert "never promoted" in capsys.readouterr().out
    assert _rows(archive, "SELECT timeline_id, source_kind, source_ref, reason FROM archive_vetoes") == [
        (_SHIP, "convergence_report", _CONVERGENCE, "not canon: one officer's reading"),
    ]

    assert _reset(monkeypatch, config, data_dir) == 0
    assert "1 vetoed by the Captain" in capsys.readouterr().out
    assert _rows(archive, "SELECT source_kind FROM archive") == [("captains_log",)]

    # The next crew revises the report; its reset does not archive it either.
    (data_dir / "ontology" / "instance_id").write_text(_NEXT_SHIP, encoding="utf-8")
    asyncio.run(_records(data_dir).write_entry(
        author="system", path=_CONVERGENCE, content=_REVISED, message="AD-551: Convergence report (revised)",
        classification="ship",
    ))
    assert _reset(monkeypatch, config, data_dir) == 0
    assert "1 vetoed by the Captain" in capsys.readouterr().out
    assert _rows(archive, "SELECT COUNT(*) FROM archive WHERE source_ref = ?", (_CONVERGENCE,)) == [(0,)]
    assert _rows(
        archive,
        "SELECT timeline_id, created_count, present_count, erased_count, withheld_count FROM generations ORDER BY id",
    ) == [(_SHIP, 1, 0, 0, 1), (_NEXT_SHIP, 0, 1, 0, 1)]

    results = asyncio.run(_oracle_query(tmp_path, "coolant drift"))
    assert results  # premise: the Captain's log is there to be read
    assert not any("officers" in result.content for result in results)  # the vetoed report never reached a crew

    assert _archive(monkeypatch, config, data_dir, "pending") == 0
    assert f"  x vetoed by the Captain: {_CONVERGENCE}" in capsys.readouterr().out


# --- C3: what a veto refuses ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "code", "vetoes"),
    [
        ("not-eligible", 1, 0),
        ("withheld", 1, 0),
        ("archived", 1, 0),
        ("erased", 0, 0),
        ("again", 0, 1),
        ("blank-reason", 2, 0),
        ("declined", 0, 0),
        ("disabled", 2, 0),
    ],
    ids=["not-eligible", "withheld", "archived", "erased", "again", "blank-reason", "declined", "disabled"],
)
def test_a_veto_that_cannot_or_need_not_happen_vetoes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, code: int, vetoes: int,
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path, archive_enabled=case != "disabled")
    archive = tmp_path / "archive.db"
    ref, reason, yes = _CONVERGENCE, "not canon", True
    if case in ("archived", "erased"):
        assert _reset(monkeypatch, config, data_dir) == 0  # archives the report
    if case == "erased":
        (entry_id,) = _rows(archive, "SELECT id FROM archive WHERE source_ref = ?", (_CONVERGENCE,))[0]
        assert _erase(monkeypatch, config, entry_id, "superseded") == 0
    if case == "again":
        assert _veto(monkeypatch, config, data_dir, _CONVERGENCE, "the first veto") == 0
    if case == "not-eligible":
        ref = "reports/no-such-report.md"
    if case == "withheld":
        ref = _PRIVATE
    if case == "blank-reason":
        reason = "   "
    if case == "declined":
        yes = False
        monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    assert _veto(monkeypatch, config, data_dir, ref, reason, yes=yes) == code

    assert _vetoes_on_disk(archive) == vetoes
    if case == "disabled":
        assert not archive.exists()


# --- C4, C5: the parser and the dry run --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "attribute", "value"),
    [
        (["archive", "pending"], "archive_cmd", "pending"),
        (["--data-dir", "elsewhere", "archive", "pending"], "data_dir", Path("elsewhere")),
        (["archive", "veto", _CONVERGENCE, "--reason", "not canon", "--yes"], "source_ref", _CONVERGENCE),
        (["--config", "named.yaml", "archive", "veto", _CONVERGENCE, "--reason", "r"], "config", Path("named.yaml")),
        (["archive", "veto", _CONVERGENCE, "--reason", "r", "--data-dir", "elsewhere"], "data_dir", Path("elsewhere")),
    ],
    ids=["pending", "pending-root-data-dir", "veto", "veto-root-config", "veto-own-data-dir"],
)
def test_main_dispatches_pending_and_veto_with_the_captains_options(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], attribute: str, value: Any,
) -> None:
    seen: list[_Namespace] = []

    def _command(args: _Namespace) -> int:
        seen.append(args)
        return 3

    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)  # no repository .env into the worker
    monkeypatch.setattr(asyncio, "set_event_loop_policy", lambda policy: None)  # main sets one on Windows
    monkeypatch.setattr(cli, "_cmd_archive", _command)
    monkeypatch.setattr("sys.argv", ["probos", *argv])

    with pytest.raises(SystemExit) as exited:
        cli.main()

    assert exited.value.code == 3
    assert [getattr(args, attribute) for args in seen] == [value]


def test_the_dry_run_points_the_captain_to_the_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))

    assert _reset(monkeypatch, _config(tmp_path), data_dir, dry_run=True) == 0

    out = capsys.readouterr().out
    assert "2 to promote, 1 withheld" in out  # S1's plan line, unchanged
    assert "probos archive pending" in out and "probos archive veto" in out
    assert not (tmp_path / "archive.db").exists()


def test_only_the_cli_vetoes_a_source() -> None:
    """``veto_source`` is named in ``src`` by ``__main__.py`` alone: no agent or service vetoes or un-vetoes."""
    assert _naming("veto_source") == {"__main__.py"}
