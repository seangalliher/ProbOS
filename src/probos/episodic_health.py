"""AD-822: subprocess-isolated ChromaDB boot-time health probe.

Companion to AD-820's :mod:`probos.shutdown_integrity`. Where AD-820 detects
*unclean shutdown* on the previous run, this module detects *corruption
present right now* — the class of failure that segfaults the runtime when
it first touches chroma (#750 root cause).

The probe spawns ``python -m probos._episodic_probe <data_dir>`` in a
subprocess. If the probe crashes (including native SIGSEGV), errors, or
hangs past ``timeout_s``, this module returns a non-ok result and the
caller refuses to boot.

Why a subprocess and not an in-process try/except: ChromaDB's native HNSW
code can SIGSEGV on a torn index. SIGSEGV bypasses Python's exception
machinery — a try/except cannot catch it. Running the probe in a child
process means a segfault kills the child without affecting the parent
runtime, and the parent observes the non-zero exit code as evidence.

Uses :class:`subprocess.Popen` rather than :func:`asyncio.create_subprocess_exec`
per the standing rule in ``.github/copilot-instructions.md`` —
``WindowsSelectorEventLoop`` does not support async subprocess. The
canonical reference for this pattern is
:meth:`probos.agents.shell_command.ShellCommandAgent._run_sync`.
"""

from __future__ import annotations

import logging
import os
import struct
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SKIP_ENV_VAR = "PROBOS_SKIP_EPISODIC_HEALTH_CHECK"

# AD-822b: HNSW persistence file layout (chroma-hnswlib fork).
# Layout verified 2026-05-23 against preserved corrupted dir at
# C:\\Users\\seang\\AppData\\Local\\ProbOS\\data\\chroma-corrupted-2026-05-22-150712\\
# header.bin. See prompts/ad-822b/ad-822b-hnsw-validation.md Step R2.
#
# Format: little-endian, 4-byte u32 version prefix + 13 upstream
# hnswlib fields in saveIndex order (hnswalg.h):
#   version (u32)                       offset 0
#   offsetLevel0_ (u64)                  offset 4
#   max_elements_ (u64)                  offset 12
#   cur_element_count (u64)              offset 20
#   size_data_per_element_ (u64)         offset 28
#   label_offset_ (u64)                  offset 36
#   offsetData_ (u64)                    offset 44
#   maxlevel_ (i32)                      offset 52
#   enterpoint_node_ (u32)               offset 56
#   maxM_ (u64)                          offset 60
#   maxM0_ (u64)                         offset 68
#   M_ (u64)                             offset 76
#   mult_ (double)                       offset 84
#   ef_construction_ (u64)               offset 92
# Total: 100 bytes.
HNSW_HEADER_BYTES = 100
HNSW_HEADER_STRUCT_FMT = "<IQQQQQQiIQQQdQ"
HNSW_LENGTH_ENTRY_BYTES = 4  # length.bin = uint32 per element
# Sanity bounds — values outside these almost certainly indicate
# corruption rather than a legitimately exotic config. Healthy
# 384-dim float32 + M=16 metadata = 1676 bytes/element.
HNSW_MIN_SIZE_PER_ELEMENT = 64       # smallest plausible embedding
HNSW_MAX_SIZE_PER_ELEMENT = 65_536   # 8192-dim float64 + metadata


@dataclass(frozen=True)
class HnswHeader:
    """Parsed ``header.bin`` fields used for structural validation.

    Field names track upstream hnswlib (`hnswalg.h::saveIndex`).
    Only the fields used by :func:`validate_hnsw_files` are surfaced;
    others are decoded but discarded.
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


class EpisodicCorruptionDetected(RuntimeError):
    """The episodic store failed the boot-time health probe.

    Carries the probe stderr / exit code so the caller can shape an
    operator-readable error message pointing at AD-819 recovery.
    """

    def __init__(
        self,
        data_dir: Path,
        error: str,
        duration_s: float,
        *,
        file_validation_failed: bool = False,
    ) -> None:
        self.data_dir = data_dir
        self.error = error
        self.duration_s = duration_s
        # AD-822b: when True, the failure came from the pre-open
        # structural file probe (exit code 5) rather than from chroma
        # raising during open. Operator message leads with file
        # truncation framing in that case.
        self.file_validation_failed = file_validation_failed
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        if self.file_validation_failed:
            return (
                f"Episodic memory HNSW index appears truncated or corrupted "
                f"(structural validation failed in {self.duration_s:.1f}s).\n"
                f"  reason: {self.error}\n\n"
                f"On-disk HNSW files are inconsistent (torn write or partial "
                f"flush from a prior process). Booting would segfault inside "
                f"the native mmap path.\n\n"
                f"Options:\n"
                f"  (a) Run 'probos rebuild-episodic' to reconstruct ChromaDB "
                f"from cognitive_journal + ward_room (AD-819).\n"
                f"  (b) Restore the data dir from a backup (AD-823).\n"
                f"  (c) Set {SKIP_ENV_VAR}=1 to bypass the probe (NOT recommended "
                f"— the runtime will likely crash on first episodic access).\n\n"
                f"Data dir: {self.data_dir}"
            )
        return (
            f"Episodic memory health probe failed after {self.duration_s:.1f}s.\n"
            f"  reason: {self.error}\n\n"
            f"The on-disk ChromaDB index appears corrupted. Booting the "
            f"runtime would likely segfault inside the native HNSW code.\n\n"
            f"Options:\n"
            f"  (a) Run 'probos rebuild-episodic' to reconstruct ChromaDB "
            f"from the surviving ward room (AD-819).\n"
            f"  (b) Restore the data dir from a backup (AD-823).\n"
            f"  (c) Set {SKIP_ENV_VAR}=1 to bypass the probe (NOT recommended "
            f"— the runtime will likely crash on first episodic access).\n\n"
            f"Data dir: {self.data_dir}"
        )


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


def _parse_hnsw_header(header_path: Path) -> HnswHeader | None:
    """Parse ``header.bin``. Return None on read failure or size mismatch.

    The struct format is :data:`HNSW_HEADER_STRUCT_FMT`. Returns None
    (not raises) so callers can accumulate per-dir errors without an
    early abort that would mask other torn dirs.
    """
    try:
        raw = header_path.read_bytes()
    except OSError as exc:
        logger.warning(
            "AD-822b: cannot read %s (%s); treating as parse failure",
            header_path, exc,
        )
        return None
    if len(raw) != HNSW_HEADER_BYTES:
        logger.warning(
            "AD-822b: %s wrong size: got %d expected %d; treating as parse failure",
            header_path, len(raw), HNSW_HEADER_BYTES,
        )
        return None
    try:
        fields = struct.unpack(HNSW_HEADER_STRUCT_FMT, raw)
    except struct.error as exc:
        logger.warning(
            "AD-822b: %s struct.unpack failed (%s); treating as parse failure",
            header_path, exc,
        )
        return None
    # Field indexes per HNSW_HEADER_STRUCT_FMT comment above:
    #   [0]=version, [1]=offsetLevel0_, [2]=max_elements_,
    #   [3]=cur_element_count, [4]=size_data_per_element_, ...
    return HnswHeader(
        max_elements=fields[2],
        cur_element_count=fields[3],
        size_data_per_element=fields[4],
        raw_bytes=raw,
    )


def validate_hnsw_files(data_dir: Path) -> HnswValidationResult:
    """Structurally validate every HNSW dir under ``data_dir``.

    For each subdir containing a ``header.bin``:
      * Parse the header. If parse fails, record an error.
      * Check ``data_level0.bin`` exists and its size equals
        ``size_data_per_element * max_elements``.
      * Check ``length.bin`` exists and its size in u32 entries equals
        ``max_elements``.
      * Sanity-check ``cur_element_count <= max_elements``.
      * Sanity-check ``size_data_per_element`` is within
        ``[HNSW_MIN_SIZE_PER_ELEMENT, HNSW_MAX_SIZE_PER_ELEMENT]``.

    ``link_lists.bin`` is checked for existence only (sparse format).
    ``index_metadata.pickle`` is not checked here.

    Returns :class:`HnswValidationResult` with ``ok=False`` and a tuple
    of one error string per problem (each prefixed with the relative
    path) on any failure. First-boot data dirs (data_dir missing) and
    data dirs with no HNSW segment subdirs return ``ok=True`` —
    absence is not corruption.

    Read-only: never opens ``data_level0.bin`` (could be hundreds of
    MB); only reads the 100-byte ``header.bin``. Wall time on a
    healthy 70k-element index is <10 ms.
    """
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        # First-boot data dir — same convention as _episodic_probe:
        # absence is healthy, not corruption.
        return HnswValidationResult(ok=True, errors=(), dirs_checked=0)

    errors: list[str] = []
    dirs_checked = 0

    for entry in sorted(data_dir.iterdir()):
        if not entry.is_dir():
            continue
        # ChromaDB names HNSW segment dirs after segment UUIDs.
        # Heuristic: dir contains ``header.bin``. Avoids hardcoding a
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
                f"{entry.name}/header.bin: cur_element_count="
                f"{header.cur_element_count} exceeds max_elements="
                f"{header.max_elements}"
            )

        if not (
            HNSW_MIN_SIZE_PER_ELEMENT
            <= header.size_data_per_element
            <= HNSW_MAX_SIZE_PER_ELEMENT
        ):
            errors.append(
                f"{entry.name}/header.bin: size_data_per_element="
                f"{header.size_data_per_element} outside plausible range "
                f"[{HNSW_MIN_SIZE_PER_ELEMENT}, {HNSW_MAX_SIZE_PER_ELEMENT}]"
            )

        # BF-298: validate INTERNAL CONSISTENCY between header, length.bin,
        # and data_level0.bin rather than against header.max_elements. The
        # latter is allocated capacity; hnswlib only writes up to the actual
        # element count, so a healthy non-full index always has files smaller
        # than max_elements * size_data_per_element. AD-822b's original check
        # false-positive blocked any healthy non-full HNSW.
        #
        # A real torn write produces MISMATCH between length.bin entries and
        # header.cur_element_count, or between data_level0.bin size and what
        # length.bin reports. Those are the invariants we actually check.
        length_bin = entry / "length.bin"
        length_bin_entries: int | None = None
        if not length_bin.is_file():
            errors.append(f"{entry.name}/length.bin: missing")
        else:
            length_bin_entries = length_bin.stat().st_size // HNSW_LENGTH_ENTRY_BYTES
            # Sanity: length.bin should not exceed max_elements (allocation)
            if length_bin_entries > header.max_elements:
                errors.append(
                    f"{entry.name}/length.bin: {length_bin_entries} entries "
                    f"exceeds max_elements={header.max_elements} (allocation overrun)"
                )
            # The torn-write signature: header.cur_element_count mismatches
            # length.bin. A graceful flush writes both atomically; only a
            # partial flush leaves them disagreeing.
            #
            # BF-600: exempt cur_element_count == 0. ChromaDB >= 1.5.x writes
            # length.bin at the index allocation capacity (== max_elements,
            # default 100) and leaves header.bin at the init value
            # cur_element_count=0 until a real sync/compaction flushes it. A
            # small or freshly-built store therefore legitimately shows
            # ``cur=0`` with ``length.bin=100`` while every added row is still
            # safe in the WAL (chroma rebuilds the in-memory index on next
            # open). That is NOT a torn write — a genuine partial flush leaves
            # a NON-ZERO cur_element_count disagreeing with length.bin (e.g.
            # the BF-298 reference case header=70779 vs length=70966). Gating
            # on ``cur > 0`` removes the false positive that hard-blocked
            # boot/backup on fresh and small data dirs without weakening
            # detection of real mid-flush corruption.
            if (
                header.cur_element_count > 0
                and length_bin_entries != header.cur_element_count
            ):
                errors.append(
                    f"{entry.name}: header.cur_element_count={header.cur_element_count} "
                    f"!= length.bin entries={length_bin_entries} (torn write signature)"
                )

        data_level0 = entry / "data_level0.bin"
        if not data_level0.is_file():
            errors.append(f"{entry.name}/data_level0.bin: missing")
        elif length_bin_entries is not None:
            # data_level0.bin must hold exactly length_bin_entries * size_per_element
            # bytes — anything else indicates the data file was truncated mid-write
            # relative to the length counter.
            expected = header.size_data_per_element * length_bin_entries
            actual = data_level0.stat().st_size
            if actual != expected:
                errors.append(
                    f"{entry.name}/data_level0.bin: size {actual} "
                    f"expected {expected} (size_data_per_element * length_bin_entries)"
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


def check_episodic_health(
    data_dir: Path,
    *,
    timeout_s: float = 30.0,
) -> EpisodicHealthResult:
    """Probe chroma in a subprocess; return a result the caller can gate on.

    Args:
        data_dir: the per-instance data directory. Same value passed to
            ``EpisodicMemory(db_path=str(data_dir / 'episodic.db'))`` —
            chroma lives at ``data_dir`` root (not under an ``episodic/``
            subdir; see :func:`EpisodicMemory.start`).
        timeout_s: maximum wall time to wait for the probe. Defaults to
            30s; cold chroma open + HNSW load is normally <5s, so 30s
            leaves headroom for a slow disk.

    The :envvar:`PROBOS_SKIP_EPISODIC_HEALTH_CHECK` env var bypasses the
    probe entirely; a WARNING is logged so post-mortems can see the
    operator accepted the risk.
    """
    if os.environ.get(SKIP_ENV_VAR, "").strip() == "1":
        logger.warning(
            "AD-822: %s=1 — skipping episodic health probe (operator override)",
            SKIP_ENV_VAR,
        )
        return EpisodicHealthResult(ok=True, error=None, duration_s=0.0)

    data_dir = Path(data_dir)
    start = time.monotonic()

    # stderr -> tempfile (not stdout — BF-282 binary-stdout lesson, applied
    # defensively even though stderr is text). The tempfile is cleaned up
    # in finally so a hung child doesn't leak files.
    stderr_file = tempfile.NamedTemporaryFile(
        prefix="probos-episodic-probe-",
        suffix=".log",
        delete=False,
    )
    stderr_path = Path(stderr_file.name)
    stderr_file.close()

    proc: subprocess.Popen[bytes] | None = None
    try:
        with open(stderr_path, "wb") as stderr_sink:
            proc = subprocess.Popen(
                [sys.executable, "-m", "probos._episodic_probe", str(data_dir)],
                stdout=subprocess.DEVNULL,
                stderr=stderr_sink,
            )
            try:
                exit_code = proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                # Probe hung — almost certainly a torn index that's deadlocked
                # the chroma native code. Kill it and surface as a failure.
                proc.kill()
                try:
                    proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    pass
                duration_s = time.monotonic() - start
                logger.warning(
                    "AD-822: episodic health probe hung past %.1fs; killed",
                    timeout_s,
                )
                return EpisodicHealthResult(
                    ok=False,
                    error=f"probe timed out after {timeout_s:.1f}s",
                    duration_s=duration_s,
                )

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
        file_validation_failed = exit_code == 5
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
    finally:
        try:
            stderr_path.unlink(missing_ok=True)
        except OSError:
            pass
