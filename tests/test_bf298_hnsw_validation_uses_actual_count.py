"""BF-298: HNSW validation must use cur_element_count (length.bin) not max_elements.

The original AD-822b validated data_level0.bin / length.bin against
header.max_elements (allocation capacity). That false-positive flagged any
healthy non-full HNSW directory because hnswlib only writes up to the
actual element count, not the full preallocation.

The right check is internal consistency:
- length.bin entries == header.cur_element_count
- data_level0.bin size == size_data_per_element * length_bin_entries
- length_bin_entries <= max_elements (sanity)
"""
from __future__ import annotations

import struct
from pathlib import Path

from probos.episodic_health import (
    HNSW_HEADER_BYTES,
    HNSW_HEADER_STRUCT_FMT,
    HNSW_LENGTH_ENTRY_BYTES,
    validate_hnsw_files,
)


def _build_header(
    *, max_elements: int, cur_element_count: int, size_data_per_element: int
) -> bytes:
    return struct.pack(
        HNSW_HEADER_STRUCT_FMT,
        1,                    # version
        0,                    # offsetLevel0_
        max_elements,         # max_elements_
        cur_element_count,    # cur_element_count
        size_data_per_element,
        1668,                 # label_offset
        132,                  # offsetData
        3,                    # maxlevel
        0,                    # enterpoint_node
        16,                   # maxM
        32,                   # maxM0
        16,                   # M
        0.36067,              # mult
        100,                  # ef_construction
    )


def _write_hnsw(
    parent: Path,
    *,
    max_elements: int,
    cur_element_count: int,
    length_bin_entries: int | None = None,
    data_level0_elements: int | None = None,
    size_data_per_element: int = 1676,
) -> Path:
    """Synthesize an HNSW segment dir with operator-controlled mismatches."""
    if length_bin_entries is None:
        length_bin_entries = cur_element_count
    if data_level0_elements is None:
        data_level0_elements = length_bin_entries

    seg = parent / "deadbeef-0000-0000-0000-000000000000"
    seg.mkdir()
    seg.joinpath("header.bin").write_bytes(
        _build_header(
            max_elements=max_elements,
            cur_element_count=cur_element_count,
            size_data_per_element=size_data_per_element,
        )
    )
    seg.joinpath("data_level0.bin").write_bytes(
        b"\x00" * (size_data_per_element * data_level0_elements)
    )
    seg.joinpath("length.bin").write_bytes(
        b"\x00" * (length_bin_entries * HNSW_LENGTH_ENTRY_BYTES)
    )
    seg.joinpath("link_lists.bin").write_bytes(b"\x00" * 64)
    return seg


def test_healthy_non_full_hnsw_passes(tmp_path: Path) -> None:
    """BF-298: a healthy HNSW with headroom (cur < max) must PASS validation.

    Pre-fix AD-822b false-positive flagged this case because it expected
    file sizes equal to max_elements * size_data_per_element.
    """
    _write_hnsw(
        tmp_path,
        max_elements=32768,
        cur_element_count=24730,  # matches operator's real 2026-05-23 rebuild
    )
    result = validate_hnsw_files(tmp_path)
    assert result.ok, f"healthy non-full HNSW must pass; errors={result.errors}"


def test_torn_write_data_short_of_length_bin_fails(tmp_path: Path) -> None:
    """BF-298: data_level0.bin shorter than length.bin entries indicates
    a partial flush. Catch it.
    """
    _write_hnsw(
        tmp_path,
        max_elements=100,
        cur_element_count=50,
        length_bin_entries=50,
        data_level0_elements=30,  # truncated relative to length.bin
    )
    result = validate_hnsw_files(tmp_path)
    assert not result.ok
    assert any("data_level0.bin" in e for e in result.errors)


def test_torn_write_header_lags_length_bin_fails(tmp_path: Path) -> None:
    """BF-298: header.cur_element_count not yet bumped to match length.bin
    indicates a torn write. This is the signature from the operator's
    2026-05-22 corruption (header=70779, length.bin=70966).
    """
    _write_hnsw(
        tmp_path,
        max_elements=131072,
        cur_element_count=70779,  # header lagging
        length_bin_entries=70966,  # length.bin advanced
    )
    result = validate_hnsw_files(tmp_path)
    assert not result.ok
    assert any("torn write signature" in e for e in result.errors)


def test_length_bin_overruns_max_elements_fails(tmp_path: Path) -> None:
    """BF-298: sanity check — length.bin should never exceed max_elements."""
    _write_hnsw(
        tmp_path,
        max_elements=100,
        cur_element_count=200,  # header matches length.bin so the only error is overrun
        length_bin_entries=200,
    )
    result = validate_hnsw_files(tmp_path)
    assert not result.ok
    assert any("allocation overrun" in e for e in result.errors)


def test_fresh_unsynced_index_cur_zero_passes(tmp_path: Path) -> None:
    """BF-600: a freshly-built / small ChromaDB >= 1.5.x store writes
    length.bin at the allocation capacity (== max_elements, default 100)
    but leaves header.cur_element_count at the init value 0 until a real
    sync/compaction flushes it. Rows are safe in the WAL and the index
    rebuilds on open, so this is NOT a torn write and must PASS the
    structural pre-check (which otherwise hard-blocks boot/backup).
    """
    _write_hnsw(
        tmp_path,
        max_elements=100,
        cur_element_count=0,        # header never synced
        length_bin_entries=100,     # length.bin at allocation capacity
        data_level0_elements=100,   # data_level0 sized to allocation, internally consistent
    )
    result = validate_hnsw_files(tmp_path)
    assert result.ok, f"fresh un-synced index must pass; errors={result.errors}"


def test_torn_write_nonzero_cur_still_flagged_after_bf600(tmp_path: Path) -> None:
    """BF-600: the cur==0 exemption must NOT mask a genuine torn write,
    which always has a NON-ZERO cur_element_count disagreeing with
    length.bin (the 2026-05-22 corruption signature).
    """
    _write_hnsw(
        tmp_path,
        max_elements=131072,
        cur_element_count=70779,
        length_bin_entries=70966,
    )
    result = validate_hnsw_files(tmp_path)
    assert not result.ok
    assert any("torn write signature" in e for e in result.errors)

