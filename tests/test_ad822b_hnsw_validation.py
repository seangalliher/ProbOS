"""AD-822b: structural HNSW file validation tests.

Synthesize valid and corrupted HNSW directory layouts under ``tmp_path``.
The fake ``header.bin`` writer must match the struct layout pinned in
:data:`probos.episodic_health.HNSW_HEADER_STRUCT_FMT` (verified against
the preserved corrupted dir on 2026-05-23 \u2014 see
``prompts/ad-822b/ad-822b-hnsw-validation.md`` Step R2).
"""

from __future__ import annotations

import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

from probos.episodic_health import (
    HNSW_HEADER_BYTES,
    HNSW_HEADER_STRUCT_FMT,
    HNSW_LENGTH_ENTRY_BYTES,
    check_episodic_health,
    validate_hnsw_files,
)


def _build_test_header(
    *,
    max_elements: int,
    cur_element_count: int,
    size_data_per_element: int,
) -> bytes:
    """Emit a 100-byte chroma-hnswlib ``header.bin`` matching the
    production parser. Only the three fields the validation reads are
    meaningful; everything else uses plausible defaults so the bytes
    decode cleanly.
    """
    return struct.pack(
        HNSW_HEADER_STRUCT_FMT,
        1,                          # version (u32)
        0,                          # offsetLevel0_
        max_elements,               # max_elements_
        cur_element_count,          # cur_element_count
        size_data_per_element,      # size_data_per_element_
        max(0, size_data_per_element - 8),   # label_offset_ (placeholder)
        0,                          # offsetData_
        0,                          # maxlevel_ (i32)
        0,                          # enterpoint_node_ (u32)
        16,                         # maxM_
        32,                         # maxM0_
        16,                         # M_
        0.36,                       # mult_
        100,                        # ef_construction_
    )


def _write_valid_hnsw_dir(
    parent: Path,
    *,
    max_elements: int = 100,
    cur_element_count: int = 50,
    size_data_per_element: int = 1676,
) -> Path:
    """Construct a structurally valid HNSW segment dir."""
    seg = parent / "deadbeef-0000-0000-0000-000000000000"
    seg.mkdir()
    header_bytes = _build_test_header(
        max_elements=max_elements,
        cur_element_count=cur_element_count,
        size_data_per_element=size_data_per_element,
    )
    assert len(header_bytes) == HNSW_HEADER_BYTES
    (seg / "header.bin").write_bytes(header_bytes)
    (seg / "data_level0.bin").write_bytes(
        b"\x00" * (size_data_per_element * max_elements)
    )
    (seg / "length.bin").write_bytes(
        b"\x00" * (max_elements * HNSW_LENGTH_ENTRY_BYTES)
    )
    (seg / "link_lists.bin").write_bytes(b"\x00" * 64)
    return seg


def test_validate_healthy_dir_returns_ok(tmp_path: Path) -> None:
    _write_valid_hnsw_dir(tmp_path)
    # Acceptance criterion 7: validation runs in <50ms on healthy dir.
    start = time.perf_counter()
    result = validate_hnsw_files(tmp_path)
    elapsed_ms = (time.perf_counter() - start) * 1000
    print(f"validate_hnsw_files elapsed: {elapsed_ms:.2f}ms")
    assert result.ok
    assert result.errors == ()
    assert result.dirs_checked == 1
    assert elapsed_ms < 50, f"validation took {elapsed_ms:.2f}ms (>50ms budget)"


def test_validate_truncated_data_level0_returns_error(tmp_path: Path) -> None:
    seg = _write_valid_hnsw_dir(tmp_path)
    # Truncate data_level0.bin to half its expected size
    f = seg / "data_level0.bin"
    f.write_bytes(b"\x00" * (f.stat().st_size // 2))

    result = validate_hnsw_files(tmp_path)
    assert not result.ok
    assert any("data_level0.bin" in e for e in result.errors)


def test_validate_missing_header_skipped(tmp_path: Path) -> None:
    """A dir without header.bin is not an HNSW segment dir \u2014 skip it."""
    seg = tmp_path / "not-an-hnsw-segment"
    seg.mkdir()
    (seg / "random.txt").write_text("hi")

    result = validate_hnsw_files(tmp_path)
    assert result.ok
    assert result.dirs_checked == 0


def test_validate_cur_element_count_exceeds_max_returns_error(
    tmp_path: Path,
) -> None:
    seg = tmp_path / "deadbeef-0000-0000-0000-000000000000"
    seg.mkdir()
    # Hand-build a header where cur > max but data/length files match
    # max (so the only triggered error is the cur > max check).
    header_bytes = _build_test_header(
        max_elements=100,
        cur_element_count=999,
        size_data_per_element=1676,
    )
    (seg / "header.bin").write_bytes(header_bytes)
    (seg / "data_level0.bin").write_bytes(b"\x00" * (1676 * 100))
    (seg / "length.bin").write_bytes(
        b"\x00" * (100 * HNSW_LENGTH_ENTRY_BYTES)
    )
    (seg / "link_lists.bin").write_bytes(b"\x00" * 64)

    result = validate_hnsw_files(tmp_path)
    assert not result.ok
    assert any("cur_element_count" in e for e in result.errors)


def test_validate_returns_ok_on_first_boot_missing_data_dir(
    tmp_path: Path,
) -> None:
    """First boot: data_dir doesn't exist yet \u2014 treat as healthy."""
    nonexistent = tmp_path / "never-created"
    result = validate_hnsw_files(nonexistent)
    assert result.ok
    assert result.dirs_checked == 0


def test_probe_subprocess_returns_exit_code_5_on_validation_failure(
    tmp_path: Path,
) -> None:
    """End-to-end: torn HNSW dir \u2192 probe subprocess exits 5."""
    seg = _write_valid_hnsw_dir(tmp_path)
    # Need a chroma.sqlite3 marker for the probe to advance past the
    # 'no-chroma-sqlite' early exit.
    (tmp_path / "chroma.sqlite3").write_bytes(b"\x00" * 4096)
    # Truncate data_level0.bin so validation fires.
    f = seg / "data_level0.bin"
    f.write_bytes(b"\x00" * 16)

    proc = subprocess.run(
        [sys.executable, "-m", "probos._episodic_probe", str(tmp_path)],
        capture_output=True,
        timeout=30,
    )
    assert proc.returncode == 5, (
        f"expected exit 5; got {proc.returncode}\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert b"hnsw-validation" in proc.stderr


def test_propagates_through_check_episodic_health(tmp_path: Path) -> None:
    """exit code 5 \u2192 EpisodicHealthResult.file_validation_failed=True."""
    seg = _write_valid_hnsw_dir(tmp_path)
    (tmp_path / "chroma.sqlite3").write_bytes(b"\x00" * 4096)
    (seg / "data_level0.bin").write_bytes(b"\x00" * 16)

    result = check_episodic_health(tmp_path, timeout_s=30.0)
    assert not result.ok
    assert result.file_validation_failed is True
    assert "hnsw-validation" in (result.error or "")
