"""AD-1200 bounded handle reads, including actual filesystem retarget races."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.security import file_access as access
from probos.security.file_access import BoundedReadStatus as Status


@pytest.fixture(autouse=True)
def _candidate_provenance() -> Any:
    yield
    source = Path(__file__).resolve().parents[1] / "src"
    assert all(
        Path(module.__file__).resolve().is_relative_to(source)
        for name, module in tuple(sys.modules.items())
        if (name == "probos" or name.startswith("probos."))
        and getattr(module, "__file__", None)
    )


def _read(path: Path, root: Path, **kwargs: Any) -> access.BoundedTextRead:
    return access.read_bounded_utf8(
        str(path), authorized_root=root, protected_roots=kwargs.pop("protected_roots", ()),
        **kwargs,
    )


def _junction(link: Path, target: Path) -> None:
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
        assert link.is_junction()
    else:
        link.symlink_to(target, target_is_directory=True)
        assert link.is_symlink()


def _unlink_junction(path: Path) -> None:
    if os.name == "nt":
        path.rmdir()
    else:
        path.unlink()


@pytest.mark.parametrize(
    ("payload", "status", "text"),
    [
        (b"rules\n", Status.OK, "rules\n"),
        (b"", Status.EMPTY, ""),
        (b" \t\r\n", Status.EMPTY, " \t\r\n"),
        (b"\xef\xbb\xbfrules", Status.OK, "rules"),
        ("\u03c0 \U0001f642".encode(), Status.OK, "\u03c0 \U0001f642"),
        (b"a\xffb", Status.INVALID_UTF8, ""),
        (b"\xe2\x82", Status.INVALID_UTF8, ""),
        (b"a\x00b", Status.BINARY, ""),
        (b"a\x01b", Status.BINARY, ""),
        ("a\u0085b".encode(), Status.BINARY, ""),
    ],
)
def test_read_bounded_utf8_decoding_has_typed_outcome(
    tmp_path: Path, payload: bytes, status: Status, text: str,
) -> None:
    target = tmp_path / "AGENTS.md"
    target.write_bytes(payload)
    result = _read(target, tmp_path)
    assert result.status == status
    assert result.text == text
    assert result.bytes_read == len(payload)


@pytest.mark.parametrize("size", [8191, 8192, 8193, 30000])
def test_read_bounded_utf8_exact_byte_limit_includes_only_one_detection_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, size: int,
) -> None:
    target = tmp_path / "AGENTS.md"
    target.write_bytes(b"x" * size)
    requests: list[int] = []
    original = os.read

    def read(fd: int, count: int) -> bytes:
        requests.append(count)
        return original(fd, count)

    monkeypatch.setattr(access.os, "read", read)
    result = _read(target, tmp_path)
    assert requests == [8193]
    assert result.bytes_read == min(size, 8193)
    assert result.text == "x" * min(size, 8192)
    assert result.status == (Status.TRUNCATED if size > 8192 else Status.OK)


@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"])
def test_read_bounded_utf8_truncated_terminal_code_point_is_withheld(
    tmp_path: Path, bom: bytes,
) -> None:
    prefix = b"x" * (8191 - len(bom))
    target = tmp_path / "AGENTS.md"
    target.write_bytes(bom + prefix + "\u20ac".encode() + b"tail")
    result = _read(target, tmp_path)
    assert result.status == Status.TRUNCATED
    assert result.bytes_read == 8193
    assert result.text == prefix.decode()
    assert "\ufffd" not in result.text


def test_read_bounded_utf8_invalid_interior_is_not_a_truncated_prefix(tmp_path: Path) -> None:
    target = tmp_path / "AGENTS.md"
    target.write_bytes(b"x" * 100 + b"\xff" + b"x" * 9000)
    result = _read(target, tmp_path)
    assert result.status == Status.INVALID_UTF8 and result.text == ""


def test_read_bounded_utf8_absent_and_non_regular_are_distinct(tmp_path: Path) -> None:
    assert _read(tmp_path / "absent", tmp_path).status == Status.ABSENT
    folder = tmp_path / "AGENTS.md"
    folder.mkdir()
    assert _read(folder, tmp_path).status == Status.NOT_REGULAR


@pytest.mark.parametrize(
    "raw", ["", "\x00", "C:relative", r"\\?\C:\AGENTS.md", r"\\.\NUL", "AGENTS.md:stream", "\ud800", None, "NUL.md"],
)
def test_read_bounded_utf8_malformed_paths_fail_before_open(
    tmp_path: Path, raw: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("invalid path reached the filesystem read")

    monkeypatch.setattr(access.os, "read", unexpected)
    result = access.read_bounded_utf8(raw, authorized_root=tmp_path, protected_roots=())
    assert result.status == Status.INVALID_PATH


def test_read_bounded_utf8_missing_absolute_root_does_not_infer_cwd(tmp_path: Path) -> None:
    result = access.read_bounded_utf8(
        "AGENTS.md", authorized_root=Path("."), protected_roots=(),
    )
    assert result.status == Status.INVALID_PATH


def test_validate_read_location_explicit_authority_and_invalid_inputs(tmp_path: Path) -> None:
    assert access.validate_read_location(tmp_path) == tmp_path
    assert access.validate_read_location("child", relative_base=tmp_path) == tmp_path / "child"
    for raw in ("", None, "relative", "\x00"):
        with pytest.raises(ValueError):
            access.validate_read_location(raw)


def test_read_bounded_utf8_relative_name_uses_only_explicit_root(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("local", encoding="utf-8")
    result = access.read_bounded_utf8(
        "AGENTS.md", authorized_root=tmp_path, protected_roots=(),
    )
    assert result.text == "local"


def test_read_bounded_utf8_floor_policy_and_containment_preserved(tmp_path: Path) -> None:
    root = tmp_path / "authorized"
    root.mkdir()
    target = root / "AGENTS.md"
    target.write_text("private", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    assert _read(outside, root).status == Status.DENIED
    assert _read(target, root, protected_roots=[root]).status == Status.DENIED
    assert _read(target, root, permitted_roots=[tmp_path / "other"]).status == Status.DENIED
    assert _read(target, root, protected_roots=[root], exempt_roots=[target]).text == "private"
    secret = root / "credential_vault.json"
    secret.write_text("secret", encoding="utf-8")
    assert _read(secret, root, exempt_roots=[secret]).status == Status.DENIED


def test_read_bounded_utf8_existing_junction_never_reads_outside_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "AGENTS.md").write_bytes(b"OUTSIDE-BYTES")
    link = tmp_path / "authorized"
    _junction(link, outside)
    calls: list[int] = []
    original = os.read

    def read(fd: int, count: int) -> bytes:
        calls.append(fd)
        return original(fd, count)

    monkeypatch.setattr(access.os, "read", read)
    try:
        result = _read(link / "AGENTS.md", link)
        assert result.status == Status.UNSAFE_PATH
        assert result.bytes_read == 0 and calls == []
    finally:
        _unlink_junction(link)


@pytest.mark.parametrize("swap", ["root", "ancestor", "file"])
def test_read_bounded_utf8_retarget_happens_but_outside_bytes_are_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, swap: str,
) -> None:
    ancestor = tmp_path / "container"
    root = ancestor / "authorized"
    root.mkdir(parents=True)
    target = root / "AGENTS.md"
    target.write_bytes(b"AUTHORIZED-BYTES")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "AGENTS.md").write_bytes(b"OUTSIDE-BYTES")
    (outside / "authorized").mkdir()
    (outside / "authorized" / "AGENTS.md").write_bytes(b"OUTSIDE-BYTES")
    changed = target if swap == "file" else root if swap == "root" else ancestor
    displaced = tmp_path / "displaced"
    happened = False
    read_calls: list[bytes] = []
    original_read = os.read

    def read(fd: int, count: int) -> bytes:
        data = original_read(fd, count)
        read_calls.append(data)
        return data

    def retarget() -> None:
        nonlocal happened
        changed.rename(displaced)
        if swap == "file":
            (outside / "AGENTS.md").rename(changed)
        else:
            _junction(changed, outside)
        happened = True

    if os.name == "nt":
        original_open = access._open_windows_instruction_path

        def open_path(path: Path, *, directory: bool) -> int:
            if path == changed and not happened:
                retarget()
            return original_open(path, directory=directory)

        monkeypatch.setattr(access, "_open_windows_instruction_path", open_path)
    else:
        original_open = os.open

        def open_path(path: Any, flags: int, **kwargs: Any) -> int:
            if path == changed.name and not happened:
                retarget()
            return original_open(path, flags, **kwargs)

        monkeypatch.setattr(access.os, "open", open_path)
    monkeypatch.setattr(access.os, "read", read)
    try:
        result = _read(target, root)
        assert happened, "the retarget race fixture did not fire"
        assert target.read_bytes() == b"OUTSIDE-BYTES"
        assert result.status in (Status.UNSAFE_PATH, Status.CHANGED, Status.IO_ERROR)
        assert result.text == "" and result.bytes_read == 0
        assert read_calls == [], "validation must precede every byte read"
    finally:
        if happened:
            if swap == "file":
                changed.unlink()
            else:
                _unlink_junction(changed)
            displaced.rename(changed)


def test_read_bounded_utf8_observed_write_withholds_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "AGENTS.md"
    target.write_bytes(b"OLD")
    original = os.read

    def read(fd: int, count: int) -> bytes:
        data = original(fd, count)
        target.write_bytes(b"CHANGED-LENGTH")
        return data

    monkeypatch.setattr(access.os, "read", read)
    result = _read(target, tmp_path)
    assert target.read_bytes() == b"CHANGED-LENGTH"
    assert result.status == Status.CHANGED
    assert result.text == "" and result.bytes_read == 3


def test_read_bounded_utf8_io_errors_log_reason_without_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    target = tmp_path / "AGENTS.md"
    target.write_bytes(b"SENSITIVE-INSTRUCTION")

    def read(fd: int, count: int) -> bytes:
        raise OSError("SENSITIVE-INSTRUCTION")

    monkeypatch.setattr(access.os, "read", read)
    result = _read(target, tmp_path)
    assert result.status == Status.IO_ERROR
    assert "io_error" in caplog.text
    assert "SENSITIVE-INSTRUCTION" not in caplog.text


def test_read_bounded_utf8_short_read_is_not_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "AGENTS.md"
    target.write_bytes(b"longer")
    monkeypatch.setattr(access.os, "read", lambda fd, count: b"lo")
    result = _read(target, tmp_path)
    assert result.status == Status.IO_ERROR
    assert result.text == "" and result.bytes_read == 2


def test_read_bounded_utf8_handle_ctime_compares_with_same_stat_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "AGENTS.md"
    target.write_bytes(b"stable")
    original = os.fstat

    def fstat(fd: int) -> Any:
        info = original(fd)
        return SimpleNamespace(
            st_dev=info.st_dev, st_ino=info.st_ino, st_mode=info.st_mode,
            st_size=info.st_size, st_mtime_ns=info.st_mtime_ns,
            st_ctime_ns=info.st_ctime_ns + 1,
        )

    monkeypatch.setattr(access.os, "fstat", fstat)
    result = _read(target, tmp_path)
    assert result.status == (Status.OK if os.name == "nt" else Status.CHANGED)


def test_read_bounded_utf8_selected_file_disappearance_is_not_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "AGENTS.override.md"
    target.write_text("selected", encoding="utf-8")
    original = access.resolve_read_path

    def resolve(*args: Any, **kwargs: Any) -> Path:
        result = original(*args, **kwargs)
        target.unlink()
        return result

    monkeypatch.setattr(access, "resolve_read_path", resolve)
    result = _read(target, tmp_path)
    assert not target.exists()
    assert result.status == Status.CHANGED and result.text == ""
