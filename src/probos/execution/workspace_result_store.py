"""AD-1240: workspace tool-result publication, verified readback and reaping.

Layout (``<GEN>`` is the UTC hour of the injected clock, ``YYYYMMDDTHHZ``)::

    <root>/<owner-key>/.tool-results/<GEN>/<agent-digest>/<artifact-id>/
        payload.jsonl  outline.json  manifest.json

``.tool-results`` is a runtime-reserved directory whose contents may be removed
once their retention has expired. Every artifact is created exclusively and is
never rewritten; ``manifest.json`` is published by a hard link that cannot
replace an existing file, and its ``committed_at`` always falls inside its
generation's hour. The reaper removes only whole generations whose hour ended
at least one retention period ago, and it decides that from the name and the
clock alone, so ProbOS's own writers cannot race it.

ProbOS does not preserve what a process outside ProbOS writes or substitutes
inside the directory. While a generation is unexpired, a read refuses a payload, outline or manifest that differs from what the running ProbOS process committed in its digest, sizes, outline hash, `committed_at`, representation or owner digest (manifest keys it did not write are not compared); after a restart, a read can check only that the payload, outline and manifest agree with one another, so a consistent rewrite by a writer with ProbOS's own OS identity is not detected then, and no artifact is ever readable past the end of its generation's hour plus 24 hours, which is decided from the directory name alone. Once a generation has expired it is removed whole.
The reaper never follows a link.

Three classes share this module, each with one reason to change:
``WorkspaceResultStore`` (lifecycle, latch and the public protocol),
``ArtifactIO`` (the worker-thread disk protocol for one artifact) and
``GenerationReaper`` (the retention sweep).
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import logging
import math
import os
import re
import secrets
import stat
import sys
import time
from collections.abc import Callable, Iterable
from contextlib import ExitStack
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Literal, TypeVar

from probos.execution.workspace import WorkspaceManager
from probos.execution.workspace_results import (
    CANONICAL_MAX_BYTES,
    ENCODED_MAX_BYTES,
    GENERATION_NAME_RE,
    GENERATION_SECONDS,
    OUTLINE_MAX_BYTES,
    RESULT_DIRECTORY,
    RESULT_RETENTION_SECONDS,
    AgentWorkspace,
    CanonicalCapture,
    WorkspaceReapResult,
    WorkspaceResultError,
    WorkspaceResultRef,
    WorkspaceSlice,
    await_result_task,
    drained_result_io,
    generation_expiry,
    generation_name,
    generation_start,
    result_time,
)
from probos.security.file_access import (
    FileAccessDenied,
    PinnedDirectory,
    is_reparse_point,
    pin_directory,
    validate_read_location,
)

logger = logging.getLogger(__name__)

# One sweep touches at most this many entries; the rest wait for the next sweep.
SWEEP_ENTRY_CAP = 10_000
# Entries are removed down to this depth below <GEN>: <digest>/<artifact>/<file>.
REAP_MAX_DEPTH = 3

_RESULT_KIND = "probos.workspace-result"
_HEX_32 = re.compile(r"[0-9a-f]{32}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_MANIFEST_MAX_BYTES = 4096
# Windows: sharing violation, lock violation, access denied, directory not
# empty, delete pending. POSIX: names resolved at import (not every errno
# exists on every platform).
_TRANSIENT_WINERRORS = frozenset({32, 33, 5, 145, 303})
_SHARING_WINERRORS = frozenset({32, 33})
_DIRECTORY_NOT_EMPTY_WINERROR = 145
_POSIX_TRANSIENT_ERRNOS = frozenset(
    getattr(errno, name) for name in ("EBUSY", "EAGAIN", "ETXTBSY", "ENOTEMPTY")
    if hasattr(errno, name)
)
_T = TypeVar("_T")
_Identities = tuple[tuple[Path, tuple[int, int, int]], ...]


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retry for brief sharing violations; sleeps in a worker thread.

    ``attempts`` counts tries (so ``len(delays)`` sleeps at most), and
    ``sweep_sleep_budget`` caps the cumulative sleep of one sweep.
    """

    attempts: int = 4
    delays: tuple[float, ...] = (0.05, 0.2, 0.5)
    sweep_sleep_budget: float = 2.0

    def __post_init__(self) -> None:
        if (
            type(self.attempts) is not int or self.attempts < 1
            or type(self.delays) is not tuple or len(self.delays) < self.attempts - 1
            or any(type(delay) not in (int, float) or not math.isfinite(delay) or delay < 0 for delay in self.delays)
            or type(self.sweep_sleep_budget) not in (int, float)
            or not math.isfinite(self.sweep_sleep_budget) or self.sweep_sleep_budget < 0
        ):
            raise ValueError("invalid workspace result retry policy")


def classify_os_error(
    exc: BaseException, *, platform: str,
) -> Literal["gone", "transient", "integrity"]:
    """Sort a filesystem failure into the retention taxonomy.

    ``gone`` is only a verdict about the entry the failing call named: a
    missing directory in a pinned chain is an integrity failure, and the
    caller decides which one it is looking at. ``platform`` is explicit so
    both platforms' tables can be exercised anywhere.
    """
    if isinstance(exc, FileNotFoundError):
        return "gone"
    if _is_transient(exc, platform):
        return "transient"
    return "integrity"


def _is_transient(exc: BaseException, platform: str) -> bool:
    if not isinstance(exc, OSError):
        return False
    if platform == "win32":
        return isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in _TRANSIENT_WINERRORS
    return exc.errno in _POSIX_TRANSIENT_ERRNOS


def _transient(exc: BaseException) -> bool:
    return classify_os_error(exc, platform=sys.platform) == "transient"


def _sharing_violation(exc: BaseException) -> bool:
    return getattr(exc, "winerror", None) in _SHARING_WINERRORS


def _directory_not_empty(exc: OSError) -> bool:
    return exc.errno == errno.ENOTEMPTY or getattr(exc, "winerror", None) == _DIRECTORY_NOT_EMPTY_WINERROR


def _chain_intact(directory: PinnedDirectory) -> bool:
    try:
        directory.verify()
    except (OSError, FileAccessDenied):
        return False
    return True


class RetryRunner:
    """Run an operation under a ``RetryPolicy`` and an injected sleep.

    One instance spans one sweep or one store operation, so the sleep it has
    spent is that sweep's cumulative budget. It never sleeps past the budget:
    once the next delay would exceed it, the failure is raised instead.
    """

    def __init__(self, policy: RetryPolicy, sleep: Callable[[float], None]) -> None:
        self._policy = policy
        self._sleep = sleep
        self._slept = 0.0

    def run(self, operation: Callable[[], _T], retryable: Callable[[Exception], bool]) -> _T:
        attempt = 0
        while True:
            try:
                return operation()
            except Exception as exc:
                attempt += 1
                if attempt >= self._policy.attempts or not retryable(exc):
                    raise
                delay = self._policy.delays[attempt - 1]
                if self._slept + delay > self._policy.sweep_sleep_budget:
                    raise
                self._sleep(delay)
                self._slept += delay


class DirectoryIdentities:
    """Identities of directories this process pinned, compared on later pins.

    Entries under a generation are evicted when the reaper starts removing it,
    so the cache is bounded by the live generations (N5). Callers serialize
    access, so it needs no lock of its own.
    """

    def __init__(self) -> None:
        self._by_path: dict[Path, tuple[int, int, int]] = {}

    def expected(self) -> tuple[tuple[Path, tuple[int, int, int]], ...]:
        return tuple(self._by_path.items())

    def remember(self, identities: Iterable[tuple[Path, tuple[int, int, int]]]) -> None:
        self._by_path.update(identities)

    def knows(self, path: Path) -> bool:
        """True when this process has pinned ``path`` itself and still remembers its identity."""
        return path in self._by_path

    def evict_under(self, path: Path) -> int:
        stale = [known for known in self._by_path if known == path or known.is_relative_to(path)]
        for known in stale:
            del self._by_path[known]
        return len(stale)

    def known(self) -> frozenset[Path]:
        """Read-only diagnostic accessor: the paths currently remembered."""
        return frozenset(self._by_path)


@dataclass(frozen=True)
class _Committed:
    """What this process committed for one artifact; compared with the files on every read."""

    sha256: str
    committed_at: float
    source_chars: int
    utf8_bytes: int
    outline_sha256: str
    owner_digest: str
    representation: str

    @classmethod
    def of(cls, reference: WorkspaceResultRef, owner_digest: str) -> _Committed:
        return cls(
            reference.sha256, reference.committed_at, reference.source_chars, reference.utf8_bytes,
            hashlib.sha256(reference.outline.encode("ascii")).hexdigest(), owner_digest,
            reference.representation,
        )


def _bucket_of(payload_path: Path) -> tuple[Path, str]:
    """``(namespace, GEN)`` of ``<namespace>/<GEN>/<digest>/<artifact>/payload.jsonl``."""
    return payload_path.parents[3], payload_path.parents[2].name


class CommittedArtifacts:
    """What this process committed, one bucket per ``(namespace, GEN)`` (F2).

    A read compares the artifact files with this record, so while the process
    lives a rewrite of the payload, outline or manifest by a writer outside
    ProbOS is refused. A bucket is dropped only when its whole generation is
    removed: an earlier eviction would let a tampered ``committed_at`` extend
    readability again. It is process-local and never restored from disk, so
    after a restart a read can only check the files against one another.
    Callers serialize access, so it needs no lock of its own.
    """

    def __init__(self) -> None:
        self._buckets: dict[tuple[Path, str], dict[str, _Committed]] = {}

    def record(self, payload_path: Path, committed: _Committed) -> None:
        bucket = self._buckets.setdefault(_bucket_of(payload_path), {})
        bucket[os.path.normcase(str(payload_path))] = committed

    def get(self, payload_path: Path) -> _Committed | None:
        bucket = self._buckets.get(_bucket_of(payload_path), {})
        return bucket.get(os.path.normcase(str(payload_path)))

    def evict_generation(self, namespace: Path, generation: str) -> None:
        self._buckets.pop((namespace, generation), None)

    def __len__(self) -> int:
        return sum(len(bucket) for bucket in self._buckets.values())


@dataclass
class _SweepTally:
    deleted: int = 0
    skipped: int = 0
    failed: int = 0
    deferred: int = 0
    # Transient filesystem failures only. ``deferred`` also counts entries held
    # back by the sweep's entry cap, which must never escalate to a latch.
    transient: int = 0
    entries: int = 0

    def freeze(self) -> WorkspaceReapResult:
        return WorkspaceReapResult(self.deleted, self.skipped, self.failed, self.deferred)


class _RolledOver(Exception):
    """The commit-time clock left the generation an artifact was staged in."""

    def __init__(self, committed_at: float) -> None:
        super().__init__("generation rolled over")
        self.committed_at = committed_at


def _result_json(value: dict[str, object]) -> bytes:
    data = json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii")
    if len(data) > _MANIFEST_MAX_BYTES:
        raise WorkspaceResultError("manifest_limit")
    return data


def _encode_result(text: str) -> bytes:
    # A Unicode code point needs at most 12 ASCII bytes in JSON. 42 per
    # fragment leaves room for the quotes and LF under the 512-byte line cap.
    lines = [
        (json.dumps(text[index:index + 42], ensure_ascii=True) + "\n").encode("ascii")
        for index in range(0, len(text), 42)
    ]
    if not lines:
        lines = [b'""\n']
    if sum(map(len, lines)) > ENCODED_MAX_BYTES:
        raise WorkspaceResultError("encoded_limit")
    return b"".join(lines)


def _decode_result(data: bytes) -> str:
    if not data or len(data) > ENCODED_MAX_BYTES:
        raise WorkspaceResultError("payload_invalid")
    fragments: list[str] = []
    chars = 0
    for line in data.splitlines(keepends=True):
        if len(line) > 512 or not line.endswith(b"\n") or b"\r" in line:
            raise WorkspaceResultError("payload_invalid")
        try:
            value = json.loads(line.decode("ascii"))
        except (ValueError, UnicodeError) as exc:
            raise WorkspaceResultError("payload_invalid") from exc
        if type(value) is not str:
            raise WorkspaceResultError("payload_invalid")
        chars += len(value)
        if chars > CANONICAL_MAX_BYTES:
            raise WorkspaceResultError("payload_invalid")
        fragments.append(value)
    return "".join(fragments)


def _revalidated(payload: CanonicalCapture) -> CanonicalCapture:
    """A copy built through the constructor, so every admission check runs again."""
    return CanonicalCapture(
        payload.text, payload.representation, payload.source_chars,
        payload.utf8_bytes, payload.sha256, payload.outline,
    )


def _result_reference(path: Path, manifest: dict[str, object], outline: str) -> WorkspaceResultRef:
    artifact = path.parent
    digest = artifact.parent
    namespace = digest.parent.parent
    if (
        manifest.get("kind") != _RESULT_KIND or type(manifest.get("version")) is not int
        or manifest["version"] != 1 or manifest.get("artifact_id") != artifact.name
        or manifest.get("owner_digest") != digest.name
        or manifest.get("owner_key") != namespace.parent.name
        or _HEX_32.fullmatch(artifact.name) is None
        or _HEX_64.fullmatch(digest.name) is None
    ):
        raise WorkspaceResultError("manifest_invalid")
    committed_at = result_time(manifest.get("committed_at"))
    for key in ("source_chars", "utf8_bytes"):
        if type(manifest.get(key)) is not int or not 0 <= manifest[key] <= CANONICAL_MAX_BYTES:
            raise WorkspaceResultError("manifest_invalid")
    sha256 = manifest.get("sha256")
    representation = manifest.get("representation")
    if (
        type(sha256) is not str or _HEX_64.fullmatch(sha256) is None
        or representation not in ("text", "python-repr")
        or hashlib.sha256(outline.encode("ascii")).hexdigest() != manifest.get("outline_sha256")
    ):
        raise WorkspaceResultError("manifest_invalid")
    return WorkspaceResultRef(
        str(path), digest.name, artifact.name, sha256,
        manifest["source_chars"], manifest["utf8_bytes"], representation,
        committed_at, committed_at + RESULT_RETENTION_SECONDS, outline,
    )


def _rotated(names: Iterable[str], after: str | None) -> list[str]:
    """``names`` in name order, resuming after ``after`` and wrapping round to the names up to it.

    A sweep that reached its entry cap resumes after the owner or generation where
    its budget ran out, so entries that exhaust the budget in one place cannot keep
    the others from ever being reached. With no cursor this is plain name order.
    """
    ordered = sorted(names)
    if after is None:
        return ordered
    return [name for name in ordered if name > after] + [name for name in ordered if name <= after]


def _is_expired(name: str, now: float, tally: _SweepTally) -> bool:
    """True when ``name`` is a generation whose retention has expired at ``now``.

    A name this system does not produce, and a generation whose hour has not
    started, are counted ``skipped``; a generation still inside its retention is
    not counted. It reads nothing but the name and the clock.
    """
    if GENERATION_NAME_RE.fullmatch(name) is None:
        tally.skipped += 1
        return False
    try:
        begins = generation_start(name)
    except WorkspaceResultError:
        tally.skipped += 1  # not a name this system produces
        return False
    if begins > now:
        tally.skipped += 1  # a future name is not ours to age
        return False
    if now >= generation_expiry(name):
        return True
    return False


class GenerationReaper:
    """Remove whole generations once their retention has expired.

    ``sweep`` runs in a worker thread, one at a time (the store serializes
    it). It decides from a generation's name and the clock alone and never
    reads a manifest, so a writer that commits inside a generation cannot
    race it. Removal is a bounded bottom-up walk built only from
    ``pin_directory``, ``list_names``, ``remove_file`` and ``remove_directory``.
    A link, junction or special file is never followed, removed or counted as
    a failure; the generation that holds one is retained.

    Every root and owner-namespace pin and listing runs, together with its closing
    check, under the sweep's retry policy; the closing check of the pin that removal
    ran under is not retried. An operation that is still failing transiently is deferred, and
    a root or namespace deferred for one retention period within this process
    latches publication, so retention cannot stay off with only log lines to show
    for it.

    On POSIX, removal acts on directory objects that were verified to be inside the expired generation when they were opened, not on their current pathnames; a process outside ProbOS that moves such a directory elsewhere during removal can have entries removed from it at its new location, and the reaper's next check then treats the change as foreign (inside the generation) or as an integrity failure (above it).
    """

    def __init__(
        self, root: Path, *, sanitize: Callable[[str], str], identities: DirectoryIdentities,
        committed: CommittedArtifacts,
        sleep: Callable[[float], None] = time.sleep, retry: RetryPolicy = RetryPolicy(),
    ) -> None:
        self._root = root
        self._sanitize = sanitize
        self._identities = identities
        self._committed = committed
        self._sleep = sleep
        self._retry = retry
        # In-process only: when a root or owner namespace first deferred on a
        # transient failure; cleared by the next sweep that gets through it.
        self._held_since: dict[Path, float] = {}
        # In-process only: where a sweep that reached SWEEP_ENTRY_CAP stopped, per
        # directory (the root, or one owner namespace). The next sweep resumes after
        # that owner or generation and wraps round, so entries that exhaust the budget
        # in one place cannot keep the others from being reached.
        self._capped_at: dict[Path, str] = {}

    def sweep(self, now: float) -> WorkspaceReapResult:
        tally = _SweepTally()
        runner = RetryRunner(self._retry, self._sleep)
        try:
            self._reap_root(now, tally, runner)
        except OSError as exc:
            if not _transient(exc):
                raise
            # The root, or an ancestor probed on the way to it, kept failing with a
            # brief sharing violation. Nothing was found wrong with it: defer.
            self._hold(self._root, now, tally, exc, "workspace root")
        else:
            self._held_since.pop(self._root, None)
        return tally.freeze()

    def _pin(self, stack: ExitStack, path: Path, runner: RetryRunner) -> PinnedDirectory:
        """Pin ``path`` under the sweep's retry policy; the pin closes with ``stack``."""
        return runner.run(lambda: stack.enter_context(pin_directory(path, expected=self._identities.expected())), _transient)

    def _probe(self, path: Path) -> _Identities:
        """One attempt to pin ``path``: its chain identities, once the pin has also closed cleanly.

        The caller retries a failure at any step, the closing check included, whole,
        with a fresh pin each time.
        """
        with pin_directory(path, expected=self._identities.expected()) as directory:
            return directory.identities

    def _listed(self, path: Path) -> tuple[_Identities, tuple[str, ...]]:
        """One attempt to pin and list ``path``: chain identities and names, once the pin has closed cleanly."""
        with pin_directory(path, expected=self._identities.expected()) as directory:
            return directory.identities, directory.list_names()

    def _note_cap(self, directory: Path, name: str, before: int, tally: _SweepTally) -> None:
        """Record ``name`` as where ``directory``'s entry budget ran out, when it ran out inside ``name``."""
        if before < SWEEP_ENTRY_CAP <= tally.entries:
            self._capped_at[directory] = name

    def _reap_root(self, now: float, tally: _SweepTally, runner: RetryRunner) -> None:
        existing = self._root
        while True:
            try:
                self._identities.remember(runner.run(partial(self._probe, existing), _transient))
                break
            except FileNotFoundError as exc:
                if existing == self._root and self._identities.knows(self._root):
                    # This process pinned the root before, so its absence is a change
                    # to the anchor, not a root that was never created.
                    self._integrity_failure(exc, tally)
                    return
                parent = existing.parent
                if parent == existing:
                    # No ancestor can be pinned, not even the filesystem anchor.
                    raise WorkspaceResultError("workspace_reap_failed") from exc
                existing = parent
        if existing != self._root:
            # An absent root has nothing to reap; its existing ancestors are
            # validated and none is created.
            return
        identities, names = runner.run(partial(self._listed, self._root), _transient)
        self._identities.remember(identities)
        # No root pin is held while the owners are reaped: each namespace pin pins
        # and verifies the whole chain from the filesystem anchor again.
        for key in _rotated(names, self._capped_at.get(self._root)):
            if self._sanitize(key) == key:
                before = tally.entries
                self._reap_owner(key, now, tally, runner)
                self._note_cap(self._root, key, before, tally)
        if tally.entries < SWEEP_ENTRY_CAP:
            self._capped_at.pop(self._root, None)

    def _hold(
        self, path: Path, now: float, tally: _SweepTally, exc: BaseException, what: str,
    ) -> None:
        """Defer a root or namespace whose transient failure outlasted the retries.

        The first deferral stamps the path. Once the same path has been held for
        one retention period the deferral counts as a failure and latches
        publication (reversible, like the 2R rule for a held generation).
        """
        self._held_since.setdefault(path, now)
        if now - self._held_since[path] >= RESULT_RETENTION_SECONDS:
            tally.failed += 1
            logger.error(
                "Workspace result sweep could not verify the %s for one retention period "
                "because of a transient failure (%s); retention is unavailable and "
                "publications require a completed stop and a successful start",
                what, type(exc).__name__,
            )
            return
        tally.deferred += 1
        logger.warning(
            "Workspace result sweep could not verify the %s because of a transient failure "
            "(%s); expired results under it are not removed in this sweep, the next sweep "
            "retries, and a failure that lasts one retention period latches publication "
            "unavailable", what, type(exc).__name__,
        )

    def _reap_owner(self, key: str, now: float, tally: _SweepTally, runner: RetryRunner) -> None:
        namespace = self._root / key / RESULT_DIRECTORY
        try:
            self._reap_namespace(namespace, now, tally, runner)
        except (OSError, ValueError, FileAccessDenied) as exc:
            # The namespace chain itself failed; a missing entry here is a
            # changed chain, never "already gone".
            if classify_os_error(exc, platform=sys.platform) == "transient":
                self._hold(namespace, now, tally, exc, "owner namespace")
            else:
                tally.failed += 1
                logger.error(
                    "Workspace result sweep could not verify an owner namespace (%s); "
                    "retention is unavailable and publications require a completed "
                    "stop and a successful start", type(exc).__name__,
                )
        else:
            self._held_since.pop(namespace, None)

    def _reap_namespace(self, namespace: Path, now: float, tally: _SweepTally, runner: RetryRunner) -> None:
        try:
            identities, names = runner.run(partial(self._listed, namespace), _transient)
        except FileNotFoundError:
            if self._identities.knows(namespace):
                raise  # this process pinned it before: its absence is a changed chain
            return  # this owner has no result namespace
        self._identities.remember(identities)
        expired: list[str] = []
        for name in _rotated(names, self._capped_at.get(namespace)):
            if _is_expired(name, now, tally):
                expired.append(name)
        if expired:
            with ExitStack() as stack:
                owner = self._pin(stack, namespace, runner)
                for name in expired:
                    before = tally.entries
                    self._reap_expired(owner, namespace, name, now, tally, runner)
                    self._note_cap(namespace, name, before, tally)
        if tally.entries < SWEEP_ENTRY_CAP:
            self._capped_at.pop(namespace, None)

    def _reap_expired(
        self, owner: PinnedDirectory, namespace: Path, name: str, now: float,
        tally: _SweepTally, runner: RetryRunner,
    ) -> None:
        # Identities under an expiring generation guard nothing any more, and
        # would only stop substituted content from being removed with it.
        self._identities.evict_under(namespace / name)
        deferred_before = tally.deferred
        transient_before = tally.transient
        if self._reap_entry(owner, owner, name, 0, tally, runner):
            # The commitment record goes only with a generation removed whole (or
            # already gone): a deferred, capped or held generation keeps it, so a
            # rewrite of its files is still refused if the clock moves back.
            self._committed.evict_generation(namespace, name)
            tally.deleted += 1
            logger.info("Workspace result generation %s removed after its retention expired", name)
            return
        if tally.transient > transient_before:
            # Escalation (reversible): a generation still held one further
            # retention period after it expired counts as a failure and latches
            # publication. Only a transient filesystem failure escalates: entries
            # held back by the sweep's cap, and foreign (skipped) entries, never do.
            # Changing this to "warn only" means replacing the branch with a
            # logger.error. The residual: a lock held for more than a further 24 h
            # turns offload off until restart; with warn-only instead, such a lock
            # would grow disk use without bound.
            if now >= generation_expiry(name) + RESULT_RETENTION_SECONDS:
                tally.deferred = deferred_before
                tally.failed += 1
                logger.error(
                    "Workspace result generation %s is still held one retention period "
                    "after it expired; retention is unavailable and publications "
                    "require a completed stop and a successful start", name,
                )

    def _reap_entry(
        self, parent: PinnedDirectory, anchor: PinnedDirectory, name: str, depth: int,
        tally: _SweepTally, runner: RetryRunner,
    ) -> bool:
        """Remove one entry below ``parent``; True once it is gone.

        ``anchor`` is the owner's ``.tool-results`` pin, whose chain every
        failure is settled against.
        """
        if tally.entries >= SWEEP_ENTRY_CAP:
            tally.deferred += 1
            return False
        tally.entries += 1
        try:
            info = (parent.path / name).lstat()
            if is_reparse_point(info) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                tally.skipped += 1
                return False
            if stat.S_ISDIR(info.st_mode):
                return self._reap_directory(parent, anchor, name, depth, tally, runner)
            runner.run(lambda: parent.remove_file(name), _transient)
            return True
        except (OSError, ValueError, FileAccessDenied) as exc:
            return self._settle(anchor, exc, tally)

    def _reap_directory(
        self, parent: PinnedDirectory, anchor: PinnedDirectory, name: str, depth: int,
        tally: _SweepTally, runner: RetryRunner,
    ) -> bool:
        attempts = 0
        while True:
            attempts += 1
            with pin_directory(parent.path / name, expected=self._identities.expected()) as child:
                names = child.list_names()
                if depth >= REAP_MAX_DEPTH and names:
                    tally.skipped += len(names)  # below the depth bound: left in place
                    return False
                emptied = True
                for entry in sorted(names):
                    emptied = self._reap_entry(child, anchor, entry, depth + 1, tally, runner) and emptied
            if not emptied:
                return False
            try:
                runner.run(
                    lambda: parent.remove_directory(name),
                    lambda exc: _transient(exc) and not _directory_not_empty(exc),
                )
                return True
            except OSError as exc:
                # Not empty: something arrived after the listing. List again
                # and remove again, within the same attempt bound.
                if not _directory_not_empty(exc) or attempts >= self._retry.attempts:
                    raise

    def _settle(self, anchor: PinnedDirectory, exc: Exception, tally: _SweepTally) -> bool:
        """Account for a failure on one entry; True when the entry is already gone.

        Settled against the anchor, the chain from the workspace root to the
        owner's ``.tool-results`` directory, checked first whatever the failure's
        kind. An entry inside an expired generation whose identity changes while
        the reaper removes it is treated as content placed there by a process
        outside ProbOS when the pinned primitives report an identity change or a
        refused name and the chain from the workspace root to the owner's
        ``.tool-results`` directory still verifies: it is removed or left for the
        next sweep and never latches. With that chain intact, any other error from
        such an entry that is neither already-gone nor transient (for example
        ``ENOTDIR``, ``EACCES`` or ``EIO``) is an integrity failure and latches
        publication, and so is a change anywhere in that chain.
        """
        if not _chain_intact(anchor):
            return self._integrity_failure(exc, tally)
        kind = classify_os_error(exc, platform=sys.platform)
        if kind == "gone":
            return True  # the entry, or the subtree it heads, is already gone
        if kind == "transient":
            tally.deferred += 1
            tally.transient += 1
            return False
        if isinstance(exc, (FileAccessDenied, ValueError)):
            # The anchor is sound and only this entry is refused: a name or kind the
            # pinned primitives will not touch, or an identity change at or below the
            # generation. Foreign material, retained and never a failure.
            tally.skipped += 1
            return False
        return self._integrity_failure(exc, tally)

    def _integrity_failure(self, exc: Exception, tally: _SweepTally) -> bool:
        tally.failed += 1
        logger.error(
            "Workspace result sweep hit an integrity failure (%s); retention is "
            "unavailable and publications require a completed stop and a successful start",
            type(exc).__name__,
        )
        return False


class ArtifactIO:
    """Worker-thread disk protocol for one artifact: publish and read back.

    ``publish`` creates every file exclusively and commits ``manifest.json``
    by a no-replacement hard link. ``read`` verifies the manifest, the retention
    window and the payload digest before it returns any text. Both run under
    the store's serialization and re-check its admission gates before the
    point of commitment.
    """

    def __init__(
        self, root: Path, *, workspace: WorkspaceManager, clock: Callable[[], float],
        identities: DirectoryIdentities, committed: CommittedArtifacts,
        sleep: Callable[[float], None], retry: RetryPolicy,
        check_binding: Callable[[AgentWorkspace], None], check_writer: Callable[[], None],
    ) -> None:
        self._root = root
        self._workspace = workspace
        self._clock = clock
        self._identities = identities
        self._committed = committed
        self._sleep = sleep
        self._retry = retry
        self._check_binding = check_binding
        self._check_writer = check_writer
        # Process-local and never restored from disk: a backward clock must not
        # move a publication into an earlier generation or shorten retention.
        self._high_water = -math.inf

    def publish(self, binding: AgentWorkspace, payload: CanonicalCapture) -> WorkspaceResultRef:
        encoded = _encode_result(payload.text)
        generation = generation_name(max(result_time(self._clock()), self._high_water))
        for _ in range(2):  # one rollover retry; a second rollover is a write failure
            try:
                return self._publish_in(generation, binding, payload, encoded)
            except _RolledOver as rolled:
                logger.info(
                    "Workspace result commit crossed an hour boundary; the staged artifact "
                    "stays unadvertised and publication retries once in the next generation",
                )
                generation = generation_name(rolled.committed_at)
        raise WorkspaceResultError("workspace_write_failed")

    def _publish_in(
        self, generation: str, binding: AgentWorkspace, payload: CanonicalCapture, encoded: bytes,
    ) -> WorkspaceResultRef:
        parent = self._root / binding.owner_key / RESULT_DIRECTORY / generation / binding.owner_digest
        artifact_id = secrets.token_hex(16)
        path = parent / artifact_id / "payload.jsonl"
        self._check_binding(binding)
        if (
            validate_read_location(path) != path
            or parent != binding.root / binding.owner_key / RESULT_DIRECTORY / generation / binding.owner_digest
            or binding.owner_key != self._workspace.sanitize(binding.owner_key)
            or ".." in path.parts
        ):
            raise WorkspaceResultError("workspace_path_invalid")
        with pin_directory(parent, create=True, expected=self._identities.expected()) as directory:
            self._identities.remember(directory.identities)
            directory.make_directory(artifact_id)
            with pin_directory(parent / artifact_id) as artifact:
                artifact.write_new("payload.jsonl", encoded)
                artifact.write_new("outline.json", payload.outline.encode("ascii"))
                self._check_binding(binding)
                self._check_writer()
                clock_value = result_time(self._clock())
                committed_at = max(clock_value, generation_start(generation), self._high_water)
                if committed_at >= generation_start(generation) + GENERATION_SECONDS:
                    raise _RolledOver(committed_at)
                manifest = {
                    "kind": _RESULT_KIND, "version": 1, "owner_key": binding.owner_key,
                    "owner_digest": binding.owner_digest, "artifact_id": artifact_id,
                    "committed_at": committed_at,
                    "representation": payload.representation, "sha256": payload.sha256,
                    "source_chars": payload.source_chars, "utf8_bytes": payload.utf8_bytes,
                    "outline_sha256": hashlib.sha256(payload.outline.encode("ascii")).hexdigest(),
                }
                manifest_bytes = _result_json(manifest)
                artifact.write_new("manifest.staged", manifest_bytes)
                self._check_binding(binding)
                self._check_writer()
                try:
                    artifact.publish_file("manifest.staged", "manifest.json")
                except (OSError, FileAccessDenied):
                    if not self._manifest_committed(artifact, manifest_bytes):
                        raise
                    # The link committed the manifest; only dropping the staged
                    # name failed. The artifact is committed either way.
                    self._drop_staged(artifact)
                self._high_water = committed_at
                reference = _result_reference(path, manifest, payload.outline)
                self._committed.record(path, _Committed.of(reference, binding.owner_digest))
                artifact.verify()
        logger.debug(
            "Workspace result committed with bounded payload and manifest; verified "
            "readback is available until its commit-clock expiry",
        )
        return reference

    def _manifest_committed(self, artifact: PinnedDirectory, manifest_bytes: bytes) -> bool:
        """True only when ``manifest.json`` holds exactly the bytes just staged."""
        try:
            return artifact.read_bytes("manifest.json", max_bytes=_MANIFEST_MAX_BYTES).data == manifest_bytes
        except (OSError, FileAccessDenied):
            return False

    def _drop_staged(self, artifact: PinnedDirectory) -> None:
        """Remove ``manifest.staged`` under the retry policy, or leave it for the reaper."""
        runner = RetryRunner(self._retry, self._sleep)
        try:
            runner.run(lambda: artifact.remove_file("manifest.staged"), _transient)
        except FileNotFoundError:
            return
        except (OSError, FileAccessDenied):
            logger.debug(
                "Staged workspace manifest could not be removed after commit; it is left "
                "in place and goes with its generation",
            )

    def read(
        self, path: Path, generation: str, offset: int | None, limit: int | None,
    ) -> WorkspaceSlice:
        clock_value = result_time(self._clock())
        if clock_value >= generation_expiry(generation):
            raise WorkspaceResultError("result_expired")
        with pin_directory(path.parent, expected=self._identities.expected()) as artifact:
            manifest = json.loads(artifact.read_bytes("manifest.json", max_bytes=_MANIFEST_MAX_BYTES).data)
            if type(manifest) is not dict:
                raise WorkspaceResultError("manifest_invalid")
            outline = artifact.read_bytes("outline.json", max_bytes=OUTLINE_MAX_BYTES).data.decode("ascii")
            reference = _result_reference(path, manifest, outline)
            owner_digest = path.parents[1].name
            recorded = self._committed.get(path)
            if recorded is not None and recorded != _Committed.of(reference, owner_digest):
                raise WorkspaceResultError("payload_changed")
            begins = generation_start(generation)
            if not begins <= reference.committed_at < begins + GENERATION_SECONDS:
                raise WorkspaceResultError("manifest_invalid")
            if clock_value >= reference.expires_at:
                raise WorkspaceResultError("result_expired")
            payload = RetryRunner(self._retry, self._sleep).run(
                lambda: artifact.read_bytes("payload.jsonl", max_bytes=ENCODED_MAX_BYTES),
                _sharing_violation,
            )
            text = _decode_result(payload.data)
            encoded = text.encode("utf-8", errors="strict")
            if (
                len(encoded) != reference.utf8_bytes or len(text) != reference.source_chars
                or hashlib.sha256(encoded).hexdigest() != reference.sha256
            ):
                raise WorkspaceResultError("payload_changed")
            clock_value = result_time(self._clock())
            if clock_value >= reference.expires_at:
                raise WorkspaceResultError("result_expired")
            start = offset or 0
            end = start + limit if limit is not None else len(text)
            selected = text[start:end]
            actual_start, actual_end, _ = slice(start, end).indices(len(text))
            return WorkspaceSlice(selected, actual_start, max(actual_start, actual_end), reference)


async def _cancel_task(task: asyncio.Task[None]) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


class WorkspaceResultStore:
    """Lifecycle, latch and public protocol for workspace tool results.

    Publication, reads and sweeps are serialized by one lock, and every
    worker thread is drained before cancellation propagates. Any failed sweep
    latches publication unavailable until a completed ``stop`` and a
    successful ``start``; a clean public sweep never clears the latch.
    """

    def __init__(
        self, workspace: WorkspaceManager, *,
        clock: Callable[[], float] = time.time,
        background_register: Callable[[asyncio.Task[None]], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        retry: RetryPolicy = RetryPolicy(),
    ) -> None:
        self._workspace = workspace
        self._clock = clock
        self._background_register = background_register
        self._bindings: dict[str, tuple[object, AgentWorkspace]] = {}
        self._authority = object()
        self._lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._reaper_task: asyncio.Task[None] | None = None
        self._started = False
        self._stopped = True
        self._faulted = False
        self._fault_epoch = 0
        identities = DirectoryIdentities()
        committed = CommittedArtifacts()
        self._reaper = GenerationReaper(
            workspace.root, sanitize=workspace.sanitize, identities=identities,
            committed=committed, sleep=sleep, retry=retry,
        )
        self._artifacts = ArtifactIO(
            workspace.root, workspace=workspace, clock=clock, identities=identities,
            committed=committed, sleep=sleep, retry=retry,
            check_binding=self._check_binding, check_writer=self._check_writer,
        )

    @property
    def root(self) -> Path:
        return self._workspace.root

    @property
    def background_tasks(self) -> tuple[asyncio.Task[None], ...]:
        return (self._reaper_task,) if self._reaper_task is not None else ()

    def bind_agent(self, agent_id: str, registered_agent: object) -> AgentWorkspace:
        if (
            type(agent_id) is not str or not agent_id or len(agent_id) > 256
            or getattr(registered_agent, "id", None) != agent_id
            or type(getattr(registered_agent, "id", None)) is not str
        ):
            raise WorkspaceResultError("agent_identity_invalid")
        try:
            digest = hashlib.sha256(agent_id.encode("utf-8", errors="strict")).hexdigest()
            root = validate_read_location(self.root)
        except (ValueError, UnicodeError) as exc:
            raise WorkspaceResultError("workspace_path_invalid") from exc
        if root == Path(root.anchor) or ".." in self.root.parts:
            raise WorkspaceResultError("workspace_path_invalid")
        prior = self._bindings.get(agent_id)
        if prior is not None:
            if prior[0] is not registered_agent:
                raise WorkspaceResultError("agent_identity_changed")
            self._check_binding(prior[1])
            return prior[1]
        key = self._workspace.key_for_agent(registered_agent)
        if key == "shared":
            raise WorkspaceResultError("agent_identity_invalid")
        binding = AgentWorkspace(agent_id, key, digest, root, self._authority)
        self._bindings[agent_id] = (registered_agent, binding)
        return binding

    def _check_binding(self, binding: AgentWorkspace) -> None:
        if (
            type(binding) is not AgentWorkspace
            or binding.authority is not self._authority
            or self._bindings.get(binding.agent_id, (None, None))[1] is not binding
        ):
            raise WorkspaceResultError("workspace_owner_invalid")
        agent = self._bindings[binding.agent_id][0]
        if getattr(agent, "id", None) != binding.agent_id or self._workspace.key_for_agent(agent) != binding.owner_key:
            raise WorkspaceResultError("agent_identity_changed")

    def _check_writer(self) -> None:
        if (
            self._faulted or not self._started or self._reaper_task is None
            or self._reaper_task.done() or self._reaper_task.cancelling()
        ):
            raise WorkspaceResultError("workspace_unavailable")

    def _latch_failure(self) -> None:
        self._faulted = True
        self._started = False
        self._stopped = False
        self._fault_epoch += 1

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._started:
                self._check_writer()
                return
            if not self._stopped:
                raise WorkspaceResultError("workspace_unavailable")
            if self._background_register is None:
                raise WorkspaceResultError("reaper_unregistered")
            self._stopped = False
            epoch = self._fault_epoch
            task: asyncio.Task[None] | None = None
            try:
                root = validate_read_location(self.root)
                if root == Path(root.anchor) or ".." in self.root.parts:
                    raise WorkspaceResultError("workspace_path_invalid")
                # An absent root sweep validates existing ancestors but creates none.
                sweep = await self.reap_tool_results()
                if sweep.failed or self._fault_epoch != epoch:
                    raise WorkspaceResultError("workspace_reap_failed")
                task = asyncio.create_task(self._reap_loop(), name="workspace-result-reaper")
                self._reaper_task = task
                self._background_register(task)
                await asyncio.sleep(0)
                async with self._lock:
                    if task.done() or task.cancelling():
                        raise WorkspaceResultError("reaper_unavailable")
                    if self._fault_epoch != epoch:
                        raise WorkspaceResultError("workspace_reap_failed")
                    self._faulted = False
                    self._started = True
            except BaseException:
                self._latch_failure()
                if task is not None:
                    cleanup = asyncio.create_task(_cancel_task(task), name="workspace-result-start-drain")
                    await await_result_task(cleanup)
                raise
            logger.info(
                "Workspace result reaper registered; hourly-generation retention "
                "is active and admitted publications are enabled",
            )

    async def stop(self) -> None:
        task = asyncio.create_task(self._stop_service(), name="workspace-result-stop")
        await await_result_task(task)

    async def _stop_service(self) -> None:
        async with self._lifecycle_lock:
            self._started = False
            task = self._reaper_task
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            async with self._lock:
                self._stopped = True
            logger.info(
                "Workspace result service stopped after draining I/O; new publications "
                "are refused and committed files remain for compatible retention",
            )

    async def _reap_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(60)
                sweep = await self.reap_tool_results()
                if sweep.failed:
                    raise WorkspaceResultError("workspace_reap_failed")
        except asyncio.CancelledError:
            self._latch_failure()
            raise
        except Exception:
            self._latch_failure()
            logger.error(
                "Workspace result reaper failed; retention is unavailable and new "
                "publications require a completed stop followed by successful startup",
            )
            raise

    async def store_tool_result(
        self, binding: AgentWorkspace, payload: CanonicalCapture,
    ) -> WorkspaceResultRef:
        self._check_binding(binding)
        self._check_writer()
        if type(payload) is not CanonicalCapture:
            raise WorkspaceResultError("capture_invalid")
        checked = _revalidated(payload)
        async with self._lock:
            self._check_writer()
            try:
                return await drained_result_io(lambda: self._artifacts.publish(binding, checked))
            except WorkspaceResultError:
                raise
            except (OSError, ValueError, FileAccessDenied) as exc:
                logger.error(
                    "Workspace result publication failed; complete recovery was not "
                    "committed and delivery will stop without retrying the producer",
                )
                raise WorkspaceResultError("workspace_write_failed") from exc

    async def read_tool_result_slice(
        self, binding: AgentWorkspace, path: str, offset: int | None, limit: int | None,
    ) -> WorkspaceSlice:
        self._check_binding(binding)
        if any(value is not None and type(value) is not int for value in (offset, limit)):
            raise WorkspaceResultError("slice_invalid")
        try:
            candidate = validate_read_location(path)
            namespace = self.root / binding.owner_key / RESULT_DIRECTORY
            artifact = candidate.parent
            generation = artifact.parent.parent.name
            if (
                candidate.name != "payload.jsonl" or _HEX_32.fullmatch(artifact.name) is None
                or artifact.parent.name != binding.owner_digest
                or artifact.parent.parent.parent != namespace
                or GENERATION_NAME_RE.fullmatch(generation) is None
                or ".." in Path(path).parts
            ):
                raise WorkspaceResultError("workspace_owner_invalid")
        except (ValueError, TypeError) as exc:
            raise WorkspaceResultError("workspace_path_invalid") from exc
        async with self._lock:
            try:
                return await drained_result_io(
                    lambda: self._artifacts.read(candidate, generation, offset, limit),
                )
            except WorkspaceResultError:
                raise
            except (OSError, ValueError, FileAccessDenied) as exc:
                raise WorkspaceResultError("workspace_read_failed") from exc

    async def reap_tool_results(self) -> WorkspaceReapResult:
        async with self._lock:
            try:
                clock = result_time(self._clock())
                result = await drained_result_io(lambda: self._reaper.sweep(clock))
            except asyncio.CancelledError:
                self._latch_failure()
                logger.warning(
                    "Workspace result sweep cancelled after worker drainage; retention "
                    "is unavailable and publications require completed stop and successful start",
                )
                raise
            except Exception as exc:
                self._latch_failure()
                logger.error(
                    "Workspace result sweep failed; retention is unavailable and "
                    "publications require completed stop and successful start",
                )
                if isinstance(exc, WorkspaceResultError):
                    raise
                raise WorkspaceResultError("workspace_reap_failed") from exc
            if result.failed:
                self._latch_failure()
                logger.error(
                    "Workspace result sweep reported failures (count=%d, capped at 1000000); "
                    "retention is unavailable and publications require completed stop and successful start",
                    min(result.failed, 1_000_000),
                )
            if result.deferred:
                logger.info(
                    "Workspace result sweep deferred %d expired entries (count capped at "
                    "1000000); they are retried on the next sweep and %s",
                    min(result.deferred, 1_000_000),
                    "publication stays unavailable until a completed stop and a successful start"
                    if self._faulted else "publication stays enabled",
                )
            return result
