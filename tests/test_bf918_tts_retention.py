"""BF-918 (#1626) S3: spoken TTS audio is stored as ``tts_audio`` and swept by age;
anything else holding the same bytes keeps them, and a sweep removes only an entry no
write touched since it was listed; the inventory tool reads and never writes.

Real store, reaper, route and tool. Every path is under ``tmp_path``; nothing touches
the live store.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import sqlite3
import struct
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.attachments.reaper import AttachmentReaper
from probos.audio.tts import TTSResult
from probos.cognitive.episode_archive import ARCHIVE_FILENAME, ArchiveRecord, EpisodeArchive
from probos.config import AttachmentsConfig, LipSyncConfig, PerceptionConfig, TTSConfig
from probos.routers import avatars as avatars_router_mod
from probos.routers import chat as chat_router_mod
from probos.routers.deps import get_runtime
from probos.startup.finalize import _start_attachment_reaper

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DAY = 86400


def _piper_wav(samples: int, *, rate: int = 22050, channels: int = 1) -> bytes:
    """A PCM WAV of ``samples`` frames: Piper's shape by default."""
    data = b"\x00\x00" * samples * channels
    fmt = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, channels, rate, rate * 2 * channels, 2 * channels, 16)
    body = fmt + struct.pack("<4sI", b"data", len(data)) + data
    return struct.pack("<4sI4s", b"RIFF", 4 + len(body), b"WAVE") + body


def _wav_fields(samples: int, *, pad: bytes = b"", **override: int) -> bytes:
    """Piper's canonical 44-byte WAV header with ``override`` applied, then ``samples`` frames of silence."""
    data = b"\x00\x00" * samples + pad
    fields = {
        "riff_size": 36 + len(data), "fmt_size": 16, "fmt": 1, "channels": 1, "rate": 22050,
        "byte_rate": 44100, "align": 2, "bits": 16, "data_size": len(data),
    }
    fields.update(override)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI", b"RIFF", fields["riff_size"], b"WAVE", b"fmt ", fields["fmt_size"],
        fields["fmt"], fields["channels"], fields["rate"], fields["byte_rate"], fields["align"],
        fields["bits"], b"data", fields["data_size"],
    )
    return header + data


async def _write(store, blob: bytes, origin: str, *, mime: str = "audio/wav", age_seconds: float | None = None) -> str:
    sha = hashlib.sha256(blob).hexdigest()
    await store.write(sha, blob, mime, origin=origin)
    if age_seconds is not None:
        async with store._lock:  # noqa: SLF001 -- force-age, as tests/test_attachment_reaper.py does
            store._index[sha]["written_at"] = time.time() - age_seconds  # noqa: SLF001
            store._save_index_sync()  # noqa: SLF001
    return sha


def _reaper(store, *, tts_ttl: int = 900, max_store_bytes: int = 0) -> AttachmentReaper:
    return AttachmentReaper(
        store,
        perception_cfg=PerceptionConfig(enabled=True, frame_retention_seconds=300),
        attachments_cfg=AttachmentsConfig(max_store_bytes=max_store_bytes, tts_audio_retention_seconds=tts_ttl),
    )


@pytest.mark.asyncio
async def test_tts_audio_is_a_known_origin(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    store = FilesystemAttachmentStore(tmp_path)
    sha = await _write(store, _piper_wav(100), "tts_audio")
    assert [s for s, _ in await store.list_by_origin("tts_audio")] == [sha]
    assert "unknown attachment origin" not in caplog.text


@pytest.mark.asyncio
async def test_reaper_deletes_tts_audio_past_its_ttl_and_nothing_else(tmp_path: Path) -> None:
    store = FilesystemAttachmentStore(tmp_path)
    old_tts = await _write(store, _piper_wav(110), "tts_audio", age_seconds=1000)
    new_tts = await _write(store, _piper_wav(120), "tts_audio", age_seconds=10)
    old_chat = await _write(store, _piper_wav(130), "chat_attachment", age_seconds=10 * _DAY)

    summary = await _reaper(store, tts_ttl=900).sweep_once()

    assert summary["age_ttl_removed"] == 1
    assert not await store.exists(old_tts)
    assert await store.exists(new_tts)
    assert await store.exists(old_chat)


@pytest.mark.asyncio
async def test_a_chat_upload_of_the_same_bytes_upgrades_tts_audio(tmp_path: Path) -> None:
    """Spoken first, then uploaded by the Captain: the more durable origin wins, and it is kept.
    An expired spoken WAV in the same sweep is the control: the sweep does delete."""
    store = FilesystemAttachmentStore(tmp_path)
    blob = _piper_wav(140)
    sha = await _write(store, blob, "tts_audio")
    await _write(store, blob, "chat_attachment", age_seconds=10 * _DAY)
    expired = await _write(store, _piper_wav(141), "tts_audio", age_seconds=1000)

    assert [s for s, _ in await store.list_by_origin("chat_attachment")] == [sha]
    assert [s for s, _ in await store.list_by_origin("tts_audio")] == [expired]
    await _reaper(store, tts_ttl=60).sweep_once()
    assert await store.exists(sha)
    assert not await store.exists(expired)


@pytest.mark.asyncio
async def test_speaking_bytes_already_held_never_downgrades_them(tmp_path: Path) -> None:
    """An invariant, not a fix discriminator: before BF-918 ``tts_audio`` was an unknown origin,
    coerced to ``chat_attachment``, so this passed then too. It guards the durability order.
    An expired spoken WAV in the same sweep is the control."""
    store = FilesystemAttachmentStore(tmp_path)
    blob = _piper_wav(150)
    sha = await _write(store, blob, "chat_attachment")
    await _write(store, blob, "tts_audio", age_seconds=10 * _DAY)
    expired = await _write(store, _piper_wav(151), "tts_audio", age_seconds=1000)

    assert [s for s, _ in await store.list_by_origin("chat_attachment")] == [sha]
    await _reaper(store, tts_ttl=60).sweep_once()
    assert await store.exists(sha)
    assert not await store.exists(expired)


@pytest.mark.asyncio
async def test_lru_evicts_tts_audio_first(tmp_path: Path) -> None:
    store = FilesystemAttachmentStore(tmp_path)
    frame = await _write(store, b"\xff\xd8" + b"f" * 4000, "perception_frame", mime="image/jpeg", age_seconds=5)
    spoken = await _write(store, _piper_wav(2000), "tts_audio", age_seconds=1)  # newer than the frame
    total = await store.total_size_bytes()

    summary = await _reaper(store, tts_ttl=_DAY, max_store_bytes=total - 1).sweep_once()

    assert summary["lru_removed"] == 1
    assert not await store.exists(spoken)  # spoken audio goes first, though it is newer
    assert await store.exists(frame)


@pytest.mark.asyncio
async def test_unlink_if_unchanged_removes_only_the_entry_that_was_listed(tmp_path: Path) -> None:
    """Review round 1, A1: the store's conditional removal. Another origin, or a write after the
    listed time, keeps the entry; the listed values remove it and report its bytes; once gone, ``None``."""
    store = FilesystemAttachmentStore(tmp_path)
    blob = _piper_wav(165)
    sha = await _write(store, blob, "tts_audio", age_seconds=1000)
    [(listed, written_at)] = await store.list_by_origin("tts_audio")

    assert listed == sha
    assert await store.unlink_if_unchanged(sha, origin="chat_attachment", written_at=written_at) is None
    assert await store.unlink_if_unchanged(sha, origin="tts_audio", written_at=written_at - 1) is None
    assert await store.exists(sha)
    assert await store.unlink_if_unchanged(sha, origin="tts_audio", written_at=written_at) == len(blob)
    assert not await store.exists(sha)
    assert sha not in json.loads((tmp_path / ".index.json").read_text(encoding="utf-8"))
    assert await store.unlink_if_unchanged(sha, origin="tts_audio", written_at=written_at) is None


def _write_after_listing(store, *, origin: str, nth: int, sha: str, blob: bytes, write_origin: str) -> list[int]:
    """Wrap the real store's listing: right after its ``nth`` listing of ``origin``, write ``blob``
    again under ``write_origin`` (a refresh when that is the same origin, else an upgrade). The write
    lands between a sweep's snapshot and its removals, as the production awaits allow; here the
    order is fixed. Returns the listing count."""
    listed = store.list_by_origin
    calls = [0]

    async def listing_then_write(requested: str) -> list[tuple[str, float]]:
        rows = await listed(requested)
        if requested == origin:
            calls[0] += 1
            if calls[0] == nth:
                await store.write(sha, blob, "audio/wav", origin=write_origin)
        return rows

    store.list_by_origin = listing_then_write
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("write_origin", ["tts_audio", "chat_attachment", "agent_artifact"])
async def test_a_write_after_the_ttl_listing_keeps_its_entry(tmp_path: Path, write_origin: str) -> None:
    """Review round 1, A1: the age pass lists expired spoken audio; a write then refreshes or upgrades
    one entry before its removal. That entry is kept and frees nothing; an untouched expired one is
    removed (the control)."""
    store = FilesystemAttachmentStore(tmp_path)
    blob = _piper_wav(170)
    control_blob = _piper_wav(180)
    target = await _write(store, blob, "tts_audio", age_seconds=1000)
    control = await _write(store, control_blob, "tts_audio", age_seconds=2000)
    calls = _write_after_listing(store, origin="tts_audio", nth=1, sha=target, blob=blob, write_origin=write_origin)

    summary = await _reaper(store, tts_ttl=900).sweep_once()

    assert calls == [1]
    assert summary["age_ttl_removed"] == 1
    assert summary["freed_bytes"] == len(control_blob)
    assert await store.exists(target)
    assert not await store.exists(control)
    assert target in {s for s, _ in await store.list_by_origin(write_origin)}


@pytest.mark.asyncio
@pytest.mark.parametrize("write_origin", ["tts_audio", "chat_attachment", "agent_artifact"])
async def test_a_write_after_the_lru_listing_keeps_its_entry(tmp_path: Path, write_origin: str) -> None:
    """Review round 1, A1: the size pass lists spoken audio oldest first; a write then refreshes or
    upgrades the oldest before its eviction. It is kept and frees nothing, so the pass evicts the next
    one (the control) to get under the cap."""
    store = FilesystemAttachmentStore(tmp_path)
    blob = _piper_wav(190)
    control_blob = _piper_wav(200)
    target = await _write(store, blob, "tts_audio", age_seconds=20)  # the oldest: first to go
    control = await _write(store, control_blob, "tts_audio", age_seconds=10)
    total = await store.total_size_bytes()
    # The age pass lists tts_audio first (nothing has expired under a one-day TTL); the size pass second.
    calls = _write_after_listing(store, origin="tts_audio", nth=2, sha=target, blob=blob, write_origin=write_origin)

    summary = await _reaper(store, tts_ttl=_DAY, max_store_bytes=total - 1).sweep_once()

    assert calls == [2]
    assert summary["lru_removed"] == 1
    assert summary["freed_bytes"] == len(control_blob)
    assert await store.exists(target)
    assert not await store.exists(control)
    assert target in {s for s, _ in await store.list_by_origin(write_origin)}


@pytest.mark.asyncio
async def test_route_stores_speech_as_tts_audio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "attachments"
    target.mkdir()
    monkeypatch.setattr("probos.attachments.store._resolve_attachments_dir", lambda configured: target)
    wav = _piper_wav(160)

    class _Stub:
        name = "piper"

        async def synthesize(self, text, emotion=None, voice_override=None):
            return TTSResult(audio_bytes=wav, mime="audio/wav")

    monkeypatch.setattr("probos.audio.tts.select_backend", lambda *_a, **_k: _Stub())
    rt = SimpleNamespace(config=SimpleNamespace(
        attachments=AttachmentsConfig(attachments_dir=str(target)),
        lipsync=LipSyncConfig(),
        tts=TTSConfig(backend="piper"),
    ))
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()
    app = FastAPI()
    app.include_router(avatars_router_mod.router)
    app.dependency_overrides[get_runtime] = lambda: rt
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            body = (await client.post("/api/avatars/tts", json={"text": "hello"})).json()
        index = json.loads((target / ".index.json").read_text(encoding="utf-8"))
        assert index[body["audio_attachment_id"]]["origin"] == "tts_audio"
    finally:
        chat_router_mod._ATTACHMENT_STORE_CACHE.clear()


@pytest.mark.asyncio
async def test_reaper_starts_for_the_tts_ttl_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Perception off and no size cap: spoken audio still expires."""
    target = tmp_path / "attachments"
    target.mkdir()
    monkeypatch.setattr("probos.attachments.store._resolve_attachments_dir", lambda configured: target)
    config = SimpleNamespace(
        perception=PerceptionConfig(enabled=False),
        attachments=AttachmentsConfig(attachments_dir=str(target), max_store_bytes=0),
    )
    runtime = SimpleNamespace(config=config, attachment_reaper=None)
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()
    try:
        await _start_attachment_reaper(runtime=runtime, config=config)
        assert isinstance(runtime.attachment_reaper, AttachmentReaper)
    finally:
        if runtime.attachment_reaper is not None:
            await runtime.attachment_reaper.stop()
        chat_router_mod._ATTACHMENT_STORE_CACHE.clear()


# --- the inventory tool (scripts/tts_audio_inventory.py) -------------------------------


def _tool():
    spec = importlib.util.spec_from_file_location(
        "tts_audio_inventory", _REPO_ROOT / "scripts" / "tts_audio_inventory.py",
    )
    module = importlib.util.module_from_spec(spec)
    # A dataclass in the tool finds its module's namespace through sys.modules while the module executes.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


async def _legacy_store(data_dir: Path) -> dict[str, str]:
    """A data dir with the shapes a live store holds: legacy spoken WAVs, and what must be kept."""
    store = FilesystemAttachmentStore(data_dir / "attachments")
    shas = {
        "legacy": await _write(store, _piper_wav(700), "chat_attachment", age_seconds=3 * _DAY),
        "legacy_low": await _write(store, _piper_wav(700, rate=16000), "chat_attachment", age_seconds=3 * _DAY),
        "referenced": await _write(store, _piper_wav(800), "chat_attachment", age_seconds=3 * _DAY),
        "stereo": await _write(store, _piper_wav(900, channels=2), "chat_attachment", age_seconds=3 * _DAY),
        "recent": await _write(store, _piper_wav(1000), "chat_attachment", age_seconds=60),
        "spoken_now": await _write(store, _piper_wav(1100), "tts_audio", age_seconds=3 * _DAY),
        "image": await _write(store, b"\x89PNG" + b"i" * 50, "chat_attachment", mime="image/png", age_seconds=3 * _DAY),
    }
    # A chat record that names one WAV, in a real SQLite database (the tool opens every database it finds).
    connection = sqlite3.connect(data_dir / "chat.db")
    try:
        connection.execute("CREATE TABLE chat_thread_messages (id INTEGER PRIMARY KEY, parts TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO chat_thread_messages (parts) VALUES (?)",
            (json.dumps([{"type": "attachment", "attachment_id": shas["referenced"]}]),),
        )
        connection.commit()
    finally:
        connection.close()
    return shas


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_the_dry_run_finds_the_legacy_wavs_and_changes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data_dir = tmp_path / "data"
    shas = asyncio.run(_legacy_store(data_dir))
    before = _snapshot(data_dir)

    assert _tool().main(["--data-dir", str(data_dir), "--list"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert sorted(report["candidate_ids"]) == sorted([shas["legacy"], shas["legacy_low"]])
    assert report["wav_entries"] == 6
    assert report["kept"] == {
        "other_origin": 1, "missing_file": 0, "not_piper_shaped": 1, "too_young": 1, "referenced": 1,
    }
    assert report["unreadable"] == []
    assert _snapshot(data_dir) == before


async def _archive_reference(data_dir: Path, sha: str) -> None:
    """Archive one episode whose outcome names ``sha``, through the real writer: canonical JSON,
    then zlib, in a SQLite BLOB, as dream pruning stores it (``cognitive/episode_archive.py``)."""
    archive = EpisodeArchive(str(data_dir / ARCHIVE_FILENAME))
    await archive.start()
    try:
        record = ArchiveRecord(
            episode_id="bf918-archived",
            document="The Captain's recording, played back to the crew. " * 8,
            metadata={"content_hash": "c" * 64, "outcomes_json": json.dumps([{"attachment_ids": [sha]}])},
        )
        assert await archive.archive([record], reason="capacity") == frozenset({"bf918-archived"})
    finally:
        await archive.stop()


@pytest.mark.parametrize(
    "extra", [["--delete"], ["--delete", "--confirm", "2"], ["--attachments-dir", "elsewhere"]],
)
def test_the_tool_cannot_delete_or_read_another_store(tmp_path: Path, extra: list[str]) -> None:
    """Review round 1, A3 and A5: the tool is read-only and reads only ``<data-dir>/attachments``.
    Each option is refused by the parser, and nothing anywhere under ``tmp_path`` changes, a lock
    file included."""
    data_dir = tmp_path / "data"
    asyncio.run(_legacy_store(data_dir))
    before = _snapshot(tmp_path)

    with pytest.raises(SystemExit) as exited:
        _tool().main(["--data-dir", str(data_dir), *extra])

    assert exited.value.code == 2
    assert _snapshot(tmp_path) == before


def test_only_the_exact_piper_header_is_a_candidate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Review round 1, A4: each malformed WAV breaks exactly one rule of the header Piper writes;
    the canonical one (the control) is the only candidate."""
    data_dir = tmp_path / "data"
    malformed = {
        "no_data_chunk": _wav_fields(700)[:36],
        "riff_size": _wav_fields(701, riff_size=0),
        "fmt_size": _wav_fields(702, fmt_size=0),
        "byte_rate": _wav_fields(703, byte_rate=0),
        "block_align": _wav_fields(704, align=0),
        "payload_absent": _wav_fields(705, data_size=2 * 705 + 100),
        "empty_payload": _wav_fields(0),
        "odd_payload": _wav_fields(706, pad=b"\x00"),
    }

    async def build() -> tuple[str, dict[str, str]]:
        store = FilesystemAttachmentStore(data_dir / "attachments")
        good = await _write(store, _wav_fields(720), "chat_attachment", age_seconds=3 * _DAY)
        bad = {
            name: await _write(store, blob, "chat_attachment", age_seconds=3 * _DAY)
            for name, blob in malformed.items()
        }
        return good, bad

    good, bad = asyncio.run(build())

    assert _tool().main(["--data-dir", str(data_dir), "--list"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["candidate_ids"] == [good]
    assert report["kept"]["not_piper_shaped"] == len(bad) == 8


def test_an_archived_reference_keeps_its_wav(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Review round 1, A2: a WAV named only inside the compressed episode archive is kept; its
    unreferenced twin is still a candidate (the control), and the run creates nothing anywhere."""
    data_dir = tmp_path / "data"
    shas = asyncio.run(_legacy_store(data_dir))
    asyncio.run(_archive_reference(data_dir, shas["legacy"]))
    # The production encoding hides the id from a byte scan: the defect this test proves fixed.
    assert shas["legacy"].encode("ascii") not in (data_dir / ARCHIVE_FILENAME).read_bytes()
    before = _snapshot(data_dir)

    assert _tool().main(["--data-dir", str(data_dir), "--list"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["candidate_ids"] == [shas["legacy_low"]]
    assert report["kept"]["referenced"] == 2  # the chat record's and the archived one
    assert report["unreadable"] == []
    assert _snapshot(data_dir) == before


def test_an_archive_row_that_cannot_be_decoded_keeps_every_candidate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Review round 1, A2: fail closed. An archive row the archive's own decoder rejects keeps
    every candidate, and the file is named."""
    data_dir = tmp_path / "data"
    asyncio.run(_legacy_store(data_dir))
    asyncio.run(_archive_reference(data_dir, "0" * 64))
    connection = sqlite3.connect(data_dir / ARCHIVE_FILENAME)
    try:
        connection.execute("UPDATE episode_archive SET payload = ?", (b"not zlib",))
        connection.commit()
    finally:
        connection.close()

    assert _tool().main(["--data-dir", str(data_dir)]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["candidates"] == 0
    assert report["unreadable"] == [str((data_dir / ARCHIVE_FILENAME).resolve())]


@pytest.mark.parametrize("name", ["chroma.sqlite3-wal", "backups/episodic-2026-10-01.tar"])
def test_a_reference_in_a_file_of_any_name_keeps_its_wav(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str,
) -> None:
    """Review round 1, A2: no file is skipped for its name; a WAL file and an uncompressed tar
    backup are real carriers. The unreferenced twin is the control."""
    data_dir = tmp_path / "data"
    shas = asyncio.run(_legacy_store(data_dir))
    carrier = data_dir / name
    carrier.parent.mkdir(parents=True, exist_ok=True)
    carrier.write_bytes(b"\x37\x7f\x06\x82 frame " + shas["legacy"].encode("ascii") + b" end")

    assert _tool().main(["--data-dir", str(data_dir), "--list"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["candidate_ids"] == [shas["legacy_low"]]
    assert report["unreadable"] == []


def _record_naming(data_dir: Path, sha: str) -> Path:
    """A directory of records outside the store, holding one file that names ``sha``."""
    records = data_dir / "records"
    records.mkdir()
    (records / "note.txt").write_bytes(b"replayed " + sha.encode("ascii"))
    return records.resolve()


def _refusing_scandir(refused: Path) -> object:
    """``os.scandir`` refusing to list ``refused`` as the OS refuses a directory the user may
    not read. Portable: no permission is changed, and every other directory lists."""
    real_scandir = os.scandir
    target = os.path.normcase(str(refused))

    def scandir(path: str | os.PathLike[str] = ".") -> object:
        if os.path.normcase(os.fspath(path)) == target:
            raise PermissionError(13, "Access is denied", os.fspath(path))
        return real_scandir(path)

    return scandir


def test_a_directory_that_cannot_be_listed_keeps_every_candidate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 2, F1: a directory the walk cannot list is named in ``unreadable`` and
    keeps every candidate. The first run is the control: listed, the same directory's
    record keeps its WAV and only the unreferenced twin is a candidate."""
    data_dir = tmp_path / "data"
    shas = asyncio.run(_legacy_store(data_dir))
    records = _record_naming(data_dir, shas["legacy"])
    tool = _tool()

    assert tool.main(["--data-dir", str(data_dir), "--list"]) == 0
    control = json.loads(capsys.readouterr().out)
    assert control["candidate_ids"] == [shas["legacy_low"]]
    assert control["unreadable"] == []

    monkeypatch.setattr(os, "scandir", _refusing_scandir(records))
    assert tool.main(["--data-dir", str(data_dir), "--list"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["candidate_ids"] == []
    assert report["kept"]["referenced"] == 3  # every eligible WAV: legacy, legacy_low, referenced
    assert report["unreadable"] == [f"{records}{os.sep}"]


@pytest.mark.parametrize("probe", ["islink", "isjunction"])
def test_a_link_to_a_directory_is_not_followed_and_keeps_every_candidate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, probe: str,
) -> None:
    """Review round 2, F1: a symbolic link or a junction to a directory is never followed and
    is named, so every candidate is kept. Portable: the directory is real and only the link
    check answers yes for it. The first run is the control."""
    data_dir = tmp_path / "data"
    shas = asyncio.run(_legacy_store(data_dir))
    records = _record_naming(data_dir, shas["legacy"])
    tool = _tool()

    assert tool.main(["--data-dir", str(data_dir), "--list"]) == 0
    assert json.loads(capsys.readouterr().out)["candidate_ids"] == [shas["legacy_low"]]

    real_check = {"islink": os.path.islink, "isjunction": os.path.isjunction}[probe]
    target = os.path.normcase(str(records))
    monkeypatch.setattr(os.path, probe, lambda path: os.path.normcase(os.fspath(path)) == target or real_check(path))
    assert tool.main(["--data-dir", str(data_dir), "--list"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["candidate_ids"] == []
    assert report["unreadable"] == [f"{records}{os.sep}"]


def test_a_store_directory_that_cannot_be_listed_stops_the_inventory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 2: the store's own listing (the ``unindexed_wavs`` count) is not skipped in
    silence; it raises, as an unreadable index does, and prints no report. The first run is
    the control: one WAV with no index entry is counted."""
    data_dir = tmp_path / "data"
    asyncio.run(_legacy_store(data_dir))
    (data_dir / "attachments" / f"{'e' * 64}.wav").write_bytes(_piper_wav(10))
    tool = _tool()

    assert tool.main(["--data-dir", str(data_dir)]) == 0
    assert json.loads(capsys.readouterr().out)["unindexed_wavs"] == 1

    monkeypatch.setattr(os, "scandir", _refusing_scandir((data_dir / "attachments").resolve()))
    with pytest.raises(PermissionError):
        tool.main(["--data-dir", str(data_dir)])
    assert capsys.readouterr().out == ""


def _link_directory(link: Path, target: Path) -> None:
    """Make ``link`` a real link to the directory ``target``: a junction on Windows (no
    privilege needed), a symbolic link elsewhere. Skips the test where this machine cannot."""
    try:
        if sys.platform == "win32":
            import _winapi  # CPython's Windows-only module; the test alone uses it, to make a junction without a shell

            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot make a directory link on this machine: {exc}")
    assert os.path.islink(link) or os.path.isjunction(link)  # the premise: a real link, not a copy


def test_a_linked_store_is_read_through_its_link_and_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Review round 3, A-R3-1: ``<data-dir>/attachments`` linked to a store outside the data
    directory is read as the vessel reads it, and the report names the link's target. The
    first run, a plain store, is the control: ``attachments_link`` is null."""
    tool = _tool()
    plain = tmp_path / "plain"
    asyncio.run(_legacy_store(plain))
    assert tool.main(["--data-dir", str(plain)]) == 0
    assert json.loads(capsys.readouterr().out)["attachments_link"] is None

    data_dir = tmp_path / "data"
    external = tmp_path / "external_store"
    data_dir.mkdir()
    external.mkdir()
    _link_directory(data_dir / "attachments", external)
    shas = asyncio.run(_legacy_store(data_dir))  # the store resolves its root, so it writes into the target
    assert (external / ".index.json").is_file()  # the premise: the store lives outside the data directory

    assert tool.main(["--data-dir", str(data_dir), "--list"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["attachments_link"] == os.path.realpath(external)
    assert sorted(report["candidate_ids"]) == sorted([shas["legacy"], shas["legacy_low"]])
    assert report["wav_entries"] == 6
    assert report["unreadable"] == []


def test_a_store_linked_inside_the_data_directory_keeps_every_candidate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Review round 3: when ``<data-dir>/attachments`` links to a directory inside the data
    directory, the walk reads that directory under its own name (it is not a link) and its
    index names every id, so every candidate is kept: conservative, never a false candidate."""
    data_dir = tmp_path / "data"
    inside = data_dir / "store"
    inside.mkdir(parents=True)
    _link_directory(data_dir / "attachments", inside)
    asyncio.run(_legacy_store(data_dir))

    assert _tool().main(["--data-dir", str(data_dir), "--list"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["candidate_ids"] == []
    assert report["kept"]["referenced"] == 3  # every eligible WAV: legacy, legacy_low, referenced
    assert report["unreadable"] == []


def test_unindexed_wavs_are_matched_as_the_os_matches_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Review round 3, A-R3-2: ``.wav``, ``.WAV`` and ``.WaV`` files with no index entry are all
    WAV files to Windows, as ``Path.glob`` counted them before round 2; elsewhere only ``.wav`` is."""
    attachments = tmp_path / "data" / "attachments"
    attachments.mkdir(parents=True)
    for name in ("lower.wav", "upper.WAV", "mixed.WaV"):
        (attachments / name).write_bytes(_piper_wav(10))

    assert _tool().main(["--data-dir", str(tmp_path / "data")]) == 0

    assert json.loads(capsys.readouterr().out)["unindexed_wavs"] == (3 if os.name == "nt" else 1)


def test_a_store_link_to_nothing_stops_the_inventory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Review round 3: ``<data-dir>/attachments`` linked to a directory that is gone (a removed
    or unplugged store) cannot be listed; it is not an absent store. The run raises and prints
    no report, where a report of an empty store would be falsely clean."""
    data_dir = tmp_path / "data"
    gone = tmp_path / "gone"
    data_dir.mkdir()
    gone.mkdir()
    link = data_dir / "attachments"
    _link_directory(link, gone)
    gone.rmdir()
    assert os.path.lexists(link) and not os.path.exists(link)  # the premise: a link to nothing

    with pytest.raises(OSError):
        _tool().main(["--data-dir", str(data_dir)])
    assert capsys.readouterr().out == ""
