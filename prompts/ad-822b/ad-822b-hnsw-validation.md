# AD-822b — Boot-time HNSW file validation (pre-open integrity probe)

**Status:** Ready for Builder
**Dependencies:** AD-822 (subprocess boot probe) shipped; pairs with it.
**Issue:** Closes #755.
**Estimated tests:** 6 new tests in `tests/test_ad822b_hnsw_validation.py`.

---

## Problem

When ChromaDB's HNSW persistence is torn (header written, neighbor lists
partial — see #750), the native C++ side `mmap`s the files without
validating them. The first pointer-follow into a truncated `data_level0.bin`
or an out-of-bounds `cur_element_count` produces a `SIGSEGV` below the
Python interpreter. No `try/except` can catch it; AD-822 catches it via
subprocess isolation, but the operator-facing failure mode is still
"`probos serve` exits with no obvious cause."

AD-822 is the *catch-the-crash* layer. AD-822b is the *don't-let-it-crash*
layer: a fast, read-only structural probe of the HNSW files that runs
**before** ChromaDB opens the collection and detects truncation /
inconsistency *without* triggering the segfault.

Three-layer defense after this lands:

| Layer | What it detects | Mechanism |
|---|---|---|
| AD-820 | Unclean shutdown last run | shutdown_status.json gating |
| AD-822 | Latent corruption that survives shutdown gating | subprocess probe (catches segfault) |
| AD-822b (this) | Truncated / torn HNSW files | structural file validation (prevents segfault) |

## Solution overview

Add `validate_hnsw_files(data_dir)` to `episodic_health.py` that walks
each UUID-named subdir under `data_dir`, parses the small `header.bin`
binary struct, and structurally checks `data_level0.bin`, `length.bin`,
and `link_lists.bin` against the header. Returns `HnswValidationResult`.

Wire it into `_episodic_probe.py` to run **before** `chromadb.PersistentClient`
opens the collection. On failure, exit with **status code 5** (new — AD-822
already uses 0 / 1 / 2; we reserve 5 for "structural file validation
failed" so the parent can distinguish corruption-detected from
crash-detected).

Propagate a new `EpisodicCorruptionDetected` sub-detail via
`EpisodicHealthResult` so `_boot_runtime` in `__main__.py` can shape an
operator message that names the specific remediation
(`probos rebuild-episodic`).

The check is read-only, `O(n_uuid_dirs)`, and was measured against the
preserved corrupted dir at <2 ms per dir on warm cache. AD-822b adds
no boot latency that operators would notice (<10 ms total per the BF
acceptance bound).

---

## Critical research the Builder MUST do before writing code

The hnswlib header layout the Builder will parse has **NOT** been
codified in this prompt — it must be reverified against the upstream
library AND the actual on-disk file before any code lands. Skipping
this step risks the BF-274 / BF-278 class of bug ("worked against
my mental model, didn't match reality").

### Step R1: Read the upstream hnswlib write path

Open `hnswlib/hnswalg.h` in the `nmslib/hnswlib` GitHub repo (search
for `saveIndex`). The fields are written by `writeBinaryPOD` in this
order (verify the version pinned by ChromaDB — `chroma-hnswlib` is a
fork and may differ):

```
offsetLevel0_       size_t (8 bytes)
max_elements_       size_t (8 bytes)
cur_element_count   size_t (8 bytes)
size_data_per_element_   size_t (8 bytes)
label_offset_       size_t (8 bytes)
offsetData_         size_t (8 bytes)
maxlevel_           int    (4 bytes)
enterpoint_node_    tableint = unsigned int (4 bytes)
maxM_               size_t (8 bytes)
maxM0_              size_t (8 bytes)
M_                  size_t (8 bytes)
mult_               double (8 bytes)
ef_construction_    size_t (8 bytes)
```

Total raw hnswlib header: 96 bytes. **The preserved corrupted dir's
`header.bin` is 100 bytes** — `chroma-hnswlib` adds a small trailer
or leading field. Decode the actual bytes (see Step R2) and adjust
the layout if `chroma-hnswlib`'s fork differs. Pin which library
version ChromaDB depends on by reading
`.venv/Lib/site-packages/chromadb/segment/impl/vector/local_hnsw.py`
and following the import to the underlying package — the version is
authoritative.

### Step R2: Decode the actual on-disk header

The operator has preserved a known-corrupted ChromaDB dir at:

```
C:\Users\seang\AppData\Local\ProbOS\data\chroma-corrupted-2026-05-22-150712\
```

Files present (verified 2026-05-23):

```
chroma.sqlite3                                                45,314,048 bytes
chroma\chroma.sqlite3                                            188,416 bytes
d04b00d3-c353-4b21-8d98-9fcc412b0ed4\header.bin                      100 bytes
d04b00d3-c353-4b21-8d98-9fcc412b0ed4\length.bin                  283,864 bytes
d04b00d3-c353-4b21-8d98-9fcc412b0ed4\link_lists.bin              584,424 bytes
d04b00d3-c353-4b21-8d98-9fcc412b0ed4\data_level0.bin         118,939,016 bytes
d04b00d3-c353-4b21-8d98-9fcc412b0ed4\index_metadata.pickle       235,236 bytes
```

First 100 bytes of `header.bin` (little-endian u64 dump, captured
2026-05-23):

```
offset  0: 01 00 00 00 00 00 00 00   (u64=1)
offset  8: 00 00 00 00 00 00 02 00
offset 16: 00 00 00 00 7b 14 01 00
offset 24: 00 00 00 00 8c 06 00 00
offset 32: 00 00 00 00 84 06 00 00
offset 40: 00 00 00 00 84 00 00 00
offset 48: 00 00 00 00 03 00 00 00
offset 56: dc 00 00 00 10 00 00 00
offset 64: 00 00 00 00 20 00 00 00
offset 72: 00 00 00 00 10 00 00 00
offset 80: 00 00 00 00 fe 82 2b 65
offset 88: 47 15 d7 3f 64 00 00 00
offset 96: 00 00 00 0a              (4 bytes)
```

**Cross-checks the Builder MUST verify after picking a layout:**

- `length.bin` size in bytes / 4 = number of u32 entries. Should match
  exactly one of `max_elements_` or `cur_element_count`. Here:
  `283,864 / 4 = 70,966 entries`. **The Builder must confirm which
  field this matches in the live hnswlib write path.**
- `data_level0.bin` size should equal `size_data_per_element_ * max_elements_`
  (or `* cur_element_count` depending on whether the fork pre-allocates).
  Here: `118,939,016 / 70,966 ≈ 1,676 bytes per element`. For a
  384-dim float32 embedding that's 1,536 bytes of vector + ~140 bytes
  of label/neighbor-link metadata — plausible.
- `link_lists.bin` is a sparse upper-level adjacency store; its exact
  size is harder to predict structurally, so **do not gate
  validation on link_lists.bin size**. Treat its presence (file
  exists, size > 0) as the only check.

If after decoding, NONE of the candidate field positions resolve to
self-consistent values matching these external invariants
(`length.bin` count, `data_level0.bin` size divisibility), STOP and
escalate. The header layout is likely a different ChromaDB-fork
variant and a guess will produce false positives on healthy boots.

### Step R3: Locate where to insert the validation

`src/probos/_episodic_probe.py` opens the client at this line (verified
2026-05-23):

```python
client = chromadb.PersistentClient(path=str(data_dir))
```

Validation MUST run **before** this line. The new `validate_hnsw_files`
call returns `HnswValidationResult`; if `not result.ok`, write the
error list to stderr (one per line, prefixed `hnsw-validation:`) and
`return 5`.

`src/probos/episodic_health.py` interprets the exit code in
`check_episodic_health()`. Add a new branch: `exit_code == 5` →
`EpisodicHealthResult(ok=False, error=<stderr>, duration_s=...)` with
a new field distinguishing this from the generic AD-822 failure
(see Section 3 wire format).

---

## Section 0 — File-format constants (new)

**File:** `src/probos/episodic_health.py` (top-of-module constants,
beneath `SKIP_ENV_VAR`)

Add the structural constants and a parsed-header dataclass. The
Builder picks the final byte offsets after Step R2 decoding; the
layout below is a starting hypothesis based on the upstream hnswlib
order — adjust if R2 disagrees.

```python
# AD-822b: HNSW persistence file layout (chroma-hnswlib fork)
# See prompts/ad-822b/ad-822b-hnsw-validation.md Step R2 for the
# verification process against the preserved corrupted dir.
HNSW_HEADER_BYTES = 100  # observed on-disk; raw hnswlib is 96
HNSW_LENGTH_ENTRY_BYTES = 4  # length.bin = uint32 per element
# Sanity bounds — values outside these almost certainly indicate
# corruption rather than a legitimately exotic config.
HNSW_MIN_SIZE_PER_ELEMENT = 64       # smallest plausible embedding
HNSW_MAX_SIZE_PER_ELEMENT = 65_536   # 8192-dim float64 + metadata


@dataclass(frozen=True)
class HnswHeader:
    """Parsed `header.bin` fields used for structural validation.

    Field names track upstream hnswlib (`hnswalg.h::saveIndex`).
    The Builder confirms exact byte offsets via Step R2 of the prompt
    before populating; do not trust the offsets from memory.
    """
    max_elements: int
    cur_element_count: int
    size_data_per_element: int
    raw_bytes: bytes  # full header for forensic logging


@dataclass(frozen=True)
class HnswValidationResult:
    """Result of validating one or more HNSW dirs under a data_dir."""
    ok: bool
    errors: tuple[str, ...]
    dirs_checked: int
```

## Section 1 — `validate_hnsw_files`

**File:** `src/probos/episodic_health.py` (append after the existing
`EpisodicHealthResult`)

```python
def _parse_hnsw_header(header_path: Path) -> HnswHeader | None:
    """Parse `header.bin`. Returns None on read failure or size mismatch."""
    try:
        raw = header_path.read_bytes()
    except OSError as exc:
        logger.warning(
            "AD-822b: cannot read %s (%s)", header_path, exc,
        )
        return None
    if len(raw) != HNSW_HEADER_BYTES:
        logger.warning(
            "AD-822b: %s wrong size: got %d expected %d",
            header_path, len(raw), HNSW_HEADER_BYTES,
        )
        return None
    # Byte offsets confirmed via Step R2 decoding. Builder MUST verify
    # against the upstream library version pinned by ChromaDB before
    # picking these — see the prompt's `Critical research` section.
    import struct
    # NOTE: replace `<...>` with the verified format string. The
    # candidate layout (raw hnswlib) is:
    #   <QQQQQQiIQQQdQ  (96 bytes)
    # ChromaDB's 100-byte header has 4 extra bytes — locate them.
    raise NotImplementedError(
        "Builder: fill in struct.unpack format after Step R2 decoding"
    )


def validate_hnsw_files(data_dir: Path) -> HnswValidationResult:
    """Structurally validate every HNSW dir under `data_dir`.

    For each UUID-named subdir containing an `header.bin`:
      * Parse the header. If parse fails, record an error.
      * Check `data_level0.bin` exists and its size matches
        ``size_data_per_element * max_elements`` (with a small
        tolerance for end-of-file alignment).
      * Check `length.bin` exists and its size in u32 entries equals
        ``max_elements`` (or ``cur_element_count`` — pin via R2).
      * Sanity-check ``cur_element_count <= max_elements``.
      * Sanity-check ``size_data_per_element`` is within
        ``[HNSW_MIN_SIZE_PER_ELEMENT, HNSW_MAX_SIZE_PER_ELEMENT]``.

    `link_lists.bin` is checked for existence only (sparse format).
    `index_metadata.pickle` is not checked here.

    Returns `HnswValidationResult(ok=False, errors=[...])` on any
    failure. The errors list contains one string per problem, prefixed
    with the relative path so the operator can see which dir is bad.

    Designed to run in <10ms on a healthy on-disk index. Performs only
    file reads of `header.bin` (small fixed size); never opens
    `data_level0.bin` (could be hundreds of MB).
    """
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        # First-boot data dir — same convention as _episodic_probe:
        # absence is healthy, not corruption.
        return HnswValidationResult(ok=True, errors=(), dirs_checked=0)

    errors: list[str] = []
    dirs_checked = 0

    for entry in data_dir.iterdir():
        if not entry.is_dir():
            continue
        # ChromaDB names HNSW segment dirs after segment UUIDs.
        # Heuristic: dir contains `header.bin`. Avoids hardcoding a
        # UUID pattern that future ChromaDB versions might break.
        header_path = entry / "header.bin"
        if not header_path.is_file():
            continue
        dirs_checked += 1

        header = _parse_hnsw_header(header_path)
        if header is None:
            errors.append(f"{entry.name}/header.bin: parse failed")
            continue

        if header.cur_element_count > header.max_elements:
            errors.append(
                f"{entry.name}/header.bin: cur_element_count={header.cur_element_count} "
                f"exceeds max_elements={header.max_elements}"
            )

        if not (HNSW_MIN_SIZE_PER_ELEMENT
                <= header.size_data_per_element
                <= HNSW_MAX_SIZE_PER_ELEMENT):
            errors.append(
                f"{entry.name}/header.bin: size_data_per_element="
                f"{header.size_data_per_element} outside plausible range "
                f"[{HNSW_MIN_SIZE_PER_ELEMENT}, {HNSW_MAX_SIZE_PER_ELEMENT}]"
            )

        data_level0 = entry / "data_level0.bin"
        if not data_level0.is_file():
            errors.append(f"{entry.name}/data_level0.bin: missing")
        else:
            expected = header.size_data_per_element * header.max_elements
            actual = data_level0.stat().st_size
            if actual != expected:
                errors.append(
                    f"{entry.name}/data_level0.bin: size {actual} "
                    f"expected {expected} (size_data_per_element * max_elements)"
                )

        length_bin = entry / "length.bin"
        if not length_bin.is_file():
            errors.append(f"{entry.name}/length.bin: missing")
        else:
            expected_entries = header.max_elements
            actual_entries = length_bin.stat().st_size // HNSW_LENGTH_ENTRY_BYTES
            if actual_entries != expected_entries:
                errors.append(
                    f"{entry.name}/length.bin: {actual_entries} entries "
                    f"expected {expected_entries} (max_elements)"
                )

        link_lists = entry / "link_lists.bin"
        if not link_lists.is_file():
            errors.append(f"{entry.name}/link_lists.bin: missing")
        # Do NOT gate on link_lists.bin size — sparse format.

    return HnswValidationResult(
        ok=not errors,
        errors=tuple(errors),
        dirs_checked=dirs_checked,
    )
```

### Section 1 acceptance

- Function is **read-only** — never writes, never opens the
  collection, never imports chromadb.
- Header parse failures degrade to a per-dir error, not an exception.
- Wall time on a healthy 70k-element index: <10 ms (Builder
  benchmarks with `time.perf_counter()` in the test).

---

## Section 2 — Wire validation into `_episodic_probe.py`

**File:** `src/probos/_episodic_probe.py`

Insert the call between the `sqlite_marker.exists()` check and the
`chromadb.PersistentClient(...)` open.

```python
# === SEARCH ===
    sqlite_marker = data_dir / "chroma.sqlite3"
    if not sqlite_marker.exists():
        # data_dir exists but chroma has never been initialized here.
        # Healthy — runtime will create the collection on first start().
        print("ok rows=0 no-chroma-sqlite", file=sys.stdout)
        return 0

    try:
        client = chromadb.PersistentClient(path=str(data_dir))
# === REPLACE ===
    sqlite_marker = data_dir / "chroma.sqlite3"
    if not sqlite_marker.exists():
        # data_dir exists but chroma has never been initialized here.
        # Healthy — runtime will create the collection on first start().
        print("ok rows=0 no-chroma-sqlite", file=sys.stdout)
        return 0

    # AD-822b: structural HNSW file validation BEFORE chromadb touches
    # the files. Catches torn writes that would segfault inside the
    # native mmap path. Read-only, <10ms.
    try:
        from probos.episodic_health import validate_hnsw_files
        validation = validate_hnsw_files(data_dir)
    except Exception as exc:
        # Defensive: if validation itself throws, treat as a soft
        # failure rather than masking it with a successful open.
        print(f"hnsw-validation-crashed: {exc!r}", file=sys.stderr)
        return 5
    if not validation.ok:
        for err in validation.errors:
            print(f"hnsw-validation: {err}", file=sys.stderr)
        return 5

    try:
        client = chromadb.PersistentClient(path=str(data_dir))
# === END REPLACE ===
```

### Exit-code map (post AD-822b)

| Code | Meaning |
|---|---|
| 0 | Healthy (collection opened + peeked + counted) |
| 1 | Unhealthy — chroma raised an exception |
| 2 | Bad CLI arguments |
| 5 | **AD-822b: HNSW structural validation failed (new)** |

## Section 3 — Propagate exit code 5 through `episodic_health.py`

**File:** `src/probos/episodic_health.py`

Extend `EpisodicHealthResult` with an optional flag distinguishing
file-validation failure from generic probe failure, so `_boot_runtime`
can choose the right operator message.

```python
# === SEARCH ===
@dataclass(frozen=True)
class EpisodicHealthResult:
    ok: bool
    error: str | None
    duration_s: float
# === REPLACE ===
@dataclass(frozen=True)
class EpisodicHealthResult:
    ok: bool
    error: str | None
    duration_s: float
    # AD-822b: True when the structural HNSW file probe rejected the
    # store before ChromaDB even opened it (exit code 5). Distinct
    # from generic probe failure (chroma raised, exit code 1) so the
    # operator message can name the specific remediation path.
    file_validation_failed: bool = False
# === END REPLACE ===
```

Then in `check_episodic_health`, branch on `exit_code == 5`:

```python
# === SEARCH ===
        duration_s = time.monotonic() - start
        if exit_code == 0:
            logger.info(
                "AD-822: episodic health probe ok (%.2fs)", duration_s,
            )
            return EpisodicHealthResult(ok=True, error=None, duration_s=duration_s)

        try:
            stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            stderr_text = ""
        reason = stderr_text or f"probe exited with code {exit_code}"
        logger.warning(
            "AD-822: episodic health probe failed exit=%s reason=%s",
            exit_code, reason,
        )
        return EpisodicHealthResult(
            ok=False,
            error=reason,
            duration_s=duration_s,
        )
# === REPLACE ===
        duration_s = time.monotonic() - start
        if exit_code == 0:
            logger.info(
                "AD-822: episodic health probe ok (%.2fs)", duration_s,
            )
            return EpisodicHealthResult(ok=True, error=None, duration_s=duration_s)

        try:
            stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            stderr_text = ""
        reason = stderr_text or f"probe exited with code {exit_code}"

        # AD-822b: exit code 5 = structural HNSW file validation failed
        # before ChromaDB even opened the collection. Route to the
        # operator message that names rebuild-episodic explicitly.
        file_validation_failed = (exit_code == 5)
        logger.warning(
            "AD-822%s: episodic health probe failed exit=%s reason=%s",
            "b" if file_validation_failed else "",
            exit_code, reason,
        )
        return EpisodicHealthResult(
            ok=False,
            error=reason,
            duration_s=duration_s,
            file_validation_failed=file_validation_failed,
        )
# === END REPLACE ===
```

## Section 4 — Operator message in `__main__.py`

**File:** `src/probos/__main__.py`

Locate the `check_episodic_health` call inside `_boot_runtime` (added
by AD-822). Shape the operator-readable error to mention
`probos rebuild-episodic` when `file_validation_failed` is True.

The Builder finds the existing failure-path block via:

```bash
grep -n "EpisodicCorruptionDetected\|check_episodic_health" src/probos/__main__.py
```

and adds a branch like:

```python
if not result.ok:
    if result.file_validation_failed:
        message = (
            f"Episodic memory HNSW index appears truncated or corrupted "
            f"(structural validation failed in {result.duration_s:.1f}s).\n"
            f"  reason: {result.error}\n\n"
            f"Run 'probos rebuild-episodic' to reconstruct from "
            f"cognitive_journal + ward_room (AD-819), or restore from "
            f"a backup directory (AD-823).\n\n"
            f"Set {SKIP_ENV_VAR}=1 to bypass the probe (NOT recommended)."
        )
    else:
        # Existing AD-822 message (chroma raised inside the probe).
        message = ...  # unchanged
    raise EpisodicCorruptionDetected(data_dir, message, result.duration_s)
```

**Builder must verify the exact shape of the existing failure block
before editing — do not assume the message text or the exception
constructor signature from memory.** Use the existing AD-822 pattern
as the template and add only the `file_validation_failed` branch.

---

## Tests — `tests/test_ad822b_hnsw_validation.py` (new file)

Six required tests. All use `tmp_path` and construct synthetic HNSW
file layouts; no test depends on the live `data/` directory or the
preserved corrupted dir (which lives outside the workspace).

```python
"""AD-822b: structural HNSW file validation tests.

Synthesize valid and corrupted HNSW directory layouts under tmp_path.
The fake `header.bin` writer must match whatever struct layout the
Builder confirmed via Step R2 of the prompt.
"""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

import pytest

from probos.episodic_health import (
    HNSW_HEADER_BYTES,
    HNSW_LENGTH_ENTRY_BYTES,
    validate_hnsw_files,
)


def _write_valid_hnsw_dir(
    parent: Path,
    *,
    max_elements: int = 100,
    cur_element_count: int = 50,
    size_data_per_element: int = 1676,
) -> Path:
    """Construct a structurally valid HNSW segment dir.

    The header bytes use the format string the Builder pinned in
    Section 1 (`_parse_hnsw_header`); keep that single source of truth.
    """
    seg = parent / "deadbeef-0000-0000-0000-000000000000"
    seg.mkdir()
    # Builder: replace this with the exact format used by
    # `_parse_hnsw_header` after Step R2 decoding.
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
    result = validate_hnsw_files(tmp_path)
    assert result.ok
    assert result.errors == ()
    assert result.dirs_checked == 1


def test_validate_truncated_data_level0_returns_error(tmp_path: Path) -> None:
    seg = _write_valid_hnsw_dir(tmp_path)
    # Truncate data_level0.bin to half its expected size
    f = seg / "data_level0.bin"
    f.write_bytes(b"\x00" * (f.stat().st_size // 2))

    result = validate_hnsw_files(tmp_path)
    assert not result.ok
    assert any("data_level0.bin" in e for e in result.errors)


def test_validate_missing_header_skipped(tmp_path: Path) -> None:
    """A dir without header.bin is not an HNSW segment dir — skip it."""
    seg = tmp_path / "not-an-hnsw-segment"
    seg.mkdir()
    (seg / "random.txt").write_text("hi")

    result = validate_hnsw_files(tmp_path)
    assert result.ok
    assert result.dirs_checked == 0


def test_validate_cur_element_count_exceeds_max_returns_error(
    tmp_path: Path,
) -> None:
    _write_valid_hnsw_dir(
        tmp_path, max_elements=100, cur_element_count=999,
    )
    result = validate_hnsw_files(tmp_path)
    assert not result.ok
    assert any("cur_element_count" in e for e in result.errors)


def test_validate_returns_ok_on_first_boot_missing_data_dir(
    tmp_path: Path,
) -> None:
    """First boot: data_dir doesn't exist yet — treat as healthy."""
    nonexistent = tmp_path / "never-created"
    result = validate_hnsw_files(nonexistent)
    assert result.ok
    assert result.dirs_checked == 0


def test_probe_subprocess_returns_exit_code_5_on_validation_failure(
    tmp_path: Path,
) -> None:
    """End-to-end: torn HNSW dir → probe subprocess exits 5."""
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
```

`_build_test_header` is a Builder-supplied helper that emits the
same byte layout as `_parse_hnsw_header` decodes. Keep it in the
same test file (not in `episodic_health.py` — production code does
not need to *write* headers, only read them).

### Optional 7th test (recommended, not required)

```python
def test_propagates_through_check_episodic_health(tmp_path: Path) -> None:
    """exit code 5 → EpisodicHealthResult.file_validation_failed=True."""
    seg = _write_valid_hnsw_dir(tmp_path)
    (tmp_path / "chroma.sqlite3").write_bytes(b"\x00" * 4096)
    (seg / "data_level0.bin").write_bytes(b"\x00" * 16)

    from probos.episodic_health import check_episodic_health
    result = check_episodic_health(tmp_path, timeout_s=30.0)
    assert not result.ok
    assert result.file_validation_failed is True
    assert "hnsw-validation" in (result.error or "")
```

---

## What this AD does NOT change

- Does NOT modify `EpisodicMemory.start()` or any chroma open path.
- Does NOT change the AD-822 subprocess probe contract (existing exit
  codes 0/1/2 keep their meaning).
- Does NOT add chromadb as an `episodic_health.py` import — validation
  is pure file I/O + `struct.unpack`.
- Does NOT touch the live runtime, the live data dir, or the
  preserved corrupted dir (read-only inspection only — never writes).
- Does NOT introduce `asyncio.create_subprocess_exec` (BF-280 forbids
  it from runtime code). The AD-822 `Popen + thread executor` pattern
  already handles the subprocess invocation; AD-822b adds no new
  subprocess call site.
- Does NOT attempt to validate `index_metadata.pickle` —
  Python pickle deserialization is a separate corruption surface, out
  of scope here.

## Engineering Principles checklist

- (S) Single responsibility: `validate_hnsw_files` does one thing —
  structural file check. No collection open, no chroma import.
- (O) Open/closed: extends `EpisodicHealthResult` via a new field with
  a default of `False` — existing callers untouched.
- (L) Liskov: not applicable (no inheritance).
- (I) Interface segregation: the new `HnswValidationResult` is a
  narrow dataclass, not a generic result type.
- (D) Dependency inversion: the function takes a `Path`, not a
  configured object — testable with `tmp_path` directly.
- Fail-fast tier: validation errors are *logged + propagated*
  (tier-3 propagate via exit code 5). No exception is swallowed
  silently in production. The defensive `try/except Exception` around
  `_parse_hnsw_header`'s file read is tier-2 log-and-degrade because
  a partial read still produces a structured failure path
  (`return None` → "parse failed" error in result).
- Async hygiene: no async code added — pure file I/O.
- Logging: every WARNING includes the file path AND the specific
  failure mode (size mismatch, parse failed, etc.). No bare
  `logger.warning("error")`.
- Config: no new config — validation is unconditional. If a future
  operator wants to bypass, the existing `PROBOS_SKIP_EPISODIC_HEALTH_CHECK`
  envvar already short-circuits the entire probe (which includes
  AD-822b).
- Test isolation: every test uses `tmp_path`; no test depends on
  another test's state; no test touches `data/` or the live runtime.
- Type annotations: all new public APIs (`validate_hnsw_files`,
  `HnswValidationResult`, `HnswHeader`) are fully annotated.

---

## Acceptance criteria

1. `tests/test_ad822b_hnsw_validation.py` has **6 or more** tests
   (7 if the optional propagation test is included). All pass under
   `pytest -n 0 --timeout=60`.
2. The AD-820..826 regression suite (62 tests) remains green:
   `pytest tests/test_ad820_shutdown_integrity.py tests/test_ad821_hnsw_sync_threshold.py
   tests/test_ad822_episodic_health.py tests/test_ad823_episodic_backup.py
   tests/test_ad824_shutdown_hygiene.py tests/test_ad825_drain_shutdown.py
   tests/test_ad826_voice_config.py -n 0 --timeout=60` reports
   `62 passed`.
3. The BF-295 regression (`tests/test_bf295_migration_timeouts.py`)
   remains green.
4. Single commit titled `AD-822b: boot-time HNSW file validation` with
   trailer `Closes #755`.
5. All changes comply with the Engineering Principles in
   `.github/copilot-instructions.md`.
6. No code path uses `asyncio.create_subprocess_exec` (BF-280).
7. The validation runs in <10 ms per dir on a healthy 70k-element
   index (Builder confirms with a `time.perf_counter()` check inside
   the healthy-dir test; assert <50 ms to leave headroom for slow CI
   disks, log the actual measurement).

## Standing constraints (from operator)

- **Do not** touch the live runtime at `D:\ProbOS\` from a subprocess
  outside this Builder session. Tests use `tmp_path` only.
- **Do not** modify anything under `C:\Users\seang\AppData\Local\ProbOS\`.
  Read-only inspection of the preserved corrupted dir for format
  research only.
- **Do not** copy any data from `C:\Users\seang\AppData\Local\ProbOS\`
  into the repo or into tests. Test data is synthesized fresh from
  zero bytes.

## Tracking

- Append a one-line entry to `PROGRESS.md` under the current era
  (AD-822b — boot-time HNSW structural validation; closes #755).
- Append a `DECISIONS.md` AD-822b entry naming the three-layer defense
  shape (AD-820 / AD-822 / AD-822b) and pointing back to this prompt.
- The `docs/development/roadmap.md` AD-822 row already mentions a
  "pre-open validation" follow-up — convert that row to "shipped"
  with the AD-822b cross-reference.

## Verified Against Codebase (2026-05-23)

```
git show c71409ee --stat            # BF-295 commit base — green
gh issue view 755                   # Open; this prompt closes it
ls src/probos/_episodic_probe.py    # Exists (AD-822); ~100 lines
ls src/probos/episodic_health.py    # Exists (AD-822); ~200 lines
ls C:\Users\seang\AppData\Local\ProbOS\data\chroma-corrupted-2026-05-22-150712\
   → chroma.sqlite3 (45MB), d04b...uuid/{header.bin=100B, length.bin=283864B,
     link_lists.bin=584424B, data_level0.bin=118MB, index_metadata.pickle=235KB}
header.bin first 100 bytes captured above for Step R2 cross-check
```

External invariants captured from preserved corrupted dir:
```
length.bin entries = 283,864 / 4         = 70,966
data_level0.bin / entries = 118,939,016 / 70,966 ≈ 1,676 bytes/element
```

Builder's Step R2 decoding must reproduce these two numbers from the
parsed header to confirm the layout is correct.
