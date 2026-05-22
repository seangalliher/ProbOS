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
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SKIP_ENV_VAR = "PROBOS_SKIP_EPISODIC_HEALTH_CHECK"


class EpisodicCorruptionDetected(RuntimeError):
    """The episodic store failed the boot-time health probe.

    Carries the probe stderr / exit code so the caller can shape an
    operator-readable error message pointing at AD-819 recovery.
    """

    def __init__(self, data_dir: Path, error: str, duration_s: float) -> None:
        self.data_dir = data_dir
        self.error = error
        self.duration_s = duration_s
        super().__init__(self._format_message())

    def _format_message(self) -> str:
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
        logger.warning(
            "AD-822: episodic health probe failed exit=%s reason=%s",
            exit_code, reason,
        )
        return EpisodicHealthResult(
            ok=False,
            error=reason,
            duration_s=duration_s,
        )
    finally:
        try:
            stderr_path.unlink(missing_ok=True)
        except OSError:
            pass
