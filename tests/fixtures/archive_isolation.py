"""BF-919 (#1632): no test opens the operator's Ship's Archive.

``ArchiveConfig.db_path`` defaults to ``""``, and ``resolve_archive_db_path`` turns that into a platform default
under the home directory (on Windows ``AppData\\Local\\ProbOS\\archive\\archive.db``). That is outside ``data_dir``,
so BF-883's data directory isolation never covered it, and every default-config boot in the suite opened and
migrated the operator's own archive.

``tests/conftest.py`` enters ``archive_isolation`` once per session in every xdist worker:

* the redirect: ``probos.config.resolve_archive_db_path`` answers an empty ``db_path`` with the current test's own
  path under the worker's archive root, and resolves a set ``db_path`` exactly as before. Every production caller
  imports the resolver inside the calling function, so replacing the module attribute is what they call;
* the refusal: ``ArchiveStore`` refuses, before it opens anything, a file that is the operator's own default or is
  not under the suite's temporary roots. A boot logs that error and continues without the archive, so each refusal
  is also recorded, and the test that caused it (or the session, for one outside any test) fails.

A caller that bound the resolver at import would bypass the redirect; the refusal still stops it. Neither reaches a
child process: the suites that start ``probos`` children give them their own home directory.
"""

from __future__ import annotations

import functools
import itertools
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import probos.config as probos_config
from probos.config import ArchiveConfig
from probos.knowledge.archive_store import ArchiveStore

ARCHIVE_FILE = "archive.db"
IN_MEMORY = ":memory:"


def comparable(path: str | os.PathLike[str]) -> Path:
    """One form for comparing paths: absolute, links resolved, the platform's case rule applied."""
    return Path(os.path.normcase(str(Path(path).resolve())))


def archive_root_for(tmp_path_factory: Any, worker_id: str) -> Path:
    """The worker's own archive root, beside its AD-682 data directory and never inside it."""
    return tmp_path_factory.mktemp(f"probos_archive_{worker_id}", numbered=False)


class ArchiveIsolation:
    """The redirect of the archive's default path and the refusal of any archive file outside the temporary roots."""

    def __init__(
        self, root: Path, allowed_roots: list[Path], original_resolver: Callable[[ArchiveConfig], Path],
    ) -> None:
        self.root = root
        self.original_resolver = original_resolver
        self.operator_default = comparable(original_resolver(ArchiveConfig()))
        self.allowed_roots = [comparable(allowed) for allowed in allowed_roots]
        self.session_path = root / "session" / ARCHIVE_FILE
        self.current = self.session_path
        self.refused: list[str] = []
        self._reported = 0
        self._numbers = itertools.count(1)

    def resolve(self, archive: ArchiveConfig) -> Path:
        """The redirect: a set ``db_path`` as before, an empty one the current test's own path."""
        if archive.db_path:
            return self.original_resolver(archive)
        return self.current

    def allowed(self, db_path: str) -> bool:
        """True for ``:memory:`` and for a file under a temporary root that is not the operator's default."""
        if db_path == IN_MEMORY:
            return True
        candidate = comparable(db_path)
        if candidate == self.operator_default:
            return False
        return any(candidate.is_relative_to(allowed) for allowed in self.allowed_roots)

    def next_test_path(self) -> Path:
        """A fresh path for the next test; nothing creates it unless that test opens the archive."""
        return self.root / f"t{next(self._numbers)}" / ARCHIVE_FILE

    def unreported(self) -> list[str]:
        """The refusals not reported yet; this call reports them."""
        new = self.refused[self._reported:]
        self._reported = len(self.refused)
        return new

    def refusing(self, original_init: Callable[..., None]) -> Callable[..., None]:
        """``ArchiveStore.__init__`` that refuses, and records, a file outside the temporary roots."""

        @functools.wraps(original_init)
        def _refusing_init(store: Any, db_path: str, *args: Any, **kwargs: Any) -> None:
            if not self.allowed(str(db_path)):
                self.refused.append(str(db_path))
                raise RuntimeError(
                    f"BF-919: a test opened a Ship's Archive outside the suite's temporary roots: {db_path}"
                )
            original_init(store, db_path, *args, **kwargs)

        return _refusing_init


@contextmanager
def archive_isolation(root: Path, allowed_roots: list[Path]) -> Iterator[ArchiveIsolation]:
    """Install the redirect and the refusal; restore both on exit."""
    original_resolver = probos_config.resolve_archive_db_path
    original_init = ArchiveStore.__init__
    isolation = ArchiveIsolation(root, allowed_roots, original_resolver)
    probos_config.resolve_archive_db_path = isolation.resolve
    ArchiveStore.__init__ = isolation.refusing(original_init)  # type: ignore[method-assign]
    try:
        yield isolation
    finally:
        ArchiveStore.__init__ = original_init  # type: ignore[method-assign]
        probos_config.resolve_archive_db_path = original_resolver
